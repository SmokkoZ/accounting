"""URL query parameter helpers for Streamlit pages."""

from __future__ import annotations

from typing import Any, Dict, Optional

import streamlit as st

from src.ui.utils import feature_flags


def normalize_query_value(value: Any) -> Optional[str]:
    """
    Coerce Streamlit query param values into normalized strings.
    """
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        if not value:
            return None
        return str(value[0])
    return str(value)


def read_query_params() -> Dict[str, Any]:
    """
    Read the current query parameters using the best available API.
    """
    if feature_flags.has("query_params"):
        params = getattr(st, "query_params", None)
        if params is not None:
            try:
                return dict(params)
            except Exception:
                pass

    getter = getattr(st, "experimental_get_query_params", None)
    if callable(getter):
        try:
            return getter()
        except Exception:
            return {}
    return {}


def set_query_param_flag(key: str, enabled: bool) -> bool:
    """
    Toggle a boolean query parameter, returning True when the URL was updated.
    """
    target = "1" if enabled else None

    if feature_flags.has("query_params") and hasattr(st, "query_params"):
        try:
            params = st.query_params
            current = normalize_query_value(params.get(key))
            if target is None:
                if current is None:
                    return False
                del params[key]
                return True
            if current == target:
                return False
            params[key] = target
            return True
        except Exception:
            pass

    getter = getattr(st, "experimental_get_query_params", None)
    setter = getattr(st, "experimental_set_query_params", None)
    if not callable(setter):
        return False

    try:
        existing = getter() if callable(getter) else {}
        if target is None:
            if key not in existing:
                return False
            existing.pop(key, None)
        else:
            existing[key] = target
        setter(**existing)
        return True
    except Exception:
        return False


__all__ = ["normalize_query_value", "read_query_params", "set_query_param_flag"]
