#!/usr/bin/env python3
"""
Database migration to add high-frequency performance indexes.

Indexes created:
- idx_bets_status_created
- idx_surebets_status_created
- idx_ledger_surebet
- idx_ledger_created
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

# Ensure src is on the path for Config + logging helpers
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

try:
    from core.config import Config
    from utils.logging_config import setup_logging

    logger = setup_logging()
except Exception:  # pragma: no cover - fallback for minimal environments
    import logging

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logger = logging.getLogger("perf_migration")


INDEX_STATEMENTS: tuple[tuple[str, str], ...] = (
    (
        "idx_bets_status_created",
        "CREATE INDEX IF NOT EXISTS idx_bets_status_created "
        "ON bets(status, created_at_utc DESC)",
    ),
    (
        "idx_surebets_status_created",
        "CREATE INDEX IF NOT EXISTS idx_surebets_status_created "
        "ON surebets(status, created_at_utc DESC)",
    ),
    (
        "idx_ledger_surebet",
        "CREATE INDEX IF NOT EXISTS idx_ledger_surebet "
        "ON ledger_entries(surebet_id, created_at_utc DESC)",
    ),
    (
        "idx_ledger_created",
        "CREATE INDEX IF NOT EXISTS idx_ledger_created "
        "ON ledger_entries(created_at_utc DESC)",
    ),
)


def create_indexes(cursor: sqlite3.Cursor) -> None:
    """Apply CREATE INDEX statements."""
    for name, statement in INDEX_STATEMENTS:
        logger.info("Ensuring index %s", name)
        cursor.execute(statement)


def verify_index_usage(cursor: sqlite3.Cursor) -> None:
    """Run EXPLAIN statements to confirm index selection."""
    sample_queries = [
        (
            "bets_incoming",
            "SELECT id FROM bets WHERE status = ? ORDER BY created_at_utc DESC LIMIT 25",
            ("incoming",),
        ),
        (
            "surebets_open",
            "SELECT id FROM surebets WHERE status = ? ORDER BY created_at_utc DESC LIMIT 25",
            ("open",),
        ),
        (
            "ledger_by_surebet",
            "SELECT * FROM ledger_entries WHERE surebet_id = ? ORDER BY created_at_utc DESC LIMIT 50",
            (1,),
        ),
        (
            "ledger_recent",
            "SELECT * FROM ledger_entries ORDER BY created_at_utc DESC LIMIT 50",
            tuple(),
        ),
    ]

    for label, sql, params in sample_queries:
        cursor.execute(f"EXPLAIN QUERY PLAN {sql}", params)
        plan = cursor.fetchall()
        logger.info("EXPLAIN %s: %s", label, plan)


def migrate_performance_indexes() -> bool:
    """Entry point for the migration."""
    db_path = Config.DB_PATH
    logger.info("Applying performance indexes to %s", db_path)

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        create_indexes(cursor)
        verify_index_usage(cursor)

        conn.commit()
        conn.close()
        logger.info("Performance index migration completed.")
        return True
    except sqlite3.Error as exc:
        logger.error("SQLite error during migration: %s", exc)
        return False
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Unexpected error during migration: %s", exc)
        return False


if __name__ == "__main__":
    success = migrate_performance_indexes()
    sys.exit(0 if success else 1)
