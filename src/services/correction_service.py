"""
Correction service for post-settlement adjustments.

Implements Story 5.1 requirements: forward-only corrections via BOOKMAKER_CORRECTION
ledger entries, FX rate freezing, and validation of associate-bookmaker relationships.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional

from src.core.database import get_db_connection
from src.services.fx_manager import get_fx_rate, get_latest_fx_rate
from src.utils.database_utils import TransactionError, transactional
from src.utils.logging_config import get_logger


logger = get_logger(__name__)


class CorrectionError(Exception):
    """Raised when correction application fails."""

    pass


class CorrectionService:
    """Service for applying forward-only corrections to ledger entries."""

    def __init__(self, db: sqlite3.Connection | None = None) -> None:
        """
        Initialize the correction service.

        Args:
            db: Optional database connection. If None, creates its own connection.
        """
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

    def apply_correction(
        self,
        associate_id: int,
        bookmaker_id: int,
        amount_native: Decimal,
        native_currency: str,
        note: str,
        created_by: str = "local_user",
    ) -> int:
        """
        Apply forward-only correction by creating new ledger entry.

        CRITICAL: This does NOT edit existing entries. Creates new entry_type='BOOKMAKER_CORRECTION'.

        Args:
            associate_id: The associate receiving the correction
            bookmaker_id: The bookmaker account affected
            amount_native: Positive (increase holdings) or negative (decrease holdings)
            native_currency: Currency code (EUR, USD, GBP, AUD, CAD)
            note: Required explanatory note for audit trail
            created_by: User applying the correction

        Returns:
            entry_id of created ledger entry

        Raises:
            CorrectionError: If validation fails or correction cannot be applied
        """
        logger.info(
            "applying_correction",
            associate_id=associate_id,
            bookmaker_id=bookmaker_id,
            amount=str(amount_native),
            currency=native_currency,
        )

        # Validate correction data
        self._validate_correction_data(
            associate_id, bookmaker_id, amount_native, native_currency, note
        )

        # Freeze FX rate at current time
        fx_rate = self._get_current_fx_rate(native_currency)

        # Calculate EUR amount with proper precision
        amount_eur = self._calculate_eur_amount(amount_native, fx_rate)

        try:
            with transactional(self.db) as conn:
                entry_id = self._write_correction_entry(
                    conn,
                    associate_id,
                    bookmaker_id,
                    amount_native,
                    native_currency,
                    fx_rate,
                    amount_eur,
                    note,
                    created_by,
                )
        except TransactionError as exc:  # pragma: no cover - defensive path
            raise CorrectionError(str(exc)) from exc
        except Exception as exc:
            logger.error(
                "correction_failed",
                associate_id=associate_id,
                bookmaker_id=bookmaker_id,
                error=str(exc),
                exc_info=True,
            )
            raise CorrectionError("Correction application failed.") from exc

        logger.info(
            "correction_applied",
            entry_id=entry_id,
            associate_id=associate_id,
            bookmaker_id=bookmaker_id,
            amount_eur=str(amount_eur),
        )

        return entry_id

    def get_corrections_since(
        self, days: int = 30, associate_id: Optional[int] = None
    ) -> List[dict]:
        """
        Get corrections from the last N days.

        Args:
            days: Number of days to look back (default 30)
            associate_id: Optional filter by associate

        Returns:
            List of correction entries with details
        """
        cutoff = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        cutoff = cutoff - timedelta(days=days)
        cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        query = """
            SELECT
                le.id,
                le.created_at_utc,
                le.associate_id,
                a.display_alias,
                le.bookmaker_id,
                b.bookmaker_name,
                le.amount_native,
                le.native_currency,
                le.fx_rate_snapshot,
                le.amount_eur,
                le.note,
                le.created_by
            FROM ledger_entries le
            JOIN associates a ON le.associate_id = a.id
            LEFT JOIN bookmakers b ON le.bookmaker_id = b.id
            WHERE le.type = 'BOOKMAKER_CORRECTION'
                AND le.created_at_utc >= ?
        """

        params = [cutoff_str]

        if associate_id is not None:
            query += " AND le.associate_id = ?"
            params.append(associate_id)

        query += " ORDER BY le.created_at_utc DESC"

        cursor = self.db.execute(query, params)
        rows = cursor.fetchall()

        corrections = []
        for row in rows:
            corrections.append(
                {
                    "id": row["id"],
                    "created_at_utc": row["created_at_utc"],
                    "associate_id": row["associate_id"],
                    "display_alias": row["display_alias"],
                    "bookmaker_id": row["bookmaker_id"],
                    "bookmaker_name": row["bookmaker_name"],
                    "amount_native": Decimal(row["amount_native"]),
                    "native_currency": row["native_currency"],
                    "fx_rate_snapshot": Decimal(row["fx_rate_snapshot"]),
                    "amount_eur": Decimal(row["amount_eur"]),
                    "note": row["note"],
                    "created_by": row["created_by"],
                }
            )

        return corrections

    def _validate_correction_data(
        self,
        associate_id: int,
        bookmaker_id: int,
        amount_native: Decimal,
        native_currency: str,
        note: str,
    ) -> None:
        """
        Validate correction inputs before processing.

        Raises:
            CorrectionError: If validation fails
        """
        # Check zero amount
        if amount_native == Decimal("0"):
            raise CorrectionError("Correction amount cannot be zero")

        # Check note is provided
        if not note or not note.strip():
            raise CorrectionError("Explanatory note is required for corrections")

        # Check currency is supported
        supported_currencies = ["EUR", "USD", "GBP", "AUD", "CAD"]
        if native_currency.upper() not in supported_currencies:
            raise CorrectionError(
                f"Unsupported currency: {native_currency}. "
                f"Supported: {', '.join(supported_currencies)}"
            )

        # Check associate exists
        cursor = self.db.execute(
            "SELECT id FROM associates WHERE id = ?", (associate_id,)
        )
        if not cursor.fetchone():
            raise CorrectionError(f"Associate not found: {associate_id}")

        # Check bookmaker exists and belongs to associate
        cursor = self.db.execute(
            """
            SELECT id FROM bookmakers
            WHERE id = ? AND associate_id = ?
        """,
            (bookmaker_id, associate_id),
        )
        if not cursor.fetchone():
            raise CorrectionError(
                f"Bookmaker {bookmaker_id} not found or does not belong to "
                f"associate {associate_id}"
            )

    def _get_current_fx_rate(self, currency: str) -> Decimal:
        """
        Get current FX rate and freeze it for ledger entry.

        Args:
            currency: Currency code (EUR, USD, GBP, AUD, CAD)

        Returns:
            Current FX rate (EUR per 1 unit native)

        Raises:
            CorrectionError: If FX rate is not available
        """
        if currency.upper() == "EUR":
            return Decimal("1.00")

        # Get the most recent FX rate
        result = get_latest_fx_rate(currency.upper())

        if result is None:
            raise CorrectionError(
                f"No FX rate available for {currency}. "
                f"Please ensure FX rates are up to date."
            )

        fx_rate, rate_date = result

        logger.info(
            "fx_rate_frozen",
            currency=currency,
            rate=str(fx_rate),
            rate_date=rate_date,
        )

        return fx_rate

    def _calculate_eur_amount(
        self, amount_native: Decimal, fx_rate: Decimal
    ) -> Decimal:
        """
        Calculate EUR amount with proper Decimal precision.

        Args:
            amount_native: Amount in native currency
            fx_rate: FX rate (EUR per 1 unit native)

        Returns:
            Amount in EUR with 2 decimal places
        """
        amount_eur = amount_native * fx_rate
        return amount_eur.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def _write_correction_entry(
        self,
        conn: sqlite3.Connection,
        associate_id: int,
        bookmaker_id: int,
        amount_native: Decimal,
        native_currency: str,
        fx_rate: Decimal,
        amount_eur: Decimal,
        note: str,
        created_by: str,
    ) -> int:
        """
        Write correction entry to ledger.

        Args:
            conn: Database connection (within transaction)
            associate_id: Associate ID
            bookmaker_id: Bookmaker ID
            amount_native: Native currency amount
            native_currency: Currency code
            fx_rate: Frozen FX rate
            amount_eur: EUR amount
            note: Explanatory note
            created_by: User applying correction

        Returns:
            ID of created ledger entry
        """
        # Quantize values for storage
        amount_native = self._quantize_currency(amount_native)
        fx_rate = fx_rate.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        amount_eur = self._quantize_currency(amount_eur)

        cursor = conn.execute(
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
                "BOOKMAKER_CORRECTION",
                associate_id,
                bookmaker_id,
                str(amount_native),
                native_currency.upper(),
                str(fx_rate),
                str(amount_eur),
                None,  # settlement_state (not applicable for corrections)
                None,  # principal_returned_eur (not applicable)
                None,  # per_surebet_share_eur (not applicable)
                None,  # surebet_id (corrections are independent)
                None,  # bet_id (corrections are independent)
                None,  # settlement_batch_id (not applicable)
                created_by,
                note,
            ),
        )

        return cursor.lastrowid

    @staticmethod
    def _quantize_currency(value: Decimal) -> Decimal:
        """Round monetary values to cents."""
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
