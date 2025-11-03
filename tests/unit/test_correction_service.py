"""
Unit tests for CorrectionService.

Tests Story 5.1 requirements: forward-only corrections, validation,
FX rate freezing, and Decimal precision.
"""

import pytest
import sqlite3
from decimal import Decimal
from datetime import datetime, timezone

from src.services.correction_service import CorrectionService, CorrectionError
from src.core.database import get_db_connection
from src.core.schema import create_schema
from src.core.seed_data import insert_seed_data


@pytest.fixture
def test_db():
    """Create in-memory test database with schema and seed data."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    # Create schema
    create_schema(conn)

    # Insert seed data
    insert_seed_data(conn)

    # Add test FX rates (EUR per 1 unit of foreign currency)
    conn.execute(
        """
        INSERT INTO fx_rates_daily (currency_code, rate_to_eur, fetched_at_utc, date)
        VALUES
            ('USD', '0.869565', '2025-11-03T00:00:00Z', '2025-11-03'),
            ('GBP', '1.138952', '2025-11-03T00:00:00Z', '2025-11-03'),
            ('AUD', '0.568182', '2025-11-03T00:00:00Z', '2025-11-03'),
            ('CAD', '0.680272', '2025-11-03T00:00:00Z', '2025-11-03')
    """
    )
    conn.commit()

    yield conn
    conn.close()


@pytest.fixture
def correction_service(test_db):
    """Create CorrectionService with test database."""
    service = CorrectionService(db=test_db)
    yield service
    # Note: Don't close connection as it's managed by test_db fixture


def test_apply_positive_correction_eur(correction_service, test_db):
    """Test positive correction increases associate holdings (EUR)."""
    # Arrange
    associate_id = 1  # Admin from seed data
    bookmaker_id = 1  # Admin's bookmaker from seed data
    amount = Decimal("100.00")
    note = "Test positive correction"

    # Act
    entry_id = correction_service.apply_correction(
        associate_id=associate_id,
        bookmaker_id=bookmaker_id,
        amount_native=amount,
        native_currency="EUR",
        note=note,
    )

    # Assert
    assert entry_id is not None
    assert entry_id > 0

    # Verify ledger entry
    cursor = test_db.execute(
        "SELECT * FROM ledger_entries WHERE id = ?", (entry_id,)
    )
    entry = cursor.fetchone()

    assert entry is not None
    assert entry["type"] == "BOOKMAKER_CORRECTION"
    assert entry["associate_id"] == associate_id
    assert entry["bookmaker_id"] == bookmaker_id
    assert Decimal(entry["amount_native"]) == Decimal("100.00")
    assert entry["native_currency"] == "EUR"
    assert Decimal(entry["fx_rate_snapshot"]) == Decimal("1.00")
    assert Decimal(entry["amount_eur"]) == Decimal("100.00")
    assert entry["note"] == note
    assert entry["created_by"] == "local_user"

    # Verify fields that should be NULL for corrections
    assert entry["settlement_state"] is None
    assert entry["principal_returned_eur"] is None
    assert entry["per_surebet_share_eur"] is None
    assert entry["surebet_id"] is None
    assert entry["bet_id"] is None
    assert entry["settlement_batch_id"] is None


def test_apply_negative_correction_usd(correction_service, test_db):
    """Test negative correction decreases associate holdings (USD)."""
    # Arrange
    associate_id = 1
    bookmaker_id = 1
    amount = Decimal("-25.00")
    note = "Test negative correction"

    # Act
    entry_id = correction_service.apply_correction(
        associate_id=associate_id,
        bookmaker_id=bookmaker_id,
        amount_native=amount,
        native_currency="USD",
        note=note,
    )

    # Assert
    cursor = test_db.execute(
        "SELECT * FROM ledger_entries WHERE id = ?", (entry_id,)
    )
    entry = cursor.fetchone()

    assert Decimal(entry["amount_native"]) == Decimal("-25.00")
    assert entry["native_currency"] == "USD"
    assert Decimal(entry["fx_rate_snapshot"]) == Decimal("0.869565")
    # -25.00 USD * 0.869565 EUR/USD = -21.74 EUR (rounded)
    assert Decimal(entry["amount_eur"]) == Decimal("-21.74")


def test_correction_validation_zero_amount(correction_service):
    """Test zero corrections are rejected."""
    with pytest.raises(CorrectionError, match="cannot be zero"):
        correction_service.apply_correction(
            associate_id=1,
            bookmaker_id=1,
            amount_native=Decimal("0.00"),
            native_currency="EUR",
            note="This should fail",
        )


def test_correction_validation_missing_note(correction_service):
    """Test missing notes are rejected."""
    with pytest.raises(CorrectionError, match="required"):
        correction_service.apply_correction(
            associate_id=1,
            bookmaker_id=1,
            amount_native=Decimal("100.00"),
            native_currency="EUR",
            note="",
        )


def test_correction_validation_whitespace_note(correction_service):
    """Test whitespace-only notes are rejected."""
    with pytest.raises(CorrectionError, match="required"):
        correction_service.apply_correction(
            associate_id=1,
            bookmaker_id=1,
            amount_native=Decimal("100.00"),
            native_currency="EUR",
            note="   ",
        )


def test_correction_validation_invalid_associate(correction_service):
    """Test invalid associate ID is rejected."""
    with pytest.raises(CorrectionError, match="Associate not found"):
        correction_service.apply_correction(
            associate_id=9999,
            bookmaker_id=1,
            amount_native=Decimal("100.00"),
            native_currency="EUR",
            note="This should fail",
        )


def test_correction_validation_invalid_bookmaker(correction_service):
    """Test invalid bookmaker ID is rejected."""
    with pytest.raises(CorrectionError, match="not found"):
        correction_service.apply_correction(
            associate_id=1,
            bookmaker_id=9999,
            amount_native=Decimal("100.00"),
            native_currency="EUR",
            note="This should fail",
        )


def test_correction_validation_bookmaker_wrong_associate(correction_service, test_db):
    """Test bookmaker must belong to specified associate."""
    # Create second associate and bookmaker
    cursor = test_db.execute(
        """
        INSERT INTO associates (display_alias, home_currency)
        VALUES ('TestUser', 'EUR')
    """
    )
    associate_2_id = cursor.lastrowid

    cursor = test_db.execute(
        """
        INSERT INTO bookmakers (associate_id, bookmaker_name)
        VALUES (?, 'Pinnacle')
    """,
        (associate_2_id,),
    )
    bookmaker_2_id = cursor.lastrowid
    test_db.commit()

    # Try to apply correction using associate 1's ID with associate 2's bookmaker
    with pytest.raises(CorrectionError, match="does not belong"):
        correction_service.apply_correction(
            associate_id=1,  # Admin
            bookmaker_id=bookmaker_2_id,  # TestUser's bookmaker
            amount_native=Decimal("100.00"),
            native_currency="EUR",
            note="This should fail",
        )


def test_correction_validation_unsupported_currency(correction_service):
    """Test unsupported currency is rejected."""
    with pytest.raises(CorrectionError, match="Unsupported currency"):
        correction_service.apply_correction(
            associate_id=1,
            bookmaker_id=1,
            amount_native=Decimal("100.00"),
            native_currency="JPY",
            note="This should fail",
        )


def test_correction_fx_rate_freezing_gbp(correction_service, test_db):
    """Test FX rates are frozen at correction time (GBP)."""
    entry_id = correction_service.apply_correction(
        associate_id=1,
        bookmaker_id=1,
        amount_native=Decimal("50.00"),
        native_currency="GBP",
        note="Test FX rate freezing",
    )

    cursor = test_db.execute(
        "SELECT * FROM ledger_entries WHERE id = ?", (entry_id,)
    )
    entry = cursor.fetchone()

    # Verify FX rate snapshot is stored
    assert Decimal(entry["fx_rate_snapshot"]) == Decimal("1.138952")
    # 50.00 GBP * 1.138952 EUR/GBP = 56.95 EUR (rounded)
    assert Decimal(entry["amount_eur"]) == Decimal("56.95")


def test_correction_decimal_precision(correction_service, test_db):
    """Test all calculations use proper Decimal precision."""
    # Test amount with many decimal places
    entry_id = correction_service.apply_correction(
        associate_id=1,
        bookmaker_id=1,
        amount_native=Decimal("100.12345"),
        native_currency="AUD",
        note="Test decimal precision",
    )

    cursor = test_db.execute(
        "SELECT * FROM ledger_entries WHERE id = ?", (entry_id,)
    )
    entry = cursor.fetchone()

    # Native amount should be rounded to 2 decimal places
    assert Decimal(entry["amount_native"]) == Decimal("100.12")

    # EUR amount should also be 2 decimal places
    # 100.12 AUD * 0.568182 EUR/AUD = 56.89 EUR (rounded)
    assert Decimal(entry["amount_eur"]) == Decimal("56.89")


def test_correction_missing_fx_rate(correction_service, test_db):
    """Test error when FX rate is not available."""
    # Use a currency with rate first to confirm success
    entry_id = correction_service.apply_correction(
        associate_id=1,
        bookmaker_id=1,
        amount_native=Decimal("100.00"),
        native_currency="CAD",
        note="This should work",
    )
    assert entry_id > 0

    # Now delete CAD rate and try again
    test_db.execute("DELETE FROM fx_rates_daily WHERE currency_code = 'CAD'")
    test_db.commit()

    # Should fail now that rate is missing
    with pytest.raises(CorrectionError, match="No FX rate available"):
        correction_service.apply_correction(
            associate_id=1,
            bookmaker_id=1,
            amount_native=Decimal("100.00"),
            native_currency="CAD",
            note="This should fail",
        )


def test_get_corrections_since_30_days(correction_service, test_db):
    """Test retrieving corrections from last 30 days."""
    # Apply several corrections
    correction_service.apply_correction(
        associate_id=1,
        bookmaker_id=1,
        amount_native=Decimal("100.00"),
        native_currency="EUR",
        note="Correction 1",
    )

    correction_service.apply_correction(
        associate_id=1,
        bookmaker_id=1,
        amount_native=Decimal("-50.00"),
        native_currency="USD",
        note="Correction 2",
    )

    correction_service.apply_correction(
        associate_id=1,
        bookmaker_id=1,
        amount_native=Decimal("25.00"),
        native_currency="GBP",
        note="Correction 3",
    )

    # Retrieve corrections
    corrections = correction_service.get_corrections_since(days=30)

    # Assert
    assert len(corrections) == 3
    # All corrections returned by get_corrections_since are BOOKMAKER_CORRECTION type
    # (no need to assert on 'type' field since it's filtered in the query)
    assert corrections[0]["note"] == "Correction 3"  # Most recent first
    assert corrections[1]["note"] == "Correction 2"
    assert corrections[2]["note"] == "Correction 1"


def test_get_corrections_filter_by_associate(correction_service, test_db):
    """Test filtering corrections by associate."""
    # Create second associate and bookmaker
    cursor = test_db.execute(
        """
        INSERT INTO associates (display_alias, home_currency)
        VALUES ('Partner', 'EUR')
    """
    )
    associate_2_id = cursor.lastrowid

    cursor = test_db.execute(
        """
        INSERT INTO bookmakers (associate_id, bookmaker_name)
        VALUES (?, 'Bet365')
    """,
        (associate_2_id,),
    )
    bookmaker_2_id = cursor.lastrowid
    test_db.commit()

    # Apply corrections for both associates
    correction_service.apply_correction(
        associate_id=1,
        bookmaker_id=1,
        amount_native=Decimal("100.00"),
        native_currency="EUR",
        note="Admin correction",
    )

    correction_service.apply_correction(
        associate_id=associate_2_id,
        bookmaker_id=bookmaker_2_id,
        amount_native=Decimal("50.00"),
        native_currency="EUR",
        note="Partner correction",
    )

    # Filter by associate 1
    corrections = correction_service.get_corrections_since(
        days=30, associate_id=1
    )
    assert len(corrections) == 1
    assert corrections[0]["associate_id"] == 1
    assert corrections[0]["note"] == "Admin correction"

    # Filter by associate 2
    corrections = correction_service.get_corrections_since(
        days=30, associate_id=associate_2_id
    )
    assert len(corrections) == 1
    assert corrections[0]["associate_id"] == associate_2_id
    assert corrections[0]["note"] == "Partner correction"


def test_get_corrections_empty_result(correction_service):
    """Test get_corrections_since returns empty list when no corrections exist."""
    corrections = correction_service.get_corrections_since(days=30)
    assert corrections == []


def test_correction_created_by_custom_user(correction_service, test_db):
    """Test correction with custom created_by field."""
    entry_id = correction_service.apply_correction(
        associate_id=1,
        bookmaker_id=1,
        amount_native=Decimal("100.00"),
        native_currency="EUR",
        note="Test custom user",
        created_by="admin@example.com",
    )

    cursor = test_db.execute(
        "SELECT * FROM ledger_entries WHERE id = ?", (entry_id,)
    )
    entry = cursor.fetchone()

    assert entry["created_by"] == "admin@example.com"


def test_correction_timestamp_format(correction_service, test_db):
    """Test correction timestamp follows ISO8601 format."""
    entry_id = correction_service.apply_correction(
        associate_id=1,
        bookmaker_id=1,
        amount_native=Decimal("100.00"),
        native_currency="EUR",
        note="Test timestamp",
    )

    cursor = test_db.execute(
        "SELECT created_at_utc FROM ledger_entries WHERE id = ?", (entry_id,)
    )
    entry = cursor.fetchone()

    timestamp = entry["created_at_utc"]

    # Verify format: YYYY-MM-DDTHH:MM:SS.ffffffZ
    assert timestamp.endswith("Z")
    assert "T" in timestamp

    # Verify it's parseable
    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    assert dt.tzinfo is not None


def test_correction_service_close(test_db):
    """Test service cleanup when it owns the connection."""
    # Create service without providing connection (it will create its own)
    service = CorrectionService()
    service.close()

    # Verify connection is closed by trying to use it
    with pytest.raises(sqlite3.ProgrammingError):
        service.db.execute("SELECT 1")


def test_correction_service_close_shared_connection(test_db):
    """Test service doesn't close connection it doesn't own."""
    # Create service with provided connection
    service = CorrectionService(db=test_db)
    service.close()

    # Connection should still be usable
    cursor = test_db.execute("SELECT 1")
    result = cursor.fetchone()
    assert result[0] == 1
