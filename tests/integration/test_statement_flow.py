"""
Integration tests for Statement generation workflow.

Tests complete flow from UI to database with realistic data scenarios.
"""

import pytest
from decimal import Decimal
from datetime import datetime
from unittest.mock import patch, Mock

from src.services.statement_service import StatementService


@pytest.fixture
def service():
    """Create StatementService instance."""
    return StatementService()


@pytest.fixture
def sample_associate_data():
    """Sample associate data for testing."""
    return {
        "id": 1,
        "display_alias": "Test Associate",
        "home_currency": "EUR",
    }


@pytest.fixture
def sample_ledger_entries():
    """Sample ledger entries for testing."""
    return [
        # Deposits
        {
            "id": 1,
            "type": "DEPOSIT",
            "associate_id": 1,
            "amount_eur": "1000.00",
            "native_currency": "EUR",
            "amount_native": "1000.00",
            "fx_rate_snapshot": "1.0",
            "settlement_state": None,
            "principal_returned_eur": None,
            "per_surebet_share_eur": None,
            "surebet_id": None,
            "bet_id": None,
            "created_at_utc": "2025-10-15T10:00:00Z",
            "note": "Initial deposit"
        },
        # Bet result - WON
        {
            "id": 2,
            "type": "BET_RESULT",
            "associate_id": 1,
            "amount_eur": "-100.00",
            "native_currency": "EUR",
            "amount_native": "-100.00",
            "fx_rate_snapshot": "1.0",
            "settlement_state": "WON",
            "principal_returned_eur": "100.00",
            "per_surebet_share_eur": "50.00",
            "surebet_id": 1,
            "bet_id": 1,
            "created_at_utc": "2025-10-20T15:00:00Z",
            "note": "Bet settlement - Won"
        },
        # Withdrawal
        {
            "id": 3,
            "type": "WITHDRAWAL",
            "associate_id": 1,
            "amount_eur": "-200.00",
            "native_currency": "EUR",
            "amount_native": "-200.00",
            "fx_rate_snapshot": "1.0",
            "settlement_state": None,
            "principal_returned_eur": None,
            "per_surebet_share_eur": None,
            "surebet_id": None,
            "bet_id": None,
            "created_at_utc": "2025-10-25T12:00:00Z",
            "note": "Withdrawal"
        },
        # Another bet result - WON
        {
            "id": 4,
            "type": "BET_RESULT",
            "associate_id": 1,
            "amount_eur": "-150.00",
            "native_currency": "EUR",
            "amount_native": "-150.00",
            "fx_rate_snapshot": "1.0",
            "settlement_state": "WON",
            "principal_returned_eur": "150.00",
            "per_surebet_share_eur": "75.00",
            "surebet_id": 2,
            "bet_id": 2,
            "created_at_utc": "2025-10-28T18:00:00Z",
            "note": "Bet settlement - Won"
        }
    ]


@pytest.fixture
def mock_database_with_data(sample_associate_data, sample_ledger_entries):
    """Mock database with sample data."""
    conn = Mock()
    cursor = Mock()
    conn.cursor.return_value = cursor
    conn.close = Mock()
    
    # Mock associate lookup
    def mock_execute(query, params=None):
        normalized = " ".join(query.split())
        if "SELECT display_alias" in normalized and "FROM associates" in normalized:
            cursor.fetchone.return_value = sample_associate_data
            cursor.fetchall.return_value = []
        elif "SUM(CASE WHEN type = 'DEPOSIT'" in normalized and "total_deposits" in normalized:
            cursor.fetchone.return_value = {
                "total_deposits": 1000.0,
                "total_withdrawals": 200.0,
            }
        elif "principal_returned_eur AS REAL" in normalized:
            cursor.fetchone.return_value = {"should_hold_eur": 275.0}
        elif "SUM(CAST(amount_eur AS REAL)) AS current_holding_eur" in normalized:
            cursor.fetchone.return_value = {"current_holding_eur": 550.0}
        elif "FROM bookmakers" in normalized and "balance_eur" in normalized:
            cursor.fetchone.return_value = None
            cursor.fetchall.return_value = [
                {
                    "bookmaker_name": "Bookie One",
                    "balance_eur": 550.0,
                    "deposits_eur": 1000.0,
                    "withdrawals_eur": 200.0,
                    "balance_native": 550.0,
                    "native_currency": "EUR",
                }
            ]
        elif "SELECT id, type, amount_eur" in normalized:
            cursor.fetchone.return_value = None
            cursor.fetchall.return_value = sample_ledger_entries
        else:
            cursor.fetchone.return_value = None
            cursor.fetchall.return_value = []
    
    cursor.execute.side_effect = mock_execute
    
    return conn, cursor


class TestCompleteStatementGeneration:
    """Test complete statement generation with realistic data."""
    
    def test_profitable_associate_statement(self, service, mock_database_with_data):
        """Test statement generation for profitable associate."""
        conn, cursor = mock_database_with_data
        
        with patch('src.services.statement_service.get_db_connection', return_value=conn):
            result = service.generate_statement(1, "2025-10-31T23:59:59Z")
        
        # Verify calculations
        assert result.associate_name == "Test Associate"
        assert result.net_deposits_eur == Decimal("800.00")    # 1000 deposit - 200 withdrawal
        assert result.should_hold_eur == Decimal("275.00")      # 100+50 + 150+75
        assert result.current_holding_eur == Decimal("550.00")   # 1000 - 100 - 200 - 150
        assert result.raw_profit_eur == Decimal("-525.00")       # 275 - 800 (loss)
        assert result.delta_eur == Decimal("275.00")           # 550 - 275
        
        # Verify database was called correctly
        assert cursor.execute.call_count >= 4  # associate + 3 calculations
    
    def test_loss_associate_statement(self, service):
        """Test statement generation for associate with losses."""
        conn = Mock()
        cursor = Mock()
        conn.cursor.return_value = cursor
        
        # Mock data for loss scenario
        cursor.fetchone.side_effect = [
            {"display_alias": "Loss Associate", "home_currency": "EUR"},
            {"total_deposits": 2000.0, "total_withdrawals": 0.0},
            {"should_hold_eur": 1200.0},
            {"current_holding_eur": 1100.0},
        ]
        cursor.fetchall.return_value = []
        
        with patch('src.services.statement_service.get_db_connection', return_value=conn):
            result = service.generate_statement(1, "2025-10-31T23:59:59Z")
        
        assert result.net_deposits_eur == Decimal("2000.00")
        assert result.should_hold_eur == Decimal("1200.00")
        assert result.current_holding_eur == Decimal("1100.00")
        assert result.raw_profit_eur == Decimal("-800.00")    # 1200 - 2000 (loss)
        assert result.delta_eur == Decimal("-100.00")        # 1100 - 1200 (short)
    
    def test_balanced_associate_statement(self, service):
        """Test statement generation for balanced associate."""
        conn = Mock()
        cursor = Mock()
        conn.cursor.return_value = cursor
        
        # Mock data for balanced scenario
        cursor.fetchone.side_effect = [
            {"display_alias": "Balanced Associate", "home_currency": "EUR"},
            {"total_deposits": 1000.0, "total_withdrawals": 0.0},
            {"should_hold_eur": 1000.0},
            {"current_holding_eur": 1000.0},
        ]
        cursor.fetchall.return_value = []
        
        with patch('src.services.statement_service.get_db_connection', return_value=conn):
            result = service.generate_statement(1, "2025-10-31T23:59:59Z")
        
        assert result.net_deposits_eur == Decimal("1000.00")
        assert result.should_hold_eur == Decimal("1000.00")
        assert result.current_holding_eur == Decimal("1000.00")
        assert result.raw_profit_eur == Decimal("0.00")      # 1000 - 1000 (break-even)
        assert result.delta_eur == Decimal("0.00")           # 1000 - 1000 (balanced)


class TestTransactionRetrieval:
    """Test transaction retrieval for export functionality."""
    
    def test_get_associate_transactions_for_export(self, service, mock_database_with_data):
        """Test transaction retrieval for CSV export."""
        conn, cursor = mock_database_with_data
        
        with patch('src.services.statement_service.get_db_connection', return_value=conn):
            transactions = service.get_associate_transactions(1, "2025-10-31T23:59:59Z")
        
        assert len(transactions) == 4
        assert transactions[0]["type"] == "DEPOSIT"
        assert transactions[1]["type"] == "BET_RESULT"
        assert transactions[2]["type"] == "WITHDRAWAL"
        assert transactions[3]["type"] == "BET_RESULT"
        
        # Verify cutoff date filtering (all transactions should be before cutoff)
        for transaction in transactions:
            assert transaction["created_at_utc"] <= "2025-10-31T23:59:59Z"
    
    def test_get_associate_transactions_empty_result(self, service):
        """Test transaction retrieval with no matching transactions."""
        conn = Mock()
        cursor = Mock()
        conn.cursor.return_value = cursor
        
        cursor.fetchall.return_value = []
        
        with patch('src.services.statement_service.get_db_connection', return_value=conn):
            transactions = service.get_associate_transactions(1, "2025-10-31T23:59:59Z")
        
        assert transactions == []


class TestFormattingIntegration:
    """Test formatting with realistic scenarios."""
    
    def test_partner_facing_section_realistic_profit(self, service):
        """Test partner-facing formatting with realistic profit scenario."""
        from src.services.statement_service import StatementCalculations, BookmakerStatementRow

        calc = StatementCalculations(
            associate_id=1,
            net_deposits_eur=Decimal("5000.00"),
            should_hold_eur=Decimal("7500.00"),
            current_holding_eur=Decimal("7200.00"),
            raw_profit_eur=Decimal("2500.00"),
            delta_eur=Decimal("-300.00"),
            total_deposits_eur=Decimal("5000.00"),
            total_withdrawals_eur=Decimal("0.00"),
            bookmakers=[
                BookmakerStatementRow(
                    bookmaker_name="Profitable Bookie",
                    balance_eur=Decimal("7200.00"),
                    deposits_eur=Decimal("5000.00"),
                    withdrawals_eur=Decimal("0.00"),
                    balance_native=Decimal("7200.00"),
                    native_currency="EUR",
                )
            ],
            associate_name="Profitable Associate",
            home_currency="EUR",
            cutoff_date="2025-10-31T23:59:59Z",
            generated_at="2025-11-05T11:00:00Z"
        )
        
        result = service.format_partner_facing_section(calc)
        
        # Verify realistic profit formatting
        assert result.total_deposits_eur == Decimal("5000.00")
        assert result.holdings_eur == Decimal("7200.00")
        assert result.bookmakers[0].bookmaker_name == "Profitable Bookie"
    
    def test_internal_section_realistic_scenarios(self, service):
        """Test internal section formatting with realistic scenarios."""
        from src.services.statement_service import StatementCalculations
        
        # Test holding more scenario
        calc_holding_more = StatementCalculations(
            associate_id=1,
            net_deposits_eur=Decimal("1000.00"),
            should_hold_eur=Decimal("2000.00"),
            current_holding_eur=Decimal("2500.00"),
            raw_profit_eur=Decimal("1000.00"),
            delta_eur=Decimal("500.00"),
            total_deposits_eur=Decimal("1000.00"),
            total_withdrawals_eur=Decimal("0.00"),
            bookmakers=[],
            associate_name="Test Associate",
            home_currency="EUR",
            cutoff_date="2025-10-31T23:59:59Z",
            generated_at="2025-11-05T11:00:00Z"
        )
        
        result = service.format_internal_section(calc_holding_more)
        assert "Currently holding: EUR 2,500.00" in result.current_holdings
        assert "Holding more by EUR 500.00" in result.reconciliation_delta
        assert result.delta_indicator == "over"
        
        # Test short scenario
        calc_short = StatementCalculations(
            associate_id=1,
            net_deposits_eur=Decimal("1000.00"),
            should_hold_eur=Decimal("2000.00"),
            current_holding_eur=Decimal("1500.00"),
            raw_profit_eur=Decimal("1000.00"),
            delta_eur=Decimal("-500.00"),
            total_deposits_eur=Decimal("1000.00"),
            total_withdrawals_eur=Decimal("0.00"),
            bookmakers=[],
            associate_name="Test Associate",
            home_currency="EUR",
            cutoff_date="2025-10-31T23:59:59Z",
            generated_at="2025-11-05T11:00:00Z"
        )
        
        result_short = service.format_internal_section(calc_short)
        assert "Short by EUR 500.00" in result_short.reconciliation_delta
        assert result_short.delta_indicator == "short"


class TestCutoffDateScenarios:
    """Test various cutoff date scenarios."""
    
    def test_month_end_cutoff(self, service):
        """Test statement generation with month-end cutoff."""
        conn = Mock()
        cursor = Mock()
        conn.cursor.return_value = cursor
        
        # Mock data
        cursor.fetchone.side_effect = [
            {"display_alias": "Test Associate", "home_currency": "EUR"},
            {"total_deposits": 1000.0, "total_withdrawals": 0.0},
            {"should_hold_eur": 1200.0},
            {"current_holding_eur": 1150.0},
        ]
        cursor.fetchall.return_value = []
        
        with patch('src.services.statement_service.get_db_connection', return_value=conn):
            result = service.generate_statement(1, "2025-10-31T23:59:59Z")
        
        assert result.cutoff_date == "2025-10-31T23:59:59Z"
        
        # Verify cutoff date was used in queries
        execute_calls = cursor.execute.call_args_list
        cutoff_date_found = False
        for call in execute_calls:
            if call[0] and "created_at_utc <= ?" in call[0][0]:
                cutoff_date_found = True
                assert "2025-10-31T23:59:59Z" in call[0][1]
        
        assert cutoff_date_found
    
    def test_mid_month_cutoff(self, service):
        """Test statement generation with mid-month cutoff."""
        conn = Mock()
        cursor = Mock()
        conn.cursor.return_value = cursor
        
        # Mock data
        cursor.fetchone.side_effect = [
            {"display_alias": "Test Associate", "home_currency": "EUR"},
            {"total_deposits": 500.0, "total_withdrawals": 0.0},
            {"should_hold_eur": 600.0},
            {"current_holding_eur": 550.0}
        ]
        cursor.fetchall.return_value = []
        
        with patch('src.services.statement_service.get_db_connection', return_value=conn):
            result = service.generate_statement(1, "2025-10-15T23:59:59Z")
        
        assert result.cutoff_date == "2025-10-15T23:59:59Z"
        
        # Verify cutoff date was used in queries
        execute_calls = cursor.execute.call_args_list
        cutoff_date_found = False
        for call in execute_calls:
            if call[0] and "created_at_utc <= ?" in call[0][0]:
                cutoff_date_found = True
                assert "2025-10-15T23:59:59Z" in call[0][1]
        
        assert cutoff_date_found


class TestErrorHandlingIntegration:
    """Test error handling in realistic scenarios."""
    
    def test_database_connection_failure(self, service):
        """Test handling of database connection failure."""
        with patch('src.services.statement_service.get_db_connection') as mock_get_conn:
            mock_get_conn.side_effect = Exception("Database connection failed")
            
            with pytest.raises(Exception, match="Database connection failed"):
                service.generate_statement(1, "2025-10-31T23:59:59Z")
    
    def test_partial_data_scenarios(self, service):
        """Test scenarios with partial or missing data."""
        conn = Mock()
        cursor = Mock()
        conn.cursor.return_value = cursor
        
        # Mock scenario where some calculations return NULL
        cursor.fetchone.side_effect = [
            {"display_alias": "Test Associate", "home_currency": "EUR"},
            {"total_deposits": 1000.0, "total_withdrawals": 0.0},
            {"should_hold_eur": None},    # No bet results yet
            {"current_holding_eur": 1000.0}
        ]
        cursor.fetchall.return_value = []
        
        with patch('src.services.statement_service.get_db_connection', return_value=conn):
            result = service.generate_statement(1, "2025-10-31T23:59:59Z")
        
        # Should handle NULL gracefully
        assert result.should_hold_eur == Decimal("0.00")
        assert result.raw_profit_eur == Decimal("-1000.00")  # 0 - 1000
        assert result.delta_eur == Decimal("1000.00")      # 1000 - 0


class TestLargeDatasetPerformance:
    """Test performance with large datasets."""
    
    def test_large_transaction_history(self, service):
        """Test handling of large transaction history."""
        conn = Mock()
        cursor = Mock()
        conn.cursor.return_value = cursor
        
        # Mock calculation results
        cursor.fetchone.side_effect = [
            {"display_alias": "High Volume Associate", "home_currency": "EUR"},
            {"total_deposits": 50000.0, "total_withdrawals": 0.0},
            {"should_hold_eur": 55000.0},
            {"current_holding_eur": 54500.0}
        ]
        
        # Mock large transaction list
        large_transaction_list = []
        for i in range(1000):
            large_transaction_list.append({
                "id": i,
                "type": "BET_RESULT",
                "amount_eur": "100.00",
                "created_at_utc": "2025-10-31T23:59:59Z"
            })
        
        def execute_side_effect(query, params=None):
            normalized = " ".join(query.split())
            if "SELECT id, type, amount_eur" in normalized:
                cursor.fetchall.return_value = large_transaction_list
            elif "FROM bookmakers" in normalized:
                cursor.fetchall.return_value = []
            else:
                cursor.fetchall.return_value = []

        cursor.execute.side_effect = execute_side_effect
        
        with patch('src.services.statement_service.get_db_connection', return_value=conn):
            transactions = service.get_associate_transactions(1, "2025-10-31T23:59:59Z")
        
        assert len(transactions) == 1000
        
        # Test that calculations still work with large values
        with patch('src.services.statement_service.get_db_connection', return_value=conn):
            result = service.generate_statement(1, "2025-10-31T23:59:59Z")
        assert result.net_deposits_eur == Decimal("50000.00")
        assert result.should_hold_eur == Decimal("55000.00")
        assert result.current_holding_eur == Decimal("54500.00")



