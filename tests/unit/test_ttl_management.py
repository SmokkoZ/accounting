from datetime import datetime, timedelta, timezone

from src.ui.utils.ttl import (
    TTLState,
    classify_ttl,
    compute_ttl_seconds,
    format_ttl_label,
)


def _iso(dt: datetime) -> str:
    return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def test_compute_ttl_seconds_handles_future_and_past():
    reference = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    future = reference + timedelta(seconds=90)
    past = reference - timedelta(seconds=45)

    assert compute_ttl_seconds(_iso(future), now=reference) == 90
    assert compute_ttl_seconds(_iso(past), now=reference) == -45


def test_classify_ttl_transitions():
    assert classify_ttl(200) == TTLState.ACTIVE
    assert classify_ttl(90) == TTLState.WARNING
    assert classify_ttl(0) == TTLState.EXPIRED
    assert classify_ttl(-5) == TTLState.EXPIRED


def test_format_ttl_label_formats_hours_minutes_seconds():
    assert format_ttl_label(65) == "01:05"
    assert format_ttl_label(0) == "Expired"
    assert format_ttl_label(-10) == "Expired"
    assert format_ttl_label(3665) == "1:01:05"
