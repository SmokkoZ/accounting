"""
Signal broadcast orchestration for the Streamlit operator console.

Provides chat option discovery plus rate-limited delivery via the existing
Telegram messaging queue. Designed for Story 12.1 (Signal Broadcaster page).
"""

from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from src.core.database import get_db_connection
from src.services.telegram_messaging_queue import MessagingQueue, MessagingSendResult
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class ChatOption:
    """A selectable Telegram chat (associate + bookmaker pairing)."""

    chat_id: str
    associate_id: int
    bookmaker_id: int
    associate_alias: str
    bookmaker_name: str
    associate_is_active: bool
    bookmaker_is_active: bool

    @property
    def label(self) -> str:
        return build_chat_label(self.associate_alias, self.bookmaker_name)


@dataclass(frozen=True)
class BroadcastResult:
    """Outcome for a single chat delivery."""

    chat_id: str
    label: str
    success: bool
    message_id: Optional[str]
    error_message: Optional[str]
    attempts: int
    latency_ms: float


@dataclass(frozen=True)
class BroadcastSummary:
    """Aggregated summary for UI + logging."""

    preset_key: Optional[str]
    message_length: int
    results: List[BroadcastResult]

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def succeeded(self) -> int:
        return sum(1 for result in self.results if result.success)

    @property
    def failed(self) -> int:
        return self.total - self.succeeded

    @property
    def success_labels(self) -> List[str]:
        return [result.label for result in self.results if result.success]

    @property
    def failure_summaries(self) -> List[Tuple[str, Optional[str]]]:
        return [
            (result.label, result.error_message)
            for result in self.results
            if not result.success
        ]


def build_chat_label(associate_alias: str, bookmaker_name: str) -> str:
    """
    Build a friendly label combining associate + bookmaker information.
    """
    alias = associate_alias.strip() if associate_alias else "Unknown associate"
    bookmaker = bookmaker_name.strip() if bookmaker_name else "Unknown bookmaker"
    return f"{alias} - {bookmaker}"


class SignalBroadcastService:
    """
    Handles chat discovery and Telegram delivery for operator broadcasts.
    """

    def __init__(
        self,
        *,
        db: Optional[sqlite3.Connection] = None,
        messaging_queue: Optional[MessagingQueue] = None,
    ) -> None:
        self._owns_connection = db is None
        self.db = db or get_db_connection()

        self._owns_queue = messaging_queue is None
        self._queue = messaging_queue or MessagingQueue()

    def close(self) -> None:
        """Release owned resources."""
        if self._owns_connection:
            try:
                self.db.close()
            except Exception:  # pragma: no cover - defensive close
                pass
        if self._owns_queue:
            try:
                self._queue.close()
            except Exception:  # pragma: no cover - defensive close
                pass

    # ------------------------------------------------------------------ Chats --

    def list_chat_options(self, *, include_inactive: bool = False) -> List[ChatOption]:
        """
        Return all whitelisted chats plus joined associate/bookmaker metadata.
        """
        source, where_clause = self._chat_source(include_inactive=include_inactive)
        query = f"""
            SELECT
                chats.chat_id AS chat_id,
                chats.associate_id AS associate_id,
                chats.bookmaker_id AS bookmaker_id,
                a.display_alias AS associate_alias,
                a.is_active AS associate_is_active,
                b.bookmaker_name AS bookmaker_name,
                b.is_active AS bookmaker_is_active
            FROM {source} chats
            JOIN associates a ON a.id = chats.associate_id
            JOIN bookmakers b ON b.id = chats.bookmaker_id
            {where_clause}
            ORDER BY LOWER(a.display_alias), LOWER(b.bookmaker_name)
        """
        cursor = self.db.execute(query)
        options: List[ChatOption] = []
        for row in cursor.fetchall():
            option = ChatOption(
                chat_id=str(row["chat_id"]),
                associate_id=int(row["associate_id"]),
                bookmaker_id=int(row["bookmaker_id"]),
                associate_alias=row["associate_alias"] or "",
                bookmaker_name=row["bookmaker_name"] or "",
                associate_is_active=bool(row["associate_is_active"]),
                bookmaker_is_active=bool(row["bookmaker_is_active"]),
            )
            options.append(option)
        return options

    def _chat_source(self, *, include_inactive: bool) -> Tuple[str, str]:
        """
        Determine which table to query (telegram_chats vs chat_registrations).
        """
        use_telegram_chats = self._table_exists("telegram_chats")
        if use_telegram_chats:
            condition = "WHERE chats.chat_type = 'bookmaker' AND chats.bookmaker_id IS NOT NULL"
        else:
            condition = ""

        if not include_inactive:
            extra_filters = " AND " if condition else "WHERE "
            condition = (
                f"{condition}{extra_filters}a.is_active = 1 AND b.is_active = 1"
            )

        source_table = "telegram_chats" if use_telegram_chats else "chat_registrations"
        return source_table, condition

    def _table_exists(self, table_name: str) -> bool:
        cursor = self.db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        )
        return cursor.fetchone() is not None

    # -------------------------------------------------------------- Broadcast --

    def broadcast(
        self,
        *,
        message: str,
        chat_ids: Sequence[str],
        preset_key: Optional[str] = None,
    ) -> BroadcastSummary:
        """
        Send the provided message to all chat_ids via MessagingQueue.
        """
        normalized_message = message
        if not normalized_message.strip():
            raise ValueError("Message must not be empty.")
        if not chat_ids:
            raise ValueError("At least one chat must be selected.")

        known = self._index_chat_options()
        selected_options = self._validate_chat_ids(chat_ids, known)

        async def _runner() -> List[Tuple[ChatOption, MessagingSendResult]]:
            results: List[Tuple[ChatOption, MessagingSendResult]] = []
            for option in selected_options:
                send_result = await self._queue.send(option.chat_id, normalized_message)
                results.append((option, send_result))
            return results

        send_pairs = asyncio.run(_runner())
        broadcast_results = [
            self._to_broadcast_result(option, send_result)
            for option, send_result in send_pairs
        ]

        summary = BroadcastSummary(
            preset_key=preset_key,
            message_length=len(normalized_message),
            results=broadcast_results,
        )
        self._log_summary(summary, selected_options)
        return summary

    def _index_chat_options(self) -> Dict[str, ChatOption]:
        options = self.list_chat_options(include_inactive=True)
        return {option.chat_id: option for option in options}

    def _validate_chat_ids(
        self, chat_ids: Sequence[str], known: Dict[str, ChatOption]
    ) -> List[ChatOption]:
        selected = []
        for chat_id in chat_ids:
            chat_id_str = str(chat_id)
            option = known.get(chat_id_str)
            if option is None:
                raise ValueError(f"Chat {chat_id_str} is not registered/authorized.")
            selected.append(option)
        return selected

    def _to_broadcast_result(
        self, option: ChatOption, send_result: MessagingSendResult
    ) -> BroadcastResult:
        success = bool(send_result.success)
        result = BroadcastResult(
            chat_id=option.chat_id,
            label=option.label,
            success=success,
            message_id=send_result.message_id,
            error_message=send_result.error_message,
            attempts=send_result.attempts,
            latency_ms=send_result.latency_ms,
        )
        log_payload = {
            "chat_id": option.chat_id,
            "associate_id": option.associate_id,
            "bookmaker_id": option.bookmaker_id,
            "label": option.label,
            "success": success,
            "attempts": send_result.attempts,
            "latency_ms": send_result.latency_ms,
            "message_id": send_result.message_id,
            "error": send_result.error_message,
        }
        logger.info("signal_broadcast_result", **log_payload)
        return result

    def _log_summary(
        self, summary: BroadcastSummary, selected_options: Iterable[ChatOption]
    ) -> None:
        logger.info(
            "signal_broadcast_complete",
            preset_key=summary.preset_key,
            message_length=summary.message_length,
            total=summary.total,
            succeeded=summary.succeeded,
            failed=summary.failed,
            chat_ids=[option.chat_id for option in selected_options],
            labels=[option.label for option in selected_options],
        )


__all__ = [
    "BroadcastResult",
    "BroadcastSummary",
    "ChatOption",
    "SignalBroadcastService",
    "build_chat_label",
]
