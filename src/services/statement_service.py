"""
Monthly Statement Service

Calculates associate statements including funding, entitlement, and reconciliation.
All calculations are read-only and use cutoff date filtering.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

import structlog
from datetime import datetime

from src.core.database import get_db_connection
from src.utils.datetime_helpers import utc_now_iso

logger = structlog.get_logger()


@dataclass
class BookmakerStatementRow:
    """Per-bookmaker summary for statement output."""

    bookmaker_name: str
    balance_eur: Decimal
    deposits_eur: Decimal
    withdrawals_eur: Decimal
    balance_native: Decimal
    native_currency: str


@dataclass
class StatementCalculations:
    """Container for all statement calculation results."""

    associate_id: int
    net_deposits_eur: Decimal
    should_hold_eur: Decimal
    current_holding_eur: Decimal
    raw_profit_eur: Decimal
    delta_eur: Decimal
    total_deposits_eur: Decimal
    total_withdrawals_eur: Decimal
    bookmakers: List[BookmakerStatementRow]
    associate_name: str
    home_currency: str
    cutoff_date: str
    generated_at: str


@dataclass
class PartnerFacingSection:
    """Data for partner-facing statement section."""
    total_deposits_eur: Decimal
    total_withdrawals_eur: Decimal
    holdings_eur: Decimal
    delta_eur: Decimal
    bookmakers: List[BookmakerStatementRow]


@dataclass
class InternalSection:
    """Data for internal-only statement section."""
    current_holdings: str
    reconciliation_delta: str
    delta_status: str
    delta_indicator: str


class StatementService:
    """Service for generating monthly associate statements."""
    
    def __init__(self):
        self.logger = logger.bind(service="statement_service")
    
    def generate_statement(self, associate_id: int, cutoff_date: str) -> StatementCalculations:
        """
        Generate complete statement calculations for an associate.
        
        Args:
            associate_id: ID of the associate
            cutoff_date: ISO datetime string for cutoff (inclusive)
            
        Returns:
            StatementCalculations with all computed values
            
        Raises:
            ValueError: If associate_id not found or cutoff_date invalid
        """
        self.logger.info("generating_statement", associate_id=associate_id, cutoff_date=cutoff_date)
        
        conn = get_db_connection()
        try:
            # Validate associate exists and get name
            associate_name, home_currency = self._get_associate_details(conn, associate_id)
            if not associate_name:
                raise ValueError(f"Associate ID {associate_id} not found")
            
            # Perform all calculations
            total_deposits, total_withdrawals = self._calculate_funding_totals(
                conn, associate_id, cutoff_date
            )
            net_deposits = total_deposits - total_withdrawals
            should_hold = self._calculate_should_hold(conn, associate_id, cutoff_date)
            current_holding = self._calculate_current_holding(conn, associate_id, cutoff_date)
            bookmakers = self._calculate_bookmaker_breakdown(
                conn, associate_id, cutoff_date
            )
            
            # Calculate derived values
            raw_profit = should_hold - net_deposits
            delta = current_holding - should_hold
            
            calculations = StatementCalculations(
                associate_id=associate_id,
                net_deposits_eur=net_deposits,
                should_hold_eur=should_hold,
                current_holding_eur=current_holding,
                raw_profit_eur=raw_profit,
                delta_eur=delta,
                total_deposits_eur=total_deposits,
                total_withdrawals_eur=total_withdrawals,
                bookmakers=bookmakers,
                associate_name=associate_name,
                home_currency=home_currency or "",
                cutoff_date=cutoff_date,
                generated_at=utc_now_iso()
            )
            
            self.logger.info(
                "statement_calculated",
                associate_id=associate_id,
                net_deposits=float(net_deposits),
                should_hold=float(should_hold),
                current_holding=float(current_holding),
                raw_profit=float(raw_profit),
                delta=float(delta)
            )
            
            return calculations
            
        finally:
            conn.close()
    
    def _get_associate_details(self, conn, associate_id: int) -> Tuple[Optional[str], Optional[str]]:
        """Get associate display name and currency by ID."""
        cursor = conn.cursor()
        cursor.execute(
            "SELECT display_alias, home_currency FROM associates WHERE id = ?",
            (associate_id,)
        )
        row = cursor.fetchone()
        if not row:
            return None, None
        return row["display_alias"], row["home_currency"]
    
    def _calculate_funding_totals(
        self, conn, associate_id: int, cutoff_date: str
    ) -> Tuple[Decimal, Decimal]:
        """
        Calculate total deposits and withdrawals up to the cutoff date.
        """
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                SUM(CASE WHEN type = 'DEPOSIT' THEN CAST(amount_eur AS REAL) ELSE 0 END) AS total_deposits,
                SUM(CASE WHEN type = 'WITHDRAWAL' THEN ABS(CAST(amount_eur AS REAL)) ELSE 0 END) AS total_withdrawals
            FROM ledger_entries
            WHERE associate_id = ?
              AND type IN ('DEPOSIT', 'WITHDRAWAL')
              AND created_at_utc <= ?
            """,
            (associate_id, cutoff_date),
        )
        row = cursor.fetchone()
        if not row:
            return Decimal("0.00"), Decimal("0.00")

        def _extract(value: object) -> Decimal:
            return Decimal(str(value or 0.0))

        try:
            deposits_value = row["total_deposits"]  # type: ignore[index]
            withdrawals_value = row["total_withdrawals"]  # type: ignore[index]
        except (TypeError, KeyError, IndexError):
            deposits_value = row[0] if isinstance(row, (list, tuple)) else 0.0  # type: ignore[index]
            withdrawals_value = (
                row[1] if isinstance(row, (list, tuple)) and len(row) > 1 else 0.0  # type: ignore[index]
            )

        total_deposits = _extract(deposits_value)
        total_withdrawals = _extract(withdrawals_value)
        return total_deposits, total_withdrawals
    
    def _calculate_should_hold(self, conn, associate_id: int, cutoff_date: str) -> Decimal:
        """
        Calculate SHOULD_HOLD_EUR = SUM(principal_returned_eur + per_surebet_share_eur)
        
        Args:
            conn: Database connection
            associate_id: Associate ID
            cutoff_date: Cutoff date (inclusive)
            
        Returns:
            Should hold amount as Decimal
        """
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                SUM(
                    CAST(principal_returned_eur AS REAL) +
                    CAST(per_surebet_share_eur AS REAL)
                ) AS should_hold_eur
            FROM ledger_entries
            WHERE associate_id = ?
            AND type = 'BET_RESULT'
            AND created_at_utc <= ?
            AND principal_returned_eur IS NOT NULL
            AND per_surebet_share_eur IS NOT NULL
        """, (associate_id, cutoff_date))
        
        row = cursor.fetchone()
        result = row["should_hold_eur"] or 0.0
        return Decimal(str(result))
    
    def _calculate_current_holding(self, conn, associate_id: int, cutoff_date: str) -> Decimal:
        """
        Calculate CURRENT_HOLDING_EUR = SUM(all ledger entries)
        
        Args:
            conn: Database connection
            associate_id: Associate ID
            cutoff_date: Cutoff date (inclusive)
            
        Returns:
            Current holding as Decimal
        """
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                SUM(CAST(amount_eur AS REAL)) AS current_holding_eur
            FROM ledger_entries
            WHERE associate_id = ?
            AND created_at_utc <= ?
        """, (associate_id, cutoff_date))
        
        row = cursor.fetchone()
        result = row["current_holding_eur"] or 0.0
        return Decimal(str(result))

    def _calculate_bookmaker_breakdown(
        self, conn, associate_id: int, cutoff_date: str
    ) -> List[BookmakerStatementRow]:
        """
        Build per-bookmaker balance/deposit/withdrawal summaries.
        """
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                b.id,
                b.bookmaker_name,
                SUM(CASE WHEN le.id IS NULL THEN 0 ELSE CAST(le.amount_eur AS REAL) END) AS balance_eur,
                SUM(CASE WHEN le.type = 'DEPOSIT' THEN CAST(le.amount_eur AS REAL) ELSE 0 END) AS deposits_eur,
                SUM(CASE WHEN le.type = 'WITHDRAWAL' THEN ABS(CAST(le.amount_eur AS REAL)) ELSE 0 END) AS withdrawals_eur,
                SUM(CASE WHEN le.id IS NULL THEN 0 ELSE CAST(le.amount_native AS REAL) END) AS balance_native,
                a.home_currency AS native_currency
            FROM bookmakers b
            JOIN associates a ON a.id = b.associate_id
            LEFT JOIN ledger_entries le
                ON le.bookmaker_id = b.id
               AND le.associate_id = ?
               AND le.created_at_utc <= ?
            WHERE b.associate_id = ?
            GROUP BY b.id, b.bookmaker_name, a.home_currency
            ORDER BY b.bookmaker_name
            """,
            (associate_id, cutoff_date, associate_id),
        )

        rows = cursor.fetchall() or []
        breakdown: List[BookmakerStatementRow] = []
        for row in rows:
            balance = Decimal(str(row["balance_eur"] or 0.0))
            deposits = Decimal(str(row["deposits_eur"] or 0.0))
            withdrawals = Decimal(str(row["withdrawals_eur"] or 0.0))
            balance_native = Decimal(str(row["balance_native"] or 0.0))
            native_currency = row["native_currency"] or ""
            breakdown.append(
                BookmakerStatementRow(
                    bookmaker_name=row["bookmaker_name"],
                    balance_eur=balance.quantize(Decimal("0.01")),
                    deposits_eur=deposits.quantize(Decimal("0.01")),
                    withdrawals_eur=withdrawals.quantize(Decimal("0.01")),
                    balance_native=balance_native.quantize(Decimal("0.01")),
                    native_currency=native_currency,
                )
            )
        return breakdown
    
    def format_partner_facing_section(self, calc: StatementCalculations) -> PartnerFacingSection:
        """
        Format partner-facing statement section.
        
        Args:
            calc: Statement calculations
            
        Returns:
            Formatted partner-facing section
        """
        return PartnerFacingSection(
            total_deposits_eur=calc.total_deposits_eur,
            total_withdrawals_eur=calc.total_withdrawals_eur,
            holdings_eur=calc.current_holding_eur,
            delta_eur=calc.delta_eur,
            bookmakers=calc.bookmakers,
        )
    
    def format_internal_section(self, calc: StatementCalculations) -> InternalSection:
        """
        Format internal-only statement section.
        
        Args:
            calc: Statement calculations
            
        Returns:
            Formatted internal section
        """
        current_holdings = self._format_currency(calc.current_holding_eur)
        delta_amount = self._format_currency(abs(calc.delta_eur))
        
        # Determine delta status indicators
        if calc.delta_eur > 0:
            delta_status = f"Holding more by {delta_amount}"
            delta_indicator = "over"
        elif calc.delta_eur < 0:
            delta_status = f"Short by {delta_amount}"
            delta_indicator = "short"
        else:
            delta_status = "Balanced"
            delta_indicator = "balanced"
        
        return InternalSection(
            current_holdings=f"Currently holding: {current_holdings}",
            reconciliation_delta=delta_status,
            delta_status=delta_status,
            delta_indicator=delta_indicator
        )
    
    def _format_currency(self, amount: Decimal) -> str:
        """Format Decimal as Euro currency with commas."""
        return f"EUR {amount:,.2f}"
    
    def get_associate_transactions(self, associate_id: int, cutoff_date: str) -> List[Dict]:
        """
        Get detailed transaction list for CSV export.
        
        Args:
            associate_id: Associate ID
            cutoff_date: Cutoff date (inclusive)
            
        Returns:
            List of transaction dictionaries
        """
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    id,
                    type,
                    amount_eur,
                    native_currency,
                    amount_native,
                    fx_rate_snapshot,
                    settlement_state,
                    principal_returned_eur,
                    per_surebet_share_eur,
                    surebet_id,
                    bet_id,
                    created_at_utc,
                    note
                FROM ledger_entries
                WHERE associate_id = ?
                AND created_at_utc <= ?
                ORDER BY created_at_utc DESC
            """, (associate_id, cutoff_date))
            
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
            
        finally:
            conn.close()
    
    def validate_cutoff_date(self, cutoff_date: str) -> bool:
        """
        Validate that cutoff date is not in the future.
        
        Args:
            cutoff_date: ISO datetime string
            
        Returns:
            True if valid, False if future date
        """
        try:
            cutoff_dt = datetime.fromisoformat(cutoff_date.replace('Z', '+00:00'))
            now_dt = datetime.fromisoformat(utc_now_iso().replace('Z', '+00:00'))
            return cutoff_dt.date() <= now_dt.date()
        except ValueError:
            return False
