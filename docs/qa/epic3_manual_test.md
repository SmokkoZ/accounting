# Epic 3 Manual Testing Guide

**Version:** 1.0
**Date:** 2025-10-31
**Epic:** 3 - Surebet Matching & Risk Analysis
**Prerequisites:** Epics 1 & 2 completed

---

## Overview

This guide provides step-by-step manual testing procedures for Epic 3 functionality:
- **Story 3.1:** Deterministic Matching Engine
- **Story 3.2:** Worst-Case EUR Profit Calculation

It also includes end-to-end workflow testing covering previous epics to validate the complete system.

---

## Table of Contents

1. [Test Environment Setup](#test-environment-setup)
2. [Epic 3.1: Deterministic Matching Engine](#epic-31-deterministic-matching-engine)
3. [Epic 3.2: Worst-Case EUR Profit Calculation](#epic-32-worst-case-eur-profit-calculation)
4. [End-to-End Workflow Testing](#end-to-end-workflow-testing)
5. [Edge Cases & Error Handling](#edge-cases--error-handling)
6. [Regression Testing Checklist](#regression-testing-checklist)

---

## Test Environment Setup

### Prerequisites

1. **Python Environment**
   ```bash
   python --version  # Should be 3.12+
   ```

2. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Database Setup**
   ```bash
   # Fresh database for testing
   rm data/surebet.db  # Delete old database if exists
   python -c "from src.core.database import get_db_connection; from src.core.schema import create_schema; conn = get_db_connection(); create_schema(conn); print('Database created')"
   ```

4. **Seed Test Data**
   ```bash
   python -c "from src.core.database import get_db_connection; from src.core.seed_data import seed_all_data; conn = get_db_connection(); seed_all_data(conn); print('Data seeded')"
   ```

5. **Verify Seed Data**
   ```bash
   sqlite3 data/surebet.db
   sqlite> SELECT id, display_alias FROM associates;
   sqlite> SELECT id, bookmaker_name FROM bookmakers;
   sqlite> SELECT id, normalized_event_name FROM canonical_events;
   sqlite> .quit
   ```

6. **Setup FX Rates**
   ```python
   # Run this Python script to add FX rates
   from src.core.database import get_db_connection
   from src.services.fx_manager import store_fx_rate
   from decimal import Decimal
   from datetime import datetime, UTC

   conn = get_db_connection()
   today = datetime.now(UTC).isoformat().replace("+00:00", "Z")

   # Add common FX rates
   store_fx_rate("AUD", Decimal("0.60"), today, "manual", conn)
   store_fx_rate("GBP", Decimal("1.15"), today, "manual", conn)
   store_fx_rate("USD", Decimal("0.92"), today, "manual", conn)

   print("FX rates added successfully")
   conn.close()
   ```

---

## Epic 3.1: Deterministic Matching Engine

### Test Case 3.1.1: Basic Over/Under Matching

**Objective:** Verify that opposite-side bets (OVER/UNDER) are matched into a surebet

**Test Data Setup:**
```python
from src.core.database import get_db_connection
from decimal import Decimal

conn = get_db_connection()

# Get IDs for Alice and Bob
cursor = conn.execute("SELECT id FROM associates WHERE display_alias = 'Alice'")
alice_id = cursor.fetchone()[0]
cursor = conn.execute("SELECT id FROM associates WHERE display_alias = 'Bob'")
bob_id = cursor.fetchone()[0]

# Get bookmaker IDs
cursor = conn.execute("SELECT id FROM bookmakers WHERE associate_id = ?", (alice_id,))
alice_bookmaker = cursor.fetchone()[0]
cursor = conn.execute("SELECT id FROM bookmakers WHERE associate_id = ?", (bob_id,))
bob_bookmaker = cursor.fetchone()[0]

# Get a canonical event
cursor = conn.execute("SELECT id FROM canonical_events LIMIT 1")
event_id = cursor.fetchone()[0]

# Get canonical market for TOTALS
cursor = conn.execute("SELECT id FROM canonical_markets WHERE market_code = 'TOTALS'")
market_id = cursor.fetchone()[0]

print(f"Alice ID: {alice_id}, Alice Bookmaker: {alice_bookmaker}")
print(f"Bob ID: {bob_id}, Bob Bookmaker: {bob_bookmaker}")
print(f"Event ID: {event_id}, Market ID: {market_id}")
```

**Test Steps:**

1. **Create Bet 1 (Alice - OVER 2.5)**
   ```python
   # Insert bet for Alice
   cursor = conn.execute("""
       INSERT INTO bets (
           associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
           status, stake_eur, odds, currency, market_code, period_scope,
           line_value, side, is_supported
       )
       VALUES (?, ?, ?, ?, 'incoming', '100.00', '2.10', 'EUR',
               'TOTALS', 'FULL_TIME', '2.5', 'OVER', 1)
   """, (alice_id, alice_bookmaker, event_id, market_id))
   bet1_id = cursor.lastrowid
   conn.commit()
   print(f"Bet 1 created: ID {bet1_id}")
   ```

2. **Verify Bet 1 - Check Status**
   ```python
   from src.services.bet_verification import BetVerificationService

   service = BetVerificationService(conn)
   service.approve_bet(bet1_id, actor="Manual Test")

   # Check status
   cursor = conn.execute("SELECT status FROM bets WHERE id = ?", (bet1_id,))
   status = cursor.fetchone()[0]
   print(f"✓ Bet 1 status after approval: {status}")
   assert status == "verified", f"Expected 'verified', got '{status}'"
   ```

3. **Create Bet 2 (Bob - UNDER 2.5)**
   ```python
   cursor = conn.execute("""
       INSERT INTO bets (
           associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
           status, stake_eur, odds, currency, market_code, period_scope,
           line_value, side, is_supported
       )
       VALUES (?, ?, ?, ?, 'incoming', '100.00', '2.10', 'EUR',
               'TOTALS', 'FULL_TIME', '2.5', 'UNDER', 1)
   """, (bob_id, bob_bookmaker, event_id, market_id))
   bet2_id = cursor.lastrowid
   conn.commit()
   print(f"Bet 2 created: ID {bet2_id}")
   ```

4. **Verify Bet 2 - Should Auto-Match**
   ```python
   service.approve_bet(bet2_id, actor="Manual Test")

   # Check status - should be 'matched'
   cursor = conn.execute("SELECT status FROM bets WHERE id = ?", (bet2_id,))
   status = cursor.fetchone()[0]
   print(f"✓ Bet 2 status after approval: {status}")
   assert status == "matched", f"Expected 'matched', got '{status}'"
   ```

5. **Verify Surebet Created**
   ```python
   # Check that both bets are linked to same surebet
   cursor = conn.execute("""
       SELECT DISTINCT surebet_id FROM surebet_bets
       WHERE bet_id IN (?, ?)
   """, (bet1_id, bet2_id))
   surebet_ids = [row[0] for row in cursor.fetchall()]

   print(f"✓ Surebets found: {surebet_ids}")
   assert len(surebet_ids) == 1, f"Expected 1 surebet, found {len(surebet_ids)}"

   surebet_id = surebet_ids[0]
   print(f"✓ Surebet ID: {surebet_id}")
   ```

6. **Verify Side Assignments**
   ```python
   # Check side assignments (OVER -> A, UNDER -> B)
   cursor = conn.execute("""
       SELECT bet_id, side FROM surebet_bets
       WHERE surebet_id = ?
       ORDER BY bet_id
   """, (surebet_id,))

   sides = [(row[0], row[1]) for row in cursor.fetchall()]
   print(f"✓ Side assignments: {sides}")

   # Bet 1 (OVER) should be Side A
   assert sides[0] == (bet1_id, 'A'), f"Bet 1 should be Side A, got {sides[0]}"
   # Bet 2 (UNDER) should be Side B
   assert sides[1] == (bet2_id, 'B'), f"Bet 2 should be Side B, got {sides[1]}"

   print("✅ Test Case 3.1.1 PASSED")
   ```

**Expected Results:**
- ✅ Bet 1 status: `verified`
- ✅ Bet 2 status: `matched` (auto-matched with Bet 1)
- ✅ Both bets linked to same surebet
- ✅ OVER bet assigned to Side A
- ✅ UNDER bet assigned to Side B

---

### Test Case 3.1.2: YES/NO Matching

**Objective:** Verify YES/NO market matching

**Test Steps:**

1. **Create YES Bet**
   ```python
   cursor = conn.execute("""
       INSERT INTO bets (
           associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
           status, stake_eur, odds, currency, market_code, period_scope,
           line_value, side, is_supported
       )
       VALUES (?, ?, ?, ?, 'verified', '50.00', '1.90', 'EUR',
               'BTTS', 'FULL_TIME', NULL, 'YES', 1)
   """, (alice_id, alice_bookmaker, event_id, market_id))
   yes_bet_id = cursor.lastrowid
   conn.commit()
   print(f"YES bet created: ID {yes_bet_id}")
   ```

2. **Create NO Bet - Should Auto-Match**
   ```python
   from src.services.surebet_matcher import SurebetMatcher

   cursor = conn.execute("""
       INSERT INTO bets (
           associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
           status, stake_eur, odds, currency, market_code, period_scope,
           line_value, side, is_supported
       )
       VALUES (?, ?, ?, ?, 'verified', '50.00', '2.20', 'EUR',
               'BTTS', 'FULL_TIME', NULL, 'NO', 1)
   """, (bob_id, bob_bookmaker, event_id, market_id))
   no_bet_id = cursor.lastrowid
   conn.commit()

   # Attempt matching
   matcher = SurebetMatcher(conn)
   surebet_id = matcher.attempt_match(no_bet_id)

   print(f"✓ Surebet created: {surebet_id}")
   assert surebet_id is not None, "Surebet should be created"
   ```

3. **Verify Side Assignments**
   ```python
   cursor = conn.execute("""
       SELECT b.side, sb.side as surebet_side
       FROM surebet_bets sb
       JOIN bets b ON sb.bet_id = b.id
       WHERE sb.surebet_id = ?
       ORDER BY b.id
   """, (surebet_id,))

   mappings = [(row[0], row[1]) for row in cursor.fetchall()]
   print(f"✓ Side mappings: {mappings}")

   # YES -> A, NO -> B
   assert mappings[0] == ('YES', 'A'), f"YES should map to A"
   assert mappings[1] == ('NO', 'B'), f"NO should map to B"

   print("✅ Test Case 3.1.2 PASSED")
   ```

**Expected Results:**
- ✅ YES bet assigned to Side A
- ✅ NO bet assigned to Side B
- ✅ Both bets matched into surebet

---

### Test Case 3.1.3: Matching Requires Same Criteria

**Objective:** Verify that matching only occurs when event, market, period, and line match

**Test Steps:**

1. **Create Bet with Line 2.5**
   ```python
   cursor = conn.execute("""
       INSERT INTO bets (
           associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
           status, stake_eur, odds, currency, market_code, period_scope,
           line_value, side, is_supported
       )
       VALUES (?, ?, ?, ?, 'verified', '100.00', '2.10', 'EUR',
               'TOTALS', 'FULL_TIME', '2.5', 'OVER', 1)
   """, (alice_id, alice_bookmaker, event_id, market_id))
   bet_2_5_id = cursor.lastrowid
   conn.commit()
   ```

2. **Create Opposite Bet with Different Line (3.5) - Should NOT Match**
   ```python
   cursor = conn.execute("""
       INSERT INTO bets (
           associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
           status, stake_eur, odds, currency, market_code, period_scope,
           line_value, side, is_supported
       )
       VALUES (?, ?, ?, ?, 'verified', '100.00', '1.85', 'EUR',
               'TOTALS', 'FULL_TIME', '3.5', 'UNDER', 1)
   """, (bob_id, bob_bookmaker, event_id, market_id))
   bet_3_5_id = cursor.lastrowid
   conn.commit()

   matcher = SurebetMatcher(conn)
   result = matcher.attempt_match(bet_3_5_id)

   print(f"✓ Match result: {result}")
   assert result is None, "Should not match due to different line values"

   # Check bet status - should still be verified, not matched
   cursor = conn.execute("SELECT status FROM bets WHERE id = ?", (bet_3_5_id,))
   status = cursor.fetchone()[0]
   assert status == "verified", f"Bet should remain 'verified', got '{status}'"

   print("✅ Test Case 3.1.3 PASSED")
   ```

**Expected Results:**
- ✅ Bets with different line values do NOT match
- ✅ Bet status remains `verified` (not `matched`)

---

### Test Case 3.1.4: Multiple Bets on Same Side

**Objective:** Verify that multiple bets can be added to the same side of a surebet

**Test Steps:**

1. **Create First OVER Bet**
   ```python
   cursor = conn.execute("""
       INSERT INTO bets (
           associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
           status, stake_eur, odds, currency, market_code, period_scope,
           line_value, side, is_supported
       )
       VALUES (?, ?, ?, ?, 'verified', '50.00', '2.10', 'EUR',
               'TOTALS', 'FULL_TIME', '1.5', 'OVER', 1)
   """, (alice_id, alice_bookmaker, event_id, market_id))
   over1_id = cursor.lastrowid
   conn.commit()
   ```

2. **Create UNDER Bet**
   ```python
   cursor = conn.execute("""
       INSERT INTO bets (
           associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
           status, stake_eur, odds, currency, market_code, period_scope,
           line_value, side, is_supported
       )
       VALUES (?, ?, ?, ?, 'verified', '100.00', '1.80', 'EUR',
               'TOTALS', 'FULL_TIME', '1.5', 'UNDER', 1)
   """, (bob_id, bob_bookmaker, event_id, market_id))
   under1_id = cursor.lastrowid
   conn.commit()

   matcher = SurebetMatcher(conn)
   surebet_id = matcher.attempt_match(under1_id)
   print(f"✓ Surebet created: {surebet_id}")
   ```

3. **Add Second OVER Bet to Existing Surebet**
   ```python
   cursor = conn.execute("""
       INSERT INTO bets (
           associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
           status, stake_eur, odds, currency, market_code, period_scope,
           line_value, side, is_supported
       )
       VALUES (?, ?, ?, ?, 'verified', '50.00', '2.05', 'EUR',
               'TOTALS', 'FULL_TIME', '1.5', 'OVER', 1)
   """, (alice_id, alice_bookmaker, event_id, market_id))
   over2_id = cursor.lastrowid
   conn.commit()

   surebet_id_2 = matcher.attempt_match(over2_id)
   print(f"✓ Matched to surebet: {surebet_id_2}")

   # Should match to same surebet
   assert surebet_id == surebet_id_2, "Should match to existing surebet"
   ```

4. **Verify Multiple Bets on Side A**
   ```python
   cursor = conn.execute("""
       SELECT bet_id, side FROM surebet_bets
       WHERE surebet_id = ?
       ORDER BY bet_id
   """, (surebet_id,))

   bets = [(row[0], row[1]) for row in cursor.fetchall()]
   print(f"✓ Surebet composition: {bets}")

   # Count bets per side
   side_a_count = sum(1 for _, side in bets if side == 'A')
   side_b_count = sum(1 for _, side in bets if side == 'B')

   assert side_a_count == 2, f"Expected 2 bets on Side A, got {side_a_count}"
   assert side_b_count == 1, f"Expected 1 bet on Side B, got {side_b_count}"

   print("✅ Test Case 3.1.4 PASSED")
   ```

**Expected Results:**
- ✅ Multiple OVER bets added to Side A
- ✅ Single UNDER bet on Side B
- ✅ All linked to same surebet

---

## Epic 3.2: Worst-Case EUR Profit Calculation

### Test Case 3.2.1: Safe Classification (ROI >= 1%)

**Objective:** Verify that surebets with good profit/ROI are classified as "Safe"

**Test Steps:**

1. **Create Profitable Surebet**
   ```python
   from src.services.surebet_calculator import SurebetRiskCalculator

   # Create OVER bet: 100 EUR @ 2.10 = 210 EUR payout
   cursor = conn.execute("""
       INSERT INTO bets (
           associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
           status, stake_eur, odds, currency, payout, market_code, period_scope,
           line_value, side, is_supported
       )
       VALUES (?, ?, ?, ?, 'verified', '100.00', '2.10', 'EUR', '210.00',
               'TOTALS', 'FULL_TIME', '0.5', 'OVER', 1)
   """, (alice_id, alice_bookmaker, event_id, market_id))
   over_id = cursor.lastrowid

   # Create UNDER bet: 100 EUR @ 2.10 = 210 EUR payout
   cursor = conn.execute("""
       INSERT INTO bets (
           associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
           status, stake_eur, odds, currency, payout, market_code, period_scope,
           line_value, side, is_supported
       )
       VALUES (?, ?, ?, ?, 'verified', '100.00', '2.10', 'EUR', '210.00',
               'TOTALS', 'FULL_TIME', '0.5', 'UNDER', 1)
   """, (bob_id, bob_bookmaker, event_id, market_id))
   under_id = cursor.lastrowid
   conn.commit()

   # Match them
   matcher = SurebetMatcher(conn)
   surebet_id = matcher.attempt_match(under_id)
   print(f"✓ Surebet created: {surebet_id}")
   ```

2. **Verify Risk Calculation**
   ```python
   # Risk should be auto-calculated by matcher
   cursor = conn.execute("""
       SELECT worst_case_profit_eur, total_staked_eur, roi, risk_classification
       FROM surebets WHERE id = ?
   """, (surebet_id,))
   row = cursor.fetchone()

   print(f"✓ Worst-case profit: {row[0]} EUR")
   print(f"✓ Total staked: {row[1]} EUR")
   print(f"✓ ROI: {row[2]}%")
   print(f"✓ Risk classification: {row[3]}")

   from decimal import Decimal
   assert Decimal(row[0]) == Decimal("10.00"), "Profit should be 10 EUR (210 - 200)"
   assert Decimal(row[1]) == Decimal("200.00"), "Total staked should be 200 EUR"
   assert Decimal(row[2]) == Decimal("5.00"), "ROI should be 5% (10/200 * 100)"
   assert row[3] == "Safe", f"Should be 'Safe', got '{row[3]}'"

   print("✅ Test Case 3.2.1 PASSED")
   ```

**Expected Results:**
- ✅ Worst-case profit: 10.00 EUR
- ✅ Total staked: 200.00 EUR
- ✅ ROI: 5.00%
- ✅ Risk classification: **Safe**

---

### Test Case 3.2.2: Low ROI Classification (0% < ROI < 1%)

**Objective:** Verify Low ROI classification for marginal profit

**Test Steps:**

1. **Create Low Profit Surebet**
   ```python
   # OVER bet: 100 EUR @ 2.005 = 200.50 EUR payout
   cursor = conn.execute("""
       INSERT INTO bets (
           associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
           status, stake_eur, odds, currency, payout, market_code, period_scope,
           line_value, side, is_supported
       )
       VALUES (?, ?, ?, ?, 'verified', '100.00', '2.005', 'EUR', '200.50',
               'TOTALS', 'FULL_TIME', '4.5', 'OVER', 1)
   """, (alice_id, alice_bookmaker, event_id, market_id))

   # UNDER bet: 100 EUR @ 2.005 = 200.50 EUR payout
   cursor = conn.execute("""
       INSERT INTO bets (
           associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
           status, stake_eur, odds, currency, payout, market_code, period_scope,
           line_value, side, is_supported
       )
       VALUES (?, ?, ?, ?, 'verified', '100.00', '2.005', 'EUR', '200.50',
               'TOTALS', 'FULL_TIME', '4.5', 'UNDER', 1)
   """, (bob_id, bob_bookmaker, event_id, market_id))
   under_id = cursor.lastrowid
   conn.commit()

   matcher = SurebetMatcher(conn)
   surebet_id = matcher.attempt_match(under_id)
   ```

2. **Check Classification**
   ```python
   cursor = conn.execute("""
       SELECT worst_case_profit_eur, roi, risk_classification
       FROM surebets WHERE id = ?
   """, (surebet_id,))
   row = cursor.fetchone()

   print(f"✓ Worst-case profit: {row[0]} EUR")
   print(f"✓ ROI: {row[1]}%")
   print(f"✓ Risk classification: {row[2]}")

   assert Decimal(row[0]) == Decimal("0.50"), "Profit should be 0.50 EUR"
   assert Decimal(row[1]) == Decimal("0.25"), "ROI should be 0.25%"
   assert row[2] == "Low ROI", f"Should be 'Low ROI', got '{row[2]}'"

   print("✅ Test Case 3.2.2 PASSED")
   ```

**Expected Results:**
- ✅ Worst-case profit: 0.50 EUR (positive but small)
- ✅ ROI: 0.25% (less than 1%)
- ✅ Risk classification: **Low ROI**

---

### Test Case 3.2.3: Unsafe Classification (Negative Profit)

**Objective:** Verify Unsafe classification for guaranteed loss

**Test Steps:**

1. **Create Losing Surebet**
   ```python
   # OVER bet: 100 EUR @ 1.80 = 180 EUR payout
   cursor = conn.execute("""
       INSERT INTO bets (
           associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
           status, stake_eur, odds, currency, payout, market_code, period_scope,
           line_value, side, is_supported
       )
       VALUES (?, ?, ?, ?, 'verified', '100.00', '1.80', 'EUR', '180.00',
               'TOTALS', 'FULL_TIME', '5.5', 'OVER', 1)
   """, (alice_id, alice_bookmaker, event_id, market_id))

   # UNDER bet: 100 EUR @ 1.80 = 180 EUR payout
   cursor = conn.execute("""
       INSERT INTO bets (
           associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
           status, stake_eur, odds, currency, payout, market_code, period_scope,
           line_value, side, is_supported
       )
       VALUES (?, ?, ?, ?, 'verified', '100.00', '1.80', 'EUR', '180.00',
               'TOTALS', 'FULL_TIME', '5.5', 'UNDER', 1)
   """, (bob_id, bob_bookmaker, event_id, market_id))
   under_id = cursor.lastrowid
   conn.commit()

   matcher = SurebetMatcher(conn)
   surebet_id = matcher.attempt_match(under_id)
   ```

2. **Check Classification**
   ```python
   cursor = conn.execute("""
       SELECT worst_case_profit_eur, roi, risk_classification
       FROM surebets WHERE id = ?
   """, (surebet_id,))
   row = cursor.fetchone()

   print(f"✓ Worst-case profit: {row[0]} EUR")
   print(f"✓ ROI: {row[1]}%")
   print(f"✓ Risk classification: {row[2]}")

   assert Decimal(row[0]) == Decimal("-20.00"), "Profit should be -20 EUR (180 - 200)"
   assert Decimal(row[1]) == Decimal("-10.00"), "ROI should be -10%"
   assert row[2] == "Unsafe", f"Should be 'Unsafe', got '{row[2]}'"

   print("✅ Test Case 3.2.3 PASSED")
   ```

**Expected Results:**
- ✅ Worst-case profit: -20.00 EUR (negative)
- ✅ ROI: -10.00% (negative)
- ✅ Risk classification: **Unsafe**

---

### Test Case 3.2.4: Multi-Currency Risk Calculation

**Objective:** Verify FX conversion in risk calculation

**Test Steps:**

1. **Create Multi-Currency Surebet**
   ```python
   # OVER bet in AUD: 100 AUD @ 2.10 (0.60 EUR/AUD) = 60 EUR stake, 126 EUR payout
   cursor = conn.execute("""
       INSERT INTO bets (
           associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
           status, stake_eur, stake_original, odds, odds_original,
           currency, payout, market_code, period_scope,
           line_value, side, is_supported
       )
       VALUES (?, ?, ?, ?, 'verified', '60.00', '100.00', '2.10', '2.10',
               'AUD', '210.00', 'TOTALS', 'FULL_TIME', '6.5', 'OVER', 1)
   """, (alice_id, alice_bookmaker, event_id, market_id))

   # UNDER bet in GBP: 100 GBP @ 2.10 (1.15 EUR/GBP) = 115 EUR stake, 241.50 EUR payout
   cursor = conn.execute("""
       INSERT INTO bets (
           associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
           status, stake_eur, stake_original, odds, odds_original,
           currency, payout, market_code, period_scope,
           line_value, side, is_supported
       )
       VALUES (?, ?, ?, ?, 'verified', '115.00', '100.00', '2.10', '2.10',
               'GBP', '210.00', 'TOTALS', 'FULL_TIME', '6.5', 'UNDER', 1)
   """, (bob_id, bob_bookmaker, event_id, market_id))
   under_id = cursor.lastrowid
   conn.commit()

   matcher = SurebetMatcher(conn)
   surebet_id = matcher.attempt_match(under_id)
   ```

2. **Verify EUR Conversion**
   ```python
   cursor = conn.execute("""
       SELECT worst_case_profit_eur, total_staked_eur, roi, risk_classification
       FROM surebets WHERE id = ?
   """, (surebet_id,))
   row = cursor.fetchone()

   print(f"✓ Worst-case profit: {row[0]} EUR")
   print(f"✓ Total staked: {row[1]} EUR")
   print(f"✓ ROI: {row[2]}%")
   print(f"✓ Risk classification: {row[3]}")

   # Total staked: 60 + 115 = 175 EUR
   # Profit if A wins: 126 - 175 = -49 EUR
   # Profit if B wins: 241.50 - 175 = 66.50 EUR
   # Worst case: -49 EUR

   assert Decimal(row[1]) == Decimal("175.00"), "Total staked should be 175 EUR"
   assert Decimal(row[0]) == Decimal("-49.00"), "Worst-case should be -49 EUR"
   assert row[3] == "Unsafe", "Should be Unsafe due to negative worst-case"

   print("✅ Test Case 3.2.4 PASSED")
   ```

**Expected Results:**
- ✅ Currencies correctly converted to EUR
- ✅ Total staked: 175.00 EUR (60 + 115)
- ✅ Worst-case profit: -49.00 EUR
- ✅ Risk classification: **Unsafe**

---

## End-to-End Workflow Testing

### Workflow Test: Complete Bet Lifecycle

**Objective:** Test the complete workflow from bet ingestion to matched surebet with risk analysis

**Scenario:** Two operators place opposite bets on the same match

**Test Steps:**

1. **Operator Alice - Upload Bet Screenshot**
   ```python
   # Simulate bet ingestion
   cursor = conn.execute("""
       INSERT INTO bets (
           associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
           status, stake_eur, odds, currency, market_code, period_scope,
           line_value, side, is_supported, screenshot_path, ingestion_source
       )
       VALUES (?, ?, ?, ?, 'incoming', '150.00', '2.15', 'EUR',
               'TOTALS', 'FULL_TIME', '3.5', 'OVER', 1,
               'data/screenshots/test_alice.png', 'manual_upload')
   """, (alice_id, alice_bookmaker, event_id, market_id))
   alice_bet_id = cursor.lastrowid
   conn.commit()

   print(f"✓ Step 1: Alice's bet ingested (ID: {alice_bet_id})")
   print(f"  Status: incoming")
   ```

2. **Operator Reviews and Approves Alice's Bet**
   ```python
   from src.services.bet_verification import BetVerificationService

   service = BetVerificationService(conn)
   service.approve_bet(alice_bet_id, actor="Operator")

   cursor = conn.execute("SELECT status FROM bets WHERE id = ?", (alice_bet_id,))
   status = cursor.fetchone()[0]
   print(f"✓ Step 2: Alice's bet approved")
   print(f"  Status: {status}")
   assert status == "verified"
   ```

3. **Operator Bob - Upload Opposite Bet**
   ```python
   cursor = conn.execute("""
       INSERT INTO bets (
           associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
           status, stake_eur, odds, currency, market_code, period_scope,
           line_value, side, is_supported, screenshot_path, ingestion_source
       )
       VALUES (?, ?, ?, ?, 'incoming', '150.00', '2.05', 'EUR',
               'TOTALS', 'FULL_TIME', '3.5', 'UNDER', 1,
               'data/screenshots/test_bob.png', 'manual_upload')
   """, (bob_id, bob_bookmaker, event_id, market_id))
   bob_bet_id = cursor.lastrowid
   conn.commit()

   print(f"✓ Step 3: Bob's bet ingested (ID: {bob_bet_id})")
   ```

4. **Operator Approves Bob's Bet - Auto-Matching Triggered**
   ```python
   service.approve_bet(bob_bet_id, actor="Operator")

   cursor = conn.execute("SELECT status FROM bets WHERE id = ?", (bob_bet_id,))
   bob_status = cursor.fetchone()[0]
   cursor = conn.execute("SELECT status FROM bets WHERE id = ?", (alice_bet_id,))
   alice_status = cursor.fetchone()[0]

   print(f"✓ Step 4: Bob's bet approved - Auto-matching triggered")
   print(f"  Alice's status: {alice_status}")
   print(f"  Bob's status: {bob_status}")

   assert alice_status == "matched", "Alice's bet should be matched"
   assert bob_status == "matched", "Bob's bet should be matched"
   ```

5. **Verify Surebet Created with Risk Analysis**
   ```python
   cursor = conn.execute("""
       SELECT s.id, s.worst_case_profit_eur, s.total_staked_eur,
              s.roi, s.risk_classification
       FROM surebets s
       JOIN surebet_bets sb ON s.id = sb.surebet_id
       WHERE sb.bet_id = ?
   """, (bob_bet_id,))
   row = cursor.fetchone()

   surebet_id = row[0]
   print(f"✓ Step 5: Surebet created (ID: {surebet_id})")
   print(f"  Worst-case profit: {row[1]} EUR")
   print(f"  Total staked: {row[2]} EUR")
   print(f"  ROI: {row[3]}%")
   print(f"  Risk: {row[4]}")

   # Verify both bets linked
   cursor = conn.execute("""
       SELECT COUNT(*) FROM surebet_bets WHERE surebet_id = ?
   """, (surebet_id,))
   bet_count = cursor.fetchone()[0]
   assert bet_count == 2, f"Surebet should have 2 bets, found {bet_count}"

   print("✅ End-to-End Workflow Test PASSED")
   ```

**Expected Results:**
- ✅ Alice's bet: `incoming` → `verified` → `matched`
- ✅ Bob's bet: `incoming` → `matched` (direct)
- ✅ Surebet created with both bets
- ✅ Risk analysis automatically calculated
- ✅ Classification displayed (Safe/Low ROI/Unsafe)

---

## Edge Cases & Error Handling

### Edge Case 1: Unsupported Bet Type

**Test:** Verify unsupported bets are not matched

```python
# Create multi bet (unsupported)
cursor = conn.execute("""
    INSERT INTO bets (
        associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
        status, stake_eur, odds, currency, market_code, period_scope,
        line_value, side, is_supported, is_multi
    )
    VALUES (?, ?, ?, ?, 'verified', '100.00', '5.50', 'EUR',
            'TOTALS', 'FULL_TIME', '2.5', 'OVER', 0, 1)
""", (alice_id, alice_bookmaker, event_id, market_id))
multi_bet_id = cursor.lastrowid
conn.commit()

# Try to match - should return None
matcher = SurebetMatcher(conn)
result = matcher.attempt_match(multi_bet_id)

print(f"✓ Match result for unsupported bet: {result}")
assert result is None, "Unsupported bets should not match"

print("✅ Edge Case 1 PASSED")
```

---

### Edge Case 2: Idempotent Matching

**Test:** Re-running match on already matched bet returns same surebet

```python
# Create and match bets
cursor = conn.execute("""
    INSERT INTO bets (
        associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
        status, stake_eur, odds, currency, market_code, period_scope,
        line_value, side, is_supported
    )
    VALUES (?, ?, ?, ?, 'verified', '100.00', '2.10', 'EUR',
            'TOTALS', 'FULL_TIME', '7.5', 'OVER', 1)
""", (alice_id, alice_bookmaker, event_id, market_id))

cursor = conn.execute("""
    INSERT INTO bets (
        associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
        status, stake_eur, odds, currency, market_code, period_scope,
        line_value, side, is_supported
    )
    VALUES (?, ?, ?, ?, 'verified', '100.00', '2.10', 'EUR',
            'TOTALS', 'FULL_TIME', '7.5', 'UNDER', 1)
""", (bob_id, bob_bookmaker, event_id, market_id))
bet_id = cursor.lastrowid
conn.commit()

matcher = SurebetMatcher(conn)

# First match
surebet_1 = matcher.attempt_match(bet_id)

# Second match (idempotent)
surebet_2 = matcher.attempt_match(bet_id)

print(f"✓ First match: {surebet_1}")
print(f"✓ Second match: {surebet_2}")
assert surebet_1 == surebet_2, "Should return same surebet ID"

print("✅ Edge Case 2 PASSED")
```

---

### Edge Case 3: Missing FX Rate Fallback

**Test:** Verify fallback to last known FX rate

```python
from datetime import date, timedelta

# Add AUD rate for yesterday
yesterday = date.today() - timedelta(days=1)
cursor = conn.execute("""
    INSERT INTO fx_rates_daily (currency_code, rate_to_eur, fetched_at_utc, date)
    VALUES ('NZD', '0.55', ?, ?)
""", (datetime.now(UTC).isoformat().replace("+00:00", "Z"),
      yesterday.strftime("%Y-%m-%d")))
conn.commit()

# Create bet in NZD (no rate for today)
cursor = conn.execute("""
    INSERT INTO bets (
        associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
        status, stake_eur, stake_original, odds, currency, market_code,
        period_scope, line_value, side, is_supported
    )
    VALUES (?, ?, ?, ?, 'verified', '55.00', '100.00', '2.10', 'NZD',
            'TOTALS', 'FULL_TIME', '8.5', 'OVER', 1)
""", (alice_id, alice_bookmaker, event_id, market_id))

cursor = conn.execute("""
    INSERT INTO bets (
        associate_id, bookmaker_id, canonical_event_id, canonical_market_id,
        status, stake_eur, odds, currency, market_code,
        period_scope, line_value, side, is_supported
    )
    VALUES (?, ?, ?, ?, 'verified', '100.00', '2.10', 'EUR',
            'TOTALS', 'FULL_TIME', '8.5', 'UNDER', 1)
""", (bob_id, bob_bookmaker, event_id, market_id))
bet_id = cursor.lastrowid
conn.commit()

# Should use yesterday's rate with warning
matcher = SurebetMatcher(conn)
surebet_id = matcher.attempt_match(bet_id)

print(f"✓ Surebet created using fallback FX rate: {surebet_id}")
assert surebet_id is not None, "Should create surebet with fallback rate"

print("✅ Edge Case 3 PASSED")
```

---

## Regression Testing Checklist

Run this checklist to ensure all previous functionality still works:

### Database & Schema
- [ ] All 14 tables exist
- [ ] Foreign key constraints enabled
- [ ] Ledger append-only triggers work
- [ ] Surebet_bets side immutable trigger works
- [ ] New risk columns exist in surebets table

### Bet Verification (Epic 2)
- [ ] Can approve incoming bets
- [ ] Can reject incoming bets with reason
- [ ] Audit log created on approval/rejection
- [ ] Field validation works (positive stake, minimum odds)
- [ ] Canonical event auto-creation works

### Matching (Epic 3.1)
- [ ] OVER/UNDER matching works
- [ ] YES/NO matching works
- [ ] TEAM_A/TEAM_B matching works
- [ ] Side assignment deterministic (OVER→A, UNDER→B)
- [ ] Matching requires same event/market/period/line
- [ ] Multiple bets can join same surebet
- [ ] Unsupported bets excluded from matching
- [ ] Idempotent matching (re-run returns same result)

### Risk Calculation (Epic 3.2)
- [ ] Safe classification (profit >= 0, ROI >= 1%)
- [ ] Low ROI classification (profit >= 0, ROI < 1%)
- [ ] Unsafe classification (profit < 0)
- [ ] Multi-currency EUR conversion works
- [ ] FX rate fallback works
- [ ] Risk auto-calculated after matching
- [ ] All values stored as Decimal (no float errors)

### Unit Tests
- [ ] Run full test suite: `python -m pytest tests/unit/ -v`
- [ ] All 187+ tests pass
- [ ] No test failures or errors

---

## Test Summary Template

After completing all tests, fill out this summary:

```
EPIC 3 MANUAL TEST SUMMARY
==========================
Date: _____________
Tester: _____________

Test Case Results:
------------------
✅ 3.1.1: Basic Over/Under Matching       [ PASS / FAIL ]
✅ 3.1.2: YES/NO Matching                  [ PASS / FAIL ]
✅ 3.1.3: Matching Criteria Validation     [ PASS / FAIL ]
✅ 3.1.4: Multiple Bets on Same Side       [ PASS / FAIL ]
✅ 3.2.1: Safe Classification              [ PASS / FAIL ]
✅ 3.2.2: Low ROI Classification           [ PASS / FAIL ]
✅ 3.2.3: Unsafe Classification            [ PASS / FAIL ]
✅ 3.2.4: Multi-Currency Risk Calculation  [ PASS / FAIL ]
✅ End-to-End Workflow                     [ PASS / FAIL ]
✅ Edge Case 1: Unsupported Bets           [ PASS / FAIL ]
✅ Edge Case 2: Idempotent Matching        [ PASS / FAIL ]
✅ Edge Case 3: FX Rate Fallback           [ PASS / FAIL ]

Regression Checklist:
---------------------
Database & Schema:     [ ___ / 5 ] checks passed
Bet Verification:      [ ___ / 5 ] checks passed
Matching:              [ ___ / 8 ] checks passed
Risk Calculation:      [ ___ / 7 ] checks passed
Unit Tests:            [ ___ / 2 ] checks passed

Issues Found:
-------------
1. _____________________________________________
2. _____________________________________________
3. _____________________________________________

Overall Status: [ PASS / FAIL / PARTIAL ]

Notes:
------
__________________________________________________
__________________________________________________
```

---

**End of Manual Testing Guide**
