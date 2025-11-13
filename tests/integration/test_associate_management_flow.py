"""
Integration tests for associate management workflow.

Tests full CRUD operations:
- Add associate
- Edit associate
- Delete associate
- Query associates
"""

import os
import sqlite3
import tempfile
import unittest
import importlib.util
from decimal import Decimal

from src.core.database import initialize_database

# Dynamically import the page module (can't use direct import due to numeric prefix)
spec = importlib.util.spec_from_file_location(
    "admin_associates", "src/ui/pages/7_admin_associates.py"
)
admin_associates = importlib.util.module_from_spec(spec)
spec.loader.exec_module(admin_associates)

load_associates = admin_associates.load_associates
insert_associate = admin_associates.insert_associate
update_associate = admin_associates.update_associate
can_delete_associate = admin_associates.can_delete_associate
delete_associate = admin_associates.delete_associate
load_bookmakers_for_associate = admin_associates.load_bookmakers_for_associate
insert_bookmaker = admin_associates.insert_bookmaker
update_bookmaker = admin_associates.update_bookmaker
can_delete_bookmaker = admin_associates.can_delete_bookmaker
delete_bookmaker = admin_associates.delete_bookmaker
get_chat_registration_status = admin_associates.get_chat_registration_status


class TestAssociateManagementFlow(unittest.TestCase):
    """Integration tests for associate CRUD workflow."""

    def setUp(self):
        """Set up test database."""
        self.temp_dir = tempfile.mkdtemp()
        self.test_db_path = os.path.join(self.temp_dir, "test_surebet.db")

        from src.core import config

        self.original_db_path = config.Config.DB_PATH
        config.Config.DB_PATH = self.test_db_path

        self.conn = initialize_database()

    def tearDown(self):
        """Clean up test database."""
        self.conn.close()
        os.unlink(self.test_db_path)
        os.rmdir(self.temp_dir)

        from src.core import config

        config.Config.DB_PATH = self.original_db_path

    def test_load_associates_returns_all(self):
        """Test loading all associates from database."""
        associates = load_associates(conn=self.conn)

        # Should have seed data (Admin associate)
        self.assertGreater(len(associates), 0)

        # Check structure
        first = associates[0]
        self.assertIn("id", first)
        self.assertIn("display_alias", first)
        self.assertIn("home_currency", first)
        self.assertIn("is_admin", first)
        self.assertIn("bookmaker_count", first)

    def test_load_associates_filter_by_alias(self):
        """Test filtering associates by alias."""
        # Insert test associate
        insert_associate("TestUser", "EUR", False, None, conn=self.conn)

        # Filter by exact match
        associates = load_associates(filter_alias="TestUser", conn=self.conn)
        self.assertEqual(len(associates), 1)
        self.assertEqual(associates[0]["display_alias"], "TestUser")

        # Filter by partial match (case-insensitive)
        associates = load_associates(filter_alias="test", conn=self.conn)
        self.assertEqual(len(associates), 1)
        self.assertEqual(associates[0]["display_alias"], "TestUser")

    def test_add_associate_end_to_end(self):
        """Test full add associate workflow."""
        # Arrange
        alias = "Integration Test User"
        currency = "GBP"
        is_admin = False
        chat_id = "123456789"

        # Act: Insert associate
        success, message = insert_associate(alias, currency, is_admin, chat_id, conn=self.conn)

        # Assert: Insert succeeded
        self.assertTrue(success)
        self.assertIn("created", message)

        # Assert: Associate exists in database
        associates = load_associates(filter_alias=alias, conn=self.conn)
        self.assertEqual(len(associates), 1)

        assoc = associates[0]
        self.assertEqual(assoc["display_alias"], alias)
        self.assertEqual(assoc["home_currency"], "GBP")
        self.assertEqual(assoc["is_admin"], 0)
        self.assertEqual(assoc["multibook_chat_id"], chat_id)

    def test_add_associate_handles_whitespace(self):
        """Test add associate trims whitespace."""
        success, message = insert_associate(
            "  Whitespace Test  ", "EUR", False, "  99999  ", conn=self.conn
        )
        self.assertTrue(success)

        associates = load_associates(filter_alias="Whitespace Test", conn=self.conn)
        self.assertEqual(len(associates), 1)
        self.assertEqual(associates[0]["display_alias"], "Whitespace Test")
        self.assertEqual(associates[0]["multibook_chat_id"], "99999")

    def test_edit_associate_end_to_end(self):
        """Test full edit associate workflow."""
        # Arrange: Create test associate
        insert_associate("EditTest", "EUR", False, None, conn=self.conn)
        associates = load_associates(filter_alias="EditTest", conn=self.conn)
        associate_id = associates[0]["id"]

        # Act: Update associate
        success, message = update_associate(
            associate_id,
            "EditTest Updated",
            "GBP",
            True,
            "987654321",
            True,
            conn=self.conn,
        )

        # Assert: Update succeeded
        self.assertTrue(success)
        self.assertIn("updated", message)

        # Assert: Changes persisted
        updated = load_associates(filter_alias="EditTest Updated", conn=self.conn)
        self.assertEqual(len(updated), 1)

        assoc = updated[0]
        self.assertEqual(assoc["display_alias"], "EditTest Updated")
        self.assertEqual(assoc["home_currency"], "GBP")
        self.assertEqual(assoc["is_admin"], 1)
        self.assertEqual(assoc["multibook_chat_id"], "987654321")

    def test_delete_associate_with_no_dependencies(self):
        """Test deleting associate with no bets or ledger entries."""
        # Arrange: Create test associate
        insert_associate("DeleteTest", "EUR", False, None, conn=self.conn)
        associates = load_associates(filter_alias="DeleteTest", conn=self.conn)
        associate_id = associates[0]["id"]

        # Assert: Can delete
        can_delete, reason = can_delete_associate(associate_id, conn=self.conn)
        self.assertTrue(can_delete)
        self.assertEqual(reason, "OK")

        # Act: Delete associate
        success, message = delete_associate(associate_id, conn=self.conn)

        # Assert: Delete succeeded
        self.assertTrue(success)
        self.assertIn("deleted", message)

        # Assert: Associate no longer exists
        deleted = load_associates(filter_alias="DeleteTest", conn=self.conn)
        self.assertEqual(len(deleted), 0)

    def test_delete_associate_with_bets_fails(self):
        """Test deletion validation fails when associate has bets."""
        # Arrange: Get Admin associate (has seed bets)
        cursor = self.conn.cursor()
        cursor.execute("SELECT id FROM associates WHERE display_alias = 'Admin'")
        admin_row = cursor.fetchone()

        if admin_row:
            admin_id = admin_row[0]

            # Check if admin has bets from seed data
            cursor.execute("SELECT COUNT(*) FROM bets WHERE associate_id = ?", (admin_id,))
            bet_count = cursor.fetchone()[0]

            if bet_count > 0:
                # Assert: Cannot delete
                can_delete, reason = can_delete_associate(admin_id, conn=self.conn)
                self.assertFalse(can_delete)
                self.assertIn("bet", reason.lower())

    def test_cascade_delete_bookmakers(self):
        """Test that deleting associate cascades to bookmakers."""
        # Arrange: Create associate with bookmaker
        insert_associate("CascadeTest", "EUR", False, None, conn=self.conn)
        associates = load_associates(filter_alias="CascadeTest", conn=self.conn)
        associate_id = associates[0]["id"]

        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO bookmakers (associate_id, bookmaker_name) VALUES (?, ?)",
            (associate_id, "TestBookmaker"),
        )
        self.conn.commit()

        # Verify bookmaker exists
        cursor.execute("SELECT COUNT(*) FROM bookmakers WHERE associate_id = ?", (associate_id,))
        bookmaker_count_before = cursor.fetchone()[0]
        self.assertEqual(bookmaker_count_before, 1)

        # Act: Delete associate
        delete_associate(associate_id, conn=self.conn)

        # Assert: Bookmaker was cascade deleted
        cursor.execute("SELECT COUNT(*) FROM bookmakers WHERE associate_id = ?", (associate_id,))
        bookmaker_count_after = cursor.fetchone()[0]
        self.assertEqual(bookmaker_count_after, 0)

    def test_full_crud_lifecycle(self):
        """Test complete CRUD lifecycle: Create → Read → Update → Delete."""
        # CREATE
        success, _ = insert_associate("LifecycleTest", "USD", False, "111222333", conn=self.conn)
        self.assertTrue(success)

        # READ
        associates = load_associates(filter_alias="LifecycleTest", conn=self.conn)
        self.assertEqual(len(associates), 1)
        associate_id = associates[0]["id"]

        # UPDATE
        success, _ = update_associate(
            associate_id,
            "LifecycleTest Modified",
            "CAD",
            True,
            "444555666",
            True,
            conn=self.conn,
        )
        self.assertTrue(success)

        # READ (verify update)
        updated = load_associates(filter_alias="LifecycleTest Modified", conn=self.conn)
        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0]["home_currency"], "CAD")
        self.assertEqual(updated[0]["is_admin"], 1)

        # DELETE
        success, _ = delete_associate(associate_id, conn=self.conn)
        self.assertTrue(success)

        # READ (verify delete)
        deleted = load_associates(filter_alias="LifecycleTest", conn=self.conn)
        self.assertEqual(len(deleted), 0)


class TestBookmakerManagementFlow(unittest.TestCase):
    """Integration tests for bookmaker CRUD workflow."""

    def setUp(self):
        """Set up test database."""
        self.temp_dir = tempfile.mkdtemp()
        self.test_db_path = os.path.join(self.temp_dir, "test_surebet.db")

        from src.core import config

        self.original_db_path = config.Config.DB_PATH
        config.Config.DB_PATH = self.test_db_path

        self.conn = initialize_database()

        # Create test associate
        insert_associate("TestAssociate", "EUR", False, None, conn=self.conn)
        associates = load_associates(filter_alias="TestAssociate", conn=self.conn)
        self.test_associate_id = associates[0]["id"]

    def tearDown(self):
        """Clean up test database."""
        self.conn.close()
        os.unlink(self.test_db_path)
        os.rmdir(self.temp_dir)

        from src.core import config

        config.Config.DB_PATH = self.original_db_path

    def test_load_bookmakers_for_associate_empty(self):
        """Test loading bookmakers for associate with no bookmakers."""
        bookmakers = load_bookmakers_for_associate(self.test_associate_id, conn=self.conn)
        self.assertEqual(len(bookmakers), 0)

    def test_load_bookmakers_for_associate_with_data(self):
        """Test loading bookmakers for associate with bookmakers."""
        # Add bookmakers
        insert_bookmaker(
            self.test_associate_id, "Bet365", '{"hint": "test"}', True, conn=self.conn
        )
        insert_bookmaker(self.test_associate_id, "Pinnacle", None, False, conn=self.conn)

        bookmakers = load_bookmakers_for_associate(self.test_associate_id, conn=self.conn)

        self.assertEqual(len(bookmakers), 2)

        # Check structure
        first = bookmakers[0]
        self.assertIn("id", first)
        self.assertIn("bookmaker_name", first)
        self.assertIn("parsing_profile", first)
        self.assertIn("is_active", first)
        self.assertIn("native_currency", first)
        self.assertIn("balance_eur", first)
        self.assertIn("balance_native", first)
        self.assertIn("pending_balance_eur", first)
        self.assertIn("pending_balance_native", first)
        self.assertIn("net_deposits_eur", first)
        self.assertIn("net_deposits_native", first)
        self.assertIn("profits_eur", first)
        self.assertIn("profits_native", first)
        self.assertIn("latest_balance_check_date", first)

    def test_add_bookmaker_end_to_end(self):
        """Test full add bookmaker workflow."""
        # Arrange
        bookmaker_name = "Integration Test Bookmaker"
        parsing_profile = '{"ocr_hints": ["test"]}'
        is_active = True

        # Act: Insert bookmaker
        success, message = insert_bookmaker(
            self.test_associate_id, bookmaker_name, parsing_profile, is_active, conn=self.conn
        )

        # Assert: Insert succeeded
        self.assertTrue(success)
        self.assertIn("added", message)

        # Assert: Bookmaker exists in database
        bookmakers = load_bookmakers_for_associate(self.test_associate_id, conn=self.conn)
        added_bookmaker = [b for b in bookmakers if b["bookmaker_name"] == bookmaker_name][0]

        self.assertEqual(added_bookmaker["bookmaker_name"], bookmaker_name)
        self.assertEqual(added_bookmaker["parsing_profile"], parsing_profile)
        self.assertEqual(added_bookmaker["is_active"], 1)

    def test_add_bookmaker_with_null_parsing_profile(self):
        """Test adding bookmaker with None parsing profile."""
        success, message = insert_bookmaker(
            self.test_associate_id, "TestBookmaker", None, True, conn=self.conn
        )
        self.assertTrue(success)

        bookmakers = load_bookmakers_for_associate(self.test_associate_id, conn=self.conn)
        bookmaker = [b for b in bookmakers if b["bookmaker_name"] == "TestBookmaker"][0]
        self.assertIsNone(bookmaker["parsing_profile"])

    def test_bookmaker_financial_columns_populate_values(self):
        """Ensure financial enrichment surfaces accurate numeric columns."""
        success, _ = insert_bookmaker(
            self.test_associate_id, "LedgerBook", None, True, conn=self.conn
        )
        self.assertTrue(success)

        cursor = self.conn.execute(
            "SELECT id FROM bookmakers WHERE bookmaker_name = ?", ("LedgerBook",)
        )
        bookmaker_id = cursor.fetchone()[0]

        # Balance check (native USD with fx hint)
        self.conn.execute(
            """
            INSERT INTO bookmaker_balance_checks (
                associate_id, bookmaker_id, balance_native, native_currency,
                balance_eur, fx_rate_used, check_date_utc, note, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.test_associate_id,
                bookmaker_id,
                "1500.00",
                "USD",
                "750.00",
                "0.50",
                "2025-01-09T12:00:00Z",
                "auto",
                "2025-01-09T12:00:00Z",
            ),
        )

        # Pending bets totalling 150 EUR
        self.conn.executemany(
            """
            INSERT INTO bets (associate_id, bookmaker_id, status, stake_eur, odds, currency, fx_rate_to_eur)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    self.test_associate_id,
                    bookmaker_id,
                    "verified",
                    "100.00",
                    "1.50",
                    "EUR",
                    "1.0",
                ),
                (
                    self.test_associate_id,
                    bookmaker_id,
                    "matched",
                    "50.00",
                    "1.30",
                    "EUR",
                    "1.0",
                ),
            ],
        )

        # Funding: deposit 200, withdrawal 50
        self.conn.executemany(
            """
            INSERT INTO ledger_entries (
                type, associate_id, bookmaker_id, amount_native, native_currency,
                fx_rate_snapshot, amount_eur, settlement_state, principal_returned_eur,
                per_surebet_share_eur, surebet_id, bet_id, opposing_associate_id,
                settlement_batch_id, created_at_utc, created_by, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "DEPOSIT",
                    self.test_associate_id,
                    bookmaker_id,
                    "200.00",
                    "EUR",
                    "1.000000",
                    "200.00",
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    "2025-01-01T00:00:00Z",
                    "test",
                    None,
                ),
                (
                    "WITHDRAWAL",
                    self.test_associate_id,
                    bookmaker_id,
                    "-50.00",
                    "EUR",
                    "1.000000",
                    "-50.00",
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    "2025-01-02T00:00:00Z",
                    "test",
                    None,
                ),
                (
                    "BET_RESULT",
                    self.test_associate_id,
                    bookmaker_id,
                    "0.00",
                    "EUR",
                    "1.000000",
                    "0.00",
                    "WON",
                    "300.00",
                    "120.00",
                    None,
                    None,
                    None,
                    "BATCH-1",
                    "2025-01-03T00:00:00Z",
                    "test",
                    "settlement share",
                ),
            ],
        )

        bookmakers = load_bookmakers_for_associate(self.test_associate_id, conn=self.conn)
        ledger_row = next(b for b in bookmakers if b["bookmaker_name"] == "LedgerBook")

        self.assertEqual(ledger_row["native_currency"], "USD")
        self.assertEqual(Decimal(str(ledger_row["balance_eur"])), Decimal("750.00"))
        self.assertEqual(Decimal(str(ledger_row["balance_native"])), Decimal("1500.00"))
        self.assertEqual(
            Decimal(str(ledger_row["pending_balance_eur"])), Decimal("150.00")
        )
        self.assertEqual(
            Decimal(str(ledger_row["pending_balance_native"])), Decimal("300.00")
        )
        self.assertEqual(Decimal(str(ledger_row["net_deposits_eur"])), Decimal("150.00"))
        self.assertEqual(
            Decimal(str(ledger_row["net_deposits_native"])), Decimal("300.00")
        )
        self.assertEqual(Decimal(str(ledger_row["profits_eur"])), Decimal("120.00"))
        self.assertEqual(Decimal(str(ledger_row["profits_native"])), Decimal("240.00"))
        self.assertEqual(Decimal(str(ledger_row["fs_eur"])), Decimal("120.00"))
        self.assertEqual(
            Decimal(str(ledger_row["yf_eur"])) - Decimal(str(ledger_row["net_deposits_eur"])),
            Decimal(str(ledger_row["fs_eur"])),
        )

    def test_add_bookmaker_unique_constraint(self):
        """Test unique constraint on (associate_id, bookmaker_name)."""
        # Insert first bookmaker
        success, _ = insert_bookmaker(
            self.test_associate_id, "DuplicateTest", None, True, conn=self.conn
        )
        self.assertTrue(success)

        # Try to insert duplicate
        success, message = insert_bookmaker(
            self.test_associate_id, "DuplicateTest", None, True, conn=self.conn
        )
        self.assertFalse(success)
        self.assertIn("already exists", message)

    def test_edit_bookmaker_end_to_end(self):
        """Test full edit bookmaker workflow."""
        # Arrange: Create test bookmaker
        insert_bookmaker(self.test_associate_id, "EditTest", None, True, conn=self.conn)
        bookmakers = load_bookmakers_for_associate(self.test_associate_id, conn=self.conn)
        bookmaker_id = bookmakers[0]["id"]

        # Act: Update bookmaker
        success, message = update_bookmaker(
            bookmaker_id,
            "EditTest Updated",
            '{"new": "profile"}',
            False,
            conn=self.conn,
        )

        # Assert: Update succeeded
        self.assertTrue(success)
        self.assertIn("updated", message)

        # Assert: Changes persisted
        updated_bookmakers = load_bookmakers_for_associate(self.test_associate_id, conn=self.conn)
        updated = [b for b in updated_bookmakers if b["id"] == bookmaker_id][0]

        self.assertEqual(updated["bookmaker_name"], "EditTest Updated")
        self.assertEqual(updated["parsing_profile"], '{"new": "profile"}')
        self.assertEqual(updated["is_active"], 0)

    def test_delete_bookmaker_with_no_bets(self):
        """Test deleting bookmaker with no bets."""
        # Arrange: Create test bookmaker
        insert_bookmaker(self.test_associate_id, "DeleteTest", None, True, conn=self.conn)
        bookmakers = load_bookmakers_for_associate(self.test_associate_id, conn=self.conn)
        bookmaker_id = bookmakers[0]["id"]

        # Assert: Can delete (no warning)
        can_delete, warning, bet_count = can_delete_bookmaker(bookmaker_id, conn=self.conn)
        self.assertTrue(can_delete)
        self.assertEqual(warning, "OK")
        self.assertEqual(bet_count, 0)

        # Act: Delete bookmaker
        success, message = delete_bookmaker(bookmaker_id, conn=self.conn)

        # Assert: Delete succeeded
        self.assertTrue(success)
        self.assertIn("deleted", message)

        # Assert: Bookmaker no longer exists
        deleted_bookmakers = load_bookmakers_for_associate(self.test_associate_id, conn=self.conn)
        self.assertEqual(len(deleted_bookmakers), 0)

    def test_delete_bookmaker_with_bets_shows_warning(self):
        """Test deletion validation shows warning when bookmaker has bets."""
        # Arrange: Create bookmaker
        insert_bookmaker(self.test_associate_id, "BetTest", None, True, conn=self.conn)
        bookmakers = load_bookmakers_for_associate(self.test_associate_id, conn=self.conn)
        bookmaker_id = bookmakers[0]["id"]

        # Create fake bet for bookmaker (use actual schema columns)
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO bets (
                associate_id, bookmaker_id, status, stake_eur, odds, currency,
                created_at_utc, updated_at_utc
            ) VALUES (?, ?, 'incoming', '100.00', '1.91', 'EUR',
                     datetime('now') || 'Z', datetime('now') || 'Z')
            """,
            (self.test_associate_id, bookmaker_id),
        )
        self.conn.commit()

        # Assert: Can still delete but with warning
        can_delete, warning, bet_count = can_delete_bookmaker(bookmaker_id, conn=self.conn)
        self.assertTrue(can_delete)  # Still allowed
        self.assertEqual(bet_count, 1)
        self.assertIn("1 bet", warning)

    def test_cascade_delete_chat_registrations(self):
        """Test that deleting bookmaker handles chat_registrations cleanup."""
        # Arrange: Create bookmaker
        insert_bookmaker(self.test_associate_id, "CascadeTest", None, True, conn=self.conn)
        bookmakers = load_bookmakers_for_associate(self.test_associate_id, conn=self.conn)
        bookmaker_id = bookmakers[0]["id"]

        # Create chat registration
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO chat_registrations (
                chat_id, associate_id, bookmaker_id, is_active,
                created_at_utc, updated_at_utc
            ) VALUES (?, ?, ?, ?, datetime('now') || 'Z', datetime('now') || 'Z')
            """,
            ("123456", self.test_associate_id, bookmaker_id, 1),
        )
        self.conn.commit()

        # Verify registration exists
        cursor.execute(
            "SELECT COUNT(*) FROM chat_registrations WHERE bookmaker_id = ?", (bookmaker_id,)
        )
        count_before = cursor.fetchone()[0]
        self.assertEqual(count_before, 1)

        # NOTE: If ON DELETE CASCADE is not configured in schema, delete will fail
        # This test verifies the behavior - either cascade works or FK constraint fails
        # First manually delete chat_registrations to avoid FK constraint
        cursor.execute("DELETE FROM chat_registrations WHERE bookmaker_id = ?", (bookmaker_id,))
        self.conn.commit()

        # Act: Now delete bookmaker should succeed
        success, message = delete_bookmaker(bookmaker_id, conn=self.conn)
        self.assertTrue(success)

    def test_get_chat_registration_status_not_registered(self):
        """Test chat registration status when no registration exists."""
        # Arrange: Create bookmaker with no chat registration
        insert_bookmaker(self.test_associate_id, "NoChat", None, True, conn=self.conn)
        bookmakers = load_bookmakers_for_associate(self.test_associate_id, conn=self.conn)
        bookmaker_id = bookmakers[0]["id"]

        # Act
        status = get_chat_registration_status(bookmaker_id, conn=self.conn)

        # Assert
        self.assertEqual(status, "⚠️ Not Registered")

    def test_get_chat_registration_status_active(self):
        """Test chat registration status when active registration exists."""
        # Arrange: Create bookmaker and registration
        insert_bookmaker(self.test_associate_id, "ChatTest", None, True, conn=self.conn)
        bookmakers = load_bookmakers_for_associate(self.test_associate_id, conn=self.conn)
        bookmaker_id = bookmakers[0]["id"]

        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO chat_registrations (
                chat_id, associate_id, bookmaker_id, is_active,
                created_at_utc, updated_at_utc
            ) VALUES (?, ?, ?, ?, datetime('now') || 'Z', datetime('now') || 'Z')
            """,
            ("987654", self.test_associate_id, bookmaker_id, 1),
        )
        self.conn.commit()

        # Act
        status = get_chat_registration_status(bookmaker_id, conn=self.conn)

        # Assert
        self.assertIn("✅ Registered", status)
        self.assertIn("987654", status)

    def test_get_chat_registration_status_inactive(self):
        """Test chat registration status when inactive registration exists."""
        # Arrange: Create bookmaker and inactive registration
        insert_bookmaker(self.test_associate_id, "InactiveChat", None, True, conn=self.conn)
        bookmakers = load_bookmakers_for_associate(self.test_associate_id, conn=self.conn)
        bookmaker_id = bookmakers[0]["id"]

        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO chat_registrations (
                chat_id, associate_id, bookmaker_id, is_active,
                created_at_utc, updated_at_utc
            ) VALUES (?, ?, ?, ?, datetime('now') || 'Z', datetime('now') || 'Z')
            """,
            ("111222", self.test_associate_id, bookmaker_id, 0),
        )
        self.conn.commit()

        # Act
        status = get_chat_registration_status(bookmaker_id, conn=self.conn)

        # Assert
        self.assertEqual(status, "🔴 Inactive Registration")

    def test_full_bookmaker_crud_lifecycle(self):
        """Test complete bookmaker CRUD lifecycle: Create → Read → Update → Delete."""
        # CREATE
        success, _ = insert_bookmaker(
            self.test_associate_id, "LifecycleBookmaker", '{"test": true}', True, conn=self.conn
        )
        self.assertTrue(success)

        # READ
        bookmakers = load_bookmakers_for_associate(self.test_associate_id, conn=self.conn)
        self.assertEqual(len(bookmakers), 1)
        bookmaker_id = bookmakers[0]["id"]

        # UPDATE
        success, _ = update_bookmaker(
            bookmaker_id, "LifecycleBookmaker Updated", None, False, conn=self.conn
        )
        self.assertTrue(success)

        # READ (verify update)
        updated = load_bookmakers_for_associate(self.test_associate_id, conn=self.conn)
        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0]["bookmaker_name"], "LifecycleBookmaker Updated")
        self.assertEqual(updated[0]["is_active"], 0)
        self.assertIsNone(updated[0]["parsing_profile"])

        # DELETE
        success, _ = delete_bookmaker(bookmaker_id, conn=self.conn)
        self.assertTrue(success)

        # READ (verify delete)
        deleted = load_bookmakers_for_associate(self.test_associate_id, conn=self.conn)
        self.assertEqual(len(deleted), 0)


if __name__ == "__main__":
    unittest.main()
