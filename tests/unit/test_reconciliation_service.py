"""
Unit tests for ReconciliationService.

Tests Story 5.2 requirements: associate balance calculations, DELTA thresholds,
status determination, and human-readable explanations.
"""

import pytest
import sqlite3
from decimal import Decimal
from pathlib import Path
import tempfile

from src.services.reconciliation_service import (
    ReconciliationService,
    AssociateBalance,
)
from src.core.schema import create_schema


@pytest.fixture
def test_db():
    """Create a temporary test database with schema."""
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    temp_file.close()
    db_path = temp_file.name

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    # Create schema
    create_schema(conn)

    yield conn

    conn.close()
    Path(db_path).unlink()


@pytest.fixture
def service(test_db):
    """Create ReconciliationService with test database."""
    return ReconciliationService(db=test_db)


def seed_associates(db: sqlite3.Connection):
    """Seed test associates."""
    db.executemany(
        """
        INSERT INTO associates (id, display_alias)
        VALUES (?, ?)
        """,
        [
            (1, "Alice"),
            (2, "Bob"),
            (3, "Charlie"),
            (4, "Admin"),
        ],
    )
    db.commit()


def seed_bookmakers(db: sqlite3.Connection):
    """Seed test bookmakers for all associates."""
    db.executemany(
        """
        INSERT INTO bookmakers (id, associate_id, bookmaker_name)
        VALUES (?, ?, ?)
        """,
        [
            (1, 1, 'TestBookmaker1'),
            (2, 2, 'TestBookmaker2'),
            (3, 3, 'TestBookmaker3'),
            (4, 4, 'TestBookmaker4'),
        ]
    )
    db.commit()


def create_test_surebet_context(db: sqlite3.Connection, bet_id: int = 1, associate_id: int = 1):
    """Create minimal surebet context for ledger entries tests."""
    db.execute(
        """
        INSERT OR IGNORE INTO canonical_events (id, normalized_event_name, kickoff_time_utc, sport)
        VALUES (1, 'Test Match', '2025-01-01T12:00:00Z', 'soccer')
        """
    )
    db.execute(
        """
        INSERT OR IGNORE INTO canonical_markets (id, market_code, description)
        VALUES (1, 'match_winner', 'Match Winner')
        """
    )
    # Use same ID for bookmaker as associate (matching seed_bookmakers)
    db.execute(
        f"""
        INSERT OR IGNORE INTO bets (
            id, associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
            odds, stake_eur, currency, status
        )
        VALUES ({bet_id}, {associate_id}, {associate_id}, 1, 1, '2.00', '100.00', 'EUR', 'settled')
        """
    )
    db.execute(
        """
        INSERT OR IGNORE INTO surebets (id, canonical_event_id, market_code, period_scope, status)
        VALUES (1, 1, 'match_winner', 'FT', 'settled')
        """
    )
    db.commit()


# ========================================
# Test NET_DEPOSITS_EUR Calculation
# ========================================


def test_calculate_net_deposits_eur_deposits_only(test_db, service):
    """
    Test NET_DEPOSITS calculation with only deposits.

    Given: Associate with multiple DEPOSIT entries
    When: Balances calculated
    Then: NET_DEPOSITS = sum of all deposits
    """
    seed_associates(test_db)
    seed_bookmakers(test_db)

    # Alice deposits €1000 and €500
    test_db.executemany(
        """
        INSERT INTO ledger_entries (
            type, associate_id, bookmaker_id, amount_native, native_currency,
            fx_rate_snapshot, amount_eur, created_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("DEPOSIT", 1, 1, "1000.00", "EUR", "1.00", "1000.00", "test"),
            ("DEPOSIT", 1, 1, "500.00", "EUR", "1.00", "500.00", "test"),
        ],
    )
    test_db.commit()

    balances = service.get_associate_balances()
    alice = next(b for b in balances if b.associate_alias == "Alice")

    assert alice.net_deposits_eur == Decimal("1500.00")


def test_calculate_net_deposits_eur_with_withdrawals(test_db, service):
    """
    Test NET_DEPOSITS calculation with deposits and withdrawals.

    Given: Associate with DEPOSIT and WITHDRAWAL entries
    When: Balances calculated
    Then: NET_DEPOSITS = deposits - withdrawals
    """
    seed_associates(test_db)
    seed_bookmakers(test_db)

    # Bob deposits €2000, withdraws €500
    test_db.executemany(
        """
        INSERT INTO ledger_entries (
            type, associate_id, bookmaker_id, amount_native, native_currency,
            fx_rate_snapshot, amount_eur, created_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("DEPOSIT", 2, 1, "2000.00", "EUR", "1.00", "2000.00", "test"),
            ("WITHDRAWAL", 2, 1, "-500.00", "EUR", "1.00", "-500.00", "test"),
        ],
    )
    test_db.commit()

    balances = service.get_associate_balances()
    bob = next(b for b in balances if b.associate_alias == "Bob")

    assert bob.net_deposits_eur == Decimal("1500.00")


# ========================================
# Test SHOULD_HOLD_EUR Calculation
# ========================================


def test_calculate_should_hold_eur_from_bet_results(test_db, service):
    """
    Test SHOULD_HOLD calculation from BET_RESULT entries.

    Given: Associate with BET_RESULT entries
    When: Balances calculated
    Then: SHOULD_HOLD = sum(principal_returned + per_surebet_share)
    """
    seed_associates(test_db)
    seed_bookmakers(test_db)

    # Create surebet context
    create_test_surebet_context(test_db, bet_id=1, associate_id=1)

    # Alice: principal returned €100, share €50
    test_db.execute(
        """
        INSERT INTO ledger_entries (
            type, associate_id, bookmaker_id, amount_native, native_currency,
            fx_rate_snapshot, amount_eur, settlement_state, principal_returned_eur,
            per_surebet_share_eur, surebet_id, bet_id, settlement_batch_id, created_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "BET_RESULT", 1, 1, "150.00", "EUR", "1.00", "150.00", "WON",
            "100.00", "50.00", 1, 1, "batch-1", "test"
        ),
    )
    test_db.commit()

    balances = service.get_associate_balances()
    alice = next(b for b in balances if b.associate_alias == "Alice")

    assert alice.should_hold_eur == Decimal("150.00")


# ========================================
# Test CURRENT_HOLDING_EUR Calculation
# ========================================


def test_calculate_current_holding_eur_all_entry_types(test_db, service):
    """
    Test CURRENT_HOLDING calculation from all ledger entry types.

    Given: Associate with BET_RESULT, DEPOSIT, WITHDRAWAL, BOOKMAKER_CORRECTION entries
    When: Balances calculated
    Then: CURRENT_HOLDING = sum of all amount_eur values
    """
    seed_associates(test_db)
    seed_bookmakers(test_db)

    # Setup for BET_RESULT
    create_test_surebet_context(test_db, bet_id=1, associate_id=1)

    # Charlie: various entry types
    test_db.executemany(
        """
        INSERT INTO ledger_entries (
            type, associate_id, bookmaker_id, amount_native, native_currency,
            fx_rate_snapshot, amount_eur, settlement_state, principal_returned_eur,
            per_surebet_share_eur, surebet_id, bet_id, settlement_batch_id, created_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            # BET_RESULT: +€150
            ("BET_RESULT", 3, 1, "150.00", "EUR", "1.00", "150.00", "WON",
             "100.00", "50.00", 1, 1, "batch-1", "test"),
            # DEPOSIT: +€1000
            ("DEPOSIT", 3, 1, "1000.00", "EUR", "1.00", "1000.00", None,
             None, None, None, None, None, "test"),
            # WITHDRAWAL: -€200
            ("WITHDRAWAL", 3, 1, "-200.00", "EUR", "1.00", "-200.00", None,
             None, None, None, None, None, "test"),
            # BOOKMAKER_CORRECTION: +€50
            ("BOOKMAKER_CORRECTION", 3, 1, "50.00", "EUR", "1.00", "50.00", None,
             None, None, None, None, None, "test"),
        ],
    )
    test_db.commit()

    balances = service.get_associate_balances()
    charlie = next(b for b in balances if b.associate_alias == "Charlie")

    # Total: 150 + 1000 - 200 + 50 = 1000
    assert charlie.current_holding_eur == Decimal("1000.00")


# ========================================
# Test DELTA Calculation and Status
# ========================================


def test_calculate_delta_overholder(test_db, service):
    """
    Test DELTA calculation for overholder scenario.

    Given: Associate with CURRENT_HOLDING > SHOULD_HOLD by more than €10
    When: Balances calculated
    Then: DELTA > 0, status = "overholder", icon = 🔴
    """
    seed_associates(test_db)
    seed_bookmakers(test_db)

    # Setup for BET_RESULT
    create_test_surebet_context(test_db, bet_id=1, associate_id=1)

    # Alice: SHOULD_HOLD = €1600, CURRENT_HOLDING = €2400, DELTA = +€800
    test_db.executemany(
        """
        INSERT INTO ledger_entries (
            type, associate_id, bookmaker_id, amount_native, native_currency,
            fx_rate_snapshot, amount_eur, settlement_state, principal_returned_eur,
            per_surebet_share_eur, surebet_id, bet_id, settlement_batch_id, created_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            # BET_RESULT: principal €1500 + share €100 = €1600 should_hold
            ("BET_RESULT", 1, 1, "1600.00", "EUR", "1.00", "1600.00", "WON",
             "1500.00", "100.00", 1, 1, "batch-1", "test"),
            # DEPOSIT: +€800 extra
            ("DEPOSIT", 1, 1, "800.00", "EUR", "1.00", "800.00", None,
             None, None, None, None, None, "test"),
        ],
    )
    test_db.commit()

    balances = service.get_associate_balances()
    alice = next(b for b in balances if b.associate_alias == "Alice")

    assert alice.should_hold_eur == Decimal("1600.00")
    assert alice.current_holding_eur == Decimal("2400.00")
    assert alice.delta_eur == Decimal("800.00")
    assert alice.status == "overholder"
    assert alice.status_icon == "🔴"


def test_calculate_delta_short(test_db, service):
    """
    Test DELTA calculation for short scenario.

    Given: Associate with CURRENT_HOLDING < SHOULD_HOLD by more than €10
    When: Balances calculated
    Then: DELTA < 0, status = "short", icon = 🟠
    """
    seed_associates(test_db)
    seed_bookmakers(test_db)

    # Setup for BET_RESULT
    create_test_surebet_context(test_db, bet_id=1, associate_id=2)

    # Bob: SHOULD_HOLD = €700, CURRENT_HOLDING = €400, DELTA = -€300
    test_db.executemany(
        """
        INSERT INTO ledger_entries (
            type, associate_id, bookmaker_id, amount_native, native_currency,
            fx_rate_snapshot, amount_eur, settlement_state, principal_returned_eur,
            per_surebet_share_eur, surebet_id, bet_id, settlement_batch_id, created_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            # BET_RESULT: principal €600 + share €100 = €700 should_hold
            ("BET_RESULT", 2, 1, "700.00", "EUR", "1.00", "700.00", "WON",
             "600.00", "100.00", 1, 1, "batch-1", "test"),
            # WITHDRAWAL: -€300 (short)
            ("WITHDRAWAL", 2, 1, "-300.00", "EUR", "1.00", "-300.00", None,
             None, None, None, None, None, "test"),
        ],
    )
    test_db.commit()

    balances = service.get_associate_balances()
    bob = next(b for b in balances if b.associate_alias == "Bob")

    assert bob.should_hold_eur == Decimal("700.00")
    assert bob.current_holding_eur == Decimal("400.00")
    assert bob.delta_eur == Decimal("-300.00")
    assert bob.status == "short"
    assert bob.status_icon == "🟠"


def test_calculate_delta_balanced(test_db, service):
    """
    Test DELTA calculation for balanced scenario.

    Given: Associate with |CURRENT_HOLDING - SHOULD_HOLD| <= €10
    When: Balances calculated
    Then: DELTA ≈ 0, status = "balanced", icon = 🟢
    """
    seed_associates(test_db)
    seed_bookmakers(test_db)

    # Setup for BET_RESULT
    create_test_surebet_context(test_db, bet_id=1, associate_id=4)

    # Admin: SHOULD_HOLD = €2100, CURRENT_HOLDING = €2095, DELTA = -€5
    test_db.executemany(
        """
        INSERT INTO ledger_entries (
            type, associate_id, bookmaker_id, amount_native, native_currency,
            fx_rate_snapshot, amount_eur, settlement_state, principal_returned_eur,
            per_surebet_share_eur, surebet_id, bet_id, settlement_batch_id, created_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            # BET_RESULT: principal €2000 + share €100 = €2100 should_hold
            ("BET_RESULT", 4, 1, "2100.00", "EUR", "1.00", "2100.00", "WON",
             "2000.00", "100.00", 1, 1, "batch-1", "test"),
            # WITHDRAWAL: -€5 (minor difference)
            ("WITHDRAWAL", 4, 1, "-5.00", "EUR", "1.00", "-5.00", None,
             None, None, None, None, None, "test"),
        ],
    )
    test_db.commit()

    balances = service.get_associate_balances()
    admin = next(b for b in balances if b.associate_alias == "Admin")

    assert admin.should_hold_eur == Decimal("2100.00")
    assert admin.current_holding_eur == Decimal("2095.00")
    assert admin.delta_eur == Decimal("-5.00")
    assert admin.status == "balanced"
    assert admin.status_icon == "🟢"


# ========================================
# Test Status Threshold Boundaries
# ========================================


def test_status_determination_thresholds(service):
    """
    Test status determination at threshold boundaries.

    Given: Various DELTA values at boundaries
    When: Status determined
    Then: Correct status and icon assigned
    """
    # Exactly +€10 (boundary for overholder)
    status, icon = service._determine_status(Decimal("10.00"))
    assert status == "balanced"
    assert icon == "🟢"

    # Just over +€10 (overholder)
    status, icon = service._determine_status(Decimal("10.01"))
    assert status == "overholder"
    assert icon == "🔴"

    # Exactly -€10 (boundary for short)
    status, icon = service._determine_status(Decimal("-10.00"))
    assert status == "balanced"
    assert icon == "🟢"

    # Just under -€10 (short)
    status, icon = service._determine_status(Decimal("-10.01"))
    assert status == "short"
    assert icon == "🟠"

    # Exactly zero
    status, icon = service._determine_status(Decimal("0.00"))
    assert status == "balanced"
    assert icon == "🟢"


# ========================================
# Test Human-Readable Explanations
# ========================================


def test_human_readable_explanation_overholder(service):
    """
    Test explanation generation for overholder status.

    Given: Overholder associate balance
    When: Explanation generated
    Then: Contains correct amounts and collection message
    """
    balance = AssociateBalance(
        associate_id=1,
        associate_alias="Alice",
        net_deposits_eur=Decimal("1000.00"),
        should_hold_eur=Decimal("1200.00"),
        current_holding_eur=Decimal("2000.00"),
        delta_eur=Decimal("800.00"),
        status="overholder",
        status_icon="🔴",
    )

    explanation = service.get_explanation(balance)

    assert "Alice" in explanation
    assert "€800.00" in explanation
    assert "€1,000.00" in explanation  # net_deposits formatted
    assert "€1,200.00" in explanation  # should_hold formatted
    assert "€2,000.00" in explanation  # current_holding formatted
    assert "Collect €800.00 from them" in explanation


def test_human_readable_explanation_short(service):
    """
    Test explanation generation for short status.

    Given: Short associate balance
    When: Explanation generated
    Then: Contains correct amounts and shortage message
    """
    balance = AssociateBalance(
        associate_id=2,
        associate_alias="Bob",
        net_deposits_eur=Decimal("500.00"),
        should_hold_eur=Decimal("700.00"),
        current_holding_eur=Decimal("400.00"),
        delta_eur=Decimal("-300.00"),
        status="short",
        status_icon="🟠",
    )

    explanation = service.get_explanation(balance)

    assert "Bob" in explanation
    assert "short €300.00" in explanation
    assert "€500.00" in explanation
    assert "€700.00" in explanation
    assert "€400.00" in explanation
    assert "Someone else is holding their €300.00" in explanation


def test_human_readable_explanation_balanced(service):
    """
    Test explanation generation for balanced status.

    Given: Balanced associate balance
    When: Explanation generated
    Then: Contains correct amounts and balanced message
    """
    balance = AssociateBalance(
        associate_id=4,
        associate_alias="Admin",
        net_deposits_eur=Decimal("2000.00"),
        should_hold_eur=Decimal("2100.00"),
        current_holding_eur=Decimal("2095.00"),
        delta_eur=Decimal("-5.00"),
        status="balanced",
        status_icon="🟢",
    )

    explanation = service.get_explanation(balance)

    assert "Admin" in explanation
    assert "balanced" in explanation
    assert "€2,000.00" in explanation
    assert "€2,100.00" in explanation
    assert "€2,095.00" in explanation


# ========================================
# Test Edge Cases
# ========================================


def test_associate_with_no_entries(test_db, service):
    """
    Test associate with no ledger entries.

    Given: Associate exists but has no ledger entries
    When: Balances calculated
    Then: All values are €0.00, status is balanced
    """
    seed_associates(test_db)
    seed_bookmakers(test_db)

    balances = service.get_associate_balances()
    alice = next(b for b in balances if b.associate_alias == "Alice")

    assert alice.net_deposits_eur == Decimal("0.00")
    assert alice.should_hold_eur == Decimal("0.00")
    assert alice.current_holding_eur == Decimal("0.00")
    assert alice.delta_eur == Decimal("0.00")
    assert alice.status == "balanced"


def test_all_associates_included(test_db, service):
    """
    Test that all seeded associates are included in results.

    Given: Multiple associates seeded
    When: Balances calculated
    Then: All associates appear in results
    """
    seed_associates(test_db)

    balances = service.get_associate_balances()
    aliases = [b.associate_alias for b in balances]

    assert "Alice" in aliases
    assert "Bob" in aliases
    assert "Charlie" in aliases
    assert "Admin" in aliases
    assert len(balances) == 4


def test_decimal_precision_handling(test_db, service):
    """
    Test proper Decimal arithmetic and rounding.

    Given: Entries with various decimal places
    When: Balances calculated
    Then: All values rounded to 2 decimal places
    """
    seed_associates(test_db)
    seed_bookmakers(test_db)

    # Setup for BET_RESULT
    create_test_surebet_context(test_db, bet_id=1, associate_id=1)

    # Values that need rounding
    test_db.execute(
        """
        INSERT INTO ledger_entries (
            type, associate_id, bookmaker_id, amount_native, native_currency,
            fx_rate_snapshot, amount_eur, settlement_state, principal_returned_eur,
            per_surebet_share_eur, surebet_id, bet_id, settlement_batch_id, created_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "BET_RESULT", 1, 1, "33.333", "EUR", "1.00", "33.333", "WON",
            "33.331", "0.002", 1, 1, "batch-1", "test"
        ),
    )
    test_db.commit()

    balances = service.get_associate_balances()
    alice = next(b for b in balances if b.associate_alias == "Alice")

    # Check that all values are rounded to 2 decimal places
    assert alice.current_holding_eur == Decimal("33.33")
    assert alice.should_hold_eur == Decimal("33.33")
    assert alice.delta_eur == Decimal("0.00")


# ========================================
# Test Sorting
# ========================================


def test_balances_sorted_by_delta_descending(test_db, service):
    """
    Test that balances are sorted by DELTA (largest overholder first).

    Given: Multiple associates with different DELTAs
    When: Balances calculated
    Then: Results sorted by DELTA descending
    """
    seed_associates(test_db)
    seed_bookmakers(test_db)

    # Setup for BET_RESULT
    create_test_surebet_context(test_db, bet_id=1, associate_id=1)
    create_test_surebet_context(test_db, bet_id=2, associate_id=2)
    create_test_surebet_context(test_db, bet_id=3, associate_id=3)

    # Alice: DELTA = +€800 (overholder)
    # Bob: DELTA = -€300 (short)
    # Charlie: DELTA = +€100 (overholder)
    test_db.executemany(
        """
        INSERT INTO ledger_entries (
            type, associate_id, bookmaker_id, amount_native, native_currency,
            fx_rate_snapshot, amount_eur, settlement_state, principal_returned_eur,
            per_surebet_share_eur, surebet_id, bet_id, settlement_batch_id, created_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            # Alice: should €1000, current €1800, delta +€800
            ("BET_RESULT", 1, 1, "1000.00", "EUR", "1.00", "1000.00", "WON",
             "1000.00", "0.00", 1, 1, "batch-1", "test"),
            ("DEPOSIT", 1, 1, "800.00", "EUR", "1.00", "800.00", None,
             None, None, None, None, None, "test"),

            # Bob: should €700, current €400, delta -€300
            ("BET_RESULT", 2, 1, "700.00", "EUR", "1.00", "700.00", "WON",
             "700.00", "0.00", 1, 2, "batch-1", "test"),
            ("WITHDRAWAL", 2, 1, "-300.00", "EUR", "1.00", "-300.00", None,
             None, None, None, None, None, "test"),

            # Charlie: should €500, current €600, delta +€100
            ("BET_RESULT", 3, 1, "500.00", "EUR", "1.00", "500.00", "WON",
             "500.00", "0.00", 1, 3, "batch-1", "test"),
            ("DEPOSIT", 3, 1, "100.00", "EUR", "1.00", "100.00", None,
             None, None, None, None, None, "test"),
        ],
    )
    test_db.commit()

    balances = service.get_associate_balances()

    # Should be sorted: Alice (+€800), Charlie (+€100), Admin (€0), Bob (-€300)
    assert balances[0].associate_alias == "Alice"
    assert balances[0].delta_eur == Decimal("800.00")

    assert balances[1].associate_alias == "Charlie"
    assert balances[1].delta_eur == Decimal("100.00")

    # Bob should be last (most negative delta)
    assert balances[-1].associate_alias == "Bob"
    assert balances[-1].delta_eur == Decimal("-300.00")


def test_inactive_associates_excluded(test_db, service):
    """
    Test that inactive associates are excluded from reconciliation results.

    Given: An associate marked inactive
    When: Balances calculated
    Then: Inactive associate should not appear in results
    """
    seed_associates(test_db)
    seed_bookmakers(test_db)

    # Mark Bob as inactive
    test_db.execute("UPDATE associates SET is_active = 0 WHERE id = 2")
    test_db.commit()

    balances = service.get_associate_balances()
    aliases = {b.associate_alias for b in balances}

    assert "Bob" not in aliases
    assert "Alice" in aliases
