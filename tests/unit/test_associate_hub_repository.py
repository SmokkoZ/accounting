"""
Unit tests for AssociateHubRepository (Story 5.5)

Tests for associate and bookmaker aggregation queries with various filter combinations.
"""

import pytest
import sqlite3
from decimal import Decimal
from typing import List
from unittest.mock import Mock, patch

from src.repositories.associate_hub_repository import (
    AssociateHubRepository,
    AssociateMetrics,
    BookmakerSummary
)


class TestAssociateHubRepository:
    """Test cases for AssociateHubRepository."""
    
    @pytest.fixture
    def mock_db(self):
        """Mock database connection."""
        mock_conn = Mock(spec=sqlite3.Connection)
        mock_cursor = Mock(spec=sqlite3.Cursor)
        mock_conn.execute.return_value = mock_cursor
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.commit.return_value = None
        return mock_conn
    
    @pytest.fixture
    def repository(self, mock_db):
        """Create repository instance with mocked database."""
        return AssociateHubRepository(mock_db)
    
    def test_init(self, mock_db):
        """Test repository initialization."""
        repo = AssociateHubRepository(mock_db)
        assert repo.db == mock_db
    
    def test_list_associates_with_metrics_basic(self, repository, mock_db):
        """Test basic associate listing without filters."""
        # Mock database response
        mock_rows = [
            {
                'associate_id': 1,
                'associate_alias': 'Test User',
                'is_admin': 1,
                'is_active': 1,
                'home_currency': 'EUR',
                'telegram_chat_id': '123456',
                'net_deposits_eur': '1000.00',
                'fair_share_eur': '50.00',
                'current_holding_eur': '950.00',
                'pending_balance_eur': '75.00',
                'bookmaker_count': 3,
                'active_bookmaker_count': 2,
                'last_activity_utc': '2025-01-01T12:00:00Z'
            }
        ]
        
        mock_db.execute.return_value.fetchall.return_value = mock_rows
        
        # Call method
        result = repository.list_associates_with_metrics()
        
        # Verify query was called
        mock_db.execute.assert_called_once()
        
        # Verify result structure
        assert len(result) == 1
        associate = result[0]
        assert associate.associate_id == 1
        assert associate.associate_alias == 'Test User'
        assert associate.is_admin == True
        assert associate.is_active == True
        assert associate.home_currency == 'EUR'
        assert associate.telegram_chat_id == '123456'
        assert associate.net_deposits_eur == Decimal('1000.00')
        assert associate.fair_share_eur == Decimal('50.00')
        assert associate.should_hold_eur == Decimal('1050.00')
        assert associate.current_holding_eur == Decimal('950.00')
        assert associate.balance_eur == Decimal('950.00')
        assert associate.pending_balance_eur == Decimal('75.00')
        assert associate.delta_eur == Decimal('-100.00')
        assert associate.bookmaker_count == 3
        assert associate.active_bookmaker_count == 2
        assert associate.last_activity_utc == '2025-01-01T12:00:00Z'
        assert associate.status == "short"
        assert associate.delta_display() == "-€100.00"
        assert associate.title() == "Short"
        assert associate.status_color == "#ffebee"
    
    def test_list_associates_with_filters(self, repository, mock_db):
        """Test associate listing with filters applied."""
        mock_db.execute.return_value.fetchall.return_value = []
        
        # Call with filters
        repository.list_associates_with_metrics(
            search="test",
            admin_filter=[True],
            associate_status_filter=[True],
            bookmaker_status_filter=[True],
            risk_filter=["balanced", "overholding"],
            currency_filter=["EUR", "GBP"],
            sort_by="delta_desc",
            limit=25,
            offset=0
        )
        
        # Verify query was called with correct parameters
        mock_db.execute.assert_called_once()
        call_args = mock_db.execute.call_args
        
        # Check that search term is in the query
        query = call_args[0][0]
        assert "WHERE" in query
        assert "LOWER(a.display_alias) LIKE ?" in query
        assert "LOWER(COALESCE(a.multibook_chat_id, '')) LIKE ?" in query
        assert "LOWER(COALESCE(bsearch.bookmaker_name, '')) LIKE ?" in query
        assert "LOWER(COALESCE(bsearch.bookmaker_chat_id, '')) LIKE ?" in query
        assert "a.is_admin IN" in query
        assert "a.is_active IN" in query
        assert "UPPER(a.home_currency) IN" in query
        assert "HAVING CASE" in query
        assert "ORDER BY" in query
        assert "LIMIT ? OFFSET ?" in query
        params = call_args[0][1]
        assert "balanced" in params
        assert "overholding" in params

    def test_list_associates_with_risk_filter(self, repository, mock_db):
        """Ensure risk filter adds HAVING clause and normalizes slugs."""
        mock_db.execute.return_value.fetchall.return_value = []

        repository.list_associates_with_metrics(
            risk_filter=["balanced", "Balanced", "unknown", "short"],
            limit=10,
        )

        call_args = mock_db.execute.call_args
        query = call_args[0][0]
        params = call_args[0][1]
        assert "HAVING CASE" in query
        assert params.count("balanced") == 1
        assert "short" in params
        assert "unknown" not in params
    
    def test_list_associates_with_sort_options(self, repository, mock_db):
        """Test different sorting options."""
        mock_db.execute.return_value.fetchall.return_value = []
        
        # Test each sort option
        sort_options = [
            "alias_asc",
            "alias_desc",
            "nd_asc",
            "nd_desc",
            "delta_asc",
            "delta_desc",
            "activity_asc",
            "activity_desc",
            "balance_asc",
            "balance_desc",
            "pending_asc",
            "pending_desc",
            "bookmaker_active_desc",
        ]
        
        for sort_option in sort_options:
            repository.list_associates_with_metrics(sort_by=sort_option)
            
            # Verify query contains appropriate ORDER BY clause
            call_args = mock_db.execute.call_args
            query = call_args[0][0]
            assert "ORDER BY" in query
    
    def test_get_associate_for_edit(self, repository, mock_db):
        """Test retrieving associate for editing."""
        # Mock database response
        mock_row = {
            'id': 1,
            'display_alias': 'Test User',
            'is_admin': 1,
            'is_active': 1,
            'home_currency': 'EUR',
            'multibook_chat_id': '123456',
            'internal_notes': 'notes',
            'max_surebet_stake_eur': '100.00',
            'max_bookmaker_exposure_eur': '200.00',
            'preferred_balance_chat_id': '-999',
            'created_at_utc': '2025-01-01T00:00:00Z',
            'updated_at_utc': '2025-01-01T00:00:00Z'
        }
        
        mock_db.execute.return_value.fetchone.return_value = mock_row
        
        # Call method
        result = repository.get_associate_for_edit(1)
        
        # Verify query
        mock_db.execute.assert_called_once()
        
        # Verify result
        assert result is not None
        assert result['id'] == 1
        assert result['display_alias'] == 'Test User'
        assert result['is_admin'] == True
        assert result['is_active'] == True
        assert result['home_currency'] == 'EUR'
        assert result['telegram_chat_id'] == '123456'
        assert result['internal_notes'] == 'notes'
        assert result['max_surebet_stake_eur'] == '100.00'
        assert result['max_bookmaker_exposure_eur'] == '200.00'
        assert result['preferred_balance_chat_id'] == '-999'
    
    def test_get_associate_for_edit_not_found(self, repository, mock_db):
        """Test retrieving non-existent associate."""
        mock_db.execute.return_value.fetchone.return_value = None
        
        result = repository.get_associate_for_edit(999)
        
        assert result is None
    
    def test_update_associate(self, repository, mock_db):
        """Test updating associate details."""
        # Mock successful update
        mock_db.execute.return_value = Mock()
        
        # Call method
        repository.update_associate(
            associate_id=1,
            display_alias="Updated User",
            home_currency="GBP",
            is_admin=False,
            is_active=True,
            telegram_chat_id="789012",
            internal_notes="note",
            max_surebet_stake_eur="100",
            max_bookmaker_exposure_eur="200",
            preferred_balance_chat_id="-111",
        )
        
        # Verify query was called
        mock_db.execute.assert_called_once()
        call_args = mock_db.execute.call_args
        
        query = call_args[0][0]
        params = call_args[0][1]
        
        assert "UPDATE associates" in query
        assert "display_alias = ?" in query
        assert "home_currency = ?" in query
        assert "is_admin = ?" in query
        assert "is_active = ?" in query
        assert "multibook_chat_id = ?" in query
        assert "preferred_balance_chat_id = ?" in query
        assert "WHERE id = ?" in query
        
        assert params[0] == "Updated User"
        assert params[1] == "GBP"
        assert params[2] is False
        assert params[3] is True
        assert params[4] == "789012"
        assert params[5] == "note"
        assert params[6] == "100.00"
        assert params[7] == "200.00"
        assert params[8] == "-111"
        assert params[10] == 1
        
        # Repository uses context manager for transactions, no explicit commit needed
    
    def test_list_bookmakers_for_associate(self, repository, mock_db):
        """Test retrieving bookmakers for associate."""
        # Mock database response
        mock_rows = [
            {
                'bookmaker_id': 1,
                'bookmaker_name': 'Bookmaker A',
                'is_active': 1,
                'parsing_profile': None,
                'account_currency': 'AUD',
                'bookmaker_chat_id': '-100',
                'coverage_chat_id': '-200',
                'region': 'EU',
                'risk_level': 'High',
                'internal_notes': 'note',
                'associate_alias': 'Tester',
                'associate_home_currency': 'EUR',
                'modeled_balance_eur': '500.00',
                'reported_balance_eur': '520.00',
                'balance_native': '800.00',
                'check_native_currency': 'USD',
                'fx_rate_used': '1.60',
                'pending_balance_eur': '50.00',
                'last_balance_check_utc': '2025-01-01T10:00:00Z'
            }
        ]
        
        mock_db.execute.return_value.fetchall.return_value = mock_rows
        
        # Call method
        result = repository.list_bookmakers_for_associate(1)
        
        # Verify query
        mock_db.execute.assert_called_once()
        
        # Verify result
        assert len(result) == 1
        bookmaker = result[0]
        assert bookmaker.bookmaker_id == 1
        assert bookmaker.bookmaker_name == 'Bookmaker A'
        assert bookmaker.is_active == True
        assert bookmaker.parsing_profile is None
        assert bookmaker.associate_id == 1
        assert bookmaker.associate_alias == 'Tester'
        assert bookmaker.native_currency == 'USD'
        assert bookmaker.account_currency == 'AUD'
        assert bookmaker.modeled_balance_eur == Decimal('500.00')
        assert bookmaker.reported_balance_eur == Decimal('520.00')
        assert bookmaker.delta_eur == Decimal('20.00')
        assert bookmaker.pending_balance_eur == Decimal('50.00')
        assert bookmaker.active_balance_native == Decimal('800.00')
        assert bookmaker.pending_balance_native == Decimal('31.25')
        assert bookmaker.bookmaker_chat_id == '-100'
        assert bookmaker.coverage_chat_id == '-200'
        assert bookmaker.internal_notes == 'note'
        assert bookmaker.last_balance_check_utc == '2025-01-01T10:00:00Z'
    
    def test_update_bookmaker(self, repository, mock_db):
        """Test updating bookmaker details."""
        repository.get_bookmaker_for_edit = Mock(
            return_value={
                "associate_id": 1,
                "account_currency": "EUR",
                "bookmaker_chat_id": None,
                "coverage_chat_id": None,
                "region": None,
                "risk_level": None,
                "internal_notes": None,
                "parsing_profile": None,
            }
        )
        mock_db.execute.return_value = Mock()
        # Call method
        repository.update_bookmaker(
            bookmaker_id=1,
            bookmaker_name="Updated Bookmaker",
            is_active=False,
            parsing_profile='{"test": "profile"}',
            associate_id=2,
            account_currency="USD",
            bookmaker_chat_id="-1",
            internal_notes="note",
        )
        
        # Verify query
        mock_db.execute.assert_called_once()
        call_args = mock_db.execute.call_args
        
        query = call_args[0][0]
        params = call_args[0][1]
        
        assert "UPDATE bookmakers" in query
        assert "bookmaker_name = ?" in query
        assert "associate_id = ?" in query
        assert "is_active = ?" in query
        assert "parsing_profile = ?" in query
        assert "bookmaker_chat_id = ?" in query
        assert "WHERE id = ?" in query
        
        assert params[0] == "Updated Bookmaker"
        assert params[1] == 2
        assert params[2] == "USD"
        assert params[3] is False
        assert params[4] == '{"test": "profile"}'
        assert params[5] == "-1"
        assert params[9] == "note"
        assert params[11] == 1
        
        mock_db.commit.assert_called_once()
    
    def test_database_error_handling(self, repository, mock_db):
        """Test handling of database errors."""
        # Mock database error
        mock_db.execute.side_effect = sqlite3.Error("Database error")
        
        # Call should raise exception
        with pytest.raises(sqlite3.Error):
            repository.list_associates_with_metrics()
    
    def test_empty_results(self, repository, mock_db):
        """Test handling of empty query results."""
        mock_db.execute.return_value.fetchall.return_value = []
        
        result = repository.list_associates_with_metrics()
        
        assert result == []


class TestAssociateMetrics:
    """Test cases for AssociateMetrics dataclass."""
    
    def test_balanced_status(self):
        """Test balanced status calculation."""
        metrics = AssociateMetrics(
            associate_id=1,
            associate_alias="Test",
            home_currency="EUR",
            is_admin=False,
            is_active=True,
            telegram_chat_id=None,
            bookmaker_count=2,
            active_bookmaker_count=2,
            net_deposits_eur=Decimal('1000.00'),
            should_hold_eur=Decimal('1000.00'),
            fair_share_eur=Decimal('0.00'),
            current_holding_eur=Decimal('1000.00'),
            balance_eur=Decimal('1000.00'),
            pending_balance_eur=Decimal('0.00'),
            delta_eur=Decimal('0.00'),
            last_activity_utc=None,
            status="balanced",
            status_color="#e8f5e9"
        )
        
        assert metrics.status == "balanced"
        assert metrics.status_color == "#e8f5e9"
        assert metrics.title() == "Balanced"
        assert metrics.delta_display() == "+€0.00"
    
    def test_overholding_status(self):
        """Test overholding status calculation."""
        metrics = AssociateMetrics(
            associate_id=1,
            associate_alias="Test",
            home_currency="EUR",
            is_admin=False,
            is_active=True,
            telegram_chat_id=None,
            bookmaker_count=2,
            active_bookmaker_count=2,
            net_deposits_eur=Decimal('1000.00'),
            should_hold_eur=Decimal('1000.00'),
            fair_share_eur=Decimal('0.00'),
            current_holding_eur=Decimal('1050.00'),
            balance_eur=Decimal('1050.00'),
            pending_balance_eur=Decimal('25.00'),
            delta_eur=Decimal('50.00'),
            last_activity_utc=None,
            status="overholding",
            status_color="#fff3e0"
        )
        
        assert metrics.status == "overholding"
        assert metrics.status_color == "#fff3e0"
        assert metrics.title() == "Overholding"
        assert metrics.delta_display() == "+€50.00"
    
    def test_short_status(self):
        """Test short status calculation."""
        metrics = AssociateMetrics(
            associate_id=1,
            associate_alias="Test",
            home_currency="EUR",
            is_admin=False,
            is_active=True,
            telegram_chat_id=None,
            bookmaker_count=2,
            active_bookmaker_count=2,
            net_deposits_eur=Decimal('1000.00'),
            should_hold_eur=Decimal('1000.00'),
            fair_share_eur=Decimal('0.00'),
            current_holding_eur=Decimal('950.00'),
            balance_eur=Decimal('950.00'),
            pending_balance_eur=Decimal('75.00'),
            delta_eur=Decimal('-50.00'),
            last_activity_utc=None,
            status="short",
            status_color="#ffebee"
        )
        
        assert metrics.status == "short"
        assert metrics.status_color == "#ffebee"
        assert metrics.title() == "Short"
        assert metrics.delta_display() == "-€50.00"


class TestBookmakerSummary:
    """Test cases for BookmakerSummary dataclass."""
    
    def test_bookmaker_summary_creation(self):
        """Test bookmaker summary creation."""
        summary = BookmakerSummary(
            associate_id=1,
            bookmaker_id=1,
            bookmaker_name="Test Bookmaker",
            is_active=True,
            parsing_profile=None,
            native_currency="EUR",
            modeled_balance_eur=Decimal('500.00'),
            reported_balance_eur=Decimal('520.00'),
            delta_eur=Decimal('20.00'),
            last_balance_check_utc="2025-01-01T10:00:00Z",
            status="balanced",
            status_icon="🟢",
            status_color="#e8f5e9"
        )
        
        assert summary.bookmaker_id == 1
        assert summary.bookmaker_name == "Test Bookmaker"
        assert summary.is_active == True
        assert summary.parsing_profile is None
        assert summary.associate_id == 1
        assert summary.native_currency == "EUR"
        assert summary.modeled_balance_eur == Decimal('500.00')
        assert summary.reported_balance_eur == Decimal('520.00')
        assert summary.delta_eur == Decimal('20.00')
        assert summary.last_balance_check_utc == "2025-01-01T10:00:00Z"
    
    def test_bookmaker_summary_null_values(self):
        """Test bookmaker summary with null values."""
        summary = BookmakerSummary(
            associate_id=1,
            bookmaker_id=1,
            bookmaker_name="Test Bookmaker",
            is_active=True,
            parsing_profile=None,
            native_currency="EUR",
            modeled_balance_eur=Decimal('500.00'),
            reported_balance_eur=None,
            delta_eur=None,
            last_balance_check_utc=None,
            status="unverified",
            status_icon="⚪",
            status_color="#eceff1"
        )
        
        assert summary.reported_balance_eur is None
        assert summary.delta_eur is None
        assert summary.last_balance_check_utc is None
