"""
Tests for the performance index migration script.
"""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def perf_migration_module():
    module_path = Path("scripts/migrate_add_performance_indexes.py").resolve()
    spec = importlib.util.spec_from_file_location("perf_mig", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_performance_indexes_created(tmp_path, perf_migration_module, monkeypatch):
    db_path = tmp_path / "perf.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE bets (
            id INTEGER PRIMARY KEY,
            status TEXT,
            created_at_utc TEXT
        );
        CREATE TABLE surebets (
            id INTEGER PRIMARY KEY,
            status TEXT,
            created_at_utc TEXT
        );
        CREATE TABLE ledger_entries (
            id INTEGER PRIMARY KEY,
            surebet_id INTEGER,
            created_at_utc TEXT
        );
        """
    )
    conn.close()

    monkeypatch.setattr(perf_migration_module.Config, "DB_PATH", str(db_path))
    assert perf_migration_module.migrate_performance_indexes() is True

    with sqlite3.connect(db_path) as verify_conn:
        indexes = {
            row[0]
            for row in verify_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }

    expected = {
        "idx_bets_status_created",
        "idx_surebets_status_created",
        "idx_ledger_surebet",
        "idx_ledger_created",
    }
    assert expected.issubset(indexes)
