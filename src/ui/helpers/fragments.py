"""
Fragment helpers wrapping Streamlit's ``st.fragment`` API with graceful fallbacks.

This module centralises fragment feature detection, instrumentation, and
performance diagnostics so individual pages can opt in to partial reruns
without duplicating boilerplate.
"""

from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, TypeVar

import streamlit as st

from src.ui.utils import feature_flags

R = TypeVar("R")

_DEBUG_SESSION_KEY = "ui.debug_performance"
_FRAGMENT_HISTORY_LIMIT = 120


class FragmentTimer:
    """Collect execution timing metrics for fragment render functions."""

    def __init__(self) -> None:
        self._timings: Dict[str, List[float]] = {}

    @contextlib.contextmanager
    def time_fragment(self, fragment_name: str) -> Iterable[None]:
        """Measure execution time for a fragment render block."""
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - start
            timings = self._timings.setdefault(fragment_name, [])
            timings.append(elapsed)
            if len(timings) > _FRAGMENT_HISTORY_LIMIT:
                del timings[0]

    def get_stats(self) -> Dict[str, Dict[str, float]]:
        """Return aggregated timing metrics per fragment."""
        stats: Dict[str, Dict[str, float]] = {}
        for name, durations in self._timings.items():
            if not durations:
                continue
            total = sum(durations)
            stats[name] = {
                "count": float(len(durations)),
                "total": total,
                "avg": total / len(durations),
                "min": min(durations),
                "max": max(durations),
                "last": durations[-1],
            }
        return stats

    def clear(self) -> None:
        """Reset all collected timing metrics."""
        self._timings.clear()


fragment_timer = FragmentTimer()


def fragments_supported() -> bool:
    """Return True when the current runtime exposes ``st.fragment``."""
    return feature_flags.has("fragment")


def is_debug_enabled() -> bool:
    """Return whether performance debug mode is currently enabled."""
    return bool(st.session_state.get(_DEBUG_SESSION_KEY, False))


def render_debug_toggle(label: str = "Show performance debug") -> bool:
    """Render a toggle for fragment performance diagnostics."""
    if _DEBUG_SESSION_KEY not in st.session_state:
        st.session_state[_DEBUG_SESSION_KEY] = False
    value = st.checkbox(
        label,
        value=bool(st.session_state[_DEBUG_SESSION_KEY]),
        key=_DEBUG_SESSION_KEY,
        help="Display fragment timing statistics for troubleshooting.",
    )
    return value


def render_debug_panel(expanded: bool = False) -> None:
    """Render performance diagnostics if debug mode is enabled."""
    if not is_debug_enabled():
        return

    stats = fragment_timer.get_stats()
    with st.expander("Performance Debug", expanded=expanded):
        if not stats:
            st.write("No fragment timings recorded yet.")
            return

        for fragment_name, data in stats.items():
            st.markdown(f"**{fragment_name}**")
            st.write(
                f"- Calls: {int(data['count'])}\n"
                f"- Last: {data['last']:.3f}s\n"
                f"- Avg: {data['avg']:.3f}s\n"
                f"- Min: {data['min']:.3f}s\n"
                f"- Max: {data['max']:.3f}s\n"
                f"- Total: {data['total']:.3f}s"
            )


def clear_debug_metrics() -> None:
    """Clear accumulated fragment timing statistics."""
    fragment_timer.clear()


def fragment(name: str, *, run_every: Optional[int] = None) -> Callable[[Callable[..., R]], Callable[..., R]]:
    """
    Decorator that wraps a render function in ``st.fragment`` when available.

    The wrapped function records performance metrics regardless of fragment
    support so debug tooling remains consistent across fallbacks.
    """

    def decorator(func: Callable[..., R]) -> Callable[..., R]:
        def instrumented(*args: Any, **kwargs: Any) -> R:
            with fragment_timer.time_fragment(name):
                result = func(*args, **kwargs)
            return result

        if not fragments_supported():
            return instrumented

        try:
            fragment_decorator = st.fragment if run_every is None else st.fragment(run_every=run_every)
        except TypeError:
            fragment_decorator = st.fragment

        return fragment_decorator(instrumented)

    return decorator


def call_fragment(
    name: str,
    render_fn: Callable[..., R],
    *,
    run_every: Optional[int] = None,
    **kwargs: Any,
) -> Optional[R]:
    """
    Convenience wrapper that executes a fragment render function immediately.

    This helper is useful for inline fragment definitions without explicit
    decorators.
    """

    @fragment(name, run_every=run_every)
    def _fragment_wrapper() -> R:
        return render_fn(**kwargs)

    return _fragment_wrapper()


@dataclass(frozen=True)
class FragmentContext:
    """Metadata passed to render callbacks when additional state is useful."""

    name: str
    run_every: Optional[int] = None


__all__ = [
    "FragmentContext",
    "call_fragment",
    "clear_debug_metrics",
    "fragment",
    "fragment_timer",
    "fragments_supported",
    "is_debug_enabled",
    "render_debug_panel",
    "render_debug_toggle",
]
