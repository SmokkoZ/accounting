"""
Database initialization and connection management for the Surebet Accounting System.

This module handles:
- Creating the data directory if it doesn't exist
- Setting up SQLite with WAL mode and foreign keys
- Providing database connection utilities
"""

import os
import sqlite3
import threading
from pathlib import Path
from typing import Optional

from src.core.config import Config


_SCHEMA_LOCK = threading.Lock()
_SCHEMA_INITIALIZED = False


def ensure_data_directory() -> None:
    """Create the data directory if it doesn't exist."""
    db_path = Path(Config.DB_PATH)
    data_dir = db_path.parent

    if not data_dir.exists():
        data_dir.mkdir(parents=True, exist_ok=True)
        print(f"Created data directory: {data_dir}")


def get_db_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """
    Get a database connection with proper configuration.

    Args:
        db_path: Path to the SQLite database file. If None, uses Config.DB_PATH.

    Returns:
        Configured SQLite connection with WAL mode and foreign keys enabled.
    """
    if db_path is None:
        db_path = Config.DB_PATH

    # Ensure data directory exists
    ensure_data_directory()

    # Create connection with row factory for dict-like access
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    # Configure SQLite for optimal performance and data integrity
    conn.execute("PRAGMA foreign_keys = ON")  # Enforce referential integrity
    conn.execute("PRAGMA journal_mode = WAL")  # Write-Ahead Logging for resilience
    conn.execute("PRAGMA synchronous = NORMAL")  # Balance safety vs performance
    conn.execute("PRAGMA cache_size = 10000")  # 10MB cache
    conn.execute("PRAGMA temp_store = MEMORY")  # Store temp tables in memory

    # Ensure schema migrations (e.g., pair_key columns) are applied once per process
    global _SCHEMA_INITIALIZED
    if not _SCHEMA_INITIALIZED:
        with _SCHEMA_LOCK:
            if not _SCHEMA_INITIALIZED:
                try:
                    # Local import avoids circular dependency during module load
                    from src.core.schema import create_schema

                    create_schema(conn)
                except Exception as exc:  # pragma: no cover - defensive log path
                    print(f"WARNING: Failed to ensure schema is current: {exc}")
                else:
                    _SCHEMA_INITIALIZED = True

    return conn


def initialize_database(db_path: Optional[str] = None) -> sqlite3.Connection:
    """
    Initialize the database with schema and seed data.

    Args:
        db_path: Path to the SQLite database file. If None, uses Config.DB_PATH.

    Returns:
        Database connection with initialized schema.
    """
    conn = get_db_connection(db_path)

    # Import here to avoid circular imports
    from src.core.schema import create_schema
    from src.core.seed_data import insert_seed_data

    # Create schema
    create_schema(conn)

    # Insert seed data
    insert_seed_data(conn)

    return conn


def close_connection(conn: sqlite3.Connection) -> None:
    """
    Close the database connection properly.

    Args:
        conn: Database connection to close.
    """
    if conn:
        conn.close()


def backup_database(backup_path: str) -> None:
    """
    Create a backup of the database.

    Args:
        backup_path: Path where the backup will be saved.
    """
    source = sqlite3.connect(Config.DB_PATH)
    backup = sqlite3.connect(backup_path)

    try:
        source.backup(backup)
        print(f"Database backed up to: {backup_path}")
    finally:
        source.close()
        backup.close()
