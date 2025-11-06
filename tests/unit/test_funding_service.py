"""Unit tests for Funding Service.

Tests core functionality of creating and managing funding drafts,
accepting/rejecting drafts, and ledger entry creation.
"""

import pytest
import sqlite3
from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import Mock, patch, MagicMock

from src.services.funding_service import (
    FundingService,
    FundingDraft,
    FundingError,
)


class TestFundingService:
    """Test cases for FundingService."""

    @pytest.fixture
    def mock_db(self):
        """Create a mock database connection."""
        mock_conn = Mock(spec=sqlite3.Connection)
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.execute.return_value = mock_cursor
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=None)
        return mock_conn

    @pytest.fixture
    def funding_service(self, mock_db):
        """Create FundingService instance with mock database."""
        with patch('src.services.funding_service.get_db_connection', return_value=mock_db):
            return FundingService()

    def test_init(self, funding_service):
        """Test FundingService initialization."""
        assert funding_service.db is not None
        assert funding_service._drafts == {}

    def test_create_funding_draft_success(self, funding_service):
        """Test successful creation of a funding draft."""
        with patch.object(funding_service, "_get_associate_alias", return_value="Test User"), patch.object(
            funding_service, "_get_bookmaker_name", return_value="Test Bookmaker"
        ):
            draft_id = funding_service.create_funding_draft(
                associate_id=1,
                bookmaker_id=10,
                event_type="DEPOSIT",
                amount_native=Decimal('100.00'),
                currency="USD",
                note="Test deposit"
            )
        
        # Verify
        assert draft_id is not None
        assert draft_id in funding_service._drafts
        
        draft = funding_service._drafts[draft_id]
        assert draft.associate_id == 1
        assert draft.event_type == "DEPOSIT"
        assert draft.amount_native == Decimal('100.00')
        assert draft.currency == "USD"
        assert draft.note == "Test deposit"
        assert draft.bookmaker_id == 10
        assert draft.bookmaker_name == "Test Bookmaker"

    def test_create_funding_draft_invalid_amount(self, funding_service):
        """Test funding draft creation with invalid amount."""
        with patch.object(funding_service, "_get_associate_alias", return_value="Test User"), patch.object(
            funding_service, "_get_bookmaker_name", return_value="Test Bookmaker"
        ):
            with pytest.raises(FundingError, match="Amount must be positive"):
                funding_service.create_funding_draft(
                    associate_id=1,
                    bookmaker_id=10,
                    event_type="DEPOSIT",
                    amount_native=Decimal('-100.00'),
                    currency="USD",
                    note="Test deposit"
                )

    def test_create_funding_draft_invalid_event_type(self, funding_service):
        """Test funding draft creation with invalid event type."""
        with patch.object(funding_service, "_get_associate_alias", return_value="Test User"), patch.object(
            funding_service, "_get_bookmaker_name", return_value="Test Bookmaker"
        ):
            with pytest.raises(FundingError, match="Event type must be 'DEPOSIT' or 'WITHDRAWAL'"):
                funding_service.create_funding_draft(
                    associate_id=1,
                    bookmaker_id=10,
                    event_type="INVALID",
                    amount_native=Decimal('100.00'),
                    currency="USD",
                    note="Test deposit"
                )

    def test_get_pending_drafts(self, funding_service):
        """Test retrieval of pending funding drafts."""
        with patch.object(funding_service, "_get_associate_alias", return_value="Test User"), patch.object(
            funding_service, "_get_bookmaker_name", return_value="Test Bookmaker"
        ):
            draft_id = funding_service.create_funding_draft(
                associate_id=1,
                bookmaker_id=10,
                event_type="DEPOSIT",
                amount_native=Decimal('100.00'),
                currency="USD"
            )
        
        # Get drafts
        drafts = funding_service.get_pending_drafts()
        
        # Verify
        assert len(drafts) == 1
        draft = drafts[0]
        assert isinstance(draft, FundingDraft)
        assert draft.draft_id == draft_id
        assert draft.event_type == "DEPOSIT"
        assert draft.amount_native == Decimal('100.00')
        assert draft.currency == "USD"

    @patch('src.services.funding_service.get_fx_rate')
    @patch('src.services.funding_service.transactional')
    def test_accept_funding_draft_success(self, mock_transactional, mock_get_fx_rate, funding_service):
        """Test successful acceptance of funding draft."""
        # Setup mocks
        mock_get_fx_rate.return_value = Decimal('0.85')
        mock_conn = Mock()
        mock_transactional.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.lastrowid = 456  # Ledger entry ID
        
        with patch.object(funding_service, "_get_associate_alias", return_value="Test User"), patch.object(
            funding_service, "_get_bookmaker_name", return_value="Test Bookmaker"
        ):
            draft_id = funding_service.create_funding_draft(
                associate_id=1,
                bookmaker_id=10,
                event_type="DEPOSIT",
                amount_native=Decimal('100.00'),
                currency="USD",
                note="Test deposit"
            )
        
        # Accept draft
        ledger_id = funding_service.accept_funding_draft(draft_id)
        
        # Verify
        assert ledger_id == 456
        assert draft_id not in funding_service._drafts
        mock_get_fx_rate.assert_called_once_with("USD", datetime.now(timezone.utc).date())
        mock_conn.execute.assert_called_once()
        _, params = mock_conn.execute.call_args[0]
        assert params[2] == 10  # bookmaker_id column

    def test_accept_funding_draft_not_found(self, funding_service):
        """Test acceptance of non-existent draft."""
        with pytest.raises(FundingError, match="Draft not found"):
            funding_service.accept_funding_draft('non-existent-draft')

    def test_reject_funding_draft_success(self, funding_service):
        """Test successful rejection of funding draft."""
        # Mock associate alias lookup for draft creation
        mock_row = Mock()
        mock_row.__getitem__ = lambda self, key: {'display_alias': 'Test User'}[key]
        funding_service.db.execute.return_value.fetchone.return_value = mock_row
        
        # Create a draft
        draft_id = funding_service.create_funding_draft(
            associate_id=1,
            event_type="DEPOSIT",
            amount_native=Decimal('100.00'),
            currency="USD"
        )
        
        # Reject draft
        funding_service.reject_funding_draft(draft_id)
        
        # Verify
        assert draft_id not in funding_service._drafts

    def test_reject_funding_draft_not_found(self, funding_service):
        """Test rejection of non-existent draft."""
        with pytest.raises(FundingError, match="Draft not found"):
            funding_service.reject_funding_draft('non-existent-draft')

    def test_get_funding_history(self, funding_service):
        """Test retrieval of funding history."""
        # Setup mock database response with proper row objects
        mock_row = Mock()
        mock_row.__getitem__ = lambda self, key: {
            'id': 1,
            'event_type': 'DEPOSIT',
            'associate_id': 1,
            'associate_alias': 'John Doe',
            'amount_native': '100.00',
            'native_currency': 'USD',
            'fx_rate_snapshot': '0.85',
            'amount_eur': '85.00',
            'created_at_utc': '2025-11-04T08:00:00Z',
            'note': 'Test deposit'
        }[key]
        funding_service.db.execute.return_value.fetchall.return_value = [mock_row]
        
        # Get history
        history = funding_service.get_funding_history(days=30)
        
        # Verify
        assert len(history) == 1
        entry = history[0]
        assert entry['associate_alias'] == 'John Doe'
        assert entry['event_type'] == 'DEPOSIT'
        assert entry['amount_native'] == Decimal('100.00')
        assert entry['native_currency'] == 'USD'
        assert entry['amount_eur'] == Decimal('85.00')
        assert entry['note'] == 'Test deposit'

    def test_get_associate_alias_success(self, funding_service):
        """Test successful associate alias retrieval."""
        funding_service.db.execute.return_value.fetchone.return_value = {'display_alias': 'Test User'}
        
        alias = funding_service._get_associate_alias(1)
        
        assert alias == 'Test User'
        funding_service.db.execute.assert_called_once_with(
            "SELECT display_alias FROM associates WHERE id = ?",
            (1,)
        )

    def test_get_associate_alias_not_found(self, funding_service):
        """Test associate alias retrieval when associate not found."""
        funding_service.db.execute.return_value.fetchone.return_value = None
        
        with pytest.raises(FundingError, match="Associate not found: 1"):
            funding_service._get_associate_alias(1)

    def test_funding_draft_dataclass(self):
        """Test FundingDraft dataclass functionality."""
        draft = FundingDraft(
            draft_id='test-draft',
            associate_id=1,
            associate_alias='Test User',
            bookmaker_id=10,
            bookmaker_name='Test Bookmaker',
            event_type='DEPOSIT',
            amount_native=Decimal('100.00'),
            currency='USD',
            note='Test note',
            created_at_utc='2025-11-04T08:00:00Z'
        )
        
        assert draft.draft_id == 'test-draft'
        assert draft.associate_id == 1
        assert draft.associate_alias == 'Test User'
        assert draft.bookmaker_id == 10
        assert draft.bookmaker_name == 'Test Bookmaker'
        assert draft.event_type == 'DEPOSIT'
        assert draft.amount_native == Decimal('100.00')
        assert draft.currency == 'USD'
        assert draft.note == 'Test note'
        assert draft.created_at_utc == '2025-11-04T08:00:00Z'

    def test_funding_draft_validation_invalid_event_type(self):
        """Test FundingDraft validation with invalid event type."""
        with pytest.raises(ValueError, match="Invalid event_type"):
            FundingDraft(
                draft_id='test-draft',
                associate_id=1,
                associate_alias='Test User',
                bookmaker_id=10,
                bookmaker_name='Test Bookmaker',
                event_type='INVALID',
                amount_native=Decimal('100.00'),
                currency='USD',
                note='Test note',
                created_at_utc='2025-11-04T08:00:00Z'
            )

    def test_funding_draft_validation_negative_amount(self):
        """Test FundingDraft validation with negative amount."""
        with pytest.raises(ValueError, match="Amount must be positive"):
            FundingDraft(
                draft_id='test-draft',
                associate_id=1,
                associate_alias='Test User',
                bookmaker_id=10,
                bookmaker_name='Test Bookmaker',
                event_type='DEPOSIT',
                amount_native=Decimal('-100.00'),
                currency='USD',
                note='Test note',
                created_at_utc='2025-11-04T08:00:00Z'
            )

    def test_funding_draft_validation_invalid_currency(self):
        """Test FundingDraft validation with invalid currency."""
        with pytest.raises(ValueError, match="Currency must be a valid 3-letter ISO code"):
            FundingDraft(
                draft_id='test-draft',
                associate_id=1,
                associate_alias='Test User',
                bookmaker_id=10,
                bookmaker_name='Test Bookmaker',
                event_type='DEPOSIT',
                amount_native=Decimal('100.00'),
                currency='INVALID',
                note='Test note',
                created_at_utc='2025-11-04T08:00:00Z'
            )

    def test_quantize_currency(self):
        """Test currency quantization."""
        value = Decimal('100.123456')
        quantized = FundingService._quantize_currency(value)
        assert quantized == Decimal('100.12')


class TestFundingError:
    """Test cases for FundingError."""

    def test_error_creation(self):
        """Test FundingError creation."""
        error = FundingError("Test error message")
        assert str(error) == "Test error message"
        assert isinstance(error, Exception)

    def test_error_inheritance(self):
        """Test FundingError inheritance."""
        assert issubclass(FundingError, Exception)
