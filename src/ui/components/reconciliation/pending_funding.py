from src.ui.utils.state_management import safe_rerun
﻿"""
Pending Funding Events Component.

Implements Story 5.4: Manual entry form and draft management interface
for deposit/withdrawal events awaiting approval.
"""

import streamlit as st
import sqlite3
from decimal import Decimal, InvalidOperation
from typing import List, Optional

from src.services.funding_service import FundingService, FundingDraft, FundingError
from src.core.database import get_db_connection
from src.ui.utils.formatters import format_eur, format_currency_amount
from src.ui.utils.validators import validate_balance_amount
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


def render_pending_funding_section() -> None:
    """Render the complete pending funding section with form and draft management."""
    st.markdown("### ðŸ’³ Pending Funding Events")
    st.markdown("*Review and approve deposit/withdrawal events so associate balances reflect cash movements.*")
    
    # Initialize funding service in session state if not exists
    if 'funding_service' not in st.session_state:
        st.session_state.funding_service = FundingService()
    
    funding_service = st.session_state.funding_service
    
    # Render manual entry form
    render_funding_entry_form(funding_service)
    
    # Get pending drafts
    drafts = funding_service.get_pending_drafts()
    
    if drafts:
        st.divider()
        render_pending_drafts_list(drafts, funding_service)
    
    # Render funding history
    st.divider()
    render_funding_history(funding_service)


def render_funding_entry_form(funding_service: FundingService) -> None:
    """Render the manual funding entry form."""
    with st.expander("âž• Add Funding Event", expanded=not funding_service.get_pending_drafts()):
        associates = get_active_associates()
        if not associates:
            st.error("âŒ No active associates found. Please add associates first.")
            return

        selected_associate = st.selectbox(
            "Associate*",
            options=associates,
            format_func=lambda a: a["display_alias"],
            key="funding_associate_select",
        )

        bookmakers = get_bookmakers_for_associate(selected_associate["id"])
        if not bookmakers:
            st.error(
                "âŒ No bookmakers found for this associate. Add a bookmaker before recording funding."
            )
            st.caption("Tip: Use the Admin & Associates page to register bookmakers.")
            return

        bookmaker_lookup = {
            b["id"]: b for b in bookmakers
        }
        bookmaker_labels = {
            bid: f"{info['bookmaker_name']} {'(inactive)' if not info['is_active'] else ''}"
            for bid, info in bookmaker_lookup.items()
        }
        bookmaker_ids = list(bookmaker_lookup.keys())
        bookmaker_select_key = f"funding_bookmaker_select_{selected_associate['id']}"

        with st.form("funding_entry_form"):
            col_event, col_bookmaker = st.columns([1, 1])

            with col_event:
                event_type = st.radio(
                    "Event Type*",
                    options=["DEPOSIT", "WITHDRAWAL"],
                    key="funding_event_type",
                )

            with col_bookmaker:
                selected_bookmaker_id = st.selectbox(
                    "Bookmaker*",
                    options=bookmaker_ids,
                    format_func=lambda bid: bookmaker_labels[bid],
                    key=bookmaker_select_key,
                )

            col3, col4 = st.columns(2)
            
            # Amount input
            with col3:
                amount_str = st.text_input(
                    "Amount*",
                    placeholder="0.00",
                    key="funding_amount",
                    help="Positive amount in selected currency"
                )
            
            # Currency selector
            with col4:
                currencies = get_supported_currencies()
                currency = st.selectbox(
                    "Currency*",
                    options=currencies,
                    key="funding_currency"
                )
            
            # Optional note
            note = st.text_area(
                "Note (Optional)",
                placeholder="e.g., Bank transfer from Partner A",
                key="funding_note"
            )
            
            # Submit button
            submit_button = st.form_submit_button(
                "âž• Add Funding Event",
                type="primary",
                width="stretch"
            )
            
            if submit_button:
                handle_funding_form_submit(
                    funding_service,
                    selected_associate['id'],
                    selected_bookmaker_id,
                    bookmaker_lookup[selected_bookmaker_id]['bookmaker_name'],
                    event_type,
                    amount_str,
                    currency,
                    note
                )


def render_pending_drafts_list(drafts: List[FundingDraft], funding_service: FundingService) -> None:
    """Render the list of pending funding drafts."""
    st.markdown("#### ðŸ“‹ Pending Funding Drafts")
    
    for draft in drafts:
        with st.container():
            # Draft header with actions
            col_info, col_actions = st.columns([4, 1])
            
            with col_info:
                # Draft details
                st.markdown(f"**{draft.associate_alias}** â†’ {draft.bookmaker_name} Â· {draft.event_type}")
                
                amount_display = format_currency_amount(
                    draft.amount_native,
                    draft.currency
                )
                st.markdown(f"{amount_display} â€¢ {draft.created_at_utc}")
                
                if draft.note:
                    st.caption(f"ðŸ“ {draft.note}")
            
            with col_actions:
                # Action buttons
                col_accept, col_reject = st.columns(2)
                
                with col_accept:
                    if st.button(
                        "âœ…",
                        key=f"accept_{draft.draft_id}",
                        help="Accept and create ledger entry",
                        type="primary"
                    ):
                        handle_accept_draft(funding_service, draft.draft_id)
                
                with col_reject:
                    if st.button(
                        "âŒ",
                        key=f"reject_{draft.draft_id}",
                        help="Reject and discard draft"
                    ):
                        handle_reject_draft(funding_service, draft.draft_id)
        
        st.divider()


def render_funding_history(funding_service: FundingService) -> None:
    """Render the funding history section."""
    st.markdown("#### ðŸ“š Recent Funding History")
    
    try:
        history = funding_service.get_funding_history(days=30)
        
        if not history:
            st.info("ðŸ“Š No funding events in the last 30 days.")
            return
        
        # Display history in a table
        for entry in history:
            with st.container():
                col_type, col_details = st.columns([1, 4])
                
                with col_type:
                    # Event type badge
                    badge_color = "green" if entry['event_type'] == 'DEPOSIT' else "orange"
                    st.markdown(f'<span style="background-color: {badge_color}; color: white; padding: 2px 8px; border-radius: 4px;">{entry["event_type"]}</span>', unsafe_allow_html=True)
                
                with col_details:
                    # Entry details
                    amount_native = format_currency_amount(
                        abs(entry['amount_native']),
                        entry['native_currency']
                    )
                    amount_eur = format_eur(entry['amount_eur'])
                    
                    st.markdown(
                        f"**{entry['associate_alias']}** â†’ {entry['bookmaker_name']} - {amount_native} ({amount_eur})"
                    )
                    st.caption(f"{entry['created_at_utc']}")
                    
                    if entry['note']:
                        st.caption(f"ðŸ“ {entry['note']}")
                
                st.divider()
    
    except FundingError as e:
        st.error(f"âŒ Failed to load funding history: {e}")


def handle_funding_form_submit(
    funding_service: FundingService,
    associate_id: int,
    bookmaker_id: int,
    bookmaker_name: str,
    event_type: str,
    amount_str: str,
    currency: str,
    note: Optional[str]
) -> None:
    """Handle submission of the funding entry form."""
    try:
        # Validate amount
        is_valid, error_msg = validate_balance_amount(amount_str)
        if not is_valid:
            st.error(f"âŒ {error_msg}")
            return
        
        amount = Decimal(amount_str)
        
        # Create draft
        draft_id = funding_service.create_funding_draft(
            associate_id=associate_id,
            bookmaker_id=bookmaker_id,
            event_type=event_type,
            amount_native=amount,
            currency=currency,
            note=note,
            bookmaker_name=bookmaker_name
        )
        
        st.success(f"âœ… Funding draft created for {bookmaker_name}!")
        safe_rerun()
        
    except FundingError as e:
        st.error(f"âŒ Failed to create funding draft: {e}")
        logger.error(
            "funding_draft_creation_failed",
            associate_id=associate_id,
            bookmaker_id=bookmaker_id,
            event_type=event_type,
            amount=amount_str,
            currency=currency,
            error=str(e)
        )


def handle_accept_draft(funding_service: FundingService, draft_id: str) -> None:
    """Handle acceptance of a funding draft."""
    try:
        ledger_id = funding_service.accept_funding_draft(draft_id)
        
        st.success(f"âœ… Funding event accepted! Ledger entry #{ledger_id} created.")
        safe_rerun()
        
    except FundingError as e:
        st.error(f"âŒ Failed to accept funding draft: {e}")
        logger.error(
            "funding_draft_acceptance_failed",
            draft_id=draft_id,
            error=str(e)
        )


def handle_reject_draft(funding_service: FundingService, draft_id: str) -> None:
    """Handle rejection of a funding draft."""
    try:
        funding_service.reject_funding_draft(draft_id)
        
        st.info("ðŸ“‹ Funding event discarded.")
        safe_rerun()
        
    except FundingError as e:
        st.error(f"âŒ Failed to reject funding draft: {e}")
        logger.error(
            "funding_draft_rejection_failed",
            draft_id=draft_id,
            error=str(e)
        )


def get_active_associates() -> List[dict]:
    """Get list of active associates for dropdown."""
    try:
        db = get_db_connection()
        cursor = db.execute(
            """
            SELECT id, display_alias 
            FROM associates 
            WHERE is_active = TRUE 
            ORDER BY display_alias
            """
        )
        
        associates = []
        for row in cursor.fetchall():
            associates.append({
                'id': row['id'],
                'display_alias': row['display_alias']
            })
        
        return associates
        
    except Exception as e:
        logger.error("failed_to_load_associates", error=str(e))
        st.error("âŒ Failed to load associates from database.")
        return []


def get_bookmakers_for_associate(associate_id: int) -> List[dict]:
    """Return bookmakers linked to the associate."""
    try:
        db = get_db_connection()
        cursor = db.execute(
            """
            SELECT id, bookmaker_name, is_active
            FROM bookmakers
            WHERE associate_id = ?
            ORDER BY bookmaker_name
            """,
            (associate_id,),
        )

        bookmakers: List[dict] = []
        for row in cursor.fetchall():
            bookmakers.append(
                {
                    "id": row["id"],
                    "bookmaker_name": row["bookmaker_name"],
                    "is_active": bool(row["is_active"]),
                }
            )
        return bookmakers
    except Exception as e:
        logger.error("failed_to_load_bookmakers", associate_id=associate_id, error=str(e))
        st.error("âŒ Failed to load bookmakers for the selected associate.")
        return []


def get_supported_currencies() -> List[str]:
    """Get list of supported currencies."""
    # Common currencies supported by the system
    return [
        "EUR",  # Euro
        "GBP",  # British Pound
        "USD",  # US Dollar
        "AUD",  # Australian Dollar
        "CAD",  # Canadian Dollar
        "CHF",  # Swiss Franc
        "NOK",  # Norwegian Krone
        "SEK",  # Swedish Krona
        "DKK",  # Danish Krone
    ]