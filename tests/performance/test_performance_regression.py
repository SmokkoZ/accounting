"""
Regression tests to guard performance alert instrumentation.
"""

from __future__ import annotations

import time

import pytest

from src.ui.utils import performance


class DummyStreamlit:
    def __init__(self) -> None:
        self.session_state: dict[str, object] = {}


@pytest.fixture
def dummy_st(monkeypatch: pytest.MonkeyPatch) -> DummyStreamlit:
    dummy = DummyStreamlit()
    monkeypatch.setattr(performance, "st", dummy)
    return dummy


def test_performance_alerts_trigger_on_budget_exceed(dummy_st: DummyStreamlit, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(performance.PERFORMANCE_BUDGETS, "benchmark_fragment", 0.0001)
    with performance.track_timing("benchmark_fragment"):
        time.sleep(0.001)

    alerts = performance.get_performance_alerts()
    assert alerts
    assert alerts[-1]["label"] == "benchmark_fragment"
    performance.clear_performance_alerts()


def test_performance_alerts_reset_with_clear(dummy_st: DummyStreamlit):
    performance.record_timing("bench", 0.002, threshold=0.0001)
    assert performance.get_performance_alerts()
    performance.clear_performance_alerts()
    assert performance.get_performance_alerts() == []
