"""
Associates Hub page - Management tab (Story 13.1).

Renders a new Streamlit page with a Management-first experience that combines
associate configuration, inline editing, derived metrics, and bookmaker
management with confirmation prompts for sensitive operations.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd
import streamlit as st

from src.repositories.associate_hub_repository import (
    AssociateHubRepository,
    AssociateMetrics,
    BookmakerSummary,
)
from src.services.bookmaker_balance_service import BookmakerBalanceService
from src.services.funding_transaction_service import FundingTransactionService
from src.ui.components.associate_hub.drawer import render_detail_drawer
from src.ui.components.associate_hub.filters import render_filters
from src.ui.helpers.dialogs import open_dialog, render_confirmation_dialog
from src.ui.helpers.editor import (
    extract_editor_changes,
    get_selected_row_ids,
)
from src.ui.ui_components import load_global_styles
from src.ui.utils.state_management import safe_rerun
from src.ui.utils.validators import VALID_CURRENCIES


PENDING_TAB_KEY = "associates_hub_pending_tab"
ASSOC_EDITOR_KEY = "associates_hub_associates_editor"
BOOKMAKER_EDITOR_KEY = "associates_hub_bookmakers_editor"
SELECTED_IDS_KEY = "associates_hub_selected_ids"
SELECTED_ASSOCIATE_KEY = "associates_hub_selected_associate"
BOOKMAKER_SCOPE_KEY = "associates_hub_bookmaker_scope"
BOOKMAKER_REASSIGN_PAYLOAD_KEY = "associates_hub_reassign_payload"
BOOKMAKER_REASSIGN_DIALOG_KEY = "associates_hub_reassign_dialog"

MANAGEMENT_TAB_INDEX = 0
OVERVIEW_TAB_INDEX = 1
HISTORY_TAB_INDEX = 2


@dataclass(frozen=True)
class AssociateRow:
    """Serializable representation used for testing and persistence."""

    id: Optional[int]
    display_alias: str
    home_currency: str
    is_admin: bool
    is_active: bool
    multibook_chat_id: Optional[str]
    internal_notes: Optional[str]
    max_surebet_stake_eur: Optional[Decimal]
    max_bookmaker_exposure_eur: Optional[Decimal]
    preferred_balance_chat_id: Optional[str]


def _configure_page() -> None:
    """Set global page config once."""
    try:
        st.set_page_config(
            page_title="Associates Hub",
            page_icon=":material/diversity_3:",
            layout="wide",
            initial_sidebar_state="expanded",
        )
    except st.errors.StreamlitAPIException:
        # Already configured by outer shell.
        pass


def _editor_has_changes(state: Optional[Dict[str, Any]]) -> bool:
    """Return True when the Streamlit editor captured modifications."""
    if not state:
        return False
    return any(
        bool(state.get(key))
        for key in ("edited_rows", "added_rows", "deleted_rows")
    )


def _decimal_to_float(value: Optional[Decimal]) -> Optional[float]:
    """Convert Decimals to floats for data_editor consumption."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _build_associate_dataframe(
    items: Sequence[AssociateMetrics],
) -> pd.DataFrame:
    """Convert associate metrics to a pandas DataFrame for the editor."""
    records: List[Dict[str, Any]] = []
    for metric in items:
        records.append(
            {
                "id": metric.associate_id,
                "display_alias": metric.associate_alias,
                "home_currency": metric.home_currency or "EUR",
                "is_admin": metric.is_admin,
                "is_active": metric.is_active,
                "multibook_chat_id": metric.telegram_chat_id or "",
                "internal_notes": metric.internal_notes or "",
                "max_surebet_stake_eur": _decimal_to_float(
                    metric.max_surebet_stake_eur
                ),
                "max_bookmaker_exposure_eur": _decimal_to_float(
                    metric.max_bookmaker_exposure_eur
                ),
                "preferred_balance_chat_id": metric.preferred_balance_chat_id or "",
                "nd_eur": _decimal_to_float(metric.net_deposits_eur),
                "yf_eur": _decimal_to_float(metric.should_hold_eur),
                "tb_eur": _decimal_to_float(metric.current_holding_eur),
                "imbalance_eur": _decimal_to_float(metric.delta_eur),
                "bookmaker_count": metric.bookmaker_count,
                "last_activity": metric.last_activity_utc or "Never",
                "action": "",
            }
        )
    if not records:
        return pd.DataFrame(
            columns=[
                "id",
                "display_alias",
                "home_currency",
                "is_admin",
                "is_active",
                "multibook_chat_id",
                "internal_notes",
                "max_surebet_stake_eur",
                "max_bookmaker_exposure_eur",
                "preferred_balance_chat_id",
                "nd_eur",
                "yf_eur",
                "tb_eur",
                "imbalance_eur",
                "bookmaker_count",
                "last_activity",
                "action",
            ]
        )
    frame = pd.DataFrame(records)
    return frame


def _build_bookmaker_dataframe(
    items: Sequence[BookmakerSummary],
) -> Tuple[pd.DataFrame, Dict[int, Dict[str, Any]]]:
    """Convert bookmaker summaries into dataframe + metadata map."""
    records: List[Dict[str, Any]] = []
    metadata: Dict[int, Dict[str, Any]] = {}
    for summary in items:
        active_balance = summary.reported_balance_eur or summary.modeled_balance_eur
        associate_alias = getattr(summary, "associate_alias", "") or ""
        metadata[summary.bookmaker_id] = {
            "associate_id": summary.associate_id,
            "bookmaker_name": summary.bookmaker_name,
            "active_balance": active_balance,
            "associate_alias": associate_alias,
        }
        active_native = getattr(summary, "active_balance_native", None)
        pending_native = getattr(summary, "pending_balance_native", None)
        records.append(
            {
                "id": summary.bookmaker_id,
                "associate_id": summary.associate_id,
                "associate_alias": associate_alias,
                "bookmaker_name": summary.bookmaker_name,
                "account_currency": summary.native_currency,
                "is_active": summary.is_active,
                "parsing_profile": summary.parsing_profile or "",
                "bookmaker_chat_id": summary.bookmaker_chat_id or "",
                "coverage_chat_id": summary.coverage_chat_id or "",
                "region": summary.region or "",
                "risk_level": summary.risk_level or "",
                "internal_notes": summary.internal_notes or "",
                "active_balance_native": _decimal_to_float(active_native),
                "pending_balance_native": _decimal_to_float(pending_native),
                "active_balance_eur": _decimal_to_float(active_balance),
                "pending_balance_eur": _decimal_to_float(summary.pending_balance_eur),
                "last_balance_check": summary.last_balance_check_utc or "Never",
            }
        )
    columns = [
        "id",
        "associate_id",
        "associate_alias",
        "bookmaker_name",
        "account_currency",
        "is_active",
        "parsing_profile",
        "bookmaker_chat_id",
        "coverage_chat_id",
        "region",
        "risk_level",
        "internal_notes",
        "active_balance_native",
        "pending_balance_native",
        "active_balance_eur",
        "pending_balance_eur",
        "last_balance_check",
    ]
    if not records:
        return pd.DataFrame(columns=columns), metadata
    return pd.DataFrame(records), metadata


def _normalize_associate_payload(row: Dict[str, Any]) -> AssociateRow:
    """Ensure associate payloads have sanitized values."""
    alias = (row.get("display_alias") or "").strip()
    currency = (row.get("home_currency") or "EUR").strip().upper()
    multibook = (row.get("multibook_chat_id") or "").strip()
    notes = (row.get("internal_notes") or "").strip()
    preferred_chat = (row.get("preferred_balance_chat_id") or "").strip()

    def _to_decimal(value: Any) -> Optional[Decimal]:
        if value in (None, ""):
            return None
        try:
            return Decimal(str(value))
        except (ValueError, TypeError, ArithmeticError):
            return None

    return AssociateRow(
        id=row.get("id"),
        display_alias=alias,
        home_currency=currency or "EUR",
        is_admin=bool(row.get("is_admin")),
        is_active=bool(row.get("is_active", True)),
        multibook_chat_id=multibook or None,
        internal_notes=notes or None,
        max_surebet_stake_eur=_to_decimal(row.get("max_surebet_stake_eur")),
        max_bookmaker_exposure_eur=_to_decimal(
            row.get("max_bookmaker_exposure_eur")
        ),
        preferred_balance_chat_id=preferred_chat or None,
    )


def _normalize_bookmaker_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    """Return sanitized bookmaker row values."""
    payload = {
        "id": row.get("id"),
        "associate_id": row.get("associate_id"),
        "bookmaker_name": (row.get("bookmaker_name") or "").strip(),
        "account_currency": (row.get("account_currency") or "EUR").strip().upper(),
        "is_active": bool(row.get("is_active", True)),
        "parsing_profile": (row.get("parsing_profile") or "").strip() or None,
        "bookmaker_chat_id": (row.get("bookmaker_chat_id") or "").strip() or None,
        "coverage_chat_id": (row.get("coverage_chat_id") or "").strip() or None,
        "region": (row.get("region") or "").strip() or None,
        "risk_level": (row.get("risk_level") or "").strip() or None,
        "internal_notes": (row.get("internal_notes") or "").strip() or None,
    }
    try:
        if payload["associate_id"] not in (None, ""):
            payload["associate_id"] = int(payload["associate_id"])
        else:
            payload["associate_id"] = None
    except (TypeError, ValueError):
        payload["associate_id"] = None
    return payload


def _render_selection_picker(
    dataframe: pd.DataFrame, selected_ids: Sequence[int]
) -> List[int]:
    """Provide a multiselect fallback so operators can pin associates explicitly."""
    if dataframe.empty:
        return list(selected_ids)
    options: Dict[str, int] = {}
    for _, row in dataframe.iterrows():
        associate_id = int(row.get("id") or 0)
        if not associate_id:
            continue
        label = f"{row.get('display_alias', 'Associate')} (ID {associate_id})"
        options.setdefault(label, associate_id)

    default_labels = [
        label for label, assoc_id in options.items() if assoc_id in selected_ids
    ]
    chosen_labels = st.multiselect(
        "Associate focus",
        options=list(options.keys()),
        default=default_labels,
        help="Use this picker to refine or clear the selection explicitly.",
    )
    return [options[label] for label in chosen_labels]


def _handle_associate_actions(
    state: Optional[Dict[str, Any]],
    edited_df: pd.DataFrame,
    associate_lookup: Dict[int, str],
) -> None:
    """Process Selectbox-based actions and strip them from change tracking."""
    if not state:
        return
    edited_rows = state.get("edited_rows")
    if not isinstance(edited_rows, dict):
        return

    pending_actions: List[Tuple[int, str]] = []
    for row_idx, payload in list(edited_rows.items()):
        action = payload.pop("action", None)
        if action:
            pending_actions.append((row_idx, action))
        if not payload:
            edited_rows.pop(row_idx, None)

    for row_idx, action in pending_actions:
        if row_idx >= len(edited_df):
            continue
        row = edited_df.iloc[row_idx]
        associate_id = int(row.get("id") or 0)
        alias = associate_lookup.get(associate_id, row.get("display_alias", "Associate"))
        st.session_state[SELECTED_ASSOCIATE_KEY] = associate_id

        if action == "Details":
            st.session_state["hub_drawer_open"] = True
            st.session_state["hub_drawer_associate_id"] = associate_id
            st.session_state["hub_drawer_tab"] = "profile"
            st.toast(f"Opening details for {alias}")
            safe_rerun("open_associate_details")
        elif action == "Go to Overview":
            st.session_state[PENDING_TAB_KEY] = OVERVIEW_TAB_INDEX
            st.toast(f"{alias} queued for Overview tab")
            safe_rerun("associate_overview_jump")
        elif action == "View history":
            st.session_state[PENDING_TAB_KEY] = HISTORY_TAB_INDEX
            st.toast(f"{alias} queued for Balance History")
            safe_rerun("associate_history_jump")


def _handle_pending_bookmaker_confirmation(
    repository: AssociateHubRepository,
) -> None:
    """Render confirmation dialog when reassignment requires approval."""
    payload = st.session_state.get(BOOKMAKER_REASSIGN_PAYLOAD_KEY)
    if not payload:
        return

    dialog_body = (
        f"Reassign **{payload['bookmaker_name']}** from associate "
        f"{payload['current_alias']} to {payload['target_alias']}?\n\n"
        f"Active balance: €{payload['active_balance']:,.2f}. "
        "This affects downstream financial dashboards."
    )
    decision = render_confirmation_dialog(
        key=BOOKMAKER_REASSIGN_DIALOG_KEY,
        title="Confirm bookmaker reassignment",
        body=dialog_body,
        confirm_label="Reassign",
        cancel_label="Keep current associate",
    )
    if decision is None:
        return

    st.session_state.pop(BOOKMAKER_REASSIGN_PAYLOAD_KEY, None)
    if decision:
        try:
            repository.update_bookmaker(
                payload["bookmaker_id"],
                payload["bookmaker_name"],
                payload["is_active"],
                payload.get("parsing_profile"),
                associate_id=payload["new_associate_id"],
                account_currency=payload["account_currency"],
                bookmaker_chat_id=payload.get("bookmaker_chat_id"),
                coverage_chat_id=payload.get("coverage_chat_id"),
                region=payload.get("region"),
                risk_level=payload.get("risk_level"),
                internal_notes=payload.get("internal_notes"),
            )
        except Exception as exc:
            st.error(f"Failed to reassign bookmaker: {exc}")
            return
        st.success(
            f"Reassigned {payload['bookmaker_name']} "
            f"to {payload['target_alias']}."
        )
    else:
        st.info("Bookmaker reassignment cancelled.")
    safe_rerun()


def _queue_bookmaker_reassignment(payload: Dict[str, Any]) -> None:
    """Store reassignment details and trigger dialog on next render."""
    st.session_state[BOOKMAKER_REASSIGN_PAYLOAD_KEY] = payload
    open_dialog(BOOKMAKER_REASSIGN_DIALOG_KEY)
    safe_rerun("bookmaker_reassignment_prompt")


def _persist_associate_changes(
    repository: AssociateHubRepository,
    source_df: pd.DataFrame,
    edited_df: pd.DataFrame,
    state: Optional[Dict[str, Any]],
) -> None:
    """Write associate edits/inserts via the repository."""
    if not state:
        st.info("No pending associate changes.")
        return

    changes = extract_editor_changes(state)
    if not (
        changes.added_rows or changes.edited_rows or changes.deleted_rows
    ):
        st.info("No pending associate changes.")
        return

    applied = 0
    errors: List[str] = []

    if changes.deleted_rows:
        errors.append(
            "Deleting associates is disabled on the Management tab."
        )

    for row_idx, edited in changes.edited_rows.items():
        if row_idx >= len(edited_df):
            continue
        payload = _normalize_associate_payload(
            edited_df.iloc[row_idx].to_dict()
        )
        if not payload.id:
            errors.append("Cannot update associate without ID.")
            continue
        try:
            repository.update_associate(
                payload.id,
                payload.display_alias,
                payload.home_currency,
                payload.is_admin,
                payload.is_active,
                payload.multibook_chat_id,
                internal_notes=payload.internal_notes,
                max_surebet_stake_eur=payload.max_surebet_stake_eur,
                max_bookmaker_exposure_eur=payload.max_bookmaker_exposure_eur,
                preferred_balance_chat_id=payload.preferred_balance_chat_id,
            )
            applied += 1
        except Exception as exc:
            errors.append(str(exc))

    for row in changes.added_rows:
        payload = _normalize_associate_payload(row)
        if not payload.display_alias:
            errors.append("Display alias is required for new associates.")
            continue
        try:
            repository.create_associate(
                payload.display_alias,
                payload.home_currency,
                payload.is_admin,
                payload.is_active,
                telegram_chat_id=payload.multibook_chat_id,
                internal_notes=payload.internal_notes,
                max_surebet_stake_eur=payload.max_surebet_stake_eur,
                max_bookmaker_exposure_eur=payload.max_bookmaker_exposure_eur,
                preferred_balance_chat_id=payload.preferred_balance_chat_id,
            )
            applied += 1
        except Exception as exc:
            errors.append(str(exc))

    if applied:
        st.success(f"Saved {applied} associate change(s).")
    if errors:
        for error in errors:
            st.error(error)
    if applied:
        safe_rerun("associates_saved")


def _persist_bookmaker_changes(
    repository: AssociateHubRepository,
    source_df: pd.DataFrame,
    edited_df: pd.DataFrame,
    state: Optional[Dict[str, Any]],
    *,
    metadata: Dict[int, Dict[str, Any]],
    associate_lookup: Dict[int, str],
) -> None:
    """Write bookmaker updates/inserts."""
    if not state:
        st.info("No pending bookmaker changes.")
        return

    changes = extract_editor_changes(state)
    if not (
        changes.added_rows or changes.edited_rows or changes.deleted_rows
    ):
        st.info("No pending bookmaker changes.")
        return

    if changes.deleted_rows:
        st.warning("Deleting bookmakers from this tab is not supported yet.")

    applied = 0
    errors: List[str] = []

    for row_idx, edited in changes.edited_rows.items():
        if row_idx >= len(edited_df):
            continue
        payload = _normalize_bookmaker_payload(
            edited_df.iloc[row_idx].to_dict()
        )
        bookmaker_id = payload.get("id")
        if not bookmaker_id:
            errors.append("Cannot update bookmaker without ID.")
            continue
        context = metadata.get(int(bookmaker_id), {})
        previous_associate = context.get("associate_id")
        new_associate = payload.get("associate_id") or previous_associate
        if previous_associate != new_associate:
            balance = context.get("active_balance") or Decimal("0")
            if balance and abs(balance) > Decimal("0"):
                target_alias = associate_lookup.get(
                    new_associate, f"Associate {new_associate}"
                )
                current_alias = associate_lookup.get(
                    previous_associate, f"Associate {previous_associate}"
                )
                _queue_bookmaker_reassignment(
                    {
                        "bookmaker_id": bookmaker_id,
                        "bookmaker_name": payload["bookmaker_name"],
                        "current_alias": current_alias,
                        "target_alias": target_alias,
                        "new_associate_id": new_associate,
                        "active_balance": float(balance),
                        "is_active": payload["is_active"],
                        "parsing_profile": payload["parsing_profile"],
                        "account_currency": payload["account_currency"],
                        "bookmaker_chat_id": payload.get("bookmaker_chat_id"),
                        "coverage_chat_id": payload.get("coverage_chat_id"),
                        "region": payload.get("region"),
                        "risk_level": payload.get("risk_level"),
                        "internal_notes": payload.get("internal_notes"),
                    }
                )
                continue
        try:
            repository.update_bookmaker(
                bookmaker_id,
                payload["bookmaker_name"],
                payload["is_active"],
                payload["parsing_profile"],
                associate_id=new_associate,
                account_currency=payload["account_currency"],
                bookmaker_chat_id=payload.get("bookmaker_chat_id"),
                coverage_chat_id=payload.get("coverage_chat_id"),
                region=payload.get("region"),
                risk_level=payload.get("risk_level"),
                internal_notes=payload.get("internal_notes"),
            )
            applied += 1
        except Exception as exc:
            errors.append(str(exc))

    for row in changes.added_rows:
        payload = _normalize_bookmaker_payload(row)
        if not payload["bookmaker_name"]:
            errors.append("Bookmaker name is required.")
            continue
        if not payload["associate_id"]:
            errors.append("New bookmakers must specify an associate ID.")
            continue
        try:
            repository.create_bookmaker(
                payload["associate_id"],
                payload["bookmaker_name"],
                payload["is_active"],
                payload["parsing_profile"],
                account_currency=payload["account_currency"],
                bookmaker_chat_id=payload.get("bookmaker_chat_id"),
                coverage_chat_id=payload.get("coverage_chat_id"),
                region=payload.get("region"),
                risk_level=payload.get("risk_level"),
                internal_notes=payload.get("internal_notes"),
            )
            applied += 1
        except Exception as exc:
            errors.append(str(exc))

    if applied:
        st.success(f"Saved {applied} bookmaker change(s).")
    if errors:
        for error in errors:
            st.error(error)
    if applied:
        safe_rerun("bookmakers_saved")


def _render_associate_table(
    repository: AssociateHubRepository,
    filter_state: Dict[str, Any],
) -> Tuple[List[int], Dict[int, str]]:
    """Render associates data_editor and return selection + lookup."""
    page = max(int(filter_state.get("page", 0)), 0)
    page_size = int(filter_state.get("page_size") or 25)
    associates = repository.list_associates_with_metrics(
        search=filter_state.get("search"),
        admin_filter=filter_state.get("admin_filter"),
        associate_status_filter=filter_state.get("associate_status_filter"),
        bookmaker_status_filter=filter_state.get("bookmaker_status_filter"),
        currency_filter=filter_state.get("currency_filter"),
        sort_by=filter_state.get("sort_by"),
        limit=page_size,
        offset=page * page_size,
    )
    df = _build_associate_dataframe(associates)
    associate_lookup = {
        metric.associate_id: metric.associate_alias for metric in associates
    }
    st.metric(
        "Associates in view",
        len(df),
        help="Limited by filters and pagination controls above.",
    )

    column_config = {
        "display_alias": st.column_config.TextColumn(
            "Display Alias",
            help="Shown across the console; must be unique.",
        ),
        "home_currency": st.column_config.SelectboxColumn(
            "Currency",
            options=VALID_CURRENCIES,
        ),
        "is_admin": st.column_config.CheckboxColumn("Admin"),
        "is_active": st.column_config.CheckboxColumn("Active"),
        "multibook_chat_id": st.column_config.TextColumn(
            "Multibook Chat",
            help="Telegram chat ID used for automation.",
        ),
        "internal_notes": st.column_config.TextColumn(
            "Internal Notes",
            width="medium",
        ),
        "max_surebet_stake_eur": st.column_config.NumberColumn(
            "Max Stake (EUR)",
            help="Optional surebet stake ceiling.",
            step=100.0,
            format="%.2f",
        ),
        "max_bookmaker_exposure_eur": st.column_config.NumberColumn(
            "Max Exposure (EUR)",
            help="Optional total bookmaker exposure limit.",
            step=500.0,
            format="%.2f",
        ),
        "preferred_balance_chat_id": st.column_config.TextColumn(
            "Preferred Balance Chat",
            help="Destination for balance reports.",
        ),
        "nd_eur": st.column_config.NumberColumn(
            "ND (EUR)",
            disabled=True,
            format="%.2f",
        ),
        "yf_eur": st.column_config.NumberColumn(
            "YF (EUR)",
            disabled=True,
            format="%.2f",
        ),
        "tb_eur": st.column_config.NumberColumn(
            "TB (EUR)",
            disabled=True,
            format="%.2f",
        ),
        "imbalance_eur": st.column_config.NumberColumn(
            "I'' (EUR)",
            disabled=True,
            format="%.2f",
        ),
        "bookmaker_count": st.column_config.NumberColumn(
            "Bookmakers",
            disabled=True,
        ),
        "last_activity": st.column_config.TextColumn(
            "Last Activity",
            disabled=True,
        ),
        "action": st.column_config.SelectboxColumn(
            "Action",
            options=[
                "",
                "Details",
                "Go to Overview",
                "View history",
            ],
            help="Choose a quick action per associate.",
        ),
    }

    edited_df = st.data_editor(
        df,
        key=ASSOC_EDITOR_KEY,
        column_config=column_config,
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        use_container_width=True,
    )
    raw_state = st.session_state.get(ASSOC_EDITOR_KEY)
    try:
        state = dict(raw_state) if raw_state is not None else None
    except TypeError:
        state = raw_state
    _handle_associate_actions(state, edited_df, associate_lookup)

    stored_selection = st.session_state.get(SELECTED_IDS_KEY, [])
    selected_ids = get_selected_row_ids(state, edited_df)
    if not selected_ids and not state:
        selected_ids = stored_selection
    selected_ids = _render_selection_picker(edited_df, selected_ids)
    st.session_state[SELECTED_IDS_KEY] = selected_ids

    if _editor_has_changes(state):
        if st.button(
            ":material/save: Save Associate Changes",
            type="primary",
            use_container_width=True,
        ):
            _persist_associate_changes(repository, df, edited_df, state)
    else:
        st.button(
            ":material/save: Save Associate Changes",
            type="primary",
            use_container_width=True,
            disabled=True,
        )

    return selected_ids, associate_lookup


def _render_bookmaker_table(
    repository: AssociateHubRepository,
    selected_ids: Sequence[int],
    associate_lookup: Dict[int, str],
) -> None:
    """Render bookmaker management table."""
    scope = st.radio(
        "Bookmaker scope",
        options=("Selected associate(s)", "All"),
        key=BOOKMAKER_SCOPE_KEY,
        horizontal=True,
    )

    if scope == "Selected associate(s)" and not selected_ids:
        st.info("Select at least one associate above to manage bookmakers.")
        return

    target_associate_ids = (
        selected_ids if scope == "Selected associate(s)" else associate_lookup.keys()
    )
    summaries: List[BookmakerSummary] = []
    for assoc_id in target_associate_ids:
        try:
            summaries.extend(repository.list_bookmakers_for_associate(assoc_id))
        except Exception as exc:
            st.error(f"Failed to load bookmakers for associate {assoc_id}: {exc}")
            return

    df, metadata = _build_bookmaker_dataframe(summaries)
    if not df.empty:
        def _alias(row: pd.Series) -> str:
            alias = (row.get("associate_alias") or "").strip()
            if alias:
                return alias
            assoc_id = row.get("associate_id")
            try:
                assoc_id = int(assoc_id)
            except (TypeError, ValueError):
                return ""
            return associate_lookup.get(assoc_id, "")

        df["associate_alias"] = df.apply(_alias, axis=1)

        if "active_balance_native" in df.columns:
            df["active_balance_native"] = df["active_balance_native"].fillna(df["active_balance_eur"])
        if "pending_balance_native" in df.columns:
            df["pending_balance_native"] = df["pending_balance_native"].fillna(df["pending_balance_eur"])

    column_config = {
        "associate_id": st.column_config.NumberColumn(
            "Associate ID",
            help="Enter the numeric ID; search list above for the alias.",
        ),
        "associate_alias": st.column_config.TextColumn(
            "Associate",
            disabled=True,
            help="Alias of the currently linked associate.",
        ),
        "bookmaker_name": st.column_config.TextColumn("Bookmaker"),
        "account_currency": st.column_config.SelectboxColumn(
            "Currency",
            options=VALID_CURRENCIES,
        ),
        "is_active": st.column_config.CheckboxColumn("Active"),
        "parsing_profile": st.column_config.TextColumn(
            "Parsing Profile",
            help="JSON profile for OCR/parsing.",
        ),
        "bookmaker_chat_id": st.column_config.TextColumn(
            "Bookmaker Chat",
            help="Telegram chat for statements/pings.",
        ),
        "coverage_chat_id": st.column_config.TextColumn(
            "Coverage Chat",
            help="Coverage/multibook chat destination.",
        ),
        "region": st.column_config.TextColumn("Region"),
        "risk_level": st.column_config.TextColumn("Risk"),
        "internal_notes": st.column_config.TextColumn("Internal notes"),
        "active_balance_native": st.column_config.NumberColumn(
            "Active Balance (Native)",
            disabled=True,
            format="%.2f",
            help="Latest reported balance in the bookmaker's native currency.",
        ),
        "pending_balance_native": st.column_config.NumberColumn(
            "Pending (Native)",
            disabled=True,
            format="%.2f",
            help="Pending exposure converted to the native currency.",
        ),
        "active_balance_eur": st.column_config.NumberColumn(
            "Active Balance (EUR)",
            disabled=True,
            format="%.2f",
        ),
        "pending_balance_eur": st.column_config.NumberColumn(
            "Pending (EUR)",
            disabled=True,
            format="%.2f",
        ),
        "last_balance_check": st.column_config.TextColumn(
            "Last balance check",
            disabled=True,
        ),
    }

    edited_df = st.data_editor(
        df,
        key=BOOKMAKER_EDITOR_KEY,
        column_config=column_config,
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        use_container_width=True,
    )
    state = st.session_state.get(BOOKMAKER_EDITOR_KEY)

    if _editor_has_changes(state):
        if st.button(
            ":material/save: Save Bookmaker Changes",
            type="primary",
            use_container_width=True,
        ):
            _persist_bookmaker_changes(
                repository,
                df,
                edited_df,
                state,
                metadata=metadata,
                associate_lookup=associate_lookup,
            )
    else:
        st.button(
            ":material/save: Save Bookmaker Changes",
            type="primary",
            use_container_width=True,
            disabled=True,
        )


def _render_management_tab(
    repository: AssociateHubRepository,
) -> None:
    """Render the Management tab contents."""
    st.title(":material/diversity_3: Associates Hub")
    st.caption(
        "Configure associates and bookmakers with inline editing. "
        "Money movements remain on the Overview/History tabs."
    )
    filter_state, should_refresh = render_filters(repository)
    if should_refresh:
        safe_rerun("associates_filters_refresh")
        return

    selected_ids, _visible_lookup = _render_associate_table(
        repository, filter_state
    )
    st.divider()

    full_associates = repository.list_associates_with_metrics(limit=500)
    associate_lookup = {
        metric.associate_id: metric.associate_alias for metric in full_associates
    }
    st.subheader("Bookmaker Management")
    _render_bookmaker_table(repository, selected_ids, associate_lookup)


def _render_overview_placeholder() -> None:
    st.title("Overview")
    st.info(
        "Overview tab is coming in Story 13.2. Use Management actions to "
        "pre-select an associate for deep links."
    )


def _render_history_placeholder() -> None:
    st.title("Balance History")
    st.info(
        "Balance History will arrive in Story 13.3. The selected associate "
        "state is preserved for future charts and exports."
    )


def main() -> None:
    _configure_page()
    load_global_styles()

    try:
        repository = AssociateHubRepository()
        funding_service = FundingTransactionService()
        balance_service = BookmakerBalanceService()
    except Exception as exc:
        st.error(f"Failed to initialise services: {exc}")
        return

    desired_tab = st.session_state.pop(PENDING_TAB_KEY, None)
    _handle_pending_bookmaker_confirmation(repository)

    tab_labels = ["Management", "Overview", "Balance History"]
    if desired_tab is not None:
        requested = tab_labels[min(max(desired_tab, 0), len(tab_labels) - 1)]
        st.toast(f"{requested} tab requested; please click the tab above.")
    tabs = st.tabs(tab_labels)

    with tabs[MANAGEMENT_TAB_INDEX]:
        _render_management_tab(repository)

    with tabs[OVERVIEW_TAB_INDEX]:
        _render_overview_placeholder()

    with tabs[HISTORY_TAB_INDEX]:
        _render_history_placeholder()

    render_detail_drawer(repository, funding_service, balance_service)


if __name__ == "__main__":
    main()
