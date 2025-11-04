"""
Primary dashboard surface for the Surebet Accounting System.

Demonstrates modern Streamlit primitives (fragments, status blocks, toasts,
page links) while falling back gracefully on older runtimes.
"""

from __future__ import annotations

import random
import time
from datetime import datetime
from typing import Iterable

import streamlit as st

from src.ui.utils.feature_flags import has

st.title("Operations Overview")
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


if has("status"):
    with st.status("Fetching latest ledger snapshots...", expanded=False) as status:
        time.sleep(0.1)
        status.update(label="Snapshots loaded", state="complete", expanded=False)
else:
    st.info("Snapshots refresh whenever filters or inputs change.")


def _render_metrics_block() -> None:
    cols = st.columns(3)
    for col, (name, value, delta) in zip(cols, _generate_metrics()):
        col.metric(name, value, delta)


if has("fragment"):
    @st.fragment(run_every=30)
    def render_metrics_fragment() -> None:
        _render_metrics_block()

    render_metrics_fragment()
else:
    _render_metrics_block()


st.divider()

col_activity, col_shortcuts = st.columns([3, 1])

with col_activity:
    st.subheader("Activity Stream")

    if has("write_stream"):

        def _activity_feed() -> Iterable[str]:
            events = [
                "Checking bookmaker balances...",
                "Syncing telegram queue...",
                "Refreshing settlement projections...",
                "Recomputing exposure deltas...",
            ]
            for event in events:
                yield f"- {event}\n"
                time.sleep(0.1)

        st.write_stream(_activity_feed())
    else:
        st.caption(
            "Streamed updates appear here when newer Streamlit runtimes are available."
        )
        st.write(
            "- Checking bookmaker balances...\n"
            "- Syncing telegram queue...\n"
            "- Refreshing settlement projections..."
        )

with col_shortcuts:
    st.subheader("Shortcuts")
    if has("page_link"):
        st.page_link(
            "pages/8_associate_operations.py",
            label="Associate Hub",
            icon=":material/groups_3:",
        )
        st.page_link(
            "pages/6_reconciliation.py",
            label="Reconciliation",
            icon=":material/account_balance:",
        )
        st.page_link(
            "pages/2_verified_bets.py",
            label="Surebets",
            icon=":material/target:",
        )
    else:
        st.write("Use sidebar navigation when quick links are unavailable.")

    if has("toast") and st.button("Show Tip"):
        st.toast("Use keyboard shortcut R to reset filters in the Associate Hub.")


st.divider()
st.caption(f"Dashboard refreshed at {datetime.now():%Y-%m-%d %H:%M:%S}.")
