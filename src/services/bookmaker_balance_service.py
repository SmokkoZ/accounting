"""
Bookmaker balance drilldown service.

Provides aggregation logic for Story 5.3 including modeled vs. reported
balances, mismatch status, and float attribution helpers.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Dict, Iterable, List, Optional, Tuple

from src.core.database import get_db_connection
from src.repositories import BookmakerBalanceCheckRepository
from src.services.fx_manager import convert_to_eur, get_latest_fx_rate
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

TWO_PLACES = Decimal("0.01")
DEFAULT_FX_RATE = Decimal("1.0")


@dataclass
class FloatCounterparty:
    """Represents a short associate who should receive funds from an overholder."""

    associate_id: int
    associate_alias: str
    amount_eur: Decimal
    amount_native: Optional[Decimal] = None


@dataclass
class BookmakerBalance:
    """Bookmaker reconciliation snapshot for one associate-bookmaker pairing."""

    associate_id: int
    associate_alias: str
    bookmaker_id: int
    bookmaker_name: str
    modeled_balance_eur: Decimal
    modeled_balance_native: Optional[Decimal]
    reported_balance_eur: Optional[Decimal]
    reported_balance_native: Optional[Decimal]
    native_currency: str
    difference_eur: Optional[Decimal]
    difference_native: Optional[Decimal]
    status: str
    status_icon: str
    status_color: str
    status_label: str
    last_checked_at_utc: Optional[str]
    fx_rate_used: Optional[Decimal]
    is_bookmaker_active: bool
    owed_to: List[FloatCounterparty] = field(default_factory=list)

    def has_reported_balance(self) -> bool:
        """Return True when a recent reported balance exists."""
        return self.reported_balance_eur is not None


class BookmakerBalanceService:
    """
    Aggregate modeled vs. reported bookmaker balances with attribution logic.
    """

    BALANCED_THRESHOLD_EUR = Decimal("10")
    WARNING_THRESHOLD_EUR = Decimal("50")

    def __init__(self, db: sqlite3.Connection | None = None) -> None:
        self._owns_connection = db is None
        self.db = db or get_db_connection()
        self.repository = BookmakerBalanceCheckRepository(self.db)

    def close(self) -> None:
        """Close the managed database connection if owned by the service."""
        try:
            self.repository.close()
        finally:
            if self._owns_connection:
                try:
                    self.db.close()
                except Exception:  # pragma: no cover - defensive close
                    pass

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def get_bookmaker_balances(self) -> List[BookmakerBalance]:
        """Return modeled vs. reported balances with mismatch status."""
        latest_checks = self.repository.get_latest_checks_map()

        rows = self.db.execute(
            """
            SELECT
                a.id AS associate_id,
                a.display_alias AS associate_alias,
                a.home_currency AS home_currency,
                b.id AS bookmaker_id,
                b.bookmaker_name,
                b.is_active AS bookmaker_active,
                COALESCE(SUM(CAST(le.amount_eur AS REAL)), 0) AS modeled_balance_eur
            FROM associates a
            JOIN bookmakers b ON b.associate_id = a.id
            LEFT JOIN ledger_entries le
                ON le.associate_id = a.id
                AND le.bookmaker_id = b.id
            WHERE a.is_active = 1
            GROUP BY
                a.id,
                a.display_alias,
                a.home_currency,
                b.id,
                b.bookmaker_name,
                b.is_active
            ORDER BY a.display_alias, b.bookmaker_name
            """
        ).fetchall()

        balances: List[BookmakerBalance] = []

        for row in rows:
            base = self._hydrate_balance_row(row, latest_checks)
            balances.append(base)

        self._enrich_float_attribution(balances)
        return balances

    def update_reported_balance(
        self,
        associate_id: int,
        bookmaker_id: int,
        balance_native: Decimal,
        native_currency: str,
        *,
        check_date_utc: Optional[str] = None,
        note: Optional[str] = None,
    ) -> int:
        """
        Insert or update a bookmaker balance check and return its ID.
        """
        native_currency = native_currency.upper()
        fx_rate = self._resolve_fx_rate(native_currency)

        balance_eur = convert_to_eur(balance_native, native_currency, fx_rate).quantize(
            TWO_PLACES, rounding=ROUND_HALF_UP
        )

        try:
            record_id = self.repository.upsert_balance_check(
                associate_id=associate_id,
                bookmaker_id=bookmaker_id,
                balance_native=balance_native.quantize(TWO_PLACES, rounding=ROUND_HALF_UP),
                native_currency=native_currency,
                balance_eur=balance_eur,
                fx_rate_used=fx_rate,
                check_date_utc=check_date_utc,
                note=note,
            )
        except sqlite3.IntegrityError as exc:
            logger.error(
                "balance_check_upsert_failed",
                associate_id=associate_id,
                bookmaker_id=bookmaker_id,
                error=str(exc),
            )
            raise

        return record_id

    def get_correction_prefill(
        self, balance: BookmakerBalance
    ) -> Optional[Dict[str, object]]:
        """
        Build correction pre-fill payload for Story 5.1 interface.

        Returns None when no mismatch exists.
        """
        if balance.difference_eur is None or balance.difference_eur == Decimal("0"):
            return None

        amount_native = (
            balance.difference_native.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
            if balance.difference_native is not None
            else None
        )

        return {
            "associate_id": balance.associate_id,
            "bookmaker_id": balance.bookmaker_id,
            "native_currency": balance.native_currency,
            "amount_native": amount_native,
            "amount_eur": balance.difference_eur,
            "note": (
                f"Bookmaker reconciliation adjustment for {balance.bookmaker_name} "
                f"on {balance.last_checked_at_utc or 'latest run'}"
            ),
        }

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _hydrate_balance_row(
        self,
        row: sqlite3.Row,
        latest_checks: Dict[Tuple[int, int], Dict],
    ) -> BookmakerBalance:
        associate_id = row["associate_id"]
        bookmaker_id = row["bookmaker_id"]
        modeled_eur = Decimal(str(row["modeled_balance_eur"] or 0)).quantize(
            TWO_PLACES, rounding=ROUND_HALF_UP
        )

        home_currency = row["home_currency"] or "EUR"
        check = latest_checks.get((associate_id, bookmaker_id))

        if check:
            reported_native = check["balance_native"]
            native_currency = check["native_currency"]
            reported_eur = check["balance_eur"]
            fx_rate_used = check["fx_rate_used"]
            last_checked_at = check["check_date_utc"]
        else:
            reported_native = None
            native_currency = home_currency or "EUR"
            reported_eur = None
            fx_rate_used = None
            last_checked_at = None

        fx_rate = fx_rate_used or self._resolve_fx_rate(native_currency)

        modeled_native = (
            self._convert_eur_to_native(modeled_eur, fx_rate) if fx_rate is not None else None
        )

        if reported_native is not None:
            reported_native_val = reported_native.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        else:
            reported_native_val = None

        if reported_eur is not None:
            reported_eur_val = reported_eur.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        else:
            reported_eur_val = None

        difference_eur, difference_native, status, icon, color, label = self._calculate_difference(
            modeled_eur, reported_eur_val, fx_rate
        )

        return BookmakerBalance(
            associate_id=associate_id,
            associate_alias=row["associate_alias"],
            bookmaker_id=bookmaker_id,
            bookmaker_name=row["bookmaker_name"],
            modeled_balance_eur=modeled_eur,
            modeled_balance_native=modeled_native,
            reported_balance_eur=reported_eur_val,
            reported_balance_native=reported_native_val,
            native_currency=native_currency,
            difference_eur=difference_eur,
            difference_native=difference_native,
            status=status,
            status_icon=icon,
            status_color=color,
            status_label=label,
            last_checked_at_utc=last_checked_at,
            fx_rate_used=fx_rate,
            is_bookmaker_active=bool(row["bookmaker_active"]),
        )

    def _resolve_fx_rate(self, currency: str) -> Decimal:
        """
        Resolve the most recent FX rate for a currency.
        """
        currency = currency.upper()
        if currency == "EUR":
            return DEFAULT_FX_RATE

        latest = get_latest_fx_rate(currency)
        if latest is None:
            logger.warning(
                "fx_rate_missing_for_currency",
                currency=currency,
            )
            return DEFAULT_FX_RATE
        return Decimal(latest[0]).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)

    def _convert_eur_to_native(
        self, amount_eur: Decimal, fx_rate: Optional[Decimal]
    ) -> Optional[Decimal]:
        """Convert EUR amount back to native currency."""
        if fx_rate is None or fx_rate == Decimal("0"):
            return None
        try:
            native = (amount_eur / fx_rate).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
            return native
        except (InvalidOperation, ZeroDivisionError):  # pragma: no cover - defensive
            return None

    def _calculate_difference(
        self,
        modeled_eur: Decimal,
        reported_eur: Optional[Decimal],
        fx_rate: Optional[Decimal],
    ) -> Tuple[Optional[Decimal], Optional[Decimal], str, str, str, str]:
        """
        Determine difference, native value, and status metadata.
        """
        if reported_eur is None:
            return (None, None, "unverified", "⚪", "#eceff1", "No reported balance")

        difference_eur = (reported_eur - modeled_eur).quantize(
            TWO_PLACES, rounding=ROUND_HALF_UP
        )
        difference_native = self._convert_eur_to_native(difference_eur, fx_rate)

        abs_diff = abs(difference_eur)
        if abs_diff < self.BALANCED_THRESHOLD_EUR:
            return (
                difference_eur,
                difference_native,
                "balanced",
                "🟢",
                "#e8f5e9",
                "Balanced (±€10)",
            )

        if abs_diff < self.WARNING_THRESHOLD_EUR:
            icon = "🟡" if difference_eur >= 0 else "🟠"
            label = "Minor mismatch (monitor)"
            color = "#fff8e1"
            return (
                difference_eur,
                difference_native,
                "minor_mismatch",
                icon,
                color,
                label,
            )

        icon = "🔺" if difference_eur >= 0 else "🔻"
        label = "Major mismatch - investigate"
        color = "#ffebee"
        return (
            difference_eur,
            difference_native,
            "major_mismatch",
            icon,
            color,
            label,
        )

    def _enrich_float_attribution(self, balances: List[BookmakerBalance]) -> None:
        """
        Populate owed_to lists for overholding balances.
        """
        by_bookmaker: Dict[str, List[BookmakerBalance]] = {}
        for balance in balances:
            key = balance.bookmaker_name.lower()
            by_bookmaker.setdefault(key, []).append(balance)

        for _, rows in by_bookmaker.items():
            positives = [
                r
                for r in rows
                if r.difference_eur is not None and r.difference_eur > Decimal("0")
            ]
            negatives = [
                r
                for r in rows
                if r.difference_eur is not None and r.difference_eur < Decimal("0")
            ]

            if not positives or not negatives:
                continue

            available: Dict[int, Decimal] = {
                neg.associate_id: abs(neg.difference_eur) for neg in negatives
            }

            for overholder in positives:
                remaining = overholder.difference_eur or Decimal("0")
                if remaining <= 0:
                    continue

                owed: List[FloatCounterparty] = []
                for short in negatives:
                    short_available = available.get(short.associate_id, Decimal("0"))
                    if short_available <= 0 or remaining <= 0:
                        continue

                    allocation = min(remaining, short_available).quantize(
                        TWO_PLACES, rounding=ROUND_HALF_UP
                    )
                    if allocation <= 0:
                        continue

                    owed.append(
                        FloatCounterparty(
                            associate_id=short.associate_id,
                            associate_alias=short.associate_alias,
                            amount_eur=allocation,
                            amount_native=self._convert_eur_to_native(
                                allocation, overholder.fx_rate_used
                            ),
                        )
                    )
                    available[short.associate_id] = short_available - allocation
                    remaining -= allocation

                overholder.owed_to = owed

    # Context manager convenience -------------------------------------------------

    def __enter__(self) -> "BookmakerBalanceService":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
