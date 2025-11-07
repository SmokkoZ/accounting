"""
Media helpers for lightweight previews.

Provides cached thumbnail generation so image-heavy tables can render
quick previews while still offering full-size expanders on demand.
"""

from __future__ import annotations

from functools import lru_cache, wraps
from io import BytesIO
from pathlib import Path
from typing import Optional

from PIL import Image, UnidentifiedImageError
import streamlit as st

THUMB_CACHE_TTL = 3600  # seconds


def _cache_data(ttl: int):
    cache_data = getattr(st, "cache_data", None)
    if callable(cache_data):
        try:
            return cache_data(ttl=ttl, show_spinner=False)
        except Exception:
            pass

    def decorator(func):
        cached = lru_cache(maxsize=256)(func)

        @wraps(func)
        def wrapper(*args, **kwargs):
            return cached(*args, **kwargs)

        wrapper.clear = cached.cache_clear  # type: ignore[attr-defined]
        return wrapper

    return decorator


def _resample_mode():
    resampling = getattr(Image, "Resampling", None)
    if resampling and hasattr(resampling, "LANCZOS"):
        return resampling.LANCZOS
    return getattr(Image, "LANCZOS", Image.BICUBIC)


@_cache_data(THUMB_CACHE_TTL)
def _render_thumbnail(path_str: str, width: int) -> Optional[bytes]:
    path = Path(path_str)
    if not path.exists():
        return None

    try:
        with Image.open(path) as img:
            if img.width == 0:
                return None
            ratio = width / float(img.width)
            height = max(1, int(img.height * ratio))
            thumbnail = img.copy()
            thumbnail.thumbnail((width, height), _resample_mode())

            buffer = BytesIO()
            thumbnail.save(buffer, format="PNG", optimize=True)
            return buffer.getvalue()
    except (OSError, UnidentifiedImageError):
        return None


def make_thumb(image_path: str | Path, width: int = 300) -> Optional[bytes]:
    """
    Return cached thumbnail bytes for ``image_path``.
    """
    return _render_thumbnail(str(image_path), width)


def clear_thumbnail_cache() -> None:
    """
    Clear cached thumbnails (e.g., after screenshot replacements).
    """
    clear = getattr(_render_thumbnail, "clear", None)
    if callable(clear):
        clear()


def render_thumbnail(
    image_path: str | Path,
    *,
    caption: Optional[str] = None,
    width: int = 300,
    expander_label: str = ":material/zoom_in: View full size",
) -> None:
    """
    Render a thumbnail with a full-size expander fallback.
    """
    absolute_path = Path(image_path)
    if absolute_path.suffix.lower() == ".pdf":
        st.caption(caption or "PDF preview")
        st.warning("PDF preview not supported in thumbnail helper.")
        return

    thumb = make_thumb(absolute_path, width)
    if not thumb:
        st.warning("Preview unavailable")
        return

    st.image(thumb, caption=caption, width=width)
    with st.expander(expander_label):
        st.image(str(absolute_path), use_container_width=True, caption=caption)


__all__ = ["THUMB_CACHE_TTL", "clear_thumbnail_cache", "make_thumb", "render_thumbnail"]
