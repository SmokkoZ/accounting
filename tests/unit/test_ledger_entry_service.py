"""
Unit tests for LedgerEntryService (Story 4.4).

These tests focus on transaction-protected ledger writing and status updates.
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from typing import Dict

import pytest

from src.services.ledger_entry_service import (
    LedgerEntryService,
    SettlementCommitError,
)
from src.services.settlement_service import (
    BetOutcome,
    LedgerEntryPreview,
    Participant,
    SettlementPreview,
)


@pytest.fixture
def db_conn() -> sqlite3.Connection:
    """Create an in-memory SQLite database with minimal schema for tests."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    conn.executescript(
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
            associate_id INTEGER NOT NULL,
            bookmaker_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            stake_original TEXT,
            stake_eur TEXT,
            odds TEXT,
            currency TEXT,
            updated_at_utc TEXT,
            created_at_utc TEXT,
            FOREIGN KEY (associate_id) REFERENCES associates(id),
            FOREIGN KEY (bookmaker_id) REFERENCES bookmakers(id)
        );

        CREATE TABLE surebet_bets (
            surebet_id INTEGER NOT NULL,
            bet_id INTEGER NOT NULL,
            PRIMARY KEY (surebet_id, bet_id),
            FOREIGN KEY (surebet_id) REFERENCES surebets(id),
            FOREIGN KEY (bet_id) REFERENCES bets(id)
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
            note TEXT,
            opposing_associate_id INTEGER,
            FOREIGN KEY (associate_id) REFERENCES associates(id),
            FOREIGN KEY (bookmaker_id) REFERENCES bookmakers(id),
            FOREIGN KEY (surebet_id) REFERENCES surebets(id),
            FOREIGN KEY (bet_id) REFERENCES bets(id)
        );

        CREATE TABLE surebet_settlement_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            surebet_id INTEGER NOT NULL,
            winner_associate_id INTEGER NOT NULL,
            loser_associate_id INTEGER NOT NULL,
            amount_eur TEXT NOT NULL,
            winner_ledger_entry_id INTEGER NOT NULL,
            loser_ledger_entry_id INTEGER NOT NULL,
            created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            FOREIGN KEY (surebet_id) REFERENCES surebets(id),
            FOREIGN KEY (winner_ledger_entry_id) REFERENCES ledger_entries(id),
            FOREIGN KEY (loser_ledger_entry_id) REFERENCES ledger_entries(id)
        );
        """
    )

    # Seed reference data
    conn.execute("INSERT INTO associates (id, display_alias) VALUES (1, 'Alice'), (2, 'Bob')")
    conn.execute(
        "INSERT INTO bookmakers (id, bookmaker_name) VALUES (1, 'Bet365'), (2, 'Pinnacle')"
    )
    conn.execute(
        """
        INSERT INTO surebets (id, status, settled_at_utc, updated_at_utc, created_at_utc)
        VALUES (1, 'open', NULL, '2025-11-03T00:00:00Z', '2025-11-03T00:00:00Z')
        """
    )
    conn.execute(
        """
        INSERT INTO bets (
            id, associate_id, bookmaker_id, status,
            stake_original, stake_eur, odds, currency,
            updated_at_utc, created_at_utc
        )
        VALUES
            (1, 1, 1, 'matched', '100.00', '100.00', '2.00', 'EUR', '2025-11-03T00:00:00Z', '2025-11-03T00:00:00Z'),
            (2, 2, 2, 'matched', '100.00', '100.00', '3.50', 'EUR', '2025-11-03T00:00:00Z', '2025-11-03T00:00:00Z')
        """
    )
    conn.execute(
        """
        INSERT INTO surebet_bets (surebet_id, bet_id)
        VALUES (1, 1), (1, 2)
        """
    )

    conn.commit()

    yield conn
    conn.close()


def _build_preview(per_surebet_share: Decimal = Decimal("0.00")) -> SettlementPreview:
    """Helper to create a SettlementPreview for tests."""
    participants = [
        Participant(
            bet_id=1,
            associate_id=1,
            bookmaker_id=1,
            associate_alias="Alice",
            bookmaker_name="Bet365",
            outcome=BetOutcome.WON,
            seat_type="staked",
            stake_eur=Decimal("100.00"),
            stake_native=Decimal("100.00"),
            odds=Decimal("2.00"),
            currency="EUR",
            fx_rate=Decimal("1.00"),
        ),
        Participant(
            bet_id=2,
            associate_id=2,
            bookmaker_id=2,
            associate_alias="Bob",
            bookmaker_name="Pinnacle",
            outcome=BetOutcome.LOST,
            seat_type="staked",
            stake_eur=Decimal("100.00"),
            stake_native=Decimal("100.00"),
            odds=Decimal("3.50"),
            currency="EUR",
            fx_rate=Decimal("1.00"),
        ),
    ]

    ledger_previews = [
        LedgerEntryPreview(
            bet_id=1,
            associate_alias="Alice",
            bookmaker_name="Bet365",
            outcome="WON",
            principal_returned_eur=Decimal("100.00"),
            per_surebet_share_eur=per_surebet_share,
            total_amount_eur=Decimal("100.00") + per_surebet_share,
            fx_rate=Decimal("1.00"),
            currency="EUR",
        ),
        LedgerEntryPreview(
            bet_id=2,
            associate_alias="Bob",
            bookmaker_name="Pinnacle",
            outcome="LOST",
            principal_returned_eur=Decimal("0.00"),
            per_surebet_share_eur=per_surebet_share,
            total_amount_eur=per_surebet_share,
            fx_rate=Decimal("1.00"),
            currency="EUR",
        ),
    ]

    per_bet_outcomes: Dict[int, BetOutcome] = {
        1: BetOutcome.WON,
        2: BetOutcome.LOST,
    }
    per_bet_net_gains: Dict[int, Decimal] = {
        1: Decimal("100.00"),
        2: Decimal("-100.00"),
    }

    return SettlementPreview(
        surebet_id=1,
        per_bet_outcomes=per_bet_outcomes,
        per_bet_net_gains=per_bet_net_gains,
        surebet_profit_eur=sum(per_bet_net_gains.values()),
        num_participants=len(participants),
        participants=participants,
        per_surebet_share_eur=per_surebet_share,
        ledger_entries=ledger_previews,
        settlement_batch_id="preview-batch-id",
        warnings=[],
    )


def test_confirm_settlement_creates_ledger_entries(db_conn: sqlite3.Connection) -> None:
    """Confirm settlement writes ledger entries and updates statuses."""
    preview = _build_preview()
    service = LedgerEntryService(db=db_conn)

    confirmation = service.confirm_settlement(1, preview)

    assert confirmation.success is True
    assert confirmation.entries_written == 2
    assert confirmation.total_eur_amount == Decimal("0.00")
    assert len(confirmation.ledger_entry_ids) == 2

    rows = db_conn.execute(
        "SELECT * FROM ledger_entries ORDER BY bet_id"
    ).fetchall()
    assert len(rows) == 2

    first, second = rows
    assert first["bet_id"] == 1
    assert first["type"] == "BET_RESULT"
    assert first["settlement_state"] == "WON"
    assert first["amount_native"] == "100.00"
    assert first["principal_returned_eur"] == "100.00"
    assert first["per_surebet_share_eur"] == "0.00"
    assert first["opposing_associate_id"] == 2

    assert second["bet_id"] == 2
    assert second["settlement_state"] == "LOST"
    assert second["amount_native"] == "-100.00"
    assert second["principal_returned_eur"] == "0.00"
    assert second["opposing_associate_id"] == 1

    surebet_row = db_conn.execute("SELECT status, settled_at_utc FROM surebets WHERE id = 1").fetchone()
    assert surebet_row["status"] == "settled"
    assert surebet_row["settled_at_utc"] is not None

    bet_statuses = db_conn.execute(
        "SELECT id, status FROM bets ORDER BY id"
    ).fetchall()
    assert [row["status"] for row in bet_statuses] == ["settled", "settled"]

    settlement_links = db_conn.execute(
        "SELECT * FROM surebet_settlement_links"
    ).fetchall()
    assert len(settlement_links) == 1
    link = settlement_links[0]
    assert link["surebet_id"] == 1
    assert link["winner_associate_id"] == 1
    assert link["loser_associate_id"] == 2
    assert link["winner_ledger_entry_id"] == first["id"]
    assert link["loser_ledger_entry_id"] == second["id"]
    assert Decimal(link["amount_eur"]) == Decimal("100.00")


def test_confirm_settlement_handles_all_void(db_conn: sqlite3.Connection) -> None:
    """Void outcomes still generate ledger rows with zero profit and refunded principal."""
    preview = _build_preview()
    # Adjust participants/outcomes to VOID scenario
    preview.participants[0].outcome = BetOutcome.VOID
    preview.participants[1].outcome = BetOutcome.VOID
    preview.per_bet_outcomes = {1: BetOutcome.VOID, 2: BetOutcome.VOID}
    preview.per_bet_net_gains = {1: Decimal("0.00"), 2: Decimal("0.00")}
    preview.surebet_profit_eur = Decimal("0.00")
    preview.per_surebet_share_eur = Decimal("0.00")
    preview.ledger_entries = [
        LedgerEntryPreview(
            bet_id=1,
            associate_alias="Alice",
            bookmaker_name="Bet365",
            outcome="VOID",
            principal_returned_eur=Decimal("100.00"),
            per_surebet_share_eur=Decimal("0.00"),
            total_amount_eur=Decimal("100.00"),
            fx_rate=Decimal("1.00"),
            currency="EUR",
        ),
        LedgerEntryPreview(
            bet_id=2,
            associate_alias="Bob",
            bookmaker_name="Pinnacle",
            outcome="VOID",
            principal_returned_eur=Decimal("100.00"),
            per_surebet_share_eur=Decimal("0.00"),
            total_amount_eur=Decimal("100.00"),
            fx_rate=Decimal("1.00"),
            currency="EUR",
        ),
    ]

    service = LedgerEntryService(db=db_conn)
    confirmation = service.confirm_settlement(1, preview)

    rows = db_conn.execute(
        "SELECT settlement_state, amount_native, amount_eur, principal_returned_eur, per_surebet_share_eur "
        "FROM ledger_entries ORDER BY bet_id"
    ).fetchall()

    assert [row["settlement_state"] for row in rows] == ["VOID", "VOID"]
    assert all(row["amount_native"] == "0.00" for row in rows)
    assert all(row["amount_eur"] == "0.00" for row in rows)
    assert rows[0]["principal_returned_eur"] == "100.00"
    assert rows[1]["principal_returned_eur"] == "100.00"
    assert all(row["per_surebet_share_eur"] == "0.00" for row in rows)
    assert confirmation.total_eur_amount == Decimal("0.00")
    opposing = db_conn.execute(
        "SELECT opposing_associate_id FROM ledger_entries ORDER BY bet_id"
    ).fetchall()
    assert [row["opposing_associate_id"] for row in opposing] == [2, 1]
    assert (
        db_conn.execute("SELECT COUNT(*) FROM surebet_settlement_links").fetchone()[0]
        == 0
    )


def test_confirm_settlement_rolls_back_on_failure(db_conn: sqlite3.Connection) -> None:
    """Failures during ledger write should rollback all database changes."""
    preview = _build_preview()
    service = LedgerEntryService(db=db_conn)

    original_write = service._write_ledger_entries

    def boom(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("Simulated failure")

    service._write_ledger_entries = boom  # type: ignore[assignment]

    with pytest.raises(SettlementCommitError):
        service.confirm_settlement(1, preview)

    # Ensure no ledger rows inserted
    count = db_conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0]
    assert count == 0

    assert (
        db_conn.execute("SELECT COUNT(*) FROM surebet_settlement_links").fetchone()[0]
        == 0
    )

    # Surebet should remain open
    surebet_row = db_conn.execute("SELECT status FROM surebets WHERE id = 1").fetchone()
    assert surebet_row["status"] == "open"

    # Bets should remain unchanged
    statuses = db_conn.execute("SELECT status FROM bets ORDER BY id").fetchall()
    assert [row["status"] for row in statuses] == ["matched", "matched"]

    # Restore original method to avoid side effects
    service._write_ledger_entries = original_write  # type: ignore[assignment]
