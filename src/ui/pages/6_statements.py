"""
Monthly Statements Page

Generate per-associate statements showing funding, entitlement, and 50/50 split.
Partner-facing and internal-only sections with export functionality.
"""

from __future__ import annotations

import io
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import streamlit as st

from src.core.database import get_db_connection
from src.services.statement_service import (
    StatementService,
    StatementCalculations,
    PartnerFacingSection,
    InternalSection
)
from src.ui.helpers.fragments import (
    call_fragment,
    render_debug_panel,
    render_debug_toggle,
)
from src.ui.helpers.streaming import show_pdf_preview, show_success_toast
from src.ui.ui_components import advanced_section, form_gated_filters, load_global_styles
from src.ui.utils.formatters import format_utc_datetime
from src.ui.utils.state_management import render_reset_control, safe_rerun

PAGE_TITLE = "Statements"
PAGE_ICON = ":material/contract:"
STATEMENT_PDF_DIR = Path("data/exports/statements")


def _escape_pdf_text(value: str) -> str:
    """Escape characters reserved in PDF text objects."""
    return (
        value.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )


def _write_simple_pdf(lines: List[str], output_path: Path) -> None:
    """Write a minimal PDF file containing the provided lines."""
    content_lines = ["BT", "/F1 12 Tf", "16 TL", "72 720 Td"]
    for line in lines:
        content_lines.append(f"({_escape_pdf_text(line)}) Tj")
        content_lines.append("T*")
    content_lines.append("ET")
    content = "\n".join(content_lines)
    content_bytes = content.encode("utf-8")

    objects = [
        "1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        "2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
        "3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj\n",
        f"4 0 obj << /Length {len(content_bytes)} >>\nstream\n{content}\nendstream\nendobj\n",
        "5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
    ]

    buffer = io.BytesIO()
    buffer.write(b"%PDF-1.4\n")
    offsets = []
    for obj in objects:
        offsets.append(buffer.tell())
        buffer.write(obj.encode("utf-8"))
    xref_offset = buffer.tell()
    buffer.write(f"xref\n0 {len(objects) + 1}\n".encode("utf-8"))
    buffer.write(b"0000000000 65535 f \n")
    for offset in offsets:
        buffer.write(f"{offset:010d} 00000 n \n".encode("utf-8"))
    buffer.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF".encode(
            "utf-8"
        )
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(buffer.getvalue())


def generate_statement_pdf(
    calc: StatementCalculations,
    partner_section: PartnerFacingSection,
    internal_section: InternalSection,
) -> Path:
    """Generate a lightweight PDF summary for the statement."""
    cutoff_date = calc.cutoff_date.split("T")[0]
    pdf_path = STATEMENT_PDF_DIR / f"statement_{calc.associate_id}_{cutoff_date.replace('-', '')}.pdf"
    lines = [
        f"Statement for {calc.associate_name}",
        f"Cutoff Date: {cutoff_date}",
        partner_section.funding_summary,
        partner_section.entitlement_summary,
        partner_section.profit_loss_summary,
        f"Admin Share: {partner_section.split_calculation['admin_share']}",
        f"Associate Share: {partner_section.split_calculation['associate_share']}",
        internal_section.current_holdings,
        internal_section.reconciliation_delta,
    ]
    _write_simple_pdf(lines, pdf_path)
    return pdf_path

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
    st.subheader("ðŸ“Š Statement Parameters")
    
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
    
    st.caption("ðŸ’¡ All transactions up to and including this date will be included")
    
    return associate_id, cutoff_datetime


def render_statement_header(calc: StatementCalculations) -> None:
    """Render statement header with associate info and timestamps."""
    st.markdown("---")
    st.header(f"ðŸ“‹ Monthly Statement for {calc.associate_name}")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Period Ending", format_utc_datetime(calc.cutoff_date))
    with col2:
        st.metric("Generated", format_utc_datetime(calc.generated_at))
    with col3:
        st.metric("Timezone", "AWST")


def render_partner_facing_section(partner_section: PartnerFacingSection) -> None:
    """Render partner-facing statement section."""
    st.markdown("---")
    st.subheader("ðŸ’° Partner Statement")
    
    # Funding Summary
    st.markdown("##### Funding Summary")
    st.info(partner_section.funding_summary)
    st.caption("Total deposits minus withdrawals up to cutoff date")
    
    # Entitlement Summary
    st.markdown("##### Entitlement Summary")
    st.info(partner_section.entitlement_summary)
    st.caption("Total principal returned plus profit shares from all settled bets")
    
    # Profit/Loss Summary
    st.markdown("##### Profit/Loss Summary")
    if "ðŸŸ¢" in partner_section.profit_loss_summary:
        st.success(partner_section.profit_loss_summary)
    elif "ðŸ”´" in partner_section.profit_loss_summary:
        st.error(partner_section.profit_loss_summary)
    else:
        st.info(partner_section.profit_loss_summary)
    st.caption("Raw profit = Entitlement - Funding")
    
    # 50/50 Split Calculation
    st.markdown("##### 50/50 Split Calculation")
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Admin Share", partner_section.split_calculation["admin_share"])
    with col2:
        st.metric("Associate Share", partner_section.split_calculation["associate_share"])
    
    st.caption(partner_section.split_calculation["explanation"])


def render_internal_section(internal_section: InternalSection) -> None:
    """Render internal-only statement section."""
    st.markdown("---")
    st.subheader("ðŸ”’ Internal Reconciliation")
    
    # Current Holdings
    st.markdown("##### Current Holdings")
    st.info(internal_section.current_holdings)
    st.caption("Sum of all ledger entries for this associate")
    
    # Reconciliation Delta
    st.markdown("##### Reconciliation Delta")
    delta_emoji = internal_section.delta_emoji
    delta_status = internal_section.reconciliation_delta
    
    if delta_emoji == "ðŸŸ¢":
        st.success(f"{delta_emoji} {delta_status}")
    elif delta_emoji == "ðŸ”´":
        st.error(f"{delta_emoji} {delta_status}")
    else:
        st.warning(f"{delta_emoji} {delta_status}")
    
    st.caption("Delta = Current Holdings - Should Hold")


def render_export_options(calc: StatementCalculations, partner_section: PartnerFacingSection) -> None:
    """Render export functionality buttons."""
    st.markdown("---")
    st.subheader("ðŸ“¤ Export Options")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        # Copy to Clipboard (partner-facing only)
        clipboard_text = f"""
PARTNER STATEMENT - {calc.associate_name}
Period Ending: {calc.cutoff_date.split('T')[0]}

{partner_section.funding_summary}
{partner_section.entitlement_summary}
{partner_section.profit_loss_summary}

50/50 Split:
- Admin Share: {partner_section.split_calculation["admin_share"]}
- Associate Share: {partner_section.split_calculation["associate_share"]}

{partner_section.split_calculation["explanation"]}
        """.strip()
        
        if st.button("ðŸ“‹ Copy to Clipboard", key="copy_clipboard", width="stretch"):
            st.session_state.clipboard_text = clipboard_text
            st.success("âœ… Partner statement copied to session state!")
            st.code(clipboard_text)
    
    with col2:
        # Export to CSV
        if st.button("ðŸ“„ Export to CSV", key="export_csv", width="stretch"):
            with st.spinner("Generating CSV export..."):
                try:
                    export_service = StatementService()
                    transactions = export_service.get_associate_transactions(
                        calc.associate_id, calc.cutoff_date
                    )
                    
                    if transactions:
                        # Create DataFrame
                        df = pd.DataFrame(transactions)
                        
                        # Create temporary file
                        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f:
                            df.to_csv(f.name, index=False)
                            temp_path = f.name
                        
                        st.success(f"âœ… CSV exported with {len(transactions)} transactions")
                        st.download_button(
                            label="ðŸ“¥ Download CSV",
                            data=open(temp_path, 'rb').read(),
                            file_name=f"statement_{calc.associate_name}_{calc.cutoff_date.split('T')[0]}.csv",
                            mime="text/csv"
                        )
                        
                        # Clean up
                        Path(temp_path).unlink(missing_ok=True)
                    else:
                        st.info("No transactions found for this period")
                        
                except Exception as e:
                    st.error(f"âŒ CSV export failed: {str(e)}")
    
    with col3:
        st.markdown("### PDF Preview")
        st.caption("Preview and download options are available below.")


def render_generate_button(associate_id: int, cutoff_date: str) -> bool:
    """Render generate statement button with validation."""
    if not associate_id or not cutoff_date:
        st.warning("âš ï¸ Please select an associate and cutoff date")
        return False
    
    # Validate cutoff date is not in future
    statement_service = StatementService()
    if not statement_service.validate_cutoff_date(cutoff_date):
        st.error("âŒ Cutoff date cannot be in future")
        return False
    
    return st.button(
        "ðŸš€ Generate Statement",
        type="primary",
        width="stretch",
        key="generate_statement"
    )


def render_statement_details(calc: StatementCalculations, *, expanded: bool = False) -> None:
    """Render detailed transaction table."""
    with st.expander("ðŸ“Š Transaction Details", expanded=expanded):
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




def render_statement_pdf_preview(
    calc: StatementCalculations,
    partner_section: PartnerFacingSection,
    internal_section: InternalSection,
) -> None:
    """Generate and render PDF preview for the statement."""
    pdf_path = generate_statement_pdf(calc, partner_section, internal_section)
    st.markdown("### :material/picture_as_pdf: PDF Preview")
    show_pdf_preview(
        pdf_path,
        height=520,
        fallback_message="Update Streamlit or download the PDF below to preview.",
    )
    with open(pdf_path, "rb") as pdf_file:
        st.download_button(
            label=":material/download: Download PDF",
            data=pdf_file.read(),
            file_name=pdf_path.name,
            mime="application/pdf",
        )


def _render_statement_output(
    calc: StatementCalculations,
    *,
    options: Optional[Dict[str, object]] = None,
) -> None:
    """Render the complete statement output within a fragment."""
    options = options or {}
    show_internal = bool(options.get("show_internal_section", True))
    show_pdf = bool(options.get("show_pdf_preview", True))
    auto_expand_transactions = bool(options.get("auto_expand_transactions", False))

    statement_service = StatementService()
    partner_section = statement_service.format_partner_facing_section(calc)
    internal_section = statement_service.format_internal_section(calc)

    render_statement_header(calc)
    render_partner_facing_section(partner_section)
    if show_internal:
        render_internal_section(internal_section)
    render_export_options(calc, partner_section)
    if show_pdf:
        render_statement_pdf_preview(calc, partner_section, internal_section)
    render_statement_details(calc, expanded=auto_expand_transactions)

def render_validation_errors(errors: List[str]) -> None:
    """Render validation error messages."""
    for error in errors:
        st.error(f"âŒ {error}")


def main() -> None:
    """Main entry point for Statements page."""
    st.set_page_config(
        page_title=PAGE_TITLE,
        page_icon=PAGE_ICON,
        layout="wide"
    )
    load_global_styles()

    st.title(f"{PAGE_ICON} {PAGE_TITLE}")
    st.caption("Generate per-associate statements showing funding, entitlement, and 50/50 split")

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

    def _render_statement_options() -> Dict[str, bool]:
        col1, col2, col3 = st.columns(3)
        with col1:
            show_pdf_preview = st.checkbox(
                ":material/picture_as_pdf: Show PDF preview",
                value=True,
                key="statements_show_pdf",
            )
        with col2:
            show_internal_section = st.checkbox(
                ":material/admin_panel_settings: Show internal section",
                value=True,
                key="statements_show_internal",
            )
        with col3:
            auto_expand_transactions = st.checkbox(
                ":material/table_rows: Auto-expand transactions",
                value=False,
                key="statements_expand_transactions",
            )
        return {
            "show_pdf_preview": show_pdf_preview,
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
    
    # Generate button with validation
    if associate_id and cutoff_date:
        if render_generate_button(associate_id, cutoff_date):
            with st.spinner("Generating statement..."):
                try:
                    statement_service = StatementService()
                    calc = statement_service.generate_statement(associate_id, cutoff_date)
                    
                    st.session_state.current_statement = calc
                    st.session_state.statement_generated = True
                    st.success(f"Ã¢ÂœÂ… Statement generated for {calc.associate_name}")
                    show_success_toast(f"Statement generated for {calc.associate_name}")
                    safe_rerun()
                    
                except ValueError as e:
                    st.error(f"âŒ Validation Error: {str(e)}")
                except Exception as e:
                    st.error(f"âŒ Statement generation failed: {str(e)}")
    
    # Display generated statement
    if st.session_state.statement_generated and st.session_state.current_statement:
        calc = st.session_state.current_statement

        call_fragment(
            "statements.output",
            _render_statement_output,
            calc=calc,
            options=statement_options,
        )

    # Instructions
    # Instructions
    with st.expander("ðŸ“– Statement Information", expanded=False):
        st.markdown("""
        ### About Monthly Statements
        
        **Purpose:** Generate partner statements showing funding, entitlement, and profit splits.
        
        **Sections:**
        - **Partner Statement**: Shareable with associates showing funding, entitlement, and 50/50 split
        - **Internal Reconciliation**: Internal-only section showing current holdings vs. entitlement
        - **Transaction Details**: Complete transaction list for verification
        
        **Calculations:**
        - **Net Deposits**: SUM(DEPOSITS) - SUM(WITHDRAWALS)
        - **Should Hold**: SUM(principal_returned + per_surebet_share)
        - **Current Holding**: SUM(all ledger entries)
        - **Raw Profit**: Should Hold - Net Deposits
        - **Delta**: Current Holding - Should Hold
        
        **Export Options:**
        - **Copy to Clipboard**: Partner-facing section only
        - **Export to CSV**: Complete transaction list
        - **Export to PDF**: Coming soon
        
        **Important:** Statements are read-only snapshots and do not modify any ledger entries.
        """)

    render_debug_panel()


if __name__ == "__main__":
    main()




