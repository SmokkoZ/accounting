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
from typing import Dict, Any, List, Optional

from src.ui.cache import get_cached_connection, invalidate_query_cache, query_df
from src.services.bet_verification import BetVerificationService
from src.services.matching_service import MatchingService, MatchingSuggestions
from src.ui.components.manual_upload import render_manual_upload_panel
from src.ui.components.bet_card import render_bet_card
from src.ui.helpers import auto_refresh as auto_refresh_helper
from src.ui.helpers import url_state
from src.ui.helpers.fragments import (
    call_fragment,
    fragments_supported,
    render_debug_panel,
    render_debug_toggle,
)
from src.ui.utils import feature_flags
from src.ui.ui_components import advanced_section, form_gated_filters, load_global_styles
from src.ui.utils.navigation_links import render_navigation_link
from src.ui.utils.pagination import apply_pagination, get_total_count, paginate
from src.ui.utils.performance import track_timing
from src.ui.utils.state_management import render_reset_control, safe_rerun

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
                    "pages/2_verified_bets.py",
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

    for bet_id in bet_ids:
        key = f"select_bet_{bet_id}"
        if key in st.session_state:
            st.session_state[key] = False

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

    for bet_id in bet_ids:
        key = f"select_bet_{bet_id}"
        if key in st.session_state:
            st.session_state[key] = False

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
_COMPACT_QUERY_KEY = "compact"
_COMPACT_TOGGLE_KEY = "incoming_bets_compact_mode"
_COMPACT_SYNC_KEY = "_incoming_bets_compact_last_synced"


def _read_compact_mode_from_query() -> bool:
    params = url_state.read_query_params()
    raw_value = url_state.normalize_query_value(params.get(_COMPACT_QUERY_KEY))
    if raw_value is None:
        return False
    return raw_value.lower() in {"1", "true", "yes", "on", "compact"}


def _persist_compact_query_state(value: bool) -> None:
    last_synced = st.session_state.get(_COMPACT_SYNC_KEY)
    if last_synced == value:
        return

    updated = url_state.set_query_param_flag(_COMPACT_QUERY_KEY, value)
    if updated:
        st.session_state[_COMPACT_SYNC_KEY] = value


def _get_compact_mode_state() -> bool:
    if _COMPACT_TOGGLE_KEY not in st.session_state:
        default_value = _read_compact_mode_from_query()
        st.session_state[_COMPACT_TOGGLE_KEY] = default_value
        st.session_state[_COMPACT_SYNC_KEY] = default_value
    return bool(st.session_state[_COMPACT_TOGGLE_KEY])


def _render_compact_mode_toggle() -> bool:
    _get_compact_mode_state()
    toggle_value = st.toggle(
        ":material/density_small: Compact bet rows",
        key=_COMPACT_TOGGLE_KEY,
        help="Shrink bet card padding and thumbnails so more rows stay on screen.",
    )
    _persist_compact_query_state(toggle_value)
    return toggle_value


def _render_incoming_bets_queue(
    *,
    associate_filter: List[str],
    confidence_filter: str,
    auto_refresh_enabled: bool,
    compact_mode: bool,
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

                if "All" not in associate_filter and associate_filter:
                    placeholders = ",".join(["?" for _ in associate_filter])
                    filters.append(f"a.display_alias IN ({placeholders})")
                    query_params.extend(associate_filter)

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

                if not incoming_bets:
                    st.info(":material/inbox: No bets awaiting review! Queue is empty.")
                    return

                st.caption(
                    f"Showing {pagination.start_row}-{pagination.end_row} of {pagination.total_rows} bets"
                )

                suggestions_by_bet: Dict[int, MatchingSuggestions] = {}
                bets_by_id: Dict[int, Dict[str, Any]] = {}
                selected_batch_ids: List[int] = []
                selection_col_ratio = [0.07, 0.93] if compact_mode else [0.1, 0.9]

                for bet_dict in incoming_bets:
                    bet_id = bet_dict["bet_id"]
                    bets_by_id[bet_id] = bet_dict
                    suggestions = matching_service.suggest_for_bet(bet_dict)
                    suggestions_by_bet[bet_id] = suggestions

                    checkbox_key = f"select_bet_{bet_id}"
                    if checkbox_key not in st.session_state:
                        st.session_state[checkbox_key] = False

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
                            compact_mode=compact_mode,
                        )

                    if selected:
                        selected_batch_ids.append(bet_id)

                if compact_mode:
                    st.markdown(
                        "<hr style='margin:0.35rem 0;border-top:1px dashed rgba(148,163,184,0.35);' />",
                        unsafe_allow_html=True,
                    )
                else:
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

batch_feedback = st.session_state.pop("batch_feedback", None)
if batch_feedback:
    if batch_feedback.get("approved"):
        st.success(f"{batch_feedback['approved']} bet(s) approved in batch.")
    if batch_feedback.get("rejected"):
        st.info(f"{batch_feedback['rejected']} bet(s) rejected in batch.")
    for error_message in batch_feedback.get("errors", []):
        st.warning(error_message)

toggle_cols = st.columns([5, 2, 2])
with toggle_cols[1]:
    render_debug_toggle(":material/monitor_heart: Performance debug")
with toggle_cols[2]:
    compact_mode_enabled = _render_compact_mode_toggle()

# Manual upload panel at top (collapsible)
with st.expander(":material/cloud_upload: Upload Manual Bet", expanded=False):
    render_manual_upload_panel()

st.markdown("---")

action_cols = st.columns([6, 2])
with action_cols[1]:
    render_reset_control(
        key="incoming_reset",
        description="Clear filters, dialogs, and auto-refresh toggles for Incoming Bets.",
        prefixes=("incoming_", "filters_", "dialog_", "advanced_", "approve_", "reject_"),
    )

# Metrics and filters
filter_state: dict[str, object] = {
    "associate_filter": ["All"],
    "confidence_filter": "All",
}

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

    def _render_filter_controls() -> dict[str, object]:
        filter_col1, filter_col2 = st.columns(2)

        with filter_col1:
            try:
                associates_df = query_df(
                    "SELECT DISTINCT display_alias FROM associates ORDER BY display_alias"
                )
                associate_options = ["All"] + associates_df["display_alias"].dropna().tolist()
            except Exception as exc:
                logger.error("failed_to_load_associates", error=str(exc))
                st.warning("Unable to load associate list. Showing only 'All'.")
                associate_options = ["All"]

            associate_filter = st.multiselect(
                "Filter by Associate",
                options=associate_options,
                default=associate_options[:1],
                key="incoming_filters_associates",
            )

        with filter_col2:
            confidence_options = [
                "All",
                "High (>=80%)",
                "Medium (50-79%)",
                "Low (<50%)",
                "Failed",
            ]
            confidence_filter = st.selectbox(
                "Filter by Confidence",
                options=confidence_options,
                index=0,
                key="incoming_filters_confidence",
            )

        return {
            "associate_filter": associate_filter,
            "confidence_filter": confidence_filter,
        }

    with advanced_section():
        filter_state, _ = form_gated_filters(
            "incoming_filters",
            _render_filter_controls,
            submit_label="Apply Filters",
            help_text="Update the queue with the selected filters.",
        )

    st.markdown("---")
except Exception as exc:
    logger.error("incoming_filter_failure", error=str(exc), exc_info=True)
    st.error("Failed to prepare filters; falling back to defaults.")

associate_filter = filter_state["associate_filter"]
confidence_filter = filter_state["confidence_filter"]

auto_refresh_supported = fragments_supported()
default_auto_refresh_state = auto_refresh_helper.resolve_toggle_state(
    session_key=_AUTO_REFRESH_KEY,
    sync_key=_AUTO_REFRESH_SYNC_KEY,
    query_key=_AUTO_REFRESH_QUERY_KEY,
    supported=auto_refresh_supported,
    default_on=True,
)
auto_refresh_enabled = st.toggle(
    ":material/autorenew: Auto-refresh queue (30s)",
    key=_AUTO_REFRESH_KEY,
    value=default_auto_refresh_state,
    help="Run the incoming bets fragment on an interval when available.",
    disabled=not auto_refresh_supported,
)
auto_refresh_helper.persist_query_state(
    value=auto_refresh_enabled,
    query_key=_AUTO_REFRESH_QUERY_KEY,
    sync_key=_AUTO_REFRESH_SYNC_KEY,
)
st.caption(
    auto_refresh_helper.format_status(
        enabled=auto_refresh_enabled,
        supported=auto_refresh_supported,
        interval_seconds=_AUTO_REFRESH_INTERVAL_SECONDS,
        inflight_key=_AUTO_REFRESH_INFLIGHT_KEY,
        last_run_key=_AUTO_REFRESH_LAST_RUN_KEY,
    )
)

st.markdown("---")

auto_refresh_run_every = (
    _AUTO_REFRESH_INTERVAL_SECONDS if auto_refresh_enabled and auto_refresh_supported else None
)

call_fragment(
    "incoming_bets.queue",
    _render_incoming_bets_queue,
    run_every=auto_refresh_run_every,
    associate_filter=associate_filter,
    confidence_filter=confidence_filter,
    auto_refresh_enabled=bool(auto_refresh_run_every),
    compact_mode=compact_mode_enabled,
)

render_debug_panel()
