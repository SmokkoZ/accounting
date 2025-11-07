"""
Tests for thumbnail generation helpers.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from io import BytesIO

from src.ui.media import clear_thumbnail_cache, make_thumb


def test_make_thumb_generates_and_caches(tmp_path):
    image = tmp_path / "sample.png"
    _write_image(image, color=(255, 0, 0))

    clear_thumbnail_cache()
    thumb_a = make_thumb(image, width=100)
    assert isinstance(thumb_a, bytes)

    _write_image(image, color=(0, 0, 255))
    thumb_b = make_thumb(image, width=100)
    assert thumb_a == thumb_b  # cached result

    clear_thumbnail_cache()
    thumb_c = make_thumb(image, width=100)
    assert thumb_c != thumb_a


def test_make_thumb_handles_missing_file(tmp_path):
    clear_thumbnail_cache()
    missing = tmp_path / "missing.png"
    assert make_thumb(missing) is None


def test_make_thumb_respects_requested_width(tmp_path):
    image = tmp_path / "sizing.png"
    _write_image(image, color=(0, 255, 0))
    clear_thumbnail_cache()
    thumb_bytes = make_thumb(image, width=80)
    thumb = Image.open(BytesIO(thumb_bytes))
    assert thumb.width == 80


def _write_image(path: Path, color: tuple[int, int, int]) -> None:
    image = Image.new("RGB", (200, 120), color=color)
    image.save(path)
