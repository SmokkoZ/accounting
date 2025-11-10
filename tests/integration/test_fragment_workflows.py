import importlib
import sys
import types
from dataclasses import dataclass
from decimal import Decimal

import pytest

from src.ui.helpers import fragments


class SessionStateStub(dict):
    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError as exc:
            raise AttributeError(item) from exc

    def __setattr__(self, key, value):
        self[key] = value


class NoOpContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class PlaceholderStub:
    def __init__(self, root):
        self._root = root

    def download_button(self, *args, **kwargs):
        return None

    def metric(self, *args, **kwargs):
        return None

    def empty(self):
        return self


class ColumnStub:
    def __init__(self, root):
        self._root = root

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def metric(self, *args, **kwargs):
        return self._root.metric(*args, **kwargs)

    def button(self, *args, **kwargs):
        return self._root.button(*args, **kwargs)

    def selectbox(self, *args, **kwargs):
        return self._root.selectbox(*args, **kwargs)

    def multiselect(self, *args, **kwargs):
        return self._root.multiselect(*args, **kwargs)

    def checkbox(self, *args, **kwargs):
        return self._root.checkbox(*args, **kwargs)

    def caption(self, *args, **kwargs):
        return self._root.caption(*args, **kwargs)

    def markdown(self, *args, **kwargs):
        return self._root.markdown(*args, **kwargs)

    def info(self, *args, **kwargs):
        return self._root.info(*args, **kwargs)

    def warning(self, *args, **kwargs):
        return self._root.warning(*args, **kwargs)

    def success(self, *args, **kwargs):
        return self._root.success(*args, **kwargs)

    def error(self, *args, **kwargs):
        return self._root.error(*args, **kwargs)

    def write(self, *args, **kwargs):
        return self._root.write(*args, **kwargs)

    def empty(self):
        return PlaceholderStub(self._root)


class StreamlitPageStub:
    """Simplified Streamlit façade sufficient for fragment workflow tests."""

    def __init__(self):
        self.session_state = SessionStateStub()
        self.checkbox_value = False
        self.toggle_value = False
        self.radio_selection = None
        self.selectbox_selection = None
        self.multiselect_selection = None
        self.button_map = {}
        self.date_input_value = None
        self.checkbox_map = {}

    def as_module(self) -> types.ModuleType:
        module = types.ModuleType("streamlit")
        module.session_state = self.session_state
        for name in (
            "set_page_config",
            "title",
            "caption",
            "markdown",
            "subheader",
            "header",
            "write",
            "info",
            "warning",
            "error",
            "success",
            "metric",
            "columns",
            "checkbox",
            "toggle",
            "selectbox",
            "multiselect",
            "radio",
            "button",
            "spinner",
            "expander",
            "container",
            "empty",
            "rerun",
            "stop",
            "dataframe",
            "code",
        ):
            setattr(module, name, getattr(self, name))

        module.fragment = self.fragment
        module.divider = self.divider
        module.text_input = self.text_input
        module.number_input = self.number_input
        module.date_input = self.date_input
        module.columns = self.columns
        return module

    # Basic UI primitives -------------------------------------------------
    def set_page_config(self, **kwargs):
        return None

    def title(self, *args, **kwargs):
        return None

    def caption(self, *args, **kwargs):
        return None

    def markdown(self, *args, **kwargs):
        return None

    def subheader(self, *args, **kwargs):
        return None

    def header(self, *args, **kwargs):
        return None

    def write(self, *args, **kwargs):
        return None

    def info(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None

    def success(self, *args, **kwargs):
        return None

    def metric(self, *args, **kwargs):
        return None

    def divider(self, *args, **kwargs):
        return None

    def code(self, *args, **kwargs):
        return None

    def dataframe(self, *args, **kwargs):
        return None

    # Layout primitives ---------------------------------------------------
    def columns(self, spec):
        if isinstance(spec, int):
            size = spec
        else:
            size = len(list(spec))
        return [ColumnStub(self) for _ in range(size)]

    def expander(self, *args, **kwargs):
        return NoOpContext()

    def container(self, *args, **kwargs):
        return NoOpContext()

    def empty(self):
        return PlaceholderStub(self)

    def spinner(self, *args, **kwargs):
        return NoOpContext()

    # Inputs ---------------------------------------------------------------
    def checkbox(self, label, *, value=False, key=None, help=None):
        result = self.checkbox_map.get(key, self.checkbox_value)
        if key:
            self.session_state[key] = result
        return result

    def toggle(self, label, *, key=None, value=False, help=None, disabled=False):
        result = self.toggle_value
        if key:
            self.session_state[key] = result
        return result

    def selectbox(self, label, options, index=0, key=None, **kwargs):
        if not options:
            choice = None
        elif self.selectbox_selection is not None:
            choice = self.selectbox_selection
        else:
            choice = options[index]
        if key:
            self.session_state[key] = choice
        return choice

    def multiselect(self, label, options, default=None, key=None, **kwargs):
        selection = self.multiselect_selection
        if selection is None:
            selection = list(default or ([] if options is None else []))
        if key:
            self.session_state[key] = selection
        return selection

    def radio(self, label, options, index=0, key=None, **kwargs):
        selection = self.radio_selection if self.radio_selection is not None else options[index]
        if key:
            self.session_state[key] = selection
        return selection

    def button(self, label, *, key=None, help=None, **kwargs):
        return self.button_map.get(key or label, False)

    def text_input(self, *args, **kwargs):
        return ""

    def number_input(self, *args, **kwargs):
        return 0

    def date_input(self, label, value=None, **kwargs):
        return self.date_input_value or value

    # Control flow ---------------------------------------------------------
    def rerun(self):
        self.session_state["_rerun"] = True

    def stop(self):
        raise RuntimeError("streamlit.stop")

    # Fragment decorator ----------------------------------------------------
    def fragment(self, func=None, *, run_every=None):
        def decorator(callable_obj):
            def wrapper(*args, **kwargs):
                return callable_obj(*args, **kwargs)

            wrapper.__wrapped__ = callable_obj
            wrapper._run_every = run_every
            return wrapper

        if func is None:
            return decorator
        return decorator(func)


class PandasStub(types.ModuleType):
    def __init__(self):
        super().__init__("pandas")

    class DataFrame:
        def __init__(self, data):
            self.data = data

        def to_csv(self, index=False):
            return "metric_0,metric_1\n0,0"


class LoggerStub:
    def info(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None

    def debug(self, *args, **kwargs):
        return None


@pytest.fixture
def streamlit_stub(monkeypatch):
    stub = StreamlitPageStub()
    module = stub.as_module()
    monkeypatch.setitem(sys.modules, "streamlit", module)
    monkeypatch.setattr(fragments, "st", module)
    fragments.feature_flags._compute_feature_matrix.cache_clear()
    return stub


@pytest.fixture
def pandas_stub(monkeypatch):
    stub = PandasStub()
    monkeypatch.setitem(sys.modules, "pandas", stub)
    return stub


def _record_call_fragment(monkeypatch):
    recorded = []

    def capture(name, fn, **kwargs):
        recorded.append({"name": name, "kwargs": kwargs, "fn": fn})
        return None

    monkeypatch.setattr("src.ui.helpers.fragments.call_fragment", capture)
    return recorded


def _reload(module_name: str):
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


class IncomingBetsDB:
    def execute(self, query):
        if "FROM bets" in query:
            return _Cursor({"waiting": 3, "approved_today": 1, "rejected_today": 0})
        if "FROM associates" in query:
            return _Cursor([{"display_alias": "Alice"}, {"display_alias": "Bob"}])
        return _Cursor({})

    def close(self):
        return None


class VerifiedBetsDB:
    def execute(self, query):
        if "COUNT(*) as cnt FROM surebets WHERE status = 'open'" in query:
            return _Cursor({"cnt": 5})
        if "risk_classification" in query:
            return _Cursor({"cnt": 2})
        if "FROM associates" in query:
            return _Cursor([{"display_alias": "Alice"}, {"display_alias": "Bob"}])
        return _Cursor({})

    def close(self):
        return None


class _Cursor:
    def __init__(self, data):
        self.data = data

    def fetchone(self):
        if isinstance(self.data, dict):
            return self.data
        if isinstance(self.data, list):
            return self.data[0] if self.data else {}
        return self.data

    def fetchall(self):
        if isinstance(self.data, list):
            return self.data
        if isinstance(self.data, dict):
            return [self.data]
        return []


@pytest.mark.usefixtures("pandas_stub")
def test_incoming_bets_fragment_registration(monkeypatch, streamlit_stub):
    streamlit_stub.toggle_value = True

    recorded = _record_call_fragment(monkeypatch)
    monkeypatch.setattr("src.ui.helpers.fragments.fragments_supported", lambda: True)
    monkeypatch.setattr("src.ui.ui_components.load_global_styles", lambda: None)
    monkeypatch.setattr("src.ui.components.manual_upload.render_manual_upload_panel", lambda: None)
    monkeypatch.setattr("structlog.get_logger", lambda: LoggerStub())
    monkeypatch.setattr("src.core.database.get_db_connection", lambda: IncomingBetsDB())

    _reload("src.ui.pages.1_incoming_bets")

    assert recorded, "Expected incoming bets page to register fragment"
    entry = recorded[0]
    assert entry["name"] == "incoming_bets.queue"
    assert entry["kwargs"]["run_every"] == 30
    assert entry["kwargs"]["auto_refresh_enabled"] is True


@pytest.mark.usefixtures("pandas_stub")
def test_verified_bets_fragment_registration(monkeypatch, streamlit_stub):
    recorded = _record_call_fragment(monkeypatch)
    monkeypatch.setattr("src.ui.ui_components.load_global_styles", lambda: None)
    monkeypatch.setattr("src.core.database.get_db_connection", lambda: VerifiedBetsDB())
    monkeypatch.setattr("src.utils.logging_config.get_logger", lambda *args, **kwargs: LoggerStub())
    monkeypatch.setattr("asyncio.run", lambda coroutine: [])

    _reload("src.ui.pages.2_surebets_summary")

    assert recorded, "Expected verified bets page to register fragment"
    call = recorded[-1]
    assert call["name"] == "surebets.overview.table"
    kwargs = call["kwargs"]
    assert kwargs["sort_by"] in {"kickoff", "roi", "staked"}
    assert kwargs["show_unsafe_only"] in {True, False}
    assert "filter_associate" in kwargs


@pytest.mark.usefixtures("pandas_stub")
def test_reconciliation_fragment_registration(monkeypatch, streamlit_stub):
    @dataclass
    class Balance:
        associate_alias: str
        status: str
        net_deposits_eur: Decimal
        should_hold_eur: Decimal
        current_holding_eur: Decimal
        delta_eur: Decimal
        status_icon: str = ":material/check:"

    class FakeReconciliationService:
        def __init__(self, db):
            self._closed = False

        def get_associate_balances(self):
            return [
                Balance(
                    associate_alias="Alice",
                    status="balanced",
                    net_deposits_eur=Decimal("10"),
                    should_hold_eur=Decimal("10"),
                    current_holding_eur=Decimal("10"),
                    delta_eur=Decimal("0"),
                )
            ]

        def get_explanation(self, balance):
            return "All good"

        def close(self):
            self._closed = True

    class FakeBookmakerBalanceService:
        def __init__(self, db):
            pass

        def get_bookmaker_balances(self):
            return []

        def close(self):
            return None

    class FakeDB:
        def close(self):
            return None

    recorded = _record_call_fragment(monkeypatch)
    monkeypatch.setattr("src.ui.ui_components.load_global_styles", lambda: None)
    monkeypatch.setattr("src.utils.logging_config.get_logger", lambda *args, **kwargs: LoggerStub())
    monkeypatch.setattr("src.ui.components.reconciliation.pending_funding.render_pending_funding_section", lambda: None)
    monkeypatch.setattr("src.ui.components.reconciliation.bookmaker_drilldown.render_bookmaker_drilldown", lambda *args, **kwargs: None)
    monkeypatch.setattr("src.core.database.get_db_connection", lambda: FakeDB())
    monkeypatch.setattr("src.services.reconciliation_service.ReconciliationService", FakeReconciliationService)
    monkeypatch.setattr("src.services.bookmaker_balance_service.BookmakerBalanceService", FakeBookmakerBalanceService)

    _reload("src.ui.pages.6_reconciliation")

    assert recorded, "Expected reconciliation page to register fragment"
    call = recorded[-1]
    assert call["name"] == "reconciliation.associate_cards"
    entries = call["kwargs"]["balance_entries"]
    assert len(entries) == 1
    assert entries[0]["balance"].associate_alias == "Alice"


@pytest.mark.usefixtures("pandas_stub")
def test_statements_fragment_registration(monkeypatch, streamlit_stub):
    recorded = _record_call_fragment(monkeypatch)
    monkeypatch.setattr("src.ui.ui_components.load_global_styles", lambda: None)

    module = _reload("src.ui.pages.6_statements")

    # Avoid database lookups in render_input_panel
    monkeypatch.setattr(module, "render_input_panel", lambda: (None, None))

    streamlit_stub.session_state.statement_generated = True
    streamlit_stub.session_state.current_statement = types.SimpleNamespace(associate_name="Alice")

    module.main()

    assert recorded, "Expected statements page to invoke fragment"
    call = recorded[-1]
    assert call["name"] == "statements.output"
    assert call["kwargs"]["calc"].associate_name == "Alice"


def test_export_fragment_registration(monkeypatch, streamlit_stub):
    recorded = _record_call_fragment(monkeypatch)
    monkeypatch.setattr("src.ui.ui_components.load_global_styles", lambda: None)
    monkeypatch.setattr("src.services.ledger_export_service.LedgerExportService", lambda: None)

    module = _reload("src.ui.pages.5_export")
    module.main()

    names = [entry["name"] for entry in recorded]
    assert names[:2] == ["export.action", "export.history"]
