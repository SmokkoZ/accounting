"""
Standalone Telegram navigation page for the Coverage Proof Outbox.

Reuses the shared outbox panel so operators can access the resend workflow
without hunting through the Surebets screen first.
"""

from __future__ import annotations

import streamlit as st

from src.ui.pages.coverage_proof_outbox_panel import render_coverage_proof_outbox
from src.ui.ui_components import load_global_styles

PAGE_TITLE = "Coverage Proof Outbox"
PAGE_ICON = ":material/outbox:"

st.set_page_config(page_title=PAGE_TITLE, page_icon=PAGE_ICON, layout="wide")
load_global_styles()

st.title(f"{PAGE_ICON} {PAGE_TITLE}")
st.caption("Monitor Telegram coverage proof deliveries and safely trigger resends.")

render_coverage_proof_outbox()
