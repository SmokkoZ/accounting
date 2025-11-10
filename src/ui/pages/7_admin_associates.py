"""
Admin Associates page - manage associates and bookmakers.

This page provides:
- View all associates with search/filter
- Add new associates
- Edit existing associates
- Delete associates (with validation)
- Manage bookmakers per associate
"""

from dataclasses import dataclass, asdict
from datetime import datetime, date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import pandas as pd
import shutil
import sqlite3
import streamlit as st
import structlog

from src.core.database import get_db_connection
from src.ui.helpers import fragments
from src.ui.helpers.dialogs import (
    ActionItem,
    open_dialog,
    render_action_menu,
    render_confirmation_dialog,
)
from src.ui.helpers.editor import (
    build_associates_dataframe,
    build_bookmakers_dataframe,
    extract_editor_changes,
    filter_bookmakers_by_associates,
    get_associate_column_config,
    get_bookmaker_column_config,
    get_selected_row_ids,
    validate_associate_row,
    validate_bookmaker_row,
)
from src.ui.ui_components import load_global_styles
from src.ui.utils import feature_flags
from src.ui.utils.performance import (
    clear_performance_alerts,
    clear_timings,
    get_performance_alerts,
    get_recent_timings,
)
from src.ui.utils.performance_dashboard import (
    prepare_recent_timings,
    summarize_timings,
)
from src.ui.utils.state_management import safe_rerun
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
from src.services.bookmaker_financials_service import BookmakerFinancialsService
from src.ui.pages.balance_management import render_balance_history_tab

logger = structlog.get_logger()

load_global_styles()

PAGE_TITLE = "Admin & Associates"
PAGE_ICON = ":material/admin_panel_settings:"
ASSOCIATES_EDITOR_KEY = "associates_editor"
BOOKMAKERS_EDITOR_KEY = "bookmakers_editor"
BULK_DEACTIVATE_DIALOG_KEY = "bulk_deactivate_associates"
BULK_DEACTIVATE_IDS_KEY = "bulk_deactivate_ids"
ASSOC_FEEDBACK_KEY = "associates_editor_feedback"
BOOKMAKER_FEEDBACK_KEY = "bookmakers_editor_feedback"
ASSOCIATE_SELECTION_KEY = "associates_editor_selected_ids"
ASSOCIATE_SELECTION_WIDGET_KEY = "associates_editor_selector_labels"
ASSOCIATE_SORT_PREFIX = "associates_editor_sort"
BOOKMAKER_SORT_PREFIX = "bookmakers_editor_sort"
SORT_DIRECTION_LABELS: Tuple[str, str] = ("Ascending", "Descending")
ASSOCIATE_SORT_OPTIONS: Sequence[Tuple[str, str]] = (
    ("Alias", "display_alias"),
    ("Home Currency", "home_currency"),
    ("Admin status", "is_admin"),
    ("Active status", "is_active"),
    ("Bookmaker count", "bookmaker_count"),
    ("Created date", "created_at_utc"),
)
BOOKMAKER_SORT_OPTIONS: Sequence[Tuple[str, str]] = (
    ("Name", "bookmaker_name"),
    ("Chat ID", "bookmaker_chat_id"),
    ("Balance (EUR)", "balance_eur"),
    ("Pending (EUR)", "pending_balance_eur"),
    ("Deposits (EUR)", "net_deposits_eur"),
    ("Profit (EUR)", "profits_eur"),
    ("Active status", "is_active"),
)


def _supports_data_editor() -> bool:
    """Return True when the current Streamlit runtime exposes typed editors."""

    return bool(getattr(st, "data_editor", None)) and feature_flags.has("data_editor")


def _get_editor_state(key: str) -> Optional[Dict[str, Any]]:
    """Return the raw session_state payload for a data_editor instance."""

    state = st.session_state.get(key)
    if state is None:
        return None
    if isinstance(state, dict):
        return state
    # DataEditorState behaves like a mapping but not all versions expose .copy()
    try:
        return dict(state)
    except TypeError:
        return state  # Fallback to direct reference


def _editor_has_changes(state: Optional[Dict[str, Any]]) -> bool:
    """Check whether the editor has pending edits, additions, or deletions."""

    changes = extract_editor_changes(state)
    return bool(changes.edited_rows or changes.added_rows or changes.deleted_rows)


def _pop_feedback(key: str) -> Optional[Dict[str, Any]]:
    """Retrieve and clear feedback payloads stored in session_state."""

    return st.session_state.pop(key, None)


def _push_feedback(key: str, success_count: int, errors: List[str]) -> None:
    """Store feedback data so it can be rendered after rerun."""

    st.session_state[key] = {"success": success_count, "errors": errors}


def _format_associate_selection_label(associate: Mapping[str, Any]) -> str:
    """Return a human friendly selection label for multiselect options."""

    alias = associate.get("display_alias") or f"Associate #{associate.get('id', '?')}"
    currency = (associate.get("home_currency") or "N/A").upper()
    status = "Active" if associate.get("is_active") else "Inactive"
    return f"{alias}  {currency}  {status} (#{associate.get('id', '?')})"


def _render_selection_picker(
    associates: Sequence[Mapping[str, Any]],
    preferred_ids: Sequence[int],
    current_selection: Sequence[int],
) -> List[int]:
    """Render the associate picker used to drive bookmaker filtering."""

    if not associates:
        st.session_state.pop(ASSOCIATE_SELECTION_WIDGET_KEY, None)
        return []

    option_map = {
        _format_associate_selection_label(assoc): int(assoc["id"])
        for assoc in associates
        if assoc.get("id") is not None
    }
    widget_key = ASSOCIATE_SELECTION_WIDGET_KEY

    fallback_ids = list(preferred_ids) if preferred_ids else list(current_selection or [])
    preferred_labels = [
        label for label, assoc_id in option_map.items() if assoc_id in preferred_ids
    ]
    fallback_labels = [
        label for label, assoc_id in option_map.items() if assoc_id in fallback_ids
    ]

    if widget_key not in st.session_state:
        st.session_state[widget_key] = preferred_labels or fallback_labels
    elif preferred_ids:
        st.session_state[widget_key] = preferred_labels
    else:
        current_labels: List[str] = [
            label
            for label in st.session_state.get(widget_key, [])
            if label in option_map
        ]
        st.session_state[widget_key] = current_labels

    st.caption(
        "Use the selector below to pick the associates whose bookmakers you want to manage."
    )
    st.multiselect(
        "Associates selected for bookmaker management",
        options=list(option_map.keys()),
        key=widget_key,
        placeholder="Choose one or more associates",
        label_visibility="collapsed",
    )

    selected_labels: Sequence[str] = st.session_state.get(widget_key, [])
    selected_ids = [option_map[label] for label in selected_labels]
    return selected_ids


def _render_sort_controls(
    label: str,
    *,
    options: Sequence[Tuple[str, str]],
    state_prefix: str,
    default_label: Optional[str] = None,
) -> Tuple[str, bool]:
    """Render sort controls and return the selected column/direction."""

    if not options:
        return "", True

    labels = [display for display, _ in options]
    value_map = {display: column for display, column in options}
    default_label = default_label or labels[0]

    column_key = f"{state_prefix}_column"
    direction_key = f"{state_prefix}_direction"

    if column_key not in st.session_state:
        st.session_state[column_key] = default_label
    if direction_key not in st.session_state:
        st.session_state[direction_key] = SORT_DIRECTION_LABELS[0]

    select_col, order_col = st.columns([3, 1])
    with select_col:
        st.selectbox(label, labels, key=column_key)
    with order_col:
        st.radio(
            "Order",
            SORT_DIRECTION_LABELS,
            horizontal=True,
            key=direction_key,
        )

    selected_label = st.session_state.get(column_key, default_label)
    selected_column = value_map.get(selected_label, value_map[default_label])
    ascending = st.session_state.get(direction_key, SORT_DIRECTION_LABELS[0]) == SORT_DIRECTION_LABELS[0]
    return selected_column, ascending


def _row_id_from_dataframe(dataframe: pd.DataFrame, row_index: int) -> Optional[int]:
    """Return the database ID stored in a dataframe row."""

    if row_index < 0 or row_index >= len(dataframe):
        return None
    value = dataframe.iloc[row_index].get("id")
    if value is None or pd.isna(value):
        return None
    return int(value)


def _resolve_bookmaker_associate_id(
    bookmaker_id: int,
    candidate_value: Optional[Any],
    conn,
) -> Optional[int]:
    """Return a reliable associate_id for a bookmaker."""

    if candidate_value not in (None, ""):
        try:
            return int(candidate_value)
        except (TypeError, ValueError):
            pass

    cursor = conn.cursor()
    cursor.execute("SELECT associate_id FROM bookmakers WHERE id = ?", (bookmaker_id,))
    row = cursor.fetchone()
    if not row:
        return None
    return int(row["associate_id"])


def _normalize_associate_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    """Return sanitized associate payload extracted from editor rows."""

    alias = (row.get("display_alias") or "").strip()
    home_currency = (row.get("home_currency") or "EUR").strip().upper()
    chat_id = (row.get("multibook_chat_id") or "").strip()

    return {
        "id": row.get("id"),
        "display_alias": alias,
        "home_currency": home_currency or "EUR",
        "is_admin": bool(row.get("is_admin")),
        "is_active": bool(row.get("is_active", True)),
        "multibook_chat_id": chat_id or None,
        "share_pct": row.get("share_pct"),
    }


def _normalize_bookmaker_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    """Return sanitized bookmaker payload extracted from editor rows."""

    return {
        "id": row.get("id"),
        "associate_id": row.get("associate_id"),
        "bookmaker_name": (row.get("bookmaker_name") or "").strip(),
        "parsing_profile": (row.get("parsing_profile") or "").strip() or None,
        "is_active": bool(row.get("is_active", True)),
        "bookmaker_chat_id": (row.get("bookmaker_chat_id") or "").strip() or None,
    }


def _merge_bookmaker_metadata(
    payload: Dict[str, Any],
    metadata: Optional[Mapping[int, Mapping[str, Any]]],
) -> None:
    """Rehydrate hidden bookmaker fields (e.g., parsing_profile) from metadata."""

    if not metadata:
        return

    payload_id = payload.get("id")
    if not payload_id:
        return

    meta = metadata.get(int(payload_id))
    if not meta:
        return

    if payload.get("parsing_profile") is None:
        payload["parsing_profile"] = meta.get("parsing_profile")


def _process_associate_editor_changes(
    source_df: pd.DataFrame,
    edited_df: pd.DataFrame,
    state: Optional[Dict[str, Any]],
) -> None:
    """Persist pending edits from the associates data_editor."""

    if not _editor_has_changes(state):
        st.info("No pending associate changes.")
        return

    changes = extract_editor_changes(state)
    conn = get_db_connection()
    applied = 0
    errors: List[str] = []

    # Handle deletions first to avoid foreign key conflicts with inserts.
    for row_idx in changes.deleted_rows:
        associate_id = _row_id_from_dataframe(source_df, row_idx)
        if not associate_id:
            continue

        can_delete, reason = can_delete_associate(associate_id, conn=conn)
        if not can_delete:
            errors.append(f"Associate {associate_id}: {reason}")
            continue

        success, message = delete_associate(associate_id, conn=conn)
        if success:
            applied += 1
        else:
            errors.append(message)

    # Apply edits.
    for row_idx, _ in changes.edited_rows.items():
        if row_idx >= len(edited_df):
            continue

        payload = _normalize_associate_row(edited_df.iloc[row_idx].to_dict())
        payload_id = payload.get("id") or _row_id_from_dataframe(edited_df, row_idx)
        if not payload_id:
            errors.append("Cannot update row without ID.")
            continue
        payload["id"] = int(payload_id)

        is_valid, validation_errors = validate_associate_row(payload, db_connection=conn)
        if not is_valid:
            alias = payload.get("display_alias") or f"ID {payload_id}"
            errors.append(f"{alias}: {'; '.join(validation_errors)}")
            continue

        success, message = update_associate(
            payload["id"],
            payload["display_alias"],
            payload["home_currency"],
            payload["is_admin"],
            payload["multibook_chat_id"],
            payload["is_active"],
            conn=conn,
        )
        if success:
            applied += 1
        else:
            errors.append(message)

    # Apply insertions.
    for row in changes.added_rows:
        payload = _normalize_associate_row(row)
        is_valid, validation_errors = validate_associate_row(payload, db_connection=conn)
        if not is_valid:
            errors.append("; ".join(validation_errors))
            continue

        success, message = insert_associate(
            payload["display_alias"],
            payload["home_currency"],
            payload["is_admin"],
            payload["multibook_chat_id"],
            is_active=payload["is_active"],
            conn=conn,
        )
        if success:
            applied += 1
        else:
            errors.append(message)

    _push_feedback(ASSOC_FEEDBACK_KEY, applied, errors)
    safe_rerun()


def _process_bookmaker_editor_changes(
    source_df: pd.DataFrame,
    edited_df: pd.DataFrame,
    state: Optional[Dict[str, Any]],
    *,
    default_associate_id: Optional[int] = None,
    bookmaker_metadata: Optional[Mapping[int, Mapping[str, Any]]] = None,
) -> None:
    """Persist pending edits from the bookmakers data_editor."""

    if not _editor_has_changes(state):
        st.info("No pending bookmaker changes.")
        return

    changes = extract_editor_changes(state)
    conn = get_db_connection()
    applied = 0
    errors: List[str] = []

    for row_idx in changes.deleted_rows:
        bookmaker_id = _row_id_from_dataframe(source_df, row_idx)
        if not bookmaker_id:
            continue
        success, message = delete_bookmaker(bookmaker_id, conn=conn)
        if success:
            applied += 1
        else:
            errors.append(message)

    for row_idx in changes.edited_rows.keys():
        if row_idx >= len(edited_df):
            continue

        payload = _normalize_bookmaker_row(edited_df.iloc[row_idx].to_dict())
        payload_id = payload.get("id") or _row_id_from_dataframe(edited_df, row_idx)
        if not payload_id:
            errors.append("Cannot update bookmaker without ID.")
            continue
        payload["id"] = int(payload_id)
        _merge_bookmaker_metadata(payload, bookmaker_metadata)

        is_valid, validation_errors = validate_bookmaker_row(payload)
        if not is_valid:
            name = payload.get("bookmaker_name") or f"ID {payload_id}"
            errors.append(f"{name}: {'; '.join(validation_errors)}")
            continue

        success, message = update_bookmaker(
            payload["id"],
            payload["bookmaker_name"],
            payload["parsing_profile"],
            payload["is_active"],
            conn=conn,
        )
        if not success:
            errors.append(message)
            continue

        associate_id = _resolve_bookmaker_associate_id(
            payload["id"],
            payload.get("associate_id"),
            conn,
        )
        if associate_id is None:
            errors.append(f"Unable to resolve associate for bookmaker ID {payload['id']}.")
            continue

        chat_success, chat_message = upsert_bookmaker_chat_registration(
            payload["id"],
            associate_id,
            payload.get("bookmaker_chat_id"),
            conn=conn,
        )
        if not chat_success:
            errors.append(chat_message)
            continue

        applied += 1

    for row in changes.added_rows:
        payload = _normalize_bookmaker_row(row)
        _merge_bookmaker_metadata(payload, bookmaker_metadata)
        associate_id = payload.get("associate_id") or default_associate_id
        if not associate_id:
            errors.append("Associate selection is required for new bookmakers.")
            continue

        is_valid, validation_errors = validate_bookmaker_row(payload)
        if not is_valid:
            errors.append("; ".join(validation_errors))
            continue

        payload["associate_id"] = int(associate_id)
        success, message = insert_bookmaker(
            payload["associate_id"],
            payload["bookmaker_name"],
            payload["parsing_profile"],
            payload["is_active"],
            conn=conn,
        )
        if not success:
            errors.append(message)
            continue

        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id
            FROM bookmakers
            WHERE associate_id = ? AND bookmaker_name = ?
            ORDER BY updated_at_utc DESC, id DESC
            LIMIT 1
            """,
            (payload["associate_id"], payload["bookmaker_name"]),
        )
        row = cursor.fetchone()
        if not row:
            errors.append(
                f"Bookmaker '{payload['bookmaker_name']}' saved but ID lookup failed for chat registration."
            )
            continue

        chat_success, chat_message = upsert_bookmaker_chat_registration(
            int(row["id"]),
            payload["associate_id"],
            payload.get("bookmaker_chat_id"),
            conn=conn,
        )
        if not chat_success:
            errors.append(chat_message)
            continue

        applied += 1

    _push_feedback(BOOKMAKER_FEEDBACK_KEY, applied, errors)
    safe_rerun()


def _render_feedback(key: str) -> None:
    """Display success/error feedback stored from the previous run."""

    feedback = _pop_feedback(key)
    if not feedback:
        return

    success_count = feedback.get("success", 0)
    errors = feedback.get("errors") or []

    if success_count:
        st.success(f"Saved {success_count} change(s).", icon="✅")

    if errors:
        with st.expander("View validation errors", expanded=True):
            for error in errors:
                st.error(error, icon="")


def render_associates_editor_section(search_filter: Optional[str]) -> List[int]:
    """Modern associates editor with typed data_editor controls."""

    _render_feedback(ASSOC_FEEDBACK_KEY)

    associates = load_associates(filter_alias=search_filter)
    source_df = build_associates_dataframe(associates)
    column_config = get_associate_column_config()

    st.metric("Total Associates", len(source_df))

    sort_column, sort_ascending = _render_sort_controls(
        "Sort associates by",
        options=ASSOCIATE_SORT_OPTIONS,
        state_prefix=ASSOCIATE_SORT_PREFIX,
    )
    if sort_column and sort_column in source_df.columns:
        source_df = (
            source_df.sort_values(
                by=sort_column,
                ascending=sort_ascending,
                na_position="last",
                kind="mergesort",
            ).reset_index(drop=True)
        )

    edited_df = st.data_editor(
        source_df,
        key=ASSOCIATES_EDITOR_KEY,
        column_config=column_config,
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        height=360,
    )

    state = _get_editor_state(ASSOCIATES_EDITOR_KEY)
    preferred_ids = get_selected_row_ids(state, edited_df)
    previous_selected_ids: List[int] = st.session_state.get(ASSOCIATE_SELECTION_KEY, [])
    selected_ids = _render_selection_picker(
        associates,
        preferred_ids,
        current_selection=previous_selected_ids,
    )

    if selected_ids != previous_selected_ids:
        st.session_state[ASSOCIATE_SELECTION_KEY] = selected_ids
        safe_rerun()

    st.session_state[ASSOCIATE_SELECTION_KEY] = selected_ids

    actions_col1, actions_col2 = st.columns([1, 1])
    with actions_col1:
        save_disabled = not _editor_has_changes(state)
        if st.button(
            " Save Associate Changes",
            key="save_associates_button",
            type="primary",
            width="stretch",
            disabled=save_disabled,
        ):
            _process_associate_editor_changes(source_df, edited_df, state)

    with actions_col2:
        bulk_disabled = not selected_ids
        if st.button(
            " Deactivate Selected",
            key="bulk_deactivate_button",
            width="stretch",
            disabled=bulk_disabled,
        ):
            st.session_state[BULK_DEACTIVATE_IDS_KEY] = selected_ids
            open_dialog(BULK_DEACTIVATE_DIALOG_KEY)

    pending_ids = st.session_state.get(BULK_DEACTIVATE_IDS_KEY)
    if pending_ids:
        decision = render_confirmation_dialog(
            key=BULK_DEACTIVATE_DIALOG_KEY,
            title="Confirm Bulk Deactivation",
            body=f"This will deactivate {len(pending_ids)} associate(s). Bookmakers remain linked but inactive.",
            confirm_label="Deactivate",
            confirm_type="primary",
        )
        if decision is True:
            can_deactivate, reasons = can_deactivate_associates(pending_ids)
            if not can_deactivate:
                for reason in reasons:
                    st.error(reason, icon="")
                st.session_state.pop(BULK_DEACTIVATE_IDS_KEY, None)
            else:
                success, message = bulk_set_associate_active_state(
                    pending_ids,
                    is_active=False,
                )
                st.session_state.pop(BULK_DEACTIVATE_IDS_KEY, None)
                errors = [] if success else [message]
                applied = len(pending_ids) if success else 0
                _push_feedback(ASSOC_FEEDBACK_KEY, applied, errors)
                safe_rerun()
        elif decision is False:
            st.session_state.pop(BULK_DEACTIVATE_IDS_KEY, None)

    return selected_ids


def render_bookmakers_editor_section(selected_associate_ids: List[int]) -> None:
    """Typed bookmaker editor filtered by selected associates."""

    _render_feedback(BOOKMAKER_FEEDBACK_KEY)

    if not selected_associate_ids:
        st.info("Use the selector in the associates table to pick who you want to manage.")
        return

    bookmakers = load_bookmakers_for_associates(selected_associate_ids)
    bookmaker_metadata = {
        int(row["id"]): row
        for row in bookmakers
        if row.get("id") is not None
    }
    source_df = build_bookmakers_dataframe(bookmakers)
    show_associate_column = len(selected_associate_ids) > 1
    allow_additions = len(selected_associate_ids) == 1
    column_config = get_bookmaker_column_config(show_associate=show_associate_column)

    sort_column, sort_ascending = _render_sort_controls(
        "Sort bookmakers by",
        options=BOOKMAKER_SORT_OPTIONS,
        state_prefix=BOOKMAKER_SORT_PREFIX,
    )
    if sort_column and sort_column in source_df.columns:
        source_df = (
            source_df.sort_values(
                by=sort_column,
                ascending=sort_ascending,
                na_position="last",
                kind="mergesort",
            ).reset_index(drop=True)
        )

    if allow_additions:
        st.caption(
            "Add new bookmakers directly in the table. They will attach to the selected associate."
        )
    else:
        st.warning("Adding new bookmakers requires selecting exactly one associate.")

    edited_df = st.data_editor(
        source_df,
        key=BOOKMAKERS_EDITOR_KEY,
        column_config=column_config,
        num_rows="dynamic" if allow_additions else "fixed",
        hide_index=True,
        width="stretch",
        height=300,
    )

    state = _get_editor_state(BOOKMAKERS_EDITOR_KEY)
    save_disabled = not _editor_has_changes(state)
    default_associate_id = selected_associate_ids[0] if allow_additions else None

    if st.button(
        " Save Bookmaker Changes",
        key="save_bookmakers_button",
        type="primary",
        width="stretch",
        disabled=save_disabled,
    ):
        _process_bookmaker_editor_changes(
            source_df,
            edited_df,
            state,
            default_associate_id=default_associate_id,
            bookmaker_metadata=bookmaker_metadata,
        )


def render_modern_associate_management_tab() -> None:
    """Entry point for the new data_editor-driven associate management UI."""

    st.subheader("Associate Management")
    search_filter = st.text_input(
        "Search by alias",
        key="associates_search_modern",
        placeholder="Type to filter...",
        label_visibility="collapsed",
    )

    selected_ids = fragments.call_fragment(
        "associates_editor",
        render_associates_editor_section,
        search_filter=search_filter,
    )
    if selected_ids is None:
        selected_ids = st.session_state.get(ASSOCIATE_SELECTION_KEY, [])

    st.divider()

    fragments.call_fragment(
        "bookmakers_editor",
        render_bookmakers_editor_section,
        selected_associate_ids=selected_ids,
    )


def render_legacy_associate_management_tab() -> None:
    """Fallback UI when data_editor is unavailable."""

    st.subheader("Associate Management")
    st.info(
        "Upgrade Streamlit to 1.46+ to unlock typed data editors. "
        "Using legacy forms for now."
    )

    col_add, col_search = st.columns([1, 3])
    with col_add:
        if st.button("[+] Add Associate", width="stretch"):
            st.session_state.show_add_form = True
            safe_rerun()

    with col_search:
        search_filter = st.text_input(
            "Search by alias",
            placeholder="Type to filter...",
            label_visibility="collapsed",
        )

    render_add_associate_form()
    associates = load_associates(filter_alias=search_filter)
    st.metric("Total Associates", len(associates))
    render_associates_table(associates)

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
            a.is_active,
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
    is_active: bool = True,
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
                is_active,
                multibook_chat_id,
                created_at_utc,
                updated_at_utc
            ) VALUES (?, ?, ?, ?, ?, datetime('now') || 'Z', datetime('now') || 'Z')
            """,
            (
                display_alias.strip(),
                home_currency.upper(),
                1 if is_admin else 0,
                1 if is_active else 0,
                multibook_chat_id.strip() if multibook_chat_id else None,
            ),
        )
        conn.commit()
        logger.info(
            "associate_created",
            alias=display_alias,
            currency=home_currency,
            is_admin=is_admin,
            is_active=is_active,
        )
        return True, f" Associate '{display_alias}' created"
    except Exception as e:
        conn.rollback()
        logger.error("associate_insert_failed", error=str(e), alias=display_alias)
        return False, f" Failed to create associate: {str(e)}"


def update_associate(
    associate_id: int,
    display_alias: str,
    home_currency: str,
    is_admin: bool,
    multibook_chat_id: Optional[str],
    is_active: bool,
    conn: Optional[sqlite3.Connection] = None,
) -> Tuple[bool, str]:
    """Update existing associate in database.

    Args:
        associate_id: ID of associate to update
        display_alias: New display name
        home_currency: New currency code
        is_admin: New admin flag
        multibook_chat_id: New Telegram chat ID
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
            UPDATE associates
            SET display_alias = ?,
                home_currency = ?,
                is_admin = ?,
                is_active = ?,
                multibook_chat_id = ?,
                updated_at_utc = datetime('now') || 'Z'
            WHERE id = ?
            """,
            (
                display_alias.strip(),
                home_currency.upper(),
                1 if is_admin else 0,
                1 if is_active else 0,
                multibook_chat_id.strip() if multibook_chat_id else None,
                associate_id,
            ),
        )
        conn.commit()
        logger.info(
            "associate_updated",
            associate_id=associate_id,
            alias=display_alias,
            is_active=is_active,
        )
        return True, " Associate updated"
    except Exception as e:
        conn.rollback()
        logger.error("associate_update_failed", error=str(e), associate_id=associate_id)
        return False, f" Failed to update associate: {str(e)}"


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
        return True, f" Associate '{alias}' deleted"
    except Exception as e:
        conn.rollback()
        logger.error("associate_delete_failed", error=str(e), associate_id=associate_id)
        return False, f" Failed to delete associate: {str(e)}"


def bulk_set_associate_active_state(
    associate_ids: Sequence[int],
    *,
    is_active: bool,
    conn: Optional[sqlite3.Connection] = None,
) -> Tuple[bool, str]:
    """Toggle active status for multiple associates at once."""

    if not associate_ids:
        return False, "Select at least one associate."

    if conn is None:
        conn = get_db_connection()
    cursor = conn.cursor()

    placeholders = ",".join("?" for _ in associate_ids)
    try:
        cursor.execute(
            f"""
            UPDATE associates
            SET is_active = ?,
                updated_at_utc = datetime('now') || 'Z'
            WHERE id IN ({placeholders})
            """,
            (1 if is_active else 0, *associate_ids),
        )
        conn.commit()
        logger.info(
            "associates_bulk_state_updated",
            count=len(associate_ids),
            is_active=is_active,
        )
        action = "activated" if is_active else "deactivated"
        return True, f" {len(associate_ids)} associate(s) {action}"
    except Exception as exc:
        conn.rollback()
        logger.error("associates_bulk_state_failed", error=str(exc))
        return False, f" Failed to update associate state: {exc}"


def can_deactivate_associates(
    associate_ids: Sequence[int], conn: Optional[sqlite3.Connection] = None
) -> Tuple[bool, List[str]]:
    """Ensure bulk deactivation keeps at least one active admin online."""

    if not associate_ids:
        return False, ["Select at least one associate."]

    if conn is None:
        conn = get_db_connection()
    cursor = conn.cursor()

    placeholders = ",".join("?" for _ in associate_ids)
    cursor.execute(
        f"""
        SELECT COUNT(*)
        FROM associates
        WHERE is_admin = 1
          AND is_active = 1
          AND id NOT IN ({placeholders})
        """,
        associate_ids,
    )
    remaining_active_admins = cursor.fetchone()[0]

    cursor.execute(
        f"""
        SELECT display_alias
        FROM associates
        WHERE id IN ({placeholders}) AND is_admin = 1
        """,
        associate_ids,
    )
    selected_admins = [row[0] for row in cursor.fetchall()]

    errors: List[str] = []
    if not remaining_active_admins and selected_admins:
        errors.append(
            "At least one admin must remain active. Deselect an admin or activate another before continuing."
        )

    return (not errors, errors)


# ============================================================================
# DATABASE QUERY FUNCTIONS - BOOKMAKERS
# ============================================================================


def load_bookmakers_for_associate(
    associate_id: int, conn: Optional[sqlite3.Connection] = None
) -> List[Dict]:
    """Load fully enriched bookmaker rows for the associate."""
    if conn is None:
        conn = get_db_connection()

    service = BookmakerFinancialsService(conn)
    snapshots = service.get_financials_for_associate(associate_id)
    return [asdict(snapshot) for snapshot in snapshots]


def load_bookmakers_for_associates(
    associate_ids: Sequence[int],
    conn: Optional[sqlite3.Connection] = None,
) -> List[Dict]:
    """Load bookmakers for multiple associates (used by the master-detail editor)."""

    if not associate_ids:
        return []

    if conn is None:
        conn = get_db_connection()

    records: List[Dict] = []
    for associate_id in associate_ids:
        records.extend(load_bookmakers_for_associate(associate_id, conn=conn))

    return records


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



def upsert_bookmaker_chat_registration(
    bookmaker_id: int,
    associate_id: int,
    chat_id: Optional[str],
    conn: Optional[sqlite3.Connection] = None,
) -> Tuple[bool, str]:
    """Create, update, or remove the latest chat registration for a bookmaker."""

    if conn is None:
        conn = get_db_connection()
    cursor = conn.cursor()

    try:
        if not chat_id:
            cursor.execute("DELETE FROM chat_registrations WHERE bookmaker_id = ?", (bookmaker_id,))
            conn.commit()
            return True, "Chat registration removed."

        cursor.execute(
            """
            SELECT id
            FROM chat_registrations
            WHERE bookmaker_id = ?
            ORDER BY updated_at_utc DESC, created_at_utc DESC, id DESC
            LIMIT 1
            """,
            (bookmaker_id,),
        )
        row = cursor.fetchone()
        if row:
            cursor.execute(
                """
                UPDATE chat_registrations
                SET chat_id = ?,
                    associate_id = ?,
                    is_active = 1,
                    updated_at_utc = datetime('now') || 'Z'
                WHERE id = ?
                """,
                (chat_id.strip(), associate_id, row["id"]),
            )
        else:
            cursor.execute(
                """
                INSERT INTO chat_registrations (
                    chat_id,
                    associate_id,
                    bookmaker_id,
                    is_active,
                    created_at_utc,
                    updated_at_utc
                ) VALUES (?, ?, ?, 1, datetime('now') || 'Z', datetime('now') || 'Z')
                """,
                (chat_id.strip(), associate_id, bookmaker_id),
            )
        conn.commit()
        return True, "Chat registration updated."
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        if "chat_registrations.chat_id" in str(exc):
            return False, "Chat ID already registered to another bookmaker."
        return False, f"Failed to update chat registration: {exc}"
    except Exception as exc:
        conn.rollback()
        return False, f"Failed to update chat registration: {exc}"

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
        return True, f" Bookmaker '{bookmaker_name}' added"
    except sqlite3.IntegrityError as e:
        conn.rollback()
        if "UNIQUE constraint failed" in str(e):
            return False, " Bookmaker already exists for this associate"
        logger.error("bookmaker_insert_failed", error=str(e), bookmaker_name=bookmaker_name)
        return False, f" Failed to create bookmaker: {str(e)}"
    except Exception as e:
        conn.rollback()
        logger.error("bookmaker_insert_failed", error=str(e), bookmaker_name=bookmaker_name)
        return False, f" Failed to create bookmaker: {str(e)}"


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
        return True, " Bookmaker updated"
    except sqlite3.IntegrityError as e:
        conn.rollback()
        if "UNIQUE constraint failed" in str(e):
            return False, " Bookmaker name already exists for this associate"
        logger.error("bookmaker_update_failed", error=str(e), bookmaker_id=bookmaker_id)
        return False, f" Failed to update bookmaker: {str(e)}"
    except Exception as e:
        conn.rollback()
        logger.error("bookmaker_update_failed", error=str(e), bookmaker_id=bookmaker_id)
        return False, f" Failed to update bookmaker: {str(e)}"


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
            f" This bookmaker has {bet_count} bet(s). Deleting will orphan these records.",
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
        return True, f" Bookmaker '{name}' deleted"
    except Exception as e:
        conn.rollback()
        logger.error("bookmaker_delete_failed", error=str(e), bookmaker_id=bookmaker_id)
        return False, f" Failed to delete bookmaker: {str(e)}"


# ============================================================================
# UI COMPONENTS - ASSOCIATES
# ============================================================================


def render_add_associate_form() -> None:
    """Render the Add Associate form in an expander."""
    with st.expander(" Add New Associate", expanded=st.session_state.get("show_add_form", False)):
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
                cancel = st.form_submit_button("Cancel", width="stretch")
            with col_save:
                submit = st.form_submit_button("Save", type="primary", width="stretch")

            if cancel:
                st.session_state.show_add_form = False
                safe_rerun()

            if submit:
                # Validate inputs
                conn = get_db_connection()

                alias_valid, alias_error = validate_alias(alias_input, db_connection=conn)
                currency_valid, currency_error = validate_currency(currency_input)
                chat_id_valid, chat_id_error = validate_multibook_chat_id(chat_id_input)

                if not alias_valid:
                    st.error(f" {alias_error}")
                elif not currency_valid:
                    st.error(f" {currency_error}")
                elif not chat_id_valid:
                    st.error(f" {chat_id_error}")
                else:
                    # Insert associate
                    success, message = insert_associate(
                        alias_input, currency_input, is_admin_input, chat_id_input or None
                    )
                    if success:
                        st.success(message)
                        st.session_state.show_add_form = False
                        safe_rerun()
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
        with st.expander(f" Edit Associate: {associate['display_alias']}", expanded=True):
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
                    is_active_input = st.checkbox(
                        "Is Active",
                        value=bool(associate.get("is_active", True)),
                        key=f"edit_is_active_{associate_id}",
                    )
                    chat_id_input = st.text_input(
                        "Multibook Chat ID (optional)",
                        value=associate["multibook_chat_id"] or "",
                        key=f"edit_chat_id_{associate_id}",
                    )

                col_cancel, col_save = st.columns([1, 1])
                with col_cancel:
                    cancel = st.form_submit_button("Cancel", width="stretch")
                with col_save:
                    submit = st.form_submit_button(
                        "Save Changes", type="primary", width="stretch"
                    )

                if cancel:
                    st.session_state[modal_key] = False
                    safe_rerun()

                if submit:
                    # Validate inputs
                    conn = get_db_connection()

                    alias_valid, alias_error = validate_alias(
                        alias_input, exclude_id=associate_id, db_connection=conn
                    )
                    currency_valid, currency_error = validate_currency(currency_input)
                    chat_id_valid, chat_id_error = validate_multibook_chat_id(chat_id_input)

                    if not alias_valid:
                        st.error(f" {alias_error}")
                    elif not currency_valid:
                        st.error(f" {currency_error}")
                    elif not chat_id_valid:
                        st.error(f" {chat_id_error}")
                    else:
                        # Update associate
                        success, message = update_associate(
                            associate_id,
                            alias_input,
                            currency_input,
                            is_admin_input,
                            chat_id_input or None,
                            is_active_input,
                        )
                        if success:
                            st.success(message)
                            st.session_state[modal_key] = False
                            safe_rerun()
                        else:
                            st.error(message)


def render_delete_confirmation_modal(associate: Dict) -> None:
    """Render the Delete Confirmation dialog."""
    associate_id = associate["id"]
    pending_key = f"pending_delete_assoc_{associate_id}"
    dialog_key = f"delete_associate_{associate_id}"

    if st.session_state.pop(pending_key, False):
        open_dialog(dialog_key)

    decision = render_confirmation_dialog(
        key=dialog_key,
        title=f"Delete Associate: {associate['display_alias']}",
        body="This will remove the associate and all related bookmakers. This action cannot be undone.",
        confirm_label="Delete",
    )

    if decision is None:
        return

    if not decision:
        return

    can_delete, reason = can_delete_associate(associate_id)
    if not can_delete:
        st.error(reason)
        open_dialog(dialog_key)
        return

    success, message = delete_associate(associate_id)
    if success:
        st.success(message)
        safe_rerun()
    else:
        st.error(message)
        open_dialog(dialog_key)


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
        with st.expander(f" Add Bookmaker to {associate['display_alias']}", expanded=True):
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
                    cancel = st.form_submit_button("Cancel", width="stretch")
                with col_save:
                    submit = st.form_submit_button("Save", type="primary", width="stretch")

                if cancel:
                    st.session_state[form_key] = False
                    safe_rerun()

                if submit:
                    # Validate inputs
                    if not name_input or not name_input.strip():
                        st.error(" Bookmaker name is required")
                    else:
                        # Validate JSON if provided
                        json_valid, json_error = validate_json(parsing_profile_input)
                        if not json_valid:
                            st.error(f" {json_error}")
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
                                safe_rerun()
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
        with st.expander(f" Edit Bookmaker: {bookmaker['bookmaker_name']}", expanded=True):
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
                    cancel = st.form_submit_button("Cancel", width="stretch")
                with col_save:
                    submit = st.form_submit_button(
                        "Save Changes", type="primary", width="stretch"
                    )

                if cancel:
                    st.session_state[modal_key] = False
                    safe_rerun()

                if submit:
                    # Validate inputs
                    if not name_input or not name_input.strip():
                        st.error(" Bookmaker name is required")
                    else:
                        # Validate JSON if provided
                        json_valid, json_error = validate_json(parsing_profile_input)
                        if not json_valid:
                            st.error(f" {json_error}")
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
                                safe_rerun()
                            else:
                                st.error(message)


def render_delete_bookmaker_modal(bookmaker: Dict, associate_alias: str) -> None:
    """Render the Delete Bookmaker confirmation dialog."""
    bookmaker_id = bookmaker["id"]
    pending_key = f"pending_delete_bookmaker_{bookmaker_id}"
    dialog_key = f"delete_bookmaker_{bookmaker_id}"

    if st.session_state.pop(pending_key, False):
        open_dialog(dialog_key)

    can_delete, warning, _ = can_delete_bookmaker(bookmaker_id)
    body_lines = [
        f"Deleting {bookmaker['bookmaker_name']} will remove it from {associate_alias}.",
    ]
    if warning and warning != "OK":
        body_lines.append(warning)

    decision = render_confirmation_dialog(
        key=dialog_key,
        title=f"Delete Bookmaker: {bookmaker['bookmaker_name']}",
        body="\n\n".join(body_lines),
        confirm_label="Delete",
    )

    if decision is None or not decision:
        return

    success, message = delete_bookmaker(bookmaker_id)
    if success:
        st.success(message)
        safe_rerun()
    else:
        st.error(message)
        open_dialog(dialog_key)



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
        status_icon = " Active" if bookmaker["is_active"] else " Inactive"
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
        bookmaker_id = bookmaker['id']
        can_delete, warning, _ = can_delete_bookmaker(bookmaker_id)
        delete_description = None if can_delete else warning
        actions = [
            ActionItem(
                key='edit',
                label='Edit',
                icon=':material/edit:',
            ),
            ActionItem(
                key='delete',
                label='Delete',
                icon=':material/delete:',
                button_type='secondary',
                disabled=not can_delete,
                description=delete_description,
            ),
        ]
        triggered_action = render_action_menu(
            key=f'bookmaker_actions_{bookmaker_id}',
            label='Actions',
            actions=actions,
        )

        if triggered_action == 'edit':
            st.session_state[f'show_edit_bookmaker_{bookmaker_id}'] = True
            safe_rerun()
        elif triggered_action == 'delete':
            st.session_state[f'pending_delete_bookmaker_{bookmaker_id}'] = True
            open_dialog(f'delete_bookmaker_{bookmaker_id}')
            safe_rerun()


def render_bookmakers_for_associate(associate: Dict) -> None:
    """Render expandable bookmaker section for an associate.

    Args:
        associate: Associate dictionary from database
    """
    associate_id = associate["id"]
    bookmaker_count = associate["bookmaker_count"]

    # Expandable section for bookmakers
    expander_label = f" Bookmakers ({bookmaker_count})"
    with st.expander(expander_label, expanded=False):
        # Add Bookmaker button
        if st.button(
            " Add Bookmaker",
            key=f"add_bm_btn_{associate_id}",
            width="stretch",
        ):
            st.session_state[f"show_add_bookmaker_{associate_id}"] = True
            safe_rerun()

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


def render_feature_status_panel() -> None:
    """Display Streamlit version compatibility information."""
    status = feature_flags.get_feature_status()
    version = status["version"]

    st.subheader(":material/new_releases: Feature Compatibility")

    with st.expander("Version Information", expanded=True):
        col1, col2, col3 = st.columns(3)
        col1.metric("Current", version.get("current") or "Unknown")
        col2.metric(
            "Minimum Met",
            "Yes" if version.get("minimum_met") else "No",
            help=f"Requires Streamlit {version['minimum_required']}+",
        )
        col3.metric(
            "Recommended",
            "Yes" if version.get("recommended_met") else "No",
            help=f"Recommended Streamlit {version['recommended']}+",
        )
        st.info(
            f"Minimum: {version['minimum_required']}  "
            f"Recommended: {version['recommended']}  "
            f"Mode: {status['compatibility_mode'].title()}"
        )

    feature_rows = []
    for name, info in status["features"].items():
        feature_rows.append(
            {
                "Feature": name.replace("_", " ").title(),
                "Available": "Yes" if info["available"] else "No",
                "Fallback": "Yes" if info["fallback_available"] else "No",
                "Introduced": info["introduced"],
                "Purpose": info["required_for"],
            }
        )

    with st.expander("Feature Availability", expanded=False):
        if feature_rows:
            st.dataframe(
                pd.DataFrame(feature_rows),
                width="stretch",
                hide_index=True,
            )
        else:
            st.write("No feature metadata available.")

        recommendations = status.get("recommendations") or []
        if recommendations:
            st.warning(
                "### :material/upgrade: Upgrade Recommended\n"
                + "\n".join(f"- {item}" for item in recommendations)
            )


def render_performance_dashboard() -> None:
    """Show recent UI timing metrics collected via track_timing."""
    timings = get_recent_timings()
    alerts = get_performance_alerts()

    with st.expander(":material/speed: Performance Dashboard", expanded=False):
        if alerts:
            alert_lines = "\n".join(
                f"- {item['label']}: {item['duration']:.3f}s "
                f"(budget {item['threshold']:.2f}s)"
                for item in alerts[-5:]
            )
            st.warning(
                "### :material/notifications_active: Performance Alerts\n"
                f"{alert_lines}"
            )

        if not timings:
            st.info("No UI timing samples yet. Interact with the queues to collect data.")
        else:
            recent_df = prepare_recent_timings(timings)
            summary = summarize_timings(recent_df)
            st.dataframe(
                recent_df,
                width="stretch",
                hide_index=True,
                column_config={
                    "Duration (s)": st.column_config.NumberColumn(
                        "Duration (s)",
                        format="%.3f",
                        help="Execution time reported by `track_timing` calls.",
                    )
                },
            )
            col1, col2, col3 = st.columns(3)
            col1.metric("Average", f"{summary.average_seconds:.3f}s")
            col2.metric("Slowest", f"{summary.slowest_seconds:.3f}s")
            col3.metric("Fastest", f"{summary.fastest_seconds:.3f}s")

        if st.button(":material/history_toggle_off: Clear Timing Samples"):
            clear_timings()
            clear_performance_alerts()
            st.success("Cleared recorded timings and alerts for this session.")

        st.markdown("#### UI Performance Playbook")
        st.markdown(
            "- Target page load times under **2 seconds**.\n"
            "- Filter operations should respond in ** 1.5 seconds** for 10k records.\n"
            "- Aim for cache hit rates above **80%**.\n"
            "- Confirm indexes are used for high-traffic queries.\n\n"
            "Refer to the [UI Performance Playbook](docs/performance-playbook.md) "
            "for detailed remediation steps."
        )


def _format_bytes(value: float) -> str:
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    idx = 0
    while value >= 1024 and idx < len(units) - 1:
        value /= 1024
        idx += 1
    return f"{value:.1f} {units[idx]}"


def _gather_diagnostics_snapshot() -> Dict[str, Any]:
    snapshot: Dict[str, Any] = {
        "db": {"associates": 0, "bookmakers": 0, "error": None},
        "performance": {},
        "resources": {},
        "features": feature_flags.get_feature_status(),
    }

    conn: Optional[sqlite3.Connection] = None
    try:
        conn = get_db_connection()
        conn.row_factory = sqlite3.Row
        associates = conn.execute("SELECT COUNT(1) AS total FROM associates").fetchone()
        bookmakers = conn.execute("SELECT COUNT(1) AS total FROM bookmakers").fetchone()
        snapshot["db"]["associates"] = associates["total"] if associates else 0
        snapshot["db"]["bookmakers"] = bookmakers["total"] if bookmakers else 0
    except sqlite3.Error as exc:
        snapshot["db"]["error"] = str(exc)
    finally:
        if conn is not None:
            conn.close()

    open_dialogs = len(
        [
            key
            for key, value in st.session_state.items()
            if key.endswith("__open") and value
        ]
    )
    snapshot["performance"] = {
        "last_refresh": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "open_dialogs": open_dialogs,
    }

    disk_usage = shutil.disk_usage(Path("."))
    snapshot["resources"] = {
        "disk_free": disk_usage.free,
        "disk_total": disk_usage.total,
    }
    return snapshot


def render_system_diagnostics_panel() -> None:
    """Render consolidated diagnostics for admin operators."""
    snapshot = _gather_diagnostics_snapshot()
    with st.expander(" System Diagnostics", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("#### Database Health")
            if snapshot["db"].get("error"):
                st.error(f"Database check failed: {snapshot['db']['error']}")
            else:
                st.metric("Associates", snapshot["db"]["associates"])
                st.metric("Bookmakers", snapshot["db"]["bookmakers"])
        with col2:
            st.markdown("#### Performance Metrics")
            st.metric("Last Refresh", snapshot["performance"].get("last_refresh", "--"))
            st.metric("Open Dialogs", snapshot["performance"].get("open_dialogs", 0))

        st.markdown("#### Feature Status Summary")
        missing = snapshot["features"].get("missing") or []
        if missing:
            st.warning(
                "Missing features: "
                + ", ".join(missing)
                + ". Upgrade Streamlit to unlock advanced UI capabilities."
            )
        else:
            st.success("All tracked Streamlit features are active.")

        st.markdown("#### System Resources")
        st.metric(
            "Disk Free",
            _format_bytes(float(snapshot["resources"].get("disk_free", 0))),
        )
        st.metric(
            "Disk Total",
            _format_bytes(float(snapshot["resources"].get("disk_total", 0))),
        )


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
        col1, col2, col3, col4, col5 = st.columns([3, 1.5, 1, 1.5, 2])

        with col1:
            admin_badge = ":material/verified:" if assoc["is_admin"] else ""
            st.markdown(f"**{assoc['display_alias']}** {admin_badge}")

        with col2:
            st.text(assoc["home_currency"])

        with col3:
            st.text(str(assoc["bookmaker_count"]))

        with col4:
            created_date = format_utc_datetime_local(assoc["created_at_utc"])
            if created_date:
                created_display = created_date.split(" ")[0]
            else:
                created_display = "N/A"
            st.text(created_display)

        with col5:
            assoc_id = assoc["id"]
            can_delete, delete_reason = can_delete_associate(assoc_id)
            actions = [
                ActionItem(
                    key="edit",
                    label="Edit",
                    icon=":material/edit:",
                ),
                ActionItem(
                    key="delete",
                    label="Delete",
                    icon=":material/delete:",
                    button_type="secondary",
                    disabled=not can_delete,
                    description=None if can_delete else delete_reason,
                ),
            ]
            triggered = render_action_menu(
                key=f"associate_actions_{assoc_id}",
                label="Actions",
                actions=actions,
            )

            if triggered == "edit":
                st.session_state[f"show_edit_modal_{assoc_id}"] = True
                safe_rerun()
            elif triggered == "delete":
                st.session_state[f"pending_delete_assoc_{assoc_id}"] = True
                open_dialog(f"delete_associate_{assoc_id}")
                safe_rerun()

        # Render expandable bookmaker section
        render_bookmakers_for_associate(assoc)

        st.divider()


# ============================================================================
# MAIN PAGE RENDER
# ============================================================================

# Only run Streamlit UI code if not being imported by tests
if __name__ != "__main__" or "pytest" not in globals():
    try:
        st.set_page_config(page_title=PAGE_TITLE, page_icon=PAGE_ICON, layout="wide")

        st.title(f"{PAGE_ICON} {PAGE_TITLE}")
        render_feature_status_panel()
        render_performance_dashboard()
        render_system_diagnostics_panel()
        st.divider()

        # Initialize session state
        if "show_add_form" not in st.session_state:
            st.session_state.show_add_form = False

        # Tabs
        tab1, tab2 = st.tabs(["Associates & Bookmakers", "Balance History"])

        with tab1:
            if _supports_data_editor():
                render_modern_associate_management_tab()
            else:
                render_legacy_associate_management_tab()

        with tab2:
            render_balance_history_tab()
    except Exception:
        # Silently ignore errors during test imports
        pass

