from src.ui.utils.state_management import safe_rerun
﻿"""
Drawer component for Associate Operations Hub (Story 5.5)

Multi-tab detail surface for associate profile, balance management, and transaction history.
Handles forms for editing associate/bookmaker details and funding operations.
"""

from __future__ import annotations

import streamlit as st
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Any

from src.repositories.associate_hub_repository import AssociateHubRepository, BookmakerSummary
from src.services.funding_transaction_service import (
    FundingTransactionService, 
    FundingTransaction, 
    FundingTransactionError
)
from src.services.bookmaker_balance_service import BookmakerBalanceService
from src.ui.utils.validators import validate_decimal_input, validate_currency_code


def render_detail_drawer(
    repository: AssociateHubRepository,
    funding_service: FundingTransactionService,
    balance_service: BookmakerBalanceService
) -> None:
    """
    Render the main detail drawer with tabs.
    
    Args:
        repository: AssociateHubRepository instance
        funding_service: FundingTransactionService instance  
        balance_service: BookmakerBalanceService instance
    """
    # Check if drawer should be open
    if not st.session_state.get("hub_drawer_open", False):
        return
    
    associate_id = st.session_state.get("hub_drawer_associate_id")
    bookmaker_id = st.session_state.get("hub_drawer_bookmaker_id")
    current_tab = st.session_state.get("hub_drawer_tab", "profile")
    
    if not associate_id:
        st.error("âŒ Associate ID not found")
        return
    
    # Get associate data
    associate = repository.get_associate_for_edit(associate_id)
    if not associate:
        st.error(f"âŒ Associate {associate_id} not found")
        return
    
    # Render drawer with tabs
    with st.sidebar:
        st.markdown("## ðŸ‘¤ Associate Details")
        st.markdown(f"**{associate['display_alias']}** (ID: {associate_id})")
        st.divider()
        
        # Close button
        if st.button("âŒ Close", key="hub_drawer_close", width="stretch"):
            st.session_state["hub_drawer_open"] = False
            # Clear drawer-specific state
            for key in ["hub_drawer_associate_id", "hub_drawer_bookmaker_id", "hub_drawer_tab", "hub_funding_action"]:
                if key in st.session_state:
                    del st.session_state[key]
            safe_rerun()
        
        st.divider()
        
        # Tab navigation
        tab1, tab2, tab3 = st.tabs(["ðŸ‘¤ Profile", "ðŸ’° Balances", "ðŸ“Š Transactions"])
        
        with tab1:
            render_profile_tab(repository, associate, bookmaker_id)
        
        with tab2:
            render_balances_tab(balance_service, associate, bookmaker_id)
        
        with tab3:
            render_transactions_tab(funding_service, associate, bookmaker_id)


def render_profile_tab(
    repository: AssociateHubRepository,
    associate: Dict[str, Any],
    bookmaker_id: Optional[int]
) -> None:
    """
    Render profile tab for editing associate and bookmaker details.
    
    Args:
        repository: AssociateHubRepository instance
        associate: Associate data
        bookmaker_id: Optional bookmaker ID to focus on
    """
    st.markdown("### ðŸ“ Edit Profile")
    
    # Associate editing form
    with st.form("associate_edit_form"):
        st.markdown("#### ðŸ‘¤ Associate Information")
        
        col1, col2 = st.columns(2)
        
        with col1:
            display_alias = st.text_input(
                "Display Alias*",
                value=associate["display_alias"],
                key="associate_display_alias",
                help="Display name for the associate"
            )
            
            home_currency = st.text_input(
                "Home Currency*",
                value=associate["home_currency"],
                key="associate_home_currency",
                max_chars=3,
                help="3-letter ISO currency code (e.g., EUR, GBP, USD)"
            )
        
        with col2:
            telegram_chat_id = st.text_input(
                "Telegram Chat ID",
                value=associate["telegram_chat_id"] or "",
                key="associate_telegram_chat_id",
                help="Optional Telegram chat ID for notifications"
            )
            
            is_admin = st.checkbox(
                "Admin User",
                value=associate["is_admin"],
                key="associate_is_admin",
                help="Grant administrative privileges"
            )
            
            is_active = st.checkbox(
                "Active Associate",
                value=associate["is_active"],
                key="associate_is_active",
                help="Associate is currently active"
            )
        
        # Submit button for associate
        col1, col2 = st.columns(2)
        with col1:
            if st.form_submit_button("ðŸ’¾ Save Associate", type="primary"):
                try:
                    # Validation
                    if not display_alias.strip():
                        st.error("âŒ Display alias is required")
                        return
                    
                    if not validate_currency_code(home_currency):
                        st.error("âŒ Invalid currency code")
                        return
                    
                    # Update associate
                    repository.update_associate(
                        associate_id=associate["id"],
                        display_alias=display_alias.strip(),
                        home_currency=home_currency.upper(),
                        is_admin=is_admin,
                        is_active=is_active,
                        telegram_chat_id=telegram_chat_id.strip() or None
                    )
                    
                    st.success("âœ… Associate updated successfully!")
                    safe_rerun()
                    
                except Exception as e:
                    st.error(f"âŒ Failed to update associate: {e}")
        
        with col2:
            if st.form_submit_button("ðŸ”„ Reset"):
                # Reset form to current values
                for key in ["associate_display_alias", "associate_home_currency", 
                           "associate_telegram_chat_id", "associate_is_admin", "associate_is_active"]:
                    if key in st.session_state:
                        del st.session_state[key]
                safe_rerun()
    
    st.divider()
    
    # Bookmaker management
    render_bookmaker_management(repository, associate["id"])


def render_bookmaker_management(repository: AssociateHubRepository, associate_id: int) -> None:
    """
    Render bookmaker management section.
    
    Args:
        repository: AssociateHubRepository instance
        associate_id: Associate ID
    """
    st.markdown("#### ðŸ“Š Bookmaker Management")
    
    # Get bookmakers for this associate
    bookmakers = repository.list_bookmakers_for_associate(associate_id)
    
    if not bookmakers:
        st.info("ðŸ“­ No bookmakers configured for this associate.")
        return
    
    # Display existing bookmakers with edit forms
    for bookmaker in bookmakers:
        with st.expander(f"ðŸ“Š {bookmaker.bookmaker_name}", expanded=False):
            bookmaker_data = {
                "id": bookmaker.bookmaker_id,
                "bookmaker_name": bookmaker.bookmaker_name,
                "is_active": bookmaker.is_active,
                "parsing_profile": bookmaker.parsing_profile or ""
            }
            
            render_bookmaker_edit_form(repository, bookmaker_data)


def render_bookmaker_edit_form(
    repository: AssociateHubRepository,
    bookmaker_data: Dict[str, Any]
) -> None:
    """
    Render form for editing a single bookmaker.
    
    Args:
        repository: AssociateHubRepository instance
        bookmaker_data: Bookmaker data
    """
    with st.form(f"bookmaker_edit_form_{bookmaker_data['id']}"):
        col1, col2 = st.columns(2)
        
        with col1:
            bookmaker_name = st.text_input(
                "Bookmaker Name*",
                value=bookmaker_data["bookmaker_name"],
                key=f"bookmaker_name_{bookmaker_data['id']}",
                help="Display name for the bookmaker"
            )
        
        with col2:
            is_active = st.checkbox(
                "Active Bookmaker",
                value=bookmaker_data["is_active"],
                key=f"bookmaker_active_{bookmaker_data['id']}",
                help="Bookmaker is currently active"
            )
        
        parsing_profile = st.text_area(
            "Parsing Profile",
            value=bookmaker_data["parsing_profile"],
            key=f"bookmaker_profile_{bookmaker_data['id']}",
            help="Optional parsing configuration for bet slip processing",
            height=100
        )
        
        col1, col2 = st.columns(2)
        with col1:
            if st.form_submit_button("ðŸ’¾ Save Bookmaker", type="primary"):
                try:
                    if not bookmaker_name.strip():
                        st.error("âŒ Bookmaker name is required")
                        return
                    
                    repository.update_bookmaker(
                        bookmaker_id=bookmaker_data["id"],
                        bookmaker_name=bookmaker_name.strip(),
                        is_active=is_active,
                        parsing_profile=parsing_profile.strip() or None
                    )
                    
                    st.success("âœ… Bookmaker updated successfully!")
                    safe_rerun()
                    
                except Exception as e:
                    st.error(f"âŒ Failed to update bookmaker: {e}")
        
        with col2:
            if st.form_submit_button("ðŸ”„ Reset"):
                # Reset form
                for key in [f"bookmaker_name_{bookmaker_data['id']}", 
                           f"bookmaker_active_{bookmaker_data['id']}",
                           f"bookmaker_profile_{bookmaker_data['id']}"]:
                    if key in st.session_state:
                        del st.session_state[key]
                safe_rerun()


def render_balances_tab(
    balance_service: BookmakerBalanceService,
    associate: Dict[str, Any],
    bookmaker_id: Optional[int]
) -> None:
    """
    Render balance management tab.
    
    Args:
        balance_service: BookmakerBalanceService instance
        associate: Associate data
        bookmaker_id: Optional bookmaker ID to focus on
    """
    st.markdown("### ðŸ’° Balance Management")
    
    # Get bookmakers for associate
    try:
        bookmaker_balances = balance_service.get_bookmaker_balances()
        associate_bookmakers = [
            b for b in bookmaker_balances 
            if b.associate_id == associate["id"]
        ]
    except Exception as e:
        st.error(f"âŒ Failed to load bookmaker balances: {e}")
        return
    
    if not associate_bookmakers:
        st.info("ðŸ“­ No bookmakers found for this associate.")
        return
    
    # Balance check form
    st.markdown("#### ðŸ“ Add Balance Check")
    
    # Bookmaker selection
    bookmaker_options = {
        b.bookmaker_id: f"{b.bookmaker_name} ({b.bookmaker_id})"
        for b in associate_bookmakers
    }
    
    selected_bookmaker_id = st.selectbox(
        "Select Bookmaker*",
        options=list(bookmaker_options.keys()),
        format_func=lambda x: bookmaker_options[x],
        key="balance_check_bookmaker",
        help="Choose bookmaker to update balance for"
    )
    
    # Get selected bookmaker details
    selected_bookmaker = next(
        (b for b in associate_bookmakers if b.bookmaker_id == selected_bookmaker_id),
        None
    )
    
    if selected_bookmaker:
        with st.form("balance_check_form"):
            col1, col2 = st.columns(2)
            
            with col1:
                balance_native = st.text_input(
                    "Reported Balance*",
                    key="balance_check_amount",
                    placeholder="e.g., 1000.00",
                    help="Current balance reported by bookmaker"
                )
                
                native_currency = st.text_input(
                    "Currency*",
                    value=selected_bookmaker.native_currency,
                    key="balance_check_currency",
                    max_chars=3,
                    help="Currency of the reported balance"
                )
            
            with col2:
                check_note = st.text_area(
                    "Note",
                    key="balance_check_note",
                    placeholder="Optional notes about this balance check...",
                    help="Any additional context about this balance check",
                    height=80
                )
            
            if st.form_submit_button("ðŸ’¾ Record Balance Check", type="primary"):
                try:
                    # Validation
                    if not balance_native.strip():
                        st.error("âŒ Balance amount is required")
                        return
                    
                    if not validate_currency_code(native_currency):
                        st.error("âŒ Invalid currency code")
                        return
                    
                    amount = validate_decimal_input(balance_native)
                    if amount is None:
                        st.error("âŒ Invalid balance amount")
                        return
                    
                    if amount <= 0:
                        st.error("âŒ Balance must be positive")
                        return
                    
                    # Record balance check
                    record_id = balance_service.update_reported_balance(
                        associate_id=associate["id"],
                        bookmaker_id=selected_bookmaker_id,
                        balance_native=amount,
                        native_currency=native_currency.upper(),
                        note=check_note.strip() or None
                    )
                    
                    st.success(f"âœ… Balance check recorded successfully (ID: {record_id})!")
                    safe_rerun()
                    
                except Exception as e:
                    st.error(f"âŒ Failed to record balance check: {e}")
    
    st.divider()
    
    # Balance history
    st.markdown("#### ðŸ“Š Recent Balance Checks")
    
    # Filter bookmaker if specified
    display_bookmakers = associate_bookmakers
    if bookmaker_id:
        display_bookmakers = [
            b for b in associate_bookmakers 
            if b.bookmaker_id == bookmaker_id
        ]
    
    for bookmaker in display_bookmakers:
        with st.expander(f"ðŸ“Š {bookmaker.bookmaker_name}", expanded=False):
            render_bookmaker_balance_summary(bookmaker)


def render_bookmaker_balance_summary(bookmaker) -> None:
    """
    Render summary for a single bookmaker balance.
    
    Args:
        bookmaker: BookmakerBalance object
    """
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            "Modeled Balance",
            f"â‚¬{bookmaker.modeled_balance_eur:,.2f}",
            delta="From ledger"
        )
    
    with col2:
        if bookmaker.reported_balance_eur:
            st.metric(
                "Reported Balance",
                f"â‚¬{bookmaker.reported_balance_eur:,.2f}",
                delta=f"In {bookmaker.native_currency}"
            )
        else:
            st.metric("Reported Balance", "Not reported", delta="â€”")
    
    with col3:
        if bookmaker.difference_eur:
            delta_color = "normal" if abs(bookmaker.difference_eur) <= 10 else "inverse"
            st.metric(
                "Difference",
                f"â‚¬{abs(bookmaker.difference_eur):,.2f}",
                delta=bookmaker.status_label,
                delta_color=delta_color
            )
        else:
            st.metric("Difference", "â€”", delta="No comparison")
    
    with col4:
        if bookmaker.last_checked_at_utc:
            try:
                from datetime import datetime
                check_date = datetime.fromisoformat(bookmaker.last_checked_at_utc.replace('Z', '+00:00'))
                st.write(f"**Last Check:**")
                st.write(check_date.strftime('%Y-%m-%d %H:%M'))
            except (ValueError, AttributeError):
                st.write(f"**Last Check:**")
                st.write(bookmaker.last_checked_at_utc[:19])
        else:
            st.write("**Last Check:**")
            st.write("Never")


def render_transactions_tab(
    funding_service: FundingTransactionService,
    associate: Dict[str, Any],
    bookmaker_id: Optional[int]
) -> None:
    """
    Render transactions tab with funding forms and history.
    
    Args:
        funding_service: FundingTransactionService instance
        associate: Associate data
        bookmaker_id: Optional bookmaker ID to focus on
    """
    st.markdown("### ðŸ“Š Funding & Transactions")
    
    # Funding action
    funding_action = st.session_state.get("hub_funding_action", "deposit")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("ðŸ’° Deposit", key="switch_deposit", width="stretch"):
            st.session_state["hub_funding_action"] = "deposit"
            safe_rerun()
    
    with col2:
        if st.button("ðŸ’¸ Withdraw", key="switch_withdraw", width="stretch"):
            st.session_state["hub_funding_action"] = "withdraw"
            safe_rerun()
    
    # Funding form
    action_text = "Deposit" if funding_action == "deposit" else "Withdrawal"
    st.markdown(f"#### ðŸ’° Record {action_text}")
    
    with st.form("funding_transaction_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            amount_native = st.text_input(
                f"{action_text} Amount*",
                key="funding_amount",
                placeholder="e.g., 500.00",
                help=f"Amount to {funding_action.lower()} in associate's home currency"
            )
            
            native_currency = st.text_input(
                "Currency*",
                value=associate["home_currency"],
                key="funding_currency",
                max_chars=3,
                help="Currency for the transaction"
            )
        
        with col2:
            # Bookmaker selection (optional)
            try:
                bookmakers = funding_service.db.execute(
                    "SELECT id, bookmaker_name FROM bookmakers WHERE associate_id = ? ORDER BY bookmaker_name",
                    (associate["id"],)
                ).fetchall()
                
                bookmaker_options = {None: "Associate-level"} | {
                    b["id"]: b["bookmaker_name"] for b in bookmakers
                }
            except Exception:
                bookmaker_options = {None: "Associate-level"}
            
            selected_bookmaker_id = st.selectbox(
                "Bookmaker (Optional)",
                options=list(bookmaker_options.keys()),
                format_func=lambda x: bookmaker_options[x],
                key="funding_bookmaker",
                help="Optional: restrict transaction to specific bookmaker"
            )
            
            note = st.text_area(
                "Note",
                key="funding_note",
                placeholder="Optional notes about this transaction...",
                help="Any additional context about this transaction",
                height=80
            )
        
        if st.form_submit_button(f"ðŸ’¾ Record {action_text}", type="primary"):
            try:
                # Validation
                if not amount_native.strip():
                    st.error("âŒ Amount is required")
                    return
                
                if not validate_currency_code(native_currency):
                    st.error("âŒ Invalid currency code")
                    return
                
                amount = validate_decimal_input(amount_native)
                if amount is None:
                    st.error("âŒ Invalid amount")
                    return
                
                if amount <= 0:
                    st.error("âŒ Amount must be positive")
                    return
                
                # Create and record transaction
                transaction = FundingTransaction(
                    associate_id=associate["id"],
                    bookmaker_id=selected_bookmaker_id,
                    transaction_type=funding_action.upper(),
                    amount_native=amount,
                    native_currency=native_currency.upper(),
                    note=note.strip() or None
                )
                
                ledger_id = funding_service.record_transaction(transaction)
                
                st.success(f"âœ… {action_text} recorded successfully (ID: {ledger_id})!")
                
                # Clear form
                for key in ["funding_amount", "funding_currency", "funding_bookmaker", "funding_note"]:
                    if key in st.session_state:
                        del st.session_state[key]
                
                safe_rerun()
                
            except FundingTransactionError as e:
                st.error(f"âŒ {e}")
            except Exception as e:
                st.error(f"âŒ Failed to record transaction: {e}")
    
    st.divider()
    
    # Transaction history
    st.markdown("#### ðŸ“œ Recent Transactions")
    
    try:
        history = funding_service.get_transaction_history(
            associate_id=associate["id"],
            bookmaker_id=bookmaker_id,
            days=30
        )
        
        if not history:
            st.info("ðŸ“­ No recent transactions found.")
            return
        
        # Display transactions
        for transaction in history:
            with st.expander(
                f"{'ðŸ’°' if transaction['transaction_type'] == 'DEPOSIT' else 'ðŸ’¸'} "
                f"{transaction['transaction_type']} - "
                f"{transaction['created_at_utc'][:10]}",
                expanded=False
            ):
                render_transaction_details(transaction)
                
    except Exception as e:
        st.error(f"âŒ Failed to load transaction history: {e}")


def render_transaction_details(transaction: Dict[str, Any]) -> None:
    """
    Render details for a single transaction.
    
    Args:
        transaction: Transaction data
    """
    col1, col2 = st.columns(2)
    
    with col1:
        st.write(f"**Type:** {transaction['transaction_type']}")
        st.write(f"**Amount:** {transaction['native_currency']} {transaction['amount_native']:,.2f}")
        st.write(f"**EUR Equivalent:** â‚¬{transaction['amount_eur']:,.2f}")
        st.write(f"**FX Rate:** {transaction['fx_rate_snapshot']}")
    
    with col2:
        if transaction['bookmaker_name']:
            st.write(f"**Bookmaker:** {transaction['bookmaker_name']}")
        
        st.write(f"**Created:** {transaction['created_at_utc']}")
        st.write(f"**Created By:** {transaction['created_by']}")
        
        if transaction['note']:
            st.write(f"**Note:** {transaction['note']}")