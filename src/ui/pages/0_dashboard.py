"""
Primary dashboard surface for the Surebet Accounting System.

Displays realtime operational metrics, refresh cadence, and high-impact
shortcuts for operators starting their triage sessions.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable, Iterable, Optional

import streamlit as st

from src.core.database import get_db_connection
from src.integrations.fx_api_client import fetch_daily_fx_rates
from src.services.daily_statement_service import DailyStatementSender
from src.services.surebet_matcher import SurebetMatcher
from src.ui.cache import invalidate_query_cache
from src.ui.helpers import auto_refresh as auto_refresh_helper
from src.ui.helpers.dialogs import open_dialog, render_confirmation_dialog
from src.ui.helpers.fragments import fragment, fragments_supported
from src.ui.helpers.streaming import show_info_toast, stream_with_fallback
from src.ui.services.dashboard_metrics import DashboardMetricSnapshot, load_dashboard_metrics
from src.ui.ui_components import card, load_global_styles, metric_compact
from src.ui.utils.navigation_links import render_navigation_link
from src.utils.logging_config import get_logger

load_global_styles()

PAGE_TITLE = "Dashboard"
PAGE_ICON = ":material/monitoring:"
_AUTO_REFRESH_INTERVAL_SECONDS = 30  # Matches Incoming Bets auto-refresh cadence.
_REFRESH_INFLIGHT_KEY = "_dashboard_metrics_refresh_inflight"
_REFRESH_LAST_RUN_KEY = "_dashboard_metrics_refresh_last_completed"

st.title(f"{PAGE_ICON} {PAGE_TITLE}")
st.caption(
    "Realtime view of key surebet metrics. Values refresh automatically when "
    "data sources update."
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class MetricCardDefinition:
    key: str
    label: str
    description: str
    link_script: str
    link_label: str
    link_icon: str
    help_text: str


@dataclass(frozen=True)
class ActionOutcome:
    success: bool
    message: str
    details: Optional[str] = None


@dataclass(frozen=True)
class OperationalAction:
    key: str
    label: str
    icon: str
    description: str
    confirm_title: str
    confirm_body: str
    confirm_label: str
    confirm_type: str
    running_text: str
    handler: Callable[[], ActionOutcome]


_METRIC_CARDS: tuple[MetricCardDefinition, ...] = (
    MetricCardDefinition(
        key="waiting_incoming",
        label="Waiting Incoming Bets",
        description="Queue backlog awaiting review",
        link_script="pages/1_incoming_bets.py",
        link_label="Incoming Bets",
        link_icon=":material/inbox:",
        help_text="Open the Incoming Bets queue to triage submissions.",
    ),
    MetricCardDefinition(
        key="approved_today",
        label="Approved Bets (Today)",
        description="Same-day approvals",
        link_script="pages/1_incoming_bets.py",
        link_label="Incoming Bets",
        link_icon=":material/done_all:",
        help_text="Jump to Incoming Bets to audit today's approvals.",
    ),
    MetricCardDefinition(
        key="open_surebets",
        label="Open Surebets",
        description="Active opportunities",
        link_script="pages/2_surebets_summary.py",
        link_label="Surebets Summary",
        link_icon=":material/target:",
        help_text="Open Surebets Summary to inspect safety and ROI details.",
    ),
    MetricCardDefinition(
        key="pending_settlements",
        label="Pending Settlements",
        description="Verified + matched bets awaiting settlement",
        link_script="pages/3_verified_bets_queue.py",
        link_label="Settlement",
        link_icon=":material/task_alt:",
        help_text="Open the Settlement queue to finalize ready bets.",
    ),
)


# ---------------------------------------------------------------------------
# Metric rendering
# ---------------------------------------------------------------------------


def _format_count(value: Optional[int]) -> str:
    return f"{value:,}" if value is not None else "--"


def _render_metric_cards(snapshot: DashboardMetricSnapshot) -> None:
    if snapshot.has_failures():
        st.warning(
            "Some dashboard metrics failed to load. Values marked '--' will "
            "update automatically after the next refresh.",
            icon="⚠️",
        )

    with card("Key Metrics", "Live operational stats", icon=":material/monitoring:"):
        for card_def in _METRIC_CARDS:
            value = getattr(snapshot, card_def.key, None)
            metric_cols = st.columns([3, 1])
            with metric_cols[0]:
                metric_compact(card_def.label, _format_count(value), delta=card_def.description)
            with metric_cols[1]:
                render_navigation_link(
                    card_def.link_script,
                    label=card_def.link_label,
                    icon=card_def.link_icon,
                    help_text=card_def.help_text,
                )


def _render_refresh_metadata(auto_refresh_supported: bool) -> None:
    status_text = auto_refresh_helper.format_status(
        enabled=auto_refresh_supported,
        supported=auto_refresh_supported,
        interval_seconds=_AUTO_REFRESH_INTERVAL_SECONDS,
        inflight_key=_REFRESH_INFLIGHT_KEY,
        last_run_key=_REFRESH_LAST_RUN_KEY,
    )
    st.caption(status_text)

    last_run = st.session_state.get(_REFRESH_LAST_RUN_KEY)
    if isinstance(last_run, datetime):
        local_display = last_run.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
        st.caption(f":material/history: Metrics last refreshed at {local_display}")
    else:
        st.caption(":material/history: Waiting for first refresh cycle...")


def _render_metrics_block() -> None:
    auto_refresh_supported = fragments_supported()
    snapshot: DashboardMetricSnapshot
    with auto_refresh_helper.auto_refresh_cycle(
        enabled=auto_refresh_supported,
        inflight_key=_REFRESH_INFLIGHT_KEY,
        last_run_key=_REFRESH_LAST_RUN_KEY,
    ):
        snapshot = load_dashboard_metrics()

    if not auto_refresh_supported:
        st.session_state[_REFRESH_LAST_RUN_KEY] = datetime.now(UTC)

    _render_metric_cards(snapshot)
    _render_refresh_metadata(auto_refresh_supported)


@fragment("dashboard.metrics", run_every=_AUTO_REFRESH_INTERVAL_SECONDS)
def render_metrics_fragment() -> None:
    _render_metrics_block()


render_metrics_fragment()


# ---------------------------------------------------------------------------
# Operational actions
# ---------------------------------------------------------------------------


def _run_daily_statements() -> ActionOutcome:
    sender = DailyStatementSender()
    progress = st.progress(0.0)

    def _on_progress(current: int, total: int) -> None:
        fraction = 0.0 if total <= 0 else min(max(current / total, 0.0), 1.0)
        progress.progress(fraction)

    try:
        result = asyncio.run(sender.send_all(progress_callback=_on_progress))
        message = (
            f"Sent {result.sent}/{result.total_targets} statements – "
            f"{result.failed} failed, {result.skipped} skipped."
        )
        details = f"Retries performed: {result.retried}"
        return ActionOutcome(True, message, details)
    except Exception as exc:  # pragma: no cover - defensive path
        logger.error("dashboard_daily_statements_failed", error=str(exc))
        return ActionOutcome(False, f"Daily statements failed: {exc}")
    finally:
        sender.close()
        progress.empty()


def _run_fx_refresh() -> ActionOutcome:
    try:
        success = asyncio.run(fetch_daily_fx_rates())
    except Exception as exc:  # pragma: no cover - defensive path
        logger.error("dashboard_fx_refresh_failed", error=str(exc))
        return ActionOutcome(False, f"FX rate refresh failed: {exc}")

    if success:
        return ActionOutcome(True, "FX rates refreshed from exchangerate-api.com.")
    return ActionOutcome(False, "FX provider reported an error. See logs for details.")


def _run_surebet_matcher() -> ActionOutcome:
    conn = get_db_connection()
    try:
        matcher = SurebetMatcher(conn)
        rows = conn.execute(
            "SELECT id FROM bets WHERE status IN ('verified', 'matched') ORDER BY updated_at_utc ASC"
        ).fetchall()
        bet_ids = [row["id"] for row in rows]
        matched = 0
        for bet_id in bet_ids:
            try:
                if matcher.attempt_match(bet_id):
                    matched += 1
            except Exception as exc:
                logger.warning("dashboard_matcher_error", bet_id=bet_id, error=str(exc))
        conn.commit()
    except Exception as exc:  # pragma: no cover - defensive path
        logger.error("dashboard_matcher_failed", error=str(exc))
        return ActionOutcome(False, f"Surebet matcher sweep failed: {exc}")
    finally:
        conn.close()

    invalidate_query_cache()
    total_processed = len(bet_ids)
    message = f"Processed {total_processed} bet(s); {matched} produced/updated surebets."
    details = "No verified bets were waiting." if total_processed == 0 else None
    return ActionOutcome(True, message, details)


_OPERATIONS: tuple[OperationalAction, ...] = (
    OperationalAction(
        key="dashboard_send_statements",
        label="Send Global Statements",
        icon=":material/send:",
        description="Broadcast Telegram statements to all registered chats.",
        confirm_title="Send global Telegram statements?",
        confirm_body=(
            "This will invoke DailyStatementSender and contact every active chat "
            "registration using current balances. Ensure Telegram credentials "
            "are configured before proceeding."
        ),
        confirm_label="Send Statements",
        confirm_type="primary",
        running_text="Sending statements...",
        handler=_run_daily_statements,
    ),
    OperationalAction(
        key="dashboard_refresh_fx",
        label="Fetch FX Rates",
        icon=":material/currency_exchange:",
        description="Refresh daily FX rates from the configured provider.",
        confirm_title="Fetch updated FX rates?",
        confirm_body=(
            "Fetches rates from exchangerate-api.com and stores them for balance "
            "checks. This may take a few seconds."
        ),
        confirm_label="Fetch Rates",
        confirm_type="primary",
        running_text="Fetching FX rates...",
        handler=_run_fx_refresh,
    ),
    OperationalAction(
        key="dashboard_match_surebets",
        label="Run Surebet Matcher",
        icon=":material/auto_fix_high:",
        description="Sweep verified bets to ensure matches are up-to-date.",
        confirm_title="Run the surebet matcher now?",
        confirm_body=(
            "Runs the deterministic matcher across all verified/matched bets "
            "to catch up any pending pairings."
        ),
        confirm_label="Run Matcher",
        confirm_type="secondary",
        running_text="Running surebet matcher...",
        handler=_run_surebet_matcher,
    ),
)


def _render_action_trigger(action: OperationalAction) -> None:
    payload_key = f"{action.key}__payload"
    if st.button(
        f"{action.icon} {action.label}",
        key=f"{action.key}__button",
        help=action.description,
        type="secondary",
        width='stretch',
    ):
        st.session_state[payload_key] = True
        open_dialog(action.key)

    if st.session_state.get(payload_key):
        decision = render_confirmation_dialog(
            key=action.key,
            title=action.confirm_title,
            body=action.confirm_body,
            confirm_label=action.confirm_label,
            confirm_type=action.confirm_type,
        )
        if decision is True:
            with st.spinner(action.running_text):
                outcome = action.handler()
            if outcome.success:
                st.success(outcome.message)
                if outcome.details:
                    st.caption(outcome.details)
            else:
                st.error(outcome.message)
                if outcome.details:
                    st.caption(outcome.details)
            st.session_state.pop(payload_key, None)
        elif decision is False:
            st.session_state.pop(payload_key, None)


def _render_operational_actions() -> None:
    with card(
        "Operational Starters",
        "Kick off high-signal actions without leaving the dashboard.",
        icon=":material/rocket_launch:",
    ):
        cols = st.columns(len(_OPERATIONS))
        for action, column in zip(_OPERATIONS, cols):
            with column:
                _render_action_trigger(action)


_render_operational_actions()


# ---------------------------------------------------------------------------
# Activity stream + shortcuts remain unchanged
# ---------------------------------------------------------------------------

st.divider()
col_activity, col_shortcuts = st.columns([3, 1])

with col_activity:
    st.subheader("Activity Stream")

    def _activity_feed() -> Iterable[str]:
        events = [
            "Checking bookmaker balances...",
            "Syncing telegram queue...",
            "Refreshing settlement projections...",
            "Recomputing exposure deltas...",
        ]
        for event in events:
            yield f"- {event}\n"

    stream_with_fallback(_activity_feed, header=":material/dvr: Live log output")

with col_shortcuts:
    st.subheader("Shortcuts")

    render_navigation_link(
        "pages/8_associate_operations.py",
        label="Associate Hub",
        icon=":material/groups_3:",
        help_text="Open 'Associate Operations Hub' from the sidebar.",
    )
    render_navigation_link(
        "pages/6_reconciliation.py",
        label="Reconciliation",
        icon=":material/account_balance:",
        help_text="Use sidebar navigation when page links are unavailable.",
    )
    render_navigation_link(
        "pages/2_surebets_summary.py",
        label="Surebets Summary",
        icon=":material/target:",
    )

    if st.button("Show Tip", key="dashboard_tip"):
        show_info_toast("Use keyboard shortcut R to reset filters in the Associate Hub.")


st.divider()
