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
class StatementCalculations:
    """Container for all statement calculation results."""
    # Raw calculations
    associate_id: int
    net_deposits_eur: Decimal
    should_hold_eur: Decimal
    current_holding_eur: Decimal
    
    # Derived calculations
    raw_profit_eur: Decimal
    delta_eur: Decimal
    
    # Metadata
    associate_name: str
    cutoff_date: str
    generated_at: str


@dataclass
class PartnerFacingSection:
    """Data for partner-facing statement section."""
    funding_summary: str
    entitlement_summary: str
    profit_loss_summary: str
    split_calculation: Dict[str, str]


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
            associate_name = self._get_associate_name(conn, associate_id)
            if not associate_name:
                raise ValueError(f"Associate ID {associate_id} not found")
            
            # Perform all calculations
            net_deposits = self._calculate_net_deposits(conn, associate_id, cutoff_date)
            should_hold = self._calculate_should_hold(conn, associate_id, cutoff_date)
            current_holding = self._calculate_current_holding(conn, associate_id, cutoff_date)
            
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
                associate_name=associate_name,
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
    
    def _get_associate_name(self, conn, associate_id: int) -> Optional[str]:
        """Get associate display name by ID."""
        cursor = conn.cursor()
        cursor.execute(
            "SELECT display_alias FROM associates WHERE id = ?",
            (associate_id,)
        )
        row = cursor.fetchone()
        return row["display_alias"] if row else None
    
    def _calculate_net_deposits(self, conn, associate_id: int, cutoff_date: str) -> Decimal:
        """
        Calculate NET_DEPOSITS_EUR = SUM(DEPOSIT.amount_eur) - SUM(WITHDRAWAL.amount_eur)
        
        Args:
            conn: Database connection
            associate_id: Associate ID
            cutoff_date: Cutoff date (inclusive)
            
        Returns:
            Net deposits as Decimal
        """
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                SUM(
                    CASE
                        WHEN type = 'DEPOSIT' THEN CAST(amount_eur AS REAL)
                        WHEN type = 'WITHDRAWAL' THEN -CAST(amount_eur AS REAL)
                        ELSE 0
                    END
                ) AS net_deposits_eur
            FROM ledger_entries
            WHERE associate_id = ?
            AND type IN ('DEPOSIT', 'WITHDRAWAL')
            AND created_at_utc <= ?
        """, (associate_id, cutoff_date))
        
        row = cursor.fetchone()
        result = row["net_deposits_eur"] or 0.0
        return Decimal(str(result))
    
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
    
    def format_partner_facing_section(self, calc: StatementCalculations) -> PartnerFacingSection:
        """
        Format partner-facing statement section.
        
        Args:
            calc: Statement calculations
            
        Returns:
            Formatted partner-facing section
        """
        funding_amount = self._format_currency(calc.net_deposits_eur)
        entitlement_amount = self._format_currency(calc.should_hold_eur)
        profit_amount = self._format_currency(calc.raw_profit_eur)
        
        # Calculate 50/50 split
        admin_share = calc.raw_profit_eur / Decimal("2")
        associate_share = calc.raw_profit_eur / Decimal("2")
        
        return PartnerFacingSection(
            funding_summary=f"You funded: {funding_amount} total",
            entitlement_summary=f"You're entitled to: {entitlement_amount}",
            profit_loss_summary=self._format_profit_loss(calc.raw_profit_eur),
            split_calculation={
                "admin_share": self._format_currency(admin_share),
                "associate_share": self._format_currency(associate_share),
                "explanation": "Profit is split 50/50 between associate and admin"
            }
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
    
    def _format_profit_loss(self, amount: Decimal) -> str:
        """Format profit/loss with color coding indicator."""
        formatted_amount = self._format_currency(amount)
        if amount > 0:
            return f"Profit: {formatted_amount}"
        elif amount < 0:
            return f"Loss: {formatted_amount}"
        else:
            return f"Break-even: {formatted_amount}"
    
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
            return cutoff_dt <= now_dt
        except ValueError:
            return False
