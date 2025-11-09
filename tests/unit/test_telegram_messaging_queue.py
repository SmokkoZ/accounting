"""
Unit tests for the Telegram messaging queue abstraction.
"""

import asyncio

from src.services.telegram_messaging_queue import MessagingQueue
from src.services.telegram_notifier import TelegramNotificationResult


def _fake_monotonic_generator():
    value = {"current": 0.0}

    def now() -> float:
        return value["current"]

    return value, now


def _fake_sleep_factory(time_state):
    async def fake_sleep(duration: float) -> None:
        fake_sleep.calls.append(duration)
        time_state["current"] += duration

    fake_sleep.calls = []
    return fake_sleep


def test_per_chat_throttle_respects_interval(monkeypatch):
    time_state, fake_monotonic = _fake_monotonic_generator()
    fake_sleep = _fake_sleep_factory(time_state)
    monkeypatch.setattr(
        "src.services.telegram_messaging_queue.time.monotonic", fake_monotonic
    )
    monkeypatch.setattr("src.services.telegram_messaging_queue.asyncio.sleep", fake_sleep)

    class FakeResponse:
        message_id = "msg-1"

    queue = MessagingQueue(
        send_callable=lambda *_: FakeResponse(),
        global_rps=100,
        per_chat_rps=1.0,
        max_retries=0,
        run_in_thread=False,
    )
    try:
        asyncio.run(queue.send("chat-1", "first"))
        asyncio.run(queue.send("chat-1", "second"))
    finally:
        queue.close()

    assert fake_sleep.calls
    assert any(duration >= 0.9 for duration in fake_sleep.calls)


def test_handles_retry_after_and_metrics(monkeypatch):
    time_state, fake_monotonic = _fake_monotonic_generator()
    fake_sleep = _fake_sleep_factory(time_state)
    monkeypatch.setattr(
        "src.services.telegram_messaging_queue.time.monotonic", fake_monotonic
    )
    monkeypatch.setattr("src.services.telegram_messaging_queue.asyncio.sleep", fake_sleep)

    class RetrySender:
        def __init__(self) -> None:
            self.calls = 0

        def __call__(self, chat_id: str, text: str) -> TelegramNotificationResult:
            self.calls += 1
            if self.calls == 1:
                return TelegramNotificationResult(
                    success=False,
                    error_message="Too Many Requests: retry after 2",
                )
            return TelegramNotificationResult(success=True, message_id="retry-id")

    queue = MessagingQueue(
        send_callable=RetrySender(),
        global_rps=10,
        per_chat_rps=10,
        max_retries=2,
        run_in_thread=False,
    )
    try:
        result = asyncio.run(queue.send("chat-2", "retry"))
    finally:
        queue.close()

    assert result.success
    assert result.attempts == 2
    assert fake_sleep.calls
    assert any(duration >= 2.0 for duration in fake_sleep.calls)
    assert queue.metrics["retried"] == 1
