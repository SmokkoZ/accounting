"""
Unit tests for BookmakerBalanceService.
"""

import sqlite3
from datetime import datetime
from decimal import Decimal

import pytest

from src.core.schema import create_schema
from src.services.bookmaker_balance_service import (
    BookmakerBalanceService,
)


@pytest.fixture()
def db_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    create_schema(conn)

    # Seed associates and bookmakers
    conn.executescript(
        """
        INSERT INTO associates (id, display_alias, home_currency, is_admin)
        VALUES (1, 'Alice', 'EUR', 0), (2, 'Bob', 'EUR', 0);

        INSERT INTO bookmakers (id, associate_id, bookmaker_name, is_active)
        VALUES (1, 1, 'Bet365', 1),
               (2, 2, 'Bet365', 1);

        INSERT INTO ledger_entries (
            type, associate_id, bookmaker_id, amount_native, native_currency,
            fx_rate_snapshot, amount_eur, settlement_state, principal_returned_eur,
            per_surebet_share_eur, created_at_utc
        ) VALUES
            ('DEPOSIT', 1, 1, '500.00', 'EUR', '1.0', '500.00', NULL, NULL, NULL, '2025-11-01T10:00:00Z'),
            ('DEPOSIT', 2, 2, '400.00', 'EUR', '1.0', '400.00', NULL, NULL, NULL, '2025-11-01T11:00:00Z');
        """
    )

    conn.execute(
        """
        INSERT INTO bookmaker_balance_checks (
            associate_id, bookmaker_id, balance_native, native_currency,
            balance_eur, fx_rate_used, check_date_utc, note
        ) VALUES
            (1, 1, '600.00', 'EUR', '600.00', '1.0', '2025-11-02T12:00:00Z', 'Reported over'),
            (2, 2, '350.00', 'EUR', '350.00', '1.0', '2025-11-02T12:05:00Z', 'Reported short');
        """
    )

    conn.commit()
    try:
        yield conn
    finally:
        conn.close()


def test_get_bookmaker_balances_and_attribution(db_conn: sqlite3.Connection) -> None:
    service = BookmakerBalanceService(db_conn)
    balances = service.get_bookmaker_balances()

    # Expect two balances
    assert len(balances) == 2

    alice = next(b for b in balances if b.associate_alias == "Alice")
    bob = next(b for b in balances if b.associate_alias == "Bob")

    assert alice.modeled_balance_eur == Decimal("500.00")
    assert alice.reported_balance_eur == Decimal("600.00")
    assert alice.difference_eur == Decimal("100.00")
    assert alice.status == "major_mismatch"
    assert alice.owed_to  # should list Bob as owed counterpart
    assert len(alice.owed_to) == 1
    owed = alice.owed_to[0]
    assert owed.associate_alias == "Bob"
    assert owed.amount_eur == Decimal("50.00")

    assert bob.modeled_balance_eur == Decimal("400.00")
    assert bob.reported_balance_eur == Decimal("350.00")
    assert bob.difference_eur == Decimal("-50.00")

    service.close()


def test_update_reported_balance(db_conn: sqlite3.Connection) -> None:
    service = BookmakerBalanceService(db_conn)
    service.update_reported_balance(
        associate_id=1,
        bookmaker_id=1,
        balance_native=Decimal("580.00"),
        native_currency="EUR",
        check_date_utc="2025-11-03T09:00:00Z",
        note="Manual update",
    )

    repo_latest = service.repository.get_latest_check(1, 1)
    assert repo_latest is not None
    assert repo_latest["balance_native"] == Decimal("580.00")
    assert repo_latest["note"] == "Manual update"

    service.close()


def test_get_pending_balance_summary_defaults_to_zero(
    db_conn: sqlite3.Connection,
) -> None:
    service = BookmakerBalanceService(db_conn)

    summary = service.get_pending_balance_summary(associate_id=1, bookmaker_id=1)

    assert summary.total_eur == Decimal("0.00")
    assert summary.display_amount == Decimal("0.00")
    assert summary.display_currency == "EUR"

    service.close()


def test_get_pending_balance_summary_converts_to_home_currency(
    db_conn: sqlite3.Connection,
) -> None:
    db_conn.execute(
        "INSERT INTO associates (id, display_alias, home_currency, is_admin) VALUES (3, 'Cara', 'GBP', 0)"
    )
    db_conn.execute(
        "INSERT INTO bookmakers (id, associate_id, bookmaker_name, is_active) VALUES (3, 3, 'SkyBet', 1)"
    )
    db_conn.executemany(
        """
        INSERT INTO bets (associate_id, bookmaker_id, status, stake_eur, odds, currency, fx_rate_to_eur)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (3, 3, "verified", "100.00", "2.1", "GBP", "1.0"),
            (3, 3, "matched", "150.00", "1.9", "GBP", "1.0"),
            (3, 3, "incoming", "999.00", "2.0", "GBP", "1.0"),
        ],
    )
    db_conn.execute(
        """
        INSERT INTO fx_rates_daily (currency_code, rate_to_eur, fetched_at_utc, date, created_at_utc)
        VALUES ('GBP', '1.25', '2025-11-02T00:00:00Z', '2025-11-02', '2025-11-02T00:00:00Z')
        """
    )
    db_conn.commit()

    service = BookmakerBalanceService(db_conn)
    summary = service.get_pending_balance_summary(associate_id=3, bookmaker_id=3)

    assert summary.total_eur == Decimal("250.00")
    assert summary.display_amount == Decimal("200.00")  # 250 / 1.25
    assert summary.display_currency == "GBP"

    service.close()


def test_build_balance_message_uses_latest_report_and_pending(
    db_conn: sqlite3.Connection,
) -> None:
    db_conn.executemany(
        """
        INSERT INTO bets (associate_id, bookmaker_id, status, stake_eur, odds, currency, fx_rate_to_eur)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (1, 1, "verified", "50.00", "2.0", "EUR", "1.0"),
            (1, 1, "matched", "100.00", "1.8", "EUR", "1.0"),
        ],
    )
    db_conn.commit()

    service = BookmakerBalanceService(db_conn)
    payload = service.build_balance_message(
        associate_id=1,
        bookmaker_id=1,
        as_of=datetime(2025, 11, 8, 9, 30),
    )

    assert payload.message == "08/11/25 Balance: 600.00 EUR, pending balance: 150.00 EUR."
    assert payload.balance_amount == Decimal("600.00")
    assert payload.balance_currency == "EUR"
    assert payload.pending_amount == Decimal("150.00")
    assert payload.pending_currency == "EUR"

    service.close()


def test_build_balance_message_handles_missing_report(
    db_conn: sqlite3.Connection,
) -> None:
    db_conn.execute(
        "INSERT INTO associates (id, display_alias, home_currency, is_admin) VALUES (3, 'Cara', 'USD', 0)"
    )
    db_conn.execute(
        "INSERT INTO bookmakers (id, associate_id, bookmaker_name, is_active) VALUES (3, 3, 'FanDuel', 1)"
    )
    db_conn.executemany(
        """
        INSERT INTO bets (associate_id, bookmaker_id, status, stake_eur, odds, currency, fx_rate_to_eur)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (3, 3, "verified", "75.00", "1.5", "USD", "1.0"),
            (3, 3, "matched", "25.00", "1.2", "USD", "1.0"),
        ],
    )
    db_conn.execute(
        """
        INSERT INTO ledger_entries (
            type, associate_id, bookmaker_id, amount_native, native_currency,
            fx_rate_snapshot, amount_eur, settlement_state, principal_returned_eur,
            per_surebet_share_eur, created_at_utc
        ) VALUES (
            'DEPOSIT', 3, 3, '100.00', 'USD', '1.10', '110.00', NULL, NULL, NULL, '2025-11-01T07:00:00Z'
        )
        """
    )
    db_conn.execute(
        """
        INSERT INTO fx_rates_daily (currency_code, rate_to_eur, fetched_at_utc, date, created_at_utc)
        VALUES ('USD', '1.10', '2025-11-02T00:00:00Z', '2025-11-02', '2025-11-02T00:00:00Z')
        """
    )
    db_conn.commit()

    service = BookmakerBalanceService(db_conn)
    payload = service.build_balance_message(
        associate_id=3,
        bookmaker_id=3,
        as_of=datetime(2025, 11, 8, 0, 5),
    )

    assert payload.message == "08/11/25 Balance: 100.00 USD, pending balance: 90.91 USD."
    assert payload.balance_amount == Decimal("100.00")
    assert payload.pending_amount == Decimal("90.91")
    assert payload.pending_currency == "USD"

    service.close()
