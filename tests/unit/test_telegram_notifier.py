"""
Unit tests for TelegramNotifier helper.
"""

from unittest.mock import MagicMock, AsyncMock

import pytest
from telegram.error import TelegramError

from src.core.config import Config
from src.services.telegram_notifier import (
    TelegramNotificationError,
    TelegramNotifier,
)


@pytest.fixture(autouse=True)
def reset_token(monkeypatch):
    """Ensure tests can override the bot token cleanly."""
    monkeypatch.setattr(Config, "TELEGRAM_BOT_TOKEN", "test-token")


def test_send_plaintext_success():
    fake_bot = MagicMock()
    fake_bot.send_message.return_value.message_id = 101

    notifier = TelegramNotifier(bot=fake_bot)
    result = notifier.send_plaintext("12345", "Funding approved.")

    assert result.success is True
    assert result.message_id == "101"
    fake_bot.send_message.assert_called_once_with(chat_id="12345", text="Funding approved.")


def test_send_plaintext_failure_returns_error():
    fake_bot = MagicMock()
    fake_bot.send_message.side_effect = TelegramError("network down")

    notifier = TelegramNotifier(bot=fake_bot)
    result = notifier.send_plaintext("12345", "Funding approved.")

    assert result.success is False
    assert "network down" in (result.error_message or "")


def test_send_plaintext_handles_async_bot():
    class AsyncBot:
        async def send_message(self, **kwargs):
            class Resp:
                message_id = 77

            return Resp()

    notifier = TelegramNotifier(bot=AsyncBot())
    result = notifier.send_plaintext("12345", "Async message.")

    assert result.success is True
    assert result.message_id == "77"


def test_notifier_requires_token(monkeypatch):
    monkeypatch.setattr(Config, "TELEGRAM_BOT_TOKEN", "")
    with pytest.raises(TelegramNotificationError):
        TelegramNotifier()
