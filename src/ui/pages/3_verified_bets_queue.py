"""
Verified Bets Queue - lists approved bets awaiting matching (and optionally matched bets).

This page helps operators verify that approved bets have all the fields
required for surebet matching (canonical event, market, period, side).
"""

import streamlit as st
from typing import Optional, List, Dict, Any
from src.core.database import get_db_connection
from src.services.bet_verification import BetVerificationService
from src.ui.ui_components import load_global_styles
from src.ui.utils.navigation_links import render_navigation_link


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


# Filters
col1, col2 = st.columns(2)
with col1:
    include_matched = st.checkbox("Include matched bets", value=False)
with col2:
    # Associate filter
    db = get_db_connection()
    associates = db.execute("SELECT DISTINCT display_alias FROM associates ORDER BY display_alias").fetchall()
    associate_options = ["All"] + [row["display_alias"] for row in associates]
    filter_associate = st.selectbox("Filter by associate", associate_options)

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
            if current.get("screenshot_path"):
                try:
                    st.image(current["screenshot_path"], width=300, caption=f"Bet #{current['bet_id']}")
                    with st.expander("View full-size screenshot"):
                        st.image(current["screenshot_path"])  # default width (content)
                        st.caption(current["screenshot_path"]) 
                except Exception:
                    st.caption(f"Screenshot: {current['screenshot_path']}")
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
                    st.rerun()
                except Exception as e:
                    st.error(f"Update failed: {e}")
