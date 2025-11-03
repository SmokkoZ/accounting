"""
Unit tests for core database functionality.

Tests schema creation, validation, and seed data insertion.
"""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.core.database import initialize_database, get_db_connection
from src.core.schema_validation import validate_schema, SchemaValidationError
from src.core.seed_data import get_seed_data_summary


class TestCoreDatabase(unittest.TestCase):
    """Test core database functionality."""

    def setUp(self):
        """Set up test database."""
        # Create temporary database for testing
        self.temp_dir = tempfile.mkdtemp()
        self.test_db_path = os.path.join(self.temp_dir, "test_surebet.db")

        # Override config for testing
        from src.core import config

        self.original_db_path = config.Config.DB_PATH
        config.Config.DB_PATH = self.test_db_path

        # Initialize test database
        self.conn = initialize_database()

    def tearDown(self):
        """Clean up test database."""
        self.conn.close()
        os.unlink(self.test_db_path)
        os.rmdir(self.temp_dir)

        # Restore original config
        from src.core import config

        config.Config.DB_PATH = self.original_db_path

    def test_database_initialization(self):
        """Test that database initializes correctly."""
        # Check that database file exists
        self.assertTrue(os.path.exists(self.test_db_path))

        # Check that foreign keys are enabled
        cursor = self.conn.execute("PRAGMA foreign_keys")
        self.assertTrue(cursor.fetchone()[0])

        # Check that WAL mode is enabled
        cursor = self.conn.execute("PRAGMA journal_mode")
        self.assertEqual(cursor.fetchone()[0], "wal")

    def test_schema_validation(self):
        """Test that schema validation passes."""
        # This should not raise an exception
        try:
            validate_schema(self.conn)
        except SchemaValidationError as e:
            self.fail(f"Schema validation failed: {e}")

    def test_all_tables_exist(self):
        """Test that all required tables are created."""
        required_tables = [
            "associates",
            "bookmakers",
            "canonical_events",
            "canonical_markets",
            "bets",
            "surebets",
            "surebet_bets",
            "ledger_entries",
            "verification_audit",
            "multibook_message_log",
            "bookmaker_balance_checks",
            "fx_rates_daily",
        ]

        cursor = self.conn.execute(
            """
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
        """
        )

        existing_tables = {row[0] for row in cursor.fetchall()}

        for table in required_tables:
            self.assertIn(table, existing_tables, f"Missing table: {table}")

    def test_seed_data_insertion(self):
        """Test that seed data is inserted correctly."""
        summary = get_seed_data_summary(self.conn)

        # Check that associates were inserted
        self.assertEqual(summary["associates"], 2)

        # Check that bookmakers were inserted
        self.assertEqual(summary["bookmakers"], 4)

        # Check that canonical markets were inserted
        self.assertEqual(summary["canonical_markets"], 14)

        # Check that other tables are empty (except for seed data)
        self.assertEqual(summary["canonical_events"], 0)
        self.assertEqual(summary["bets"], 0)
        self.assertEqual(summary["surebets"], 0)

    def test_ledger_append_only_constraint(self):
        """Test that ledger_entries table is append-only."""
        # Insert a test ledger entry
        self.conn.execute(
            """
            INSERT INTO ledger_entries 
            (type, associate_id, amount_native, native_currency, fx_rate_snapshot, amount_eur, settlement_state, principal_returned_eur, per_surebet_share_eur, settlement_batch_id, note)
            VALUES ('BET_RESULT', 1, '0.00', 'EUR', '1.0', '0.00', 'VOID', '0.00', '0.00', 'test-batch', 'Append-only test entry')
        """
        )

        # Try to update - should fail
        with self.assertRaises(sqlite3.IntegrityError) as cm:
            self.conn.execute(
                """
                UPDATE ledger_entries
                SET amount_eur = '200.00' WHERE id = 1
            """
            )

        self.assertIn("append-only", str(cm.exception))

        # Try to delete - should fail
        with self.assertRaises(sqlite3.IntegrityError) as cm:
            self.conn.execute("DELETE FROM ledger_entries WHERE id = 1")

        self.assertIn("append-only", str(cm.exception))

    def test_surebet_bets_side_immutable(self):
        """Test that surebet_bets.side is immutable after creation."""
        # Insert test data
        self.conn.execute(
            """
            INSERT INTO canonical_events (normalized_event_name) 
            VALUES ('Test Event')
        """
        )

        self.conn.execute(
            """
            INSERT INTO canonical_markets (market_code, description) 
            VALUES ('TEST_MARKET', 'Test Market')
        """
        )

        self.conn.execute(
            """
            INSERT INTO surebets (canonical_event_id, canonical_market_id, market_code, period_scope)
            VALUES (1, 1, 'TEST_MARKET', 'FULL_MATCH')
        """
        )

        self.conn.execute(
            """
            INSERT INTO bets (associate_id, bookmaker_id, stake_eur, odds) 
            VALUES (1, 1, '100.00', '2.0')
        """
        )

        self.conn.execute(
            """
            INSERT INTO surebet_bets (surebet_id, bet_id, side) 
            VALUES (1, 1, 'A')
        """
        )

        # Try to update side - should fail
        with self.assertRaises(sqlite3.IntegrityError) as cm:
            self.conn.execute(
                """
                UPDATE surebet_bets
                SET side = 'B' WHERE surebet_id = 1 AND bet_id = 1
            """
            )

        self.assertIn("immutable", str(cm.exception))

    def test_foreign_key_constraints(self):
        """Test that foreign key constraints are enforced."""
        # Try to insert a bet with non-existent associate - should fail
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                """
                INSERT INTO bets (associate_id, bookmaker_id, stake_eur, odds) 
                VALUES (999, 1, '100.00', '2.0')
            """
            )

        # Try to insert a bookmaker with non-existent associate - should fail
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                """
                INSERT INTO bookmakers (associate_id, bookmaker_name) 
                VALUES (999, 'Test Bookmaker')
            """
            )

    def test_unique_constraints(self):
        """Test that unique constraints are enforced."""
        # Try to insert duplicate associate - should fail
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                """
                INSERT INTO associates (display_alias, home_currency) 
                VALUES ('Admin', 'EUR')
            """
            )

        # Try to insert duplicate bookmaker for same associate - should fail
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                """
                INSERT INTO bookmakers (associate_id, bookmaker_name) 
                VALUES (1, 'Bet365')
            """
            )

    def test_currency_fields_stored_as_text(self):
        """Test that currency fields are stored as TEXT type."""
        # Check table schema for currency fields
        cursor = self.conn.execute("PRAGMA table_info(bets)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}

        # Currency fields should be TEXT type
        self.assertEqual(columns["stake_eur"], "TEXT")
        self.assertEqual(columns["odds"], "TEXT")
        self.assertEqual(columns["fx_rate_to_eur"], "TEXT")

        # Check ledger entries
        cursor = self.conn.execute("PRAGMA table_info(ledger_entries)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}

        self.assertEqual(columns["amount_native"], "TEXT")
        self.assertEqual(columns["native_currency"], "TEXT")
        self.assertEqual(columns["amount_eur"], "TEXT")
        self.assertEqual(columns["fx_rate_snapshot"], "TEXT")
        self.assertEqual(columns["principal_returned_eur"], "TEXT")
        self.assertEqual(columns["per_surebet_share_eur"], "TEXT")

    def test_timestamp_fields_stored_as_text(self):
        """Test that timestamp fields are stored as TEXT type."""
        # Check table schema for timestamp fields
        cursor = self.conn.execute("PRAGMA table_info(bets)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}

        # Timestamp fields should be TEXT type
        self.assertEqual(columns["created_at_utc"], "TEXT")
        self.assertEqual(columns["updated_at_utc"], "TEXT")

        # Check other tables
        cursor = self.conn.execute("PRAGMA table_info(ledger_entries)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}

        self.assertEqual(columns["created_at_utc"], "TEXT")


if __name__ == "__main__":
    unittest.main()
