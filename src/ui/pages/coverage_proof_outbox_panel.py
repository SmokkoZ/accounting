"""
Shared Coverage Proof Outbox panel for Telegram-focused pages.

Provides a reusable renderer so both the Surebets view and the dedicated
Telegram navigation page can surface the exact same controls, cooldown
messaging, and resend actions.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import streamlit as st

from src.services.coverage_proof_service import CoverageProofService
from src.ui.utils.formatters import format_utc_datetime_local
from src.ui.utils.state_management import safe_rerun
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

RATE_LIMIT_HEALTH_BADGES: Dict[str, tuple[str, str]] = {
    "ready": (":material/task_alt:", "Safe"),
    "queued": (":material/schedule:", "Queued"),
    "blocked": (":material/block:", "Blocked"),
}

DELIVERY_STATUS_BADGES: Dict[str, tuple[str, str]] = {
    "sent": (":material/check_circle:", "Sent"),
    "failed": (":material/error:", "Failed"),
    "pending": (":material/schedule:", "Pending"),
}

OUTBOX_RESEND_STATE_PREFIX = "coverage_outbox_resend_ctx_"
LEGACY_OUTBOX_RESEND_PREFIX = "coverage_outbox_resend_"


def format_cooldown_label(seconds: Optional[int]) -> str:
    """Convert cooldown seconds into a short human readable label."""
    if seconds is None or seconds <= 0:
        return "Ready"
    seconds = int(seconds)
    minutes, remainder = divmod(seconds, 60)
    if minutes:
        return f"{minutes}m {remainder:02d}s"
    return f"{remainder}s"


def render_coverage_proof_outbox(limit: Optional[int] = 50) -> None:
    """Render Coverage Proof outbox with cooldown-aware resend controls."""
    st.markdown("### Coverage Proof Outbox")
    st.caption(
        "Review the latest Telegram deliveries from `multibook_message_log` and resend them safely."
    )
    st.info(
        ":material/info: Telegram allows roughly 10 coverage-proof drops per chat per minute "
        "(see `docs/front-end-spec.md`). Resend buttons stay disabled while the cooldown resets "
        "so we do not trip rate limits."
    )

    service = CoverageProofService()
    try:
        entries = service.get_outbox_entries(limit=limit)
    except Exception as exc:
        st.error("Failed to load Coverage Proof outbox. Please try again.")
        logger.error("coverage_proof_outbox_load_error", error=str(exc), exc_info=True)
        return
    finally:
        service.close()

    logger.info("coverage_proof_outbox_render", rows=len(entries), limit=limit)

    if not entries:
        st.caption("No coverage proof deliveries have been logged yet.")
        return

    header_cols = st.columns([2.4, 1.4, 1.3, 1.4, 1.3, 1.2, 1.2, 1.1])
    headers = [
        "Associate / Surebet",
        "Chat ID",
        "Message ID",
        "Status",
        "Last Attempt",
        "Next Send",
        "Rate Limit",
        "Actions",
    ]
    for column, label in zip(header_cols, headers):
        column.markdown(f"**{label}**")

    for entry in entries:
        row_cols = st.columns([2.4, 1.4, 1.3, 1.4, 1.3, 1.2, 1.2, 1.1])
        associate_text = (
            f"**{entry['associate_alias']}**<br/>"
            f"<span style='color:var(--text-muted, #666);'>Surebet #{entry['surebet_id']}</span>"
        )
        row_cols[0].markdown(associate_text, unsafe_allow_html=True)
        row_cols[1].code(entry.get("chat_id") or "-")
        row_cols[2].code(entry.get("message_id") or "-")

        status_icon, status_label = DELIVERY_STATUS_BADGES.get(
            entry.get("status", "sent"), (":material/info:", entry.get("status", "").title())
        )
        status_markup = f"{status_icon} {status_label}"
        if entry.get("error_message"):
            status_markup += f"<br/><span style='color:#d04545'>{entry['error_message']}</span>"
        row_cols[3].markdown(status_markup, unsafe_allow_html=True)

        last_attempt = entry.get("last_attempt")
        last_attempt_display = (
            format_utc_datetime_local(last_attempt) if last_attempt else "-"
        )
        row_cols[4].markdown(last_attempt_display)

        cooldown_seconds = entry.get("seconds_until_next_send") or 0
        cooldown_prefix = ":material/hourglass_bottom:" if cooldown_seconds else ":material/check:"
        row_cols[5].markdown(
            f"{cooldown_prefix} {format_cooldown_label(cooldown_seconds)}"
        )

        health_icon, health_label = RATE_LIMIT_HEALTH_BADGES.get(
            entry.get("rate_limit_health", "ready"),
            (":material/info:", entry.get("rate_limit_health", 'Unknown').title()),
        )
        row_cols[6].markdown(f"{health_icon} {health_label}")

        disabled = cooldown_seconds > 0
        disabled_help = (
            "Telegram cooldown active - resend available when timer reaches Ready."
            if disabled
            else "Resend coverage proof using resend=True."
        )
        button_key = f"coverage_outbox_resend_btn_{entry['log_id']}"
        triggered = row_cols[7].button(
            "Resend",
            key=button_key,
            disabled=disabled,
            help=disabled_help,
        )
        if triggered:
            state_key = f"{OUTBOX_RESEND_STATE_PREFIX}{entry['log_id']}"
            st.session_state[state_key] = {
                "log_id": entry["log_id"],
                "surebet_id": entry["surebet_id"],
                "associate_alias": entry["associate_alias"],
            }
            safe_rerun()


__all__ = [
    "render_coverage_proof_outbox",
    "OUTBOX_RESEND_STATE_PREFIX",
    "LEGACY_OUTBOX_RESEND_PREFIX",
    "RATE_LIMIT_HEALTH_BADGES",
    "DELIVERY_STATUS_BADGES",
    "format_cooldown_label",
]
