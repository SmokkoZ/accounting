"""
Database utility helpers.

Provides consistent transaction handling for SQLite connections used across
services. Using an explicit context manager avoids relying on implicit commit
semantics and guarantees rollback on any exception.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from src.utils.logging_config import get_logger


logger = get_logger(__name__)


class TransactionError(Exception):
    """Raised when a database transaction fails."""

    pass


@contextmanager
def transactional(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """
    Provide a transactional scope around a series of database operations.

    Ensures an explicit BEGIN/COMMIT pair and performs rollback when any
    exception escapes the context block.
    """
    try:
        conn.execute("BEGIN")
        yield conn
    except Exception as exc:  # pragma: no cover - defensive logging path
        logger.error("transaction_rollback", error=str(exc))
        conn.rollback()
        raise TransactionError("Database transaction failed") from exc
    else:
        conn.commit()
