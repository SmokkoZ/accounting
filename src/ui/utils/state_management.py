"""
Session state helpers for Streamlit pages.

Provides a shared reset utility so each page can clear its own widget/session
state without impacting other parts of the console. Also includes a safe rerun
wrapper to avoid duplicating Streamlit checks across pages.
"""

from __future__ import annotations

from typing import Iterable, Sequence

import streamlit as st
import structlog

from src.ui.helpers.dialogs import open_dialog, render_confirmation_dialog
DEFAULT_PREFIXES: tuple[str, ...] = (
    "filters_",
    "advanced_",
    "resolve_",
    "dialog_",
    "triage_",
    "form_",
)

logger = structlog.get_logger(__name__)


def reset_page_state(prefixes: Sequence[str] = DEFAULT_PREFIXES) -> None:
    """
    Remove keys from ``st.session_state`` that start with any of the prefixes.

    Args:
        prefixes: Iterable of prefix strings to match against state keys.
    """
    try:
        state_keys = list(st.session_state.keys())
    except (AttributeError, RuntimeError):
        return

    for key in state_keys:
        if any(key.startswith(prefix) for prefix in prefixes):
            st.session_state.pop(key, None)


def safe_rerun(reason: str = "user_action") -> None:
    """
    Trigger ``st.rerun`` when available while capturing the reason for logging.
    """
    try:
        st.session_state["_last_rerun_reason"] = reason
    except Exception:  # pragma: no cover - defensive
        pass

    logger.debug("ui_rerun", reason=reason)

    rerun = getattr(st, "rerun", None)
    if callable(rerun):
        rerun()


def render_reset_control(
    *,
    key: str,
    label: str = ":material/restart_alt: Reset page state",
    description: str = "Clear filters, dialogs, and advanced controls for this page.",
    prefixes: Iterable[str] = DEFAULT_PREFIXES,
) -> None:
    """
    Render a reset button + confirmation dialog wired to ``reset_page_state``.

    Args:
        key: Unique key for the dialog/button.
        label: Button label.
        description: Warning message shown inside the confirmation dialog.
        prefixes: Prefixes passed to ``reset_page_state``.
    """
    button_key = f"{key}__button"
    if st.button(label, key=button_key, type="secondary", help=description, width="stretch"):
        open_dialog(key)

    decision = render_confirmation_dialog(
        key=key,
        title="Reset page state?",
        body=description,
        confirm_label="Reset",
        cancel_label="Keep state",
        confirm_type="secondary",
    )
    if decision is None:
        return

    if decision:
        reset_page_state(tuple(prefixes))
        safe_rerun(reason=f"{key}_reset")
