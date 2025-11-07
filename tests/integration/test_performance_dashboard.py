"""
Integration-style tests for the performance dashboard helpers.
"""

from __future__ import annotations

import pandas as pd

from src.ui.utils.performance_dashboard import (
    PerformanceSummary,
    prepare_recent_timings,
    summarize_timings,
)


def test_prepare_recent_timings_formats_dataframe():
    timings = [
        {"timestamp": 1_700_000_000, "label": "incoming_queue", "duration": 0.2},
        {"timestamp": 1_700_000_100, "label": "surebets_overview", "duration": 0.4},
    ]
    df = prepare_recent_timings(timings, limit=1)
    assert list(df.columns) == ["Time", "Fragment / Page", "Duration (s)"]
    assert len(df) == 1
    assert df.iloc[0]["Fragment / Page"] == "surebets_overview"


def test_summarize_timings_returns_aggregates():
    df = pd.DataFrame(
        {
            "Time": pd.date_range("2025-11-01", periods=3, freq="s"),
            "Fragment / Page": ["a", "b", "c"],
            "Duration (s)": [0.1, 0.2, 0.05],
        }
    )
    summary = summarize_timings(df)
    assert isinstance(summary, PerformanceSummary)
    assert summary.sample_count == 3
    assert summary.slowest_seconds == 0.2
