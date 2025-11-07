"""
Caching utilities for Streamlit UI pages.

Provides shared helpers for reusing database connections and caching
read-heavy queries via ``st.cache_resource`` / ``st.cache_data`` with
safe fallbacks for non-Streamlit execution contexts (e.g., tests).
"""

from __future__ import annotations

import sqlite3
from functools import lru_cache, wraps
from typing import Any, Dict, Iterable, Sequence, Tuple

import pandas as pd
import streamlit as st

from src.core.config import Config
from src.core.database import get_db_connection

QUERY_TTL_SECONDS = 5
_ACTIVE_CONNECTIONS: Dict[str, sqlite3.Connection] = {}


def _fallback_cache(maxsize: int | None = None):
    """
    Provide a simple ``lru_cache`` decorator with a ``clear`` helper.
    """

    def decorator(func):
        cached = lru_cache(maxsize=maxsize)(func)

        @wraps(func)
        def wrapper(*args, **kwargs):
            return cached(*args, **kwargs)

        wrapper.clear = cached.cache_clear  # type: ignore[attr-defined]
        return wrapper

    return decorator


def _cache_data(ttl: int):
    cache_data = getattr(st, "cache_data", None)
    if callable(cache_data):
        try:
            return cache_data(ttl=ttl, show_spinner=False)
        except Exception:
            # Fall back below if Streamlit caching is unavailable (e.g., tests)
            pass
    return _fallback_cache(maxsize=64)


def _cache_resource():
    cache_resource = getattr(st, "cache_resource", None)
    if callable(cache_resource):
        try:
            return cache_resource(show_spinner=False)
        except Exception:
            pass
    return _fallback_cache(maxsize=None)


def _connection_key(db_path: str | None) -> str:
    return db_path or Config.DB_PATH


@_cache_resource()
def get_cached_connection(db_path: str | None = None) -> sqlite3.Connection:
    """
    Return a cached SQLite connection (per database path).
    """
    key = _connection_key(db_path)
    conn = get_db_connection(db_path)
    _ACTIVE_CONNECTIONS[key] = conn
    return conn


@_cache_data(QUERY_TTL_SECONDS)
def _query_df_cached(sql: str, params: Tuple[Any, ...], db_path: str) -> pd.DataFrame:
    """
    Internal cached query runner. Arguments must remain hashable.
    """
    conn = get_cached_connection(db_path)
    return pd.read_sql_query(sql, conn, params=params)


def query_df(sql: str, params: Sequence[Any] | None = None, *, db_path: str | None = None) -> pd.DataFrame:
    """
    Execute ``sql`` with optional parameters and return a cached DataFrame.
    """
    normalized_params: Tuple[Any, ...] = tuple(params or ())
    target_db = _connection_key(db_path)
    return _query_df_cached(sql, normalized_params, target_db)


def invalidate_query_cache() -> None:
    """
    Clear cached DataFrame results (e.g., after writes).
    """
    clear = getattr(_query_df_cached, "clear", None)
    if callable(clear):
        clear()


def invalidate_connection_cache(paths: Iterable[str] | None = None) -> None:
    """
    Clear cached database connections (optionally filtered by DB path).
    """
    clear = getattr(get_cached_connection, "clear", None)
    if not callable(clear):
        return

    if paths is None:
        targets = list(_ACTIVE_CONNECTIONS.keys())
    else:
        targets = [_connection_key(path) for path in paths]

    for key in targets:
        conn = _ACTIVE_CONNECTIONS.pop(key, None)
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    clear()


__all__ = [
    "QUERY_TTL_SECONDS",
    "get_cached_connection",
    "invalidate_connection_cache",
    "invalidate_query_cache",
    "query_df",
]
