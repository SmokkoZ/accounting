"""
Date and time utilities for the Surebet Accounting System.

This module provides helper functions for consistent datetime handling.
"""

from datetime import datetime, timezone
from typing import Optional


def utc_now_iso() -> str:
    """
    Return current UTC time as ISO8601 with Z suffix.

    Returns:
        Current UTC time in ISO8601 format with 'Z' suffix.
        Example: "2025-10-29T14:30:00.123456Z"
    """
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_utc_iso(iso_string: str) -> datetime:
    """
    Parse ISO8601 string with Z suffix to datetime object.

    Args:
        iso_string: ISO8601 string with 'Z' suffix.

    Returns:
        Datetime object in UTC timezone.
    """
    # Replace Z with +00:00 for proper parsing
    if iso_string.endswith("Z"):
        iso_string = iso_string[:-1] + "+00:00"

    return datetime.fromisoformat(iso_string)


def format_utc_iso(dt: datetime) -> str:
    """
    Format datetime object as ISO8601 with Z suffix.

    Args:
        dt: Datetime object (will be converted to UTC if not already).

    Returns:
        ISO8601 string with 'Z' suffix.
    """
    # Convert to UTC if not already
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)

    return dt.isoformat().replace("+00:00", "Z")


def get_date_string(dt: Optional[datetime] = None) -> str:
    """
    Get date string in YYYY-MM-DD format.

    Args:
        dt: Datetime object. If None, uses current UTC time.

    Returns:
        Date string in YYYY-MM-DD format.
    """
    if dt is None:
        dt = datetime.now(timezone.utc)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)

    return dt.strftime("%Y-%m-%d")
