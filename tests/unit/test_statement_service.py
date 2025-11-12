"""
Focused unit tests for ``StatementService`` calculations.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import sqlite3
from unittest.mock import MagicMock

import pytest

from src.services.statement_service import (
    InternalSection,
    PartnerFacingSection,
    StatementCalculations,
    StatementService,
    BookmakerStatementRow,
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
        ),
    )
    monkeypatch.setattr(
        StatementService,
        "_calculate_should_hold",
        lambda self, conn, associate_id, cutoff: Decimal("1250.00"),
    )
    monkeypatch.setattr(
        StatementService,
        "_calculate_current_holding",
        lambda self, conn, associate_id, cutoff: Decimal("1200.00"),
    )
    monkeypatch.setattr(
        StatementService,
        "_calculate_profit_before_payout",
        lambda self, conn, associate_id, cutoff: Decimal("300.00"),
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
    assert calc.profit_before_payout_eur == Decimal("300.00")
    assert calc.raw_profit_eur == Decimal("250.00")
    assert calc.delta_eur == Decimal("-50.00")
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
        profit_before_payout_eur=Decimal("275.00"),
        raw_profit_eur=Decimal("150.00"),
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
    assert partner.total_deposits_eur == Decimal("800.00")
    assert partner.profit_before_payout_eur == Decimal("275.00")
    assert partner.bookmakers[0].bookmaker_name == "Bookie Test"


def test_internal_section_detects_over_and_short_states(service: StatementService):
    positive = service.format_internal_section(
        StatementCalculations(
            associate_id=1,
            net_deposits_eur=Decimal("0"),
            should_hold_eur=Decimal("0"),
            current_holding_eur=Decimal("100"),
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

    negative = service.format_internal_section(
        StatementCalculations(
            associate_id=1,
            net_deposits_eur=Decimal("0"),
            should_hold_eur=Decimal("100"),
            current_holding_eur=Decimal("50"),
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


def test_validate_cutoff_date_future(monkeypatch: pytest.MonkeyPatch):
    service = StatementService()
    future = datetime.now(timezone.utc).replace(year=datetime.now(timezone.utc).year + 1)
    future_iso = future.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert service.validate_cutoff_date(future_iso) is False
