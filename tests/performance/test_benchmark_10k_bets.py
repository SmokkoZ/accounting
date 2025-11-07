"""
Synthetic benchmark tests validating Story 8.9 budgets.
"""

from __future__ import annotations

from pathlib import Path

from scripts.benchmark_10k_bets import (
    BENCHMARK_ROW_COUNT,
    TARGET_FILTER_SECONDS,
    TARGET_PAGINATION_SECONDS,
    run_benchmark,
    seed_benchmark_dataset,
)
from src.ui.cache import invalidate_connection_cache, invalidate_query_cache


def test_benchmark_runs_under_targets(tmp_path):
    db_path = tmp_path / "bench.db"
    resolved = seed_benchmark_dataset(db_path)
    result = run_benchmark(resolved)

    assert result.rows_seeded == BENCHMARK_ROW_COUNT
    assert result.filter_duration < TARGET_FILTER_SECONDS
    assert result.pagination_duration < TARGET_PAGINATION_SECONDS


def test_benchmark_seed_is_idempotent(tmp_path):
    db_path = tmp_path / "bench.db"
    resolved = seed_benchmark_dataset(db_path, total_rows=1_000)
    # Second seed should not duplicate rows.
    seed_benchmark_dataset(Path(resolved), total_rows=1_000)

    result = run_benchmark(resolved)
    assert result.rows_seeded == 1_000

    # Clean caches for subsequent tests.
    invalidate_connection_cache()
    invalidate_query_cache()
