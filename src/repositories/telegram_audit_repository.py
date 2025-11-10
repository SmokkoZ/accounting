"""
Repository helpers for the telegram_audit_log table.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, Iterable, List, Optional

from src.core.database import get_db_connection


class TelegramAuditRepository:
    """Persist and query Telegram pending photo audit events."""

    def __init__(self, db: Optional[sqlite3.Connection] = None) -> None:
        self._db = db or get_db_connection()
        self._owns_connection = db is None

    def close(self) -> None:
        """Close the owned database connection, if any."""
        if self._owns_connection:
            try:
                self._db.close()
            except Exception:  # pragma: no cover - defensive cleanup
                pass

    def record_event(
        self,
        *,
        pending_photo_id: Optional[int],
        chat_id: Optional[str],
        message_id: Optional[str],
        action: str,
        operator: Optional[str],
        reason: Optional[str],
        outcome: str,
        source: str = "ui",
    ) -> None:
        """Insert an audit event row."""
        if action not in {"discard", "force_ingest", "auto_discard", "ingest"}:
            raise ValueError(f"Unsupported Telegram audit action: {action}")
        self._db.execute(
            """
            INSERT INTO telegram_audit_log (
                pending_photo_id,
                chat_id,
                message_id,
                action,
                operator,
                reason,
                outcome,
                source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pending_photo_id,
                chat_id,
                message_id,
                action,
                operator,
                reason,
                outcome,
                source,
            ),
        )
        self._db.commit()

    def list_events_for_pending(self, pending_photo_id: int) -> List[Dict[str, Any]]:
        """Return audit events for a specific pending photo."""
        cursor = self._db.execute(
            """
            SELECT *
            FROM telegram_audit_log
            WHERE pending_photo_id = ?
            ORDER BY created_at_utc DESC
            """,
            (pending_photo_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def list_recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return the most recent audit entries."""
        cursor = self._db.execute(
            """
            SELECT *
            FROM telegram_audit_log
            ORDER BY created_at_utc DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]


__all__ = ["TelegramAuditRepository"]
