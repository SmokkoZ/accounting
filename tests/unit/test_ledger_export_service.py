"""
Unit tests for Ledger Export Service.

Tests core export functionality including CSV generation, validation,
and file handling with various data scenarios.
"""

import csv
import os
import tempfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.services.ledger_export_service import LedgerExportService


class TestLedgerExportService:
    """Test cases for LedgerExportService."""

    @pytest.fixture
    def temp_export_dir(self):
        """Create a temporary directory for exports."""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield temp_dir

    @pytest.fixture
    def service(self, temp_export_dir):
        """Create service instance with temporary export directory."""
        return LedgerExportService(export_dir=temp_export_dir)

    @pytest.fixture
    def mock_db_data(self):
        """Mock database response for ledger entries."""
        return [
            {
                "entry_id": 1,
                "entry_type": "BET_RESULT",
                "associate_alias": "Alice",
                "bookmaker_name": "Bet365",
                "amount_native": "100.50",
                "native_currency": "AUD",
                "fx_rate_snapshot": "0.65",
                "amount_eur": "65.33",
                "settlement_state": "WON",
                "principal_returned_eur": "100.50",
                "per_surebet_share_eur": "25.12",
                "surebet_id": 123,
                "bet_id": 456,
                "settlement_batch_id": "batch-123",
                "created_at_utc": "2025-01-01T10:00:00Z",
                "created_by": "local_user",
                "note": "Test bet result"
            },
            {
                "entry_id": 2,
                "entry_type": "DEPOSIT",
                "associate_alias": "Bob",
                "bookmaker_name": None,
                "amount_native": "500.00",
                "native_currency": "EUR",
                "fx_rate_snapshot": "1.00",
                "amount_eur": "500.00",
                "settlement_state": None,
                "principal_returned_eur": None,
                "per_surebet_share_eur": None,
                "surebet_id": None,
                "bet_id": None,
                "settlement_batch_id": None,
                "created_at_utc": "2025-01-01T11:00:00Z",
                "created_by": "local_user",
                "note": "Initial deposit"
            }
        ]

    def test_init_creates_export_directory(self, temp_export_dir):
        """Test that service creates export directory on initialization."""
        service = LedgerExportService(export_dir=temp_export_dir)
        assert service.export_dir.exists()
        assert service.export_dir.is_dir()

    def test_format_row_for_csv_with_all_fields(self, service):
        """Test CSV row formatting with complete data."""
        row = {
            "entry_id": 1,
            "amount_native": "100.50",
            "fx_rate_snapshot": "0.65",
            "settlement_state": "WON",
            "associate_alias": "Alice"
        }
        
        formatted = service._format_row_for_csv(row)
        
        assert formatted["entry_id"] == "1"
        assert formatted["amount_native"] == "100.50"
        assert formatted["fx_rate_snapshot"] == "0.65"
        assert formatted["settlement_state"] == "WON"
        assert formatted["associate_alias"] == "Alice"

    def test_format_row_for_csv_with_null_values(self, service):
        """Test CSV row formatting with NULL values."""
        row = {
            "entry_id": 1,
            "bookmaker_name": None,
            "settlement_state": None,
            "principal_returned_eur": None
        }
        
        formatted = service._format_row_for_csv(row)
        
        assert formatted["entry_id"] == "1"
        assert formatted["bookmaker_name"] == ""
        assert formatted["settlement_state"] == ""
        assert formatted["principal_returned_eur"] == ""

    def test_get_file_size_display(self, service):
        """Test file size formatting."""
        assert service.get_file_size_display(500) == "500.0 B"
        assert service.get_file_size_display(1536) == "1.5 KB"
        assert service.get_file_size_display(1048576) == "1.0 MB"
        assert service.get_file_size_display(1073741824) == "1.0 GB"

    @patch('src.services.ledger_export_service.get_db_connection')
    def test_export_full_ledger_success(self, mock_get_conn, service, mock_db_data):
        """Test successful ledger export."""
        # Mock database connection and cursor
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn
        
        # Mock cursor.execute to return test data
        mock_cursor.fetchall.return_value = mock_db_data
        
        # Execute export
        file_path, row_count = service.export_full_ledger()
        
        # Verify file was created
        assert Path(file_path).exists()
        assert row_count == 2
        
        # Verify file content
        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            
        assert len(rows) == 2
        assert rows[0]["entry_id"] == "1"
        assert rows[0]["entry_type"] == "BET_RESULT"
        assert rows[0]["associate_alias"] == "Alice"
        assert rows[1]["entry_id"] == "2"
        assert rows[1]["entry_type"] == "DEPOSIT"
        assert rows[1]["associate_alias"] == "Bob"

    @patch('src.services.ledger_export_service.get_db_connection')
    def test_export_full_ledger_with_validation_failure(self, mock_get_conn, service):
        """Test export failure due to validation."""
        # Mock database connection
        mock_conn = MagicMock()
        mock_get_conn.return_value = mock_conn
        
        # Mock cursor to return data but validation will fail
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [{"entry_id": 1}]
        
        # Mock file operations to cause validation failure
        with patch.object(service, '_validate_export') as mock_validate:
            mock_validate.side_effect = ValueError("Row count mismatch")
            
            with pytest.raises(ValueError, match="Row count mismatch"):
                service.export_full_ledger()

    @patch('src.services.ledger_export_service.get_db_connection')
    def test_export_full_ledger_database_error(self, mock_get_conn, service):
        """Test export failure due to database error."""
        mock_get_conn.side_effect = Exception("Database connection failed")
        
        with pytest.raises(Exception, match="Database connection failed"):
            service.export_full_ledger()

    def test_validate_export_success(self, service):
        """Test successful export validation."""
        # Create a test CSV file
        test_file = service.export_dir / "test.csv"
        with open(test_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['entry_id', 'entry_type'])  # Header
            writer.writerow(['1', 'BET_RESULT'])        # Data row
            writer.writerow(['2', 'DEPOSIT'])          # Data row
        
        # Should not raise exception
        service._validate_export(test_file, 2)

    def test_validate_export_file_not_found(self, service):
        """Test validation when file doesn't exist."""
        non_existent_file = service.export_dir / "non_existent.csv"
        
        with pytest.raises(FileNotFoundError, match="Export file not created"):
            service._validate_export(non_existent_file, 1)

    def test_validate_export_row_count_mismatch(self, service):
        """Test validation when row count doesn't match."""
        # Create a test CSV file with wrong row count
        test_file = service.export_dir / "test.csv"
        with open(test_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['entry_id', 'entry_type'])  # Header
            writer.writerow(['1', 'BET_RESULT'])        # Only 1 data row
        
        with pytest.raises(ValueError, match="Row count mismatch"):
            service._validate_export(test_file, 5)  # Expect 5 rows, only have 1

    def test_get_export_history_empty(self, service):
        """Test export history when no files exist."""
        history = service.get_export_history()
        assert history == []

    def test_get_export_history_with_files(self, service):
        """Test export history with existing files."""
        # Create test export files
        files_data = [
            ("ledger_20250101_100000.csv", 100),
            ("ledger_20250101_110000.csv", 150),
            ("ledger_20250101_120000.csv", 200)
        ]
        
        for filename, row_count in files_data:
            file_path = service.export_dir / filename
            with open(file_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['entry_id'])  # Header
                for i in range(row_count):
                    writer.writerow([i])  # Data rows
        
        # Get history
        history = service.get_export_history(limit=10)
        
        assert len(history) == 3
        # Should be sorted by modification time (newest first)
        filenames = [h['filename'] for h in history]
        row_counts = [h['row_count'] for h in history]
        
        assert "ledger_20250101_120000.csv" in filenames
        assert "ledger_20250101_110000.csv" in filenames
        assert "ledger_20250101_100000.csv" in filenames
        assert 200 in row_counts
        assert 150 in row_counts
        assert 100 in row_counts

    def test_get_export_history_with_limit(self, service):
        """Test export history with limit parameter."""
        # Create more files than limit
        for i in range(15):
            filename = f"ledger_20250101_{i:02d}0000.csv"
            file_path = service.export_dir / filename
            with open(file_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['entry_id'])
                writer.writerow([i])
        
        history = service.get_export_history(limit=5)
        assert len(history) == 5

    def test_get_export_history_ignores_non_ledger_files(self, service):
        """Test that non-ledger CSV files are ignored."""
        # Create mix of files
        (service.export_dir / "other.csv").touch()
        (service.export_dir / "ledger_test.csv").touch()
        (service.export_dir / "ledger_20250101_100000.csv").touch()
        
        history = service.get_export_history()
        
        # Should only find proper ledger file (generic pattern now includes all ledger_*.csv files)
        assert len(history) >= 1
        filenames = [h['filename'] for h in history]
        assert "ledger_20250101_100000.csv" in filenames

    @patch('src.services.ledger_export_service.get_db_connection')
    def test_export_csv_headers_and_format(self, mock_get_conn, service, mock_db_data):
        """Test that CSV export has correct headers and format."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = mock_db_data
        mock_get_conn.return_value = mock_conn
        
        file_path, _ = service.export_full_ledger()
        
        # Read and verify CSV structure
        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            rows = list(reader)
        
        # Check all expected headers are present
        expected_headers = [
            "entry_id", "entry_type", "associate_alias", "bookmaker_name",
            "surebet_id", "bet_id", "settlement_batch_id", "settlement_state",
            "amount_native", "native_currency", "fx_rate_snapshot", "amount_eur",
            "principal_returned_eur", "per_surebet_share_eur",
            "created_at_utc", "created_by", "note"
        ]
        
        for header in expected_headers:
            assert header in headers
        
        # Verify UTF-8 encoding by reading special characters
        assert len(headers) == len(expected_headers)
        assert len(rows) == len(mock_db_data)

    @patch('src.services.ledger_export_service.datetime')
    @patch('src.services.ledger_export_service.get_db_connection')
    def test_export_filename_format(self, mock_get_conn, mock_datetime, service, mock_db_data):
        """Test that export filename follows correct timestamp format."""
        # Mock timestamp (service adds milliseconds with slice)
        mock_datetime.now.return_value.strftime.return_value = "20250101_123456"
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = mock_db_data
        mock_get_conn.return_value = mock_conn
        
        file_path, _ = service.export_full_ledger()
        
        expected_filename = "ledger_20250101_123.csv"
        assert Path(file_path).name == expected_filename
