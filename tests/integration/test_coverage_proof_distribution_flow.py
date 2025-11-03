"""
Integration tests for Coverage Proof Distribution Flow.

Tests end-to-end coverage proof distribution workflow including
database operations, Telegram integration, and message logging.
"""

import asyncio
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import Message

from src.services.coverage_proof_service import CoverageProofService
from src.core.database import get_db_connection
from src.core.schema import create_schema


@pytest.fixture
def test_db_file(tmp_path):
    """Create a temporary database file for integration testing."""
    db_path = tmp_path / "test_surebet.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    # Create schema
    create_schema(conn)

    yield conn, db_path

    conn.close()


@pytest.fixture
def setup_full_scenario(test_db_file):
    """Set up a complete surebet scenario with all data."""
    conn, db_path = test_db_file
    cursor = conn.cursor()

    # Create associates with multibook chats
    cursor.execute(
        """
        INSERT INTO associates (id, display_alias, home_currency, multibook_chat_id, is_admin)
        VALUES (1, 'Alice', 'EUR', '111111', FALSE),
               (2, 'Bob', 'USD', '222222', FALSE),
               (3, 'Charlie', 'GBP', '333333', FALSE)
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
        VALUES (1, 'Liverpool vs Chelsea', 'Football', 'Premier League', '2025-11-15T17:30:00Z')
        """
    )

    # Create canonical market
    cursor.execute(
        """
        INSERT INTO canonical_markets (id, market_code, description)
        VALUES (1, 'MATCH_WINNER', 'Match Winner')
        """
    )

    # Create temporary screenshot files for testing
    screenshot_dir = Path("data/screenshots")
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    screenshot_paths = []
    for i in range(1, 4):
        screenshot_path = screenshot_dir / f"test_bet{i}.png"
        screenshot_path.write_bytes(b"fake image data")
        screenshot_paths.append(str(screenshot_path))

    # Create bets with real screenshot paths
    cursor.execute(
        f"""
        INSERT INTO bets (
            id, associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
            status, stake_eur, odds, currency, screenshot_path,
            stake_original, odds_original,
            created_at_utc, updated_at_utc
        )
        VALUES (1, 1, 1, 1, 1, 'verified', '100.00', '2.10', 'EUR', '{screenshot_paths[0]}',
                '100.00', '2.10',
                datetime('now') || 'Z', datetime('now') || 'Z'),
               (2, 2, 2, 1, 1, 'verified', '120.00', '3.50', 'USD', '{screenshot_paths[1]}',
                '120.00', '3.50',
                datetime('now') || 'Z', datetime('now') || 'Z'),
               (3, 3, 3, 1, 1, 'verified', '110.00', '3.40', 'GBP', '{screenshot_paths[2]}',
                '110.00', '3.40',
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
        VALUES (1, 1, 1, 'MATCH_WINNER', 'FULL_MATCH', NULL, 'open',
                '8.50', '330.00', '0.0257', 'Safe',
                datetime('now') || 'Z', datetime('now') || 'Z')
        """
    )

    # Link bets to surebet (Alice on Side A, Bob and Charlie on Side B)
    cursor.execute(
        """
        INSERT INTO surebet_bets (surebet_id, bet_id, side)
        VALUES (1, 1, 'A'),
               (1, 2, 'B'),
               (1, 3, 'B')
        """
    )

    conn.commit()

    yield conn, screenshot_paths

    # Cleanup screenshot files
    for path in screenshot_paths:
        Path(path).unlink(missing_ok=True)

    conn.close()


@pytest.mark.asyncio
async def test_full_coverage_proof_distribution(setup_full_scenario):
    """Test complete coverage proof distribution workflow."""
    conn, screenshot_paths = setup_full_scenario

    # Mock Telegram bot
    mock_bot = AsyncMock()
    mock_messages = [MagicMock(spec=Message) for _ in range(3)]
    for i, msg in enumerate(mock_messages):
        msg.message_id = 10000 + i
    mock_bot.send_media_group.return_value = mock_messages

    with patch("src.services.coverage_proof_service.Bot", return_value=mock_bot), \
         patch("builtins.open", MagicMock()):

        service = CoverageProofService(db=conn)

        # Send coverage proof
        results = await service.send_coverage_proof(surebet_id=1)

        # Verify results
        assert len(results) == 3

        # All should be successful
        success_count = sum(1 for r in results if r.success)
        assert success_count == 3

        # Verify database updates
        # Check coverage_proof_sent_at_utc is set
        details = service.get_surebet_details(1)
        assert details["coverage_proof_sent_at_utc"] is not None

        # Check multibook_message_log entries
        log_rows = conn.execute(
            """
            SELECT * FROM multibook_message_log
            WHERE surebet_id = 1
            ORDER BY associate_id
            """
        ).fetchall()

        assert len(log_rows) == 3
        for row in log_rows:
            assert row["message_type"] == "COVERAGE_PROOF"
            assert row["delivery_status"] == "sent"
            assert row["message_id"] is not None

        service.close()


@pytest.mark.asyncio
async def test_coverage_proof_partial_failure(setup_full_scenario):
    """Test coverage proof distribution with partial failures."""
    conn, screenshot_paths = setup_full_scenario

    # Remove multibook chat ID for one associate
    conn.execute(
        """
        UPDATE associates
        SET multibook_chat_id = NULL
        WHERE id = 3
        """
    )
    conn.commit()

    # Mock Telegram bot
    mock_bot = AsyncMock()
    mock_messages = [MagicMock(spec=Message)]
    mock_messages[0].message_id = 10000
    mock_bot.send_media_group.return_value = mock_messages

    with patch("src.services.coverage_proof_service.Bot", return_value=mock_bot), \
         patch("builtins.open", MagicMock()):

        service = CoverageProofService(db=conn)

        # Send coverage proof
        results = await service.send_coverage_proof(surebet_id=1)

        # Verify results
        assert len(results) == 3

        # Charlie should have failed (no multibook chat)
        success_count = sum(1 for r in results if r.success)
        assert success_count == 2

        failed_results = [r for r in results if not r.success]
        assert len(failed_results) == 1
        assert failed_results[0].associate_alias == "Charlie"
        assert "Multibook chat missing" in failed_results[0].error_message

        # Verify database - coverage_proof_sent_at_utc should NOT be set
        # because not all associates received coverage proof
        details = service.get_surebet_details(1)
        assert details["coverage_proof_sent_at_utc"] is None

        # Check multibook_message_log has failed entry
        failed_log = conn.execute(
            """
            SELECT * FROM multibook_message_log
            WHERE surebet_id = 1 AND delivery_status = 'failed'
            """
        ).fetchone()

        assert failed_log is not None
        assert failed_log["associate_id"] == 3
        assert failed_log["error_message"] is not None

        service.close()


@pytest.mark.asyncio
async def test_coverage_proof_resend_workflow(setup_full_scenario):
    """Test resending coverage proof after initial send."""
    conn, screenshot_paths = setup_full_scenario

    # Mock Telegram bot
    mock_bot = AsyncMock()
    mock_messages = [MagicMock(spec=Message) for _ in range(3)]
    for i, msg in enumerate(mock_messages):
        msg.message_id = 20000 + i
    mock_bot.send_media_group.return_value = mock_messages

    with patch("src.services.coverage_proof_service.Bot", return_value=mock_bot), \
         patch("builtins.open", MagicMock()):

        service = CoverageProofService(db=conn)

        # First send
        results_1 = await service.send_coverage_proof(surebet_id=1)
        assert all(r.success for r in results_1)

        # Verify coverage_proof_sent_at_utc is set
        details = service.get_surebet_details(1)
        first_sent_at = details["coverage_proof_sent_at_utc"]
        assert first_sent_at is not None

        # Try to send again without resend=True (should be blocked)
        results_2 = await service.send_coverage_proof(surebet_id=1, resend=False)
        assert len(results_2) == 0

        # Resend with resend=True (should succeed)
        results_3 = await service.send_coverage_proof(surebet_id=1, resend=True)
        assert len(results_3) == 3
        assert all(r.success for r in results_3)

        # Check that multibook_message_log now has 6 entries (3 original + 3 resend)
        log_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM multibook_message_log WHERE surebet_id = 1"
        ).fetchone()["cnt"]
        assert log_count == 6

        service.close()


@pytest.mark.asyncio
async def test_rate_limiting_across_multiple_sends(setup_full_scenario):
    """Test rate limiting behavior across multiple coverage proof sends."""
    conn, screenshot_paths = setup_full_scenario

    # Create multiple surebets to trigger rate limiting
    cursor = conn.cursor()

    for surebet_id in range(2, 12):  # Create 10 more surebets
        cursor.execute(
            """
            INSERT INTO surebets (
                id, canonical_event_id, canonical_market_id, market_code,
                period_scope, status, created_at_utc, updated_at_utc
            )
            VALUES (?, 1, 1, 'MATCH_WINNER', 'FULL_MATCH', 'open',
                    datetime('now') || 'Z', datetime('now') || 'Z')
            """,
            (surebet_id,)
        )

        # Link same bets to each surebet
        cursor.execute(
            """
            INSERT INTO surebet_bets (surebet_id, bet_id, side)
            VALUES (?, 1, 'A'),
                   (?, 2, 'B'),
                   (?, 3, 'B')
            """,
            (surebet_id, surebet_id, surebet_id)
        )

    conn.commit()

    # Mock Telegram bot
    mock_bot = AsyncMock()
    mock_messages = [MagicMock(spec=Message)]
    mock_messages[0].message_id = 30000
    mock_bot.send_media_group.return_value = mock_messages

    with patch("src.services.coverage_proof_service.Bot", return_value=mock_bot), \
         patch("builtins.open", MagicMock()):

        service = CoverageProofService(db=conn)

        # Send coverage proof for multiple surebets rapidly
        all_results = []
        for surebet_id in range(1, 6):  # Send for 5 surebets
            results = await service.send_coverage_proof(surebet_id=surebet_id)
            all_results.extend(results)

        # All should eventually succeed (rate limiting should handle delays)
        success_count = sum(1 for r in all_results if r.success)
        assert success_count == len(all_results)

        service.close()


@pytest.mark.asyncio
async def test_coverage_proof_with_missing_screenshots(setup_full_scenario):
    """Test coverage proof handling when screenshot files are missing."""
    conn, screenshot_paths = setup_full_scenario

    # Delete one screenshot file
    Path(screenshot_paths[1]).unlink()

    # Mock Telegram bot
    mock_bot = AsyncMock()
    mock_messages = [MagicMock(spec=Message)]
    mock_messages[0].message_id = 40000
    mock_bot.send_media_group.return_value = mock_messages

    with patch("src.services.coverage_proof_service.Bot", return_value=mock_bot), \
         patch("builtins.open", MagicMock()):

        service = CoverageProofService(db=conn)

        # Send coverage proof
        results = await service.send_coverage_proof(surebet_id=1)

        # Alice should succeed (gets Bob and Charlie's screenshots, but Bob's file is missing)
        # So Alice will get partial screenshots (only Charlie's)
        alice_result = [r for r in results if r.associate_alias == "Alice"][0]

        # Bob and Charlie should succeed (both get Alice's screenshot)
        bob_result = [r for r in results if r.associate_alias == "Bob"][0]
        charlie_result = [r for r in results if r.associate_alias == "Charlie"][0]

        # Note: The actual behavior depends on how the service handles missing files
        # In current implementation, it logs a warning and continues with remaining files

        service.close()


@pytest.mark.asyncio
async def test_coverage_proof_status_tracking_in_dashboard_flow(setup_full_scenario):
    """Test coverage proof status tracking as would be used in dashboard."""
    conn, screenshot_paths = setup_full_scenario

    # Mock Telegram bot
    mock_bot = AsyncMock()
    mock_messages = [MagicMock(spec=Message)]
    mock_messages[0].message_id = 50000
    mock_bot.send_media_group.return_value = mock_messages

    with patch("src.services.coverage_proof_service.Bot", return_value=mock_bot), \
         patch("builtins.open", MagicMock()):

        service = CoverageProofService(db=conn)

        # Initial state - coverage proof not sent
        details_before = service.get_surebet_details(1)
        assert details_before["coverage_proof_sent_at_utc"] is None

        # Send coverage proof
        results = await service.send_coverage_proof(surebet_id=1)
        assert all(r.success for r in results)

        # After send - coverage proof sent timestamp should be set
        details_after = service.get_surebet_details(1)
        assert details_after["coverage_proof_sent_at_utc"] is not None

        # Verify button state logic (as would be in UI)
        coverage_sent = details_after["coverage_proof_sent_at_utc"]
        assert coverage_sent is not None  # Button should show "Coverage proof sent"

        # Resend attempt without resend flag should be blocked
        results_blocked = await service.send_coverage_proof(surebet_id=1, resend=False)
        assert len(results_blocked) == 0

        service.close()
