"""Integration tests for the Telegram pending photo audit trail."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from src.core.schema import create_schema
from src.repositories.telegram_audit_repository import TelegramAuditRepository
from src.services.telegram_pending_photo_service import TelegramPendingPhotoService
from src.utils.datetime_helpers import format_utc_iso


def _seed_core_entities(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        INSERT INTO associates (id, display_alias, home_currency, is_active, is_admin)
        VALUES (1, 'Alice', 'EUR', 1, 0)
        """
    )
    conn.execute(
        """
        INSERT INTO bookmakers (id, associate_id, bookmaker_name, is_active)
        VALUES (10, 1, 'Bet365', 1)
        """
    )
    conn.commit()


def _insert_pending(
    conn: sqlite3.Connection,
    *,
    token: str,
    message_id: str,
) -> int:
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=30)
    cursor = conn.execute(
        """
        INSERT INTO pending_photos (
            chat_id,
            user_id,
            associate_id,
            bookmaker_id,
            associate_alias,
            bookmaker_name,
            home_currency,
            screenshot_path,
            photo_message_id,
            confirmation_token,
            expires_at_utc,
            created_at_utc,
            updated_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "chat-1",
            101,
            1,
            10,
            "Alice",
            "Bet365",
            "EUR",
            "shot.png",
            message_id,
            token,
            format_utc_iso(expires),
            format_utc_iso(now),
            format_utc_iso(now),
        ),
    )
    conn.commit()
    return int(cursor.lastrowid)


def test_service_actions_populate_telegram_audit_log(tmp_path):
    db_path = tmp_path / "audit.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    _seed_core_entities(conn)
    discard_id = _insert_pending(conn, token="discard1", message_id="m1")
    force_id = _insert_pending(conn, token="force2", message_id="m2")

    service = TelegramPendingPhotoService(db=conn, extraction_runner=lambda _: None)
    service.discard(discard_id, operator="ui_operator", reason="bad-quality")
    service.force_ingest(force_id, operator="ui_operator", justification="manual-override")
    service.close()

    repo = TelegramAuditRepository(db=conn)
    events = repo.list_recent(limit=10)
    repo.close()

    assert len(events) >= 2
    discard_event = next(event for event in events if event["pending_photo_id"] == discard_id)
    force_event = next(event for event in events if event["pending_photo_id"] == force_id)

    assert discard_event["action"] == "discard"
    assert discard_event["operator"] == "ui_operator"
    assert discard_event["reason"] == "bad-quality"
    assert discard_event["message_id"] == "m1"

    assert force_event["action"] == "force_ingest"
    assert force_event["reason"] == "manual-override"
    assert force_event["message_id"] == "m2"
    assert force_event["outcome"].startswith("bet_id=")
