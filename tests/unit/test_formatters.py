"""Unit tests for display formatters."""

import pytest
from decimal import Decimal
from datetime import datetime, timedelta
from src.ui.utils.formatters import (
    format_confidence_badge,
    format_currency_amount,
    format_bet_summary,
    format_market_display,
    format_timestamp_relative,
    format_eur,
    format_percentage,
    format_utc_datetime_local,
    get_risk_badge_html,
    format_currency_with_symbol,
)


class TestConfidenceBadge:
    """Tests for confidence badge formatting."""

    def test_confidence_badge_high(self):
        """Test high confidence (≥0.8)."""
        emoji, label, color = format_confidence_badge(0.9)
        assert emoji == "✅"
        assert "High" in label
        assert "90%" in label
        assert color == "success"

    def test_confidence_badge_medium(self):
        """Test medium confidence (0.5-0.79)."""
        emoji, label, color = format_confidence_badge(0.65)
        assert emoji == "⚠️"
        assert "Medium" in label
        assert "65%" in label
        assert color == "warning"

    def test_confidence_badge_low(self):
        """Test low confidence (<0.5)."""
        emoji, label, color = format_confidence_badge(0.3)
        assert emoji == "❌"
        assert "Low" in label
        assert "30%" in label
        assert color == "error"

    def test_confidence_badge_failed(self):
        """Test failed extraction (None)."""
        emoji, label, color = format_confidence_badge(None)
        assert emoji == "❌"
        assert "Failed" in label
        assert color == "error"

    def test_confidence_badge_edge_cases(self):
        """Test edge cases (exactly 0.8, 0.5)."""
        # Exactly 0.8 should be high
        emoji, label, color = format_confidence_badge(0.8)
        assert "High" in label

        # Exactly 0.5 should be medium
        emoji, label, color = format_confidence_badge(0.5)
        assert "Medium" in label


class TestCurrencyFormatting:
    """Tests for currency amount formatting."""

    def test_format_currency_gbp(self):
        """Test GBP formatting."""
        result = format_currency_amount(Decimal("100.50"), "GBP")
        assert result == "£100.50"

    def test_format_currency_eur(self):
        """Test EUR formatting."""
        result = format_currency_amount(Decimal("1000"), "EUR")
        assert result == "€1,000.00"

    def test_format_currency_aud(self):
        """Test AUD formatting."""
        result = format_currency_amount(Decimal("500.75"), "AUD")
        assert result == "$500.75"

    def test_format_currency_large_amount(self):
        """Test large amount with thousands separator."""
        result = format_currency_amount(Decimal("12345.67"), "USD")
        assert result == "$12,345.67"

    def test_format_currency_none(self):
        """Test None amount."""
        result = format_currency_amount(None, "AUD")
        assert result == "N/A"

    def test_format_currency_unknown_code(self):
        """Test unknown currency code."""
        result = format_currency_amount(Decimal("100"), "XYZ")
        assert result == "XYZ100.00"


class TestBetSummary:
    """Tests for bet summary formatting."""

    def test_bet_summary_complete(self):
        """Test complete bet summary."""
        summary = format_bet_summary(Decimal("100"), Decimal("1.90"), Decimal("190"), "AUD")
        assert "$100.00" in summary
        assert "1.90" in summary
        assert "$190.00" in summary

    def test_bet_summary_incomplete(self):
        """Test incomplete bet data."""
        summary = format_bet_summary(None, Decimal("1.90"), Decimal("190"), "AUD")
        assert "Incomplete bet data" in summary

        summary = format_bet_summary(Decimal("100"), None, Decimal("190"), "AUD")
        assert "Incomplete bet data" in summary

        summary = format_bet_summary(Decimal("100"), Decimal("1.90"), None, "AUD")
        assert "Incomplete bet data" in summary


class TestMarketDisplay:
    """Tests for market code display formatting."""

    def test_market_display_known_codes(self):
        """Test known market codes."""
        assert format_market_display("TOTAL_GOALS_OVER_UNDER") == "Total Goals O/U"
        assert format_market_display("ASIAN_HANDICAP") == "Asian Handicap"
        assert format_market_display("MATCH_WINNER") == "Match Winner"

    def test_market_display_none(self):
        """Test None market code."""
        result = format_market_display(None)
        assert "(not extracted)" in result

    def test_market_display_unknown_code(self):
        """Test unknown market code gets title-cased."""
        result = format_market_display("UNKNOWN_MARKET_TYPE")
        assert "Unknown Market Type" in result


class TestTimestampRelative:
    """Tests for relative timestamp formatting."""

    def test_timestamp_seconds_ago(self):
        """Test seconds ago."""
        now = datetime.utcnow()
        past = now - timedelta(seconds=30)
        timestamp = past.isoformat() + "Z"
        result = format_timestamp_relative(timestamp)
        assert "seconds ago" in result

    def test_timestamp_minutes_ago(self):
        """Test minutes ago."""
        now = datetime.utcnow()
        past = now - timedelta(minutes=5)
        timestamp = past.isoformat() + "Z"
        result = format_timestamp_relative(timestamp)
        assert "minutes ago" in result

    def test_timestamp_hours_ago(self):
        """Test hours ago."""
        now = datetime.utcnow()
        past = now - timedelta(hours=2)
        timestamp = past.isoformat() + "Z"
        result = format_timestamp_relative(timestamp)
        assert "hours ago" in result

    def test_timestamp_days_ago(self):
        """Test days ago."""
        now = datetime.utcnow()
        past = now - timedelta(days=3)
        timestamp = past.isoformat() + "Z"
        result = format_timestamp_relative(timestamp)
        assert "days ago" in result

    def test_timestamp_invalid(self):
        """Test invalid timestamp returns original."""
        invalid = "not-a-timestamp"
        result = format_timestamp_relative(invalid)
        assert result == invalid


class TestEURFormatting:
    """Tests for EUR formatting function (Story 3.3)."""

    def test_format_eur_decimal(self):
        """Test EUR formatting with Decimal."""
        result = format_eur(Decimal("100.50"))
        assert result == "€100.50"

    def test_format_eur_large_amount(self):
        """Test EUR formatting with thousands separator."""
        result = format_eur(Decimal("12345.67"))
        assert result == "€12,345.67"

    def test_format_eur_string_input(self):
        """Test EUR formatting with string input (from database)."""
        result = format_eur("250.00")
        assert result == "€250.00"

    def test_format_eur_none(self):
        """Test EUR formatting with None."""
        result = format_eur(None)
        assert result == "€0.00"

    def test_format_eur_invalid(self):
        """Test EUR formatting with invalid input."""
        result = format_eur("not-a-number")
        assert result == "€0.00"

    def test_format_eur_negative(self):
        """Test EUR formatting with negative amount."""
        result = format_eur(Decimal("-50.25"))
        assert result == "€-50.25"


class TestPercentageFormatting:
    """Tests for percentage formatting function (Story 3.3)."""

    def test_format_percentage_decimal(self):
        """Test percentage formatting with Decimal."""
        result = format_percentage(Decimal("2.5"))
        assert result == "2.5%"

    def test_format_percentage_string_input(self):
        """Test percentage formatting with string input (from database)."""
        result = format_percentage("1.25")
        assert result == "1.2%"  # Rounded to 1 decimal place

    def test_format_percentage_none(self):
        """Test percentage formatting with None."""
        result = format_percentage(None)
        assert result == "0.0%"

    def test_format_percentage_invalid(self):
        """Test percentage formatting with invalid input."""
        result = format_percentage("not-a-number")
        assert result == "0.0%"

    def test_format_percentage_negative(self):
        """Test percentage formatting with negative ROI."""
        result = format_percentage(Decimal("-0.5"))
        assert result == "-0.5%"


class TestUTCDateTimeLocal:
    """Tests for UTC datetime local formatting (Story 3.3)."""

    def test_format_utc_datetime_local_valid(self):
        """Test UTC datetime formatting with valid input."""
        result = format_utc_datetime_local("2025-11-01T15:00:00Z")
        assert result == "2025-11-01 15:00"

    def test_format_utc_datetime_local_none(self):
        """Test UTC datetime formatting with None."""
        result = format_utc_datetime_local(None)
        assert result == "—"

    def test_format_utc_datetime_local_empty(self):
        """Test UTC datetime formatting with empty string."""
        result = format_utc_datetime_local("")
        assert result == "—"

    def test_format_utc_datetime_local_invalid(self):
        """Test UTC datetime formatting with invalid input."""
        result = format_utc_datetime_local("not-a-date")
        assert result == "not-a-date"


class TestRiskBadgeHTML:
    """Tests for risk badge HTML generation (Story 3.3)."""

    def test_risk_badge_safe(self):
        """Test risk badge for Safe classification."""
        result = get_risk_badge_html("Safe")
        assert "✅" in result
        assert "Safe" in result
        assert "#28a745" in result  # Green border
        assert "#d4edda" in result  # Green background

    def test_risk_badge_low_roi(self):
        """Test risk badge for Low ROI classification."""
        result = get_risk_badge_html("Low ROI")
        assert "🟡" in result
        assert "Low ROI" in result
        assert "#ffc107" in result  # Yellow border
        assert "#fff3cd" in result  # Yellow background

    def test_risk_badge_unsafe(self):
        """Test risk badge for Unsafe classification."""
        result = get_risk_badge_html("Unsafe")
        assert "❌" in result
        assert "UNSAFE" in result
        assert "#dc3545" in result  # Red border
        assert "#f8d7da" in result  # Red background
        assert "3px" in result  # Thicker border for prominence

    def test_risk_badge_none(self):
        """Test risk badge for None/unknown classification."""
        result = get_risk_badge_html(None)
        assert "⚪" in result
        assert "Unknown" in result

    def test_risk_badge_empty_string(self):
        """Test risk badge for empty string."""
        result = get_risk_badge_html("")
        assert "⚪" in result
        assert "Unknown" in result


class TestCurrencyWithSymbol:
    """Tests for currency symbol formatting."""

    def test_format_currency_with_symbol_eur(self):
        """Test EUR currency formatting."""
        formatted = format_currency_with_symbol(Decimal("1250.50"), "EUR")
        assert formatted == "€1,250.50"

    def test_format_currency_with_symbol_gbp(self):
        """Test GBP currency formatting."""
        formatted = format_currency_with_symbol(Decimal("1250.50"), "GBP")
        assert formatted == "£1,250.50"

    def test_format_currency_with_symbol_usd(self):
        """Test USD currency formatting."""
        formatted = format_currency_with_symbol(Decimal("1250.50"), "USD")
        assert formatted == "$1,250.50"

    def test_format_currency_with_symbol_aud(self):
        """Test AUD currency formatting."""
        formatted = format_currency_with_symbol(Decimal("1250.50"), "AUD")
        assert formatted == "A$1,250.50"

    def test_format_currency_with_symbol_nzd(self):
        """Test NZD currency formatting."""
        formatted = format_currency_with_symbol(Decimal("1250.50"), "NZD")
        assert formatted == "NZ$1,250.50"

    def test_format_currency_with_symbol_unknown_currency(self):
        """Test unknown currency formatting (fallback to code)."""
        formatted = format_currency_with_symbol(Decimal("1250.50"), "XYZ")
        assert formatted == "XYZ 1,250.50"

    def test_format_currency_with_symbol_none_amount(self):
        """Test formatting with None amount."""
        formatted = format_currency_with_symbol(None, "EUR")
        assert formatted == "N/A"

    def test_format_currency_with_symbol_integer(self):
        """Test formatting integer amount."""
        formatted = format_currency_with_symbol(Decimal("1000"), "EUR")
        assert formatted == "€1,000.00"

    def test_format_currency_with_symbol_lowercase_currency(self):
        """Test formatting with lowercase currency code."""
        formatted = format_currency_with_symbol(Decimal("100.50"), "eur")
        assert formatted == "€100.50"
