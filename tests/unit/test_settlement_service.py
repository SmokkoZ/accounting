"""
Unit tests for settlement service (Story 4.3).

Tests cover:
- Equal-split calculation algorithm
- Per-bet net gain calculations
- FX conversion and Decimal precision
- Participant seat type determination
- Edge cases (all-VOID, losses, multi-currency)
"""

import pytest
from decimal import Decimal
from unittest.mock import Mock, patch
from src.services.settlement_service import (
    SettlementService,
    BetOutcome,
    SettlementPreview,
)


@pytest.fixture
def mock_db():
    """Create a mock database connection."""
    db = Mock()
    cursor = Mock()
    db.cursor.return_value = cursor
    return db


@pytest.fixture
def settlement_service(mock_db):
    """Create a settlement service with mock database."""
    return SettlementService(db=mock_db)


def test_calculate_net_gain_won(settlement_service):
    """
    Test net gain calculation for WON bet.

    Given: Bet with €100 stake @ 1.90 odds that WON
    When: Calculate net gain
    Then: Net gain = (100 × 1.90) - 100 = €90.00
    """
    stake_eur = Decimal("100.00")
    odds = Decimal("1.90")
    outcome = BetOutcome.WON

    net_gain = settlement_service._calculate_net_gain(stake_eur, odds, outcome)

    assert net_gain == Decimal("90.00")


def test_calculate_net_gain_lost(settlement_service):
    """
    Test net gain calculation for LOST bet.

    Given: Bet with €80 stake @ 2.10 odds that LOST
    When: Calculate net gain
    Then: Net gain = -€80.00
    """
    stake_eur = Decimal("80.00")
    odds = Decimal("2.10")
    outcome = BetOutcome.LOST

    net_gain = settlement_service._calculate_net_gain(stake_eur, odds, outcome)

    assert net_gain == Decimal("-80.00")


def test_calculate_net_gain_void(settlement_service):
    """
    Test net gain calculation for VOID bet.

    Given: Bet with €100 stake @ 1.90 odds that is VOID
    When: Calculate net gain
    Then: Net gain = €0.00
    """
    stake_eur = Decimal("100.00")
    odds = Decimal("1.90")
    outcome = BetOutcome.VOID

    net_gain = settlement_service._calculate_net_gain(stake_eur, odds, outcome)

    assert net_gain == Decimal("0.00")


def test_calculate_per_share_normal(settlement_service):
    """
    Test per-share calculation with normal profit.

    Given: Surebet profit of €10.00 with 2 participants
    When: Calculate per-share amount
    Then: Share = €10.00 ÷ 2 = €5.00
    """
    surebet_profit = Decimal("10.00")
    num_participants = 2

    share = settlement_service._calculate_per_share(surebet_profit, num_participants)

    assert share == Decimal("5.00")


def test_calculate_per_share_loss(settlement_service):
    """
    Test per-share calculation with loss.

    Given: Surebet loss of -€80.00 with 2 participants
    When: Calculate per-share amount
    Then: Share = -€80.00 ÷ 2 = -€40.00
    """
    surebet_profit = Decimal("-80.00")
    num_participants = 2

    share = settlement_service._calculate_per_share(surebet_profit, num_participants)

    assert share == Decimal("-40.00")


def test_calculate_per_share_odd_division(settlement_service):
    """
    Test per-share calculation with rounding.

    Given: Surebet profit of €10.00 with 3 participants
    When: Calculate per-share amount
    Then: Share = €10.00 ÷ 3 = €3.33 (rounded)
    """
    surebet_profit = Decimal("10.00")
    num_participants = 3

    share = settlement_service._calculate_per_share(surebet_profit, num_participants)

    assert share == Decimal("3.33")


def test_convert_to_eur_from_eur(settlement_service):
    """
    Test EUR to EUR conversion (no conversion needed).

    Given: Amount in EUR
    When: Convert to EUR
    Then: Amount unchanged
    """
    amount = Decimal("100.50")
    currency = "EUR"
    fx_rates = {"EUR": Decimal("1.00")}

    result = settlement_service._convert_to_eur(amount, currency, fx_rates)

    assert result == Decimal("100.50")


def test_convert_to_eur_from_usd(settlement_service):
    """
    Test USD to EUR conversion.

    Given: $100.00 at rate 0.85 EUR/USD
    When: Convert to EUR
    Then: €85.00
    """
    amount = Decimal("100.00")
    currency = "USD"
    fx_rates = {"USD": Decimal("0.85")}

    result = settlement_service._convert_to_eur(amount, currency, fx_rates)

    assert result == Decimal("85.00")


def test_convert_to_eur_rounding(settlement_service):
    """
    Test EUR conversion with rounding to 2 decimal places.

    Given: 100 AUD at rate 0.6123 EUR/AUD
    When: Convert to EUR
    Then: €61.23 (rounded from 61.23)
    """
    amount = Decimal("100.00")
    currency = "AUD"
    fx_rates = {"AUD": Decimal("0.6123")}

    result = settlement_service._convert_to_eur(amount, currency, fx_rates)

    assert result == Decimal("61.23")


@patch("src.services.settlement_service.get_fx_rate")
def test_get_fx_snapshot_mixed_currencies(mock_fx_rate, settlement_service):
    """
    Test FX snapshot with multiple currencies.

    Given: Bets in EUR, USD, and AUD
    When: Get FX snapshot
    Then: Returns rates for all currencies
    """
    mock_fx_rate.side_effect = lambda curr: {"USD": 0.85, "AUD": 0.60}.get(curr)

    bets = [
        {"currency": "EUR"},
        {"currency": "USD"},
        {"currency": "AUD"},
    ]

    fx_rates = settlement_service._get_fx_snapshot(bets)

    assert fx_rates["EUR"] == Decimal("1.00")
    assert fx_rates["USD"] == Decimal("0.85")
    assert fx_rates["AUD"] == Decimal("0.60")


@patch("src.services.settlement_service.get_fx_rate")
def test_get_fx_snapshot_missing_rate(mock_fx_rate, settlement_service):
    """
    Test FX snapshot with missing rate.

    Given: Currency with no available FX rate
    When: Get FX snapshot
    Then: Raises ValueError
    """
    mock_fx_rate.return_value = None

    bets = [{"currency": "XYZ"}]

    with pytest.raises(ValueError, match="FX rate not available for currency: XYZ"):
        settlement_service._get_fx_snapshot(bets)


def test_validate_outcomes_success(settlement_service):
    """
    Test outcome validation with all bets covered.

    Given: All bets have outcomes specified
    When: Validate outcomes
    Then: No exception raised
    """
    bets = [{"id": 1}, {"id": 2}]
    outcomes = {1: BetOutcome.WON, 2: BetOutcome.LOST}

    # Should not raise
    settlement_service._validate_outcomes(bets, outcomes)


def test_validate_outcomes_missing(settlement_service):
    """
    Test outcome validation with missing outcome.

    Given: Bet without outcome specified
    When: Validate outcomes
    Then: Raises ValueError
    """
    bets = [{"id": 1}, {"id": 2}]
    outcomes = {1: BetOutcome.WON}  # Missing bet 2

    with pytest.raises(ValueError, match="Missing outcome for bet 2"):
        settlement_service._validate_outcomes(bets, outcomes)


def test_generate_warnings_all_void(settlement_service):
    """
    Test warning generation for all-VOID scenario.

    Given: All bets marked as VOID
    When: Generate warnings
    Then: Includes all-VOID warning
    """
    from src.services.settlement_service import Participant

    participants = [
        Participant(
            bet_id=1,
            associate_id=1,
            bookmaker_id=1,
            associate_alias="Alice",
            bookmaker_name="BetFair",
            outcome=BetOutcome.VOID,
            seat_type="non-staked",
            stake_eur=Decimal("100.00"),
            stake_native=Decimal("100.00"),
            odds=Decimal("1.90"),
            currency="EUR",
            fx_rate=Decimal("1.00"),
        ),
        Participant(
            bet_id=2,
            associate_id=2,
            bookmaker_id=2,
            associate_alias="Bob",
            bookmaker_name="Pinnacle",
            outcome=BetOutcome.VOID,
            seat_type="non-staked",
            stake_eur=Decimal("80.00"),
            stake_native=Decimal("80.00"),
            odds=Decimal("2.10"),
            currency="EUR",
            fx_rate=Decimal("1.00"),
        ),
    ]

    warnings = settlement_service._generate_warnings(
        Decimal("0.00"), participants, Decimal("0.00")
    )

    assert any("All bets are VOID" in w for w in warnings)


def test_generate_warnings_loss(settlement_service):
    """
    Test warning generation for loss scenario.

    Given: Negative surebet profit
    When: Generate warnings
    Then: Includes loss warning
    """
    from src.services.settlement_service import Participant

    participants = [
        Participant(
            bet_id=1,
            associate_id=1,
            bookmaker_id=1,
            associate_alias="Alice",
            bookmaker_name="BetFair",
            outcome=BetOutcome.LOST,
            seat_type="staked",
            stake_eur=Decimal("100.00"),
            stake_native=Decimal("100.00"),
            odds=Decimal("1.90"),
            currency="EUR",
            fx_rate=Decimal("1.00"),
        ),
    ]

    warnings = settlement_service._generate_warnings(
        Decimal("-100.00"), participants, Decimal("-100.00")
    )

    assert any("Loss scenario" in w for w in warnings)


def test_generate_warnings_multi_currency(settlement_service):
    """
    Test warning generation for multi-currency settlement.

    Given: Bets in multiple currencies
    When: Generate warnings
    Then: Includes multi-currency warning
    """
    from src.services.settlement_service import Participant

    participants = [
        Participant(
            bet_id=1,
            associate_id=1,
            bookmaker_id=1,
            associate_alias="Alice",
            bookmaker_name="BetFair",
            outcome=BetOutcome.WON,
            seat_type="staked",
            stake_eur=Decimal("100.00"),
            stake_native=Decimal("100.00"),
            odds=Decimal("1.90"),
            currency="EUR",
            fx_rate=Decimal("1.00"),
        ),
        Participant(
            bet_id=2,
            associate_id=2,
            bookmaker_id=2,
            associate_alias="Bob",
            bookmaker_name="Pinnacle",
            outcome=BetOutcome.LOST,
            seat_type="staked",
            stake_eur=Decimal("68.00"),
            stake_native=Decimal("80.00"),
            odds=Decimal("2.10"),
            currency="USD",
            fx_rate=Decimal("0.85"),
        ),
    ]

    warnings = settlement_service._generate_warnings(
        Decimal("10.00"), participants, Decimal("5.00")
    )

    assert any("Multi-currency" in w for w in warnings)


def test_generate_ledger_previews_won_bet(settlement_service):
    """
    Test ledger preview generation for WON bet.

    Given: WON bet with staked seat
    When: Generate ledger previews
    Then: Principal returned + per-surebet share
    """
    from src.services.settlement_service import Participant

    participants = [
        Participant(
            bet_id=1,
            associate_id=1,
            bookmaker_id=1,
            associate_alias="Alice",
            bookmaker_name="BetFair",
            outcome=BetOutcome.WON,
            seat_type="staked",
            stake_eur=Decimal("100.00"),
            stake_native=Decimal("100.00"),
            odds=Decimal("1.90"),
            currency="EUR",
            fx_rate=Decimal("1.00"),
        ),
    ]

    previews = settlement_service._generate_ledger_previews(
        participants, Decimal("5.00")
    )

    assert len(previews) == 1
    assert previews[0].principal_returned_eur == Decimal("100.00")
    assert previews[0].per_surebet_share_eur == Decimal("5.00")
    assert previews[0].total_amount_eur == Decimal("105.00")


def test_generate_ledger_previews_lost_bet(settlement_service):
    """
    Test ledger preview generation for LOST bet.

    Given: LOST bet with staked seat
    When: Generate ledger previews
    Then: No principal returned + per-surebet share
    """
    from src.services.settlement_service import Participant

    participants = [
        Participant(
            bet_id=2,
            associate_id=2,
            bookmaker_id=2,
            associate_alias="Bob",
            bookmaker_name="Pinnacle",
            outcome=BetOutcome.LOST,
            seat_type="staked",
            stake_eur=Decimal("80.00"),
            stake_native=Decimal("80.00"),
            odds=Decimal("2.10"),
            currency="EUR",
            fx_rate=Decimal("1.00"),
        ),
    ]

    previews = settlement_service._generate_ledger_previews(
        participants, Decimal("5.00")
    )

    assert len(previews) == 1
    assert previews[0].principal_returned_eur == Decimal("0.00")
    assert previews[0].per_surebet_share_eur == Decimal("5.00")
    assert previews[0].total_amount_eur == Decimal("5.00")


def test_generate_ledger_previews_void_bet(settlement_service):
    """
    Test ledger preview generation for VOID bet.

    Given: VOID bet with non-staked seat
    When: Generate ledger previews
    Then: No principal, no share (non-staked seat gets €0)
    """
    from src.services.settlement_service import Participant

    participants = [
        Participant(
            bet_id=3,
            associate_id=3,
            bookmaker_id=3,
            associate_alias="Charlie",
            bookmaker_name="Bet365",
            outcome=BetOutcome.VOID,
            seat_type="non-staked",
            stake_eur=Decimal("100.00"),
            stake_native=Decimal("100.00"),
            odds=Decimal("1.90"),
            currency="EUR",
            fx_rate=Decimal("1.00"),
        ),
    ]

    previews = settlement_service._generate_ledger_previews(
        participants, Decimal("5.00")
    )

    assert len(previews) == 1
    assert previews[0].principal_returned_eur == Decimal("0.00")
    assert previews[0].per_surebet_share_eur == Decimal("0.00")
    assert previews[0].total_amount_eur == Decimal("0.00")


@patch("src.services.settlement_service.get_fx_rate")
def test_preview_settlement_normal_case(mock_fx_rate, settlement_service, mock_db):
    """
    Test complete preview settlement flow (normal case).

    Given: Surebet with Side A WON and Side B LOST
    When: Preview settlement
    Then: Returns complete SettlementPreview with correct calculations
    """
    # Setup mock data
    mock_fx_rate.return_value = 1.0
    cursor = mock_db.cursor.return_value
    cursor.fetchall.return_value = [
        {
            "id": 1,
            "associate_id": 1,
            "bookmaker_id": 1,
            "stake": "100.00",
            "odds": "1.90",
            "currency": "EUR",
            "associate_alias": "Alice",
            "bookmaker_name": "BetFair",
        },
        {
            "id": 2,
            "associate_id": 2,
            "bookmaker_id": 2,
            "stake": "80.00",
            "odds": "2.10",
            "currency": "EUR",
            "associate_alias": "Bob",
            "bookmaker_name": "Pinnacle",
        },
    ]

    outcomes = {1: BetOutcome.WON, 2: BetOutcome.LOST}

    preview = settlement_service.preview_settlement(1, outcomes)

    # Verify calculations
    # Bet 1 (WON): net gain = (100 × 1.90) - 100 = 90
    # Bet 2 (LOST): net gain = -80
    # Surebet profit = 90 + (-80) = 10
    # Per-share = 10 ÷ 2 = 5
    assert preview.surebet_profit_eur == Decimal("10.00")
    assert preview.num_participants == 2
    assert preview.per_surebet_share_eur == Decimal("5.00")

    # Verify ledger entries
    assert len(preview.ledger_entries) == 2

    # Bet 1: principal 100 + share 5 = 105
    assert preview.ledger_entries[0].total_amount_eur == Decimal("105.00")

    # Bet 2: principal 0 + share 5 = 5
    assert preview.ledger_entries[1].total_amount_eur == Decimal("5.00")


@patch("src.services.settlement_service.get_fx_rate")
def test_preview_settlement_all_void(mock_fx_rate, settlement_service, mock_db):
    """
    Test preview settlement with all bets VOID.

    Given: All bets marked as VOID
    When: Preview settlement
    Then: Zero profit, non-staked seats, warning generated
    """
    mock_fx_rate.return_value = 1.0
    cursor = mock_db.cursor.return_value
    cursor.fetchall.return_value = [
        {
            "id": 1,
            "associate_id": 1,
            "bookmaker_id": 1,
            "stake": "100.00",
            "odds": "1.90",
            "currency": "EUR",
            "associate_alias": "Alice",
            "bookmaker_name": "BetFair",
        },
        {
            "id": 2,
            "associate_id": 2,
            "bookmaker_id": 2,
            "stake": "80.00",
            "odds": "2.10",
            "currency": "EUR",
            "associate_alias": "Bob",
            "bookmaker_name": "Pinnacle",
        },
    ]

    outcomes = {1: BetOutcome.VOID, 2: BetOutcome.VOID}

    preview = settlement_service.preview_settlement(1, outcomes)

    # Verify all-VOID handling
    assert preview.surebet_profit_eur == Decimal("0.00")
    assert preview.per_surebet_share_eur == Decimal("0.00")
    assert any("All bets are VOID" in w for w in preview.warnings)

    # Verify all participants get €0
    for entry in preview.ledger_entries:
        assert entry.total_amount_eur == Decimal("0.00")


@patch("src.services.settlement_service.get_fx_rate")
def test_preview_settlement_with_void_participant(
    mock_fx_rate, settlement_service, mock_db
):
    """
    Test preview settlement with one VOID bet (non-staked seat).

    Given: Side A VOID, Side B LOST
    When: Preview settlement
    Then: Side A gets non-staked seat (€0), Side B gets staked seat with loss
    """
    mock_fx_rate.return_value = 1.0
    cursor = mock_db.cursor.return_value
    cursor.fetchall.return_value = [
        {
            "id": 1,
            "associate_id": 1,
            "bookmaker_id": 1,
            "stake": "100.00",
            "odds": "1.90",
            "currency": "EUR",
            "associate_alias": "Alice",
            "bookmaker_name": "BetFair",
        },
        {
            "id": 2,
            "associate_id": 2,
            "bookmaker_id": 2,
            "stake": "80.00",
            "odds": "2.10",
            "currency": "EUR",
            "associate_alias": "Bob",
            "bookmaker_name": "Pinnacle",
        },
    ]

    outcomes = {1: BetOutcome.VOID, 2: BetOutcome.LOST}

    preview = settlement_service.preview_settlement(1, outcomes)

    # Verify calculations
    # Bet 1 (VOID): net gain = 0
    # Bet 2 (LOST): net gain = -80
    # Surebet profit = 0 + (-80) = -80
    # Per-share = -80 ÷ 2 = -40
    assert preview.surebet_profit_eur == Decimal("-80.00")
    assert preview.per_surebet_share_eur == Decimal("-40.00")

    # Verify participant types
    assert preview.participants[0].seat_type == "non-staked"
    assert preview.participants[1].seat_type == "staked"

    # Bet 1 (VOID, non-staked): gets €0
    assert preview.ledger_entries[0].total_amount_eur == Decimal("0.00")

    # Bet 2 (LOST, staked): gets share of -40
    assert preview.ledger_entries[1].total_amount_eur == Decimal("-40.00")
