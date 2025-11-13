"""
Bookmaker financial enrichment service for Admin & Associates tooling.

Provides balance, pending stake, funding, and profit snapshots per bookmaker
with dual-currency representations (native + EUR).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from src.core.database import get_db_connection
from src.services.fx_manager import get_latest_fx_rate
from src.services.settlement_constants import SETTLEMENT_NOTE_PREFIX
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

TWO_PLACES = Decimal("0.01")


@dataclass(frozen=True)
class BookmakerFinancialSnapshot:
    """Typed snapshot used by downstream UI/tests."""

    id: int
    associate_id: int
    bookmaker_name: str
    parsing_profile: Optional[str]
    is_active: bool
    bookmaker_chat_id: Optional[str]
    created_at_utc: Optional[str]
    updated_at_utc: Optional[str]
    balance_eur: Optional[Decimal]
    balance_native: Optional[Decimal]
    native_currency: str
    pending_balance_eur: Decimal
    pending_balance_native: Optional[Decimal]
    net_deposits_eur: Decimal
    net_deposits_native: Optional[Decimal]
    profits_eur: Decimal
    profits_native: Optional[Decimal]
    latest_balance_check_date: Optional[str]
    fs_eur: Decimal = field(init=False)
    yf_eur: Decimal = field(init=False)
    i_double_prime_eur: Optional[Decimal] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "fs_eur", self.profits_eur)
        object.__setattr__(
            self,
            "yf_eur",
            (self.net_deposits_eur + self.profits_eur).quantize(
                TWO_PLACES, rounding=ROUND_HALF_UP
            ),
        )
        if self.balance_eur is None:
            imbalance = None
        else:
            imbalance = (self.balance_eur - self.yf_eur).quantize(
                TWO_PLACES, rounding=ROUND_HALF_UP
            )
        object.__setattr__(self, "i_double_prime_eur", imbalance)


class BookmakerFinancialsService:
    """Service that enriches bookmaker records with financial aggregates."""

    def __init__(self, db: Optional[sqlite3.Connection] = None) -> None:
        self._owns_connection = db is None
        self.db = db or get_db_connection()

    def close(self) -> None:
        """Close owned database connection."""
        if not self._owns_connection:
            return
        try:
            self.db.close()
        except Exception:  # pragma: no cover - defensive close
            pass

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def get_financials_for_associate(self, associate_id: int) -> List[BookmakerFinancialSnapshot]:
        """Return bookmaker financial snapshots for the provided associate."""
        has_balance_table = self._table_exists("bookmaker_balance_checks")
        has_chat_table = self._table_exists("chat_registrations")

        balance_select, balance_join = self._build_balance_segments(has_balance_table)
        chat_select, chat_join = self._build_chat_segments(has_chat_table)

        query = f"""
            SELECT
                b.id,
                b.associate_id,
                b.bookmaker_name,
                b.parsing_profile,
                b.is_active,
                b.created_at_utc,
                b.updated_at_utc,
                {chat_select},
                {balance_select},
                COALESCE(pending.pending_eur, 0) AS pending_balance_eur,
                COALESCE(funding.net_deposits_eur, 0) AS net_deposits_eur,
                COALESCE(entitlements.surebet_profit_eur, 0) AS surebet_profit_eur,
                a.home_currency AS home_currency
            FROM bookmakers b
            JOIN associates a ON a.id = b.associate_id
            {chat_join}
            {balance_join}
            LEFT JOIN (
                SELECT
                    associate_id,
                    bookmaker_id,
                    SUM(
                        CASE
                            WHEN stake_eur IS NOT NULL AND stake_eur != ''
                            THEN CAST(stake_eur AS REAL)
                            ELSE 0
                        END
                    ) AS pending_eur
                FROM bets
                WHERE status IN ('verified', 'matched')
                GROUP BY associate_id, bookmaker_id
            ) pending ON pending.bookmaker_id = b.id AND pending.associate_id = b.associate_id
            LEFT JOIN (
                SELECT
                    associate_id,
                    bookmaker_id,
                    SUM(
                        CASE
                            WHEN type = 'DEPOSIT' THEN CAST(amount_eur AS REAL)
                            WHEN type = 'WITHDRAWAL' THEN CAST(amount_eur AS REAL)
                            ELSE 0
                        END
                    ) AS net_deposits_eur
                FROM ledger_entries
                WHERE bookmaker_id IS NOT NULL
                  AND type IN ('DEPOSIT', 'WITHDRAWAL')
                  AND (note IS NULL OR note NOT LIKE ?)
                GROUP BY associate_id, bookmaker_id
            ) funding ON funding.bookmaker_id = b.id AND funding.associate_id = b.associate_id
            LEFT JOIN (
                SELECT
                    associate_id,
                    bookmaker_id,
                    SUM(
                        COALESCE(CAST(per_surebet_share_eur AS REAL), 0)
                    ) AS surebet_profit_eur
                FROM ledger_entries
                WHERE bookmaker_id IS NOT NULL
                  AND type = 'BET_RESULT'
                GROUP BY associate_id, bookmaker_id
            ) entitlements ON entitlements.bookmaker_id = b.id AND entitlements.associate_id = b.associate_id
            WHERE b.associate_id = ?
            ORDER BY b.bookmaker_name ASC
        """

        settlement_filter = f"{SETTLEMENT_NOTE_PREFIX}%"
        cursor = self.db.execute(query, (settlement_filter, associate_id))
        rows = cursor.fetchall()

        fx_cache: Dict[str, Optional[Decimal]] = {}
        snapshots: List[BookmakerFinancialSnapshot] = []
        for row in rows:
            balance_eur = self._to_decimal(row["balance_eur"])
            balance_native = self._to_decimal(row["balance_native"])
            native_currency = (
                (row["balance_native_currency"] or row["home_currency"] or "EUR")
                .strip()
                .upper()
            )
            pending_eur = self._to_decimal(row["pending_balance_eur"]) or Decimal("0.00")
            net_deposits_eur = self._to_decimal(row["net_deposits_eur"]) or Decimal("0.00")

            # Fair Share = settlement share sums; profits alias for backward compatibility
            fair_share_eur = self._to_decimal(row["surebet_profit_eur"]) or Decimal("0.00")
            profits_eur = fair_share_eur.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

            pending_native, deposits_native, profits_native = self._convert_group_to_native(
                native_currency,
                self._parse_decimal(row["balance_fx_rate"]),
                pending_eur,
                net_deposits_eur,
                profits_eur,
                fx_cache,
            )

            snapshots.append(
                BookmakerFinancialSnapshot(
                    id=row["id"],
                    associate_id=row["associate_id"],
                    bookmaker_name=row["bookmaker_name"],
                    parsing_profile=row["parsing_profile"],
                    is_active=bool(row["is_active"]),
                    bookmaker_chat_id=row["bookmaker_chat_id"],
                    created_at_utc=row["created_at_utc"],
                    updated_at_utc=row["updated_at_utc"],
                    balance_eur=balance_eur,
                    balance_native=balance_native,
                    native_currency=native_currency,
                    pending_balance_eur=pending_eur,
                    pending_balance_native=pending_native,
                    net_deposits_eur=net_deposits_eur,
                    net_deposits_native=deposits_native,
                    profits_eur=profits_eur,
                    profits_native=profits_native,
                    latest_balance_check_date=row["latest_balance_check_date"],
                )
            )

        return snapshots

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _build_balance_segments(self, enabled: bool) -> tuple[str, str]:
        if not enabled:
            return (
                "NULL AS balance_eur,\n                NULL AS balance_native,\n"
                "                NULL AS balance_native_currency,\n"
                "                NULL AS balance_fx_rate,\n"
                "                NULL AS latest_balance_check_date",
                "",
            )

        select_clause = """
                lb.balance_eur,
                lb.balance_native,
                lb.native_currency AS balance_native_currency,
                lb.fx_rate_used AS balance_fx_rate,
                lb.check_date_utc AS latest_balance_check_date
        """.strip()

        join_clause = """
            LEFT JOIN (
                SELECT
                    bookmaker_id,
                    balance_eur,
                    balance_native,
                    native_currency,
                    fx_rate_used,
                    check_date_utc,
                    ROW_NUMBER() OVER (
                        PARTITION BY bookmaker_id
                        ORDER BY check_date_utc DESC, id DESC
                    ) AS rn
                FROM bookmaker_balance_checks
            ) lb ON lb.bookmaker_id = b.id AND lb.rn = 1
        """
        return select_clause, join_clause

    def _build_chat_segments(self, enabled: bool) -> tuple[str, str]:
        if not enabled:
            return "NULL AS bookmaker_chat_id", ""

        select_clause = "chat_latest.chat_id AS bookmaker_chat_id"
        join_clause = """
            LEFT JOIN (
                SELECT
                    bookmaker_id,
                    chat_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY bookmaker_id
                        ORDER BY updated_at_utc DESC, created_at_utc DESC, id DESC
                    ) AS rn
                FROM chat_registrations
            ) chat_latest ON chat_latest.bookmaker_id = b.id AND chat_latest.rn = 1
        """
        return select_clause, join_clause

    def _convert_group_to_native(
        self,
        currency: str,
        fx_rate_hint: Optional[Decimal],
        pending_eur: Decimal,
        net_deposits_eur: Decimal,
        profits_eur: Decimal,
        cache: Dict[str, Optional[Decimal]],
    ) -> tuple[Optional[Decimal], Optional[Decimal], Optional[Decimal]]:
        """Convert EUR aggregates to native currency using cached FX data."""
        if currency == "EUR":
            return pending_eur, net_deposits_eur, profits_eur

        fx_rate = self._resolve_fx_rate(currency, fx_rate_hint, cache)
        if fx_rate is None or fx_rate == Decimal("0"):
            return None, None, None

        return (
            self._convert_eur_to_native(pending_eur, fx_rate),
            self._convert_eur_to_native(net_deposits_eur, fx_rate),
            self._convert_eur_to_native(profits_eur, fx_rate),
        )

    def _resolve_fx_rate(
        self,
        currency: str,
        hint: Optional[Decimal],
        cache: Dict[str, Optional[Decimal]],
    ) -> Optional[Decimal]:
        """Return FX rate for currency with caching and fallback lookups."""
        currency = currency.upper()
        if currency == "EUR":
            return Decimal("1.0")

        if hint is not None and hint > Decimal("0"):
            return hint

        if currency in cache:
            return cache[currency]

        lookup = get_latest_fx_rate(currency, conn=self.db)
        rate = lookup[0] if lookup else None
        cache[currency] = rate
        if rate is None:
            logger.warning("missing_fx_rate", currency=currency)
        return rate

    @staticmethod
    def _convert_eur_to_native(amount: Decimal, fx_rate: Decimal) -> Decimal:
        """Convert EUR amount into native currency using provided FX rate."""
        try:
            native = (amount / fx_rate).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
            return native
        except (InvalidOperation, ZeroDivisionError):  # pragma: no cover - defensive
            return Decimal("0.00")

    @staticmethod
    def _parse_decimal(value: Any) -> Optional[Decimal]:
        if value in (None, ""):
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError):
            return None

    @staticmethod
    def _to_decimal(value: Any) -> Optional[Decimal]:
        if value in (None, ""):
            return None
        try:
            return Decimal(str(value)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        except (InvalidOperation, TypeError):
            return None

    def _table_exists(self, name: str) -> bool:
        cursor = self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        )
        return cursor.fetchone() is not None

    def __enter__(self) -> "BookmakerFinancialsService":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
