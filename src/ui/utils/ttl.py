"""
Helpers for TTL countdown formatting and state classification.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from src.utils.datetime_helpers import parse_utc_iso

EXPIRY_WARNING_THRESHOLD_SECONDS = 120


class TTLState(str, Enum):
    """Visual treatment for TTL countdowns."""

    ACTIVE = "active"
    WARNING = "warning"
    EXPIRED = "expired"


def compute_ttl_seconds(expires_at_iso: str, *, now: Optional[datetime] = None) -> int:
    """Return the remaining TTL in whole seconds."""
    expires_at = parse_utc_iso(expires_at_iso)
    current = now or datetime.now(timezone.utc)
    return int((expires_at - current).total_seconds())


def classify_ttl(ttl_seconds: int, *, warning_threshold: int = EXPIRY_WARNING_THRESHOLD_SECONDS) -> TTLState:
    """Classify TTL for styling."""
    if ttl_seconds <= 0:
        return TTLState.EXPIRED
    if ttl_seconds <= warning_threshold:
        return TTLState.WARNING
    return TTLState.ACTIVE


def format_ttl_label(ttl_seconds: int) -> str:
    """Format TTL as HH:MM:SS or 'Expired'."""
    if ttl_seconds <= 0:
        return "Expired"
    seconds = ttl_seconds
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


__all__ = ["TTLState", "compute_ttl_seconds", "classify_ttl", "format_ttl_label"]
