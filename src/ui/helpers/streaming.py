"""
Streaming, progress, and notification helpers for the Streamlit UI layer.

This module centralises ``st.write_stream`` fallbacks, ``st.status`` handling,
toast notifications, PDF previews, and reusable error/retry controls so that
individual pages stay lean.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator, List, Optional, Tuple, Union

import streamlit as st

from src.ui.utils import feature_flags
from src.ui.utils.state_management import safe_rerun

StepCallback = Callable[[], None]
StepSpec = Union[str, Tuple[str, Optional[StepCallback]]]


def has_feature(name: str) -> bool:
    """Expose feature flag helper referenced by story docs."""
    return feature_flags.has(name)


def stream_with_fallback(
    source: Union[Callable[[], Iterable[str]], Iterable[str]],
    header: Optional[str] = None,
    *,
    placeholder=None,
) -> List[str]:
    """
    Stream text chunks using ``st.write_stream`` when available, otherwise fallback.

    Args:
        source: Generator function or iterable yielding text chunks.
        header: Optional caption shown above the stream.
        placeholder: Optional placeholder to reuse for fallback rendering.

    Returns:
        List of emitted chunks (useful for tests/logging).
    """

    iterator = source() if callable(source) else source
    emitted: List[str] = []

    if header:
        st.caption(header)

    if has_feature("write_stream"):

        def _wrapped() -> Iterator[str]:
            for chunk in iterator:
                emitted.append(chunk)
                yield chunk

        st.write_stream(_wrapped())
        return emitted

    holder = placeholder or st.empty()
    lines: List[str] = []
    for chunk in iterator:
        emitted.append(chunk)
        lines.append(chunk)
        holder.markdown("\n".join(lines))
    return emitted


@dataclass
class _StatusContext:
    """Internal adapter to normalise ``st.status`` and fallback rendering."""

    status_obj: Optional[object]
    title: str
    fallback_container: Optional[object] = None

    def write(self, message: str) -> None:
        if self.status_obj:
            self.status_obj.write(message)
        else:
            st.write(f"- {message}")

    def update(self, label: str, state: str = "running") -> None:
        if self.status_obj and hasattr(self.status_obj, "update"):
            self.status_obj.update(label=label, state=state)
        else:
            icon = {
                "running": ":material/sync:",
                "complete": ":material/task_alt:",
                "error": ":material/error:",
            }.get(state, ":material/info:")
            st.info(f"{icon} {label}")


def _iter_steps(steps: Iterable[StepSpec]) -> Iterator[Tuple[str, Optional[StepCallback]]]:
    for step in steps:
        if isinstance(step, tuple):
            yield step[0], step[1]
        else:
            yield step, None


def status_with_steps(
    title: str,
    steps: Iterable[StepSpec],
    *,
    expanded: bool = True,
) -> Iterator[str]:
    """
    Display a status block and yield step labels as they execute.

    Args:
        title: Status title (e.g., "Ledger export").
        steps: Sequence of labels or (label, callback) pairs.
        expanded: Whether the status block is expanded by default.

    Yields:
        Each step label after its optional callback executes.
    """

    status_ctx: _StatusContext
    status_cm = None
    if has_feature("status"):
        status_cm = st.status(title, expanded=expanded)
        status_ctx = _StatusContext(status_obj=status_cm.__enter__(), title=title)
    else:
        st.info(f":material/info: {title}")
        status_ctx = _StatusContext(status_obj=None, title=title)

    try:
        for label, callback in _iter_steps(list(steps)):
            status_ctx.write(label)
            if callback:
                callback()
            yield label
        status_ctx.update(f"{title} complete", state="complete")
    finally:
        if status_cm is not None:
            status_cm.__exit__(None, None, None)


def show_success_toast(message: str) -> None:
    """Display a success toast with fallback."""
    if has_feature("toast"):
        st.toast(message, icon="✅")
    else:
        st.success(message)


def show_error_toast(message: str) -> None:
    """Display an error toast with fallback."""
    if has_feature("toast"):
        st.toast(message, icon="⚠️")
    else:
        st.error(message)


def show_info_toast(message: str) -> None:
    """Display an informational toast with fallback."""
    if has_feature("toast"):
        st.toast(message, icon="💡")
    else:
        st.info(message)


def handle_streaming_error(
    error: Exception,
    operation: str,
    retry_func: Optional[Callable[[], None]] = None,
    *,
    key: Optional[str] = None,
) -> None:
    """
    Render a consistent error block with optional retry controls.

    Args:
        error: Exception that occurred.
        operation: Human-readable operation name (e.g., "OCR processing").
        retry_func: Optional callable to retry the operation inline.
        key: Optional key suffix to disambiguate buttons.
    """

    safe_key = (key or operation.replace(" ", "_")).lower()
    st.error(f"Error during {operation}: {error}")

    if not retry_func:
        return

    retry_label = f":material/restart_alt: Retry {operation}"
    cancel_label = ":material/close: Cancel"

    if st.button(retry_label, key=f"{safe_key}_retry"):
        try:
            retry_func()
            show_success_toast(f"{operation} completed successfully!")
            safe_rerun()
        except Exception as retry_error:  # pragma: no cover - defensive
            st.error(f"Retry failed: {retry_error}")

    if st.button(cancel_label, key=f"{safe_key}_cancel"):
        st.warning(f"{operation} cancelled")


def show_pdf_preview(
    file_path: Union[str, Path],
    *,
    height: int = 600,
    fallback_message: str = "PDF preview not available.",
) -> bool:
    """
    Display a PDF preview via ``st.pdf`` with download fallback.

    Args:
        file_path: Path to the PDF file.
        height: Viewer height.
        fallback_message: Message when ``st.pdf`` is unavailable.

    Returns:
        True when preview succeeds, False otherwise.
    """

    pdf_path = Path(file_path)
    if not pdf_path.exists():
        st.warning(f"PDF file not found: {pdf_path}")
        return False

    if has_feature("pdf"):
        st.pdf(str(pdf_path), height=height)
        return True

    st.info(fallback_message)
    with open(pdf_path, "rb") as pdf_bytes:
        st.download_button(
            label=":material/picture_as_pdf: Download PDF",
            data=pdf_bytes.read(),
            file_name=pdf_path.name,
            mime="application/pdf",
        )
    return False


__all__ = [
    "handle_streaming_error",
    "has_feature",
    "show_error_toast",
    "show_info_toast",
    "show_pdf_preview",
    "show_success_toast",
    "status_with_steps",
    "stream_with_fallback",
]
