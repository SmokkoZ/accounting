"""
Coverage Proof Service for Manual Coverage Proof Distribution.

This module handles:
- Querying opposite side bet screenshots for coverage proof
- Sending coverage proof messages to associates' multibook chats
- Tracking coverage proof delivery status
- Rate limiting Telegram API calls
"""

import asyncio
import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from telegram import Bot
from telegram.error import TelegramError

from src.core.config import Config
from src.core.database import get_db_connection
from src.utils.datetime_helpers import utc_now_iso
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class CoverageProofResult:
    """Result of coverage proof distribution for a single associate."""

    associate_id: int
    associate_alias: str
    success: bool
    message_id: Optional[str] = None
    error_message: Optional[str] = None
    screenshots_sent: Optional[List[str]] = None


class CoverageProofService:
    """Service for sending coverage proof to associates via Telegram."""

    # Rate limiting: 10 messages per minute per chat (Telegram API limit)
    RATE_LIMIT_MESSAGES_PER_MINUTE = 10
    RATE_LIMIT_WINDOW_SECONDS = 60

    def __init__(self, db: Optional[sqlite3.Connection] = None):
        """
        Initialize the Coverage Proof Service.

        Args:
            db: Optional database connection. If not provided, creates a new connection.
        """
        self.db = db or get_db_connection()
        self._owns_connection = db is None

        # Rate limiting tracking: {chat_id: [(timestamp, message_count), ...]}
        self._rate_limit_tracker: Dict[str, List[Tuple[float, int]]] = {}

    def close(self) -> None:
        """Close database connection if owned by this service."""
        if self._owns_connection and self.db:
            self.db.close()

    def get_opposite_screenshots(
        self, surebet_id: int, side: str
    ) -> List[Dict[str, str]]:
        """
        Query all screenshots for the opposite side of a surebet.

        Args:
            surebet_id: ID of the surebet
            side: The side for which to get opposite screenshots ("A" or "B")

        Returns:
            List of dictionaries containing screenshot paths and bet details
        """
        opposite_side = "B" if side == "A" else "A"

        query = """
            SELECT
                b.id as bet_id,
                b.screenshot_path,
                b.associate_id,
                a.display_alias as associate_alias,
                bk.bookmaker_name,
                b.stake_original,
                b.odds_original,
                b.currency
            FROM bets b
            JOIN surebet_bets sb ON b.id = sb.bet_id
            JOIN associates a ON b.associate_id = a.id
            JOIN bookmakers bk ON b.bookmaker_id = bk.id
            WHERE sb.surebet_id = ?
                AND sb.side = ?
                AND b.screenshot_path IS NOT NULL
            ORDER BY b.associate_id
        """

        rows = self.db.execute(query, (surebet_id, opposite_side)).fetchall()
        return [dict(row) for row in rows]

    def get_surebet_associates_by_side(
        self, surebet_id: int
    ) -> Dict[str, List[Dict[str, any]]]:
        """
        Get all associates participating in a surebet, grouped by side.

        Args:
            surebet_id: ID of the surebet

        Returns:
            Dictionary with keys "A" and "B", each containing list of associate details
        """
        query = """
            SELECT DISTINCT
                sb.side,
                a.id as associate_id,
                a.display_alias as associate_alias,
                a.multibook_chat_id
            FROM surebet_bets sb
            JOIN bets b ON sb.bet_id = b.id
            JOIN associates a ON b.associate_id = a.id
            WHERE sb.surebet_id = ?
            ORDER BY sb.side, a.display_alias
        """

        rows = self.db.execute(query, (surebet_id,)).fetchall()
        associates = {"A": [], "B": []}

        for row in rows:
            side = row["side"]
            associates[side].append(
                {
                    "associate_id": row["associate_id"],
                    "associate_alias": row["associate_alias"],
                    "multibook_chat_id": row["multibook_chat_id"],
                }
            )

        return associates

    def get_surebet_details(self, surebet_id: int) -> Optional[Dict]:
        """
        Get surebet details for message formatting.

        Args:
            surebet_id: ID of the surebet

        Returns:
            Dictionary with surebet details or None if not found
        """
        query = """
            SELECT
                s.id,
                s.market_code,
                s.period_scope,
                s.line_value,
                s.status,
                s.coverage_proof_sent_at_utc,
                e.normalized_event_name as event_name
            FROM surebets s
            JOIN canonical_events e ON s.canonical_event_id = e.id
            WHERE s.id = ?
        """

        row = self.db.execute(query, (surebet_id,)).fetchone()
        return dict(row) if row else None

    def _format_coverage_proof_message(
        self, surebet_details: Dict, market_line: str
    ) -> str:
        """
        Format the coverage proof message text.

        Args:
            surebet_details: Surebet details dictionary
            market_line: Formatted market line (e.g., "Over 2.5")

        Returns:
            Formatted message text
        """
        event_name = surebet_details.get("event_name", "Unknown Event")
        return f"You're covered for {event_name} / {market_line}. Opposite side attached."

    def _check_rate_limit(self, chat_id: str) -> Tuple[bool, float]:
        """
        Check if sending to this chat would exceed rate limits.

        Args:
            chat_id: Telegram chat ID

        Returns:
            Tuple of (allowed, wait_seconds)
            - allowed: True if message can be sent now
            - wait_seconds: Seconds to wait before sending (0 if allowed)
        """
        current_time = time.time()
        window_start = current_time - self.RATE_LIMIT_WINDOW_SECONDS

        # Clean up old entries outside the rate limit window
        if chat_id in self._rate_limit_tracker:
            self._rate_limit_tracker[chat_id] = [
                (ts, count)
                for ts, count in self._rate_limit_tracker[chat_id]
                if ts > window_start
            ]

        # Count messages in current window
        message_count = sum(
            count for ts, count in self._rate_limit_tracker.get(chat_id, [])
        )

        if message_count >= self.RATE_LIMIT_MESSAGES_PER_MINUTE:
            # Calculate wait time until oldest message exits the window
            oldest_timestamp = self._rate_limit_tracker[chat_id][0][0]
            wait_seconds = oldest_timestamp + self.RATE_LIMIT_WINDOW_SECONDS - current_time
            return False, max(0, wait_seconds)

        return True, 0.0

    def _record_rate_limit(self, chat_id: str) -> None:
        """
        Record a message send for rate limiting tracking.

        Args:
            chat_id: Telegram chat ID
        """
        current_time = time.time()
        if chat_id not in self._rate_limit_tracker:
            self._rate_limit_tracker[chat_id] = []

        self._rate_limit_tracker[chat_id].append((current_time, 1))

    async def send_coverage_proof_to_associate(
        self,
        bot: Bot,
        surebet_id: int,
        associate_id: int,
        associate_alias: str,
        multibook_chat_id: Optional[str],
        opposite_screenshots: List[Dict],
        surebet_details: Dict,
    ) -> CoverageProofResult:
        """
        Send coverage proof to a single associate.

        Args:
            bot: Telegram bot instance
            surebet_id: ID of the surebet
            associate_id: ID of the associate
            associate_alias: Display alias of the associate
            multibook_chat_id: Telegram chat ID for multibook chat
            opposite_screenshots: List of opposite side screenshots
            surebet_details: Surebet details for message formatting

        Returns:
            CoverageProofResult with send status
        """
        # Validate multibook chat ID exists
        if not multibook_chat_id:
            error_msg = f"Multibook chat missing for {associate_alias}"
            logger.warning(
                "coverage_proof_no_chat",
                surebet_id=surebet_id,
                associate_id=associate_id,
                associate_alias=associate_alias,
            )
            return CoverageProofResult(
                associate_id=associate_id,
                associate_alias=associate_alias,
                success=False,
                error_message=error_msg,
            )

        # Validate screenshots exist
        if not opposite_screenshots:
            error_msg = f"No opposite side screenshots available for {associate_alias}"
            logger.warning(
                "coverage_proof_no_screenshots",
                surebet_id=surebet_id,
                associate_id=associate_id,
            )
            return CoverageProofResult(
                associate_id=associate_id,
                associate_alias=associate_alias,
                success=False,
                error_message=error_msg,
            )

        # Check rate limit
        allowed, wait_seconds = self._check_rate_limit(multibook_chat_id)
        if not allowed:
            logger.warning(
                "coverage_proof_rate_limited",
                chat_id=multibook_chat_id,
                wait_seconds=wait_seconds,
            )
            # Wait until rate limit window clears
            await asyncio.sleep(wait_seconds + 1)

        # Prepare screenshot paths
        screenshot_paths = []
        for screenshot in opposite_screenshots:
            path = screenshot.get("screenshot_path")
            if path:
                screenshot_paths.append(path)

        # Format message text
        market_line = f"{surebet_details.get('market_code', 'Unknown Market')}"
        if surebet_details.get("line_value"):
            market_line += f" {surebet_details['line_value']}"

        message_text = self._format_coverage_proof_message(surebet_details, market_line)

        # Send message with screenshots
        try:
            # Send photos as media group (up to 10 photos per group)
            from telegram import InputMediaPhoto

            media_group = []
            for i, path in enumerate(screenshot_paths[:10]):  # Telegram limit: 10 photos per group
                # Verify file exists
                file_path = Path(path)
                if not file_path.exists():
                    logger.warning(
                        "coverage_proof_screenshot_not_found",
                        path=path,
                        associate_id=associate_id,
                    )
                    continue

                # First photo includes caption
                caption = message_text if i == 0 else None
                media_group.append(InputMediaPhoto(open(file_path, "rb"), caption=caption))

            if not media_group:
                error_msg = "No valid screenshot files found"
                return CoverageProofResult(
                    associate_id=associate_id,
                    associate_alias=associate_alias,
                    success=False,
                    error_message=error_msg,
                )

            # Send media group
            messages = await bot.send_media_group(
                chat_id=int(multibook_chat_id), media=media_group
            )

            # Record rate limit
            self._record_rate_limit(multibook_chat_id)

            # Get first message ID for logging
            message_id = str(messages[0].message_id) if messages else None

            logger.info(
                "coverage_proof_sent",
                surebet_id=surebet_id,
                associate_id=associate_id,
                chat_id=multibook_chat_id,
                message_id=message_id,
                screenshot_count=len(media_group),
            )

            return CoverageProofResult(
                associate_id=associate_id,
                associate_alias=associate_alias,
                success=True,
                message_id=message_id,
                screenshots_sent=screenshot_paths,
            )

        except TelegramError as e:
            error_msg = f"Telegram API error: {str(e)}"
            logger.error(
                "coverage_proof_telegram_error",
                surebet_id=surebet_id,
                associate_id=associate_id,
                chat_id=multibook_chat_id,
                error=str(e),
            )
            return CoverageProofResult(
                associate_id=associate_id,
                associate_alias=associate_alias,
                success=False,
                error_message=error_msg,
            )
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            logger.error(
                "coverage_proof_send_error",
                surebet_id=surebet_id,
                associate_id=associate_id,
                error=str(e),
                exc_info=True,
            )
            return CoverageProofResult(
                associate_id=associate_id,
                associate_alias=associate_alias,
                success=False,
                error_message=error_msg,
            )

    def log_coverage_proof(
        self,
        surebet_id: int,
        associate_id: int,
        message_id: Optional[str],
        screenshots_sent: List[str],
        success: bool,
        error_message: Optional[str] = None,
    ) -> None:
        """
        Log coverage proof delivery to multibook_message_log table.

        Args:
            surebet_id: ID of the surebet
            associate_id: ID of the associate
            message_id: Telegram message ID (None if failed)
            screenshots_sent: List of screenshot paths sent
            success: Whether the send was successful
            error_message: Error message if failed
        """
        delivery_status = "sent" if success else "failed"
        sent_at_utc = utc_now_iso() if success else None

        try:
            self.db.execute(
                """
                INSERT INTO multibook_message_log (
                    surebet_id,
                    associate_id,
                    message_type,
                    delivery_status,
                    message_id,
                    error_message,
                    sent_at_utc,
                    created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    surebet_id,
                    associate_id,
                    "COVERAGE_PROOF",
                    delivery_status,
                    message_id,
                    error_message,
                    sent_at_utc,
                    utc_now_iso(),
                ),
            )
            self.db.commit()

            logger.info(
                "coverage_proof_logged",
                surebet_id=surebet_id,
                associate_id=associate_id,
                delivery_status=delivery_status,
            )

        except Exception as e:
            logger.error(
                "coverage_proof_log_error",
                surebet_id=surebet_id,
                associate_id=associate_id,
                error=str(e),
                exc_info=True,
            )

    def mark_coverage_proof_sent(self, surebet_id: int) -> None:
        """
        Mark surebet as having coverage proof sent.

        Args:
            surebet_id: ID of the surebet
        """
        try:
            self.db.execute(
                """
                UPDATE surebets
                SET coverage_proof_sent_at_utc = ?,
                    updated_at_utc = ?
                WHERE id = ?
                """,
                (utc_now_iso(), utc_now_iso(), surebet_id),
            )
            self.db.commit()

            logger.info("surebet_coverage_proof_marked", surebet_id=surebet_id)

        except Exception as e:
            logger.error(
                "mark_coverage_proof_error",
                surebet_id=surebet_id,
                error=str(e),
                exc_info=True,
            )

    async def send_coverage_proof(
        self, surebet_id: int, resend: bool = False
    ) -> List[CoverageProofResult]:
        """
        Send coverage proof to all associates in a surebet.

        Args:
            surebet_id: ID of the surebet
            resend: Whether this is a resend (ignore coverage_proof_sent_at_utc check)

        Returns:
            List of CoverageProofResult for each associate
        """
        # Get surebet details
        surebet_details = self.get_surebet_details(surebet_id)
        if not surebet_details:
            logger.error("coverage_proof_surebet_not_found", surebet_id=surebet_id)
            return []

        # Check if surebet is open
        if surebet_details["status"] != "open":
            logger.warning(
                "coverage_proof_surebet_not_open",
                surebet_id=surebet_id,
                status=surebet_details["status"],
            )
            return []

        # Check if already sent (unless resending)
        if not resend and surebet_details.get("coverage_proof_sent_at_utc"):
            logger.warning(
                "coverage_proof_already_sent",
                surebet_id=surebet_id,
                sent_at=surebet_details["coverage_proof_sent_at_utc"],
            )
            return []

        # Get associates by side
        associates_by_side = self.get_surebet_associates_by_side(surebet_id)

        # Initialize Telegram bot
        if not Config.TELEGRAM_BOT_TOKEN:
            logger.error("coverage_proof_no_bot_token")
            return []

        bot = Bot(token=Config.TELEGRAM_BOT_TOKEN)

        results = []

        # Send to Side A associates (opposite side screenshots = Side B)
        for associate in associates_by_side["A"]:
            opposite_screenshots = self.get_opposite_screenshots(surebet_id, "A")
            result = await self.send_coverage_proof_to_associate(
                bot,
                surebet_id,
                associate["associate_id"],
                associate["associate_alias"],
                associate["multibook_chat_id"],
                opposite_screenshots,
                surebet_details,
            )
            results.append(result)

            # Log to database
            self.log_coverage_proof(
                surebet_id,
                result.associate_id,
                result.message_id,
                result.screenshots_sent or [],
                result.success,
                result.error_message,
            )

        # Send to Side B associates (opposite side screenshots = Side A)
        for associate in associates_by_side["B"]:
            opposite_screenshots = self.get_opposite_screenshots(surebet_id, "B")
            result = await self.send_coverage_proof_to_associate(
                bot,
                surebet_id,
                associate["associate_id"],
                associate["associate_alias"],
                associate["multibook_chat_id"],
                opposite_screenshots,
                surebet_details,
            )
            results.append(result)

            # Log to database
            self.log_coverage_proof(
                surebet_id,
                result.associate_id,
                result.message_id,
                result.screenshots_sent or [],
                result.success,
                result.error_message,
            )

        # Mark surebet as having coverage proof sent if all successful
        if all(result.success for result in results):
            self.mark_coverage_proof_sent(surebet_id)

        return results
