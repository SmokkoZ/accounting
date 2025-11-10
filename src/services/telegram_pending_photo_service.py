"""
Service layer for Telegram pending photo oversight and manual interventions.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

from src.core.database import get_db_connection
from src.repositories.telegram_audit_repository import TelegramAuditRepository
from src.utils.datetime_helpers import utc_now_iso
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class PendingPhoto:
    """Lightweight view of a pending photo record."""

    id: int
    chat_id: str
    photo_message_id: str
    associate_alias: Optional[str]
    bookmaker_name: Optional[str]
    confirmation_token: str
    expires_at_utc: str
    created_at_utc: str
    stake_override: Optional[str]
    stake_currency: Optional[str]
    win_override: Optional[str]
    win_currency: Optional[str]
    status: str
    screenshot_path: Optional[str]
    home_currency: Optional[str]


class PendingPhotoError(Exception):
    """Base error for pending photo operations."""


class PendingPhotoNotFound(PendingPhotoError):
    """Raised when a pending record cannot be found or is not eligible."""


class PendingPhotoAlreadyProcessed(PendingPhotoError):
    """Raised when the pending record is no longer actionable."""


class TelegramPendingPhotoService:
    """Expose read/write operations for pending photo oversight and actions."""

    def __init__(
        self,
        *,
        db: Optional[sqlite3.Connection] = None,
        audit_repository: Optional[TelegramAuditRepository] = None,
        extraction_runner: Optional[Callable[[int], None]] = None,
    ) -> None:
        self._db = db or get_db_connection()
        self._owns_db = db is None
        self._audit_repo = audit_repository or TelegramAuditRepository(db=self._db)
        self._owns_audit_repo = audit_repository is None
        self._extraction_runner = extraction_runner or self._default_extraction_runner

    def close(self) -> None:
        """Dispose owned resources."""
        if self._owns_audit_repo:
            self._audit_repo.close()
        if self._owns_db:
            self._db.close()

    def list_pending(self) -> List[PendingPhoto]:
        """Return all active pending rows ordered by expiration."""
        cursor = self._db.execute(
            """
            SELECT *
            FROM pending_photos
            WHERE status = 'pending'
            ORDER BY expires_at_utc ASC, id ASC
            """
        )
        rows = cursor.fetchall()
        return [self._map_row(row) for row in rows]

    def discard(
        self,
        pending_id: int,
        *,
        operator: str,
        reason: str,
    ) -> Dict[str, Optional[str]]:
        """Discard a pending entry and delete its screenshot."""
        pending = self._get_pending(pending_id)
        if pending["status"] != "pending":
            raise PendingPhotoAlreadyProcessed("Screenshot already ingested.")
        if pending["bet_id"]:
            raise PendingPhotoAlreadyProcessed("Screenshot already ingested.")

        now = utc_now_iso()
        self._db.execute(
            "UPDATE pending_photos SET status = 'discarded', updated_at_utc = ? WHERE id = ?",
            (now, pending_id),
        )
        self._db.commit()

        self._delete_file(pending.get("screenshot_path"))
        self._audit_repo.record_event(
            pending_photo_id=pending_id,
            chat_id=pending.get("chat_id"),
            message_id=pending.get("photo_message_id"),
            action="discard",
            operator=operator,
            reason=reason,
            outcome="discarded",
            source="ui",
        )
        logger.info(
            "pending_photo_discarded",
            pending_id=pending_id,
            operator=operator,
            reason=reason,
        )
        return {
            "status": "discarded",
            "updated_at": now,
        }

    def force_ingest(
        self,
        pending_id: int,
        *,
        operator: str,
        justification: str,
    ) -> Dict[str, int]:
        """Create a bet record from a pending screenshot, mimicking bot ingest."""
        pending = self._get_pending(pending_id)
        if pending["status"] != "pending":
            raise PendingPhotoAlreadyProcessed("Screenshot already ingested.")
        if pending["bet_id"]:
            raise PendingPhotoAlreadyProcessed("Screenshot already ingested.")

        manual_stake = pending.get("stake_override")
        manual_win = pending.get("win_override")
        bet_id = self._create_bet_record(
            associate_id=pending["associate_id"],
            bookmaker_id=pending["bookmaker_id"],
            chat_id=pending["chat_id"],
            message_id=pending.get("photo_message_id") or "",
            screenshot_path=pending["screenshot_path"],
            manual_stake_override=manual_stake,
            manual_stake_currency=pending.get("stake_currency"),
            manual_win_override=manual_win,
            manual_win_currency=pending.get("win_currency"),
        )

        self._db.execute(
            """
            UPDATE pending_photos
            SET status = 'confirmed',
                bet_id = ?,
                updated_at_utc = ?
            WHERE id = ?
            """,
            (bet_id, utc_now_iso(), pending_id),
        )
        self._db.commit()

        self._audit_repo.record_event(
            pending_photo_id=pending_id,
            chat_id=pending.get("chat_id"),
            message_id=pending.get("photo_message_id"),
            action="force_ingest",
            operator=operator,
            reason=justification,
            outcome=f"bet_id={bet_id}",
            source="ui",
        )
        logger.info(
            "pending_photo_force_ingest",
            pending_id=pending_id,
            operator=operator,
            bet_id=bet_id,
        )

        # Fire and forget extraction to mimic bot behaviour.
        try:
            self._extraction_runner(bet_id)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "pending_photo_force_ingest_extraction_failed",
                bet_id=bet_id,
                error=str(exc),
                exc_info=True,
            )

        return {"bet_id": bet_id}

    def _get_pending(self, pending_id: int) -> Dict[str, Optional[str]]:
        cursor = self._db.execute(
            "SELECT * FROM pending_photos WHERE id = ?",
            (pending_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise PendingPhotoNotFound(f"Pending photo {pending_id} not found.")
        return dict(row)

    @staticmethod
    def _map_row(row: sqlite3.Row) -> PendingPhoto:
        return PendingPhoto(
            id=row["id"],
            chat_id=row["chat_id"],
            photo_message_id=row["photo_message_id"],
            associate_alias=row["associate_alias"],
            bookmaker_name=row["bookmaker_name"],
            confirmation_token=row["confirmation_token"],
            expires_at_utc=row["expires_at_utc"],
            created_at_utc=row["created_at_utc"],
            stake_override=row["stake_override"],
            stake_currency=row["stake_currency"],
            win_override=row["win_override"],
            win_currency=row["win_currency"],
            status=row["status"],
            screenshot_path=row["screenshot_path"],
            home_currency=row["home_currency"],
        )

    @staticmethod
    def _delete_file(path_value: Optional[str]) -> None:
        if not path_value:
            return
        try:
            path = Path(path_value)
            if path.exists():
                path.unlink()
        except Exception as exc:  # pragma: no cover - defensive log path
            logger.warning("pending_file_delete_failed", path=path_value, error=str(exc))

    def _create_bet_record(
        self,
        *,
        associate_id: int,
        bookmaker_id: int,
        chat_id: str,
        message_id: str,
        screenshot_path: str,
        manual_stake_override: Optional[str],
        manual_stake_currency: Optional[str],
        manual_win_override: Optional[str],
        manual_win_currency: Optional[str],
    ) -> int:
        cursor = self._db.execute(
            """
            INSERT INTO bets (
                associate_id,
                bookmaker_id,
                status,
                stake_eur,
                odds,
                screenshot_path,
                telegram_message_id,
                ingestion_source,
                manual_stake_override,
                manual_stake_currency,
                manual_potential_win_override,
                manual_potential_win_currency,
                created_at_utc,
                updated_at_utc
            ) VALUES (?, ?, 'incoming', '0.00', '1.00', ?, ?, 'telegram', ?, ?, ?, ?, ?, ?)
            """,
            (
                associate_id,
                bookmaker_id,
                screenshot_path,
                message_id,
                manual_stake_override,
                manual_stake_currency,
                manual_win_override,
                manual_win_currency,
                utc_now_iso(),
                utc_now_iso(),
            ),
        )
        bet_id = cursor.lastrowid
        self._db.commit()
        logger.info(
            "pending_photo_bet_record_created",
            bet_id=bet_id,
            chat_id=chat_id,
            message_id=message_id,
        )
        return int(bet_id)

    @staticmethod
    def _default_extraction_runner(bet_id: int) -> None:
        """Spawn a background thread to kick off OCR extraction."""

        def _worker() -> None:
            try:
                from src.services.bet_ingestion import BetIngestionService

                service = BetIngestionService()
                try:
                    service.process_bet_extraction(bet_id)
                finally:
                    service.close()
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.warning(
                    "pending_photo_extraction_worker_failed",
                    bet_id=bet_id,
                    error=str(exc),
                    exc_info=True,
                )

        thread = threading.Thread(target=_worker, name=f"pending-photo-{bet_id}", daemon=True)
        thread.start()


__all__ = [
    "PendingPhoto",
    "PendingPhotoAlreadyProcessed",
    "PendingPhotoError",
    "PendingPhotoNotFound",
    "TelegramPendingPhotoService",
]
