"""
Stake ledger helpers for capturing BET_STAKE entries at bet verification time.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Dict, Mapping

import structlog

from src.core.config import Config
from src.services.fx_manager import get_fx_rate

logger = structlog.get_logger(__name__)


class StakeLedgerService:
    """Encapsulates creation and adjustment of BET_STAKE ledger entries."""

    RATE_PRECISION = Decimal("0.000001")
    CURRENCY_PRECISION = Decimal("0.01")

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def sync_bet_stake(
        self,
        *,
        bet: Mapping[str, object],
        created_by: str,
        note: str,
        release_when_missing: bool = False,
    ) -> None:
        """
        Ensure BET_STAKE ledger rows match the current bet stake snapshot.

        Args:
            bet: Latest bet record (dict-like) including stake fields.
            created_by: Actor recorded on ledger entries.
            note: Ledger note explaining why the entry was written.
            release_when_missing: When True, missing stake information zeros out
                any existing BET_STAKE rows. When False, missing data skips writes.
        """
        if not Config.STAKE_AT_PLACEMENT:
            return

        bet_id_raw = bet.get("id")
        associate_raw = bet.get("associate_id")
        bookmaker_raw = bet.get("bookmaker_id")

        try:
            bet_id = int(bet_id_raw) if bet_id_raw is not None else None
            associate_id = int(associate_raw) if associate_raw is not None else None
            bookmaker_id = int(bookmaker_raw) if bookmaker_raw is not None else None
        except (TypeError, ValueError):
            bet_id = associate_id = bookmaker_id = None

        if bet_id is None or associate_id is None or bookmaker_id is None:
            logger.warning(
                "stake_entry_skipped",
                reason="missing_identifiers",
                bet_id=bet_id_raw,
                associate_id=associate_raw,
                bookmaker_id=bookmaker_raw,
            )
            return

        target_amounts: Dict[str, Decimal] = {}
        try:
            currency, stake_native = self._extract_stake(bet)
            if stake_native > Decimal("0"):
                target_amounts[currency] = -stake_native
        except ValueError:
            if not release_when_missing:
                logger.warning(
                    "stake_entry_skipped",
                    reason="missing_or_zero_stake",
                    bet_id=bet_id,
                )
                return

        adjustments = self._calculate_adjustments(bet_id, target_amounts)
        if not adjustments:
            return

        for currency, amount_native in adjustments.items():
            fx_rate = self._resolve_fx_rate(currency)
            quantized_native = self._quantize_currency(amount_native)
            if quantized_native == Decimal("0.00"):
                continue

            amount_eur = self._quantize_currency(quantized_native * fx_rate)

            self.conn.execute(
                """
                INSERT INTO ledger_entries (
                    type,
                    associate_id,
                    bookmaker_id,
                    amount_native,
                    native_currency,
                    fx_rate_snapshot,
                    amount_eur,
                    settlement_state,
                    principal_returned_eur,
                    per_surebet_share_eur,
                    surebet_id,
                    bet_id,
                    settlement_batch_id,
                    created_by,
                    note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "BET_STAKE",
                    associate_id,
                    bookmaker_id,
                    str(quantized_native),
                    currency,
                    str(fx_rate.quantize(self.RATE_PRECISION, rounding=ROUND_HALF_UP)),
                    str(amount_eur),
                    None,
                    None,
                    None,
                    None,
                    int(bet_id),
                    None,
                    created_by,
                    note,
                ),
            )

            logger.info(
                "bet_stake_entry_written",
                bet_id=bet_id,
                currency=currency,
                amount_native=str(quantized_native),
                amount_eur=str(amount_eur),
            )

    def reset_bet_stake(self, *, bet_id: int, created_by: str, note: str) -> None:
        """
        Zero out BET_STAKE balances for a bet by inserting offsetting entries.
        """
        if not Config.STAKE_AT_PLACEMENT:
            return

        bet = {"id": bet_id, "associate_id": None, "bookmaker_id": None}
        # Existing ledger rows already contain associate/bookmaker references,
        # so fetch any row to capture those identifiers.
        row = self.conn.execute(
            """
            SELECT associate_id, bookmaker_id
            FROM ledger_entries
            WHERE bet_id = ? AND type = 'BET_STAKE'
            ORDER BY id DESC LIMIT 1
            """,
            (bet_id,),
        ).fetchone()
        if row:
            bet["associate_id"] = row["associate_id"]
            bet["bookmaker_id"] = row["bookmaker_id"]
        self.sync_bet_stake(
            bet=bet,
            created_by=created_by,
            note=note,
            release_when_missing=True,
        )

    def _calculate_adjustments(
        self, bet_id: int, target_amounts: Dict[str, Decimal]
    ) -> Dict[str, Decimal]:
        current = self._load_current_totals(bet_id)
        adjustments: Dict[str, Decimal] = {}

        current_only = sorted(set(current.keys()) - set(target_amounts.keys()))
        overlap = sorted(set(current.keys()) & set(target_amounts.keys()))
        new_only = sorted(set(target_amounts.keys()) - set(current.keys()))

        for currency in current_only + overlap + new_only:
            current_value = current.get(currency, Decimal("0"))
            target_value = target_amounts.get(currency, Decimal("0"))
            delta = target_value - current_value
            delta = self._quantize_currency(delta)
            if delta != Decimal("0.00"):
                adjustments[currency] = delta
        return adjustments

    def _load_current_totals(self, bet_id: int) -> Dict[str, Decimal]:
        totals: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        cursor = self.conn.execute(
            """
            SELECT native_currency, amount_native
            FROM ledger_entries
            WHERE bet_id = ? AND type = 'BET_STAKE'
            """,
            (bet_id,),
        )
        for row in cursor.fetchall():
            currency = (row["native_currency"] or "EUR").upper()
            try:
                totals[currency] += Decimal(str(row["amount_native"]))
            except (InvalidOperation, TypeError):
                logger.warning(
                    "stake_entry_amount_parse_failed",
                    bet_id=bet_id,
                    currency=currency,
                    raw=row["amount_native"],
                )
        return totals

    def _extract_stake(self, bet: Mapping[str, object]) -> tuple[str, Decimal]:
        currency = (
            (bet.get("manual_stake_currency") or bet.get("stake_currency") or bet.get("currency") or "EUR")
            .strip()
            .upper()
        )

        for field in (
            "manual_stake_override",
            "stake_original",
            "stake_amount",
            "stake",
        ):
            raw = bet.get(field)
            value = self._safe_decimal(raw)
            if value is not None and value > 0:
                return currency, self._quantize_currency(value)

        value = self._safe_decimal(bet.get("stake_eur"))
        if value is not None and value > 0:
            return "EUR", self._quantize_currency(value)

        raise ValueError("Missing stake information")

    def _safe_decimal(self, raw: object) -> Decimal | None:
        if raw is None or raw == "":
            return None
        try:
            return Decimal(str(raw))
        except (InvalidOperation, ValueError):
            return None

    def _resolve_fx_rate(self, currency: str) -> Decimal:
        try:
            return get_fx_rate(currency, date.today(), conn=self.conn)
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning(
                "stake_entry_fx_missing",
                currency=currency,
                error=str(exc),
            )
            return Decimal("1.0")

    def _quantize_currency(self, value: Decimal) -> Decimal:
        return value.quantize(self.CURRENCY_PRECISION, rounding=ROUND_HALF_UP)
