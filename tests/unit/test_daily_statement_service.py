"""
Unit tests for the Daily Statement sender.

Exercises target collection, rate-limit handling, and retry paths.
"""

import asyncio
import sqlite3
import pytest
from src.core.schema import create_schema
from src.services.daily_statement_service import DailyStatementSender
from src.services.telegram_messaging_queue import MessagingSendResult
from src.utils.datetime_helpers import utc_now_iso


@pytest.fixture
def test_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    create_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def seeded_db(test_db):
    cursor = test_db.cursor()
    cursor.execute(
        "INSERT INTO associates (id, display_alias, home_currency, is_active) VALUES (1, 'Alice', 'EUR', 1)"
    )
    cursor.execute(
        "INSERT INTO bookmakers (id, associate_id, bookmaker_name, is_active) VALUES (1, 1, 'BetOne', 1)"
    )
    cursor.execute(
        "INSERT INTO bookmakers (id, associate_id, bookmaker_name, is_active) VALUES (2, 1, 'BetDisabled', 0)"
    )
    cursor.execute(
        """
        INSERT INTO bookmaker_balance_checks (
            associate_id, bookmaker_id, balance_native, native_currency,
            balance_eur, fx_rate_used, check_date_utc
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (1, 1, "150.00", "EUR", "150.00", "1.0", utc_now_iso()),
    )
    cursor.execute(
        """
        INSERT INTO bets (associate_id, bookmaker_id, status, stake_eur, odds, currency)
        VALUES (?, ?, 'matched', '50.00', '1.45', 'EUR')
        """,
        (1, 1),
    )
    cursor.execute(
        "INSERT INTO chat_registrations (chat_id, associate_id, bookmaker_id, is_active) VALUES ('1001', 1, 1, 1)"
    )
    cursor.execute(
        "INSERT INTO chat_registrations (chat_id, associate_id, bookmaker_id, is_active) VALUES ('1002', 1, 2, 1)"
    )
    test_db.commit()
    return test_db


def test_send_all_sends_active_chat_and_skips_inactive_bookmaker(seeded_db):
    progress_updates: list[tuple[int, int]] = []

    class FakeQueue:
        async def send(self, chat_id: str, text: str) -> MessagingSendResult:
            return MessagingSendResult(success=True, message_id="42", attempts=1, latency_ms=5, outcome="sent")

    sender = DailyStatementSender(
        db=seeded_db,
        messaging_queue=FakeQueue(),
    )
    try:
        result = asyncio.run(
            sender.send_all(
                progress_callback=lambda processed, total: progress_updates.append(
                    (processed, total)
                )
            )
        )
    finally:
        sender.close()

    assert result.sent == 1
    assert result.failed == 0
    assert result.skipped == 1
    assert result.retried == 0
    assert len(result.log) == 2
    assert result.log[0].status == "skipped"
    assert result.log[1].status == "sent"
    assert result.log[1].message_id == "42"
    assert progress_updates == [(1, 1), (1, 1)]


def test_send_all_records_failure_when_queue_fails(seeded_db):
    class BrokenQueue:
        async def send(self, chat_id: str, text: str) -> MessagingSendResult:
            return MessagingSendResult(
                success=False,
                error_message="server error",
                attempts=2,
                latency_ms=1,
                outcome="failed",
            )

    sender = DailyStatementSender(
        db=seeded_db,
        messaging_queue=BrokenQueue(),
    )
    try:
        result = asyncio.run(sender.send_all())
    finally:
        sender.close()

    assert result.sent == 0
    assert result.failed == 1
    assert result.skipped == 1
    assert result.retried == 1
    assert result.log[-1].status == "failed"
    assert result.log[-1].error_message == "server error"
