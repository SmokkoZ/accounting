from __future__ import annotations

from decimal import Decimal

from streamlit.testing.v1 import AppTest

from src.services.statement_service import StatementCalculations, StatementService
from src.ui.utils.identity_copy import identity_caption_text, identity_label, identity_tooltip


def _render_statement_header() -> None:
    import importlib as _importlib  # noqa: WPS433
    import streamlit as st  # noqa: F401
    from decimal import Decimal  # noqa: WPS433
    from src.services.statement_service import StatementCalculations  # noqa: WPS433

    calc = StatementCalculations(
        associate_id=42,
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
        associate_name="Identity UI Test",
        home_currency="EUR",
        cutoff_date="2025-10-31T23:59:59Z",
        generated_at="2025-11-01T00:00:00Z",
    )
    page = _importlib.import_module("src.ui.pages.6_statements")
    page.render_statement_header(calc)


def _render_partner_section() -> None:
    import importlib as _importlib  # noqa: WPS433
    import streamlit as st  # noqa: F401
    from decimal import Decimal  # noqa: WPS433
    from src.services.statement_service import (  # noqa: WPS433
        StatementCalculations,
        StatementService,
    )

    calc = StatementCalculations(
        associate_id=42,
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
        associate_name="Identity UI Test",
        home_currency="EUR",
        cutoff_date="2025-10-31T23:59:59Z",
        generated_at="2025-11-01T00:00:00Z",
    )
    service = StatementService()
    partner = service.format_partner_facing_section(calc)
    page = _importlib.import_module("src.ui.pages.6_statements")
    page.render_partner_facing_section(partner)


def test_statement_header_identity_metrics_render_consistent_copy() -> None:
    at = AppTest.from_function(_render_statement_header)
    at.run()
    labels = [metric.label for metric in at.metric]
    assert identity_label() in labels
    help_map = {metric.label: metric.help for metric in at.metric}
    assert help_map.get(identity_label()) == identity_tooltip()


def test_partner_section_captions_include_identity_formula() -> None:
    at = AppTest.from_function(_render_partner_section)
    at.run()
    labels = [metric.label for metric in at.metric]
    assert identity_label() in labels
    caption_blob = " ".join(caption.value for caption in at.caption)
    assert identity_caption_text() in caption_blob
