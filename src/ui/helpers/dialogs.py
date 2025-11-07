from src.ui.utils.state_management import safe_rerun
﻿"""
Reusable dialog and action menu helpers with Streamlit feature fallbacks.

These helpers ensure consistent styling for confirmation flows and compact
action menus while gracefully degrading when the runtime lacks newer APIs
(`st.dialog`, `st.popover`, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

import streamlit as st

from src.ui.utils import feature_flags


class _InteractionState:
    """State manager for dialog/popover interactions."""

    def __init__(self, base_key: str) -> None:
        self.base_key = base_key

    @property
    def _open_key(self) -> str:
        return f"{self.base_key}__open"

    @property
    def _payload_key(self) -> str:
        return f"{self.base_key}__payload"

    def open(self) -> None:
        st.session_state[self._open_key] = True

    def close(self) -> None:
        st.session_state.pop(self._open_key, None)

    def is_open(self) -> bool:
        return bool(st.session_state.get(self._open_key))

    def push_payload(self, payload: Any) -> None:
        st.session_state[self._payload_key] = payload

    def pop_payload(self) -> Any:
        return st.session_state.pop(self._payload_key, None)


def open_dialog(key: str) -> None:
    """Mark a dialog identified by ``key`` as open for the next render pass."""
    _InteractionState(key).open()


def close_dialog(key: str) -> None:
    """Mark a dialog identified by ``key`` as closed."""
    _InteractionState(key).close()


def render_settlement_confirmation(
    *,
    key: str,
    button_label: str = "âœ… Confirm Settlement",
    title: str = "Confirm Settlement",
    warning_text: str = "This action is PERMANENT and will post ledger entries.",
    note_label: Optional[str] = "Optional note for audit trail",
) -> Optional[str]:
    """
    Render the settlement confirmation trigger and dialog.

    Returns the confirmation note (may be empty string) when the user confirms.
    """
    state = _InteractionState(key)
    confirmed_note = state.pop_payload()
    if confirmed_note is not None:
        return confirmed_note

    if st.button(
        button_label,
        key=f"{key}__open_button",
        type="primary",
        width="stretch",
    ):
        state.open()

    if not state.is_open():
        return None

    if feature_flags.supports_dialogs():
        _render_settlement_dialog_modal(
            state=state,
            key=key,
            title=title,
            warning_text=warning_text,
            note_label=note_label,
        )
    else:
        _render_settlement_dialog_fallback(
            state=state,
            key=key,
            title=title,
            warning_text=warning_text,
            note_label=note_label,
        )

    return None


def _render_settlement_dialog_modal(
    *,
    state: _InteractionState,
    key: str,
    title: str,
    warning_text: str,
    note_label: Optional[str],
) -> None:
    @st.dialog(title)
    def _modal() -> None:
        st.warning(warning_text)
        note_value = ""
        if note_label:
            note_value = st.text_area(
                note_label,
                key=f"{key}__note",
                placeholder="Optional operator note (visible in audit logs)",
            )

        confirm_col, cancel_col = st.columns([2, 1])
        with confirm_col:
            if st.button(
                "Confirm Settlement",
                key=f"{key}__confirm",
                type="primary",
                width="stretch",
            ):
                state.push_payload(note_value.strip())
                state.close()
                safe_rerun()
        with cancel_col:
            if st.button(
                "Cancel",
                key=f"{key}__cancel",
                width="stretch",
            ):
                state.close()
                safe_rerun()

    _modal()


def _render_settlement_dialog_fallback(
    *,
    state: _InteractionState,
    key: str,
    title: str,
    warning_text: str,
    note_label: Optional[str],
) -> None:
    with st.container(border=True):
        st.markdown(f"### {title}")
        st.warning(warning_text)
        note_value = ""
        if note_label:
            note_value = st.text_area(
                note_label,
                key=f"{key}__note",
                placeholder="Optional operator note (visible in audit logs)",
            )

        confirm_col, cancel_col = st.columns([2, 1])
        with confirm_col:
            if st.button(
                "Confirm Settlement",
                key=f"{key}__confirm",
                type="primary",
                width="stretch",
            ):
                state.push_payload(note_value.strip())
                state.close()
                safe_rerun()
        with cancel_col:
            if st.button(
                "Cancel",
                key=f"{key}__cancel",
                width="stretch",
            ):
                state.close()
                safe_rerun()


def render_confirmation_dialog(
    *,
    key: str,
    title: str,
    body: str,
    confirm_label: str = "Confirm",
    cancel_label: str = "Cancel",
    confirm_type: str = "primary",
) -> Optional[bool]:
    """
    Render a generic confirmation dialog.

    Returns True when confirmed, False when cancelled, and None while pending.
    """
    state = _InteractionState(key)
    outcome = state.pop_payload()
    if outcome is not None:
        return bool(outcome)

    if not state.is_open():
        return None

    renderer = (
        _render_confirmation_modal
        if feature_flags.supports_dialogs()
        else _render_confirmation_fallback
    )
    renderer(
        state=state,
        key=key,
        title=title,
        body=body,
        confirm_label=confirm_label,
        cancel_label=cancel_label,
        confirm_type=confirm_type,
    )
    return None


def _render_confirmation_modal(
    *,
    state: _InteractionState,
    key: str,
    title: str,
    body: str,
    confirm_label: str,
    cancel_label: str,
    confirm_type: str,
) -> None:
    @st.dialog(title)
    def _modal() -> None:
        st.warning(body)
        confirm_col, cancel_col = st.columns([2, 1])
        with confirm_col:
            if st.button(
                confirm_label,
                key=f"{key}__confirm",
                type=confirm_type,
                width="stretch",
            ):
                state.push_payload(True)
                state.close()
                safe_rerun()
        with cancel_col:
            if st.button(
                cancel_label,
                key=f"{key}__cancel",
                width="stretch",
            ):
                state.push_payload(False)
                state.close()
                safe_rerun()

    _modal()


def _render_confirmation_fallback(
    *,
    state: _InteractionState,
    key: str,
    title: str,
    body: str,
    confirm_label: str,
    cancel_label: str,
    confirm_type: str,
) -> None:
    with st.container(border=True):
        st.markdown(f"### {title}")
        st.warning(body)
        confirm_col, cancel_col = st.columns([2, 1])
        with confirm_col:
            if st.button(
                confirm_label,
                key=f"{key}__confirm",
                type=confirm_type,
                width="stretch",
            ):
                state.push_payload(True)
                state.close()
                safe_rerun()
        with cancel_col:
            if st.button(
                cancel_label,
                key=f"{key}__cancel",
                width="stretch",
            ):
                state.push_payload(False)
                state.close()
                safe_rerun()


def render_canonical_event_dialog(
    *,
    key: str,
    bet: Dict[str, Any],
    sport_options: Optional[Iterable[str]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Render the canonical event creation dialog and return payload on submit.
    """
    state = _InteractionState(key)
    payload = state.pop_payload()
    if payload is not None:
        return payload

    if not state.is_open():
        return None

    options = list(sport_options or ["football", "tennis", "basketball", "cricket", "rugby"])

    renderer = (
        _render_canonical_event_modal
        if feature_flags.supports_dialogs()
        else _render_canonical_event_fallback
    )
    renderer(state=state, key=key, bet=bet, sport_options=options)
    return None


def _render_canonical_event_modal(
    *,
    state: _InteractionState,
    key: str,
    bet: Dict[str, Any],
    sport_options: List[str],
) -> None:
    @st.dialog("Create New Event")
    def _modal() -> None:
        _canonical_event_form(state=state, key=key, bet=bet, sport_options=sport_options)

    _modal()


def _render_canonical_event_fallback(
    *,
    state: _InteractionState,
    key: str,
    bet: Dict[str, Any],
    sport_options: List[str],
) -> None:
    with st.container(border=True):
        st.markdown("### Create New Event")
        _canonical_event_form(state=state, key=key, bet=bet, sport_options=sport_options)


def _canonical_event_form(
    *,
    state: _InteractionState,
    key: str,
    bet: Dict[str, Any],
    sport_options: List[str],
) -> None:
    default_event_name = bet.get("selection_text", "")
    default_kickoff = bet.get("kickoff_time_utc", "")

    event_name = st.text_input(
        "Event Name *",
        value=default_event_name,
        placeholder="e.g., Manchester United vs Liverpool",
        help="Minimum 5 characters required",
        key=f"{key}__event_name",
    )
    sport = st.selectbox(
        "Sport *",
        options=sport_options,
        index=0,
        key=f"{key}__sport",
    )
    competition = st.text_input(
        "Competition / League (optional)",
        value="",
        placeholder="e.g., Premier League, ATP Masters",
        help="Maximum 100 characters",
        key=f"{key}__competition",
    )
    kickoff_time = st.text_input(
        "Kickoff Time (UTC) *",
        value=default_kickoff,
        placeholder="YYYY-MM-DDTHH:MM:SSZ",
        help="ISO8601 format with Z suffix required",
        key=f"{key}__kickoff",
    )

    st.caption("* Required fields")

    cols = st.columns([2, 1])
    with cols[0]:
        if st.button(
            "Create Event",
            key=f"{key}__submit",
            type="primary",
            width="stretch",
        ):
            errors = _validate_canonical_event_inputs(
                event_name=event_name,
                competition=competition,
                kickoff_time=kickoff_time,
            )
            if errors:
                for error in errors:
                    st.error(error)
                return

            payload = {
                "event_name": event_name.strip(),
                "sport": sport,
                "competition": competition.strip() or None,
                "kickoff_time_utc": kickoff_time.strip(),
            }
            state.push_payload(payload)
            state.close()
            safe_rerun()

    with cols[1]:
        if st.button(
            "Cancel",
            key=f"{key}__cancel",
            width="stretch",
        ):
            state.close()
            safe_rerun()


def _validate_canonical_event_inputs(
    *,
    event_name: str,
    competition: str,
    kickoff_time: str,
) -> List[str]:
    errors: List[str] = []

    if not event_name or len(event_name.strip()) < 5:
        errors.append("Event name must be at least 5 characters long.")

    if competition and len(competition.strip()) > 100:
        errors.append("Competition name must not exceed 100 characters.")

    kickoff_value = kickoff_time.strip()
    if not kickoff_value:
        errors.append("Kickoff time is required.")
    elif not kickoff_value.endswith("Z"):
        errors.append("Kickoff time must end with 'Z' (UTC timezone).")
    else:
        try:
            datetime.fromisoformat(kickoff_value.replace("Z", "+00:00"))
        except ValueError:
            errors.append("Invalid kickoff time format. Use YYYY-MM-DDTHH:MM:SSZ.")

    return errors


def render_correction_dialog(
    *,
    key: str,
    defaults: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Render correction dialog and return payload when submitted.
    """
    state = _InteractionState(key)
    payload = state.pop_payload()
    if payload is not None:
        return payload

    if not state.is_open():
        return None

    renderer = (
        _render_correction_modal
        if feature_flags.supports_dialogs()
        else _render_correction_fallback
    )
    renderer(state=state, key=key, defaults=defaults)
    return None


def _render_correction_modal(
    *,
    state: _InteractionState,
    key: str,
    defaults: Dict[str, Any],
) -> None:
    title = f"Apply Correction Â· {defaults.get('bookmaker_name', 'Bookmaker')}"

    @st.dialog(title)
    def _modal() -> None:
        _correction_form(state=state, key=key, defaults=defaults)

    _modal()


def _render_correction_fallback(
    *,
    state: _InteractionState,
    key: str,
    defaults: Dict[str, Any],
) -> None:
    st.markdown(
        f"### Apply Correction Â· {defaults.get('bookmaker_name', 'Bookmaker')}",
    )
    _correction_form(state=state, key=key, defaults=defaults)


def _correction_form(
    *,
    state: _InteractionState,
    key: str,
    defaults: Dict[str, Any],
) -> None:
    associate_alias = defaults.get("associate_alias", "Associate")
    bookmaker_name = defaults.get("bookmaker_name", "Bookmaker")
    amount_eur = defaults.get("amount_eur")
    amount_native = defaults.get("amount_native")
    native_currency = defaults.get("native_currency", "EUR")

    st.warning(
        f"This will post a correction entry for **{associate_alias} Â· {bookmaker_name}**."
    )
    st.caption(
        "Positive amounts increase bookmaker holdings; negative amounts decrease holdings."
    )

    amount_placeholder = amount_native or ""
    amount_value = st.text_input(
        "Correction Amount (native currency) *",
        value=str(amount_placeholder),
        key=f"{key}__amount_native",
        placeholder="e.g., +100.50 or -25.00",
    )
    currency = st.text_input(
        "Currency *",
        value=native_currency,
        key=f"{key}__currency",
        help="ISO currency code",
    )
    note_value = st.text_area(
        "Required note *",
        value=defaults.get("note", ""),
        key=f"{key}__note",
        placeholder="Provide context for the correction",
        max_chars=500,
    )

    st.caption(f"Modeled mismatch: {amount_eur} EUR")

    cols = st.columns([2, 1])
    with cols[0]:
        if st.button(
            "Apply Correction",
            key=f"{key}__apply",
            type="primary",
            width="stretch",
        ):
            payload = _validate_correction_inputs(
                amount_value=amount_value,
                currency=currency,
                note=note_value,
            )
            if payload["errors"]:
                for error in payload["errors"]:
                    st.error(error)
                return

            result = {
                "amount_native": payload["amount_native"],
                "native_currency": payload["currency"],
                "note": payload["note"],
            }
            state.push_payload(result)
            state.close()
            safe_rerun()

    with cols[1]:
        if st.button(
            "Cancel",
            key=f"{key}__cancel",
            width="stretch",
        ):
            state.close()
            safe_rerun()


def _validate_correction_inputs(
    *,
    amount_value: str,
    currency: str,
    note: str,
) -> Dict[str, Any]:
    from decimal import Decimal, InvalidOperation

    errors: List[str] = []
    amount_native = None

    value = (amount_value or "").strip()
    if not value:
        errors.append("Correction amount is required.")
    else:
        try:
            amount_native = Decimal(value.replace("+", ""))
        except (InvalidOperation, ValueError):
            errors.append("Correction amount must be a valid decimal number.")

    currency_value = (currency or "").strip().upper()
    if not currency_value:
        errors.append("Currency is required.")

    note_value = (note or "").strip()
    if not note_value:
        errors.append("A note is required for audit purposes.")

    return {
        "errors": errors,
        "amount_native": amount_native,
        "currency": currency_value,
        "note": note_value,
    }


@dataclass(frozen=True)
class ActionItem:
    """Definition for an action rendered inside a popover."""

    key: str
    label: str
    icon: Optional[str] = None
    description: Optional[str] = None
    button_type: str = "secondary"
    disabled: bool = False


def render_action_menu(
    *,
    key: str,
    label: str = "Actions",
    actions: Iterable[ActionItem],
) -> Optional[str]:
    """
    Render a compact action menu and return the triggered action key.
    """
    state = _InteractionState(key)
    triggered = state.pop_payload()
    if triggered is not None:
        return triggered

    actions = list(actions)
    button_labels = [
        f"{item.icon} {item.label}" if item.icon else item.label for item in actions
    ]

    supports_popovers = getattr(feature_flags, "supports_popovers", None)
    supports_popovers = supports_popovers if callable(supports_popovers) else (lambda: False)

    if supports_popovers():
        with st.popover(label, width="stretch"):
            for item, display in zip(actions, button_labels):
                if st.button(
                    display,
                    key=f"{key}__action_{item.key}",
                    type=item.button_type,
                    disabled=item.disabled,
                    width="stretch",
                    help=item.description,
                ):
                    state.push_payload(item.key)
                    safe_rerun()
    else:
        st.caption(label)
        for item, display in zip(actions, button_labels):
            if st.button(
                display,
                key=f"{key}__action_{item.key}",
                type=item.button_type,
                disabled=item.disabled,
                help=item.description,
                width="stretch",
            ):
                state.push_payload(item.key)
                safe_rerun()

    return None


__all__ = [
    "ActionItem",
    "close_dialog",
    "open_dialog",
    "render_action_menu",
    "render_canonical_event_dialog",
    "render_confirmation_dialog",
    "render_correction_dialog",
    "render_settlement_confirmation",
]