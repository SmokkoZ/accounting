"""
Associate Operations Hub Page (Story 5.5)

Unified operations hub for reviewing and updating associates, their bookmakers,
balances, and funding transactions from one screen.
"""

from __future__ import annotations

import streamlit as st
import structlog
from typing import Dict, List

from src.repositories.associate_hub_repository import AssociateHubRepository
from src.services.funding_transaction_service import FundingTransactionService
from src.services.bookmaker_balance_service import BookmakerBalanceService
from src.ui.components.associate_hub import (
    render_filters,
    render_associate_listing,
    render_detail_drawer,
    render_pagination_info,
    get_filter_state
)
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

# Page configuration
st.set_page_config(
    page_title="Associate Operations Hub",
    page_icon="👤",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Page header
st.title("👤 Associate Operations Hub")
st.markdown(
    """
    Unified interface for managing associates, bookmakers, balances, and funding operations.
    Review status, update profiles, record balance checks, and process transactions.
    """
)


def main() -> None:
    """Main page logic."""
    # Initialize services
    try:
        repository = AssociateHubRepository()
        funding_service = FundingTransactionService()
        balance_service = BookmakerBalanceService()
    except Exception as e:
        st.error(f"❌ Failed to initialize services: {e}")
        logger.error("services_initialization_failed", error=str(e), exc_info=True)
        return

    # Render filters
    filter_state, should_refresh = render_filters(repository)
    
    # Auto-refresh on filter changes
    if should_refresh:
        st.rerun()
        return

    # Load data with current filters
    try:
        with st.spinner("🔄 Loading associate data..."):
            # Get associates matching filters
            associates = repository.list_associates_with_metrics(
                search=filter_state.get("search"),
                admin_filter=filter_state.get("admin_filter"),
                associate_status_filter=filter_state.get("associate_status_filter"),
                bookmaker_status_filter=filter_state.get("bookmaker_status_filter"),
                currency_filter=filter_state.get("currency_filter"),
                sort_by=filter_state.get("sort_by"),
                limit=filter_state.get("page_size"),
                offset=filter_state.get("page") * filter_state.get("page_size", 25)
            )
            
            # Get bookmakers for all associates (batch load for efficiency)
            associate_ids = [a.associate_id for a in associates]
            bookmakers_dict = {}
            
            if associate_ids:
                for associate_id in associate_ids:
                    bookmakers = repository.list_bookmakers_for_associate(associate_id)
                    if bookmakers:
                        bookmakers_dict[associate_id] = bookmakers
            
            # Get total count for pagination
            total_count = len(repository.list_associates_with_metrics(
                search=filter_state.get("search"),
                admin_filter=filter_state.get("admin_filter"),
                associate_status_filter=filter_state.get("associate_status_filter"),
                bookmaker_status_filter=filter_state.get("bookmaker_status_filter"),
                currency_filter=filter_state.get("currency_filter"),
                sort_by=filter_state.get("sort_by")
            ))
    
    except Exception as e:
        st.error(f"❌ Failed to load data: {e}")
        logger.error("data_loading_failed", error=str(e), exc_info=True)
        return

    # Render main listing
    if associates:
        render_associate_listing(associates, bookmakers_dict)
        
        # Render pagination controls
        render_pagination_info(total_count, filter_state)
    else:
        # Render empty state
        from src.ui.components.associate_hub.filters import render_empty_state
        render_empty_state(filter_state)

    # Render detail drawer if needed
    render_detail_drawer(repository, funding_service, balance_service)
    
    # Performance metrics (development only)
    if st.session_state.get("show_debug_info", False):
        with st.expander("🔧 Debug Info", expanded=False):
            st.write(f"**Total associates loaded:** {len(associates)}")
            st.write(f"**Bookmakers loaded:** {len(bookmakers_dict)}")
            st.write(f"**Filter state:** {filter_state}")
            
            # Performance timing
            if "load_start_time" in st.session_state:
                load_time = (st.session_state.get("load_end_time", 0) - 
                           st.session_state["load_start_time"])
                st.write(f"**Load time:** {load_time:.3f}s")


def handle_drawer_state() -> None:
    """Handle drawer-specific state management."""
    # Clear drawer state if closed
    if not st.session_state.get("hub_drawer_open", False):
        keys_to_clear = [
            "hub_drawer_associate_id",
            "hub_drawer_bookmaker_id", 
            "hub_drawer_tab",
            "hub_funding_action"
        ]
        for key in keys_to_clear:
            if key in st.session_state:
                del st.session_state[key]


def handle_keyboard_shortcuts() -> None:
    """Handle keyboard shortcuts for power users."""
    # Check for keyboard shortcuts in URL params or session state
    if st.session_state.get("shortcut_reset_filters"):
        from src.ui.components.associate_hub.filters import update_filter_state
        update_filter_state(
            search="",
            admin_filter=[],
            associate_status_filter=[],
            bookmaker_status_filter=[],
            currency_filter=[],
            sort_by="alias_asc",
            page=0
        )
        del st.session_state["shortcut_reset_filters"]
        st.rerun()


def validate_page_access() -> bool:
    """Validate user has access to associate operations.
    
    Returns:
        True if access is allowed, False otherwise
    """
    # For now, allow all users - this can be enhanced with role-based access
    return True


if __name__ == "__main__":
    # Validate access
    if not validate_page_access():
        st.error("❌ You don't have permission to access Associate Operations Hub")
        st.stop()
    
    # Handle special states
    handle_drawer_state()
    handle_keyboard_shortcuts()
    
    # Track performance
    import time
    st.session_state["load_start_time"] = time.time()
    
    try:
        main()
    except Exception as e:
        st.error(f"❌ Unexpected error: {e}")
        logger.error("page_error", error=str(e), exc_info=True)
    finally:
        st.session_state["load_end_time"] = time.time()
    
    # Sidebar help section
    with st.sidebar:
        st.divider()
        st.markdown("### 💡 Tips")
        
        tips = [
            "🔍 **Search** works on aliases, bookmakers, and chat IDs",
            "📊 **Expand rows** to see bookmaker details and actions", 
            "💰 **Funding actions** are available for each associate",
            "🔄 **Filters persist** across page refreshes",
            "⌨️ **Keyboard shortcuts:** Press 'R' to reset filters"
        ]
        
        for tip in tips:
            st.caption(tip)
        
        st.divider()
        st.markdown("### 📞 Help")
        st.caption("Need assistance? Contact the system administrator.")
        
        # Debug toggle (development only)
        if st.session_state.get("is_developer", False):
            show_debug = st.checkbox("🔧 Show Debug Info", value=st.session_state.get("show_debug_info", False))
            st.session_state["show_debug_info"] = show_debug


# Error handling for missing dependencies
try:
    # Verify required components are available
    from src.ui.components.associate_hub.filters import render_filters
    from src.ui.components.associate_hub.listing import render_associate_listing
    from src.ui.components.associate_hub.drawer import render_detail_drawer
except ImportError as e:
    st.error(f"❌ Missing required components: {e}")
    logger.error("missing_components", error=str(e), exc_info=True)
