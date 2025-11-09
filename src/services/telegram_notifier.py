"""
Lightweight helper for sending Telegram notifications from the UI layers.

Designed for Story 9.2 so Streamlit operators can optionally confirm
funding approvals back to the originating chat.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from typing import Optional

from telegram import Bot
from telegram.error import TelegramError

from src.core.config import Config
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


class TelegramNotificationError(Exception):
    """Raised when notifications cannot be delivered (configuration or API error)."""

    pass


@dataclass(frozen=True)
class TelegramNotificationResult:
    """Result metadata for a Telegram notification attempt."""

    success: bool
    message_id: Optional[str] = None
    error_message: Optional[str] = None


class TelegramNotifier:
    """Minimal wrapper around python-telegram-bot for one-off text notifications."""

    def __init__(self, bot: Optional[Bot] = None) -> None:
        token = Config.TELEGRAM_BOT_TOKEN
        if not token:
            raise TelegramNotificationError("TELEGRAM_BOT_TOKEN not configured")
        self._bot = bot or Bot(token=token)
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()

    def send_plaintext(self, chat_id: str, text: str) -> TelegramNotificationResult:
        """
        Send a plaintext message to the provided chat_id.

        Args:
            chat_id: Telegram chat ID (string form is safest for large IDs)
            text: Message body
        """
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._bot.send_message(chat_id=chat_id, text=text), self._loop
            )
            response = future.result()
            message_id = getattr(response, "message_id", None)
        except TelegramError as exc:
            error_message = str(exc)
            logger.error(
                "telegram_notify_plaintext_failed",
                chat_id=chat_id,
                error=error_message,
                exc_info=True,
            )
            return TelegramNotificationResult(
                success=False,
                error_message=error_message,
            )
        except Exception as exc:  # pragma: no cover - defensive guardrail
            error_message = str(exc)
            logger.error(
                "telegram_notify_plaintext_failed",
                chat_id=chat_id,
                error=error_message,
                exc_info=True,
            )
            return TelegramNotificationResult(
                success=False,
                error_message=error_message,
            )

        logger.info(
            "telegram_notify_plaintext_sent",
            chat_id=chat_id,
            message_id=message_id,
        )
        return TelegramNotificationResult(
            success=True,
            message_id=str(message_id) if message_id is not None else None,
        )

    def close(self) -> None:
        """Shut down the notifier event loop."""
        try:
            if self._loop.is_running():
                self._loop.call_soon_threadsafe(self._loop.stop)
            if self._thread.is_alive():
                self._thread.join(timeout=2)
        finally:
            self._loop.close()


__all__ = [
    "TelegramNotificationError",
    "TelegramNotificationResult",
    "TelegramNotifier",
]
