"""
Integration tests for the complete reconciliation workflow.

Tests Story 5.2 end-to-end: associate balances calculation across multiple
ledger entry types, interactions with settlement and correction services.
"""

import pytest
import sqlite3
from decimal import Decimal
from pathlib import Path
import tempfile

from src.services.reconciliation_service import ReconciliationService
from src.services.ledger_entry_service import LedgerEntryService
from src.services.settlement_service import SettlementService, BetOutcome
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


def seed_test_data(db: sqlite3.Connection):
    """Seed comprehensive test data for reconciliation flow."""
    # Associates
    db.executemany(
        """
        INSERT INTO associates (id, display_alias)
        VALUES (?, ?)
        """,
        [
            (1, "Alice"),
            (2, "Bob"),
            (3, "Charlie"),
        ],
    )

    # Bookmakers
    db.executemany(
        """
        INSERT INTO bookmakers (id, associate_id, bookmaker_name)
        VALUES (?, ?, ?)
        """,
        [
            (1, 1, "Bet365"),
            (2, 2, "Betfair"),
        ],
    )

    # Events
    db.execute(
        """
        INSERT INTO canonical_events (id, normalized_event_name, kickoff_time_utc, sport)
        VALUES (1, 'Man Utd vs Liverpool', '2025-01-15T15:00:00Z', 'soccer')
        """
    )

    # Bets for surebet
    db.executemany(
        """
        INSERT INTO bets (
            id, associate_id, bookmaker_id, event_id, market_type, selection,
            odds, stake_amount, stake_currency, status, confidence_score
        )
        VALUES (?, ?, ?, 1, 'match_winner', ?, ?, ?, 'EUR', 'verified', 1.0)
        """,
        [
            (1, 1, 1, "home", "2.10", "500.00"),
            (2, 2, 2, "away", "2.15", "480.00"),
        ],
    )

    # Surebets
    db.execute(
        """
        INSERT INTO surebets (id, status)
        VALUES (1, 'open')
        """
    )

    # Link bets to surebet
    db.executemany(
        """
        INSERT INTO surebet_bets (surebet_id, bet_id)
        VALUES (1, ?)
        """,
        [(1,), (2,)],
    )

    db.commit()


# ========================================
# Integration Test: Complete Reconciliation Flow
# ========================================


def test_reconciliation_flow_with_deposits_and_settlements(test_db):
    """
    Test complete reconciliation flow: deposits → settlements → balance calculations.

    Given: Associates make deposits and settle bets
    When: Reconciliation calculated
    Then: Balances accurately reflect all transactions
    """
    seed_test_data(test_db)

    # Step 1: Associates make deposits
    test_db.executemany(
        """
        INSERT INTO ledger_entries (
            type, associate_id, bookmaker_id, amount_native, native_currency,
            fx_rate_snapshot, amount_eur, created_by, note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'test', ?)
        """,
        [
            ("DEPOSIT", 1, 1, "1000.00", "EUR", "1.00", "1000.00", "Alice initial deposit"),
            ("DEPOSIT", 2, 2, "2000.00", "EUR", "1.00", "2000.00", "Bob initial deposit"),
            ("DEPOSIT", 3, 1, "1500.00", "EUR", "1.00", "1500.00", "Charlie initial deposit"),
        ],
    )
    test_db.commit()

    # Step 2: Verify initial balances (only deposits)
    service = ReconciliationService(db=test_db)
    balances = service.get_associate_balances()

    alice = next(b for b in balances if b.associate_alias == "Alice")
    bob = next(b for b in balances if b.associate_alias == "Bob")
    charlie = next(b for b in balances if b.associate_alias == "Charlie")

    # Before settlements: CURRENT_HOLDING = NET_DEPOSITS, SHOULD_HOLD = 0
    assert alice.net_deposits_eur == Decimal("1000.00")
    assert alice.should_hold_eur == Decimal("0.00")
    assert alice.current_holding_eur == Decimal("1000.00")
    assert alice.delta_eur == Decimal("1000.00")
    assert alice.status == "overholder"

    # Step 3: Settle the surebet (Alice WON, Bob LOST)
    # Simulate settlement by adding BET_RESULT entries
    test_db.executemany(
        """
        INSERT INTO ledger_entries (
            type, associate_id, bookmaker_id, amount_native, native_currency,
            fx_rate_snapshot, amount_eur, settlement_state, principal_returned_eur,
            per_surebet_share_eur, surebet_id, bet_id, settlement_batch_id, created_by, note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'test', ?)
        """,
        [
            # Alice WON: stake returned €500, payout €1050, net gain €550, share €275
            ("BET_RESULT", 1, 1, "550.00", "EUR", "1.00", "550.00", "WON",
             "500.00", "275.00", 1, 1, "batch-1", "Alice won bet"),
            # Bob LOST: lost €480, share €275
            ("BET_RESULT", 2, 2, "-480.00", "EUR", "1.00", "-480.00", "LOST",
             "0.00", "275.00", 1, 2, "batch-1", "Bob lost bet"),
        ],
    )

    # Update surebet status
    test_db.execute("UPDATE surebets SET status = 'settled' WHERE id = 1")
    test_db.commit()

    # Step 4: Calculate post-settlement balances
    balances = service.get_associate_balances()

    alice = next(b for b in balances if b.associate_alias == "Alice")
    bob = next(b for b in balances if b.associate_alias == "Bob")

    # Alice: NET_DEPOSITS €1000, SHOULD_HOLD €775 (€500 + €275), CURRENT_HOLDING €1550 (€1000 + €550)
    assert alice.net_deposits_eur == Decimal("1000.00")
    assert alice.should_hold_eur == Decimal("775.00")
    assert alice.current_holding_eur == Decimal("1550.00")
    assert alice.delta_eur == Decimal("775.00")
    assert alice.status == "overholder"

    # Bob: NET_DEPOSITS €2000, SHOULD_HOLD €275 (€0 + €275), CURRENT_HOLDING €1520 (€2000 - €480)
    assert bob.net_deposits_eur == Decimal("2000.00")
    assert bob.should_hold_eur == Decimal("275.00")
    assert bob.current_holding_eur == Decimal("1520.00")
    assert bob.delta_eur == Decimal("1245.00")
    assert bob.status == "overholder"

    # Charlie: no bets yet
    charlie = next(b for b in balances if b.associate_alias == "Charlie")
    assert charlie.net_deposits_eur == Decimal("1500.00")
    assert charlie.should_hold_eur == Decimal("0.00")
    assert charlie.current_holding_eur == Decimal("1500.00")

    service.close()


def test_reconciliation_flow_with_withdrawals(test_db):
    """
    Test reconciliation with withdrawals affecting CURRENT_HOLDING.

    Given: Associates make deposits, settle bets, then make withdrawals
    When: Reconciliation calculated
    Then: CURRENT_HOLDING reflects withdrawals
    """
    seed_test_data(test_db)

    # Deposits
    test_db.executemany(
        """
        INSERT INTO ledger_entries (
            type, associate_id, bookmaker_id, amount_native, native_currency,
            fx_rate_snapshot, amount_eur, created_by, note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'test', ?)
        """,
        [
            ("DEPOSIT", 1, 1, "1000.00", "EUR", "1.00", "1000.00", "Alice deposit"),
            ("DEPOSIT", 2, 2, "2000.00", "EUR", "1.00", "2000.00", "Bob deposit"),
        ],
    )

    # Settlements
    test_db.executemany(
        """
        INSERT INTO ledger_entries (
            type, associate_id, bookmaker_id, amount_native, native_currency,
            fx_rate_snapshot, amount_eur, settlement_state, principal_returned_eur,
            per_surebet_share_eur, surebet_id, bet_id, settlement_batch_id, created_by, note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'test', ?)
        """,
        [
            ("BET_RESULT", 1, 1, "550.00", "EUR", "1.00", "550.00", "WON",
             "500.00", "275.00", 1, 1, "batch-1", "Alice settlement"),
            ("BET_RESULT", 2, 2, "-480.00", "EUR", "1.00", "-480.00", "LOST",
             "0.00", "275.00", 1, 2, "batch-1", "Bob settlement"),
        ],
    )

    # Alice withdraws €1000
    test_db.execute(
        """
        INSERT INTO ledger_entries (
            type, associate_id, bookmaker_id, amount_native, native_currency,
            fx_rate_snapshot, amount_eur, created_by, note
        ) VALUES ('WITHDRAWAL', 1, 1, '-1000.00', 'EUR', '1.00', '-1000.00', 'test', 'Alice withdrawal')
        """
    )
    test_db.commit()

    # Calculate balances
    service = ReconciliationService(db=test_db)
    balances = service.get_associate_balances()

    alice = next(b for b in balances if b.associate_alias == "Alice")

    # Alice: NET_DEPOSITS €0 (€1000 - €1000), SHOULD_HOLD €775, CURRENT_HOLDING €550 (€1000 + €550 - €1000)
    assert alice.net_deposits_eur == Decimal("0.00")
    assert alice.should_hold_eur == Decimal("775.00")
    assert alice.current_holding_eur == Decimal("550.00")
    assert alice.delta_eur == Decimal("-225.00")
    assert alice.status == "short"

    service.close()


def test_reconciliation_flow_with_bookmaker_corrections(test_db):
    """
    Test reconciliation with BOOKMAKER_CORRECTION entries.

    Given: Associates have deposits and settlements, then corrections are applied
    When: Reconciliation calculated
    Then: CURRENT_HOLDING includes correction amounts
    """
    seed_test_data(test_db)

    # Deposits
    test_db.execute(
        """
        INSERT INTO ledger_entries (
            type, associate_id, bookmaker_id, amount_native, native_currency,
            fx_rate_snapshot, amount_eur, created_by, note
        ) VALUES ('DEPOSIT', 1, 1, '1000.00', 'EUR', '1.00', '1000.00', 'test', 'Alice deposit')
        """
    )

    # Settlement
    test_db.execute(
        """
        INSERT INTO ledger_entries (
            type, associate_id, bookmaker_id, amount_native, native_currency,
            fx_rate_snapshot, amount_eur, settlement_state, principal_returned_eur,
            per_surebet_share_eur, surebet_id, bet_id, settlement_batch_id, created_by, note
        ) VALUES ('BET_RESULT', 1, 1, '550.00', 'EUR', '1.00', '550.00', 'WON',
                  '500.00', '275.00', 1, 1, 'batch-1', 'test', 'Alice settlement')
        """
    )

    # Bookmaker correction: Alice's bookmaker account was credited €200 due to promotion
    test_db.execute(
        """
        INSERT INTO ledger_entries (
            type, associate_id, bookmaker_id, amount_native, native_currency,
            fx_rate_snapshot, amount_eur, created_by, note
        ) VALUES ('BOOKMAKER_CORRECTION', 1, 1, '200.00', 'EUR', '1.00', '200.00', 'test', 'Bonus credited')
        """
    )
    test_db.commit()

    # Calculate balances
    service = ReconciliationService(db=test_db)
    balances = service.get_associate_balances()

    alice = next(b for b in balances if b.associate_alias == "Alice")

    # Alice: SHOULD_HOLD €775, CURRENT_HOLDING €1750 (€1000 + €550 + €200)
    assert alice.should_hold_eur == Decimal("775.00")
    assert alice.current_holding_eur == Decimal("1750.00")
    assert alice.delta_eur == Decimal("975.00")
    assert alice.status == "overholder"

    service.close()


def test_reconciliation_multi_currency_scenario(test_db):
    """
    Test reconciliation with multiple currencies using FX snapshots.

    Given: Associates have entries in different currencies with FX conversions
    When: Reconciliation calculated
    Then: All amounts correctly converted to EUR
    """
    seed_test_data(test_db)

    # Alice deposits in EUR
    test_db.execute(
        """
        INSERT INTO ledger_entries (
            type, associate_id, bookmaker_id, amount_native, native_currency,
            fx_rate_snapshot, amount_eur, created_by, note
        ) VALUES ('DEPOSIT', 1, 1, '1000.00', 'EUR', '1.00', '1000.00', 'test', 'EUR deposit')
        """
    )

    # Bob deposits in GBP (rate: 1 GBP = 1.15 EUR)
    test_db.execute(
        """
        INSERT INTO ledger_entries (
            type, associate_id, bookmaker_id, amount_native, native_currency,
            fx_rate_snapshot, amount_eur, created_by, note
        ) VALUES ('DEPOSIT', 2, 2, '1000.00', 'GBP', '1.15', '1150.00', 'test', 'GBP deposit')
        """
    )

    # Bob settlement in GBP
    test_db.execute(
        """
        INSERT INTO ledger_entries (
            type, associate_id, bookmaker_id, amount_native, native_currency,
            fx_rate_snapshot, amount_eur, settlement_state, principal_returned_eur,
            per_surebet_share_eur, surebet_id, bet_id, settlement_batch_id, created_by, note
        ) VALUES ('BET_RESULT', 2, 2, '-480.00', 'GBP', '1.15', '-552.00', 'LOST',
                  '0.00', '275.00', 1, 2, 'batch-1', 'test', 'GBP settlement')
        """
    )
    test_db.commit()

    # Calculate balances
    service = ReconciliationService(db=test_db)
    balances = service.get_associate_balances()

    bob = next(b for b in balances if b.associate_alias == "Bob")

    # Bob: NET_DEPOSITS €1150, SHOULD_HOLD €275, CURRENT_HOLDING €598 (€1150 - €552)
    assert bob.net_deposits_eur == Decimal("1150.00")
    assert bob.should_hold_eur == Decimal("275.00")
    assert bob.current_holding_eur == Decimal("598.00")
    assert bob.delta_eur == Decimal("323.00")
    assert bob.status == "overholder"

    service.close()


def test_reconciliation_with_void_bets(test_db):
    """
    Test reconciliation when bets are voided.

    Given: Associate has a VOID bet result
    When: Reconciliation calculated
    Then: SHOULD_HOLD includes principal returned but no profit/loss
    """
    seed_test_data(test_db)

    # Deposit
    test_db.execute(
        """
        INSERT INTO ledger_entries (
            type, associate_id, bookmaker_id, amount_native, native_currency,
            fx_rate_snapshot, amount_eur, created_by, note
        ) VALUES ('DEPOSIT', 1, 1, '1000.00', 'EUR', '1.00', '1000.00', 'test', 'Alice deposit')
        """
    )

    # Void bet: stake returned, no profit/loss, but gets share
    test_db.execute(
        """
        INSERT INTO ledger_entries (
            type, associate_id, bookmaker_id, amount_native, native_currency,
            fx_rate_snapshot, amount_eur, settlement_state, principal_returned_eur,
            per_surebet_share_eur, surebet_id, bet_id, settlement_batch_id, created_by, note
        ) VALUES ('BET_RESULT', 1, 1, '50.00', 'EUR', '1.00', '50.00', 'VOID',
                  '500.00', '50.00', 1, 1, 'batch-1', 'test', 'Void bet')
        """
    )
    test_db.commit()

    # Calculate balances
    service = ReconciliationService(db=test_db)
    balances = service.get_associate_balances()

    alice = next(b for b in balances if b.associate_alias == "Alice")

    # Alice: SHOULD_HOLD €550 (€500 principal + €50 share), CURRENT_HOLDING €1050
    assert alice.should_hold_eur == Decimal("550.00")
    assert alice.current_holding_eur == Decimal("1050.00")
    assert alice.delta_eur == Decimal("500.00")
    assert alice.status == "overholder"

    service.close()


def test_reconciliation_zero_sum_verification(test_db):
    """
    Test that total system DELTA sums to zero (closed system verification).

    Given: Multiple associates with various transactions
    When: Reconciliation calculated
    Then: Sum of all DELTAs should be close to zero (accounting for rounding)
    """
    seed_test_data(test_db)

    # Multiple transactions
    test_db.executemany(
        """
        INSERT INTO ledger_entries (
            type, associate_id, bookmaker_id, amount_native, native_currency,
            fx_rate_snapshot, amount_eur, created_by, note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'test', ?)
        """,
        [
            ("DEPOSIT", 1, 1, "1000.00", "EUR", "1.00", "1000.00", "Alice deposit"),
            ("DEPOSIT", 2, 2, "2000.00", "EUR", "1.00", "2000.00", "Bob deposit"),
            ("DEPOSIT", 3, 1, "1500.00", "EUR", "1.00", "1500.00", "Charlie deposit"),
        ],
    )

    # Settlements that redistribute funds
    test_db.executemany(
        """
        INSERT INTO ledger_entries (
            type, associate_id, bookmaker_id, amount_native, native_currency,
            fx_rate_snapshot, amount_eur, settlement_state, principal_returned_eur,
            per_surebet_share_eur, surebet_id, bet_id, settlement_batch_id, created_by, note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'test', ?)
        """,
        [
            ("BET_RESULT", 1, 1, "550.00", "EUR", "1.00", "550.00", "WON",
             "500.00", "275.00", 1, 1, "batch-1", "Alice settlement"),
            ("BET_RESULT", 2, 2, "-480.00", "EUR", "1.00", "-480.00", "LOST",
             "0.00", "275.00", 1, 2, "batch-1", "Bob settlement"),
            ("BET_RESULT", 3, 1, "0.00", "EUR", "1.00", "0.00", "WON",
             "0.00", "-550.00", 1, 3, "batch-1", "Charlie admin seat"),
        ],
    )
    test_db.commit()

    # Calculate balances
    service = ReconciliationService(db=test_db)
    balances = service.get_associate_balances()

    # Sum all DELTAs
    total_delta = sum(b.delta_eur for b in balances)

    # In a closed system with no external flows, total DELTA should be ≈ 0
    # Allow small rounding tolerance
    assert abs(total_delta) < Decimal("0.10")

    service.close()
