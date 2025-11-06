"""
Associate Operations Hub (Story 5.5)

Unified operations workspace for reviewing associates, their bookmakers, balances,
and funding transactions. Modern Streamlit primitives (fragments, status blocks)
are used when available to improve responsiveness without breaking compatibility
with older runtimes.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import streamlit as st
from streamlit.errors import StreamlitAPIException

from src.repositories.associate_hub_repository import AssociateHubRepository
from src.services.bookmaker_balance_service import BookmakerBalanceService
from src.services.funding_transaction_service import FundingTransactionService
from src.ui.components.associate_hub import (
    render_associate_listing,
    render_detail_drawer,
    render_filters,
    render_pagination_info,
    render_empty_state,
)
from src.ui.utils.feature_flags import has
from src.ui.ui_components import load_global_styles
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

load_global_styles()

PAGE_TITLE = "Associate Operations Hub"
PAGE_ICON = ":material/groups_3:"

def _configure_page() -> None:
    """Set page config when allowed (ignored if already configured)."""
    try:
        st.set_page_config(
            page_title=PAGE_TITLE,
            page_icon=PAGE_ICON,
            layout="wide",
            initial_sidebar_state="expanded",
        )
    except StreamlitAPIException:
        # Main app already configured the shell.
        pass


_configure_page()

st.title(f"{PAGE_ICON} {PAGE_TITLE}")
st.markdown(
    "Manage associates, bookmakers, balances, and funding movements in one place. "
    "Filters persist across refreshes for fast back-to-back operations."
)


def _load_associate_payload(
    repository: AssociateHubRepository, filter_state: Dict[str, object]
) -> Tuple[List[object], Dict[int, List[object]], int]:
    """Fetch associates, bookmakers, and total count for the current filters."""
    associates = repository.list_associates_with_metrics(
        search=filter_state.get("search"),
        admin_filter=filter_state.get("admin_filter"),
        associate_status_filter=filter_state.get("associate_status_filter"),
        bookmaker_status_filter=filter_state.get("bookmaker_status_filter"),
        currency_filter=filter_state.get("currency_filter"),
        sort_by=filter_state.get("sort_by"),
        limit=filter_state.get("page_size"),
        offset=filter_state.get("page", 0) * filter_state.get("page_size", 25),
    )

    associate_ids = [assoc.associate_id for assoc in associates]
    bookmakers: Dict[int, List[object]] = {}

    if associate_ids:
        for associate_id in associate_ids:
            items = repository.list_bookmakers_for_associate(associate_id)
            if items:
                bookmakers[associate_id] = items

    total_count = len(
        repository.list_associates_with_metrics(
            search=filter_state.get("search"),
            admin_filter=filter_state.get("admin_filter"),
            associate_status_filter=filter_state.get("associate_status_filter"),
            bookmaker_status_filter=filter_state.get("bookmaker_status_filter"),
            currency_filter=filter_state.get("currency_filter"),
            sort_by=filter_state.get("sort_by"),
        )
    )

    return associates, bookmakers, total_count


def main() -> None:
    """Render the Associate Operations Hub page."""
    try:
        repository = AssociateHubRepository()
        funding_service = FundingTransactionService()
        balance_service = BookmakerBalanceService()
    except Exception as exc:
        st.error(f"Failed to initialise services: {exc}")
        logger.error("services_initialization_failed", error=str(exc), exc_info=True)
        return

    filter_state, should_refresh = render_filters(repository)

    if should_refresh:
        st.rerun()
        return

    def render_listing_section() -> None:
        load_label = "Loading associate data..."

        try:
            if has("status"):
                with st.status(load_label, expanded=False) as status:
                    associates, bookmakers, total_count = _load_associate_payload(
                        repository, filter_state
                    )
                    status.update(label="Associates loaded", state="complete")
            else:
                with st.spinner(load_label):
                    associates, bookmakers, total_count = _load_associate_payload(
                        repository, filter_state
                    )
        except Exception as exc:
            st.error(f"Failed to load associate data: {exc}")
            logger.error("data_loading_failed", error=str(exc), exc_info=True)
            return

        if associates:
            render_associate_listing(associates, bookmakers)
            render_pagination_info(total_count, filter_state)
        else:
            render_empty_state(filter_state)

        if st.session_state.get("show_debug_info"):
            st.markdown("### Debug Info")
            st.write(f"Associates returned: {len(associates)}")
            st.write(f"Bookmakers loaded: {len(bookmakers)}")
            st.write(f"Current filter state: {filter_state}")

    if has("fragment"):
        # Refresh the listing every 60 seconds without re-running filters.
        @st.fragment(run_every=60)
        def listing_fragment() -> None:
            render_listing_section()

        listing_fragment()
    else:
        render_listing_section()

    # Drawer must render outside the fragment to avoid sidebar restrictions.
    render_detail_drawer(repository, funding_service, balance_service)


def handle_drawer_state() -> None:
    """Clear drawer state when the drawer is closed."""
    if not st.session_state.get("hub_drawer_open", False):
        for key in (
            "hub_drawer_associate_id",
            "hub_drawer_bookmaker_id",
            "hub_drawer_tab",
            "hub_funding_action",
        ):
            st.session_state.pop(key, None)


def handle_keyboard_shortcuts() -> None:
    """Apply keyboard shortcuts for power users."""
    if st.session_state.get("shortcut_reset_filters"):
        from src.ui.components.associate_hub.filters import update_filter_state

        update_filter_state(
            search="",
            admin_filter=[],
            associate_status_filter=[],
            bookmaker_status_filter=[],
            currency_filter=[],
            sort_by="alias_asc",
            page=0,
        )
        st.session_state.pop("shortcut_reset_filters")
        st.rerun()


def validate_page_access() -> bool:
    """Placeholder access control hook."""
    return True


if __name__ == "__main__":
    if not validate_page_access():
        st.error("You do not have permission to access the Associate Operations Hub.")
        st.stop()

    handle_drawer_state()
    handle_keyboard_shortcuts()

    import time

    st.session_state["load_start_time"] = time.time()

    try:
        main()
    except Exception as exc:  # pragma: no cover - ensure visibility
        st.error(f"Unexpected error: {exc}")
        logger.error("page_error", error=str(exc), exc_info=True)
    finally:
        st.session_state["load_end_time"] = time.time()

    with st.sidebar:
        st.divider()
        st.markdown("### Tips")
        st.caption("- Search covers aliases, bookmakers, and chat IDs.")
        st.caption("- Expand rows to reveal bookmaker details and actions.")
        st.caption("- Funding actions are available within each associate drawer.")
        st.caption("- Filters persist across refreshes for rapid triage.")
        st.caption("- Press 'R' to reset filters when keyboard shortcuts are enabled.")

        st.divider()
        st.markdown("### Help")
        st.caption("Need assistance? Contact the system administrator.")

        if st.session_state.get("is_developer"):
            show_debug = st.checkbox(
                "Show Debug Info", value=st.session_state.get("show_debug_info", False)
            )
            st.session_state["show_debug_info"] = show_debug
