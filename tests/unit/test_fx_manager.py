"""
Unit tests for FX Manager module.

Tests cover:
- Decimal precision handling
- Snapshot immutability
- Fallback to last known rate
- Error handling for missing currencies
"""

import sqlite3
import unittest
from datetime import date, datetime
from decimal import Decimal

import pytest

from src.core.database import get_db_connection
from src.services.fx_manager import (
    get_fx_rate,
    convert_to_eur,
    format_timestamp_utc,
    store_fx_rate,
    get_latest_fx_rate,
    parse_utc_iso,
)


class TestFXManager(unittest.TestCase):
    """Test cases for FX Manager functions."""

    def setUp(self):
        """Set up test database with sample data."""
        # Use in-memory database for testing
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row

        # Create fx_rates_daily table
        self.conn.execute(
            """
            CREATE TABLE fx_rates_daily (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                currency_code TEXT NOT NULL,
                rate_to_eur TEXT NOT NULL,
                fetched_at_utc TEXT NOT NULL,
                date TEXT NOT NULL,
                created_at_utc TEXT NOT NULL DEFAULT (datetime('now') || 'Z'),
                UNIQUE(currency_code, date)
            )
        """
        )

        # Insert sample data
        self.insert_sample_data()

    def tearDown(self):
        """Clean up test database."""
        self.conn.close()

    def insert_sample_data(self):
        """Insert sample FX rate data for testing."""
        sample_data = [
            (
                "AUD",
                "0.60",
                "2025-10-29T00:00:00Z",
                "2025-10-29",
                "2025-10-29T00:00:00Z",
            ),
            (
                "AUD",
                "0.61",
                "2025-10-28T00:00:00Z",
                "2025-10-28",
                "2025-10-28T00:00:00Z",
            ),
            (
                "GBP",
                "1.15",
                "2025-10-29T00:00:00Z",
                "2025-10-29",
                "2025-10-29T00:00:00Z",
            ),
            (
                "USD",
                "0.92",
                "2025-10-29T00:00:00Z",
                "2025-10-29",
                "2025-10-29T00:00:00Z",
            ),
        ]

        self.conn.executemany(
            """
            INSERT INTO fx_rates_daily 
            (currency_code, rate_to_eur, fetched_at_utc, date, created_at_utc)
            VALUES (?, ?, ?, ?, ?)
        """,
            sample_data,
        )

        self.conn.commit()

    def test_get_fx_rate_existing_currency_date(self):
        """Test getting FX rate for existing currency and date."""
        # Mock the database connection to use our test database
        import src.services.fx_manager

        original_get_db = src.services.fx_manager.get_db_connection
        src.services.fx_manager.get_db_connection = lambda: self.conn

        try:
            rate = get_fx_rate("AUD", date(2025, 10, 29))
            self.assertEqual(rate, Decimal("0.60"))
        finally:
            # Restore original function
            src.services.fx_manager.get_db_connection = original_get_db

    def test_get_fx_rate_fallback_to_last_known(self):
        """Test fallback to last known rate when date not found."""
        # Mock the database connection to use our test database
        import src.services.fx_manager

        original_get_db = src.services.fx_manager.get_db_connection
        src.services.fx_manager.get_db_connection = lambda: self.conn

        try:
            # Request rate for a date that doesn't exist
            rate = get_fx_rate("AUD", date(2025, 10, 30))
            # Should return the most recent rate (0.60 from 2025-10-29)
            self.assertEqual(rate, Decimal("0.60"))
        finally:
            # Restore original function
            src.services.fx_manager.get_db_connection = original_get_db

    def test_get_fx_rate_eur_base_currency(self):
        """Test that EUR always returns 1.0."""
        rate = get_fx_rate("EUR", date(2025, 10, 29))
        self.assertEqual(rate, Decimal("1.0"))

    def test_get_fx_rate_missing_currency(self):
        """Test error when currency doesn't exist."""
        # Mock the database connection to use our test database
        import src.services.fx_manager

        original_get_db = src.services.fx_manager.get_db_connection
        src.services.fx_manager.get_db_connection = lambda: self.conn

        try:
            with self.assertRaises(ValueError) as context:
                get_fx_rate("CAD", date(2025, 10, 29))

            self.assertIn("No FX rate found for currency: CAD", str(context.exception))
        finally:
            # Restore original function
            src.services.fx_manager.get_db_connection = original_get_db

    def test_convert_to_eur_non_eur_currency(self):
        """Test currency conversion for non-EUR currencies."""
        amount = Decimal("100.00")
        fx_rate = Decimal("0.60")  # 1 AUD = 0.60 EUR

        result = convert_to_eur(amount, "AUD", fx_rate)
        self.assertEqual(result, Decimal("60.00"))

    def test_convert_to_eur_eur_currency(self):
        """Test that EUR conversion returns the same amount."""
        amount = Decimal("100.00")
        fx_rate = Decimal("1.0")  # Should be ignored for EUR

        result = convert_to_eur(amount, "EUR", fx_rate)
        self.assertEqual(result, Decimal("100.00"))

    def test_convert_to_eur_decimal_precision(self):
        """Test that conversion maintains decimal precision."""
        amount = Decimal("100.123456")
        fx_rate = Decimal("0.60")

        result = convert_to_eur(amount, "AUD", fx_rate)
        # Should be rounded to 2 decimal places
        self.assertEqual(result, Decimal("60.07"))

    def test_format_timestamp_utc(self):
        """Test UTC timestamp formatting."""
        timestamp = format_timestamp_utc()

        # Should end with 'Z'
        self.assertTrue(timestamp.endswith("Z"))

        # Should be valid ISO8601
        parsed = parse_utc_iso(timestamp)
        self.assertIsInstance(parsed, datetime)

    def test_store_fx_rate_new_currency(self):
        """Test storing a new FX rate."""
        # Mock the database connection to use our test database
        import src.services.fx_manager

        original_get_db = src.services.fx_manager.get_db_connection
        src.services.fx_manager.get_db_connection = lambda: self.conn

        try:
            store_fx_rate(
                currency="CAD",
                rate_to_eur=Decimal("0.65"),
                fetched_at_utc="2025-10-29T12:00:00Z",
                source="test",
                conn=self.conn,
            )

            # Verify the rate was stored
            cursor = self.conn.execute(
                """
                SELECT rate_to_eur FROM fx_rates_daily 
                WHERE currency_code = 'CAD' AND date = '2025-10-29'
            """
            )
            row = cursor.fetchone()

            self.assertIsNotNone(row)
            self.assertEqual(row["rate_to_eur"], "0.65")
        finally:
            # Restore original function
            src.services.fx_manager.get_db_connection = original_get_db

    def test_store_fx_rate_replace_existing(self):
        """Test that storing a rate replaces existing rate for same date."""
        # Mock the database connection to use our test database
        import src.services.fx_manager

        original_get_db = src.services.fx_manager.get_db_connection
        src.services.fx_manager.get_db_connection = lambda: self.conn

        try:
            # Store a new rate for AUD on 2025-10-29 (should replace existing)
            store_fx_rate(
                currency="AUD",
                rate_to_eur=Decimal("0.65"),
                fetched_at_utc="2025-10-29T13:00:00Z",
                source="test",
                conn=self.conn,
            )

            # Re-open connection for verification (store_fx_rate closes it)
            conn = self.conn

            # Verify the rate was updated
            cursor = conn.execute(
                """
                SELECT rate_to_eur FROM fx_rates_daily
                WHERE currency_code = 'AUD' AND date = '2025-10-29'
            """
            )
            row = cursor.fetchone()

            self.assertIsNotNone(row)
            self.assertEqual(row["rate_to_eur"], "0.65")

            # Verify there's still only one record for this currency/date
            cursor = conn.execute(
                """
                SELECT COUNT(*) as count FROM fx_rates_daily
                WHERE currency_code = 'AUD' AND date = '2025-10-29'
            """
            )
            count = cursor.fetchone()["count"]
            self.assertEqual(count, 1)

            conn.close()
        finally:
            # Restore original function
            src.services.fx_manager.get_db_connection = original_get_db

    def test_get_latest_fx_rate_existing_currency(self):
        """Test getting latest FX rate for existing currency."""
        # Mock the database connection to use our test database
        import src.services.fx_manager

        original_get_db = src.services.fx_manager.get_db_connection
        src.services.fx_manager.get_db_connection = lambda: self.conn

        try:
            rate, date_str = get_latest_fx_rate("AUD")
            self.assertEqual(rate, Decimal("0.60"))  # Most recent rate
            self.assertEqual(date_str, "2025-10-29")
        finally:
            # Restore original function
            src.services.fx_manager.get_db_connection = original_get_db

    def test_get_latest_fx_rate_eur(self):
        """Test getting latest FX rate for EUR."""
        rate, date_str = get_latest_fx_rate("EUR")
        self.assertEqual(rate, Decimal("1.0"))
        self.assertIsNotNone(date_str)

    def test_get_latest_fx_rate_missing_currency(self):
        """Test getting latest FX rate for missing currency."""
        # Mock the database connection to use our test database
        import src.services.fx_manager

        original_get_db = src.services.fx_manager.get_db_connection
        src.services.fx_manager.get_db_connection = lambda: self.conn

        try:
            result = get_latest_fx_rate("CAD")
            self.assertIsNone(result)
        finally:
            # Restore original function
            src.services.fx_manager.get_db_connection = original_get_db

    def test_parse_utc_iso_with_z_suffix(self):
        """Test parsing ISO8601 string with Z suffix."""
        iso_string = "2025-10-29T14:30:00Z"
        result = parse_utc_iso(iso_string)

        self.assertIsInstance(result, datetime)
        self.assertEqual(result.year, 2025)
        self.assertEqual(result.month, 10)
        self.assertEqual(result.day, 29)
        self.assertEqual(result.hour, 14)
        self.assertEqual(result.minute, 30)
        self.assertEqual(result.second, 0)

    def test_parse_utc_iso_without_z_suffix(self):
        """Test parsing ISO8601 string without Z suffix."""
        iso_string = "2025-10-29T14:30:00+00:00"
        result = parse_utc_iso(iso_string)

        self.assertIsInstance(result, datetime)
        self.assertEqual(result.year, 2025)
        self.assertEqual(result.month, 10)
        self.assertEqual(result.day, 29)
        self.assertEqual(result.hour, 14)
        self.assertEqual(result.minute, 30)
        self.assertEqual(result.second, 0)


if __name__ == "__main__":
    unittest.main()
