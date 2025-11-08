"""
Repository for persisting notification attempts so operators have a follow-up trail.
"""

from __future__ import annotations

import sqlite3
from typing import Optional

from src.core.database import get_db_connection


class NotificationAuditRepository:
    """Lightweight helper around the notification_audit table."""

    def __init__(self, db: Optional[sqlite3.Connection] = None) -> None:
        self._owns_connection = db is None
        self._db = db or get_db_connection()

    def close(self) -> None:
        """Close the managed connection when the repository created it."""
        if self._owns_connection:
            try:
                self._db.close()
            except Exception:  # pragma: no cover - defensive
                pass

    def record_attempt(
        self,
        *,
        draft_id: str,
        chat_id: Optional[str],
        ledger_id: Optional[int],
        operator_id: Optional[str],
        status: str,
        detail: Optional[str] = None,
    ) -> None:
        """
        Persist a notification attempt for auditing.

        Args:
            draft_id: UUID of the funding draft
            chat_id: Telegram chat identifier (if known)
            ledger_id: Ledger entry tied to the notification
            operator_id: Operator/contact who triggered the notification
            status: 'sent' or 'failed'
            detail: Optional diagnostic/failure note
        """
        if status not in {"sent", "failed"}:
            raise ValueError("status must be either 'sent' or 'failed'")

        needs_follow_up = 1 if status == "failed" else 0
        self._db.execute(
            """
            INSERT INTO notification_audit (
                draft_id,
                chat_id,
                ledger_id,
                operator_id,
                status,
                detail,
                needs_follow_up
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                draft_id,
                chat_id,
                ledger_id,
                operator_id,
                status,
                detail,
                needs_follow_up,
            ),
        )
        self._db.commit()
