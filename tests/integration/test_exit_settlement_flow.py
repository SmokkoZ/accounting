import csv
import io
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from src.core.schema import create_schema
from src.services.exit_settlement_service import ExitSettlementService
from src.services.settlement_constants import (
    SETTLEMENT_MODEL_FOOTNOTE,
    SETTLEMENT_NOTE_PREFIX,
)
from src.services.statement_service import StatementService


def _connect_factory(db_path: Path):
    def _connect():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    return _connect


def _insert_ledger_entry(
    conn: sqlite3.Connection,
    *,
    associate_id: int,
    entry_type: str,
    amount: str,
    created_at: str,
    note: str,
    settlement_state: str | None = None,
    principal: str | None = None,
    share: str | None = None,
) -> None:
    conn.execute(
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
            created_at_utc,
            created_by,
            note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entry_type,
            associate_id,
            None,
            amount,
            "EUR",
            "1.00",
            amount,
            settlement_state,
            principal,
            share,
            created_at,
            "pytest",
            note,
        ),
    )


def _seed_overholding_dataset(conn: sqlite3.Connection, associate_id: int) -> None:
    _insert_ledger_entry(
        conn,
        associate_id=associate_id,
        entry_type="DEPOSIT",
        amount="600.00",
        created_at="2025-10-01T00:00:00Z",
        note="seed deposit one",
    )
    _insert_ledger_entry(
        conn,
        associate_id=associate_id,
        entry_type="DEPOSIT",
        amount="200.00",
        created_at="2025-10-05T00:00:00Z",
        note="seed deposit two",
    )
    _insert_ledger_entry(
        conn,
        associate_id=associate_id,
        entry_type="WITHDRAWAL",
        amount="-50.00",
        created_at="2025-10-08T12:00:00Z",
        note="seed withdrawal",
    )
    # WON seat with positive share
    _insert_ledger_entry(
        conn,
        associate_id=associate_id,
        entry_type="BET_RESULT",
        amount="-140.00",
        created_at="2025-10-10T09:00:00Z",
        note="won bet",
        settlement_state="WON",
        principal="100.00",
        share="40.00",
    )
    # LOST seat with negative share
    _insert_ledger_entry(
        conn,
        associate_id=associate_id,
        entry_type="BET_RESULT",
        amount="-20.00",
        created_at="2025-10-10T09:05:00Z",
        note="lost bet",
        settlement_state="LOST",
        principal="0.00",
        share="-20.00",
    )
    # VOID seat
    _insert_ledger_entry(
        conn,
        associate_id=associate_id,
        entry_type="BET_RESULT",
        amount="0.00",
        created_at="2025-10-10T09:10:00Z",
        note="void bet",
        settlement_state="VOID",
        principal="0.00",
        share="0.00",
    )
    _insert_ledger_entry(
        conn,
        associate_id=associate_id,
        entry_type="BOOKMAKER_CORRECTION",
        amount="400.00",
        created_at="2025-10-12T00:00:00Z",
        note="manual correction boost",
    )
    conn.execute(
        "INSERT INTO associates (id, display_alias, home_currency) VALUES (?, ?, ?)",
        (associate_id, f"Associate {associate_id}", "EUR"),
    )
    conn.commit()


def _seed_underholding_dataset(conn: sqlite3.Connection, associate_id: int) -> None:
    _insert_ledger_entry(
        conn,
        associate_id=associate_id,
        entry_type="DEPOSIT",
        amount="200.00",
        created_at="2025-09-01T00:00:00Z",
        note="initial deposit",
    )
    _insert_ledger_entry(
        conn,
        associate_id=associate_id,
        entry_type="BET_RESULT",
        amount="-150.00",
        created_at="2025-09-05T00:00:00Z",
        note="underholding share",
        settlement_state="WON",
        principal="110.00",
        share="40.00",
    )
    conn.execute(
        "INSERT INTO associates (id, display_alias, home_currency) VALUES (?, ?, ?)",
        (associate_id, f"Associate {associate_id}", "EUR"),
    )
    conn.commit()


def _prepare_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "exit_flow.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    conn.close()
    return db_path


def test_exit_settlement_flow_generates_receipt_and_csv_footnote(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = _prepare_db(tmp_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _seed_overholding_dataset(conn, associate_id=1)
    conn.close()

    connect = _connect_factory(db_path)
    monkeypatch.setattr("src.services.statement_service.get_db_connection", connect)
    monkeypatch.setattr("src.services.funding_transaction_service.get_db_connection", connect)

    statement_service = StatementService()
    exit_service = ExitSettlementService(
        statement_service=statement_service,
        receipt_root=tmp_path / "receipts",
    )
    cutoff = "2025-10-31T23:59:59Z"

    calc_before = statement_service.generate_statement(1, cutoff)
    assert calc_before.i_double_prime_eur > Decimal("0")

    result = exit_service.settle_associate_now(1, cutoff, calculations=calc_before, created_by="pytest")

    assert result.was_posted is True
    assert result.entry_type == "WITHDRAWAL"
    assert result.delta_after == Decimal("0.00")
    assert result.receipt.file_path and result.receipt.file_path.exists()
    content = result.receipt.file_path.read_text()
    assert SETTLEMENT_MODEL_FOOTNOTE in content

    with connect() as check_conn:
        row = check_conn.execute(
            "SELECT type, amount_eur, note FROM ledger_entries WHERE note LIKE ? ORDER BY id DESC LIMIT 1",
            (f"{SETTLEMENT_NOTE_PREFIX}%",),
        ).fetchone()
        assert row["type"] == "WITHDRAWAL"
        assert Decimal(str(row["amount_eur"])) < Decimal("0")

    export = statement_service.export_statement_csv(
        1,
        cutoff,
        calculations=result.updated_calculations,
    )
    reader = list(csv.reader(io.StringIO(export.content.decode("utf-8"))))
    summary_map = {row[0]: row[1] for row in reader if row and len(row) >= 2}
    assert "Exit Payout (-I'')" in summary_map
    assert summary_map.get("Footnote") == SETTLEMENT_MODEL_FOOTNOTE


def test_exit_settlement_flow_handles_underholding_with_deposit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = _prepare_db(tmp_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _seed_underholding_dataset(conn, associate_id=2)
    conn.close()

    connect = _connect_factory(db_path)
    monkeypatch.setattr("src.services.statement_service.get_db_connection", connect)
    monkeypatch.setattr("src.services.funding_transaction_service.get_db_connection", connect)

    statement_service = StatementService()
    exit_service = ExitSettlementService(
        statement_service=statement_service,
        receipt_root=tmp_path / "receipts_under",
    )
    cutoff = "2025-10-31T23:59:59Z"

    calc_before = statement_service.generate_statement(2, cutoff)
    assert calc_before.i_double_prime_eur < Decimal("0")

    result = exit_service.settle_associate_now(2, cutoff, calculations=calc_before)

    assert result.entry_type == "DEPOSIT"
    assert result.amount_eur > Decimal("0")
    assert result.receipt.exit_payout_after_eur == Decimal("0.00")

    with connect() as check_conn:
        row = check_conn.execute(
            "SELECT COUNT(*) AS cnt FROM ledger_entries WHERE note LIKE ?",
            (f"{SETTLEMENT_NOTE_PREFIX}%",),
        ).fetchone()
        assert row["cnt"] == 1


def test_exit_settlement_flow_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = _prepare_db(tmp_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _seed_overholding_dataset(conn, associate_id=3)
    conn.close()

    connect = _connect_factory(db_path)
    monkeypatch.setattr("src.services.statement_service.get_db_connection", connect)
    monkeypatch.setattr("src.services.funding_transaction_service.get_db_connection", connect)

    statement_service = StatementService()
    exit_service = ExitSettlementService(
        statement_service=statement_service,
        receipt_root=tmp_path / "receipts_idempotent",
    )
    cutoff = "2025-10-31T23:59:59Z"

    calc_before = statement_service.generate_statement(3, cutoff)
    first_result = exit_service.settle_associate_now(3, cutoff, calculations=calc_before)
    second_result = exit_service.settle_associate_now(
        3, cutoff, calculations=first_result.updated_calculations
    )

    assert first_result.was_posted is True
    assert second_result.was_posted is False

    with connect() as check_conn:
        count = check_conn.execute(
            "SELECT COUNT(*) AS cnt FROM ledger_entries WHERE note LIKE ?",
            (f"{SETTLEMENT_NOTE_PREFIX}%",),
        ).fetchone()
        assert count["cnt"] == 1
