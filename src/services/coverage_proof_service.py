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
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from telegram import Bot
from telegram.error import TelegramError

from src.core.config import Config
from src.core.database import get_db_connection
from src.services.rate_limit_settings import (
    ChatRateLimitSettings,
    RateLimitSettingsStore,
)
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
    OUTBOX_DEFAULT_LIMIT = 200
    DEFAULT_CHAT_RATE_LIMITS: List[ChatRateLimitSettings] = [
        ChatRateLimitSettings(
            chat_id="__default__",
            label="All multibook chats",
            messages_per_interval=10,
            interval_seconds=60,
            burst_allowance=2,
        ),
        ChatRateLimitSettings(
            chat_id="-1002003004001",
            label="Ops Primary Multibook",
            messages_per_interval=8,
            interval_seconds=60,
            burst_allowance=2,
        ),
        ChatRateLimitSettings(
            chat_id="-1002003004002",
            label="VIP Multibook Escalations",
            messages_per_interval=5,
            interval_seconds=60,
            burst_allowance=1,
        ),
    ]

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
        self._rate_limit_store = RateLimitSettingsStore()
        self._rate_limit_profiles: "OrderedDict[str, ChatRateLimitSettings]" = (
            self._rate_limit_store.load(self.DEFAULT_CHAT_RATE_LIMITS)
        )
        self._rate_limit_profiles_version = self._rate_limit_store.current_version()

    def close(self) -> None:
        """Close database connection if owned by this service."""
        if self._owns_connection and self.db:
            self.db.close()

    def _ensure_rate_limit_profiles_current(self) -> None:
        """Reload operator overrides if the backing file changed."""
        current_version = self._rate_limit_store.current_version()
        if current_version != self._rate_limit_profiles_version:
            self._rate_limit_profiles = self._rate_limit_store.load(
                self.DEFAULT_CHAT_RATE_LIMITS
            )
            self._rate_limit_profiles_version = current_version

    def _get_chat_rate_limit_settings(
        self, chat_id: Optional[str]
    ) -> ChatRateLimitSettings:
        """Return the configured profile for a chat or fall back to defaults."""
        self._ensure_rate_limit_profiles_current()
        if chat_id and chat_id in self._rate_limit_profiles:
            return self._rate_limit_profiles[chat_id]
        if "__default__" in self._rate_limit_profiles:
            return self._rate_limit_profiles["__default__"]
        # As a final fallback return the first configured profile.
        return next(iter(self._rate_limit_profiles.values()))

    def get_rate_limit_profiles(self) -> List[ChatRateLimitSettings]:
        """Expose the hydrated profiles for UI surfaces."""
        self._ensure_rate_limit_profiles_current()
        return list(self._rate_limit_profiles.values())

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

    @staticmethod
    def _parse_iso_timestamp(value: Optional[str]) -> Optional[datetime]:
        """Parse ISO8601 timestamp strings that may end with Z."""
        if not value:
            return None
        cleaned = value.replace(" ", "T")
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(cleaned)
        except ValueError:
            return None

    @staticmethod
    def _format_utc(dt: Optional[datetime]) -> Optional[str]:
        """Return ISO string with Z suffix for UTC datetimes."""
        if not dt:
            return None
        return (
            dt.astimezone(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )

    def _get_chat_cooldowns(
        self, chat_ids: Optional[List[str]] = None
    ) -> Dict[str, Dict[str, Any]]:
        """
        Calculate remaining cooldown per chat based on recent log activity.

        Args:
            chat_ids: Optional filter of chat IDs to include.

        Returns:
            Dict keyed by chat ID containing seconds_remaining and attempt_count.
        """
        if chat_ids is not None and not chat_ids:
            return {}

        profiles = self.get_rate_limit_profiles()
        longest_window = max(
            (profile.interval_seconds for profile in profiles),
            default=self.RATE_LIMIT_WINDOW_SECONDS,
        )
        window_start = datetime.now(timezone.utc) - timedelta(seconds=longest_window)
        window_start_iso = self._format_utc(window_start)

        params: List[Any] = []
        chat_filter = ""
        if chat_ids:
            placeholders = ",".join("?" for _ in chat_ids)
            chat_filter = f"AND assoc.multibook_chat_id IN ({placeholders})"
            params.extend(chat_ids)

        params.append(window_start_iso)

        query = f"""
            SELECT
                assoc.multibook_chat_id AS chat_id,
                COALESCE(log.sent_at_utc, log.created_at_utc) AS attempt_at
            FROM multibook_message_log log
            JOIN associates assoc ON assoc.id = log.associate_id
            WHERE
                log.message_type = 'COVERAGE_PROOF'
                AND assoc.multibook_chat_id IS NOT NULL
                {chat_filter}
                AND COALESCE(log.sent_at_utc, log.created_at_utc) >= ?
        """

        attempt_map: Dict[str, List[datetime]] = {}
        cooldowns: Dict[str, Dict[str, Any]] = {}
        now = datetime.now(timezone.utc)
        for row in self.db.execute(query, params).fetchall():
            chat_id = row["chat_id"]
            attempt_at = self._parse_iso_timestamp(row["attempt_at"])
            if not chat_id or attempt_at is None:
                continue
            attempt_map.setdefault(chat_id, []).append(attempt_at)

        for chat_id, attempts in attempt_map.items():
            settings = self._get_chat_rate_limit_settings(chat_id)
            window_seconds = settings.interval_seconds
            cutoff = now - timedelta(seconds=window_seconds)
            recent_attempts = [ts for ts in attempts if ts >= cutoff]
            attempt_count = len(recent_attempts)
            seconds_remaining = 0
            if attempt_count >= settings.total_allowed and recent_attempts:
                oldest_dt = min(recent_attempts)
                elapsed = (now - oldest_dt).total_seconds()
                seconds_remaining = max(0, int(window_seconds - elapsed))

            cooldowns[chat_id] = {
                "seconds_remaining": seconds_remaining,
                "attempt_count": attempt_count,
            }

        return cooldowns

    def get_rate_limit_cooldowns(
        self, chat_ids: Optional[List[str]] = None
    ) -> Dict[str, Dict[str, Any]]:
        """
        Public helper exposing cooldown metrics for dashboards/monitoring.

        Args:
            chat_ids: Optional list of Telegram chat IDs to scope results.

        Returns:
            Dict keyed by chat ID describing attempt counts and cooldown status.
        """
        return self._get_chat_cooldowns(chat_ids)

    def get_outbox_entries(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Return recent coverage proof delivery attempts for operator outbox views.

        Args:
            limit: Optional limit override (defaults to OUTBOX_DEFAULT_LIMIT).

        Returns:
            List of dictionaries describing each delivery attempt.
        """
        effective_limit = limit or self.OUTBOX_DEFAULT_LIMIT
        query = """
            SELECT
                log.id,
                log.surebet_id,
                log.associate_id,
                assoc.display_alias AS associate_alias,
                assoc.multibook_chat_id AS chat_id,
                log.message_id,
                log.delivery_status,
                log.error_message,
                log.sent_at_utc,
                log.created_at_utc
            FROM multibook_message_log log
            JOIN associates assoc ON assoc.id = log.associate_id
            WHERE log.message_type = 'COVERAGE_PROOF'
            ORDER BY log.created_at_utc DESC
            LIMIT ?
        """
        rows = self.db.execute(query, (effective_limit,)).fetchall()

        chat_ids = [row["chat_id"] for row in rows if row["chat_id"]]
        cooldowns = self._get_chat_cooldowns(chat_ids)

        now = datetime.now(timezone.utc)
        entries: List[Dict[str, Any]] = []
        for row in rows:
            chat_id = row["chat_id"]
            last_attempt = row["sent_at_utc"] or row["created_at_utc"]
            cooldown_state = cooldowns.get(chat_id, {"seconds_remaining": 0})
            seconds_until_next = cooldown_state.get("seconds_remaining", 0)
            rate_limit_health = (
                "blocked"
                if seconds_until_next > 0
                else "queued"
                if row["delivery_status"] == "pending"
                else "ready"
            )
            cooldown_expires_at = (
                self._format_utc(now + timedelta(seconds=seconds_until_next))
                if seconds_until_next
                else None
            )
            entries.append(
                {
                    "log_id": row["id"],
                    "surebet_id": row["surebet_id"],
                    "associate_id": row["associate_id"],
                    "associate_alias": row["associate_alias"],
                    "chat_id": chat_id,
                    "message_id": row["message_id"],
                    "status": row["delivery_status"],
                    "error_message": row["error_message"],
                    "last_attempt": last_attempt,
                    "seconds_until_next_send": seconds_until_next,
                    "cooldown_expires_at": cooldown_expires_at,
                    "rate_limit_health": rate_limit_health,
                }
            )

        logger.info(
            "coverage_proof_outbox_scrape",
            entry_count=len(entries),
            limit=effective_limit,
        )
        return entries

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
        settings = self._get_chat_rate_limit_settings(chat_id)
        window_seconds = settings.interval_seconds
        allowed_messages = settings.total_allowed
        window_start = current_time - window_seconds

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

        if message_count >= allowed_messages and self._rate_limit_tracker.get(chat_id):
            # Calculate wait time until oldest message exits the window
            oldest_timestamp = self._rate_limit_tracker[chat_id][0][0]
            wait_seconds = oldest_timestamp + window_seconds - current_time
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

    async def send(
        self, surebet_id: int, *, resend: bool = False
    ) -> List[CoverageProofResult]:
        """
        Wrapper to maintain a concise API name for UI callers.

        Args:
            surebet_id: Target surebet identifier.
            resend: Whether to bypass previous send guards.
        """
        return await self.send_coverage_proof(surebet_id, resend=resend)
