"""
Incoming Bets page - displays bets awaiting review.

This page provides:
- Manual upload panel for uploading bet screenshots
- List of all incoming bets with metadata
- Screenshot previews
- Confidence scores with color coding
- Ingestion source indicators (Telegram vs Manual)
- Inline editing and approval/rejection actions (Epic 2)
"""

import streamlit as st
import structlog
from decimal import Decimal
from datetime import datetime

from src.core.database import get_db_connection
from src.services.bet_verification import BetVerificationService
from src.ui.components.manual_upload import render_manual_upload_panel
from src.ui.components.bet_card import render_bet_card
from src.ui.ui_components import load_global_styles
from src.ui.utils.navigation_links import render_navigation_link

logger = structlog.get_logger()


# Helper functions for approval/rejection workflow
def _handle_bet_actions(verification_service: BetVerificationService) -> None:
    """Handle approval and rejection actions from session state.

    Args:
        verification_service: BetVerificationService instance
    """
    # Check for approval actions
    approval_keys = [key for key in st.session_state.keys() if key.startswith("approve_bet_")]
    for key in approval_keys:
        bet_id = int(key.replace("approve_bet_", ""))
        action_data = st.session_state[key]

        if isinstance(action_data, dict):
            # Process approval with edits
            try:
                # Extract canonical event ID
                event_selection = action_data["event_selection"]
                canonical_event_id = None

                if event_selection == "[+] Create New Event":
                    # Hand over to the modal flow handled by bet_card
                    st.session_state[f"show_create_event_modal_{bet_id}"] = True
                    del st.session_state[key]
                    st.rerun()
                    return
                elif event_selection != "(None - Select Event)":
                    # Find event ID from selection
                    canonical_events = action_data["canonical_events"]
                    for event in canonical_events:
                        event_display = f"{event['normalized_event_name']} ({event['kickoff_time_utc'][:10] if event['kickoff_time_utc'] else 'TBD'})"
                        if event_display == event_selection:
                            canonical_event_id = event["id"]
                            break

                # Extract market code
                market_selection = action_data["market_selection"]
                market_code = None
                if market_selection != "(None - Select Market)":
                    market_code = market_selection.split("(")[-1].rstrip(")")

                # Build edited fields dictionary
                edited_fields = {}
                
                # Only include canonical_event_id if an event was selected
                if canonical_event_id is not None:
                    edited_fields["canonical_event_id"] = canonical_event_id
                
                # Only include market_code if a market was selected
                if market_code is not None:
                    edited_fields["market_code"] = market_code
                
                # Always include these fields
                edited_fields.update({
                    "period_scope": action_data["period"],
                    "line_value": str(Decimal(str(action_data["line"]))) if action_data["line"] else None,
                    "side": action_data["side"],
                    "stake_original": str(Decimal(str(action_data["stake"]))),
                    "odds_original": str(Decimal(str(action_data["odds"]))),
                    "payout": str(Decimal(str(action_data["payout"]))),
                    "currency": action_data["currency"],
                })

                # Capture manual event name input for auto-create fallback
                event_name_input = action_data.get("event_name_input")
                if canonical_event_id is None and event_name_input:
                    edited_fields["_event_name_override"] = event_name_input.strip()

                # Validate and approve
                verification_service.approve_bet(bet_id, edited_fields)
                st.success(f":material/check_circle: Bet #{bet_id} approved successfully!")
                render_navigation_link(
                    "pages/2_verified_bets.py",
                    label="Review Surebets",
                    icon=":material/target:",
                    help_text="Open 'Surebets' from navigation to continue coverage review.",
                )
                logger.info("bet_approved_via_ui", bet_id=bet_id)

            except ValueError as e:
                st.error(f"❌ Validation error: {str(e)}")
                logger.error("bet_approval_failed", bet_id=bet_id, error=str(e))
            except Exception as e:
                st.error(f"❌ Failed to approve bet: {str(e)}")
                logger.error("bet_approval_exception", bet_id=bet_id, error=str(e), exc_info=True)

            # Clean up session state
            del st.session_state[key]
            st.rerun()
        else:
            # Simple approval without edits (from non-editable mode)
            del st.session_state[key]

    # Check for rejection actions
    rejection_keys = [key for key in st.session_state.keys() if key.startswith("reject_bet_")]
    for key in rejection_keys:
        bet_id = int(key.replace("reject_bet_", ""))

        # Show rejection modal (modal handles its own state management)
        _show_rejection_modal(bet_id, verification_service, key)


def _show_rejection_modal(bet_id: int, verification_service: BetVerificationService, session_key: str) -> None:
    """Show modal dialog for bet rejection.

    Args:
        bet_id: ID of bet to reject
        verification_service: BetVerificationService instance
        session_key: The session state key that triggered this modal
    """
    @st.dialog(f"Reject Bet #{bet_id}?")
    def rejection_dialog():
        st.warning("Are you sure you want to reject this bet?")

        reason = st.text_area(
            "Rejection Reason (optional)",
            placeholder="e.g., 'Accumulator bet', 'Duplicate', 'Invalid screenshot'",
            max_chars=500,
            key=f"rejection_reason_{bet_id}"
        )

        col1, col2 = st.columns(2)
        with col1:
            if st.button("❌ Confirm Rejection", type="primary", width="stretch", key=f"confirm_reject_{bet_id}"):
                try:
                    verification_service.reject_bet(bet_id, reason if reason else None)
                    # Clean up session state
                    if session_key in st.session_state:
                        del st.session_state[session_key]
                    st.success(f":material/highlight_off: Bet #{bet_id} rejected successfully!")
                    render_navigation_link(
                        "pages/5_corrections.py",
                        label="Track Corrections",
                        icon=":material/edit_note:",
                        help_text="Open 'Corrections' via navigation to review rejection fallout.",
                    )
                    logger.info("bet_rejected_via_ui", bet_id=bet_id, reason=reason)
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Failed to reject bet: {str(e)}")
                    logger.error("bet_rejection_exception", bet_id=bet_id, error=str(e), exc_info=True)

        with col2:
            if st.button("Cancel", width="content", key=f"cancel_reject_{bet_id}"):
                # Clean up session state
                if session_key in st.session_state:
                    del st.session_state[session_key]
                st.rerun()

    rejection_dialog()


# Configure page
PAGE_TITLE = "Incoming Bets"
PAGE_ICON = ":material/inbox:"

st.set_page_config(page_title=PAGE_TITLE, layout="wide")
load_global_styles()

st.title(f"{PAGE_ICON} {PAGE_TITLE}")

# Manual upload panel at top (collapsible)
with st.expander(":material/cloud_upload: Upload Manual Bet", expanded=False):
    render_manual_upload_panel()

st.markdown("---")

# Database connection
db = get_db_connection()

# Initialize verification service for Epic 2 approval/rejection workflow
verification_service = BetVerificationService(db)

# Handle approval/rejection actions from session state
_handle_bet_actions(verification_service)

# Counters
try:
    counts = db.execute(
        """
        SELECT
            SUM(CASE WHEN status='incoming' THEN 1 ELSE 0 END) as waiting,
            SUM(CASE WHEN status='verified' AND date(updated_at_utc)=date('now') THEN 1 ELSE 0 END) as approved_today,
            SUM(CASE WHEN status='rejected' AND date(updated_at_utc)=date('now') THEN 1 ELSE 0 END) as rejected_today
        FROM bets
        """
    ).fetchone()

    col1, col2, col3 = st.columns(3)
    col1.metric("⏳ Waiting Review", counts["waiting"] or 0)
    col2.metric("✅ Approved Today", counts["approved_today"] or 0)
    col3.metric("❌ Rejected Today", counts["rejected_today"] or 0)

except Exception as e:
    logger.error("failed_to_load_counters", error=str(e))
    st.error("Failed to load counters")

st.markdown("---")

# Filter options
with st.expander("🔍 Filters", expanded=False):
    filter_col1, filter_col2 = st.columns(2)

    with filter_col1:
        # Filter by associate
        associates_data = db.execute(
            "SELECT DISTINCT display_alias FROM associates ORDER BY display_alias"
        ).fetchall()
        associate_filter = st.multiselect(
            "Filter by Associate",
            options=["All"] + [a["display_alias"] for a in associates_data],
            default=["All"],
        )

    with filter_col2:
        # Filter by confidence
        confidence_filter = st.selectbox(
            "Filter by Confidence",
            options=["All", "High (≥80%)", "Medium (50-79%)", "Low (<50%)", "Failed"],
            index=0,
        )

st.markdown("---")

# Incoming bets queue
st.subheader("📋 Bets Awaiting Review")

try:
    # Build query with filters
    query = """
        SELECT
            b.id as bet_id,
            b.screenshot_path,
            a.display_alias as associate,
            bk.bookmaker_name as bookmaker,
            b.ingestion_source,
            ce.normalized_event_name as canonical_event,
            b.selection_text,
            b.market_code,
            b.period_scope,
            b.line_value,
            b.side,
            b.stake_original as stake,
            b.odds_original as odds,
            b.payout,
            b.currency,
            b.kickoff_time_utc,
            b.normalization_confidence,
            b.is_multi,
            b.created_at_utc
        FROM bets b
        JOIN associates a ON b.associate_id = a.id
        JOIN bookmakers bk ON b.bookmaker_id = bk.id
        LEFT JOIN canonical_events ce ON b.canonical_event_id = ce.id
        WHERE b.status = 'incoming'
    """

    # Apply associate filter
    query_params = []
    if "All" not in associate_filter and associate_filter:
        placeholders = ",".join(["?" for _ in associate_filter])
        query += f" AND a.display_alias IN ({placeholders})"
        query_params.extend(associate_filter)

    # Apply confidence filter (cast TEXT to REAL for numeric comparison)
    if confidence_filter != "All":
        if confidence_filter == "High (≥80%)":
            query += " AND CAST(b.normalization_confidence AS REAL) >= 0.8"
        elif confidence_filter == "Medium (50-79%)":
            query += " AND CAST(b.normalization_confidence AS REAL) >= 0.5 AND CAST(b.normalization_confidence AS REAL) < 0.8"
        elif confidence_filter == "Low (<50%)":
            query += " AND CAST(b.normalization_confidence AS REAL) < 0.5"
        elif confidence_filter == "Failed":
            query += " AND (b.normalization_confidence IS NULL OR b.normalization_confidence = '')"

    query += " ORDER BY b.created_at_utc DESC"

    # Execute query
    incoming_bets = db.execute(query, query_params).fetchall()

    if not incoming_bets:
        st.info("✨ No bets awaiting review! Queue is empty.")
    else:
        st.caption(f"Showing {len(incoming_bets)} bet(s)")

        # Render each bet card with inline editing (Epic 2)
        for bet in incoming_bets:
            bet_dict = dict(bet)  # Convert Row to dict
            render_bet_card(bet_dict, show_actions=True, editable=True, verification_service=verification_service)

except Exception as e:
    logger.error("failed_to_load_incoming_bets", error=str(e), exc_info=True)
    st.error(f"Failed to load incoming bets: {str(e)}")
    st.exception(e)

# Auto-refresh option
st.markdown("---")
if st.checkbox("🔄 Auto-refresh every 30 seconds"):
    import time

    time.sleep(30)
    st.rerun()
