"""
Verified Bets Queue - lists approved bets awaiting matching (and optionally matched bets).

This page helps operators verify that approved bets have all the fields
required for surebet matching (canonical event, market, period, side).
"""

from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

from src.core.database import get_db_connection
from src.services.bet_verification import BetVerificationService
from src.ui.media import render_thumbnail
from src.ui.components.resolve_triage import render_resolve_queue_with_triage
from src.ui.ui_components import advanced_section, form_gated_filters, load_global_styles
from src.ui.utils.navigation_links import render_navigation_link
from src.ui.utils.state_management import render_reset_control, safe_rerun


PAGE_TITLE = "Verified Bets Queue"
PAGE_ICON = ":material/task_alt:"

st.set_page_config(page_title=PAGE_TITLE, layout="wide")
load_global_styles()

st.title(f"{PAGE_ICON} {PAGE_TITLE}")
st.caption("Review approved bets and check matching prerequisites")


def load_verified_bets(include_matched: bool, filter_associate: Optional[str]) -> List[Dict[str, Any]]:
    db = get_db_connection()

    status_clause = "b.status = 'verified'"
    if include_matched:
        status_clause = "b.status IN ('verified','matched')"

    query = f"""
        SELECT
            b.id as bet_id,
            a.display_alias as associate,
            bk.bookmaker_name as bookmaker,
            ce.normalized_event_name as event_name,
            b.selection_text as selection_text,
            b.market_code,
            b.period_scope,
            b.line_value,
            b.side,
            b.stake_original as stake,
            b.odds_original as odds,
            b.payout,
            b.currency,
            b.normalization_confidence,
            b.kickoff_time_utc,
            b.created_at_utc,
            b.updated_at_utc,
            b.canonical_event_id,
            b.screenshot_path,
            b.status
        FROM bets b
        JOIN associates a ON b.associate_id = a.id
        JOIN bookmakers bk ON b.bookmaker_id = bk.id
        LEFT JOIN canonical_events ce ON b.canonical_event_id = ce.id
        WHERE {status_clause}
    """

    params: List[Any] = []
    if filter_associate and filter_associate != "All":
        query += " AND a.display_alias = ?"
        params.append(filter_associate)

    query += " ORDER BY b.updated_at_utc DESC"

    rows = get_db_connection().execute(query, params).fetchall()
    return [dict(r) for r in rows]


def load_associate_filter_options() -> List[str]:
    """Return associate list for filter dropdown."""
    db = get_db_connection()
    try:
        rows = db.execute(
            "SELECT DISTINCT display_alias FROM associates ORDER BY display_alias"
        ).fetchall()
        return ["All"] + [row["display_alias"] for row in rows]
    finally:
        db.close()


def load_resolve_events_queue(statuses: Optional[List[str]] = None) -> pd.DataFrame:
    """Load bets requiring event resolution triage."""
    db = get_db_connection()
    try:
        rows = db.execute(
            """
            SELECT
                b.id AS bet_id,
                a.display_alias AS associate,
                b.selection_text,
                b.normalization_confidence,
                b.confidence_score,
                b.created_at_utc,
                COALESCE(b.resolve_status, 'needs_review') AS resolve_status,
                b.status,
                b.canonical_event_id
            FROM bets b
            JOIN associates a ON b.associate_id = a.id
            WHERE b.status IN ('incoming', 'verified')
              AND (b.canonical_event_id IS NULL OR COALESCE(b.resolve_status, 'needs_review') != 'auto_ok')
            ORDER BY b.created_at_utc DESC
            """
        ).fetchall()
    finally:
        db.close()

    records: List[Dict[str, Any]] = []
    for row in rows:
        raw_conf = row["normalization_confidence"] or row["confidence_score"]
        try:
            confidence_value = float(raw_conf) if raw_conf is not None else 0.0
        except (TypeError, ValueError):
            confidence_value = 0.0
        records.append(
            {
                "bet_id": row["bet_id"],
                "associate": row["associate"],
                "alias_evidence": row["selection_text"] or "(no selection text)",
                "confidence_score": confidence_value,
                "created_at_utc": row["created_at_utc"],
                "resolve_status": row["resolve_status"],
                "bet_status": row["status"],
            }
        )

    df = pd.DataFrame.from_records(records)
    if statuses and not df.empty:
        df = df[df["resolve_status"].isin(statuses)]
    return df


def bulk_mark_events_auto_ok(bet_ids: List[int]) -> int:
    """Mark the provided bet IDs as auto-resolved."""
    if not bet_ids:
        return 0

    db = get_db_connection()
    updated = 0
    try:
        for bet_id in bet_ids:
            cursor = db.execute(
                """
                UPDATE bets
                SET resolve_status = 'auto_ok',
                    updated_at_utc = datetime('now') || 'Z'
                WHERE id = ?
                """,
                (bet_id,),
            )
            updated += cursor.rowcount
        db.commit()
    finally:
        db.close()
    return updated


action_cols = st.columns([6, 2])
with action_cols[1]:
    render_reset_control(
        key="verified_queue_reset",
        description="Clear filters, edit selections, and triage state for this page.",
        prefixes=("verified_queue_", "filters_", "advanced_", "dialog_", "resolve_"),
    )


def _render_filter_form() -> Dict[str, object]:
    col1, col2 = st.columns(2)
    with col1:
        include = st.checkbox(
            "Include matched bets",
            value=False,
            key="verified_queue_include_matched",
        )
    with col2:
        associate_options = load_associate_filter_options()
        selected = st.selectbox(
            "Filter by associate",
            associate_options,
            key="verified_queue_associate",
        )
    return {"include_matched": include, "filter_associate": selected}


with advanced_section():
    filter_state, _ = form_gated_filters(
        "verified_queue_filters",
        _render_filter_form,
        submit_label="Apply Filters",
        help_text="Refresh the table with the latest filters.",
    )
    include_matched = bool(filter_state["include_matched"])
    filter_associate = filter_state["filter_associate"]

st.markdown("---")

bets = load_verified_bets(include_matched, filter_associate)

if not bets:
    st.info("No verified bets found.")
else:
    st.caption(f"Showing {len(bets)} bet(s)")

    # Present as a simple table to aid auditing
    def simplify(row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "Bet #": row["bet_id"],
            "Associate": row["associate"],
            "Bookmaker": row["bookmaker"],
            "Event": row.get("event_name") or "(unset)",
            "Market": row.get("market_code") or "(unset)",
            "Period": row.get("period_scope") or "(unset)",
            "Side": row.get("side") or "(unset)",
            "Line": row.get("line_value") or "",
            "Conf": row.get("normalization_confidence") or "",
            "Kickoff": row.get("kickoff_time_utc") or "",
            "Status": row.get("status"),
            "Screenshot": row.get("screenshot_path") or "",
        }

    table = [simplify(r) for r in bets]
    st.dataframe(table)

    # Quick checklist to highlight matching readiness
    not_ready = [
        r
        for r in bets
        if not all(
            [
                r.get("canonical_event_id") is not None,
                r.get("market_code"),
                r.get("period_scope"),
                r.get("side"),
            ]
        )
    ]

    if not_ready:
        st.warning(
            f"{len(not_ready)} bet(s) missing fields required for matching (event/market/period/side)."
        )
        with st.expander("Show details"):
            for r in not_ready:
                st.write(
                    f"- Bet #{r['bet_id']}: event={r.get('event_name') or '(unset)'} | "
                    f"market={r.get('market_code') or '(unset)'} | period={r.get('period_scope') or '(unset)'} | "
                    f"side={r.get('side') or '(unset)'}"
                )

# Resolve events triage
st.markdown("---")
st.subheader("Resolve Events Queue")
triage_cols = st.columns([2, 2])
with triage_cols[0]:
    confidence_threshold = st.slider(
        "Auto-OK threshold",
        min_value=0.5,
        max_value=1.0,
        step=0.05,
        value=0.8,
        help="Only events at or above this confidence will be eligible for bulk Auto-OK.",
    )
with triage_cols[1]:
    status_filter = st.multiselect(
        "Statuses",
        options=["needs_review", "unresolved", "auto_ok"],
        default=["needs_review", "unresolved"],
        key="resolve_status_filter",
        help="Filter the triage queue by current resolution status.",
    )

resolve_queue_df = load_resolve_events_queue(status_filter)
selected_bet_ids: List[int] = []
if resolve_queue_df.empty:
    st.info("No events require resolution right now. ✅")
else:
    selected_bet_ids = render_resolve_queue_with_triage(
        resolve_queue_df,
        selection_key="resolve_queue_triage",
        bulk_threshold=confidence_threshold,
    )

if selected_bet_ids:
    updated = bulk_mark_events_auto_ok(selected_bet_ids)
    if updated:
        st.success(f"{updated} event(s) marked as Auto-OK.")
        safe_rerun()

# Edit section
st.markdown("---")
st.subheader("Edit Verified Bet")

bet_ids = [b["bet_id"] for b in bets]
if not bet_ids:
    st.caption("No bets to edit.")
else:
    target_bet_id = st.selectbox("Select Bet # to edit", bet_ids)

    # Load helpers
    db_edit = get_db_connection()
    svc = BetVerificationService(db_edit)
    canonical_events = svc.load_canonical_events()
    canonical_markets = svc.load_canonical_markets()

    # Build event options
    event_display = [
        (
            e["id"],
            f"{e['normalized_event_name']} ({e['kickoff_time_utc'][:10] if e['kickoff_time_utc'] else 'TBD'})"
        )
        for e in canonical_events
    ]
    event_labels = ["(Keep current)"] + [label for _, label in event_display]
    event_values = [None] + [eid for eid, _ in event_display]

    # Pull current values
    current = next(b for b in bets if b["bet_id"] == target_bet_id)

    # Context: screenshot + summary
    st.markdown("### Selected Bet Context")
    ctx_col1, ctx_col2 = st.columns([1, 2])
    with ctx_col1:
        screenshot_path = current.get("screenshot_path")
        if screenshot_path:
            render_thumbnail(
                screenshot_path,
                caption=f"Bet #{current['bet_id']}",
                width=240,
                expander_label="View full-size screenshot",
            )
            st.caption(screenshot_path)
    with ctx_col2:
        st.write(f"Associate: {current.get('associate')} @ {current.get('bookmaker')}")
        st.write(f"Status: {current.get('status')}  |  Confidence: {current.get('normalization_confidence')}")
        st.write(f"Extracted event text: {current.get('selection_text') or '(none)'}")
        st.write(
            f"Market: {current.get('market_code') or '(unset)'} | Period: {current.get('period_scope') or '(unset)'} | Side: {current.get('side') or '(unset)'}"
        )
        st.write(
            f"Stake: {current.get('stake') or ''} {current.get('currency') or ''}  @ {current.get('odds') or ''}  => {current.get('payout') or ''}"
        )

    # Latest OCR raw response (full width below columns to avoid layout overlap)
    try:
        ocr = db_edit.execute(
            """
            SELECT model_version, raw_response, created_at_utc
            FROM extraction_log
            WHERE bet_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (target_bet_id,),
        ).fetchone()
        if ocr:
            with st.expander("Raw OCR extraction"):
                st.code(ocr["raw_response"] or "", language="markdown")
                st.caption(f"OCR model: {ocr['model_version']} at {ocr['created_at_utc']}")
        else:
            st.info("No OCR extraction log found for this bet.")
    except Exception:
        st.info("OCR log unavailable.")

    with st.form("edit_verified_bet_form"):
        event_choice = st.selectbox("Event", event_labels, index=0)
        market_choice = st.selectbox(
            "Market",
            ["(Keep current)"] + [f"{m['description']} ({m['market_code']})" for m in canonical_markets],
            index=0,
        )

        # Period and side
        period_options = [
            "FULL_MATCH",
            "FIRST_HALF",
            "SECOND_HALF",
            "FIRST_QUARTER",
            "SECOND_QUARTER",
        ]
        period_choice = st.selectbox(
            "Period",
            ["(Keep current)"] + period_options,
            index=0,
        )

        # Side options depend on market
        selected_market_code = None
        if market_choice != "(Keep current)":
            selected_market_code = market_choice.split("(")[-1].rstrip(")")
        else:
            selected_market_code = current.get("market_code")
        valid_sides = svc.get_valid_sides_for_market(selected_market_code)
        side_choice = st.selectbox(
            "Side",
            ["(Keep current)"] + valid_sides,
            index=0,
        )

        # Optional: line value
        line_value = st.text_input(
            "Line (optional)",
            value=str(current.get("line_value") or ""),
        )

        # Optional: relaxed event creation if not selecting from list
        st.markdown("###### Or create event (optional)")
        new_event_name = st.text_input(
            "Event Name",
            value=current.get("event_name") or "",
            placeholder="e.g., Atalanta vs Lazio",
        )
        new_event_kickoff = st.text_input(
            "Kickoff (UTC)",
            value=current.get("kickoff_time_utc") or "",
            placeholder="YYYY-MM-DDTHH:MM:SSZ or leave empty",
        )
        new_event_sport = st.selectbox(
            "Sport",
            ["(Default football)", "football", "tennis", "basketball", "cricket", "rugby"],
            index=0,
        )

        submitted = st.form_submit_button("Save changes", type="primary")
        if submitted:
            edited: Dict[str, Any] = {}

            # Event selection
            if event_choice != "(Keep current)":
                idx = event_labels.index(event_choice)
                selected_event_id = event_values[idx]
                if selected_event_id:
                    edited["canonical_event_id"] = selected_event_id
            else:
                # Create or match relaxed if provided
                if new_event_name and len(new_event_name) >= 5:
                    try:
                        event_id = svc.get_or_create_canonical_event(
                            bet_id=target_bet_id,
                            event_name=new_event_name.strip(),
                            sport=None if new_event_sport == "(Default football)" else new_event_sport,
                            kickoff_time_utc=(new_event_kickoff.strip() or None),
                        )
                        edited["canonical_event_id"] = event_id
                    except Exception as e:
                        st.error(f"Event creation failed: {e}")
                        st.stop()

            # Market
            if market_choice != "(Keep current)":
                edited["market_code"] = selected_market_code

            # Period
            if period_choice != "(Keep current)":
                edited["period_scope"] = period_choice

            # Side
            if side_choice != "(Keep current)":
                edited["side"] = side_choice

            # Line value
            if line_value.strip() == "":
                edited["line_value"] = None
            else:
                edited["line_value"] = line_value.strip()

            try:
                svc.update_verified_bet(target_bet_id, edited)
                st.success(":material/check_circle: Bet updated. If matchable, it will be paired automatically.")
                render_navigation_link(
                    "pages/2_verified_bets.py",
                    label="Open Surebets",
                    icon=":material/target:",
                    help_text="Use the navigation to open 'Surebets' and continue settlement prep.",
                )
                safe_rerun()
            except Exception as e:
                st.error(f"Update failed: {e}")
