"""
Tests for Streamlit caching helpers.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from src.core.config import Config
from src.ui import cache


def _setup_db(tmp_path: Path) -> str:
    db_path = tmp_path / "cache_test.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE bets (id INTEGER PRIMARY KEY, status TEXT)")
    conn.executemany(
        "INSERT INTO bets(status) VALUES (?)",
        [("incoming",), ("verified",)],
    )
    conn.commit()
    conn.close()
    return str(db_path)


def test_get_cached_connection_reuses_instance(tmp_path):
    db_path = _setup_db(tmp_path)
    cache.invalidate_connection_cache()

    conn1 = cache.get_cached_connection(db_path)
    conn2 = cache.get_cached_connection(db_path)
    assert conn1 is conn2

    cache.invalidate_connection_cache([db_path])
    conn3 = cache.get_cached_connection(db_path)
    assert conn3 is not conn1

    cache.invalidate_connection_cache([db_path])


def test_query_df_cache_and_invalidation(tmp_path):
    db_path = _setup_db(tmp_path)
    original_db_path = Config.DB_PATH
    Config.DB_PATH = db_path

    try:
        cache.invalidate_connection_cache()
        cache.invalidate_query_cache()

        first = cache.query_df("SELECT COUNT(*) AS total_rows FROM bets")
        assert int(first.iloc[0]["total_rows"]) == 2

        with sqlite3.connect(db_path) as conn:
            conn.execute("INSERT INTO bets(status) VALUES (?)", ("incoming",))
            conn.commit()

        cached = cache.query_df("SELECT COUNT(*) AS total_rows FROM bets")
        assert int(cached.iloc[0]["total_rows"]) == 2

        cache.invalidate_query_cache()
        updated = cache.query_df("SELECT COUNT(*) AS total_rows FROM bets")
        assert int(updated.iloc[0]["total_rows"]) == 3
    finally:
        Config.DB_PATH = original_db_path
        cache.invalidate_connection_cache([db_path])
        cache.invalidate_query_cache()
