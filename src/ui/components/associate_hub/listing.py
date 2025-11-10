"""
Listing component for Associate Operations Hub (Story 5.5)

Renders associate summary rows with expandable bookmaker sub-tables and action buttons.
Handles expand/collapse state persistence and displays status indicators.
"""

from __future__ import annotations

import streamlit as st
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

from src.repositories.associate_hub_repository import AssociateMetrics, BookmakerSummary
from src.ui.components.associate_hub.filters import update_filter_state
from src.ui.utils.formatters import format_currency_amount
from src.ui.utils.state_management import safe_rerun


def _format_optional_eur(value: Optional[Decimal]) -> str:
    """Format EUR amounts when data is present, otherwise return a placeholder."""
    return format_currency_amount(value, "EUR") if value is not None else "N/A"


def _format_signed_eur(value: Optional[Decimal]) -> str:
    """Render EUR amounts with explicit +/- for deltas."""
    if value is None:
        return "N/A"
    formatted = format_currency_amount(value, "EUR")
    return f"+{formatted}" if value >= 0 else formatted


def _format_local_timestamp(timestamp: Optional[str], fmt: str = "%Y-%m-%d %H:%M") -> str:
    """Produce a human-readable local timestamp or fallback text."""
    if not timestamp:
        return "Never"
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return parsed.strftime(fmt)
    except (ValueError, AttributeError):
        return timestamp[:16]
def render_associate_listing(
    associates: List[AssociateMetrics], 
    bookmakers_dict: Dict[int, List[BookmakerSummary]]
) -> None:
    """
    Render each associate as a card with summary metrics and bookmaker details.
    """
    if not associates:
        st.warning("No associates found matching current filters.")
        return

    for index, associate in enumerate(associates):
        if index:
            st.divider()

        associate_key = f"associate_{associate.associate_id}"
        admin_label = "Admin" if associate.is_admin else "User"
        currency_label = associate.home_currency or "EUR"
        bookie_summary = f"{associate.active_bookmaker_count}/{associate.bookmaker_count}"
        status_label = associate.title()
        last_activity = _format_local_timestamp(associate.last_activity_utc)

        with st.container():
            header_cols = st.columns([3, 1, 1])
            with header_cols[0]:
                st.markdown(f"#### {associate.associate_alias}")
                st.caption(f"{admin_label} - Currency: {currency_label}")
                st.caption(f"{bookie_summary} bookmakers")
                if associate.telegram_chat_id:
                    st.caption(f"Telegram: {associate.telegram_chat_id}")
            with header_cols[1]:
                st.metric(
                    "Bookmakers",
                    bookie_summary,
                    delta="Active / Total",
                )
            with header_cols[2]:
                st.markdown(
                    f"<span style='color:{associate.status_color}; font-weight:600;'>{status_label}</span>",
                    unsafe_allow_html=True,
                )
                st.caption(f"Last activity: {last_activity}")

            metric_cols = st.columns(4)
            metric_cols[0].metric(
                "Net Deposits (EUR)",
                _format_optional_eur(associate.net_deposits_eur),
                delta="Auto-refresh",
            )
            metric_cols[1].metric(
                "Should Hold (EUR)",
                _format_optional_eur(associate.should_hold_eur),
                delta=f"{associate.bookmaker_count} total",
            )
            metric_cols[2].metric(
                "Current Holding (EUR)",
                _format_optional_eur(associate.current_holding_eur),
                delta="Latest snapshot",
            )
            metric_cols[3].metric(
                "Delta (EUR)",
                _format_signed_eur(associate.delta_eur),
                delta=status_label,
            )

            render_action_buttons(associate)

            bookmakers = bookmakers_dict.get(associate.associate_id)
            if bookmakers:
                with st.expander(
                    f"Bookmaker details · {associate.associate_alias}",
                    expanded=False,
                ):
                    render_bookmaker_subtable(bookmakers)
            else:
                st.info("No bookmakers configured for this associate.")


def render_action_buttons(associate: AssociateMetrics) -> None:
    """
    Render action buttons for an associate row.
    
    Args:
        associate: Associate metrics
    """
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        if st.button(
            ":material/edit: Edit Profile",
            key=f"edit_profile_{associate.associate_id}",
            help="Edit associate details",
            width="stretch"
        ):
            # Set session state for drawer
            st.session_state["hub_drawer_open"] = True
            st.session_state["hub_drawer_associate_id"] = associate.associate_id
            st.session_state["hub_drawer_tab"] = "profile"
            safe_rerun()
    
    with col2:
        if st.button(
            ":material/savings: Deposit",
            key=f"deposit_{associate.associate_id}",
            help="Record deposit transaction",
            width="stretch"
        ):
            st.session_state["hub_drawer_open"] = True
            st.session_state["hub_drawer_associate_id"] = associate.associate_id
            st.session_state["hub_drawer_tab"] = "transactions"
            st.session_state["hub_funding_action"] = "deposit"
            safe_rerun()
    
    with col3:
        if st.button(
            ":material/payments: Withdraw",
            key=f"withdraw_{associate.associate_id}",
            help="Record withdrawal transaction",
            width="stretch"
        ):
            st.session_state["hub_drawer_open"] = True
            st.session_state["hub_drawer_associate_id"] = associate.associate_id
            st.session_state["hub_drawer_tab"] = "transactions"
            st.session_state["hub_funding_action"] = "withdraw"
            safe_rerun()
    
    with col4:
        if st.button(
            ":material/visibility: View Details",
            key=f"details_{associate.associate_id}",
            help="View full associate details",
            width="stretch"
        ):
            st.session_state["hub_drawer_open"] = True
            st.session_state["hub_drawer_associate_id"] = associate.associate_id
            st.session_state["hub_drawer_tab"] = "profile"
            safe_rerun()


def render_bookmaker_subtable(bookmakers: List[BookmakerSummary]) -> None:
    """
    Render bookmaker sub-table for an associate.
    
    Args:
        bookmakers: List of bookmaker summaries
    """
    if not bookmakers:
        st.info("No bookmakers found.")
        return
    
    # Header
    col1, col2, col3, col4, col5, col6, col7, col8 = st.columns([2, 1, 1, 1, 1, 1, 1, 1])
    
    with col1:
        st.markdown("**Bookmaker**")
    with col2:
        st.markdown("**Active**")
    with col3:
        st.markdown("**Profile**")
    with col4:
        st.markdown("**Modeled Balance**")
    with col5:
        st.markdown("**Reported Balance**")
    with col6:
        st.markdown("**Delta**")
    with col7:
        st.markdown("**Last Check**")
    with col8:
        st.markdown("**Actions**")
    
    st.divider()
    
    # Bookmaker rows
    for bookmaker in bookmakers:
        col1, col2, col3, col4, col5, col6, col7, col8 = st.columns([2, 1, 1, 1, 1, 1, 1, 1])
        
        with col1:
            st.write(bookmaker.bookmaker_name)
        
        with col2:
            active_text = "Active" if bookmaker.is_active else "Inactive"
            st.write(active_text)
        
        with col3:
            if bookmaker.parsing_profile:
                st.caption(bookmaker.parsing_profile)
            else:
                st.caption("No profile")
        
        with col4:
            st.write(_format_optional_eur(bookmaker.modeled_balance_eur))
        
        with col5:
            st.write(_format_optional_eur(bookmaker.reported_balance_eur))
        
        with col6:
            if bookmaker.delta_eur is not None:
                delta_color = "green" if bookmaker.delta_eur >= 0 else "red"
                st.markdown(f":{delta_color}[{_format_signed_eur(bookmaker.delta_eur)}]")
            else:
                st.caption("N/A")
        
        with col7:
            st.caption(_format_local_timestamp(bookmaker.last_balance_check_utc, "%m/%d %H:%M"))
        
        with col8:
            col8a, col8b, col8c = st.columns(3)
            
            with col8a:
                if st.button(
                    ":material/edit:",
                    key=f"edit_bookmaker_{bookmaker.bookmaker_id}",
                    help="Edit bookmaker",
                    width="stretch",
                ):
                    st.session_state["hub_drawer_open"] = True
                    st.session_state["hub_drawer_associate_id"] = bookmaker.associate_id
                    st.session_state["hub_drawer_bookmaker_id"] = bookmaker.bookmaker_id
                    st.session_state["hub_drawer_tab"] = "profile"
                    safe_rerun()
            
            with col8b:
                if st.button(
                    ":material/account_balance_wallet:",
                    key=f"balance_{bookmaker.bookmaker_id}",
                    help="Manage balance",
                    width="stretch",
                ):
                    st.session_state["hub_drawer_open"] = True
                    st.session_state["hub_drawer_associate_id"] = bookmaker.associate_id
                    st.session_state["hub_drawer_bookmaker_id"] = bookmaker.bookmaker_id
                    st.session_state["hub_drawer_tab"] = "balances"
                    safe_rerun()
            
            with col8c:
                if st.button(
                    ":material/visibility:",
                    key=f"bookmaker_details_{bookmaker.bookmaker_id}",
                    help="Bookmaker details",
                    width="stretch",
                ):
                    st.session_state["hub_drawer_open"] = True
                    st.session_state["hub_drawer_associate_id"] = bookmaker.associate_id
                    st.session_state["hub_drawer_bookmaker_id"] = bookmaker.bookmaker_id
                    st.session_state["hub_drawer_tab"] = "transactions"
                    safe_rerun()


def render_empty_state(filter_state: Dict) -> None:
    """
    Render empty state when no associates match filters.
    
    Args:
        filter_state: Current filter state
    """
    st.warning("No associates found matching your filters.")
    
    # Show what filters are active
    active_filters = []
    
    if filter_state.get("search", "").strip():
        active_filters.append(f"Search: '{filter_state['search']}'")
    
    if filter_state.get("admin_filter"):
        admin_labels = []
        if True in filter_state["admin_filter"]:
            admin_labels.append("Admin")
        if False in filter_state["admin_filter"]:
            admin_labels.append("Non-Admin")
        active_filters.append(f"Admin: {', '.join(admin_labels)}")
    
    if filter_state.get("associate_status_filter"):
        status_labels = []
        if True in filter_state["associate_status_filter"]:
            status_labels.append("Active")
        if False in filter_state["associate_status_filter"]:
            status_labels.append("Inactive")
        active_filters.append(f"Status: {', '.join(status_labels)}")
    
    if filter_state.get("currency_filter"):
        active_filters.append(f"Currencies: {', '.join(filter_state['currency_filter'])}")
    
    if active_filters:
        st.caption("**Active filters:**")
        for filter_text in active_filters:
            st.caption(filter_text)
    
    st.info("**Tip:** Try adjusting your filters or click 'Reset Filters' to see all associates.")


def render_hub_dashboard(associates: List[AssociateMetrics]) -> None:
    """
    Show a dashboard of aggregate associate and bookmaker metrics.
    """
    if not associates:
        return

    total_associates = len(associates)
    total_admins = sum(1 for a in associates if a.is_admin)
    total_active = sum(1 for a in associates if a.is_active)
    total_bookmakers = sum(a.bookmaker_count for a in associates)
    active_bookmakers = sum(a.active_bookmaker_count for a in associates)

    total_net_deposits = sum(a.net_deposits_eur for a in associates)
    total_current_holdings = sum(a.current_holding_eur for a in associates)
    total_should_hold = sum(a.should_hold_eur for a in associates)
    total_delta = sum(a.delta_eur for a in associates)

    balanced_count = sum(1 for a in associates if a.status == "balanced")
    overholding_count = sum(1 for a in associates if a.status == "overholding")
    short_count = sum(1 for a in associates if a.status == "short")

    balanced_ratio = balanced_count / total_associates if total_associates else 0
    bookmaker_ratio = active_bookmakers / total_bookmakers if total_bookmakers else 0

    st.markdown("### Operations Dashboard")
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            "Total Associates",
            total_associates,
            delta=f"{total_active} active · {total_admins} admins",
        )

    with col2:
        st.metric(
            "Net Deposits (EUR)",
            _format_optional_eur(total_net_deposits),
            delta="Auto refresh",
        )

    with col3:
        st.metric(
            "Current Holdings (EUR)",
            _format_optional_eur(total_current_holdings),
            delta="Latest snapshot",
        )

    with col4:
        st.metric(
            "Delta (EUR)",
            _format_signed_eur(total_delta),
            delta=f"Should hold: {_format_optional_eur(total_should_hold)}",
        )

    st.divider()

    status_col, bookmaker_col = st.columns(2)

    with status_col:
        st.metric(
            "Status mix",
            f"{balanced_count} balanced",
            delta=f"{overholding_count} over · {short_count} short",
        )
        st.progress(min(max(balanced_ratio, 0.0), 1.0))
        st.caption(f"{balanced_ratio:.0%} of associates balanced")

    with bookmaker_col:
        st.metric(
            "Bookmakers Active",
            f"{active_bookmakers}/{total_bookmakers}",
            delta="Active / Total",
        )
        st.progress(min(max(bookmaker_ratio, 0.0), 1.0))
        st.caption(f"{bookmaker_ratio:.0%} of bookmakers active")

