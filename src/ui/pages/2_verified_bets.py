"""
Surebets Safety Dashboard - display open surebets with risk indicators.

This page shows all open surebets with risk classifications, allowing operators
to prioritize review and identify potentially unsafe positions.
"""

import streamlit as st
from decimal import Decimal
from datetime import date, datetime
from pathlib import Path
import asyncio
from typing import List, Dict, Optional, Literal
from src.core.database import get_db_connection
from src.ui.utils.formatters import (
    format_percentage,
    format_utc_datetime_local,
    format_market_display,
    get_risk_badge_html,
)
from src.services.fx_manager import get_fx_rate, convert_to_eur
from src.integrations.fx_api_client import fetch_daily_fx_rates
from src.services.surebet_calculator import SurebetRiskCalculator
from src.services.coverage_proof_service import CoverageProofService
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


# Configure page
st.set_page_config(page_title="Surebets Dashboard", layout="wide")
st.title("🎯 Surebets Dashboard")


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
        datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        + "Z"
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
    """
    Render a surebet card with all details and risk badge.

    Args:
        surebet: Surebet dictionary with all display data
    """
    with st.container(border=True):
        # Header row with event and risk badge
        col1, col2 = st.columns([3, 1])

        with col1:
            st.markdown(f"### {surebet['event_name']}")
            market_display = format_market_display(surebet["market_code"])
            details = [market_display]
            if surebet.get("period_scope"):
                details.append(surebet["period_scope"].replace("_", " ").title())
            if surebet.get("line_value"):
                details.append(f"Line: {surebet['line_value']}")
            st.caption(" • ".join(details))

        with col2:
            # Risk badge (prominent, right-aligned)
            st.markdown(
                get_risk_badge_html(surebet.get("risk_classification")),
                unsafe_allow_html=True,
            )

        st.markdown("---")

        # Event info row
        col_a, col_b, col_c = st.columns(3)
        col_a.metric(
            "Kickoff",
            format_utc_datetime_local(surebet.get("kickoff_time_utc")),
        )
        col_b.metric("Sport", surebet.get("sport", "—"))
        col_c.metric("League", surebet.get("league", "—"))

        # EUR calculations row
        st.markdown("#### EUR Calculations")
        calc_cols = st.columns(3)

        worst_case = surebet.get("worst_case_profit_eur")
        total_staked = surebet.get("total_staked_eur")
        roi = surebet.get("roi")

        calc_cols[0].metric("Worst-case Profit", _format_amount_code(worst_case, "EUR"))
        calc_cols[1].metric("Total Staked", _format_amount_code(total_staked, "EUR"))
        calc_cols[2].metric("ROI", format_percentage(roi))

        # Bets display
        st.markdown("#### Bets")
        bets = surebet.get("bets", {"A": [], "B": []})

        bet_col_a, bet_col_b = st.columns(2)

        with bet_col_a:
            st.markdown("**Side A**")
            if bets["A"]:
                for bet in bets["A"]:
                    # Native amount display with ISO currency code (e.g., "AUD 80.00")
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
                    # EUR conversion display (using FX table or fallback to stored stake_eur)
                    eur_converted = None
                    try:
                        if native_amt is not None and bet.get("currency"):
                            if bet["currency"].upper() == "EUR":
                                eur_converted = native_amt
                            else:
                                rate = get_fx_rate(bet["currency"], date.today())
                                eur_converted = convert_to_eur(
                                    native_amt, bet["currency"], rate
                                )
                        elif bet.get("stake_eur"):
                            eur_converted = (
                                Decimal(bet["stake_eur"]) if bet["stake_eur"] else None
                            )
                    except Exception:
                        # If conversion fails, omit EUR display
                        eur_converted = None
                    eur_display = (
                        f" ({_format_amount_code(eur_converted, 'EUR')})"
                        if eur_converted is not None
                        else ""
                    )
                    odds_disp = (
                        bet.get("odds_original")
                        if bet.get("odds_original") not in (None, "")
                        else bet.get("odds")
                    )
                    st.write(
                        f"- {bet['associate_name']} @ {bet['bookmaker_name']}: "
                        f"{stake_display}{eur_display} @ {odds_disp}"
                    )
            else:
                st.caption("No bets on Side A")

        with bet_col_b:
            st.markdown("**Side B**")
            if bets["B"]:
                for bet in bets["B"]:
                    # Native amount display with ISO currency code (e.g., "AUD 80.00")
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
                    # EUR conversion display (using FX table or fallback to stored stake_eur)
                    eur_converted = None
                    try:
                        if native_amt is not None and bet.get("currency"):
                            if bet["currency"].upper() == "EUR":
                                eur_converted = native_amt
                            else:
                                rate = get_fx_rate(bet["currency"], date.today())
                                eur_converted = convert_to_eur(
                                    native_amt, bet["currency"], rate
                                )
                        elif bet.get("stake_eur"):
                            eur_converted = (
                                Decimal(bet["stake_eur"]) if bet["stake_eur"] else None
                            )
                    except Exception:
                        eur_converted = None
                    eur_display = (
                        f" ({_format_amount_code(eur_converted, 'EUR')})"
                        if eur_converted is not None
                        else ""
                    )
                    odds_disp = (
                        bet.get("odds_original")
                        if bet.get("odds_original") not in (None, "")
                        else bet.get("odds")
                    )
                    st.write(
                        f"- {bet['associate_name']} @ {bet['bookmaker_name']}: "
                        f"{stake_display}{eur_display} @ {odds_disp}"
                    )
            else:
                st.caption("No bets on Side B")

        # Drill-down expander for detailed view
        with st.expander("📊 Detailed Breakdown"):
            st.markdown("##### Detailed EUR Calculation")

            # Compute per-side P/L in EUR
            def _stake_eur_for_bet(b):
                try:
                    if b.get("stake_eur"):
                        return Decimal(str(b["stake_eur"]))
                    native = (
                        Decimal(str(b["stake_original"]))
                        if b.get("stake_original")
                        else None
                    )
                    cur = b.get("currency")
                    if native is None or not cur:
                        return None
                    if cur.upper() == "EUR":
                        return native
                    rate = get_fx_rate(cur, date.today())
                    return convert_to_eur(native, cur, rate)
                except Exception:
                    return None

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

            pl_a_net, pl_a_profit, pl_a_lost = _sum_pl_if_side_wins(
                bets["A"], bets["B"]
            )
            pl_b_net, pl_b_profit, pl_b_lost = _sum_pl_if_side_wins(
                bets["B"], bets["A"]
            )

            detail_cols = st.columns(2)
            with detail_cols[0]:
                st.write(f"**If Side A wins:** {_format_amount_code(pl_a_net, 'EUR')}")
                st.caption(
                    f"Profit on A: {_format_amount_code(pl_a_profit, 'EUR')}  •  Lost on B: {_format_amount_code(pl_a_lost, 'EUR')}"
                )
            with detail_cols[1]:
                st.write(f"**If Side B wins:** {_format_amount_code(pl_b_net, 'EUR')}")
                st.caption(
                    f"Profit on B: {_format_amount_code(pl_b_profit, 'EUR')}  •  Lost on A: {_format_amount_code(pl_b_lost, 'EUR')}"
                )

            st.write(f"**Worst case:** {_format_amount_code(worst_case, 'EUR')}")

            st.markdown("##### Screenshot Links")
            all_bets = bets["A"] + bets["B"]
            if all_bets:
                cols = st.columns(3)
                shown = 0
                for bet in all_bets:
                    path = bet.get("screenshot_path")
                    if path:
                        try:
                            col = cols[shown % 3]
                            col.image(
                                path,
                                caption=f"Bet #{bet['bet_id']}",
                                use_column_width=True,
                            )
                            try:
                                data = Path(path).read_bytes()
                                col.download_button(
                                    label="Download",
                                    data=data,
                                    file_name=Path(path).name,
                                    mime=None,
                                )
                            except Exception:
                                pass
                            shown += 1
                        except Exception:
                            st.write(
                                f"- Bet #{bet['bet_id']}: {path} (image not found)"
                            )
            else:
                st.caption("No screenshots available")

            st.markdown("##### FX Rates Used")
            st.caption(
                "FX rate transparency: Check fx_rates_daily table for rates used in EUR conversion"
            )

        # Action buttons
        st.markdown("---")

        # Check if coverage proof has been sent
        coverage_sent = surebet.get("coverage_proof_sent_at_utc")

        action_cols = st.columns([2, 2, 1])
        with action_cols[0]:
            if coverage_sent:
                # Show "Coverage proof sent" with checkmark and re-send option
                st.success(
                    f"✓ Coverage proof sent at {format_utc_datetime_local(coverage_sent)}"
                )
            else:
                # Show "Send Coverage Proof" button
                if st.button(
                    "📤 Send Coverage Proof",
                    key=f"coverage_{surebet['surebet_id']}",
                    use_container_width=True,
                ):
                    # Store the surebet ID in session state for processing
                    st.session_state[f"send_coverage_{surebet['surebet_id']}"] = True
                    st.rerun()

        with action_cols[1]:
            if coverage_sent:
                # Show "Re-send Coverage Proof" button with confirmation modal
                if st.button(
                    "🔄 Re-send Coverage Proof",
                    key=f"resend_{surebet['surebet_id']}",
                    use_container_width=True,
                ):
                    st.session_state[f"confirm_resend_{surebet['surebet_id']}"] = True
                    st.rerun()
            else:
                st.caption("Coverage proof not sent yet")

        with action_cols[2]:
            if st.button(
                "⚖️ Settle",
                key=f"settle_{surebet['surebet_id']}",
                use_container_width=True,
            ):
                st.info("Settlement feature coming soon")

        # Handle confirmation modal for re-send
        if st.session_state.get(f"confirm_resend_{surebet['surebet_id']}", False):
            with st.container():
                st.warning(
                    "⚠️ Are you sure you want to re-send coverage proof? Associates will receive the screenshots again."
                )
                confirm_cols = st.columns([1, 1, 2])
                with confirm_cols[0]:
                    if st.button(
                        "✓ Yes, Re-send", key=f"confirm_yes_{surebet['surebet_id']}"
                    ):
                        st.session_state[f"resend_coverage_{surebet['surebet_id']}"] = (
                            True
                        )
                        del st.session_state[f"confirm_resend_{surebet['surebet_id']}"]
                        st.rerun()
                with confirm_cols[1]:
                    if st.button("✗ Cancel", key=f"confirm_no_{surebet['surebet_id']}"):
                        del st.session_state[f"confirm_resend_{surebet['surebet_id']}"]
                        st.rerun()


def render_settlement_surebet_card(surebet: Dict, index: int) -> None:
    """
    Render a surebet card for settlement with outcome selection.

    Args:
        surebet: Surebet dictionary with all display data
        index: Index of surebet in list (for unique keys)
    """
    surebet_id = surebet["surebet_id"]
    time_info = surebet.get("time_info", {})

    with st.container(border=True):
        # Header with event name and time indicator
        col1, col2 = st.columns([3, 1])

        with col1:
            st.markdown(f"### {surebet['event_name']}")
            market_display = format_market_display(surebet["market_code"])
            details = [market_display]
            if surebet.get("period_scope"):
                details.append(surebet["period_scope"].replace("_", " ").title())
            if surebet.get("line_value"):
                details.append(f"Line: {surebet['line_value']}")
            st.caption(" • ".join(details))

        with col2:
            # Time indicator (highlight if past)
            if time_info.get("is_past", False):
                elapsed_hours = time_info.get("elapsed_hours", 0)
                if elapsed_hours > 24:
                    st.error(f"⏰ {time_info.get('display_text', 'Past')}")
                else:
                    st.warning(f"⏰ {time_info.get('display_text', 'Past')}")
            else:
                st.info(f"⏰ {time_info.get('display_text', 'Upcoming')}")

        st.markdown("---")

        # Event info
        col_a, col_b = st.columns(2)
        col_a.metric(
            "Kickoff", format_utc_datetime_local(surebet.get("kickoff_time_utc"))
        )
        col_b.metric(
            "Sport / League",
            f"{surebet.get('sport', '—')} / {surebet.get('league', '—')}",
        )

        st.markdown("---")

        # Initialize session state for this surebet's outcome selection
        base_outcome_key = f"base_outcome_{surebet_id}_{index}"
        if base_outcome_key not in st.session_state:
            st.session_state[base_outcome_key] = None

        # Base outcome selection
        st.markdown("#### Settlement Outcome")
        base_outcome = st.radio(
            "Select base outcome:",
            options=["A_WON", "B_WON"],
            format_func=lambda x: (
                "Side A WON / Side B LOST"
                if x == "A_WON"
                else "Side B WON / Side A LOST"
            ),
            key=base_outcome_key,
            horizontal=True,
        )

        st.markdown("---")

        # Bets with outcome overrides
        st.markdown("#### Bets")
        bets = surebet.get("bets", {"A": [], "B": []})

        # Get default outcomes based on base selection
        default_outcomes = (
            get_default_bet_outcomes(bets, base_outcome) if base_outcome else {}
        )

        bet_col_a, bet_col_b = st.columns(2)

        # Side A bets
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

                    # Outcome dropdown
                    default_val = default_outcomes.get(bet_id, "WON")
                    outcome = st.selectbox(
                        "Outcome:",
                        options=["WON", "LOST", "VOID"],
                        index=["WON", "LOST", "VOID"].index(default_val),
                        key=f"outcome_{surebet_id}_{bet_id}_{index}",
                        label_visibility="collapsed",
                    )

                    # Show screenshot link
                    if bet.get("screenshot_path"):
                        try:
                            with st.expander("View Screenshot"):
                                st.image(bet["screenshot_path"], use_column_width=True)
                        except Exception:
                            st.caption(f"Screenshot: {bet['screenshot_path']}")

                    st.markdown("---")
            else:
                st.caption("No bets on Side A")

        # Side B bets
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

                    # Outcome dropdown
                    default_val = default_outcomes.get(bet_id, "LOST")
                    outcome = st.selectbox(
                        "Outcome:",
                        options=["WON", "LOST", "VOID"],
                        index=["WON", "LOST", "VOID"].index(default_val),
                        key=f"outcome_{surebet_id}_{bet_id}_{index}",
                        label_visibility="collapsed",
                    )

                    # Show screenshot link
                    if bet.get("screenshot_path"):
                        try:
                            with st.expander("View Screenshot"):
                                st.image(bet["screenshot_path"], use_column_width=True)
                        except Exception:
                            st.caption(f"Screenshot: {bet['screenshot_path']}")

                    st.markdown("---")
            else:
                st.caption("No bets on Side B")

        # Settle button (placeholder for Story 4.3+)
        st.markdown("---")
        if st.button(
            f"⚖️ Preview Settlement",
            key=f"settle_btn_{surebet_id}_{index}",
            use_container_width=True,
        ):
            # Collect all bet outcomes
            all_bets = bets["A"] + bets["B"]
            bet_outcomes = {}
            for bet in all_bets:
                bet_id = bet["bet_id"]
                outcome_key = f"outcome_{surebet_id}_{bet_id}_{index}"
                bet_outcomes[bet_id] = st.session_state.get(outcome_key, "WON")

            # Validate
            is_valid, error_msg = validate_settlement_submission(
                base_outcome, bet_outcomes
            )

            if not is_valid:
                st.error(error_msg)
            else:
                # Check for all VOID warning
                all_void = all(outcome == "VOID" for outcome in bet_outcomes.values())
                if all_void:
                    st.warning(
                        "⚠️ All bets marked VOID - settlement calculations will reflect zero profit/loss"
                    )

                st.success(f"✓ Settlement validated for Surebet #{surebet_id}")
                st.info(
                    "Settlement preview and calculation (Story 4.3) will appear here"
                )


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
    results = await service.send_coverage_proof(surebet_id, resend=resend)
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
        st.rerun()


# Main page layout with tabs
st.markdown("Monitor, settle, and manage all open surebets.")

# Create tabs
tab_overview, tab_settle = st.tabs(["📊 Overview", "⚖️ Settle"])

# ========================================
# TAB 1: OVERVIEW (Safety Dashboard)
# ========================================
with tab_overview:
    st.markdown(
        "Monitor all open surebets and identify risky positions requiring attention."
    )

    # Summary counters
    st.markdown("### Summary")
    counter_cols = st.columns(2)
    total_open = count_open_surebets()
    total_unsafe = count_unsafe_surebets()

    counter_cols[0].metric("Open Surebets", total_open)
    counter_cols[1].metric(
        "Unsafe (❌)", total_unsafe, delta=None if total_unsafe == 0 else "⚠️ Attention"
    )

    st.markdown("---")

    # Filters and sorting controls
    st.markdown("### Filters & Sorting")
    control_cols = st.columns([2, 2, 2, 2])

    with control_cols[0]:
        sort_by = st.selectbox(
            "Sort by",
            ["kickoff", "roi", "staked"],
            format_func=lambda x: {
                "kickoff": "Kickoff Time (soonest first)",
                "roi": "ROI (lowest first - risky at top)",
                "staked": "Total Staked (largest first)",
            }[x],
        )

    with control_cols[1]:
        show_unsafe_only = st.checkbox("Show only unsafe (❌)")

    with control_cols[2]:
        associates = ["All"] + load_associates()
        filter_associate = st.selectbox("Filter by associate", associates)

    with control_cols[3]:
        st.caption("FX Rates")
        if st.button("Update FX Rates Now", use_container_width=True):
            try:
                with st.spinner("Updating FX rates from API..."):
                    success = asyncio.run(fetch_daily_fx_rates())
                if success:
                    st.success("FX rates updated. Recalculating open surebets...")
                    db_fx = get_db_connection()
                    rows = db_fx.execute(
                        "SELECT id FROM surebets WHERE status='open'"
                    ).fetchall()
                    calc = SurebetRiskCalculator(db_fx)
                    for r in rows:
                        sid = r["id"]
                        try:
                            data = calc.calculate_surebet_risk(sid)
                            db_fx.execute(
                                """
                                UPDATE surebets
                                SET worst_case_profit_eur = ?,
                                    total_staked_eur = ?,
                                    roi = ?,
                                    risk_classification = ?,
                                    updated_at_utc = datetime('now') || 'Z'
                                WHERE id = ?
                                """,
                                (
                                    str(data["worst_case_profit_eur"]),
                                    str(data["total_staked_eur"]),
                                    str(data["roi"]),
                                    data["risk_classification"],
                                    sid,
                                ),
                            )
                            db_fx.commit()
                        except Exception:
                            pass
                    db_fx.close()
                    st.success("Open surebets recalculated. Refresh to view updates.")
                else:
                    st.error(
                        "Failed to update FX rates from API. Check config/network."
                    )
            except Exception as e:
                st.error(f"FX update failed: {e}")

    st.markdown("---")

    # Load and display surebets
    surebets = load_open_surebets(sort_by, show_unsafe_only, filter_associate)

    if not surebets:
        st.info("No surebets found matching your filters.")
    else:
        st.markdown(f"### Surebets ({len(surebets)} found)")

        for surebet in surebets:
            render_surebet_card(surebet)


# ========================================
# TAB 2: SETTLE (Settlement Interface)
# ========================================
with tab_settle:
    st.markdown("Settle completed surebets in chronological order by kickoff time.")

    # Settlement counters
    st.markdown("### Summary")
    counter_cols = st.columns(2)
    settled_today = count_settled_today()
    still_open = count_open_surebets()

    counter_cols[0].metric("Settled Today", settled_today)
    counter_cols[1].metric("Still Open (Unsettled)", still_open)

    st.markdown("---")

    # Load surebets for settlement (sorted by kickoff time)
    st.markdown("### Surebets Ready for Settlement")
    st.caption("Sorted by kickoff time (oldest first)")

    settlement_surebets = load_open_surebets_for_settlement()

    if not settlement_surebets:
        st.info("No open surebets available for settlement.")
    else:
        st.markdown(f"**{len(settlement_surebets)} open surebet(s)**")

        for idx, surebet in enumerate(settlement_surebets):
            render_settlement_surebet_card(surebet, idx)
