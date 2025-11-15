"""
Focused unit tests for ``StatementService`` calculations.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO
import sqlite3
from unittest.mock import MagicMock

from openpyxl import load_workbook
import pytest

from src.services.statement_service import (
    InternalSection,
    PartnerFacingSection,
    StatementCalculations,
    StatementService,
    BookmakerStatementRow,
)
from src.services.settlement_constants import (
    SETTLEMENT_MODEL_FOOTNOTE,
    SETTLEMENT_MODEL_VERSION,
)


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> StatementService:
    dummy_conn = MagicMock()
    monkeypatch.setattr("src.services.statement_service.get_db_connection", lambda: dummy_conn)
    monkeypatch.setattr(dummy_conn, "close", MagicMock())

    monkeypatch.setattr(
        StatementService,
        "_get_associate_details",
        lambda self, conn, associate_id: ("Demo Associate", "EUR"),
    )
    monkeypatch.setattr(
        StatementService,
        "_calculate_funding_totals",
        lambda self, conn, associate_id, cutoff: (
            Decimal("1000.00"),
            Decimal("0.00"),
            Decimal("1000.00"),
        ),
    )
    monkeypatch.setattr(
        StatementService,
        "_calculate_current_holding",
        lambda self, conn, associate_id, cutoff: Decimal("1200.00"),
    )
    monkeypatch.setattr(
        StatementService,
        "_calculate_should_hold",
        lambda self, conn, associate_id, cutoff: Decimal("1250.00"),
    )
    monkeypatch.setattr(
        StatementService,
        "_calculate_profit_before_payout",
        lambda self, conn, associate_id, cutoff: Decimal("250.00"),
    )
    monkeypatch.setattr(
        StatementService,
        "_calculate_bookmaker_breakdown",
        lambda self, conn, associate_id, cutoff: [
            BookmakerStatementRow(
                bookmaker_name="Bookie A",
                balance_eur=Decimal("500.00"),
                deposits_eur=Decimal("400.00"),
                withdrawals_eur=Decimal("100.00"),
                balance_native=Decimal("500.00"),
                native_currency="EUR",
            )
        ],
    )
    return StatementService()


def test_generate_statement_returns_expected_delta(service: StatementService):
    cutoff = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    calc = service.generate_statement(associate_id=7, cutoff_date=cutoff)

    assert calc.associate_name == "Demo Associate"
    assert calc.profit_before_payout_eur == Decimal("250.00")
    assert calc.raw_profit_eur == Decimal("250.00")
    assert calc.delta_eur == Decimal("-50.00")
    assert calc.should_hold_eur == calc.net_deposits_eur + calc.fs_eur
    assert calc.total_deposits_eur == Decimal("1000.00")
    assert calc.total_withdrawals_eur == Decimal("0.00")
    assert len(calc.bookmakers) == 1
    assert calc.cutoff_date == cutoff


def test_partner_section_formats_summaries(service: StatementService):
    calc = StatementCalculations(
        associate_id=1,
        net_deposits_eur=Decimal("500.00"),
        should_hold_eur=Decimal("650.00"),
        current_holding_eur=Decimal("640.00"),
        fair_share_eur=Decimal("150.00"),
        profit_before_payout_eur=Decimal("150.00"),
        raw_profit_eur=Decimal("-350.00"),
        delta_eur=Decimal("-10.00"),
        total_deposits_eur=Decimal("800.00"),
        total_withdrawals_eur=Decimal("300.00"),
        bookmakers=[
            BookmakerStatementRow(
                bookmaker_name="Bookie Test",
                balance_eur=Decimal("640.00"),
                deposits_eur=Decimal("500.00"),
                withdrawals_eur=Decimal("100.00"),
                balance_native=Decimal("640.00"),
                native_currency="EUR",
            )
        ],
        associate_name="Demo",
        home_currency="EUR",
        cutoff_date="2025-10-31T23:59:59Z",
        generated_at="2025-11-07T00:00:00Z",
    )

    partner = service.format_partner_facing_section(calc)
    assert isinstance(partner, PartnerFacingSection)
    assert partner.net_deposits_eur == Decimal("500.00")
    assert partner.fair_share_eur == Decimal("150.00")
    assert partner.yield_funds_eur == Decimal("650.00")
    assert partner.total_balance_eur == Decimal("640.00")
    assert partner.imbalance_eur == Decimal("-10.00")
    assert partner.exit_payout_eur == Decimal("10.00")
    assert partner.total_deposits_eur == Decimal("800.00")
    assert partner.profit_before_payout_eur == Decimal("150.00")
    assert partner.bookmakers[0].bookmaker_name == "Bookie Test"


def test_internal_section_detects_over_and_short_states(service: StatementService):
    positive = service.format_internal_section(
        StatementCalculations(
            associate_id=1,
            net_deposits_eur=Decimal("0"),
            should_hold_eur=Decimal("0"),
            current_holding_eur=Decimal("100"),
            fair_share_eur=Decimal("25"),
            profit_before_payout_eur=Decimal("25"),
            raw_profit_eur=Decimal("0"),
            delta_eur=Decimal("100"),
            total_deposits_eur=Decimal("0"),
            total_withdrawals_eur=Decimal("0"),
            bookmakers=[],
            associate_name="",
             home_currency="EUR",
            cutoff_date="",
            generated_at="",
        )
    )
    assert isinstance(positive, InternalSection)
    assert "more" in positive.reconciliation_delta.lower()
    assert positive.total_balance_eur == Decimal("100")
    assert positive.exit_payout_eur == Decimal("-75")

    negative = service.format_internal_section(
        StatementCalculations(
            associate_id=1,
            net_deposits_eur=Decimal("0"),
            should_hold_eur=Decimal("100"),
            current_holding_eur=Decimal("50"),
            fair_share_eur=Decimal("-40"),
            profit_before_payout_eur=Decimal("-40"),
            raw_profit_eur=Decimal("-100"),
            delta_eur=Decimal("-50"),
            total_deposits_eur=Decimal("0"),
            total_withdrawals_eur=Decimal("0"),
            bookmakers=[],
            associate_name="",
            home_currency="EUR",
            cutoff_date="",
            generated_at="",
        )
    )
    assert "short" in negative.reconciliation_delta.lower()
    assert negative.exit_payout_eur == Decimal("-90")


def test_calculate_profit_before_payout_handles_signed_shares():
    service = StatementService()
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE ledger_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            associate_id INTEGER,
            type TEXT,
            per_surebet_share_eur TEXT,
            created_at_utc TEXT
        )
        """
    )
    rows = [
        (1, "BET_RESULT", "10.00", "2025-10-01T10:00:00Z"),
        (1, "BET_RESULT", "-4.50", "2025-10-05T10:00:00Z"),
        (1, "BET_RESULT", "0.00", "2025-10-07T10:00:00Z"),  # VOID seat share
        (1, "BET_RESULT", "3.25", "2025-11-01T10:00:00Z"),  # beyond cutoff
        (2, "BET_RESULT", "999.00", "2025-10-01T10:00:00Z"),  # different associate
        (1, "DEPOSIT", "18.00", "2025-10-02T10:00:00Z"),  # ignored type
        (1, "BET_RESULT", None, "2025-10-03T10:00:00Z"),  # null share
    ]
    conn.executemany(
        "INSERT INTO ledger_entries (associate_id, type, per_surebet_share_eur, created_at_utc) VALUES (?, ?, ?, ?)",
        rows,
    )

    result = service._calculate_profit_before_payout(
        conn, associate_id=1, cutoff_date="2025-10-31T23:59:59Z"
    )

    assert result == Decimal("5.50")
    conn.close()


def test_calculate_funding_totals_preserves_signed_withdrawals():
    service = StatementService()
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE ledger_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            associate_id INTEGER,
            type TEXT,
            amount_eur TEXT,
            created_at_utc TEXT,
            note TEXT
        )
        """
    )
    conn.executemany(
        """
        INSERT INTO ledger_entries (associate_id, type, amount_eur, created_at_utc)
        VALUES (?, ?, ?, ?)
        """,
        [
            (1, "DEPOSIT", "1000.00", "2025-10-01T10:00:00Z"),
            (1, "WITHDRAWAL", "-200.00", "2025-10-05T12:00:00Z"),
            (2, "WITHDRAWAL", "-999.00", "2025-10-07T12:00:00Z"),  # different associate
            (1, "WITHDRAWAL", "-50.00", "2025-11-15T12:00:00Z"),   # beyond cutoff
        ],
    )

    totals = service._calculate_funding_totals(
        conn, associate_id=1, cutoff_date="2025-10-31T23:59:59Z"
    )

    total_deposits, total_withdrawals, net_deposits = totals
    assert total_deposits == Decimal("1000.00")
    assert total_withdrawals == Decimal("200.00")
    assert net_deposits == Decimal("800.00")
    conn.close()


def test_export_statement_excel_creates_formatted_layout(
    monkeypatch: pytest.MonkeyPatch,
):
    calc = StatementCalculations(
        associate_id=2,
        net_deposits_eur=Decimal("500.00"),
        should_hold_eur=Decimal("650.00"),
        current_holding_eur=Decimal("2168.91"),
        fair_share_eur=Decimal("150.00"),
        profit_before_payout_eur=Decimal("150.00"),
        raw_profit_eur=Decimal("120.00"),
        delta_eur=Decimal("1518.91"),
        total_deposits_eur=Decimal("700.00"),
        total_withdrawals_eur=Decimal("200.00"),
        bookmakers=[
            BookmakerStatementRow(
                bookmaker_name="Ladbrokes",
                balance_eur=Decimal("-99.94"),
                deposits_eur=Decimal("0.00"),
                withdrawals_eur=Decimal("0.00"),
                balance_native=Decimal("-171.00"),
                native_currency="AUD",
            ),
            BookmakerStatementRow(
                bookmaker_name="Sportsbet",
                balance_eur=Decimal("2268.85"),
                deposits_eur=Decimal("0.00"),
                withdrawals_eur=Decimal("0.00"),
                balance_native=Decimal("4009.00"),
                native_currency="AUD",
            ),
        ],
        associate_name="Demo Associate",
        home_currency="EUR",
        cutoff_date="2025-10-31T23:59:59Z",
        generated_at="2025-11-01T00:00:00Z",
    )
    service = StatementService()
    monkeypatch.setattr(
        "src.services.statement_service.utc_now_iso",
        lambda: "2025-11-15T00:00:00Z",
    )
    monkeypatch.setattr(
        StatementService,
        "_calculate_multibook_delta",
        lambda self, associate_id, cutoff_date: Decimal("25.00"),
    )
    payload = service.export_statement_excel(
        associate_id=calc.associate_id,
        cutoff_date=calc.cutoff_date,
        calculations=calc,
    )
    assert payload.filename == "demo-associate_EUR_31-10-2025_statement.xlsx"

    workbook = load_workbook(BytesIO(payload.content), data_only=True)
    sheet = workbook["Statement"]

    assert sheet["A1"].value == "Associate:"
    assert sheet["B1"].value == "Demo Associate"
    assert sheet["A2"].value == "As of (UTC):"
    assert sheet["B2"].value == calc.cutoff_date
    assert sheet["A3"].value == "Generated:"
    assert sheet["B3"].value == "2025-11-15T00:00:00Z"

    assert sheet["A5"].value == "Bookmaker"
    assert sheet["B6"].value == pytest.approx(-171.0)
    assert sheet["D6"].value == pytest.approx(-99.94)
    assert sheet["A6"].value == "Ladbrokes"
    assert sheet["A7"].value == "Sportsbet"

    assert sheet["A8"].value == "Total"
    assert sheet["B8"].value == pytest.approx(3838.0)
    assert sheet["D8"].value == pytest.approx(2168.91)

    assert sheet["A10"].value == "Summary (All amounts in EUR)"
    assert sheet["A11"].value == "Total Balance"
    assert sheet["B11"].value == pytest.approx(3838.0)
    assert sheet["C11"].value == "EUR"
    assert sheet["D11"].value == pytest.approx(2168.91)
    assert sheet["A12"].value == "Net Deposits (ND)"
    assert sheet["B12"].value == pytest.approx(884.78, rel=1e-3)
    assert sheet["C12"].value == "EUR"
    assert sheet["D12"].value == pytest.approx(500.0)
    assert sheet["A13"].value == "Imbalance (Total Balance − Yield Funds)"
    assert sheet["B13"].value == pytest.approx(2687.79, rel=1e-3)
    assert sheet["C13"].value == "EUR"
    assert sheet["D13"].value == pytest.approx(1518.91)
    assert sheet["A14"].value == "Fair Share (FS)"
    assert sheet["B14"].value == pytest.approx(265.43, rel=1e-3)
    assert sheet["C14"].value == "EUR"
    assert sheet["D14"].value == pytest.approx(150.0)


def test_build_roi_csv_rows_include_version_and_footnote(service: StatementService):
    calc = service.generate_statement(
        associate_id=7, cutoff_date=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    roi_rows = [
        {
            "surebet_id": 42,
            "settled_at_utc": "2025-10-31T00:00:00Z",
            "associate_stake": Decimal("10.00"),
            "associate_profit": Decimal("2.50"),
            "group_stake": Decimal("10.00"),
            "group_profit": Decimal("2.50"),
        }
    ]
    rows = service._build_roi_csv_rows(
        calc,
        export_time="2025-11-15T00:00:00Z",
        roi_rows=roi_rows,
    )
    assert ["Identity Version", SETTLEMENT_MODEL_VERSION] in rows
    assert rows[-1] == ["Footnote", SETTLEMENT_MODEL_FOOTNOTE]


def test_validate_cutoff_date_future(monkeypatch: pytest.MonkeyPatch):
    service = StatementService()
    future = datetime.now(timezone.utc).replace(year=datetime.now(timezone.utc).year + 1)
    future_iso = future.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert service.validate_cutoff_date(future_iso) is False
