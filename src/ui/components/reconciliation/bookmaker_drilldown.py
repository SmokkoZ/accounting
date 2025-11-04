"""
Streamlit component for the bookmaker balance drilldown (Story 5.3).
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Callable, Iterable, List, Optional

import streamlit as st

from src.services.bookmaker_balance_service import BookmakerBalance
from src.ui.utils.formatters import format_currency_with_symbol
from src.ui.utils.validators import VALID_CURRENCIES, validate_balance_amount
from src.utils.datetime_helpers import parse_utc_iso


UpdateBalanceCallback = Callable[
    [int, int, Decimal, str, str, Optional[str]], None
]  # associate_id, bookmaker_id, amount_native, currency, check_date_utc, note
PrefillCorrectionCallback = Callable[[BookmakerBalance], None]


def render_bookmaker_drilldown(
    balances: List[BookmakerBalance],
    *,
    on_update_balance: UpdateBalanceCallback,
    on_prefill_correction: PrefillCorrectionCallback,
) -> None:
    """
    Render bookmaker drilldown UI with filtering, manual updates, and attribution.
    """
    st.subheader("Bookmaker Drilldown")
    st.caption("Compare modeled holdings to reported balances per bookmaker.")

    if not balances:
        st.info("No bookmaker data available yet. Add bookmakers or ledger entries to begin.")
        return

    mismatch_only = st.checkbox("Show only mismatches", key="bm_drilldown_mismatch")
    search_query = st.text_input(
        "Search by associate or bookmaker",
        key="bm_drilldown_search",
        placeholder="Type an associate or bookmaker name...",
    )
    sort_option = st.selectbox(
        "Sort by",
        options=[
            "Largest mismatch",
            "Most recent balance check",
            "Associate (A → Z)",
        ],
        index=0,
        key="bm_drilldown_sort",
    )

    filtered = _apply_filters(balances, mismatch_only, search_query)
    if not filtered:
        st.warning("No bookmaker balances match the selected filters.")
        return

    sorted_balances = _apply_sort(filtered, sort_option)
    grouped = _group_by_associate(sorted_balances)

    for associate_alias, associate_balances in grouped.items():
        total_delta = _sum_differences(associate_balances)
        header = f"{associate_alias}"
        if total_delta is not None:
            header += f" · Net Δ {format_currency_with_symbol(total_delta, 'EUR')}"

        with st.expander(header, expanded=False):
            for balance in associate_balances:
                _render_bookmaker_card(
                    balance, on_update_balance=on_update_balance, on_prefill=on_prefill_correction
                )


# --------------------------------------------------------------------------- #
# Filtering & grouping helpers
# --------------------------------------------------------------------------- #


def _apply_filters(
    balances: Iterable[BookmakerBalance], mismatch_only: bool, search_query: str
) -> List[BookmakerBalance]:
    results: List[BookmakerBalance] = []
    query = (search_query or "").strip().lower()

    for balance in balances:
        if mismatch_only and (balance.difference_eur is None or balance.difference_eur == 0):
            continue

        if query:
            haystacks = [
                balance.associate_alias.lower(),
                balance.bookmaker_name.lower(),
            ]
            if not any(query in haystack for haystack in haystacks):
                continue

        results.append(balance)

    return results


def _apply_sort(balances: List[BookmakerBalance], sort_option: str) -> List[BookmakerBalance]:
    if sort_option == "Most recent balance check":
        return sorted(
            balances,
            key=lambda b: (
                _parse_datetime_sort_key(b.last_checked_at_utc),
                b.associate_alias.lower(),
                b.bookmaker_name.lower(),
            ),
            reverse=True,
        )

    if sort_option == "Associate (A → Z)":
        return sorted(
            balances,
            key=lambda b: (b.associate_alias.lower(), b.bookmaker_name.lower()),
        )

    # Default: Largest mismatch by absolute EUR value
    return sorted(
        balances,
        key=lambda b: (abs(b.difference_eur or Decimal("0")), b.associate_alias.lower()),
        reverse=True,
    )


def _group_by_associate(
    balances: Iterable[BookmakerBalance],
) -> dict[str, List[BookmakerBalance]]:
    grouped: dict[str, List[BookmakerBalance]] = {}
    for balance in balances:
        grouped.setdefault(balance.associate_alias, []).append(balance)
    return grouped


def _parse_datetime_sort_key(value: Optional[str]) -> float:
    if not value:
        return 0.0
    try:
        dt = parse_utc_iso(value)
        return dt.timestamp()
    except Exception:
        return 0.0


def _sum_differences(balances: Iterable[BookmakerBalance]) -> Optional[Decimal]:
    deltas = [b.difference_eur for b in balances if b.difference_eur is not None]
    if not deltas:
        return None
    total = sum(deltas, Decimal("0"))
    return total.quantize(Decimal("0.01"))


# --------------------------------------------------------------------------- #
# Card rendering
# --------------------------------------------------------------------------- #


def _render_bookmaker_card(
    balance: BookmakerBalance,
    *,
    on_update_balance: UpdateBalanceCallback,
    on_prefill: PrefillCorrectionCallback,
) -> None:
    container = st.container()
    with container:
        header_cols = st.columns([4, 1])
        with header_cols[0]:
            subtitle = f"{balance.status_icon} {balance.bookmaker_name}"
            if not balance.is_bookmaker_active:
                subtitle += " · (inactive)"
            st.markdown(f"### {subtitle}")
            st.caption(balance.status_label)

        with header_cols[1]:
            if balance.difference_eur is not None and balance.difference_eur != 0:
                if st.button(
                    "Apply Correction",
                    key=f"prefill_{balance.associate_id}_{balance.bookmaker_id}",
                    type="secondary",
                ):
                    on_prefill(balance)
                    st.success("Correction form pre-filled. Open the Corrections page to review.")

        stat_cols = st.columns([2, 2, 2])
        with stat_cols[0]:
            st.metric(
                "Modeled Balance (EUR)",
                format_currency_with_symbol(balance.modeled_balance_eur, "EUR"),
            )
            if balance.modeled_balance_native is not None:
                st.caption(
                    f"≈ {format_currency_with_symbol(balance.modeled_balance_native, balance.native_currency)}"
                )

        with stat_cols[1]:
            reported_text = (
                format_currency_with_symbol(balance.reported_balance_eur, "EUR")
                if balance.reported_balance_eur is not None
                else "Not provided"
            )
            st.metric("Reported Balance (EUR)", reported_text)
            if balance.reported_balance_native is not None:
                st.caption(
                    f"{format_currency_with_symbol(balance.reported_balance_native, balance.native_currency)}"
                )

        with stat_cols[2]:
            diff_text = (
                format_currency_with_symbol(balance.difference_eur, "EUR")
                if balance.difference_eur is not None
                else "N/A"
            )
            st.metric("Difference (EUR)", diff_text)
            if balance.difference_native is not None:
                st.caption(
                    f"{format_currency_with_symbol(balance.difference_native, balance.native_currency)}"
                )

        badges_cols = st.columns([3, 2])
        with badges_cols[0]:
            _render_last_checked(balance.last_checked_at_utc)
            if balance.owed_to:
                st.markdown("**Float Attribution**")
                owed_lines = [
                    f"- {counterparty.associate_alias}: "
                    f"{format_currency_with_symbol(counterparty.amount_eur, 'EUR')}"
                    + (
                        f" ({format_currency_with_symbol(counterparty.amount_native, balance.native_currency)})"
                        if counterparty.amount_native is not None
                        else ""
                    )
                    for counterparty in balance.owed_to
                ]
                st.markdown("\n".join(owed_lines))

        with badges_cols[1]:
            _render_update_form(balance, on_update_balance)

        st.markdown("---")


def _render_last_checked(last_checked_iso: Optional[str]) -> None:
    if not last_checked_iso:
        st.info("No reported balance yet. Record a balance check to compare.")
        return

    try:
        last_dt = parse_utc_iso(last_checked_iso)
        delta = datetime.now(timezone.utc) - last_dt
        hours = delta.total_seconds() / 3600
        if hours < 1:
            message = "Last checked: < 1 hour ago"
        else:
            message = f"Last checked: {math.floor(hours)} hour(s) ago"
        st.caption(f"{message} ({last_checked_iso})")
    except Exception:
        st.caption(f"Last checked: {last_checked_iso}")


def _render_update_form(balance: BookmakerBalance, on_update_balance: UpdateBalanceCallback) -> None:
    default_amount = (
        str(balance.reported_balance_native)
        if balance.reported_balance_native is not None
        else ""
    )
    default_currency = (
        balance.native_currency if balance.native_currency in VALID_CURRENCIES else "EUR"
    )

    if balance.last_checked_at_utc:
        try:
            existing_dt = parse_utc_iso(balance.last_checked_at_utc)
        except Exception:
            existing_dt = datetime.now(timezone.utc)
    else:
        existing_dt = datetime.now(timezone.utc)

    form = st.form(f"update_balance_form_{balance.associate_id}_{balance.bookmaker_id}")
    with form:
        amount_input = st.text_input(
            "Balance (native)",
            value=default_amount,
            key=f"amount_{balance.associate_id}_{balance.bookmaker_id}",
        )
        currency_input = st.selectbox(
            "Currency",
            options=VALID_CURRENCIES,
            index=VALID_CURRENCIES.index(default_currency)
            if default_currency in VALID_CURRENCIES
            else 0,
            key=f"currency_{balance.associate_id}_{balance.bookmaker_id}",
        )
        col_date, col_time = st.columns(2)
        date_input = col_date.date_input(
            "Check Date",
            value=existing_dt.date(),
            key=f"date_{balance.associate_id}_{balance.bookmaker_id}",
        )
        time_input = col_time.time_input(
            "Check Time (UTC)",
            value=existing_dt.time(),
            key=f"time_{balance.associate_id}_{balance.bookmaker_id}",
        )
        note_input = st.text_input(
            "Note (optional)",
            value=balance.status_label if balance.difference_eur else "",
            key=f"note_{balance.associate_id}_{balance.bookmaker_id}",
        )

        submitted = st.form_submit_button("Update Balance", type="primary")

        if submitted:
            valid, error = validate_balance_amount(amount_input)
            if not valid:
                st.error(error)
                return

            try:
                amount_decimal = Decimal(amount_input.strip())
            except (InvalidOperation, AttributeError):
                st.error("Enter a valid numeric balance amount.")
                return

            check_datetime = datetime.combine(date_input, time_input).replace(tzinfo=timezone.utc)
            check_date_utc = check_datetime.isoformat().replace("+00:00", "Z")

            try:
                on_update_balance(
                    balance.associate_id,
                    balance.bookmaker_id,
                    amount_decimal,
                    currency_input,
                    check_date_utc,
                    note_input.strip() or None,
                )
            except Exception as exc:
                st.error(f"Failed to update balance: {exc}")
            else:
                st.success("Balance check saved.")
                st.experimental_rerun()
