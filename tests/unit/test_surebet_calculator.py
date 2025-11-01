"""
Unit tests for SurebetRiskCalculator service.

Tests cover:
- EUR conversion with various currencies
- Profit/ROI calculation with different scenarios
- Risk classification thresholds
- Missing FX rate handling
"""

import pytest
import sqlite3
from decimal import Decimal
from datetime import date, datetime, UTC

from src.services.surebet_calculator import SurebetRiskCalculator
from src.core.schema import create_schema
from src.services.fx_manager import store_fx_rate


@pytest.fixture
def test_db():
    """Create in-memory test database with schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    create_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def calculator(test_db):
    """Create SurebetRiskCalculator instance with test database."""
    return SurebetRiskCalculator(test_db)


@pytest.fixture
def setup_fx_rates(test_db):
    """Setup FX rates for testing."""
    today = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    # Store test FX rates
    store_fx_rate("AUD", Decimal("0.60"), today, "test", test_db)
    store_fx_rate("GBP", Decimal("1.15"), today, "test", test_db)
    store_fx_rate("USD", Decimal("0.92"), today, "test", test_db)


@pytest.fixture
def setup_test_data(test_db, setup_fx_rates):
    """Setup test data: associates, events, bets, surebet."""
    # Create associates
    test_db.execute(
        "INSERT INTO associates (id, display_alias) VALUES (1, 'Alice'), (2, 'Bob')"
    )

    # Create bookmakers
    test_db.execute(
        """
        INSERT INTO bookmakers (id, associate_id, bookmaker_name)
        VALUES (1, 1, 'Bet365'), (2, 2, 'Pinnacle')
        """
    )

    # Create canonical event
    test_db.execute(
        """
        INSERT INTO canonical_events (id, normalized_event_name, sport, league)
        VALUES (1, 'Team A vs Team B', 'Soccer', 'Premier League')
        """
    )

    # Create canonical market
    test_db.execute(
        """
        INSERT INTO canonical_markets (id, market_code, description)
        VALUES (1, 'TOTALS', 'Total Goals Over/Under')
        """
    )

    # Create surebet
    test_db.execute(
        """
        INSERT INTO surebets (
            id, canonical_event_id, canonical_market_id,
            market_code, period_scope, line_value, status
        )
        VALUES (1, 1, 1, 'TOTALS', 'FULL_TIME', '2.5', 'open')
        """
    )

    test_db.commit()


def test_calculate_surebet_risk_safe_classification(
    test_db, calculator, setup_test_data
):
    """
    Given: Surebet with profitable outcomes on both sides (ROI >= 1.0%)
    When: Risk is calculated
    Then: Classification should be 'Safe' with positive worst-case profit
    """
    # Create bets with positive profit on both sides
    # Side A (OVER): Stake 100 EUR @ 2.10 = Payout 210 EUR
    test_db.execute(
        """
        INSERT INTO bets (
            id, associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
            status, stake_eur, stake_original, odds, odds_original,
            currency, payout, market_code, period_scope, line_value,
            side, is_supported
        )
        VALUES (1, 1, 1, 1, 1, 'matched', '100.00', '100.00', '2.10', '2.10',
                'EUR', '210.00', 'TOTALS', 'FULL_TIME', '2.5', 'OVER', 1)
        """
    )

    # Side B (UNDER): Stake 100 EUR @ 2.10 = Payout 210 EUR
    test_db.execute(
        """
        INSERT INTO bets (
            id, associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
            status, stake_eur, stake_original, odds, odds_original,
            currency, payout, market_code, period_scope, line_value,
            side, is_supported
        )
        VALUES (2, 2, 2, 1, 1, 'matched', '100.00', '100.00', '2.10', '2.10',
                'EUR', '210.00', 'TOTALS', 'FULL_TIME', '2.5', 'UNDER', 1)
        """
    )

    # Link bets to surebet
    test_db.execute(
        "INSERT INTO surebet_bets (surebet_id, bet_id, side) VALUES (1, 1, 'A'), (1, 2, 'B')"
    )
    test_db.commit()

    # Calculate risk
    result = calculator.calculate_surebet_risk(1)

    # Assert Safe classification
    assert result["risk_classification"] == "Safe"
    assert result["color_code"] == "✅"
    assert result["worst_case_profit_eur"] == Decimal("10.00")  # 210 - 200 = 10
    assert result["total_staked_eur"] == Decimal("200.00")
    assert result["roi"] == Decimal("5.00")  # (10/200) * 100 = 5%
    assert result["profit_if_a_wins"] == Decimal("10.00")
    assert result["profit_if_b_wins"] == Decimal("10.00")
    assert result["side_a_count"] == 1
    assert result["side_b_count"] == 1


def test_calculate_surebet_risk_low_roi_classification(
    test_db, calculator, setup_test_data
):
    """
    Given: Surebet with small positive profit (ROI < 1.0%)
    When: Risk is calculated
    Then: Classification should be 'Low ROI'
    """
    # Side A: Stake 100 EUR @ 2.01 = Payout 201 EUR
    test_db.execute(
        """
        INSERT INTO bets (
            id, associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
            status, stake_eur, stake_original, odds, odds_original,
            currency, payout, market_code, period_scope, line_value,
            side, is_supported
        )
        VALUES (1, 1, 1, 1, 1, 'matched', '100.00', '100.00', '2.01', '2.01',
                'EUR', '201.00', 'TOTALS', 'FULL_TIME', '2.5', 'OVER', 1)
        """
    )

    # Side B: Stake 100 EUR @ 2.01 = Payout 201 EUR
    test_db.execute(
        """
        INSERT INTO bets (
            id, associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
            status, stake_eur, stake_original, odds, odds_original,
            currency, payout, market_code, period_scope, line_value,
            side, is_supported
        )
        VALUES (2, 2, 2, 1, 1, 'matched', '100.00', '100.00', '2.01', '2.01',
                'EUR', '201.00', 'TOTALS', 'FULL_TIME', '2.5', 'UNDER', 1)
        """
    )

    test_db.execute(
        "INSERT INTO surebet_bets (surebet_id, bet_id, side) VALUES (1, 1, 'A'), (1, 2, 'B')"
    )
    test_db.commit()

    result = calculator.calculate_surebet_risk(1)

    # Assert Low ROI classification
    assert result["risk_classification"] == "Low ROI"
    assert result["color_code"] == "🟡"
    assert result["worst_case_profit_eur"] == Decimal("1.00")  # 201 - 200 = 1
    assert result["roi"] == Decimal("0.50")  # (1/200) * 100 = 0.5%


def test_calculate_surebet_risk_unsafe_classification(
    test_db, calculator, setup_test_data
):
    """
    Given: Surebet with guaranteed loss (negative worst-case profit)
    When: Risk is calculated
    Then: Classification should be 'Unsafe'
    """
    # Side A: Stake 100 EUR @ 1.80 = Payout 180 EUR
    test_db.execute(
        """
        INSERT INTO bets (
            id, associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
            status, stake_eur, stake_original, odds, odds_original,
            currency, payout, market_code, period_scope, line_value,
            side, is_supported
        )
        VALUES (1, 1, 1, 1, 1, 'matched', '100.00', '100.00', '1.80', '1.80',
                'EUR', '180.00', 'TOTALS', 'FULL_TIME', '2.5', 'OVER', 1)
        """
    )

    # Side B: Stake 100 EUR @ 1.80 = Payout 180 EUR
    test_db.execute(
        """
        INSERT INTO bets (
            id, associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
            status, stake_eur, stake_original, odds, odds_original,
            currency, payout, market_code, period_scope, line_value,
            side, is_supported
        )
        VALUES (2, 2, 2, 1, 1, 'matched', '100.00', '100.00', '1.80', '1.80',
                'EUR', '180.00', 'TOTALS', 'FULL_TIME', '2.5', 'UNDER', 1)
        """
    )

    test_db.execute(
        "INSERT INTO surebet_bets (surebet_id, bet_id, side) VALUES (1, 1, 'A'), (1, 2, 'B')"
    )
    test_db.commit()

    result = calculator.calculate_surebet_risk(1)

    # Assert Unsafe classification
    assert result["risk_classification"] == "Unsafe"
    assert result["color_code"] == "❌"
    assert result["worst_case_profit_eur"] == Decimal("-20.00")  # 180 - 200 = -20
    assert result["roi"] == Decimal("-10.00")  # (-20/200) * 100 = -10%


def test_calculate_surebet_risk_with_fx_conversion(
    test_db, calculator, setup_test_data
):
    """
    Given: Surebet with bets in different currencies
    When: Risk is calculated
    Then: All amounts should be correctly converted to EUR
    """
    # Side A: Stake 100 AUD @ 2.10 (0.60 EUR per AUD) = 60 EUR stake, 126 EUR payout
    test_db.execute(
        """
        INSERT INTO bets (
            id, associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
            status, stake_eur, stake_original, odds, odds_original,
            currency, payout, market_code, period_scope, line_value,
            side, is_supported
        )
        VALUES (1, 1, 1, 1, 1, 'matched', '60.00', '100.00', '2.10', '2.10',
                'AUD', '210.00', 'TOTALS', 'FULL_TIME', '2.5', 'OVER', 1)
        """
    )

    # Side B: Stake 100 GBP @ 2.10 (1.15 EUR per GBP) = 115 EUR stake, 241.50 EUR payout
    test_db.execute(
        """
        INSERT INTO bets (
            id, associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
            status, stake_eur, stake_original, odds, odds_original,
            currency, payout, market_code, period_scope, line_value,
            side, is_supported
        )
        VALUES (2, 2, 2, 1, 1, 'matched', '115.00', '100.00', '2.10', '2.10',
                'GBP', '210.00', 'TOTALS', 'FULL_TIME', '2.5', 'UNDER', 1)
        """
    )

    test_db.execute(
        "INSERT INTO surebet_bets (surebet_id, bet_id, side) VALUES (1, 1, 'A'), (1, 2, 'B')"
    )
    test_db.commit()

    result = calculator.calculate_surebet_risk(1)

    # Total staked: 60 + 115 = 175 EUR
    # Profit if A wins: 126 - 175 = -49 EUR
    # Profit if B wins: 241.50 - 175 = 66.50 EUR
    # Worst case: -49 EUR
    assert result["total_staked_eur"] == Decimal("175.00")
    assert result["worst_case_profit_eur"] == Decimal("-49.00")
    assert result["risk_classification"] == "Unsafe"


def test_calculate_surebet_risk_asymmetric_sides(test_db, calculator, setup_test_data):
    """
    Given: Surebet with different profit scenarios for each side
    When: Risk is calculated
    Then: Worst-case should be the minimum of the two scenarios
    """
    # Side A: Stake 100 EUR @ 2.50 = Payout 250 EUR
    test_db.execute(
        """
        INSERT INTO bets (
            id, associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
            status, stake_eur, stake_original, odds, odds_original,
            currency, payout, market_code, period_scope, line_value,
            side, is_supported
        )
        VALUES (1, 1, 1, 1, 1, 'matched', '100.00', '100.00', '2.50', '2.50',
                'EUR', '250.00', 'TOTALS', 'FULL_TIME', '2.5', 'OVER', 1)
        """
    )

    # Side B: Stake 100 EUR @ 1.80 = Payout 180 EUR
    test_db.execute(
        """
        INSERT INTO bets (
            id, associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
            status, stake_eur, stake_original, odds, odds_original,
            currency, payout, market_code, period_scope, line_value,
            side, is_supported
        )
        VALUES (2, 2, 2, 1, 1, 'matched', '100.00', '100.00', '1.80', '1.80',
                'EUR', '180.00', 'TOTALS', 'FULL_TIME', '2.5', 'UNDER', 1)
        """
    )

    test_db.execute(
        "INSERT INTO surebet_bets (surebet_id, bet_id, side) VALUES (1, 1, 'A'), (1, 2, 'B')"
    )
    test_db.commit()

    result = calculator.calculate_surebet_risk(1)

    # Profit if A wins: 250 - 200 = 50 EUR
    # Profit if B wins: 180 - 200 = -20 EUR
    # Worst case: -20 EUR
    assert result["profit_if_a_wins"] == Decimal("50.00")
    assert result["profit_if_b_wins"] == Decimal("-20.00")
    assert result["worst_case_profit_eur"] == Decimal("-20.00")
    assert result["risk_classification"] == "Unsafe"


def test_calculate_surebet_risk_multiple_bets_per_side(
    test_db, calculator, setup_test_data
):
    """
    Given: Surebet with multiple bets on each side
    When: Risk is calculated
    Then: All bets should be aggregated correctly
    """
    # Side A - Bet 1: 50 EUR @ 2.10 = 105 EUR
    test_db.execute(
        """
        INSERT INTO bets (
            id, associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
            status, stake_eur, stake_original, odds, odds_original,
            currency, payout, market_code, period_scope, line_value,
            side, is_supported
        )
        VALUES (1, 1, 1, 1, 1, 'matched', '50.00', '50.00', '2.10', '2.10',
                'EUR', '105.00', 'TOTALS', 'FULL_TIME', '2.5', 'OVER', 1)
        """
    )

    # Side A - Bet 2: 50 EUR @ 2.10 = 105 EUR
    test_db.execute(
        """
        INSERT INTO bets (
            id, associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
            status, stake_eur, stake_original, odds, odds_original,
            currency, payout, market_code, period_scope, line_value,
            side, is_supported
        )
        VALUES (2, 1, 1, 1, 1, 'matched', '50.00', '50.00', '2.10', '2.10',
                'EUR', '105.00', 'TOTALS', 'FULL_TIME', '2.5', 'OVER', 1)
        """
    )

    # Side B - Bet 1: 100 EUR @ 2.10 = 210 EUR
    test_db.execute(
        """
        INSERT INTO bets (
            id, associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
            status, stake_eur, stake_original, odds, odds_original,
            currency, payout, market_code, period_scope, line_value,
            side, is_supported
        )
        VALUES (3, 2, 2, 1, 1, 'matched', '100.00', '100.00', '2.10', '2.10',
                'EUR', '210.00', 'TOTALS', 'FULL_TIME', '2.5', 'UNDER', 1)
        """
    )

    test_db.execute(
        """
        INSERT INTO surebet_bets (surebet_id, bet_id, side)
        VALUES (1, 1, 'A'), (1, 2, 'A'), (1, 3, 'B')
        """
    )
    test_db.commit()

    result = calculator.calculate_surebet_risk(1)

    # Total stakes: 50 + 50 + 100 = 200 EUR
    # Profit if A wins: (105 + 105) - 200 = 10 EUR
    # Profit if B wins: 210 - 200 = 10 EUR
    assert result["total_staked_eur"] == Decimal("200.00")
    assert result["profit_if_a_wins"] == Decimal("10.00")
    assert result["profit_if_b_wins"] == Decimal("10.00")
    assert result["worst_case_profit_eur"] == Decimal("10.00")
    assert result["side_a_count"] == 2
    assert result["side_b_count"] == 1


def test_calculate_surebet_risk_missing_surebet(calculator):
    """
    Given: Non-existent surebet ID
    When: Risk calculation is attempted
    Then: ValueError should be raised
    """
    with pytest.raises(ValueError, match="Surebet 999 not found"):
        calculator.calculate_surebet_risk(999)


def test_calculate_surebet_risk_no_linked_bets(test_db, calculator, setup_test_data):
    """
    Given: Surebet with no linked bets
    When: Risk calculation is attempted
    Then: ValueError should be raised
    """
    with pytest.raises(ValueError, match="Surebet 1 has no linked bets"):
        calculator.calculate_surebet_risk(1)


def test_calculate_surebet_risk_zero_total_stake(test_db, calculator, setup_test_data):
    """
    Given: Surebet with zero total stakes (edge case)
    When: Risk is calculated
    Then: ROI should be 0 to avoid division by zero
    """
    # Create bets with zero stakes (edge case)
    test_db.execute(
        """
        INSERT INTO bets (
            id, associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
            status, stake_eur, stake_original, odds, odds_original,
            currency, payout, market_code, period_scope, line_value,
            side, is_supported
        )
        VALUES (1, 1, 1, 1, 1, 'matched', '0.00', '0.00', '2.10', '2.10',
                'EUR', '0.00', 'TOTALS', 'FULL_TIME', '2.5', 'OVER', 1)
        """
    )

    test_db.execute(
        """
        INSERT INTO bets (
            id, associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
            status, stake_eur, stake_original, odds, odds_original,
            currency, payout, market_code, period_scope, line_value,
            side, is_supported
        )
        VALUES (2, 2, 2, 1, 1, 'matched', '0.00', '0.00', '2.10', '2.10',
                'EUR', '0.00', 'TOTALS', 'FULL_TIME', '2.5', 'UNDER', 1)
        """
    )

    test_db.execute(
        "INSERT INTO surebet_bets (surebet_id, bet_id, side) VALUES (1, 1, 'A'), (1, 2, 'B')"
    )
    test_db.commit()

    result = calculator.calculate_surebet_risk(1)

    # Should not raise division by zero error
    assert result["total_staked_eur"] == Decimal("0.00")
    assert result["roi"] == Decimal("0")
