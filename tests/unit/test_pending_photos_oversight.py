from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import List

import pytest

from src.core.schema import create_schema
from src.services.telegram_pending_photo_service import (
    PendingPhotoAlreadyProcessed,
    PendingPhotoNotFound,
    TelegramPendingPhotoService,
)
from src.utils.datetime_helpers import format_utc_iso


def _seed_reference_data(conn: sqlite3.Connection) -> None:
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


def _insert_pending_photo(conn: sqlite3.Connection, screenshot_path: str) -> int:
    expires = datetime.now(timezone.utc) + timedelta(minutes=30)
    now = datetime.now(timezone.utc)
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
            "12345",
            99,
            1,
            10,
            "Alice",
            "Bet365",
            "EUR",
            screenshot_path,
            "98765",
            "token123",
            format_utc_iso(expires),
            format_utc_iso(now),
            format_utc_iso(now),
        ),
    )
    conn.commit()
    return int(cursor.lastrowid)


def _build_service(conn: sqlite3.Connection, calls: List[int] | None = None) -> TelegramPendingPhotoService:
    def runner(bet_id: int) -> None:
        if calls is not None:
            calls.append(bet_id)

    return TelegramPendingPhotoService(db=conn, extraction_runner=runner)


def test_list_pending_returns_dataclass(tmp_path):
    db_path = tmp_path / "pending.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    _seed_reference_data(conn)
    pending_id = _insert_pending_photo(conn, screenshot_path="screenshot.png")

    service = _build_service(conn)
    entries = service.list_pending()
    service.close()

    assert len(entries) == 1
    entry = entries[0]
    assert entry.id == pending_id
    assert entry.associate_alias == "Alice"
    assert entry.confirmation_token == "token123"


def test_discard_updates_status_and_logs_audit(tmp_path):
    db_path = tmp_path / "pending.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    _seed_reference_data(conn)
    screenshot = tmp_path / "pending.png"
    screenshot.write_text("dummy")
    pending_id = _insert_pending_photo(conn, screenshot_path=str(screenshot))

    service = _build_service(conn)
    service.discard(pending_id, operator="operator", reason="bad-photo")
    service.close()

    row = conn.execute("SELECT status FROM pending_photos WHERE id = ?", (pending_id,)).fetchone()
    assert row["status"] == "discarded"
    assert not screenshot.exists()

    audit = conn.execute(
        "SELECT action, operator, reason, outcome FROM telegram_audit_log WHERE pending_photo_id = ?",
        (pending_id,),
    ).fetchone()
    assert audit is not None
    assert audit["action"] == "discard"
    assert audit["operator"] == "operator"
    assert audit["reason"] == "bad-photo"


def test_force_ingest_creates_bet_and_triggers_runner(tmp_path):
    db_path = tmp_path / "pending.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    _seed_reference_data(conn)
    pending_id = _insert_pending_photo(conn, screenshot_path="pending.png")

    calls: List[int] = []
    service = _build_service(conn, calls)
    result = service.force_ingest(pending_id, operator="operator", justification="need-fast")

    bet_id = result["bet_id"]
    service.close()
    assert calls == [bet_id]

    row = conn.execute("SELECT status, bet_id FROM pending_photos WHERE id = ?", (pending_id,)).fetchone()
    assert row["status"] == "confirmed"
    assert row["bet_id"] == bet_id

    audit = conn.execute(
        "SELECT action, reason, outcome FROM telegram_audit_log WHERE pending_photo_id = ?",
        (pending_id,),
    ).fetchone()
    assert audit["action"] == "force_ingest"
    assert audit["reason"] == "need-fast"
    assert f"{bet_id}" in audit["outcome"]

    with pytest.raises(PendingPhotoAlreadyProcessed):
        service = _build_service(conn)
        try:
            service.force_ingest(pending_id, operator="operator", justification="duplicate")
        finally:
            service.close()


def test_discard_missing_row_raises_not_found(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    _seed_reference_data(conn)
    service = _build_service(conn)
    with pytest.raises(PendingPhotoNotFound):
        service.discard(999, operator="operator", reason="n/a")
    service.close()
