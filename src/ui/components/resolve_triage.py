"""
Resolve queue triage helpers with confidence indicators and bulk actions.
"""

from __future__ import annotations

from typing import Iterable, List, Optional

import pandas as pd
import streamlit as st

HIGH_CONFIDENCE = 0.8
MEDIUM_CONFIDENCE = 0.5


def render_confidence_indicator(confidence: Optional[float]) -> str:
    """Return emoji-labelled confidence indicator."""
    if confidence is None:
        return "⚪ Unknown"
    try:
        value = float(confidence)
    except (TypeError, ValueError):
        return "⚪ Unknown"

    if value >= HIGH_CONFIDENCE:
        return f"🟢 High ({value:.0%})"
    if value >= MEDIUM_CONFIDENCE:
        return f"🟡 Medium ({value:.0%})"
    return f"🔴 Low ({value:.0%})"


def render_resolve_queue_with_triage(
    events_df: pd.DataFrame,
    *,
    selection_key: str = "resolve_triage",
    bulk_threshold: float = HIGH_CONFIDENCE,
) -> List[int]:
    """
    Render the resolve queue table with confidence indicators and bulk controls.

    Returns:
        List of bet IDs selected for bulk processing (empty list when none).
    """
    if events_df.empty:
        st.success("All events are resolved. 🎉")
        return []

    display_df = events_df.copy()
    display_df["Conf"] = display_df["confidence_score"].apply(render_confidence_indicator)

    column_order = [
        "bet_id",
        "associate",
        "bookmaker",
        "event_name",
        "odds",
        "stake",
        "market_code",
        "side",
        "period_scope",
        "line_value",
        "kickoff_time_utc",
        "Conf",
        "bet_status",
    ]
    column_labels = {
        "bet_id": "Bet ID",
        "associate": "Associate",
        "bookmaker": "Bookmaker",
        "event_name": "Event",
        "odds": "Odds",
        "stake": "Stake",
        "market_code": "Market",
        "side": "Side",
        "period_scope": "Period",
        "line_value": "Line",
        "kickoff_time_utc": "Kickoff",
        "Conf": "Conf",
        "bet_status": "Status",
    }

    render_df = display_df[column_order].rename(columns=column_labels)

    st.dataframe(
        render_df,
        hide_index=True,
        width="stretch",
    )

    high_conf_df = display_df[
        display_df["confidence_score"].astype(float) >= bulk_threshold
    ]
    if high_conf_df.empty:
        st.caption("No high-confidence events available for bulk actions.")
        return []

    selection_state_key = f"{selection_key}__selected_ids"
    with st.expander(
        f"Bulk Actions ({len(high_conf_df)} high-confidence events)", expanded=False
    ):
        selectable_ids = high_conf_df["bet_id"].tolist()
        selected = st.multiselect(
            "Select events to mark as Auto-OK",
            selectable_ids,
            default=selectable_ids,
            key=selection_state_key,
            help="Only events above the confidence threshold are eligible.",
        )
        if st.button(
            "Bulk mark as Auto-OK",
            type="primary",
            disabled=not selected,
            width="stretch",
            key=f"{selection_key}__bulk_button",
        ):
            return list(selected)

    return []


__all__ = ["render_confidence_indicator", "render_resolve_queue_with_triage"]
