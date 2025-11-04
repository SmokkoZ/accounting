"""
Unit tests for BookmakerBalanceCheckRepository.
"""

import sqlite3
from decimal import Decimal

import pytest

from src.core.schema import create_schema
from src.repositories import BookmakerBalanceCheckRepository


@pytest.fixture()
def db_conn() -> sqlite3.Connection:
    """Create in-memory database with core schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    create_schema(conn)

    # Seed associates and bookmakers required for foreign keys
    conn.execute(
        "INSERT INTO associates (id, display_alias, home_currency, is_admin) VALUES (1, 'Alice', 'EUR', 0)"
    )
    conn.execute(
        "INSERT INTO bookmakers (id, associate_id, bookmaker_name) VALUES (1, 1, 'Bet365')"
    )
    conn.commit()
    try:
        yield conn
    finally:
        conn.close()


def test_upsert_and_latest_check(db_conn: sqlite3.Connection) -> None:
    repo = BookmakerBalanceCheckRepository(db_conn)

    record_id = repo.upsert_balance_check(
        associate_id=1,
        bookmaker_id=1,
        balance_native=Decimal("100.50"),
        native_currency="EUR",
        balance_eur=Decimal("100.50"),
        fx_rate_used=Decimal("1.0"),
        check_date_utc="2025-11-03T12:00:00Z",
        note="Initial check",
    )
    assert record_id > 0

    latest = repo.get_latest_check(associate_id=1, bookmaker_id=1)
    assert latest is not None
    assert latest["balance_native"] == Decimal("100.50")
    assert latest["note"] == "Initial check"

    # Update same timestamp with new data
    repo.upsert_balance_check(
        associate_id=1,
        bookmaker_id=1,
        balance_native=Decimal("120.00"),
        native_currency="EUR",
        balance_eur=Decimal("120.00"),
        fx_rate_used=Decimal("1.0"),
        check_date_utc="2025-11-03T12:00:00Z",
        note="Adjusted",
    )

    latest = repo.get_latest_check(associate_id=1, bookmaker_id=1)
    assert latest is not None
    assert latest["balance_native"] == Decimal("120.00")
    assert latest["note"] == "Adjusted"


def test_latest_checks_map_and_recent_list(db_conn: sqlite3.Connection) -> None:
    repo = BookmakerBalanceCheckRepository(db_conn)

    # Insert multiple checks
    repo.upsert_balance_check(
        associate_id=1,
        bookmaker_id=1,
        balance_native=Decimal("90"),
        native_currency="EUR",
        balance_eur=Decimal("90"),
        fx_rate_used=Decimal("1.0"),
        check_date_utc="2025-11-02T10:00:00Z",
    )
    repo.upsert_balance_check(
        associate_id=1,
        bookmaker_id=1,
        balance_native=Decimal("110"),
        native_currency="EUR",
        balance_eur=Decimal("110"),
        fx_rate_used=Decimal("1.0"),
        check_date_utc="2025-11-04T10:00:00Z",
        note="Most recent",
    )

    latest_map = repo.get_latest_checks_map()
    assert (1, 1) in latest_map
    latest = latest_map[(1, 1)]
    assert latest["balance_eur"] == Decimal("110")
    assert latest["note"] == "Most recent"

    recent = repo.list_recent_checks(limit=5)
    assert len(recent) == 2
    assert recent[0]["balance_eur"] == Decimal("110")
    assert recent[1]["balance_eur"] == Decimal("90")
