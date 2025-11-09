"""
Messaging queue that respects Telegram rate limits, retries, and observability requirements.
"""

from __future__ import annotations

import asyncio
import hashlib
import random
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

from telegram.error import TelegramError

from src.core.config import Config
from src.services.telegram_notifier import (
    TelegramNotificationError,
    TelegramNotificationResult,
    TelegramNotifier,
)
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

SendCallable = Callable[[str, str], Any]


@dataclass(frozen=True)
class MessagingSendResult:
    """Outcome of a single dispatch request emitted by the messaging queue."""

    success: bool
    message_id: Optional[str] = None
    error_message: Optional[str] = None
    attempts: int = 0
    latency_ms: float = 0.0
    outcome: str = "unknown"


class MessagingQueue:
    """Rate-limited, retriable wrapper around the Telegram send API."""

    RETRY_AFTER_PATTERN = re.compile(r"retry after (?P<seconds>\d+(?:\.\d+)?)", re.IGNORECASE)
    RETRYABLE_PATTERNS = (
        re.compile(r"5\d\d"),
        re.compile(r"timeout"),
        re.compile(r"timed out"),
        re.compile(r"network"),
    )

    def __init__(
        self,
        *,
        notifier: Optional[TelegramNotifier] = None,
        notifier_factory: Optional[Callable[[], TelegramNotifier]] = None,
        send_callable: Optional[SendCallable] = None,
        run_in_thread: bool = True,
        global_rps: Optional[int] = None,
        per_chat_rps: Optional[float] = None,
        max_retries: int = 3,
        dry_run: bool = False,
    ) -> None:
        self.global_capacity = max(
            1, global_rps if global_rps is not None else Config.TELEGRAM_MAX_RPS
        )
        per_chat_rps_value = (
            per_chat_rps
            if per_chat_rps is not None
            else Config.TELEGRAM_PER_CHAT_RPS
        )
        self.per_chat_interval = (
            1.0 / per_chat_rps_value if per_chat_rps_value > 0 else 0.0
        )
        self.max_retries = max(0, max_retries)
        self._run_in_thread = run_in_thread
        self._dry_run = dry_run
        self._global_tokens = float(self.global_capacity)
        self._last_refill = time.monotonic()
        self._global_lock = asyncio.Lock()
        self._chat_lock = asyncio.Lock()
        self._chat_timestamps: Dict[str, float] = {}
        self._global_backoff_until = 0.0
        self._per_chat_backoff: Dict[str, float] = {}
        self._dedupe_registry: Dict[Tuple[str, str], Optional[str]] = {}
        self._metrics = {"sent": 0, "retried": 0, "failed": 0}

        self._send_callable: SendCallable
        self._notifier_to_close: Optional[TelegramNotifier] = None
        if send_callable is not None:
            self._send_callable = send_callable
        else:
            if notifier is not None:
                self._notifier_to_close = notifier
            else:
                factory = notifier_factory or TelegramNotifier
                try:
                    self._notifier_to_close = factory()
                except TelegramNotificationError as exc:
                    raise ValueError(f"Telegram notifier unavailable: {exc}") from exc
            self._send_callable = self._notifier_to_close.send_plaintext

    @property
    def metrics(self) -> Dict[str, int]:
        """Return current counters for sent/retried/failed messages."""
        return dict(self._metrics)

    def close(self) -> None:
        """Release any owned notifier resources."""
        if self._notifier_to_close:
            try:
                close_fn = getattr(self._notifier_to_close, "close", None)
                if callable(close_fn):
                    close_fn()
            except Exception:
                logger.exception("telegram_queue_close_failed")

    async def send(self, chat_id: str, message: str) -> MessagingSendResult:
        """Send a message respecting throttles, retries, and idempotency."""
        message_hash = self._hash_message(message)
        dedupe_key = (chat_id, message_hash)
        if dedupe_key in self._dedupe_registry:
            logger.info(
                "telegram_queue_deduplicate",
                chat_id=chat_id,
                message_hash=message_hash,
                attempt=0,
                latency_ms=0,
                outcome="dedup",
                message_id=self._dedupe_registry[dedupe_key],
            )
            return MessagingSendResult(
                success=True,
                message_id=self._dedupe_registry[dedupe_key],
                attempts=0,
                latency_ms=0.0,
                outcome="dedup",
            )

        max_attempts = self.max_retries + 1
        attempt = 0
        last_latency = 0.0
        last_error: Optional[str] = None
        while attempt < max_attempts:
            attempt += 1
            await self._enforce_rate_limits(chat_id)
            start = time.monotonic()
            result = await self._dispatch(chat_id, message)
            last_latency = (time.monotonic() - start) * 1000
            outcome = "sent" if result.success else "failed"
            logger.info(
                "telegram_queue_attempt",
                chat_id=chat_id,
                message_hash=message_hash,
                attempt=attempt,
                latency_ms=int(last_latency),
                outcome=outcome,
            )

            if result.success:
                self._metrics["sent"] += 1
                self._dedupe_registry[dedupe_key] = result.message_id
                self._log_metrics()
                return MessagingSendResult(
                    success=True,
                    message_id=result.message_id,
                    error_message=None,
                    attempts=attempt,
                    latency_ms=last_latency,
                    outcome="sent",
                )

            last_error = result.error_message or "Unknown telegram error"
            if attempt >= max_attempts:
                break

            retry_after = self._extract_retry_after(last_error)
            should_retry = self._should_retry(last_error)
            if not (retry_after or should_retry):
                break

            self._metrics["retried"] += 1

            if retry_after:
                logger.warning(
                    "telegram_queue_retry_after",
                    chat_id=chat_id,
                    message_hash=message_hash,
                    attempt=attempt,
                    retry_after=retry_after,
                )
                await self._apply_retry_after(chat_id, retry_after)
            else:
                await self._handle_backoff(attempt)

        self._metrics["failed"] += 1
        self._log_metrics()
        return MessagingSendResult(
            success=False,
            message_id=None,
            error_message=last_error,
            attempts=attempt,
            latency_ms=last_latency,
            outcome="failed",
        )

    def _log_metrics(self) -> None:
        logger.debug(
            "telegram_queue_metrics",
            sent=self._metrics["sent"],
            retried=self._metrics["retried"],
            failed=self._metrics["failed"],
        )

    async def _dispatch(self, chat_id: str, message: str) -> TelegramNotificationResult:
        if self._dry_run:
            return TelegramNotificationResult(success=True)

        if self._run_in_thread:
            return await asyncio.to_thread(self._run_send, chat_id, message)
        return await self._run_send_async(chat_id, message)

    async def _run_send_async(self, chat_id: str, message: str) -> TelegramNotificationResult:
        try:
            result = self._send_callable(chat_id, message)
        except TelegramError as exc:  # pragma: no cover - defensive guardrail
            return TelegramNotificationResult(success=False, error_message=str(exc))

        if asyncio.iscoroutine(result):
            result = await result
        return self._normalize_result(result)

    def _run_send(self, chat_id: str, message: str) -> TelegramNotificationResult:
        try:
            result = self._send_callable(chat_id, message)
        except TelegramError as exc:  # pragma: no cover - defensive guardrail
            return TelegramNotificationResult(success=False, error_message=str(exc))

        return self._normalize_result(result)

    def _normalize_result(self, result: Any) -> TelegramNotificationResult:
        if isinstance(result, TelegramNotificationResult):
            return result
        message_id = getattr(result, "message_id", None)
        if message_id is not None:
            return TelegramNotificationResult(success=True, message_id=str(message_id))
        return TelegramNotificationResult(success=True)

    async def _enforce_rate_limits(self, chat_id: str) -> None:
        await self._respect_backoff(chat_id)
        await self._acquire_global_slot()
        await self._enforce_per_chat_interval(chat_id)

    async def _respect_backoff(self, chat_id: str) -> None:
        while True:
            now = time.monotonic()
            wait_until = max(
                0.0,
                self._global_backoff_until - now,
                self._per_chat_backoff.get(chat_id, 0.0) - now,
            )
            if wait_until <= 0:
                return
            await asyncio.sleep(wait_until)

    async def _acquire_global_slot(self) -> None:
        while True:
            async with self._global_lock:
                now = time.monotonic()
                elapsed = now - self._last_refill
                if elapsed > 0:
                    refill = elapsed * self.global_capacity
                    self._global_tokens = min(self.global_capacity, self._global_tokens + refill)
                    self._last_refill = now

                if self._global_tokens >= 1:
                    self._global_tokens -= 1
                    return

                sleep_seconds = max(0.0, (1 - self._global_tokens) / self.global_capacity)
            await asyncio.sleep(sleep_seconds)

    async def _enforce_per_chat_interval(self, chat_id: str) -> None:
        if self.per_chat_interval <= 0:
            return
        wait = 0.0
        async with self._chat_lock:
            now = time.monotonic()
            last_sent = self._chat_timestamps.get(chat_id, 0.0)
            wait = max(0.0, last_sent + self.per_chat_interval - now)
        if wait > 0:
            await asyncio.sleep(wait)
        async with self._chat_lock:
            self._chat_timestamps[chat_id] = time.monotonic()

    async def _apply_retry_after(self, chat_id: str, retry_after: float) -> None:
        if retry_after <= 0:
            retry_after = 0.1
        until = time.monotonic() + retry_after
        self._global_backoff_until = max(self._global_backoff_until, until)
        self._per_chat_backoff[chat_id] = max(self._per_chat_backoff.get(chat_id, 0.0), until)
        await asyncio.sleep(retry_after)

    async def _handle_backoff(self, attempt: int) -> None:
        delay = min(1.0 * 2 ** (attempt - 1), 30.0)
        jitter = random.uniform(0.0, 0.5)
        await asyncio.sleep(delay + jitter)

    @classmethod
    def _extract_retry_after(cls, error_message: Optional[str]) -> Optional[float]:
        if not error_message:
            return None
        match = cls.RETRY_AFTER_PATTERN.search(error_message)
        if not match:
            return None
        try:
            return float(match.group("seconds"))
        except (TypeError, ValueError):
            return None

    @classmethod
    def _should_retry(cls, error_message: Optional[str]) -> bool:
        if not error_message:
            return True
        normalized = error_message.lower()
        if "too many requests" in normalized:
            return True
        return any(pattern.search(normalized) for pattern in cls.RETRYABLE_PATTERNS)

    @staticmethod
    def _hash_message(message: str) -> str:
        return hashlib.sha256(message.encode("utf-8")).hexdigest()


__all__ = ["MessagingQueue", "MessagingSendResult"]
