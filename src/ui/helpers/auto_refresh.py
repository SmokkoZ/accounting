"""Auto-refresh state helpers shared across Streamlit pages."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Iterator, Optional

import streamlit as st

from src.ui.helpers import url_state

_TRUTHY_VALUES = {"1", "true", "yes", "on", "auto", "enabled"}
_FALSY_VALUES = {"0", "false", "no", "off", "disabled"}


def read_query_flag(query_key: str) -> Optional[bool]:
    """
    Interpret the boolean query parameter for the provided key.
    """
    params = url_state.read_query_params()
    raw_value = url_state.normalize_query_value(params.get(query_key))
    if raw_value is None:
        return None
    lowered = raw_value.lower()
    if lowered in _TRUTHY_VALUES:
        return True
    if lowered in _FALSY_VALUES:
        return False
    return None


def resolve_toggle_state(
    *,
    session_key: str,
    sync_key: str,
    query_key: str,
    supported: bool,
    default_on: bool,
) -> bool:
    """
    Determine the toggle's default value, honoring query params and support.
    """
    if not supported:
        st.session_state[session_key] = False
        persist_query_state(value=False, query_key=query_key, sync_key=sync_key)
        st.session_state[sync_key] = False
        return False

    if session_key in st.session_state:
        return bool(st.session_state[session_key])

    query_value = read_query_flag(query_key)
    resolved = default_on if query_value is None else query_value
    st.session_state[session_key] = bool(resolved)
    st.session_state[sync_key] = query_value
    return bool(resolved)


def persist_query_state(*, value: bool, query_key: str, sync_key: str) -> None:
    """
    Persist the toggle state to the URL for saved-view support.
    """
    last_synced = st.session_state.get(sync_key)
    if last_synced == value:
        return

    updated = url_state.set_query_param_flag(query_key, value)
    if updated or last_synced is None or last_synced != value:
        st.session_state[sync_key] = value


@contextmanager
def auto_refresh_cycle(*, enabled: bool, inflight_key: str, last_run_key: str) -> Iterator[None]:
    """
    Track auto-refresh spinner state and last completion timestamp.
    """
    if not enabled:
        yield
        return

    st.session_state[inflight_key] = True
    try:
        yield
    finally:
        st.session_state[inflight_key] = False
        st.session_state[last_run_key] = datetime.now(UTC)


def _coerce_datetime(value: object) -> Optional[datetime]:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        except ValueError:
            return None
    return None


def format_status(
    *,
    enabled: bool,
    supported: bool,
    interval_seconds: int,
    inflight_key: str,
    last_run_key: str,
) -> str:
    """
    Produce a descriptive status string for the auto-refresh indicator.
    """
    if not supported:
        return (
            ":material/info: Auto-refresh requires Streamlit fragment support; "
            "use manual refresh on older versions."
        )

    if not enabled:
        return ":material/pause_circle: Auto-refresh paused. Enable the toggle to resume automated updates."

    if st.session_state.get(inflight_key):
        return ":material/sync: Refreshing incoming bets..."

    last_run = _coerce_datetime(st.session_state.get(last_run_key))
    if last_run is None:
        return f":material/autorenew: Auto-refresh ON - Runs every {interval_seconds}s"

    elapsed = max(int((datetime.now(UTC) - last_run).total_seconds()), 0)
    remaining = max(interval_seconds - elapsed, 0)
    next_message = "refreshing now" if remaining == 0 else f"next run in {remaining}s"

    return f":material/autorenew: Auto-refresh ON - Last ran {elapsed}s ago - {next_message}"


__all__ = [
    "auto_refresh_cycle",
    "format_status",
    "persist_query_state",
    "read_query_flag",
    "resolve_toggle_state",
]
