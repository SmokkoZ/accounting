from __future__ import annotations

from decimal import Decimal

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.exit_settlement_service import ExitSettlementResult, SettlementReceipt
from src.services.statement_service import StatementCalculations, StatementService

from streamlit.testing.v1 import AppTest


def test_statements_settle_section_renders_button():
    def app():
        import importlib as _importlib
        from decimal import Decimal
        from src.services.statement_service import StatementCalculations
        import streamlit as st  # noqa: F401

        calc = StatementCalculations(
            associate_id=99,
            net_deposits_eur=Decimal("500.00"),
            should_hold_eur=Decimal("650.00"),
            current_holding_eur=Decimal("600.00"),
            fair_share_eur=Decimal("150.00"),
            profit_before_payout_eur=Decimal("150.00"),
            raw_profit_eur=Decimal("150.00"),
            delta_eur=Decimal("-50.00"),
            total_deposits_eur=Decimal("800.00"),
            total_withdrawals_eur=Decimal("300.00"),
            bookmakers=[],
            associate_name="Smoke Tester",
            home_currency="EUR",
            cutoff_date="2025-10-31T23:59:59Z",
            generated_at="2025-11-01T00:00:00Z",
        )
        page = _importlib.import_module("src.ui.pages.6_statements")
        page.render_settle_associate_section(calc)

    at = AppTest.from_function(app)
    at.run()
    labels = [button.label for button in at.button]
    assert any("Settle Associate Now" in label for label in labels)


def test_operations_exit_controls_render_button():
    def app():
        import importlib as _importlib
        import streamlit as st  # noqa: F401

        drawer = _importlib.import_module("src.ui.components.associate_hub.drawer")
        drawer.render_exit_settlement_controls(
            {"id": 77, "display_alias": "Ops Tester", "home_currency": "EUR"},
        )

    at = AppTest.from_function(app)
    at.run()
    labels = [button.label for button in at.button]
    assert any("Settle Associate Now" in label for label in labels)


def test_settlement_success_shows_receipt_preview():
    def app():
        import importlib as _importlib
        from decimal import Decimal
        from src.services.exit_settlement_service import ExitSettlementResult, SettlementReceipt
        from src.services.statement_service import StatementCalculations, StatementService

        calc = StatementCalculations(
            associate_id=99,
            net_deposits_eur=Decimal("500.00"),
            should_hold_eur=Decimal("650.00"),
            current_holding_eur=Decimal("600.00"),
            fair_share_eur=Decimal("150.00"),
            profit_before_payout_eur=Decimal("150.00"),
            raw_profit_eur=Decimal("150.00"),
            delta_eur=Decimal("-50.00"),
            total_deposits_eur=Decimal("800.00"),
            total_withdrawals_eur=Decimal("300.00"),
            bookmakers=[],
            associate_name="Smoke Tester",
            home_currency="EUR",
            cutoff_date="2025-10-31T23:59:59Z",
            generated_at="2025-11-01T00:00:00Z",
        )

        class FakeService:
            def __init__(self) -> None:
                self.statement_service = StatementService()

            def settle_associate_now(
                self,
                associate_id: int,
                cutoff_date: str,
                *,
                calculations: StatementCalculations | None = None,
                created_by: str = "test",
            ) -> ExitSettlementResult:
                receipt = SettlementReceipt(
                    associate_id=calc.associate_id,
                    associate_alias=calc.associate_name,
                    cutoff_utc=calc.cutoff_date,
                    entry_id=1,
                    entry_type="WITHDRAWAL",
                    amount_eur=Decimal("50.00"),
                    imbalance_before_eur=Decimal("50.00"),
                    imbalance_after_eur=Decimal("0.00"),
                    exit_payout_after_eur=Decimal("0.00"),
                    note="Test settlement",
                    generated_at="2025-11-13T00:00:00Z",
                    version="YF-v1",
                    markdown="Receipt content",
                    file_path=None,
                )
                return ExitSettlementResult(
                    entry_id=receipt.entry_id,
                    entry_type=receipt.entry_type,
                    amount_eur=receipt.amount_eur,
                    delta_before=receipt.imbalance_before_eur,
                    delta_after=receipt.imbalance_after_eur,
                    note=receipt.note,
                    was_posted=True,
                    updated_calculations=calc,
                    receipt=receipt,
                )

        page = _importlib.import_module("src.ui.pages.6_statements")
        page.render_settle_associate_section(calc, exit_service=FakeService())

    at = AppTest.from_function(app)
    at.session_state["settle_confirm_99"] = True
    at.session_state["settle_associate_now_99"] = True
    at.run()

    assert any("Receipt Preview" in exp.label for exp in at.expander)
    labels = [button.label for button in at.button]
    assert any(":material/refresh: Refresh statement view" in label for label in labels)
