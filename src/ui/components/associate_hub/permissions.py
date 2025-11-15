"""
Shared permission helpers for Associates Hub components.

Centralises the Streamlit session-state keys that gate funding actions so the
Management/Overview tabs and the shared drawer follow the same rules.
"""

from __future__ import annotations

import streamlit as st

FUNDING_PERMISSION_KEY = "associates_hub_funding_permission"


def has_funding_permission() -> bool:
    """True when the operator has confirmed the funding permission gate."""
    return bool(st.session_state.get(FUNDING_PERMISSION_KEY, False))
