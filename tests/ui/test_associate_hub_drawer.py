from __future__ import annotations

from decimal import Decimal
from unittest.mock import Mock

from streamlit.testing.v1 import AppTest

from src.services.bookmaker_balance_service import BookmakerBalance


def test_render_bookmaker_balance_summary_hides_telegram_controls():
    """Show that the new hub context hides Telegram-only actions."""

    def app():
        import streamlit as st
        from src.ui.components.associate_hub import drawer

        st.session_state.clear()
        associate = {"id": 1, "display_alias": "Alpha"}
        bookmaker = BookmakerBalance(
            associate_id=1,
            associate_alias="Alpha",
            bookmaker_id=10,
            bookmaker_name="Bookie One",
            modeled_balance_eur=Decimal("100.00"),
            modeled_balance_native=None,
            reported_balance_eur=Decimal("120.00"),
            reported_balance_native=None,
            native_currency="EUR",
            difference_eur=Decimal("20.00"),
            difference_native=None,
            status="balanced",
            status_icon="ok",
            status_color="#fff",
            status_label="Balanced",
            last_checked_at_utc="2025-11-15T10:00:00Z",
            fx_rate_used=Decimal("1.0"),
            is_bookmaker_active=True,
        )
        drawer.render_bookmaker_balance_summary(
            balance_service=Mock(),
            associate=associate,
            bookmaker=bookmaker,
            show_telegram_actions=False,
        )

    at = AppTest.from_function(app)
    at.run()

    assert all("Send balance to Telegram" not in button.label for button in at.button)


def test_transactions_tab_respects_permission_gate():
    """Funding forms stay locked until the permission toggle is enabled."""

    def app():
        import streamlit as st
        from src.ui.components.associate_hub import drawer
        from unittest.mock import Mock

        st.session_state.clear()
        st.session_state["associates_hub_funding_permission"] = False

        class FakeFundingService:
            def __init__(self) -> None:
                self.db = Mock()
                self.db.execute.return_value.fetchall.return_value = []

            def get_transaction_history(self, **kwargs):
                return []

        drawer.render_transactions_tab(
            funding_service=FakeFundingService(),
            associate={"id": 1, "home_currency": "EUR", "display_alias": "Alpha"},
            bookmaker_id=None,
        )

    at = AppTest.from_function(app)
    at.run()

    assert any(
        "Funding actions are read-only" in info.value for info in at.info
    )
