"""
Primary dashboard surface for the Surebet Accounting System.

Demonstrates modern Streamlit primitives (fragments, status blocks, toasts,
page links) while falling back gracefully on older runtimes.
"""

from __future__ import annotations

import random
from datetime import datetime
from typing import Iterable

import streamlit as st

from src.ui.helpers.fragments import fragment
from src.ui.helpers.streaming import show_info_toast, status_with_steps, stream_with_fallback
from src.ui.utils.navigation_links import render_navigation_link
from src.ui.ui_components import card, load_global_styles, metric_compact

load_global_styles()

PAGE_TITLE = "Dashboard"
PAGE_ICON = ":material/monitoring:"

st.title(f"{PAGE_ICON} {PAGE_TITLE}")
st.caption(
    "Realtime view of key surebet metrics. Values refresh automatically when "
    "data sources update."
)


def _generate_metrics() -> Iterable[tuple[str, str, str]]:
    """Return demo metrics until backend integration is wired."""
    return (
        ("Active Associates", f"{random.randint(18, 24)}", "+2 vs last week"),
        ("Open Surebets", f"{random.randint(45, 62)}", "-4 vs yesterday"),
        ("Pending Settlements", f"{random.randint(5, 12)}", "+1 vs SLA threshold"),
    )


for _ in status_with_steps(
    "Fetching latest ledger snapshots...",
    [("Load snapshots", lambda: None)],
    expanded=False,
):
    pass


def _render_metrics_block() -> None:
    with card("Key Metrics", "Live operational stats", icon=":material/monitoring:"):
        for name, value, delta in _generate_metrics():
            metric_compact(name, value, delta=delta)


@fragment("dashboard.metrics", run_every=30)
def render_metrics_fragment() -> None:
    _render_metrics_block()


render_metrics_fragment()


st.divider()

col_activity, col_shortcuts = st.columns([3, 1])

with col_activity:
    st.subheader("Activity Stream")

    def _activity_feed() -> Iterable[str]:
        events = [
            "Checking bookmaker balances...",
            "Syncing telegram queue...",
            "Refreshing settlement projections...",
            "Recomputing exposure deltas...",
        ]
        for event in events:
            yield f"- {event}\n"

    stream_with_fallback(_activity_feed, header=":material/dvr: Live log output")

with col_shortcuts:
    st.subheader("Shortcuts")

    render_navigation_link(
        "pages/8_associate_operations.py",
        label="Associate Hub",
        icon=":material/groups_3:",
        help_text="Open 'Associate Operations Hub' from the sidebar.",
    )
    render_navigation_link(
        "pages/6_reconciliation.py",
        label="Reconciliation",
        icon=":material/account_balance:",
        help_text="Use sidebar navigation when page links are unavailable.",
    )
    render_navigation_link(
        "pages/2_verified_bets.py",
        label="Surebets",
        icon=":material/target:",
    )

    if st.button("Show Tip", key="dashboard_tip"):
        show_info_toast("Use keyboard shortcut R to reset filters in the Associate Hub.")


st.divider()
st.caption(f"Dashboard refreshed at {datetime.now():%Y-%m-%d %H:%M:%S}.")
