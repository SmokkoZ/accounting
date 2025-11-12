"""
Export Page - Ledger CSV Export

Provides interface for exporting the full ledger to CSV for audit and backup purposes.
Includes export history and re-download functionality.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional
import inspect

import streamlit as st

from src.core.database import get_db_connection
from src.services.ledger_export_service import LedgerExportService
from src.ui.helpers.fragments import (
    call_fragment,
    render_debug_panel,
    render_debug_toggle,
)
from src.ui.helpers.streaming import (
    handle_streaming_error,
    show_success_toast,
    status_with_steps,
    stream_with_fallback,
)
from src.ui.ui_components import advanced_section, form_gated_filters, load_global_styles
from src.ui.utils.formatters import format_utc_datetime
from src.ui.utils.state_management import render_reset_control, safe_rerun
from src.utils.logging_config import get_logger

PAGE_TITLE = "Export"
PAGE_ICON = ":material/ios_share:"
logger = get_logger(__name__)


def _supports_associate_filtering() -> bool:
    """Detect whether the service accepts associate filtering."""
    try:
        params = inspect.signature(LedgerExportService.export_full_ledger).parameters
    except (ValueError, TypeError):
        return False
    return "associate_id" in params


def load_associates_for_export() -> List[Dict[str, object]]:
    """Load associates for filtering the export."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.execute(
            """
            SELECT id, display_alias, home_currency
            FROM associates
            ORDER BY display_alias
            """
        )
        return [
            {
                "id": row["id"],
                "display_alias": row["display_alias"],
                "home_currency": row["home_currency"],
            }
            for row in cursor.fetchall()
        ]
    except Exception as exc:
        logger.error("export_load_associates_failed", error=str(exc))
        st.warning("Unable to load associates. Only full-ledger exports are available.")
        return []
    finally:
        if conn is not None:
            conn.close()


def format_scope_label(history_entry: Dict[str, object]) -> str:
    """Pretty label for export scope."""
    scope = history_entry.get("scope")
    if scope == "associate":
        alias = history_entry.get("associate_alias")
        if alias:
            return alias
        alias_slug = history_entry.get("alias_slug")
        if alias_slug:
            return alias_slug.replace("-", " ").title()
        associate_id = history_entry.get("associate_id")
        return f"Associate #{associate_id}" if associate_id is not None else "Associate"
    if scope == "all":
        return "All Associates"
    return "Unknown"

def render_export_button(*, validate_after_export: bool = True) -> None:
    """Render the main export button and handle export logic."""
    st.subheader("Export Full Ledger")

    st.info(
        "Export the complete ledger with all entries, including joins to associate "
        "names and bookmaker names. Use the associate filter below to scope the "
        "export to a single account. Files are saved to `data/exports/` and a download "
        "link will be provided."
    )

    associates = load_associates_for_export()
    supports_filter = _supports_associate_filtering()
    associate_options: Dict[str, Optional[int]] = {"All Associates": None}
    for associate in associates:
        label = (
            f"{associate['display_alias']} ({associate['home_currency']})"
            if associate.get("home_currency")
            else associate["display_alias"]
        )
        associate_options[label] = associate["id"]

    selected_label = st.selectbox(
        "Associate Filter",
        options=list(associate_options.keys()),
        help="Choose an associate to export only their ledger entries.",
        key="export_associate_filter",
    )
    selected_associate_id = associate_options[selected_label]
    if selected_associate_id is not None and not supports_filter:
        st.warning(
            "This running version cannot filter exports per associate yet. "
            "Restart the app after updating to enable scoped exports."
        )

    if st.button(":material/ios_share: Export Ledger", type="primary", width="stretch"):
        export_service = LedgerExportService()
        if selected_associate_id is not None and not supports_filter:
            st.error(
                "Per-associate exports are unavailable until the backend reloads with the latest version. "
                "Please restart and try again."
            )
            return
        progress: Dict[str, str | int | None] = {"scope_label": selected_label}

        def _run_export_job() -> None:
            def _export_generator():
                scope_suffix = (
                    f" for {selected_label}" if selected_associate_id is not None else ""
                )
                yield f":material/storage: Querying ledger data{scope_suffix}..."
                export_kwargs = {}
                if selected_associate_id is not None and supports_filter:
                    export_kwargs["associate_id"] = selected_associate_id
                result = export_service.export_full_ledger(**export_kwargs)
                progress["file_path"], progress["row_count"] = result
                yield f":material/check: Ledger exported with {progress['row_count']:,} rows"

            stream_with_fallback(_export_generator, header=":material/article: Export progress log")

        try:
            list(
                status_with_steps(
                    f"Ledger export ({selected_label})",
                    [
                        ":material/playlist_add_check: Validating export parameters",
                        (":material/autorenew: Running export job", _run_export_job),
                        ":material/link: Preparing download link",
                    ],
                )
            )
        except Exception as exc:
            handle_streaming_error(exc, "ledger export")
            return

        file_path = progress.get("file_path")
        row_count = progress.get("row_count")
        if not file_path or not row_count:
            st.error("Export completed without returning file metadata.")
            return

        show_success_toast(f"Ledger exported for {selected_label} ({int(row_count):,} rows)")

        st.markdown("### Download Link")
        st.markdown(f":material/download: [{Path(file_path).name}](file://{Path(file_path).absolute()})")

        file_stat = Path(file_path).stat()
        file_size = export_service.get_file_size_display(file_stat.st_size)

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("File Size", file_size)
        with col2:
            st.metric("Rows Exported", f"{int(row_count):,}")
        with col3:
            st.metric("Status", "Complete")
        with col4:
            st.metric("Scope", progress.get("scope_label", selected_label))

        if validate_after_export:
            try:
                with open(file_path, "r", encoding="utf-8") as handle:
                    actual_rows = max(sum(1 for _ in handle) - 1, 0)
                if actual_rows != int(row_count):
                    st.warning(
                        f"Validation detected a mismatch ({actual_rows:,} rows vs expected {int(row_count):,})."
                    )
                else:
                    st.caption(":material/task_alt: Validation passed for exported file.")
            except OSError as exc:
                st.warning(f"Unable to validate export file: {exc}")

        safe_rerun()


def render_export_history(limit: int) -> None:
    """Render the export history table with re-download functionality."""
    st.subheader("Export History")
    
    try:
        export_service = LedgerExportService()
        history = export_service.get_export_history(limit=limit)
        
        if not history:
            st.info("No export history found. Export files will appear here.")
            return
        
        # Display history as a table
        for i, export in enumerate(history, 1):
            with st.expander(f"{export['filename']} - {export['created_time']}"):
                scope_label = format_scope_label(export)
                col1, col2, col3, col4, col5 = st.columns(5)

                with col1:
                    st.metric("Rows", f"{export['row_count']:,}")
                
                with col2:
                    st.metric("Size", export_service.get_file_size_display(export['file_size']))
                
                with col3:
                    st.metric("Scope", scope_label)
                
                with col4:
                    st.metric("Created", format_utc_datetime(export['created_time']))

                with col5:
                    if st.button(f":material/download: Download", key=f"download_{i}"):
                        file_path = Path(export['file_path'])
                        if file_path.exists():
                            st.markdown(
                                f":material/folder: [{export['filename']}](file://{file_path.absolute()})"
                            )
                        else:
                            st.error("File not found")
                
                # Full file path
                st.code(export['file_path'])
        
    except Exception as e:
        st.error(f"Failed to load export history: {str(e)}")


def render_export_instructions() -> None:
    """Render instructions and information about the export functionality."""
    with st.expander(":material/menu_book: Export Information", expanded=False):
        st.markdown("""
        ### About Ledger Export
        
        **Purpose:** Create a complete CSV export of all ledger entries for external audit or backup.
        
        **File Format:** 
        - CSV with UTF-8 encoding
        - Comma delimiter with proper escaping
        - All numeric fields as strings to preserve Decimal precision
        - NULL values as empty strings
        
        **Columns Included:**
        - `entry_id` - Unique identifier for the ledger entry
        - `entry_type` - Type (BET_RESULT, DEPOSIT, WITHDRAWAL, BOOKMAKER_CORRECTION)
        - `associate_alias` - Associate display name
        - `bookmaker_name` - Bookmaker name (if applicable)
        - `surebet_id` - Related surebet ID (if applicable)
        - `bet_id` - Related bet ID (if applicable)
        - `settlement_batch_id` - Settlement batch identifier
        - `settlement_state` - WON/LOST/VODE (for bet results)
        - `amount_native` - Amount in native currency
        - `native_currency` - Native currency code
        - `fx_rate_snapshot` - Exchange rate used (EUR per 1 unit native)
        - `amount_eur` - Amount converted to EUR
        - `principal_returned_eur` - Principal amount returned (EUR)
        - `per_surebet_share_eur` - Share amount in surebet split (EUR)
        - `created_at_utc` - Entry creation timestamp (UTC)
        - `created_by` - Who created the entry
        - `note` - Any additional notes
        
        **File Location:** All exports are saved to `data/exports/` with timestamp naming.

        **Filtering:** Use the Associate Filter on this page to export transactions for a single associate. Leave it on "All Associates" for a complete ledger dump.
        
        **Validation:** Each export is validated to ensure all data is correctly written and row counts match.
        """)


def main() -> None:
    """Main entry point for the Export page."""
    st.set_page_config(
        page_title=PAGE_TITLE,
        page_icon=PAGE_ICON,
        layout="wide"
    )
    load_global_styles()
st.title(f"{PAGE_ICON} {PAGE_TITLE}")
st.caption("CSV export workflow for ledger data and audit trails.")

toggle_cols = st.columns([6, 2])
with toggle_cols[1]:
    render_debug_toggle(":material/monitor_heart: Performance debug")

action_cols = st.columns([6, 2])
with action_cols[1]:
    render_reset_control(
        key="export_reset",
        description="Clear export options and dialog state.",
        prefixes=("export_", "filters_", "advanced_", "dialog_"),
    )


def _render_export_options() -> Dict[str, object]:
    col1, col2 = st.columns([2, 1])
    with col1:
        validate_after_export = st.checkbox(
            "Validate file after export",
            value=True,
            key="export_validate_file",
            help="Read the generated CSV and verify the row count before completing.",
        )
    with col2:
        history_limit = st.number_input(
            "History entries",
            min_value=5,
            max_value=50,
            step=5,
            value=10,
            key="export_history_limit",
        )
    return {
        "validate_after_export": validate_after_export,
        "history_limit": int(history_limit),
    }


with advanced_section():
    export_options, _ = form_gated_filters(
        "export_filters",
        _render_export_options,
        submit_label="Apply Options",
        help_text="Update export validation and history preferences.",
    )
    
    # Render main sections
    call_fragment(
        "export.action",
        render_export_button,
        validate_after_export=export_options["validate_after_export"],
    )
    st.divider()
    call_fragment(
        "export.history",
        render_export_history,
        limit=export_options["history_limit"],
    )
    st.divider()
    render_export_instructions()
    
    # Footer info
    st.markdown("---")
    st.caption(
        ":material/lightbulb: **Tip:** For very large ledgers (10,000+ rows), the export may take "
        "several seconds. The progress spinner will indicate when the export is complete."
    )

    render_debug_panel()


if __name__ == "__main__":
    main()

