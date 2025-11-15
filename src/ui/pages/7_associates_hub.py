"""
Associates Hub page - Management tab (Story 13.1).

Renders a new Streamlit page with a Management-first experience that combines
associate configuration, inline editing, derived metrics, and bookmaker
management with confirmation prompts for sensitive operations.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd
import streamlit as st

from src.repositories.associate_hub_repository import (
    AssociateHubRepository,
    AssociateMetrics,
    BookmakerSummary,
)
from src.services.bookmaker_balance_service import BookmakerBalanceService
from src.services.funding_transaction_service import (
    FundingTransaction,
    FundingTransactionError,
    FundingTransactionService,
)
from src.ui.components.associate_hub.drawer import render_detail_drawer
from src.ui.components.associate_hub.filters import render_filters
from src.ui.components.associate_hub.listing import QuickAction, render_associate_listing, render_empty_state, render_hub_dashboard
from src.ui.helpers.dialogs import open_dialog, render_confirmation_dialog
from src.ui.helpers.editor import (
    extract_editor_changes,
    get_selected_row_ids,
)
from src.ui.ui_components import load_global_styles
from src.ui.utils.state_management import safe_rerun
from src.ui.utils.validators import VALID_CURRENCIES
from src.ui.helpers.dialogs import close_dialog


PENDING_TAB_KEY = "associates_hub_pending_tab"
ACTIVE_TAB_KEY = "associates_hub_active_tab"
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


def _queue_tab_switch(tab_index: int, message: str) -> None:
    """Persist a tab switch request so it executes on the next render."""
    st.session_state[ACTIVE_TAB_KEY] = tab_index
    st.session_state[PENDING_TAB_KEY] = {
        "tab": tab_index,
        "message": message,
    }


def _list_associates_with_metrics(repository: AssociateHubRepository, **kwargs: Any) -> List[AssociateMetrics]:
    """
    Call repository.list_associates_with_metrics with backward compatibility.

    Older deployments may not yet accept the new `risk_filter` argument, so we
    fall back to removing it if Python raises the corresponding TypeError.
    """
    try:
        return repository.list_associates_with_metrics(**kwargs)
    except TypeError as exc:
        if "risk_filter" in str(exc) and "risk_filter" in kwargs:
            trimmed = dict(kwargs)
            trimmed.pop("risk_filter", None)
            return repository.list_associates_with_metrics(**trimmed)
        raise

OVERVIEW_FUNDING_DIALOG_KEY = "associates_overview_funding_dialog"
OVERVIEW_DIALOG_PAYLOAD_KEY = f"{OVERVIEW_FUNDING_DIALOG_KEY}__payload"
METRIC_OVERRIDE_KEY = "associates_hub_metric_overrides"


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


class FundingDialogValidationError(Exception):
    """Raised when overview funding dialog validation fails."""


def _resolve_operator_identity() -> str:
    """Return the best operator identifier available for created_by fields."""
    candidate_keys = (
        "operator_name",
        "operator_email",
        "user_email",
        "user_display_name",
    )
    for key in candidate_keys:
        value = st.session_state.get(key)
        if value:
            return str(value)
    return "local_user"


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


def _apply_metric_overrides(
    associates: List[AssociateMetrics],
) -> List[AssociateMetrics]:
    """Merge any cached overrides created after funding operations."""
    overrides: Dict[int, AssociateMetrics] = st.session_state.get(
        METRIC_OVERRIDE_KEY, {}
    )
    if not overrides:
        return associates
    merged: List[AssociateMetrics] = []
    for metric in associates:
        merged.append(overrides.get(metric.associate_id, metric))
    return merged


def _store_metric_override(metric: AssociateMetrics) -> None:
    """Persist the freshest metrics for an associate for subsequent renders."""
    overrides: Dict[int, AssociateMetrics] = st.session_state.setdefault(
        METRIC_OVERRIDE_KEY, {}
    )
    overrides[metric.associate_id] = metric


def _launch_overview_funding_dialog(
    associate: AssociateMetrics,
    action: str,
) -> None:
    """Open the funding dialog prefilled for the given associate."""
    st.session_state[SELECTED_ASSOCIATE_KEY] = associate.associate_id
    st.session_state[OVERVIEW_DIALOG_PAYLOAD_KEY] = {
        "associate_id": associate.associate_id,
        "associate_alias": associate.associate_alias,
        "home_currency": associate.home_currency or "EUR",
        "action": action.lower(),
    }
    open_dialog(OVERVIEW_FUNDING_DIALOG_KEY)
    safe_rerun("overview_funding_launch")


def submit_overview_funding_transaction(
    *,
    funding_service: FundingTransactionService,
    repository: AssociateHubRepository,
    associate_id: int,
    action: str,
    amount_value: str,
    currency_value: str,
    bookmaker_id: Optional[int],
    note_value: str,
    operator_name: Optional[str] = None,
) -> Tuple[str, AssociateMetrics]:
    """
    Validate and submit a funding transaction coming from the Overview tab.
    """
    amount_text = (amount_value or "").strip()
    if not amount_text:
        raise FundingDialogValidationError("Amount is required.")
    try:
        amount = Decimal(amount_text)
    except (InvalidOperation, ValueError) as exc:  # pragma: no cover - safety
        raise FundingDialogValidationError("Amount must be a valid decimal.") from exc
    if amount <= 0:
        raise FundingDialogValidationError("Amount must be positive.")

    currency = (currency_value or "").strip().upper()
    if not currency:
        raise FundingDialogValidationError("Currency is required.")
    if currency not in VALID_CURRENCIES:
        raise FundingDialogValidationError(
            f"{currency} is not a supported currency."
        )

    direction = action.strip().upper()
    if direction not in {"DEPOSIT", "WITHDRAW"}:
        raise FundingDialogValidationError("Unsupported funding direction.")

    note = (note_value or "").strip() or None
    transaction = FundingTransaction(
        associate_id=associate_id,
        bookmaker_id=bookmaker_id,
        transaction_type=direction,
        amount_native=amount,
        native_currency=currency,
        note=note,
        created_by=operator_name or _resolve_operator_identity(),
    )
    ledger_id = funding_service.record_transaction(transaction)
    metrics = repository.get_associate_metrics(associate_id)
    if metrics is None:
        raise FundingDialogValidationError(
            "Could not refresh associate metrics after posting the transaction."
        )
    return str(ledger_id), metrics


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
            _queue_tab_switch(OVERVIEW_TAB_INDEX, f"{alias} opened in the Overview tab.")
            safe_rerun("associate_overview_jump")
        elif action == "View history":
            _queue_tab_switch(HISTORY_TAB_INDEX, f"{alias} opened in Balance History.")
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
    associates = _list_associates_with_metrics(
        repository,
        search=filter_state.get("search"),
        admin_filter=filter_state.get("admin_filter"),
        associate_status_filter=filter_state.get("associate_status_filter"),
        bookmaker_status_filter=filter_state.get("bookmaker_status_filter"),
        risk_filter=filter_state.get("risk_filter"),
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


def _open_overview_drawer(associate_id: int, tab: str = "profile") -> None:
    """Open the shared associate drawer from the Overview tab."""
    st.session_state["hub_drawer_open"] = True
    st.session_state["hub_drawer_associate_id"] = associate_id
    st.session_state.pop("hub_drawer_bookmaker_id", None)
    st.session_state["hub_drawer_tab"] = tab
    safe_rerun("overview_drawer_open")


def _overview_funding_callback(action: str) -> Callable[[AssociateMetrics], None]:
    """Return a QuickAction callback that launches the funding dialog."""

    def _callback(associate: AssociateMetrics) -> None:
        _launch_overview_funding_dialog(associate, action)

    return _callback


def _build_overview_quick_actions() -> Sequence[QuickAction]:
    """Quick actions for the Overview tab cards."""

    def _details_callback(associate: AssociateMetrics) -> None:
        st.session_state[SELECTED_ASSOCIATE_KEY] = associate.associate_id
        _open_overview_drawer(associate.associate_id, tab="profile")

    def _go_to_management(associate: AssociateMetrics) -> None:
        st.session_state[SELECTED_ASSOCIATE_KEY] = associate.associate_id
        _queue_tab_switch(
            MANAGEMENT_TAB_INDEX,
            f"{associate.associate_alias} opened in the Management tab.",
        )
        safe_rerun("overview_go_to_management")

    return (
        QuickAction(
            key_prefix="overview_deposit",
            label="Deposit",
            icon=":material/savings:",
            help_text="Record a deposit for this associate",
            callback=_overview_funding_callback("deposit"),
            button_type="primary",
        ),
        QuickAction(
            key_prefix="overview_withdraw",
            label="Withdraw",
            icon=":material/payments:",
            help_text="Record a withdrawal for this associate",
            callback=_overview_funding_callback("withdraw"),
            button_type="secondary",
        ),
        QuickAction(
            key_prefix="overview_details",
            label="Details",
            icon=":material/visibility:",
            help_text="Open the shared associate drawer",
            callback=_details_callback,
        ),
        QuickAction(
            key_prefix="overview_management",
            label="Go to Management",
            icon=":material/switch_access_shortcut:",
            help_text="Jump to the Management tab with this associate highlighted",
            callback=_go_to_management,
        ),
    )


def _close_overview_funding_dialog() -> None:
    """Clear dialog state after submission or cancel."""
    close_dialog(OVERVIEW_FUNDING_DIALOG_KEY)
    st.session_state.pop(OVERVIEW_DIALOG_PAYLOAD_KEY, None)
    for key in (
        "overview_funding_amount",
        "overview_funding_currency",
        "overview_funding_bookmaker",
        "overview_funding_note",
    ):
        st.session_state.pop(key, None)


def _render_overview_funding_dialog(
    repository: AssociateHubRepository,
    funding_service: FundingTransactionService,
) -> None:
    """Render the funding dialog when triggered from Overview quick actions."""
    payload = st.session_state.get(OVERVIEW_DIALOG_PAYLOAD_KEY)
    dialog_open = st.session_state.get(f"{OVERVIEW_FUNDING_DIALOG_KEY}__open")
    if payload and not dialog_open:
        st.session_state.pop(OVERVIEW_DIALOG_PAYLOAD_KEY, None)
        payload = None
    if not payload:
        return
    if not dialog_open:
        return

    associate_id = payload.get("associate_id")
    if not associate_id:
        st.error("Associate context missing for funding dialog.")
        _close_overview_funding_dialog()
        return

    action = (payload.get("action") or "deposit").lower()
    action_label = "Deposit" if action == "deposit" else "Withdrawal"
    alias = payload.get("associate_alias", "Associate")
    default_currency = (payload.get("home_currency") or "EUR").upper()

    try:
        bookmaker_summaries = repository.list_bookmakers_for_associate(associate_id)
    except Exception as exc:
        bookmaker_summaries = []
        st.warning(f"Failed to load bookmaker options: {exc}")

    bookmaker_options: List[Optional[int]] = [None]
    bookmaker_labels: Dict[Optional[int], str] = {None: "Associate-level"}
    for summary in bookmaker_summaries:
        bookmaker_options.append(summary.bookmaker_id)
        bookmaker_labels[summary.bookmaker_id] = summary.bookmaker_name

    def _render_form() -> None:
        st.markdown(f"### {action_label} – {alias}")
        st.caption("Amounts validate in native currency; submissions update ND/TB/I'' immediately.")
        with st.form("overview_funding_form"):
            amount_value = st.text_input(
                f"{action_label} Amount*",
                key="overview_funding_amount",
                placeholder="500.00",
            )
            currency_index = (
                VALID_CURRENCIES.index(default_currency)
                if default_currency in VALID_CURRENCIES
                else 0
            )
            currency_value = st.selectbox(
                "Currency*",
                options=VALID_CURRENCIES,
                index=currency_index,
                key="overview_funding_currency",
            )
            bookmaker_value = st.selectbox(
                "Bookmaker (optional)",
                options=bookmaker_options,
                format_func=lambda value: bookmaker_labels.get(value, "Associate-level"),
                key="overview_funding_bookmaker",
            )
            note_value = st.text_area(
                "Note",
                key="overview_funding_note",
                placeholder="Optional audit note",
                height=80,
            )
            submitted = st.form_submit_button(
                f"Record {action_label}",
                type="primary",
                use_container_width=True,
            )

        if submitted:
            try:
                ledger_id, metrics = submit_overview_funding_transaction(
                    funding_service=funding_service,
                    repository=repository,
                    associate_id=associate_id,
                    action=action,
                    amount_value=amount_value,
                    currency_value=currency_value,
                    bookmaker_id=bookmaker_value,
                    note_value=note_value,
                    operator_name=_resolve_operator_identity(),
                )
            except FundingDialogValidationError as exc:
                st.error(str(exc))
                return
            except FundingTransactionError as exc:
                st.error(f"Funding operation failed: {exc}")
                return

            st.success(f"{action_label} recorded successfully (Ledger #{ledger_id}).")
            st.toast(
                f"Ledger #{ledger_id} posted for {alias}.",
                icon=":material/check_circle:",
            )
            _store_metric_override(metrics)
            _close_overview_funding_dialog()
            safe_rerun("overview_funding_success")
            return

        if st.button(
            ":material/close: Cancel",
            key="overview_funding_cancel",
            type="secondary",
            use_container_width=True,
        ):
            _close_overview_funding_dialog()

    dialog_title = f"{action_label} – {alias}"
    supports_dialog = callable(getattr(st, "dialog", None))
    if supports_dialog:
        @st.dialog(dialog_title)
        def _modal() -> None:
            _render_form()

        _modal()
    else:
        with st.sidebar:
            st.markdown(f"## {dialog_title}")
            _render_form()


def _render_history_placeholder() -> None:
    st.title("Balance History")
    st.info(
        "Balance History will arrive in Story 13.3. The selected associate "
        "state is preserved for future charts and exports."
    )


def _render_overview_tab(
    repository: AssociateHubRepository,
    funding_service: FundingTransactionService,
) -> None:
    """Render the Overview tab with dashboard metrics and quick actions."""
    st.title(":material/dashboard: Overview")
    st.caption(
        "Monitor ND/YF/TB/I'' at a glance and launch read-only detail views or "
        "funding flows without leaving the hub."
    )

    filter_state, should_refresh = render_filters(
        repository,
        widget_suffix="_overview",
    )
    if should_refresh:
        safe_rerun("overview_filters_refresh")
        return

    _render_overview_funding_dialog(repository, funding_service)

    try:
        associates = _list_associates_with_metrics(
            repository,
            search=filter_state.get("search"),
            admin_filter=filter_state.get("admin_filter"),
            associate_status_filter=filter_state.get("associate_status_filter"),
            bookmaker_status_filter=filter_state.get("bookmaker_status_filter"),
            risk_filter=filter_state.get("risk_filter"),
            currency_filter=filter_state.get("currency_filter"),
            sort_by=filter_state.get("sort_by", "alias_asc"),
            limit=500,
        )
    except Exception as exc:
        st.error(f"Failed to load associates for Overview: {exc}")
        return

    associates = _apply_metric_overrides(associates)
    if not associates:
        render_empty_state(filter_state)
        return

    highlight_id = st.session_state.get(SELECTED_ASSOCIATE_KEY)
    render_hub_dashboard(associates)
    if highlight_id:
        st.caption(
            ":material/push_pin: Highlighting the associate selected from Management."
        )

    render_associate_listing(
        associates,
        quick_actions=_build_overview_quick_actions(),
        highlight_associate_id=highlight_id,
        show_bookmakers=False,
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

    pending_tab = st.session_state.pop(PENDING_TAB_KEY, None)
    _handle_pending_bookmaker_confirmation(repository)

    tab_labels = ["Management", "Overview", "Balance History"]
    active_tab_index = int(st.session_state.get(ACTIVE_TAB_KEY, MANAGEMENT_TAB_INDEX))
    toast_message: Optional[str] = None
    target_index: Optional[int] = None
    if isinstance(pending_tab, dict):
        target_index = pending_tab.get("tab")
        toast_message = pending_tab.get("message")
    elif pending_tab is not None:
        target_index = pending_tab

    if target_index is not None:
        try:
            normalized_index = int(target_index)
        except (TypeError, ValueError):
            normalized_index = MANAGEMENT_TAB_INDEX
        normalized_index = max(0, min(len(tab_labels) - 1, normalized_index))
        active_tab_index = normalized_index
        st.session_state[ACTIVE_TAB_KEY] = active_tab_index
        st.toast(
            toast_message or f"{tab_labels[active_tab_index]} tab opened.",
            icon=":material/check_circle:",
        )

    tab_choice = st.radio(
        "Associates Hub Tabs",
        tab_labels,
        index=active_tab_index,
        key="associates_hub_tab_selector",
        horizontal=True,
        label_visibility="collapsed",
    )
    selected_index = tab_labels.index(tab_choice)
    if selected_index != active_tab_index:
        active_tab_index = selected_index
        st.session_state[ACTIVE_TAB_KEY] = active_tab_index

    if active_tab_index == MANAGEMENT_TAB_INDEX:
        _render_management_tab(repository)
    elif active_tab_index == OVERVIEW_TAB_INDEX:
        _render_overview_tab(repository, funding_service)
    else:
        _render_history_placeholder()

    render_detail_drawer(repository, funding_service, balance_service)


if __name__ == "__main__":
    main()
