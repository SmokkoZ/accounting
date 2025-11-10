"""Standalone Surebets summary page."""

import streamlit as st

from src.ui.ui_components import load_global_styles
from src.ui.pages.surebets_components import render_surebets_summary_page

PAGE_TITLE = "Surebets Summary"
PAGE_ICON = ":material/target:"

st.set_page_config(page_title=PAGE_TITLE, layout="wide")
load_global_styles()

st.title(f"{PAGE_ICON} {PAGE_TITLE}")
render_surebets_summary_page()
