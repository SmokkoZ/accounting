"""
Unit tests for FundingTransactionService (Story 5.5)

Tests for funding transaction creation, validation, and history retrieval.
"""

import pytest
from decimal import Decimal, InvalidOperation
from datetime import datetime, date
from unittest.mock import Mock, patch, MagicMock

from src.services.funding_transaction_service import (
    FundingTransactionService,
    FundingTransaction,
    FundingTransactionError
)


class TestFundingTransaction:
    """Test cases for FundingTransaction dataclass."""
    
    def test_valid_transaction_creation(self):
        """Test creating a valid transaction."""
        transaction = FundingTransaction(
            associate_id=1,
            bookmaker_id=2,
            transaction_type="DEPOSIT",
            amount_native=Decimal("100.00"),
            native_currency="EUR",
            note="Test deposit"
        )
        
        assert transaction.associate_id == 1
        assert transaction.bookmaker_id == 2
        assert transaction.transaction_type == "DEPOSIT"
        assert transaction.amount_native == Decimal("100.00")
        assert transaction.native_currency == "EUR"
        assert transaction.note == "Test deposit"
        assert transaction.created_by == "local_user"
    
    def test_invalid_transaction_type(self):
        """Test transaction with invalid type."""
        with pytest.raises(ValueError, match="Invalid transaction_type"):
            FundingTransaction(
                associate_id=1,
                bookmaker_id=None,
                transaction_type="INVALID",
                amount_native=Decimal("100.00"),
                native_currency="EUR",
                note=None
            )
    
    def test_negative_amount(self):
        """Test transaction with negative amount."""
        with pytest.raises(ValueError, match="Amount must be positive"):
            FundingTransaction(
                associate_id=1,
                bookmaker_id=None,
                transaction_type="DEPOSIT",
                amount_native=Decimal("-100.00"),
                native_currency="EUR",
                note=None
            )
    
    def test_zero_amount(self):
        """Test transaction with zero amount."""
        with pytest.raises(ValueError, match="Amount must be positive"):
            FundingTransaction(
                associate_id=1,
                bookmaker_id=None,
                transaction_type="DEPOSIT",
                amount_native=Decimal("0.00"),
                native_currency="EUR",
                note=None
            )
    
    def test_invalid_currency_code(self):
        """Test transaction with invalid currency code."""
        with pytest.raises(ValueError, match="Currency must be a valid 3-letter ISO code"):
            FundingTransaction(
                associate_id=1,
                bookmaker_id=None,
                transaction_type="DEPOSIT",
                amount_native=Decimal("100.00"),
                native_currency="INVALID",
                note=None
            )
    
    def test_empty_currency_code(self):
        """Test transaction with empty currency code."""
        with pytest.raises(ValueError, match="Currency must be a valid 3-letter ISO code"):
            FundingTransaction(
                associate_id=1,
                bookmaker_id=None,
                transaction_type="DEPOSIT",
                amount_native=Decimal("100.00"),
                native_currency="",
                note=None
            )


class TestFundingTransactionService:
    """Test cases for FundingTransactionService."""
    
    @pytest.fixture
    def mock_db(self):
        """Mock database connection."""
        mock_conn = Mock()
        mock_conn.execute.return_value = Mock()
        mock_conn.commit.return_value = None
        return mock_conn
    
    @pytest.fixture
    def service(self, mock_db):
        """Create service instance with mocked database."""
        return FundingTransactionService(mock_db)
    
    def test_init_with_db(self, mock_db):
        """Test service initialization with database."""
        service = FundingTransactionService(mock_db)
        assert service.db == mock_db
        assert service._owns_connection == False
    
    def test_init_without_db(self):
        """Test service initialization without database."""
        with patch('src.services.funding_transaction_service.get_db_connection') as mock_get_db:
            mock_conn = Mock()
            mock_get_db.return_value = mock_conn
            
            service = FundingTransactionService()
            
            assert service.db == mock_conn
            assert service._owns_connection == True
            mock_get_db.assert_called_once()
    
    def test_close_owned_connection(self):
        """Test closing owned connection."""
        with patch('src.services.funding_transaction_service.get_db_connection') as mock_get_db:
            mock_conn = Mock()
            mock_get_db.return_value = mock_conn
            
            service = FundingTransactionService()
            service.close()
            
            mock_conn.close.assert_called_once()
    
    def test_close_unowned_connection(self, mock_db):
        """Test not closing unowned connection."""
        service = FundingTransactionService(mock_db)
        service.close()
        
        # Should not call close on unowned connection
        mock_db.close.assert_not_called()
    
    def test_record_deposit_transaction(self, service, mock_db):
        """Test recording a deposit transaction."""
        # Mock database responses
        mock_db.execute.return_value.fetchone.return_value = {"COUNT(*)": 1}
        mock_db.execute.return_value.lastrowid = 123
        
        # Mock FX rate
        with patch('src.services.funding_transaction_service.get_fx_rate') as mock_fx:
            mock_fx.return_value = Decimal("1.1000")
            
            # Mock transactional context
            with patch('src.services.funding_transaction_service.transactional') as mock_transactional:
                mock_conn = Mock()
                mock_cursor = Mock()
                mock_cursor.lastrowid = 123
                mock_conn.execute.return_value = mock_cursor
                mock_transactional.return_value.__enter__.return_value = mock_conn
                mock_transactional.return_value.__exit__.return_value = None
                
                transaction = FundingTransaction(
                    associate_id=1,
                    bookmaker_id=None,
                    transaction_type="DEPOSIT",
                    amount_native=Decimal("100.00"),
                    native_currency="EUR",
                    note="Test deposit"
                )
                
                result = service.record_transaction(transaction)
                
                assert result == 123
    
    def test_record_withdrawal_transaction(self, service, mock_db):
        """Test recording a withdrawal transaction."""
        # Mock database responses
        mock_db.execute.return_value.fetchone.return_value = {"COUNT(*)": 1}
        mock_db.execute.return_value.lastrowid = 124
        
        # Mock FX rate
        with patch('src.services.funding_transaction_service.get_fx_rate') as mock_fx:
            mock_fx.return_value = Decimal("1.1000")
            
            # Mock transactional context
            with patch('src.services.funding_transaction_service.transactional') as mock_transactional:
                mock_conn = Mock()
                mock_cursor = Mock()
                mock_cursor.lastrowid = 124
                mock_conn.execute.return_value = mock_cursor
                mock_transactional.return_value.__enter__.return_value = mock_conn
                mock_transactional.return_value.__exit__.return_value = None
                
                transaction = FundingTransaction(
                    associate_id=1,
                    bookmaker_id=None,
                    transaction_type="WITHDRAWAL",
                    amount_native=Decimal("100.00"),
                    native_currency="EUR",
                    note="Test withdrawal"
                )
                
                result = service.record_transaction(transaction)
                
                assert result == 124
    
    def test_record_transaction_bookmaker_level(self, service, mock_db):
        """Test recording transaction for specific bookmaker."""
        # Mock database responses
        mock_db.execute.return_value.fetchone.return_value = {"COUNT(*)": 1}
        mock_db.execute.return_value.lastrowid = 125
        
        # Mock FX rate
        with patch('src.services.funding_transaction_service.get_fx_rate') as mock_fx:
            mock_fx.return_value = Decimal("1.1000")
            
            # Mock transactional context
            with patch('src.services.funding_transaction_service.transactional') as mock_transactional:
                mock_conn = Mock()
                mock_cursor = Mock()
                mock_cursor.lastrowid = 125
                mock_conn.execute.return_value = mock_cursor
                mock_transactional.return_value.__enter__.return_value = mock_conn
                mock_transactional.return_value.__exit__.return_value = None
                
                transaction = FundingTransaction(
                    associate_id=1,
                    bookmaker_id=2,
                    transaction_type="DEPOSIT",
                    amount_native=Decimal("100.00"),
                    native_currency="EUR",
                    note="Bookmaker deposit"
                )
                
                result = service.record_transaction(transaction)
                
                assert result == 125
    
    def test_record_transaction_invalid_associate(self, service, mock_db):
        """Test recording transaction for non-existent associate."""
        # Mock associate not found
        mock_db.execute.return_value.fetchone.return_value = None
        
        transaction = FundingTransaction(
            associate_id=999,
            bookmaker_id=None,
            transaction_type="DEPOSIT",
            amount_native=Decimal("100.00"),
            native_currency="EUR",
            note=None
        )
        
        with pytest.raises(FundingTransactionError, match="Associate not found"):
            service.record_transaction(transaction)
    
    def test_record_transaction_invalid_bookmaker(self, service, mock_db):
        """Test recording transaction for non-existent bookmaker."""
        # Mock associate exists but bookmaker doesn't
        mock_db.execute.side_effect = [
            Mock(fetchone=lambda: {"COUNT(*)": 1}),  # Associate exists
            Mock(fetchone=lambda: None)  # Bookmaker doesn't exist
        ]
        
        transaction = FundingTransaction(
            associate_id=1,
            bookmaker_id=999,
            transaction_type="DEPOSIT",
            amount_native=Decimal("100.00"),
            native_currency="EUR",
            note=None
        )
        
        with pytest.raises(FundingTransactionError, match="Bookmaker not found"):
            service.record_transaction(transaction)
    
    def test_get_transaction_history(self, service, mock_db):
        """Test retrieving transaction history."""
        # Mock database response
        mock_rows = [
            {
                'id': 1,
                'transaction_type': 'DEPOSIT',
                'associate_id': 1,
                'associate_alias': 'Test User',
                'bookmaker_id': None,
                'bookmaker_name': None,
                'amount_native': '100.00',
                'native_currency': 'EUR',
                'fx_rate_snapshot': '1.100000',
                'amount_eur': '110.00',
                'created_at_utc': '2025-01-01T12:00:00Z',
                'created_by': 'local_user',
                'note': 'Test deposit'
            }
        ]
        
        mock_db.execute.return_value.fetchall.return_value = mock_rows
        
        # Call method
        result = service.get_transaction_history()
        
        # Verify query
        mock_db.execute.assert_called_once()
        
        # Verify result
        assert len(result) == 1
        transaction = result[0]
        assert transaction['id'] == 1
        assert transaction['transaction_type'] == 'DEPOSIT'
        assert transaction['associate_id'] == 1
        assert transaction['associate_alias'] == 'Test User'
        assert transaction['bookmaker_id'] is None
        assert transaction['bookmaker_name'] is None
        assert transaction['amount_native'] == Decimal('100.00')
        assert transaction['native_currency'] == 'EUR'
        assert transaction['fx_rate_snapshot'] == Decimal('1.100000')
        assert transaction['amount_eur'] == Decimal('110.00')
        assert transaction['created_at_utc'] == '2025-01-01T12:00:00Z'
        assert transaction['created_by'] == 'local_user'
        assert transaction['note'] == 'Test deposit'
    
    def test_get_transaction_history_with_filters(self, service, mock_db):
        """Test retrieving transaction history with filters."""
        mock_db.execute.return_value.fetchall.return_value = []
        
        # Call with filters
        service.get_transaction_history(
            associate_id=1,
            bookmaker_id=2,
            days=7
        )
        
        # Verify query parameters
        mock_db.execute.assert_called_once()
        call_args = mock_db.execute.call_args
        
        query = call_args[0][0]
        params = call_args[0][1]
        
        assert "WHERE le.type IN" in query
        assert "AND le.created_at_utc >= ?" in query
        assert "AND le.associate_id = ?" in query
        assert "AND le.bookmaker_id = ?" in query
        assert "ORDER BY le.created_at_utc DESC" in query
    
    def test_get_associate_balance_summary(self, service, mock_db):
        """Test retrieving associate balance summary."""
        # Mock database responses
        mock_db.execute.side_effect = [
            Mock(fetchone=lambda: {'net_deposits_eur': '1000.00'}),  # Net deposits
            Mock(fetchone=lambda: {'current_holding_eur': '950.00'})   # Current holdings
        ]
        
        # Call method
        result = service.get_associate_balance_summary(1)
        
        # Verify queries were called
        assert mock_db.execute.call_count == 2
        
        # Verify result
        assert result['net_deposits_eur'] == Decimal('1000.00')
        assert result['current_holding_eur'] == Decimal('950.00')
        assert result['delta_eur'] == Decimal('-50.00')
        assert result['should_hold_eur'] == Decimal('1000.00')
    
    def test_validate_funding_amount_valid(self, service):
        """Test valid funding amount validation."""
        # Should not raise exception
        service.validate_funding_amount(Decimal("100.00"), "EUR")
        service.validate_funding_amount(Decimal("0.01"), "USD")
        service.validate_funding_amount(Decimal("99999.99"), "GBP")
    
    def test_validate_funding_amount_invalid(self, service):
        """Test invalid funding amount validation."""
        with pytest.raises(FundingTransactionError, match="Amount must be positive"):
            service.validate_funding_amount(Decimal("0.00"), "EUR")
        
        with pytest.raises(FundingTransactionError, match="Amount must be positive"):
            service.validate_funding_amount(Decimal("-100.00"), "EUR")
        
        with pytest.raises(FundingTransactionError, match="Amount exceeds maximum"):
            service.validate_funding_amount(Decimal("100000.01"), "EUR")
        
        with pytest.raises(FundingTransactionError, match="Invalid currency code"):
            service.validate_funding_amount(Decimal("100.00"), "")
        
        with pytest.raises(FundingTransactionError, match="Invalid currency code"):
            service.validate_funding_amount(Decimal("100.00"), "INVALID")
    
    def test_get_fx_rate_available(self, service):
        """Test getting available FX rate."""
        with patch('src.services.funding_transaction_service.get_fx_rate') as mock_fx:
            mock_fx.return_value = Decimal("1.2000")
            
            result = service._get_fx_rate("GBP")
            
            assert result == Decimal("1.2000")
            mock_fx.assert_called_once_with("GBP", date.today())
    
    def test_get_fx_rate_unavailable(self, service):
        """Test getting unavailable FX rate."""
        with patch('src.services.funding_transaction_service.get_fx_rate') as mock_fx:
            mock_fx.return_value = None
            
            result = service._get_fx_rate("XYZ")
            
            assert result == Decimal("1.0")
    
    def test_create_ledger_entry(self, service):
        """Test creating ledger entry."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.lastrowid = 456
        mock_conn.execute.return_value = mock_cursor
        
        transaction = FundingTransaction(
            associate_id=1,
            bookmaker_id=None,
            transaction_type="DEPOSIT",
            amount_native=Decimal("100.00"),
            native_currency="EUR",
            note=None
        )
        
        result = service._create_ledger_entry(
            conn=mock_conn,
            transaction=transaction,
            amount_native=Decimal("100.00"),
            fx_rate_snapshot=Decimal("1.1000")
        )
        
        # Verify query
        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        
        query = call_args[0][0]
        params = call_args[0][1]
        
        assert "INSERT INTO ledger_entries" in query
        assert "type," in query
        assert "associate_id," in query
        assert "bookmaker_id," in query
        assert "surebet_id," in query
        assert "bet_id," in query
        assert "settlement_state," in query
        assert "amount_native," in query
        assert "native_currency," in query
        assert "fx_rate_snapshot," in query
        assert "amount_eur," in query
        assert "principal_returned_eur," in query
        assert "per_surebet_share_eur," in query
        assert "settlement_batch_id," in query
        assert "created_by," in query
        assert "note" in query
        
        assert list(params) == [
            "DEPOSIT", 1, None, None, None, None,
            "100.00", "EUR", "1.1000", "110.00", None, None, None,
            "local_user", None
        ]
        
        assert result == 456
    
    def test_quantize_currency(self):
        """Test currency quantization."""
        result = FundingTransactionService._quantize_currency(Decimal("1.23456"))
        assert result == Decimal("1.23")
        
        result = FundingTransactionService._quantize_currency(Decimal("1.235"))
        assert result == Decimal("1.24")  # Round half up
  
    
    def test_context_manager(self, mock_db):
        """Test service as context manager."""
        with FundingTransactionService(mock_db) as service:
            assert service.db == mock_db
        
        # Should not close since we didn't own connection
        mock_db.close.assert_not_called()
    
    def test_database_error_handling(self, service, mock_db):
        """Test handling of database errors."""
        # Mock database error
        mock_db.execute.side_effect = Exception("Database error")
        
        transaction = FundingTransaction(
            associate_id=1,
            bookmaker_id=None,
            transaction_type="DEPOSIT",
            amount_native=Decimal("100.00"),
            native_currency="EUR",
            note=None
        )
        
        with pytest.raises(FundingTransactionError, match="Failed to record funding transaction"):
            service.record_transaction(transaction)
    
    def test_transaction_error_handling(self, service, mock_db):
        """Test handling of transactional errors."""
        # Mock transactional error
        with patch('src.services.funding_transaction_service.transactional') as mock_transactional:
            from src.utils.database_utils import TransactionError
            mock_transactional.side_effect = TransactionError("Transaction failed")
            
            transaction = FundingTransaction(
                associate_id=1,
                bookmaker_id=None,
                transaction_type="DEPOSIT",
                amount_native=Decimal("100.00"),
                native_currency="EUR",
                note=None
            )
            
            with pytest.raises(FundingTransactionError, match="Database transaction failed"):
                service.record_transaction(transaction)
