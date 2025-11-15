"""
Listing component for Associate Operations Hub (Story 5.5)

Renders associate summary rows with expandable bookmaker sub-tables and action buttons.
Handles expand/collapse state persistence and displays status indicators.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Callable, Dict, List, Optional, Sequence

import streamlit as st

from src.repositories.associate_hub_repository import AssociateMetrics, BookmakerSummary
from src.ui.components.associate_hub.filters import RISK_LABELS, update_filter_state
from src.ui.utils.formatters import format_currency_amount
from src.ui.utils.state_management import safe_rerun
from src.ui.utils.identity_copy import identity_label, identity_tooltip

CARD_STYLE_KEY = "associate_card_styles_loaded"


@dataclass(frozen=True)
class QuickAction:
    """Definition for an action rendered within a card."""

    key_prefix: str
    label: str
    help_text: str
    callback: Callable[[AssociateMetrics], None]
    icon: Optional[str] = None
    button_type: str = "secondary"


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


def _ensure_card_styles() -> None:
    """Inject styling so associate cards have visible white borders."""
    if st.session_state.get(CARD_STYLE_KEY):
        return

    st.markdown(
        """
        <style>
        .associate-card {
            border: 1px solid rgba(255, 255, 255, 0.45);
            border-radius: 14px;
            padding: 1.25rem 1.5rem;
            margin-bottom: 1rem;
            background-color: rgba(255, 255, 255, 0.02);
            scroll-margin-top: 90px;
        }
        .associate-card.associate-card--highlight {
            border-color: #a5b4fc;
            box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.35);
        }
        .associate-card + .associate-card {
            margin-top: 0.5rem;
        }
        .associate-card h4 {
            margin-bottom: 0.25rem;
        }
        .associate-card .selected-pill {
            display: inline-flex;
            align-items: center;
            gap: 0.25rem;
            padding: 0.15rem 0.55rem;
            border-radius: 999px;
            background-color: rgba(99, 102, 241, 0.22);
            color: #c7d2fe;
            font-size: 0.75rem;
            font-weight: 500;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.session_state[CARD_STYLE_KEY] = True
def render_associate_listing(
    associates: List[AssociateMetrics],
    bookmakers_dict: Optional[Dict[int, List[BookmakerSummary]]] = None,
    *,
    quick_actions: Optional[Sequence[QuickAction]] = None,
    highlight_associate_id: Optional[int] = None,
    show_bookmakers: bool = True,
) -> None:
    """
    Render each associate as a card with summary metrics and bookmaker details.
    """
    if not associates:
        st.warning("No associates found matching current filters.")
        return

    _ensure_card_styles()
    bookmaker_lookup = bookmakers_dict or {}

    for associate in associates:
        is_highlighted = (
            highlight_associate_id is not None
            and associate.associate_id == highlight_associate_id
        )
        card_classes = "associate-card"
        if is_highlighted:
            card_classes += " associate-card--highlight"

        admin_label = "Admin" if associate.is_admin else "User"
        currency_label = associate.home_currency or "EUR"
        bookie_summary = f"{associate.active_bookmaker_count}/{associate.bookmaker_count}"
        status_label = associate.title()
        last_activity = _format_local_timestamp(associate.last_activity_utc)

        st.markdown(
            f"<div id='associate-card-{associate.associate_id}'></div>",
            unsafe_allow_html=True,
        )
        st.markdown(f'<div class="{card_classes}">', unsafe_allow_html=True)
        with st.container():
            header_cols = st.columns([3, 1, 1])
            with header_cols[0]:
                st.markdown(f"#### {associate.associate_alias}")
                st.caption(f"{admin_label} - Currency: {currency_label}")
                st.caption(f"{bookie_summary} bookmakers")
                if associate.telegram_chat_id:
                    st.caption(f"Telegram: {associate.telegram_chat_id}")
                if is_highlighted:
                    st.markdown(
                        "<span class='selected-pill'>"
                        ":material/star: Selected"
                        "</span>",
                        unsafe_allow_html=True,
                    )
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

            identity_cols = st.columns(5)
            identity_metrics = [
                {
                    "label": "Net Deposits (ND)",
                    "value": _format_optional_eur(associate.net_deposits_eur),
                    "delta": "Deposits - withdrawals",
                    "help": "ND sums DEPOSIT - WITHDRAWAL ledger entries.",
                },
                {
                    "label": "Fair Share (FS)",
                    "value": _format_signed_eur(associate.fair_share_eur),
                    "delta": "Equal-share ROI",
                    "help": "FS comes from BET_RESULT shares; can be +/- based on ROI.",
                },
                {
                    "label": identity_label(),
                    "value": _format_optional_eur(associate.should_hold_eur),
                    "delta": f"{associate.bookmaker_count} total",
                    "help": identity_tooltip(),
                },
                {
                    "label": "Total Balance (TB)",
                    "value": _format_optional_eur(associate.current_holding_eur),
                    "delta": "Latest snapshot",
                    "help": "TB aggregates bookmaker holdings from ledger entries.",
                },
                {
                    "label": "Imbalance (I'')",
                    "value": _format_signed_eur(associate.delta_eur),
                    "delta": status_label,
                    "help": "I'' = TB - YF. Positive = overholding, negative = short.",
                },
            ]
            for column, metric in zip(identity_cols, identity_metrics):
                column.metric(
                    metric["label"],
                    metric["value"],
                    delta=metric.get("delta"),
                    help=metric.get("help"),
                )

            render_action_buttons(associate, quick_actions=quick_actions)

            if show_bookmakers:
                bookmakers = bookmaker_lookup.get(associate.associate_id)
                if bookmakers:
                    with st.expander(
                        f"Bookmaker details \u2022 {associate.associate_alias}",
                        expanded=False,
                    ):
                        render_bookmaker_subtable(bookmakers)
                else:
                    st.info("No bookmakers configured for this associate.")
        st.markdown("</div>", unsafe_allow_html=True)


def render_action_buttons(
    associate: AssociateMetrics,
    *,
    quick_actions: Optional[Sequence[QuickAction]] = None,
) -> None:
    """
    Render dynamic action buttons for an associate card.
    """
    actions = [
        action for action in (quick_actions or _default_quick_actions())
        if action.callback is not None
    ]
    if not actions:
        return

    columns = st.columns(len(actions))
    for column, action in zip(columns, actions):
        with column:
            label = f"{action.icon} {action.label}" if action.icon else action.label
            if st.button(
                label,
                key=f"{action.key_prefix}_{associate.associate_id}",
                help=action.help_text,
                type=action.button_type,
                width='stretch',
            ):
                action.callback(associate)


def _default_quick_actions() -> Sequence[QuickAction]:
    """Default action layout for the operations hub."""
    return (
        QuickAction(
            key_prefix="edit_profile",
            label="Edit Profile",
            icon=":material/edit:",
            help_text="Edit associate details",
            callback=_open_drawer(tab="profile"),
        ),
        QuickAction(
            key_prefix="deposit",
            label="Deposit",
            icon=":material/savings:",
            help_text="Record deposit transaction",
            callback=_open_drawer(tab="transactions", funding_action="deposit"),
        ),
        QuickAction(
            key_prefix="withdraw",
            label="Withdraw",
            icon=":material/payments:",
            help_text="Record withdrawal transaction",
            callback=_open_drawer(tab="transactions", funding_action="withdraw"),
        ),
        QuickAction(
            key_prefix="details",
            label="View Details",
            icon=":material/visibility:",
            help_text="View full associate details",
            callback=_open_drawer(tab="profile"),
        ),
    )


def _open_drawer(
    *,
    tab: str,
    funding_action: Optional[str] = None,
) -> Callable[[AssociateMetrics], None]:
    """Return a callback that opens the shared drawer for an associate."""

    def _callback(associate: AssociateMetrics) -> None:
        st.session_state["hub_drawer_open"] = True
        st.session_state["hub_drawer_associate_id"] = associate.associate_id
        st.session_state.pop("hub_drawer_bookmaker_id", None)
        st.session_state["hub_drawer_tab"] = tab
        if funding_action:
            st.session_state["hub_funding_action"] = funding_action
        safe_rerun()

    return _callback


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

    if filter_state.get("bookmaker_status_filter"):
        status_labels = []
        if True in filter_state["bookmaker_status_filter"]:
            status_labels.append("Active")
        if False in filter_state["bookmaker_status_filter"]:
            status_labels.append("Inactive")
        active_filters.append(f"Bookmakers: {', '.join(status_labels)}")

    risk_values = filter_state.get("risk_filter") or []
    if risk_values:
        risk_labels = [RISK_LABELS.get(slug, slug.title()) for slug in risk_values]
        if risk_labels:
            active_filters.append(f"Risk: {', '.join(risk_labels)}")

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
            delta=f"{total_active} active  {total_admins} admins",
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
            delta=f"{overholding_count} over  {short_count} short",
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

