"""
Filter bar components for the Associate Operations Hub.

Provides persistent search, multi-select filters, and sorting with session
state management. Favour ASCII strings so the UI renders consistently across
environments with different encodings.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

import streamlit as st

from src.repositories.associate_hub_repository import AssociateHubRepository
from src.ui.utils.state_management import safe_rerun

ADMIN_LABELS: Dict[bool, str] = {True: "Admin", False: "Non-Admin"}
STATUS_LABELS: Dict[bool, str] = {True: "Active", False: "Inactive"}


def _labels_from_state(values: Iterable[bool], mapping: Dict[bool, str]) -> List[str]:
    """Convert stored boolean flags into display labels."""
    return [mapping[value] for value in values if value in mapping]


def _flags_from_selection(selection: Iterable[str], mapping: Dict[bool, str]) -> List[bool]:
    """Convert selected labels back into ordered boolean flags."""
    labels_to_flags = {label: flag for flag, label in mapping.items()}
    seen: List[bool] = []
    for label in selection:
        flag = labels_to_flags.get(label)
        if flag is not None and flag not in seen:
            seen.append(flag)
    return seen


def get_filter_state() -> Dict[str, Any]:
    """Read the current filter state from Streamlit session state."""
    return {
        "search": st.session_state.get("hub_search", ""),
        "admin_filter": st.session_state.get("hub_admin_filter", []),
        "associate_status_filter": st.session_state.get("hub_associate_status_filter", []),
        "bookmaker_status_filter": st.session_state.get("hub_bookmaker_status_filter", []),
        "currency_filter": st.session_state.get("hub_currency_filter", []),
        "sort_by": st.session_state.get("hub_sort_by", "alias_asc"),
        "page": st.session_state.get("hub_page", 0),
        "page_size": st.session_state.get("hub_page_size", 25),
    }


def update_filter_state(**kwargs: Any) -> None:
    """Persist provided filter values into Streamlit session state."""
    mappings = {
        "search": "hub_search",
        "admin_filter": "hub_admin_filter",
        "associate_status_filter": "hub_associate_status_filter",
        "bookmaker_status_filter": "hub_bookmaker_status_filter",
        "currency_filter": "hub_currency_filter",
        "sort_by": "hub_sort_by",
        "page": "hub_page",
        "page_size": "hub_page_size",
    }

    for key, value in kwargs.items():
        session_key = mappings.get(key)
        if session_key:
            st.session_state[session_key] = value


def render_filters(repository: AssociateHubRepository) -> Tuple[Dict[str, Any], bool]:
    """Render the filter bar and return the updated state plus refresh flag."""
    current_state = get_filter_state()
    should_refresh = False
    active_filter_count = get_active_filters_count(current_state)

    with st.container():
        st.subheader("Filters & Search")

        top_cols = st.columns([3, 1, 1])

        with top_cols[0]:
            search_value = st.text_input(
                "Search Associates",
                value=current_state["search"],
                key="hub_search_input",
                placeholder="Alias, bookmaker, or chat ID",
                help="Searches associate aliases, bookmaker names, and Telegram chat IDs.",
            )
            if search_value != current_state["search"]:
                update_filter_state(search=search_value, page=0)
                should_refresh = True

        with top_cols[1]:
            metric_delta = (
                "Filters narrow the list" if active_filter_count else "Showing all associates"
            )
            st.metric("Active filters", active_filter_count, delta=metric_delta)
            if active_filter_count:
                st.caption("Reset filters to broaden the view.")

        with top_cols[2]:
            if st.button(
                "Reset Filters",
                key="hub_reset_filters",
                help="Clear every filter and re-run the listing.",
            ):
                update_filter_state(
                    search="",
                    admin_filter=[],
                    associate_status_filter=[],
                    bookmaker_status_filter=[],
                    currency_filter=[],
                    sort_by="alias_asc",
                    page=0,
                )
                should_refresh = True
                safe_rerun()

        st.divider()

        filter_cols = st.columns(3)

        with filter_cols[0]:
            admin_selection = st.multiselect(
                "Admin Status",
                options=list(ADMIN_LABELS.values()),
                default=_labels_from_state(current_state["admin_filter"], ADMIN_LABELS),
                key="hub_admin_filter_select",
                help="Filter by whether the associate has admin privileges.",
            )
            admin_filter = _flags_from_selection(admin_selection, ADMIN_LABELS)
            if admin_filter != current_state["admin_filter"]:
                update_filter_state(admin_filter=admin_filter, page=0)
                should_refresh = True

        with filter_cols[1]:
            associate_selection = st.multiselect(
                "Associate Status",
                options=list(STATUS_LABELS.values()),
                default=_labels_from_state(current_state["associate_status_filter"], STATUS_LABELS),
                key="hub_associate_status_filter_select",
                help="Filter by whether the associate is active.",
            )
            associate_filter = _flags_from_selection(associate_selection, STATUS_LABELS)
            if associate_filter != current_state["associate_status_filter"]:
                update_filter_state(associate_status_filter=associate_filter, page=0)
                should_refresh = True

        with filter_cols[2]:
            bookmaker_selection = st.multiselect(
                "Bookmaker Status",
                options=list(STATUS_LABELS.values()),
                default=_labels_from_state(current_state["bookmaker_status_filter"], STATUS_LABELS),
                key="hub_bookmaker_status_filter_select",
                help="Filter by whether any bookmaker mapped to the associate is active.",
            )
            bookmaker_filter = _flags_from_selection(bookmaker_selection, STATUS_LABELS)
            if bookmaker_filter != current_state["bookmaker_status_filter"]:
                update_filter_state(bookmaker_status_filter=bookmaker_filter, page=0)
                should_refresh = True

        control_cols = st.columns([1, 1, 1, 1])

        with control_cols[0]:
            currency_cache_key = "hub_currency_options"
            if currency_cache_key not in st.session_state:
                try:
                    rows = repository.db.execute(
                        "SELECT DISTINCT home_currency FROM associates "
                        "WHERE home_currency IS NOT NULL ORDER BY home_currency"
                    ).fetchall()
                    st.session_state[currency_cache_key] = [row[0] for row in rows]
                except Exception:
                    st.session_state[currency_cache_key] = []

            currencies = st.session_state[currency_cache_key]
            currency_selection = st.multiselect(
                "Currencies",
                options=currencies,
                default=current_state["currency_filter"],
                key="hub_currency_filter_select",
                help="Filter associates by their home currency.",
            )
            if currency_selection != current_state["currency_filter"]:
                update_filter_state(currency_filter=currency_selection, page=0)
                should_refresh = True

        sort_options = {
            "Alias (A-Z)": "alias_asc",
            "Alias (Z-A)": "alias_desc",
            "Delta (High-Low)": "delta_desc",
            "Delta (Low-High)": "delta_asc",
            "Active Bookmakers": "bookmaker_active_desc",
        }
        sort_labels = list(sort_options.keys())
        current_sort_label = next(
            (label for label, value in sort_options.items() if value == current_state["sort_by"]),
            "Alias (A-Z)",
        )
        selected_sort_label = current_sort_label

        with control_cols[1]:
            selected_label = st.selectbox(
                "Sort By",
                options=sort_labels,
                index=sort_labels.index(current_sort_label),
                key="hub_sort_by_select",
                help="Sort order for the associate listing.",
            )
            selected_sort_label = selected_label
            if sort_options[selected_label] != current_state["sort_by"]:
                update_filter_state(sort_by=sort_options[selected_label], page=0)
                should_refresh = True

        with control_cols[2]:
            page_size_options = [10, 25, 50, 100]
            page_size = st.selectbox(
                "Page Size",
                options=page_size_options,
                index=page_size_options.index(current_state["page_size"]),
                key="hub_page_size_select",
                help="Number of associates to show per page.",
            )
            if page_size != current_state["page_size"]:
                update_filter_state(page_size=page_size, page=0)
                should_refresh = True

        with control_cols[3]:
            st.caption(f"Page: {current_state['page'] + 1}")

        st.divider()

        active_filter_labels = []

        if current_state["search"].strip():
            active_filter_labels.append(f"Search: '{current_state['search']}'")

        if current_state["admin_filter"]:
            admin_labels = _labels_from_state(current_state["admin_filter"], ADMIN_LABELS)
            active_filter_labels.append(f"Admin: {', '.join(admin_labels)}")

        if current_state["associate_status_filter"]:
            status_labels = _labels_from_state(current_state["associate_status_filter"], STATUS_LABELS)
            active_filter_labels.append(f"Status: {', '.join(status_labels)}")

        if current_state["bookmaker_status_filter"]:
            bookmaker_labels = _labels_from_state(current_state["bookmaker_status_filter"], STATUS_LABELS)
            active_filter_labels.append(f"Bookmakers: {', '.join(bookmaker_labels)}")

        if current_state["currency_filter"]:
            active_filter_labels.append(f"Currencies: {', '.join(current_state['currency_filter'])}")

        if current_state["sort_by"] != "alias_asc":
            active_filter_labels.append(f"Sort: {selected_sort_label}")

        if active_filter_labels:
            st.caption("Active filters:")
            st.caption(" | ".join(active_filter_labels))

    updated_state = get_filter_state()
    return updated_state, should_refresh


def render_pagination_info(total_count: int, current_state: Dict[str, Any]) -> None:
    """Render pagination helpers beneath the listing."""
    if total_count == 0:
        st.warning("No associates found. Adjust or reset filters to broaden the search.")
        return

    page_size = current_state["page_size"]
    current_page = current_state["page"]
    total_pages = max((total_count + page_size - 1) // page_size, 1)
    start_idx = current_page * page_size + 1
    end_idx = min((current_page + 1) * page_size, total_count)

    col1, col2, col3, col4, col5 = st.columns([1, 1, 2, 1, 1])

    with col2:
        st.info(f"Showing {start_idx}-{end_idx} of {total_count} associates.")

    with col4:
        col4a, col4b = st.columns(2)

        with col4a:
            if st.button("Previous", key="hub_prev_page", disabled=current_page == 0):
                update_filter_state(page=current_page - 1)
                safe_rerun()

        with col4b:
            if st.button("Next", key="hub_next_page", disabled=current_page >= total_pages - 1):
                update_filter_state(page=current_page + 1)
                safe_rerun()


def get_active_filters_count(current_state: Dict[str, Any]) -> int:
    """Return the count of non-default filters currently applied."""
    count = 0

    if current_state["search"].strip():
        count += 1
    if current_state["admin_filter"]:
        count += 1
    if current_state["associate_status_filter"]:
        count += 1
    if current_state["bookmaker_status_filter"]:
        count += 1
    if current_state["currency_filter"]:
        count += 1
    if current_state["sort_by"] != "alias_asc":
        count += 1

    return count
