"""
Unit tests for BalanceHistoryService.
"""

from __future__ import annotations

import io
import sqlite3
from decimal import Decimal

from openpyxl import load_workbook
import pytest

from src.core.schema import create_schema
from src.services.balance_history_service import BalanceHistoryService


@pytest.fixture()
def db_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    create_schema(conn)

    conn.executescript(
        """
        INSERT INTO associates (id, display_alias, home_currency, is_admin)
        VALUES (1, 'Alpha', 'EUR', 0);

        INSERT INTO bookmakers (id, associate_id, bookmaker_name, is_active)
        VALUES (10, 1, 'Bookie One', 1);

        INSERT INTO ledger_entries (
            type, associate_id, bookmaker_id, amount_native, native_currency,
            fx_rate_snapshot, amount_eur, settlement_state, principal_returned_eur,
            per_surebet_share_eur, created_at_utc
        ) VALUES
            ('DEPOSIT', 1, 10, '500.00', 'EUR', '1.0', '500.00', NULL, NULL, NULL, '2025-11-01T08:00:00Z'),
            ('WITHDRAWAL', 1, 10, '-100.00', 'EUR', '1.0', '-100.00', NULL, NULL, NULL, '2025-11-03T09:00:00Z'),
            ('BET_RESULT', 1, 10, '0.00', 'EUR', '1.0', '0.00', 'WON', NULL, '50.00', '2025-11-05T10:00:00Z'),
            ('DEPOSIT', 1, 10, '50.00', 'EUR', '1.0', '50.00', NULL, NULL, NULL, '2025-11-09T11:00:00Z');

        INSERT INTO bookmaker_balance_checks (
            associate_id, bookmaker_id, balance_native, native_currency,
            balance_eur, fx_rate_used, check_date_utc, note
        ) VALUES
            (1, 10, '420.00', 'EUR', '420.00', '1.0', '2025-11-07T12:00:00Z', 'Weekly check'),
            (1, 10, '460.00', 'EUR', '460.00', '1.0', '2025-11-10T13:30:00Z', 'Follow-up check');
        """
    )
    conn.commit()
    try:
        yield conn
    finally:
        conn.close()


def test_fetch_history_calculates_nd_yf_and_imbalance(
    db_conn: sqlite3.Connection,
) -> None:
    service = BalanceHistoryService(db_conn)
    result = service.fetch_history(
        associate_id=1,
        bookmaker_id=10,
        start_date="2025-11-01",
        end_date="2025-11-30",
        limit=10,
    )

    assert result.total_count == 2
    assert len(result.entries) == 2

    latest = result.entries[0]
    assert latest.balance_eur == Decimal("460.00")
    assert latest.net_deposits_eur == Decimal("450.00")
    assert latest.fair_share_eur == Decimal("50.00")
    assert latest.yf_eur == Decimal("500.00")
    assert latest.imbalance_eur == Decimal("-40.00")
    assert latest.ledger_balance_eur == Decimal("450.00")

    earlier = result.entries[1]
    assert earlier.balance_eur == Decimal("420.00")
    assert earlier.net_deposits_eur == Decimal("400.00")
    assert earlier.yf_eur == Decimal("450.00")
    assert earlier.imbalance_eur == Decimal("-30.00")

    service.close()


def test_fetch_history_respects_date_window(db_conn: sqlite3.Connection) -> None:
    service = BalanceHistoryService(db_conn)
    result = service.fetch_history(
        associate_id=1,
        bookmaker_id=10,
        start_date="2025-11-10",
        end_date="2025-11-10",
    )
    assert result.total_count == 1
    assert len(result.entries) == 1
    assert result.entries[0].balance_eur == Decimal("460.00")
    service.close()


def test_export_history_generates_styled_workbook(db_conn: sqlite3.Connection) -> None:
    service = BalanceHistoryService(db_conn)
    export = service.export_history(
        associate_id=1,
        bookmaker_id=10,
        start_date="2025-11-01",
        end_date="2025-11-30",
        associate_label="Alpha (ID 1)",
        bookmaker_label="Bookie One (ID 10)",
    )
    assert export.row_count == 2
    assert export.file_name.endswith("_history.xlsx")
    workbook = load_workbook(io.BytesIO(export.content), data_only=True)
    sheet = workbook["Balance History"]
    assert sheet["B1"].value == "Alpha (ID 1)"
    assert sheet["B2"].value == "Bookie One (ID 10)"
    # Data starts on row 5; verify a cell value
    assert sheet["A5"].value == "Timestamp (UTC)"
    assert str(sheet["A6"].value).startswith("2025-11")
    # Ensure ND values written numerically on first data row
    assert isinstance(sheet["D6"].value, (float, int))
    service.close()
