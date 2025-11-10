"""
Pagination helpers for Streamlit tables.

Handles shared session-state management, LIMIT/OFFSET helpers, and count
queries so every table follows the same UX (25/50/100 rows, prev/next,
and optional jump-to-page control).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence, Tuple

import streamlit as st

from src.ui.cache import query_df
from src.ui.utils.state_management import safe_rerun

DEFAULT_PAGE_SIZES: Tuple[int, int, int] = (25, 50, 100)


@dataclass(slots=True)
class Pagination:
    table_key: str
    page: int
    page_size: int
    total_rows: int

    @property
    def limit(self) -> int:
        return self.page_size

    @property
    def offset(self) -> int:
        return max(0, (self.page - 1) * self.page_size)

    @property
    def total_pages(self) -> int:
        if self.total_rows <= 0:
            return 1
        return max(1, math.ceil(self.total_rows / self.page_size))

    @property
    def start_row(self) -> int:
        if self.total_rows == 0:
            return 0
        return self.offset + 1

    @property
    def end_row(self) -> int:
        if self.total_rows == 0:
            return 0
        return min(self.total_rows, self.offset + self.page_size)

    @property
    def has_prev(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages


def _state_key(table_key: str, suffix: str) -> str:
    clean_key = table_key.replace(" ", "_")
    return f"{clean_key}__pagination_{suffix}"


def paginate(
    table_key: str,
    total_rows: int,
    *,
    default_page_size: int = 25,
    page_size_options: Sequence[int] = DEFAULT_PAGE_SIZES,
    label: str = "rows",
) -> Pagination:
    """
    Render pagination controls + return the computed pagination metadata.
    """

    if not page_size_options:
        raise ValueError("page_size_options must include at least one value")

    unique_options = tuple(dict.fromkeys(page_size_options))
    if default_page_size not in unique_options:
        unique_options = (default_page_size,) + unique_options

    size_key = _state_key(table_key, "size")
    page_key = _state_key(table_key, "page")
    goto_key = _state_key(table_key, "goto")

    session = st.session_state
    if size_key not in session:
        session[size_key] = default_page_size
    if page_key not in session:
        session[page_key] = 1
    if goto_key not in session:
        session[goto_key] = 1

    prev_size = session[size_key]
    default_index = unique_options.index(prev_size) if prev_size in unique_options else 0
    col_size, col_goto, col_prev, col_next = st.columns([1.2, 1.2, 1.0, 1.0])

    with col_size:
        st.selectbox(
            "Rows per page",
            options=unique_options,
            index=default_index,
            key=size_key,
            label_visibility="collapsed",
        )
        st.caption("Rows per page")

    if session[size_key] != prev_size:
        session[page_key] = 1
        session[goto_key] = 1
        safe_rerun(f"{table_key}_page_size")

    pagination = Pagination(
        table_key=table_key,
        page=max(1, session[page_key]),
        page_size=int(session[size_key]),
        total_rows=total_rows,
    )
    previous_page = session[page_key]
    session[page_key] = min(pagination.page, pagination.total_pages)
    if session[page_key] != previous_page:
        session[goto_key] = session[page_key]
    pagination = Pagination(
        table_key=table_key,
        page=session[page_key],
        page_size=pagination.page_size,
        total_rows=total_rows,
    )
    summary_text = (
        "No rows to display"
        if pagination.total_rows == 0
        else f"Showing {pagination.start_row}-{pagination.end_row} of "
        f"{pagination.total_rows} {label}"
    )
    goto_max_value = max(1, pagination.total_pages)
    session[goto_key] = min(max(1, session[goto_key]), goto_max_value)

    with col_goto:
        target = st.number_input(
            "Go to page",
            min_value=1,
            max_value=goto_max_value,
            value=session[goto_key],
            step=1,
            key=goto_key,
            label_visibility="collapsed",
        )
        st.caption("Go to page")
        if goto_max_value > 1 and int(target) != pagination.page:
            session[page_key] = int(target)
            session[goto_key] = session[page_key]
            safe_rerun(f"{table_key}_goto")

    with col_prev:
        disabled = not pagination.has_prev
        if st.button("◀ Prev", key=_state_key(table_key, "prev"), disabled=disabled, width="stretch"):
            session[page_key] = max(1, pagination.page - 1)
            session[goto_key] = session[page_key]
            safe_rerun(f"{table_key}_prev")

    with col_next:
        disabled = not pagination.has_next
        if st.button("Next ▶", key=_state_key(table_key, "next"), disabled=disabled, width="stretch"):
            session[page_key] = min(pagination.total_pages, pagination.page + 1)
            session[goto_key] = session[page_key]
            safe_rerun(f"{table_key}_next")

    st.caption(summary_text)

    return pagination


def apply_pagination(sql: str, pagination: Pagination) -> Tuple[str, Tuple[int, int]]:
    """
    Append ``LIMIT/OFFSET`` placeholders to ``sql`` and return extra params.
    """
    paginated_sql = f"{sql.strip()} LIMIT ? OFFSET ?"
    return paginated_sql, (pagination.limit, pagination.offset)


def get_total_count(count_sql: str, params: Sequence[object] | None = None) -> int:
    """
    Execute a cached count query and return the integer result.
    """
    df = query_df(count_sql, params=params or ())
    if df.empty:
        return 0
    first_value = df.iloc[0, 0]
    try:
        return int(first_value)
    except (TypeError, ValueError):
        return 0


def paginate_params(params: Iterable[object], pagination: Pagination) -> Tuple[object, ...]:
    """
    Utility to append limit/offset values to an existing params iterable.
    """
    return (*params, pagination.limit, pagination.offset)


__all__ = [
    "DEFAULT_PAGE_SIZES",
    "Pagination",
    "apply_pagination",
    "get_total_count",
    "paginate",
    "paginate_params",
]
