"""Unit tests for balance check query functions."""

import pytest
import sqlite3
from decimal import Decimal
from datetime import date, datetime
from typing import Generator

from src.ui.pages.balance_management import (
    load_balance_checks,
    calculate_modeled_balance,
    insert_balance_check,
    update_balance_check,
    delete_balance_check,
)


@pytest.fixture
def test_db() -> Generator[sqlite3.Connection, None, None]:
    """Create in-memory test database with schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    # Create tables
    conn.execute("""
        CREATE TABLE associates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            display_alias TEXT NOT NULL UNIQUE,
            home_currency TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            is_admin INTEGER DEFAULT 0,
            multibook_chat_id TEXT,
            created_at_utc TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE bookmakers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            associate_id INTEGER NOT NULL,
            bookmaker_name TEXT NOT NULL,
            parsing_profile TEXT,
            is_active INTEGER DEFAULT 1,
            created_at_utc TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL,
            FOREIGN KEY (associate_id) REFERENCES associates(id) ON DELETE CASCADE,
            UNIQUE (associate_id, bookmaker_name)
        )
    """)

    conn.execute("""
        CREATE TABLE bookmaker_balance_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            associate_id INTEGER NOT NULL,
            bookmaker_id INTEGER NOT NULL,
            balance_native TEXT NOT NULL,
            native_currency TEXT NOT NULL,
            balance_eur TEXT NOT NULL,
            fx_rate_used TEXT NOT NULL,
            check_date_utc TEXT NOT NULL,
            created_at_utc TEXT NOT NULL DEFAULT (datetime('now') || 'Z'),
            note TEXT,
            FOREIGN KEY (associate_id) REFERENCES associates(id),
            FOREIGN KEY (bookmaker_id) REFERENCES bookmakers(id)
        )
    """)

    conn.execute("""
        CREATE TABLE ledger_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL CHECK (type IN ('BET_RESULT', 'DEPOSIT', 'WITHDRAWAL', 'BOOKMAKER_CORRECTION')),
            associate_id INTEGER NOT NULL REFERENCES associates(id),
            bookmaker_id INTEGER REFERENCES bookmakers(id),
            amount_native TEXT NOT NULL,
            native_currency TEXT NOT NULL,
            fx_rate_snapshot TEXT NOT NULL,
            amount_eur TEXT NOT NULL,
            settlement_state TEXT CHECK (settlement_state IN ('WON', 'LOST', 'VOID') OR settlement_state IS NULL),
            principal_returned_eur TEXT,
            per_surebet_share_eur TEXT,
            surebet_id INTEGER,
            bet_id INTEGER,
            settlement_batch_id TEXT,
            created_at_utc TEXT NOT NULL DEFAULT (datetime('now') || 'Z'),
            created_by TEXT NOT NULL DEFAULT 'local_user',
            note TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE fx_rates_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            currency_code TEXT NOT NULL,
            rate_to_eur TEXT NOT NULL,
            date TEXT NOT NULL,
            fetched_at_utc TEXT NOT NULL,
            created_at_utc TEXT NOT NULL DEFAULT (datetime('now') || 'Z'),
            UNIQUE (currency_code, date)
        )
    """)

    # Insert test data
    conn.execute(
        "INSERT INTO associates (display_alias, home_currency, is_admin, created_at_utc, updated_at_utc) VALUES ('Alice', 'EUR', 0, '2025-11-01T00:00:00Z', '2025-11-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO associates (display_alias, home_currency, is_admin, created_at_utc, updated_at_utc) VALUES ('Bob', 'GBP', 0, '2025-11-01T00:00:00Z', '2025-11-01T00:00:00Z')"
    )

    conn.execute(
        "INSERT INTO bookmakers (associate_id, bookmaker_name, is_active, created_at_utc, updated_at_utc) VALUES (1, 'Bet365', 1, '2025-11-01T00:00:00Z', '2025-11-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO bookmakers (associate_id, bookmaker_name, is_active, created_at_utc, updated_at_utc) VALUES (2, 'Betfair', 1, '2025-11-01T00:00:00Z', '2025-11-01T00:00:00Z')"
    )

    # Insert FX rates
    conn.execute(
        "INSERT INTO fx_rates_daily (currency_code, rate_to_eur, date, fetched_at_utc) VALUES ('EUR', '1.0', '2025-11-01', '2025-11-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO fx_rates_daily (currency_code, rate_to_eur, date, fetched_at_utc) VALUES ('GBP', '0.85', '2025-11-01', '2025-11-01T00:00:00Z')"
    )

    conn.commit()

    yield conn

    conn.close()


def test_load_balance_checks_returns_all_for_bookmaker(test_db: sqlite3.Connection) -> None:
    """Test loading all balance checks for a bookmaker."""
    # Insert balance checks
    test_db.execute(
        """
        INSERT INTO bookmaker_balance_checks
        (associate_id, bookmaker_id, balance_native, native_currency, balance_eur, fx_rate_used, check_date_utc)
        VALUES (1, 1, '1250.00', 'EUR', '1250.00', '1.0', '2025-11-01T14:30:00Z')
    """
    )
    test_db.execute(
        """
        INSERT INTO bookmaker_balance_checks
        (associate_id, bookmaker_id, balance_native, native_currency, balance_eur, fx_rate_used, check_date_utc)
        VALUES (1, 1, '1000.00', 'EUR', '1000.00', '1.0', '2025-10-31T14:30:00Z')
    """
    )
    test_db.commit()

    checks = load_balance_checks(bookmaker_id=1, conn=test_db)

    assert len(checks) == 2
    assert all(check["bookmaker_id"] == 1 for check in checks)
    # Should be ordered by check_date_utc DESC (newest first)
    assert checks[0]["check_date_utc"] == "2025-11-01T14:30:00Z"
    assert checks[1]["check_date_utc"] == "2025-10-31T14:30:00Z"


def test_load_balance_checks_filters_by_date_range(test_db: sqlite3.Connection) -> None:
    """Test date range filtering."""
    # Insert balance checks with different dates
    test_db.execute(
        """
        INSERT INTO bookmaker_balance_checks
        (associate_id, bookmaker_id, balance_native, native_currency, balance_eur, fx_rate_used, check_date_utc)
        VALUES (1, 1, '1000.00', 'EUR', '1000.00', '1.0', '2025-11-01T00:00:00Z')
    """
    )
    test_db.execute(
        """
        INSERT INTO bookmaker_balance_checks
        (associate_id, bookmaker_id, balance_native, native_currency, balance_eur, fx_rate_used, check_date_utc)
        VALUES (1, 1, '1200.00', 'EUR', '1200.00', '1.0', '2025-11-15T00:00:00Z')
    """
    )
    test_db.execute(
        """
        INSERT INTO bookmaker_balance_checks
        (associate_id, bookmaker_id, balance_native, native_currency, balance_eur, fx_rate_used, check_date_utc)
        VALUES (1, 1, '1300.00', 'EUR', '1300.00', '1.0', '2025-11-30T00:00:00Z')
    """
    )
    test_db.commit()

    checks = load_balance_checks(
        bookmaker_id=1, start_date="2025-11-10", end_date="2025-11-20", conn=test_db
    )

    assert len(checks) == 1
    assert checks[0]["check_date_utc"] == "2025-11-15T00:00:00Z"


def test_calculate_modeled_balance_from_ledger(test_db: sqlite3.Connection) -> None:
    """Test modeled balance calculation."""
    # Insert ledger entries
    test_db.execute(
        """
        INSERT INTO ledger_entries
        (type, associate_id, bookmaker_id, amount_native, native_currency, fx_rate_snapshot, amount_eur, note)
        VALUES ('DEPOSIT', 1, 1, '100.00', 'EUR', '1.0', '100.00', 'Test deposit')
    """
    )
    test_db.execute(
        """
        INSERT INTO ledger_entries
        (type, associate_id, bookmaker_id, amount_native, native_currency, fx_rate_snapshot, amount_eur, note)
        VALUES ('WITHDRAWAL', 1, 1, '50.00', 'EUR', '1.0', '50.00', 'Test withdrawal')
    """
    )
    test_db.commit()

    result = calculate_modeled_balance(1, 1, test_db)

    assert result["modeled_balance_eur"] == Decimal("150.00")
    assert result["native_currency"] == "EUR"
    assert result["modeled_balance_native"] == Decimal("150.00")


def test_insert_balance_check_with_fx_conversion(test_db: sqlite3.Connection) -> None:
    """Test inserting balance check with FX conversion."""
    success, message = insert_balance_check(
        associate_id=2,
        bookmaker_id=2,
        balance_native=Decimal("1000.00"),
        native_currency="GBP",
        check_date_utc="2025-11-01T14:30:00Z",
        note="Test check",
        conn=test_db,
    )

    assert success is True
    assert "recorded" in message.lower()

    # Verify insert
    cursor = test_db.execute("SELECT * FROM bookmaker_balance_checks WHERE bookmaker_id = 2")
    check = cursor.fetchone()

    assert check is not None
    assert Decimal(check["balance_native"]) == Decimal("1000.00")
    assert check["native_currency"] == "GBP"
    # FX rate should be fetched from the database (value will vary)
    assert Decimal(check["fx_rate_used"]) > 0
    # Balance EUR should be GBP * fx_rate
    expected_eur = Decimal("1000.00") * Decimal(check["fx_rate_used"])
    assert abs(Decimal(check["balance_eur"]) - expected_eur) < Decimal("0.01")


def test_update_balance_check_recalculates_fx(test_db: sqlite3.Connection) -> None:
    """Test updating balance check recalculates FX rate."""
    # Insert initial check
    test_db.execute(
        """
        INSERT INTO bookmaker_balance_checks
        (associate_id, bookmaker_id, balance_native, native_currency, balance_eur, fx_rate_used, check_date_utc)
        VALUES (1, 1, '1000.00', 'EUR', '1000.00', '1.0', '2025-11-01T14:30:00Z')
    """
    )
    test_db.commit()

    check_id = test_db.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Update balance check
    success, message = update_balance_check(
        check_id=check_id,
        balance_native=Decimal("1100.00"),
        native_currency="EUR",
        check_date_utc="2025-11-01T15:00:00Z",
        note="Updated check",
        conn=test_db,
    )

    assert success is True

    # Verify update
    cursor = test_db.execute(f"SELECT * FROM bookmaker_balance_checks WHERE id = {check_id}")
    check = cursor.fetchone()

    assert Decimal(check["balance_native"]) == Decimal("1100.00")
    assert Decimal(check["balance_eur"]) == Decimal("1100.00")


def test_delete_balance_check(test_db: sqlite3.Connection) -> None:
    """Test deleting balance check."""
    # Insert check
    test_db.execute(
        """
        INSERT INTO bookmaker_balance_checks
        (associate_id, bookmaker_id, balance_native, native_currency, balance_eur, fx_rate_used, check_date_utc)
        VALUES (1, 1, '1000.00', 'EUR', '1000.00', '1.0', '2025-11-01T14:30:00Z')
    """
    )
    test_db.commit()

    check_id = test_db.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Delete check
    success, message = delete_balance_check(check_id, test_db)

    assert success is True

    # Verify deletion
    cursor = test_db.execute(f"SELECT * FROM bookmaker_balance_checks WHERE id = {check_id}")
    check = cursor.fetchone()

    assert check is None
