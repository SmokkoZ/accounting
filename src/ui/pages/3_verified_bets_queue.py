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


PAGE_TITLE = "Ingested betslips"
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
                bk.bookmaker_name AS bookmaker,
                COALESCE(ce.normalized_event_name, b.selection_text) AS event_name,
                b.odds_original,
                b.stake_original,
                b.market_code,
                b.side,
                b.period_scope,
                b.line_value,
                b.kickoff_time_utc,
                b.normalization_confidence,
                b.confidence_score,
                COALESCE(b.resolve_status, 'needs_review') AS resolve_status,
                b.status
            FROM bets b
            JOIN associates a ON b.associate_id = a.id
            JOIN bookmakers bk ON b.bookmaker_id = bk.id
            LEFT JOIN canonical_events ce ON b.canonical_event_id = ce.id
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
                "bookmaker": row["bookmaker"],
                "event_name": row["event_name"],
                "odds": row["odds_original"],
                "stake": row["stake_original"],
                "market_code": row["market_code"],
                "side": row["side"],
                "period_scope": row["period_scope"],
                "line_value": row["line_value"],
                "kickoff_time_utc": row["kickoff_time_utc"],
                "confidence_score": confidence_value,
                "resolve_status": row["resolve_status"],
                "bet_status": row["status"],
            }
        )

    df = pd.DataFrame.from_records(records)
    if statuses and not df.empty:
        df = df[df["resolve_status"].isin(statuses)]
    return df

def _to_float(value: Any) -> Optional[float]:
    if value in ("", None):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

EDITABLE_COLUMN_MAP = {
    "event": ("selection_text", lambda v: (str(v).strip() or None) if v is not None else None),
    "odds": ("odds_original", _to_float),
    "stake": ("stake_original", _to_float),
    "market": ("market_code", lambda v: (str(v).strip() or None) if v is not None else None),
    "side": ("side", lambda v: (str(v).strip() or None) if v is not None else None),
    "line": ("line_value", _to_float),
    "period": ("period_scope", lambda v: (str(v).strip() or None) if v is not None else None),
    "kickoff": ("kickoff_time_utc", lambda v: (str(v).strip() or None) if v is not None else None),
}

def persist_inline_edits(changes: List[tuple[int, Dict[str, Any]]]) -> int:
    if not changes:
        return 0
    db = get_db_connection()
    service = BetVerificationService(db)
    updated = 0
    errors: List[str] = []
    try:
        for bet_id, column_updates in changes:
            if not column_updates:
                continue
            try:
                service.update_verified_bet(bet_id, column_updates, verified_by="inline_editor")
            except Exception as exc:  # pragma: no cover - user-visible errors
                errors.append(f"Bet #{bet_id}: {exc}")
            else:
                updated += 1
        db.commit()
    finally:
        db.close()

    for message in errors:
        st.error(message)
    return updated

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
    display_rows: List[Dict[str, Any]] = []
    for row in bets:
        display_rows.append(
            {
                "bet_id": row["bet_id"],
                "associate": row["associate"],
                "bookmaker": row["bookmaker"],
                "event": row.get("selection_text") or row.get("event_name") or "",
                "canonical_event": row.get("event_name") or "",
                "odds": row.get("odds"),
                "stake": row.get("stake"),
                "market": row.get("market_code") or "",
                "side": row.get("side") or "",
                "line": row.get("line_value"),
                "period": row.get("period_scope") or "",
                "kickoff": row.get("kickoff_time_utc") or "",
                "conf": row.get("normalization_confidence"),
                "bet_status": row.get("status"),
            }
        )

    base_df = pd.DataFrame(display_rows)
    editable_columns = ["event", "odds", "stake", "market", "side", "line", "period", "kickoff"]
    disabled_columns = ["bet_id", "associate", "bookmaker", "canonical_event", "conf", "bet_status"]
    column_config = {
        "bet_id": st.column_config.NumberColumn("Bet ID", disabled=True),
        "associate": st.column_config.TextColumn("Associate", disabled=True),
        "bookmaker": st.column_config.TextColumn("Bookmaker", disabled=True),
        "event": st.column_config.TextColumn("Event (editable alias)"),
        "canonical_event": st.column_config.TextColumn("Canonical Event", disabled=True),
        "odds": st.column_config.NumberColumn("Odds", format="%.2f"),
        "stake": st.column_config.NumberColumn("Stake", format="%.2f"),
        "market": st.column_config.TextColumn("Market"),
        "side": st.column_config.TextColumn("Side"),
        "line": st.column_config.NumberColumn("Line", format="%.2f"),
        "period": st.column_config.TextColumn("Period"),
        "kickoff": st.column_config.TextColumn("Kickoff (UTC)", help="YYYY-MM-DDTHH:MM:SSZ"),
        "conf": st.column_config.TextColumn("Conf", disabled=True),
        "bet_status": st.column_config.TextColumn("Status", disabled=True),
    }

    edited_df = st.data_editor(
        base_df,
        column_config=column_config,
        disabled=disabled_columns,
        hide_index=True,
        use_container_width=True,
        key="verified_bets_editor",
    )

    if st.button("Save inline edits", type="primary", key="save_inline_edits_button"):
        base_records = base_df.to_dict("records")
        edited_records = edited_df.to_dict("records")
        changes: List[tuple[int, Dict[str, Any]]] = []

        def _values_equal(val1: Any, val2: Any) -> bool:
            if pd.isna(val1) and pd.isna(val2):
                return True
            return val1 == val2

        for original, edited in zip(base_records, edited_records):
            row_changes: Dict[str, Any] = {}
            for field in editable_columns:
                original_value = original.get(field)
                edited_value = edited.get(field)
                if not _values_equal(original_value, edited_value):
                    column_name, normalizer = EDITABLE_COLUMN_MAP[field]
                    row_changes[column_name] = normalizer(edited_value)
            if row_changes:
                changes.append((original["bet_id"], row_changes))

        if not changes:
            st.info("No inline changes detected.")
        else:
            updates = persist_inline_edits(changes)
            if updates:
                st.success(f"{updates} bet(s) updated.")
                safe_rerun()
            else:
                st.warning("No bets were updated. Please verify your changes and try again.")

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
                    "pages/2_surebets_summary.py",
                    label="Open Surebets Summary",
                    icon=":material/target:",
                    help_text="Use the navigation to open 'Surebets' and continue settlement prep.",
                )
                safe_rerun()
            except Exception as e:
                st.error(f"Update failed: {e}")
