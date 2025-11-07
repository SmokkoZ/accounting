"""Tests for Streamlit session state helpers."""

from __future__ import annotations

import pytest

from src.ui.utils import state_management


class DummyStreamlit:
    """Minimal Streamlit stub for state management tests."""

    def __init__(self) -> None:
        self.session_state: dict[str, object] = {}
        self.rerun_called = False

    def rerun(self) -> None:  # pragma: no cover - invoked via safe_rerun
        self.rerun_called = True


@pytest.fixture
def dummy_st(monkeypatch: pytest.MonkeyPatch) -> DummyStreamlit:
    dummy = DummyStreamlit()
    monkeypatch.setattr(state_management, "st", dummy)
    return dummy


def test_reset_page_state_clears_prefixed_keys(dummy_st: DummyStreamlit) -> None:
    dummy_st.session_state = {
        "filters_status": "active",
        "dialog_confirm": True,
        "persistent_value": 42,
    }

    state_management.reset_page_state(prefixes=("filters_", "dialog_"))

    assert "filters_status" not in dummy_st.session_state
    assert "dialog_confirm" not in dummy_st.session_state
    assert dummy_st.session_state["persistent_value"] == 42


def test_safe_rerun_stores_reason_and_invokes_rerun(dummy_st: DummyStreamlit) -> None:
    state_management.safe_rerun("unit_test")

    assert dummy_st.session_state["_last_rerun_reason"] == "unit_test"
    assert dummy_st.rerun_called is True
