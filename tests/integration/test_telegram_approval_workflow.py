"""
Integration tests for the Telegram funding approval workflow.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Tuple

import pytest

from src.core.schema import create_schema
from src.repositories.notification_audit_repository import (
    NotificationAuditRepository,
)
from src.services.funding_service import FundingError, FundingService
from src.services.telegram_approval_workflow import TelegramApprovalWorkflow
from src.services.telegram_notifier import TelegramNotificationResult
from src.ui import cache as ui_cache
from src.ui.services import dashboard_metrics


def _seed_database(conn: sqlite3.Connection) -> None:
    """Populate the minimum reference data for tests."""
    create_schema(conn)
    conn.execute(
        """
        INSERT INTO associates (id, display_alias, home_currency, is_active, is_admin)
        VALUES (1, 'Alice', 'EUR', TRUE, FALSE)
        """
    )
    conn.execute(
        """
        INSERT INTO bookmakers (id, associate_id, bookmaker_name, is_active)
        VALUES (10, 1, 'Bet365', TRUE)
        """
    )
    conn.commit()


def _create_thread_safe_service(db_path: str) -> FundingService:
    """Return a FundingService bound to the SQLite file so threads can connect independently."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return FundingService(db=conn)


def test_acceptance_is_atomic_across_threads(tmp_path, monkeypatch):
    """Only one operator can post the ledger entry even if approvals race."""
    monkeypatch.setattr(
        "src.services.funding_service.get_fx_rate",
        lambda *_: Decimal("1.0"),
    )

    db_path = str(tmp_path / "workflow.sqlite3")
    primary = sqlite3.connect(db_path)
    primary.row_factory = sqlite3.Row
    _seed_database(primary)
    seed_service = FundingService(db=primary)
    draft_id = seed_service.create_funding_draft(
        associate_id=1,
        bookmaker_id=10,
        event_type="DEPOSIT",
        amount_native=Decimal("25"),
        currency="EUR",
        source="telegram",
        chat_id="999",
    )
    seed_service.close()

    results: List[Tuple[str, str]] = []

    def worker() -> None:
        service = _create_thread_safe_service(db_path)
        try:
            service.accept_funding_draft(draft_id, created_by="operator")
            results.append(("success", "ledger"))
        except FundingError as exc:
            results.append(("error", str(exc)))
        finally:
            service.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    successes = [status for status, _ in results if status == "success"]
    errors = [message for status, message in results if status == "error"]

    assert len(successes) == 1
    assert len(errors) == 1
    assert "already processed" in errors[0]

    verifier = sqlite3.connect(db_path)
    ledger_count = verifier.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0]
    assert ledger_count == 1
    verifier.close()


def test_workflow_logs_notification_failures(monkeypatch):
    """Workflow audit captures notification issues for manual follow-up."""
    monkeypatch.setattr(
        "src.services.funding_service.get_fx_rate",
        lambda *_: Decimal("1.0"),
    )

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _seed_database(conn)
    service = FundingService(db=conn)
    draft_id = service.create_funding_draft(
        associate_id=1,
        bookmaker_id=10,
        event_type="DEPOSIT",
        amount_native=Decimal("55"),
        currency="EUR",
        source="telegram",
        chat_id="8888",
    )
    draft = service.get_pending_drafts(source="telegram")[0]

    audit_repo = NotificationAuditRepository(db=conn)

    class FailingNotifier:
        def send_plaintext(self, chat_id: str, text: str) -> TelegramNotificationResult:
            return TelegramNotificationResult(success=False, error_message="rate limited")

    workflow = TelegramApprovalWorkflow(
        funding_service=service,
        notifier_factory=FailingNotifier,
        audit_repository=audit_repo,
    )

    outcome = workflow.approve(draft=draft, notify_sender=True, operator_id="qa_user")
    workflow.close()

    assert outcome.notification_attempted is True
    assert outcome.notification_result is not None
    assert outcome.notification_result.success is False

    row = conn.execute(
        "SELECT status, needs_follow_up, detail FROM notification_audit WHERE draft_id = ?",
        (draft_id,),
    ).fetchone()
    assert row is not None
    assert row["status"] == "failed"
    assert row["needs_follow_up"] == 1
    assert "rate limited" in (row["detail"] or "")

    service.close()
    audit_repo.close()
    conn.close()


def test_dashboard_metrics_refresh_after_bet_approval(tmp_path):
    """Dashboard metrics reflect queue changes after a bet is approved."""
    db_path = tmp_path / "dashboard_metrics_refresh.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    create_schema(conn)

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
    incoming_created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        """
        INSERT INTO bets (id, associate_id, bookmaker_id, status, updated_at_utc, odds, currency, ingestion_source)
        VALUES (1, 1, 10, 'incoming', ?, '1.25', 'EUR', 'manual_upload')
        """,
        (incoming_created,),
    )
    conn.commit()
    conn.close()

    db_path_str = str(db_path)
    ui_cache.invalidate_connection_cache([db_path_str])
    ui_cache.invalidate_query_cache()

    snapshot_before = dashboard_metrics.load_dashboard_metrics(db_path=db_path_str)
    assert snapshot_before.waiting_incoming == 1
    assert snapshot_before.approved_today == 0

    approved_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "UPDATE bets SET status='verified', updated_at_utc=? WHERE id = 1",
        (approved_timestamp,),
    )
    conn.commit()
    conn.close()

    ui_cache.invalidate_query_cache()
    snapshot_after = dashboard_metrics.load_dashboard_metrics(db_path=db_path_str)

    assert snapshot_after.waiting_incoming == 0
    assert snapshot_after.approved_today == 1

    ui_cache.invalidate_connection_cache([db_path_str])
    ui_cache.invalidate_query_cache()
