"""
Post-Settlement Corrections Interface.

This page allows operators to apply forward-only corrections to bookmaker holdings
by creating new BOOKMAKER_CORRECTION ledger entries. All corrections are auditable
and maintain immutability of existing ledger records.
"""

import streamlit as st
from decimal import Decimal, InvalidOperation
from typing import List, Dict, Optional
from src.core.database import get_db_connection
from src.services.correction_service import CorrectionService, CorrectionError
from src.ui.ui_components import load_global_styles
from src.ui.utils.formatters import format_utc_datetime_local
from src.utils.logging_config import get_logger
from src.ui.utils.state_management import safe_rerun

logger = get_logger(__name__)


# Configure page
PAGE_TITLE = "Corrections"
PAGE_ICON = ":material/edit_note:"

st.set_page_config(page_title=PAGE_TITLE, layout="wide")
load_global_styles()
st.title(f"{PAGE_ICON} {PAGE_TITLE}")

st.markdown(
    """
Apply forward-only corrections to bookmaker holdings. All corrections create new
BOOKMAKER_CORRECTION ledger entries without modifying existing records.

**Common Use Cases:**
- Late VOID corrections (refunds not processed during settlement)
- Grading error fixes (incorrect win/loss classification)
- Bookmaker fee deductions
- Manual balance adjustments
"""
)

# Display success message if present
if "correction_success_message" in st.session_state:
    st.success(st.session_state.pop("correction_success_message"))

# ========================================
# Helper Functions
# ========================================


def load_associates() -> List[Dict]:
    """Load all associates for selection."""
    db = get_db_connection()
    cursor = db.execute(
        """
        SELECT id, display_alias, home_currency
        FROM associates
        ORDER BY display_alias
    """
    )
    associates = []
    for row in cursor.fetchall():
        associates.append(
            {
                "id": row["id"],
                "display_alias": row["display_alias"],
                "home_currency": row["home_currency"],
            }
        )
    db.close()
    return associates


def load_bookmakers_for_associate(associate_id: int) -> List[Dict]:
    """Load bookmakers for a specific associate."""
    db = get_db_connection()
    cursor = db.execute(
        """
        SELECT id, bookmaker_name, is_active
        FROM bookmakers
        WHERE associate_id = ?
        ORDER BY bookmaker_name
    """,
        (associate_id,),
    )
    bookmakers = []
    for row in cursor.fetchall():
        bookmakers.append(
            {
                "id": row["id"],
                "bookmaker_name": row["bookmaker_name"],
                "is_active": row["is_active"],
            }
        )
    db.close()
    return bookmakers


def format_correction_row(correction: Dict) -> Dict:
    """Format correction data for display."""
    amount_native = correction["amount_native"]
    amount_eur = correction["amount_eur"]
    currency = correction["native_currency"]

    # Format amounts with sign
    amount_native_str = f"{amount_native:+.2f} {currency}"
    amount_eur_str = f"{amount_eur:+.2f} EUR"

    return {
        "ID": correction["id"],
        "Timestamp": format_utc_datetime_local(correction["created_at_utc"]),
        "Associate": correction["display_alias"],
        "Bookmaker": correction["bookmaker_name"],
        "Amount (Native)": amount_native_str,
        "FX Rate": f"{correction['fx_rate_snapshot']:.6f}",
        "Amount (EUR)": amount_eur_str,
        "Note": correction["note"],
        "Created By": correction["created_by"],
    }


# ========================================
# Correction Form
# ========================================

prefill_payload = st.session_state.get("correction_prefill")
if prefill_payload and not st.session_state.get("correction_prefill_applied"):
    raw_native = prefill_payload.get("amount_native")
    raw_eur = prefill_payload.get("amount_eur")
    prefill_amount = ""

    for candidate in (raw_native, raw_eur):
        if candidate is None:
            continue
        try:
            dec_value = Decimal(str(candidate))
        except (InvalidOperation, TypeError):
            continue
        else:
            prefill_amount = f"{dec_value:+.2f}"
            break

    st.session_state["correction_amount"] = prefill_amount
    st.session_state["correction_note"] = prefill_payload.get("note", "")
    st.session_state["correction_currency"] = prefill_payload.get("native_currency", "EUR")
    st.session_state["correction_prefill_associate_id"] = prefill_payload.get("associate_id")
    st.session_state["correction_prefill_bookmaker_id"] = prefill_payload.get("bookmaker_id")
    st.session_state["correction_prefill_applied"] = True

if prefill_payload:
    st.info("Bookmaker Drilldown pre-filled the correction form. Review and submit.")
else:
    st.session_state.setdefault("correction_amount", "")
    st.session_state.setdefault("correction_note", "")
    st.session_state.setdefault("correction_currency", "EUR")

st.header("Apply Correction")

# Associate selection (outside form to allow dynamic updates)
associates = load_associates()
if not associates:
    st.error("No associates found. Please create associates first.")
    st.stop()

associate_options = {
    f"{a['display_alias']} ({a['home_currency']})": a["id"]
    for a in associates
}
prefill_associate_id = st.session_state.get("correction_prefill_associate_id")
if prefill_associate_id is not None:
    for option_label, option_id in associate_options.items():
        if option_id == prefill_associate_id:
            st.session_state.setdefault("associate_selection", option_label)
            break
else:
    st.session_state.setdefault("associate_selection", next(iter(associate_options.keys())))

selected_associate = st.selectbox(
    "Associate *",
    options=list(associate_options.keys()),
    help="Select the associate receiving the correction",
    key="associate_selection",
)
associate_id = associate_options[selected_associate]

# Get selected associate details
selected_associate_data = next(a for a in associates if a["id"] == associate_id)
associate_home_currency = selected_associate_data["home_currency"]

# Load bookmakers for selected associate
bookmakers = load_bookmakers_for_associate(associate_id)

st.markdown("---")

# Form for remaining fields
with st.form("correction_form", clear_on_submit=True):
    col1, col2 = st.columns(2)

    with col1:
        # Bookmaker selection
        if not bookmakers:
            st.warning(
                f"No bookmakers found for {selected_associate.split(' (')[0]}. "
                "Please add bookmakers first."
            )
            bookmaker_id = None
            selected_bookmaker = None
        else:
            bookmaker_options = {
                f"{b['bookmaker_name']} {'(inactive)' if not b['is_active'] else ''}": b[
                    "id"
                ]
                for b in bookmakers
            }
            prefill_bookmaker_id = st.session_state.get("correction_prefill_bookmaker_id")
            if prefill_bookmaker_id is not None:
                for option_label, option_id in bookmaker_options.items():
                    if option_id == prefill_bookmaker_id:
                        st.session_state.setdefault("bookmaker_selection", option_label)
                        break
            else:
                st.session_state.setdefault(
                    "bookmaker_selection", next(iter(bookmaker_options.keys()))
                )
            selected_bookmaker = st.selectbox(
                "Bookmaker *",
                options=list(bookmaker_options.keys()),
                help="Select the bookmaker account to correct",
                key="bookmaker_selection",
            )
            bookmaker_id = bookmaker_options[selected_bookmaker]

        # Currency selection (default to associate's home currency)
        currency_options = ["EUR", "USD", "GBP", "AUD", "CAD"]
        current_currency = st.session_state.get("correction_currency", associate_home_currency)
        if current_currency not in currency_options:
            current_currency = associate_home_currency if associate_home_currency in currency_options else "EUR"
            st.session_state["correction_currency"] = current_currency
        default_currency_index = currency_options.index(current_currency)
        currency = st.selectbox(
            "Currency *",
            options=currency_options,
            index=default_currency_index,
            help="Select the currency for this correction (defaults to associate's home currency)",
            key="correction_currency",
        )

    with col2:
        # Amount input
        amount_str = st.text_input(
            "Correction Amount *",
            value=st.session_state.get("correction_amount", ""),
            placeholder="e.g., +100.50 or -25.00",
            help="Positive = increase holdings, Negative = decrease holdings",
            key="correction_amount",
        )

    # Note field (full width)
    note = st.text_area(
        "Explanatory Note *",
        value=st.session_state.get("correction_note", ""),
        placeholder="e.g., Late VOID correction for Bet #123",
        help="Required: Explain why this correction is being applied",
        max_chars=500,
        key="correction_note",
    )

    # Submit button
    submitted = st.form_submit_button(
        "Apply Correction",
        type="primary",
        width="stretch",
    )

    if submitted:
        # Validate inputs
        errors = []

        if not bookmaker_id:
            errors.append("Please select a valid bookmaker")

        if not amount_str or not amount_str.strip():
            errors.append("Correction amount is required")
        else:
            try:
                # Parse amount (handle +/- prefix)
                amount_clean = amount_str.strip().replace("+", "")
                amount_native = Decimal(amount_clean)
            except (InvalidOperation, ValueError):
                errors.append(f"Invalid amount format: {amount_str}")
                amount_native = None

        if not note or not note.strip():
            errors.append("Explanatory note is required")

        # Display errors if any
        if errors:
            for error in errors:
                st.error(error)
        else:
            # Apply correction
            try:
                service = CorrectionService()
                entry_id = service.apply_correction(
                    associate_id=associate_id,
                    bookmaker_id=bookmaker_id,
                    amount_native=amount_native,
                    native_currency=currency,
                    note=note.strip(),
                    created_by="local_user",
                )
                service.close()

                # Show success message with entry ID
                st.session_state["correction_success_message"] = (
                    f"✅ Correction applied successfully! "
                    f"Ledger Entry ID: {entry_id}"
                )
                st.session_state.pop("correction_prefill", None)
                st.session_state.pop("correction_prefill_applied", None)
                st.session_state.pop("correction_prefill_associate_id", None)
                st.session_state.pop("correction_prefill_bookmaker_id", None)
                st.session_state["correction_amount"] = ""
                st.session_state["correction_note"] = ""
                safe_rerun()

            except CorrectionError as e:
                st.error(f"Correction failed: {e}")
                logger.error(
                    "correction_ui_error",
                    associate_id=associate_id,
                    bookmaker_id=bookmaker_id,
                    error=str(e),
                )
            except Exception as e:
                st.error(f"Unexpected error: {e}")
                logger.error(
                    "correction_unexpected_error",
                    associate_id=associate_id,
                    bookmaker_id=bookmaker_id,
                    error=str(e),
                    exc_info=True,
                )

# ========================================
# Recent Corrections History
# ========================================

st.header("Recent Corrections (Last 30 Days)")

# Filter options
col1, col2 = st.columns([3, 1])
with col1:
    filter_associate_options = ["All Associates"] + [
        a["display_alias"] for a in associates
    ]
    filter_associate = st.selectbox(
        "Filter by Associate",
        options=filter_associate_options,
        key="filter_associate",
    )

with col2:
    filter_days = st.number_input(
        "Days to show",
        min_value=1,
        max_value=365,
        value=30,
        step=1,
        key="filter_days",
    )

# Load corrections
service = CorrectionService()
try:
    if filter_associate == "All Associates":
        corrections = service.get_corrections_since(days=filter_days)
    else:
        # Find associate ID
        associate_id_filter = next(
            a["id"] for a in associates if a["display_alias"] == filter_associate
        )
        corrections = service.get_corrections_since(
            days=filter_days, associate_id=associate_id_filter
        )
finally:
    service.close()

if not corrections:
    st.info("No corrections found for the selected criteria.")
else:
    # Format corrections for display
    formatted_corrections = [format_correction_row(c) for c in corrections]

    # Display as dataframe
    st.dataframe(
        formatted_corrections,
        width="stretch",
        hide_index=True,
    )

    # Summary statistics
    st.subheader("Summary")
    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Total Corrections", len(corrections))

    with col2:
        total_eur = sum(c["amount_eur"] for c in corrections)
        st.metric("Net Impact (EUR)", f"{total_eur:+.2f}")

    with col3:
        positive_count = sum(1 for c in corrections if c["amount_eur"] > 0)
        negative_count = len(corrections) - positive_count
        st.metric(
            "Positive / Negative",
            f"{positive_count} / {negative_count}",
        )

# ========================================
# Footer Notes
# ========================================

st.markdown("---")
st.caption(
    """
**Important Notes:**
- All corrections create NEW ledger entries (type: BOOKMAKER_CORRECTION)
- Existing ledger entries are NEVER modified or deleted
- FX rates are frozen at the time of correction
- All corrections require an explanatory note for audit trail
"""
)
