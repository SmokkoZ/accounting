"""
Resolve queue triage helpers with confidence indicators and bulk actions.
"""

from __future__ import annotations

from typing import Iterable, List, Optional

import pandas as pd
import streamlit as st

from src.ui.utils.formatters import format_utc_datetime_compact

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
    display_df["confidence_display"] = display_df["confidence_score"].apply(
        render_confidence_indicator
    )
    if "created_at_utc" in display_df.columns:
        display_df["created_local"] = display_df["created_at_utc"].apply(
            lambda value: format_utc_datetime_compact(value) if value else "—"
        )

    st.dataframe(
        display_df,
        column_config={
            "confidence_display": st.column_config.TextColumn(
                "Confidence", help="LLM extraction confidence"
            ),
            "alias_evidence": st.column_config.TextColumn(
                "Alias Evidence", help="Evidence for canonical alias"
            ),
            "created_local": st.column_config.TextColumn("Created (Perth)"),
        },
        hide_index=True,
        use_container_width=True,
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
            use_container_width=True,
            key=f"{selection_key}__bulk_button",
        ):
            return list(selected)

    return []


__all__ = ["render_confidence_indicator", "render_resolve_queue_with_triage"]
