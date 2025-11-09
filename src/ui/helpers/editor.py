"""
Typed Streamlit data_editor helpers for associates/bookmakers management.

This module centralises column configurations, dataframe builders, selection
helpers, and validation utilities so page implementations can focus on the
workflow logic instead of low-level editor plumbing.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import pandas as pd
import streamlit as st

from src.ui.utils.validators import (
    VALID_CURRENCIES,
    validate_alias,
    validate_currency,
    validate_json,
    validate_multibook_chat_id,
)


ASSOCIATE_COLUMNS: Tuple[str, ...] = (
    "id",
    "display_alias",
    "home_currency",
    "is_admin",
    "is_active",
    "multibook_chat_id",
    "bookmaker_count",
    "created_at_utc",
    "updated_at_utc",
)

BOOKMAKER_COLUMNS: Tuple[str, ...] = (
    "id",
    "associate_id",
    "bookmaker_name",
    "bookmaker_chat_id",
    "is_active",
    "balance_eur",
    "pending_balance_eur",
    "net_deposits_eur",
)


@dataclass(frozen=True)
class EditorChanges:
    """Normalized representation of edits made inside a data_editor."""

    edited_rows: Dict[int, Dict[str, Any]]
    added_rows: List[Dict[str, Any]]
    deleted_rows: List[int]


def build_associates_dataframe(records: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    """Return a normalized dataframe for the associates editor."""

    if not records:
        return pd.DataFrame(columns=ASSOCIATE_COLUMNS)

    frame = pd.DataFrame(records)
    for column in ASSOCIATE_COLUMNS:
        if column not in frame.columns:
            frame[column] = None

    frame = frame.loc[:, ASSOCIATE_COLUMNS].copy()
    for bool_column in ("is_admin", "is_active"):
        frame[bool_column] = frame[bool_column].where(
            frame[bool_column].notna(), False
        ).astype(bool)
    frame["bookmaker_count"] = frame["bookmaker_count"].where(
        frame["bookmaker_count"].notna(), 0
    ).astype(int)
    return frame.reset_index(drop=True)


def build_bookmakers_dataframe(records: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    """Return a normalized dataframe for the bookmakers editor."""

    if not records:
        return pd.DataFrame(columns=BOOKMAKER_COLUMNS)

    frame = pd.DataFrame(records)
    for column in BOOKMAKER_COLUMNS:
        if column not in frame.columns:
            frame[column] = None

    frame = frame.loc[:, BOOKMAKER_COLUMNS].copy()
    frame["is_active"] = frame["is_active"].where(
        frame["is_active"].notna(), True
    ).astype(bool)
    frame["associate_id"] = frame["associate_id"].fillna(0).astype(int)
    frame["bookmaker_chat_id"] = frame["bookmaker_chat_id"].fillna("").astype(str)

    for column in ("balance_eur", "pending_balance_eur", "net_deposits_eur"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

    return frame.reset_index(drop=True)


def get_associate_column_config() -> Dict[str, st.column_config.Column]:
    """Typed column configuration for the associates data_editor."""

    return {
        "id": st.column_config.NumberColumn("ID", disabled=True, width="small"),
        "display_alias": st.column_config.TextColumn(
            "Display Alias",
            required=True,
            width="medium",
            help="Friendly name shown throughout the console. Must be unique.",
        ),
        "home_currency": st.column_config.SelectboxColumn(
            "Currency",
            options=VALID_CURRENCIES,
            width="small",
        ),
        "is_admin": st.column_config.CheckboxColumn("Admin", width="small"),
        "is_active": st.column_config.CheckboxColumn("Active", width="small"),
        "multibook_chat_id": st.column_config.TextColumn(
            "Multibook Chat ID",
            width="medium",
            help="Optional Telegram chat ID for multibook automation.",
        ),
        "bookmaker_count": st.column_config.NumberColumn(
            "Bookmakers",
            disabled=True,
            width="small",
        ),
        "created_at_utc": st.column_config.DatetimeColumn(
            "Created",
            disabled=True,
            format="YYYY-MM-DD HH:mm",
            width="medium",
        ),
        "updated_at_utc": st.column_config.DatetimeColumn(
            "Updated",
            disabled=True,
            format="YYYY-MM-DD HH:mm",
            width="medium",
        ),
    }


def get_bookmaker_column_config(*, show_associate: bool = False) -> Dict[str, st.column_config.Column]:
    """Typed column configuration for the bookmakers data_editor."""

    config: Dict[str, st.column_config.Column] = {
        "id": st.column_config.NumberColumn("ID", disabled=True, width="small"),
        "bookmaker_name": st.column_config.TextColumn(
            "Bookmaker",
            required=True,
            width="medium",
        ),
        "bookmaker_chat_id": st.column_config.TextColumn(
            "Bookmaker Chat ID",
            width="medium",
            help="Latest Telegram chat registered for this bookmaker.",
        ),
        "is_active": st.column_config.CheckboxColumn("Active", width="small"),
        "balance_eur": st.column_config.NumberColumn(
            "Balance (EUR)",
            disabled=True,
            format="%.2f",
            help="Latest reported bookmaker balance converted to EUR.",
        ),
        "pending_balance_eur": st.column_config.NumberColumn(
            "Pending Balance (EUR)",
            disabled=True,
            format="%.2f",
            help="Verified + matched stakes awaiting settlement for this bookmaker.",
        ),
        "net_deposits_eur": st.column_config.NumberColumn(
            "Deposits (EUR)",
            disabled=True,
            format="%.2f",
            help="Net deposits (deposits minus withdrawals) tied to this bookmaker.",
        ),
    }

    if show_associate:
        config["associate_id"] = st.column_config.NumberColumn(
            "Associate ID",
            disabled=True,
            width="small",
        )

    return config


def extract_editor_changes(state: Optional[Mapping[str, Any]]) -> EditorChanges:
    """Normalize Streamlit data_editor session state into a stable structure."""

    if not state:
        return EditorChanges({}, [], [])

    edited = dict(state.get("edited_rows", {}))
    added = list(state.get("added_rows", []))
    deleted = list(state.get("deleted_rows", []))
    return EditorChanges(edited_rows=edited, added_rows=added, deleted_rows=deleted)


def get_selected_row_ids(
    state: Optional[Mapping[str, Any]],
    dataframe: pd.DataFrame,
    *,
    id_column: str = "id",
) -> List[int]:
    """Return the database IDs represented by the current data_editor selection."""

    if not state or not dataframe.size:
        return []

    selection = state.get("selection") or {}
    rows_payload = selection.get("rows")

    if isinstance(rows_payload, list):
        row_entries: Iterable[Any] = rows_payload
    elif isinstance(rows_payload, dict):
        flattened: List[Any] = []
        for key in ("selected_rows", "rows", "indices"):
            value = rows_payload.get(key)
            if isinstance(value, list):
                flattened.extend(value)
        row_entries = flattened
    else:
        row_entries = []

    selected_ids: List[int] = []

    for entry in row_entries:
        if isinstance(entry, dict):
            idx = entry.get("index", entry.get("row"))
        else:
            idx = entry

        if isinstance(idx, int) and 0 <= idx < len(dataframe):
            value = dataframe.iloc[idx][id_column]
            if pd.notna(value):
                selected_ids.append(int(value))

    return selected_ids


def filter_bookmakers_by_associates(
    bookmakers: pd.DataFrame,
    associate_ids: Sequence[int],
) -> pd.DataFrame:
    """Return bookmakers limited to the provided associate IDs."""

    if not associate_ids or bookmakers.empty:
        return bookmakers.iloc[0:0]

    mask = bookmakers["associate_id"].isin(associate_ids)
    return bookmakers.loc[mask].reset_index(drop=True)


def validate_share_percentage(value: Optional[Any]) -> Tuple[bool, str]:
    """Validate optional share percentage input (0-100, max 1 decimal place)."""

    if value in (None, ""):
        return True, ""

    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return False, "Share % must be a numeric value."

    if decimal_value < 0 or decimal_value > 100:
        return False, "Share % must be between 0 and 100."

    exponent = decimal_value.normalize().as_tuple().exponent
    if isinstance(exponent, int) and exponent < -1:
        return False, "Share % supports at most 1 decimal place."

    return True, ""


def validate_currency_code(value: Optional[str]) -> Tuple[bool, str]:
    """Wrapper around validate_currency with clearer error copy for editors."""

    return validate_currency(value or "")


def validate_parsing_profile(profile: Optional[str]) -> Tuple[bool, str]:
    """Ensure parsing profile, when provided, is valid JSON."""

    return validate_json(profile)


def validate_associate_row(
    row: Mapping[str, Any],
    *,
    db_connection,
) -> Tuple[bool, List[str]]:
    """Validate associate editor row values."""

    errors: List[str] = []

    alias = (row.get("display_alias") or "").strip()
    is_valid_alias, alias_error = validate_alias(alias, exclude_id=row.get("id"), db_connection=db_connection)
    if not is_valid_alias:
        errors.append(alias_error or "Alias is invalid.")

    currency = (row.get("home_currency") or "").strip().upper()
    is_valid_currency, currency_error = validate_currency(currency)
    if not is_valid_currency:
        errors.append(currency_error or "Currency is invalid.")

    chat_id = (row.get("multibook_chat_id") or "").strip()
    if chat_id and not chat_id.lstrip("-").isdigit():
        errors.append("Chat ID must be numeric (you can use negative IDs for channels).")

    share_value = row.get("share_pct")
    is_valid_share, share_error = validate_share_percentage(share_value)
    if not is_valid_share:
        errors.append(share_error)

    return not errors, errors


def validate_bookmaker_row(row: Mapping[str, Any]) -> Tuple[bool, List[str]]:
    """Validate bookmaker editor row values."""

    errors: List[str] = []
    name = (row.get("bookmaker_name") or "").strip()
    if not name:
        errors.append("Bookmaker name is required.")

    profile = row.get("parsing_profile")
    ok_profile, profile_error = validate_parsing_profile(profile)
    if not ok_profile:
        errors.append(profile_error or "Parsing profile JSON is invalid.")

    chat_id = (row.get("bookmaker_chat_id") or "").strip()
    if chat_id:
        ok_chat, chat_error = validate_multibook_chat_id(chat_id)
        if not ok_chat:
            errors.append(chat_error or "Chat ID must be numeric.")

    return not errors, errors


__all__ = [
    "ASSOCIATE_COLUMNS",
    "BOOKMAKER_COLUMNS",
    "EditorChanges",
    "build_associates_dataframe",
    "build_bookmakers_dataframe",
    "extract_editor_changes",
    "filter_bookmakers_by_associates",
    "get_associate_column_config",
    "get_bookmaker_column_config",
    "get_selected_row_ids",
    "validate_associate_row",
    "validate_bookmaker_row",
    "validate_currency_code",
    "validate_parsing_profile",
    "validate_share_percentage",
]
