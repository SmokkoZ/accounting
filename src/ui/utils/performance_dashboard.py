"""
Pure helpers for rendering the Performance Dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

import pandas as pd


@dataclass(slots=True)
class PerformanceSummary:
    average_seconds: float
    slowest_seconds: float
    fastest_seconds: float
    sample_count: int


def prepare_recent_timings(timings: Iterable[Mapping[str, float]], limit: int = 50) -> pd.DataFrame:
    """
    Convert raw timing dictionaries into a normalized DataFrame.
    """
    records = list(timings)
    if not records:
        return pd.DataFrame(columns=["Time", "Fragment / Page", "Duration (s)"])

    df = pd.DataFrame(records)
    df = df.tail(limit).copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
    df = df.rename(
        columns={
            "timestamp": "Time",
            "label": "Fragment / Page",
            "duration": "Duration (s)",
        }
    )
    return df[["Time", "Fragment / Page", "Duration (s)"]]


def summarize_timings(df: pd.DataFrame) -> PerformanceSummary:
    """
    Calculate aggregate metrics for the dashboard cards.
    """
    if df.empty:
        return PerformanceSummary(0.0, 0.0, 0.0, 0)

    durations = df["Duration (s)"]
    return PerformanceSummary(
        average_seconds=float(durations.mean()),
        slowest_seconds=float(durations.max()),
        fastest_seconds=float(durations.min()),
        sample_count=len(df),
    )


__all__ = ["PerformanceSummary", "prepare_recent_timings", "summarize_timings"]
