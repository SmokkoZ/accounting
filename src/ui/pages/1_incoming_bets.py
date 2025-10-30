"""
Incoming Bets page - displays bets awaiting review.

This page provides:
- Manual upload panel for uploading bet screenshots
- List of all incoming bets with metadata
- Screenshot previews
- Confidence scores with color coding
- Ingestion source indicators (Telegram vs Manual)
- Approval/rejection actions (Epic 2)
"""

import streamlit as st
import structlog

from src.core.database import get_db_connection
from src.ui.components.manual_upload import render_manual_upload_panel

logger = structlog.get_logger()

# Configure page
st.set_page_config(page_title="Incoming Bets", layout="wide")

st.title("📥 Incoming Bets")

# Manual upload panel at top (collapsible)
with st.expander("📤 Upload Manual Bet", expanded=False):
    render_manual_upload_panel()

st.markdown("---")

# Database connection
db = get_db_connection()

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

# Incoming bets queue
st.subheader("📋 Bets Awaiting Review")

try:
    # Query incoming bets
    incoming_bets = db.execute(
        """
        SELECT
            b.id as bet_id,
            b.screenshot_path,
            a.display_alias as associate,
            bk.bookmaker_name as bookmaker,
            b.ingestion_source,
            b.market_code,
            b.period_scope,
            b.side,
            b.stake_original,
            b.stake_eur,
            b.odds_original,
            b.odds,
            b.payout,
            b.currency,
            b.normalization_confidence,
            b.is_multi,
            b.created_at_utc
        FROM bets b
        JOIN associates a ON b.associate_id = a.id
        JOIN bookmakers bk ON b.bookmaker_id = bk.id
        WHERE b.status = 'incoming'
        ORDER BY b.created_at_utc DESC
        """
    ).fetchall()

    if not incoming_bets:
        st.info("✅ No bets awaiting review")
    else:
        st.caption(f"Showing {len(incoming_bets)} bet(s)")

        # Display each bet
        for bet in incoming_bets:
            with st.container():
                col1, col2, col3 = st.columns([1, 3, 1])

                with col1:
                    # Screenshot preview
                    try:
                        st.image(bet["screenshot_path"], width=150, caption="Screenshot")
                    except Exception:
                        st.warning("⚠️ Screenshot not found")
                        logger.warning(
                            "screenshot_not_found",
                            bet_id=bet["bet_id"],
                            path=bet["screenshot_path"],
                        )

                with col2:
                    # Bet details header
                    st.markdown(
                        f"**Bet #{bet['bet_id']}** - {bet['associate']} @ {bet['bookmaker']}"
                    )

                    # Ingestion source icon
                    source_icon = "📱" if bet["ingestion_source"] == "telegram" else "📤"
                    source_label = (
                        "Telegram" if bet["ingestion_source"] == "telegram" else "Manual Upload"
                    )
                    st.caption(f"{source_icon} {source_label} • Created: {bet['created_at_utc']}")

                    # Extracted data
                    if bet["market_code"]:
                        # Build bet description
                        market_display = bet["market_code"].replace("_", " ").title()
                        period_display = (
                            bet["period_scope"].replace("_", " ").title()
                            if bet["period_scope"]
                            else "N/A"
                        )
                        side_display = (
                            bet["side"].replace("_", " ").title() if bet["side"] else "N/A"
                        )

                        st.write(f"**Market:** {market_display} - {period_display}")
                        st.write(f"**Selection:** {side_display}")

                        # Display stake/odds/payout
                        stake_display = f"{bet['stake_original'] or bet['stake_eur']}"
                        odds_display = f"{bet['odds_original'] or bet['odds']}"
                        payout_display = f"{bet['payout'] or 'N/A'}"
                        currency_display = bet["currency"] or "EUR"

                        st.write(
                            f"**Bet:** {stake_display} {currency_display} @ {odds_display} = {payout_display} {currency_display}"
                        )

                    else:
                        st.warning("⚠️ Extraction failed - manual entry required")

                    # Flags
                    if bet["is_multi"]:
                        st.error("🚫 **Accumulator - Not Supported**")

                    # Check for operator notes
                    notes = db.execute(
                        """
                        SELECT notes
                        FROM verification_audit
                        WHERE bet_id = ?
                        AND action = 'CREATED'
                        ORDER BY created_at_utc DESC
                        LIMIT 1
                        """,
                        (bet["bet_id"],),
                    ).fetchone()

                    if notes and notes["notes"]:
                        st.info(f"📝 Note: {notes['notes']}")

                with col3:
                    # Confidence badge
                    if bet["normalization_confidence"]:
                        try:
                            confidence_float = float(bet["normalization_confidence"])
                            if confidence_float >= 0.8:
                                st.success(f"✅ High\n{confidence_float:.0%}")
                            elif confidence_float >= 0.5:
                                st.warning(f"⚠️ Medium\n{confidence_float:.0%}")
                            else:
                                st.error(f"❌ Low\n{confidence_float:.0%}")
                        except (ValueError, TypeError):
                            st.error("❌ Invalid")
                    else:
                        st.error("❌ Failed")

                    # Actions (Epic 2 - disabled for now)
                    st.button(
                        "✅ Approve",
                        key=f"approve_{bet['bet_id']}",
                        disabled=True,
                        help="Approval feature coming in Epic 2",
                    )
                    st.button(
                        "❌ Reject",
                        key=f"reject_{bet['bet_id']}",
                        disabled=True,
                        help="Rejection feature coming in Epic 2",
                    )

                st.markdown("---")

except Exception as e:
    logger.error("failed_to_load_incoming_bets", error=str(e), exc_info=True)
    st.error(f"Failed to load incoming bets: {str(e)}")
    st.exception(e)
