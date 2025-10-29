# Settlement Math Specification

**Parent Document**: [PRD Main](../prd.md)
**Version**: v4
**Last Updated**: 2025-10-29

---

## Overview

This document defines the exact mathematical formulas used for surebet settlement, equal-split profit distribution, admin share logic, and reconciliation calculations. These formulas are **contractual** — the system MUST implement them exactly as specified.

---

## Core Principles

1. **Equal-Split Settlement** (System Law #3): All participants get equal slices of profit/loss
2. **Admin Share Logic**: If admin didn't stake, they still get exactly one seat (and also eat losses)
3. **VOID Handling** (System Law #4): VOID participants still participate in split (net_gain_eur = 0)
4. **Frozen FX** (System Law #2): All calculations use `fx_rate_snapshot` from ledger row creation

---

## 1. Per-Bet P/L Calculation (in EUR)

Each bet's net gain/loss is converted to EUR using the `fx_rate_snapshot` at settlement time.

### Input Fields (from `bets` table)
- `stake_native` (TEXT Decimal, e.g., "50.00")
- `odds_normalized` (TEXT Decimal, e.g., "1.90")
- `native_currency` (TEXT, e.g., "AUD")
- `settlement_state` (TEXT: "WON" | "LOST" | "VOID")

### FX Conversion
```python
# Get latest FX rate for native_currency from fx_rates_daily
fx_rate_snapshot = get_latest_fx_rate(native_currency)  # EUR per 1 unit of native currency

# Convert stake to EUR
stake_eur = Decimal(stake_native) * fx_rate_snapshot
```

### Net Gain Calculation

#### Case 1: WON
```python
payout_native = Decimal(stake_native) * Decimal(odds_normalized)
payout_eur = payout_native * fx_rate_snapshot
net_gain_eur = payout_eur - stake_eur
```

**Example**:
- Stake: 50.00 AUD @ 1.90 odds
- FX: 0.62 EUR/AUD
- Payout: 50.00 * 1.90 = 95.00 AUD = 58.90 EUR
- Stake: 50.00 AUD = 31.00 EUR
- Net Gain: 58.90 - 31.00 = **27.90 EUR**

#### Case 2: LOST
```python
net_gain_eur = -stake_eur
```

**Example**:
- Stake: 50.00 AUD
- FX: 0.62 EUR/AUD
- Stake: 50.00 AUD = 31.00 EUR
- Net Gain: **-31.00 EUR**

#### Case 3: VOID
```python
net_gain_eur = Decimal("0.00")
```

**Example**:
- Stake: 50.00 AUD (refunded)
- Net Gain: **0.00 EUR**

**Important**: VOID bets still participate in split calculation (System Law #4).

---

## 2. Surebet Aggregate P/L

Sum all bets' net gains within the surebet.

### Formula
```python
surebet_profit_eur = sum(bet.net_gain_eur for bet in surebet.all_bets)
```

**Note**: `surebet_profit_eur` can be **positive** (profit) or **negative** (loss).

### Example
**Surebet with 2 bets**:
- Bet A (OVER 6.5): 50 AUD @ 1.90 → WON → +27.90 EUR
- Bet B (UNDER 6.5): 100 GBP @ 2.00 → LOST → -116.00 EUR
- **surebet_profit_eur** = 27.90 + (-116.00) = **-88.10 EUR** (loss)

---

## 3. Participant Count (N) — Admin Seat Logic

Determine how many equal slices to create.

### Rules (System Law #3)

#### Rule 1: Admin DID stake
If the admin (operator) placed at least one bet in this surebet:
```python
N = len(betting_participants)
```

**Example**:
- Surebet has 3 associates (including admin)
- Admin staked → N = **3**

#### Rule 2: Admin did NOT stake
If the admin did NOT place any bet in this surebet:
```python
N = len(betting_participants) + 1
```

**Example**:
- Surebet has 2 associates (Alice, Bob)
- Admin didn't stake → N = 2 + 1 = **3**
- Admin gets one extra "coordinator seat"

### Important
- The admin's extra seat participates in **both upside and downside**
- If `surebet_profit_eur < 0` (loss), admin eats one equal slice of the loss
- There is **never** a second skim or fee (System Law #3)

---

## 4. Equal-Split Share

Divide total profit/loss equally among all participants.

### Formula
```python
per_surebet_share_eur = surebet_profit_eur / N
```

### Example 1: Profit with Admin Coordinator Seat
- `surebet_profit_eur` = +100.00 EUR
- 2 associates staked (Alice, Bob)
- Admin didn't stake → N = 3
- **per_surebet_share_eur** = 100.00 / 3 = **+33.33 EUR** (each)

### Example 2: Loss with Admin Coordinator Seat
- `surebet_profit_eur` = -90.00 EUR
- 2 associates staked (Alice, Bob)
- Admin didn't stake → N = 3
- **per_surebet_share_eur** = -90.00 / 3 = **-30.00 EUR** (each)

**Critical**: Admin also eats **-30.00 EUR** of the loss.

### Example 3: Admin Staked
- `surebet_profit_eur` = +100.00 EUR
- 3 associates staked (Alice, Bob, Admin)
- Admin staked → N = 3
- **per_surebet_share_eur** = 100.00 / 3 = **+33.33 EUR** (each)

---

## 5. Principal Returned (per Associate)

Calculate how much of each participant's stake effectively came back to them via WON or VOID bets.

### Formula
```python
# For each associate in the surebet:
principal_returned_eur = sum(
    stake_eur for bet in associate.bets_in_surebet
    if bet.settlement_state in ("WON", "VOID")
)
```

### Example
**Associate Alice has 2 bets in surebet**:
- Bet 1: 50 AUD @ 1.90 (WON) → stake_eur = 31.00 EUR
- Bet 2: 30 AUD @ 2.10 (VOID) → stake_eur = 18.60 EUR
- **principal_returned_eur** = 31.00 + 18.60 = **49.60 EUR**

**Associate Bob has 1 bet in surebet**:
- Bet 3: 100 GBP @ 2.00 (LOST) → stake_eur = 0 EUR (lost)
- **principal_returned_eur** = **0.00 EUR**

---

## 6. Entitlement Component (per Associate, per Surebet)

Each associate's total entitlement from this surebet combines their principal returned plus their equal-split share.

### Formula
```python
entitlement_component_eur = principal_returned_eur + per_surebet_share_eur
```

### Example
**Surebet with profit +100 EUR, N=3**:

| Associate | Bets | Principal Returned | Per-Surebet Share | Entitlement Component |
|-----------|------|-------------------|-------------------|----------------------|
| Alice | 2 WON | 49.60 EUR | +33.33 EUR | 82.93 EUR |
| Bob | 1 LOST | 0.00 EUR | +33.33 EUR | 33.33 EUR |
| Admin (coordinator) | None | 0.00 EUR | +33.33 EUR | 33.33 EUR |

**Total entitlement**: 82.93 + 33.33 + 33.33 = **149.59 EUR** ≈ 49.60 (principal) + 100.00 (profit) ✓

---

## 7. Ledger Entry Fields (BET_RESULT)

When writing `ledger_entries` rows during settlement, include these calculated fields:

### Per Bet Row
```python
ledger_entry = {
    "type": "BET_RESULT",
    "associate_id": bet.associate_id,
    "bookmaker_id": bet.bookmaker_id,
    "surebet_id": surebet.id,
    "bet_id": bet.id,
    "settlement_state": bet.settlement_state,  # "WON" | "LOST" | "VOID"
    "amount_native": bet.stake_native,
    "native_currency": bet.native_currency,
    "fx_rate_snapshot": fx_rate_snapshot,  # frozen at settlement time
    "amount_eur": net_gain_eur,  # calculated above
    "principal_returned_eur": stake_eur if settlement_state in ("WON", "VOID") else Decimal("0"),
    "per_surebet_share_eur": per_surebet_share_eur,  # same for all participants
    "settlement_batch_id": batch_id,  # same for all rows in this confirm click
    "note": f"settlement batch {batch_id}",
    "created_at_utc": now_utc_iso8601(),
    "created_by": "local_user"
}
```

### Admin Coordinator Seat (if admin didn't stake)
If admin didn't stake, create ONE extra ledger row for the admin's coordinator seat:

```python
admin_ledger_entry = {
    "type": "BET_RESULT",
    "associate_id": admin.id,
    "bookmaker_id": None,  # admin didn't place a bet
    "surebet_id": surebet.id,
    "bet_id": None,  # no physical bet
    "settlement_state": None,  # coordinator seat, not a bet
    "amount_native": "0.00",
    "native_currency": admin.home_currency,
    "fx_rate_snapshot": fx_rate_snapshot,
    "amount_eur": "0.00",  # no actual bet
    "principal_returned_eur": "0.00",
    "per_surebet_share_eur": per_surebet_share_eur,  # admin's equal slice
    "settlement_batch_id": batch_id,
    "note": f"admin coordinator seat - settlement batch {batch_id}",
    "created_at_utc": now_utc_iso8601(),
    "created_by": "local_user"
}
```

---

## 8. All-VOID Edge Case

If **all bets** in a surebet are VOID:
- `surebet_profit_eur` = 0.00 EUR
- `per_surebet_share_eur` = 0.00 EUR
- Still write BET_RESULT rows for each bet with:
  - `amount_eur` = 0.00
  - `per_surebet_share_eur` = 0.00
  - Correct `principal_returned_eur` (stakes refunded)

**Why**: Preserves entitlement history continuity (System Law #4).

### Example
**All-VOID Surebet**:
- Bet A: 50 AUD (VOID) → principal_returned = 31.00 EUR
- Bet B: 100 GBP (VOID) → principal_returned = 116.00 EUR
- `surebet_profit_eur` = 0.00 EUR
- N = 2 (both staked)
- `per_surebet_share_eur` = 0.00 / 2 = **0.00 EUR**

**Ledger Entries**:
- Alice: principal_returned = 31.00, per_surebet_share = 0.00 → entitlement = 31.00 EUR
- Bob: principal_returned = 116.00, per_surebet_share = 0.00 → entitlement = 116.00 EUR

---

## 9. Reconciliation Calculations

These are **aggregate queries** over `ledger_entries` to determine who's overholding vs. short.

### 9.1 NET_DEPOSITS_EUR

**Formula**:
```sql
SELECT
    SUM(CASE WHEN type='DEPOSIT' THEN CAST(amount_eur AS REAL) ELSE 0 END) -
    SUM(CASE WHEN type='WITHDRAWAL' THEN CAST(amount_eur AS REAL) ELSE 0 END)
FROM ledger_entries
WHERE associate_id = :associate_id
```

**Python**:
```python
def calc_net_deposits_eur(associate_id):
    deposits = sum(
        Decimal(e.amount_eur) for e in ledger_entries
        if e.associate_id == associate_id and e.type == "DEPOSIT"
    )
    withdrawals = sum(
        Decimal(e.amount_eur) for e in ledger_entries
        if e.associate_id == associate_id and e.type == "WITHDRAWAL"
    )
    return deposits - withdrawals
```

**Meaning**: How much cash the associate personally funded into the operation.

---

### 9.2 SHOULD_HOLD_EUR (Entitlement)

**Formula**:
```sql
SELECT
    SUM(CAST(principal_returned_eur AS REAL) + CAST(per_surebet_share_eur AS REAL))
FROM ledger_entries
WHERE associate_id = :associate_id AND type = 'BET_RESULT'
```

**Python**:
```python
def calc_should_hold_eur(associate_id):
    return sum(
        Decimal(e.principal_returned_eur or "0") + Decimal(e.per_surebet_share_eur or "0")
        for e in ledger_entries
        if e.associate_id == associate_id and e.type == "BET_RESULT"
    )
```

**Meaning**: How much of the pool belongs to them after all settled surebets.

**Intuition**: "If we froze the world after all settled bets, this is how much of the pot is yours."

---

### 9.3 CURRENT_HOLDING_EUR

**Formula**:
```python
def calc_current_holding_eur(associate_id):
    total = Decimal("0")
    for e in ledger_entries:
        if e.associate_id != associate_id:
            continue

        if e.type == "BET_RESULT":
            # Add principal returned + equal-split share
            total += Decimal(e.principal_returned_eur or "0") + Decimal(e.per_surebet_share_eur or "0")
        elif e.type == "DEPOSIT":
            # Add deposit
            total += Decimal(e.amount_eur)
        elif e.type == "WITHDRAWAL":
            # Subtract withdrawal
            total -= Decimal(e.amount_eur)
        elif e.type == "BOOKMAKER_CORRECTION":
            # Add correction (can be positive or negative)
            total += Decimal(e.amount_eur)

    return total
```

**Meaning**: What the model thinks they're physically holding across all their bookmakers right now.

---

### 9.4 DELTA

**Formula**:
```python
DELTA = CURRENT_HOLDING_EUR - SHOULD_HOLD_EUR
```

**Interpretation**:

| DELTA Value | Meaning | Color | Action |
|-------------|---------|-------|--------|
| `> 0` | Holding **more** than entitlement | Red | "Holding +€X more than entitlement (group float you should collect)" |
| `≈ 0` | Balanced | Green | "Balanced" |
| `< 0` | Holding **less** than entitlement | Orange | "Holding -€X less than entitlement (they're owed €X / someone else is parking their money)" |

---

## 10. Monthly Statements Calculations

For partner-facing reports at period end (e.g., "End of October 2025").

### 10.1 NET_DEPOSITS_EUR
Same as reconciliation (see 9.1), but filtered up to cutoff timestamp:
```sql
WHERE associate_id = :associate_id AND created_at_utc <= :cutoff_utc
```

### 10.2 SHOULD_HOLD_EUR
Same as reconciliation (see 9.2), but filtered up to cutoff timestamp:
```sql
WHERE associate_id = :associate_id AND type = 'BET_RESULT' AND created_at_utc <= :cutoff_utc
```

### 10.3 RAW_PROFIT_EUR

**Formula**:
```python
RAW_PROFIT_EUR = SHOULD_HOLD_EUR - NET_DEPOSITS_EUR
```

**Meaning**: How far ahead the associate is compared to what they funded.

**Can be positive or negative**:
- Positive: They're up
- Negative: They're down (admin also eats losses)

### 10.4 Human-Readable Explanation

**Template**:
```
You funded €{NET_DEPOSITS_EUR} total.
Right now you're entitled to €{SHOULD_HOLD_EUR}.
That means you're {up/down} €{abs(RAW_PROFIT_EUR)} overall.
Our deal is 50/50, so €{abs(RAW_PROFIT_EUR) / 2} each.
```

**Example (Profit)**:
```
You funded €1,000.00 total.
Right now you're entitled to €1,150.00.
That means you're up €150.00 overall.
Our deal is 50/50, so €75.00 each.
```

**Example (Loss)**:
```
You funded €1,000.00 total.
Right now you're entitled to €950.00.
That means you're down €50.00 overall.
Our deal is 50/50, so €25.00 each (loss split equally).
```

---

## 11. FX Snapshot Logic (System Law #2)

### When to Capture FX Snapshot
At the moment of creating a `ledger_entries` row:
1. Get latest known FX rate from `fx_rates_daily` for the `native_currency`
2. If no rate exists for today, reuse the most recent known rate
3. Store that rate in `fx_rate_snapshot` field

### Never Re-FX the Past
- All reconciliation math uses the `fx_rate_snapshot` from each ledger row
- We never "revalue" old rows if FX changes
- This ensures audit trail stability (System Law #2)

### Python Example
```python
def get_fx_rate_snapshot(native_currency: str) -> Decimal:
    """Get latest FX rate for native_currency -> EUR"""
    # Query fx_rates_daily for latest rate
    latest_rate = db.query(
        "SELECT rate_to_eur FROM fx_rates_daily "
        "WHERE currency_code = ? "
        "ORDER BY fetched_at_utc DESC LIMIT 1",
        (native_currency,)
    ).fetchone()

    if latest_rate:
        return Decimal(latest_rate["rate_to_eur"])
    else:
        raise ValueError(f"No FX rate found for {native_currency}")
```

---

## 12. Worked Example: Complete Settlement

### Scenario
**Surebet**: First Half Total Corners Over/Under 6.5
- **Side A (OVER 6.5)**:
  - Bet 1: Alice, 50 AUD @ 1.90 (Bet365) → **WON**
  - Bet 2: Bob, 30 AUD @ 1.95 (Sportsbet) → **WON**
- **Side B (UNDER 6.5)**:
  - Bet 3: Charlie, 100 GBP @ 2.00 (Ladbrokes) → **LOST**

**Admin**: Did NOT stake in this surebet (coordinator role only)

**FX Rates** (at settlement):
- AUD → EUR: 0.62
- GBP → EUR: 1.16

---

### Step 1: Calculate Per-Bet P/L

**Bet 1 (Alice, WON)**:
- Stake: 50 AUD = 50 * 0.62 = 31.00 EUR
- Payout: 50 * 1.90 = 95.00 AUD = 95 * 0.62 = 58.90 EUR
- Net Gain: 58.90 - 31.00 = **+27.90 EUR**

**Bet 2 (Bob, WON)**:
- Stake: 30 AUD = 30 * 0.62 = 18.60 EUR
- Payout: 30 * 1.95 = 58.50 AUD = 58.5 * 0.62 = 36.27 EUR
- Net Gain: 36.27 - 18.60 = **+17.67 EUR**

**Bet 3 (Charlie, LOST)**:
- Stake: 100 GBP = 100 * 1.16 = 116.00 EUR
- Payout: 0 (lost)
- Net Gain: **-116.00 EUR**

---

### Step 2: Calculate Surebet Profit

```python
surebet_profit_eur = 27.90 + 17.67 + (-116.00) = -70.43 EUR
```

**Result**: **Loss of 70.43 EUR**

---

### Step 3: Determine Participant Count (N)

Participants who staked: Alice, Bob, Charlie (3)
Admin: Did NOT stake

**N = 3 (participants) + 1 (admin coordinator seat) = 4**

---

### Step 4: Calculate Equal-Split Share

```python
per_surebet_share_eur = -70.43 / 4 = -17.61 EUR (each)
```

**Result**: Each participant (including admin) eats **-17.61 EUR** of the loss.

---

### Step 5: Calculate Principal Returned

**Alice**:
- Bet 1 WON → principal returned = 31.00 EUR

**Bob**:
- Bet 2 WON → principal returned = 18.60 EUR

**Charlie**:
- Bet 3 LOST → principal returned = 0.00 EUR

**Admin**:
- No bets → principal returned = 0.00 EUR

---

### Step 6: Calculate Entitlement Component

| Associate | Principal Returned | Per-Surebet Share | Entitlement Component |
|-----------|-------------------|-------------------|----------------------|
| Alice | 31.00 EUR | -17.61 EUR | 13.39 EUR |
| Bob | 18.60 EUR | -17.61 EUR | 0.99 EUR |
| Charlie | 0.00 EUR | -17.61 EUR | -17.61 EUR |
| Admin | 0.00 EUR | -17.61 EUR | -17.61 EUR |

**Total**: 13.39 + 0.99 + (-17.61) + (-17.61) = **-20.84 EUR**
Wait, that doesn't match. Let me recalculate...

**Check**:
- Total stakes returned: 31.00 + 18.60 = 49.60 EUR
- Total profit: -70.43 EUR
- Total entitlement: 49.60 + (-70.43) = **-20.83 EUR** ✓

---

### Step 7: Write Ledger Entries

**Settlement Batch ID**: `batch_2025_10_29_001`

**Bet 1 (Alice)**:
```python
{
    "type": "BET_RESULT",
    "associate_id": 1,  # Alice
    "bookmaker_id": 1,  # Bet365
    "surebet_id": 100,
    "bet_id": 1,
    "settlement_state": "WON",
    "amount_native": "50.00",
    "native_currency": "AUD",
    "fx_rate_snapshot": "0.62",
    "amount_eur": "27.90",
    "principal_returned_eur": "31.00",
    "per_surebet_share_eur": "-17.61",
    "settlement_batch_id": "batch_2025_10_29_001",
    "note": "settlement batch batch_2025_10_29_001",
    "created_at_utc": "2025-10-29T18:00:00Z",
    "created_by": "local_user"
}
```

**Bet 2 (Bob)**:
```python
{
    "type": "BET_RESULT",
    "associate_id": 2,  # Bob
    "bookmaker_id": 2,  # Sportsbet
    "surebet_id": 100,
    "bet_id": 2,
    "settlement_state": "WON",
    "amount_native": "30.00",
    "native_currency": "AUD",
    "fx_rate_snapshot": "0.62",
    "amount_eur": "17.67",
    "principal_returned_eur": "18.60",
    "per_surebet_share_eur": "-17.61",
    "settlement_batch_id": "batch_2025_10_29_001",
    "note": "settlement batch batch_2025_10_29_001",
    "created_at_utc": "2025-10-29T18:00:00Z",
    "created_by": "local_user"
}
```

**Bet 3 (Charlie)**:
```python
{
    "type": "BET_RESULT",
    "associate_id": 3,  # Charlie
    "bookmaker_id": 3,  # Ladbrokes
    "surebet_id": 100,
    "bet_id": 3,
    "settlement_state": "LOST",
    "amount_native": "100.00",
    "native_currency": "GBP",
    "fx_rate_snapshot": "1.16",
    "amount_eur": "-116.00",
    "principal_returned_eur": "0.00",
    "per_surebet_share_eur": "-17.61",
    "settlement_batch_id": "batch_2025_10_29_001",
    "note": "settlement batch batch_2025_10_29_001",
    "created_at_utc": "2025-10-29T18:00:00Z",
    "created_by": "local_user"
}
```

**Admin Coordinator Seat**:
```python
{
    "type": "BET_RESULT",
    "associate_id": 0,  # Admin
    "bookmaker_id": None,
    "surebet_id": 100,
    "bet_id": None,
    "settlement_state": None,
    "amount_native": "0.00",
    "native_currency": "EUR",
    "fx_rate_snapshot": "1.00",
    "amount_eur": "0.00",
    "principal_returned_eur": "0.00",
    "per_surebet_share_eur": "-17.61",
    "settlement_batch_id": "batch_2025_10_29_001",
    "note": "admin coordinator seat - settlement batch batch_2025_10_29_001",
    "created_at_utc": "2025-10-29T18:00:00Z",
    "created_by": "local_user"
}
```

---

### Step 8: Update Surebet & Bets Status

```python
# Mark surebet as settled
UPDATE surebets SET status='settled', updated_at_utc='2025-10-29T18:00:00Z' WHERE id=100;

# Mark bets as settled
UPDATE bets SET status='settled', settlement_state='WON', updated_at_utc='2025-10-29T18:00:00Z' WHERE id=1;
UPDATE bets SET status='settled', settlement_state='WON', updated_at_utc='2025-10-29T18:00:00Z' WHERE id=2;
UPDATE bets SET status='settled', settlement_state='LOST', updated_at_utc='2025-10-29T18:00:00Z' WHERE id=3;
```

---

**End of Settlement Math Specification**
