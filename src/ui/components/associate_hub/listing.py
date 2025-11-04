"""
Listing component for Associate Operations Hub (Story 5.5)

Renders associate summary rows with expandable bookmaker sub-tables and action buttons.
Handles expand/collapse state persistence and displays status indicators.
"""

from __future__ import annotations

import streamlit as st
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from src.repositories.associate_hub_repository import AssociateMetrics, BookmakerSummary
from src.ui.components.associate_hub.filters import update_filter_state


def render_associate_listing(
    associates: List[AssociateMetrics], 
    bookmakers_dict: Dict[int, List[BookmakerSummary]]
) -> None:
    """
    Render the main associate listing with expandable rows.
    
    Args:
        associates: List of associate metrics to display
        bookmakers_dict: Dictionary mapping associate_id to their bookmakers
    """
    if not associates:
        st.warning("📭 No associates found matching current filters.")
        return
    
    # Container for the listing with sticky header
    with st.container():
        # Header row
        col1, col2, col3, col4, col5, col6, col7, col8, col9 = st.columns([2, 1, 1, 1, 1, 1, 1, 1, 1])
        
        with col1:
            st.markdown("**Associate**")
        with col2:
            st.markdown("**Admin**")
        with col3:
            st.markdown("**Currency**")
        with col4:
            st.markdown("**Bookmakers**")
        with col5:
            st.markdown("**Net Deposits**")
        with col6:
            st.markdown("**Should Hold**")
        with col7:
            st.markdown("**Current Holding**")
        with col8:
            st.markdown("**Delta**")
        with col9:
            st.markdown("**Status**")
        
        st.divider()
        
        # Associate rows
        for i, associate in enumerate(associates):
            # Generate unique keys for this associate
            associate_key = f"associate_{associate.associate_id}"
            expand_key = f"{associate_key}_expanded"
            
            # Check if this row should be expanded
            is_expanded = st.session_state.get(expand_key, False)
            
            # Create expandable row
            with st.expander(
                label=f"👤 {associate.associate_alias}",
                expanded=is_expanded
            ):
                # Main row content
                col1, col2, col3, col4, col5, col6, col7, col8, col9 = st.columns([2, 1, 1, 1, 1, 1, 1, 1, 1])
                
                with col1:
                    st.write(associate.associate_alias)
                    if associate.telegram_chat_id:
                        st.caption(f"📱 {associate.telegram_chat_id}")
                
                with col2:
                    admin_badge = "👑 Admin" if associate.is_admin else "👤 User"
                    st.write(admin_badge)
                
                with col3:
                    st.write(associate.home_currency)
                
                with col4:
                    active_text = f"{associate.active_bookmaker_count}/{associate.bookmaker_count}"
                    st.write(active_text)
                    if associate.active_bookmaker_count < associate.bookmaker_count:
                        st.caption("Some inactive")
                
                with col5:
                    st.write(f"€{associate.net_deposits_eur:,.2f}")
                
                with col6:
                    st.write(f"€{associate.should_hold_eur:,.2f}")
                
                with col7:
                    st.write(f"€{associate.current_holding_eur:,.2f}")
                
                with col8:
                    delta_color = "green" if associate.delta_eur >= 0 else "red"
                    st.markdown(
                        f":{delta_color}[{associate.delta_display()}]"
                    )
                
                with col9:
                    # Status pill with color
                    status_emoji = {
                        "balanced": "🟢",
                        "overholding": "🔺", 
                        "short": "🔻"
                    }.get(associate.status, "⚪")
                    
                    st.markdown(
                        f'<span style="background-color: {associate.status_color}; '
                        f'padding: 2px 8px; border-radius: 12px; font-size: 12px;">'
                        f'{status_emoji} {associate.title()}</span>',
                        unsafe_allow_html=True
                    )
                
                # Action buttons row
                render_action_buttons(associate)
                
                # Bookmaker sub-table (only visible when expanded)
                if associate.associate_id in bookmakers_dict:
                    bookmakers = bookmakers_dict[associate.associate_id]
                    if bookmakers:
                        st.markdown("**📊 Bookmaker Details**")
                        render_bookmaker_subtable(bookmakers)
                    else:
                        st.info("📭 No bookmakers configured for this associate.")
                
                # Last activity info
                if associate.last_activity_utc:
                    try:
                        activity_date = datetime.fromisoformat(associate.last_activity_utc.replace('Z', '+00:00'))
                        local_date = activity_date.strftime('%Y-%m-%d %H:%M')
                        st.caption(f"🕒 Last activity: {local_date}")
                    except (ValueError, AttributeError):
                        st.caption(f"🕒 Last activity: {associate.last_activity_utc}")
    
    # Update expand state tracking
    for associate in associates:
        expand_key = f"associate_{associate.associate_id}_expanded"
        # This will be updated by Streamlit's expander state


def render_action_buttons(associate: AssociateMetrics) -> None:
    """
    Render action buttons for an associate row.
    
    Args:
        associate: Associate metrics
    """
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        if st.button(
            "👤 Edit Profile",
            key=f"edit_profile_{associate.associate_id}",
            help="Edit associate details",
            use_container_width=True
        ):
            # Set session state for drawer
            st.session_state["hub_drawer_open"] = True
            st.session_state["hub_drawer_associate_id"] = associate.associate_id
            st.session_state["hub_drawer_tab"] = "profile"
            st.rerun()
    
    with col2:
        if st.button(
            "💰 Deposit",
            key=f"deposit_{associate.associate_id}",
            help="Record deposit transaction",
            use_container_width=True
        ):
            st.session_state["hub_drawer_open"] = True
            st.session_state["hub_drawer_associate_id"] = associate.associate_id
            st.session_state["hub_drawer_tab"] = "transactions"
            st.session_state["hub_funding_action"] = "deposit"
            st.rerun()
    
    with col3:
        if st.button(
            "💸 Withdraw",
            key=f"withdraw_{associate.associate_id}",
            help="Record withdrawal transaction",
            use_container_width=True
        ):
            st.session_state["hub_drawer_open"] = True
            st.session_state["hub_drawer_associate_id"] = associate.associate_id
            st.session_state["hub_drawer_tab"] = "transactions"
            st.session_state["hub_funding_action"] = "withdraw"
            st.rerun()
    
    with col4:
        if st.button(
            "📊 View Details",
            key=f"details_{associate.associate_id}",
            help="View full associate details",
            use_container_width=True
        ):
            st.session_state["hub_drawer_open"] = True
            st.session_state["hub_drawer_associate_id"] = associate.associate_id
            st.session_state["hub_drawer_tab"] = "profile"
            st.rerun()


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
            status_icon = "✅" if bookmaker.is_active else "❌"
            st.write(f"{status_icon} {bookmaker.bookmaker_name}")
        
        with col2:
            active_text = "✅ Active" if bookmaker.is_active else "❌ Inactive"
            st.write(active_text)
        
        with col3:
            if bookmaker.parsing_profile:
                st.caption(f"📄 {bookmaker.parsing_profile}")
            else:
                st.caption("📄 No profile")
        
        with col4:
            st.write(f"€{bookmaker.modeled_balance_eur:,.2f}")
        
        with col5:
            if bookmaker.reported_balance_eur is not None:
                st.write(f"€{bookmaker.reported_balance_eur:,.2f}")
            else:
                st.caption("📭 Not reported")
        
        with col6:
            if bookmaker.delta_eur is not None:
                delta_color = "green" if bookmaker.delta_eur >= 0 else "red"
                delta_text = f"+€{abs(bookmaker.delta_eur):,.2f}" if bookmaker.delta_eur >= 0 else f"-€{abs(bookmaker.delta_eur):,.2f}"
                st.markdown(f":{delta_color}[{delta_text}]")
            else:
                st.caption("—")
        
        with col7:
            if bookmaker.last_balance_check_utc:
                try:
                    check_date = datetime.fromisoformat(bookmaker.last_balance_check_utc.replace('Z', '+00:00'))
                    local_date = check_date.strftime('%m/%d %H:%M')
                    st.caption(local_date)
                except (ValueError, AttributeError):
                    st.caption(bookmaker.last_balance_check_utc[:10])
            else:
                st.caption("Never")
        
        with col8:
            col8a, col8b, col8c = st.columns(3)
            
            with col8a:
                if st.button(
                    "✏️",
                    key=f"edit_bookmaker_{bookmaker.bookmaker_id}",
                    help="Edit bookmaker",
                    use_container_width=True
                ):
                    st.session_state["hub_drawer_open"] = True
                    st.session_state["hub_drawer_associate_id"] = bookmaker.associate_id
                    st.session_state["hub_drawer_bookmaker_id"] = bookmaker.bookmaker_id
                    st.session_state["hub_drawer_tab"] = "profile"
                    st.rerun()
            
            with col8b:
                if st.button(
                    "💰",
                    key=f"balance_{bookmaker.bookmaker_id}",
                    help="Manage balance",
                    use_container_width=True
                ):
                    st.session_state["hub_drawer_open"] = True
                    st.session_state["hub_drawer_associate_id"] = bookmaker.associate_id
                    st.session_state["hub_drawer_bookmaker_id"] = bookmaker.bookmaker_id
                    st.session_state["hub_drawer_tab"] = "balances"
                    st.rerun()
            
            with col8c:
                if st.button(
                    "📊",
                    key=f"bookmaker_details_{bookmaker.bookmaker_id}",
                    help="Bookmaker details",
                    use_container_width=True
                ):
                    st.session_state["hub_drawer_open"] = True
                    st.session_state["hub_drawer_associate_id"] = bookmaker.associate_id
                    st.session_state["hub_drawer_bookmaker_id"] = bookmaker.bookmaker_id
                    st.session_state["hub_drawer_tab"] = "transactions"
                    st.rerun()


def render_empty_state(filter_state: Dict) -> None:
    """
    Render empty state when no associates match filters.
    
    Args:
        filter_state: Current filter state
    """
    st.warning("📭 No associates found matching your filters.")
    
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
        st.caption("🔍 **Active filters:**")
        for filter_text in active_filters:
            st.caption(f"• {filter_text}")
    
    st.info("💡 **Tip:** Try adjusting your filters or click '🔄 Reset Filters' to see all associates.")


def render_summary_metrics(associates: List[AssociateMetrics]) -> None:
    """
    Render summary metrics for the current associate list.
    
    Args:
        associates: List of associate metrics
    """
    if not associates:
        return
    
    total_associates = len(associates)
    total_admins = sum(1 for a in associates if a.is_admin)
    total_active = sum(1 for a in associates if a.is_active)
    
    total_net_deposits = sum(a.net_deposits_eur for a in associates)
    total_current_holdings = sum(a.current_holding_eur for a in associates)
    total_delta = total_current_holdings - total_net_deposits
    
    balanced_count = sum(1 for a in associates if a.status == "balanced")
    overholding_count = sum(1 for a in associates if a.status == "overholding")
    short_count = sum(1 for a in associates if a.status == "short")
    
    # Metrics row
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            "Total Associates",
            total_associates,
            delta=f"{total_admins} admins, {total_active} active"
        )
    
    with col2:
        st.metric(
            "Total Net Deposits",
            f"€{total_net_deposits:,.2f}",
            delta="Across all associates"
        )
    
    with col3:
        st.metric(
            "Current Holdings", 
            f"€{total_current_holdings:,.2f}",
            delta=f"Delta: €{total_delta:,.2f}"
        )
    
    with col4:
        st.metric(
            "Status Breakdown",
            f"{balanced_count} balanced",
            delta=f"{overholding_count} over, {short_count} short"
        )
    
    st.divider()
