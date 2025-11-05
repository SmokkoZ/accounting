"""
OpenAI GPT-4o client for bet screenshot extraction and normalization.

This module provides:
- Vision-based OCR extraction from bet screenshots
- Structured data extraction with confidence scoring
- Accumulator/multi-leg bet detection
- Error handling and retry logic
"""

import base64
import time
from decimal import Decimal
from pathlib import Path
from typing import Dict, Optional, Any

import structlog
from openai import OpenAI, OpenAIError

from src.core.config import Config

logger = structlog.get_logger()


class OpenAIClient:
    """Client for OpenAI GPT-4o vision-based bet extraction."""

    # Model version for GPT-4o vision
    MODEL_VERSION = "gpt-4o-2024-11-20"

    # Confidence thresholds
    HIGH_CONFIDENCE_THRESHOLD = 0.8

    # Retry configuration
    MAX_RETRIES = 1
    RETRY_DELAY_SECONDS = 2

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize OpenAI client.

        Args:
            api_key: OpenAI API key. If None, uses Config.OPENAI_API_KEY.

        Raises:
            ValueError: If API key is not provided.
        """
        self.api_key = api_key or Config.OPENAI_API_KEY
        if not self.api_key:
            raise ValueError("OpenAI API key is required")

        self.client = OpenAI(api_key=self.api_key)
        logger.info("openai_client_initialized", model_version=self.MODEL_VERSION)

    def extract_bet_from_screenshot(self, screenshot_path: str) -> Dict[str, Any]:
        """
        Extract bet data from a screenshot using GPT-4o vision.

        Args:
            screenshot_path: Path to the bet screenshot image.

        Returns:
            Dictionary containing extracted bet data:
                - canonical_event: Normalized event name (str or None)
                - market_code: Market type code (str or None)
                - period_scope: Period of bet (str or None)
                - line_value: Line/handicap value (str or None)
                - side: Bet side (str or None)
                - stake: Stake amount (Decimal or None)
                - odds: Betting odds (Decimal or None)
                - payout: Potential payout (Decimal or None)
                - currency: Currency code (str or None)
                - kickoff_time_utc: Event kickoff time ISO8601 (str or None)
                - is_multi: Whether bet is multi-leg/accumulator (bool)
                - is_supported: Whether bet type is supported (bool)
                - confidence: Extraction confidence 0.0-1.0 (Decimal)
                - model_version_extraction: Model version used (str)
                - model_version_normalization: Model version used (str)
                - extraction_metadata: Additional metadata (dict)

        Raises:
            FileNotFoundError: If screenshot file doesn't exist.
            OpenAIError: If API call fails after retries.
        """
        start_time = time.time()

        # Validate screenshot path
        screenshot_file = Path(screenshot_path)
        if not screenshot_file.exists():
            logger.error("screenshot_not_found", path=screenshot_path)
            raise FileNotFoundError(f"Screenshot not found: {screenshot_path}")

        # Attempt extraction with retry logic
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                result = self._call_gpt4o_vision(screenshot_path)

                # Calculate extraction duration
                duration_ms = int((time.time() - start_time) * 1000)
                result["extraction_metadata"]["extraction_duration_ms"] = duration_ms

                logger.info(
                    "bet_extraction_successful",
                    screenshot=screenshot_path,
                    confidence=str(result["confidence"]),
                    is_multi=result["is_multi"],
                    duration_ms=duration_ms,
                    attempt=attempt + 1,
                )

                return result

            except OpenAIError as e:
                logger.warning(
                    "openai_api_error",
                    error=str(e),
                    attempt=attempt + 1,
                    max_retries=self.MAX_RETRIES,
                )

                # Retry on failure (except on last attempt)
                if attempt < self.MAX_RETRIES:
                    time.sleep(self.RETRY_DELAY_SECONDS)
                    continue
                else:
                    # Final attempt failed
                    logger.error(
                        "bet_extraction_failed",
                        screenshot=screenshot_path,
                        error=str(e),
                        attempts=attempt + 1,
                    )
                    raise

        # This should never be reached, but keep for type safety
        raise RuntimeError("Unexpected error in extraction retry logic")

    def _call_gpt4o_vision(self, screenshot_path: str) -> Dict[str, Any]:
        """
        Make the actual API call to GPT-4o vision.

        Args:
            screenshot_path: Path to screenshot image.

        Returns:
            Extracted bet data dictionary.

        Raises:
            OpenAIError: If API call fails.
        """
        # Read and encode image
        with open(screenshot_path, "rb") as image_file:
            image_data = base64.b64encode(image_file.read()).decode("utf-8")

        # Construct prompt
        prompt = self._build_extraction_prompt()

        # Call OpenAI API
        response = self.client.chat.completions.create(
            model=self.MODEL_VERSION,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{image_data}",
                                "detail": "high",
                            },
                        },
                    ],
                }
            ],
            max_tokens=1000,
            temperature=0.0,  # Deterministic extraction
        )

        # Extract response
        raw_response = response.choices[0].message.content or ""

        logger.debug(
            "gpt4o_raw_response",
            response=raw_response,
            prompt_tokens=response.usage.prompt_tokens if response.usage else None,
            completion_tokens=response.usage.completion_tokens if response.usage else None,
        )

        # Parse response into structured data
        parsed_data = self._parse_extraction_response(raw_response)

        # Add metadata
        parsed_data["model_version_extraction"] = self.MODEL_VERSION
        parsed_data["model_version_normalization"] = self.MODEL_VERSION
        parsed_data["extraction_metadata"] = {
            "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
            "completion_tokens": response.usage.completion_tokens if response.usage else 0,
            "total_tokens": response.usage.total_tokens if response.usage else 0,
            "raw_response": raw_response,
        }

        # Calculate confidence score
        parsed_data["confidence"] = self._calculate_confidence(parsed_data)

        # Detect multi-leg bets
        parsed_data["is_multi"] = self._detect_multi_leg(parsed_data, raw_response)
        parsed_data["is_supported"] = not parsed_data["is_multi"]

        return parsed_data

    def _build_extraction_prompt(self) -> str:
        """
        Build the prompt for bet extraction.

        Returns:
            Prompt string for GPT-4o.
        """
        return """Extract betting slip information from this screenshot. Return data in this exact format:

EVENT: <Team A vs Team B or event description>
SPORT: <football, basketball, tennis, etc.>
LEAGUE: <league name if visible>
MARKET_LABEL: <the exact market name as shown by the bookmaker (raw)>
MARKET_CODE: <if obviously mappable, pick from the codes list below; otherwise write UNKNOWN>
PERIOD_SCOPE: <FULL_MATCH, FIRST_HALF, SECOND_HALF, etc.>
LINE_VALUE: <handicap/line value if applicable, e.g., 2.5, +0.5, or NONE>
SIDE: <OVER, UNDER, TEAM_A, TEAM_B, DRAW, YES, NO, or specific team name>
STAKE: <stake amount as number only>
ODDS: <betting odds as decimal, e.g., 1.91>
PAYOUT: <potential payout as number only>
CURRENCY: <currency code - AUD, GBP, EUR, USD, etc.>
KICKOFF_TIME: <kickoff time in ISO8601 UTC format if visible, or UNKNOWN>
MULTI_LEG: <YES if accumulator/multi-leg bet, NO if single bet>

Market Codes:
- TOTAL_GOALS_OVER_UNDER: Football goals O/U (full match)
- FIRST_HALF_TOTAL_GOALS: Football 1H goals O/U
- SECOND_HALF_TOTAL_GOALS: Football 2H goals O/U
- TOTAL_CARDS_OVER_UNDER: Football bookings/cards O/U (match)
- TOTAL_CORNERS_OVER_UNDER: Football corners O/U (match)
- HOME_TEAM_TOTAL_CORNERS_OVER_UNDER: Football home team corners O/U
- AWAY_TEAM_TOTAL_CORNERS_OVER_UNDER: Football away team corners O/U
- TOTAL_SHOTS_OVER_UNDER: Football shots O/U (match)
- TOTAL_SHOTS_ON_TARGET_OVER_UNDER: Football shots on target O/U (match)
- BOTH_TEAMS_TO_SCORE: Football BTTS yes/no
- RED_CARD_AWARDED: Football red card awarded yes/no (any team)
- PENALTY_AWARDED: Football penalty awarded yes/no (any team)
- DRAW_NO_BET: Football two-way (home/away) with draw void
- ASIAN_HANDICAP: Two-way Asian handicap/spread
- MATCH_WINNER: Tennis match winner (two-way) or football two-way contexts only
- TOTAL_GAMES_OVER_UNDER: Tennis total games O/U (match)
- OTHER: Any other market type

Important:
1. If a field cannot be determined, write "UNKNOWN"
2. For MULTI_LEG, check if this is a single bet or accumulator (parlay)
3. STAKE, ODDS, PAYOUT should be numbers only (no currency symbols)
4. KICKOFF_TIME should be in UTC with Z suffix if known
5. Be conservative - mark as UNKNOWN if uncertain

Example output:
EVENT: Manchester United vs Liverpool
SPORT: football
LEAGUE: Premier League
MARKET_LABEL: Over/Under 2.5 Goals (Full Time)
MARKET_CODE: TOTAL_GOALS_OVER_UNDER
PERIOD_SCOPE: FULL_MATCH
LINE_VALUE: 2.5
SIDE: OVER
STAKE: 100.50
ODDS: 1.91
PAYOUT: 191.96
CURRENCY: AUD
KICKOFF_TIME: 2025-10-30T19:00:00Z
MULTI_LEG: NO
"""

    def _parse_extraction_response(self, raw_response: str) -> Dict[str, Any]:
        """
        Parse the GPT-4o response into structured data.

        Args:
            raw_response: Raw text response from GPT-4o.

        Returns:
            Parsed dictionary with extracted fields.
        """
        # Parse line-by-line
        lines = raw_response.strip().split("\n")
        data = {}

        for line in lines:
            if ":" in line:
                key, value = line.split(":", 1)
                key = key.strip().upper()
                value = value.strip()

                # Map to our field names
                if key == "EVENT":
                    data["canonical_event"] = value if value != "UNKNOWN" else None
                elif key == "SPORT":
                    data["sport"] = value if value != "UNKNOWN" else None
                elif key == "LEAGUE":
                    data["league"] = value if value != "UNKNOWN" else None
                elif key == "MARKET_LABEL":
                    data["market_label"] = value if value != "UNKNOWN" else None
                elif key == "MARKET_CODE":
                    data["market_code"] = value if value != "UNKNOWN" else None
                elif key == "PERIOD_SCOPE":
                    data["period_scope"] = value if value != "UNKNOWN" else None
                elif key == "LINE_VALUE":
                    data["line_value"] = value if value not in ("UNKNOWN", "NONE") else None
                elif key == "SIDE":
                    data["side"] = value if value != "UNKNOWN" else None
                elif key == "STAKE":
                    try:
                        data["stake"] = Decimal(value) if value != "UNKNOWN" else None
                    except Exception:
                        data["stake"] = None
                elif key == "ODDS":
                    try:
                        data["odds"] = Decimal(value) if value != "UNKNOWN" else None
                    except Exception:
                        data["odds"] = None
                elif key == "PAYOUT":
                    try:
                        data["payout"] = Decimal(value) if value != "UNKNOWN" else None
                    except Exception:
                        data["payout"] = None
                elif key == "CURRENCY":
                    data["currency"] = value if value != "UNKNOWN" else None
                elif key == "KICKOFF_TIME":
                    data["kickoff_time_utc"] = value if value != "UNKNOWN" else None

        # Ensure all required fields exist (even if None)
        required_fields = [
            "canonical_event",
            "market_code",
            "period_scope",
            "line_value",
            "side",
            "stake",
            "odds",
            "payout",
            "currency",
            "kickoff_time_utc",
        ]
        for field in required_fields:
            data.setdefault(field, None)

        return data

    def _detect_multi_leg(self, parsed_data: Dict[str, Any], raw_response: str) -> bool:
        """
        Detect if bet is a multi-leg/accumulator bet.

        Args:
            parsed_data: Parsed extraction data.
            raw_response: Raw GPT response.

        Returns:
            True if multi-leg bet, False otherwise.
        """
        # Check MULTI_LEG field in response
        for line in raw_response.strip().split("\n"):
            if "MULTI_LEG:" in line.upper():
                value = line.split(":", 1)[1].strip().upper()
                return value == "YES"

        # Default to single bet if not detected
        return False

    def _calculate_confidence(self, parsed_data: Dict[str, Any]) -> Decimal:
        """
        Calculate confidence score based on extraction completeness.

        High confidence (≥0.8): All required fields extracted cleanly
        Low confidence (<0.8): Missing fields or ambiguity

        Args:
            parsed_data: Parsed extraction data.

        Returns:
            Confidence score as Decimal (0.0 to 1.0).
        """
        # Required fields for high confidence
        critical_fields = [
            "canonical_event",
            "market_code",
            "side",
            "stake",
            "odds",
            "currency",
        ]

        # Count how many critical fields are present
        present_count = sum(1 for field in critical_fields if parsed_data.get(field) is not None)

        # Calculate base confidence
        base_confidence = Decimal(present_count) / Decimal(len(critical_fields))

        # Bonus points for optional fields
        optional_fields = ["period_scope", "line_value", "payout", "kickoff_time_utc"]
        optional_count = sum(1 for field in optional_fields if parsed_data.get(field) is not None)

        # Add up to 0.2 bonus for optional fields
        bonus = Decimal(optional_count) / Decimal(len(optional_fields)) * Decimal("0.2")

        confidence = min(base_confidence + bonus, Decimal("1.0"))

        # Round to 2 decimal places
        confidence = confidence.quantize(Decimal("0.01"))

        logger.debug(
            "confidence_calculated",
            critical_present=present_count,
            critical_total=len(critical_fields),
            optional_present=optional_count,
            confidence=str(confidence),
        )

        return confidence
