"""
FX Rate Manager for the Surebet Accounting System.

This module provides functions for managing foreign exchange rates,
including rate lookup, currency conversion, and timestamp formatting.
"""

import sqlite3
import structlog
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from src.core.database import get_db_connection
from src.utils.datetime_helpers import utc_now_iso, get_date_string

logger = structlog.get_logger()


def get_fx_rate(
    currency: str, rate_date: date | None = None, conn: Optional[sqlite3.Connection] = None
) -> Decimal:
    """
    Get the FX rate for a currency on a specific date.

    Args:
        currency: ISO currency code (e.g., "AUD", "GBP", "USD")
        rate_date: Date for which to get the rate. Defaults to today.
        conn: Optional database connection to reuse (not closed by this function).

    Returns:
        Decimal representing the rate to EUR (how many EUR per 1 unit of currency)

    Raises:
        ValueError: If no rate exists for the currency
    """
    if currency.upper() == "EUR":
        # EUR to EUR is always 1.0
        return Decimal("1.0")

    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True

    target_date = rate_date or date.today()
    target_date_str = target_date.strftime("%Y-%m-%d")

    try:
        # Try to get rate for the specific date
        cursor = conn.execute(
            """
            SELECT rate_to_eur FROM fx_rates_daily 
            WHERE currency_code = ? AND date = ?
            ORDER BY date DESC, fetched_at_utc DESC
            LIMIT 1
        """,
            (currency.upper(), target_date_str),
        )

        row = cursor.fetchone()

        if row:
            # Found rate for the specific date
            return Decimal(row["rate_to_eur"])

        # If no rate for specific date, get the most recent rate
        cursor = conn.execute(
            """
            SELECT rate_to_eur, date FROM fx_rates_daily 
            WHERE currency_code = ?
            ORDER BY date DESC, fetched_at_utc DESC
            LIMIT 1
        """,
            (currency.upper(),),
        )

        row = cursor.fetchone()

        if row:
            # Found most recent rate
            logger.warning(
                "fx_rate_fallback_used",
                currency=currency,
                requested_date=target_date_str,
                used_date=row["date"],
            )
            return Decimal(row["rate_to_eur"])

        # No rate found for this currency
        raise ValueError(f"No FX rate found for currency: {currency}")

    finally:
        if should_close:
            conn.close()


def convert_to_eur(amount: Decimal, currency: str, fx_rate: Decimal) -> Decimal:
    """
    Convert an amount from a native currency to EUR.

    Args:
        amount: Amount in the native currency
        currency: ISO currency code (for logging/validation)
        fx_rate: Exchange rate (how many EUR per 1 unit of currency)

    Returns:
        Decimal amount in EUR with 2 decimal places

    Raises:
        InvalidOperation: If amount or fx_rate are invalid Decimals
    """
    if currency.upper() == "EUR":
        # No conversion needed for EUR
        return amount.quantize(Decimal("0.01"))

    # Convert to EUR
    eur_amount = amount * fx_rate

    # Round to 2 decimal places (standard for currency)
    return eur_amount.quantize(Decimal("0.01"))


def format_timestamp_utc() -> str:
    """
    Return current timestamp as ISO8601 with "Z" suffix.

    Returns:
        Current UTC timestamp in ISO8601 format with "Z" suffix
        Example: "2025-10-29T14:30:00Z"
    """
    return utc_now_iso()


def store_fx_rate(
    currency: str,
    rate_to_eur: Decimal,
    fetched_at_utc: str,
    source: str = "manual",
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    """
    Store an FX rate in the database.

    Args:
        currency: ISO currency code
        rate_to_eur: Rate to EUR (how many EUR per 1 unit of currency)
        fetched_at_utc: UTC timestamp when rate was fetched
        source: Source of the rate (e.g., "exchangerate-api.com", "manual")
        conn: Optional database connection (for testing)
    """
    date_str = get_date_string(parse_utc_iso(fetched_at_utc))

    # Use provided connection or create new one
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True

    try:
        # Insert or replace rate for this currency and date
        conn.execute(
            """
            INSERT OR REPLACE INTO fx_rates_daily
            (currency_code, rate_to_eur, fetched_at_utc, date, created_at_utc)
            VALUES (?, ?, ?, ?, ?)
        """,
            (
                currency.upper(),
                str(rate_to_eur),
                fetched_at_utc,
                date_str,
                utc_now_iso(),
            ),
        )

        conn.commit()

        logger.info(
            "fx_rate_stored",
            currency=currency,
            rate=str(rate_to_eur),
            date=date_str,
            source=source,
        )

    finally:
        if should_close:
            conn.close()


def get_latest_fx_rate(
    currency: str, conn: Optional[sqlite3.Connection] = None
) -> Optional[tuple[Decimal, str]]:
    """
    Get the most recent FX rate for a currency.

    Args:
        currency: ISO currency code
        conn: Optional database connection to reuse (not closed by this function).

    Returns:
        Tuple of (rate_to_eur, date) or None if no rate exists
    """
    if currency.upper() == "EUR":
        return Decimal("1.0"), get_date_string()

    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True

    try:
        cursor = conn.execute(
            """
            SELECT rate_to_eur, date FROM fx_rates_daily 
            WHERE currency_code = ?
            ORDER BY date DESC, fetched_at_utc DESC
            LIMIT 1
        """,
            (currency.upper(),),
        )

        row = cursor.fetchone()

        if row:
            return Decimal(row["rate_to_eur"]), row["date"]

        return None

    finally:
        if should_close:
            conn.close()


def parse_utc_iso(iso_string: str) -> datetime:
    """
    Parse ISO8601 string with Z suffix to datetime object.

    Args:
        iso_string: ISO8601 string with 'Z' suffix.

    Returns:
        Datetime object in UTC timezone.
    """
    # Replace Z with +00:00 for proper parsing
    if iso_string.endswith("Z"):
        iso_string = iso_string[:-1] + "+00:00"

    return datetime.fromisoformat(iso_string)
