"""
Unit tests for pagination helpers.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from src.core.config import Config
from src.ui.cache import invalidate_connection_cache, invalidate_query_cache
from src.ui.utils.pagination import Pagination, apply_pagination, get_total_count, paginate_params


def test_pagination_math_properties():
    pagination = Pagination(table_key="bets", page=2, page_size=50, total_rows=120)
    assert pagination.limit == 50
    assert pagination.offset == 50
    assert pagination.total_pages == 3
    assert pagination.start_row == 51
    assert pagination.end_row == 100
    assert pagination.has_prev
    assert pagination.has_next


def test_apply_pagination_and_params():
    pagination = Pagination(table_key="ledger", page=4, page_size=25, total_rows=500)
    sql, extra = apply_pagination("SELECT * FROM ledger ORDER BY created_at DESC", pagination)
    assert sql.endswith("LIMIT ? OFFSET ?")
    assert extra == (25, 75)

    params = paginate_params(("approved",), pagination)
    assert params == ("approved", 25, 75)


def test_get_total_count(tmp_path):
    db_path = _make_db(tmp_path)
    original_db_path = Config.DB_PATH
    Config.DB_PATH = db_path

    try:
        invalidate_connection_cache()
        invalidate_query_cache()
        total = get_total_count("SELECT COUNT(*) FROM bets")
        assert total == 2
    finally:
        Config.DB_PATH = original_db_path
        invalidate_connection_cache([db_path])
        invalidate_query_cache()


def _make_db(tmp_path: Path) -> str:
    db_file = tmp_path / "pagination.db"
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE bets(id INTEGER PRIMARY KEY, status TEXT)")
    conn.executemany(
        "INSERT INTO bets(status) VALUES (?)",
        [("incoming",), ("verified",)],
    )
    conn.commit()
    conn.close()
    return str(db_file)
