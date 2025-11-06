"""
Helpers for rendering navigation cross-links with feature flag awareness.

These utilities keep `st.page_link` usage centralized so that we gracefully
degrade on runtimes that do not provide modern navigation primitives.
"""

from __future__ import annotations

import streamlit as st

from src.ui.utils.feature_flags import has


def render_navigation_link(
    script: str,
    *,
    label: str,
    icon: str,
    help_text: str | None = None,
) -> None:
    """Render a contextual navigation link with fallback guidance."""
    if has("page_link"):
        st.page_link(script, label=label, icon=icon)
    else:
        fallback = help_text or f"Use the sidebar navigation to open '{label}'."
        st.caption(fallback)


__all__ = ["render_navigation_link"]
