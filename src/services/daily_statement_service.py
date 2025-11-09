from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Callable, List, Optional

from src.core.config import Config
from src.core.database import get_db_connection
from src.services.bookmaker_balance_service import BalanceMessage, BookmakerBalanceService
from src.services.telegram_messaging_queue import MessagingQueue, MessagingSendResult
from src.utils.datetime_helpers import utc_now_iso
from src.utils.logging_config import get_logger

logger = get_logger(__name__)
ProgressCallback = Callable[[int, int], None]


@dataclass(frozen=True)
class DailyStatementTarget:
    """Information describing a single chat registration target."""

    chat_id: str
    associate_id: int
    bookmaker_id: int
    associate_alias: str
    bookmaker_name: str


@dataclass
class DailyStatementLogEntry:
    """Audit record for one chat attempt."""

    chat_id: str
    associate_id: int
    bookmaker_id: int
    associate_alias: str
    bookmaker_name: str
    status: str
    message_text: Optional[str]
    message_id: Optional[str]
    error_message: Optional[str]
    retries: int
    timestamp: str


@dataclass
class DailyStatementBatchResult:
    """Summary of the batch run for UI and exports."""

    total_targets: int
    log: List[DailyStatementLogEntry]

    @property
    def sent(self) -> int:
        return sum(1 for entry in self.log if entry.status == "sent")

    @property
    def failed(self) -> int:
        return sum(1 for entry in self.log if entry.status == "failed")

    @property
    def skipped(self) -> int:
        return sum(1 for entry in self.log if entry.status == "skipped")

    @property
    def retried(self) -> int:
        return sum(1 for entry in self.log if entry.retries > 0)


class DailyStatementSender:
    """Send the standardized balance + pending summary to all chats."""

    DEFAULT_GLOBAL_CAP = 15
    DEFAULT_PER_CHAT_INTERVAL = 1.0
    DEFAULT_MAX_RETRIES = 3

    def __init__(
        self,
        *,
        db: Optional[sqlite3.Connection] = None,
        messaging_queue: Optional[MessagingQueue] = None,
        global_rate_limit: int = DEFAULT_GLOBAL_CAP,
        per_chat_interval: float = DEFAULT_PER_CHAT_INTERVAL,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        self._owns_connection = db is None
        self.db = db or get_db_connection()
        self.max_retries = max(0, max_retries)

        if messaging_queue is None and not Config.TELEGRAM_BOT_TOKEN:
            raise ValueError("TELEGRAM_BOT_TOKEN not configured")

        if messaging_queue is None:
            per_chat_rps = 1.0 / max(per_chat_interval, 0.1)
            self._queue = MessagingQueue(
                global_rps=max(1, global_rate_limit),
                per_chat_rps=per_chat_rps,
                max_retries=self.max_retries,
            )
        else:
            self._queue = messaging_queue

    def close(self) -> None:
        """Close owned resources."""
        if self._owns_connection:
            try:
                self.db.close()
            except Exception:
                pass
        try:
            self._queue.close()
        except Exception:
            pass

    def _collect_targets(self) -> tuple[List[DailyStatementTarget], List[DailyStatementLogEntry]]:
        cursor = self.db.execute(
            """
            SELECT
                cr.chat_id,
                cr.associate_id,
                cr.bookmaker_id,
                cr.is_active AS registration_active,
                b.bookmaker_name,
                b.is_active AS bookmaker_active,
                a.display_alias AS associate_alias,
                a.is_active AS associate_active
            FROM chat_registrations cr
            JOIN associates a ON a.id = cr.associate_id
            JOIN bookmakers b ON b.id = cr.bookmaker_id
            ORDER BY a.display_alias, b.bookmaker_name
            """
        ).fetchall()

        targets: List[DailyStatementTarget] = []
        skips: List[DailyStatementLogEntry] = []

        for row in cursor:
            chat_id = str(row["chat_id"])
            associate_alias = row["associate_alias"] or ""
            bookmaker_name = row["bookmaker_name"] or ""

            if not bool(row["registration_active"]):
                skips.append(self._build_skip_entry(row, "registration is inactive"))
                continue

            if not bool(row["associate_active"]):
                skips.append(self._build_skip_entry(row, "associate is inactive"))
                continue

            if not bool(row["bookmaker_active"]):
                skips.append(self._build_skip_entry(row, "bookmaker is inactive"))
                continue

            targets.append(
                DailyStatementTarget(
                    chat_id=chat_id,
                    associate_id=row["associate_id"],
                    bookmaker_id=row["bookmaker_id"],
                    associate_alias=associate_alias,
                    bookmaker_name=bookmaker_name,
                )
            )

        return targets, skips

    def _build_skip_entry(self, row: sqlite3.Row, reason: str) -> DailyStatementLogEntry:
        return DailyStatementLogEntry(
            chat_id=str(row["chat_id"]),
            associate_id=row["associate_id"],
            bookmaker_id=row["bookmaker_id"],
            associate_alias=row["associate_alias"] or "",
            bookmaker_name=row["bookmaker_name"] or "",
            status="skipped",
            message_text=None,
            message_id=None,
            error_message=reason,
            retries=0,
            timestamp=utc_now_iso(),
        )

    async def _send_with_retries(
        self, target: DailyStatementTarget, payload: BalanceMessage
    ) -> DailyStatementLogEntry:
        result = await self._queue.send(target.chat_id, payload.message)
        retries = max(result.attempts - 1, 0)

        if result.success:
            logger.info(
                "daily_statement_sent",
                chat_id=target.chat_id,
                associate_id=target.associate_id,
                bookmaker_id=target.bookmaker_id,
                message_id=result.message_id,
                retries=retries,
            )
            return DailyStatementLogEntry(
                chat_id=target.chat_id,
                associate_id=target.associate_id,
                bookmaker_id=target.bookmaker_id,
                associate_alias=target.associate_alias,
                bookmaker_name=target.bookmaker_name,
                status="sent",
                message_text=payload.message,
                message_id=result.message_id,
                error_message=None,
                retries=retries,
                timestamp=utc_now_iso(),
            )

        logger.warning(
            "daily_statement_send_error",
            chat_id=target.chat_id,
            associate_id=target.associate_id,
            bookmaker_id=target.bookmaker_id,
            error=result.error_message,
            retries=retries,
        )
        logger.error(
            "daily_statement_failed",
            chat_id=target.chat_id,
            associate_id=target.associate_id,
            bookmaker_id=target.bookmaker_id,
            error=result.error_message,
            retries=retries,
        )
        return DailyStatementLogEntry(
            chat_id=target.chat_id,
            associate_id=target.associate_id,
            bookmaker_id=target.bookmaker_id,
            associate_alias=target.associate_alias,
            bookmaker_name=target.bookmaker_name,
            status="failed",
            message_text=payload.message,
            message_id=result.message_id,
            error_message=result.error_message,
            retries=retries,
            timestamp=utc_now_iso(),
        )

    async def send_all(
        self, *, progress_callback: Optional[ProgressCallback] = None
    ) -> DailyStatementBatchResult:
        targets, skipped = self._collect_targets()
        total_targets = len(targets)

        if total_targets == 0:
            logger.info("daily_statements_no_targets")
            if progress_callback:
                progress_callback(0, 0)
            return DailyStatementBatchResult(total_targets=0, log=skipped)

        log_entries: List[DailyStatementLogEntry] = skipped.copy()

        with BookmakerBalanceService(self.db) as balance_service:
            for index, target in enumerate(targets, start=1):
                try:
                    payload = balance_service.build_balance_message(
                        associate_id=target.associate_id,
                        bookmaker_id=target.bookmaker_id,
                    )
                except ValueError as exc:
                    entry = DailyStatementLogEntry(
                        chat_id=target.chat_id,
                        associate_id=target.associate_id,
                        bookmaker_id=target.bookmaker_id,
                        associate_alias=target.associate_alias,
                        bookmaker_name=target.bookmaker_name,
                        status="skipped",
                        message_text=None,
                        message_id=None,
                        error_message=str(exc),
                        retries=0,
                        timestamp=utc_now_iso(),
                    )
                    log_entries.append(entry)
                    if progress_callback:
                        progress_callback(index, total_targets)
                    continue

                entry = await self._send_with_retries(target, payload)
                log_entries.append(entry)
                if progress_callback:
                    progress_callback(index, total_targets)

        if progress_callback:
            progress_callback(total_targets, total_targets)

        result = DailyStatementBatchResult(total_targets=total_targets, log=log_entries)
        logger.info(
            "daily_statements_complete",
            total_targets=total_targets,
            sent=result.sent,
            failed=result.failed,
            skipped=result.skipped,
            retried=result.retried,
        )
        return result
