"""
Session state helpers for Streamlit pages.

Provides a shared reset utility so each page can clear its own widget/session
state without impacting other parts of the console. Also includes a safe rerun
wrapper to avoid duplicating Streamlit checks across pages.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Sequence, TypeVar

import streamlit as st
import structlog

from src.ui.helpers.dialogs import open_dialog, render_confirmation_dialog
from src.services.signal_broadcast_service import ChatOption

DEFAULT_PREFIXES: tuple[str, ...] = (
    "filters_",
    "advanced_",
    "resolve_",
    "dialog_",
    "triage_",
    "form_",
)

logger = structlog.get_logger(__name__)
T = TypeVar("T")


@dataclass(frozen=True)
class SignalRoutingPreset:
    """Pre-configured grouping of chat IDs for quick routing."""

    key: str
    label: str
    description: str
    chat_ids: List[str]


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


def build_signal_routing_presets(chat_options: Sequence[ChatOption]) -> List[SignalRoutingPreset]:
    """
    Derive useful routing presets from the available chat options.

    - Associate presets: all bookmaker chats for one associate.
    - Bookmaker presets: all associates registered for one bookmaker.
    - All-active preset: broadcast to every active chat (if more than one).
    """
    options = list(chat_options)
    if not options:
        return []

    presets: List[SignalRoutingPreset] = []
    active_chat_ids = [option.chat_id for option in options if option.associate_is_active and option.bookmaker_is_active]
    if len(active_chat_ids) > 1:
        presets.append(
            SignalRoutingPreset(
                key="all-active",
                label="All active chats",
                description="Broadcast to every active associate/bookmaker chat pairing.",
                chat_ids=active_chat_ids,
            )
        )

    by_associate: Dict[int, List[ChatOption]] = defaultdict(list)
    by_bookmaker: Dict[int, List[ChatOption]] = defaultdict(list)
    for option in options:
        by_associate[option.associate_id].append(option)
        by_bookmaker[option.bookmaker_id].append(option)

    for associate_id, associate_options in sorted(by_associate.items(), key=lambda item: (item[1][0].associate_alias.lower(), item[0])):
        if len(associate_options) < 2:
            continue
        label_alias = associate_options[0].associate_alias or f"Associate {associate_id}"
        presets.append(
            SignalRoutingPreset(
                key=f"associate:{associate_id}",
                label=f"{label_alias} - all bookmakers",
                description="Sends the signal to every bookmaker chat tied to this associate.",
                chat_ids=[opt.chat_id for opt in associate_options],
            )
        )

    for bookmaker_id, bookmaker_options in sorted(by_bookmaker.items(), key=lambda item: (item[1][0].bookmaker_name.lower(), item[0])):
        if len(bookmaker_options) < 2:
            continue
        bookmaker_label = bookmaker_options[0].bookmaker_name or f"Bookmaker {bookmaker_id}"
        presets.append(
            SignalRoutingPreset(
                key=f"bookmaker:{bookmaker_id}",
                label=f"{bookmaker_label} - all associates",
                description="Routes to every associate chat registered for this bookmaker.",
                chat_ids=[opt.chat_id for opt in bookmaker_options],
            )
        )

    return presets


def get_or_create_state_value(key: str, loader: Callable[[], T]) -> T:
    """
    Simple session-state cache helper for expensive computations.
    """
    if key not in st.session_state:
        st.session_state[key] = loader()
    return st.session_state[key]
