"""
Delta Provenance page - view associate delta breakdown by counterparty.

This page provides:
- Delta provenance breakdown showing surpluses/shortfalls by counterparty
- Transaction-level details for each delta
- Filtering and search capabilities
- Export functionality for analysis
"""

import streamlit as st
import structlog
import sqlite3
from typing import List, Dict, Optional, Tuple
from datetime import datetime, date, timedelta
from decimal import Decimal

from src.core.database import get_db_connection
from src.services.delta_provenance_service import DeltaProvenanceService
from src.ui.ui_components import load_global_styles
from src.ui.utils.formatters import (
    format_utc_datetime_local,
    format_currency_with_symbol,
)
from src.ui.utils.validators import validate_associate_id

logger = structlog.get_logger()

load_global_styles()

# ============================================================================
# PAGE CONFIG AND INITIALIZATION
# ============================================================================

PAGE_TITLE = "Delta Provenance"
PAGE_ICON = ":material/source:"

st.set_page_config(
    page_title=PAGE_TITLE, 
    page_icon=PAGE_ICON, 
    layout="wide"
)

st.title(f"{PAGE_ICON} {PAGE_TITLE}")
st.markdown("View associate deltas broken down by counterparty and surebet")

# ============================================================================
# DATABASE QUERY FUNCTIONS
# ============================================================================

def get_all_associates(conn: sqlite3.Connection) -> List[Dict]:
    """Get all associates for dropdown selection.
    
    Args:
        conn: Database connection
        
    Returns:
        List of associate dictionaries
    """
    cursor = conn.execute(
        "SELECT id, display_alias FROM associates ORDER BY display_alias ASC"
    )
    return [{"id": row["id"], "alias": row["display_alias"]} for row in cursor.fetchall()]

def get_delta_summary(
    associate_id: int, 
    conn: sqlite3.Connection
) -> Dict:
    """Get delta summary for an associate.
    
    Args:
        associate_id: ID of the associate
        conn: Database connection
        
    Returns:
        Summary dictionary with totals
    """
    cursor = conn.execute(
        """
        SELECT 
            COUNT(*) as total_transactions,
            SUM(CASE WHEN amount_eur > 0 THEN amount_eur ELSE 0 END) as total_surplus,
            SUM(CASE WHEN amount_eur < 0 THEN ABS(amount_eur) ELSE 0 END) as total_deficit,
            SUM(amount_eur) as net_delta
        FROM (
            SELECT 
                CASE 
                    WHEN ssl.winner_associate_id = ? THEN ssl.amount_eur
                    ELSE -ssl.amount_eur
                END as amount_eur
            FROM surebet_settlement_links ssl
            WHERE ssl.winner_associate_id = ? OR ssl.loser_associate_id = ?
        ) delta_query
        """,
        (associate_id, associate_id, associate_id)
    )
    
    row = cursor.fetchone()
    return {
        "total_transactions": row["total_transactions"] or 0,
        "total_surplus": Decimal(row["total_surplus"] or "0.00"),
        "total_deficit": Decimal(row["total_deficit"] or "0.00"),
        "net_delta": Decimal(row["net_delta"] or "0.00"),
    }

def get_counterparty_breakdown(
    associate_id: int,
    conn: sqlite3.Connection
) -> List[Dict]:
    """Get counterparty breakdown for an associate.
    
    Args:
        associate_id: ID of the associate
        conn: Database connection
        
    Returns:
        List of counterparty dictionaries
    """
    query = """
        SELECT 
            CASE 
                WHEN ssl.winner_associate_id = ? THEN ssl.loser_associate_id
                ELSE ssl.winner_associate_id
            END as counterparty_id,
            CASE 
                WHEN ssl.winner_associate_id = ? THEN loser.display_alias
                ELSE winner.display_alias
            END as counterparty_alias,
            COUNT(*) as transaction_count,
            SUM(CASE 
                WHEN ssl.winner_associate_id = ? THEN ssl.amount_eur
                ELSE -ssl.amount_eur
            END) as net_amount_eur,
            SUM(CASE 
                WHEN ssl.winner_associate_id = ? THEN ssl.amount_eur
                ELSE 0
            END) as total_won_eur,
            SUM(CASE 
                WHEN ssl.loser_associate_id = ? THEN ssl.amount_eur
                ELSE 0
            END) as total_lost_eur,
            MIN(ssl.created_at_utc) as first_transaction,
            MAX(ssl.created_at_utc) as last_transaction
        FROM surebet_settlement_links ssl
        JOIN associates winner ON ssl.winner_associate_id = winner.id
        JOIN associates loser ON ssl.loser_associate_id = loser.id
        WHERE (ssl.winner_associate_id = ? OR ssl.loser_associate_id = ?)
        GROUP BY counterparty_id, counterparty_alias
        ORDER BY net_amount_eur DESC
    """
    
    cursor = conn.execute(query, 
        (associate_id, associate_id, associate_id, associate_id, 
         associate_id, associate_id, associate_id))
    
    results = []
    for row in cursor.fetchall():
        results.append({
            "counterparty_id": row["counterparty_id"],
            "counterparty_alias": row["counterparty_alias"],
            "transaction_count": row["transaction_count"],
            "net_amount_eur": Decimal(row["net_amount_eur"]),
            "total_won_eur": Decimal(row["total_won_eur"] or "0.00"),
            "total_lost_eur": Decimal(row["total_lost_eur"] or "0.00"),
            "first_transaction": row["first_transaction"],
            "last_transaction": row["last_transaction"],
        })
    
    return results

# ============================================================================
# UI COMPONENTS
# ============================================================================

def render_summary_metrics(summary: Dict) -> None:
    """Render summary metrics at top of page.
    
    Args:
        summary: Summary dictionary with totals
    """
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            "Total Transactions",
            summary["total_transactions"],
            help="Total number of settlement transactions"
        )
    
    with col2:
        net_delta_color = "normal" if summary["net_delta"] >= 0 else "inverse"
        st.metric(
            "Net Delta",
            f"€{summary['net_delta']:.2f}",
            delta_color=net_delta_color,
            help="Positive = overall surplus, Negative = overall deficit"
        )
    
    with col3:
        st.metric(
            "Total Surplus",
            f"€{summary['total_surplus']:.2f}",
            help="Total amount won from counterparties"
        )
    
    with col4:
        st.metric(
            "Total Deficit",
            f"€{summary['total_deficit']:.2f}",
            help="Total amount lost to counterparties"
        )

def render_counterparty_table(
    counterparties: List[Dict], 
    selected_associate_id: int
) -> None:
    """Render table of counterparties with their breakdowns.
    
    Args:
        counterparties: List of counterparty dictionaries
        selected_associate_id: ID of the selected associate
    """
    if not counterparties:
        st.info("No transactions found for this associate.")
        return
    
    st.subheader("Counterparty Breakdown")
    
    for counterparty in counterparties:
        # Expandable row for each counterparty
        with st.expander(
            f"{counterparty['counterparty_alias']} - "
            f"Net: €{counterparty['net_amount_eur']:.2f} "
            f"({counterparty['transaction_count']} transactions)",
            expanded=False
        ):
            # Counterparty details
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.markdown("**Transaction Summary**")
                st.text(f"Total Transactions: {counterparty['transaction_count']}")
                st.text(f"Net Amount: €{counterparty['net_amount_eur']:.2f}")
                st.text(f"First: {format_utc_datetime_local(counterparty['first_transaction'])}")
                st.text(f"Last: {format_utc_datetime_local(counterparty['last_transaction'])}")
            
            with col2:
                st.markdown("**Won from Counterparty**")
                st.text(f"Amount: €{counterparty['total_won_eur']:.2f}")
                
                if counterparty['total_won_eur'] > 0:
                    st.success("Positive balance with this counterparty")
                else:
                    st.info("No wins from this counterparty")
            
            with col3:
                st.markdown("**Lost to Counterparty**")
                st.text(f"Amount: €{counterparty['total_lost_eur']:.2f}")
                
                if counterparty['total_lost_eur'] > 0:
                    st.warning("Negative balance with this counterparty")
                else:
                    st.info("No losses to this counterparty")
            
            # View details button
            if st.button(
                "🔍 View Transaction Details",
                key=f"details_{counterparty['counterparty_id']}"
            ):
                st.session_state[f"show_details_{counterparty['counterparty_id']}"] = True
                st.rerun()

def render_transaction_details(
    associate_id: int,
    counterparty_id: int,
    delta_service: DeltaProvenanceService
) -> None:
    """Render detailed transaction list for a specific counterparty.
    
    Args:
        associate_id: ID of the primary associate
        counterparty_id: ID of the counterparty
        delta_service: DeltaProvenanceService instance
    """
    st.subheader(f"Transaction Details")
    
    try:
        entries, summary = delta_service.get_associate_delta_provenance(
            associate_id=associate_id,
            limit=100
        )
        
        # Filter for specific counterparty
        counterparty_entries = [
            entry for entry in entries 
            if entry.counterparty_associate_id == counterparty_id
        ]
        
        if not counterparty_entries:
            st.info("No detailed transactions found for this counterparty.")
            return
        
        # Transaction table
        for entry in counterparty_entries:
            col1, col2, col3, col4, col5 = st.columns([2, 2, 2, 2, 2])
            
            with col1:
                st.markdown(f"**Surebet {entry.surebet_id}**")
            
            with col2:
                amount_color = "green" if entry.is_positive else "red"
                amount_text = f"€{entry.amount_eur:.2f}"
                if entry.is_positive:
                    st.markdown(f"<span style='color:green'>{amount_text}</span>", unsafe_allow_html=True)
                else:
                    st.markdown(f"<span style='color:red'>{amount_text}</span>", unsafe_allow_html=True)
            
            with col3:
                st.text(entry.counterparty_alias)
            
            with col4:
                st.text(format_utc_datetime_local(entry.created_at_utc))
            
            with col5:
                if entry.note:
                    st.text(entry.note[:50] + "..." if len(entry.note) > 50 else entry.note)
        
    except Exception as e:
        st.error(f"Error loading transaction details: {str(e)}")
        logger.error("transaction_details_error", associate_id=associate_id, 
                   counterparty_id=counterparty_id, error=str(e))

# ============================================================================
# MAIN PAGE LOGIC
# ============================================================================

def main():
    """Main page rendering logic."""
    
    # Initialize session state
    if "selected_associate_id" not in st.session_state:
        st.session_state.selected_associate_id = None
    
    # Get database connection
    conn = get_db_connection()
    delta_service = DeltaProvenanceService(conn)
    
    # Associate selection
    associates = get_all_associates(conn)
    
    if not associates:
        st.error("No associates found in the system.")
        return
    
    # Create associate selection dropdown
    associate_options = {assoc["id"]: assoc["alias"] for assoc in associates}
    selected_alias = st.selectbox(
        "Select Associate",
        options=list(associate_options.values()),
        index=None,
        placeholder="Choose an associate to view delta provenance..."
    )
    
    if selected_alias:
        # Find the selected associate ID
        selected_associate_id = None
        for assoc_id, assoc_alias in associate_options.items():
            if assoc_alias == selected_alias:
                selected_associate_id = assoc_id
                break
        
        if selected_associate_id:
            st.session_state.selected_associate_id = selected_associate_id
            
            # Get summary data
            summary = get_delta_summary(selected_associate_id, conn)
            
            # Render summary metrics
            render_summary_metrics(summary)
            
            # Get counterparty breakdown
            counterparties = get_counterparty_breakdown(selected_associate_id, conn)
            
            # Render counterparty table
            render_counterparty_table(counterparties, selected_associate_id)
            
            # Check for transaction detail views
            for counterparty in counterparties:
                detail_key = f"show_details_{counterparty['counterparty_id']}"
                if st.session_state.get(detail_key, False):
                    render_transaction_details(
                        selected_associate_id,
                        counterparty['counterparty_id'],
                        delta_service
                    )
                    
                    if st.button("← Back to Counterparty List"):
                        st.session_state[detail_key] = False
                        st.rerun()

# Run the main function
if __name__ == "__main__" or "pytest" in globals():
    try:
        main()
    except Exception as e:
        st.error(f"An error occurred: {str(e)}")
        logger.error("delta_provenance_page_error", error=str(e))
