"""
Associate Hub Repository for Story 5.5

Provides aggregated data queries for Associate Operations Hub including
associate metrics, bookmaker balances, and filtering capabilities.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.core.database import get_db_connection
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

TWO_PLACES = Decimal("0.01")


def _to_decimal(value: Any) -> Optional[Decimal]:
    """Safely convert DB scalar to quantized Decimal."""
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        return None


def _to_decimal_raw(value: Any) -> Optional[Decimal]:
    """Convert DB scalar to Decimal without quantizing (useful for FX rates)."""
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _decimal_to_text(value: Any) -> Optional[str]:
    """Normalize numeric input to a DB-friendly text representation."""
    decimal_value = _to_decimal(value)
    return str(decimal_value) if decimal_value is not None else None


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
    internal_notes: Optional[str] = None
    max_surebet_stake_eur: Optional[Decimal] = None
    max_bookmaker_exposure_eur: Optional[Decimal] = None
    preferred_balance_chat_id: Optional[str] = None

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
    pending_balance_eur: Optional[Decimal] = None
    bookmaker_chat_id: Optional[str] = None
    coverage_chat_id: Optional[str] = None
    region: Optional[str] = None
    risk_level: Optional[str] = None
    internal_notes: Optional[str] = None
    associate_alias: Optional[str] = None
    active_balance_native: Optional[Decimal] = None
    pending_balance_native: Optional[Decimal] = None


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
        risk_filter: Optional[List[str]] = None,
        sort_by: str = "alias_asc",
        associate_ids: Optional[Sequence[int]] = None,
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
            a.internal_notes AS internal_notes,
            a.max_surebet_stake_eur AS max_surebet_stake_eur,
            a.max_bookmaker_exposure_eur AS max_bookmaker_exposure_eur,
            a.preferred_balance_chat_id AS preferred_balance_chat_id,
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
        delta_expr = (
            "(COALESCE(holdings.current_holding_eur, 0) - "
            "(COALESCE(deposits.net_deposits_eur, 0) + COALESCE(shares.fair_share_eur, 0)))"
        )
        nd_expr = "COALESCE(deposits.net_deposits_eur, 0)"
        balanced_threshold = float(self.BALANCED_THRESHOLD_EUR)
        status_case_expr = (
            "CASE "
            f"WHEN ABS({delta_expr}) <= {balanced_threshold} THEN 'balanced' "
            f"WHEN {delta_expr} > 0 THEN 'overholding' "
            "ELSE 'short' END"
        )
        normalized_risk_filter: List[str] = []
        if risk_filter:
            for value in risk_filter:
                slug = (value or "").strip().lower()
                if slug in {"balanced", "overholding", "short"} and slug not in normalized_risk_filter:
                    normalized_risk_filter.append(slug)
        
        # Add filters
        if search:
            normalized_search = f"%{search.lower()}%"
            query += (
                " AND (LOWER(a.display_alias) LIKE ? "
                "OR LOWER(COALESCE(a.multibook_chat_id, '')) LIKE ? "
                "OR EXISTS (SELECT 1 FROM bookmakers bsearch "
                "WHERE bsearch.associate_id = a.id AND ("
                "LOWER(COALESCE(bsearch.bookmaker_name, '')) LIKE ? "
                "OR LOWER(COALESCE(bsearch.bookmaker_chat_id, '')) LIKE ?"
                ")))"
            )
            params.extend(
                [
                    normalized_search,
                    normalized_search,
                    normalized_search,
                    normalized_search,
                ]
            )
            
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
            query += f" AND UPPER(a.home_currency) IN ({currency_placeholders})"
            params.extend(code.upper() for code in currency_filter)

        if associate_ids:
            placeholders = ",".join("?" * len(associate_ids))
            query += f" AND a.id IN ({placeholders})"
            params.extend(int(value) for value in associate_ids)
        
        query += (
            " GROUP BY a.id, a.display_alias, a.home_currency, a.is_admin, a.is_active, "
            "a.multibook_chat_id, a.internal_notes, a.max_surebet_stake_eur, "
            "a.max_bookmaker_exposure_eur, a.preferred_balance_chat_id, "
            "deposits.net_deposits_eur, holdings.current_holding_eur, "
            "pending.pending_balance_eur"
        )

        if normalized_risk_filter:
            placeholders = ",".join("?" * len(normalized_risk_filter))
            query += f" HAVING {status_case_expr} IN ({placeholders})"
            params.extend(normalized_risk_filter)
        
        # Add sorting
        sort_map = {
            "alias_asc": "a.display_alias ASC",
            "alias_desc": "a.display_alias DESC",
            "nd_desc": f"{nd_expr} DESC",
            "nd_asc": f"{nd_expr} ASC",
            "delta_desc": f"{delta_expr} DESC",
            "delta_asc": f"{delta_expr} ASC",
            "activity_desc": "MAX(COALESCE(bh.check_date_utc, le.created_at_utc)) DESC",
            "activity_asc": "MAX(COALESCE(bh.check_date_utc, le.created_at_utc)) ASC",
            "balance_desc": "COALESCE(holdings.current_holding_eur, 0) DESC",
            "balance_asc": "COALESCE(holdings.current_holding_eur, 0) ASC",
            "pending_desc": "COALESCE(pending.pending_balance_eur, 0) DESC",
            "pending_asc": "COALESCE(pending.pending_balance_eur, 0) ASC",
            "bookmaker_active_desc": "active_bookmaker_count DESC, a.display_alias ASC",
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
                status_color=status_color,
                internal_notes=row.get("internal_notes"),
                max_surebet_stake_eur=_to_decimal(row.get("max_surebet_stake_eur")),
                max_bookmaker_exposure_eur=_to_decimal(row.get("max_bookmaker_exposure_eur")),
                preferred_balance_chat_id=row.get("preferred_balance_chat_id"),
            )
            metrics.append(metric)

        return metrics

    def get_associate_metrics(self, associate_id: int) -> Optional[AssociateMetrics]:
        """
        Fetch the latest metrics for a single associate.
        """
        results = self.list_associates_with_metrics(
            associate_ids=[associate_id],
            limit=1,
        )
        return results[0] if results else None

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
            b.account_currency AS account_currency,
            b.bookmaker_chat_id AS bookmaker_chat_id,
            b.coverage_chat_id AS coverage_chat_id,
            b.region AS region,
            b.risk_level AS risk_level,
            b.internal_notes AS internal_notes,
            a.display_alias AS associate_alias,
            a.home_currency AS associate_home_currency,
            COALESCE(ledger.modeled_balance_eur, 0) AS modeled_balance_eur,
            checks.reported_balance_eur,
            checks.balance_native,
            checks.native_currency AS check_native_currency,
            checks.fx_rate_used,
            checks.last_balance_check_utc,
            COALESCE(pending.pending_balance_eur, 0) AS pending_balance_eur
        FROM bookmakers b
        JOIN associates a ON a.id = b.associate_id
        LEFT JOIN (
            SELECT 
                bookmaker_id,
                SUM(
                    CASE
                        WHEN amount_eur IS NULL THEN 0
                        WHEN type = 'DEPOSIT' THEN CAST(amount_eur AS REAL)
                        WHEN type = 'WITHDRAWAL' THEN -CAST(amount_eur AS REAL)
                        ELSE 0
                    END
                ) AS modeled_balance_eur
            FROM ledger_entries 
            WHERE associate_id = ?
              AND bookmaker_id IS NOT NULL
            GROUP BY bookmaker_id
        ) ledger ON ledger.bookmaker_id = b.id
        LEFT JOIN (
            SELECT 
                bookmaker_id,
                balance_eur AS reported_balance_eur,
                balance_native,
                native_currency,
                fx_rate_used,
                check_date_utc AS last_balance_check_utc,
                ROW_NUMBER() OVER (PARTITION BY bookmaker_id ORDER BY check_date_utc DESC) AS rn
            FROM bookmaker_balance_checks
            WHERE associate_id = ?
        ) checks ON checks.bookmaker_id = b.id AND checks.rn = 1
        LEFT JOIN (
            SELECT 
                bookmaker_id,
                SUM(
                    CASE
                        WHEN stake_eur IS NOT NULL AND stake_eur != ''
                        THEN CAST(stake_eur AS REAL)
                        ELSE 0
                    END
                ) AS pending_balance_eur
            FROM bets
            WHERE status IN ('verified', 'matched')
              AND bookmaker_id IS NOT NULL
            GROUP BY bookmaker_id
        ) pending ON pending.bookmaker_id = b.id
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
            
            pending_balance = _to_decimal(row.get("pending_balance_eur")) or Decimal("0.00")
            fx_rate = _to_decimal_raw(row.get("fx_rate_used"))
            balance_native = _to_decimal(row.get("balance_native"))
            native_currency = (
                (row.get("check_native_currency")
                 or row.get("account_currency")
                 or row.get("associate_home_currency")
                 or "EUR")
                .strip()
                .upper()
            )

            if balance_native is None and reported_balance is not None and fx_rate not in (None, Decimal("0")):
                balance_native = (reported_balance / fx_rate).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

            pending_native = None
            if pending_balance is not None and fx_rate not in (None, Decimal("0")):
                pending_native = (pending_balance / fx_rate).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

            summary = BookmakerSummary(
                associate_id=associate_id,
                bookmaker_id=row["bookmaker_id"],
                bookmaker_name=row["bookmaker_name"],
                is_active=bool(row["is_active"]),
                parsing_profile=row["parsing_profile"],
                native_currency=native_currency,
                modeled_balance_eur=modeled_balance,
                reported_balance_eur=reported_balance,
                delta_eur=delta_eur.quantize(TWO_PLACES, rounding=ROUND_HALF_UP) if delta_eur else None,
                last_balance_check_utc=row["last_balance_check_utc"],
                status=status,
                status_icon=status_icon,
                status_color=status_color,
                pending_balance_eur=pending_balance,
                bookmaker_chat_id=row.get("bookmaker_chat_id"),
                coverage_chat_id=row.get("coverage_chat_id"),
                region=row.get("region"),
                risk_level=row.get("risk_level"),
                internal_notes=row.get("internal_notes"),
                associate_alias=row.get("associate_alias"),
                active_balance_native=balance_native,
                pending_balance_native=pending_native,
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
                internal_notes,
                max_surebet_stake_eur,
                max_bookmaker_exposure_eur,
                preferred_balance_chat_id,
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
            "internal_notes": row.get("internal_notes"),
            "max_surebet_stake_eur": row.get("max_surebet_stake_eur"),
            "max_bookmaker_exposure_eur": row.get("max_bookmaker_exposure_eur"),
            "preferred_balance_chat_id": row.get("preferred_balance_chat_id"),
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
        telegram_chat_id: Optional[str] = None,
        *,
        internal_notes: Optional[str] = None,
        max_surebet_stake_eur: Optional[Any] = None,
        max_bookmaker_exposure_eur: Optional[Any] = None,
        preferred_balance_chat_id: Optional[str] = None,
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
            internal_notes: Free-form notes for operators
            max_surebet_stake_eur: Optional risk limit per surebet
            max_bookmaker_exposure_eur: Optional aggregate exposure cap
            preferred_balance_chat_id: Chat where balance reports go
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
                internal_notes = ?,
                max_surebet_stake_eur = ?,
                max_bookmaker_exposure_eur = ?,
                preferred_balance_chat_id = ?,
                updated_at_utc = ?
            WHERE id = ?
            """,
            (
                display_alias,
                home_currency.upper(),
                is_admin,
                is_active,
                telegram_chat_id,
                internal_notes,
                _decimal_to_text(max_surebet_stake_eur),
                _decimal_to_text(max_bookmaker_exposure_eur),
                preferred_balance_chat_id,
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

    def create_associate(
        self,
        display_alias: str,
        home_currency: str,
        is_admin: bool,
        is_active: bool,
        *,
        telegram_chat_id: Optional[str] = None,
        internal_notes: Optional[str] = None,
        max_surebet_stake_eur: Optional[Any] = None,
        max_bookmaker_exposure_eur: Optional[Any] = None,
        preferred_balance_chat_id: Optional[str] = None,
    ) -> int:
        """Insert a new associate row and return its ID."""
        from src.utils.datetime_helpers import utc_now_iso

        timestamp = utc_now_iso()
        cursor = self.db.execute(
            """
            INSERT INTO associates (
                display_alias,
                home_currency,
                is_admin,
                is_active,
                multibook_chat_id,
                internal_notes,
                max_surebet_stake_eur,
                max_bookmaker_exposure_eur,
                preferred_balance_chat_id,
                created_at_utc,
                updated_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                display_alias,
                home_currency.upper(),
                is_admin,
                is_active,
                telegram_chat_id,
                internal_notes,
                _decimal_to_text(max_surebet_stake_eur),
                _decimal_to_text(max_bookmaker_exposure_eur),
                preferred_balance_chat_id,
                timestamp,
                timestamp,
            ),
        )
        self.db.commit()
        new_id = int(cursor.lastrowid)
        logger.info(
            "associate_created",
            associate_id=new_id,
            display_alias=display_alias,
            home_currency=home_currency,
        )
        return new_id

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
                account_currency,
                bookmaker_chat_id,
                coverage_chat_id,
                region,
                risk_level,
                internal_notes,
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
            "account_currency": row.get("account_currency") or "EUR",
            "bookmaker_chat_id": row.get("bookmaker_chat_id"),
            "coverage_chat_id": row.get("coverage_chat_id"),
            "region": row.get("region"),
            "risk_level": row.get("risk_level"),
            "internal_notes": row.get("internal_notes"),
            "created_at_utc": row["created_at_utc"],
            "updated_at_utc": row["updated_at_utc"]
        }

    def update_bookmaker(
        self,
        bookmaker_id: int,
        bookmaker_name: str,
        is_active: bool,
        parsing_profile: Optional[str] = None,
        *,
        associate_id: Optional[int] = None,
        account_currency: Optional[str] = None,
        bookmaker_chat_id: Optional[str] = None,
        coverage_chat_id: Optional[str] = None,
        region: Optional[str] = None,
        risk_level: Optional[str] = None,
        internal_notes: Optional[str] = None,
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
        current = self.get_bookmaker_for_edit(bookmaker_id)
        if not current:
            raise ValueError(f"Bookmaker not found: {bookmaker_id}")

        target_associate = associate_id if associate_id is not None else current["associate_id"]
        currency_value = (account_currency or current.get("account_currency") or "EUR").strip().upper()
        chat_value = (bookmaker_chat_id if bookmaker_chat_id is not None else current.get("bookmaker_chat_id")) or None
        coverage_value = (coverage_chat_id if coverage_chat_id is not None else current.get("coverage_chat_id")) or None
        region_value = (region if region is not None else current.get("region")) or None
        risk_value = (risk_level if risk_level is not None else current.get("risk_level")) or None
        notes_value = (internal_notes if internal_notes is not None else current.get("internal_notes")) or None
        profile_value = parsing_profile if parsing_profile is not None else current.get("parsing_profile")
        chat_value = chat_value.strip() if isinstance(chat_value, str) and chat_value.strip() else None
        coverage_value = coverage_value.strip() if isinstance(coverage_value, str) and coverage_value.strip() else None
        region_value = region_value.strip() if isinstance(region_value, str) and region_value.strip() else None
        risk_value = risk_value.strip() if isinstance(risk_value, str) and risk_value.strip() else None
        notes_value = notes_value.strip() if isinstance(notes_value, str) and notes_value.strip() else None

        cursor = self.db.execute(
            """
            UPDATE bookmakers
            SET bookmaker_name = ?,
                associate_id = ?,
                account_currency = ?,
                is_active = ?,
                parsing_profile = ?,
                bookmaker_chat_id = ?,
                coverage_chat_id = ?,
                region = ?,
                risk_level = ?,
                internal_notes = ?,
                updated_at_utc = ?
            WHERE id = ?
            """,
            (
                bookmaker_name,
                target_associate,
                currency_value,
                is_active,
                profile_value,
                chat_value,
                coverage_value,
                region_value,
                risk_value,
                notes_value,
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
            parsing_profile=profile_value,
            associate_id=target_associate,
            account_currency=currency_value
        )

    def create_bookmaker(
        self,
        associate_id: int,
        bookmaker_name: str,
        is_active: bool,
        parsing_profile: Optional[str] = None,
        *,
        account_currency: str = "EUR",
        bookmaker_chat_id: Optional[str] = None,
        coverage_chat_id: Optional[str] = None,
        region: Optional[str] = None,
        risk_level: Optional[str] = None,
        internal_notes: Optional[str] = None,
    ) -> int:
        """Insert a new bookmaker for an associate and return its ID."""
        from src.utils.datetime_helpers import utc_now_iso

        timestamp = utc_now_iso()
        cursor = self.db.execute(
            """
            INSERT INTO bookmakers (
                associate_id,
                bookmaker_name,
                parsing_profile,
                is_active,
                account_currency,
                bookmaker_chat_id,
                coverage_chat_id,
                region,
                risk_level,
                internal_notes,
                created_at_utc,
                updated_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                associate_id,
                bookmaker_name,
                parsing_profile,
                is_active,
                (account_currency or "EUR").strip().upper(),
                (bookmaker_chat_id or "").strip() or None,
                (coverage_chat_id or "").strip() or None,
                (region or "").strip() or None,
                (risk_level or "").strip() or None,
                (internal_notes or "").strip() or None,
                timestamp,
                timestamp,
            ),
        )
        self.db.commit()
        new_id = int(cursor.lastrowid)
        logger.info(
            "bookmaker_created",
            bookmaker_id=new_id,
            associate_id=associate_id,
            bookmaker_name=bookmaker_name,
        )
        return new_id

    # Context manager convenience -------------------------------------------------

    def __enter__(self) -> "AssociateHubRepository":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
