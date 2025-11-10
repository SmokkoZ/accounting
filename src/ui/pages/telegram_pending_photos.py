"""
Telegram Pending Photos oversight page (Story 10.1).
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, List

import streamlit as st
from streamlit.errors import StreamlitAPIException

try:  # pragma: no cover - optional dependency guard
    from src.integrations.telegram_bot import PENDING_CONFIRMATION_TTL_SECONDS
except Exception:  # pragma: no cover - fallback when telegram deps unavailable
    PENDING_CONFIRMATION_TTL_SECONDS = 60 * 60

from src.services.telegram_pending_photo_service import (
    PendingPhotoAlreadyProcessed,
    PendingPhotoNotFound,
    TelegramPendingPhotoService,
)
from src.ui.helpers.dialogs import open_dialog, render_reason_dialog
from src.ui.helpers.fragments import fragment, render_debug_panel, render_debug_toggle
from src.ui.ui_components import load_global_styles
from src.ui.utils.state_management import safe_rerun
from src.ui.utils.ttl import TTLState, classify_ttl, compute_ttl_seconds, format_ttl_label
from src.utils.datetime_helpers import parse_utc_iso
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

PAGE_TITLE = "Telegram Pending Photos"
PAGE_ICON = ":material/photo_library:"
ALERT_QUEUE_KEY = "pending_photos_alerts"


def _configure_page() -> None:
    try:
        st.set_page_config(
            page_title=PAGE_TITLE,
            page_icon=PAGE_ICON,
            layout="wide",
            initial_sidebar_state="expanded",
        )
    except StreamlitAPIException:
        # Already configured by parent app shell.
        pass


@st.cache_data(ttl=3, show_spinner=False)
def _load_pending_payload() -> List[Dict[str, Any]]:
    service = TelegramPendingPhotoService()
    try:
        entries = service.list_pending()
        return [asdict(entry) for entry in entries]
    finally:
        service.close()


def _invalidate_pending_cache() -> None:
    _load_pending_payload.clear()  # type: ignore[attr-defined]


def _resolve_operator_identity() -> str:
    for key in ("operator_name", "operator_email", "user_email", "user_display_name"):
        value = st.session_state.get(key)
        if value:
            return str(value)
    return "local_user"


def _push_alert(level: str, message: str) -> None:
    queue: List[Dict[str, str]] = st.session_state.setdefault(ALERT_QUEUE_KEY, [])
    queue.append({"level": level, "message": message})


def _drain_alerts() -> None:
    queue: List[Dict[str, str]] = st.session_state.pop(ALERT_QUEUE_KEY, [])
    for alert in queue:
        level = alert.get("level")
        message = alert.get("message", "")
        if level == "success":
            st.success(message, icon=":material/check_circle:")
        elif level == "warning":
            st.warning(message, icon=":material/warning:")
        elif level == "error":
            st.error(message, icon=":material/error:")
        else:
            st.info(message, icon=":material/info:")


def _format_timestamp(iso_value: str) -> str:
    dt = parse_utc_iso(iso_value)
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def _render_header() -> None:
    st.markdown(
        f"{PAGE_ICON} **{PAGE_TITLE}**",
    )
    ttl_minutes = PENDING_CONFIRMATION_TTL_SECONDS // 60
    st.caption(
        f"Monitor Telegram confirm-before-ingest queue. "
        f"Items auto-discard after {ttl_minutes} minutes with the same bot policy."
    )
    _drain_alerts()

    with st.expander("Force Ingest Controls", expanded=False):
        st.toggle(
            ":material/security: Enable Force Ingest (admin only)",
            value=st.session_state.get("pending_force_toggle", False),
            key="pending_force_toggle",
            help="Force Ingest bypasses the Telegram confirmation delay. Only enable when you "
            "need to ingest a photo that was missed in chat and log the override reason.",
        )
        st.caption(
            "Force Ingest requires a justification note and logs the operator, chat, and outcome "
            "to the Telegram audit trail."
        )


def _handle_discard(entry: Dict[str, Any], reason: str) -> None:
    service = TelegramPendingPhotoService()
    operator = _resolve_operator_identity()
    try:
        service.discard(entry["id"], operator=operator, reason=reason)
        _push_alert(
            "success",
            f"Discarded Ref #{entry['confirmation_token'][:6].upper()} "
            f"for chat {entry['chat_id']}.",
        )
        logger.info(
            "pending_photos_ui_discard",
            pending_id=entry["id"],
            operator=operator,
        )
    except PendingPhotoNotFound as exc:
        _push_alert("warning", str(exc))
    except PendingPhotoAlreadyProcessed as exc:
        _push_alert("warning", str(exc))
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("pending_photos_ui_discard_failed", error=str(exc), exc_info=True)
        _push_alert("error", "Discard failed. See logs for details.")
    finally:
        service.close()
        _invalidate_pending_cache()
        safe_rerun("pending_discard")


def _handle_force_ingest(entry: Dict[str, Any], justification: str) -> None:
    service = TelegramPendingPhotoService()
    operator = _resolve_operator_identity()
    try:
        result = service.force_ingest(entry["id"], operator=operator, justification=justification)
        bet_id = result.get("bet_id")
        _push_alert(
            "success",
            f"Force ingested Ref #{entry['confirmation_token'][:6].upper()} (Bet ID {bet_id}).",
        )
        logger.info(
            "pending_photos_ui_force_ingest",
            pending_id=entry["id"],
            bet_id=bet_id,
            operator=operator,
        )
    except PendingPhotoNotFound as exc:
        _push_alert("warning", str(exc))
    except PendingPhotoAlreadyProcessed as exc:
        _push_alert("warning", str(exc))
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("pending_photos_ui_force_ingest_failed", error=str(exc), exc_info=True)
        _push_alert("error", "Force Ingest failed. See logs for details.")
    finally:
        service.close()
        _invalidate_pending_cache()
        safe_rerun("pending_force_ingest")


def _render_row(entry: Dict[str, Any]) -> None:
    ttl_seconds = compute_ttl_seconds(entry["expires_at_utc"])
    ttl_state = classify_ttl(ttl_seconds)
    ttl_label = format_ttl_label(ttl_seconds)
    ref = entry["confirmation_token"][:6].upper()
    alias = entry.get("associate_alias") or "Unknown associate"
    bookmaker = entry.get("bookmaker_name") or "Unknown bookmaker"
    chat_id = entry.get("chat_id") or "N/A"
    message_id = entry.get("photo_message_id") or "N/A"
    overrides: List[str] = []
    if entry.get("stake_override"):
        overrides.append(
            f"Stake override: {entry.get('stake_override')} {entry.get('stake_currency') or entry.get('home_currency') or ''}".strip()
        )
    if entry.get("win_override"):
        overrides.append(
            f"Win override: {entry.get('win_override')} {entry.get('win_currency') or entry.get('stake_currency') or ''}".strip()
        )

    expired = ttl_state == TTLState.EXPIRED
    force_button_disabled = expired or not st.session_state.get("pending_force_toggle", False)

    row_container = st.container()
    with row_container:
        cols = st.columns([2.5, 2.5, 1.6, 1.4])
        with cols[0]:
            st.markdown(
                f"<div class='pending-text {ttl_state.value}'>"
                f"<strong>Ref #{ref}</strong><br/>"
                f"Chat <code>{chat_id}</code><br/>"
                f"Message <code>{message_id}</code>"
                f"</div>",
                unsafe_allow_html=True,
            )
        with cols[1]:
            st.markdown(
                f"<div class='pending-text {ttl_state.value}'>"
                f"<strong>{alias}</strong><br/>{bookmaker}"
                f"</div>",
                unsafe_allow_html=True,
            )
            if overrides:
                for line in overrides:
                    st.caption(line)
            else:
                st.caption("No manual overrides.")
        with cols[2]:
            expires_label = _format_timestamp(entry["expires_at_utc"])
            st.markdown(
                f"<div class='ttl-pill {ttl_state.value}'>{ttl_label}</div>",
                unsafe_allow_html=True,
            )
            st.caption(f"Auto discard at {expires_label}")
        with cols[3]:
            discard_dialog_key = f"pending_discard_{entry['id']}"
            if st.button(
                "Discard",
                key=f"discard_btn_{entry['id']}",
                type="secondary",
                disabled=expired,
                help="Immediately discard and delete the screenshot. Reason required.",
            ):
                open_dialog(discard_dialog_key)
            discard_reason = render_reason_dialog(
                key=discard_dialog_key,
                title=f"Discard Ref #{ref}",
                description="Provide a reason so the Telegram audit trail captures this discard.",
                text_label="Discard reason",
                confirm_label="Discard",
            )
            if discard_reason:
                _handle_discard(entry, discard_reason)

            force_dialog_key = f"pending_force_{entry['id']}"
            if st.button(
                "Force Ingest",
                key=f"force_btn_{entry['id']}",
                type="primary",
                disabled=force_button_disabled,
                help="Creates the bet immediately and queues OCR with a justification note.",
            ):
                open_dialog(force_dialog_key)
            justification = render_reason_dialog(
                key=force_dialog_key,
                title=f"Force Ingest Ref #{ref}",
                description="Explain why you are overriding the Telegram confirmation flow.",
                text_label="Justification",
                confirm_label="Force Ingest",
            )
            if justification:
                _handle_force_ingest(entry, justification)

        st.divider()


@fragment("pending_photos.table", run_every=1)
def _render_pending_table() -> None:
    entries = _load_pending_payload()
    if not entries:
        st.info("No pending Telegram photos right now. 🎉")
        return

    st.metric("Active Pending Photos", len(entries))
    for entry in entries:
        _render_row(entry)


def main() -> None:
    _configure_page()
    load_global_styles()

    _render_header()

    render_debug_toggle("Show fragment performance stats")
    _render_pending_table()
    render_debug_panel(expanded=False)


if __name__ == "__main__":
    main()
