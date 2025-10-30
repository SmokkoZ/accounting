"""
File storage utilities for bet screenshots.

This module provides utilities for:
- Generating unique screenshot filenames
- Saving screenshots to disk
- Retrieving screenshot paths
"""

from pathlib import Path
from datetime import datetime, timezone
from typing import Tuple, Union

SCREENSHOT_DIR = Path("data/screenshots")


def generate_screenshot_filename(
    associate_alias: str, bookmaker_name: str, source: str = "manual_upload"
) -> str:
    """
    Generate unique screenshot filename with timestamp.

    Format: {timestamp}_{source}_{associate}_{bookmaker}.png
    Example: 20251030_143045_123_manual_admin_bet365.png

    Args:
        associate_alias: Associate display alias.
        bookmaker_name: Bookmaker name.
        source: Ingestion source (telegram or manual_upload).

    Returns:
        Unique filename string.
    """
    # Generate timestamp with milliseconds (using timezone-aware datetime)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")[:-3]

    # Sanitize names (remove spaces, special chars, lowercase)
    associate_clean = associate_alias.lower().replace(" ", "_").replace(".", "")
    bookmaker_clean = bookmaker_name.lower().replace(" ", "_").replace(".", "")

    return f"{timestamp}_{source}_{associate_clean}_{bookmaker_clean}.png"


def save_screenshot(
    file_bytes: bytes, associate_alias: str, bookmaker_name: str, source: str = "manual_upload"
) -> Tuple[str, str]:
    """
    Save screenshot to disk.

    Args:
        file_bytes: Screenshot image bytes.
        associate_alias: Associate display alias.
        bookmaker_name: Bookmaker name.
        source: Ingestion source (telegram or manual_upload).

    Returns:
        Tuple of (absolute_path, relative_path).
            - absolute_path: Full system path as string
            - relative_path: Relative path from project root (for database storage)

    Raises:
        OSError: If directory creation or file write fails.
    """
    # Ensure screenshots directory exists
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

    # Generate unique filename
    filename = generate_screenshot_filename(associate_alias, bookmaker_name, source)

    # Build paths
    absolute_path = SCREENSHOT_DIR / filename
    relative_path = f"data/screenshots/{filename}"

    # Write file to disk
    with open(absolute_path, "wb") as f:
        f.write(file_bytes)

    return str(absolute_path), relative_path


def get_screenshot_path(relative_path: str) -> Path:
    """
    Convert relative path to absolute Path object.

    Args:
        relative_path: Relative path from database (e.g., "data/screenshots/...png").

    Returns:
        Path object for the screenshot file.
    """
    return Path(relative_path)


def validate_file_size(file_bytes: bytes, max_size_mb: int = 10) -> bool:
    """
    Validate that file size is within acceptable limits.

    Args:
        file_bytes: File bytes to check.
        max_size_mb: Maximum allowed size in megabytes.

    Returns:
        True if file size is acceptable, False otherwise.
    """
    file_size_mb = len(file_bytes) / (1024 * 1024)
    return file_size_mb <= max_size_mb


def validate_file_type(filename: str) -> bool:
    """
    Validate that file has an acceptable image extension.

    Args:
        filename: Name of the file to validate.

    Returns:
        True if file type is acceptable (PNG, JPG, JPEG), False otherwise.
    """
    allowed_extensions = {".png", ".jpg", ".jpeg"}
    file_ext = Path(filename).suffix.lower()
    return file_ext in allowed_extensions
