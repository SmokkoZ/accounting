"""
Associate Hub Repository for Story 5.5

Provides aggregated data queries for Associate Operations Hub including
associate metrics, bookmaker balances, and filtering capabilities.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Tuple, Any

from src.core.database import get_db_connection
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

TWO_PLACES = Decimal("0.01")


@dataclass
class AssociateMetrics:
    """Aggregated metrics for an associate in operations hub."""
    associate_id: int
    associate_alias: str
    home_currency: str
    is_admin: bool
    is_active: bool
    telegram_chat_id: Optional[str]
    bookmaker_count: int
    active_bookmaker_count: int
    net_deposits_eur: Decimal
    should_hold_eur: Decimal
    fair_share_eur: Decimal
    current_holding_eur: Decimal
    balance_eur: Decimal
    pending_balance_eur: Decimal
    delta_eur: Decimal
    last_activity_utc: Optional[str]
    status: str  # 'balanced', 'overholding', 'short'
    status_color: str

    def delta_display(self) -> str:
        """Format delta for display with sign."""
        delta_str = f"€{abs(self.delta_eur):,.2f}"
        return f"+{delta_str}" if self.delta_eur >= 0 else f"-{delta_str}"
    
    def title(self) -> str:
        """Return status title with proper capitalization."""
        return self.status.capitalize()


@dataclass
class BookmakerSummary:
    """Bookmaker summary for associate operations hub."""
    associate_id: int
    bookmaker_id: int
    bookmaker_name: str
    is_active: bool
    parsing_profile: Optional[str]
    native_currency: str
    modeled_balance_eur: Decimal
    reported_balance_eur: Optional[Decimal]
    delta_eur: Optional[Decimal]
    last_balance_check_utc: Optional[str]
    status: str
    status_icon: str
    status_color: str


class AssociateHubRepository:
    """Repository for associate operations hub data aggregation."""

    BALANCED_THRESHOLD_EUR = Decimal("10")
    
    def __init__(self, db: Optional[sqlite3.Connection] = None) -> None:
        """Initialize repository with database connection."""
        self._owns_connection = db is None
        self.db = db or get_db_connection()

    def close(self) -> None:
        """Close managed database connection if owned by repository."""
        if not self._owns_connection:
            return
        try:
            self.db.close()
        except Exception:  # pragma: no cover - defensive close
            pass

    def list_associates_with_metrics(
        self,
        *,
        search: Optional[str] = None,
        admin_filter: Optional[List[bool]] = None,
        associate_status_filter: Optional[List[bool]] = None,
        bookmaker_status_filter: Optional[List[bool]] = None,
        currency_filter: Optional[List[str]] = None,
        sort_by: str = "alias_asc",
        limit: Optional[int] = None,
        offset: int = 0
    ) -> List[AssociateMetrics]:
        """
        Get associates with their aggregated metrics for the hub.
        
        Args:
            search: Search term for alias, bookmaker, or chat ID
            admin_filter: Filter by admin status [True, False]
            associate_status_filter: Filter by associate active status
            bookmaker_status_filter: Filter by bookmaker active status  
            currency_filter: Filter by home currency codes
            sort_by: Sort order for results
            limit: Maximum number of results
            offset: Number of results to skip
            
        Returns:
            List of associate metrics
        """
        # Build base query
        query = """
        SELECT 
            a.id AS associate_id,
            a.display_alias AS associate_alias,
            a.home_currency AS home_currency,
            a.is_admin AS is_admin,
            a.is_active AS is_active,
            a.multibook_chat_id AS telegram_chat_id,
            COUNT(DISTINCT b.id) AS bookmaker_count,
            COUNT(DISTINCT CASE WHEN b.is_active = 1 THEN b.id END) AS active_bookmaker_count,
            COALESCE(deposits.net_deposits_eur, 0) AS net_deposits_eur,
            COALESCE(holdings.current_holding_eur, 0) AS current_holding_eur,
            COALESCE(shares.fair_share_eur, 0) AS fair_share_eur,
            COALESCE(pending.pending_balance_eur, 0) AS pending_balance_eur,
            MAX(COALESCE(bh.check_date_utc, le.created_at_utc)) AS last_activity_utc
        FROM associates a
        LEFT JOIN bookmakers b ON b.associate_id = a.id
        LEFT JOIN (
            SELECT 
                associate_id,
                SUM(CAST(amount_eur AS REAL)) AS net_deposits_eur
            FROM ledger_entries 
            WHERE type IN ('DEPOSIT', 'WITHDRAWAL')
            GROUP BY associate_id
        ) deposits ON deposits.associate_id = a.id
        LEFT JOIN (
            SELECT 
                associate_id,
                SUM(CAST(amount_eur AS REAL)) AS current_holding_eur
            FROM ledger_entries
            GROUP BY associate_id
        ) holdings ON holdings.associate_id = a.id
        LEFT JOIN (
            SELECT
                associate_id,
                SUM(
                    CASE
                        WHEN per_surebet_share_eur IS NOT NULL AND per_surebet_share_eur != ''
                        THEN CAST(per_surebet_share_eur AS REAL)
                        ELSE 0
                    END
                ) AS fair_share_eur
            FROM ledger_entries
            WHERE type = 'BET_RESULT'
            GROUP BY associate_id
        ) shares ON shares.associate_id = a.id
        LEFT JOIN (
            SELECT
                associate_id,
                SUM(
                    CASE
                        WHEN stake_eur IS NOT NULL AND stake_eur != ''
                        THEN CAST(stake_eur AS REAL)
                        ELSE 0
                    END
                ) AS pending_balance_eur
            FROM bets
            WHERE status IN ('verified', 'matched')
            GROUP BY associate_id
        ) pending ON pending.associate_id = a.id
        LEFT JOIN bookmaker_balance_checks bh ON bh.associate_id = a.id
        LEFT JOIN ledger_entries le ON le.associate_id = a.id
        WHERE 1=1
        """
        
        params: List[Any] = []
        
        # Add filters
        if search:
            query += " AND (a.display_alias LIKE ? OR a.multibook_chat_id LIKE ?)"
            search_param = f"%{search}%"
            params.extend([search_param, search_param])
            
        if admin_filter:
            admin_placeholders = ",".join("?" * len(admin_filter))
            query += f" AND a.is_admin IN ({admin_placeholders})"
            params.extend(admin_filter)
            
        if associate_status_filter:
            status_placeholders = ",".join("?" * len(associate_status_filter))
            query += f" AND a.is_active IN ({status_placeholders})"
            params.extend(associate_status_filter)
            
        if bookmaker_status_filter:
            query += " AND EXISTS (SELECT 1 FROM bookmakers b2 WHERE b2.associate_id = a.id AND b2.is_active IN ("
            query += ",".join("?" * len(bookmaker_status_filter)) + "))"
            params.extend(bookmaker_status_filter)
            
        if currency_filter:
            currency_placeholders = ",".join("?" * len(currency_filter))
            query += f" AND a.home_currency IN ({currency_placeholders})"
            params.extend(currency_filter)
        
        query += (
            " GROUP BY a.id, a.display_alias, a.home_currency, a.is_admin, a.is_active, "
            "a.multibook_chat_id, deposits.net_deposits_eur, holdings.current_holding_eur, "
            "pending.pending_balance_eur"
        )
        
        # Add sorting
        sort_map = {
            "alias_asc": "a.display_alias ASC",
            "alias_desc": "a.display_alias DESC", 
            "delta_desc": "(COALESCE(holdings.current_holding_eur, 0) - COALESCE(deposits.net_deposits_eur, 0)) DESC",
            "delta_asc": "(COALESCE(holdings.current_holding_eur, 0) - COALESCE(deposits.net_deposits_eur, 0)) ASC",
            "activity_desc": "MAX(COALESCE(bh.check_date_utc, le.created_at_utc)) DESC",
            "activity_asc": "MAX(COALESCE(bh.check_date_utc, le.created_at_utc)) ASC",
            "balance_desc": "COALESCE(holdings.current_holding_eur, 0) DESC",
            "balance_asc": "COALESCE(holdings.current_holding_eur, 0) ASC",
            "pending_desc": "COALESCE(pending.pending_balance_eur, 0) DESC",
            "pending_asc": "COALESCE(pending.pending_balance_eur, 0) ASC",
        }
        
        query += f" ORDER BY {sort_map.get(sort_by, sort_map['alias_asc'])}"
        
        # Add pagination
        if limit:
            query += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
        
        logger.debug("associates_with_metrics_query", query=query, params=params)
        
        cursor = self.db.execute(query, params)
        rows = cursor.fetchall()
        
        metrics: List[AssociateMetrics] = []
        for row in rows:
            # Calculate should_hold and delta
            net_deposits = Decimal(str(row["net_deposits_eur"])).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
            current_holding = Decimal(str(row["current_holding_eur"])).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
            fair_share_raw = row["fair_share_eur"] if row["fair_share_eur"] is not None else 0
            fair_share = Decimal(str(fair_share_raw)).quantize(
                TWO_PLACES, rounding=ROUND_HALF_UP
            )
            pending_raw = row["pending_balance_eur"]
            pending_balance = Decimal(str(pending_raw if pending_raw is not None else 0)).quantize(
                TWO_PLACES, rounding=ROUND_HALF_UP
            )
            should_hold_eur = (net_deposits + fair_share).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
            delta_eur = (current_holding - should_hold_eur).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
            
            # Determine status
            abs_delta = abs(delta_eur)
            if abs_delta <= self.BALANCED_THRESHOLD_EUR:
                status = "balanced"
                status_color = "#e8f5e9"  # Green
            elif delta_eur > 0:
                status = "overholding"
                status_color = "#fff3e0"  # Orange
            else:
                status = "short"
                status_color = "#ffebee"  # Red
            
            metric = AssociateMetrics(
                associate_id=row["associate_id"],
                associate_alias=row["associate_alias"],
                home_currency=row["home_currency"] or "EUR",
                is_admin=bool(row["is_admin"]),
                is_active=bool(row["is_active"]),
                telegram_chat_id=row["telegram_chat_id"],
                bookmaker_count=row["bookmaker_count"],
                active_bookmaker_count=row["active_bookmaker_count"],
                net_deposits_eur=net_deposits,
                should_hold_eur=should_hold_eur,
                fair_share_eur=fair_share,
                current_holding_eur=current_holding,
                balance_eur=current_holding,
                pending_balance_eur=pending_balance,
                delta_eur=delta_eur,
                last_activity_utc=row["last_activity_utc"],
                status=status,
                status_color=status_color
            )
            metrics.append(metric)
        
        return metrics

    def list_bookmakers_for_associate(self, associate_id: int) -> List[BookmakerSummary]:
        """
        Get bookmaker summaries for a specific associate.
        
        Args:
            associate_id: ID of associate
            
        Returns:
            List of bookmaker summaries
        """
        query = """
        SELECT 
            b.id AS bookmaker_id,
            b.bookmaker_name,
            b.is_active AS is_active,
            b.parsing_profile AS parsing_profile,
            a.home_currency AS native_currency,
            COALESCE(ledger.modeled_balance_eur, 0) AS modeled_balance_eur,
            checks.reported_balance_eur,
            checks.last_balance_check_utc
        FROM bookmakers b
        JOIN associates a ON a.id = b.associate_id
        LEFT JOIN (
            SELECT 
                bookmaker_id,
                SUM(CASE WHEN amount_eur > 0 THEN amount_eur ELSE 0 END) - 
                SUM(CASE WHEN amount_eur < 0 THEN ABS(amount_eur) ELSE 0 END) AS modeled_balance_eur
            FROM ledger_entries 
            WHERE associate_id = ?
            AND bookmaker_id IS NOT NULL
            GROUP BY bookmaker_id
        ) ledger ON ledger.bookmaker_id = b.id
        LEFT JOIN (
            SELECT 
                bookmaker_id,
                balance_eur AS reported_balance_eur,
                check_date_utc AS last_balance_check_utc,
                ROW_NUMBER() OVER (PARTITION BY bookmaker_id ORDER BY check_date_utc DESC) as rn
            FROM bookmaker_balance_checks
            WHERE associate_id = ?
        ) checks ON checks.bookmaker_id = b.id AND checks.rn = 1
        WHERE b.associate_id = ?
        ORDER BY b.bookmaker_name
        """
        
        cursor = self.db.execute(query, (associate_id, associate_id, associate_id))
        rows = cursor.fetchall()
        
        summaries: List[BookmakerSummary] = []
        for row in rows:
            modeled_balance = Decimal(str(row["modeled_balance_eur"])).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
            reported_balance = None
            if row["reported_balance_eur"]:
                reported_balance = Decimal(str(row["reported_balance_eur"])).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
            
            delta_eur = None
            status = "unverified"
            status_icon = "⚪"
            status_color = "#eceff1"
            
            if reported_balance is not None:
                delta_eur = reported_balance - modeled_balance
                abs_delta = abs(delta_eur)
                
                if abs_delta <= self.BALANCED_THRESHOLD_EUR:
                    status = "balanced"
                    status_icon = "🟢"
                    status_color = "#e8f5e9"
                elif delta_eur > 0:
                    status = "overholding"
                    status_icon = "🔺"
                    status_color = "#fff3e0"
                else:
                    status = "short"
                    status_icon = "🔻"
                    status_color = "#ffebee"
            
            summary = BookmakerSummary(
                associate_id=associate_id,
                bookmaker_id=row["bookmaker_id"],
                bookmaker_name=row["bookmaker_name"],
                is_active=bool(row["is_active"]),
                parsing_profile=row["parsing_profile"],
                native_currency=row["native_currency"] or "EUR",
                modeled_balance_eur=modeled_balance,
                reported_balance_eur=reported_balance,
                delta_eur=delta_eur.quantize(TWO_PLACES, rounding=ROUND_HALF_UP) if delta_eur else None,
                last_balance_check_utc=row["last_balance_check_utc"],
                status=status,
                status_icon=status_icon,
                status_color=status_color
            )
            summaries.append(summary)
        
        return summaries

    def get_associate_for_edit(self, associate_id: int) -> Optional[Dict[str, Any]]:
        """
        Get associate details for editing in the hub.
        
        Args:
            associate_id: ID of associate
            
        Returns:
            Associate details dict or None if not found
        """
        cursor = self.db.execute(
            """
            SELECT 
                id,
                display_alias,
                home_currency,
                is_admin,
                is_active,
                multibook_chat_id,
                created_at_utc,
                updated_at_utc
            FROM associates
            WHERE id = ?
            """,
            (associate_id,)
        )
        row = cursor.fetchone()
        
        if not row:
            return None
            
        return {
            "id": row["id"],
            "display_alias": row["display_alias"],
            "home_currency": row["home_currency"] or "EUR",
            "is_admin": bool(row["is_admin"]),
            "is_active": bool(row["is_active"]),
            "telegram_chat_id": row["multibook_chat_id"],
            "created_at_utc": row["created_at_utc"],
            "updated_at_utc": row["updated_at_utc"]
        }

    def update_associate(
        self,
        associate_id: int,
        display_alias: str,
        home_currency: str,
        is_admin: bool,
        is_active: bool,
        telegram_chat_id: Optional[str] = None
    ) -> None:
        """
        Update associate details.
        
        Args:
            associate_id: ID of associate to update
            display_alias: New display alias
            home_currency: New home currency
            is_admin: New admin status
            is_active: New active status
            telegram_chat_id: New Telegram chat ID
        """
        from src.utils.datetime_helpers import utc_now_iso
        
        cursor = self.db.execute(
            """
            UPDATE associates
            SET display_alias = ?,
                home_currency = ?,
                is_admin = ?,
                is_active = ?,
                multibook_chat_id = ?,
                updated_at_utc = ?
            WHERE id = ?
            """,
            (
                display_alias,
                home_currency.upper(),
                is_admin,
                is_active,
                telegram_chat_id,
                utc_now_iso(),
                associate_id
            )
        )
        
        if cursor.rowcount == 0:
            raise ValueError(f"Associate not found: {associate_id}")
        
        logger.info(
            "associate_updated",
            associate_id=associate_id,
            display_alias=display_alias,
            home_currency=home_currency,
            is_admin=is_admin,
            is_active=is_active,
            telegram_chat_id=telegram_chat_id
        )

    def get_bookmaker_for_edit(self, bookmaker_id: int) -> Optional[Dict[str, Any]]:
        """
        Get bookmaker details for editing in the hub.
        
        Args:
            bookmaker_id: ID of bookmaker
            
        Returns:
            Bookmaker details dict or None if not found
        """
        cursor = self.db.execute(
            """
            SELECT 
                id,
                associate_id,
                bookmaker_name,
                is_active,
                parsing_profile,
                created_at_utc,
                updated_at_utc
            FROM bookmakers
            WHERE id = ?
            """,
            (bookmaker_id,)
        )
        row = cursor.fetchone()
        
        if not row:
            return None
            
        return {
            "id": row["id"],
            "associate_id": row["associate_id"],
            "bookmaker_name": row["bookmaker_name"],
            "is_active": bool(row["is_active"]),
            "parsing_profile": row["parsing_profile"],
            "created_at_utc": row["created_at_utc"],
            "updated_at_utc": row["updated_at_utc"]
        }

    def update_bookmaker(
        self,
        bookmaker_id: int,
        bookmaker_name: str,
        is_active: bool,
        parsing_profile: Optional[str] = None
    ) -> None:
        """
        Update bookmaker details.
        
        Args:
            bookmaker_id: ID of bookmaker to update
            bookmaker_name: New bookmaker name
            is_active: New active status
            parsing_profile: New parsing profile
        """
        from src.utils.datetime_helpers import utc_now_iso
        
        cursor = self.db.execute(
            """
            UPDATE bookmakers
            SET bookmaker_name = ?,
                is_active = ?,
                parsing_profile = ?,
                updated_at_utc = ?
            WHERE id = ?
            """,
            (
                bookmaker_name,
                is_active,
                parsing_profile,
                utc_now_iso(),
                bookmaker_id
            )
        )
        
        if cursor.rowcount == 0:
            raise ValueError(f"Bookmaker not found: {bookmaker_id}")
        
        logger.info(
            "bookmaker_updated",
            bookmaker_id=bookmaker_id,
            bookmaker_name=bookmaker_name,
            is_active=is_active,
            parsing_profile=parsing_profile
        )

    # Context manager convenience -------------------------------------------------

    def __enter__(self) -> "AssociateHubRepository":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
