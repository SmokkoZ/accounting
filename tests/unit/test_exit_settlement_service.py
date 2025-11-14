from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import List

import pytest

from src.services.exit_settlement_service import ExitSettlementService
from src.services.statement_service import StatementCalculations


def _build_calc(
    *,
    associate_id: int = 7,
    net_deposits: str = "500.00",
    fair_share: str = "0.00",
    current_holding: str = "500.00",
    total_deposits: str = "500.00",
    total_withdrawals: str = "0.00",
    associate_name: str = "Demo Associate",
    cutoff: str = "2025-10-31T23:59:59Z",
) -> StatementCalculations:
    net = Decimal(net_deposits)
    fs = Decimal(fair_share)
    tb = Decimal(current_holding)
    should_hold = net + fs
    delta = tb - should_hold
    return StatementCalculations(
        associate_id=associate_id,
        net_deposits_eur=net,
        should_hold_eur=should_hold,
        current_holding_eur=tb,
        fair_share_eur=fs,
        profit_before_payout_eur=Decimal("0.00"),
        raw_profit_eur=Decimal("0.00"),
        delta_eur=delta,
        total_deposits_eur=Decimal(total_deposits),
        total_withdrawals_eur=Decimal(total_withdrawals),
        bookmakers=[],
        associate_name=associate_name,
        home_currency="EUR",
        cutoff_date=cutoff,
        generated_at="2025-11-01T00:00:00Z",
    )


class FakeStatementService:
    def __init__(self, snapshots: List[StatementCalculations]) -> None:
        self.snapshots = snapshots
        self.calls: List[tuple[int, str]] = []

    def generate_statement(self, associate_id: int, cutoff_date: str) -> StatementCalculations:
        self.calls.append((associate_id, cutoff_date))
        if not self.snapshots:
            raise AssertionError("No snapshots queued for FakeStatementService")
        return self.snapshots.pop(0)


class DummyFundingTransactionService:
    instances: List["DummyFundingTransactionService"] = []

    def __init__(self) -> None:
        self.recorded: List[tuple] = []
        self.closed = False
        DummyFundingTransactionService.instances.append(self)

    def record_transaction(self, transaction, *, created_at_override=None):
        self.recorded.append((transaction, created_at_override))
        return 1234

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_fakes(monkeypatch: pytest.MonkeyPatch):
    DummyFundingTransactionService.instances.clear()
    monkeypatch.setattr(
        "src.services.exit_settlement_service.FundingTransactionService",
        DummyFundingTransactionService,
    )


def test_settlement_posts_withdrawal_for_positive_delta(tmp_path: Path):
    calc_before = _build_calc(current_holding="650.00")
    calc_after = _build_calc(current_holding="500.00")
    fake_statement = FakeStatementService([calc_after])
    service = ExitSettlementService(
        statement_service=fake_statement,
        receipt_root=tmp_path,
    )

    result = service.settle_associate_now(
        calc_before.associate_id,
        calc_before.cutoff_date,
        calculations=calc_before,
        created_by="pytest",
    )

    assert result.was_posted is True
    assert result.entry_type == "WITHDRAWAL"
    assert result.amount_eur == Decimal("150.00")
    assert result.delta_after == Decimal("0.00")
    funding_instance = DummyFundingTransactionService.instances[-1]
    recorded_txn, override = funding_instance.recorded[0]
    assert recorded_txn.transaction_type == "WITHDRAWAL"
    assert recorded_txn.amount_native == Decimal("150.00")
    assert override == calc_before.cutoff_date
    assert result.receipt.file_path and result.receipt.file_path.exists()
    assert "Exit Settlement Receipt" in result.receipt.markdown


def test_settlement_posts_deposit_for_negative_delta(tmp_path: Path):
    calc_before = _build_calc(fair_share="200.00", current_holding="450.00")
    calc_after = _build_calc(fair_share="200.00", current_holding="700.00")
    fake_statement = FakeStatementService([calc_after])
    service = ExitSettlementService(
        statement_service=fake_statement,
        receipt_root=tmp_path,
    )

    result = service.settle_associate_now(
        calc_before.associate_id,
        calc_before.cutoff_date,
        calculations=calc_before,
        created_by="pytest",
    )

    assert result.entry_type == "DEPOSIT"
    assert result.amount_eur == Decimal("250.00")
    funding_instance = DummyFundingTransactionService.instances[-1]
    recorded_txn, _ = funding_instance.recorded[0]
    assert recorded_txn.transaction_type == "DEPOSIT"
    assert recorded_txn.amount_native == Decimal("250.00")
    assert result.receipt.exit_payout_after_eur == Decimal("0.00")


def test_settlement_is_idempotent_within_tolerance(tmp_path: Path):
    calc_before = _build_calc(current_holding="500.00")
    fake_statement = FakeStatementService([])
    service = ExitSettlementService(
        statement_service=fake_statement,
        receipt_root=tmp_path,
    )

    result = service.settle_associate_now(
        calc_before.associate_id,
        calc_before.cutoff_date,
        calculations=calc_before,
    )

    assert result.was_posted is False
    assert result.amount_eur == Decimal("0.00")
    assert not DummyFundingTransactionService.instances  # no transactions created
