"""
Monthly Statements Page

Generate per-associate statements showing funding, entitlement, bookmaker balances, and deltas.
Partner-facing and internal-only sections with export functionality.
"""

from __future__ import annotations

import asyncio
import base64
import csv
import io
import json
import re
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pandas as pd
import streamlit as st

from src.core.database import get_db_connection
from src.services.daily_statement_service import (
    DailyStatementBatchResult,
    DailyStatementSender,
)
from src.services.exit_settlement_service import ExitSettlementService
from src.services.statement_service import (
    StatementService,
    StatementCalculations,
    PartnerFacingSection,
    InternalSection,
    CsvExportPayload,
)
from src.services.settlement_constants import SETTLEMENT_MODEL_VERSION
from src.ui.helpers.fragments import (
    call_fragment,
    render_debug_panel,
    render_debug_toggle,
)
from src.ui.helpers.streaming import show_success_toast
from src.ui.ui_components import advanced_section, form_gated_filters, load_global_styles
from src.ui.utils.formatters import format_utc_datetime
from src.ui.utils.state_management import render_reset_control, safe_rerun
from src.ui.utils.identity_copy import (
    identity_anchor_sentence,
    identity_caption_text,
    identity_formula,
    identity_label,
    identity_rollout_note,
    identity_symbol,
    identity_tooltip,
    is_yf_copy_enabled,
)

PAGE_TITLE = "Statements"
PAGE_ICON = ":material/contract:"
STATEMENT_EXPORT_DIR = Path("data/exports/statements")


def _format_eur(value: Decimal | float | str) -> str:
    """Standard currency formatter for UI display."""
    return f"€{Decimal(str(value)):,.2f}"


def _decimal_str(value: Decimal | float | str) -> str:
    """Return standardized decimal string with two decimal places."""
    return f"{Decimal(str(value)).quantize(Decimal('0.01'))}"

def _coerce_cutoff_datetime(value: str) -> datetime:
    """Parse ISO cutoff strings and fall back to now."""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)


def _roi_ratio_percentage(roi: Decimal, utile: Decimal) -> Optional[Decimal]:
    """Return abs(roi) / abs(utile) * 100, or None when UTILE is zero."""
    if utile == 0 or utile == Decimal("0"):
        return None
    return (abs(roi) / abs(utile)) * Decimal("100")


def _profit_before_payout_help_text(raw_profit: Decimal | float | str) -> str:
    """Tooltip explaining difference between ROI share and UTILE."""
    utile_value = _format_eur(raw_profit)
    return (
        "Equal-share ROI still pending payout (per-surebet shares). "
        f"Compare with Net Profit (UTILE), currently {utile_value}."
    )


def _roi_vs_utile_ratio_display(roi: Decimal, utile: Decimal) -> tuple[str, str]:
    """Return ratio text + tooltip comparing ROI share against UTILE."""
    ratio = _roi_ratio_percentage(roi, utile)
    if ratio is None:
        return "--", "Net profit (UTILE) is zero, so ratio cannot be calculated."
    ratio_display = f"{ratio.quantize(Decimal('0.1'))}%"
    help_text = (
        "Portion of Net Profit (UTILE) represented by the ROI Before Payout amount "
        "using absolute values."
    )
    return ratio_display, help_text


def _utile_help_text() -> str:
    """Describe how UTILE relates to the entitlement identity."""
    if is_yf_copy_enabled():
        return "UTILE = YF - ND = FS (legacy 'Should Hold' target minus Net Deposits)."
    return "UTILE = Should Hold - ND = FS (rename flag disabled)."


def _slugify_name(value: str) -> str:
    """Return filesystem-safe slug for filenames."""
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value.strip()).strip("-").lower()
    return slug or "statement"


def trigger_auto_download(file_path: Path, error_prefix: str = "Download") -> None:
    """Auto-trigger file download via HTML anchor."""
    try:
        data = file_path.read_bytes()
    except OSError as exc:
        st.warning(f"{error_prefix} unavailable ({exc}). Use the link below.")
        return

    b64 = base64.b64encode(data).decode()
    download_id = f"download-link-{uuid.uuid4().hex}"
    download_html = (
        f'<a id="{download_id}" href="data:application/octet-stream;base64,{b64}" '
        f'download="{file_path.name}"></a>'
        f"<script>document.getElementById('{download_id}').click();</script>"
    )
    st.markdown(download_html, unsafe_allow_html=True)


def _daily_statement_log_records(log_entries: List[Any]) -> List[Dict[str, Any]]:
    """Convert log entries into plain dictionaries for UI export."""
    return [
        {
            "timestamp": entry.timestamp,
            "chat_id": entry.chat_id,
            "associate_id": entry.associate_id,
            "associate_alias": entry.associate_alias,
            "bookmaker_id": entry.bookmaker_id,
            "bookmaker_name": entry.bookmaker_name,
            "status": entry.status,
            "retries": entry.retries,
            "message_id": entry.message_id or "",
            "error_message": entry.error_message or "",
            "message_text": entry.message_text or "",
        }
        for entry in log_entries
    ]


def _records_to_csv(records: List[Dict[str, Any]]) -> str:
    """Serialize log records to CSV for download."""
    if not records:
        return ""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(records[0].keys()))
    writer.writeheader()
    writer.writerows(records)
    return buffer.getvalue()


def _execute_daily_statements(
    progress_callback: Callable[[int, int], None]
) -> DailyStatementBatchResult:
    """Run the DailyStatementSender and return the batch summary."""
    sender = DailyStatementSender()
    try:
        return asyncio.run(sender.send_all(progress_callback=progress_callback))
    finally:
        sender.close()


def _render_daily_statement_result(result: DailyStatementBatchResult) -> None:
    """Render the summary, log table, and download controls."""
    st.markdown("---")
    st.subheader(":material/receipt_long: Daily Telegram Statement Results")
    cols = st.columns(4)
    cols[0].metric("Total Chats Targeted", result.total_targets)
    cols[1].metric("Sent", result.sent)
    cols[2].metric("Failed", result.failed)
    cols[3].metric("Skipped", result.skipped)
    st.caption(f"Retries performed: {result.retried}")

    records = _daily_statement_log_records(result.log)
    if records:
        st.dataframe(records, height=220)
    else:
        st.info("No log entries generated.")

    csv_payload = _records_to_csv(records)
    json_payload = json.dumps(records, indent=2)
    download_cols = st.columns(2)
    download_cols[0].download_button(
        label="Download log (CSV)",
        data=csv_payload,
        file_name="daily_statements_log.csv",
        mime="text/csv",
        key="daily_statements_csv",
    )
    download_cols[1].download_button(
        label="Download log (JSON)",
        data=json_payload,
        file_name="daily_statements_log.json",
        mime="application/json",
        key="daily_statements_json",
    )


@contextmanager
def _modal_context(title: str):
    """
    Provide a compatibility wrapper around Streamlit's modal API.

    Older Streamlit versions lack st.modal, so we fall back to a container.
    """
    if hasattr(st, "modal"):
        with st.modal(title):
            yield
    else:
        container = st.container()
        with container:
            st.markdown(f"### {title}")
            st.info(
                "Modal dialogs require Streamlit 1.33+. Showing an inline confirmation instead."
            )
            yield


def _persist_csv_export(export_payload: CsvExportPayload) -> Path:
    """Write an in-memory CSV export to disk ensuring unique naming."""
    STATEMENT_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    target_path = STATEMENT_EXPORT_DIR / export_payload.filename
    counter = 1
    while target_path.exists():
        target_path = STATEMENT_EXPORT_DIR / (
            f"{target_path.stem}_{counter}{target_path.suffix}"
        )
        counter += 1
    target_path.write_bytes(export_payload.content)
    return target_path


def generate_statement_summary_csv(calc: StatementCalculations) -> Path:
    """Generate statement CSV using StatementService helper."""
    statement_service = StatementService()
    export_payload = statement_service.export_statement_csv(
        calc.associate_id,
        calc.cutoff_date,
        calculations=calc,
    )
    return _persist_csv_export(export_payload)


def generate_surebet_roi_csv(calc: StatementCalculations) -> Path:
    """Generate Surebet ROI CSV for the given calculations snapshot."""
    statement_service = StatementService()
    export_payload = statement_service.export_surebet_roi_csv(
        calc.associate_id,
        calc.cutoff_date,
        calculations=calc,
    )
    return _persist_csv_export(export_payload)


def export_all_statements_zip(cutoff_date: str) -> tuple[Optional[Path], List[str]]:
    """Generate statements for all associates and bundle into ZIP."""
    associates = get_associates()
    if not associates:
        return None, []

    statement_service = StatementService()
    csv_paths: List[Path] = []
    errors: List[str] = []

    for associate in associates:
        try:
            calc = statement_service.generate_statement(associate["id"], cutoff_date)
            csv_paths.append(generate_statement_summary_csv(calc))
        except Exception as exc:
            errors.append(f"{associate['name']}: {exc}")

    if not csv_paths:
        return None, errors

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    zip_name = f"statements_all_{timestamp}.zip"
    zip_path = STATEMENT_EXPORT_DIR / zip_name

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zipf:
        for path in csv_paths:
            zipf.write(path, arcname=path.name)

    return zip_path, errors

def get_associates() -> List[Dict[str, int]]:
    """Get list of associates for dropdown selection."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, display_alias FROM associates ORDER BY display_alias"
        )
        return [{"id": row["id"], "name": row["display_alias"]} for row in cursor.fetchall()]
    finally:
        conn.close()


def render_input_panel() -> tuple[int, str]:
    """Render input panel with associate selector and date picker."""
    st.subheader(":material/insights: Statement Parameters")
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Get associates and create selector
        associates = get_associates()
        if not associates:
            st.error("No associates found in database")
            return None, None
        
        associate_options = {assoc["name"]: assoc["id"] for assoc in associates}
        selected_name = st.selectbox(
            "Select Associate:",
            options=list(associate_options.keys()),
            key="associate_selector"
        )
        associate_id = associate_options[selected_name]
    
    with col2:
        # Cutoff date picker with default to today
        now = datetime.now(timezone.utc)
        # Default to today's date (which is within the allowed range)
        default_cutoff = now.date()
        
        cutoff_date = st.date_input(
            "Cutoff Date (Inclusive):",
            value=default_cutoff,
            max_value=now.date(),
            key="cutoff_date"
        )
        
        # Convert to ISO format with time
        cutoff_datetime = cutoff_date.strftime("%Y-%m-%dT23:59:59Z")
    
    st.caption(":material/lightbulb: All transactions up to and including this date will be included")
    
    return associate_id, cutoff_datetime


def render_statement_header(calc: StatementCalculations) -> None:
    """Render statement header with associate info and timestamps."""
    st.markdown("---")
    st.header(f":material/description: Monthly Statement for {calc.associate_name}")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Period Ending", format_utc_datetime(calc.cutoff_date))
    with col2:
        st.metric("Generated", format_utc_datetime(calc.generated_at))
    with col3:
        st.metric("Timezone", "AWST")

    ratio_value, ratio_help = _roi_vs_utile_ratio_display(
        calc.profit_before_payout_eur, calc.raw_profit_eur
    )
    metric_cols = st.columns(3)
    with metric_cols[0]:
        st.metric(
            "ROI Before Payout",
            _format_eur(calc.profit_before_payout_eur),
            help=_profit_before_payout_help_text(calc.raw_profit_eur),
        )
    with metric_cols[1]:
        st.metric(
            "Net Profit (UTILE)",
            _format_eur(calc.raw_profit_eur),
            help=_utile_help_text(),
        )
    with metric_cols[2]:
        st.metric(
            "ROI vs UTILE",
            ratio_value,
            help=ratio_help,
        )

    identity_cols = st.columns(5)
    identity_metrics = [
        ("Net Deposits (ND)", calc.net_deposits_eur, "Deposits - withdrawals"),
        ("Fair Share (FS)", calc.fs_eur, "Equal-share profit/loss from BET_RESULT rows"),
        (identity_label(), calc.yf_eur, identity_tooltip()),
        ("Total Balance (TB)", calc.tb_eur, "Current bookmaker holdings"),
        ("Imbalance (I'')", calc.i_double_prime_eur, f"TB - {identity_symbol()}"),
    ]
    for column, (label, value, help_text) in zip(identity_cols, identity_metrics):
        with column:
            st.metric(label, _format_eur(value), help=help_text)

    st.caption(
        f"Exit payout (-I''): {_format_eur(calc.exit_payout_eur)} "
        "(positive = pay the associate, negative = collect from them)."
    )


def render_partner_facing_section(partner_section: PartnerFacingSection) -> None:
    """Render partner-facing statement section."""
    st.markdown("---")
    st.subheader(":material/savings: Partner Statement")

    identity_cols = st.columns(6)
    identity_metrics = [
        ("Net Deposits (ND)", partner_section.net_deposits_eur, "Deposits - withdrawals"),
        ("Fair Share (FS)", partner_section.fair_share_eur, "Equal-share profits from settlements"),
        (identity_label(), partner_section.yield_funds_eur, identity_tooltip()),
        ("Total Balance (TB)", partner_section.total_balance_eur, "Current bookmaker holdings"),
        ("Imbalance (I'')", partner_section.imbalance_eur, f"TB - {identity_symbol()}"),
        ("Exit Payout (-I'')", partner_section.exit_payout_eur, "Amount to settle associate now"),
    ]
    for column, (label, value, help_text) in zip(identity_cols, identity_metrics):
        with column:
            st.metric(label, _format_eur(value), help=help_text)

    funding_cols = st.columns(3)
    with funding_cols[0]:
        st.metric("Total Deposits", _format_eur(partner_section.total_deposits_eur))
    with funding_cols[1]:
        st.metric("Total Withdrawals", _format_eur(partner_section.total_withdrawals_eur))
    with funding_cols[2]:
        st.metric(
            "Associate Delta",
            _format_eur(partner_section.imbalance_eur),
            help="Overholding (+) vs short (-) relative to entitlement.",
        )

    ratio_value, ratio_help = _roi_vs_utile_ratio_display(
        partner_section.profit_before_payout_eur, partner_section.raw_profit_eur
    )
    profit_cols = st.columns(3)
    with profit_cols[0]:
        st.metric(
            "ROI Before Payout",
            _format_eur(partner_section.profit_before_payout_eur),
            help=_profit_before_payout_help_text(partner_section.raw_profit_eur),
        )
    with profit_cols[1]:
        st.metric(
            "Net Profit (UTILE)",
            _format_eur(partner_section.raw_profit_eur),
            help=_utile_help_text(),
        )
    with profit_cols[2]:
        st.metric(
            "ROI vs UTILE",
            ratio_value,
            help=ratio_help,
        )

    st.info(
        f"Bookmaker balances (TB) total {_format_eur(partner_section.total_balance_eur)} "
        f"- combine with ND/FS to keep {identity_symbol()} identities visible."
    )
    st.caption(identity_caption_text())
    st.caption(identity_rollout_note())

def render_internal_section(internal_section: InternalSection) -> None:
    """Render internal-only statement section."""
    st.markdown("---")
    st.subheader(":material/lock: Internal Reconciliation")
    
    # Current Holdings
    st.markdown("##### Current Holdings")
    st.info(internal_section.current_holdings)
    st.caption("Sum of all ledger entries for this associate")
    
    # Reconciliation Delta
    st.markdown("##### Reconciliation Delta")
    delta_indicator = internal_section.delta_indicator
    delta_status = internal_section.reconciliation_delta
    
    if delta_indicator == "balanced":
        st.success(delta_status)
    elif delta_indicator == "over":
        st.error(delta_status)
    else:
        st.warning(delta_status)
    
    st.caption(f"Imbalance (I'') = Total Balance (TB) - {identity_symbol()}")

    st.markdown("##### Identity Snapshot")
    identity_rows = [
        {
            "Metric": "Net Deposits (ND)",
            "Amount": _format_eur(internal_section.net_deposits_eur),
            "Description": "Deposits - withdrawals",
        },
        {
            "Metric": "Fair Share (FS)",
            "Amount": _format_eur(internal_section.fair_share_eur),
            "Description": "Equal-share settlement profit/loss",
        },
        {
            "Metric": f"{identity_label()} ({identity_formula()})",
            "Amount": _format_eur(internal_section.yield_funds_eur),
            "Description": "Cash the associate should be holding",
        },
        {
            "Metric": "Total Balance (TB)",
            "Amount": _format_eur(internal_section.total_balance_eur),
            "Description": "Recorded bookmaker holdings",
        },
        {
            "Metric": "Imbalance (I'')",
            "Amount": _format_eur(internal_section.imbalance_eur),
            "Description": f"TB - {identity_symbol()} (positive = overholder)",
        },
        {
            "Metric": "Exit Payout (-I'')",
            "Amount": _format_eur(internal_section.exit_payout_eur),
            "Description": "What Settle Associate Now will post",
        },
    ]
    st.table(identity_rows)


def render_settle_associate_section(
    calc: StatementCalculations, exit_service: Optional[ExitSettlementService] = None
) -> None:
    """Render Settle Associate Now controls."""
    st.markdown("---")
    st.subheader(":material/account_balance_wallet: Settle Associate Now")
    st.caption(
        f"{identity_anchor_sentence()} "
        f"Exit payout (-I'') = {_format_eur(calc.exit_payout_eur)} at the current cutoff. "
        f"Model {SETTLEMENT_MODEL_VERSION} keeps exports versioned."
    )

    default_cutoff = _coerce_cutoff_datetime(calc.cutoff_date)
    date_value = st.date_input(
        "Settlement date (UTC)",
        value=default_cutoff.date(),
        key=f"settle_date_{calc.associate_id}",
    )
    time_value = st.time_input(
        "Settlement time (UTC)",
        value=default_cutoff.time(),
        key=f"settle_time_{calc.associate_id}",
    )
    cutoff_value = (
        datetime.combine(date_value, time_value)
        .replace(tzinfo=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )

    confirm_key = f"settle_confirm_{calc.associate_id}"
    confirm_intent = st.checkbox(
        "I confirm this posts a balancing ledger entry and updates exports.",
        key=confirm_key,
        help="Guardrail to avoid accidental settlements.",
    )

    run_label = ":material/account_balance_wallet: Run Settle Associate Now"
    trigger = st.button(
        run_label,
        key=f"settle_associate_now_{calc.associate_id}",
        help="Posts a balancing deposit/withdrawal so I'' becomes zero.",
        disabled=not confirm_intent,
    )

    if not trigger:
        return

    service = exit_service
    validator: Optional[StatementService] = None
    if service is None:
        validator = StatementService()
        service = ExitSettlementService(statement_service=validator)
    else:
        validator = getattr(service, "statement_service", StatementService())

    if not validator or not validator.validate_cutoff_date(cutoff_value):
        st.error("Cutoff must be a valid ISO8601 UTC timestamp that is not in the future.")
        return

    calc_payload = calc if cutoff_value == calc.cutoff_date else None

    with st.spinner("Posting balancing ledger entry..."):
        try:
            result = service.settle_associate_now(
                calc.associate_id,
                cutoff_value,
                calculations=calc_payload,
                created_by="statements_ui",
            )
        except RuntimeError as exc:
            st.error(f"Settlement failed: {exc}")
            return

    if not result.was_posted:
        st.info(result.note)
        return

    st.success(
        f"Posted {result.entry_type} for {_decimal_str(result.amount_eur)} EUR. "
        "Recomputing statement snapshot..."
    )
    metrics_col1, metrics_col2 = st.columns(2)
    metrics_col1.metric("Amount Posted (EUR)", _decimal_str(result.amount_eur))
    metrics_col2.metric("Imbalance After I''", _decimal_str(result.delta_after))

    with st.expander("Receipt Preview", expanded=False):
        st.markdown(result.receipt.markdown)
        if result.receipt.file_path and result.receipt.file_path.exists():
            with open(result.receipt.file_path, "r", encoding="utf-8") as receipt_file:
                st.download_button(
                    label="Download Receipt Markdown",
                    data=receipt_file.read(),
                    file_name=result.receipt.file_path.name,
                    mime="text/markdown",
                    key=f"download_receipt_{result.receipt.file_path.name}",
                )
    st.caption(
        f"Model {result.receipt.version} receipt stored at "
        f"{result.receipt.file_path or 'data/exports/receipts/<associate_id>'}."
    )
    st.session_state.current_statement = result.updated_calculations
    show_success_toast("Associate balanced successfully.")

    refresh_key = f"settle_associate_refresh_{calc.associate_id}"
    if st.button(
        ":material/refresh: Refresh statement view",
        key=refresh_key,
        help="Click after reviewing the receipt to recompute the snapshot.",
    ):
        safe_rerun()
    else:
        st.caption(
            "Receipt preview is visible above; hit Refresh when you are ready to rerun the statement."
        )


def render_export_options(calc: StatementCalculations, partner_section: PartnerFacingSection) -> None:
    """Render export functionality buttons."""
    st.markdown("---")
    st.subheader(":material/upload_file: Export Options")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        # Copy to Clipboard (partner-facing only)
        bookmaker_lines = "\n".join(
            f"- {row.bookmaker_name}: balance {_format_eur(row.balance_eur)}, "
            f"deposits {_format_eur(row.deposits_eur)}, "
            f"withdrawals {_format_eur(row.withdrawals_eur)}"
            for row in partner_section.bookmakers
        ) or "- No bookmaker activity recorded."
        ratio_value, _ = _roi_vs_utile_ratio_display(
            calc.profit_before_payout_eur, calc.raw_profit_eur
        )
        clipboard_text = f"""
PARTNER STATEMENT - {calc.associate_name}
Period Ending: {calc.cutoff_date.split('T')[0]}

Net Deposits (ND): {_format_eur(partner_section.net_deposits_eur)}
Fair Share (FS): {_format_eur(partner_section.fair_share_eur)}
{identity_label()} ({identity_formula()}): {_format_eur(partner_section.yield_funds_eur)}
Total Balance (TB): {_format_eur(partner_section.total_balance_eur)}
Imbalance (I''): {_format_eur(partner_section.imbalance_eur)}  (TB - {identity_symbol()})
Exit Payout (-I''): {_format_eur(partner_section.exit_payout_eur)}
Total Deposits: {_format_eur(partner_section.total_deposits_eur)}
Total Withdrawals: {_format_eur(partner_section.total_withdrawals_eur)}
ROI Before Payout: {_format_eur(partner_section.profit_before_payout_eur)}
Net Profit (UTILE): {_format_eur(partner_section.raw_profit_eur)}
ROI vs UTILE: {ratio_value}

Bookmaker Breakdown:
{bookmaker_lines}
        """.strip()
        
        if st.button(":material/content_copy: Copy to Clipboard", key="copy_clipboard", width="stretch"):
            st.session_state.clipboard_text = clipboard_text
            st.success("Partner statement copied to session state.")
            st.code(clipboard_text)
    
    with col2:
        # Export statement CSV via service helper
        if st.button(":material/grid_on: Export Statement CSV", key="export_statement_csv", width="stretch"):
            with st.spinner("Generating statement summary CSV..."):
                try:
                    csv_path = generate_statement_summary_csv(calc)
                    st.success("Statement summary ready.")
                    with open(csv_path, "rb") as csv_file:
                        st.download_button(
                            label="Download Statement CSV",
                            data=csv_file.read(),
                            file_name=csv_path.name,
                            mime="text/csv",
                            key=f"download_statement_csv_{csv_path.name}",
                        )
                except Exception as e:
                    st.error(f"CSV export failed: {str(e)}")

    with col3:
        if st.button(":material/table_view: Export Surebet ROI CSV", key="export_roi_csv", width="stretch"):
            with st.spinner("Generating ROI CSV..."):
                try:
                    roi_path = generate_surebet_roi_csv(calc)
                    st.success("Surebet ROI export ready.")
                    with open(roi_path, "rb") as roi_file:
                        st.download_button(
                            label="Download Surebet ROI CSV",
                            data=roi_file.read(),
                            file_name=roi_path.name,
                            mime="text/csv",
                            key=f"download_roi_csv_{roi_path.name}",
                        )
                except Exception as e:
                    st.error(f"ROI CSV export failed: {str(e)}")


def render_generate_button(associate_id: int, cutoff_date: str) -> bool:
    """Render generate statement button with validation."""
    if not associate_id or not cutoff_date:
        st.warning("Please select an associate and cutoff date.")
        return False
    
    # Validate cutoff date is not in future
    statement_service = StatementService()
    if not statement_service.validate_cutoff_date(cutoff_date):
        st.error("Cutoff date cannot be in future.")
        return False
    
    return st.button(
        ":material/rocket_launch: Generate Statement",
        type="primary",
        width="stretch",
        key="generate_statement"
    )


def render_statement_details(calc: StatementCalculations, *, expanded: bool = False) -> None:
    """Render detailed transaction table."""
    with st.expander(":material/insights: Transaction Details", expanded=expanded):
        try:
            statement_service = StatementService()
            transactions = statement_service.get_associate_transactions(
                calc.associate_id, calc.cutoff_date
            )
            
            if transactions:
                df = pd.DataFrame(transactions)
                
                # Format for display
                display_columns = [
                    'created_at_utc', 'type', 'amount_eur', 'settlement_state',
                    'principal_returned_eur', 'per_surebet_share_eur', 'note'
                ]
                df_display = df[display_columns].copy()
                df_display["created_at_utc"] = df_display["created_at_utc"].apply(
                    format_utc_datetime
                )
                
                st.dataframe(
                    df_display,
                    width="stretch",
                    hide_index=True
                )
            else:
                st.info("No transactions found for this period")
                
        except Exception as e:
            st.error(f"Failed to load transaction details: {str(e)}")


def _render_statement_output(
    calc: StatementCalculations,
    *,
    options: Optional[Dict[str, object]] = None,
) -> None:
    """Render the complete statement output within a fragment."""
    options = options or {}
    show_internal = bool(options.get("show_internal_section", True))
    auto_expand_transactions = bool(options.get("auto_expand_transactions", False))

    statement_service = StatementService()
    partner_section = statement_service.format_partner_facing_section(calc)
    internal_section = statement_service.format_internal_section(calc)

    render_statement_header(calc)
    render_partner_facing_section(partner_section)
    if show_internal:
        render_internal_section(internal_section)
    render_settle_associate_section(calc)
    render_export_options(calc, partner_section)
    render_statement_details(calc, expanded=auto_expand_transactions)

def render_validation_errors(errors: List[str]) -> None:
    """Render validation error messages."""
    for error in errors:
        st.error(f"{error}")


def main() -> None:
    """Main entry point for Statements page."""
    st.set_page_config(
        page_title=PAGE_TITLE,
        page_icon=PAGE_ICON,
        layout="wide"
    )
    load_global_styles()
    st.session_state.setdefault("daily_statements_modal_open", False)
    st.session_state.setdefault("daily_statements_result", None)
    st.session_state.setdefault("daily_statements_error", None)

    st.title(f"{PAGE_ICON} {PAGE_TITLE}")
    st.caption("Generate per-associate statements showing funding, entitlement, bookmaker balances, and deltas")

    toggle_cols = st.columns([6, 2])
    with toggle_cols[1]:
        render_debug_toggle(":material/monitor_heart: Performance debug")

    action_cols = st.columns([6, 2])
    with action_cols[1]:
        render_reset_control(
            key="statements_reset",
            description="Clear statement inputs and advanced options.",
            prefixes=("statements_", "associate_", "cutoff_", "filters_", "advanced_", "dialog_"),
        )

    st.markdown("---")
    st.subheader(":material/notifications: Global Daily Statements")
    st.caption(
        "Send the current balance + pending summary to every active Telegram chat with configurable rate limits."
    )
    if st.button(":material/send: Send Daily Statements to All Chats", key="daily_statements_launch"):
        st.session_state.daily_statements_modal_open = True
        st.session_state.daily_statements_result = None
        st.session_state.daily_statements_error = None

    if st.session_state.daily_statements_modal_open:
        with _modal_context(":material/notifications_active: Confirm Daily Statement Dispatch"):
            st.write(
                "This will send today's balance and pending ping to each registered bookmaker chat."
            )
            st.caption(
                "Rate limits: 15 messages/sec globally, 1 message/sec per chat; retries/backoff handle Telegram 429."
            )
            if st.button("Confirm and send", key="daily_statements_confirm"):
                progress_bar = st.progress(0)
                progress_label = st.empty()

                def progress_callback(processed: int, total: int) -> None:
                    if total == 0:
                        progress_bar.progress(100)
                        progress_label.text("No active chats configured.")
                        return
                    percent = min(100, int(processed / total * 100))
                    progress_bar.progress(percent)
                    progress_label.text(f"{processed}/{total} chats processed")

                try:
                    with st.spinner("Dispatching daily statements..."):
                        result = _execute_daily_statements(progress_callback)
                    st.session_state.daily_statements_result = result
                    st.session_state.daily_statements_error = None
                    progress_label.text(f"Completed {result.total_targets} chats.")
                    st.success("Daily statements dispatch complete.")
                except Exception as exc:
                    st.session_state.daily_statements_error = str(exc)
                    st.error(f"Daily statements failed: {exc}")
                finally:
                    st.session_state.daily_statements_modal_open = False

            if st.button("Cancel", key="daily_statements_cancel"):
                st.session_state.daily_statements_modal_open = False

    def _render_statement_options() -> Dict[str, bool]:
        col1, col2 = st.columns(2)
        with col1:
            show_internal_section = st.checkbox(
                ":material/admin_panel_settings: Show internal section",
                value=True,
                key="statements_show_internal",
            )
        with col2:
            auto_expand_transactions = st.checkbox(
                ":material/table_rows: Auto-expand transactions",
                value=False,
                key="statements_expand_transactions",
            )
        return {
            "show_internal_section": show_internal_section,
            "auto_expand_transactions": auto_expand_transactions,
        }

    with advanced_section():
        statement_options, _ = form_gated_filters(
            "statements_filters",
            _render_statement_options,
            submit_label="Apply Options",
            help_text="Control which sections render after a statement is generated.",
        )
    
    # Initialize session state
    if 'statement_generated' not in st.session_state:
        st.session_state.statement_generated = False
    if 'current_statement' not in st.session_state:
        st.session_state.current_statement = None
    
    # Render input panel
    associate_id, cutoff_date = render_input_panel()
    
    # Generate buttons with validation
    if associate_id and cutoff_date:
        action_cols = st.columns(2)
        with action_cols[0]:
            generate_clicked = render_generate_button(associate_id, cutoff_date)
        with action_cols[1]:
            export_all_clicked = st.button(
                ":material/archive: Export All Statements (ZIP)",
                key="export_all_statements_zip",
                help="Generate statement summaries for every associate and download a ZIP.",
            )

        if generate_clicked:
            with st.spinner("Generating statement..."):
                try:
                    statement_service = StatementService()
                    calc = statement_service.generate_statement(associate_id, cutoff_date)

                    partner_section = statement_service.format_partner_facing_section(calc)
                    summary_path = generate_statement_summary_csv(calc)
                    st.session_state.current_statement = calc
                    st.session_state.statement_generated = True
                    st.success(f"Statement generated for {calc.associate_name}")
                    show_success_toast(f"Statement generated for {calc.associate_name}")
                    summary_resolved = summary_path.resolve()
                    trigger_auto_download(summary_resolved, "Statement download")
                    st.caption(
                        f"If the download was blocked, "
                        f"[click here to download manually]({summary_resolved.as_uri()})."
                    )
                except ValueError as e:
                    st.error(f"Validation Error: {str(e)}")
                except Exception as e:
                    st.error(f"Statement generation failed: {str(e)}")

        if export_all_clicked:
            with st.spinner("Generating statements for all associates..."):
                zip_path, errors = export_all_statements_zip(cutoff_date)
            if zip_path:
                show_success_toast("All statements generated.")
                zip_resolved = zip_path.resolve()
                trigger_auto_download(zip_resolved, "Statements ZIP download")
                st.caption(
                    f"If the ZIP download was blocked, "
                    f"[download it manually]({zip_resolved.as_uri()})."
                )
            if errors:
                st.error("Some statements failed:\n" + "\n".join(f"- {err}" for err in errors))
    
    # Display generated statement
    if st.session_state.statement_generated and st.session_state.current_statement:
        calc = st.session_state.current_statement

        call_fragment(
            "statements.output",
            _render_statement_output,
            calc=calc,
            options=statement_options,
        )

    st.divider()
    if st.session_state.daily_statements_error:
        st.error(f"Daily statements error: {st.session_state.daily_statements_error}")
    if st.session_state.daily_statements_result:
        _render_daily_statement_result(st.session_state.daily_statements_result)

    # Instructions
    # Instructions
    with st.expander(":material/menu_book: Statement Information", expanded=False):
        st.markdown(
            f"""
            ### About Monthly Statements

            - **Partner Statement**: Shareable with associates showing funding, entitlement, and bookmaker balances
            - **Internal Reconciliation**: Internal-only section showing ND/FS/{identity_symbol()}/TB identities
            - **Transaction Details**: Complete transaction list for verification

            **Identity & Settlements**

            - `ND = SUM(DEPOSIT.amount_eur) - SUM(WITHDRAWAL.amount_eur)`
            - `FS = SUM(BET_RESULT.per_surebet_share_eur)` (covers WON / LOST / VOID)
            - `{identity_formula()}` (toggle via `SUREBET_YF_COPY_ROLLOUT`)
            - `TB = SUM(all ledger entries)`
            - `I'' = TB - {identity_symbol()}` (positive = overholder, negative = short)
            - `Exit payout = -I''` (positive = pay associate, negative = collect from them)

            {identity_rollout_note()}

            Statement CSV exports list ND/FS/{identity_symbol()}/TB/I'' plus **Exit Payout**. Run **Settle Associate Now** before
            deactivating an associate so they exit with `I'' = 0`.
            """
        )


    render_debug_panel()


if __name__ == "__main__":
    main()







