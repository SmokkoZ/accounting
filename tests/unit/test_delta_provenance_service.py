"""
Unit tests for Delta Provenance Service.

Tests delta provenance tracking, settlement link creation, and query functionality.
"""

import pytest
import sqlite3
from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from src.services.delta_provenance_service import (
    DeltaProvenanceService,
    DeltaProvenanceEntry,
    DeltaProvenanceSummary
)
from src.core.database import get_db_connection


class TestDeltaProvenanceEntry:
    """Test DeltaProvenanceEntry class."""
    
    def test_init(self):
        """Test DeltaProvenanceEntry initialization."""
        entry = DeltaProvenanceEntry(
            surebet_id=1,
            counterparty_alias="test_user",
            counterparty_associate_id=2,
            amount_eur=Decimal("50.00"),
            is_positive=True,
            created_at_utc="2024-01-01T10:00:00Z",
            ledger_entry_id=100,
            note="Test transaction"
        )
        
        assert entry.surebet_id == 1
        assert entry.counterparty_alias == "test_user"
        assert entry.counterparty_associate_id == 2
        assert entry.amount_eur == Decimal("50.00")
        assert entry.is_positive is True
        assert entry.created_at_utc == "2024-01-01T10:00:00Z"
        assert entry.ledger_entry_id == 100
        assert entry.note == "Test transaction"
    
    def test_to_dict(self):
        """Test DeltaProvenanceEntry to_dict conversion."""
        entry = DeltaProvenanceEntry(
            surebet_id=1,
            counterparty_alias="test_user",
            counterparty_associate_id=2,
            amount_eur=Decimal("50.00"),
            is_positive=True,
            created_at_utc="2024-01-01T10:00:00Z",
            ledger_entry_id=100,
            note="Test transaction"
        )
        
        result = entry.to_dict()
        
        expected = {
            'surebet_id': 1,
            'counterparty_alias': "test_user",
            'counterparty_associate_id': 2,
            'amount_eur': "50.00",
            'is_positive': True,
            'created_at_utc': "2024-01-01T10:00:00Z",
            'ledger_entry_id': 100,
            'note': "Test transaction"
        }
        
        assert result == expected


class TestDeltaProvenanceSummary:
    """Test DeltaProvenanceSummary class."""
    
    def test_init(self):
        """Test DeltaProvenanceSummary initialization."""
        summary = DeltaProvenanceSummary()
        
        assert summary.total_surplus == Decimal("0.00")
        assert summary.total_deficit == Decimal("0.00")
        assert summary.net_delta == Decimal("0.00")
        assert summary.surebet_count == 0
        assert summary.counterparty_breakdown == {}
    
    def test_add_positive_entry(self):
        """Test adding a positive entry to summary."""
        summary = DeltaProvenanceSummary()
        
        entry = DeltaProvenanceEntry(
            surebet_id=1,
            counterparty_alias="test_user",
            counterparty_associate_id=2,
            amount_eur=Decimal("50.00"),
            is_positive=True,
            created_at_utc="2024-01-01T10:00:00Z",
            ledger_entry_id=100
        )
        
        summary.add_entry(entry)
        
        assert summary.total_surplus == Decimal("50.00")
        assert summary.total_deficit == Decimal("0.00")
        assert summary.net_delta == Decimal("50.00")
        assert summary.surebet_count == 1
        assert summary.counterparty_breakdown == {"test_user": Decimal("50.00")}
    
    def test_add_negative_entry(self):
        """Test adding a negative entry to summary."""
        summary = DeltaProvenanceSummary()
        
        entry = DeltaProvenanceEntry(
            surebet_id=1,
            counterparty_alias="test_user",
            counterparty_associate_id=2,
            amount_eur=Decimal("25.00"),
            is_positive=False,
            created_at_utc="2024-01-01T10:00:00Z",
            ledger_entry_id=100
        )
        
        summary.add_entry(entry)
        
        assert summary.total_surplus == Decimal("0.00")
        assert summary.total_deficit == Decimal("25.00")
        assert summary.net_delta == Decimal("-25.00")
        assert summary.surebet_count == 1
        assert summary.counterparty_breakdown == {"test_user": Decimal("-25.00")}
    
    def test_mixed_entries(self):
        """Test summary with mixed positive and negative entries."""
        summary = DeltaProvenanceSummary()
        
        # Add positive entry
        pos_entry = DeltaProvenanceEntry(
            surebet_id=1,
            counterparty_alias="user1",
            counterparty_associate_id=2,
            amount_eur=Decimal("75.00"),
            is_positive=True,
            created_at_utc="2024-01-01T10:00:00Z",
            ledger_entry_id=100
        )
        
        # Add negative entry
        neg_entry = DeltaProvenanceEntry(
            surebet_id=2,
            counterparty_alias="user2",
            counterparty_associate_id=3,
            amount_eur=Decimal("30.00"),
            is_positive=False,
            created_at_utc="2024-01-01T11:00:00Z",
            ledger_entry_id=101
        )
        
        summary.add_entry(pos_entry)
        summary.add_entry(neg_entry)
        
        assert summary.total_surplus == Decimal("75.00")
        assert summary.total_deficit == Decimal("30.00")
        assert summary.net_delta == Decimal("45.00")
        assert summary.surebet_count == 2
        assert summary.counterparty_breakdown == {
            "user1": Decimal("75.00"),
            "user2": Decimal("-30.00")
        }
    
    def test_to_dict(self):
        """Test DeltaProvenanceSummary to_dict conversion."""
        summary = DeltaProvenanceSummary()
        
        # Add test entry
        entry = DeltaProvenanceEntry(
            surebet_id=1,
            counterparty_alias="test_user",
            counterparty_associate_id=2,
            amount_eur=Decimal("50.00"),
            is_positive=True,
            created_at_utc="2024-01-01T10:00:00Z",
            ledger_entry_id=100
        )
        summary.add_entry(entry)
        
        result = summary.to_dict()
        
        expected = {
            'total_surplus': "50.00",
            'total_deficit': "0.00",
            'net_delta': "50.00",
            'surebet_count': 1,
            'counterparty_breakdown': {"test_user": "50.00"}
        }
        
        assert result == expected


class TestDeltaProvenanceService:
    """Test DeltaProvenanceService class."""
    
    @pytest.fixture
    def setup_test_db(self):
        """Set up test database with sample data."""
        # Create in-memory database
        conn = sqlite3.connect(":memory:")
        
        # Create schema
        conn.executescript("""
            CREATE TABLE associates (
                id INTEGER PRIMARY KEY,
                display_alias TEXT NOT NULL UNIQUE,
                home_currency TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0,
                multibook_chat_id TEXT,
                created_at_utc TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL
            );
            
            CREATE TABLE ledger_entries (
                id INTEGER PRIMARY KEY,
                type TEXT NOT NULL,
                associate_id INTEGER NOT NULL,
                bookmaker_id INTEGER,
                amount_native TEXT NOT NULL,
                native_currency TEXT NOT NULL,
                fx_rate_snapshot TEXT NOT NULL,
                amount_eur TEXT NOT NULL,
                settlement_state TEXT,
                principal_returned_eur TEXT,
                per_surebet_share_eur TEXT,
                surebet_id INTEGER,
                bet_id INTEGER,
                settlement_batch_id TEXT,
                opposing_associate_id INTEGER,
                created_at_utc TEXT NOT NULL,
                created_by TEXT NOT NULL,
                note TEXT
            );
            
            CREATE TABLE surebet_settlement_links (
                id INTEGER PRIMARY KEY,
                surebet_id INTEGER,
                winner_associate_id INTEGER NOT NULL,
                loser_associate_id INTEGER NOT NULL,
                amount_eur TEXT NOT NULL,
                winner_ledger_entry_id INTEGER NOT NULL,
                loser_ledger_entry_id INTEGER NOT NULL,
                created_at_utc TEXT NOT NULL,
                FOREIGN KEY (winner_associate_id) REFERENCES associates(id),
                FOREIGN KEY (loser_associate_id) REFERENCES associates(id),
                FOREIGN KEY (winner_ledger_entry_id) REFERENCES ledger_entries(id),
                FOREIGN KEY (loser_ledger_entry_id) REFERENCES ledger_entries(id)
            );
        """)
        
        # Insert test data
        conn.execute("""
            INSERT INTO associates (id, display_alias, home_currency, is_admin, created_at_utc, updated_at_utc)
            VALUES 
                (1, 'Associate 1', 'EUR', 0, datetime('now'), datetime('now')),
                (2, 'Associate 2', 'EUR', 0, datetime('now'), datetime('now'))
        """)
        
        conn.execute("""
            INSERT INTO ledger_entries 
            (id, type, associate_id, amount_native, native_currency, fx_rate_snapshot, amount_eur,
             settlement_state, principal_returned_eur, per_surebet_share_eur,
             surebet_id, bet_id, settlement_batch_id, opposing_associate_id,
             created_at_utc, created_by, note)
            VALUES 
                (100, 'BET_RESULT', 1, '50.00', 'EUR', '1.000000', '50.00',
                 'WON', '50.00', '0.00', 1, 10, 'batch-1', NULL,
                 datetime('now'), 'system', 'Test settlement'),
                (101, 'BET_RESULT', 2, '0.00', 'EUR', '1.000000', '0.00',
                 'LOST', '0.00', '0.00', 1, 11, 'batch-1', NULL,
                 datetime('now'), 'system', 'Test settlement')
        """)
        
        conn.execute("""
            INSERT INTO surebet_settlement_links 
            (surebet_id, winner_associate_id, loser_associate_id, amount_eur, 
             winner_ledger_entry_id, loser_ledger_entry_id, created_at_utc)
            VALUES 
                (1, 1, 2, '50.00', 100, 101, datetime('now'))
        """)
        
        conn.commit()
        return conn
    
    def test_init_with_db(self, setup_test_db):
        """Test DeltaProvenanceService initialization."""
        service = DeltaProvenanceService(setup_test_db)
        assert service.db == setup_test_db
    
    def test_init_without_db(self):
        """Test DeltaProvenanceService initialization without DB."""
        with patch('src.services.delta_provenance_service.get_db_connection') as mock_get_conn:
            mock_conn = Mock()
            mock_get_conn.return_value = mock_conn
            
            service = DeltaProvenanceService()
            
            mock_get_conn.assert_called_once()
            assert service.db == mock_conn
    
    def test_get_associate_delta_provenance_success(self, setup_test_db):
        """Test successful delta provenance query."""
        service = DeltaProvenanceService(setup_test_db)
        
        entries, summary = service.get_associate_delta_provenance(associate_id=1)
        
        # Verify entries
        assert len(entries) == 1
        entry = entries[0]
        assert entry.surebet_id == 1
        assert entry.counterparty_alias == "Associate 2"
        assert entry.counterparty_associate_id == 2
        assert entry.amount_eur == Decimal("50.00")
        assert entry.is_positive is True
        assert entry.ledger_entry_id == 100
        
        # Verify summary
        assert summary.total_surplus == Decimal("50.00")
        assert summary.total_deficit == Decimal("0.00")
        assert summary.net_delta == Decimal("50.00")
        assert summary.surebet_count == 1
        assert summary.counterparty_breakdown == {"Associate 2": Decimal("50.00")}
    
    def test_get_associate_delta_provenance_empty(self, setup_test_db):
        """Test delta provenance query with no results."""
        service = DeltaProvenanceService(setup_test_db)
        
        entries, summary = service.get_associate_delta_provenance(associate_id=999)
        
        assert len(entries) == 0
        assert summary.total_surplus == Decimal("0.00")
        assert summary.total_deficit == Decimal("0.00")
        assert summary.net_delta == Decimal("0.00")
        assert summary.surebet_count == 0
        assert summary.counterparty_breakdown == {}

    def test_get_associate_delta_provenance_backfills_missing_links(self, setup_test_db):
        """Ensure missing settlement links are reconstructed on demand."""
        service = DeltaProvenanceService(setup_test_db)

        setup_test_db.execute(
            """
            INSERT INTO ledger_entries
            (id, type, associate_id, amount_native, native_currency, fx_rate_snapshot, amount_eur,
             settlement_state, principal_returned_eur, per_surebet_share_eur,
             surebet_id, bet_id, settlement_batch_id, opposing_associate_id,
             created_at_utc, created_by, note)
            VALUES
                (200, 'BET_RESULT', 1, '25.00', 'EUR', '1.000000', '25.00',
                 'WON', '25.00', '0.00', 2, 20, 'batch-2', NULL,
                 datetime('now'), 'system', 'Backfill winner'),
                (201, 'BET_RESULT', 2, '0.00', 'EUR', '1.000000', '0.00',
                 'LOST', '0.00', '0.00', 2, 21, 'batch-2', NULL,
                 datetime('now'), 'system', 'Backfill loser')
            """
        )
        setup_test_db.commit()

        initial_count = setup_test_db.execute(
            "SELECT COUNT(*) FROM surebet_settlement_links WHERE surebet_id = 2"
        ).fetchone()[0]
        assert initial_count == 0

        entries, summary = service.get_associate_delta_provenance(associate_id=1)

        link_rows = setup_test_db.execute(
            "SELECT * FROM surebet_settlement_links WHERE surebet_id = 2"
        ).fetchall()
        assert len(link_rows) == 1
        link = link_rows[0]
        assert link["winner_associate_id"] == 1
        assert link["loser_associate_id"] == 2
        assert Decimal(link["amount_eur"]) == Decimal("25.00")

        opposing_rows = setup_test_db.execute(
            "SELECT opposing_associate_id FROM ledger_entries WHERE surebet_id = 2 ORDER BY amount_eur DESC"
        ).fetchall()
        assert [row["opposing_associate_id"] for row in opposing_rows] == [2, 1]

        assert summary.net_delta >= Decimal("50.00")
        assert len(entries) >= 2
    
    def test_get_counterparty_delta_summary_success(self, setup_test_db):
        """Test successful counterparty summary query."""
        service = DeltaProvenanceService(setup_test_db)
        
        result = service.get_counterparty_delta_summary(
            associate_id=1, 
            counterparty_associate_id=2
        )
        
        assert result['transaction_count'] == 1
        assert result['net_amount_eur'] == "50.00"
        assert result['total_won_eur'] == "50.00"
        assert result['total_lost_eur'] == "0.00"
        assert result['first_transaction'] is not None
        assert result['last_transaction'] is not None
    
    def test_get_counterparty_delta_summary_empty(self, setup_test_db):
        """Test counterparty summary with no transactions."""
        service = DeltaProvenanceService(setup_test_db)
        
        result = service.get_counterparty_delta_summary(
            associate_id=999, 
            counterparty_associate_id=888
        )
        
        assert result['transaction_count'] == 0
        assert result['net_amount_eur'] == "0.00"
        assert result['total_won_eur'] == "0.00"
        assert result['total_lost_eur'] == "0.00"
        assert result['first_transaction'] is None
        assert result['last_transaction'] is None
    
    def test_get_surebet_delta_details_success(self, setup_test_db):
        """Test successful surebet details query."""
        service = DeltaProvenanceService(setup_test_db)
        
        results = service.get_surebet_delta_details(surebet_id=1)
        
        assert len(results) == 1
        result = results[0]
        assert result['surebet_id'] == 1
        assert result['winner_associate_id'] == 1
        assert result['loser_associate_id'] == 2
        assert result['amount_eur'] == "50.00"
        assert result['winner_alias'] == "Associate 1"
        assert result['loser_alias'] == "Associate 2"
        assert result['winner_ledger_entry_id'] == 100
        assert result['loser_ledger_entry_id'] == 101
    
    def test_get_surebet_delta_details_filtered(self, setup_test_db):
        """Test surebet details query with associate filter."""
        service = DeltaProvenanceService(setup_test_db)
        
        # Test with associate filter
        results = service.get_surebet_delta_details(
            surebet_id=1, 
            associate_id=1
        )
        
        assert len(results) == 1
        result = results[0]
        assert result['winner_associate_id'] == 1
        
        # Test with non-participating associate
        results = service.get_surebet_delta_details(
            surebet_id=1, 
            associate_id=999
        )
        
        assert len(results) == 0
    
    def test_create_settlement_link_success(self, setup_test_db):
        """Test successful settlement link creation."""
        service = DeltaProvenanceService(setup_test_db)
        
        # Add additional ledger entries
        setup_test_db.execute("""
            INSERT INTO ledger_entries 
            (id, type, associate_id, amount_native, native_currency, fx_rate_snapshot, amount_eur, 
             created_at_utc, created_by, note)
            VALUES 
                (102, 'BET_RESULT', 3, '25.00', 'EUR', '1.000000', '25.00',
                 datetime('now'), 'system', 'Test settlement 2'),
                (103, 'BET_RESULT', 4, '0.00', 'EUR', '1.000000', '0.00',
                 datetime('now'), 'system', 'Test settlement 2')
        """)
        
        setup_test_db.commit()
        
        link_id = service.create_settlement_link(
            surebet_id=2,
            winner_associate_id=3,
            loser_associate_id=4,
            amount_eur=Decimal("25.00"),
            winner_ledger_entry_id=102,
            loser_ledger_entry_id=103
        )
        
        assert link_id is not None
        assert link_id > 1  # Should be greater than existing link ID
        
        # Verify link was created
        cursor = setup_test_db.execute(
            "SELECT * FROM surebet_settlement_links WHERE id = ?", (link_id,)
        )
        row = cursor.fetchone()
        
        assert row is not None
        assert row['surebet_id'] == 2
        assert row['winner_associate_id'] == 3
        assert row['loser_associate_id'] == 4
        assert row['amount_eur'] == "25.00"
        assert row['winner_ledger_entry_id'] == 102
        assert row['loser_ledger_entry_id'] == 103
    
    def test_create_settlement_link_database_error(self, setup_test_db):
        """Test settlement link creation with database error."""
        service = DeltaProvenanceService(setup_test_db)
        
        # Force database error by violating NOT NULL constraint on winner_associate_id
        with pytest.raises(sqlite3.Error):
            service.create_settlement_link(
                surebet_id=2,
                winner_associate_id=None,  # NULL value for NOT NULL field
                loser_associate_id=4,
                amount_eur=Decimal("25.00"),
                winner_ledger_entry_id=102,
                loser_ledger_entry_id=103
            )
    
    def test_close(self, setup_test_db):
        """Test database connection closing."""
        service = DeltaProvenanceService(setup_test_db)
        
        # Test that close doesn't raise error when _own_connection is False
        service._own_connection = False
        service.close()  # Should not call close on db
        
        # Test with mocked connection that has close method
        mock_db = Mock()
        mock_db.close = Mock()
        service.db = mock_db
        service._own_connection = True
        
        service.close()
        
        mock_db.close.assert_called_once()


class TestTelemetryLogging:
    """Test telemetry logging functionality."""
    
    @pytest.fixture
    def mock_logger(self):
        """Mock logger for testing."""
        with patch('src.services.delta_provenance_service.logger') as mock:
            yield mock
    
    @pytest.fixture
    def setup_test_db(self):
        """Set up test database."""
        conn = sqlite3.connect(":memory:")
        conn.executescript("""
            CREATE TABLE associates (
                id INTEGER PRIMARY KEY,
                display_alias TEXT NOT NULL UNIQUE,
                home_currency TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0,
                multibook_chat_id TEXT,
                created_at_utc TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL
            );
            
            CREATE TABLE ledger_entries (
                id INTEGER PRIMARY KEY,
                type TEXT NOT NULL,
                associate_id INTEGER NOT NULL,
                bookmaker_id INTEGER,
                amount_native TEXT NOT NULL,
                native_currency TEXT NOT NULL,
                fx_rate_snapshot TEXT NOT NULL,
                amount_eur TEXT NOT NULL,
                settlement_state TEXT,
                principal_returned_eur TEXT,
                per_surebet_share_eur TEXT,
                surebet_id INTEGER,
                bet_id INTEGER,
                settlement_batch_id TEXT,
                opposing_associate_id INTEGER,
                created_at_utc TEXT NOT NULL,
                created_by TEXT NOT NULL,
                note TEXT
            );
            
            CREATE TABLE surebet_settlement_links (
                id INTEGER PRIMARY KEY,
                surebet_id INTEGER,
                winner_associate_id INTEGER NOT NULL,
                loser_associate_id INTEGER NOT NULL,
                amount_eur TEXT NOT NULL,
                winner_ledger_entry_id INTEGER NOT NULL,
                loser_ledger_entry_id INTEGER NOT NULL,
                created_at_utc TEXT NOT NULL,
                FOREIGN KEY (winner_associate_id) REFERENCES associates(id),
                FOREIGN KEY (loser_associate_id) REFERENCES associates(id),
                FOREIGN KEY (winner_ledger_entry_id) REFERENCES ledger_entries(id),
                FOREIGN KEY (loser_ledger_entry_id) REFERENCES ledger_entries(id)
            );
        """)
        
        conn.execute("""
            INSERT INTO associates (id, display_alias, home_currency, is_admin, created_at_utc, updated_at_utc)
            VALUES 
                (1, 'Test Associate', 'EUR', 0, datetime('now'), datetime('now'))
        """)
        
        conn.commit()
        return conn
    
    def test_telemetry_logged_on_provenance_query(self, mock_logger, setup_test_db):
        """Test that telemetry is logged during provenance query."""
        service = DeltaProvenanceService(setup_test_db)
        
        service.get_associate_delta_provenance(associate_id=1)
        
        # Verify telemetry was logged
        mock_logger.info.assert_called_with(
            "delta_provenance_viewed",
            associate_id=1,
            entry_count=0,
            surebet_count=0,
            duration_ms=pytest.approx(0, abs=100)  # Allow some tolerance
        )
    
    def test_telemetry_logged_on_counterparty_summary(self, mock_logger, setup_test_db):
        """Test that telemetry is logged during counterparty summary query."""
        service = DeltaProvenanceService(setup_test_db)
        
        service.get_counterparty_delta_summary(associate_id=1, counterparty_associate_id=2)
        
        # Verify telemetry was logged
        mock_logger.info.assert_called_with(
            "counterparty_summary_viewed",
            associate_id=1,
            counterparty_id=2,
            transaction_count=0,
            duration_ms=pytest.approx(0, abs=100)  # Allow some tolerance
        )
    
    def test_telemetry_logged_on_surebet_details(self, mock_logger, setup_test_db):
        """Test that telemetry is logged during surebet details query."""
        service = DeltaProvenanceService(setup_test_db)
        
        service.get_surebet_delta_details(surebet_id=1)
        
        # Verify telemetry was logged
        mock_logger.info.assert_called_with(
            "surebet_details_viewed",
            surebet_id=1,
            associate_id=None,
            result_count=0,
            duration_ms=pytest.approx(0, abs=100)  # Allow some tolerance
        )
    
    def test_telemetry_logged_on_link_creation(self, mock_logger, setup_test_db):
        """Test that telemetry is logged during settlement link creation."""
        service = DeltaProvenanceService(setup_test_db)
        
        # Add ledger entries for link creation
        setup_test_db.execute("""
            INSERT INTO ledger_entries 
            (id, type, associate_id, amount_native, native_currency, fx_rate_snapshot, amount_eur, 
             created_at_utc, created_by, note)
            VALUES 
                (100, 'BET_RESULT', 1, '50.00', 'EUR', '1.000000', '50.00',
                 datetime('now'), 'system', 'Test'),
                (101, 'BET_RESULT', 2, '0.00', 'EUR', '1.000000', '0.00',
                 datetime('now'), 'system', 'Test')
        """)
        
        setup_test_db.commit()
        
        service.create_settlement_link(
            surebet_id=1,
            winner_associate_id=1,
            loser_associate_id=2,
            amount_eur=Decimal("50.00"),
            winner_ledger_entry_id=100,
            loser_ledger_entry_id=101
        )
        
        # Verify telemetry was logged
        mock_logger.info.assert_called_with(
            "settlement_link_created",
            surebet_id=1,
            winner_associate_id=1,
            loser_associate_id=2,
            amount_eur="50.00",
            link_id=pytest.approx(1),  # First link should have ID 1
            duration_ms=pytest.approx(0, abs=100)  # Allow some tolerance
        )
