"""
Telegram rate limiting dashboard.

Surfaces current cooldowns per multibook chat so operators know when it is
safe to resend coverage proof or other notifications while tuning thresholds.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import streamlit as st

from src.core.config import Config
from src.services.coverage_proof_service import CoverageProofService
from src.services.rate_limit_settings import (
    ChatRateLimitSettings,
    RateLimitSettingsStore,
)
from src.ui.helpers.streaming import show_error_toast, show_success_toast
from src.ui.pages.coverage_proof_outbox_panel import format_cooldown_label
from src.ui.ui_components import load_global_styles
from src.utils.logging_config import get_logger

PAGE_TITLE = "Rate Limiting"
PAGE_ICON = ":material/speed:"
MIN_INTERVAL_SECONDS = 10
MAX_INTERVAL_SECONDS = 300
MAX_MESSAGES_PER_INTERVAL = 60
MAX_BURST_ALLOWANCE = 10
PREVIEW_BADGE_STYLES = """
<style>
.rate-preview {
    border-radius: 8px;
    padding: 0.8rem;
    font-size: 0.9rem;
    background-color: rgba(16, 185, 129, 0.12);
    border: 1px solid rgba(16, 185, 129, 0.45);
    margin-bottom: 0.5rem;
}
.rate-preview--warn {
    background-color: rgba(248, 113, 113, 0.12);
    border-color: rgba(248, 113, 113, 0.55);
}
.rate-preview__value {
    font-weight: 600;
}
.rate-preview__meta {
    font-size: 0.8rem;
    opacity: 0.9;
}
.rate-preview__cap {
    font-size: 0.75rem;
    opacity: 0.75;
    margin-top: 0.25rem;
}
</style>
"""

logger = get_logger(__name__)
settings_store = RateLimitSettingsStore()


def _state_key(chat_id: str, field: str) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in (chat_id or "default"))
    return f"rate_limit_{safe}_{field}"


def _build_preview_badge(
    messages: int, interval: int, burst: int, per_chat_cap: float
) -> tuple[str, bool]:
    safe_limit = max(1, int(per_chat_cap * interval))
    per_second = messages / interval if interval else float(messages)
    within_cap = (messages + burst) <= safe_limit
    status_class = "ok" if within_cap else "warn"
    html = f"""
        <div class="rate-preview rate-preview--{status_class}">
            <div class="rate-preview__value">{messages} msg / {interval}s</div>
            <div class="rate-preview__meta">{per_second:.2f} msg/s · burst +{burst}</div>
            <div class="rate-preview__cap">Safe cap: {safe_limit} msg / {interval}s</div>
        </div>
    """
    return html, within_cap


def _render_profile_row(
    profile: ChatRateLimitSettings, per_chat_cap: float
) -> ChatRateLimitSettings:
    col_label, col_messages, col_interval, col_burst, col_preview = st.columns(
        [2.4, 1, 1, 1, 1.4]
    )
    col_label.markdown(f"**{profile.label}**\n`{profile.chat_id}`")

    msg_key = _state_key(profile.chat_id, "messages")
    interval_key = _state_key(profile.chat_id, "interval")
    burst_key = _state_key(profile.chat_id, "burst")

    messages = int(
        col_messages.number_input(
            "Messages",
            min_value=1,
            max_value=MAX_MESSAGES_PER_INTERVAL,
            value=profile.messages_per_interval,
            step=1,
            format="%d",
            key=msg_key,
            help="Messages allowed in the rolling window before cooldown.",
        )
    )
    interval = int(
        col_interval.number_input(
            "Interval (s)",
            min_value=MIN_INTERVAL_SECONDS,
            max_value=MAX_INTERVAL_SECONDS,
            value=profile.interval_seconds,
            step=5,
            format="%d",
            key=interval_key,
            help="Seconds that define the rolling rate-limit window.",
        )
    )
    burst = int(
        col_burst.number_input(
            "Burst",
            min_value=0,
            max_value=MAX_BURST_ALLOWANCE,
            value=profile.burst_allowance,
            step=1,
            format="%d",
            key=burst_key,
            help="Short-term buffer before service pauses sends.",
        )
    )

    preview_html, within_cap = _build_preview_badge(messages, interval, burst, per_chat_cap)
    col_preview.markdown(preview_html, unsafe_allow_html=True)
    if not within_cap:
        col_preview.caption("Adjust values to stay within Telegram's cap.")

    return ChatRateLimitSettings(
        chat_id=profile.chat_id,
        label=profile.label,
        messages_per_interval=messages,
        interval_seconds=interval,
        burst_allowance=burst,
    )


def _validate_profiles(
    profiles: List[ChatRateLimitSettings], per_chat_cap: float
) -> List[str]:
    errors: List[str] = []
    for profile in profiles:
        safe_limit = max(1, int(per_chat_cap * profile.interval_seconds))
        if profile.total_allowed > safe_limit:
            errors.append(
                f"{profile.label}: {profile.total_allowed} msg/{profile.interval_seconds}s "
                f"exceeds Telegram's safe cap of {safe_limit}."
            )
    return errors


def _resolve_operator_name() -> str:
    for key in ("operator_alias", "current_operator", "user", "username"):
        value = st.session_state.get(key)
        if value:
            return str(value)
    return "unknown"


def _default_profile(
    profiles: List[ChatRateLimitSettings],
) -> Optional[ChatRateLimitSettings]:
    if not profiles:
        return None
    return next((p for p in profiles if p.chat_id == "__default__"), profiles[0])


def _render_preview_pair(default_profile: Optional[ChatRateLimitSettings]) -> None:
    per_chat_cap = max(Config.TELEGRAM_PER_CHAT_RPS or 1.0, 1.0)
    col_global, col_chat = st.columns(2)
    global_badge = f"""
        <div class="rate-preview rate-preview--ok">
            <div class="rate-preview__value">{Config.TELEGRAM_MAX_RPS:.0f} msg/sec</div>
            <div class="rate-preview__meta">Telegram global recommendation</div>
            <div class="rate-preview__cap">Across all chats</div>
        </div>
    """
    col_global.markdown(global_badge, unsafe_allow_html=True)

    if default_profile:
        chat_badge, _ = _build_preview_badge(
            default_profile.messages_per_interval,
            default_profile.interval_seconds,
            default_profile.burst_allowance,
            per_chat_cap,
        )
        col_chat.markdown(chat_badge, unsafe_allow_html=True)
    else:
        col_chat.info("No default multibook chat profile configured.")


st.set_page_config(page_title=PAGE_TITLE, page_icon=PAGE_ICON, layout="wide")
load_global_styles()
st.markdown(PREVIEW_BADGE_STYLES, unsafe_allow_html=True)

st.title(f"{PAGE_ICON} {PAGE_TITLE}")
st.caption(
    "Live cooldown telemetry for Telegram coverage proof sends. "
    "Use this view to avoid rate-limit blocks before initiating manual resends."
)

service = CoverageProofService()
cooldowns: Dict[str, Dict[str, Any]] = {}
rate_limit_profiles: List[ChatRateLimitSettings] = []
try:
    cooldowns = service.get_rate_limit_cooldowns()
    rate_limit_profiles = service.get_rate_limit_profiles()
except Exception as exc:
    st.error("Unable to load rate limit telemetry. Please retry in a moment.")
    logger.error("rate_limit_dashboard_load_failed", error=str(exc), exc_info=True)
finally:
    service.close()

per_chat_cap = max(Config.TELEGRAM_PER_CHAT_RPS or 1.0, 1.0)
st.info(
    f"Telegram recommends staying near **{per_chat_cap:.0f} msg/sec per chat** and "
    f"**{Config.TELEGRAM_MAX_RPS:.0f} msg/sec globally**. "
    "Cooldowns expire automatically once the rolling window clears."
)

if not cooldowns:
    st.success("All Telegram chats are ready. No cooldowns active.")
else:
    st.metric("Chats Cooling Down", len(cooldowns))
    rows: List[Dict[str, Any]] = []
    for chat_id, data in sorted(cooldowns.items(), key=lambda item: item[0] or ""):
        seconds_remaining = int(data.get("seconds_remaining", 0))
        attempts = int(data.get("attempt_count", 0))
        status = "Ready" if seconds_remaining <= 0 else format_cooldown_label(seconds_remaining)
        rows.append(
            {
                "Chat ID": chat_id or "Unregistered",
                "Attempts (window)": attempts,
                "Seconds Remaining": max(0, seconds_remaining),
                "Status": status,
            }
        )

    st.dataframe(
        rows,
        hide_index=True,
        width='stretch',
    )

st.caption(
    "Need more throughput? Consider staggering sends or splitting associates across multiple chats."
)

st.divider()
st.subheader("Coverage Proof Thresholds")

default_profile = _default_profile(rate_limit_profiles)
_render_preview_pair(default_profile)

if not rate_limit_profiles:
    st.warning(
        "No chat thresholds detected. Define profiles in CoverageProofService to enable editing."
    )
else:
    st.caption(
        "Tune chat-specific throughput while keeping Telegram's caps in view. "
        "Burst allowance adds short headroom before the service queues sends."
    )
    with st.form("rate_limit_settings_form"):
        updated_profiles = [
            _render_profile_row(profile, per_chat_cap) for profile in rate_limit_profiles
        ]
        submitted = st.form_submit_button(
            "Save rate limit changes",
            width='stretch',
            type="primary",
        )

    if submitted:
        validation_errors = _validate_profiles(updated_profiles, per_chat_cap)
        if validation_errors:
            for error in validation_errors:
                st.error(error)
            show_error_toast("Fix the highlighted caps before saving.")
        else:
            try:
                settings_store.save(updated_profiles)
            except Exception as exc:  # pragma: no cover - Streamlit runtime feedback
                logger.error("rate_limit_settings_save_failed", error=str(exc), exc_info=True)
                st.error("Unable to save settings. Please retry.")
                show_error_toast("Save failed. Check logs for details.")
            else:
                show_success_toast(
                    "Rate limits saved. New thresholds apply to the next coverage proof send."
                )
                operator = _resolve_operator_name()
                logger.info(
                    "rate_limit_settings_updated_by_operator",
                    operator=operator,
                    profile_count=len(updated_profiles),
                )
                rate_limit_profiles = updated_profiles
                st.rerun()
