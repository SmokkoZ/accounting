"""
Streamlit page for broadcasting surebet signals to Telegram chats.

Implements the workflow described in Story 12.1 with cached chat lookups,
routing presets, live preview, and per-chat delivery results.
"""

from __future__ import annotations

from html import escape
from typing import Iterable, List, Optional

import streamlit as st

from src.core.config import Config
from src.services.signal_broadcast_service import (
    BroadcastSummary,
    ChatOption,
    SignalBroadcastService,
)
from src.ui.utils.state_management import (
    SignalRoutingPreset,
    build_signal_routing_presets,
    get_or_create_state_value,
)

MESSAGE_STATE_KEY = "signal_broadcast_message"
CHAT_SELECTION_KEY = "signal_broadcast_selected_chats"
SUMMARY_STATE_KEY = "signal_broadcast_last_summary"
APPLIED_PRESET_KEY = "signal_broadcast_active_preset"


@st.cache_data(show_spinner=False, ttl=60)
def _load_chat_options() -> List[ChatOption]:
    service = SignalBroadcastService()
    try:
        return service.list_chat_options()
    finally:
        service.close()


def _broadcast_signal(
    message: str, chat_ids: Iterable[str], preset_key: Optional[str]
) -> BroadcastSummary:
    service = SignalBroadcastService()
    try:
        return service.broadcast(message=message, chat_ids=list(chat_ids), preset_key=preset_key)
    finally:
        service.close()


@st.fragment
def _render_preview(message: str) -> None:
    st.subheader("Live preview")
    if not message:
        st.caption("Type a signal message to see the exact Telegram output.")
        return

    st.markdown(
        f"<pre style='white-space: pre-wrap;'>{escape(message)}</pre>",
        unsafe_allow_html=True,
    )


@st.fragment
def _render_results(summary: Optional[BroadcastSummary]) -> None:
    st.subheader("Delivery results")
    if summary is None:
        st.caption("Send a signal to view per-chat delivery results.")
        return

    success_text = f"Sent to {summary.succeeded} of {summary.total} chats."
    if summary.failed == 0:
        st.success(success_text, icon=":material/check_circle:")
    else:
        st.info(success_text, icon=":material/info:")

    if summary.failed:
        st.warning(
            "Some chats reported errors. Review the details below, adjust, and resend.",
            icon=":material/error:",
        )
        for label, error in summary.failure_summaries:
            st.error(f"{label}: {error or 'Unknown error'}", icon=":material/cancel:")

    if summary.succeeded:
        st.caption(
            "Delivered chats: " + ", ".join(summary.success_labels),
        )


def _infer_matching_preset(
    chat_ids: List[str], presets: List[SignalRoutingPreset]
) -> Optional[str]:
    selected = set(chat_ids)
    for preset in presets:
        if selected == set(preset.chat_ids):
            return preset.key
    return None


def main() -> None:
    st.title("Signal Broadcaster")
    st.caption("Paste formatted surebet signals, preview, and dispatch them to Telegram chats.")
    st.info(
        "Signals are sent exactly as typed. No formatting changes or markdown rendering is applied.",
        icon=":material/straighten:",
    )

    chat_options = _load_chat_options()
    if not chat_options:
        st.error("No Telegram chats are registered. Configure chat registrations first.")
        return

    presets = build_signal_routing_presets(chat_options)
    get_or_create_state_value(MESSAGE_STATE_KEY, lambda: "")
    get_or_create_state_value(CHAT_SELECTION_KEY, lambda: [])

    selected_chats: List[str] = st.session_state[CHAT_SELECTION_KEY]
    current_preset_key = _infer_matching_preset(selected_chats, presets)
    st.session_state[APPLIED_PRESET_KEY] = current_preset_key

    preset_options: List[Optional[SignalRoutingPreset]] = [None, *presets]
    selected_preset = st.selectbox(
        "Routing presets",
        options=preset_options,
        format_func=lambda preset: preset.label if preset else "Manual selection",
    )
    apply_disabled = selected_preset is None
    if st.button("Apply preset", disabled=apply_disabled):
        st.session_state[CHAT_SELECTION_KEY] = list(selected_preset.chat_ids) if selected_preset else []
        if selected_preset:
            st.session_state[APPLIED_PRESET_KEY] = selected_preset.key
            st.toast(f"Preset applied: {selected_preset.label}")

    col_form, col_side = st.columns([2, 1])
    with col_form:
        raw_message: str = st.text_area(
            "Signal message",
            key=MESSAGE_STATE_KEY,
            placeholder="Paste the exact signal text here...",
            height=240,
        )

        chat_label_lookup = {option.chat_id: f"{option.label} - {option.chat_id}" for option in chat_options}
        chat_value = st.multiselect(
            "Telegram chats",
            options=[option.chat_id for option in chat_options],
            key=CHAT_SELECTION_KEY,
            format_func=lambda chat_id: chat_label_lookup.get(chat_id, chat_id),
            placeholder="Search associate or bookmaker...",
        )

        token_configured = bool(Config.TELEGRAM_BOT_TOKEN)
        has_message = bool(raw_message.strip())
        can_send = has_message and bool(chat_value) and token_configured

        helper_message: Optional[str] = None
        if not has_message:
            helper_message = "Enter a signal message to enable sending."
        elif not chat_value:
            helper_message = "Select at least one chat to broadcast."
        elif not token_configured:
            helper_message = "Configure TELEGRAM_BOT_TOKEN in the environment to enable sending."

        send_clicked = st.button(
            "Send signal",
            type="primary",
            disabled=not can_send,
            width='stretch',
        )

        if helper_message:
            st.caption(helper_message)

        if send_clicked:
            try:
                summary = _broadcast_signal(
                    raw_message,
                    chat_value,
                    st.session_state.get(APPLIED_PRESET_KEY),
                )
                st.session_state[SUMMARY_STATE_KEY] = summary
                st.success(
                    f"Queued broadcast to {summary.total} chats. "
                    "Scroll to the delivery log for per-chat results.",
                    icon=":material/send:",
                )
            except ValueError as exc:
                st.error(str(exc))
            except Exception as exc:  # pragma: no cover - defensive UI guard
                st.error(f"Failed to send signal: {exc}")

    with col_side:
        _render_preview(st.session_state[MESSAGE_STATE_KEY])
        st.divider()
        _render_results(st.session_state.get(SUMMARY_STATE_KEY))


if __name__ == "__main__":
    main()
