"""
Shared Surebets helpers for summary and settlement pages.
"""

import asyncio
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import pandas as pd
import streamlit as st

from src.core.database import get_db_connection
from src.integrations.fx_api_client import fetch_daily_fx_rates
from src.services.coverage_proof_service import CoverageProofService
from src.services.fx_manager import convert_to_eur, get_fx_rate, get_latest_fx_rate
from src.services.ledger_entry_service import (
    LedgerEntryService,
    SettlementCommitError,
    SettlementConfirmation,
)
from src.services.settlement_service import BetOutcome, SettlementService
from src.services.surebet_calculator import SurebetRiskCalculator
from src.ui.helpers.dialogs import (
    open_dialog,
    render_confirmation_dialog,
    render_settlement_confirmation,
)
from src.ui.helpers.fragments import call_fragment, render_debug_panel, render_debug_toggle
from src.ui.helpers.streaming import (
    handle_streaming_error,
    show_success_toast,
    status_with_steps,
)
from src.ui.media import render_thumbnail
from src.ui.pages.coverage_proof_outbox_panel import (
    LEGACY_OUTBOX_RESEND_PREFIX,
    OUTBOX_RESEND_STATE_PREFIX,
    render_coverage_proof_outbox,
)
from src.ui.ui_components import advanced_section, form_gated_filters
from src.ui.utils.formatters import (
    format_market_display,
    format_percentage,
    format_utc_datetime_local,
    get_risk_badge_html,
)
from src.ui.utils.navigation_links import render_navigation_link
from src.ui.utils.pagination import paginate
from src.ui.utils.performance import track_timing
from src.ui.utils.state_management import render_reset_control, safe_rerun
from src.utils.logging_config import get_logger
logger = get_logger(__name__)

SUMMARY_PAGE_SCRIPT = "pages/2_surebets_summary.py"
SETTLEMENT_PAGE_SCRIPT = "pages/2b_surebets_ready_for_settlement.py"

def _to_decimal_or_none(value) -> Optional[Decimal]:
    if value in (None, "", " "):
        return None
    try:
        return Decimal(str(value))
    except (ValueError, ArithmeticError):
        return None


def _format_event_title(
    event_name: Optional[str], *, fallback: Optional[str] = None
) -> str:
    candidate = (event_name or fallback or "").strip()
    if not candidate:
        return "Unknown event"

    candidate = " ".join(candidate.split())

    def _dedupe(parts: List[str]) -> List[str]:
        seen: List[str] = []
        for part in parts:
            if not part:
                continue
            if not any(part.lower() == existing.lower() for existing in seen):
                seen.append(part)
        return seen

    lowered = candidate.lower()
    separators = [" vs ", " v ", " @ ", " - "]
    for sep in separators:
        if sep.strip() in lowered:
            pieces = [piece.strip() for piece in candidate.split(sep.strip())]
            unique = _dedupe(pieces)
            if len(unique) >= 2:
                return " vs ".join(unique[:2])

    return candidate


def _format_stake_displays(bet: Dict[str, Any]) -> tuple[str, str]:
    native_decimal = _to_decimal_or_none(bet.get("stake_original"))
    currency = (bet.get("currency") or "").strip()
    if native_decimal is not None and currency:
        stake_display = _format_amount_code(native_decimal, currency)
    else:
        stake_display = "N/A"

    eur_decimal = _stake_eur_for_bet(bet)
    eur_display = _format_amount_code(eur_decimal, "EUR") if eur_decimal is not None else "—"
    return stake_display, eur_display


def _stake_eur_for_bet(bet: Dict[str, Any]) -> Optional[Decimal]:
    """
    Return the stake in EUR using stored conversions when available and FX rates otherwise.
    """
    try:
        raw_eur = bet.get("stake_eur")
        if raw_eur is not None:
            stake_eur = _to_decimal_or_none(raw_eur)
            if stake_eur not in (None, Decimal("0")):
                return stake_eur.quantize(Decimal("0.01"))

        native = _to_decimal_or_none(bet.get("stake_original"))
        currency = (bet.get("currency") or "").strip()
        if native is None or not currency:
            return None

        if currency.upper() == "EUR":
            return native.quantize(Decimal("0.01"))

        rate: Optional[Decimal] = None
        try:
            rate = get_fx_rate(currency, date.today())
        except Exception:
            latest = get_latest_fx_rate(currency)
            if latest:
                rate = latest[0]

        if rate is None:
            return None

        return convert_to_eur(native, currency, rate)
    except Exception:
        return None



def _potential_win_eur(bet: Dict[str, Any]) -> Optional[Decimal]:
    """
    Return the potential total return in EUR for a bet.
    """
    stake_eur = _stake_eur_for_bet(bet)
    if stake_eur is None:
        return None

    odds_value = bet.get("odds_original") or bet.get("odds")
    odds_decimal = _to_decimal_or_none(odds_value)
    if odds_decimal is None:
        return None

    try:
        total_return = stake_eur * odds_decimal
        return total_return.quantize(Decimal("0.01"))
    except Exception:
        return None



def _build_bet_table(bets: List[Dict[str, Any]]) -> pd.DataFrame:
    rows: List[Dict[str, str]] = []
    for bet in bets:
        stake_display, eur_display = _format_stake_displays(bet)
        odds_value = bet.get("odds_original") or bet.get("odds")
        potential_win = _potential_win_eur(bet)
        rows.append(
            {
                "Associate": bet.get("associate_name") or "�",
                "Bookmaker": bet.get("bookmaker_name") or "�",
                "Stake": stake_display,
                "EUR": eur_display,
                "Odds": str(odds_value) if odds_value not in (None, "") else "�",
                "Potential Winning (EUR)": _format_amount_code(potential_win, "EUR")
                if potential_win is not None
                else "�",
            }
        )
    return pd.DataFrame(rows)

STATUS_STYLES: Dict[str, Dict[str, str]] = {
    "unsafe": {"color": "#dc2626", "label": "UNSAFE"},
    "safe": {"color": "#22c55e", "label": "SAFE"},
    "attention": {"color": "#f97316", "label": "ATTENTION"},
    "default": {"color": "#6366f1", "label": "SUREBET"},
}


def _metric_block(label: str, value: str, *, color: Optional[str] = None) -> str:
    color = color or "var(--text)"
    return (
        f"<div style='display:flex;flex-direction:column;gap:0.1rem;'>"
        f"<span style='font-size:1.15rem;font-weight:600;color:{color};'>{value}</span>"
        f"<span style='color:#94a3b8;font-size:0.8rem;text-transform:uppercase;letter-spacing:0.06em;'>{label}</span>"
        f"</div>"
    )


def _info_block(label: str, value: str) -> str:
    return (
        f"<div style='display:flex;flex-direction:column;gap:0.05rem;'>"
        f"<span style='color:#94a3b8;font-size:0.75rem;text-transform:uppercase;'>{label}</span>"
        f"<span style='font-weight:500;color:#e2e8f0;'>{value}</span>"
        f"</div>"
    )


def _describe_side_context(
    *,
    side_label: str,
    event_title: str,
    default_market_display: str,
    default_period_scope: Optional[str],
    default_line_value: Optional[str],
    side_bets: List[Dict[str, Any]],
) -> str:
    """
    Build a caption describing the requested context (event, market, side, line).
    """

    market_display = default_market_display
    period_scope = default_period_scope
    line_value = default_line_value
    selection_side: Optional[str] = None

    for bet in side_bets:
        if not selection_side:
            selection_side = bet.get("outcome_side") or bet.get("selection_text")
        if market_display == default_market_display:
            market_code = bet.get("bet_market_code")
            if market_code:
                market_display = format_market_display(market_code)
        if not period_scope and bet.get("bet_period_scope"):
            period_scope = bet.get("bet_period_scope")
        if (line_value in (None, "", "N/A")) and bet.get("bet_line_value"):
            line_value = bet.get("bet_line_value")

    market_fragment = f"Market: {market_display}"
    if period_scope:
        market_fragment = f"{market_fragment} ({period_scope.replace('_', ' ').title()})"

    line_fragment = (
        f"Line: {line_value}"
        if line_value not in (None, "", "N/A")
        else "Line: N/A"
    )

    return " | ".join(
        [
            f"Event: {event_title}",
            market_fragment,
            f"Side: {selection_side or side_label}",
            line_fragment,
        ]
    )


def _render_side_screenshot_preview(
    label: str, side_bets: List[Dict[str, Any]]
) -> None:
    """
    Render thumbnail previews for all available screenshots on a side.
    """

    screenshot_bets = [bet for bet in side_bets if bet.get("screenshot_path")]
    if not screenshot_bets:
        st.caption(f"No screenshot for {label}")
        return

    cols = st.columns(min(2, len(screenshot_bets)))
    for idx, bet in enumerate(screenshot_bets):
        col = cols[idx % len(cols)]
        with col:
            render_thumbnail(
                bet["screenshot_path"],
                caption=f"{label} · {bet.get('associate_name') or 'Associate'} · Bet #{bet['bet_id']}",
                width=260,
                expander_label=None,
            )

def render_surebets_page_header(description: str) -> None:
    """Render shared controls and success banners for Surebets pages."""
    toggle_cols = st.columns([6, 2])
    with toggle_cols[1]:
        render_debug_toggle(":material/monitor_heart: Performance debug")

    action_cols = st.columns([6, 2])
    with action_cols[1]:
        render_reset_control(
            key="surebets_page_reset",
            description="Clear Surebets filters, dialogs, and cached selections.",
            prefixes=("verified_bets_", "filters_", "advanced_", "dialog_", "settlement_"),
        )

    if "settlement_success_message" in st.session_state:
        st.success(st.session_state.pop("settlement_success_message"))
        render_navigation_link(
            "pages/6_reconciliation.py",
            label="Go To Reconciliation",
            icon=":material/account_balance:",
            help_text="Open 'Reconciliation' from navigation to confirm settlement impact.",
        )

    st.markdown(description)

def _navigate_to_settlement_page() -> None:
    """Attempt to navigate to the standalone settlement page."""
    try:
        st.switch_page(SETTLEMENT_PAGE_SCRIPT)
    except Exception:
        st.session_state["surebets_show_settlement_hint"] = True
        safe_rerun()

# ========================================
# Settlement Interface Helper Functions
# ========================================


def calculate_time_since_kickoff(kickoff_time_utc: str) -> Dict[str, any]:  # type: ignore[valid-type]
    """
    Calculate time elapsed since kickoff.

    Args:
        kickoff_time_utc: ISO8601 UTC timestamp with Z suffix

    Returns:
        Dict with 'elapsed_hours', 'is_past', and 'display_text'
    """
    if not kickoff_time_utc:
        return {"elapsed_hours": 0.0, "is_past": False, "display_text": "Unknown"}
    try:
        # Parse UTC timestamp (remove 'Z' suffix for datetime parsing)
        kickoff_dt = datetime.fromisoformat(kickoff_time_utc.replace("Z", "+00:00"))
        now = datetime.now(kickoff_dt.tzinfo)
        delta = now - kickoff_dt

        elapsed_hours = delta.total_seconds() / 3600
        is_past = elapsed_hours > 0

        if elapsed_hours < 1:
            display_text = (
                "Starting soon"
                if elapsed_hours > -1
                else f"In {abs(int(elapsed_hours))}h"
            )
        elif elapsed_hours < 24:
            display_text = f"Completed {int(elapsed_hours)}h ago"
        else:
            days = int(elapsed_hours / 24)
            display_text = f"Completed {days}d ago"

        return {
            "elapsed_hours": elapsed_hours,
            "is_past": is_past,
            "display_text": display_text,
        }
    except Exception as e:
        logger.error("time_calculation_error", kickoff=kickoff_time_utc, error=str(e))
        return {"elapsed_hours": 0, "is_past": False, "display_text": "Unknown"}


def load_open_surebets_for_settlement() -> List[Dict]:
    """
    Load open surebets sorted by kickoff time (oldest first) for settlement.

    Returns:
        List of surebet dictionaries with event and bet details
    """
    db = get_db_connection()

    query = """
        SELECT
            s.id as surebet_id,
            s.market_code,
            s.period_scope,
            s.line_value,
            s.status,
            s.coverage_proof_sent_at_utc,
            s.created_at_utc,
            e.normalized_event_name as event_name,
            e.kickoff_time_utc,
            e.sport,
            e.league
        FROM surebets s
        JOIN canonical_events e ON s.canonical_event_id = e.id
        WHERE s.status = 'open'
        ORDER BY e.kickoff_time_utc ASC
    """

    rows = db.execute(query).fetchall()
    surebets = [dict(row) for row in rows]

    # Load bets for each surebet
    for surebet in surebets:
        surebet["bets"] = load_surebet_bets(db, surebet["surebet_id"])
        surebet["time_info"] = calculate_time_since_kickoff(surebet["kickoff_time_utc"])

    db.close()
    return surebets


def get_default_bet_outcomes(
    bets: Dict[str, List[Dict]], base_outcome: Literal["A_WON", "B_WON"]
) -> Dict[int, str]:
    """
    Get default bet outcomes based on base outcome selection.

    Args:
        bets: Dictionary with 'A' and 'B' side bets
        base_outcome: Which side won ("A_WON" or "B_WON")

    Returns:
        Dictionary mapping bet_id to outcome ("WON", "LOST", "VOID")
    """
    outcomes = {}

    if base_outcome == "A_WON":
        # Side A bets default to WON
        for bet in bets.get("A", []):
            outcomes[bet["bet_id"]] = "WON"
        # Side B bets default to LOST
        for bet in bets.get("B", []):
            outcomes[bet["bet_id"]] = "LOST"
    else:  # B_WON
        # Side A bets default to LOST
        for bet in bets.get("A", []):
            outcomes[bet["bet_id"]] = "LOST"
        # Side B bets default to WON
        for bet in bets.get("B", []):
            outcomes[bet["bet_id"]] = "WON"

    return outcomes


def count_settled_today() -> int:
    """Count surebets settled today."""
    db = get_db_connection()
    today_start = (
        datetime.now(timezone.utc)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )

    count = db.execute(
        """SELECT COUNT(*) as cnt FROM surebets
           WHERE status = 'settled' AND settled_at_utc >= ?""",
        (today_start,),
    ).fetchone()["cnt"]

    db.close()
    return count


def validate_settlement_submission(
    base_outcome: Optional[str], bet_outcomes: Dict[int, str]
) -> tuple[bool, str]:
    """
    Validate settlement submission before processing.

    Args:
        base_outcome: Selected base outcome ("A_WON" or "B_WON" or None)
        bet_outcomes: Dictionary of bet outcomes

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Check base outcome selected
    if not base_outcome:
        return False, "Please select a base outcome (Side A WON or Side B WON)"

    # Check if all bets are VOID
    if bet_outcomes:
        all_void = all(outcome == "VOID" for outcome in bet_outcomes.values())
        if all_void:
            return (
                False,
                "WARNING: All bets marked VOID. Please confirm this is correct.",
            )

    return True, ""


def _format_amount_code(amount, code: str) -> str:
    try:
        if amount is None:
            return f"{code} 0.00"
        if isinstance(amount, str):
            amount = Decimal(amount)
        return f"{code} {amount:,.2f}"
    except Exception:
        return f"{code} 0.00"


def load_open_surebets(
    sort_by: str = "kickoff",
    show_unsafe_only: bool = False,
    filter_associate: Optional[str] = None,
) -> List[Dict]:
    """
    Load all open surebets with event and risk details.

    Args:
        sort_by: Sort order ("kickoff", "roi", "staked")
        show_unsafe_only: Filter to show only unsafe surebets
        filter_associate: Filter by associate name (None for all)

    Returns:
        List of surebet dictionaries with all display data
    """
    db = get_db_connection()

    # Base query with all required joins
    query = """
        SELECT
            s.id as surebet_id,
            s.market_code,
            s.period_scope,
            s.line_value,
            s.worst_case_profit_eur,
            s.total_staked_eur,
            s.roi,
            s.risk_classification,
            s.coverage_proof_sent_at_utc,
            s.created_at_utc,
            e.normalized_event_name as event_name,
            e.kickoff_time_utc,
            e.sport,
            e.league
        FROM surebets s
        JOIN canonical_events e ON s.canonical_event_id = e.id
        WHERE s.status = 'open'
    """

    # Add unsafe filter if requested
    if show_unsafe_only:
        query += " AND s.risk_classification = 'Unsafe'"

    # Add associate filter if requested
    if filter_associate and filter_associate != "All":
        query += """
            AND s.id IN (
                SELECT DISTINCT sb.surebet_id
                FROM surebet_bets sb
                JOIN bets b ON sb.bet_id = b.id
                JOIN associates a ON b.associate_id = a.id
                WHERE a.display_alias = ?
            )
        """

    # Add sorting
    if sort_by == "roi":
        query += " ORDER BY CAST(s.roi AS REAL) ASC"  # Lowest ROI first (risky at top)
    elif sort_by == "staked":
        query += " ORDER BY CAST(s.total_staked_eur AS REAL) DESC"  # Largest first
    else:  # Default: kickoff
        query += " ORDER BY e.kickoff_time_utc ASC"

    # Execute query
    params = (
        (filter_associate,) if filter_associate and filter_associate != "All" else ()
    )
    rows = db.execute(query, params).fetchall()

    # Convert to list of dicts
    surebets = [dict(row) for row in rows]

    # Load bets for each surebet
    for surebet in surebets:
        surebet["bets"] = load_surebet_bets(db, surebet["surebet_id"])

    db.close()
    return surebets


def load_surebet_bets(db, surebet_id: int) -> Dict[str, List[Dict]]:
    """
    Load all bets for a surebet grouped by side.

    Args:
        db: Database connection
        surebet_id: ID of the surebet

    Returns:
        Dictionary with keys "A" and "B", each containing list of bet dicts
    """
    query = """
        SELECT
            b.id as bet_id,
            b.stake_original,
            b.odds_original,
            b.odds as odds,
            b.currency,
            b.stake_eur,
            b.screenshot_path,
            b.selection_text,
            b.market_code as bet_market_code,
            b.period_scope as bet_period_scope,
            b.line_value as bet_line_value,
            b.side as outcome_side,
            sb.side,
            a.display_alias as associate_name,
            bk.bookmaker_name
        FROM bets b
        JOIN surebet_bets sb ON b.id = sb.bet_id
        JOIN associates a ON b.associate_id = a.id
        JOIN bookmakers bk ON b.bookmaker_id = bk.id
        WHERE sb.surebet_id = ?
        ORDER BY sb.side, b.associate_id
    """

    rows = db.execute(query, (surebet_id,)).fetchall()
    bets = [dict(row) for row in rows]

    # Group by side
    grouped = {"A": [], "B": []}
    for bet in bets:
        side = bet.pop("side")
        grouped[side].append(bet)

    return grouped


def _render_surebets_overview_fragment(
    *,
    sort_by: str,
    show_unsafe_only: bool,
    filter_associate: str,
) -> None:
    """Render the surebets overview list inside a fragment."""
    with track_timing("surebets_overview"):
        surebets = load_open_surebets(
            sort_by=sort_by,
            show_unsafe_only=show_unsafe_only,
            filter_associate=filter_associate,
        )

        if not surebets:
            st.info("No surebets found matching your filters.")
            return

        total_rows = len(surebets)
        pagination = paginate("surebets_overview", total_rows, label="surebets")
        start = pagination.offset
        end = start + pagination.limit
        page_surebets = surebets[start:end]

        st.markdown(f"### Surebets ({total_rows} found)")
        st.caption(
            f"Showing {pagination.start_row}-{pagination.end_row} of {total_rows} surebets"
        )
        for surebet in page_surebets:
            render_surebet_card(surebet)


def count_open_surebets() -> int:
    """Count total open surebets."""
    db = get_db_connection()
    count = db.execute(
        "SELECT COUNT(*) as cnt FROM surebets WHERE status = 'open'"
    ).fetchone()["cnt"]
    db.close()
    return count


def count_unsafe_surebets() -> int:
    """Count unsafe surebets."""
    db = get_db_connection()
    count = db.execute(
        """SELECT COUNT(*) as cnt FROM surebets
           WHERE status = 'open' AND risk_classification = 'Unsafe'"""
    ).fetchone()["cnt"]
    db.close()
    return count


def load_associates() -> List[str]:
    """Load all associate display names for filtering."""
    db = get_db_connection()
    rows = db.execute(
        "SELECT display_alias FROM associates ORDER BY display_alias"
    ).fetchall()
    db.close()
    return [row["display_alias"] for row in rows]



def render_surebet_card(surebet: Dict) -> None:
    """Render a detailed surebet card with risk context and bet breakdown."""
    bets = surebet.get("bets", {"A": [], "B": []})
    surebet_id = surebet["surebet_id"]
    bet_alias_source = bets.get("A", []) + bets.get("B", [])
    fallback_alias = next((bet.get("selection_text") for bet in bet_alias_source if bet.get("selection_text")), None)
    event_title = _format_event_title(
        surebet.get("canonical_event_name") or surebet.get("event_name"),
        fallback=fallback_alias,
    )

    status_key = (surebet.get("risk_classification") or "default").lower()
    status_style = STATUS_STYLES.get(status_key, STATUS_STYLES["default"])
    accent_color = status_style["color"]
    status_label = status_style["label"]

    worst_case = _to_decimal_or_none(surebet.get("worst_case_profit_eur"))
    total_staked = _to_decimal_or_none(surebet.get("total_staked_eur"))
    roi_value = _to_decimal_or_none(surebet.get("roi"))

    worst_case_text = _format_amount_code(worst_case, "EUR")
    profit_color = "#22c55e" if (worst_case or Decimal("0")) >= 0 else "#dc2626"
    roi_text = format_percentage(roi_value)
    roi_color = "#22c55e" if (roi_value or Decimal("0")) >= 0 else "#dc2626"
    staked_text = _format_amount_code(total_staked, "EUR")

    kickoff_value = format_utc_datetime_local(surebet.get("kickoff_time_utc")) or "TBD"
    sport_value = surebet.get("sport") or "TBD"
    league_value = surebet.get("league") or "TBD"
    coverage_sent = surebet.get("coverage_proof_sent_at_utc")
    triggered_action: Optional[str] = None

    with st.container(border=True):
        header_cols = st.columns([3, 1])
        with header_cols[0]:
            st.markdown(f"### {event_title}")
            market_display = format_market_display(surebet["market_code"])
            details = [market_display]
            if surebet.get("period_scope"):
                details.append(surebet["period_scope"].replace("_", " ").title())
            if surebet.get("line_value"):
                details.append(f"Line: {surebet['line_value']}")
            st.caption(" \u00b7 ".join(details))

        with header_cols[1]:
            st.markdown(
                f"<div style='text-align:right;font-weight:600;color:{accent_color};'>{status_label}</div>",
                unsafe_allow_html=True,
            )

        st.markdown(
            f"<div style='height:4px;background:{accent_color};border-radius:999px;margin:0.25rem 0 1rem;'></div>",
            unsafe_allow_html=True,
        )

        metric_cols = st.columns(3)
        metric_cols[0].markdown(
            _metric_block("Worst-case Profit", worst_case_text, color=profit_color),
            unsafe_allow_html=True,
        )
        metric_cols[1].markdown(
            _metric_block("ROI", roi_text, color=roi_color),
            unsafe_allow_html=True,
        )
        metric_cols[2].markdown(
            _metric_block("Total Staked", staked_text),
            unsafe_allow_html=True,
        )

        st.markdown("---")

        info_cols = st.columns(3)
        info_cols[0].markdown(_info_block("Kickoff", kickoff_value), unsafe_allow_html=True)
        info_cols[1].markdown(_info_block("Sport", sport_value), unsafe_allow_html=True)
        info_cols[2].markdown(_info_block("League", league_value), unsafe_allow_html=True)

        st.markdown("#### Bets")
        bet_col_a, bet_col_b = st.columns(2)
        with bet_col_a:
            st.markdown("**Side A**")
            st.caption(
                _describe_side_context(
                    side_label="Side A",
                    event_title=event_title,
                    default_market_display=market_display,
                    default_period_scope=surebet.get("period_scope"),
                    default_line_value=surebet.get("line_value"),
                    side_bets=bets.get("A", []),
                )
            )
            side_a_df = _build_bet_table(bets.get("A", []))
            if side_a_df.empty:
                st.caption("No bets on Side A")
            else:
                st.dataframe(side_a_df, hide_index=True, use_container_width=True)
        with bet_col_b:
            st.markdown("**Side B**")
            st.caption(
                _describe_side_context(
                    side_label="Side B",
                    event_title=event_title,
                    default_market_display=market_display,
                    default_period_scope=surebet.get("period_scope"),
                    default_line_value=surebet.get("line_value"),
                    side_bets=bets.get("B", []),
                )
            )
            side_b_df = _build_bet_table(bets.get("B", []))
            if side_b_df.empty:
                st.caption("No bets on Side B")
            else:
                st.dataframe(side_b_df, hide_index=True, use_container_width=True)

        st.markdown("")
        if coverage_sent:
            sent_at = format_utc_datetime_local(coverage_sent)
            st.caption(f":material/schedule: Coverage proof sent at {sent_at}")
        else:
            st.caption("Coverage proof not yet sent.")

        button_cols = st.columns(2)
        send_label = "Send Coverage Proof" if not coverage_sent else "Re-send Coverage Proof"
        send_action = "send_coverage" if not coverage_sent else "resend_coverage"
        with button_cols[0]:
            if st.button(
                send_label,
                key=f"surebet_send_coverage_{surebet_id}",
                use_container_width=True,
            ):
                triggered_action = send_action
        with button_cols[1]:
            if st.button(
                "Open Settlement Page",
                key=f"surebet_settle_{surebet_id}",
                use_container_width=True,
            ):
                triggered_action = "settle"

        with st.expander("Detailed Breakdown"):
            def _sum_pl_if_side_wins(winning_bets, losing_bets):
                profit = Decimal("0")
                lost = Decimal("0")
                for b in winning_bets:
                    s = _stake_eur_for_bet(b)
                    o_val = (
                        b.get("odds_original")
                        if b.get("odds_original") not in (None, "")
                        else b.get("odds")
                    )
                    o = Decimal(str(o_val)) if o_val not in (None, "") else None
                    if s is not None and o is not None:
                        profit += s * (o - Decimal("1"))
                for b in losing_bets:
                    s = _stake_eur_for_bet(b)
                    if s is not None:
                        lost += s
                return profit - lost, profit, lost

            pl_a_net, pl_a_profit, pl_a_lost = _sum_pl_if_side_wins(bets["A"], bets["B"])
            pl_b_net, pl_b_profit, pl_b_lost = _sum_pl_if_side_wins(bets["B"], bets["A"])

            outcome_cols = st.columns(2)
            with outcome_cols[0]:
                st.write(f"**If Side A wins:** {_format_amount_code(pl_a_net, 'EUR')}")
                st.caption(
                    f"Profit on A: {_format_amount_code(pl_a_profit, 'EUR')}  ·  "
                    f"Lost on B: {_format_amount_code(pl_a_lost, 'EUR')}"
                )
            with outcome_cols[1]:
                st.write(f"**If Side B wins:** {_format_amount_code(pl_b_net, 'EUR')}")
                st.caption(
                    f"Profit on B: {_format_amount_code(pl_b_profit, 'EUR')}  ·  "
                    f"Lost on A: {_format_amount_code(pl_b_lost, 'EUR')}"
                )

            screenshots = st.columns(2)
            with screenshots[0]:
                _render_side_screenshot_preview("Side A", bets["A"])
            with screenshots[1]:
                _render_side_screenshot_preview("Side B", bets["B"])

    st.markdown("---")

    if triggered_action == "send_coverage":
        st.session_state[f"send_coverage_{surebet_id}"] = True
        safe_rerun()
    elif triggered_action == "resend_coverage":
        open_dialog(f"confirm_resend_{surebet_id}")
        st.session_state[f"pending_resend_id_{surebet_id}"] = True
        safe_rerun()
    elif triggered_action == "settle":
        _navigate_to_settlement_page()

    if st.session_state.get(f"pending_resend_id_{surebet_id}", False):
        decision = render_confirmation_dialog(
            key=f"confirm_resend_{surebet_id}",
            title="Re-send coverage proof?",
            body="Associates will receive the coverage proof again. Continue?",
            confirm_label="Re-send",
            confirm_type="secondary",
        )
        if decision is not None:
            st.session_state.pop(f"pending_resend_id_{surebet_id}", None)
            if decision:
                st.session_state[f"resend_coverage_{surebet_id}"] = True
            st.session_state.pop(f"confirm_resend_{surebet_id}", None)
            safe_rerun()

def render_settlement_preview(
    surebet_id: int,
    index: int,
    preview,
    stored_outcomes: Dict[int, str],
) -> None:
    """Render settlement preview with confirmation controls."""
    st.markdown("---")
    st.markdown("### 🎯 Equal-Split Settlement Preview")

    # Guard against stale previews
    base_outcome_key = f"base_outcome_{surebet_id}_{index}"
    stored_base_key = f"settlement_preview_base_{surebet_id}"
    stored_base_outcome = st.session_state.get(stored_base_key)
    current_base_outcome = st.session_state.get(base_outcome_key)

    if stored_base_outcome is not None and current_base_outcome != stored_base_outcome:
        st.warning(
            "Base outcome changed since preview. Please regenerate the preview before confirming."
        )
        return

    if stored_outcomes:
        for bet_id, expected_outcome in stored_outcomes.items():
            outcome_key = f"outcome_{surebet_id}_{bet_id}_{index}"
            current_outcome = st.session_state.get(outcome_key)
            if current_outcome is not None and current_outcome != expected_outcome:
                st.warning(
                    "Bet outcomes changed since preview. Please regenerate the preview before confirming."
                )
                return

    # Display warnings first
    if preview.warnings:
        for warning in preview.warnings:
            if "⚠️" in warning:
                st.warning(warning)
            else:
                st.info(warning)

    # Summary metrics
    st.markdown("#### Settlement Summary")
    summary_cols = st.columns(3)

    with summary_cols[0]:
        st.metric(
            "Surebet Profit/Loss",
            f"€{preview.surebet_profit_eur:,.2f}",
            delta=(
                "Profit"
                if preview.surebet_profit_eur > 0
                else "Loss" if preview.surebet_profit_eur < 0 else None
            ),
        )

    with summary_cols[1]:
        st.metric("Participants", preview.num_participants)

    with summary_cols[2]:
        st.metric("Per-Surebet Share", f"€{preview.per_surebet_share_eur:,.2f}")

    st.markdown("---")

    # Per-bet net gains
    st.markdown("#### Per-Bet Net Gains")
    with st.expander("View per-bet calculations", expanded=False):
        net_gains_data = []
        for participant in preview.participants:
            net_gain = preview.per_bet_net_gains[participant.bet_id]
            net_gains_data.append(
                {
                    "Bet ID": participant.bet_id,
                    "Associate": participant.associate_alias,
                    "Bookmaker": participant.bookmaker_name,
                    "Outcome": participant.outcome.value,
                    "Stake (EUR)": f"€{participant.stake_eur:,.2f}",
                    "Odds": f"{participant.odds:.2f}",
                    "Net Gain (EUR)": f"€{net_gain:,.2f}",
                    "Currency": participant.currency,
                    "FX Rate": f"{participant.fx_rate:.4f}",
                }
            )

        st.dataframe(net_gains_data, width="stretch", hide_index=True)

    st.markdown("---")

    # Participant breakdown
    st.markdown("#### Participant Settlement Breakdown")
    ledger_data = []
    for entry in preview.ledger_entries:
        ledger_data.append(
            {
                "Bet ID": entry.bet_id,
                "Associate": entry.associate_alias,
                "Bookmaker": entry.bookmaker_name,
                "Outcome": entry.outcome,
                "Principal Returned": f"€{entry.principal_returned_eur:,.2f}",
                "Per-Surebet Share": f"€{entry.per_surebet_share_eur:,.2f}",
                "Total Amount": f"€{entry.total_amount_eur:,.2f}",
                "Currency": entry.currency,
                "FX Rate": f"{entry.fx_rate:.4f}",
            }
        )

    st.dataframe(ledger_data, width="stretch", hide_index=True)

    st.markdown("---")

    # Settlement batch info
    st.markdown("#### Settlement Batch Details")
    st.caption(f"**Batch ID:** `{preview.settlement_batch_id}`")
    st.caption("**Settlement Time:** Preview only (not yet committed)")

    st.markdown("---")

    confirm_cols = st.columns([3, 2])
    with confirm_cols[0]:
        confirmation_note = render_settlement_confirmation(
            key=f"settlement_confirm_{surebet_id}_{index}",
            warning_text="This action is PERMANENT and will write ledger entries.",
        )
        if confirmation_note is not None:
            confirmation_holder: Dict[str, SettlementConfirmation] = {}

            def _commit_settlement() -> None:
                service = LedgerEntryService()
                try:
                    confirmation_holder["value"] = service.confirm_settlement(
                        preview.surebet_id,
                        preview,
                        created_by="streamlit_ui",
                    )
                finally:
                    service.close()

            try:
                list(
                    status_with_steps(
                        f"Settlement for Surebet {surebet_id}",
                        [
                            ":material/rule: Validating preview inputs",
                            (":material/receipt_long: Writing ledger entries", _commit_settlement),
                            ":material/task_alt: Finalising settlement state",
                        ],
                    )
                )
            except SettlementCommitError as error:
                handle_streaming_error(error, f"settlement_{surebet_id}")
                return
            except ValueError as error:
                st.error(str(error))
                return

            confirmation = confirmation_holder.get("value")
            if not confirmation:
                st.error("Settlement did not return a confirmation payload.")
                return

            logger.info(
                "settlement_confirmed_via_dialog",
                surebet_id=surebet_id,
                settlement_batch_id=confirmation.settlement_batch_id,
                confirmation_note=confirmation_note or None,
            )
            show_success_toast(
                f"Settlement committed. Batch ID: {confirmation.settlement_batch_id}"
            )
            render_navigation_link(
                "pages/6_reconciliation.py",
                label="Go To Reconciliation",
                icon=":material/account_balance:",
                help_text="Open 'Reconciliation' from navigation to confirm settlement impact.",
            )
            st.session_state.pop(f"settlement_preview_{surebet_id}", None)
            st.session_state.pop(f"settlement_preview_outcomes_{surebet_id}", None)
            st.session_state.pop(f"settlement_preview_base_{surebet_id}", None)
            st.session_state["settlement_success_message"] = (
                f"Settlement complete for surebet {surebet_id} - Batch {confirmation.settlement_batch_id}"
            )
            safe_rerun()

    with confirm_cols[1]:
        if st.button(
            "Cancel Preview",
            key=f"cancel_preview_{surebet_id}_{index}",
            width="stretch",
        ):
            st.session_state.pop(f"settlement_preview_{surebet_id}", None)
            st.session_state.pop(f"settlement_preview_outcomes_{surebet_id}", None)
            st.session_state.pop(f"settlement_preview_base_{surebet_id}", None)
            safe_rerun()


def render_settlement_surebet_card(surebet: Dict, index: int) -> None:
    """Render a surebet card for settlement with outcome selection."""
    surebet_id = surebet["surebet_id"]
    preview_key = f"settlement_preview_{surebet_id}"
    preview_outcomes_key = f"settlement_preview_outcomes_{surebet_id}"
    preview_base_key = f"settlement_preview_base_{surebet_id}"
    bets = surebet.get("bets", {"A": [], "B": []})
    bet_alias_source = bets.get("A", []) + bets.get("B", [])
    fallback_alias = next(
        (bet.get("selection_text") for bet in bet_alias_source if bet.get("selection_text")),
        None,
    )
    event_title = _format_event_title(
        surebet.get("canonical_event_name") or surebet.get("event_name"),
        fallback=fallback_alias,
    )

    with st.container(border=True):
        st.markdown(f"### {event_title}")
        market_display = format_market_display(surebet["market_code"])
        details = [market_display]
        if surebet.get("period_scope"):
            details.append(surebet["period_scope"].replace("_", " ").title())
        if surebet.get("line_value"):
            details.append(f"Line: {surebet['line_value']}")
        st.caption(" • ".join(details))

        # Divider before settlement controls
        st.markdown("---")

        base_outcome_key = f"base_outcome_{surebet_id}_{index}"
        previous_base_outcome_key = f"{base_outcome_key}_prev"
        if base_outcome_key not in st.session_state:
            st.session_state[base_outcome_key] = None
        if previous_base_outcome_key not in st.session_state:
            st.session_state[previous_base_outcome_key] = None

        st.markdown("#### Settlement Outcome")
        st.caption("Select base outcome:")
        button_cols = st.columns(2)
        current_selection = st.session_state.get(base_outcome_key)
        with button_cols[0]:
            if st.button(
                "Side A WON / Side B LOST",
                key=f"{base_outcome_key}_btn_a",
                use_container_width=True,
                type="primary" if current_selection == "A_WON" else "secondary",
            ):
                st.session_state[base_outcome_key] = "A_WON"
                current_selection = "A_WON"
        with button_cols[1]:
            if st.button(
                "Side B WON / Side A LOST",
                key=f"{base_outcome_key}_btn_b",
                use_container_width=True,
                type="primary" if current_selection == "B_WON" else "secondary",
            ):
                st.session_state[base_outcome_key] = "B_WON"
                current_selection = "B_WON"

        base_outcome = current_selection

        st.markdown("---")

        st.markdown("#### Bets")
        bets = surebet.get("bets", {"A": [], "B": []})

        default_outcomes = (
            get_default_bet_outcomes(bets, base_outcome) if base_outcome else {}
        )

        previous_base_outcome = st.session_state.get(previous_base_outcome_key)

        if base_outcome and base_outcome != previous_base_outcome:
            for side in ("A", "B"):
                for bet in bets.get(side, []):
                    bet_id = bet["bet_id"]
                    outcome_key = f"outcome_{surebet_id}_{bet_id}_{index}"
                    default_value = default_outcomes.get(
                        bet_id, "WON" if side == "A" else "LOST"
                    )
                    st.session_state[outcome_key] = default_value
            st.session_state[previous_base_outcome_key] = base_outcome
            safe_rerun()
        elif base_outcome and previous_base_outcome is None:
            st.session_state[previous_base_outcome_key] = base_outcome
            safe_rerun()

        bet_col_a, bet_col_b = st.columns(2)

        with bet_col_a:
            st.markdown("**Side A Bets**")
            if bets["A"]:
                for bet in bets["A"]:
                    bet_id = bet["bet_id"]
                    native_amt = (
                        Decimal(bet["stake_original"])
                        if bet["stake_original"]
                        else None
                    )
                    stake_display = (
                        _format_amount_code(native_amt, bet["currency"])
                        if native_amt is not None
                        else "N/A"
                    )
                    odds_disp = (
                        bet.get("odds_original")
                        if bet.get("odds_original") not in (None, "")
                        else bet.get("odds")
                    )

                    st.write(
                        f"**Bet #{bet_id}:** {bet['associate_name']} @ {bet['bookmaker_name']}"
                    )
                    st.caption(f"{stake_display} @ {odds_disp}")

                    outcome_key = f"outcome_{surebet_id}_{bet_id}_{index}"
                    options = ["WON", "LOST", "VOID"]
                    current_value = st.session_state.get(
                        outcome_key, default_outcomes.get(bet_id, "WON")
                    )
                    st.selectbox(
                        "Outcome:",
                        options=options,
                        index=options.index(current_value),
                        key=outcome_key,
                        label_visibility="collapsed",
                    )

                    st.markdown("---")
            else:
                st.caption("No bets on Side A")

        with bet_col_b:
            st.markdown("**Side B Bets**")
            if bets["B"]:
                for bet in bets["B"]:
                    bet_id = bet["bet_id"]
                    native_amt = (
                        Decimal(bet["stake_original"])
                        if bet["stake_original"]
                        else None
                    )
                    stake_display = (
                        _format_amount_code(native_amt, bet["currency"])
                        if native_amt is not None
                        else "N/A"
                    )
                    odds_disp = (
                        bet.get("odds_original")
                        if bet.get("odds_original") not in (None, "")
                        else bet.get("odds")
                    )

                    st.write(
                        f"**Bet #{bet_id}:** {bet['associate_name']} @ {bet['bookmaker_name']}"
                    )
                    st.caption(f"{stake_display} @ {odds_disp}")

                    outcome_key = f"outcome_{surebet_id}_{bet_id}_{index}"
                    options = ["WON", "LOST", "VOID"]
                    current_value = st.session_state.get(
                        outcome_key, default_outcomes.get(bet_id, "LOST")
                    )
                    st.selectbox(
                        "Outcome:",
                        options=options,
                        index=options.index(current_value),
                        key=outcome_key,
                        label_visibility="collapsed",
                    )

                    st.markdown("---")
            else:
                st.caption("No bets on Side B")

        st.markdown("---")
        if st.button(
            "🧮 Preview Settlement",
            key=f"settle_btn_{surebet_id}_{index}",
            width="stretch",
        ):
            all_bets = bets["A"] + bets["B"]
            bet_outcomes: Dict[int, str] = {}
            for bet in all_bets:
                bet_id = bet["bet_id"]
                outcome_key = f"outcome_{surebet_id}_{bet_id}_{index}"
                bet_outcomes[bet_id] = st.session_state.get(outcome_key, "WON")

            is_valid, error_msg = validate_settlement_submission(
                base_outcome, bet_outcomes
            )

            if not is_valid:
                st.error(error_msg)
            else:
                try:
                    settlement_service = SettlementService()
                    outcomes_enum = {
                        int(bet_id): BetOutcome[outcome_str]
                        for bet_id, outcome_str in bet_outcomes.items()
                    }
                    preview = settlement_service.preview_settlement(
                        surebet_id, outcomes_enum
                    )
                    st.session_state[preview_key] = preview
                    st.session_state[preview_outcomes_key] = dict(bet_outcomes)
                    if base_outcome:
                        st.session_state[preview_base_key] = base_outcome
                except Exception as e:
                    st.error(f"Failed to generate settlement preview: {str(e)}")
                    logger.error(
                        "settlement_preview_error",
                        surebet_id=surebet_id,
                        error=str(e),
                        exc_info=True,
                    )
        stored_preview = st.session_state.get(preview_key)
    if stored_preview is not None:
        stored_outcomes = st.session_state.get(preview_outcomes_key, {})
        render_settlement_preview(surebet_id, index, stored_preview, stored_outcomes)


async def process_coverage_proof_send(
    surebet_id: int, resend: bool = False
) -> List[Dict]:
    """
    Process coverage proof send for a surebet.

    Args:
        surebet_id: ID of the surebet
        resend: Whether this is a resend

    Returns:
        List of results from coverage proof service
    """
    service = CoverageProofService()
    results = await service.send(surebet_id, resend=resend)
    service.close()
    return results


# Process coverage proof sends from session state
for key in list(st.session_state.keys()):
    if key.startswith("send_coverage_") or key.startswith("resend_coverage_"):
        # Extract surebet ID
        surebet_id = int(key.split("_")[-1])
        is_resend = key.startswith("resend_coverage_")

        # Process send
        with st.spinner(f"Sending coverage proof for surebet {surebet_id}..."):
            try:
                results = asyncio.run(
                    process_coverage_proof_send(surebet_id, resend=is_resend)
                )

                # Display results
                success_count = sum(1 for r in results if r.success)
                total_count = len(results)

                if success_count == total_count and total_count > 0:
                    st.success(f"✓ Coverage proof sent to {success_count} associate(s)")
                elif success_count > 0:
                    st.warning(
                        f"⚠️ Coverage proof sent to {success_count}/{total_count} associate(s). Some sends failed."
                    )

                    # Show detailed errors
                    for result in results:
                        if not result.success:
                            st.error(
                                f"Failed to send to {result.associate_alias}: {result.error_message}"
                            )
                else:
                    st.error(f"✗ Failed to send coverage proof to all associates")
                    for result in results:
                        st.error(f"- {result.associate_alias}: {result.error_message}")

            except Exception as e:
                st.error(f"Error sending coverage proof: {str(e)}")
                logger.error(
                    "coverage_proof_ui_error",
                    surebet_id=surebet_id,
                    error=str(e),
                    exc_info=True,
                )

        # Clear session state
        del st.session_state[key]
        safe_rerun()

# Process outbox resend actions
for key in list(st.session_state.keys()):
    if key.startswith("coverage_outbox_resend_btn_"):
        continue
    if not (
        key.startswith(OUTBOX_RESEND_STATE_PREFIX)
        or key.startswith(LEGACY_OUTBOX_RESEND_PREFIX)
    ):
        continue

    context = st.session_state.get(key)
    if not isinstance(context, dict):
        st.session_state.pop(key, None)
        continue

    surebet_id = context.get("surebet_id")
    associate_alias = context.get("associate_alias")
    if not surebet_id:
        st.session_state.pop(key, None)
        continue

    with st.spinner(
        f"Re-sending coverage proof for surebet {surebet_id} ({associate_alias})..."
    ):
        try:
            results = asyncio.run(process_coverage_proof_send(surebet_id, resend=True))
            target_result = None
            if associate_alias:
                target_result = next(
                    (r for r in results if r.associate_alias == associate_alias),
                    None,
                )

            if target_result and target_result.success:
                show_success_toast(
                    f"Coverage proof resent to {associate_alias} (Surebet {surebet_id})."
                )
            elif target_result:
                st.error(
                    f"Failed to resend to {associate_alias}: {target_result.error_message or 'Unknown error'}"
                )
            elif results:
                show_success_toast(f"Coverage proof resent for Surebet {surebet_id}.")
            else:
                st.warning(
                    f"No coverage proof deliveries were attempted for Surebet {surebet_id}."
                )
        except Exception as error:
            st.error(f"Error resending coverage proof: {error}")
            logger.error(
                "coverage_proof_outbox_resend_error",
                surebet_id=surebet_id,
                associate=associate_alias,
                error=str(error),
                exc_info=True,
            )

    del st.session_state[key]
    safe_rerun()


# ========================================
# Page Renderers
# ========================================

def render_surebets_summary_page() -> None:
    """Render the Surebets Summary view."""
    render_surebets_page_header("Monitor, settle, and manage all open surebets.")

    if st.session_state.pop("surebets_show_settlement_hint", False):
        st.info(
            "Use the 'Surebets Ready for Settlement' page to finalize this position.",
            icon=":material/info:",
        )
        render_navigation_link(
            SETTLEMENT_PAGE_SCRIPT,
            label="Open Surebets Ready for Settlement",
            icon=":material/receipt_long:",
            help_text="Launch the settlement workflow for the selected surebet.",
        )

    st.markdown("### Summary")
    counter_cols = st.columns(2)
    total_open = count_open_surebets()
    total_unsafe = count_unsafe_surebets()
    counter_cols[0].metric("Open Surebets", total_open)
    counter_cols[1].metric("Unsafe Surebets", total_unsafe)
    st.markdown("---")
    st.markdown("### Filters & Sorting")

    def _render_filters_form() -> dict[str, object]:
        control_cols = st.columns([2, 2, 2])
        with control_cols[0]:
            sort_by_value = st.selectbox(
                "Sort by",
                ["kickoff", "roi", "staked"],
                format_func=lambda x: {
                    "kickoff": "Kickoff Time (soonest first)",
                    "roi": "ROI (lowest first - risky at top)",
                    "staked": "Total Staked (largest first)",
                }[x],
                key="surebets_sort_by",
            )
        with control_cols[1]:
            unsafe_only_value = st.checkbox("Show only unsafe (??)", key="surebets_show_unsafe")
        with control_cols[2]:
            associates = ["All"] + load_associates()
            associate_value = st.selectbox(
                "Filter by associate",
                associates,
                key="surebets_filter_associate",
            )
        return {
            "sort_by": sort_by_value,
            "show_unsafe_only": unsafe_only_value,
            "filter_associate": associate_value,
        }

    with advanced_section():
        filter_state, _ = form_gated_filters(
            "surebets_filters",
            _render_filters_form,
            submit_label="Apply Filters",
            help_text="Update overview data with the selected filters.",
        )
        sort_by = filter_state["sort_by"]
        show_unsafe_only = filter_state["show_unsafe_only"]
        filter_associate = filter_state["filter_associate"]

        st.caption("FX Rates")
        if st.button("Update FX Rates Now", width="stretch"):
            try:
                with st.spinner("Updating FX rates from API..."):
                    success = asyncio.run(fetch_daily_fx_rates())
                if success:
                    st.success("FX rates updated. Recalculating open surebets...")
                    db_fx = get_db_connection()
                    rows = db_fx.execute("SELECT id FROM surebets WHERE status='open'").fetchall()
                    calc = SurebetRiskCalculator(db_fx)
                    for r in rows:
                        sid = r["id"]
                        try:
                            data = calc.calculate_surebet_risk(sid)
                            if data:
                                calc.update_cache(sid, data)
                        except Exception as exc:  # pragma: no cover - log only
                            logger.error("surebet_fx_recalc_failed", surebet_id=sid, error=str(exc))
                    db_fx.close()
            except Exception as exc:
                st.error(f"FX update failed: {exc}")

    call_fragment(
        "surebets.overview.table",
        _render_surebets_overview_fragment,
        sort_by=sort_by,
        show_unsafe_only=show_unsafe_only,
        filter_associate=filter_associate,
    )

    render_debug_panel()


def render_surebets_settlement_page() -> None:
    """Render the standalone settlement workflow."""
    render_surebets_page_header("Settle completed surebets in chronological order by kickoff time.")

    st.markdown("### Summary")
    counter_cols = st.columns(2)
    settled_today = count_settled_today()
    still_open = count_open_surebets()
    counter_cols[0].metric("Settled Today", settled_today)
    counter_cols[1].metric("Still Open (Unsettled)", still_open)
    st.markdown("---")
    st.markdown("### Surebets Ready for Settlement")
    st.caption("Sorted by kickoff time (oldest first)")

    settlement_surebets = load_open_surebets_for_settlement()
    if not settlement_surebets:
        st.info("No open surebets available for settlement.")
    else:
        st.markdown(f"**{len(settlement_surebets)} open surebet(s)**")
        for idx, surebet in enumerate(settlement_surebets):
            render_settlement_surebet_card(surebet, idx)

    render_debug_panel()



