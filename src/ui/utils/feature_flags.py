"""
Feature detection helpers for Streamlit capabilities.

This wraps ``hasattr(st, ...)`` checks so that the rest of the UI can
condition behaviour on the availability of newer Streamlit APIs while
keeping fallback paths for older runtimes (1.30+ baseline).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Dict

import streamlit as st


@lru_cache(maxsize=1)
def _compute_feature_matrix() -> Dict[str, bool]:
    """Return a cached mapping of supported feature names to booleans."""
    candidates = (
        "fragment",
        "dialog",
        "popover",
        "navigation",
        "page_link",
        "write_stream",
        "pdf",
        "status",
        "toast",
    )

    return {name: bool(getattr(st, name, None)) for name in candidates}


def has(name: str) -> bool:
    """Check whether a given Streamlit feature exists."""
    return bool(_compute_feature_matrix().get(name, False))


def supports_dialogs() -> bool:
    """Return True when the current runtime exposes dialog support."""
    return has("dialog")


def supports_popovers() -> bool:
    """Return True when the current runtime exposes popover support."""
    return has("popover")


def all_flags() -> Dict[str, bool]:
    """Expose a copy of the feature matrix for debugging."""
    return dict(_compute_feature_matrix())


__all__ = ["has", "all_flags", "supports_dialogs", "supports_popovers"]
