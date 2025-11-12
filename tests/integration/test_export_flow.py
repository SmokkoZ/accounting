"""
Integration tests for Ledger Export workflow.

Tests the complete export flow from UI interaction to file creation,
including database integration and file system operations.
"""

import csv
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.services.ledger_export_service import LedgerExportService


class TestExportFlowIntegration:
    """Integration tests for the complete export workflow."""

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
    def sample_ledger_data(self):
        """Sample ledger data for testing."""
        return [
            {
                "entry_id": 1,
                "entry_type": "BET_RESULT",
                "associate_alias": "Alice Smith",
                "bookmaker_name": "Bet365",
                "selection_text": "Manchester United vs Liverpool",
                "selection": "Over 2.5 Goals",
                "market_code": "TOTAL_GOALS_OVER_UNDER",
                "market_description": "Total Goals Over/Under",
                "side": "OVER",
                "line_value": "2.5",
                "canonical_event_name": "Manchester United vs Liverpool",
                "amount_native": "100.50",
                "native_currency": "AUD",
                "fx_rate_snapshot": "0.6523",
                "amount_eur": "65.54",
                "settlement_state": "WON",
                "principal_returned_eur": "100.50",
                "per_surebet_share_eur": "25.12",
                "surebet_id": 123,
                "bet_id": 456,
                "settlement_batch_id": "batch-20250101-001",
                "created_at_utc": "2025-01-01T10:00:00Z",
                "created_by": "local_user",
                "note": "Winning bet on Manchester United"
            },
            {
                "entry_id": 2,
                "entry_type": "DEPOSIT",
                "associate_alias": "Bob Johnson",
                "bookmaker_name": None,
                "selection_text": None,
                "selection": None,
                "market_code": None,
                "market_description": None,
                "side": None,
                "line_value": None,
                "canonical_event_name": None,
                "amount_native": "1000.00",
                "native_currency": "EUR",
                "fx_rate_snapshot": "1.0000",
                "amount_eur": "1000.00",
                "settlement_state": None,
                "principal_returned_eur": None,
                "per_surebet_share_eur": None,
                "surebet_id": None,
                "bet_id": None,
                "settlement_batch_id": None,
                "created_at_utc": "2025-01-01T09:00:00Z",
                "created_by": "local_user",
                "note": "Initial funding for account"
            },
            {
                "entry_id": 3,
                "entry_type": "WITHDRAWAL",
                "associate_alias": "Charlie Brown",
                "bookmaker_name": "William Hill",
                "selection_text": None,
                "selection": None,
                "market_code": None,
                "market_description": None,
                "side": None,
                "line_value": None,
                "canonical_event_name": None,
                "amount_native": "200.00",
                "native_currency": "GBP",
                "fx_rate_snapshot": "1.1567",
                "amount_eur": "231.34",
                "settlement_state": None,
                "principal_returned_eur": None,
                "per_surebet_share_eur": None,
                "surebet_id": None,
                "bet_id": None,
                "settlement_batch_id": None,
                "created_at_utc": "2025-01-01T11:00:00Z",
                "created_by": "local_user",
                "note": "Profit withdrawal"
            },
            {
                "entry_id": 4,
                "entry_type": "BOOKMAKER_CORRECTION",
                "associate_alias": "Alice Smith",
                "bookmaker_name": "Bet365",
                "selection_text": None,
                "selection": None,
                "market_code": None,
                "market_description": None,
                "side": None,
                "line_value": None,
                "canonical_event_name": None,
                "amount_native": "-50.00",
                "native_currency": "AUD",
                "fx_rate_snapshot": "0.6523",
                "amount_eur": "-32.62",
                "settlement_state": None,
                "principal_returned_eur": None,
                "per_surebet_share_eur": None,
                "surebet_id": None,
                "bet_id": None,
                "settlement_batch_id": "correction-20250101-001",
                "created_at_utc": "2025-01-01T12:00:00Z",
                "created_by": "admin_user",
                "note": "Corrected payout error"
            }
        ]

    @patch('src.services.ledger_export_service.get_db_connection')
    def test_complete_export_workflow_success(self, mock_get_conn, service, sample_ledger_data):
        """Test the complete export workflow with realistic data."""
        # Mock database setup
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.close = MagicMock()
        mock_get_conn.return_value = mock_conn
        
        # Set up cursor to return sample data
        mock_cursor.fetchall.return_value = sample_ledger_data
        
        # Execute export
        file_path, row_count = service.export_full_ledger()
        
        # Verify export completion
        assert Path(file_path).exists()
        assert row_count == 4
        
        # Verify database connection was properly managed
        mock_get_conn.assert_called_once()
        mock_conn.close.assert_called_once()
        
        # Verify SQL execution
        mock_cursor.execute.assert_called_once()
        call_args = mock_cursor.execute.call_args[0][0]
        assert "SELECT" in call_args
        assert "ledger_entries" in call_args
        assert "associates" in call_args
        assert "bookmakers" in call_args
        
        # Verify file content
        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            headers = reader.fieldnames
        
        # Check structure
        assert len(headers) == 20  # Expected number of columns
        assert len(rows) == 4  # All sample records
        
        # Verify specific data
        bet_result_row = next(r for r in rows if r['entry_type'] == 'BET_RESULT')
        assert bet_result_row['associate_alias'] == 'Alice Smith'
        assert bet_result_row['bookmaker_name'] == 'Bet365'
        assert bet_result_row['amount_native'] == '100.50'
        assert bet_result_row['settlement_state'] == 'WON'
        assert bet_result_row['created_at_utc'] == '01/01/2025'
        assert bet_result_row['event_name'] == 'Manchester United vs Liverpool'
        assert bet_result_row['market_selection'] == 'Total Goals Over/Under - OVER (2.5)'
        assert bet_result_row['principal_returned_native'] == '154.07'
        assert bet_result_row['surebet_id'] == '123'
        assert bet_result_row['bet_id'] == '456'
        
        deposit_row = next(r for r in rows if r['entry_type'] == 'DEPOSIT')
        assert deposit_row['associate_alias'] == 'Bob Johnson'
        assert deposit_row['bookmaker_name'] == ''
        assert deposit_row['amount_native'] == '1000.00'
        assert deposit_row['settlement_state'] == ''
        assert deposit_row['surebet_id'] == ''
        assert deposit_row['bet_id'] == ''
        
        withdrawal_row = next(r for r in rows if r['entry_type'] == 'WITHDRAWAL')
        assert withdrawal_row['associate_alias'] == 'Charlie Brown'
        assert withdrawal_row['bookmaker_name'] == 'William Hill'
        assert withdrawal_row['native_currency'] == 'GBP'
        
        correction_row = next(r for r in rows if r['entry_type'] == 'BOOKMAKER_CORRECTION')
        assert correction_row['associate_alias'] == 'Alice Smith'
        assert correction_row['note'] == 'Corrected payout error'

    @patch('src.services.ledger_export_service.get_db_connection')
    def test_export_workflow_with_large_dataset(self, mock_get_conn, service):
        """Test export performance with larger dataset."""
        # Generate large dataset (1000 rows)
        large_dataset = []
        for i in range(1000):
            large_dataset.append({
                "entry_id": i + 1,
                "entry_type": "BET_RESULT" if i % 2 == 0 else "DEPOSIT",
                "associate_alias": f"User {i % 10}",
                "bookmaker_name": f"Bookmaker {i % 5}" if i % 3 == 0 else None,
                "amount_native": str(100.0 + i),
                "native_currency": "EUR",
                "fx_rate_snapshot": "1.0000",
                "amount_eur": str(100.0 + i),
                "settlement_state": "WON" if i % 2 == 0 else None,
                "principal_returned_eur": str(100.0 + i) if i % 2 == 0 else None,
                "per_surebet_share_eur": str(25.0 + i/10) if i % 2 == 0 else None,
                "surebet_id": i + 100 if i % 2 == 0 else None,
                "bet_id": i + 200 if i % 2 == 0 else None,
                "settlement_batch_id": f"batch-{i}" if i % 2 == 0 else None,
                "created_at_utc": f"2025-01-{(i % 30) + 1:02d}T{(i % 24):02d}:00:00Z",
                "created_by": "local_user",
                "note": f"Test entry {i}"
            })
        
        # Mock database
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.close = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_cursor.fetchall.return_value = large_dataset
        
        # Execute export
        file_path, row_count = service.export_full_ledger()
        
        # Verify results
        assert Path(file_path).exists()
        assert row_count == 1000
        
        # Spot-check file content
        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        assert len(rows) == 1000
        assert rows[0]['entry_id'] == '1'
        assert rows[-1]['entry_id'] == '1000'
        assert len(set(row['entry_type'] for row in rows)) == 2  # BET_RESULT and DEPOSIT

    @patch('src.services.ledger_export_service.get_db_connection')
    def test_export_workflow_with_special_characters(self, mock_get_conn, service):
        """Test export with special characters and international data."""
        special_data = [
            {
                "entry_id": 1,
                "entry_type": "BET_RESULT",
                "associate_alias": "José García",
                "bookmaker_name": "Betclic.fr",
                "amount_native": "100,50",  # Comma as decimal
                "native_currency": "EUR",
                "fx_rate_snapshot": "1.0000",
                "amount_eur": "100.50",
                "settlement_state": "WON",
                "principal_returned_eur": "100.50",
                "per_surebet_share_eur": "25.12",
                "surebet_id": 123,
                "bet_id": 456,
                "settlement_batch_id": "batch-20250101-001",
                "created_at_utc": "2025-01-01T10:00:00Z",
                "created_by": "local_user",
                "note": "Pari gagné suréquipe française"  # French characters
            },
            {
                "entry_id": 2,
                "entry_type": "DEPOSIT",
                "associate_alias": "Михаил Иванов",  # Cyrillic characters
                "bookmaker_name": None,
                "amount_native": "500.00",
                "native_currency": "RUB",
                "fx_rate_snapshot": "0.0102",
                "amount_eur": "5.10",
                "settlement_state": None,
                "principal_returned_eur": None,
                "per_surebet_share_eur": None,
                "surebet_id": None,
                "bet_id": None,
                "settlement_batch_id": None,
                "created_at_utc": "2025-01-01T11:00:00Z",
                "created_by": "admin",
                "note": "Пополнение счета"  # Cyrillic note
            }
        ]
        
        # Mock database
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.close = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_cursor.fetchall.return_value = special_data
        
        # Execute export
        file_path, row_count = service.export_full_ledger()
        
        # Verify file content with special characters
        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        assert len(rows) == 2
        assert rows[0]['associate_alias'] == 'José García'
        assert rows[0]['note'] == 'Pari gagné suréquipe française'
        assert rows[1]['associate_alias'] == 'Михаил Иванов'
        assert rows[1]['note'] == 'Пополнение счета'

    @patch('src.services.ledger_export_service.get_db_connection')
    def test_export_history_integration(self, mock_get_conn, service):
        """Test export history functionality with real file operations."""
        # Mock database for successful exports
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.close = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_cursor.fetchall.return_value = [{"entry_id": 1}]
        
        # Create multiple exports with small delays to ensure different timestamps
        export_files = []
        for i in range(3):
            file_path, _ = service.export_full_ledger()
            export_files.append(Path(file_path))
            if i < 2:  # Don't sleep after last export
                time.sleep(0.1)  # Small delay to ensure different timestamps
        
        # Get history
        history = service.get_export_history(limit=10)
        
        # Verify history - should have 3 files (order may vary due to same timestamps)
        assert len(history) == 3
        
        # All created files should be in history
        history_filenames = [h['filename'] for h in history]
        for file_path in export_files:
            assert file_path.name in history_filenames
        
        # Verify metadata
        for hist in history:
            assert hist['file_size'] > 0
            assert hist['row_count'] == 1  # Mock data has 1 row
            assert 'created_time' in hist

    @patch('src.services.ledger_export_service.get_db_connection')
    def test_export_with_null_decimal_values(self, mock_get_conn, service):
        """Test export handling of NULL decimal values."""
        null_decimal_data = [
            {
                "entry_id": 1,
                "entry_type": "DEPOSIT",
                "associate_alias": "Alice",
                "bookmaker_name": None,
                "amount_native": "100.00",
                "native_currency": "EUR",
                "fx_rate_snapshot": "1.0000",
                "amount_eur": "100.00",
                "settlement_state": None,
                "principal_returned_eur": None,
                "per_surebet_share_eur": None,
                "surebet_id": None,
                "bet_id": None,
                "settlement_batch_id": None,
                "created_at_utc": "2025-01-01T10:00:00Z",
                "created_by": "local_user",
                "note": None
            }
        ]
        
        # Mock database
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.close = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_cursor.fetchall.return_value = null_decimal_data
        
        # Execute export
        file_path, row_count = service.export_full_ledger()
        
        # Verify NULL values are handled correctly
        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        assert len(rows) == 1
        row = rows[0]
        
        assert row['bookmaker_name'] == ''
        assert row['settlement_state'] == ''
        assert row['principal_returned_eur'] == ''
        assert row['per_surebet_share_eur'] == ''
        assert row['surebet_id'] == ''
        assert row['bet_id'] == ''
        assert row['settlement_batch_id'] == ''
        assert row['note'] == ''
        
        # Non-NULL values should be preserved
        assert row['entry_id'] == '1'
        assert row['entry_type'] == 'DEPOSIT'
        assert row['amount_native'] == '100.00'
        assert row['amount_eur'] == '100.00'

    def test_export_directory_creation_permissions(self, temp_export_dir):
        """Test export directory creation and permissions."""
        # Test with non-existent directory
        non_existent_dir = Path(temp_export_dir) / "exports" / "nested"
        service = LedgerExportService(export_dir=str(non_existent_dir))
        
        assert non_existent_dir.exists()
        assert non_existent_dir.is_dir()
        
        # Should be able to create files
        assert service.export_dir.exists()
        assert service.export_dir.is_dir()
