"""
Integration tests for bookmaker drilldown workflow.
"""

import sqlite3
from decimal import Decimal

import pytest

from src.core.schema import create_schema
from src.services.bookmaker_balance_service import BookmakerBalanceService


@pytest.fixture()
def db_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    create_schema(conn)

    conn.executescript(
        """
        INSERT INTO associates (id, display_alias, home_currency, is_admin)
        VALUES (1, 'Alice', 'EUR', 0),
               (2, 'Bob', 'EUR', 0);

        INSERT INTO bookmakers (id, associate_id, bookmaker_name, is_active)
        VALUES (1, 1, 'Bet365', 1),
               (2, 2, 'Bet365', 1);

        INSERT INTO ledger_entries (
            type, associate_id, bookmaker_id, amount_native, native_currency,
            fx_rate_snapshot, amount_eur, created_at_utc
        ) VALUES
            ('DEPOSIT', 1, 1, '800.00', 'EUR', '1.0', '800.00', '2025-11-02T08:00:00Z'),
            ('DEPOSIT', 2, 2, '600.00', 'EUR', '1.0', '600.00', '2025-11-02T09:00:00Z');

        INSERT INTO bookmaker_balance_checks (
            associate_id, bookmaker_id, balance_native, native_currency,
            balance_eur, fx_rate_used, check_date_utc
        ) VALUES
            (1, 1, '900.00', 'EUR', '900.00', '1.0', '2025-11-03T10:00:00Z'),
            (2, 2, '550.00', 'EUR', '550.00', '1.0', '2025-11-03T10:05:00Z');
        """
    )

    conn.commit()
    try:
        yield conn
    finally:
        conn.close()


def test_workflow_updates_and_prefill(db_conn: sqlite3.Connection) -> None:
    service = BookmakerBalanceService(db_conn)

    balances = service.get_bookmaker_balances()
    alice = next(b for b in balances if b.associate_alias == "Alice")
    bob = next(b for b in balances if b.associate_alias == "Bob")

    assert alice.difference_eur == Decimal("100.00")
    assert bob.difference_eur == Decimal("-50.00")
    assert alice.owed_to and alice.owed_to[0].associate_alias == "Bob"

    prefill = service.get_correction_prefill(alice)
    assert prefill is not None
    assert prefill["associate_id"] == 1
    assert prefill["bookmaker_id"] == 1
    assert prefill["amount_eur"] == Decimal("100.00")
    assert "Bet365" in prefill["note"]

    # Update reported balance for Bob to remove shortfall
    service.update_reported_balance(
        associate_id=2,
        bookmaker_id=2,
        balance_native=Decimal("600.00"),
        native_currency="EUR",
        check_date_utc="2025-11-04T08:00:00Z",
        note="Daily balance sync",
    )

    updated_balances = service.get_bookmaker_balances()
    updated_bob = next(b for b in updated_balances if b.associate_alias == "Bob")
    assert updated_bob.difference_eur == Decimal("0.00")

    service.close()
