from contextlib import contextmanager

import pytest

from src.ui.helpers import fragments


class StreamlitStub:
    """Minimal Streamlit stub capturing checkbox, write, and fragment interactions."""

    def __init__(self) -> None:
        self.session_state = {}
        self.checkbox_value = False
        self.checkbox_calls = []
        self.expanders = []
        self.write_calls = []
        self.markdown_calls = []
        self.fragment_calls = []

    def checkbox(self, label, *, value, key, help=None):
        self.checkbox_calls.append({"label": label, "value": value, "key": key, "help": help})
        # Emulate Streamlit by updating session_state with the returned value.
        self.session_state[key] = self.checkbox_value
        return self.checkbox_value

    def expander(self, label, expanded=False):
        record = {"label": label, "expanded": expanded}
        self.expanders.append(record)
        return _NoOpContextManager()

    def write(self, message):
        self.write_calls.append(message)

    def markdown(self, message):
        self.markdown_calls.append(message)

    def fragment(self, func=None, *, run_every=None):
        def decorator(callable_obj):
            self.fragment_calls.append({"run_every": run_every, "callable": callable_obj})

            def wrapper(*args, **kwargs):
                return callable_obj(*args, **kwargs)

            return wrapper

        if func is None:
            return decorator
        return decorator(func)


class _NoOpContextManager:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


@pytest.fixture(autouse=True)
def reset_fragment_timer(monkeypatch):
    """Ensure a fresh FragmentTimer per test."""
    timer = fragments.FragmentTimer()
    monkeypatch.setattr(fragments, "fragment_timer", timer)
    yield


def test_fragment_timer_collects_stats_and_enforces_history_limit(monkeypatch):
    timer = fragments.FragmentTimer()
    duration_count = (fragments._FRAGMENT_HISTORY_LIMIT + 10) * 2
    counter = iter([i * 0.01 for i in range(duration_count)])

    monkeypatch.setattr(fragments.time, "perf_counter", lambda: next(counter))

    with timer.time_fragment("alpha"):
        pass

    with timer.time_fragment("alpha"):
        pass

    for _ in range(fragments._FRAGMENT_HISTORY_LIMIT + 5):
        with timer.time_fragment("alpha"):
            pass

    stats = timer.get_stats()
    assert "alpha" in stats
    alpha_stats = stats["alpha"]
    assert alpha_stats["count"] == float(fragments._FRAGMENT_HISTORY_LIMIT)
    assert alpha_stats["min"] <= alpha_stats["avg"] <= alpha_stats["max"]

    timer.clear()
    assert timer.get_stats() == {}


def test_fragments_supported_delegates_to_feature_flags(monkeypatch):
    calls = []
    monkeypatch.setattr(fragments.feature_flags, "has", lambda name: calls.append(name) or True)
    assert fragments.fragments_supported() is True
    assert calls == ["fragment"]


def test_fragment_decorator_without_streamlit_support(monkeypatch):
    stub = StreamlitStub()
    monkeypatch.setattr(fragments, "st", stub)
    monkeypatch.setattr(fragments, "fragments_supported", lambda: False)

    @contextmanager
    def noop_timer(_fragment_name):
        yield

    monkeypatch.setattr(fragments.fragment_timer, "time_fragment", noop_timer)

    tracker = []

    @fragments.fragment("incoming.queue")
    def render_queue(data):
        tracker.append(data)
        return "done"

    result = render_queue({"id": 1})
    assert result == "done"
    assert tracker == [{"id": 1}]
    assert stub.fragment_calls == []


def test_fragment_decorator_with_streamlit_support_and_run_every(monkeypatch):
    stub = StreamlitStub()
    stub.checkbox_value = True
    monkeypatch.setattr(fragments, "st", stub)
    monkeypatch.setattr(fragments, "fragments_supported", lambda: True)

    recorded = []

    @contextmanager
    def fake_timer(fragment_name):
        recorded.append(fragment_name)
        yield

    monkeypatch.setattr(fragments.fragment_timer, "time_fragment", fake_timer)

    @fragments.fragment("verified.table", run_every=45)
    def render_table():
        return "table"

    assert render_table() == "table"
    assert recorded == ["verified.table"]
    assert stub.fragment_calls and stub.fragment_calls[0]["run_every"] == 45


def test_call_fragment_executes_callable(monkeypatch):
    stub = StreamlitStub()
    monkeypatch.setattr(fragments, "st", stub)
    monkeypatch.setattr(fragments, "fragments_supported", lambda: False)

    @contextmanager
    def noop_timer(_name):
        yield

    monkeypatch.setattr(fragments.fragment_timer, "time_fragment", noop_timer)

    points = []

    def render(**kwargs):
        points.append(kwargs)
        return 123

    result = fragments.call_fragment("statements.output", render, amount=99)
    assert result == 123
    assert points == [{"amount": 99}]


def test_render_debug_toggle_initialises_session_state(monkeypatch):
    stub = StreamlitStub()
    stub.checkbox_value = True
    monkeypatch.setattr(fragments, "st", stub)

    value = fragments.render_debug_toggle()
    assert value is True
    assert stub.checkbox_calls[0]["label"] == "Show performance debug"
    assert fragments._DEBUG_SESSION_KEY in stub.session_state


def test_render_debug_panel_handles_no_stats(monkeypatch):
    stub = StreamlitStub()
    monkeypatch.setattr(fragments, "st", stub)
    stub.session_state[fragments._DEBUG_SESSION_KEY] = True

    fragments.render_debug_panel(expanded=True)
    assert stub.expanders and stub.expanders[0]["expanded"] is True
    assert stub.write_calls[-1] == "No fragment timings recorded yet."


def test_render_debug_panel_outputs_stats(monkeypatch):
    stub = StreamlitStub()
    monkeypatch.setattr(fragments, "st", stub)
    stub.session_state[fragments._DEBUG_SESSION_KEY] = True

    monkeypatch.setattr(
        fragments.fragment_timer,
        "get_stats",
        lambda: {
            "incoming": {
                "count": 3.0,
                "total": 0.3,
                "avg": 0.1,
                "min": 0.05,
                "max": 0.15,
                "last": 0.12,
            }
        },
    )

    fragments.render_debug_panel()
    assert any("incoming" in text for text in stub.markdown_calls), "Expected fragment name in markdown output"


def test_is_debug_enabled_reflects_session_state(monkeypatch):
    stub = StreamlitStub()
    monkeypatch.setattr(fragments, "st", stub)
    stub.session_state[fragments._DEBUG_SESSION_KEY] = True
    assert fragments.is_debug_enabled() is True
    stub.session_state[fragments._DEBUG_SESSION_KEY] = False
    assert fragments.is_debug_enabled() is False
