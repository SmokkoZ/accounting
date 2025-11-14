"""
Reconciliation Dashboard - Associate balance view for tracking holdings vs entitlements.

Implements Story 5.2: Per-associate reconciliation with DELTA calculations,
color-coded status indicators, and human-readable explanations.
"""

import sqlite3
import streamlit as st
import pandas as pd
from decimal import Decimal
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.ui.cache import get_cached_connection
from src.services.reconciliation_service import ReconciliationService, AssociateBalance
from src.services.bookmaker_balance_service import BookmakerBalanceService
from src.services.correction_service import CorrectionService, CorrectionError
from src.ui.components.reconciliation.bookmaker_drilldown import (
    render_bookmaker_drilldown,
)
from src.ui.components.reconciliation.pending_funding import (
    render_pending_funding_section,
)
from src.ui.ui_components import advanced_section, form_gated_filters, load_global_styles
from src.ui.utils.pagination import paginate
from src.ui.utils.performance import track_timing
from src.ui.utils.state_management import render_reset_control, safe_rerun
from src.ui.helpers.dialogs import open_dialog, render_correction_dialog
from src.ui.helpers.fragments import (
    call_fragment,
    render_debug_panel,
    render_debug_toggle,
)
from src.ui.helpers.streaming import (
    handle_streaming_error,
    show_success_toast,
    status_with_steps,
)
from src.utils.logging_config import get_logger
from src.ui.utils.identity_copy import (
    identity_formula,
    identity_label,
    identity_symbol,
    identity_tooltip,
)


logger = get_logger(__name__)

load_global_styles()

# Configure page
PAGE_TITLE = "Reconciliation"
PAGE_ICON = ":material/account_balance:"

st.set_page_config(
    page_title=PAGE_TITLE,
    page_icon=PAGE_ICON,
    layout="wide"
)

st.title(f"{PAGE_ICON} {PAGE_TITLE}")
st.markdown("**Track who's overholding group float vs. who's short**")

toggle_cols = st.columns([6, 2])
with toggle_cols[1]:
    render_debug_toggle(":material/monitor_heart: Performance debug")

action_cols = st.columns([6, 2])
with action_cols[1]:
    render_reset_control(
        key="reconciliation_reset",
        description="Clear reconciliation filters and dialog state.",
        prefixes=("reconciliation_", "filters_", "advanced_", "dialog_"),
    )


def _render_filter_controls() -> Dict[str, object]:
    col1, col2 = st.columns([2, 1])
    with col1:
        statuses = st.multiselect(
            "Statuses to show",
            options=["overholder", "balanced", "short"],
            default=["overholder", "balanced", "short"],
            key="reconciliation_status_filter",
        )
    with col2:
        slider_api = getattr(st, "slider", None)
        if callable(slider_api):
            min_delta = slider_api(
                "Min |Delta| (EUR)",
                min_value=0,
                max_value=200,
                value=10,
                step=5,
                key="reconciliation_delta_threshold",
                help="Hide associates whose absolute delta is below this value.",
            )
        else:
            min_delta = st.number_input(
                "Min |Delta| (EUR)",
                min_value=0,
                max_value=200,
                value=10,
                step=5,
                key="reconciliation_delta_threshold_input",
                help="Hide associates whose absolute delta is below this value.",
            )
    return {"statuses": statuses, "min_delta": min_delta}


with advanced_section():
    filter_state, _ = form_gated_filters(
        "reconciliation_filters",
        _render_filter_controls,
        submit_label="Apply Filters",
        help_text="Update the dashboard with the selected filters.",
    )

# ========================================
# Helper Functions
# ========================================


def format_currency_with_sign(value: Decimal) -> str:
    """Format currency with explicit + or - sign."""
    if value > 0:
        return f"+EUR {value:,.2f}"
    elif value < 0:
        return f"-EUR {abs(value):,.2f}"
    else:
        return f"EUR {value:,.2f}"


def get_status_color(status: str) -> str:
    """Get background color for status badge."""
    colors = {
        "overholder": "#ffebee",  # Light red
        "balanced": "#e8f5e9",    # Light green
        "short": "#fff3e0",       # Light orange
    }
    return colors.get(status, "#ffffff")


def export_to_csv(balances: List[AssociateBalance]) -> str:
    """
    Convert balances to CSV format.

    Returns:
        CSV string ready for download
    """
    if not balances:
        return "No data to export"

    df = pd.DataFrame([
        {
            "Associate": b.associate_alias,
            "NET_DEPOSITS_EUR": float(b.net_deposits_eur),
            "FS_EUR": float(b.fs_eur),
            "YF_EUR": float(b.yf_eur),
            "CURRENT_HOLDING_EUR": float(b.current_holding_eur),
            "IMBALANCE_EUR": float(b.delta_eur),
            "YF_MINUS_ND": round(float(b.yf_eur - b.net_deposits_eur), 2),
            "TB_EUR": float(b.tb_eur),
            "Status": b.status,
        }
        for b in balances
    ])

    return df.to_csv(index=False)


def _render_reconciliation_details_fragment(
    *,
    balance_entries: List[Dict[str, Any]],
    bookmaker_balances,
) -> None:
    """Render associate cards, drilldowns, and correction flows inside a fragment."""
    total_rows = len(balance_entries)
    pagination = paginate(
        "reconciliation_balances",
        total_rows,
        label="associates",
    )
    start = pagination.offset
    end = start + pagination.limit
    page_entries = balance_entries[start:end]

    if total_rows:
        st.caption(
            f"Showing {pagination.start_row}-{pagination.end_row} of {total_rows} associates"
        )

    with track_timing("reconciliation_cards"):
        for entry in page_entries:
            balance: AssociateBalance = entry["balance"]
            explanation: str = entry["explanation"]

            with st.container():
                cols = st.columns([0.5, 2, 1.3, 1.3, 1.3, 1.3, 1.3])
                (
                    col_icon,
                    col_alias,
                    col_nd,
                    col_fs,
                    col_yf,
                    col_tb,
                    col_delta,
                ) = cols

                with col_icon:
                    st.markdown(f"<h2 style='margin:0'>{balance.status_icon}</h2>", unsafe_allow_html=True)

                with col_alias:
                    st.markdown(f"**{balance.associate_alias}**")
                    st.caption(balance.status.capitalize())

                with col_nd:
                    st.metric(
                        "NET DEPOSITS (ND)",
                        f"EUR {balance.net_deposits_eur:,.2f}",
                        help="Cash you put in (deposits - withdrawals)",
                    )

                with col_fs:
                    st.metric(
                        "FAIR SHARE (FS)",
                        f"EUR {balance.fs_eur:,.2f}",
                        help="Settlement profit/loss from BET_RESULT share rows",
                    )

                with col_yf:
                    st.metric(
                        identity_label().upper(),
                        f"EUR {balance.yf_eur:,.2f}",
                        help=identity_tooltip(),
                    )

                with col_tb:
                    st.metric(
                        "TOTAL BALANCE (TB)",
                        f"EUR {balance.current_holding_eur:,.2f}",
                        help="Bookmaker holdings (all ledger entry types)",
                    )

                with col_delta:
                    delta_formatted = format_currency_with_sign(balance.delta_eur)
                    st.metric(
                        "IMBALANCE (I'')",
                        delta_formatted,
                        help=f"TB - {identity_symbol()} (should be zero when balanced)",
                    )

                with st.expander(":material/info: View Details"):
                    bg_color = get_status_color(balance.status)

                    st.markdown(
                        f"""
                        <div style='background-color: {bg_color}; padding: 15px; border-radius: 5px; margin: 10px 0;'>
                            <p style='margin: 0; font-size: 16px;'>{explanation}</p>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                st.markdown("##### Financial Breakdown")

                breakdown_data = {
                    "Metric": [
                        "Net Deposits (ND)",
                        "Fair Share (FS)",
                        f"{identity_label()} ({identity_formula()})",
                        "Total Balance (TB)",
                        f"Imbalance (I'' = TB - {identity_symbol()})",
                    ],
                    "Amount (EUR)": [
                        f"EUR {balance.net_deposits_eur:,.2f}",
                        f"EUR {balance.fs_eur:,.2f}",
                        f"EUR {balance.yf_eur:,.2f}",
                        f"EUR {balance.current_holding_eur:,.2f}",
                        format_currency_with_sign(balance.delta_eur),
                    ],
                    "Description": [
                        "Deposits - withdrawals",
                        "Settlement profit/loss from BET_RESULT share rows",
                        "Identity target combining funding and share",
                        "Bookmaker ledger holdings across entry types",
                        f"TB - {identity_symbol()} (zero means balanced)",
                    ],
                }

                df_breakdown = pd.DataFrame(breakdown_data)
                st.dataframe(df_breakdown, width="stretch", hide_index=True)

        st.divider()

    st.divider()

    def update_balance_callback(
        associate_id: int,
        bookmaker_id: int,
        amount_native: Decimal,
        currency: str,
        check_date_utc: str,
        note: Optional[str],
    ) -> None:
        def _persist_balance() -> None:
            with BookmakerBalanceService() as service:
                service.update_reported_balance(
                    associate_id=associate_id,
                    bookmaker_id=bookmaker_id,
                    balance_native=amount_native,
                    native_currency=currency,
                    check_date_utc=check_date_utc,
                    note=note,
                )

        try:
            list(
                status_with_steps(
                    "Update bookmaker balance",
                    [
                        ":material/rule: Validating input",
                        (":material/sync: Persisting balance", _persist_balance),
                        ":material/refresh: Refreshing dashboard",
                    ],
                )
            )
        except Exception as error:
            handle_streaming_error(error, "balance_update")
            return

        show_success_toast("Bookmaker balance updated.")
        safe_rerun()

    def prefill_correction(balance_item) -> None:
        with BookmakerBalanceService() as service:
            payload = service.get_correction_prefill(balance_item)

        if not payload:
            st.info("No mismatch detected for this bookmaker; correction not required.")
            return

        st.session_state["recon_correction_context"] = {
            "associate_id": payload["associate_id"],
            "bookmaker_id": payload["bookmaker_id"],
            "associate_alias": balance_item.associate_alias,
            "bookmaker_name": balance_item.bookmaker_name,
            "native_currency": payload["native_currency"],
            "amount_eur": str(payload["amount_eur"]),
            "amount_native": str(payload["amount_native"]) if payload["amount_native"] is not None else "",
            "note": payload.get("note", ""),
        }
        open_dialog("reconciliation_correction")

    render_bookmaker_drilldown(
        bookmaker_balances,
        on_update_balance=update_balance_callback,
        on_prefill_correction=prefill_correction,
    )

    correction_context = st.session_state.get("recon_correction_context")
    if correction_context:
        dialog_defaults = {
            "associate_alias": correction_context["associate_alias"],
            "bookmaker_name": correction_context["bookmaker_name"],
            "amount_eur": correction_context["amount_eur"],
            "amount_native": correction_context["amount_native"],
            "native_currency": correction_context["native_currency"],
            "note": correction_context.get("note", ""),
        }
        dialog_payload = render_correction_dialog(
            key="reconciliation_correction",
            defaults=dialog_defaults,
        )
        if dialog_payload:
            correction_result: Dict[str, int] = {}

            def _apply_correction() -> None:
                service = CorrectionService()
                try:
                    correction_result["entry_id"] = service.apply_correction(
                        associate_id=correction_context["associate_id"],
                        bookmaker_id=correction_context["bookmaker_id"],
                        amount_native=dialog_payload["amount_native"],
                        native_currency=dialog_payload["native_currency"],
                        note=dialog_payload["note"],
                        created_by="reconciliation_ui",
                    )
                finally:
                    service.close()

            try:
                list(
                    status_with_steps(
                        "Applying correction",
                        [
                            ":material/rule: Validating correction inputs",
                            (":material/note_alt: Writing ledger adjustment", _apply_correction),
                            ":material/refresh: Refreshing reconciliation view",
                        ],
                    )
                )
            except CorrectionError as error:
                handle_streaming_error(error, "reconciliation_correction")
                open_dialog("reconciliation_correction")
            except Exception as error:
                handle_streaming_error(error, "reconciliation_correction")
                open_dialog("reconciliation_correction")
            else:
                entry_id = correction_result.get("entry_id")
                if entry_id is None:
                    st.error("Correction did not return a ledger entry id.")
                    open_dialog("reconciliation_correction")
                else:
                    show_success_toast(
                        f"Correction applied (ledger entry {entry_id})."
                    )
                    st.session_state.pop("recon_correction_context", None)
                    safe_rerun()
        elif not st.session_state.get("reconciliation_correction__open", False):
            st.session_state.pop("recon_correction_context", None)

    with st.expander(":material/help: How Reconciliation Works"):
        st.markdown(
            f"""
        ### Reconciliation Math

        **NET DEPOSITS (ND)**: Personal funding
        - Formula: `SUM(DEPOSIT.amount_eur) - SUM(WITHDRAWAL.amount_eur)`
        - Explanation: "Cash you put in"

        **FAIR SHARE (FS)**: Settlement profit/loss
        - Formula: `SUM(per_surebet_share_eur)` from BET_RESULT rows (covers WON/LOST/VOID)
        - Explanation: "Profit/loss allocated to the associate"

        **{identity_label().upper()}**: Identity target
        - Formula: `{identity_formula()}`
        - Explanation: "How much cash they should be holding after settlement"

        **TOTAL BALANCE (TB)**: Physical bookmaker holdings
        - Formula: Sum of ALL ledger entries (BET_RESULT + DEPOSIT + WITHDRAWAL + BOOKMAKER_CORRECTION)
        - Explanation: "What they're actually holding in bookmaker accounts"

        **IMBALANCE (I'')**: Discrepancy
        - Formula: `TB - {identity_symbol()}`
        - **Red (Overholder)**: `I'' > +10 EUR` - Holding group float (collect from them)
        - **Green (Balanced)**: `-10 EUR <= I'' <= +10 EUR` - Holdings match entitlement
        - **Orange (Short)**: `I'' < -10 EUR` - Someone else is holding their money

        ### Status Threshold
        The +/- 10 EUR threshold accounts for minor rounding differences and pending transactions.
        """
        )

# ========================================
# Main Dashboard Layout
# ========================================

# Top controls
col1, col2, col3 = st.columns([2, 1, 1])

with col1:
    st.markdown("### Associate Balance Summary")

with col2:
    if st.button("Refresh Balances", width="stretch"):
        safe_rerun()

with col3:
    # Placeholder for export button (populated after data load)
    export_placeholder = st.empty()

st.divider()

# Load reconciliation data
db: Optional[sqlite3.Connection] | None = None
reconciliation_service: Optional[ReconciliationService] = None
bookmaker_service: Optional[BookmakerBalanceService] = None

try:
    db = get_cached_connection()
    reconciliation_service = ReconciliationService(db)
    bookmaker_service = BookmakerBalanceService(db)
    balances = reconciliation_service.get_associate_balances()
    bookmaker_balances = bookmaker_service.get_bookmaker_balances()

    if not balances:
        st.info(
            "No associate balance data available yet. Add deposits or settle bets to populate this view."
        )
        st.stop()

    status_filter = list(filter_state.get("statuses") or ["overholder", "balanced", "short"])
    min_delta_value = Decimal(str(filter_state.get("min_delta", 0)))

    def _matches_filters(balance: AssociateBalance) -> bool:
        status_ok = not status_filter or balance.status in status_filter
        if min_delta_value <= 0:
            delta_ok = True
        else:
            delta_ok = abs(balance.delta_eur) >= min_delta_value
        return status_ok and delta_ok

    filtered_balances = [balance for balance in balances if _matches_filters(balance)]

    # Export button
    csv_data = export_to_csv(filtered_balances)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    export_placeholder.download_button(
        label="Export CSV",
        data=csv_data,
        file_name=f"reconciliation_{timestamp}.csv",
        mime="text/csv",
        width="stretch",
    )

    # Summary metrics
    total_overholders = sum(1 for b in filtered_balances if b.status == "overholder")
    total_short = sum(1 for b in filtered_balances if b.status == "short")
    total_balanced = sum(1 for b in filtered_balances if b.status == "balanced")

    metric_col1, metric_col2, metric_col3 = st.columns(3)
    with metric_col1:
        st.metric("Overholders", total_overholders)
    with metric_col2:
        st.metric("Balanced", total_balanced)
    with metric_col3:
        st.metric("Short", total_short)

    st.divider()

    # Pending Funding Events Section (Story 5.4)
    render_pending_funding_section()
    
    st.divider()

    if not filtered_balances:
        st.warning("No associates match the selected filters.")
    else:
        balance_entries = [
            {"balance": balance, "explanation": reconciliation_service.get_explanation(balance)}
            for balance in filtered_balances
        ]

        call_fragment(
            "reconciliation.associate_cards",
            _render_reconciliation_details_fragment,
            balance_entries=balance_entries,
            bookmaker_balances=bookmaker_balances,
        )

    render_debug_panel()

except Exception as e:
    logger.error("reconciliation_dashboard_error", error=str(e), exc_info=True)
    st.error(f"Error loading reconciliation data: {str(e)}")
    st.info("Try refreshing the page or contact support if the issue persists.")

finally:
    if bookmaker_service is not None:
        bookmaker_service.close()
    if reconciliation_service is not None:
        reconciliation_service.close()



