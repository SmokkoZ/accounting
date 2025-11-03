"""
Integration tests for settlement confirmation flow (Story 4.4).

Exercises SettlementService preview generation + LedgerEntryService commit using
an in-memory SQLite database.
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal

import pytest

from src.services.ledger_entry_service import LedgerEntryService
from src.services.settlement_service import BetOutcome, SettlementService


@pytest.fixture
def test_db() -> sqlite3.Connection:
    """Build an in-memory database with minimal schema to run the flow end-to-end."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")

    db.executescript(
        """
        CREATE TABLE associates (
            id INTEGER PRIMARY KEY,
            display_alias TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE bookmakers (
            id INTEGER PRIMARY KEY,
            bookmaker_name TEXT NOT NULL
        );

        CREATE TABLE surebets (
            id INTEGER PRIMARY KEY,
            status TEXT NOT NULL,
            settled_at_utc TEXT,
            updated_at_utc TEXT,
            created_at_utc TEXT,
            CHECK (status IN ('open', 'settled'))
        );

        CREATE TABLE bets (
            id INTEGER PRIMARY KEY,
            surebet_id INTEGER,
            associate_id INTEGER,
            bookmaker_id INTEGER,
            status TEXT NOT NULL,
            stake_original TEXT,
            stake_eur TEXT,
            odds TEXT,
            odds_original TEXT,
            currency TEXT,
            created_at_utc TEXT,
            updated_at_utc TEXT,
            FOREIGN KEY (associate_id) REFERENCES associates(id),
            FOREIGN KEY (bookmaker_id) REFERENCES bookmakers(id),
            FOREIGN KEY (surebet_id) REFERENCES surebets(id)
        );

        CREATE TABLE surebet_bets (
            surebet_id INTEGER NOT NULL,
            bet_id INTEGER NOT NULL,
            side TEXT NOT NULL,
            PRIMARY KEY (surebet_id, bet_id),
            FOREIGN KEY (surebet_id) REFERENCES surebets(id),
            FOREIGN KEY (bet_id) REFERENCES bets(id)
        );

        CREATE TABLE fx_rates_daily (
            currency_code TEXT NOT NULL,
            rate_to_eur TEXT NOT NULL,
            date TEXT NOT NULL,
            fetched_at_utc TEXT,
            created_at_utc TEXT
        );

        CREATE TABLE ledger_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL CHECK (type IN ('BET_RESULT', 'DEPOSIT', 'WITHDRAWAL', 'BOOKMAKER_CORRECTION')),
            associate_id INTEGER NOT NULL,
            bookmaker_id INTEGER,
            amount_native TEXT NOT NULL,
            native_currency TEXT NOT NULL,
            fx_rate_snapshot TEXT NOT NULL,
            amount_eur TEXT NOT NULL,
            settlement_state TEXT,
            principal_returned_eur TEXT,
            per_surebet_share_eur TEXT,
            surebet_id INTEGER,
            bet_id INTEGER,
            settlement_batch_id TEXT,
            created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            created_by TEXT NOT NULL DEFAULT 'local_user',
            note TEXT
        );
        """
    )

    # Seed data
    db.execute("INSERT INTO associates (id, display_alias) VALUES (1, 'Alice'), (2, 'Bob')")
    db.execute(
        "INSERT INTO bookmakers (id, bookmaker_name) VALUES (1, 'Bet365'), (2, 'Pinnacle')"
    )
    db.execute(
        """
        INSERT INTO surebets (id, status, settled_at_utc, updated_at_utc, created_at_utc)
        VALUES (1, 'open', NULL, '2025-11-03T00:00:00Z', '2025-11-03T00:00:00Z')
        """
    )
    db.execute(
        """
        INSERT INTO bets (
            id, surebet_id, associate_id, bookmaker_id,
            status, stake_original, stake_eur, odds, odds_original,
            currency, created_at_utc, updated_at_utc
        )
        VALUES
            (1, 1, 1, 1, 'matched', '100.00', '100.00', '1.90', NULL, 'EUR', '2025-11-03T00:00:00Z', '2025-11-03T00:00:00Z'),
            (2, 1, 2, 2, 'matched', '80.00', '80.00', '2.10', NULL, 'EUR', '2025-11-03T00:00:00Z', '2025-11-03T00:00:00Z')
        """
    )
    db.execute(
        "INSERT INTO surebet_bets (surebet_id, bet_id, side) VALUES (1, 1, 'A'), (1, 2, 'B')"
    )
    db.execute(
        """
        INSERT INTO fx_rates_daily (currency_code, rate_to_eur, date, fetched_at_utc, created_at_utc)
        VALUES
            ('EUR', '1.00', '2025-11-03', '2025-11-03T00:00:00Z', '2025-11-03T00:00:00Z')
        """
    )

    db.commit()

    yield db
    db.close()


def test_settlement_confirmation_flow_standard(test_db: sqlite3.Connection) -> None:
    """Preview settlement then confirm and verify ledger entries."""
    settlement_service = SettlementService(db=test_db)
    outcomes = {1: BetOutcome.WON, 2: BetOutcome.LOST}
    preview = settlement_service.preview_settlement(1, outcomes)

    ledger_service = LedgerEntryService(db=test_db)
    confirmation = ledger_service.confirm_settlement(1, preview)

    assert confirmation.success is True
    assert confirmation.entries_written == 2
    assert confirmation.total_eur_amount == Decimal("10.00")

    rows = test_db.execute(
        """
        SELECT bet_id, type, settlement_state, amount_native, amount_eur,
               principal_returned_eur, per_surebet_share_eur, settlement_batch_id
        FROM ledger_entries
        ORDER BY bet_id
        """
    ).fetchall()

    assert len(rows) == 2
    batch_id = rows[0]["settlement_batch_id"]
    assert batch_id == rows[1]["settlement_batch_id"] == confirmation.settlement_batch_id

    won_row = rows[0]
    lost_row = rows[1]

    assert won_row["bet_id"] == 1
    assert won_row["settlement_state"] == "WON"
    assert won_row["amount_native"] == "90.00"
    assert won_row["amount_eur"] == "90.00"
    assert won_row["principal_returned_eur"] == "100.00"
    assert won_row["per_surebet_share_eur"] == "5.00"

    assert lost_row["bet_id"] == 2
    assert lost_row["settlement_state"] == "LOST"
    assert lost_row["amount_native"] == "-80.00"
    assert lost_row["amount_eur"] == "-80.00"
    assert lost_row["principal_returned_eur"] == "0.00"
    assert lost_row["per_surebet_share_eur"] == "5.00"

    surebet = test_db.execute(
        "SELECT status, settled_at_utc FROM surebets WHERE id = 1"
    ).fetchone()
    assert surebet["status"] == "settled"
    assert surebet["settled_at_utc"] is not None

    bet_statuses = test_db.execute(
        "SELECT status FROM bets ORDER BY id"
    ).fetchall()
    assert [row["status"] for row in bet_statuses] == ["settled", "settled"]


def test_settlement_confirmation_all_void(test_db: sqlite3.Connection) -> None:
    """All VOID outcomes still produce zeroed ledger rows with refunded stakes."""
    settlement_service = SettlementService(db=test_db)
    outcomes = {1: BetOutcome.VOID, 2: BetOutcome.VOID}
    preview = settlement_service.preview_settlement(1, outcomes)

    ledger_service = LedgerEntryService(db=test_db)
    confirmation = ledger_service.confirm_settlement(1, preview)

    rows = test_db.execute(
        "SELECT settlement_state, amount_native, amount_eur, principal_returned_eur, per_surebet_share_eur "
        "FROM ledger_entries ORDER BY bet_id"
    ).fetchall()

    assert [row["settlement_state"] for row in rows] == ["VOID", "VOID"]
    assert all(row["amount_native"] == "0.00" for row in rows)
    assert all(row["amount_eur"] == "0.00" for row in rows)
    assert rows[0]["principal_returned_eur"] == "100.00"
    assert rows[1]["principal_returned_eur"] == "80.00"
    assert all(row["per_surebet_share_eur"] == "0.00" for row in rows)
    assert confirmation.total_eur_amount == Decimal("0.00")
