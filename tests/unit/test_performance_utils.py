"""
Tests for performance instrumentation helpers.
"""

from __future__ import annotations

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


def test_track_timing_records_entries(dummy_st: DummyStreamlit) -> None:
    with performance.track_timing("incoming_render"):
        pass

    entries = performance.get_recent_timings()
    assert len(entries) == 1
    assert entries[0]["label"] == "incoming_render"
    assert entries[0]["duration"] >= 0
    assert entries[0]["timestamp"] > 0


def test_clear_timings_resets_buffer(dummy_st: DummyStreamlit) -> None:
    performance.record_timing("foo", 0.1)
    assert performance.get_recent_timings()

    performance.clear_timings()
    assert performance.get_recent_timings() == []


def test_record_timing_triggers_alert_on_threshold(dummy_st: DummyStreamlit):
    performance.record_timing("hot_path", 0.2, threshold=0.1)
    alerts = performance.get_performance_alerts()
    assert alerts
    assert alerts[-1]["label"] == "hot_path"
    performance.clear_performance_alerts()
