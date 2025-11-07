"""
Synthetic benchmark generator for Story 8.9 performance targets.

The script seeds a lightweight SQLite database with 10k bet rows,
executes the same cached queries used by the UI, and captures timing
metrics so we can keep filters + pagination under the 1.5s budget.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from src.ui.cache import (
    invalidate_connection_cache,
    invalidate_query_cache,
    query_df,
)

BENCHMARK_ROW_COUNT = 10_000
TARGET_FILTER_SECONDS = 1.5
TARGET_PAGINATION_SECONDS = 0.5

BASE_SQL = """
SELECT id, status, created_at_utc, sport
FROM bets
WHERE status = ?
ORDER BY created_at_utc DESC
"""


@dataclass(slots=True)
class BenchmarkResult:
    filter_duration: float
    pagination_duration: float
    rows_seeded: int


def seed_benchmark_dataset(db_path: Path, total_rows: int = BENCHMARK_ROW_COUNT) -> str:
    """
    Create a benchmark database with ``total_rows`` bet entries.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bets (
            id INTEGER PRIMARY KEY,
            status TEXT NOT NULL,
            created_at_utc TEXT NOT NULL,
            sport TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_bets_status_created "
        "ON bets(status, created_at_utc DESC);"
    )

    existing = conn.execute("SELECT COUNT(1) FROM bets").fetchone()[0]
    if existing < total_rows:
        rows_to_insert = total_rows - existing
        batch: list[tuple[str, str, str]] = []
        now = time.time()
        for idx in range(existing + 1, total_rows + 1):
            status = "incoming" if idx % 2 == 0 else "verified"
            created = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - idx))
            sport = "soccer" if idx % 3 == 0 else "basketball"
            batch.append((status, created, sport))
            if len(batch) == 1000:
                conn.executemany(
                    "INSERT INTO bets(status, created_at_utc, sport) VALUES (?, ?, ?)",
                    batch,
                )
                batch.clear()
        if batch:
            conn.executemany(
                "INSERT INTO bets(status, created_at_utc, sport) VALUES (?, ?, ?)",
                batch,
            )
        conn.commit()

    conn.close()
    return str(db_path)


def _time_query(sql: str, params: Sequence[object], *, db_path: str) -> tuple[float, int]:
    invalidate_query_cache()
    start = time.perf_counter()
    df = query_df(sql, params=params, db_path=db_path)
    duration = time.perf_counter() - start
    return duration, len(df)


def benchmark_filters(db_path: str, *, status: str = "incoming") -> float:
    sql = f"{BASE_SQL} LIMIT 25"
    duration, row_count = _time_query(sql, (status,), db_path=db_path)
    if row_count < 1:
        raise RuntimeError("Benchmark dataset did not return any rows.")
    return duration


def benchmark_paginated_reads(
    db_path: str,
    *,
    pages: int = 5,
    page_size: int = 100,
    status: str = "incoming",
) -> float:
    total_duration = 0.0
    sql = f"{BASE_SQL} LIMIT ? OFFSET ?"
    for page in range(pages):
        offset = page * page_size
        duration, _ = _time_query(sql, (status, page_size, offset), db_path=db_path)
        total_duration += duration
    return total_duration


def run_benchmark(db_path: str) -> BenchmarkResult:
    """
    Execute the benchmark queries and return timing stats.
    """
    invalidate_connection_cache()
    invalidate_query_cache()

    filter_duration = benchmark_filters(db_path)
    pagination_duration = benchmark_paginated_reads(db_path)
    rows = _count_rows(db_path)

    return BenchmarkResult(
        filter_duration=filter_duration,
        pagination_duration=pagination_duration,
        rows_seeded=rows,
    )


def _count_rows(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(1) FROM bets").fetchone()[0]
    conn.close()
    return int(count)


def _format_result(result: BenchmarkResult) -> str:
    return (
        f"- Rows Seeded: {result.rows_seeded}\n"
        f"- Filter Query: {result.filter_duration:.3f}s "
        f"(target {TARGET_FILTER_SECONDS:.2f}s)\n"
        f"- Pagination Windows: {result.pagination_duration:.3f}s "
        f"(target {TARGET_PAGINATION_SECONDS:.2f}s)\n"
    )


def main(path: str | None = None) -> None:
    db_path = Path(path or "data/benchmark/benchmark.db")
    resolved = seed_benchmark_dataset(db_path)
    result = run_benchmark(resolved)
    print("Benchmark completed:\n")
    print(_format_result(result))

    if result.filter_duration > TARGET_FILTER_SECONDS:
        print("WARNING: Filter benchmark exceeded target.")
    if result.pagination_duration > TARGET_PAGINATION_SECONDS:
        print("WARNING: Pagination benchmark exceeded target.")


if __name__ == "__main__":
    main()
