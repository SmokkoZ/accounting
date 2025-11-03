"""
Integration tests for corrections workflow.

Tests end-to-end correction flow including database transactions,
FX rate management, and ledger entry creation.
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
def integration_db():
    """Create in-memory test database with full setup."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    # Full schema creation
    create_schema(conn)
    insert_seed_data(conn)

    # Add comprehensive FX rates
    conn.execute(
        """
        INSERT INTO fx_rates_daily (currency_code, rate_to_eur, fetched_at_utc, date)
        VALUES
            ('USD', '0.85', '2025-11-03T00:00:00Z', '2025-11-03'),
            ('GBP', '1.15', '2025-11-03T00:00:00Z', '2025-11-03'),
            ('AUD', '0.62', '2025-11-03T00:00:00Z', '2025-11-03'),
            ('CAD', '0.68', '2025-11-03T00:00:00Z', '2025-11-03'),
            ('EUR', '1.00', '2025-11-03T00:00:00Z', '2025-11-03')
    """
    )
    conn.commit()

    yield conn
    conn.close()


def test_full_correction_workflow_positive(integration_db):
    """Test complete correction workflow with positive amount."""
    service = CorrectionService(db=integration_db)

    # Apply correction
    entry_id = service.apply_correction(
        associate_id=1,
        bookmaker_id=1,
        amount_native=Decimal("100.50"),
        native_currency="EUR",
        note="Late VOID correction for Bet #123",
        created_by="admin_user",
    )

    # Verify entry was created
    assert entry_id is not None

    # Verify ledger entry details
    cursor = integration_db.execute(
        """
        SELECT * FROM ledger_entries
        WHERE id = ? AND type = 'BOOKMAKER_CORRECTION'
    """,
        (entry_id,),
    )
    entry = cursor.fetchone()

    assert entry is not None
    assert Decimal(entry["amount_native"]) == Decimal("100.50")
    assert Decimal(entry["amount_eur"]) == Decimal("100.50")
    assert entry["note"] == "Late VOID correction for Bet #123"
    assert entry["created_by"] == "admin_user"

    # Verify correction appears in history
    corrections = service.get_corrections_since(days=30)
    assert len(corrections) == 1
    assert corrections[0]["id"] == entry_id


def test_full_correction_workflow_negative_multicurrency(integration_db):
    """Test complete correction workflow with negative amount in foreign currency."""
    service = CorrectionService(db=integration_db)

    # Apply negative USD correction
    entry_id = service.apply_correction(
        associate_id=1,
        bookmaker_id=1,
        amount_native=Decimal("-50.00"),
        native_currency="USD",
        note="Bookmaker fee deduction",
    )

    # Verify EUR conversion
    cursor = integration_db.execute(
        "SELECT * FROM ledger_entries WHERE id = ?", (entry_id,)
    )
    entry = cursor.fetchone()

    assert Decimal(entry["amount_native"]) == Decimal("-50.00")
    assert entry["native_currency"] == "USD"
    assert Decimal(entry["fx_rate_snapshot"]) == Decimal("0.85")
    # -50.00 USD * 0.85 EUR/USD = -42.50 EUR
    assert Decimal(entry["amount_eur"]) == Decimal("-42.50")


def test_transaction_rollback_on_error(integration_db):
    """Test transaction rollback when correction fails."""
    service = CorrectionService(db=integration_db)

    # Get initial ledger entry count
    cursor = integration_db.execute("SELECT COUNT(*) FROM ledger_entries")
    initial_count = cursor.fetchone()[0]

    # Try to apply invalid correction (zero amount)
    with pytest.raises(CorrectionError):
        service.apply_correction(
            associate_id=1,
            bookmaker_id=1,
            amount_native=Decimal("0.00"),
            native_currency="EUR",
            note="This should fail",
        )

    # Verify no entry was created
    cursor = integration_db.execute("SELECT COUNT(*) FROM ledger_entries")
    final_count = cursor.fetchone()[0]
    assert final_count == initial_count


def test_multiple_corrections_same_bookmaker(integration_db):
    """Test applying multiple corrections to the same bookmaker account."""
    service = CorrectionService(db=integration_db)

    # Apply multiple corrections
    entry_ids = []

    entry_ids.append(
        service.apply_correction(
            associate_id=1,
            bookmaker_id=1,
            amount_native=Decimal("100.00"),
            native_currency="EUR",
            note="Correction 1",
        )
    )

    entry_ids.append(
        service.apply_correction(
            associate_id=1,
            bookmaker_id=1,
            amount_native=Decimal("-25.00"),
            native_currency="EUR",
            note="Correction 2",
        )
    )

    entry_ids.append(
        service.apply_correction(
            associate_id=1,
            bookmaker_id=1,
            amount_native=Decimal("50.00"),
            native_currency="USD",
            note="Correction 3",
        )
    )

    # Verify all entries were created
    assert len(entry_ids) == 3
    assert len(set(entry_ids)) == 3  # All unique

    # Verify all corrections in history
    corrections = service.get_corrections_since(days=30, associate_id=1)
    assert len(corrections) == 3

    # Verify net impact
    total_eur = sum(c["amount_eur"] for c in corrections)
    # 100.00 EUR - 25.00 EUR + (50.00 USD * 0.85) = 100 - 25 + 42.50 = 117.50 EUR
    assert total_eur == Decimal("117.50")


def test_correction_with_multiple_associates(integration_db):
    """Test corrections for multiple associates independently."""
    # Create second associate and bookmaker
    cursor = integration_db.execute(
        """
        INSERT INTO associates (display_alias, home_currency)
        VALUES ('Partner A', 'GBP')
    """
    )
    associate_2_id = cursor.lastrowid

    cursor = integration_db.execute(
        """
        INSERT INTO bookmakers (associate_id, bookmaker_name)
        VALUES (?, 'Bet365')
    """,
        (associate_2_id,),
    )
    bookmaker_2_id = cursor.lastrowid
    integration_db.commit()

    service = CorrectionService(db=integration_db)

    # Apply corrections for both associates
    entry_1 = service.apply_correction(
        associate_id=1,
        bookmaker_id=1,
        amount_native=Decimal("100.00"),
        native_currency="EUR",
        note="Admin correction",
    )

    entry_2 = service.apply_correction(
        associate_id=associate_2_id,
        bookmaker_id=bookmaker_2_id,
        amount_native=Decimal("50.00"),
        native_currency="GBP",
        note="Partner A correction",
    )

    # Verify both entries
    assert entry_1 != entry_2

    # Verify filtering by associate
    admin_corrections = service.get_corrections_since(days=30, associate_id=1)
    assert len(admin_corrections) == 1
    assert admin_corrections[0]["id"] == entry_1

    partner_corrections = service.get_corrections_since(
        days=30, associate_id=associate_2_id
    )
    assert len(partner_corrections) == 1
    assert partner_corrections[0]["id"] == entry_2


def test_correction_preserves_existing_ledger_entries(integration_db):
    """Test corrections don't modify existing ledger entries."""
    service = CorrectionService(db=integration_db)

    # Create a mock BET_RESULT ledger entry
    integration_db.execute(
        """
        INSERT INTO ledger_entries (
            type, associate_id, bookmaker_id,
            amount_native, native_currency, fx_rate_snapshot, amount_eur,
            settlement_state, created_by, note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            "BET_RESULT",
            1,
            1,
            "100.00",
            "EUR",
            "1.00",
            "100.00",
            "WON",
            "system",
            "Test bet result",
        ),
    )
    integration_db.commit()

    # Get the original entry
    cursor = integration_db.execute(
        """
        SELECT * FROM ledger_entries
        WHERE type = 'BET_RESULT'
    """
    )
    original_entry = dict(cursor.fetchone())

    # Apply correction
    service.apply_correction(
        associate_id=1,
        bookmaker_id=1,
        amount_native=Decimal("-50.00"),
        native_currency="EUR",
        note="Test correction",
    )

    # Verify original entry unchanged
    cursor = integration_db.execute(
        """
        SELECT * FROM ledger_entries
        WHERE type = 'BET_RESULT'
    """
    )
    current_entry = dict(cursor.fetchone())

    assert original_entry == current_entry

    # Verify correction entry is separate
    cursor = integration_db.execute(
        """
        SELECT COUNT(*) FROM ledger_entries
        WHERE type = 'BOOKMAKER_CORRECTION'
    """
    )
    correction_count = cursor.fetchone()[0]
    assert correction_count == 1


def test_correction_history_ordering(integration_db):
    """Test corrections history returns entries in descending chronological order."""
    service = CorrectionService(db=integration_db)

    # Apply corrections with small delays to ensure ordering
    notes = []
    for i in range(5):
        note = f"Correction {i + 1}"
        notes.append(note)
        service.apply_correction(
            associate_id=1,
            bookmaker_id=1,
            amount_native=Decimal("10.00"),
            native_currency="EUR",
            note=note,
        )

    # Get corrections history
    corrections = service.get_corrections_since(days=30)

    # Verify ordering (most recent first)
    assert len(corrections) == 5
    assert corrections[0]["note"] == "Correction 5"
    assert corrections[1]["note"] == "Correction 4"
    assert corrections[2]["note"] == "Correction 3"
    assert corrections[3]["note"] == "Correction 2"
    assert corrections[4]["note"] == "Correction 1"


def test_correction_respects_foreign_key_constraints(integration_db):
    """Test foreign key constraints are enforced."""
    service = CorrectionService(db=integration_db)

    # Try to create correction with invalid associate
    with pytest.raises(CorrectionError, match="Associate not found"):
        service.apply_correction(
            associate_id=999,
            bookmaker_id=1,
            amount_native=Decimal("100.00"),
            native_currency="EUR",
            note="Invalid associate",
        )

    # Try to create correction with invalid bookmaker
    with pytest.raises(CorrectionError, match="not found"):
        service.apply_correction(
            associate_id=1,
            bookmaker_id=999,
            amount_native=Decimal("100.00"),
            native_currency="EUR",
            note="Invalid bookmaker",
        )


def test_correction_decimal_rounding_edge_cases(integration_db):
    """Test decimal rounding in edge cases."""
    service = CorrectionService(db=integration_db)

    # Test rounding up
    entry_id = service.apply_correction(
        associate_id=1,
        bookmaker_id=1,
        amount_native=Decimal("33.33333"),
        native_currency="USD",
        note="Rounding up test",
    )

    cursor = integration_db.execute(
        "SELECT * FROM ledger_entries WHERE id = ?", (entry_id,)
    )
    entry = cursor.fetchone()

    # Native should round to 33.33
    assert Decimal(entry["amount_native"]) == Decimal("33.33")
    # 33.33 * 0.85 = 28.3305 -> rounds to 28.33
    assert Decimal(entry["amount_eur"]) == Decimal("28.33")


def test_get_corrections_since_filters_by_days(integration_db):
    """Test get_corrections_since respects days parameter."""
    service = CorrectionService(db=integration_db)

    # Apply correction
    entry_id = service.apply_correction(
        associate_id=1,
        bookmaker_id=1,
        amount_native=Decimal("100.00"),
        native_currency="EUR",
        note="Recent correction",
    )

    # Should appear in 30-day history
    corrections_30 = service.get_corrections_since(days=30)
    assert len(corrections_30) == 1
    assert corrections_30[0]["id"] == entry_id

    # Should also appear in 1-day history (just created)
    corrections_1 = service.get_corrections_since(days=1)
    assert len(corrections_1) == 1
    assert corrections_1[0]["id"] == entry_id
