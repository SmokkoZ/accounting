import sqlite3
from typing import Dict, Iterator, Optional, Tuple

import pytest

from src.core.schema import create_schema
from src.services.signal_broadcast_service import SignalBroadcastService, build_chat_label
from src.services.telegram_messaging_queue import MessagingSendResult
from src.ui.utils.state_management import build_signal_routing_presets


class StubMessagingQueue:
    """Deterministic fake for MessagingQueue used in unit tests."""

    def __init__(
        self, responses: Optional[Dict[str, MessagingSendResult]] = None
    ) -> None:
        self.responses = responses or {}
        self.sent_payloads: list[Tuple[str, str]] = []

    async def send(self, chat_id: str, message: str) -> MessagingSendResult:
        self.sent_payloads.append((chat_id, message))
        return self.responses.get(
            chat_id,
            MessagingSendResult(success=True, message_id=f"msg-{chat_id}", attempts=1, latency_ms=2.0),
        )

    def close(self) -> None:  # pragma: no cover - interface shim
        return


@pytest.fixture
def signal_db() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)

    conn.execute(
        """
        INSERT INTO associates (id, display_alias, home_currency, multibook_chat_id, is_active, is_admin)
        VALUES (1, 'Alpha', 'EUR', NULL, 1, 0)
        """
    )
    conn.execute(
        """
        INSERT INTO associates (id, display_alias, home_currency, multibook_chat_id, is_active, is_admin)
        VALUES (2, 'Bravo', 'GBP', NULL, 1, 0)
        """
    )
    conn.execute(
        """
        INSERT INTO bookmakers (id, associate_id, bookmaker_name, parsing_profile, is_active)
        VALUES (1, 1, 'SportsBook AU', NULL, 1)
        """
    )
    conn.execute(
        """
        INSERT INTO bookmakers (id, associate_id, bookmaker_name, parsing_profile, is_active)
        VALUES (2, 1, 'MegaPlay', NULL, 1)
        """
    )
    conn.executemany(
        """
        INSERT INTO chat_registrations (chat_id, associate_id, bookmaker_id, is_active)
        VALUES (?, ?, ?, 1)
        """,
        [
            ("1001", 1, 1),
            ("1002", 1, 2),
            ("2001", 2, 1),
        ],
    )
    conn.commit()

    try:
        yield conn
    finally:
        conn.close()


def test_build_chat_label_handles_missing_parts() -> None:
    assert build_chat_label("  Alice  ", "Book 1 ") == "Alice - Book 1"
    assert build_chat_label("", "").startswith("Unknown associate")


def test_build_routing_presets_detects_groups(signal_db: sqlite3.Connection) -> None:
    service = SignalBroadcastService(db=signal_db, messaging_queue=StubMessagingQueue())
    try:
        options = service.list_chat_options()
    finally:
        service.close()

    presets = build_signal_routing_presets(options)
    preset_keys = {preset.key for preset in presets}
    assert "all-active" in preset_keys
    assert "associate:1" in preset_keys
    assert "bookmaker:1" in preset_keys


def test_broadcast_reports_success_and_failure(signal_db: sqlite3.Connection) -> None:
    queue = StubMessagingQueue(
        responses={
            "1001": MessagingSendResult(success=True, message_id="m-1001", attempts=1, latency_ms=5.0),
            "2001": MessagingSendResult(
                success=False,
                error_message="rate limit",
                attempts=3,
                latency_ms=18.0,
            ),
        }
    )
    service = SignalBroadcastService(db=signal_db, messaging_queue=queue)

    message = "Tab (AU)\nPallacanestro\t12/11\n01:00\tFordham – Wagner\n"
    message += "NCAA Basketball\t11-2 Tempi supplementari\t\n1.25\n●\n"
    message += "Ladbrokes\n"
    message += "Pallacanestro\t12/11\n01:00\tFordham – Wagner\n"
    message += "American - NCAA Men's\t21-2 Tempi supplementari\t\n6.50\n"

    try:
        summary = service.broadcast(
            message=message,
            chat_ids=["1001", "2001"],
            preset_key="associate:mix",
        )
    finally:
        service.close()

    assert summary.total == 2
    assert summary.succeeded == 1
    assert summary.failed == 1
    assert queue.sent_payloads[0][1] == message
    assert any("rate limit" in (failure or "") for _, failure in summary.failure_summaries)


def test_broadcast_blocks_unknown_chats(signal_db: sqlite3.Connection) -> None:
    service = SignalBroadcastService(db=signal_db, messaging_queue=StubMessagingQueue())
    try:
        with pytest.raises(ValueError):
            service.broadcast(message="Test", chat_ids=["9999"])
    finally:
        service.close()
