"""URL query parameter helpers for Streamlit pages."""

from __future__ import annotations

from typing import Any, Dict, MutableMapping, Optional, Sequence, Union

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


def update_query_params(
    updates: Dict[str, Optional[Union[str, Sequence[str]]]],
) -> bool:
    """
    Bulk update arbitrary query parameters.

    Args:
        updates: Mapping of query parameter names to new values. ``None`` removes
            a parameter, while sequences set multi-value params.

    Returns:
        True when any value changed and the URL was updated.
    """

    normalized_updates: Dict[str, Optional[list[str]]] = {}
    for key, value in updates.items():
        normalized_updates[key] = _normalize_update_value(value)

    if not normalized_updates:
        return False

    if feature_flags.has("query_params") and hasattr(st, "query_params"):
        params = getattr(st, "query_params")
        if isinstance(params, MutableMapping):
            return _apply_updates_to_mapping(params, normalized_updates)

    getter = getattr(st, "experimental_get_query_params", None)
    setter = getattr(st, "experimental_set_query_params", None)
    if not callable(setter):
        return False

    try:
        existing = getter() if callable(getter) else {}
    except Exception:
        existing = {}

    changed = _apply_updates_to_dict(existing, normalized_updates)
    if not changed:
        return False

    try:
        setter(**existing)
        return True
    except Exception:
        return False


def _normalize_update_value(
    value: Optional[Union[str, Sequence[str]]]
) -> Optional[list[str]]:
    if value is None:
        return None

    if isinstance(value, str):
        cleaned = normalize_query_value(value)
        return [cleaned] if cleaned else None

    if isinstance(value, Sequence):
        values: list[str] = []
        for item in value:
            if item is None:
                continue
            as_text = normalize_query_value(item)
            if as_text:
                values.append(as_text)
        return values or None

    coerced = normalize_query_value(value)
    return [coerced] if coerced else None


def _apply_updates_to_mapping(
    params: MutableMapping[str, Any],
    updates: Dict[str, Optional[list[str]]],
) -> bool:
    changed = False
    for key, value in updates.items():
        if value is None:
            if key in params:
                try:
                    del params[key]
                except Exception:
                    params[key] = []  # type: ignore[assignment]
                changed = True
            continue

        current = _coerce_existing_value(params.get(key))
        if current == value:
            continue
        try:
            params[key] = value
        except Exception:
            continue
        changed = True
    return changed


def _apply_updates_to_dict(
    params: Dict[str, Any],
    updates: Dict[str, Optional[list[str]]],
) -> bool:
    changed = False
    for key, value in updates.items():
        if value is None:
            if key in params:
                params.pop(key, None)
                changed = True
            continue
        current = _coerce_existing_value(params.get(key))
        if current == value:
            continue
        params[key] = value
        changed = True
    return changed


def _coerce_existing_value(value: Any) -> Optional[list[str]]:
    if value is None:
        return None
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence):
        result: list[str] = []
        for item in value:
            if item is None:
                continue
            text = normalize_query_value(item)
            if text:
                result.append(text)
        return result or None
    text_value = normalize_query_value(value)
    return [text_value] if text_value else None


__all__ = ["normalize_query_value", "read_query_params", "set_query_param_flag", "update_query_params"]
