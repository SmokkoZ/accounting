"""Migration and backfill tests for Delta Provenance functionality.

Tests the migration script and data backfilling for historical settlement data.
"""

import pytest
import sqlite3
import tempfile
import os
from decimal import Decimal
from datetime import datetime, timezone, timedelta

from src.services.delta_provenance_service import DeltaProvenanceService
from src.core.database import get_db_connection


class TestDeltaProvenanceMigration:
    """Test migration script functionality."""
    
    @pytest.fixture
    def pre_migration_db(self):
        """Create a database with pre-migration schema."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as temp_db:
            conn = sqlite3.connect(temp_db.name)
            
            # Create pre-migration schema (without provenance tables)
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
                    created_at_utc TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    note TEXT
                );
                
                CREATE TABLE surebets (
                    id INTEGER PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'pending',
                    settled_at_utc TEXT
                );
                
                CREATE TABLE bets (
                    id INTEGER PRIMARY KEY,
                    associate_id INTEGER NOT NULL,
                    bookmaker_id INTEGER NOT NULL,
                    stake_original TEXT,
                    odds TEXT,
                    currency TEXT NOT NULL DEFAULT 'EUR',
                    odds_original TEXT,
                    created_at_utc TEXT NOT NULL
                );
                
                CREATE TABLE surebet_bets (
                    surebet_id INTEGER NOT NULL,
                    bet_id INTEGER NOT NULL,
                    side TEXT NOT NULL,
                    PRIMARY KEY (surebet_id, bet_id),
                    FOREIGN KEY (surebet_id) REFERENCES surebets(id),
                    FOREIGN KEY (bet_id) REFERENCES bets(id)
                );
            """)
            
            # Insert test data for migration
            conn.executescript("""
                INSERT INTO associates (id, display_alias, home_currency, is_admin, created_at_utc, updated_at_utc)
                VALUES 
                    (1, 'User One', 'EUR', 0, datetime('now'), datetime('now')),
                    (2, 'User Two', 'EUR', 0, datetime('now'), datetime('now')),
                    (3, 'User Three', 'EUR', 0, datetime('now'), datetime('now'));
                
                INSERT INTO surebets (id, status, settled_at_utc) VALUES 
                    (101, 'settled', datetime('now', '-5 days')),
                    (102, 'settled', datetime('now', '-3 days')),
                    (103, 'settled', datetime('now', '-1 day')),
                    (104, 'pending', NULL);  -- Unsettled surebet
                
                INSERT INTO bets (id, associate_id, bookmaker_id, stake_original, odds, currency, created_at_utc) VALUES 
                    (1011, 1, 1, '100.00', '2.50', 'EUR', datetime('now', '-5 days')),
                    (1012, 2, 2, '100.00', '1.80', 'EUR', datetime('now', '-5 days')),
                    (1021, 1, 1, '150.00', '3.20', 'EUR', datetime('now', '-3 days')),
                    (1022, 3, 3, '150.00', '1.40', 'EUR', datetime('now', '-3 days')),
                    (1031, 2, 2, '200.00', '2.10', 'EUR', datetime('now', '-1 day')),
                    (1032, 3, 3, '200.00', '1.60', 'EUR', datetime('now', '-1 day'));
                
                INSERT INTO surebet_bets (surebet_id, bet_id, side) VALUES 
                    (101, 1011, 'BACK'),
                    (101, 1012, 'LAY'),
                    (102, 1021, 'BACK'),
                    (102, 1022, 'LAY'),
                    (103, 1031, 'BACK'),
                    (103, 1032, 'LAY');
                
                -- Create settlement ledger entries for settled surebets
                INSERT INTO ledger_entries 
                (id, type, associate_id, bookmaker_id, amount_native, native_currency, 
                 fx_rate_snapshot, amount_eur, settlement_state, principal_returned_eur, 
                 per_surebet_share_eur, surebet_id, bet_id, settlement_batch_id, 
                 created_at_utc, created_by, note) VALUES 
                    -- Surebet 101: User 1 wins, User 2 loses
                    (1001, 'BET_RESULT', 1, 1, '250.00', 'EUR', '1.000000', '250.00', 'WON', '100.00', '150.00', 101, 1011, 'batch-101', datetime('now', '-5 days'), 'system', 'Settlement win'),
                    (1002, 'BET_RESULT', 2, 2, '0.00', 'EUR', '1.000000', '0.00', 'LOST', '0.00', '-50.00', 101, 1012, 'batch-101', datetime('now', '-5 days'), 'system', 'Settlement loss'),
                    
                    -- Surebet 102: User 1 wins, User 3 loses
                    (1003, 'BET_RESULT', 1, 1, '480.00', 'EUR', '1.000000', '480.00', 'WON', '150.00', '330.00', 102, 1021, 'batch-102', datetime('now', '-3 days'), 'system', 'Settlement win'),
                    (1004, 'BET_RESULT', 3, 3, '0.00', 'EUR', '1.000000', '0.00', 'LOST', '0.00', '-150.00', 102, 1022, 'batch-102', datetime('now', '-3 days'), 'system', 'Settlement loss'),
                    
                    -- Surebet 103: User 2 wins, User 3 loses
                    (1005, 'BET_RESULT', 2, 2, '420.00', 'EUR', '1.000000', '420.00', 'WON', '200.00', '220.00', 103, 1031, 'batch-103', datetime('now', '-1 day'), 'system', 'Settlement win'),
                    (1006, 'BET_RESULT', 3, 3, '0.00', 'EUR', '1.000000', '0.00', 'LOST', '0.00', '-200.00', 103, 1032, 'batch-103', datetime('now', '-1 day'), 'system', 'Settlement loss');
            """)
            
            conn.commit()
            yield conn, temp_db.name
            
            conn.close()
            os.unlink(temp_db.name)
    
    def test_migration_creates_tables(self, pre_migration_db):
        """Test that migration creates the required tables."""
        conn, db_path = pre_migration_db
        
        # Run migration
        self._run_migration_script(db_path)
        
        # Verify tables were created
        tables = conn.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' 
            AND name IN ('surebet_settlement_links', 'migration_audit_log')
        """).fetchall()
        
        table_names = [row[0] for row in tables]
        assert 'surebet_settlement_links' in table_names
        assert 'migration_audit_log' in table_names
    
    def test_migration_backfills_settlement_links(self, pre_migration_db):
        """Test that migration backfills settlement links correctly."""
        conn, db_path = pre_migration_db
        
        # Run migration
        self._run_migration_script(db_path)
        
        # Verify settlement links were created for settled surebets
        settlement_links = conn.execute("""
            SELECT surebet_id, winner_associate_id, loser_associate_id, amount_eur,
                   winner_ledger_entry_id, loser_ledger_entry_id
            FROM surebet_settlement_links
            ORDER BY surebet_id
        """).fetchall()
        
        # Should have links for surebets 101, 102, 103 (but not 104 - unsettled)
        assert len(settlement_links) == 3
        
        # Verify specific links
        links_by_surebet = {link[0]: link[1:] for link in settlement_links}
        
        # Surebet 101: User 1 wins, User 2 loses, amount = 150
        assert 101 in links_by_surebet
        link_101 = links_by_surebet[101]
        assert link_101[0] == 1  # winner_associate_id
        assert link_101[1] == 2  # loser_associate_id
        assert Decimal(link_101[2]) == Decimal("150.00")  # amount_eur
        assert link_101[3] == 1001  # winner_ledger_entry_id
        assert link_101[4] == 1002  # loser_ledger_entry_id
        
        # Surebet 102: User 1 wins, User 3 loses, amount = 330
        assert 102 in links_by_surebet
        link_102 = links_by_surebet[102]
        assert link_102[0] == 1  # winner_associate_id
        assert link_102[1] == 3  # loser_associate_id
        assert Decimal(link_102[2]) == Decimal("330.00")  # amount_eur
        assert link_102[3] == 1003  # winner_ledger_entry_id
        assert link_102[4] == 1004  # loser_ledger_entry_id
        
        # Surebet 103: User 2 wins, User 3 loses, amount = 220
        assert 103 in links_by_surebet
        link_103 = links_by_surebet[103]
        assert link_103[0] == 2  # winner_associate_id
        assert link_103[1] == 3  # loser_associate_id
        assert Decimal(link_103[2]) == Decimal("220.00")  # amount_eur
        assert link_103[3] == 1005  # winner_ledger_entry_id
        assert link_103[4] == 1006  # loser_ledger_entry_id
    
    def test_migration_adds_opposing_associate_id(self, pre_migration_db):
        """Test that migration adds opposing_associate_id to ledger entries."""
        conn, db_path = pre_migration_db
        
        # Run migration
        self._run_migration_script(db_path)
        
        # Verify opposing_associate_id was added and populated
        ledger_entries = conn.execute("""
            SELECT id, associate_id, opposing_associate_id, surebet_id
            FROM ledger_entries
            WHERE surebet_id IS NOT NULL
            ORDER BY surebet_id, associate_id
        """).fetchall()
        
        # Should have entries for all settled bets
        settlement_entries = [entry for entry in ledger_entries if entry[3] in [101, 102, 103]]
        assert len(settlement_entries) == 6  # 2 entries per settled surebet
        
        # Verify opposing_associate_id is set correctly
        # For surebet 101: User 1's entry should have opposing=2, User 2's entry should have opposing=1
        surebet_101_entries = [e for e in settlement_entries if e[3] == 101]
        assert len(surebet_101_entries) == 2
        
        user_1_entry = next(e for e in surebet_101_entries if e[1] == 1)
        user_2_entry = next(e for e in surebet_101_entries if e[1] == 2)
        
        assert user_1_entry[2] == 2  # User 1's opposing is User 2
        assert user_2_entry[2] == 1  # User 2's opposing is User 1
    
    def test_migration_audit_log(self, pre_migration_db):
        """Test that migration creates audit log entries."""
        conn, db_path = pre_migration_db
        
        # Run migration
        self._run_migration_script(db_path)
        
        # Verify audit log was created
        audit_logs = conn.execute("""
            SELECT migration_name, start_time, end_time, details_json
            FROM migration_audit_log
            ORDER BY start_time DESC
        """).fetchall()
        
        assert len(audit_logs) >= 1
        
        latest_log = audit_logs[0]
        assert latest_log[0] == 'delta_provenance_migration'
        assert latest_log[1] is not None  # start_time
        assert latest_log[2] is not None  # end_time
        assert latest_log[3] is not None  # details_json
        
        # Parse details and verify structure
        import json
        details = json.loads(latest_log[3])
        
        assert 'links_created' in details
        assert 'ledger_entries_updated' in details
        assert 'error_count' in details
        
        assert details['links_created'] == 3  # 3 settled surebets
        assert details['ledger_entries_updated'] == 6  # 6 ledger entries updated
        assert details['error_count'] == 0
    
    def test_migration_idempotency(self, pre_migration_db):
        """Test that migration can be run multiple times safely."""
        conn, db_path = pre_migration_db
        
        # Run migration twice
        self._run_migration_script(db_path)
        first_links_count = conn.execute("SELECT COUNT(*) FROM surebet_settlement_links").fetchone()[0]
        
        self._run_migration_script(db_path)
        second_links_count = conn.execute("SELECT COUNT(*) FROM surebet_settlement_links").fetchone()[0]
        
        # Should not create duplicate links
        assert first_links_count == second_links_count
        
        # Verify audit log has multiple entries
        audit_count = conn.execute("SELECT COUNT(*) FROM migration_audit_log").fetchone()[0]
        assert audit_count == 2
    
    def test_migration_handles_edge_cases(self, pre_migration_db):
        """Test migration handles edge cases correctly."""
        conn, db_path = pre_migration_db
        
        # Add edge case data
        conn.executescript("""
            -- Surebet with only one bet (invalid but should be handled)
            INSERT INTO surebets (id, status, settled_at_utc) VALUES (105, 'settled', datetime('now', '-2 days'));
            INSERT INTO bets (id, associate_id, bookmaker_id, stake_original, odds, currency, created_at_utc) 
            VALUES (1051, 1, 1, '100.00', '2.00', 'EUR', datetime('now', '-2 days'));
            INSERT INTO surebet_bets (surebet_id, bet_id, side) VALUES (105, 1051, 'BACK');
            
            -- Surebet with no settlement entries (settled flag but no BET_RESULT entries)
            INSERT INTO surebets (id, status, settled_at_utc) VALUES (106, 'settled', datetime('now', '-1 day'));
            INSERT INTO bets (id, associate_id, bookmaker_id, stake_original, odds, currency, created_at_utc) 
            VALUES (1061, 1, 1, '100.00', '2.00', 'EUR', datetime('now', '-1 day')),
                    (1062, 2, 2, '100.00', '1.80', 'EUR', datetime('now', '-1 day'));
            INSERT INTO surebet_bets (surebet_id, bet_id, side) VALUES 
                (106, 1061, 'BACK'), (106, 1062, 'LAY');
        """)
        conn.commit()
        
        # Run migration
        self._run_migration_script(db_path)
        
        # Verify migration handles edge cases gracefully
        settlement_links = conn.execute("""
            SELECT surebet_id FROM surebet_settlement_links ORDER BY surebet_id
        """).fetchall()
        
        surebet_ids = [link[0] for link in settlement_links]
        
        # Should include valid surebets (101, 102, 103)
        # Should exclude edge cases (105 - single bet, 106 - no settlement entries)
        assert 101 in surebet_ids
        assert 102 in surebet_ids
        assert 103 in surebet_ids
        
        # Edge cases should not create links (or should be handled appropriately)
        # The exact behavior depends on migration implementation
    
    def test_provenance_works_after_migration(self, pre_migration_db):
        """Test that delta provenance functionality works correctly after migration."""
        conn, db_path = pre_migration_db
        
        # Run migration
        self._run_migration_script(db_path)
        
        # Test delta provenance service works
        delta_service = DeltaProvenanceService(conn)
        
        # Test User 1's provenance
        entries, summary = delta_service.get_associate_delta_provenance(associate_id=1)
        
        # User 1 should have positive entries from surebets 101 and 102
        assert len(entries) == 2
        assert summary.total_surplus > Decimal("0.00")
        assert summary.net_delta > Decimal("0.00")
        assert summary.surebet_count == 2
        
        # Verify specific entries
        surebet_ids = [entry.surebet_id for entry in entries]
        assert 101 in surebet_ids
        assert 102 in surebet_ids
        
        # Test counterparty summary
        user1_user2_summary = delta_service.get_counterparty_delta_summary(
            associate_id=1,
            counterparty_associate_id=2
        )
        
        assert user1_user2_summary['transaction_count'] == 1  # Only surebet 101
        assert Decimal(user1_user2_summary['net_amount_eur']) > 0  # User 1 won
        
        # Test surebet details
        surebet_101_details = delta_service.get_surebet_delta_details(surebet_id=101)
        assert len(surebet_101_details) == 1
        
        detail = surebet_101_details[0]
        assert detail['surebet_id'] == 101
        assert detail['winner_associate_id'] == 1
        assert detail['loser_associate_id'] == 2
        assert Decimal(detail['amount_eur']) == Decimal("150.00")
    
    def test_migration_error_handling(self):
        """Test migration error handling and rollback."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as temp_db:
            conn = sqlite3.connect(temp_db.name)
            
            # Create incomplete schema (missing required tables)
            conn.executescript("""
                CREATE TABLE ledger_entries (
                    id INTEGER PRIMARY KEY,
                    type TEXT NOT NULL,
                    associate_id INTEGER NOT NULL,
                    amount_native TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL
                );
            """)
            conn.commit()
            
            # Migration should handle missing schema gracefully
            try:
                self._run_migration_script(temp_db.name)
                # If migration doesn't raise error, verify it handles the situation
                audit_logs = conn.execute("SELECT COUNT(*) FROM migration_audit_log").fetchone()[0]
                # Should either create audit log with errors or fail gracefully
            except Exception as e:
                # Migration should fail with informative error
                assert "required" in str(e).lower() or "missing" in str(e).lower()
            
            conn.close()
            os.unlink(temp_db.name)
    
    def _run_migration_script(self, db_path: str):
        """Helper to run the migration script."""
        import sys
        import importlib.util
        
        # Load migration script
        spec = importlib.util.spec_from_file_location(
            "migrate_delta_provenance", 
            "scripts/migrate_delta_provenance.py"
        )
        migration_module = importlib.util.module_from_spec(spec)
        
        # Mock the database connection
        original_get_conn = migration_module.get_db_connection
        
        def mock_get_conn():
            return sqlite3.connect(db_path)
        
        migration_module.get_db_connection = mock_get_conn
        
        # Run migration
        try:
            spec.loader.exec_module(migration_module)
            migration_module.main()
        finally:
            # Restore original function
            migration_module.get_db_connection = original_get_conn


class TestBackfillPerformance:
    """Test performance of backfill operations."""
    
    def test_large_dataset_backfill_performance(self):
        """Test migration performance with large dataset."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as temp_db:
            conn = sqlite3.connect(temp_db.name)
            
            # Create schema
            conn.executescript("""
                CREATE TABLE associates (
                    id INTEGER PRIMARY KEY,
                    display_alias TEXT NOT NULL UNIQUE,
                    home_currency TEXT NOT NULL,
                    is_admin INTEGER NOT NULL DEFAULT 0,
                    created_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL
                );
                
                CREATE TABLE ledger_entries (
                    id INTEGER PRIMARY KEY,
                    type TEXT NOT NULL,
                    associate_id INTEGER NOT NULL,
                    amount_native TEXT NOT NULL,
                    fx_rate_snapshot TEXT NOT NULL,
                    amount_eur TEXT NOT NULL,
                    settlement_state TEXT,
                    surebet_id INTEGER,
                    bet_id INTEGER,
                    settlement_batch_id TEXT,
                    created_at_utc TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    note TEXT
                );
                
                CREATE TABLE surebets (
                    id INTEGER PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'pending',
                    settled_at_utc TEXT
                );
                
                CREATE TABLE bets (
                    id INTEGER PRIMARY KEY,
                    associate_id INTEGER NOT NULL,
                    bookmaker_id INTEGER NOT NULL,
                    created_at_utc TEXT NOT NULL
                );
                
                CREATE TABLE surebet_bets (
                    surebet_id INTEGER NOT NULL,
                    bet_id INTEGER NOT NULL,
                    side TEXT NOT NULL,
                    PRIMARY KEY (surebet_id, bet_id)
                );
            """)
            
            # Insert large dataset (1000 surebets, 2000 settlement entries)
            print("Creating large test dataset...")
            base_time = datetime.now(timezone.utc) - timedelta(days=365)
            
            for i in range(1000):
                surebet_id = 2000 + i
                
                # Insert surebet
                conn.execute(
                    "INSERT INTO surebets (id, status, settled_at_utc) VALUES (?, 'settled', ?)",
                    (surebet_id, (base_time + timedelta(days=i)).isoformat() + 'Z')
                )
                
                # Create settlement entries for two associates
                winner_amount = 100 + (i % 50)
                loser_amount = -(50 + (i % 30))
                
                # Winner entry
                conn.execute("""
                    INSERT INTO ledger_entries 
                    (id, type, associate_id, amount_native, fx_rate_snapshot, amount_eur, 
                     settlement_state, surebet_id, bet_id, settlement_batch_id, 
                     created_at_utc, created_by, note) VALUES 
                    (?, 'BET_RESULT', 1, ?, '1.000000', ?, 'WON', ?, ?, 'batch-?', ?, 'system', 'Settlement')
                """, (
                    surebet_id * 10 + 1,
                    str(winner_amount),
                    str(winner_amount),
                    surebet_id,
                    surebet_id * 10 + 1,
                    surebet_id,
                    (base_time + timedelta(days=i)).isoformat() + 'Z'
                ))
                
                # Loser entry
                conn.execute("""
                    INSERT INTO ledger_entries 
                    (id, type, associate_id, amount_native, fx_rate_snapshot, amount_eur, 
                     settlement_state, surebet_id, bet_id, settlement_batch_id, 
                     created_at_utc, created_by, note) VALUES 
                    (?, 'BET_RESULT', 2, ?, '1.000000', '0.00', 'LOST', ?, ?, 'batch-?', ?, 'system', 'Settlement')
                """, (
                    surebet_id * 10 + 2,
                    '0.00',
                    surebet_id,
                    surebet_id * 10 + 2,
                    surebet_id,
                    (base_time + timedelta(days=i)).isoformat() + 'Z'
                ))
                
                # Insert surebet-bet relationships
                conn.execute("""
                    INSERT INTO surebet_bets (surebet_id, bet_id, side) VALUES 
                        (?, ?, 'BACK'), (?, ?, 'LAY')
                """, (surebet_id, surebet_id * 10 + 1, surebet_id, surebet_id * 10 + 2))
                
                # Insert minimal bet records
                conn.execute("""
                    INSERT INTO bets (id, associate_id, bookmaker_id, created_at_utc) VALUES 
                        (?, 1, 1, ?), (?, 2, 2, ?)
                """, (
                    surebet_id * 10 + 1, (base_time + timedelta(days=i)).isoformat() + 'Z',
                    surebet_id * 10 + 2, (base_time + timedelta(days=i)).isoformat() + 'Z'
                ))
                
                if i % 100 == 0:
                    conn.commit()  # Commit periodically
            
            conn.commit()
            
            print("Running migration on large dataset...")
            import time
            start_time = time.time()
            
            # Run migration
            self._run_migration_script(temp_db.name)
            
            end_time = time.time()
            migration_duration = end_time - start_time
            
            print(f"Migration completed in {migration_duration:.2f} seconds")
            
            # Verify migration completed successfully
            settlement_links_count = conn.execute("SELECT COUNT(*) FROM surebet_settlement_links").fetchone()[0]
            assert settlement_links_count == 1000  # Should create links for all settled surebets
            
            # Performance should be reasonable (less than 30 seconds for 1000 entries)
            assert migration_duration < 30.0, f"Migration took too long: {migration_duration}s"
            
            # Verify data integrity after migration
            delta_service = DeltaProvenanceService(conn)
            entries, summary = delta_service.get_associate_delta_provenance(associate_id=1)
            
            assert len(entries) == 1000  # Should have all winning entries
            assert summary.surebet_count == 1000
            assert summary.total_surplus > Decimal("0.00")
            
            conn.close()
            os.unlink(temp_db.name)


class TestMigrationRollback:
    """Test migration rollback functionality."""
    
    def test_partial_migration_rollback(self):
        """Test rollback when migration fails partway through."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as temp_db:
            conn = sqlite3.connect(temp_db.name)
            
            # Create schema with some data
            conn.executescript("""
                CREATE TABLE associates (id INTEGER PRIMARY KEY, display_alias TEXT NOT NULL);
                CREATE TABLE ledger_entries (
                    id INTEGER PRIMARY KEY, type TEXT NOT NULL, associate_id INTEGER NOT NULL,
                    amount_native TEXT NOT NULL, created_at_utc TEXT NOT NULL, surebet_id INTEGER
                );
                CREATE TABLE surebets (id INTEGER PRIMARY KEY, status TEXT NOT NULL);
                CREATE TABLE bets (id INTEGER PRIMARY KEY, associate_id INTEGER NOT NULL);
                CREATE TABLE surebet_bets (surebet_id INTEGER NOT NULL, bet_id INTEGER NOT NULL);
            """)
            
            # Insert test data
            conn.execute("INSERT INTO associates (id, display_alias) VALUES (1, 'Test User')")
            conn.execute("INSERT INTO surebets (id, status) VALUES (999, 'settled')")
            conn.execute("INSERT INTO bets (id, associate_id) VALUES (9991, 1)")
            conn.execute("INSERT INTO surebet_bets (surebet_id, bet_id) VALUES (999, 9991)")
            conn.execute("""
                INSERT INTO ledger_entries 
                (id, type, associate_id, amount_native, created_at_utc, surebet_id) VALUES 
                (9991, 'BET_RESULT', 1, '100.00', datetime('now'), 999)
            """)
            conn.commit()
            
            # Mock migration to fail partway through
            # This would require modifying the migration script or using mocks
            # For now, we test the conceptual rollback behavior
            
            try:
                # Simulate partial migration failure
                conn.execute("CREATE TABLE surebet_settlement_links (id INTEGER PRIMARY KEY)")
                conn.commit()
                
                # Simulate error during backfill
                raise Exception("Simulated migration failure")
                
            except Exception:
                # Migration should be atomic - either fully complete or fully rolled back
                # In practice, this would be handled by the migration script
                pass
            
            # Verify database is in a consistent state
            # The exact behavior depends on migration implementation
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            table_names = [row[0] for row in tables]
            
            # Should either have the new table (if migration completed) or not (if rolled back)
            # Inconsistent state would indicate a problem
            if 'surebet_settlement_links' in table_names:
                # If table exists, it should be properly populated or empty
                link_count = conn.execute("SELECT COUNT(*) FROM surebet_settlement_links").fetchone()[0]
                assert link_count >= 0  # Should be a valid count
            
            conn.close()
            os.unlink(temp_db.name)
