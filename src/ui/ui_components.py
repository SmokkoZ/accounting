"""
Reusable UI helpers for Streamlit pages.

Provides a consistent global theme via CSS injection, compact metric display
helpers, and a simple card context manager to standardize layout primitives.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

import streamlit as st
from streamlit.errors import StreamlitAPIException

_STATE_KEY = "_global_styles_loaded"
_CSS_PATH = Path("src/ui/ui_styles.css")


def load_global_styles(force: bool = False) -> None:
    """
    Inject the shared CSS stylesheet into the current Streamlit run.

    The stylesheet is only loaded once per session unless ``force`` is True.
    """
    try:
        session_state = st.session_state
    except (RuntimeError, StreamlitAPIException):
        return

    if not force and session_state.get(_STATE_KEY):
        return

    if not _CSS_PATH.exists():
        st.warning(f"Global styles not found at '{_CSS_PATH}'.")
        return

    try:
        css = _CSS_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        st.error(f"Unable to read global styles: {exc}")
        return

    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
    session_state[_STATE_KEY] = True


def metric_compact(label: str, value: str, *, delta: Optional[str] = None) -> None:
    """
    Render a compact metric row suitable for dense dashboards.

    Args:
        label: Metric label to display.
        value: Primary metric value.
        delta: Optional delta text displayed muted to the right.
    """
    pieces = [
        '<div style="display:flex;gap:.6rem;color:#94a3b8;align-items:center;">',
        f'<span>{label}</span>',
        '<span style="color:#e5e7eb;font-weight:600;">{}</span>'.format(value),
    ]
    if delta:
        pieces.append(f'<span style="color:#64748b;font-size:.85rem;">{delta}</span>')
    pieces.append("</div>")
    st.markdown("".join(pieces), unsafe_allow_html=True)


@contextmanager
def card(
    title: Optional[str] = None,
    subtitle: Optional[str] = None,
    *,
    icon: Optional[str] = None,
) -> Iterator[None]:
    """
    Render content inside a styled card container.

    Args:
        title: Optional card title rendered as an H3.
        subtitle: Optional subtitle rendered as a caption.
        icon: Optional emoji/material icon prefix for the title.
    """
    load_global_styles()

    st.markdown('<div class="card">', unsafe_allow_html=True)
    if title:
        icon_prefix = f"{icon} " if icon else ""
        st.markdown(f"### {icon_prefix}{title}")
    if subtitle:
        st.caption(subtitle)
    try:
        yield
    finally:
        st.markdown("</div>", unsafe_allow_html=True)


__all__ = ["load_global_styles", "metric_compact", "card"]
