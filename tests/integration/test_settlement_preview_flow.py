"""
Integration tests for settlement preview flow (Story 4.3).

Tests the complete flow from database to preview generation, including:
- Real database queries
- FX rate integration
- Multi-currency calculations
- End-to-end preview workflow
"""

import sqlite3
import pytest
from decimal import Decimal
from src.services.settlement_service import SettlementService, BetOutcome


@pytest.fixture
def test_db():
    """Create a test database with sample data."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row

    cursor = db.cursor()

    # Create minimal schema needed for settlement preview
    cursor.execute(
        """
        CREATE TABLE associates (
            id INTEGER PRIMARY KEY,
            display_alias TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1
        )
    """
    )
    cursor.execute(
        """
        CREATE TABLE bookmakers (
            id INTEGER PRIMARY KEY,
            bookmaker_name TEXT NOT NULL
        )
    """
    )
    cursor.execute(
        """
        CREATE TABLE bets (
            id INTEGER PRIMARY KEY,
            surebet_id INTEGER,
            associate_id INTEGER,
            bookmaker_id INTEGER,
            stake_original TEXT,
            stake_eur TEXT,
            odds TEXT NOT NULL,
            currency TEXT NOT NULL,
            odds_original TEXT
        )
    """
    )
    cursor.execute(
        """
        CREATE TABLE surebet_bets (
            surebet_id INTEGER NOT NULL,
            bet_id INTEGER NOT NULL,
            side TEXT NOT NULL,
            PRIMARY KEY (surebet_id, bet_id)
        )
    """
    )
    cursor.execute(
        """
        CREATE TABLE fx_rates_daily (
            currency_code TEXT NOT NULL,
            rate_to_eur TEXT NOT NULL,
            date TEXT NOT NULL,
            fetched_at_utc TEXT,
            created_at_utc TEXT
        )
    """
    )

    # Seed base lookup data
    cursor.execute(
        "INSERT INTO associates (id, display_alias) VALUES (1, 'Alice'), (2, 'Bob')"
    )
    cursor.execute(
        "INSERT INTO bookmakers (id, bookmaker_name) VALUES (1, 'BetFair'), (2, 'Pinnacle')"
    )

    cursor.execute(
        """
        INSERT INTO fx_rates_daily (currency_code, rate_to_eur, date)
        VALUES
            ('EUR', '1.0', '2025-11-03'),
            ('USD', '0.85', '2025-11-03'),
            ('AUD', '0.60', '2025-11-03')
    """
    )

    db.commit()
    try:
        yield db
    finally:
        db.close()


def test_settlement_preview_eur_only(test_db):
    """
    Test settlement preview with EUR-only bets.

    Given: Two bets in EUR (Side A WON, Side B LOST)
    When: Generate settlement preview
    Then: Correct profit calculation and ledger entries
    """
    cursor = test_db.cursor()

    # Insert bets
    cursor.execute(
        """
        INSERT INTO bets (id, surebet_id, associate_id, bookmaker_id, stake_original, stake_eur, odds, currency, odds_original)
        VALUES
            (1, 1, 1, 1, '100.00', '100.00', '0.00', 'EUR', '1.90'),
            (2, 1, 2, 2, '80.00', '80.00', '0.00', 'EUR', '2.10')
    """
    )
    cursor.execute(
        """
        INSERT INTO surebet_bets (surebet_id, bet_id, side)
        VALUES (1, 1, 'A'), (1, 2, 'B')
    """
    )
    test_db.commit()

    # Create service
    service = SettlementService(db=test_db)

    # Generate preview
    outcomes = {1: BetOutcome.WON, 2: BetOutcome.LOST}
    preview = service.preview_settlement(1, outcomes)

    # Verify calculations
    assert preview.surebet_profit_eur == Decimal("10.00")
    assert preview.num_participants == 2
    assert preview.per_surebet_share_eur == Decimal("5.00")
    assert preview.participants[0].odds == Decimal("1.90")
    assert preview.participants[1].odds == Decimal("2.10")

    # Verify ledger entries
    assert len(preview.ledger_entries) == 2
    assert preview.ledger_entries[0].total_amount_eur == Decimal("105.00")
    assert preview.ledger_entries[1].total_amount_eur == Decimal("5.00")


def test_settlement_preview_multi_currency(test_db):
    """
    Test settlement preview with multi-currency bets.

    Given: Bet 1 in EUR, Bet 2 in USD
    When: Generate settlement preview
    Then: FX conversion applied and warning generated
    """
    cursor = test_db.cursor()

    # Insert bets
    cursor.execute(
        """
        INSERT INTO bets (id, surebet_id, associate_id, bookmaker_id, stake_original, stake_eur, odds, currency, odds_original)
        VALUES
            (1, 2, 1, 1, '100.00', '100.00', '0.00', 'EUR', '1.90'),
            (2, 2, 2, 2, '94.12', '80.00', '0.00', 'USD', '2.10')
    """
    )
    cursor.execute(
        """
        INSERT INTO surebet_bets (surebet_id, bet_id, side)
        VALUES (2, 1, 'A'), (2, 2, 'B')
    """
    )
    test_db.commit()

    # Create service
    service = SettlementService(db=test_db)

    # Generate preview
    outcomes = {1: BetOutcome.WON, 2: BetOutcome.LOST}
    preview = service.preview_settlement(2, outcomes)

    # Verify multi-currency warning
    assert any("Multi-currency" in w for w in preview.warnings)

    # Verify FX rates stored
    assert preview.participants[0].fx_rate == Decimal("1.00")
    assert preview.participants[1].fx_rate == Decimal("0.85")

    # Verify EUR conversion: 94.12 USD × 0.85 = 80.00 EUR (rounded)
    assert preview.participants[1].stake_eur == Decimal("80.00")


def test_settlement_preview_all_void_scenario(test_db):
    """
    Test settlement preview with all bets VOID.

    Given: All bets marked as VOID
    When: Generate settlement preview
    Then: Zero profit, all participants get €0, warning generated
    """
    cursor = test_db.cursor()

    # Insert bets
    cursor.execute(
        """
        INSERT INTO bets (id, surebet_id, associate_id, bookmaker_id, stake_original, stake_eur, odds, currency, odds_original)
        VALUES
            (1, 3, 1, 1, '100.00', '100.00', '0.00', 'EUR', '1.90'),
            (2, 3, 2, 2, '80.00', '80.00', '0.00', 'EUR', '2.10')
    """
    )
    cursor.execute(
        """
        INSERT INTO surebet_bets (surebet_id, bet_id, side)
        VALUES (3, 1, 'A'), (3, 2, 'B')
    """
    )
    test_db.commit()

    # Create service
    service = SettlementService(db=test_db)

    # Generate preview
    outcomes = {1: BetOutcome.VOID, 2: BetOutcome.VOID}
    preview = service.preview_settlement(3, outcomes)

    # Verify all-VOID handling
    assert preview.surebet_profit_eur == Decimal("0.00")
    assert preview.per_surebet_share_eur == Decimal("0.00")
    assert any("All bets are VOID" in w for w in preview.warnings)

    # Verify all participants are non-staked
    for participant in preview.participants:
        assert participant.seat_type == "non-staked"

    # Verify all get €0
    for entry in preview.ledger_entries:
        assert entry.total_amount_eur == Decimal("0.00")


def test_settlement_preview_loss_scenario(test_db):
    """
    Test settlement preview with overall loss.

    Given: Surebet with negative profit
    When: Generate settlement preview
    Then: Negative per-share amount and loss warning
    """
    cursor = test_db.cursor()

    # Insert bets with high odds difference
    cursor.execute(
        """
        INSERT INTO bets (id, surebet_id, associate_id, bookmaker_id, stake_original, stake_eur, odds, currency, odds_original)
        VALUES
            (1, 4, 1, 1, '50.00', '50.00', '0.00', 'EUR', '1.50'),
            (2, 4, 2, 2, '100.00', '100.00', '0.00', 'EUR', '2.50')
    """
    )
    cursor.execute(
        """
        INSERT INTO surebet_bets (surebet_id, bet_id, side)
        VALUES (4, 1, 'A'), (4, 2, 'B')
    """
    )
    test_db.commit()

    # Create service
    service = SettlementService(db=test_db)

    # Generate preview (both lost)
    outcomes = {1: BetOutcome.LOST, 2: BetOutcome.LOST}
    preview = service.preview_settlement(4, outcomes)

    # Verify loss scenario
    assert preview.surebet_profit_eur < Decimal("0.00")
    assert preview.per_surebet_share_eur < Decimal("0.00")
    assert any("Loss scenario" in w for w in preview.warnings)


def test_settlement_preview_void_participant_mixed(test_db):
    """
    Test settlement preview with one VOID and one LOST.

    Given: Bet 1 VOID, Bet 2 LOST
    When: Generate settlement preview
    Then: Bet 1 gets non-staked seat (€0), Bet 2 gets staked seat with loss
    """
    cursor = test_db.cursor()

    # Insert bets
    cursor.execute(
        """
        INSERT INTO bets (id, surebet_id, associate_id, bookmaker_id, stake_original, stake_eur, odds, currency, odds_original)
        VALUES
            (1, 5, 1, 1, '100.00', '100.00', '0.00', 'EUR', '1.90'),
            (2, 5, 2, 2, '80.00', '80.00', '0.00', 'EUR', '2.10')
    """
    )
    cursor.execute(
        """
        INSERT INTO surebet_bets (surebet_id, bet_id, side)
        VALUES (5, 1, 'A'), (5, 2, 'B')
    """
    )
    test_db.commit()

    # Create service
    service = SettlementService(db=test_db)

    # Generate preview
    outcomes = {1: BetOutcome.VOID, 2: BetOutcome.LOST}
    preview = service.preview_settlement(5, outcomes)

    # Verify participant types
    assert preview.participants[0].seat_type == "non-staked"
    assert preview.participants[1].seat_type == "staked"

    # Verify Bet 1 (VOID) gets €0
    assert preview.ledger_entries[0].principal_returned_eur == Decimal("0.00")
    assert preview.ledger_entries[0].per_surebet_share_eur == Decimal("0.00")
    assert preview.ledger_entries[0].total_amount_eur == Decimal("0.00")

    # Verify Bet 2 (LOST) gets share of loss
    assert preview.ledger_entries[1].principal_returned_eur == Decimal("0.00")
    assert preview.ledger_entries[1].per_surebet_share_eur < Decimal("0.00")


def test_settlement_preview_three_way_bet(test_db):
    """
    Test settlement preview with three bets.

    Given: Three bets (WON, LOST, LOST)
    When: Generate settlement preview
    Then: Correct three-way split calculation
    """
    cursor = test_db.cursor()

    # Insert third associate and bet
    cursor.execute("INSERT INTO associates (id, display_alias) VALUES (3, 'Charlie')")
    cursor.execute(
        "INSERT INTO bookmakers (id, bookmaker_name) VALUES (3, 'Bet365')"
    )

    cursor.execute(
        """
        INSERT INTO bets (id, surebet_id, associate_id, bookmaker_id, stake_original, stake_eur, odds, currency, odds_original)
        VALUES
            (1, 6, 1, 1, '100.00', '100.00', '0.00', 'EUR', '3.00'),
            (2, 6, 2, 2, '150.00', '150.00', '0.00', 'EUR', '2.00'),
            (3, 6, 3, 3, '200.00', '200.00', '0.00', 'EUR', '1.50')
    """
    )
    cursor.execute(
        """
        INSERT INTO surebet_bets (surebet_id, bet_id, side)
        VALUES (6, 1, 'A'), (6, 2, 'B'), (6, 3, 'B')
    """
    )
    test_db.commit()

    # Create service
    service = SettlementService(db=test_db)

    # Generate preview (Bet 1 WON, others LOST)
    outcomes = {1: BetOutcome.WON, 2: BetOutcome.LOST, 3: BetOutcome.LOST}
    preview = service.preview_settlement(6, outcomes)

    # Verify three participants
    assert preview.num_participants == 3

    # Calculate expected values:
    # Bet 1 (WON): (100 × 3.00) - 100 = 200
    # Bet 2 (LOST): -150
    # Bet 3 (LOST): -200
    # Surebet profit: 200 - 150 - 200 = -150
    # Per-share: -150 ÷ 3 = -50
    assert preview.surebet_profit_eur == Decimal("-150.00")
    assert preview.per_surebet_share_eur == Decimal("-50.00")

    # Verify ledger entries
    # Bet 1: 100 (principal) + (-50) (share) = 50
    assert preview.ledger_entries[0].total_amount_eur == Decimal("50.00")

    # Bet 2: 0 (principal) + (-50) (share) = -50
    assert preview.ledger_entries[1].total_amount_eur == Decimal("-50.00")

    # Bet 3: 0 (principal) + (-50) (share) = -50
    assert preview.ledger_entries[2].total_amount_eur == Decimal("-50.00")


def test_settlement_preview_batch_id_uniqueness(test_db):
    """
    Test that each preview generates a unique batch ID.

    Given: Multiple preview generations
    When: Generate previews
    Then: Each has a unique batch ID
    """
    cursor = test_db.cursor()

    # Insert bets
    cursor.execute(
        """
        INSERT INTO bets (id, surebet_id, associate_id, bookmaker_id, stake_original, stake_eur, odds, currency, odds_original)
        VALUES
            (1, 7, 1, 1, '100.00', '100.00', '0.00', 'EUR', '1.90'),
            (2, 7, 2, 2, '80.00', '80.00', '0.00', 'EUR', '2.10')
    """
    )
    cursor.execute(
        """
        INSERT INTO surebet_bets (surebet_id, bet_id, side)
        VALUES (7, 1, 'A'), (7, 2, 'B')
    """
    )
    test_db.commit()

    # Create service
    service = SettlementService(db=test_db)

    # Generate multiple previews
    outcomes = {1: BetOutcome.WON, 2: BetOutcome.LOST}
    preview1 = service.preview_settlement(7, outcomes)
    preview2 = service.preview_settlement(7, outcomes)

    # Verify unique batch IDs
    assert preview1.settlement_batch_id != preview2.settlement_batch_id
    assert len(preview1.settlement_batch_id) == 36  # UUID length
    assert len(preview2.settlement_batch_id) == 36


def test_settlement_preview_decimal_precision(test_db):
    """
    Test that all calculations maintain Decimal precision.

    Given: Bets with amounts requiring rounding
    When: Generate settlement preview
    Then: All amounts rounded to 2 decimal places
    """
    cursor = test_db.cursor()

    # Insert bets with odd amounts
    cursor.execute(
        """
        INSERT INTO bets (id, surebet_id, associate_id, bookmaker_id, stake_original, stake_eur, odds, currency, odds_original)
        VALUES
            (1, 8, 1, 1, '33.33', '33.33', '0.00', 'EUR', '1.91'),
            (2, 8, 2, 2, '66.67', '66.67', '0.00', 'EUR', '2.11')
    """
    )
    cursor.execute(
        """
        INSERT INTO surebet_bets (surebet_id, bet_id, side)
        VALUES (8, 1, 'A'), (8, 2, 'B')
    """
    )
    test_db.commit()

    # Create service
    service = SettlementService(db=test_db)

    # Generate preview
    outcomes = {1: BetOutcome.WON, 2: BetOutcome.LOST}
    preview = service.preview_settlement(8, outcomes)

    # Verify all amounts have exactly 2 decimal places
    for entry in preview.ledger_entries:
        assert entry.principal_returned_eur.as_tuple().exponent == -2
        assert entry.per_surebet_share_eur.as_tuple().exponent == -2
        assert entry.total_amount_eur.as_tuple().exponent == -2

    # Verify net gains have 2 decimal places
    for net_gain in preview.per_bet_net_gains.values():
        assert net_gain.as_tuple().exponent == -2
