"""
Unit tests for OpenAI client bet extraction.

Tests cover:
- Successful extraction with high confidence
- Low confidence extraction handling
- Accumulator detection
- API failure scenarios
- Retry logic
"""

import tempfile
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest

from src.integrations.openai_client import OpenAIClient


class TestOpenAIClient:
    """Test cases for OpenAI client."""

    @pytest.fixture
    def openai_client(self):
        """Create OpenAI client with mocked API key."""
        with patch.object(OpenAIClient, "__init__", lambda x, api_key=None: None):
            client = OpenAIClient()
            client.api_key = "test-api-key"
            client.client = Mock()
            client.MODEL_VERSION = "gpt-4o-2024-11-20"
            client.HIGH_CONFIDENCE_THRESHOLD = 0.8
            client.MAX_RETRIES = 1
            client.RETRY_DELAY_SECONDS = 0.1
            return client

    @pytest.fixture
    def temp_screenshot(self):
        """Create a temporary screenshot file."""
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            # Write a minimal PNG header
            f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
            temp_path = f.name

        yield temp_path

        # Cleanup
        Path(temp_path).unlink(missing_ok=True)

    def test_extract_bet_high_confidence(self, openai_client, temp_screenshot):
        """
        Given: Valid screenshot with clear bet data
        When: Extraction is performed
        Then: High confidence result returned with all fields
        """
        # Arrange
        mock_response = self._create_mock_openai_response(
            """EVENT: Manchester United vs Liverpool
SPORT: football
LEAGUE: Premier League
MARKET_CODE: TOTAL_GOALS_OVER_UNDER
PERIOD_SCOPE: FULL_MATCH
LINE_VALUE: 2.5
SIDE: OVER
STAKE: 100.50
ODDS: 1.91
PAYOUT: 191.96
CURRENCY: AUD
KICKOFF_TIME: 2025-10-30T19:00:00Z
MULTI_LEG: NO"""
        )

        openai_client.client.chat.completions.create = Mock(return_value=mock_response)

        # Act
        result = openai_client.extract_bet_from_screenshot(temp_screenshot)

        # Assert
        assert result["canonical_event"] == "Manchester United vs Liverpool"
        assert result["market_code"] == "TOTAL_GOALS_OVER_UNDER"
        assert result["period_scope"] == "FULL_MATCH"
        assert result["line_value"] == "2.5"
        assert result["side"] == "OVER"
        assert result["stake"] == Decimal("100.50")
        assert result["odds"] == Decimal("1.91")
        assert result["payout"] == Decimal("191.96")
        assert result["currency"] == "AUD"
        assert result["kickoff_time_utc"] == "2025-10-30T19:00:00Z"
        assert result["is_multi"] is False
        assert result["is_supported"] is True
        assert result["confidence"] >= Decimal("0.8")
        assert result["model_version_extraction"] == "gpt-4o-2024-11-20"

    def test_extract_bet_low_confidence(self, openai_client, temp_screenshot):
        """
        Given: Screenshot with missing/unclear fields
        When: Extraction is performed
        Then: Low confidence result with partial data
        """
        # Arrange - response with many UNKNOWN fields
        mock_response = self._create_mock_openai_response(
            """EVENT: Manchester United vs Liverpool
SPORT: football
LEAGUE: UNKNOWN
MARKET_CODE: UNKNOWN
PERIOD_SCOPE: UNKNOWN
LINE_VALUE: NONE
SIDE: UNKNOWN
STAKE: 100.00
ODDS: UNKNOWN
PAYOUT: UNKNOWN
CURRENCY: AUD
KICKOFF_TIME: UNKNOWN
MULTI_LEG: NO"""
        )

        openai_client.client.chat.completions.create = Mock(return_value=mock_response)

        # Act
        result = openai_client.extract_bet_from_screenshot(temp_screenshot)

        # Assert
        assert result["canonical_event"] == "Manchester United vs Liverpool"
        assert result["stake"] == Decimal("100.00")
        assert result["currency"] == "AUD"
        assert result["market_code"] is None
        assert result["odds"] is None
        assert result["confidence"] < Decimal("0.8")

    def test_accumulator_detection(self, openai_client, temp_screenshot):
        """
        Given: Screenshot of multi-leg accumulator bet
        When: Extraction is performed
        Then: is_multi=True and is_supported=False
        """
        # Arrange
        mock_response = self._create_mock_openai_response(
            """EVENT: Multiple selections
SPORT: football
LEAGUE: Various
MARKET_CODE: MONEYLINE
PERIOD_SCOPE: FULL_MATCH
LINE_VALUE: NONE
SIDE: TEAM_A
STAKE: 50.00
ODDS: 5.20
PAYOUT: 260.00
CURRENCY: GBP
KICKOFF_TIME: UNKNOWN
MULTI_LEG: YES"""
        )

        openai_client.client.chat.completions.create = Mock(return_value=mock_response)

        # Act
        result = openai_client.extract_bet_from_screenshot(temp_screenshot)

        # Assert
        assert result["is_multi"] is True
        assert result["is_supported"] is False

    def test_screenshot_not_found(self, openai_client):
        """
        Given: Non-existent screenshot path
        When: Extraction is attempted
        Then: FileNotFoundError is raised
        """
        # Act & Assert
        with pytest.raises(FileNotFoundError):
            openai_client.extract_bet_from_screenshot("nonexistent.png")

    def test_api_failure_with_retry(self, openai_client, temp_screenshot):
        """
        Given: OpenAI API fails once then succeeds
        When: Extraction is attempted
        Then: Retry succeeds and returns result
        """
        # Arrange
        from openai import OpenAIError

        mock_response = self._create_mock_openai_response(
            """EVENT: Test Match
SPORT: football
MARKET_CODE: MONEYLINE
SIDE: TEAM_A
STAKE: 100
ODDS: 2.0
PAYOUT: 200
CURRENCY: EUR
PERIOD_SCOPE: FULL_MATCH
LINE_VALUE: NONE
KICKOFF_TIME: UNKNOWN
MULTI_LEG: NO"""
        )

        # First call fails with OpenAIError, second succeeds
        openai_client.client.chat.completions.create = Mock(
            side_effect=[OpenAIError("API Error"), mock_response]
        )

        # Act
        result = openai_client.extract_bet_from_screenshot(temp_screenshot)

        # Assert
        assert result["canonical_event"] == "Test Match"
        assert openai_client.client.chat.completions.create.call_count == 2

    def test_api_failure_exhausts_retries(self, openai_client, temp_screenshot):
        """
        Given: OpenAI API fails repeatedly
        When: Extraction is attempted
        Then: Exception is raised after retries exhausted
        """
        # Arrange
        from openai import OpenAIError

        openai_client.client.chat.completions.create = Mock(side_effect=OpenAIError("API Error"))

        # Act & Assert
        with pytest.raises(OpenAIError):
            openai_client.extract_bet_from_screenshot(temp_screenshot)

        # Should retry once (2 total attempts)
        assert openai_client.client.chat.completions.create.call_count == 2

    def test_confidence_calculation_all_fields(self, openai_client):
        """
        Given: Extracted data with all fields present
        When: Confidence is calculated
        Then: High confidence score returned
        """
        # Arrange
        parsed_data = {
            "canonical_event": "Test Match",
            "market_code": "MONEYLINE",
            "side": "TEAM_A",
            "stake": Decimal("100"),
            "odds": Decimal("2.0"),
            "currency": "EUR",
            "period_scope": "FULL_MATCH",
            "line_value": None,
            "payout": Decimal("200"),
            "kickoff_time_utc": "2025-10-30T19:00:00Z",
        }

        # Act
        confidence = openai_client._calculate_confidence(parsed_data)

        # Assert
        assert confidence >= Decimal("0.8")

    def test_confidence_calculation_missing_fields(self, openai_client):
        """
        Given: Extracted data with missing critical fields
        When: Confidence is calculated
        Then: Low confidence score returned
        """
        # Arrange - missing most critical fields
        parsed_data = {
            "canonical_event": "Test Match",
            "market_code": None,
            "side": None,
            "stake": Decimal("100"),
            "odds": None,
            "currency": "EUR",
            "period_scope": None,
            "line_value": None,
            "payout": None,
            "kickoff_time_utc": None,
        }

        # Act
        confidence = openai_client._calculate_confidence(parsed_data)

        # Assert
        assert confidence < Decimal("0.8")

    def test_parse_extraction_response_complete(self, openai_client):
        """
        Given: Complete GPT-4o response with all fields
        When: Response is parsed
        Then: All fields correctly extracted
        """
        # Arrange
        raw_response = """EVENT: Chelsea vs Arsenal
SPORT: football
LEAGUE: Premier League
MARKET_CODE: HANDICAP
PERIOD_SCOPE: FULL_MATCH
LINE_VALUE: +0.5
SIDE: TEAM_A
STAKE: 200.00
ODDS: 1.85
PAYOUT: 370.00
CURRENCY: GBP
KICKOFF_TIME: 2025-11-01T15:00:00Z"""

        # Act
        result = openai_client._parse_extraction_response(raw_response)

        # Assert
        assert result["canonical_event"] == "Chelsea vs Arsenal"
        assert result["market_code"] == "HANDICAP"
        assert result["period_scope"] == "FULL_MATCH"
        assert result["line_value"] == "+0.5"
        assert result["side"] == "TEAM_A"
        assert result["stake"] == Decimal("200.00")
        assert result["odds"] == Decimal("1.85")
        assert result["payout"] == Decimal("370.00")
        assert result["currency"] == "GBP"
        assert result["kickoff_time_utc"] == "2025-11-01T15:00:00Z"

    def test_parse_extraction_response_with_unknowns(self, openai_client):
        """
        Given: GPT-4o response with UNKNOWN values
        When: Response is parsed
        Then: UNKNOWN values converted to None
        """
        # Arrange
        raw_response = """EVENT: Test Match
SPORT: UNKNOWN
MARKET_CODE: MONEYLINE
SIDE: UNKNOWN
STAKE: 100
ODDS: UNKNOWN
CURRENCY: EUR
PERIOD_SCOPE: UNKNOWN
LINE_VALUE: NONE
PAYOUT: UNKNOWN
KICKOFF_TIME: UNKNOWN"""

        # Act
        result = openai_client._parse_extraction_response(raw_response)

        # Assert
        assert result["canonical_event"] == "Test Match"
        assert result["sport"] == None
        assert result["side"] is None
        assert result["odds"] is None
        assert result["period_scope"] is None
        assert result["line_value"] is None
        assert result["payout"] is None
        assert result["kickoff_time_utc"] is None

    # Helper methods

    def _create_mock_openai_response(self, content: str):
        """Create a mock OpenAI API response."""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = content
        mock_response.usage = Mock()
        mock_response.usage.prompt_tokens = 1000
        mock_response.usage.completion_tokens = 200
        mock_response.usage.total_tokens = 1200
        return mock_response
