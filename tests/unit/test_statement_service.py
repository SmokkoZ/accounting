"""
Unit tests for Statement Service.

Tests all calculation logic, formatting, and validation functionality.
"""

import pytest
from decimal import Decimal
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock

from src.services.statement_service import (
    StatementService,
    StatementCalculations,
    PartnerFacingSection,
    InternalSection
)


@pytest.fixture
def service():
    """Create a StatementService instance for testing."""
    return StatementService()

@pytest.fixture
def mock_db_connection():
    """Create a mock database connection."""
    conn = Mock()
    cursor = Mock()
    conn.cursor.return_value = cursor
    conn.close = Mock()
    return conn, cursor

@pytest.fixture
def sample_calculations():
    """Sample statement calculations for testing."""
    return StatementCalculations(
        net_deposits_eur=Decimal("1000.00"),
        should_hold_eur=Decimal("1200.00"),
        current_holding_eur=Decimal("1150.00"),
        raw_profit_eur=Decimal("200.00"),
        delta_eur=Decimal("-50.00"),
        associate_name="Test Associate",
        cutoff_date="2025-10-31T23:59:59Z",
        generated_at="2025-11-05T11:00:00Z"
    )


class TestStatementService:
    """Test cases for StatementService."""


class TestGenerateStatement:
    """Test the main generate_statement method."""
    
    def test_generate_statement_success(self, service, mock_db_connection):
        """Test successful statement generation."""
        conn, cursor = mock_db_connection
        
        # Mock associate lookup
        cursor.fetchone.side_effect = [
            {"display_alias": "Test Associate"},  # Associate name lookup
            {"net_deposits_eur": 1000.0},     # Net deposits
            {"should_hold_eur": 1200.0},       # Should hold
            {"current_holding_eur": 1150.0}    # Current holding
        ]
        
        with patch('src.services.statement_service.get_db_connection', return_value=conn):
            result = service.generate_statement(1, "2025-10-31T23:59:59Z")
        
        # Verify result structure
        assert isinstance(result, StatementCalculations)
        assert result.associate_name == "Test Associate"
        assert result.cutoff_date == "2025-10-31T23:59:59Z"
        assert result.net_deposits_eur == Decimal("1000.00")
        assert result.should_hold_eur == Decimal("1200.00")
        assert result.current_holding_eur == Decimal("1150.00")
        assert result.raw_profit_eur == Decimal("200.00")  # 1200 - 1000
        assert result.delta_eur == Decimal("-50.00")      # 1150 - 1200
        
        # Verify database queries were executed
        assert cursor.execute.call_count == 4  # associate + 3 calculation queries
    
    def test_generate_statement_associate_not_found(self, service, mock_db_connection):
        """Test error when associate not found."""
        conn, cursor = mock_db_connection
        
        # Mock associate lookup returning None
        cursor.fetchone.return_value = None
        
        with patch('src.services.statement_service.get_db_connection', return_value=conn):
            with pytest.raises(ValueError, match="Associate ID 999 not found"):
                service.generate_statement(999, "2025-10-31T23:59:59Z")
    
    def test_generate_statement_database_error(self, service, mock_db_connection):
        """Test handling of database errors."""
        conn, cursor = mock_db_connection
        
        # Mock database error
        cursor.execute.side_effect = Exception("Database error")
        
        with patch('src.services.statement_service.get_db_connection', return_value=conn):
            with pytest.raises(Exception, match="Database error"):
                service.generate_statement(1, "2025-10-31T23:59:59Z")


class TestCalculationMethods:
    """Test individual calculation methods."""
    
    def test_calculate_net_deposits(self, service, mock_db_connection):
        """Test net deposits calculation."""
        conn, cursor = mock_db_connection
        
        # Mock query result
        cursor.fetchone.return_value = {"net_deposits_eur": 1000.0}
        
        result = service._calculate_net_deposits(conn, 1, "2025-10-31T23:59:59Z")
        
        assert result == Decimal("1000.00")
        
        # Verify SQL query
        cursor.execute.assert_called_once()
        query_args = cursor.execute.call_args[0]
        assert "WHERE associate_id = ?" in query_args[0]
        assert "type IN ('DEPOSIT', 'WITHDRAWAL')" in query_args[0]
        assert "created_at_utc <= ?" in query_args[0]
        assert query_args[1] == (1, "2025-10-31T23:59:59Z")
    
    def test_calculate_net_deposits_empty_result(self, service, mock_db_connection):
        """Test net deposits with no transactions."""
        conn, cursor = mock_db_connection
        
        # Mock empty result
        cursor.fetchone.return_value = {"net_deposits_eur": None}
        
        result = service._calculate_net_deposits(conn, 1, "2025-10-31T23:59:59Z")
        
        assert result == Decimal("0.00")
    
    def test_calculate_should_hold(self, service, mock_db_connection):
        """Test should hold calculation."""
        conn, cursor = mock_db_connection
        
        # Mock query result
        cursor.fetchone.return_value = {"should_hold_eur": 1200.0}
        
        result = service._calculate_should_hold(conn, 1, "2025-10-31T23:59:59Z")
        
        assert result == Decimal("1200.00")
        
        # Verify SQL query
        cursor.execute.assert_called_once()
        query_args = cursor.execute.call_args[0]
        assert "WHERE associate_id = ?" in query_args[0]
        assert "type = 'BET_RESULT'" in query_args[0]
        assert "principal_returned_eur IS NOT NULL" in query_args[0]
        assert "per_surebet_share_eur IS NOT NULL" in query_args[0]
        assert "created_at_utc <= ?" in query_args[0]
    
    def test_calculate_current_holding(self, service, mock_db_connection):
        """Test current holding calculation."""
        conn, cursor = mock_db_connection
        
        # Mock query result
        cursor.fetchone.return_value = {"current_holding_eur": 1150.0}
        
        result = service._calculate_current_holding(conn, 1, "2025-10-31T23:59:59Z")
        
        assert result == Decimal("1150.00")
        
        # Verify SQL query
        cursor.execute.assert_called_once()
        query_args = cursor.execute.call_args[0]
        assert "WHERE associate_id = ?" in query_args[0]
        assert "created_at_utc <= ?" in query_args[0]
        assert query_args[1] == (1, "2025-10-31T23:59:59Z")


class TestFormattingMethods:
    """Test formatting methods."""
    
    def test_format_partner_facing_section_profit(self, service, sample_calculations):
        """Test partner-facing section formatting with profit."""
        result = service.format_partner_facing_section(sample_calculations)
        
        assert isinstance(result, PartnerFacingSection)
        assert "You funded: €1,000.00 total" in result.funding_summary
        assert "You're entitled to: €1,200.00" in result.entitlement_summary
        assert "🟢 Profit: €200.00" in result.profit_loss_summary
        assert result.split_calculation["admin_share"] == "€100.00"
        assert result.split_calculation["associate_share"] == "€100.00"
        assert "50/50" in result.split_calculation["explanation"]
    
    def test_format_partner_facing_section_loss(self, service):
        """Test partner-facing section formatting with loss."""
        calc = StatementCalculations(
            net_deposits_eur=Decimal("1000.00"),
            should_hold_eur=Decimal("800.00"),
            current_holding_eur=Decimal("750.00"),
            raw_profit_eur=Decimal("-200.00"),
            delta_eur=Decimal("-50.00"),
            associate_name="Test Associate",
            cutoff_date="2025-10-31T23:59:59Z",
            generated_at="2025-11-05T11:00:00Z"
        )
        
        result = service.format_partner_facing_section(calc)
        
        assert "🔴 Loss: €-200.00" in result.profit_loss_summary
    
    def test_format_partner_facing_section_break_even(self, service):
        """Test partner-facing section formatting with break-even."""
        calc = StatementCalculations(
            net_deposits_eur=Decimal("1000.00"),
            should_hold_eur=Decimal("1000.00"),
            current_holding_eur=Decimal("1000.00"),
            raw_profit_eur=Decimal("0.00"),
            delta_eur=Decimal("0.00"),
            associate_name="Test Associate",
            cutoff_date="2025-10-31T23:59:59Z",
            generated_at="2025-11-05T11:00:00Z"
        )
        
        result = service.format_partner_facing_section(calc)
        
        assert "⚪ Break-even: €0.00" in result.profit_loss_summary
    
    def test_format_internal_section_holding_more(self, service):
        """Test internal section formatting when holding more."""
        calc = StatementCalculations(
            net_deposits_eur=Decimal("1000.00"),
            should_hold_eur=Decimal("1200.00"),
            current_holding_eur=Decimal("1300.00"),  # Holding more
            raw_profit_eur=Decimal("200.00"),
            delta_eur=Decimal("100.00"),  # Positive delta
            associate_name="Test Associate",
            cutoff_date="2025-10-31T23:59:59Z",
            generated_at="2025-11-05T11:00:00Z"
        )
        
        result = service.format_internal_section(calc)
        
        assert isinstance(result, InternalSection)
        assert "Currently holding: €1,300.00" in result.current_holdings
        assert "Holding more by €100.00" in result.reconciliation_delta
        assert result.delta_emoji == "🔴"
        assert result.delta_status == "Holding more by €100.00"
    
    def test_format_internal_section_short(self, service, sample_calculations):
        """Test internal section formatting when short."""
        result = service.format_internal_section(sample_calculations)
        
        assert "Currently holding: €1,150.00" in result.current_holdings
        assert "Short by €50.00" in result.reconciliation_delta
        assert result.delta_emoji == "🟠"
        assert result.delta_status == "Short by €50.00"
    
    def test_format_internal_section_balanced(self, service):
        """Test internal section formatting when balanced."""
        calc = StatementCalculations(
            net_deposits_eur=Decimal("1000.00"),
            should_hold_eur=Decimal("1200.00"),
            current_holding_eur=Decimal("1200.00"),  # Exactly balanced
            raw_profit_eur=Decimal("200.00"),
            delta_eur=Decimal("0.00"),  # Zero delta
            associate_name="Test Associate",
            cutoff_date="2025-10-31T23:59:59Z",
            generated_at="2025-11-05T11:00:00Z"
        )
        
        result = service.format_internal_section(calc)
        
        assert "Balanced" in result.reconciliation_delta
        assert result.delta_emoji == "🟢"
        assert result.delta_status == "Balanced"
    
    def test_format_currency(self, service):
        """Test currency formatting."""
        assert service._format_currency(Decimal("1234.56")) == "€1,234.56"
        assert service._format_currency(Decimal("0.00")) == "€0.00"
        assert service._format_currency(Decimal("-100.00")) == "€-100.00"
    
    def test_format_profit_loss(self, service):
        """Test profit/loss formatting."""
        assert service._format_profit_loss(Decimal("100.00")) == "🟢 Profit: €100.00"
        assert service._format_profit_loss(Decimal("-100.00")) == "🔴 Loss: €-100.00"
        assert service._format_profit_loss(Decimal("0.00")) == "⚪ Break-even: €0.00"


class TestValidationMethods:
    """Test validation methods."""
    
    def test_validate_cutoff_date_valid_past(self, service):
        """Test validation with valid past date."""
        # Past date should be valid
        valid_date = "2025-10-31T23:59:59Z"
        
        with patch('src.services.statement_service.utc_now_iso', return_value="2025-11-05T11:00:00Z"):
            assert service.validate_cutoff_date(valid_date) is True
    
    def test_validate_cutoff_date_valid_today(self, service):
        """Test validation with current date."""
        # Current date should be valid
        with patch('src.services.statement_service.utc_now_iso', return_value="2025-11-05T11:00:00Z"):
            assert service.validate_cutoff_date("2025-11-05T10:00:00Z") is True
    
    def test_validate_cutoff_date_invalid_future(self, service):
        """Test validation with future date."""
        # Future date should be invalid
        with patch('src.services.statement_service.utc_now_iso', return_value="2025-11-05T11:00:00Z"):
            assert service.validate_cutoff_date("2025-11-06T00:00:00Z") is False
    
    def test_validate_cutoff_date_invalid_format(self, service):
        """Test validation with invalid date format."""
        # Invalid format should be invalid
        assert service.validate_cutoff_date("invalid-date") is False
        assert service.validate_cutoff_date("") is False


class TestGetAssociateTransactions:
    """Test get_associate_transactions method."""
    
    def test_get_associate_transactions_success(self, service, mock_db_connection):
        """Test successful transaction retrieval."""
        conn, cursor = mock_db_connection
        
        # Mock transaction data
        mock_rows = [
            {
                "id": 1,
                "type": "DEPOSIT",
                "amount_eur": "1000.00",
                "native_currency": "EUR",
                "amount_native": "1000.00",
                "fx_rate_snapshot": "1.0",
                "settlement_state": None,
                "principal_returned_eur": None,
                "per_surebet_share_eur": None,
                "surebet_id": None,
                "bet_id": None,
                "created_at_utc": "2025-10-31T23:59:59Z",
                "note": "Initial deposit"
            },
            {
                "id": 2,
                "type": "BET_RESULT",
                "amount_eur": "100.00",
                "native_currency": "EUR",
                "amount_native": "100.00",
                "fx_rate_snapshot": "1.0",
                "settlement_state": "WON",
                "principal_returned_eur": "50.00",
                "per_surebet_share_eur": "25.00",
                "surebet_id": 1,
                "bet_id": 1,
                "created_at_utc": "2025-10-30T23:59:59Z",
                "note": "Bet settlement"
            }
        ]
        
        cursor.fetchall.return_value = mock_rows
        
        with patch('src.services.statement_service.get_db_connection', return_value=conn):
            result = service.get_associate_transactions(1, "2025-10-31T23:59:59Z")
        
        assert len(result) == 2
        assert result[0]["type"] == "DEPOSIT"
        assert result[1]["type"] == "BET_RESULT"
        
        # Verify SQL query
        cursor.execute.assert_called_once()
        query_args = cursor.execute.call_args[0]
        assert "WHERE associate_id = ?" in query_args[0]
        assert "created_at_utc <= ?" in query_args[0]
        assert "ORDER BY created_at_utc DESC" in query_args[0]
        assert query_args[1] == (1, "2025-10-31T23:59:59Z")
    
    def test_get_associate_transactions_empty_result(self, service, mock_db_connection):
        """Test transaction retrieval with no results."""
        conn, cursor = mock_db_connection
        
        cursor.fetchall.return_value = []
        
        with patch('src.services.statement_service.get_db_connection', return_value=conn):
            result = service.get_associate_transactions(1, "2025-10-31T23:59:59Z")
        
        assert result == []


class TestEdgeCases:
    """Test edge cases and error scenarios."""
    
    def test_calculations_with_large_decimals(self, service, mock_db_connection):
        """Test calculations with large decimal values."""
        conn, cursor = mock_db_connection
        
        # Mock large decimal values
        cursor.fetchone.side_effect = [
            {"display_alias": "Test Associate"},
            {"net_deposits_eur": 999999999.99},
            {"should_hold_eur": 1000000000.01},
            {"current_holding_eur": 999999998.50}
        ]
        
        with patch('src.services.statement_service.get_db_connection', return_value=conn):
            result = service.generate_statement(1, "2025-10-31T23:59:59Z")
        
        # Verify precision is maintained
        assert result.net_deposits_eur == Decimal("999999999.99")
        assert result.should_hold_eur == Decimal("1000000000.01")
        assert result.current_holding_eur == Decimal("999999998.50")
        assert result.raw_profit_eur == Decimal("0.02")  # 1000000000.01 - 999999999.99
        assert result.delta_eur == Decimal("-1.51")    # 999999998.50 - 1000000000.01
    
    def test_calculations_with_negative_values(self, service, mock_db_connection):
        """Test calculations with negative values."""
        conn, cursor = mock_db_connection
        
        # Mock negative values (e.g., withdrawals)
        cursor.fetchone.side_effect = [
            {"display_alias": "Test Associate"},
            {"net_deposits_eur": -500.00},     # More withdrawals than deposits
            {"should_hold_eur": 0.00},         # No bet results
            {"current_holding_eur": -500.00}    # Negative balance
        ]
        
        with patch('src.services.statement_service.get_db_connection', return_value=conn):
            result = service.generate_statement(1, "2025-10-31T23:59:59Z")
        
        assert result.net_deposits_eur == Decimal("-500.00")
        assert result.should_hold_eur == Decimal("0.00")
        assert result.current_holding_eur == Decimal("-500.00")
        assert result.raw_profit_eur == Decimal("500.00")   # 0 - (-500)
        assert result.delta_eur == Decimal("-500.00")        # -500 - 0
