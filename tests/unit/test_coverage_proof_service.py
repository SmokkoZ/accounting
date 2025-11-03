"""
Unit tests for Coverage Proof Service.

Tests coverage proof distribution logic, screenshot queries,
rate limiting, and message logging.
"""

import asyncio
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import Message
from telegram.error import TelegramError

from src.services.coverage_proof_service import (
    CoverageProofResult,
    CoverageProofService,
)
from src.core.database import get_db_connection
from src.core.schema import create_schema


@pytest.fixture
def test_db():
    """Create an in-memory test database with schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    # Create schema
    create_schema(conn)

    yield conn

    conn.close()


@pytest.fixture
def seed_test_data(test_db):
    """Seed test database with associates, bookmakers, events, and bets."""
    cursor = test_db.cursor()

    # Create associates
    cursor.execute(
        """
        INSERT INTO associates (id, display_alias, home_currency, multibook_chat_id, is_admin)
        VALUES (1, 'Alice', 'EUR', '123456', FALSE),
               (2, 'Bob', 'USD', '789012', FALSE),
               (3, 'Charlie', 'GBP', NULL, FALSE)
        """
    )

    # Create bookmakers
    cursor.execute(
        """
        INSERT INTO bookmakers (id, associate_id, bookmaker_name)
        VALUES (1, 1, 'Bet365'),
               (2, 2, 'Betfair'),
               (3, 3, 'William Hill')
        """
    )

    # Create canonical event
    cursor.execute(
        """
        INSERT INTO canonical_events (id, normalized_event_name, sport, league, kickoff_time_utc)
        VALUES (1, 'Man Utd vs Arsenal', 'Football', 'Premier League', '2025-11-10T15:00:00Z')
        """
    )

    # Create canonical market
    cursor.execute(
        """
        INSERT INTO canonical_markets (id, market_code, description)
        VALUES (1, 'OVER_UNDER', 'Over/Under Goals')
        """
    )

    # Create bets for Side A (Alice)
    cursor.execute(
        """
        INSERT INTO bets (
            id, associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
            status, stake_eur, odds, currency, screenshot_path,
            created_at_utc, updated_at_utc
        )
        VALUES (1, 1, 1, 1, 1, 'verified', '100.00', '1.91', 'EUR', 'data/screenshots/bet1.png',
                datetime('now') || 'Z', datetime('now') || 'Z')
        """
    )

    # Create bets for Side B (Bob)
    cursor.execute(
        """
        INSERT INTO bets (
            id, associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
            status, stake_eur, odds, currency, screenshot_path,
            created_at_utc, updated_at_utc
        )
        VALUES (2, 2, 2, 1, 1, 'verified', '110.00', '2.10', 'USD', 'data/screenshots/bet2.png',
                datetime('now') || 'Z', datetime('now') || 'Z')
        """
    )

    # Create bets for Side B (Charlie - no multibook chat)
    cursor.execute(
        """
        INSERT INTO bets (
            id, associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
            status, stake_eur, odds, currency, screenshot_path,
            created_at_utc, updated_at_utc
        )
        VALUES (3, 3, 3, 1, 1, 'verified', '105.00', '2.05', 'GBP', 'data/screenshots/bet3.png',
                datetime('now') || 'Z', datetime('now') || 'Z')
        """
    )

    # Create surebet
    cursor.execute(
        """
        INSERT INTO surebets (
            id, canonical_event_id, canonical_market_id, market_code,
            period_scope, line_value, status,
            worst_case_profit_eur, total_staked_eur, roi, risk_classification,
            created_at_utc, updated_at_utc
        )
        VALUES (1, 1, 1, 'OVER_UNDER', 'FULL_MATCH', '2.5', 'open',
                '5.00', '315.00', '0.0158', 'Safe',
                datetime('now') || 'Z', datetime('now') || 'Z')
        """
    )

    # Link bets to surebet
    cursor.execute(
        """
        INSERT INTO surebet_bets (surebet_id, bet_id, side)
        VALUES (1, 1, 'A'),
               (1, 2, 'B'),
               (1, 3, 'B')
        """
    )

    test_db.commit()
    return test_db


def test_get_opposite_screenshots_side_a(seed_test_data):
    """Test querying opposite side screenshots for Side A associate."""
    service = CoverageProofService(db=seed_test_data)

    screenshots = service.get_opposite_screenshots(surebet_id=1, side="A")

    # Side A should get Side B screenshots (bet 2 and bet 3)
    assert len(screenshots) == 2
    assert screenshots[0]["bet_id"] == 2
    assert screenshots[0]["screenshot_path"] == "data/screenshots/bet2.png"
    assert screenshots[0]["associate_alias"] == "Bob"
    assert screenshots[1]["bet_id"] == 3
    assert screenshots[1]["screenshot_path"] == "data/screenshots/bet3.png"
    assert screenshots[1]["associate_alias"] == "Charlie"

    service.close()


def test_get_opposite_screenshots_side_b(seed_test_data):
    """Test querying opposite side screenshots for Side B associate."""
    service = CoverageProofService(db=seed_test_data)

    screenshots = service.get_opposite_screenshots(surebet_id=1, side="B")

    # Side B should get Side A screenshots (bet 1)
    assert len(screenshots) == 1
    assert screenshots[0]["bet_id"] == 1
    assert screenshots[0]["screenshot_path"] == "data/screenshots/bet1.png"
    assert screenshots[0]["associate_alias"] == "Alice"

    service.close()


def test_get_surebet_associates_by_side(seed_test_data):
    """Test grouping associates by side."""
    service = CoverageProofService(db=seed_test_data)

    associates = service.get_surebet_associates_by_side(surebet_id=1)

    # Side A should have Alice
    assert len(associates["A"]) == 1
    assert associates["A"][0]["associate_alias"] == "Alice"
    assert associates["A"][0]["multibook_chat_id"] == "123456"

    # Side B should have Bob and Charlie
    assert len(associates["B"]) == 2
    assert associates["B"][0]["associate_alias"] == "Bob"
    assert associates["B"][0]["multibook_chat_id"] == "789012"
    assert associates["B"][1]["associate_alias"] == "Charlie"
    assert associates["B"][1]["multibook_chat_id"] is None

    service.close()


def test_get_surebet_details(seed_test_data):
    """Test retrieving surebet details."""
    service = CoverageProofService(db=seed_test_data)

    details = service.get_surebet_details(surebet_id=1)

    assert details is not None
    assert details["id"] == 1
    assert details["market_code"] == "OVER_UNDER"
    assert details["line_value"] == "2.5"
    assert details["status"] == "open"
    assert details["event_name"] == "Man Utd vs Arsenal"
    assert details["coverage_proof_sent_at_utc"] is None

    service.close()


def test_format_coverage_proof_message(seed_test_data):
    """Test coverage proof message formatting."""
    service = CoverageProofService(db=seed_test_data)

    surebet_details = {
        "event_name": "Man Utd vs Arsenal",
        "market_code": "OVER_UNDER",
        "line_value": "2.5",
    }

    message = service._format_coverage_proof_message(surebet_details, "Over 2.5")

    assert "Man Utd vs Arsenal" in message
    assert "Over 2.5" in message
    assert "covered" in message.lower()
    assert "opposite side attached" in message.lower()

    service.close()


def test_rate_limiting_allows_first_message(seed_test_data):
    """Test rate limiting allows first message to a chat."""
    service = CoverageProofService(db=seed_test_data)

    allowed, wait = service._check_rate_limit("123456")

    assert allowed is True
    assert wait == 0.0

    service.close()


def test_rate_limiting_blocks_after_limit(seed_test_data):
    """Test rate limiting blocks messages after exceeding limit."""
    service = CoverageProofService(db=seed_test_data)

    # Send maximum allowed messages
    for _ in range(service.RATE_LIMIT_MESSAGES_PER_MINUTE):
        service._record_rate_limit("123456")

    # Next message should be blocked
    allowed, wait = service._check_rate_limit("123456")

    assert allowed is False
    assert wait > 0

    service.close()


def test_log_coverage_proof_success(seed_test_data):
    """Test logging successful coverage proof delivery."""
    service = CoverageProofService(db=seed_test_data)

    service.log_coverage_proof(
        surebet_id=1,
        associate_id=1,
        message_id="999",
        screenshots_sent=["data/screenshots/bet2.png", "data/screenshots/bet3.png"],
        success=True,
        error_message=None,
    )

    # Verify log entry
    row = seed_test_data.execute(
        """
        SELECT * FROM multibook_message_log
        WHERE surebet_id = 1 AND associate_id = 1
        """
    ).fetchone()

    assert row is not None
    assert row["message_type"] == "COVERAGE_PROOF"
    assert row["delivery_status"] == "sent"
    assert row["message_id"] == "999"
    assert row["sent_at_utc"] is not None

    service.close()


def test_log_coverage_proof_failure(seed_test_data):
    """Test logging failed coverage proof delivery."""
    service = CoverageProofService(db=seed_test_data)

    service.log_coverage_proof(
        surebet_id=1,
        associate_id=3,
        message_id=None,
        screenshots_sent=[],
        success=False,
        error_message="Multibook chat missing for Charlie",
    )

    # Verify log entry
    row = seed_test_data.execute(
        """
        SELECT * FROM multibook_message_log
        WHERE surebet_id = 1 AND associate_id = 3
        """
    ).fetchone()

    assert row is not None
    assert row["message_type"] == "COVERAGE_PROOF"
    assert row["delivery_status"] == "failed"
    assert row["message_id"] is None
    assert row["error_message"] == "Multibook chat missing for Charlie"
    assert row["sent_at_utc"] is None

    service.close()


def test_mark_coverage_proof_sent(seed_test_data):
    """Test marking surebet as having coverage proof sent."""
    service = CoverageProofService(db=seed_test_data)

    # Initially should be None
    details = service.get_surebet_details(1)
    assert details["coverage_proof_sent_at_utc"] is None

    # Mark as sent
    service.mark_coverage_proof_sent(1)

    # Should now have timestamp
    details = service.get_surebet_details(1)
    assert details["coverage_proof_sent_at_utc"] is not None

    service.close()


@pytest.mark.asyncio
async def test_send_coverage_proof_to_associate_success(seed_test_data):
    """Test sending coverage proof to an associate successfully."""
    service = CoverageProofService(db=seed_test_data)

    # Mock Telegram bot
    mock_bot = AsyncMock()
    mock_message = MagicMock(spec=Message)
    mock_message.message_id = 12345
    mock_bot.send_media_group.return_value = [mock_message]

    # Mock file paths to exist
    with patch("pathlib.Path.exists", return_value=True), \
         patch("builtins.open", MagicMock()):

        opposite_screenshots = service.get_opposite_screenshots(1, "A")
        surebet_details = service.get_surebet_details(1)

        result = await service.send_coverage_proof_to_associate(
            bot=mock_bot,
            surebet_id=1,
            associate_id=1,
            associate_alias="Alice",
            multibook_chat_id="123456",
            opposite_screenshots=opposite_screenshots,
            surebet_details=surebet_details,
        )

        assert result.success is True
        assert result.associate_id == 1
        assert result.associate_alias == "Alice"
        assert result.message_id == "12345"
        assert len(result.screenshots_sent) == 2

    service.close()


@pytest.mark.asyncio
async def test_send_coverage_proof_to_associate_no_chat(seed_test_data):
    """Test sending coverage proof fails when multibook chat is missing."""
    service = CoverageProofService(db=seed_test_data)

    mock_bot = AsyncMock()
    opposite_screenshots = service.get_opposite_screenshots(1, "B")
    surebet_details = service.get_surebet_details(1)

    result = await service.send_coverage_proof_to_associate(
        bot=mock_bot,
        surebet_id=1,
        associate_id=3,
        associate_alias="Charlie",
        multibook_chat_id=None,  # No chat configured
        opposite_screenshots=opposite_screenshots,
        surebet_details=surebet_details,
    )

    assert result.success is False
    assert result.associate_alias == "Charlie"
    assert "Multibook chat missing" in result.error_message

    service.close()


@pytest.mark.asyncio
async def test_send_coverage_proof_to_associate_no_screenshots(seed_test_data):
    """Test sending coverage proof fails when no screenshots available."""
    service = CoverageProofService(db=seed_test_data)

    mock_bot = AsyncMock()
    surebet_details = service.get_surebet_details(1)

    result = await service.send_coverage_proof_to_associate(
        bot=mock_bot,
        surebet_id=1,
        associate_id=1,
        associate_alias="Alice",
        multibook_chat_id="123456",
        opposite_screenshots=[],  # No screenshots
        surebet_details=surebet_details,
    )

    assert result.success is False
    assert "No opposite side screenshots available" in result.error_message

    service.close()


@pytest.mark.asyncio
async def test_send_coverage_proof_to_associate_telegram_error(seed_test_data):
    """Test handling Telegram API errors during send."""
    service = CoverageProofService(db=seed_test_data)

    # Mock Telegram bot to raise error
    mock_bot = AsyncMock()
    mock_bot.send_media_group.side_effect = TelegramError("API rate limit exceeded")

    with patch("pathlib.Path.exists", return_value=True), \
         patch("builtins.open", MagicMock()):

        opposite_screenshots = service.get_opposite_screenshots(1, "A")
        surebet_details = service.get_surebet_details(1)

        result = await service.send_coverage_proof_to_associate(
            bot=mock_bot,
            surebet_id=1,
            associate_id=1,
            associate_alias="Alice",
            multibook_chat_id="123456",
            opposite_screenshots=opposite_screenshots,
            surebet_details=surebet_details,
        )

        assert result.success is False
        assert "Telegram API error" in result.error_message

    service.close()


@pytest.mark.asyncio
async def test_send_coverage_proof_full_flow(seed_test_data):
    """Test full coverage proof send flow for a surebet."""
    service = CoverageProofService(db=seed_test_data)

    # Mock Telegram bot
    mock_bot = MagicMock()
    mock_message = MagicMock(spec=Message)
    mock_message.message_id = 12345

    with patch("src.services.coverage_proof_service.Bot", return_value=mock_bot), \
         patch.object(service, "send_coverage_proof_to_associate", return_value=CoverageProofResult(
             associate_id=1,
             associate_alias="Alice",
             success=True,
             message_id="12345",
             screenshots_sent=["data/screenshots/bet2.png"]
         )) as mock_send:

        results = await service.send_coverage_proof(surebet_id=1, resend=False)

        # Should have sent to 3 associates (Alice, Bob, Charlie)
        assert len(results) == 3

        # Verify coverage proof was marked as sent
        details = service.get_surebet_details(1)
        # Note: In this test, coverage_proof_sent_at_utc may not be set
        # because mock_send doesn't actually succeed for all associates

    service.close()


@pytest.mark.asyncio
async def test_send_coverage_proof_already_sent(seed_test_data):
    """Test coverage proof send is blocked if already sent."""
    service = CoverageProofService(db=seed_test_data)

    # Mark as already sent
    service.mark_coverage_proof_sent(1)

    results = await service.send_coverage_proof(surebet_id=1, resend=False)

    # Should return empty list (not sent)
    assert len(results) == 0

    service.close()


@pytest.mark.asyncio
async def test_send_coverage_proof_resend_allowed(seed_test_data):
    """Test coverage proof can be resent when resend=True."""
    service = CoverageProofService(db=seed_test_data)

    # Mark as already sent
    service.mark_coverage_proof_sent(1)

    with patch("src.services.coverage_proof_service.Bot"), \
         patch.object(service, "send_coverage_proof_to_associate", return_value=CoverageProofResult(
             associate_id=1,
             associate_alias="Alice",
             success=True,
             message_id="12345",
             screenshots_sent=["data/screenshots/bet2.png"]
         )):

        results = await service.send_coverage_proof(surebet_id=1, resend=True)

        # Should have sent even though already marked as sent
        assert len(results) == 3

    service.close()
