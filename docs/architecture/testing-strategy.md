# Testing Strategy

**Version:** v4
**Last Updated:** 2025-10-29
**Parent Document:** [Architecture Overview](../architecture.md)

---

## Overview

Testing strategy follows the **testing pyramid**: 70% unit tests, 25% integration tests, 5% end-to-end tests. Focus on business-critical logic: settlement math, ledger integrity, and surebet matching.

---

## Testing Pyramid

```
              /\
             /  \    E2E Tests (5%)
            /----\   Full workflow: Telegram → Settlement → Export
           /      \
          /--------\ Integration Tests (25%)
         /          \ Service layer + DB + External APIs (mocked)
        /            \
       /--------------\ Unit Tests (70%)
      /                \ Pure functions, calculators, validators
     /------------------\
```

---

## Testing Tools

### Framework

**pytest 7.0+**

```bash
# Install testing dependencies
pip install pytest pytest-asyncio pytest-mock pytest-cov freezegun
```

### Plugins

| Plugin | Purpose |
|--------|---------|
| **pytest-asyncio** | Test async Telegram bot handlers |
| **pytest-mock** | Mock external APIs (OpenAI, Telegram, FX) |
| **pytest-cov** | Code coverage reporting |
| **freezegun** | Freeze time for deterministic timestamp tests |

---

## Test Structure

```
tests/
├── unit/
│   ├── test_settlement_engine.py        # Settlement math
│   ├── test_surebet_calculator.py       # ROI calculation
│   ├── test_surebet_matcher.py          # Matching logic
│   ├── test_fx_manager.py               # Currency conversion
│   ├── test_reconciliation.py           # Health check calculations
│   └── test_decimal_helpers.py          # Utility functions
├── integration/
│   ├── test_bet_ingestion_flow.py       # Telegram → DB
│   ├── test_settlement_flow.py          # Settlement → Ledger
│   ├── test_coverage_proof.py           # Coverage delivery
│   └── test_fx_caching.py               # FX API → DB cache
├── e2e/
│   └── test_full_surebet_lifecycle.py   # End-to-end workflow
├── fixtures/
│   ├── sample_screenshots/              # Test bet screenshots
│   ├── sample_associates.sql            # Seed data
│   └── sample_bets.sql
└── conftest.py                          # Shared fixtures
```

---

## Unit Tests (70%)

**Target:** 80%+ coverage on business logic

### Example: Settlement Engine

```python
# tests/unit/test_settlement_engine.py
import pytest
from decimal import Decimal
from src.services.settlement_engine import SettlementEngine

def test_equal_split_with_admin_seat():
    """
    Given: Surebet with 2 associates betting, admin did NOT stake
    When: Settlement calculated
    Then: N = 3 (2 associates + 1 admin seat)
    """
    engine = SettlementEngine(db=get_test_db())

    # Setup: Create surebet with 2 bets (Alice, Bob)
    surebet_id = create_test_surebet(
        side_a_bets=[("Alice", Decimal("100"), Decimal("1.91"))],
        side_b_bets=[("Bob", Decimal("100"), Decimal("2.10"))]
    )

    # Settle: Side A won
    engine.settle_surebet(surebet_id, "A_WON", {}, "Test settlement")

    # Assert: Admin gets 1/3 of profit (admin did not stake)
    profit_eur = Decimal("91") - Decimal("100")  # -9 EUR loss
    expected_share = profit_eur / 3  # -3 EUR per participant

    ledger = get_ledger_entries(surebet_id)
    assert len(ledger) == 2  # Alice + Bob
    assert ledger[0]["per_surebet_share_eur"] == str(expected_share)


def test_void_participates_in_split():
    """
    Given: Surebet with 1 WON, 1 VOID
    When: Settlement calculated
    Then: Both associates get equal share of profit, VOID has net_gain_eur=0
    """
    engine = SettlementEngine(db=get_test_db())

    surebet_id = create_test_surebet(
        side_a_bets=[("Alice", Decimal("100"), Decimal("1.91"))],
        side_b_bets=[("Bob", Decimal("100"), Decimal("2.10"))]
    )

    # Settle: Side A won, but Bob's bet was VOID
    engine.settle_surebet(surebet_id, "A_WON", {
        get_bet_id("Bob"): "VOID"
    }, "Test settlement")

    ledger = get_ledger_entries(surebet_id)

    # Alice's bet: WON (net_gain = 91)
    alice_entry = [e for e in ledger if e["associate"] == "Alice"][0]
    assert alice_entry["settlement_state"] == "WON"
    assert Decimal(alice_entry["net_gain_eur"]) == Decimal("91")

    # Bob's bet: VOID (net_gain = 0, but still gets per_surebet_share)
    bob_entry = [e for e in ledger if e["associate"] == "Bob"][0]
    assert bob_entry["settlement_state"] == "VOID"
    assert Decimal(bob_entry["net_gain_eur"]) == Decimal("0")
    assert bob_entry["per_surebet_share_eur"] is not None  # Still participates


def test_frozen_fx_snapshot():
    """
    Given: Ledger entry with fx_rate_snapshot=1.50
    When: Current FX rate changes to 1.60
    Then: EUR conversion still uses 1.50 (immutable)
    """
    engine = SettlementEngine(db=get_test_db())

    # Setup: Settle with FX rate 1.50
    with freeze_fx_rate("AUD", Decimal("1.50")):
        surebet_id = create_test_surebet(
            side_a_bets=[("Alice", Decimal("100"), Decimal("1.91"), "AUD")]
        )
        engine.settle_surebet(surebet_id, "A_WON", {}, "Test")

    # Change FX rate to 1.60
    update_fx_rate("AUD", Decimal("1.60"))

    # Assert: Ledger entry still uses 1.50 snapshot
    ledger = get_ledger_entries(surebet_id)
    assert Decimal(ledger[0]["fx_rate_snapshot"]) == Decimal("1.50")
    assert Decimal(ledger[0]["amount_eur"]) == Decimal("100") * Decimal("1.50")
```

### Example: Surebet Matcher

```python
# tests/unit/test_surebet_matcher.py
def test_deterministic_side_assignment():
    """
    Given: Bet with side='OVER'
    When: determine_side() called
    Then: Returns 'A' (deterministic)
    """
    matcher = SurebetMatcher(db=get_test_db())

    assert matcher.determine_side("OVER") == "A"
    assert matcher.determine_side("UNDER") == "B"
    assert matcher.determine_side("YES") == "A"
    assert matcher.determine_side("NO") == "B"
    assert matcher.determine_side("TEAM_A") == "A"
    assert matcher.determine_side("TEAM_B") == "B"


def test_match_opposite_bets():
    """
    Given: Verified bet with OVER 2.5
    When: Opposing UNDER 2.5 bet verified
    Then: Surebet created with both bets linked
    """
    matcher = SurebetMatcher(db=get_test_db())

    # Create event and bets
    event_id = create_canonical_event("Man Utd vs Liverpool")
    bet1_id = create_bet(event_id, "TOTAL_GOALS_OVER_UNDER", "2.5", "OVER", "verified")
    bet2_id = create_bet(event_id, "TOTAL_GOALS_OVER_UNDER", "2.5", "UNDER", "verified")

    # Attempt match
    surebet_id = matcher.attempt_match(bet2_id)

    # Assert: Surebet created
    assert surebet_id is not None

    # Assert: Both bets linked with correct sides
    surebet_bets = get_surebet_bets(surebet_id)
    assert len(surebet_bets) == 2
    assert surebet_bets[0]["bet_id"] == bet1_id and surebet_bets[0]["side"] == "A"
    assert surebet_bets[1]["bet_id"] == bet2_id and surebet_bets[1]["side"] == "B"
```

---

## Integration Tests (25%)

**Target:** Test service layer + database + external APIs (mocked)

### Example: Bet Ingestion Flow

```python
# tests/integration/test_bet_ingestion_flow.py
import pytest
from unittest.mock import Mock

@pytest.fixture
def mock_openai():
    """Mock OpenAI API responses"""
    mock = Mock()
    mock.extract_bet_from_screenshot.return_value = {
        "canonical_event": "Manchester United vs Liverpool",
        "market_code": "TOTAL_GOALS_OVER_UNDER",
        "period_scope": "FULL_MATCH",
        "line_value": "2.5",
        "side": "OVER",
        "stake": "100.00",
        "odds": "1.91",
        "payout": "191.00",
        "currency": "AUD",
        "normalization_confidence": 0.85,
        "is_multi": False
    }
    return mock


def test_telegram_screenshot_to_incoming_queue(test_db, mock_telegram, mock_openai):
    """
    Given: Telegram bot receives screenshot
    When: Bot processes photo
    Then: Bet created in DB with status='incoming', OCR data populated
    """
    ingestion_service = BetIngestionService(db=test_db, openai_client=mock_openai)

    # Simulate Telegram screenshot ingestion
    screenshot_path = "tests/fixtures/sample_screenshots/bet1.png"
    bet_id = ingestion_service.ingest_telegram_screenshot(
        screenshot_path,
        associate_id=2,  # Alice
        bookmaker_id=5,  # Bet365
        telegram_message_id=123456
    )

    # Assert: Bet created
    assert bet_id is not None

    # Assert: Bet in DB with correct data
    bet = test_db.execute("SELECT * FROM bets WHERE id = ?", (bet_id,)).fetchone()
    assert bet["status"] == "incoming"
    assert bet["ingestion_source"] == "telegram"
    assert bet["telegram_message_id"] == 123456
    assert bet["market_code"] == "TOTAL_GOALS_OVER_UNDER"
    assert Decimal(bet["normalization_confidence"]) == Decimal("0.85")

    # Assert: OpenAI called once
    mock_openai.extract_bet_from_screenshot.assert_called_once_with(screenshot_path)
```

### Example: Settlement Flow

```python
# tests/integration/test_settlement_flow.py
def test_settlement_creates_ledger_entries(test_db):
    """
    Given: Open surebet with 2 bets
    When: Settlement executed
    Then: Ledger entries created, bets/surebet marked settled
    """
    # Setup: Create open surebet
    surebet_id = create_test_surebet(
        side_a_bets=[("Alice", Decimal("100"), Decimal("1.91"), "AUD")],
        side_b_bets=[("Bob", Decimal("100"), Decimal("2.10"), "GBP")]
    )

    # Settle
    engine = SettlementEngine(db=test_db)
    batch_id = engine.settle_surebet(surebet_id, "A_WON", {}, "Test settlement")

    # Assert: Surebet marked settled
    surebet = test_db.execute("SELECT status FROM surebets WHERE id = ?", (surebet_id,)).fetchone()
    assert surebet["status"] == "settled"

    # Assert: Ledger entries created
    ledger = test_db.execute("""
        SELECT * FROM ledger_entries WHERE settlement_batch_id = ?
    """, (batch_id,)).fetchall()

    assert len(ledger) == 2  # Alice + Bob
    assert all(e["type"] == "BET_RESULT" for e in ledger)
    assert all(e["settlement_batch_id"] == batch_id for e in ledger)

    # Assert: Bets marked settled
    bet_statuses = test_db.execute("""
        SELECT status FROM bets WHERE id IN (
            SELECT bet_id FROM surebet_bets WHERE surebet_id = ?
        )
    """, (surebet_id,)).fetchall()
    assert all(b["status"] == "settled" for b in bet_statuses)
```

---

## End-to-End Tests (5%)

**Target:** Test full workflow from ingestion to export

```python
# tests/e2e/test_full_surebet_lifecycle.py
def test_end_to_end_surebet_settlement(test_db, test_screenshots):
    """
    End-to-end test:
    1. Ingest 2 opposing bets (manual upload)
    2. Verify both bets
    3. Assert surebet created
    4. Settle surebet
    5. Assert ledger entries created
    6. Assert reconciliation correct
    7. Export ledger CSV
    """
    # 1. Ingest bets
    ingestion_service = BetIngestionService(db=test_db)
    bet1_id = ingestion_service.ingest_manual_screenshot(
        open(test_screenshots / "bet_over_2_5.png", "rb").read(),
        associate_id=2,  # Alice
        bookmaker_id=5   # Bet365
    )
    bet2_id = ingestion_service.ingest_manual_screenshot(
        open(test_screenshots / "bet_under_2_5.png", "rb").read(),
        associate_id=3,  # Bob
        bookmaker_id=7   # Betfair
    )

    # 2. Verify bets
    verification_service = BetVerificationService(db=test_db)
    verification_service.approve_bet(bet1_id)
    verification_service.approve_bet(bet2_id)

    # Story 2.3: Canonical Event Auto-Creation Tests
    # Unit Tests (src/services/bet_verification.py):
    # - test_get_or_create_canonical_event_creates_new_event_when_none_exists()
    # - test_get_or_create_canonical_event_reuses_fuzzy_matched_event()
    # - test_fuzzy_matching_above_threshold_reuses_event()
    # - test_fuzzy_matching_below_threshold_creates_new_event()
    # - test_fuzzy_matching_within_24h_time_window()
    # - test_fuzzy_matching_outside_24h_time_window_creates_new()
    # - test_canonical_event_creation_with_all_fields()
    # - test_canonical_event_creation_without_optional_competition()
    # - test_canonical_event_creation_validation_errors()
    # - test_canonical_event_creation_transaction_rollback_on_error()
    # - test_audit_log_created_for_auto_event_creation()
    # - test_audit_log_created_for_manual_event_creation()
    # Integration Tests:
    # - test_bet_approval_with_auto_event_creation_e2e()
    # - test_bet_approval_with_manual_event_creation_modal_e2e()
    # - test_multiple_bets_reuse_same_fuzzy_matched_event()
    # Target Coverage: 90%+ for event creation logic

    # 3. Assert surebet created
    matcher = SurebetMatcher(db=test_db)
    surebet_id = matcher.attempt_match(bet2_id)
    assert surebet_id is not None

    surebet = test_db.execute("SELECT * FROM surebets WHERE id = ?", (surebet_id,)).fetchone()
    assert surebet["status"] == "open"

    # 4. Settle surebet
    engine = SettlementEngine(db=test_db)
    batch_id = engine.settle_surebet(surebet_id, "A_WON", {}, "E2E test settlement")

    # 5. Assert ledger entries
    ledger = test_db.execute("""
        SELECT * FROM ledger_entries WHERE settlement_batch_id = ?
    """, (batch_id,)).fetchall()
    assert len(ledger) == 2

    # 6. Assert reconciliation
    reconciliation = ReconciliationService(db=test_db)
    alice_health = reconciliation.calculate_associate_health(2)
    assert alice_health["should_hold_eur"] is not None

    # 7. Export ledger CSV
    ledger_service = LedgerService(db=test_db)
    csv_path = "data/exports/e2e_test_ledger.csv"
    ledger_service.export_to_csv(csv_path)

    assert os.path.exists(csv_path)
    assert os.path.getsize(csv_path) > 0
```

---

## Test Fixtures

### Shared Fixtures (conftest.py)

```python
# tests/conftest.py
import pytest
import sqlite3
from pathlib import Path

@pytest.fixture
def test_db():
    """
    Create in-memory SQLite database for testing
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    # Create schema
    from src.core.database import create_schema
    create_schema(conn)

    # Seed test data
    seed_test_data(conn)

    yield conn
    conn.close()


def seed_test_data(conn):
    """
    Insert test associates, bookmakers, events
    """
    conn.executescript("""
        INSERT INTO associates (id, display_alias, is_admin) VALUES
        (1, 'Admin', 1),
        (2, 'Alice', 0),
        (3, 'Bob', 0);

        INSERT INTO bookmakers (id, associate_id, bookmaker_name, account_currency) VALUES
        (5, 2, 'Bet365', 'AUD'),
        (7, 3, 'Betfair', 'GBP');

        INSERT INTO canonical_events (id, event_name, sport, kickoff_time_utc) VALUES
        (100, 'Manchester United vs Liverpool', 'FOOTBALL', '2025-10-30T19:00:00Z');

        INSERT INTO fx_rates_daily (currency, rate_date, eur_per_unit) VALUES
        ('AUD', '2025-10-29', '1.50'),
        ('GBP', '2025-10-29', '0.85');
    """)
    conn.commit()


@pytest.fixture
def test_screenshots():
    """
    Path to test screenshot fixtures
    """
    return Path("tests/fixtures/sample_screenshots")
```

---

## Code Coverage

### Target Coverage

| Component | Target | Why |
|-----------|--------|-----|
| **Settlement Engine** | 95%+ | Critical financial logic |
| **Surebet Matcher** | 95%+ | Core matching algorithm |
| **FX Manager** | 90%+ | Currency conversion |
| **Ledger Service** | 90%+ | Append-only ledger |
| **UI Components** | 50% | UI is tested manually |

### Running Coverage

```bash
# Run tests with coverage
pytest --cov=src --cov-report=html

# Open coverage report
open htmlcov/index.html  # macOS
start htmlcov/index.html  # Windows
```

---

## Continuous Integration (Future)

### GitHub Actions Workflow

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v3

      - name: Set up Python 3.12
        uses: actions/setup-python@v4
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-cov

      - name: Run tests
        run: pytest --cov=src --cov-fail-under=80

      - name: Upload coverage
        uses: codecov/codecov-action@v3
```

---

## Manual Testing Checklist

**Before each release:**

- [ ] Test Telegram screenshot ingestion (send test photo)
- [ ] Test manual bet upload (UI)
- [ ] Test bet approval/rejection
- [ ] Test surebet matching (verify opposite sides matched)
- [ ] Test settlement (WON/LOST/VOID scenarios)
- [ ] Test reconciliation page (DELTA calculations)
- [ ] Test CSV export (verify file integrity)
- [ ] Test coverage proof delivery (check Telegram multibook chat)

---

**End of Document**
