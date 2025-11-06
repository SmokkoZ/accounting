"""
Balance management helper functions and Streamlit UI components.

This module provides:
1. Data-access helpers (load/insert/update/delete) used by tests and UI.
2. Streamlit rendering helpers so the Balance Management experience can be
   embedded inside other pages (e.g., Admin Associates) or exposed as a
   standalone page (`/balance_management`).
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

import structlog

try:  # Streamlit is optional for import-time usage in tests
    import streamlit as st
except ModuleNotFoundError:  # pragma: no cover - executed only in non-UI contexts
    st = None  # type: ignore

from src.core.database import get_db_connection
from src.services.fx_manager import convert_to_eur, get_fx_rate, get_latest_fx_rate
from src.ui.ui_components import load_global_styles
from src.ui.utils.formatters import format_currency_with_symbol, format_utc_datetime_local
from src.ui.utils.validators import VALID_CURRENCIES, validate_balance_amount

logger = structlog.get_logger()

PAGE_TITLE = "Balance Management"
PAGE_ICON = ":material/account_balance_wallet:"

def _require_streamlit() -> None:
    """Ensure Streamlit is available before rendering UI components."""
    if st is None:
        raise RuntimeError(
            "Streamlit is required for rendering balance management UI components."
        )


# ============================================================================
# DATA HELPERS
# ============================================================================


def load_balance_checks(
    associate_id: Optional[int] = None,
    bookmaker_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> List[Dict]:
    """Load balance checks with optional filters."""
    if conn is None:
        conn = get_db_connection()

    query = """
        SELECT
            bc.*,
            a.display_alias AS associate_name,
            bk.bookmaker_name
        FROM bookmaker_balance_checks bc
        JOIN associates a ON bc.associate_id = a.id
        JOIN bookmakers bk ON bc.bookmaker_id = bk.id
        WHERE 1=1
    """

    params: List = []

    if associate_id:
        query += " AND bc.associate_id = ?"
        params.append(associate_id)

    if bookmaker_id:
        query += " AND bc.bookmaker_id = ?"
        params.append(bookmaker_id)

    if start_date:
        query += " AND date(bc.check_date_utc) >= ?"
        params.append(start_date)

    if end_date:
        query += " AND date(bc.check_date_utc) <= ?"
        params.append(end_date)

    query += " ORDER BY bc.check_date_utc DESC"

    cursor = conn.cursor()
    cursor.execute(query, params)
    return [dict(row) for row in cursor.fetchall()]


def calculate_modeled_balance(
    associate_id: int, bookmaker_id: int, conn: Optional[sqlite3.Connection] = None
) -> Dict:
    """Calculate modeled balance from ledger entries."""
    if conn is None:
        conn = get_db_connection()

    cursor = conn.execute(
        """
        SELECT SUM(CAST(amount_eur AS REAL)) AS modeled_balance_eur
        FROM ledger_entries
        WHERE associate_id = ? AND bookmaker_id = ?
    """,
        (associate_id, bookmaker_id),
    )
    row = cursor.fetchone()
    modeled_balance_eur = Decimal(str(row["modeled_balance_eur"] or 0))

    cursor = conn.execute(
        """
        SELECT a.home_currency
        FROM associates a
        WHERE a.id = ?
    """,
        (associate_id,),
    )
    row = cursor.fetchone()
    native_currency = row["home_currency"] if row else "EUR"

    if native_currency != "EUR":
        fx_info = get_latest_fx_rate(native_currency)
        if fx_info:
            fx_rate = fx_info[0]
            modeled_balance_native = modeled_balance_eur / fx_rate
        else:
            modeled_balance_native = modeled_balance_eur
    else:
        modeled_balance_native = modeled_balance_eur

    return {
        "modeled_balance_eur": modeled_balance_eur.quantize(Decimal("0.01")),
        "modeled_balance_native": modeled_balance_native.quantize(Decimal("0.01")),
        "native_currency": native_currency,
    }


def insert_balance_check(
    associate_id: int,
    bookmaker_id: int,
    balance_native: Decimal,
    native_currency: str,
    check_date_utc: str,
    note: Optional[str],
    conn: Optional[sqlite3.Connection] = None,
) -> Tuple[bool, str]:
    """Insert a new balance check into the database."""
    if conn is None:
        conn = get_db_connection()
    cursor = conn.cursor()

    try:
        check_date_obj = date.fromisoformat(check_date_utc[:10])
        fx_rate = get_fx_rate(native_currency, check_date_obj)
        balance_eur = convert_to_eur(balance_native, native_currency, fx_rate)

        cursor.execute(
            """
            INSERT INTO bookmaker_balance_checks (
                associate_id,
                bookmaker_id,
                balance_native,
                native_currency,
                balance_eur,
                fx_rate_used,
                check_date_utc,
                created_at_utc,
                note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now') || 'Z', ?)
            """,
            (
                associate_id,
                bookmaker_id,
                str(balance_native),
                native_currency.upper(),
                str(balance_eur),
                str(fx_rate),
                check_date_utc,
                note.strip() if note else None,
            ),
        )
        conn.commit()
        logger.info(
            "balance_check_created",
            associate_id=associate_id,
            bookmaker_id=bookmaker_id,
            balance_eur=str(balance_eur),
        )
        return True, "Balance check recorded"
    except Exception as exc:
        conn.rollback()
        logger.error("balance_check_insert_failed", error=str(exc))
        return False, f"Failed to record balance check: {exc}"


def update_balance_check(
    check_id: int,
    balance_native: Decimal,
    native_currency: str,
    check_date_utc: str,
    note: Optional[str],
    conn: Optional[sqlite3.Connection] = None,
) -> Tuple[bool, str]:
    """Update an existing balance check."""
    if conn is None:
        conn = get_db_connection()
    cursor = conn.cursor()

    try:
        check_date_obj = date.fromisoformat(check_date_utc[:10])
        fx_rate = get_fx_rate(native_currency, check_date_obj)
        balance_eur = convert_to_eur(balance_native, native_currency, fx_rate)

        cursor.execute(
            """
            UPDATE bookmaker_balance_checks
            SET balance_native = ?,
                native_currency = ?,
                balance_eur = ?,
                fx_rate_used = ?,
                check_date_utc = ?,
                note = ?
            WHERE id = ?
            """,
            (
                str(balance_native),
                native_currency.upper(),
                str(balance_eur),
                str(fx_rate),
                check_date_utc,
                note.strip() if note else None,
                check_id,
            ),
        )
        conn.commit()
        logger.info("balance_check_updated", check_id=check_id, balance_eur=str(balance_eur))
        return True, "Balance check updated"
    except Exception as exc:
        conn.rollback()
        logger.error("balance_check_update_failed", error=str(exc), check_id=check_id)
        return False, f"Failed to update balance check: {exc}"


def delete_balance_check(
    check_id: int, conn: Optional[sqlite3.Connection] = None
) -> Tuple[bool, str]:
    """Delete a balance check."""
    if conn is None:
        conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("DELETE FROM bookmaker_balance_checks WHERE id = ?", (check_id,))
        conn.commit()
        logger.info("balance_check_deleted", check_id=check_id)
        return True, "Balance check deleted"
    except Exception as exc:
        conn.rollback()
        logger.error("balance_check_delete_failed", error=str(exc), check_id=check_id)
        return False, f"Failed to delete balance check: {exc}"


# ============================================================================
# STREAMLIT UI HELPERS
# ============================================================================


def render_balance_history_tab() -> None:
    """Render the Balance History UI (filters, summary, CRUD table)."""
    _require_streamlit()

    st.subheader("Balance History")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id, display_alias FROM associates ORDER BY display_alias ASC")
    associates_list = [dict(row) for row in cursor.fetchall()]

    if not associates_list:
        st.warning("No associates available. Create an associate before recording balance checks.")
        st.info("Use the Associate Management page to add the first associate.")
        st.session_state.pop("show_add_balance_check_form", None)
        return

    col_assoc, col_bookmaker, col_dates = st.columns([2, 2, 2])

    with col_assoc:
        assoc_options = [{"id": None, "display_alias": "All Associates"}] + associates_list
        assoc_idx = st.selectbox(
            "Associate",
            options=range(len(assoc_options)),
            format_func=lambda i: assoc_options[i]["display_alias"],
            key="balance_associate_filter",
        )
        selected_associate_id = assoc_options[assoc_idx]["id"]

    with col_bookmaker:
        if selected_associate_id:
            cursor.execute(
                "SELECT id, bookmaker_name FROM bookmakers WHERE associate_id = ? ORDER BY bookmaker_name ASC",
                (selected_associate_id,),
            )
            bookmakers_list = [dict(row) for row in cursor.fetchall()]
        else:
            cursor.execute("SELECT id, bookmaker_name FROM bookmakers ORDER BY bookmaker_name ASC")
            bookmakers_list = [dict(row) for row in cursor.fetchall()]

        bm_options = [{"id": None, "bookmaker_name": "All Bookmakers"}] + bookmakers_list
        bm_idx = st.selectbox(
            "Bookmaker",
            options=range(len(bm_options)),
            format_func=lambda i: bm_options[i]["bookmaker_name"],
            key="balance_bookmaker_filter",
        )
        selected_bookmaker_id = bm_options[bm_idx]["id"]

    with col_dates:
        date_range = st.selectbox(
            "Date Range",
            options=["Last 7 days", "Last 30 days", "Last 90 days", "All time"],
            key="balance_date_range",
        )

        if date_range == "Last 7 days":
            start_date = (date.today() - timedelta(days=7)).isoformat()
            end_date = date.today().isoformat()
        elif date_range == "Last 30 days":
            start_date = (date.today() - timedelta(days=30)).isoformat()
            end_date = date.today().isoformat()
        elif date_range == "Last 90 days":
            start_date = (date.today() - timedelta(days=90)).isoformat()
            end_date = date.today().isoformat()
        else:
            start_date = None
            end_date = None

    if selected_associate_id is not None and selected_bookmaker_id is not None:
        st.markdown("### Current Status")

        modeled = calculate_modeled_balance(int(selected_associate_id), int(selected_bookmaker_id))

        checks = load_balance_checks(
            associate_id=int(selected_associate_id),
            bookmaker_id=int(selected_bookmaker_id),
            start_date=None,
            end_date=None,
        )

        if checks:
            latest_check = checks[0]
            latest_balance_eur = Decimal(latest_check["balance_eur"])
            latest_balance_native = Decimal(latest_check["balance_native"])
            latest_currency = latest_check["native_currency"]
            latest_date = format_utc_datetime_local(latest_check["check_date_utc"])

            delta_eur = latest_balance_eur - modeled["modeled_balance_eur"]
            delta_native = latest_balance_native - modeled["modeled_balance_native"]

            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric(
                    "Latest Balance",
                    format_currency_with_symbol(latest_balance_native, str(latest_currency)),
                    f"as of {latest_date}",
                )
            with col2:
                st.metric(
                    "Modeled Balance",
                    format_currency_with_symbol(
                        modeled["modeled_balance_native"], str(modeled["native_currency"])
                    ),
                    "from ledger",
                )
            with col3:
                if abs(delta_eur) < Decimal("1.0"):
                    st.success(
                        f"Balanced ({format_currency_with_symbol(delta_native, str(latest_currency))})"
                    )
                elif delta_eur > Decimal("1.0"):
                    st.error(
                        f"Overholding {format_currency_with_symbol(delta_native, str(latest_currency))}"
                    )
                else:
                    st.warning(
                        f"Short {format_currency_with_symbol(abs(delta_native), str(latest_currency))}"
                    )
        else:
            st.info("No balance checks recorded yet. Add one below to start tracking.")

        st.divider()

    if st.button("Add Balance Check", width="stretch", disabled=not associates_list):
        st.session_state.show_add_balance_check_form = True
        st.rerun()

    if st.session_state.get("show_add_balance_check_form", False):
        render_add_balance_check_form(associates_list)

    checks = load_balance_checks(
        associate_id=int(selected_associate_id) if selected_associate_id is not None else None,
        bookmaker_id=int(selected_bookmaker_id) if selected_bookmaker_id is not None else None,
        start_date=start_date,
        end_date=end_date,
    )

    st.markdown(f"### Balance Check History ({len(checks)} record{'s' if len(checks) != 1 else ''})")

    if not checks:
        st.info("No balance checks found. Add one to start tracking balance history.")
    else:
        col1, col2, col3, col4, col5, col6, col7 = st.columns([1.5, 1.5, 1, 1.5, 1, 2, 1.5])
        col1.markdown("**Check Date**")
        col2.markdown("**Associate**")
        col3.markdown("**Bookmaker**")
        col4.markdown("**Native Amount**")
        col5.markdown("**EUR**")
        col6.markdown("**Note**")
        col7.markdown("**Actions**")

        st.divider()

        for check in checks:
            render_balance_check_row(check)


def render_add_balance_check_form(associates_list: List[Dict]) -> None:
    """Render the Add Balance Check form."""
    _require_streamlit()

    if not associates_list:
        st.warning("Cannot add balance checks until an associate exists.")
        st.session_state.show_add_balance_check_form = False
        return

    with st.expander("Add New Balance Check", expanded=True):
        assoc_idx = st.selectbox(
            "Associate *",
            options=range(len(associates_list)),
            format_func=lambda i: associates_list[i]["display_alias"],
            key="new_bc_associate_selector",
        )
        selected_assoc = associates_list[assoc_idx]
        selected_assoc_id = selected_assoc["id"]

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, bookmaker_name FROM bookmakers WHERE associate_id = ? ORDER BY bookmaker_name ASC",
            (selected_assoc_id,),
        )
        bookmakers_list = [dict(row) for row in cursor.fetchall()]

        if not bookmakers_list:
            st.warning("No bookmakers for this associate. Add a bookmaker first.")
            if st.button("Close", key="close_add_balance_form", width="stretch"):
                st.session_state.show_add_balance_check_form = False
                st.rerun()
            return

        cursor.execute("SELECT home_currency FROM associates WHERE id = ?", (selected_assoc_id,))
        row = cursor.fetchone()
        home_currency = row["home_currency"] if row else "EUR"

        bm_key = "new_bc_bookmaker_idx"
        if bm_key in st.session_state:
            current_idx = st.session_state[bm_key]
            if current_idx is None or current_idx >= len(bookmakers_list):
                st.session_state[bm_key] = 0

        with st.form("add_balance_check_form", clear_on_submit=True):
            st.subheader("Add Balance Check")

            col1, col2 = st.columns(2)

            with col1:
                bm_idx = st.selectbox(
                    "Bookmaker *",
                    options=range(len(bookmakers_list)),
                    format_func=lambda i: bookmakers_list[i]["bookmaker_name"],
                    key=bm_key,
                )
                selected_bm_id = bookmakers_list[bm_idx]["id"]

                check_date_input = st.date_input("Check Date *", value=date.today(), key="new_bc_date")
                check_time_input = st.time_input(
                    "Check Time (UTC) *",
                    value=datetime.now().time(),
                    key="new_bc_time",
                )

            with col2:
                balance_amount_input = st.text_input(
                    "Balance Amount *", placeholder="1250.00", key="new_bc_amount"
                )
                currency_input = st.selectbox(
                    "Currency *",
                    options=VALID_CURRENCIES,
                    index=VALID_CURRENCIES.index(home_currency) if home_currency in VALID_CURRENCIES else 0,
                    key="new_bc_currency",
                )
                note_input = st.text_input("Note (optional)", placeholder="Daily check", key="new_bc_note")

            col_cancel, col_save = st.columns([1, 1])
            with col_cancel:
                cancel = st.form_submit_button("Cancel", width="stretch")
            with col_save:
                submit = st.form_submit_button("Save", type="primary", width="stretch")

            if cancel:
                st.session_state.show_add_balance_check_form = False
                st.rerun()

            if submit:
                amount_valid, amount_error = validate_balance_amount(balance_amount_input)

                if not amount_valid:
                    st.error(f"{amount_error}")
                else:
                    if check_date_input > date.today():
                        st.warning("Future date entered. Confirm this is correct.")

                    check_datetime = datetime.combine(check_date_input, check_time_input)
                    check_date_utc = check_datetime.isoformat() + "Z"

                    success, message = insert_balance_check(
                        selected_assoc_id,
                        selected_bm_id,
                        Decimal(balance_amount_input.strip()),
                        currency_input,
                        check_date_utc,
                        note_input or None,
                    )

                    if success:
                        st.success(message)
                        st.session_state.show_add_balance_check_form = False
                        st.rerun()
                    else:
                        st.error(message)


def render_balance_check_row(check: Dict) -> None:
    """Render a single balance check row."""
    _require_streamlit()

    check_id = check["id"]

    render_edit_balance_check_modal(check)
    render_delete_balance_check_modal(check)

    col1, col2, col3, col4, col5, col6, col7 = st.columns([1.5, 1.5, 1, 1.5, 1, 2, 1.5])

    with col1:
        st.text(format_utc_datetime_local(check["check_date_utc"]))
    with col2:
        st.text(check["associate_name"])
    with col3:
        bookmaker_name = check["bookmaker_name"]
        st.text(bookmaker_name[:15] + "..." if len(bookmaker_name) > 15 else bookmaker_name)
    with col4:
        st.text(format_currency_with_symbol(Decimal(check["balance_native"]), check["native_currency"]))
    with col5:
        st.text(format_currency_with_symbol(Decimal(check["balance_eur"]), "EUR"))
    with col6:
        note_text = check["note"] or "--"
        st.text(note_text[:20] + "..." if len(note_text) > 20 else note_text)
    with col7:
        col_edit, col_delete = st.columns(2)
        with col_edit:
            if st.button("Edit", key=f"edit_bc_btn_{check_id}", width="stretch"):
                st.session_state[f"show_edit_bc_{check_id}"] = True
                st.rerun()
        with col_delete:
            if st.button("Delete", key=f"delete_bc_btn_{check_id}", width="stretch"):
                st.session_state[f"show_delete_bc_{check_id}"] = True
                st.rerun()

    st.divider()


def render_edit_balance_check_modal(check: Dict) -> None:
    """Render the Edit Balance Check modal."""
    _require_streamlit()

    check_id = check["id"]
    modal_key = f"show_edit_bc_{check_id}"

    if not st.session_state.get(modal_key, False):
        return

    with st.expander("Edit Balance Check", expanded=True):
        with st.form(f"edit_balance_check_form_{check_id}", clear_on_submit=False):
            st.subheader("Edit Balance Check")

            existing_dt = datetime.fromisoformat(check["check_date_utc"].replace("Z", ""))

            col1, col2 = st.columns(2)
            with col1:
                amount_input = st.text_input(
                    "Balance Amount *",
                    value=str(check["balance_native"]),
                    key=f"edit_bc_amount_{check_id}",
                )
                date_input = st.date_input(
                    "Check Date *",
                    value=existing_dt.date(),
                    key=f"edit_bc_date_{check_id}",
                )
                time_input = st.time_input(
                    "Check Time (UTC) *",
                    value=existing_dt.time(),
                    key=f"edit_bc_time_{check_id}",
                )

            with col2:
                currency_input = st.selectbox(
                    "Currency *",
                    options=VALID_CURRENCIES,
                    index=VALID_CURRENCIES.index(check["native_currency"])
                    if check["native_currency"] in VALID_CURRENCIES
                    else 0,
                    key=f"edit_bc_currency_{check_id}",
                )
                note_input = st.text_input(
                    "Note (optional)",
                    value=check["note"] or "",
                    key=f"edit_bc_note_{check_id}",
                )

            col_cancel, col_save = st.columns(2)
            with col_cancel:
                if st.form_submit_button("Cancel", width="stretch"):
                    st.session_state[modal_key] = False
                    st.rerun()
            with col_save:
                submit = st.form_submit_button("Save", type="primary", width="stretch")

            if submit:
                amount_valid, amount_error = validate_balance_amount(amount_input)

                if not amount_valid:
                    st.error(amount_error)
                else:
                    check_datetime = datetime.combine(date_input, time_input)
                    check_date_utc = check_datetime.isoformat() + "Z"

                    success, message = update_balance_check(
                        check_id,
                        Decimal(amount_input.strip()),
                        currency_input,
                        check_date_utc,
                        note_input or None,
                    )

                    if success:
                        st.success(message)
                        st.session_state[modal_key] = False
                        st.rerun()
                    else:
                        st.error(message)


def render_delete_balance_check_modal(check: Dict) -> None:
    """Render the Delete Balance Check confirmation modal."""
    _require_streamlit()

    check_id = check["id"]
    modal_key = f"show_delete_bc_{check_id}"

    if not st.session_state.get(modal_key, False):
        return

    with st.expander("Delete Balance Check", expanded=True):
        st.subheader("Delete Balance Check")
        st.markdown(
            (
                "Are you sure you want to delete this balance check?\n\n"
                f"**Associate:** {check['associate_name']}\n"
                f"**Bookmaker:** {check['bookmaker_name']}\n"
                f"**Amount:** {format_currency_with_symbol(Decimal(check['balance_native']), check['native_currency'])}\n"
                f"**Date:** {format_utc_datetime_local(check['check_date_utc'])}"
            )
        )

        col_cancel, col_delete = st.columns([1, 1])
        with col_cancel:
            if st.button("Cancel", key=f"cancel_delete_bc_{check_id}", width="stretch"):
                st.session_state[modal_key] = False
                st.rerun()
        with col_delete:
            if st.button(
                "Delete",
                key=f"confirm_delete_bc_{check_id}",
                type="primary",
                width="stretch",
            ):
                success, message = delete_balance_check(check_id)
                if success:
                    st.success(message)
                    st.session_state[modal_key] = False
                    st.rerun()
                else:
                    st.error(message)


def render_balance_management_page() -> None:
    """Render the standalone Balance Management page."""
    _require_streamlit()

    st.set_page_config(page_title=PAGE_TITLE, page_icon=PAGE_ICON, layout="wide")
    load_global_styles()
    st.title(f"{PAGE_ICON} {PAGE_TITLE}")
    st.caption("Record balance checks, compare with the modeled balance, and manage corrections.")
    render_balance_history_tab()


if __name__ == "__main__":
    if st is None:  # pragma: no cover - executed only when run via Streamlit
        raise RuntimeError("Streamlit must be installed to run the balance management page.")
    render_balance_management_page()
