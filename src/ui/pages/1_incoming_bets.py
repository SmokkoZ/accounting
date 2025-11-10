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

from decimal import Decimal
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Set

import streamlit as st
import structlog

from src.ui.cache import get_cached_connection, invalidate_query_cache, query_df
from src.services.bet_verification import BetVerificationService
from src.services.matching_service import MatchingService, MatchingSuggestions
from src.ui.components.manual_upload import render_manual_upload_panel
from src.ui.components.bet_card import render_bet_card
from src.ui.helpers import auto_refresh as auto_refresh_helper
from src.ui.helpers import saved_views
from src.ui.helpers import url_state
from src.ui.helpers.fragments import (
    call_fragment,
    fragments_supported,
    render_debug_panel,
)
from src.ui.utils import feature_flags
from src.ui.ui_components import form_gated_filters, load_global_styles
from src.ui.utils.navigation_links import render_navigation_link
from src.ui.utils.pagination import apply_pagination, get_total_count, paginate
from src.ui.utils.performance import track_timing
from src.ui.utils.state_management import render_reset_control, safe_rerun

logger = structlog.get_logger()

_FILTER_FORM_KEY = "incoming_filters"
_ASSOCIATE_FILTER_KEY = "incoming_filters_associates"
_BOOKMAKER_FILTER_KEY = "incoming_filters_bookmakers"
_CONFIDENCE_FILTER_KEY = "incoming_filters_confidence"

_BOOKMAKER_QUERY_KEY = "bookmaker"
_CONFIDENCE_QUERY_KEY = "confidence"

_CONFIDENCE_OPTIONS: Sequence[tuple[str, Optional[str]]] = (
    ("All", None),
    ("High (>=80%)", "high"),
    ("Medium (50-79%)", "medium"),
    ("Low (<50%)", "low"),
    ("Failed", "failed"),
)

_SELECTION_RESET_KEY = "_incoming_bets_reset_selected_ids"


def _schedule_selection_reset(bet_ids: Sequence[int]) -> None:
    """Mark bet selection checkboxes for reset on the next rerun."""
    if not bet_ids:
        return

    pending: Set[int] = set()
    existing = st.session_state.get(_SELECTION_RESET_KEY)
    if isinstance(existing, (list, tuple, set)):
        for value in existing:
            try:
                pending.add(int(value))
            except (TypeError, ValueError):
                continue

    for bet_id in bet_ids:
        try:
            pending.add(int(bet_id))
        except (TypeError, ValueError):
            continue

    st.session_state[_SELECTION_RESET_KEY] = list(pending)


def _consume_selection_reset_ids() -> Set[int]:
    """Return bet IDs scheduled for reset and clear the marker."""
    raw_ids = st.session_state.pop(_SELECTION_RESET_KEY, None)
    if raw_ids is None:
        return set()

    if not isinstance(raw_ids, (list, tuple, set)):
        raw_ids = [raw_ids]

    reset_ids: Set[int] = set()
    for value in raw_ids:
        try:
            reset_ids.add(int(value))
        except (TypeError, ValueError):
            continue
    return reset_ids


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
            if action_data.get("auto_approval"):
                try:
                    edited_fields: Dict[str, Any] = {}

                    if action_data.get("canonical_event_id"):
                        edited_fields["canonical_event_id"] = action_data[
                            "canonical_event_id"
                        ]
                    if action_data.get("market_code"):
                        edited_fields["market_code"] = action_data["market_code"]
                    if action_data.get("canonical_market_id"):
                        edited_fields["canonical_market_id"] = action_data[
                            "canonical_market_id"
                        ]
                    if action_data.get("period_scope"):
                        edited_fields["period_scope"] = action_data["period_scope"]
                    if action_data.get("line_value") is not None:
                        edited_fields["line_value"] = action_data["line_value"]
                    if action_data.get("side"):
                        edited_fields["side"] = action_data["side"]

                    if action_data.get("stake_original") is not None:
                        edited_fields["stake_original"] = str(
                            Decimal(str(action_data["stake_original"]))
                        )
                    if action_data.get("odds_original") is not None:
                        edited_fields["odds_original"] = str(
                            Decimal(str(action_data["odds_original"]))
                        )
                    if action_data.get("payout") is not None:
                        edited_fields["payout"] = str(
                            Decimal(str(action_data["payout"]))
                        )
                    if action_data.get("currency"):
                        edited_fields["currency"] = action_data["currency"]

                    verification_service.approve_bet(bet_id, edited_fields)
                    st.success(
                        f":material/flash_on: Bet #{bet_id} approved with suggested match."
                    )
                    logger.info("bet_auto_approved", bet_id=bet_id)
                    invalidate_query_cache()
                except Exception as exc:
                    st.error(f"Auto-approval failed: {exc}")
                    logger.error(
                        "bet_auto_approval_failed", bet_id=bet_id, error=str(exc)
                    )
                finally:
                    del st.session_state[key]
                    safe_rerun()
                return

            # Process approval with edits
            try:
                # Extract canonical event ID
                event_selection = action_data["event_selection"]
                canonical_event_id = None

                if event_selection == "[+] Create New Event":
                    # Hand over to the modal flow handled by bet_card
                    st.session_state[f"show_create_event_modal_{bet_id}"] = True
                    del st.session_state[key]
                    safe_rerun()
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
                    "pages/2_surebets_summary.py",
                    label="Review Surebets",
                    icon=":material/target:",
                    help_text="Open 'Surebets' from navigation to continue coverage review.",
                )
                logger.info("bet_approved_via_ui", bet_id=bet_id)
                invalidate_query_cache()

            except ValueError as e:
                st.error(f"âŒ Validation error: {str(e)}")
                logger.error("bet_approval_failed", bet_id=bet_id, error=str(e))
            except Exception as e:
                st.error(f"âŒ Failed to approve bet: {str(e)}")
                logger.error("bet_approval_exception", bet_id=bet_id, error=str(e), exc_info=True)

            # Clean up session state
            del st.session_state[key]
            safe_rerun()
        else:
            # Simple approval without edits (from non-editable mode)
            del st.session_state[key]

    # Check for rejection actions
    rejection_keys = [key for key in st.session_state.keys() if key.startswith("reject_bet_")]
    for key in rejection_keys:
        bet_id = int(key.replace("reject_bet_", ""))

        # Show rejection modal (modal handles its own state management)
        _show_rejection_modal(bet_id, key)


def _reject_bet_with_fresh_connection(
    bet_id: int, rejection_reason: Optional[str] = None
) -> None:
    """Reject a bet using the cached database connection."""
    db_action = get_cached_connection()
    BetVerificationService(db_action).reject_bet(bet_id, rejection_reason)
    invalidate_query_cache()


def _render_rejection_content(bet_id: int, session_key: str) -> None:
    """Shared UI between dialog and fallback container."""
    st.warning("Are you sure you want to reject this bet?")

    reason = st.text_area(
        "Rejection Reason (optional)",
        placeholder="e.g., 'Accumulator bet', 'Duplicate', 'Invalid screenshot'",
        max_chars=500,
        key=f"rejection_reason_{bet_id}",
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button(
            ":material/highlight_off: Confirm Rejection",
            type="primary",
            width="stretch",
            key=f"confirm_reject_{bet_id}",
        ):
            try:
                cleaned_reason = reason.strip() if isinstance(reason, str) else None
                _reject_bet_with_fresh_connection(bet_id, cleaned_reason)
                if session_key in st.session_state:
                    del st.session_state[session_key]
                st.success(f":material/highlight_off: Bet #{bet_id} rejected successfully!")
                render_navigation_link(
                    "pages/5_corrections.py",
                    label="Track Corrections",
                    icon=":material/edit_note:",
                    help_text="Open 'Corrections' via navigation to review rejection fallout.",
                )
                logger.info(
                    "bet_rejected_via_ui",
                    bet_id=bet_id,
                    reason=cleaned_reason,
                )
                safe_rerun()
            except Exception as e:
                st.error(f":material/error: Failed to reject bet: {str(e)}")
                logger.error(
                    "bet_rejection_exception",
                    bet_id=bet_id,
                    error=str(e),
                    exc_info=True,
                )

    with col2:
        if st.button("Cancel", width="content", key=f"cancel_reject_{bet_id}"):
            if session_key in st.session_state:
                del st.session_state[session_key]
            safe_rerun()


def _show_rejection_modal(bet_id: int, session_key: str) -> None:
    """Show modal dialog for bet rejection with graceful fallback."""

    def _render() -> None:
        _render_rejection_content(bet_id, session_key)

    title = f"Reject Bet #{bet_id}?"
    if feature_flags.supports_dialogs():

        @st.dialog(title)
        def rejection_dialog() -> None:
            _render()

        rejection_dialog()
    else:
        with st.container(border=True):
            st.markdown(f"### {title}")
            _render()





def _approve_selected_bets(
    bet_ids: List[int],
    verification_service: BetVerificationService,
    bets_by_id: Dict[int, Dict[str, Any]],
    suggestions_by_bet: Dict[int, MatchingSuggestions],
) -> None:
    """Approve multiple bets using high-confidence suggestions."""
    successes = 0
    failures: List[str] = []

    for bet_id in bet_ids:
        bet = bets_by_id.get(bet_id)
        suggestions = suggestions_by_bet.get(bet_id)

        if not bet or suggestions is None:
            failures.append(f"Bet #{bet_id}: missing suggestion context")
            continue

        payload = suggestions.best_auto_payload(bet)
        if not payload:
            failures.append(f"Bet #{bet_id}: no high-confidence suggestion available")
            continue

        try:
            edited_fields: Dict[str, Any] = {}
            if payload.get("canonical_event_id"):
                edited_fields["canonical_event_id"] = payload["canonical_event_id"]
            if payload.get("market_code"):
                edited_fields["market_code"] = payload["market_code"]
            if payload.get("canonical_market_id"):
                edited_fields["canonical_market_id"] = payload["canonical_market_id"]
            if payload.get("period_scope"):
                edited_fields["period_scope"] = payload["period_scope"]
            if payload.get("line_value") is not None:
                edited_fields["line_value"] = payload["line_value"]
            if payload.get("side"):
                edited_fields["side"] = payload["side"]
            if payload.get("stake_original") is not None:
                edited_fields["stake_original"] = str(
                    Decimal(str(payload["stake_original"]))
                )
            if payload.get("odds_original") is not None:
                edited_fields["odds_original"] = str(
                    Decimal(str(payload["odds_original"]))
                )
            if payload.get("payout") is not None:
                edited_fields["payout"] = str(Decimal(str(payload["payout"])))
            if payload.get("currency"):
                edited_fields["currency"] = payload["currency"]

            verification_service.approve_bet(bet_id, edited_fields)
            successes += 1
            invalidate_query_cache()
        except Exception as exc:
            failures.append(f"Bet #{bet_id}: {exc}")

    _schedule_selection_reset(bet_ids)

    st.session_state["batch_feedback"] = {
        "approved": successes,
        "rejected": 0,
        "errors": failures,
    }
    safe_rerun()


def _reject_selected_bets(
    bet_ids: List[int], verification_service: BetVerificationService
) -> None:
    """Reject multiple bets without a reason."""
    successes = 0
    failures: List[str] = []

    for bet_id in bet_ids:
        try:
            verification_service.reject_bet(bet_id)
            successes += 1
            invalidate_query_cache()
        except Exception as exc:
            failures.append(f"Bet #{bet_id}: {exc}")

    _schedule_selection_reset(bet_ids)

    st.session_state["batch_feedback"] = {
        "approved": 0,
        "rejected": successes,
        "errors": failures,
    }
    safe_rerun()
_AUTO_REFRESH_INTERVAL_SECONDS = 30
_AUTO_REFRESH_KEY = "incoming_bets_auto_refresh"
_AUTO_REFRESH_QUERY_KEY = "auto"
_AUTO_REFRESH_SYNC_KEY = "_incoming_bets_auto_refresh_synced"
_AUTO_REFRESH_INFLIGHT_KEY = "_incoming_bets_auto_refresh_inflight"
_AUTO_REFRESH_LAST_RUN_KEY = "_incoming_bets_auto_refresh_last_completed"


def _label_for_slug(options: Sequence[tuple[str, Optional[str]]], slug: Optional[str]) -> str:
    for label, value in options:
        if value == slug:
            return label
    return options[0][0]


def _slug_for_label(options: Sequence[tuple[str, Optional[str]]], label: str) -> Optional[str]:
    for option_label, slug in options:
        if option_label == label:
            return slug
    return None


def _sanitize_multiselect_selection(selection: Sequence[str], valid_options: Sequence[str]) -> List[str]:
    valid_set = set(valid_options)
    cleaned: List[str] = []
    seen = set()
    for value in selection:
        if value == "All" or value not in valid_set or value in seen:
            continue
        cleaned.append(value)
        seen.add(value)
    return cleaned


def _prime_filter_defaults_from_saved_view(
    snapshot: saved_views.SavedViewSnapshot,
    *,
    bookmaker_options: Sequence[str],
) -> None:
    if snapshot.bookmaker and _BOOKMAKER_FILTER_KEY not in st.session_state:
        valid = [value for value in snapshot.bookmaker if value in bookmaker_options]
        if valid:
            st.session_state[_BOOKMAKER_FILTER_KEY] = valid

    if snapshot.confidence and _CONFIDENCE_FILTER_KEY not in st.session_state:
        st.session_state[_CONFIDENCE_FILTER_KEY] = _label_for_slug(_CONFIDENCE_OPTIONS, snapshot.confidence)


def _render_incoming_bets_queue(
    *,
    associate_filter: List[str],
    bookmaker_filter: List[str],
    bet_type_filter: Optional[str],
    confidence_filter: str,
    auto_refresh_enabled: bool,
    search_term: str,
) -> None:
    """Render the incoming bets queue within an isolated fragment."""
    st.subheader(":material/list_alt: Bets Awaiting Review")

    with auto_refresh_helper.auto_refresh_cycle(
        enabled=auto_refresh_enabled,
        inflight_key=_AUTO_REFRESH_INFLIGHT_KEY,
        last_run_key=_AUTO_REFRESH_LAST_RUN_KEY,
    ):
        try:
            with track_timing("incoming_queue"):
                db = get_cached_connection()
                verification_service = BetVerificationService(db)
                matching_service = MatchingService(db)

                _handle_bet_actions(verification_service)

                base_from = """
                FROM bets b
                JOIN associates a ON b.associate_id = a.id
                JOIN bookmakers bk ON b.bookmaker_id = bk.id
                LEFT JOIN canonical_events ce ON b.canonical_event_id = ce.id
            """
                filters = ["b.status = 'incoming'"]
                query_params: List[Any] = []

                if search_term:
                    search_value = f"%{search_term.lower()}%"
                    filters.append(
                        "("
                        "LOWER(a.display_alias) LIKE ? OR "
                        "LOWER(bk.bookmaker_name) LIKE ? OR "
                        "LOWER(IFNULL(b.selection_text, '')) LIKE ? OR "
                        "CAST(b.id AS TEXT) LIKE ?"
                        ")"
                    )
                    query_params.extend([search_value, search_value, search_value, search_value])

                if associate_filter:
                    placeholders = ",".join(["?" for _ in associate_filter])
                    filters.append(f"a.display_alias IN ({placeholders})")
                    query_params.extend(associate_filter)

                if bookmaker_filter:
                    placeholders = ",".join(["?" for _ in bookmaker_filter])
                    filters.append(f"bk.bookmaker_name IN ({placeholders})")
                    query_params.extend(bookmaker_filter)

                if bet_type_filter == "single":
                    filters.append("(b.is_multi IS NULL OR b.is_multi = 0)")
                elif bet_type_filter == "multi":
                    filters.append("b.is_multi = 1")

                if confidence_filter != "All":
                    if confidence_filter == "High (>=80%)":
                        filters.append("CAST(b.normalization_confidence AS REAL) >= 0.8")
                    elif confidence_filter == "Medium (50-79%)":
                        filters.append(
                            "("
                            "CAST(b.normalization_confidence AS REAL) >= 0.5"
                            " AND CAST(b.normalization_confidence AS REAL) < 0.8"
                            ")"
                        )
                    elif confidence_filter == "Low (<50%)":
                        filters.append("CAST(b.normalization_confidence AS REAL) < 0.5")
                    elif confidence_filter == "Failed":
                        filters.append(
                            "(b.normalization_confidence IS NULL OR b.normalization_confidence = '')"
                        )

                where_clause = " AND ".join(filters)
                select_sql = f"""
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
                {base_from}
                WHERE {where_clause}
                ORDER BY b.created_at_utc DESC
            """
                count_sql = f"""
                SELECT COUNT(*)
                {base_from}
                WHERE {where_clause}
            """

                total_rows = get_total_count(count_sql, tuple(query_params))
                pagination = paginate("incoming_bets", total_rows, label="bets")

                paginated_sql, extra_params = apply_pagination(select_sql, pagination)
                final_params = tuple(query_params) + extra_params
                incoming_df = query_df(paginated_sql, final_params)
                incoming_bets = incoming_df.to_dict(orient="records")
                reset_selection_ids = _consume_selection_reset_ids()

                if not incoming_bets:
                    st.info(":material/inbox: No bets awaiting review! Queue is empty.")
                    return

                st.caption(
                    f"Showing {pagination.start_row}-{pagination.end_row} of {pagination.total_rows} bets"
                )

                suggestions_by_bet: Dict[int, MatchingSuggestions] = {}
                bets_by_id: Dict[int, Dict[str, Any]] = {}
                selected_batch_ids: List[int] = []
                selection_col_ratio = [0.1, 0.9]

                for bet_dict in incoming_bets:
                    bet_id = bet_dict["bet_id"]
                    bets_by_id[bet_id] = bet_dict
                    suggestions = matching_service.suggest_for_bet(bet_dict)
                    suggestions_by_bet[bet_id] = suggestions

                    checkbox_key = f"select_bet_{bet_id}"
                    if bet_id in reset_selection_ids or checkbox_key not in st.session_state:
                        st.session_state[checkbox_key] = False
                        reset_selection_ids.discard(bet_id)

                    select_col, card_col = st.columns(selection_col_ratio)
                    with select_col:
                        selected = st.checkbox("Select", key=checkbox_key)
                    with card_col:
                        render_bet_card(
                            bet_dict,
                            show_actions=True,
                            editable=True,
                            verification_service=verification_service,
                            matching_suggestions=suggestions,
                        )

                    if selected:
                        selected_batch_ids.append(bet_id)

                st.markdown("---")

                if selected_batch_ids:
                    st.info(f"{len(selected_batch_ids)} bet(s) selected for batch actions.")

                batch_col_approve, batch_col_reject = st.columns(2)
                approve_clicked = batch_col_approve.button(
                    "Approve Selected",
                    disabled=not selected_batch_ids,
                    width="stretch",
                )
                reject_clicked = batch_col_reject.button(
                    "Reject Selected",
                    disabled=not selected_batch_ids,
                    width="stretch",
                )

                if approve_clicked:
                    _approve_selected_bets(
                        selected_batch_ids,
                        verification_service,
                        bets_by_id,
                        suggestions_by_bet,
                    )
                if reject_clicked:
                    _reject_selected_bets(selected_batch_ids, verification_service)

        except Exception as exc:
            logger.error("failed_to_load_incoming_bets", error=str(exc), exc_info=True)
            st.error(f"Failed to load incoming bets: {str(exc)}")
            st.exception(exc)


# Configure page
PAGE_TITLE = "Incoming Bets"
PAGE_ICON = ":material/inbox:"

st.set_page_config(page_title=PAGE_TITLE, layout="wide")
load_global_styles()

st.title(f"{PAGE_ICON} {PAGE_TITLE}")

saved_view_manager = saved_views.SavedViewManager(slug="incoming_bets_filters")
initial_saved_view = saved_view_manager.get_snapshot()
if initial_saved_view.auto is not None and _AUTO_REFRESH_KEY not in st.session_state:
    st.session_state[_AUTO_REFRESH_KEY] = initial_saved_view.auto
    st.session_state[_AUTO_REFRESH_SYNC_KEY] = initial_saved_view.auto

batch_feedback = st.session_state.pop("batch_feedback", None)
if batch_feedback:
    if batch_feedback.get("approved"):
        st.success(f"{batch_feedback['approved']} bet(s) approved in batch.")
    if batch_feedback.get("rejected"):
        st.info(f"{batch_feedback['rejected']} bet(s) rejected in batch.")
    for error_message in batch_feedback.get("errors", []):
        st.warning(error_message)

auto_refresh_supported = fragments_supported()
default_auto_refresh_state = auto_refresh_helper.resolve_toggle_state(
    session_key=_AUTO_REFRESH_KEY,
    sync_key=_AUTO_REFRESH_SYNC_KEY,
    query_key=_AUTO_REFRESH_QUERY_KEY,
    supported=auto_refresh_supported,
    default_on=True,
)
toggle_initial_value = (
    {} if _AUTO_REFRESH_KEY in st.session_state else {"value": default_auto_refresh_state}
)

top_controls = st.columns([5, 1.5, 1.5])
with top_controls[1]:
    auto_refresh_enabled = st.toggle(
        ":material/autorenew: Auto-refresh queue (30s)",
        key=_AUTO_REFRESH_KEY,
        help="Run the incoming bets fragment on an interval when available.",
        disabled=not auto_refresh_supported,
        **toggle_initial_value,
    )
    auto_refresh_helper.persist_query_state(
        value=auto_refresh_enabled,
        query_key=_AUTO_REFRESH_QUERY_KEY,
        sync_key=_AUTO_REFRESH_SYNC_KEY,
    )
    saved_view_manager.save(auto=auto_refresh_enabled)
    st.caption(
        auto_refresh_helper.format_status(
            enabled=auto_refresh_enabled,
            supported=auto_refresh_supported,
            interval_seconds=_AUTO_REFRESH_INTERVAL_SECONDS,
            inflight_key=_AUTO_REFRESH_INFLIGHT_KEY,
            last_run_key=_AUTO_REFRESH_LAST_RUN_KEY,
        )
    )

with top_controls[2]:
    render_reset_control(
        key="incoming_reset",
        description="Clear filters, dialogs, and auto-refresh toggles for Incoming Bets.",
        prefixes=("incoming_", "filters_", "dialog_", "advanced_", "approve_", "reject_"),
    )

# Manual upload panel at top (collapsible)
with st.expander(":material/cloud_upload: Upload Manual Bet", expanded=False):
    render_manual_upload_panel()

st.markdown("---")

search_query = ""

# Metrics and filters
filter_state: dict[str, object] = {
    "associate_filter": ["All"],
    "bookmaker_filter": ["All"],
    "confidence_filter": _CONFIDENCE_OPTIONS[0][0],
}
active_associate_filter: List[str] = []
active_bookmaker_filter: List[str] = []
confidence_label = _CONFIDENCE_OPTIONS[0][0]
confidence_slug: Optional[str] = None

try:
    try:
        counts_df = query_df(
            """
            SELECT
                SUM(CASE WHEN status='incoming' THEN 1 ELSE 0 END) as waiting,
                SUM(CASE WHEN status='verified' AND date(updated_at_utc)=date('now') THEN 1 ELSE 0 END) as approved_today,
                SUM(CASE WHEN status='rejected' AND date(updated_at_utc)=date('now') THEN 1 ELSE 0 END) as rejected_today
            FROM bets
            """
        )
        if counts_df.empty:
            counts = {"waiting": 0, "approved_today": 0, "rejected_today": 0}
        else:
            counts = counts_df.iloc[0]

        col1, col2, col3 = st.columns(3)
        col1.metric("Waiting Review", int(counts.get("waiting") or 0))
        col2.metric("Approved Today", int(counts.get("approved_today") or 0))
        col3.metric("Rejected Today", int(counts.get("rejected_today") or 0))
    except Exception as exc:
        logger.error("failed_to_load_counters", error=str(exc))
        st.error("Failed to load counters")

    st.markdown("---")

    try:
        associates_df = query_df(
            "SELECT DISTINCT display_alias FROM associates ORDER BY display_alias"
        )
        associate_options = ["All"] + associates_df["display_alias"].dropna().tolist()
    except Exception as exc:
        logger.error("failed_to_load_associates", error=str(exc))
        st.warning("Unable to load associate list. Showing only 'All'.")
        associate_options = ["All"]

    try:
        bookmakers_df = query_df(
            "SELECT DISTINCT bookmaker_name FROM bookmakers ORDER BY bookmaker_name"
        )
        bookmaker_options = ["All"] + bookmakers_df["bookmaker_name"].dropna().tolist()
    except Exception as exc:
        logger.error("failed_to_load_bookmakers", error=str(exc))
        st.warning("Unable to load bookmaker list. Showing only 'All'.")
        bookmaker_options = ["All"]

    saved_filter_snapshot = saved_view_manager.get_snapshot(
        bookmaker_options=[option for option in bookmaker_options if option != "All"]
    )
    _prime_filter_defaults_from_saved_view(
        saved_filter_snapshot,
        bookmaker_options=[option for option in bookmaker_options if option != "All"],
    )

    confidence_labels = [label for label, _ in _CONFIDENCE_OPTIONS]

    def _render_filter_controls() -> dict[str, object]:
        cols = st.columns([1.5, 1.5, 1])

        with cols[0]:
            associate_filter = st.multiselect(
                "Filter by Associate",
                options=associate_options,
                default=associate_options[:1],
                key=_ASSOCIATE_FILTER_KEY,
            )

        with cols[1]:
            bookmaker_filter = st.multiselect(
                "Filter by Bookmaker",
                options=bookmaker_options,
                default=bookmaker_options[:1],
                key=_BOOKMAKER_FILTER_KEY,
            )

        with cols[2]:
            confidence_filter = st.selectbox(
                "Filter by Confidence",
                options=confidence_labels,
                key=_CONFIDENCE_FILTER_KEY,
            )

        st.caption("")  # spacing buffer

        return {
            "associate_filter": associate_filter,
            "bookmaker_filter": bookmaker_filter,
            "confidence_filter": confidence_filter,
        }

    filter_state, _ = form_gated_filters(
        _FILTER_FORM_KEY,
        _render_filter_controls,
        submit_label="Apply Filters",
        help_text="Update the queue with the selected filters. Changes persist for saved views.",
    )

    active_associate_filter = _sanitize_multiselect_selection(
        filter_state["associate_filter"],
        associate_options,
    )
    active_bookmaker_filter = _sanitize_multiselect_selection(
        filter_state["bookmaker_filter"],
        bookmaker_options,
    )
    confidence_label = str(filter_state["confidence_filter"])
    confidence_slug = _slug_for_label(_CONFIDENCE_OPTIONS, confidence_label)

    url_state.update_query_params(
        {
            _BOOKMAKER_QUERY_KEY: active_bookmaker_filter or None,
            _CONFIDENCE_QUERY_KEY: confidence_slug,
        }
    )
    saved_view_manager.save(
        bookmakers=active_bookmaker_filter or None,
        confidence=confidence_slug,
    )

    st.markdown("---")
except Exception as exc:
    logger.error("incoming_filter_failure", error=str(exc), exc_info=True)
    st.error("Failed to prepare filters; falling back to defaults.")

associate_filter = active_associate_filter
bookmaker_filter = active_bookmaker_filter
confidence_filter = confidence_label

auto_refresh_run_every = (
    _AUTO_REFRESH_INTERVAL_SECONDS if auto_refresh_enabled and auto_refresh_supported else None
)

call_fragment(
    "incoming_bets.queue",
    _render_incoming_bets_queue,
    run_every=auto_refresh_run_every,
    associate_filter=associate_filter,
    bookmaker_filter=bookmaker_filter,
    bet_type_filter=None,
    confidence_filter=confidence_filter,
    auto_refresh_enabled=bool(auto_refresh_run_every),
    search_term=search_query,
)

render_debug_panel()
