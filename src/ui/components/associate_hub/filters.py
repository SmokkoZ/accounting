"""
Filter bar component for Associate Operations Hub (Story 5.5)

Provides persistent search, multi-select filters, and sorting with session state management.
Includes debounced search to avoid choppy reruns.
"""

from __future__ import annotations

import streamlit as st
from typing import Dict, List, Optional, Tuple, Any

from src.repositories.associate_hub_repository import AssociateHubRepository


def get_filter_state() -> Dict[str, Any]:
    """
    Get current filter state from session state.
    
    Returns:
        Dictionary with current filter values
    """
    return {
        "search": st.session_state.get("hub_search", ""),
        "admin_filter": st.session_state.get("hub_admin_filter", []),
        "associate_status_filter": st.session_state.get("hub_associate_status_filter", []),
        "bookmaker_status_filter": st.session_state.get("hub_bookmaker_status_filter", []),
        "currency_filter": st.session_state.get("hub_currency_filter", []),
        "sort_by": st.session_state.get("hub_sort_by", "alias_asc"),
        "page": st.session_state.get("hub_page", 0),
        "page_size": st.session_state.get("hub_page_size", 25)
    }


def update_filter_state(**kwargs) -> None:
    """
    Update filter state in session state.
    
    Args:
        **kwargs: Filter values to update
    """
    filter_mappings = {
        "search": "hub_search",
        "admin_filter": "hub_admin_filter", 
        "associate_status_filter": "hub_associate_status_filter",
        "bookmaker_status_filter": "hub_bookmaker_status_filter",
        "currency_filter": "hub_currency_filter",
        "sort_by": "hub_sort_by",
        "page": "hub_page",
        "page_size": "hub_page_size"
    }
    
    for key, value in kwargs.items():
        session_key = filter_mappings.get(key)
        if session_key is not None:
            st.session_state[session_key] = value


def render_filters(repository: AssociateHubRepository) -> Tuple[Dict[str, Any], bool]:
    """
    Render the filter bar with search, multi-select filters, and sorting.
    
    Args:
        repository: AssociateHubRepository instance for getting filter options
        
    Returns:
        Tuple of (filter_state, should_refresh_data)
    """
    # Get current state
    current_state = get_filter_state()
    should_refresh = False
    
    # Container for filters with sticky positioning
    with st.container():
        st.subheader("🔍 Filters & Search")
        
        # Create columns for layout
        col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
        
        with col1:
            # Search with debounce using text_input and key
            search_value = st.text_input(
                "🔎 Search Associates",
                value=current_state["search"],
                key="hub_search_input",
                placeholder="Search by alias, bookmaker, or chat ID...",
                help="Searches associate aliases, bookmaker names, and Telegram chat IDs"
            )
            
            # Check if search changed (debounce effect)
            if search_value != current_state["search"]:
                update_filter_state(search=search_value, page=0)  # Reset to first page
                should_refresh = True
        
        with col2:
            # Admin status filter
            admin_options = ["Admin", "Non-Admin"]
            admin_selection = st.multiselect(
                "👤 Admin Status",
                options=admin_options,
                default=current_state["admin_filter"],
                key="hub_admin_filter_select",
                help="Filter by admin privileges"
            )
            
            # Convert to boolean values for repository
            admin_filter = []
            if "Admin" in admin_selection:
                admin_filter.append(True)
            if "Non-Admin" in admin_selection:
                admin_filter.append(False)
            
            if admin_filter != current_state["admin_filter"]:
                update_filter_state(admin_filter=admin_filter, page=0)
                should_refresh = True
        
        with col3:
            # Associate status filter
            associate_status_options = ["Active", "Inactive"]
            associate_status_selection = st.multiselect(
                "✅ Associate Status",
                options=associate_status_options,
                default=current_state["associate_status_filter"],
                key="hub_associate_status_filter_select",
                help="Filter by associate active status"
            )
            
            # Convert to boolean values
            associate_status_filter = []
            if "Active" in associate_status_selection:
                associate_status_filter.append(True)
            if "Inactive" in associate_status_selection:
                associate_status_filter.append(False)
            
            if associate_status_filter != current_state["associate_status_filter"]:
                update_filter_state(associate_status_filter=associate_status_filter, page=0)
                should_refresh = True
        
        with col4:
            # Bookmaker status filter
            bookmaker_status_options = ["Active", "Inactive"]
            bookmaker_status_selection = st.multiselect(
                "📊 Bookmaker Status",
                options=bookmaker_status_options,
                default=current_state["bookmaker_status_filter"],
                key="hub_bookmaker_status_filter_select",
                help="Filter by whether associate has active bookmakers"
            )
            
            # Convert to boolean values
            bookmaker_status_filter = []
            if "Active" in bookmaker_status_selection:
                bookmaker_status_filter.append(True)
            if "Inactive" in bookmaker_status_selection:
                bookmaker_status_filter.append(False)
            
            if bookmaker_status_filter != current_state["bookmaker_status_filter"]:
                update_filter_state(bookmaker_status_filter=bookmaker_status_filter, page=0)
                should_refresh = True
    
    # Second row for currency and sorting
    col5, col6, col7 = st.columns([1, 1, 2])
    
    with col5:
        # Currency filter - get available currencies from database
        try:
            cursor = repository.db.execute(
                "SELECT DISTINCT UPPER(home_currency) as currency FROM associates WHERE home_currency IS NOT NULL ORDER BY currency"
            )
            available_currencies = [row["currency"] for row in cursor.fetchall()]
            
            if not available_currencies:
                available_currencies = ["EUR"]  # Default fallback
        except Exception:
            available_currencies = ["EUR"]  # Default fallback
        
        currency_selection = st.multiselect(
            "💰 Currency",
            options=available_currencies,
            default=current_state["currency_filter"],
            key="hub_currency_filter_select",
            help="Filter by associate home currency"
        )
        
        if currency_selection != current_state["currency_filter"]:
            update_filter_state(currency_filter=currency_selection, page=0)
            should_refresh = True
    
    with col6:
        # Sort selector
        sort_options = {
            "Alias (A→Z)": "alias_asc",
            "Alias (Z→A)": "alias_desc",
            "Delta High→Low": "delta_desc", 
            "Delta Low→High": "delta_asc",
            "Last Activity Newest": "activity_desc",
            "Last Activity Oldest": "activity_asc"
        }
        
        sort_label = next(
            (label for label, value in sort_options.items() 
             if value == current_state["sort_by"]),
            "Alias (A→Z)"
        )
        
        selected_sort_label = st.selectbox(
            "📋 Sort By",
            options=list(sort_options.keys()),
            index=list(sort_options.keys()).index(sort_label),
            key="hub_sort_by_select",
            help="Sort order for associate listing"
        )
        
        sort_value = sort_options[selected_sort_label]
        if sort_value != current_state["sort_by"]:
            update_filter_state(sort_by=sort_value, page=0)
            should_refresh = True
    
    with col7:
        # Reset filters button and page info
        col7a, col7b, col7c = st.columns([1, 1, 2])
        
        with col7a:
            if st.button("🔄 Reset Filters", key="hub_reset_filters", help="Clear all filters"):
                update_filter_state(
                    search="",
                    admin_filter=[],
                    associate_status_filter=[],
                    bookmaker_status_filter=[],
                    currency_filter=[],
                    sort_by="alias_asc",
                    page=0
                )
                should_refresh = True
                st.rerun()
        
        with col7b:
            # Page size selector
            page_size = st.selectbox(
                "Page Size",
                options=[10, 25, 50, 100],
                index=[10, 25, 50, 100].index(current_state["page_size"]),
                key="hub_page_size_select",
                help="Number of associates per page"
            )
            
            if page_size != current_state["page_size"]:
                update_filter_state(page_size=page_size, page=0)
                should_refresh = True
        
        with col7c:
            st.markdown("&nbsp;")  # Spacer for alignment
            st.markdown(f"**Page:** {current_state['page'] + 1}")
    
    # Add horizontal rule
    st.divider()
    
    # Return updated state and refresh flag
    updated_state = get_filter_state()
    return updated_state, should_refresh


def render_pagination_info(total_count: int, current_state: Dict[str, Any]) -> None:
    """
    Render pagination information and controls.
    
    Args:
        total_count: Total number of associates matching filters
        current_state: Current filter state
    """
    if total_count == 0:
        st.warning("📭 No associates found matching current filters. Try adjusting or resetting filters.")
        return
    
    page_size = current_state["page_size"]
    current_page = current_state["page"]
    total_pages = (total_count + page_size - 1) // page_size
    start_idx = current_page * page_size + 1
    end_idx = min((current_page + 1) * page_size, total_count)
    
    # Pagination info
    col1, col2, col3, col4, col5 = st.columns([1, 1, 2, 1, 1])
    
    with col2:
        st.info(f"📊 Showing {start_idx}-{end_idx} of {total_count} associates")
    
    with col4:
        # Navigation buttons
        col4a, col4b = st.columns(2)
        
        with col4a:
            if st.button("⬅️ Previous", key="hub_prev_page", disabled=current_page == 0):
                update_filter_state(page=current_page - 1)
                st.rerun()
        
        with col4b:
            if st.button("Next ➡️", key="hub_next_page", disabled=current_page >= total_pages - 1):
                update_filter_state(page=current_page + 1)
                st.rerun()


def get_active_filters_count(current_state: Dict[str, Any]) -> int:
    """
    Count the number of active filters.
    
    Args:
        current_state: Current filter state
        
    Returns:
        Number of non-default filters active
    """
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
        count += 1  # Sort is technically a filter if not default
    
    return count
