"""
Unit tests for UI input validators.

Tests validation logic for:
- Currency codes
- Associate aliases
- Telegram chat IDs
"""

import os
import sqlite3
import tempfile
import unittest

from src.ui.utils.validators import (
    validate_currency,
    validate_alias,
    validate_multibook_chat_id,
    validate_json,
    validate_balance_amount,
    VALID_CURRENCIES,
)
from src.core.database import initialize_database


class TestCurrencyValidation(unittest.TestCase):
    """Test currency code validation."""

    def test_validate_currency_valid_codes(self):
        """Test validation passes for valid currency codes."""
        for currency in VALID_CURRENCIES:
            is_valid, error = validate_currency(currency)
            self.assertTrue(is_valid, f"{currency} should be valid")
            self.assertEqual(error, "")

    def test_validate_currency_case_insensitive(self):
        """Test validation is case-insensitive."""
        is_valid, error = validate_currency("eur")
        self.assertTrue(is_valid)
        self.assertEqual(error, "")

        is_valid, error = validate_currency("GbP")
        self.assertTrue(is_valid)
        self.assertEqual(error, "")

    def test_validate_currency_with_whitespace(self):
        """Test validation handles whitespace."""
        is_valid, error = validate_currency("  EUR  ")
        self.assertTrue(is_valid)
        self.assertEqual(error, "")

    def test_validate_currency_invalid_code(self):
        """Test validation fails for invalid codes."""
        is_valid, error = validate_currency("XYZ")
        self.assertFalse(is_valid)
        self.assertIn("Invalid currency code", error)

    def test_validate_currency_empty_string(self):
        """Test validation fails for empty string."""
        is_valid, error = validate_currency("")
        self.assertFalse(is_valid)
        self.assertIn("required", error)

    def test_validate_currency_none(self):
        """Test validation fails for None."""
        is_valid, error = validate_currency(None)
        self.assertFalse(is_valid)
        self.assertIn("required", error)


class TestAliasValidation(unittest.TestCase):
    """Test associate alias validation."""

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

    def test_validate_alias_valid(self):
        """Test validation passes for valid alias."""
        is_valid, error = validate_alias("Alice")
        self.assertTrue(is_valid)
        self.assertEqual(error, "")

    def test_validate_alias_empty_string(self):
        """Test validation fails for empty string."""
        is_valid, error = validate_alias("")
        self.assertFalse(is_valid)
        self.assertIn("required", error)

    def test_validate_alias_whitespace_only(self):
        """Test validation fails for whitespace-only string."""
        is_valid, error = validate_alias("   ")
        self.assertFalse(is_valid)
        self.assertIn("required", error)

    def test_validate_alias_too_long(self):
        """Test validation fails for alias exceeding 50 characters."""
        long_alias = "A" * 51
        is_valid, error = validate_alias(long_alias)
        self.assertFalse(is_valid)
        self.assertIn("too long", error)

    def test_validate_alias_max_length(self):
        """Test validation passes for 50-character alias."""
        max_alias = "A" * 50
        is_valid, error = validate_alias(max_alias)
        self.assertTrue(is_valid)
        self.assertEqual(error, "")

    def test_validate_alias_uniqueness_passes_when_new(self):
        """Test uniqueness validation passes when alias doesn't exist."""
        is_valid, error = validate_alias("NewAlias", db_connection=self.conn)
        self.assertTrue(is_valid)
        self.assertEqual(error, "")

    def test_validate_alias_uniqueness_fails_when_exists(self):
        """Test uniqueness validation fails when alias already exists."""
        # Seed data should have an "Admin" associate
        is_valid, error = validate_alias("Admin", db_connection=self.conn)
        self.assertFalse(is_valid)
        self.assertIn("already exists", error)

    def test_validate_alias_uniqueness_excludes_own_id(self):
        """Test uniqueness validation excludes own record when editing."""
        # Get Admin associate ID
        cursor = self.conn.cursor()
        cursor.execute("SELECT id FROM associates WHERE display_alias = 'Admin'")
        admin_id = cursor.fetchone()[0]

        # Should pass when excluding own ID
        is_valid, error = validate_alias("Admin", exclude_id=admin_id, db_connection=self.conn)
        self.assertTrue(is_valid)
        self.assertEqual(error, "")


class TestMultibookChatIdValidation(unittest.TestCase):
    """Test Telegram multibook chat ID validation."""

    def test_validate_chat_id_valid_positive(self):
        """Test validation passes for valid positive chat ID."""
        is_valid, error = validate_multibook_chat_id("123456789")
        self.assertTrue(is_valid)
        self.assertEqual(error, "")

    def test_validate_chat_id_valid_negative(self):
        """Test validation passes for valid negative chat ID (groups)."""
        is_valid, error = validate_multibook_chat_id("-100123456789")
        self.assertTrue(is_valid)
        self.assertEqual(error, "")

    def test_validate_chat_id_empty_string(self):
        """Test validation passes for empty string (optional field)."""
        is_valid, error = validate_multibook_chat_id("")
        self.assertTrue(is_valid)
        self.assertEqual(error, "")

    def test_validate_chat_id_none(self):
        """Test validation passes for None (optional field)."""
        is_valid, error = validate_multibook_chat_id(None)
        self.assertTrue(is_valid)
        self.assertEqual(error, "")

    def test_validate_chat_id_whitespace_only(self):
        """Test validation passes for whitespace-only (optional field)."""
        is_valid, error = validate_multibook_chat_id("   ")
        self.assertTrue(is_valid)
        self.assertEqual(error, "")

    def test_validate_chat_id_invalid_format(self):
        """Test validation fails for non-numeric chat ID."""
        is_valid, error = validate_multibook_chat_id("abc123")
        self.assertFalse(is_valid)
        self.assertIn("must be a number", error)

    def test_validate_chat_id_with_whitespace(self):
        """Test validation handles whitespace."""
        is_valid, error = validate_multibook_chat_id("  123456789  ")
        self.assertTrue(is_valid)
        self.assertEqual(error, "")


class TestJsonValidation(unittest.TestCase):
    """Test JSON format validation."""

    def test_validate_json_with_valid_json(self):
        """Test validation passes for valid JSON string."""
        valid_json = '{"ocr_hints": ["bet365", "odds"]}'
        is_valid, error = validate_json(valid_json)
        self.assertTrue(is_valid)
        self.assertEqual(error, "")

    def test_validate_json_with_valid_json_array(self):
        """Test validation passes for valid JSON array."""
        valid_json = '["hint1", "hint2", "hint3"]'
        is_valid, error = validate_json(valid_json)
        self.assertTrue(is_valid)
        self.assertEqual(error, "")

    def test_validate_json_with_valid_json_nested(self):
        """Test validation passes for nested JSON."""
        valid_json = '{"bookmaker": "bet365", "config": {"timeout": 30}}'
        is_valid, error = validate_json(valid_json)
        self.assertTrue(is_valid)
        self.assertEqual(error, "")

    def test_validate_json_with_empty_string(self):
        """Test validation passes for empty string (optional field)."""
        is_valid, error = validate_json("")
        self.assertTrue(is_valid)
        self.assertEqual(error, "")

    def test_validate_json_with_none(self):
        """Test validation passes for None (optional field)."""
        is_valid, error = validate_json(None)
        self.assertTrue(is_valid)
        self.assertEqual(error, "")

    def test_validate_json_with_whitespace_only(self):
        """Test validation passes for whitespace-only string (optional field)."""
        is_valid, error = validate_json("   ")
        self.assertTrue(is_valid)
        self.assertEqual(error, "")

    def test_validate_json_with_invalid_json_missing_brace(self):
        """Test validation fails for invalid JSON with missing brace."""
        invalid_json = '{"key": "value"'
        is_valid, error = validate_json(invalid_json)
        self.assertFalse(is_valid)
        self.assertIn("Invalid JSON", error)

    def test_validate_json_with_invalid_json_extra_comma(self):
        """Test validation fails for invalid JSON with trailing comma."""
        invalid_json = '{"key": "value",}'
        is_valid, error = validate_json(invalid_json)
        self.assertFalse(is_valid)
        self.assertIn("Invalid JSON", error)

    def test_validate_json_with_invalid_json_single_quotes(self):
        """Test validation fails for invalid JSON with single quotes."""
        invalid_json = "{'key': 'value'}"
        is_valid, error = validate_json(invalid_json)
        self.assertFalse(is_valid)
        self.assertIn("Invalid JSON", error)

    def test_validate_json_with_invalid_json_unquoted_keys(self):
        """Test validation fails for invalid JSON with unquoted keys."""
        invalid_json = "{key: value}"
        is_valid, error = validate_json(invalid_json)
        self.assertFalse(is_valid)
        self.assertIn("Invalid JSON", error)


class TestBalanceAmountValidation(unittest.TestCase):
    """Test balance amount validation."""

    def test_validate_balance_amount_positive(self):
        """Test validation passes for positive number."""
        is_valid, error = validate_balance_amount("1250.50")
        self.assertTrue(is_valid)
        self.assertEqual(error, "")

    def test_validate_balance_amount_integer(self):
        """Test validation passes for integer."""
        is_valid, error = validate_balance_amount("1000")
        self.assertTrue(is_valid)
        self.assertEqual(error, "")

    def test_validate_balance_amount_one_decimal(self):
        """Test validation passes for one decimal place."""
        is_valid, error = validate_balance_amount("100.5")
        self.assertTrue(is_valid)
        self.assertEqual(error, "")

    def test_validate_balance_amount_two_decimals(self):
        """Test validation passes for two decimal places."""
        is_valid, error = validate_balance_amount("100.50")
        self.assertTrue(is_valid)
        self.assertEqual(error, "")

    def test_validate_balance_amount_negative_fails(self):
        """Test validation fails for negative number."""
        is_valid, error = validate_balance_amount("-100")
        self.assertFalse(is_valid)
        self.assertIn("positive", error.lower())

    def test_validate_balance_amount_zero_fails(self):
        """Test validation fails for zero."""
        is_valid, error = validate_balance_amount("0")
        self.assertFalse(is_valid)
        self.assertIn("positive", error.lower())

    def test_validate_balance_amount_too_many_decimals(self):
        """Test validation fails for >2 decimals."""
        is_valid, error = validate_balance_amount("100.505")
        self.assertFalse(is_valid)
        self.assertIn("2 decimal", error.lower())

    def test_validate_balance_amount_empty_string(self):
        """Test validation fails for empty string."""
        is_valid, error = validate_balance_amount("")
        self.assertFalse(is_valid)
        self.assertIn("required", error.lower())

    def test_validate_balance_amount_invalid_format(self):
        """Test validation fails for invalid format."""
        is_valid, error = validate_balance_amount("abc")
        self.assertFalse(is_valid)
        self.assertIn("format", error.lower())

    def test_validate_balance_amount_with_commas(self):
        """Test validation fails for numbers with commas."""
        is_valid, error = validate_balance_amount("1,250.50")
        self.assertFalse(is_valid)
        self.assertIn("format", error.lower())


if __name__ == "__main__":
    unittest.main()
