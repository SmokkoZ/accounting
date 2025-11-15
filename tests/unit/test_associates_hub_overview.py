from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest
from unittest.mock import Mock

from src.repositories.associate_hub_repository import AssociateMetrics

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MODULE_PATH = Path("src/ui/pages/7_associates_hub.py")
SPEC = importlib.util.spec_from_file_location("associates_hub_for_tests", MODULE_PATH)
PAGE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules.setdefault("xlsxwriter", Mock())
sys.modules[SPEC.name] = PAGE
SPEC.loader.exec_module(PAGE)


class DummyFundingService:
    def __init__(self) -> None:
        self.recorded = []

    def record_transaction(self, transaction):
        self.recorded.append(transaction)
        return 812


class DummyRepository:
    def __init__(self, metrics: AssociateMetrics) -> None:
        self._metrics = metrics

    def get_associate_metrics(self, associate_id: int):
        return self._metrics


def _sample_metrics() -> AssociateMetrics:
    from decimal import Decimal

    return AssociateMetrics(
        associate_id=1,
        associate_alias="Alpha",
        home_currency="EUR",
        is_admin=True,
        is_active=True,
        telegram_chat_id=None,
        bookmaker_count=1,
        active_bookmaker_count=1,
        net_deposits_eur=Decimal("10.00"),
        should_hold_eur=Decimal("9.00"),
        fair_share_eur=Decimal("1.00"),
        current_holding_eur=Decimal("11.00"),
        balance_eur=Decimal("11.00"),
        pending_balance_eur=Decimal("0.50"),
        delta_eur=Decimal("2.00"),
        last_activity_utc="2025-01-01T00:00:00Z",
        status="balanced",
        status_color="#fff",
        internal_notes=None,
        max_surebet_stake_eur=None,
        max_bookmaker_exposure_eur=None,
        preferred_balance_chat_id=None,
    )


def test_submit_overview_funding_transaction_records_deposit():
    metrics = _sample_metrics()
    repo = DummyRepository(metrics)
    service = DummyFundingService()

    ledger_id, refreshed = PAGE.submit_overview_funding_transaction(
        funding_service=service,
        repository=repo,
        associate_id=1,
        action="deposit",
        amount_value="250.50",
        currency_value="EUR",
        bookmaker_id=None,
        note_value="Top-up",
        operator_name="tester@example.com",
    )

    assert ledger_id == "812"
    assert refreshed is metrics
    assert service.recorded, "Expected a funding transaction to be recorded"
    recorded = service.recorded[0]
    assert recorded.transaction_type == "DEPOSIT"
    assert str(recorded.amount_native) == "250.50"
    assert recorded.native_currency == "EUR"
    assert recorded.bookmaker_id is None
    assert recorded.note == "Top-up"


@pytest.mark.parametrize(
    "amount,currency,error_text",
    [
        ("", "EUR", "Amount is required."),
        ("-1", "EUR", "Amount must be positive."),
        ("25", "", "Currency is required."),
        ("25", "XYZ", "XYZ is not a supported currency."),
    ],
)
def test_submit_overview_funding_transaction_validates_inputs(amount, currency, error_text):
    service = DummyFundingService()
    repo = DummyRepository(_sample_metrics())
    with pytest.raises(PAGE.FundingDialogValidationError) as exc:
        PAGE.submit_overview_funding_transaction(
            funding_service=service,
            repository=repo,
            associate_id=1,
            action="deposit",
            amount_value=amount,
            currency_value=currency,
            bookmaker_id=None,
            note_value="",
            operator_name="tester",
        )
    assert error_text in str(exc.value)
