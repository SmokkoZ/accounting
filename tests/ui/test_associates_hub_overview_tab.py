from __future__ import annotations

from decimal import Decimal
import importlib.util
from pathlib import Path
import sys
from unittest.mock import Mock

from streamlit.testing.v1 import AppTest

from src.repositories.associate_hub_repository import (
    AssociateMetrics,
    BookmakerSummary,
)

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_overview_tab_quick_actions_render_without_telegram_panels():
    """Ensure Overview tab surfaces quick actions and omits Telegram funding panels."""

    def app():
        from decimal import Decimal as _Decimal
        import importlib.util as _importlib_util
        from pathlib import Path as _Path
        import sys as _sys
        from unittest.mock import Mock as _Mock

        from src.repositories.associate_hub_repository import (
            AssociateMetrics as _AssociateMetrics,
            BookmakerSummary as _BookmakerSummary,
        )

        module_path = _Path("src/ui/pages/7_associates_hub.py")
        spec = _importlib_util.spec_from_file_location(
            "associates_hub_overview_test", module_path
        )
        page = _importlib_util.module_from_spec(spec)
        assert spec.loader is not None
        _sys.modules.setdefault("xlsxwriter", _Mock())
        _sys.modules[spec.name] = page
        spec.loader.exec_module(page)

        class FakeRepository:
            def __init__(self) -> None:
                self._associates = [
                    _AssociateMetrics(
                        associate_id=1,
                        associate_alias="Alpha",
                        home_currency="EUR",
                        is_admin=True,
                        is_active=True,
                        telegram_chat_id="-100",
                        bookmaker_count=2,
                        active_bookmaker_count=1,
                        net_deposits_eur=_Decimal("1000.00"),
                        should_hold_eur=_Decimal("950.00"),
                        fair_share_eur=_Decimal("50.00"),
                        current_holding_eur=_Decimal("960.00"),
                        balance_eur=_Decimal("960.00"),
                        pending_balance_eur=_Decimal("40.00"),
                        delta_eur=_Decimal("10.00"),
                        last_activity_utc="2025-11-14T10:00:00Z",
                        status="balanced",
                        status_color="#fff",
                        internal_notes="",
                        max_surebet_stake_eur=_Decimal("200.00"),
                        max_bookmaker_exposure_eur=_Decimal("500.00"),
                        preferred_balance_chat_id="-200",
                    )
                ]
                snapshot = _BookmakerSummary(
                    associate_id=1,
                    bookmaker_id=10,
                    bookmaker_name="BookieOne",
                    is_active=True,
                    parsing_profile=None,
                    native_currency="EUR",
                    modeled_balance_eur=_Decimal("300.00"),
                    reported_balance_eur=_Decimal("320.00"),
                    delta_eur=_Decimal("20.00"),
                    last_balance_check_utc="2025-11-14T09:00:00Z",
                    status="balanced",
                    status_icon="ok",
                    status_color="#fff",
                    pending_balance_eur=_Decimal("15.00"),
                    bookmaker_chat_id="-111",
                    coverage_chat_id="-222",
                    region="EU",
                    risk_level="Medium",
                    internal_notes="note",
                )
                self._bookmakers = {1: [snapshot]}

            def list_associates_with_metrics(self, **kwargs):
                return self._associates

            def list_bookmakers_for_associate(self, associate_id: int):
                return self._bookmakers.get(associate_id, [])

            def get_associate_metrics(self, associate_id: int):
                return self._associates[0]

        fake_repo = FakeRepository()
        filter_state = {
            "search": "",
            "admin_filter": [],
            "associate_status_filter": [],
            "bookmaker_status_filter": [],
            "currency_filter": [],
            "sort_by": "alias_asc",
            "page": 0,
            "page_size": 25,
        }

        page.AssociateHubRepository = lambda: fake_repo  # type: ignore[attr-defined]
        page.FundingTransactionService = lambda: _Mock(record_transaction=_Mock())  # type: ignore[attr-defined]
        page.BookmakerBalanceService = lambda: object()  # type: ignore[attr-defined]
        page.render_filters = lambda repo, **kwargs: (filter_state, False)  # type: ignore[attr-defined]
        page.render_detail_drawer = lambda *args, **kwargs: None  # type: ignore[attr-defined]

        page.main()  # type: ignore[attr-defined]

    at = AppTest.from_function(app)
    at.run()

    assert not any(
        "Pending Funding (Telegram)" in markdown.value for markdown in at.markdown
    )
