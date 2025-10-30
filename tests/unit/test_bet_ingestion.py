"""
Unit tests for bet ingestion service.

Tests cover:
- Successful bet extraction and database update
- Extraction logging
- Error handling for failed extractions
- Missing screenshot handling
"""

import sqlite3
import tempfile
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest

from src.services.bet_ingestion import BetIngestionService


class TestBetIngestionService:
    """Test cases for bet ingestion service."""

    @pytest.fixture
    def test_db(self):
        """Create an in-memory test database."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row

        # Create minimal schema
        conn.execute(
            """
            CREATE TABLE bets (
                id INTEGER PRIMARY KEY,
                associate_id INTEGER NOT NULL,
                bookmaker_id INTEGER NOT NULL,
                screenshot_path TEXT,
                market_code TEXT,
                period_scope TEXT,
                line_value TEXT,
                side TEXT,
                stake_original TEXT,
                odds_original TEXT,
                payout TEXT,
                currency TEXT,
                kickoff_time_utc TEXT,
                normalization_confidence TEXT,
                is_multi BOOLEAN,
                is_supported BOOLEAN,
                model_version_extraction TEXT,
                model_version_normalization TEXT,
                status TEXT DEFAULT 'incoming',
                stake_eur TEXT DEFAULT '0.0',
                odds TEXT DEFAULT '1.0',
                created_at_utc TEXT,
                updated_at_utc TEXT
            )
        """
        )

        conn.execute(
            """
            CREATE TABLE extraction_log (
                id INTEGER PRIMARY KEY,
                bet_id INTEGER NOT NULL,
                model_version TEXT NOT NULL,
                prompt_tokens INTEGER,
                completion_tokens INTEGER,
                total_tokens INTEGER,
                extraction_duration_ms INTEGER,
                confidence_score TEXT,
                raw_response TEXT,
                error_message TEXT,
                created_at_utc TEXT
            )
        """
        )

        yield conn
        conn.close()

    @pytest.fixture
    def temp_screenshot(self):
        """Create a temporary screenshot file."""
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
            temp_path = f.name

        yield temp_path
        Path(temp_path).unlink(missing_ok=True)

    def test_process_bet_extraction_success(self, test_db, temp_screenshot):
        """
        Given: Valid bet with screenshot
        When: Extraction is processed
        Then: Bet updated and extraction logged
        """
        # Arrange
        # Insert test bet
        cursor = test_db.execute(
            """
            INSERT INTO bets (
                id, associate_id, bookmaker_id, screenshot_path,
                stake_eur, odds, created_at_utc, updated_at_utc
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                1,
                1,
                temp_screenshot,
                "0.0",
                "1.0",
                "2025-10-30T10:00:00Z",
                "2025-10-30T10:00:00Z",
            ),
        )
        test_db.commit()

        # Create service with mocked OpenAI client
        service = BetIngestionService(db_conn=test_db)

        mock_extraction_result = {
            "canonical_event": "Test Match",
            "market_code": "MONEYLINE",
            "period_scope": "FULL_MATCH",
            "line_value": None,
            "side": "TEAM_A",
            "stake": Decimal("100.00"),
            "odds": Decimal("2.0"),
            "payout": Decimal("200.00"),
            "currency": "EUR",
            "kickoff_time_utc": "2025-10-30T19:00:00Z",
            "is_multi": False,
            "is_supported": True,
            "confidence": Decimal("0.95"),
            "model_version_extraction": "gpt-4o-2024-11-20",
            "model_version_normalization": "gpt-4o-2024-11-20",
            "extraction_metadata": {
                "prompt_tokens": 1000,
                "completion_tokens": 200,
                "total_tokens": 1200,
                "extraction_duration_ms": 2500,
                "raw_response": "EVENT: Test Match...",
            },
        }

        service.openai_client.extract_bet_from_screenshot = Mock(
            return_value=mock_extraction_result
        )

        # Act
        result = service.process_bet_extraction(1)

        # Assert
        assert result is True

        # Verify bet was updated
        bet = test_db.execute("SELECT * FROM bets WHERE id = 1").fetchone()
        assert bet["market_code"] == "MONEYLINE"
        assert bet["side"] == "TEAM_A"
        assert bet["stake_original"] == "100.00"
        assert bet["odds_original"] == "2.0"
        assert bet["payout"] == "200.00"
        assert bet["currency"] == "EUR"
        assert bet["normalization_confidence"] == "0.95"
        assert bet["is_multi"] == 0
        assert bet["is_supported"] == 1

        # Verify extraction was logged
        log = test_db.execute("SELECT * FROM extraction_log WHERE bet_id = 1").fetchone()
        assert log is not None
        assert log["model_version"] == "gpt-4o-2024-11-20"
        assert log["total_tokens"] == 1200
        assert log["confidence_score"] == "0.95"
        assert log["error_message"] is None

    def test_process_bet_extraction_failure(self, test_db, temp_screenshot):
        """
        Given: Bet with screenshot that causes extraction error
        When: Extraction is processed
        Then: Error logged and bet remains incoming
        """
        # Arrange
        test_db.execute(
            """
            INSERT INTO bets (
                id, associate_id, bookmaker_id, screenshot_path,
                stake_eur, odds, created_at_utc, updated_at_utc
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                1,
                1,
                temp_screenshot,
                "0.0",
                "1.0",
                "2025-10-30T10:00:00Z",
                "2025-10-30T10:00:00Z",
            ),
        )
        test_db.commit()

        service = BetIngestionService(db_conn=test_db)
        service.openai_client.extract_bet_from_screenshot = Mock(side_effect=Exception("API Error"))

        # Act
        result = service.process_bet_extraction(1)

        # Assert
        assert result is False

        # Verify error was logged
        log = test_db.execute("SELECT * FROM extraction_log WHERE bet_id = 1").fetchone()
        assert log is not None
        assert log["error_message"] == "API Error"

    def test_process_bet_not_found(self, test_db):
        """
        Given: Non-existent bet ID
        When: Extraction is attempted
        Then: ValueError is raised
        """
        # Arrange
        service = BetIngestionService(db_conn=test_db)

        # Act & Assert
        with pytest.raises(ValueError, match="Bet not found"):
            service.process_bet_extraction(999)

    def test_process_bet_missing_screenshot(self, test_db):
        """
        Given: Bet without screenshot path
        When: Extraction is attempted
        Then: ValueError is raised
        """
        # Arrange
        test_db.execute(
            """
            INSERT INTO bets (
                id, associate_id, bookmaker_id, screenshot_path,
                stake_eur, odds, created_at_utc, updated_at_utc
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (1, 1, 1, None, "0.0", "1.0", "2025-10-30T10:00:00Z", "2025-10-30T10:00:00Z"),
        )
        test_db.commit()

        service = BetIngestionService(db_conn=test_db)

        # Act & Assert
        with pytest.raises(ValueError, match="has no screenshot"):
            service.process_bet_extraction(1)

    def test_update_bet_with_extraction_partial_data(self, test_db):
        """
        Given: Extraction result with some missing fields
        When: Bet is updated
        Then: Only available fields are updated
        """
        # Arrange
        test_db.execute(
            """
            INSERT INTO bets (
                id, associate_id, bookmaker_id, screenshot_path,
                stake_eur, odds, created_at_utc, updated_at_utc
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (1, 1, 1, "test.png", "0.0", "1.0", "2025-10-30T10:00:00Z", "2025-10-30T10:00:00Z"),
        )
        test_db.commit()

        service = BetIngestionService(db_conn=test_db)

        partial_result = {
            "canonical_event": "Test Match",
            "market_code": "MONEYLINE",
            "period_scope": None,
            "line_value": None,
            "side": "TEAM_A",
            "stake": Decimal("50.00"),
            "odds": None,
            "payout": None,
            "currency": "EUR",
            "kickoff_time_utc": None,
            "is_multi": False,
            "is_supported": True,
            "confidence": Decimal("0.60"),
            "model_version_extraction": "gpt-4o-2024-11-20",
            "model_version_normalization": "gpt-4o-2024-11-20",
        }

        # Act
        service._update_bet_with_extraction(1, partial_result)

        # Assert
        bet = test_db.execute("SELECT * FROM bets WHERE id = 1").fetchone()
        assert bet["market_code"] == "MONEYLINE"
        assert bet["side"] == "TEAM_A"
        assert bet["stake_original"] == "50.00"
        assert bet["odds_original"] is None
        assert bet["payout"] is None
        assert bet["normalization_confidence"] == "0.60"

    def test_log_extraction_metadata_success(self, test_db):
        """
        Given: Successful extraction with metadata
        When: Metadata is logged
        Then: Complete log entry created
        """
        # Arrange
        test_db.execute(
            """
            INSERT INTO bets (
                id, associate_id, bookmaker_id, screenshot_path,
                stake_eur, odds, created_at_utc, updated_at_utc
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (1, 1, 1, "test.png", "0.0", "1.0", "2025-10-30T10:00:00Z", "2025-10-30T10:00:00Z"),
        )
        test_db.commit()

        service = BetIngestionService(db_conn=test_db)

        extraction_result = {
            "confidence": Decimal("0.95"),
            "model_version_extraction": "gpt-4o-2024-11-20",
            "extraction_metadata": {
                "prompt_tokens": 1000,
                "completion_tokens": 200,
                "total_tokens": 1200,
                "extraction_duration_ms": 2500,
                "raw_response": "EVENT: Test...",
            },
        }

        # Act
        service._log_extraction_metadata(1, extraction_result, success=True)

        # Assert
        log = test_db.execute("SELECT * FROM extraction_log WHERE bet_id = 1").fetchone()
        assert log["model_version"] == "gpt-4o-2024-11-20"
        assert log["prompt_tokens"] == 1000
        assert log["completion_tokens"] == 200
        assert log["total_tokens"] == 1200
        assert log["extraction_duration_ms"] == 2500
        assert log["confidence_score"] == "0.95"
        assert "EVENT: Test..." in log["raw_response"]
        assert log["error_message"] is None

    def test_log_extraction_metadata_failure(self, test_db):
        """
        Given: Failed extraction with error
        When: Metadata is logged
        Then: Error message captured in log
        """
        # Arrange
        test_db.execute(
            """
            INSERT INTO bets (
                id, associate_id, bookmaker_id, screenshot_path,
                stake_eur, odds, created_at_utc, updated_at_utc
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (1, 1, 1, "test.png", "0.0", "1.0", "2025-10-30T10:00:00Z", "2025-10-30T10:00:00Z"),
        )
        test_db.commit()

        service = BetIngestionService(db_conn=test_db)

        # Act
        service._log_extraction_metadata(
            1,
            {"confidence": Decimal("0.0"), "extraction_metadata": {}},
            success=False,
            error_message="API Error: Timeout",
        )

        # Assert
        log = test_db.execute("SELECT * FROM extraction_log WHERE bet_id = 1").fetchone()
        assert log["error_message"] == "API Error: Timeout"
        assert log["confidence_score"] == "0.0"
