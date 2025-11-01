"""Bet card component for displaying incoming bets."""

import streamlit as st
from typing import Dict, Any, Optional
from pathlib import Path
from decimal import Decimal
from datetime import datetime
from src.ui.utils.formatters import (
    format_timestamp_relative,
    format_confidence_badge,
    format_bet_summary,
    format_market_display,
)


def render_bet_card(
    bet: Dict[str, Any],
    show_actions: bool = True,
    editable: bool = True,
    verification_service=None,
) -> None:
    """Render a single bet card with screenshot preview and details.

    Args:
        bet: Dictionary containing bet data (from database query)
        show_actions: Whether to show approve/reject buttons
        editable: Whether to show inline edit fields
        verification_service: BetVerificationService instance for data loading
    """
    bet_id = bet.get("bet_id", bet.get("id"))

    # Check if "Create New Event" modal should be shown
    if st.session_state.get(f"show_create_event_modal_{bet_id}"):
        show_create_event_modal(bet, verification_service)
        # Clear the flag after showing modal
        del st.session_state[f"show_create_event_modal_{bet_id}"]
        return

    with st.container():
        # Create 3-column layout: screenshot | details | actions
        col1, col2, col3 = st.columns([1, 3, 1])

        with col1:
            # Screenshot preview
            _render_screenshot_preview(bet)

        with col2:
            # Bet details (editable or read-only)
            if editable and verification_service:
                _render_bet_details_editable(bet, verification_service)
            else:
                _render_bet_details(bet)

        with col3:
            # Confidence badge and actions
            _render_bet_actions(bet, show_actions, editable)

        st.markdown("---")


def _render_screenshot_preview(bet: Dict[str, Any]) -> None:
    """Render screenshot preview with click-to-enlarge."""
    screenshot_path = bet.get("screenshot_path")

    if screenshot_path and Path(screenshot_path).exists():
        # Thumbnail
        st.image(screenshot_path, width=150, caption="Click to enlarge")

        # Full-size modal (using expander)
        with st.expander("🔍 View Full Size"):
            st.image(screenshot_path, use_container_width=True)
    else:
        st.warning("Screenshot\nnot found")


def _render_bet_details(bet: Dict[str, Any]) -> None:
    """Render bet details section."""
    # Header: Bet ID, Associate, Bookmaker
    st.markdown(f"**Bet #{bet['bet_id']}** - {bet['associate']} @ {bet['bookmaker']}")

    # Source icon and timestamp
    source_icon = "📱" if bet["ingestion_source"] == "telegram" else "📤"
    timestamp_rel = format_timestamp_relative(bet["created_at_utc"])
    st.caption(f"{source_icon} {bet['ingestion_source']} • {timestamp_rel}")

    # Extracted data
    if bet.get("canonical_event"):
        st.write(f"**Event:** {bet['canonical_event']}")
        st.write(f"**Market:** {format_market_display(bet.get('market_code'))}")

        # Market details
        details = []
        if bet.get("period_scope"):
            details.append(bet["period_scope"].replace("_", " ").title())
        if bet.get("line_value"):
            details.append(f"Line: {bet['line_value']}")
        if bet.get("side"):
            details.append(f"Side: {bet['side']}")
        if details:
            st.caption(" • ".join(details))

        # Financial summary
        bet_summary = format_bet_summary(
            bet.get("stake"),
            bet.get("odds"),
            bet.get("payout"),
            bet.get("currency", "AUD"),
        )
        st.write(f"**Bet:** {bet_summary}")

        # Kickoff time
        if bet.get("kickoff_time_utc"):
            st.caption(f"⏰ Kickoff: {bet['kickoff_time_utc']}")
    else:
        st.warning("⚠️ **Extraction failed** - manual entry required")

    # Special flags
    if bet.get("is_multi"):
        st.error("🚫 **Accumulator - Not Supported**")

    if bet.get("operator_note"):
        st.info(f"📝 Note: {bet['operator_note']}")


def _render_bet_details_editable(bet: Dict[str, Any], verification_service) -> None:
    """Render bet details with inline editing fields."""
    bet_id = bet["bet_id"]

    # Header: Bet ID, Associate, Bookmaker (non-editable)
    st.markdown(f"**Bet #{bet_id}** - {bet['associate']} @ {bet['bookmaker']}")

    # Source icon and timestamp
    source_icon = "📱" if bet["ingestion_source"] == "telegram" else "📤"
    timestamp_rel = format_timestamp_relative(bet["created_at_utc"])
    st.caption(f"{source_icon} {bet['ingestion_source']} • {timestamp_rel}")

    # Create form for editable fields
    with st.form(key=f"edit_bet_{bet_id}"):
        # Load dropdown data
        canonical_events = verification_service.load_canonical_events()
        canonical_markets = verification_service.load_canonical_markets()

        # Canonical Event dropdown
        event_options = ["(None - Select Event)"] + [
            f"{e['normalized_event_name']} ({e['kickoff_time_utc'][:10] if e['kickoff_time_utc'] else 'TBD'})"
            for e in canonical_events
        ]
        event_options.append("[+] Create New Event")

        current_event_idx = 0
        if bet.get("canonical_event_id"):
            # Find index of current event
            for i, event in enumerate(canonical_events):
                if event["id"] == bet["canonical_event_id"]:
                    current_event_idx = i + 1  # +1 for "(None)" option
                    break

        selected_event = st.selectbox("Event", event_options, index=current_event_idx)

        # Check if "Create New Event" was selected
        if selected_event == "[+] Create New Event":
            # Store flag in session state to show modal after form submission
            if st.form_submit_button("Open Event Creator", use_container_width=True):
                st.session_state[f"show_create_event_modal_{bet_id}"] = True
                st.rerun()
            return  # Exit early to prevent further rendering

        # Event name input (used for automatic canonical event creation)
        manual_event_name_default = bet.get("selection_text") or ""
        manual_event_name = st.text_input(
            "Event Name (auto-create)",
            value=manual_event_name_default,
            placeholder="e.g., Manchester United vs Liverpool",
            help="Used if you approve without selecting an existing event.",
            key=f"event_name_input_{bet_id}",
        )

        # Market Code dropdown
        market_options = ["(None - Select Market)"] + [
            f"{m['description']} ({m['market_code']})" for m in canonical_markets
        ]

        current_market_idx = 0
        if bet.get("market_code"):
            for i, market in enumerate(canonical_markets):
                if market["market_code"] == bet["market_code"]:
                    current_market_idx = i + 1
                    break

        selected_market = st.selectbox(
            "Market", market_options, index=current_market_idx
        )

        # Period Scope dropdown
        period_options = [
            "FULL_MATCH",
            "FIRST_HALF",
            "SECOND_HALF",
            "FIRST_QUARTER",
            "SECOND_QUARTER",
        ]
        current_period = bet.get("period_scope", "FULL_MATCH")
        selected_period = st.selectbox(
            "Period",
            period_options,
            index=(
                period_options.index(current_period)
                if current_period in period_options
                else 0
            ),
        )

        # Line Value input
        current_line = float(bet["line_value"]) if bet.get("line_value") else 0.0
        line_value = st.number_input(
            "Line Value (optional)", value=current_line, step=0.5, format="%.1f"
        )

        # Side dropdown (filtered by market)
        market_code = None
        if selected_market != "(None - Select Market)":
            # Extract market code from selection
            market_code = selected_market.split("(")[-1].rstrip(")")

        valid_sides = verification_service.get_valid_sides_for_market(market_code)
        current_side = bet.get("side", valid_sides[0] if valid_sides else "OVER")
        side_idx = valid_sides.index(current_side) if current_side in valid_sides else 0
        side = st.selectbox("Side", valid_sides, index=side_idx)

        # Financial inputs
        col_stake, col_odds, col_payout = st.columns(3)

        with col_stake:
            stake_value = bet.get("stake")
            current_stake = float(stake_value) if stake_value else 1.0
            stake = st.number_input(
                "Stake", value=current_stake, min_value=0.01, step=1.0
            )

        with col_odds:
            odds_value = bet.get("odds")
            current_odds = float(odds_value) if odds_value else 1.5
            odds = st.number_input(
                "Odds", value=current_odds, min_value=1.0, step=0.01, format="%.2f"
            )

        with col_payout:
            payout = stake * odds
            st.number_input("Payout (auto)", value=payout, disabled=True, format="%.2f")

        # Currency dropdown
        currency_options = ["AUD", "GBP", "EUR", "USD", "NZD", "CAD"]
        current_currency = bet.get("currency", "AUD")
        currency_idx = (
            currency_options.index(current_currency)
            if current_currency in currency_options
            else 0
        )
        currency = st.selectbox("Currency", currency_options, index=currency_idx)

        # Special flags
        if bet.get("is_multi"):
            st.error("🚫 **Accumulator - Not Supported**")

        if bet.get("operator_note"):
            st.info(f"📝 Note: {bet['operator_note']}")

        # Action buttons (submit buttons within form)
        col_approve, col_reject = st.columns(2)

        with col_approve:
            approve_submitted = st.form_submit_button(
                "✅ Approve", type="primary", use_container_width=True
            )

        with col_reject:
            reject_submitted = st.form_submit_button(
                "❌ Reject", use_container_width=True
            )

        # Handle form submission
        if approve_submitted:
            # Store approval action in session state
            st.session_state[f"approve_bet_{bet_id}"] = {
                "event_selection": selected_event,
                "market_selection": selected_market,
                "period": selected_period,
                "line": line_value,
                "side": side,
                "stake": stake,
                "odds": odds,
                "payout": payout,
                "currency": currency,
                "event_name_input": manual_event_name,
                "canonical_events": canonical_events,
                "canonical_markets": canonical_markets,
            }
            st.rerun()

        if reject_submitted:
            st.session_state[f"reject_bet_{bet_id}"] = True
            st.rerun()


def _render_bet_actions(
    bet: Dict[str, Any], show_actions: bool, editable: bool = False
) -> None:
    """Render confidence badge and action buttons (for non-editable mode)."""
    # Confidence badge
    emoji, label, color = format_confidence_badge(bet.get("normalization_confidence"))
    st.markdown(f"{emoji} **{label}**")

    # Only show separate action buttons if not in editable mode
    if show_actions and not editable:
        st.markdown("---")

        # Approve button (green)
        if st.button("✅ Approve", key=f"approve_{bet['bet_id']}", type="primary", use_container_width=True):
            st.session_state[f"approve_bet_{bet['bet_id']}"] = True
            st.rerun()

        # Reject button (red)
        if st.button("❌ Reject", key=f"reject_{bet['bet_id']}"):
            st.session_state[f"reject_bet_{bet['bet_id']}"] = True
            st.rerun()


@st.dialog("Create New Event")
def show_create_event_modal(bet: Dict[str, Any], verification_service) -> Optional[int]:
    """Modal dialog for creating a new canonical event.

    Args:
        bet: Bet dictionary with extracted data for pre-filling
        verification_service: BetVerificationService instance for event creation

    Returns:
        Event ID if created successfully, None otherwise
    """
    st.markdown("Create a new canonical event for this bet.")

    # Pre-fill values from bet data
    default_event_name = bet.get("selection_text", "")
    default_kickoff = bet.get("kickoff_time_utc", "")

    # Form for event creation
    event_name = st.text_input(
        "Event Name *",
        value=default_event_name,
        placeholder="e.g., Manchester United vs Liverpool",
        help="Minimum 5 characters required",
    )

    sport_options = ["football", "tennis", "basketball", "cricket", "rugby"]
    sport = st.selectbox(
        "Sport *",
        options=sport_options,
        index=0,
        help="Select the sport type",
    )

    competition = st.text_input(
        "Competition / League (Optional)",
        value="",
        placeholder="e.g., Premier League, ATP Masters",
        help="Maximum 100 characters",
    )

    kickoff_time = st.text_input(
        "Kickoff Time (UTC) *",
        value=default_kickoff,
        placeholder="YYYY-MM-DDTHH:MM:SSZ",
        help="ISO8601 format with Z suffix required",
    )

    st.caption("* Required fields")

    # Action buttons
    col1, col2 = st.columns(2)

    with col1:
        if st.button("Create Event", type="primary", use_container_width=True):
            # Validate inputs
            errors = []

            if not event_name or len(event_name) < 5:
                errors.append("Event name must be at least 5 characters")

            if competition and len(competition) > 100:
                errors.append("Competition name must not exceed 100 characters")

            if not kickoff_time or not kickoff_time.endswith("Z"):
                errors.append("Kickoff time must end with 'Z' (UTC timezone)")
            else:
                # Validate ISO8601 format
                try:
                    datetime.fromisoformat(kickoff_time.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    errors.append(
                        "Invalid kickoff time format. Use YYYY-MM-DDTHH:MM:SSZ"
                    )

            # Show errors if any
            if errors:
                for error in errors:
                    st.error(error)
                return None

            # Attempt to create event
            try:
                event_id = verification_service._create_canonical_event(
                    event_name=event_name,
                    sport=sport,
                    competition=competition if competition else None,
                    kickoff_time_utc=kickoff_time,
                )

                st.success(f"✅ Event created: {event_name}")
                st.session_state["newly_created_event_id"] = event_id
                st.rerun()

            except ValueError as e:
                st.error(f"Validation error: {str(e)}")
            except Exception as e:
                st.error(f"Failed to create event: {str(e)}")

    with col2:
        if st.button("Cancel", use_container_width=False):
            st.rerun()
