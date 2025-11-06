"""
Export Page - Ledger CSV Export

Provides interface for exporting the full ledger to CSV for audit and backup purposes.
Includes export history and re-download functionality.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Dict, List

import streamlit as st

from src.services.ledger_export_service import LedgerExportService
from src.ui.helpers.fragments import (
    call_fragment,
    render_debug_panel,
    render_debug_toggle,
)
from src.ui.ui_components import load_global_styles

PAGE_TITLE = "Export"
PAGE_ICON = ":material/ios_share:"

def render_export_button() -> None:
    """Render the main export button and handle export logic."""
    st.subheader("Export Full Ledger")
    
    st.info(
        "Export the complete ledger with all entries, including joins to associate "
        "names and bookmaker names. The export will be saved to `data/exports/` "
        "and a download link will be provided."
    )
    
    if st.button("📥 Export Full Ledger", type="primary", use_container_width=True):
        with st.spinner("Exporting ledger... This may take a moment for large datasets."):
            try:
                export_service = LedgerExportService()
                file_path, row_count = export_service.export_full_ledger()
                
                # Success message with download link
                st.success(f"✅ Ledger exported successfully! **{row_count:,} rows**")
                
                # Provide download link
                st.markdown("### Download Link")
                st.markdown(
                    f"📁 [{Path(file_path).name}](file://{Path(file_path).absolute()})"
                )
                
                # Show file info
                file_stat = Path(file_path).stat()
                file_size = export_service.get_file_size_display(file_stat.st_size)
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("File Size", file_size)
                with col2:
                    st.metric("Rows Exported", f"{row_count:,}")
                with col3:
                    st.metric("Status", "Complete")
                
                # Refresh export history
                st.rerun()
                
            except Exception as e:
                st.error(f"❌ Export failed: {str(e)}")
                st.error("Please check the logs for more details.")


def render_export_history() -> None:
    """Render the export history table with re-download functionality."""
    st.subheader("Export History")
    
    try:
        export_service = LedgerExportService()
        history = export_service.get_export_history(limit=10)
        
        if not history:
            st.info("No export history found. Export files will appear here.")
            return
        
        # Display history as a table
        for i, export in enumerate(history, 1):
            with st.expander(f"{export['filename']} - {export['created_time']}"):
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    st.metric("Rows", f"{export['row_count']:,}")
                
                with col2:
                    st.metric("Size", export_service.get_file_size_display(export['file_size']))
                
                with col3:
                    st.metric("Created", export['created_time'])
                
                with col4:
                    # Download button
                    if st.button(f"📥 Download", key=f"download_{i}"):
                        file_path = Path(export['file_path'])
                        if file_path.exists():
                            st.markdown(f"📁 [{export['filename']}](file://{file_path.absolute()})")
                        else:
                            st.error("File not found")
                
                # Full file path
                st.code(export['file_path'])
        
    except Exception as e:
        st.error(f"Failed to load export history: {str(e)}")


def render_export_instructions() -> None:
    """Render instructions and information about the export functionality."""
    with st.expander("📖 Export Information", expanded=False):
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
    
    # Render main sections
    call_fragment("export.action", render_export_button)
    st.divider()
    call_fragment("export.history", render_export_history)
    st.divider()
    render_export_instructions()
    
    # Footer info
    st.markdown("---")
    st.caption(
        "💡 **Tip:** For very large ledgers (10,000+ rows), the export may take "
        "several seconds. The progress spinner will indicate when the export is complete."
    )

    render_debug_panel()


if __name__ == "__main__":
    main()
