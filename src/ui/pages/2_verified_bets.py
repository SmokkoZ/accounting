"""
Surebets Safety Dashboard - display open surebets with risk indicators.

This page shows all open surebets with risk classifications, allowing operators
to prioritize review and identify potentially unsafe positions.
"""

import streamlit as st
from decimal import Decimal
from datetime import date
import asyncio
from typing import List, Dict, Optional
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


# Configure page
st.set_page_config(page_title="Surebets Dashboard", layout="wide")
st.title("🎯 Surebets Safety Dashboard")


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
    params = (filter_associate,) if filter_associate and filter_associate != "All" else ()
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
    count = db.execute("SELECT COUNT(*) as cnt FROM surebets WHERE status = 'open'").fetchone()[
        "cnt"
    ]
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
    rows = db.execute("SELECT display_alias FROM associates ORDER BY display_alias").fetchall()
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
                    native_amt = Decimal(bet["stake_original"]) if bet["stake_original"] else None
                    stake_display = _format_amount_code(native_amt, bet["currency"]) if native_amt is not None else "N/A"
                    # EUR conversion display (using FX table or fallback to stored stake_eur)
                    eur_converted = None
                    try:
                        if native_amt is not None and bet.get("currency"):
                            if bet["currency"].upper() == "EUR":
                                eur_converted = native_amt
                            else:
                                rate = get_fx_rate(bet["currency"], date.today())
                                eur_converted = convert_to_eur(native_amt, bet["currency"], rate)
                        elif bet.get("stake_eur"):
                            eur_converted = Decimal(bet["stake_eur"]) if bet["stake_eur"] else None
                    except Exception:
                        # If conversion fails, omit EUR display
                        eur_converted = None
                    eur_display = f" ({_format_amount_code(eur_converted, 'EUR')})" if eur_converted is not None else ""
                    st.write(
                        f"- {bet['associate_name']} @ {bet['bookmaker_name']}: "
                        f"{stake_display}{eur_display} @ {bet['odds_original']}"
                    )
            else:
                st.caption("No bets on Side A")

        with bet_col_b:
            st.markdown("**Side B**")
            if bets["B"]:
                for bet in bets["B"]:
                    # Native amount display with ISO currency code (e.g., "AUD 80.00")
                    native_amt = Decimal(bet["stake_original"]) if bet["stake_original"] else None
                    stake_display = _format_amount_code(native_amt, bet["currency"]) if native_amt is not None else "N/A"
                    # EUR conversion display (using FX table or fallback to stored stake_eur)
                    eur_converted = None
                    try:
                        if native_amt is not None and bet.get("currency"):
                            if bet["currency"].upper() == "EUR":
                                eur_converted = native_amt
                            else:
                                rate = get_fx_rate(bet["currency"], date.today())
                                eur_converted = convert_to_eur(native_amt, bet["currency"], rate)
                        elif bet.get("stake_eur"):
                            eur_converted = Decimal(bet["stake_eur"]) if bet["stake_eur"] else None
                    except Exception:
                        eur_converted = None
                    eur_display = f" ({_format_amount_code(eur_converted, 'EUR')})" if eur_converted is not None else ""
                    st.write(
                        f"- {bet['associate_name']} @ {bet['bookmaker_name']}: "
                        f"{stake_display}{eur_display} @ {bet['odds_original']}"
                    )
            else:
                st.caption("No bets on Side B")

        # Drill-down expander for detailed view
        with st.expander("📊 Detailed Breakdown"):
            st.markdown("##### Detailed EUR Calculation")

            # For drill-down, we'd need to recalculate scenario outcomes
            # For now, show available data
            detail_cols = st.columns(2)
            detail_cols[0].write(f"**If Side A wins:** Calculate profit scenario")
            detail_cols[1].write(f"**If Side B wins:** Calculate profit scenario")
            st.write(f"**Worst case:** {_format_amount_code(worst_case, 'EUR')}" )

            st.markdown("##### Screenshot Links")
            all_bets = bets["A"] + bets["B"]
            if all_bets:
                for bet in all_bets:
                    if bet.get("screenshot_path"):
                        st.write(f"- Bet #{bet['bet_id']}: `{bet['screenshot_path']}`")
            else:
                st.caption("No screenshots available")

            st.markdown("##### FX Rates Used")
            st.caption(
                "FX rate transparency: Check fx_rates_daily table for rates used in EUR conversion"
            )

        # Action buttons (placeholders for Epic 4)
        st.markdown("---")
        action_cols = st.columns([1, 1, 3])
        with action_cols[0]:
            if st.button("📤 Send Coverage Proof", key=f"coverage_{surebet['surebet_id']}"):
                st.info("Coverage proof feature coming in Epic 4")
        with action_cols[1]:
            if st.button("⚖️ Settle", key=f"settle_{surebet['surebet_id']}"):
                st.info("Settlement feature coming in Epic 4")


# Main page layout
st.markdown("Monitor all open surebets and identify risky positions requiring attention.")

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
                rows = db_fx.execute("SELECT id FROM surebets WHERE status='open'").fetchall()
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
                st.error("Failed to update FX rates from API. Check config/network.")
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
