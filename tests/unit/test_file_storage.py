"""
Unit tests for file storage utilities.

Tests:
- Screenshot filename generation
- Screenshot saving
- File size validation
- File type validation
"""

import pytest
from pathlib import Path
from src.utils.file_storage import (
    generate_screenshot_filename,
    save_screenshot,
    get_screenshot_path,
    validate_file_size,
    validate_file_type,
    SCREENSHOT_DIR,
)


class TestGenerateScreenshotFilename:
    """Tests for screenshot filename generation."""

    def test_filename_format(self):
        """Test that filename follows expected format."""
        filename = generate_screenshot_filename("Admin", "Bet365", "manual_upload")

        # Should contain timestamp, source, associate, bookmaker
        assert "manual_upload" in filename
        assert "admin" in filename
        assert "bet365" in filename
        assert filename.endswith(".png")

    def test_filename_sanitization(self):
        """Test that special characters are sanitized."""
        filename = generate_screenshot_filename("Test User", "Bet 365", "telegram")

        # Spaces should be replaced with underscores
        assert "test_user" in filename
        assert "bet_365" in filename
        assert " " not in filename

    def test_filename_uniqueness(self):
        """Test that consecutive filenames are unique (timestamp-based)."""
        import time

        filename1 = generate_screenshot_filename("Admin", "Bet365", "manual_upload")
        time.sleep(0.01)  # Small delay to ensure different timestamps
        filename2 = generate_screenshot_filename("Admin", "Bet365", "manual_upload")

        # Filenames should be different due to timestamp
        assert filename1 != filename2


class TestSaveScreenshot:
    """Tests for screenshot saving."""

    def test_save_screenshot(self, tmp_path, monkeypatch):
        """Test saving screenshot to disk."""
        # Use temporary directory for testing
        test_dir = tmp_path / "screenshots"
        monkeypatch.setattr("src.utils.file_storage.SCREENSHOT_DIR", test_dir)

        # Create fake screenshot data
        test_bytes = b"fake_image_data"

        # Save screenshot
        abs_path, rel_path = save_screenshot(test_bytes, "Admin", "Bet365", "manual_upload")

        # Verify file was created
        assert Path(abs_path).exists()
        assert Path(abs_path).is_file()

        # Verify file contents
        with open(abs_path, "rb") as f:
            assert f.read() == test_bytes

        # Verify relative path format
        assert rel_path.startswith("data/screenshots/")
        assert rel_path.endswith(".png")

    def test_save_screenshot_creates_directory(self, tmp_path, monkeypatch):
        """Test that screenshot directory is created if it doesn't exist."""
        test_dir = tmp_path / "screenshots"
        monkeypatch.setattr("src.utils.file_storage.SCREENSHOT_DIR", test_dir)

        # Directory should not exist yet
        assert not test_dir.exists()

        # Save screenshot
        test_bytes = b"fake_image_data"
        abs_path, rel_path = save_screenshot(test_bytes, "Admin", "Bet365", "manual_upload")

        # Directory should now exist
        assert test_dir.exists()
        assert test_dir.is_dir()


class TestGetScreenshotPath:
    """Tests for screenshot path retrieval."""

    def test_get_screenshot_path(self):
        """Test converting relative path to absolute Path object."""
        rel_path = "data/screenshots/test_screenshot.png"
        path_obj = get_screenshot_path(rel_path)

        assert isinstance(path_obj, Path)
        # Use Path comparison to handle platform differences (Windows \ vs /)
        assert path_obj == Path(rel_path)


class TestValidateFileSize:
    """Tests for file size validation."""

    def test_valid_file_size(self):
        """Test that valid file size passes validation."""
        # 1MB file
        test_bytes = b"x" * (1024 * 1024)
        assert validate_file_size(test_bytes, max_size_mb=10)

    def test_invalid_file_size(self):
        """Test that oversized file fails validation."""
        # 11MB file (exceeds 10MB limit)
        test_bytes = b"x" * (11 * 1024 * 1024)
        assert not validate_file_size(test_bytes, max_size_mb=10)

    def test_edge_case_exact_limit(self):
        """Test file size exactly at limit."""
        # Exactly 10MB
        test_bytes = b"x" * (10 * 1024 * 1024)
        assert validate_file_size(test_bytes, max_size_mb=10)


class TestValidateFileType:
    """Tests for file type validation."""

    def test_valid_png_file(self):
        """Test that PNG files are accepted."""
        assert validate_file_type("screenshot.png")
        assert validate_file_type("screenshot.PNG")

    def test_valid_jpg_file(self):
        """Test that JPG files are accepted."""
        assert validate_file_type("screenshot.jpg")
        assert validate_file_type("screenshot.JPG")

    def test_valid_jpeg_file(self):
        """Test that JPEG files are accepted."""
        assert validate_file_type("screenshot.jpeg")
        assert validate_file_type("screenshot.JPEG")

    def test_invalid_file_type(self):
        """Test that non-image files are rejected."""
        assert not validate_file_type("document.pdf")
        assert not validate_file_type("archive.zip")
        assert not validate_file_type("text.txt")
        assert not validate_file_type("image.gif")
        assert not validate_file_type("image.bmp")

    def test_no_extension(self):
        """Test that files without extension are rejected."""
        assert not validate_file_type("screenshot")
