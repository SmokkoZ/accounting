"""
Telegram rate limiting dashboard.

Surfaces current cooldowns per multibook chat so operators know when it is
safe to resend coverage proof or other notifications.
"""

from __future__ import annotations

from typing import Any, Dict, List

import streamlit as st

from src.services.coverage_proof_service import CoverageProofService
from src.ui.pages.coverage_proof_outbox_panel import format_cooldown_label
from src.ui.ui_components import load_global_styles
from src.utils.logging_config import get_logger

PAGE_TITLE = "Rate Limiting"
PAGE_ICON = ":material/speed:"

logger = get_logger(__name__)

st.set_page_config(page_title=PAGE_TITLE, page_icon=PAGE_ICON, layout="wide")
load_global_styles()

st.title(f"{PAGE_ICON} {PAGE_TITLE}")
st.caption(
    "Live cooldown telemetry for Telegram coverage proof sends. "
    "Use this view to avoid rate-limit blocks before initiating manual resends."
)

service = CoverageProofService()
try:
    cooldowns = service.get_rate_limit_cooldowns()
except Exception as exc:
    st.error("Unable to load rate limit telemetry. Please retry in a moment.")
    logger.error("rate_limit_dashboard_load_failed", error=str(exc), exc_info=True)
    cooldowns = {}
finally:
    service.close()

limit = CoverageProofService.RATE_LIMIT_MESSAGES_PER_MINUTE
window = CoverageProofService.RATE_LIMIT_WINDOW_SECONDS
st.info(
    f"Telegram currently allows **{limit}** coverage-proof drops per chat every "
    f"**{window} seconds**. Cooldowns automatically expire once the rolling window clears."
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
                "Attempts (60s)": attempts,
                "Seconds Remaining": max(0, seconds_remaining),
                "Status": status,
            }
        )

    st.dataframe(
        rows,
        hide_index=True,
        use_container_width=True,
    )

st.caption(
    "Need more throughput? Consider staggering sends or splitting associates across multiple chats."
)
