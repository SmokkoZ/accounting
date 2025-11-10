from __future__ import annotations

"""Aggregated metrics powering the dashboard cards."""

from dataclasses import dataclass
from typing import Optional

from src.ui.cache import query_df
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class IncomingQueueCounters:
    """Counters sourced from the Incoming Bets queue."""

    waiting: Optional[int]
    approved_today: Optional[int]


@dataclass(frozen=True)
class DashboardMetricSnapshot:
    """Complete snapshot of dashboard metrics."""

    waiting_incoming: Optional[int]
    approved_today: Optional[int]
    open_surebets: Optional[int]
    pending_settlements: Optional[int]

    def has_failures(self) -> bool:
        """Return True when any metric failed to resolve."""
        return any(
            value is None
            for value in (
                self.waiting_incoming,
                self.approved_today,
                self.open_surebets,
                self.pending_settlements,
            )
        )


def _safe_int(value: object) -> Optional[int]:
    """Convert a scalar into an int, returning 0 for NULLs."""
    if value is None:
        return 0
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return 0
        value = stripped
    try:
        # ``int`` handles bools/ints; fall back to float for SQLite sums.
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            logger.warning("dashboard_metrics_invalid_scalar", value=value)
            return None


def _run_scalar_query(
    sql: str,
    column: str,
    *,
    db_path: str | None = None,
) -> Optional[int]:
    """Execute ``sql`` and coerce the first column into an int."""
    try:
        df = query_df(sql, db_path=db_path)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error(
            "dashboard_metrics_query_failed",
            sql=sql.strip(),
            error=str(exc),
        )
        return None

    if df.empty:
        return 0

    row = df.iloc[0]
    return _safe_int(row.get(column))


def get_incoming_queue_counters(*, db_path: str | None = None) -> IncomingQueueCounters:
    """Return waiting + approved counts sourced from Incoming Bets page."""
    sql = """
        SELECT
            SUM(CASE WHEN status='incoming' THEN 1 ELSE 0 END) as waiting,
            SUM(
                CASE
                    WHEN status='verified'
                         AND date(updated_at_utc)=date('now') THEN 1
                    ELSE 0
                END
            ) as approved_today
        FROM bets
    """
    try:
        df = query_df(sql, db_path=db_path)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("dashboard_metrics_incoming_failed", error=str(exc))
        return IncomingQueueCounters(waiting=None, approved_today=None)

    if df.empty:
        return IncomingQueueCounters(waiting=0, approved_today=0)

    row = df.iloc[0]
    waiting = _safe_int(row.get("waiting"))
    approved_today = _safe_int(row.get("approved_today"))
    return IncomingQueueCounters(waiting=waiting, approved_today=approved_today)


def get_open_surebets_count(*, db_path: str | None = None) -> Optional[int]:
    """Count open surebets (Surebets page)."""
    sql = """SELECT COUNT(*) AS cnt FROM surebets WHERE status = 'open'"""
    return _run_scalar_query(sql, "cnt", db_path=db_path)


def get_pending_settlement_bets_count(*, db_path: str | None = None) -> Optional[int]:
    """Count verified/matched bets awaiting settlement (Settlement nav)."""
    sql = """
        SELECT COUNT(*) AS cnt
        FROM bets
        WHERE status IN ('verified', 'matched')
    """
    return _run_scalar_query(sql, "cnt", db_path=db_path)


def load_dashboard_metrics(*, db_path: str | None = None) -> DashboardMetricSnapshot:
    """Return the aggregated dashboard metrics snapshot."""
    incoming = get_incoming_queue_counters(db_path=db_path)
    return DashboardMetricSnapshot(
        waiting_incoming=incoming.waiting,
        approved_today=incoming.approved_today,
        open_surebets=get_open_surebets_count(db_path=db_path),
        pending_settlements=get_pending_settlement_bets_count(db_path=db_path),
    )


__all__ = [
    "DashboardMetricSnapshot",
    "IncomingQueueCounters",
    "get_incoming_queue_counters",
    "get_open_surebets_count",
    "get_pending_settlement_bets_count",
    "load_dashboard_metrics",
]
