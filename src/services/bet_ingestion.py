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
from src.services.market_normalizer import MarketNormalizer
from src.services.event_normalizer import EventNormalizer
from src.services.bet_verification import BetVerificationService
from src.core.config import Config
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

            # Normalize market fields (post-extraction)
            normalizer = MarketNormalizer(self.db)
            norm = normalizer.normalize(
                sport=extraction_result.get("sport"),
                market_label=extraction_result.get("market_label"),
                market_code_guess=extraction_result.get("market_code"),
                period_scope_text=extraction_result.get("period_scope"),
                side_text=extraction_result.get("side"),
                line_value=extraction_result.get("line_value"),
                event_name=extraction_result.get("canonical_event"),
            )

            # Merge normalized fields back into extraction_result
            # Preserve original OCR guess if normalizer couldn't map a code
            merged = dict(extraction_result)
            mapped_code = norm.get("market_code") is not None
            for k, v in norm.items():
                if k == "market_code" and v is None:
                    # Keep original OCR guess
                    continue
                if k == "normalization_confidence" and not mapped_code:
                    # Keep original extraction confidence
                    continue
                merged[k] = v
            extraction_result = merged

            # Normalize event name before any auto-creation
            normalized_event = EventNormalizer.normalize_event_name(
                extraction_result.get("canonical_event"),
                extraction_result.get("sport"),
            )
            if normalized_event:
                extraction_result["canonical_event"] = normalized_event

            # Update bet record with extracted + normalized data
            self._update_bet_with_extraction(bet_id, extraction_result)

            # Log extraction metadata
            self._log_extraction_metadata(bet_id, extraction_result, success=True)

            # Optionally auto-create/match canonical event on OCR success
            try:
                conf = extraction_result.get("confidence")
                conf_f = float(conf) if conf is not None else 0.0
                if (
                    Config.AUTO_CREATE_EVENT_ON_OCR
                    and extraction_result.get("canonical_event")
                    and conf_f >= Config.OCR_EVENT_CONFIDENCE_THRESHOLD
                ):
                    svc = BetVerificationService(self.db)
                    event_id = svc.get_or_create_canonical_event(
                        bet_id=bet_id,
                        event_name=extraction_result.get("canonical_event"),
                        sport=extraction_result.get("sport"),
                        competition=extraction_result.get("league"),
                        kickoff_time_utc=extraction_result.get("kickoff_time_utc"),
                    )
                    # Persist event_id onto bet without changing status
                    self.db.execute(
                        "UPDATE bets SET canonical_event_id = ?, updated_at_utc = ? WHERE id = ?",
                        (event_id, utc_now_iso(), bet_id),
                    )
                    self.db.commit()
            except Exception as e:
                logger.error("auto_event_create_on_ocr_failed", bet_id=bet_id, error=str(e))

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
        confidence_value = extraction_result.get("confidence")
        confidence = str(confidence_value) if confidence_value is not None else "0.0"

        # Build dynamic update to support minimal test schemas
        columns = self._get_table_columns("bets")

        manual_columns = [
            col
            for col in (
                "manual_stake_override",
                "manual_stake_currency",
                "manual_potential_win_override",
                "manual_potential_win_currency",
            )
            if col in columns
        ]
        manual_row = None
        if manual_columns:
            try:
                manual_row = self.db.execute(
                    f"SELECT {', '.join(manual_columns)} FROM bets WHERE id = ?",
                    (bet_id,),
                ).fetchone()
            except Exception:
                manual_row = None

        def _manual_value(column: str) -> Optional[str]:
            if not manual_row:
                return None
            try:
                return manual_row[column]
            except (KeyError, IndexError):
                return None

        manual_stake_locked = bool(_manual_value("manual_stake_override"))
        manual_win_locked = bool(_manual_value("manual_potential_win_override"))

        set_clauses = []
        params = []

        # Optional selection_text (if column exists)
        if "selection_text" in columns:
            set_clauses.append("selection_text = COALESCE(?, selection_text)")
            params.append(extraction_result.get("canonical_event"))

        # Common fields
        def add(col: str, value, *, skip: bool = False):
            if skip:
                return
            if col in columns:
                set_clauses.append(f"{col} = ?")
                params.append(value)

        add("market_code", extraction_result.get("market_code"))
        add("period_scope", extraction_result.get("period_scope"))
        add("line_value", extraction_result.get("line_value"))
        add("side", extraction_result.get("side"))
        add("stake_original", stake, skip=manual_stake_locked)
        add("stake_amount", stake, skip=manual_stake_locked)
        add("odds_original", odds)
        add("payout", payout, skip=manual_win_locked)
        add(
            "stake_currency",
            extraction_result.get("currency"),
            skip=manual_stake_locked,
        )
        add("confidence_score", confidence)
        add("event_id", extraction_result.get("canonical_event_id"))
        add("market_type", extraction_result.get("market_code"))
        add("selection", extraction_result.get("side"))
        # Enforce currency from associate's home currency, do not trust OCR
        try:
            cur = self.db.execute(
                """
                SELECT a.home_currency
                FROM bets b JOIN associates a ON b.associate_id = a.id
                WHERE b.id = ?
                """,
                (bet_id,),
            )
            row = cur.fetchone()
            forced_currency = (row[0] if row and row[0] else None)
        except Exception:
            forced_currency = None
        add(
            "currency",
            forced_currency or extraction_result.get("currency"),
            skip=manual_stake_locked,
        )
        add("kickoff_time_utc", extraction_result.get("kickoff_time_utc"))
        add(
            "normalization_confidence",
            extraction_result.get("normalization_confidence", confidence),
        )
        # Optional canonical_market_id
        if "canonical_market_id" in columns:
            add("canonical_market_id", extraction_result.get("canonical_market_id"))
        add("is_multi", extraction_result.get("is_multi", False))
        add("is_supported", extraction_result.get("is_supported", True))
        add("model_version_extraction", extraction_result.get("model_version_extraction"))
        add(
            "model_version_normalization",
            extraction_result.get("model_version_normalization"),
        )
        add("updated_at_utc", utc_now_iso())

        if not set_clauses:
            return

        sql = "UPDATE bets SET " + ",\n                ".join(set_clauses) + " WHERE id = ?"
        params.append(bet_id)
        self.db.execute(sql, tuple(params))

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

    def _get_table_columns(self, table: str) -> set[str]:
        cur = self.db.execute(f"PRAGMA table_info({table})")
        return {row[1] for row in cur.fetchall()}  # type: ignore[index]
