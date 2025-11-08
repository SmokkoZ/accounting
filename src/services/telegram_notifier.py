"""
Lightweight helper for sending Telegram notifications from the UI layers.

Designed for Story 9.2 so Streamlit operators can optionally confirm
funding approvals back to the originating chat.
"""

from __future__ import annotations

import asyncio
import inspect
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

    def send_plaintext(self, chat_id: str, text: str) -> TelegramNotificationResult:
        """
        Send a plaintext message to the provided chat_id.

        Args:
            chat_id: Telegram chat ID (string form is safest for large IDs)
            text: Message body
        """
        try:
            response = self._bot.send_message(chat_id=chat_id, text=text)
            if inspect.isawaitable(response):
                response = self._await_result(response)
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

        logger.info(
            "telegram_notify_plaintext_sent",
            chat_id=chat_id,
            message_id=message_id,
        )
        return TelegramNotificationResult(
            success=True,
            message_id=str(message_id) if message_id is not None else None,
        )

    @staticmethod
    def _await_result(coro):
        """Run an async telegram call in a synchronous context."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            new_loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(new_loop)
                return new_loop.run_until_complete(coro)
            finally:
                asyncio.set_event_loop(None)
                new_loop.close()

        return asyncio.run(coro)


__all__ = [
    "TelegramNotificationError",
    "TelegramNotificationResult",
    "TelegramNotifier",
]
