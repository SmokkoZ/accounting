"""
Lightweight performance instrumentation helpers for Streamlit pages.
"""

from __future__ import annotations

import time
from collections import deque
from contextlib import contextmanager
from typing import Deque, Dict, Iterator, List

import streamlit as st

STATE_KEY = "performance_timings"
ALERTS_STATE_KEY = "performance_alerts"
MAX_ENTRIES = 50
MAX_ALERTS = 20
DEFAULT_THRESHOLD = 1.5

# Allow QA to tune thresholds per fragment.
PERFORMANCE_BUDGETS: Dict[str, float] = {
    "incoming_queue": 1.5,
    "surebets_overview": 1.5,
    "reconciliation_cards": 1.5,
}


def _get_buffer() -> Deque[Dict[str, float]]:
    try:
        buffer = st.session_state.get(STATE_KEY)
    except Exception:
        return deque(maxlen=MAX_ENTRIES)

    if not isinstance(buffer, deque):
        buffer = deque(maxlen=MAX_ENTRIES)

    if buffer.maxlen != MAX_ENTRIES:
        buffer = deque(buffer, maxlen=MAX_ENTRIES)

    st.session_state[STATE_KEY] = buffer
    return buffer


def _get_alert_buffer() -> Deque[Dict[str, float]]:
    try:
        buffer = st.session_state.get(ALERTS_STATE_KEY)
    except Exception:
        return deque(maxlen=MAX_ALERTS)

    if not isinstance(buffer, deque):
        buffer = deque(maxlen=MAX_ALERTS)

    if buffer.maxlen != MAX_ALERTS:
        buffer = deque(buffer, maxlen=MAX_ALERTS)

    st.session_state[ALERTS_STATE_KEY] = buffer
    return buffer


def _record_alert(label: str, duration: float, threshold: float) -> None:
    try:
        alerts = _get_alert_buffer()
        alerts.append(
            {
                "timestamp": time.time(),
                "label": label,
                "duration": duration,
                "threshold": threshold,
            }
        )
        st.session_state[ALERTS_STATE_KEY] = alerts
    except Exception:
        pass


def _resolve_threshold(label: str, threshold: float | None) -> float | None:
    if threshold is not None:
        return threshold
    if label in PERFORMANCE_BUDGETS:
        return PERFORMANCE_BUDGETS[label]
    return DEFAULT_THRESHOLD


def record_timing(label: str, duration: float, *, threshold: float | None = None) -> None:
    """
    Store a timing entry in session state.
    """
    try:
        buffer = _get_buffer()
        buffer.append(
            {
                "timestamp": time.time(),
                "label": label,
                "duration": duration,
            }
        )
        st.session_state[STATE_KEY] = buffer
        resolved_threshold = _resolve_threshold(label, threshold)
        if resolved_threshold is not None and duration > resolved_threshold:
            _record_alert(label, duration, resolved_threshold)
    except Exception:
        pass


@contextmanager
def track_timing(label: str, *, threshold: float | None = None) -> Iterator[None]:
    """
    Context manager to measure block duration automatically.
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        record_timing(label, time.perf_counter() - start, threshold=threshold)


def get_recent_timings() -> List[Dict[str, float]]:
    """
    Return a list copy of the timing buffer for display.
    """
    try:
        buffer = st.session_state.get(STATE_KEY)
    except Exception:
        return []

    if not isinstance(buffer, deque):
        return []
    return list(buffer)


def clear_timings() -> None:
    """
    Reset performance timings (useful when changing pages).
    """
    try:
        st.session_state[STATE_KEY] = deque(maxlen=MAX_ENTRIES)
    except Exception:
        pass


def get_performance_alerts(clear: bool = False) -> List[Dict[str, float]]:
    """
    Return any recorded alert entries.
    """
    try:
        alerts = st.session_state.get(ALERTS_STATE_KEY)
    except Exception:
        alerts = None

    if not isinstance(alerts, deque):
        return []

    items = list(alerts)
    if clear:
        st.session_state[ALERTS_STATE_KEY] = deque(maxlen=MAX_ALERTS)
    return items


def clear_performance_alerts() -> None:
    try:
        st.session_state[ALERTS_STATE_KEY] = deque(maxlen=MAX_ALERTS)
    except Exception:
        pass


__all__ = [
    "PERFORMANCE_BUDGETS",
    "clear_performance_alerts",
    "clear_timings",
    "get_performance_alerts",
    "get_recent_timings",
    "record_timing",
    "track_timing",
]
