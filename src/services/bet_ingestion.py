"""
Bet ingestion service for processing screenshots and extracting bet data.

This module provides:
- Orchestration of OCR extraction pipeline
- Database updates with extracted bet data
- Extraction logging and audit trail
- Error handling for failed extractions
"""

import sqlite3
from decimal import Decimal
from typing import Optional, Dict, Any

import structlog

from src.core.database import get_db_connection
from src.integrations.openai_client import OpenAIClient
from src.utils.datetime_helpers import utc_now_iso

logger = structlog.get_logger()


class BetIngestionService:
    """Service for ingesting and processing bet screenshots."""

    def __init__(self, db_conn: Optional[sqlite3.Connection] = None):
        """
        Initialize the bet ingestion service.

        Args:
            db_conn: Database connection. If None, creates a new connection.
        """
        self.db = db_conn or get_db_connection()
        self.openai_client = OpenAIClient()

    def process_bet_extraction(self, bet_id: int) -> bool:
        """
        Process OCR extraction for a bet screenshot.

        This method:
        1. Retrieves bet record from database
        2. Calls OpenAI client to extract data from screenshot
        3. Updates bet record with extracted data
        4. Logs extraction metadata
        5. Handles errors gracefully

        Args:
            bet_id: ID of the bet to process.

        Returns:
            True if extraction succeeded, False otherwise.

        Raises:
            ValueError: If bet not found or missing screenshot.
        """
        logger.info("starting_bet_extraction", bet_id=bet_id)

        # Retrieve bet record
        bet = self._get_bet_by_id(bet_id)
        if not bet:
            raise ValueError(f"Bet not found: {bet_id}")

        screenshot_path = bet["screenshot_path"]
        if not screenshot_path:
            raise ValueError(f"Bet {bet_id} has no screenshot")

        try:
            # Extract data using OpenAI client
            extraction_result = self.openai_client.extract_bet_from_screenshot(screenshot_path)

            # Update bet record with extracted data
            self._update_bet_with_extraction(bet_id, extraction_result)

            # Log extraction metadata
            self._log_extraction_metadata(bet_id, extraction_result, success=True)

            logger.info(
                "bet_extraction_completed",
                bet_id=bet_id,
                confidence=str(extraction_result["confidence"]),
                is_multi=extraction_result["is_multi"],
            )

            return True

        except Exception as e:
            logger.error("bet_extraction_failed", bet_id=bet_id, error=str(e), exc_info=True)

            # Log failed extraction
            self._log_extraction_metadata(
                bet_id,
                {"extraction_metadata": {}, "confidence": Decimal("0.0")},
                success=False,
                error_message=str(e),
            )

            # Bet remains in "incoming" status for manual entry
            return False

    def _get_bet_by_id(self, bet_id: int) -> Optional[Dict[str, Any]]:
        """
        Retrieve bet record from database.

        Args:
            bet_id: ID of the bet.

        Returns:
            Bet record as dictionary, or None if not found.
        """
        cursor = self.db.execute(
            """
            SELECT * FROM bets WHERE id = ?
            """,
            (bet_id,),
        )
        row = cursor.fetchone()

        if row:
            return dict(row)
        return None

    def _update_bet_with_extraction(self, bet_id: int, extraction_result: Dict[str, Any]) -> None:
        """
        Update bet record with extracted data.

        Args:
            bet_id: ID of the bet to update.
            extraction_result: Extraction result from OpenAI client.
        """
        # Convert Decimal values to strings for storage
        stake = str(extraction_result["stake"]) if extraction_result.get("stake") else None
        odds = str(extraction_result["odds"]) if extraction_result.get("odds") else None
        payout = str(extraction_result["payout"]) if extraction_result.get("payout") else None
        confidence = str(extraction_result["confidence"])

        # Update bet record
        self.db.execute(
            """
            UPDATE bets
            SET
                market_code = ?,
                period_scope = ?,
                line_value = ?,
                side = ?,
                stake_original = ?,
                odds_original = ?,
                payout = ?,
                currency = ?,
                kickoff_time_utc = ?,
                normalization_confidence = ?,
                is_multi = ?,
                is_supported = ?,
                model_version_extraction = ?,
                model_version_normalization = ?,
                updated_at_utc = ?
            WHERE id = ?
            """,
            (
                extraction_result.get("market_code"),
                extraction_result.get("period_scope"),
                extraction_result.get("line_value"),
                extraction_result.get("side"),
                stake,
                odds,
                payout,
                extraction_result.get("currency"),
                extraction_result.get("kickoff_time_utc"),
                confidence,
                extraction_result.get("is_multi", False),
                extraction_result.get("is_supported", True),
                extraction_result.get("model_version_extraction"),
                extraction_result.get("model_version_normalization"),
                utc_now_iso(),
                bet_id,
            ),
        )

        self.db.commit()

        logger.debug("bet_updated_with_extraction", bet_id=bet_id)

    def _log_extraction_metadata(
        self,
        bet_id: int,
        extraction_result: Dict[str, Any],
        success: bool,
        error_message: Optional[str] = None,
    ) -> None:
        """
        Log extraction metadata to extraction_log table.

        Args:
            bet_id: ID of the bet.
            extraction_result: Extraction result from OpenAI client.
            success: Whether extraction succeeded.
            error_message: Error message if extraction failed.
        """
        metadata = extraction_result.get("extraction_metadata", {})

        # Get model version (may be None if extraction failed early)
        model_version = extraction_result.get(
            "model_version_extraction", OpenAIClient.MODEL_VERSION
        )

        # Get confidence score
        confidence = str(extraction_result.get("confidence", Decimal("0.0")))

        self.db.execute(
            """
            INSERT INTO extraction_log (
                bet_id,
                model_version,
                prompt_tokens,
                completion_tokens,
                total_tokens,
                extraction_duration_ms,
                confidence_score,
                raw_response,
                error_message,
                created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                bet_id,
                model_version,
                metadata.get("prompt_tokens"),
                metadata.get("completion_tokens"),
                metadata.get("total_tokens"),
                metadata.get("extraction_duration_ms"),
                confidence,
                metadata.get("raw_response"),
                error_message,
                utc_now_iso(),
            ),
        )

        self.db.commit()

        logger.debug(
            "extraction_metadata_logged",
            bet_id=bet_id,
            success=success,
            tokens=metadata.get("total_tokens"),
        )

    def close(self) -> None:
        """Close the database connection if owned by this service."""
        if self.db:
            self.db.close()
