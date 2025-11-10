from datetime import datetime

import pytest

from src.ui.helpers import auto_refresh


class DummyStreamlit:
    def __init__(self) -> None:
        self.session_state: dict[str, object] = {}


@pytest.fixture
def dummy_st(monkeypatch: pytest.MonkeyPatch) -> DummyStreamlit:
    stub = DummyStreamlit()
    monkeypatch.setattr(auto_refresh, "st", stub)
    return stub


def test_resolve_toggle_defaults_to_true_when_supported(dummy_st: DummyStreamlit, monkeypatch):
    monkeypatch.setattr(auto_refresh.url_state, "read_query_params", lambda: {})
    monkeypatch.setattr(auto_refresh.url_state, "normalize_query_value", lambda value: value)

    result = auto_refresh.resolve_toggle_state(
        session_key="auto_key",
        sync_key="auto_sync",
        query_key="auto",
        supported=True,
        default_on=True,
    )

    assert result is True
    assert dummy_st.session_state["auto_key"] is True
    assert "auto_sync" in dummy_st.session_state
    assert dummy_st.session_state["auto_sync"] is None


def test_resolve_toggle_respects_query_param_false(dummy_st: DummyStreamlit, monkeypatch):
    monkeypatch.setattr(auto_refresh.url_state, "read_query_params", lambda: {"auto": "0"})
    monkeypatch.setattr(auto_refresh.url_state, "normalize_query_value", lambda value: value)

    result = auto_refresh.resolve_toggle_state(
        session_key="auto_key",
        sync_key="auto_sync",
        query_key="auto",
        supported=True,
        default_on=True,
    )

    assert result is False
    assert dummy_st.session_state["auto_key"] is False
    assert dummy_st.session_state["auto_sync"] is False


def test_resolve_toggle_forces_false_when_not_supported(dummy_st: DummyStreamlit, monkeypatch):
    calls: list[tuple[str, bool]] = []

    def fake_set(key: str, value: bool) -> bool:
        calls.append((key, value))
        return True

    monkeypatch.setattr(auto_refresh.url_state, "set_query_param_flag", fake_set)

    result = auto_refresh.resolve_toggle_state(
        session_key="auto_key",
        sync_key="auto_sync",
        query_key="auto",
        supported=False,
        default_on=True,
    )

    assert result is False
    assert dummy_st.session_state["auto_key"] is False
    assert dummy_st.session_state["auto_sync"] is False
    assert calls == [("auto", False)]


def test_persist_query_state_updates_query_params(dummy_st: DummyStreamlit, monkeypatch):
    dummy_st.session_state["sync"] = None
    calls = []

    def fake_set(key: str, value: bool) -> bool:
        calls.append((key, value))
        return True

    monkeypatch.setattr(auto_refresh.url_state, "set_query_param_flag", fake_set)

    auto_refresh.persist_query_state(value=True, query_key="auto", sync_key="sync")

    assert calls == [("auto", True)]
    assert dummy_st.session_state["sync"] is True


def test_persist_query_state_skips_when_unchanged(dummy_st: DummyStreamlit, monkeypatch):
    dummy_st.session_state["sync"] = True
    def fail_call(*args, **kwargs):
        raise AssertionError("set_query_param_flag should not be called when state is unchanged")

    monkeypatch.setattr(auto_refresh.url_state, "set_query_param_flag", fail_call)

    auto_refresh.persist_query_state(value=True, query_key="auto", sync_key="sync")


def test_auto_refresh_cycle_tracks_inflight_and_last_run(dummy_st: DummyStreamlit):
    with auto_refresh.auto_refresh_cycle(enabled=True, inflight_key="spin", last_run_key="last"):
        assert dummy_st.session_state["spin"] is True

    assert dummy_st.session_state["spin"] is False
    assert isinstance(dummy_st.session_state["last"], datetime)


def test_auto_refresh_cycle_noop_when_disabled(dummy_st: DummyStreamlit):
    with auto_refresh.auto_refresh_cycle(enabled=False, inflight_key="spin", last_run_key="last"):
        pass

    assert "spin" not in dummy_st.session_state
    assert "last" not in dummy_st.session_state


def test_format_status_handles_unsupported(dummy_st: DummyStreamlit):
    message = auto_refresh.format_status(
        enabled=True,
        supported=False,
        interval_seconds=30,
        inflight_key="spin",
        last_run_key="last",
    )

    assert "requires Streamlit fragment support" in message


def test_format_status_handles_paused_state(dummy_st: DummyStreamlit):
    message = auto_refresh.format_status(
        enabled=False,
        supported=True,
        interval_seconds=30,
        inflight_key="spin",
        last_run_key="last",
    )

    assert "paused" in message.lower()


def test_format_status_handles_running_state(dummy_st: DummyStreamlit):
    dummy_st.session_state["spin"] = True
    message = auto_refresh.format_status(
        enabled=True,
        supported=True,
        interval_seconds=30,
        inflight_key="spin",
        last_run_key="last",
    )

    assert "refreshing" in message.lower()


def test_format_status_reports_last_run(dummy_st: DummyStreamlit, monkeypatch):
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            base = cls(2025, 1, 1, 12, 0, 30, tzinfo=auto_refresh.UTC)
            if tz is not None:
                return base.astimezone(tz)
            return base

        @classmethod
        def utcnow(cls) -> datetime:
            return cls(2025, 1, 1, 12, 0, 30)

    monkeypatch.setattr(auto_refresh, "datetime", FrozenDateTime)

    dummy_st.session_state["spin"] = False
    dummy_st.session_state["last"] = FrozenDateTime(2025, 1, 1, 12, 0, 0)

    message = auto_refresh.format_status(
        enabled=True,
        supported=True,
        interval_seconds=30,
        inflight_key="spin",
        last_run_key="last",
    )

    lower_message = message.lower()
    assert "last ran 30s ago" in lower_message
    assert "refreshing now" in lower_message


def test_read_query_flag_parses_truthy_values(monkeypatch):
    monkeypatch.setattr(auto_refresh.url_state, "read_query_params", lambda: {"auto": ["yes"]})
    monkeypatch.setattr(auto_refresh.url_state, "normalize_query_value", lambda value: value[0])

    assert auto_refresh.read_query_flag("auto") is True

    monkeypatch.setattr(auto_refresh.url_state, "read_query_params", lambda: {"auto": ["0"]})
    assert auto_refresh.read_query_flag("auto") is False
