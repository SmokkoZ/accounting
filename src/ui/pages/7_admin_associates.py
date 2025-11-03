"""
Admin Associates page - manage associates and bookmakers.

This page provides:
- View all associates with search/filter
- Add new associates
- Edit existing associates
- Delete associates (with validation)
- Manage bookmakers per associate
"""

import streamlit as st
import structlog
import sqlite3
from typing import List, Dict, Optional, Tuple
from datetime import datetime, date, timedelta
from decimal import Decimal

from src.core.database import get_db_connection
from src.ui.utils.validators import (
    validate_currency,
    validate_alias,
    validate_multibook_chat_id,
    validate_json,
    validate_balance_amount,
    VALID_CURRENCIES,
)
from src.ui.utils.formatters import (
    format_utc_datetime_local,
    format_currency_with_symbol,
)
from src.services.fx_manager import get_fx_rate, get_latest_fx_rate, convert_to_eur
from src.ui.pages.balance_management import render_balance_history_tab

logger = structlog.get_logger()

# ============================================================================
# DATABASE QUERY FUNCTIONS - ASSOCIATES
# ============================================================================


def load_associates(
    filter_alias: Optional[str] = None, conn: Optional[sqlite3.Connection] = None
) -> List[Dict]:
    """Load all associates with bookmaker count.

    Args:
        filter_alias: Optional case-insensitive filter on display_alias
        conn: Optional database connection (for testing)

    Returns:
        List of associate dictionaries with bookmaker_count field
    """
    if conn is None:
        conn = get_db_connection()
    cursor = conn.cursor()

    query = """
        SELECT
            a.id,
            a.display_alias,
            a.home_currency,
            a.is_admin,
            a.multibook_chat_id,
            a.created_at_utc,
            a.updated_at_utc,
            COUNT(b.id) AS bookmaker_count
        FROM associates a
        LEFT JOIN bookmakers b ON a.id = b.associate_id
    """

    params = []
    if filter_alias and filter_alias.strip():
        query += " WHERE LOWER(a.display_alias) LIKE LOWER(?)"
        params.append(f"%{filter_alias.strip()}%")

    query += " GROUP BY a.id ORDER BY a.display_alias ASC"

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [dict(row) for row in rows]


def insert_associate(
    display_alias: str,
    home_currency: str,
    is_admin: bool,
    multibook_chat_id: Optional[str],
    conn: Optional[sqlite3.Connection] = None,
) -> Tuple[bool, str]:
    """Insert new associate into database.

    Args:
        display_alias: Unique display name
        home_currency: ISO currency code
        is_admin: Admin flag (True/False)
        multibook_chat_id: Optional Telegram chat ID
        conn: Optional database connection (for testing)

    Returns:
        Tuple of (success: bool, message: str)
    """
    if conn is None:
        conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO associates (
                display_alias,
                home_currency,
                is_admin,
                multibook_chat_id,
                created_at_utc,
                updated_at_utc
            ) VALUES (?, ?, ?, ?, datetime('now') || 'Z', datetime('now') || 'Z')
            """,
            (
                display_alias.strip(),
                home_currency.upper(),
                1 if is_admin else 0,
                multibook_chat_id.strip() if multibook_chat_id else None,
            ),
        )
        conn.commit()
        logger.info(
            "associate_created",
            alias=display_alias,
            currency=home_currency,
            is_admin=is_admin,
        )
        return True, f"✅ Associate '{display_alias}' created"
    except Exception as e:
        conn.rollback()
        logger.error("associate_insert_failed", error=str(e), alias=display_alias)
        return False, f"❌ Failed to create associate: {str(e)}"


def update_associate(
    associate_id: int,
    display_alias: str,
    home_currency: str,
    is_admin: bool,
    multibook_chat_id: Optional[str],
    conn: Optional[sqlite3.Connection] = None,
) -> Tuple[bool, str]:
    """Update existing associate in database.

    Args:
        associate_id: ID of associate to update
        display_alias: New display name
        home_currency: New currency code
        is_admin: New admin flag
        multibook_chat_id: New Telegram chat ID
        conn: Optional database connection (for testing)

    Returns:
        Tuple of (success: bool, message: str)
    """
    if conn is None:
        conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            UPDATE associates
            SET display_alias = ?,
                home_currency = ?,
                is_admin = ?,
                multibook_chat_id = ?,
                updated_at_utc = datetime('now') || 'Z'
            WHERE id = ?
            """,
            (
                display_alias.strip(),
                home_currency.upper(),
                1 if is_admin else 0,
                multibook_chat_id.strip() if multibook_chat_id else None,
                associate_id,
            ),
        )
        conn.commit()
        logger.info("associate_updated", associate_id=associate_id, alias=display_alias)
        return True, "✅ Associate updated"
    except Exception as e:
        conn.rollback()
        logger.error("associate_update_failed", error=str(e), associate_id=associate_id)
        return False, f"❌ Failed to update associate: {str(e)}"


def can_delete_associate(
    associate_id: int, conn: Optional[sqlite3.Connection] = None
) -> Tuple[bool, str]:
    """Check if associate can be safely deleted.

    Args:
        associate_id: ID of associate to check
        conn: Optional database connection (for testing)

    Returns:
        Tuple of (can_delete: bool, reason: str)
    """
    if conn is None:
        conn = get_db_connection()
    cursor = conn.cursor()

    # Check bets
    cursor.execute("SELECT COUNT(*) FROM bets WHERE associate_id = ?", (associate_id,))
    bet_count = cursor.fetchone()[0]

    # Check ledger entries
    cursor.execute("SELECT COUNT(*) FROM ledger_entries WHERE associate_id = ?", (associate_id,))
    ledger_count = cursor.fetchone()[0]

    if bet_count > 0 or ledger_count > 0:
        return (
            False,
            f"Cannot delete: {bet_count} bet(s) and {ledger_count} ledger entry(ies) exist",
        )

    return True, "OK"


def delete_associate(
    associate_id: int, conn: Optional[sqlite3.Connection] = None
) -> Tuple[bool, str]:
    """Delete associate from database (cascades to bookmakers).

    Args:
        associate_id: ID of associate to delete
        conn: Optional database connection (for testing)

    Returns:
        Tuple of (success: bool, message: str)
    """
    if conn is None:
        conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Get alias for logging
        cursor.execute("SELECT display_alias FROM associates WHERE id = ?", (associate_id,))
        row = cursor.fetchone()
        alias = row[0] if row else "Unknown"

        # Delete (cascades to bookmakers via ON DELETE CASCADE)
        cursor.execute("DELETE FROM associates WHERE id = ?", (associate_id,))
        conn.commit()

        logger.info("associate_deleted", associate_id=associate_id, alias=alias)
        return True, f"✅ Associate '{alias}' deleted"
    except Exception as e:
        conn.rollback()
        logger.error("associate_delete_failed", error=str(e), associate_id=associate_id)
        return False, f"❌ Failed to delete associate: {str(e)}"


# ============================================================================
# DATABASE QUERY FUNCTIONS - BOOKMAKERS
# ============================================================================


def load_bookmakers_for_associate(
    associate_id: int, conn: Optional[sqlite3.Connection] = None
) -> List[Dict]:
    """Load all bookmakers for an associate with latest balance check.

    Args:
        associate_id: ID of the associate
        conn: Optional database connection (for testing)

    Returns:
        List of bookmaker dictionaries with balance info
    """
    if conn is None:
        conn = get_db_connection()
    cursor = conn.cursor()

    # Check if bookmaker_balance_checks table exists (for backwards compatibility)
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='bookmaker_balance_checks'"
    )
    table_exists = cursor.fetchone() is not None

    if table_exists:
        query = """
            SELECT
                b.id,
                b.associate_id,
                b.bookmaker_name,
                b.parsing_profile,
                b.is_active,
                b.created_at_utc,
                b.updated_at_utc,
                bc_latest.balance_eur,
                bc_latest.check_date_utc AS latest_balance_check_date
            FROM bookmakers b
            LEFT JOIN (
                SELECT
                    bookmaker_id,
                    balance_eur,
                    check_date_utc,
                    ROW_NUMBER() OVER (PARTITION BY bookmaker_id ORDER BY check_date_utc DESC) AS rn
                FROM bookmaker_balance_checks
            ) bc_latest ON b.id = bc_latest.bookmaker_id AND bc_latest.rn = 1
            WHERE b.associate_id = ?
            ORDER BY b.bookmaker_name ASC
        """
    else:
        # Fallback query without balance checks
        query = """
            SELECT
                b.id,
                b.associate_id,
                b.bookmaker_name,
                b.parsing_profile,
                b.is_active,
                b.created_at_utc,
                b.updated_at_utc,
                NULL AS balance_eur,
                NULL AS latest_balance_check_date
            FROM bookmakers b
            WHERE b.associate_id = ?
            ORDER BY b.bookmaker_name ASC
        """

    cursor.execute(query, (associate_id,))
    return [dict(row) for row in cursor.fetchall()]


def get_chat_registration_status(
    bookmaker_id: int, conn: Optional[sqlite3.Connection] = None
) -> str:
    """Get Telegram chat registration status for a bookmaker.

    Args:
        bookmaker_id: ID of the bookmaker
        conn: Optional database connection (for testing)

    Returns:
        Status string with icon and chat ID (if applicable)
    """
    if conn is None:
        conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT chat_id, is_active
        FROM chat_registrations
        WHERE bookmaker_id = ?
        ORDER BY created_at_utc DESC
        LIMIT 1
        """,
        (bookmaker_id,),
    )
    row = cursor.fetchone()

    if not row:
        return "⚠️ Not Registered"

    chat_id, is_active = row["chat_id"], row["is_active"]

    if is_active:
        return f"✅ Registered (Chat ID: {chat_id})"
    else:
        return "🔴 Inactive Registration"


def insert_bookmaker(
    associate_id: int,
    bookmaker_name: str,
    parsing_profile: Optional[str],
    is_active: bool,
    conn: Optional[sqlite3.Connection] = None,
) -> Tuple[bool, str]:
    """Insert new bookmaker into database.

    Args:
        associate_id: ID of the associate
        bookmaker_name: Name of the bookmaker
        parsing_profile: Optional JSON parsing profile
        is_active: Active status flag
        conn: Optional database connection (for testing)

    Returns:
        Tuple of (success: bool, message: str)
    """
    if conn is None:
        conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO bookmakers (
                associate_id,
                bookmaker_name,
                parsing_profile,
                is_active,
                created_at_utc,
                updated_at_utc
            ) VALUES (?, ?, ?, ?, datetime('now') || 'Z', datetime('now') || 'Z')
            """,
            (
                associate_id,
                bookmaker_name.strip(),
                parsing_profile.strip() if parsing_profile else None,
                1 if is_active else 0,
            ),
        )
        conn.commit()
        logger.info(
            "bookmaker_created",
            associate_id=associate_id,
            bookmaker_name=bookmaker_name,
            is_active=is_active,
        )
        return True, f"✅ Bookmaker '{bookmaker_name}' added"
    except sqlite3.IntegrityError as e:
        conn.rollback()
        if "UNIQUE constraint failed" in str(e):
            return False, "❌ Bookmaker already exists for this associate"
        logger.error("bookmaker_insert_failed", error=str(e), bookmaker_name=bookmaker_name)
        return False, f"❌ Failed to create bookmaker: {str(e)}"
    except Exception as e:
        conn.rollback()
        logger.error("bookmaker_insert_failed", error=str(e), bookmaker_name=bookmaker_name)
        return False, f"❌ Failed to create bookmaker: {str(e)}"


def update_bookmaker(
    bookmaker_id: int,
    bookmaker_name: str,
    parsing_profile: Optional[str],
    is_active: bool,
    conn: Optional[sqlite3.Connection] = None,
) -> Tuple[bool, str]:
    """Update existing bookmaker in database.

    Args:
        bookmaker_id: ID of bookmaker to update
        bookmaker_name: New bookmaker name
        parsing_profile: New parsing profile
        is_active: New active status
        conn: Optional database connection (for testing)

    Returns:
        Tuple of (success: bool, message: str)
    """
    if conn is None:
        conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            UPDATE bookmakers
            SET bookmaker_name = ?,
                parsing_profile = ?,
                is_active = ?,
                updated_at_utc = datetime('now') || 'Z'
            WHERE id = ?
            """,
            (
                bookmaker_name.strip(),
                parsing_profile.strip() if parsing_profile else None,
                1 if is_active else 0,
                bookmaker_id,
            ),
        )
        conn.commit()
        logger.info("bookmaker_updated", bookmaker_id=bookmaker_id, bookmaker_name=bookmaker_name)
        return True, "✅ Bookmaker updated"
    except sqlite3.IntegrityError as e:
        conn.rollback()
        if "UNIQUE constraint failed" in str(e):
            return False, "❌ Bookmaker name already exists for this associate"
        logger.error("bookmaker_update_failed", error=str(e), bookmaker_id=bookmaker_id)
        return False, f"❌ Failed to update bookmaker: {str(e)}"
    except Exception as e:
        conn.rollback()
        logger.error("bookmaker_update_failed", error=str(e), bookmaker_id=bookmaker_id)
        return False, f"❌ Failed to update bookmaker: {str(e)}"


def can_delete_bookmaker(
    bookmaker_id: int, conn: Optional[sqlite3.Connection] = None
) -> Tuple[bool, str, int]:
    """Check if bookmaker can be deleted.

    Args:
        bookmaker_id: ID of bookmaker to check
        conn: Optional database connection (for testing)

    Returns:
        Tuple of (can_delete: bool, warning: str, bet_count: int)
        Unlike associate deletion, bookmaker deletion is ALLOWED even if bets exist,
        but requires explicit confirmation with warning.
    """
    if conn is None:
        conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM bets WHERE bookmaker_id = ?", (bookmaker_id,))
    bet_count = cursor.fetchone()[0]

    if bet_count > 0:
        return (
            True,
            f"⚠️ This bookmaker has {bet_count} bet(s). Deleting will orphan these records.",
            bet_count,
        )

    return True, "OK", 0


def delete_bookmaker(
    bookmaker_id: int, conn: Optional[sqlite3.Connection] = None
) -> Tuple[bool, str]:
    """Delete bookmaker from database (cascades to chat_registrations).

    Args:
        bookmaker_id: ID of bookmaker to delete
        conn: Optional database connection (for testing)

    Returns:
        Tuple of (success: bool, message: str)
    """
    if conn is None:
        conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Get name for logging
        cursor.execute("SELECT bookmaker_name FROM bookmakers WHERE id = ?", (bookmaker_id,))
        row = cursor.fetchone()
        name = row[0] if row else "Unknown"

        # Delete (cascades to chat_registrations via ON DELETE CASCADE)
        cursor.execute("DELETE FROM bookmakers WHERE id = ?", (bookmaker_id,))
        conn.commit()

        logger.info("bookmaker_deleted", bookmaker_id=bookmaker_id, bookmaker_name=name)
        return True, f"✅ Bookmaker '{name}' deleted"
    except Exception as e:
        conn.rollback()
        logger.error("bookmaker_delete_failed", error=str(e), bookmaker_id=bookmaker_id)
        return False, f"❌ Failed to delete bookmaker: {str(e)}"


# ============================================================================
# UI COMPONENTS - ASSOCIATES
# ============================================================================


def render_add_associate_form() -> None:
    """Render the Add Associate form in an expander."""
    with st.expander("➕ Add New Associate", expanded=st.session_state.get("show_add_form", False)):
        with st.form("add_associate_form", clear_on_submit=True):
            st.subheader("Add New Associate")

            col1, col2 = st.columns(2)

            with col1:
                alias_input = st.text_input("Display Alias *", key="new_alias")
                currency_input = st.selectbox(
                    "Home Currency *",
                    options=VALID_CURRENCIES,
                    index=0,
                    key="new_currency",
                )

            with col2:
                is_admin_input = st.checkbox("Is Admin", value=False, key="new_is_admin")
                chat_id_input = st.text_input("Multibook Chat ID (optional)", key="new_chat_id")

            col_cancel, col_save = st.columns([1, 1])
            with col_cancel:
                cancel = st.form_submit_button("Cancel", use_container_width=True)
            with col_save:
                submit = st.form_submit_button("Save", type="primary", use_container_width=True)

            if cancel:
                st.session_state.show_add_form = False
                st.rerun()

            if submit:
                # Validate inputs
                conn = get_db_connection()

                alias_valid, alias_error = validate_alias(alias_input, db_connection=conn)
                currency_valid, currency_error = validate_currency(currency_input)
                chat_id_valid, chat_id_error = validate_multibook_chat_id(chat_id_input)

                if not alias_valid:
                    st.error(f"❌ {alias_error}")
                elif not currency_valid:
                    st.error(f"❌ {currency_error}")
                elif not chat_id_valid:
                    st.error(f"❌ {chat_id_error}")
                else:
                    # Insert associate
                    success, message = insert_associate(
                        alias_input, currency_input, is_admin_input, chat_id_input or None
                    )
                    if success:
                        st.success(message)
                        st.session_state.show_add_form = False
                        st.rerun()
                    else:
                        st.error(message)


def render_edit_associate_modal(associate: Dict) -> None:
    """Render the Edit Associate modal.

    Args:
        associate: Associate dictionary from database
    """
    associate_id = associate["id"]
    modal_key = f"show_edit_modal_{associate_id}"

    if st.session_state.get(modal_key, False):
        with st.expander(f"✏️ Edit Associate: {associate['display_alias']}", expanded=True):
            with st.form(f"edit_associate_form_{associate_id}"):
                st.subheader(f"Edit: {associate['display_alias']}")

                col1, col2 = st.columns(2)

                with col1:
                    alias_input = st.text_input(
                        "Display Alias *",
                        value=associate["display_alias"],
                        key=f"edit_alias_{associate_id}",
                    )
                    currency_input = st.selectbox(
                        "Home Currency *",
                        options=VALID_CURRENCIES,
                        index=(
                            VALID_CURRENCIES.index(associate["home_currency"])
                            if associate["home_currency"] in VALID_CURRENCIES
                            else 0
                        ),
                        key=f"edit_currency_{associate_id}",
                    )

                with col2:
                    is_admin_input = st.checkbox(
                        "Is Admin",
                        value=bool(associate["is_admin"]),
                        key=f"edit_is_admin_{associate_id}",
                    )
                    chat_id_input = st.text_input(
                        "Multibook Chat ID (optional)",
                        value=associate["multibook_chat_id"] or "",
                        key=f"edit_chat_id_{associate_id}",
                    )

                col_cancel, col_save = st.columns([1, 1])
                with col_cancel:
                    cancel = st.form_submit_button("Cancel", use_container_width=True)
                with col_save:
                    submit = st.form_submit_button(
                        "Save Changes", type="primary", use_container_width=True
                    )

                if cancel:
                    st.session_state[modal_key] = False
                    st.rerun()

                if submit:
                    # Validate inputs
                    conn = get_db_connection()

                    alias_valid, alias_error = validate_alias(
                        alias_input, exclude_id=associate_id, db_connection=conn
                    )
                    currency_valid, currency_error = validate_currency(currency_input)
                    chat_id_valid, chat_id_error = validate_multibook_chat_id(chat_id_input)

                    if not alias_valid:
                        st.error(f"❌ {alias_error}")
                    elif not currency_valid:
                        st.error(f"❌ {currency_error}")
                    elif not chat_id_valid:
                        st.error(f"❌ {chat_id_error}")
                    else:
                        # Update associate
                        success, message = update_associate(
                            associate_id,
                            alias_input,
                            currency_input,
                            is_admin_input,
                            chat_id_input or None,
                        )
                        if success:
                            st.success(message)
                            st.session_state[modal_key] = False
                            st.rerun()
                        else:
                            st.error(message)


def render_delete_confirmation_modal(associate: Dict) -> None:
    """Render the Delete Confirmation modal.

    Args:
        associate: Associate dictionary from database
    """
    associate_id = associate["id"]
    modal_key = f"show_delete_modal_{associate_id}"

    if st.session_state.get(modal_key, False):
        with st.expander(f"🗑️ Delete Associate: {associate['display_alias']}", expanded=True):
            st.warning(f"⚠️ Are you sure you want to delete **{associate['display_alias']}**?")

            # Check if can delete
            can_delete, reason = can_delete_associate(associate_id)

            if not can_delete:
                st.error(f"❌ {reason}")

            col_cancel, col_delete = st.columns([1, 1])
            with col_cancel:
                if st.button(
                    "Cancel", key=f"cancel_delete_{associate_id}", use_container_width=True
                ):
                    st.session_state[modal_key] = False
                    st.rerun()

            with col_delete:
                if st.button(
                    "Delete",
                    key=f"confirm_delete_{associate_id}",
                    type="primary",
                    disabled=not can_delete,
                    use_container_width=True,
                ):
                    success, message = delete_associate(associate_id)
                    if success:
                        st.success(message)
                        st.session_state[modal_key] = False
                        st.rerun()
                    else:
                        st.error(message)


# ============================================================================
# UI COMPONENTS - BOOKMAKERS
# ============================================================================


def render_add_bookmaker_form(associate: Dict) -> None:
    """Render the Add Bookmaker form for an associate.

    Args:
        associate: Associate dictionary from database
    """
    associate_id = associate["id"]
    form_key = f"show_add_bookmaker_{associate_id}"

    if st.session_state.get(form_key, False):
        with st.expander(f"➕ Add Bookmaker to {associate['display_alias']}", expanded=True):
            with st.form(f"add_bookmaker_form_{associate_id}"):
                st.subheader(f"Add Bookmaker to {associate['display_alias']}")

                name_input = st.text_input("Bookmaker Name *", key=f"new_bm_name_{associate_id}")
                parsing_profile_input = st.text_area(
                    "Parsing Profile (optional JSON)",
                    placeholder='{"ocr_hints": ["bet365", "odds"]}',
                    key=f"new_bm_profile_{associate_id}",
                    height=100,
                )
                is_active_input = st.checkbox(
                    "Is Active", value=True, key=f"new_bm_active_{associate_id}"
                )

                col_cancel, col_save = st.columns([1, 1])
                with col_cancel:
                    cancel = st.form_submit_button("Cancel", use_container_width=True)
                with col_save:
                    submit = st.form_submit_button("Save", type="primary", use_container_width=True)

                if cancel:
                    st.session_state[form_key] = False
                    st.rerun()

                if submit:
                    # Validate inputs
                    if not name_input or not name_input.strip():
                        st.error("❌ Bookmaker name is required")
                    else:
                        # Validate JSON if provided
                        json_valid, json_error = validate_json(parsing_profile_input)
                        if not json_valid:
                            st.error(f"❌ {json_error}")
                        else:
                            # Insert bookmaker
                            success, message = insert_bookmaker(
                                associate_id,
                                name_input,
                                parsing_profile_input or None,
                                is_active_input,
                            )
                            if success:
                                # Get associate alias for success message
                                st.success(f"{message} to '{associate['display_alias']}'")
                                st.session_state[form_key] = False
                                st.rerun()
                            else:
                                st.error(message)


def render_edit_bookmaker_modal(bookmaker: Dict, associate_alias: str) -> None:
    """Render the Edit Bookmaker modal.

    Args:
        bookmaker: Bookmaker dictionary from database
        associate_alias: Display alias of the owning associate
    """
    bookmaker_id = bookmaker["id"]
    modal_key = f"show_edit_bookmaker_{bookmaker_id}"

    if st.session_state.get(modal_key, False):
        with st.expander(f"✏️ Edit Bookmaker: {bookmaker['bookmaker_name']}", expanded=True):
            with st.form(f"edit_bookmaker_form_{bookmaker_id}"):
                st.subheader(f"Edit: {bookmaker['bookmaker_name']}")

                name_input = st.text_input(
                    "Bookmaker Name *",
                    value=bookmaker["bookmaker_name"],
                    key=f"edit_bm_name_{bookmaker_id}",
                )
                parsing_profile_input = st.text_area(
                    "Parsing Profile (optional JSON)",
                    value=bookmaker["parsing_profile"] or "",
                    key=f"edit_bm_profile_{bookmaker_id}",
                    height=100,
                )
                is_active_input = st.checkbox(
                    "Is Active",
                    value=bool(bookmaker["is_active"]),
                    key=f"edit_bm_active_{bookmaker_id}",
                )

                col_cancel, col_save = st.columns([1, 1])
                with col_cancel:
                    cancel = st.form_submit_button("Cancel", use_container_width=True)
                with col_save:
                    submit = st.form_submit_button(
                        "Save Changes", type="primary", use_container_width=True
                    )

                if cancel:
                    st.session_state[modal_key] = False
                    st.rerun()

                if submit:
                    # Validate inputs
                    if not name_input or not name_input.strip():
                        st.error("❌ Bookmaker name is required")
                    else:
                        # Validate JSON if provided
                        json_valid, json_error = validate_json(parsing_profile_input)
                        if not json_valid:
                            st.error(f"❌ {json_error}")
                        else:
                            # Update bookmaker
                            success, message = update_bookmaker(
                                bookmaker_id,
                                name_input,
                                parsing_profile_input or None,
                                is_active_input,
                            )
                            if success:
                                st.success(message)
                                st.session_state[modal_key] = False
                                st.rerun()
                            else:
                                st.error(message)


def render_delete_bookmaker_modal(bookmaker: Dict, associate_alias: str) -> None:
    """Render the Delete Bookmaker confirmation modal.

    Args:
        bookmaker: Bookmaker dictionary from database
        associate_alias: Display alias of the owning associate
    """
    bookmaker_id = bookmaker["id"]
    modal_key = f"show_delete_bookmaker_{bookmaker_id}"

    if st.session_state.get(modal_key, False):
        with st.expander(f"🗑️ Delete Bookmaker: {bookmaker['bookmaker_name']}", expanded=True):
            st.warning(f"⚠️ Are you sure you want to delete **{bookmaker['bookmaker_name']}**?")

            # Check if can delete (always True, but may have warning)
            can_delete, warning, bet_count = can_delete_bookmaker(bookmaker_id)

            if bet_count > 0:
                st.warning(warning)
                st.info("💡 Deletion is allowed but requires confirmation.")

            col_cancel, col_delete = st.columns([1, 1])
            with col_cancel:
                if st.button(
                    "Cancel",
                    key=f"cancel_delete_bm_{bookmaker_id}",
                    use_container_width=True,
                ):
                    st.session_state[modal_key] = False
                    st.rerun()

            with col_delete:
                if st.button(
                    "Delete",
                    key=f"confirm_delete_bm_{bookmaker_id}",
                    type="primary",
                    use_container_width=True,
                ):
                    success, message = delete_bookmaker(bookmaker_id)
                    if success:
                        st.success(message)
                        st.session_state[modal_key] = False
                        st.rerun()
                    else:
                        st.error(message)


def render_bookmaker_row(bookmaker: Dict, associate_alias: str) -> None:
    """Render a single bookmaker row within an associate's expander.

    Args:
        bookmaker: Bookmaker dictionary from database
        associate_alias: Display alias of the owning associate
    """
    # Render modals if active
    render_edit_bookmaker_modal(bookmaker, associate_alias)
    render_delete_bookmaker_modal(bookmaker, associate_alias)

    # Bookmaker row
    col1, col2, col3, col4, col5 = st.columns([3, 1.5, 2, 2, 2])

    with col1:
        st.markdown(f"**{bookmaker['bookmaker_name']}**")

    with col2:
        status_icon = "✅ Active" if bookmaker["is_active"] else "⚠️ Inactive"
        st.text(status_icon)

    with col3:
        # Truncate parsing profile if long
        profile = bookmaker["parsing_profile"]
        if profile:
            display_profile = (profile[:20] + "...") if len(profile) > 20 else profile
            st.text(display_profile)
        else:
            st.text("None")

    with col4:
        # Chat registration status
        chat_status = get_chat_registration_status(bookmaker["id"])
        st.text(chat_status)

    with col5:
        # Action buttons
        col_edit, col_delete = st.columns(2)
        with col_edit:
            if st.button(
                "Edit",
                key=f"edit_bm_btn_{bookmaker['id']}",
                use_container_width=True,
            ):
                st.session_state[f"show_edit_bookmaker_{bookmaker['id']}"] = True
                st.rerun()

        with col_delete:
            if st.button(
                "Delete",
                key=f"delete_bm_btn_{bookmaker['id']}",
                use_container_width=True,
            ):
                st.session_state[f"show_delete_bookmaker_{bookmaker['id']}"] = True
                st.rerun()


def render_bookmakers_for_associate(associate: Dict) -> None:
    """Render expandable bookmaker section for an associate.

    Args:
        associate: Associate dictionary from database
    """
    associate_id = associate["id"]
    bookmaker_count = associate["bookmaker_count"]

    # Expandable section for bookmakers
    expander_label = f"▶ Bookmakers ({bookmaker_count})"
    with st.expander(expander_label, expanded=False):
        # Add Bookmaker button
        if st.button(
            "➕ Add Bookmaker",
            key=f"add_bm_btn_{associate_id}",
            use_container_width=True,
        ):
            st.session_state[f"show_add_bookmaker_{associate_id}"] = True
            st.rerun()

        # Render add bookmaker form if active
        render_add_bookmaker_form(associate)

        # Load bookmakers
        bookmakers = load_bookmakers_for_associate(associate_id)

        if not bookmakers:
            st.info("No bookmakers added yet. Click 'Add Bookmaker' to create one.")
        else:
            # Bookmaker table header
            col1, col2, col3, col4, col5 = st.columns([3, 1.5, 2, 2, 2])
            col1.markdown("**Name**")
            col2.markdown("**Status**")
            col3.markdown("**Profile**")
            col4.markdown("**Chat Status**")
            col5.markdown("**Actions**")

            st.divider()

            # Render bookmaker rows
            for bookmaker in bookmakers:
                render_bookmaker_row(bookmaker, associate["display_alias"])
                st.divider()


# ============================================================================
# UI COMPONENTS - ASSOCIATES TABLE
# ============================================================================


def render_associates_table(associates: List[Dict]) -> None:
    """Render the associates table with action buttons and expandable bookmakers.

    Args:
        associates: List of associate dictionaries
    """
    if not associates:
        st.info("No associates found. Click 'Add Associate' to create one.")
        return

    # Table header
    st.markdown("### Associates")

    for assoc in associates:
        # Render edit/delete modals if active
        render_edit_associate_modal(assoc)
        render_delete_confirmation_modal(assoc)

        # Associate row
        col1, col2, col3, col4, col5, col6 = st.columns([3, 1.5, 1, 1.5, 2, 2])

        with col1:
            admin_badge = "✓" if assoc["is_admin"] else ""
            st.markdown(f"**{assoc['display_alias']}** {admin_badge}")

        with col2:
            st.text(assoc["home_currency"])

        with col3:
            st.text(str(assoc["bookmaker_count"]))

        with col4:
            created_date = format_utc_datetime_local(assoc["created_at_utc"])
            st.text(created_date.split(" ")[0] if created_date != "—" else "—")

        with col5:
            if st.button(
                "Edit",
                key=f"edit_btn_{assoc['id']}",
                use_container_width=True,
            ):
                st.session_state[f"show_edit_modal_{assoc['id']}"] = True
                st.rerun()

        with col6:
            if st.button(
                "Delete",
                key=f"delete_btn_{assoc['id']}",
                use_container_width=True,
            ):
                st.session_state[f"show_delete_modal_{assoc['id']}"] = True
                st.rerun()

        # Render expandable bookmaker section
        render_bookmakers_for_associate(assoc)

        st.divider()


# ============================================================================
# MAIN PAGE RENDER
# ============================================================================

# Only run Streamlit UI code if not being imported by tests
if __name__ != "__main__" or "pytest" not in globals():
    try:
        st.set_page_config(page_title="Admin - Associates", page_icon="🧑‍💼", layout="wide")

        st.title("🧑‍💼 Associate & Bookmaker Management")

        # Initialize session state
        if "show_add_form" not in st.session_state:
            st.session_state.show_add_form = False

        # Tabs
        tab1, tab2 = st.tabs(["Associates & Bookmakers", "Balance History"])

        with tab1:
            st.subheader("Associate Management")

            # Top controls row
            col_add, col_search = st.columns([1, 3])

            with col_add:
                if st.button("➕ Add Associate", use_container_width=True):
                    st.session_state.show_add_form = True
                    st.rerun()

            with col_search:
                search_filter = st.text_input(
                    "🔍 Search by alias",
                    placeholder="Type to filter...",
                    label_visibility="collapsed",
                )

            # Add associate form
            render_add_associate_form()

            # Load and display associates
            associates = load_associates(filter_alias=search_filter)

            # Counter
            st.metric("Total Associates", len(associates))

            # Table
            render_associates_table(associates)

        with tab2:
            render_balance_history_tab()
    except Exception:
        # Silently ignore errors during test imports
        pass
