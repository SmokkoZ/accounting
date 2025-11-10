"""Unit tests for dashboard metrics aggregation."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src.core.schema import create_schema
from src.ui import cache
from src.ui.services import dashboard_metrics


def _prepare_database(tmp_path: Path) -> str:
    db_path = tmp_path / "dashboard_metrics.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    create_schema(conn)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

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

    bet_rows = [
        (1, "incoming", now),
        (2, "verified", now),
        (3, "matched", now),
        (4, "rejected", now),
    ]
    for bet_id, status, updated_at in bet_rows:
        conn.execute(
            """
            INSERT INTO bets (id, associate_id, bookmaker_id, status, updated_at_utc, odds, currency, ingestion_source)
            VALUES (?, 1, 10, ?, ?, '1.20', 'EUR', 'manual_upload')
            """,
            (bet_id, status, updated_at),
        )

    conn.execute(
        """
        INSERT INTO surebets (id, status, created_at_utc, updated_at_utc)
        VALUES (1, 'open', ?, ?)
        """,
        (now, now),
    )
    conn.execute(
        """
        INSERT INTO surebets (id, status, created_at_utc, updated_at_utc)
        VALUES (2, 'settled', ?, ?)
        """,
        (now, now),
    )
    conn.commit()
    conn.close()
    return str(db_path)


def test_load_dashboard_metrics_returns_real_counts(tmp_path):
    db_path = _prepare_database(tmp_path)
    cache.invalidate_connection_cache([db_path])
    cache.invalidate_query_cache()

    snapshot = dashboard_metrics.load_dashboard_metrics(db_path=db_path)

    assert snapshot.waiting_incoming == 1
    assert snapshot.approved_today == 1
    assert snapshot.open_surebets == 1
    assert snapshot.pending_settlements == 2

    cache.invalidate_connection_cache([db_path])
    cache.invalidate_query_cache()


def test_metrics_handle_empty_tables(tmp_path):
    empty_db = tmp_path / "empty_metrics.db"
    conn = sqlite3.connect(empty_db)
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    conn.close()

    db_path = str(empty_db)
    cache.invalidate_connection_cache([db_path])
    cache.invalidate_query_cache()

    snapshot = dashboard_metrics.load_dashboard_metrics(db_path=db_path)

    assert snapshot.waiting_incoming == 0
    assert snapshot.approved_today == 0
    assert snapshot.open_surebets == 0
    assert snapshot.pending_settlements == 0

    cache.invalidate_connection_cache([db_path])
    cache.invalidate_query_cache()
