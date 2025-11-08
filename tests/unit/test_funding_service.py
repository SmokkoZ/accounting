"""
Unit tests for FundingService persistent draft storage.
"""

import sqlite3
from decimal import Decimal
from unittest.mock import patch

import pytest

from src.core.schema import create_schema
from src.services.funding_service import FundingError, FundingService


@pytest.fixture
def db_conn():
    """Create an in-memory database with seed data."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    conn.execute(
        """
        INSERT INTO associates (id, display_alias, home_currency, is_active, is_admin)
        VALUES (1, 'Alice', 'EUR', TRUE, FALSE)
        """
    )
    conn.execute(
        """
        INSERT INTO bookmakers (id, associate_id, bookmaker_name, is_active)
        VALUES (10, 1, 'Bet365', TRUE)
        """
    )
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def funding_service(db_conn):
    """Return a FundingService bound to the shared in-memory DB."""
    service = FundingService(db=db_conn)
    yield service
    service.close()


def test_create_funding_draft_persists_data(funding_service, db_conn):
    draft_id = funding_service.create_funding_draft(
        associate_id=1,
        bookmaker_id=10,
        event_type="DEPOSIT",
        amount_native=Decimal("150.00"),
        currency="usd",
        note="telegram:123",
        source="telegram",
        chat_id="123",
    )

    row = db_conn.execute("SELECT * FROM funding_drafts WHERE id = ?", (draft_id,)).fetchone()
    assert row is not None
    assert row["associate_alias"] == "Alice"
    assert row["bookmaker_name"] == "Bet365"
    assert row["native_currency"] == "USD"
    assert row["source"] == "telegram"
    assert row["chat_id"] == "123"


def test_create_funding_draft_invalid_amount(funding_service):
    with pytest.raises(FundingError, match="Amount must be positive"):
        funding_service.create_funding_draft(
            associate_id=1,
            bookmaker_id=10,
            event_type="DEPOSIT",
            amount_native=Decimal("-1"),
            currency="EUR",
        )


def test_get_pending_drafts_returns_sorted_results(funding_service):
    with patch(
        "src.services.funding_service.utc_now_iso",
        side_effect=["2025-01-01T00:00:00Z", "2025-01-01T00:05:00Z"],
    ):
        first = funding_service.create_funding_draft(
            associate_id=1,
            bookmaker_id=10,
            event_type="DEPOSIT",
            amount_native=Decimal("10"),
            currency="EUR",
        )
        second = funding_service.create_funding_draft(
            associate_id=1,
            bookmaker_id=10,
            event_type="WITHDRAWAL",
            amount_native=Decimal("5"),
            currency="EUR",
        )

    drafts = funding_service.get_pending_drafts()
    assert [draft.draft_id for draft in drafts] == [second, first]


def test_get_pending_drafts_filters_by_source(funding_service):
    funding_service.create_funding_draft(
        associate_id=1,
        bookmaker_id=10,
        event_type="DEPOSIT",
        amount_native=Decimal("10"),
        currency="EUR",
        source="manual",
    )
    telegram_draft = funding_service.create_funding_draft(
        associate_id=1,
        bookmaker_id=10,
        event_type="WITHDRAWAL",
        amount_native=Decimal("5"),
        currency="EUR",
        source="telegram",
    )

    drafts = funding_service.get_pending_drafts(source="telegram")
    assert len(drafts) == 1
    assert drafts[0].draft_id == telegram_draft


def test_accept_funding_draft_creates_ledger_and_deletes_record(funding_service, db_conn):
    draft_id = funding_service.create_funding_draft(
        associate_id=1,
        bookmaker_id=10,
        event_type="DEPOSIT",
        amount_native=Decimal("75"),
        currency="EUR",
        note="telegram:321",
    )

    with patch("src.services.funding_service.get_fx_rate", return_value=Decimal("1.0")):
        ledger_id = funding_service.accept_funding_draft(draft_id, created_by="telegram_bot")

    assert ledger_id is not None
    remaining = db_conn.execute("SELECT COUNT(*) FROM funding_drafts").fetchone()[0]
    assert remaining == 0
    ledger_row = db_conn.execute("SELECT note FROM ledger_entries WHERE id = ?", (ledger_id,)).fetchone()
    assert ledger_row is not None
    assert ledger_row["note"] == "telegram:321"


def test_reject_funding_draft_removes_record(funding_service, db_conn):
    draft_id = funding_service.create_funding_draft(
        associate_id=1,
        bookmaker_id=10,
        event_type="WITHDRAWAL",
        amount_native=Decimal("30"),
        currency="EUR",
        note="manual entry",
    )

    funding_service.reject_funding_draft(draft_id)
    remaining = db_conn.execute("SELECT COUNT(*) FROM funding_drafts").fetchone()[0]
    assert remaining == 0
