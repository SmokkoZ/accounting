"""Display formatting utilities for Streamlit UI.

All currency amounts are rendered with ISO currency codes (e.g., "AUD 100.00").
EUR-specific helpers also use the code format ("EUR 100.00").
"""

from datetime import datetime, timezone
from typing import Optional, Tuple, Union
import pytz
from decimal import Decimal, InvalidOperation

CURRENCY_SYMBOLS = {
    "EUR": "€",
    "GBP": "£",
    "USD": "$",
    "AUD": "$",
    "CAD": "C$",
    "NZD": "NZ$",
    "JPY": "¥",
    "CHF": "CHF ",
}

CURRENCY_SYMBOLS_WITH_PREFIX = {
    **CURRENCY_SYMBOLS,
    "AUD": "A$",
}
PERTH_TZ = pytz.timezone("Australia/Perth")


def _to_decimal(value: Optional[Decimal | float | str]) -> Optional[Decimal]:
    """Safely coerce a value to Decimal, returning None on failure."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def format_timestamp_relative(timestamp_utc: str) -> str:
    """Format timestamp as relative time (e.g., '5 minutes ago').

    Args:
        timestamp_utc: ISO8601 timestamp with Z suffix

    Returns:
        Human-readable relative time string
    """
    try:
        dt = datetime.fromisoformat(timestamp_utc.replace("Z", "+00:00"))
        now = datetime.utcnow().replace(tzinfo=dt.tzinfo)
        delta = now - dt

        seconds = delta.total_seconds()
        if seconds < 60:
            return f"{int(seconds)} seconds ago"
        elif seconds < 3600:
            return f"{int(seconds / 60)} minutes ago"
        elif seconds < 86400:
            return f"{int(seconds / 3600)} hours ago"
        else:
            return f"{int(seconds / 86400)} days ago"
    except Exception:
        return timestamp_utc


ConfidenceBadge = Tuple[str, str, str, str]

CONFIDENCE_RATIONALES = {
    "failed": "Normalization failed or has no confidence value. Please review manually.",
    "high": "Normalization signals strongly agree ({percent}). Safe to proceed.",
    "medium": "Confidence is moderate at {percent}. Double-check key fields before approving.",
    "low": "Confidence is low at {percent}. Inspect the row before taking action.",
}


def format_confidence_badge(confidence: Optional[float]) -> ConfidenceBadge:
    """Return (emoji, label, color, tooltip) for confidence level.

    Args:
        confidence: Confidence score between 0.0 and 1.0, or None if extraction failed

    Returns:
        Tuple of (emoji, label, st.color_name, tooltip_text)
    """
    tooltip_key = "failed"
    tooltip_percent = "N/A"

    if confidence is None:
        rationale = CONFIDENCE_RATIONALES[tooltip_key].format(percent=tooltip_percent)
        return ("❌", "Failed", "error", rationale)

    # Convert to float if it's a string (from database)
    try:
        confidence_float = float(confidence)
    except (TypeError, ValueError):
        rationale = CONFIDENCE_RATIONALES[tooltip_key].format(percent=tooltip_percent)
        return ("❌", "Failed", "error", rationale)

    tooltip_percent = f"{confidence_float:.0%}"

    if confidence_float >= 0.8:
        tooltip_key = "high"
        rationale = CONFIDENCE_RATIONALES[tooltip_key].format(percent=tooltip_percent)
        return ("✅", f"High ({confidence_float:.0%})", "success", rationale)
    elif confidence_float >= 0.5:
        tooltip_key = "medium"
        rationale = CONFIDENCE_RATIONALES[tooltip_key].format(percent=tooltip_percent)
        return ("⚠️", f"Medium ({confidence_float:.0%})", "warning", rationale)
    else:
        tooltip_key = "low"
        rationale = CONFIDENCE_RATIONALES[tooltip_key].format(percent=tooltip_percent)
        return ("❌", f"Low ({confidence_float:.0%})", "error", rationale)


def format_currency_amount(amount: Optional[Decimal], currency: str) -> str:
    """Format a monetary amount using the appropriate currency symbol."""
    if amount is None:
        return "N/A"

    value = _to_decimal(amount)
    if value is None:
        return "N/A"

    code = (currency or "CUR").upper()
    symbol = CURRENCY_SYMBOLS.get(code)
    formatted = f"{value:,.2f}"

    if symbol:
        return f"{symbol}{formatted}"

    return f"{code}{formatted}"


def format_bet_summary(
    stake: Optional[Decimal],
    odds: Optional[Decimal],
    payout: Optional[Decimal],
    currency: str,
) -> str:
    """Format bet as 'CODE stake @ odds = CODE payout'.

    Args:
        stake: Stake amount
        odds: Odds value
        payout: Payout amount
        currency: Currency code

    Returns:
        Formatted string like "AUD 100.00 @ 1.90 = AUD 190.00"
    """
    if stake is None or odds is None or payout is None:
        return "Incomplete bet data"

    try:
        s = Decimal(str(stake)) if not isinstance(stake, Decimal) else stake
        p = Decimal(str(payout)) if not isinstance(payout, Decimal) else payout
    except Exception:
        return "Incomplete bet data"

    stake_str = format_currency_amount(s, currency)
    payout_str = format_currency_amount(p, currency)

    if stake_str == "N/A" or payout_str == "N/A":
        return "Incomplete bet data"

    return f"{stake_str} @ {odds} = {payout_str}"


def format_market_display(market_code: Optional[str]) -> str:
    """Convert internal market code to human-readable.

    Args:
        market_code: Internal market code from database

    Returns:
        Human-readable market name
    """
    if not market_code:
        return "(not extracted)"

    # Map internal codes to display names
    market_display = {
        # Soccer O/U
        "TOTAL_GOALS_OVER_UNDER": "Total Goals O/U",
        "FIRST_HALF_TOTAL_GOALS": "1H Total Goals O/U",
        "SECOND_HALF_TOTAL_GOALS": "2H Total Goals O/U",
        "TOTAL_CARDS_OVER_UNDER": "Total Cards O/U",
        "TOTAL_CORNERS_OVER_UNDER": "Total Corners O/U",
        "TOTAL_SHOTS_OVER_UNDER": "Total Shots O/U",
        "TOTAL_SHOTS_ON_TARGET_OVER_UNDER": "Total Shots on Target O/U",
        # Soccer yes/no & team two-way
        "BOTH_TEAMS_TO_SCORE": "BTTS (Yes/No)",
        "RED_CARD_AWARDED": "Red Card Awarded (Y/N)",
        "PENALTY_AWARDED": "Penalty Awarded (Y/N)",
        "DRAW_NO_BET": "Draw No Bet",
        "ASIAN_HANDICAP": "Asian Handicap",
        # Tennis
        "MATCH_WINNER": "Match Winner",
        "TOTAL_GAMES_OVER_UNDER": "Total Games O/U",
    }

    return market_display.get(market_code, market_code.replace("_", " ").title())


def format_eur(amount: Optional[Decimal]) -> str:
    """Format an amount with the Euro symbol."""
    value = _to_decimal(amount)
    if value is None:
        return "€0.00"
    return format_currency_amount(value, "EUR")


def format_percentage(value: Optional[Decimal]) -> str:
    """Format decimal value as percentage.

    Args:
        value: Decimal value to format (e.g., 0.025 for 2.5%)

    Returns:
        Formatted string like "2.5%"
    """
    if value is None:
        return "0.0%"

    try:
        if isinstance(value, str):
            value = Decimal(value)
        return f"{value:.1f}%"
    except (ValueError, TypeError, Exception):
        return "0.0%"


def format_utc_datetime_local(iso_string: Optional[str]) -> str:
    """Format UTC timestamp as local readable format.

    Args:
        iso_string: ISO8601 timestamp with Z suffix

    Returns:
        Formatted string like "2025-11-01 15:00"
    """
    if not iso_string:
        return "—"

    return format_utc_datetime(iso_string)


def _ensure_perth_datetime(value: Union[str, datetime]) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(PERTH_TZ)


def format_utc_datetime(value: Union[str, datetime]) -> str:
    """Convert UTC timestamp to Perth local display with AWST suffix."""
    try:
        perth_dt = _ensure_perth_datetime(value)
    except Exception:
        return str(value)
    return f"{perth_dt.strftime('%Y-%m-%d %H:%M:%S')} AWST"


def format_utc_datetime_compact(value: Union[str, datetime]) -> str:
    """Compact Perth local format (MM/DD HH:MM AWST)."""
    try:
        perth_dt = _ensure_perth_datetime(value)
    except Exception:
        return str(value)
    return f"{perth_dt.strftime('%m/%d %H:%M')} AWST"


def get_risk_badge_html(risk_classification: Optional[str]) -> str:
    """Generate HTML for risk classification badge.

    Args:
        risk_classification: One of "Safe", "Low ROI", "Unsafe"

    Returns:
        HTML string with styled badge
    """
    if not risk_classification:
        return '<div style="background-color: #e0e0e0; color: #666; padding: 8px; border: 1px solid #ccc; border-radius: 5px; text-align: center;">⚪ Unknown</div>'

    if risk_classification == "Safe":
        return """<div style="background-color: #d4edda; color: #155724; padding: 8px;
                  border: 2px solid #28a745; border-radius: 5px; text-align: center; font-weight: bold;">
                  ✅ Safe</div>"""
    elif risk_classification == "Low ROI":
        return """<div style="background-color: #fff3cd; color: #856404; padding: 8px;
                  border: 2px solid #ffc107; border-radius: 5px; text-align: center; font-weight: bold;">
                  🟡 Low ROI</div>"""
    else:  # Unsafe
        return """<div style="background-color: #f8d7da; color: #721c24; padding: 8px;
                  border: 3px solid #dc3545; border-radius: 5px; text-align: center; font-weight: bold; font-size: 1.1em;">
                  ❌ UNSAFE</div>"""


def format_currency_with_symbol(amount: Optional[Decimal], currency: str) -> str:
    """Format currency amount with currency symbol (e.g., "€1,250.50").

    Args:
        amount: Decimal amount to format
        currency: ISO currency code (EUR, GBP, USD, AUD, etc.)

    Returns:
        Formatted string with currency symbol and thousand separators
    """
    value = _to_decimal(amount)
    if value is None:
        return "N/A"

    code = (currency or "CUR").upper()
    symbol = CURRENCY_SYMBOLS_WITH_PREFIX.get(code, f"{code} ")

    return f"{symbol}{value:,.2f}"
