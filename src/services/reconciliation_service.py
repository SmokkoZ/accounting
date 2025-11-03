"""
Reconciliation service for calculating associate balances and financial health.

Implements Story 5.2 requirements: per-associate reconciliation calculations,
DELTA thresholds, status determination, and human-readable explanations.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional

from src.core.database import get_db_connection
from src.utils.logging_config import get_logger


logger = get_logger(__name__)


@dataclass
class AssociateBalance:
    """Financial health snapshot for one associate."""

    associate_id: int
    associate_alias: str
    net_deposits_eur: Decimal
    should_hold_eur: Decimal
    current_holding_eur: Decimal
    delta_eur: Decimal
    status: str  # "overholder", "balanced", "short"
    status_icon: str  # 🔴, 🟢, 🟠


class ReconciliationService:
    """Service for calculating reconciliation metrics and associate balances."""

    DELTA_THRESHOLD_EUR = Decimal("10.00")  # ±€10 is "balanced"

    def __init__(self, db: sqlite3.Connection | None = None) -> None:
        self._owns_connection = db is None
        self.db = db or get_db_connection()

    def close(self) -> None:
        """Close the managed database connection if owned by the service."""
        if not self._owns_connection:
            return
        try:
            self.db.close()
        except Exception:  # pragma: no cover - defensive path
            pass

    def get_associate_balances(self) -> List[AssociateBalance]:
        """
        Calculate NET_DEPOSITS, SHOULD_HOLD, CURRENT_HOLDING, DELTA for all associates.

        Returns:
            List of AssociateBalance objects sorted by DELTA (largest overholder first)
        """
        logger.info("calculating_associate_balances")

        cursor = self.db.execute(
            """
            SELECT
                a.id AS associate_id,
                a.display_alias AS associate_alias,

                -- NET_DEPOSITS_EUR: Personal funding (deposits - withdrawals)
                COALESCE(SUM(
                    CASE
                        WHEN le.type = 'DEPOSIT' THEN CAST(le.amount_eur AS REAL)
                        WHEN le.type = 'WITHDRAWAL' THEN CAST(le.amount_eur AS REAL)
                        ELSE 0
                    END
                ), 0) AS net_deposits_eur,

                -- SHOULD_HOLD_EUR: Entitlement from settled bets
                COALESCE(SUM(
                    CASE
                        WHEN le.type = 'BET_RESULT' THEN
                            CAST(le.principal_returned_eur AS REAL) + CAST(le.per_surebet_share_eur AS REAL)
                        ELSE 0
                    END
                ), 0) AS should_hold_eur,

                -- CURRENT_HOLDING_EUR: Physical bookmaker holdings (all entry types)
                COALESCE(SUM(CAST(le.amount_eur AS REAL)), 0) AS current_holding_eur

            FROM associates a
            LEFT JOIN ledger_entries le ON a.id = le.associate_id
            WHERE a.is_active = 1
            GROUP BY a.id, a.display_alias
            ORDER BY a.display_alias
        """
        )

        balances: List[AssociateBalance] = []
        for row in cursor.fetchall():
            net_deposits = self._quantize_currency(Decimal(str(row["net_deposits_eur"])))
            should_hold = self._quantize_currency(Decimal(str(row["should_hold_eur"])))
            current_holding = self._quantize_currency(
                Decimal(str(row["current_holding_eur"]))
            )
            delta = self._quantize_currency(current_holding - should_hold)

            status, status_icon = self._determine_status(delta)

            balance = AssociateBalance(
                associate_id=row["associate_id"],
                associate_alias=row["associate_alias"],
                net_deposits_eur=net_deposits,
                should_hold_eur=should_hold,
                current_holding_eur=current_holding,
                delta_eur=delta,
                status=status,
                status_icon=status_icon,
            )
            balances.append(balance)

        # Sort by DELTA descending (largest overholders first)
        balances.sort(key=lambda b: b.delta_eur, reverse=True)

        logger.info("associate_balances_calculated", count=len(balances))
        return balances

    def get_explanation(self, balance: AssociateBalance) -> str:
        """
        Generate human-readable explanation for associate balance status.

        Args:
            balance: AssociateBalance object

        Returns:
            Human-readable explanation string
        """
        alias = balance.associate_alias
        net_deposits = self._format_currency(balance.net_deposits_eur)
        should_hold = self._format_currency(balance.should_hold_eur)
        current_holding = self._format_currency(balance.current_holding_eur)
        delta_abs = abs(balance.delta_eur)
        delta_formatted = self._format_currency(delta_abs)

        if balance.status == "overholder":
            return (
                f"{alias} is holding €{delta_formatted} more than their entitlement. "
                f"They funded €{net_deposits} total and are entitled to €{should_hold}, "
                f"but currently hold €{current_holding} in bookmaker accounts. "
                f"Collect €{delta_formatted} from them."
            )
        elif balance.status == "short":
            return (
                f"{alias} is short €{delta_formatted}. "
                f"They funded €{net_deposits} and are entitled to €{should_hold}, "
                f"but only hold €{current_holding} in bookmaker accounts. "
                f"Someone else is holding their €{delta_formatted}."
            )
        else:  # balanced
            return (
                f"{alias} is balanced. "
                f"They funded €{net_deposits} and are entitled to €{should_hold}. "
                f"Their current bookmaker holdings of €{current_holding} match their entitlement "
                f"(within €{self._format_currency(self.DELTA_THRESHOLD_EUR)} threshold)."
            )

    def _determine_status(self, delta_eur: Decimal) -> tuple[str, str]:
        """
        Determine status and icon based on DELTA threshold.

        Args:
            delta_eur: DELTA value (CURRENT_HOLDING - SHOULD_HOLD)

        Returns:
            Tuple of (status, status_icon)
        """
        if delta_eur > self.DELTA_THRESHOLD_EUR:
            return "overholder", "🔴"
        elif delta_eur < -self.DELTA_THRESHOLD_EUR:
            return "short", "🟠"
        else:
            return "balanced", "🟢"

    @staticmethod
    def _quantize_currency(value: Decimal) -> Decimal:
        """Round monetary values to 2 decimal places (cents)."""
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @staticmethod
    def _format_currency(value: Decimal) -> str:
        """Format Decimal currency value for display (e.g., '1,234.56')."""
        return f"{value:,.2f}"
