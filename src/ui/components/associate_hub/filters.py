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
RISK_LABELS: Dict[str, str] = {
    "balanced": "Balanced",
    "overholding": "Overholding",
    "short": "Short",
}
RISK_SLUG_BY_LABEL: Dict[str, str] = {label: slug for slug, label in RISK_LABELS.items()}


def _widget_key(base: str, suffix: str) -> str:
    """Return a stable widget key with optional suffix for multi-render pages."""
    return f"{base}{suffix}" if suffix else base


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


def _risk_labels_from_state(values: Iterable[str]) -> List[str]:
    """Convert stored risk slugs into display labels."""
    return [RISK_LABELS.get(slug, slug.title()) for slug in values if slug in RISK_LABELS]


def _risk_slugs_from_labels(labels: Iterable[str]) -> List[str]:
    """Convert selected risk labels back into slug storage."""
    slugs: List[str] = []
    for label in labels:
        slug = RISK_SLUG_BY_LABEL.get(label)
        if slug and slug not in slugs:
            slugs.append(slug)
    return slugs


def get_filter_state() -> Dict[str, Any]:
    """Read the current filter state from Streamlit session state."""
    return {
        "search": st.session_state.get("hub_search", ""),
        "admin_filter": st.session_state.get("hub_admin_filter", []),
        "associate_status_filter": st.session_state.get("hub_associate_status_filter", []),
        "bookmaker_status_filter": st.session_state.get("hub_bookmaker_status_filter", []),
        "risk_filter": st.session_state.get("hub_risk_filter", []),
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
        "risk_filter": "hub_risk_filter",
        "currency_filter": "hub_currency_filter",
        "sort_by": "hub_sort_by",
        "page": "hub_page",
        "page_size": "hub_page_size",
    }

    for key, value in kwargs.items():
        session_key = mappings.get(key)
        if session_key:
            st.session_state[session_key] = value


def render_filters(
    repository: AssociateHubRepository,
    *,
    widget_suffix: str = "",
) -> Tuple[Dict[str, Any], bool]:
    """Render the filter bar and return the updated state plus refresh flag."""
    current_state = get_filter_state()
    should_refresh = False
    active_filter_count = get_active_filters_count(current_state)

    with st.container():
        st.markdown(
            """
            <style>
            .hub-filter-label {
                font-size: 0.78rem;
                color: #94a3b8;
                letter-spacing: 0.08em;
                text-transform: uppercase;
                display: inline-flex;
                align-items: center;
                gap: 0.25rem;
                margin-bottom: 0.15rem;
            }
            .hub-filter-label .divider {
                width: 8px;
                height: 1px;
                background: rgba(148, 163, 184, 0.65);
                display: inline-block;
            }
            .hub-filter-wrapper {
                padding-top: 0.35rem;
                padding-bottom: 0.35rem;
            }
            .hub-filter-wrapper .stColumns {
                gap: 0.45rem;
            }
            .hub-filter-wrapper .stButton button {
                padding-top: 0.4rem;
                padding-bottom: 0.4rem;
            }
            .hub-filter-heading {
                font-size: 0.95rem;
                letter-spacing: 0.08em;
                text-transform: uppercase;
                color: #94a3b8;
                margin-bottom: 0.35rem;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )

        def _compact_label(text: str) -> None:
            st.markdown(
                f'<span class="hub-filter-label"><span class="divider"></span>{text}</span>',
                unsafe_allow_html=True,
            )

        st.markdown('<div class="hub-filter-wrapper">', unsafe_allow_html=True)
        st.markdown('<div class="hub-filter-heading">Filters & Search</div>', unsafe_allow_html=True)

        filter_cols = st.columns(
            (1.5, 1.1, 1.1, 1.1, 1.0, 1.0, 0.9, 0.7),
            gap="small",
        )

        with filter_cols[0]:
            _compact_label("Search Associates")
            search_value = st.text_input(
                "Search Associates",
                value=current_state["search"],
                key=_widget_key("hub_search_input", widget_suffix),
                placeholder="Alias, bookmaker, or chat ID",
                help="Searches associate aliases, bookmaker names, and Telegram chat IDs.",
                label_visibility="collapsed",
            )
            if search_value != current_state["search"]:
                update_filter_state(search=search_value, page=0)
                should_refresh = True

        with filter_cols[1]:
            _compact_label("Admin Status")
            admin_selection = st.multiselect(
                "Admin Status",
                options=list(ADMIN_LABELS.values()),
                default=_labels_from_state(current_state["admin_filter"], ADMIN_LABELS),
                key=_widget_key("hub_admin_filter_select", widget_suffix),
                label_visibility="collapsed",
                placeholder="Choose options",
                help="Filter by whether the associate has admin privileges.",
            )
            admin_filter = _flags_from_selection(admin_selection, ADMIN_LABELS)
            if admin_filter != current_state["admin_filter"]:
                update_filter_state(admin_filter=admin_filter, page=0)
                should_refresh = True

        with filter_cols[2]:
            _compact_label("Associate Status")
            associate_selection = st.multiselect(
                "Associate Status",
                options=list(STATUS_LABELS.values()),
                default=_labels_from_state(current_state["associate_status_filter"], STATUS_LABELS),
                key=_widget_key("hub_associate_status_filter_select", widget_suffix),
                label_visibility="collapsed",
                placeholder="Choose options",
                help="Filter by whether the associate is active.",
            )
            associate_filter = _flags_from_selection(associate_selection, STATUS_LABELS)
            if associate_filter != current_state["associate_status_filter"]:
                update_filter_state(associate_status_filter=associate_filter, page=0)
                should_refresh = True

        with filter_cols[3]:
            _compact_label("Bookmaker Status")
            bookmaker_selection = st.multiselect(
                "Bookmaker Status",
                options=list(STATUS_LABELS.values()),
                default=_labels_from_state(current_state["bookmaker_status_filter"], STATUS_LABELS),
                key=_widget_key("hub_bookmaker_status_filter_select", widget_suffix),
                label_visibility="collapsed",
                placeholder="Choose options",
                help="Filter by whether any bookmaker mapped to the associate is active.",
            )
            bookmaker_filter = _flags_from_selection(bookmaker_selection, STATUS_LABELS)
            if bookmaker_filter != current_state["bookmaker_status_filter"]:
                update_filter_state(bookmaker_status_filter=bookmaker_filter, page=0)
                should_refresh = True

        with filter_cols[4]:
            _compact_label("Risk Flags")
            risk_selection = st.multiselect(
                "Risk Flags",
                options=list(RISK_SLUG_BY_LABEL.keys()),
                default=_risk_labels_from_state(current_state["risk_filter"]),
                key=_widget_key("hub_risk_filter_select", widget_suffix),
                label_visibility="collapsed",
                placeholder="Balanced / Overholding / Short",
                help="Filter by ND/YF imbalance classification.",
            )
            normalized_risk = _risk_slugs_from_labels(risk_selection)
            if normalized_risk != current_state["risk_filter"]:
                update_filter_state(risk_filter=normalized_risk, page=0)
                should_refresh = True

        with filter_cols[5]:
            _compact_label("Currencies")
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
                key=_widget_key("hub_currency_filter_select", widget_suffix),
                label_visibility="collapsed",
                placeholder="Choose options",
                help="Filter associates by their home currency.",
            )
            if currency_selection != current_state["currency_filter"]:
                update_filter_state(currency_filter=currency_selection, page=0)
                should_refresh = True

        sort_options = {
            "Alias (A-Z)": "alias_asc",
            "Alias (Z-A)": "alias_desc",
            "Net Deposits (High-Low)": "nd_desc",
            "Net Deposits (Low-High)": "nd_asc",
            "Imbalance I'' (High-Low)": "delta_desc",
            "Imbalance I'' (Low-High)": "delta_asc",
            "Last Activity (Newest-Oldest)": "activity_desc",
            "Last Activity (Oldest-Newest)": "activity_asc",
            "Active Bookmakers": "bookmaker_active_desc",
        }
        sort_labels = list(sort_options.keys())
        current_sort_label = next(
            (label for label, value in sort_options.items() if value == current_state["sort_by"]),
            "Alias (A-Z)",
        )
        selected_sort_label = current_sort_label

        with filter_cols[6]:
            _compact_label("Sort By")
            selected_label = st.selectbox(
                "Sort By",
                options=sort_labels,
                index=sort_labels.index(current_sort_label),
                key=_widget_key("hub_sort_by_select", widget_suffix),
                label_visibility="collapsed",
                help="Sort order for the associate listing.",
            )
            selected_sort_label = selected_label
            if sort_options[selected_label] != current_state["sort_by"]:
                update_filter_state(sort_by=sort_options[selected_label], page=0)
                should_refresh = True

        with filter_cols[7]:
            _compact_label("Page Size")
            page_size_options = [10, 25, 50, 100]
            page_size = st.selectbox(
                "Page Size",
                options=page_size_options,
                index=page_size_options.index(current_state["page_size"]),
                key=_widget_key("hub_page_size_select", widget_suffix),
                label_visibility="collapsed",
                help="Number of associates to show per page.",
            )
            if page_size != current_state["page_size"]:
                update_filter_state(page_size=page_size, page=0)
                should_refresh = True

        st.divider()
        st.markdown("</div>", unsafe_allow_html=True)

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

        if current_state["risk_filter"]:
            risk_labels = _risk_labels_from_state(current_state["risk_filter"])
            active_filter_labels.append(f"Risk: {', '.join(risk_labels)}")

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
    if current_state["risk_filter"]:
        count += 1
    if current_state["currency_filter"]:
        count += 1
    if current_state["sort_by"] != "alias_asc":
        count += 1

    return count
