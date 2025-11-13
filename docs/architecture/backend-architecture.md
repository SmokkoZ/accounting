# Backend Architecture

**Version:** v4
**Last Updated:** 2025-10-29
**Parent Document:** [Architecture Overview](../architecture.md)

---

## Overview

The backend is a **service-oriented Python application** with clear separation of concerns:
- **Core**: Configuration, database, shared types
- **Services**: Business logic (ingestion, matching, settlement, reconciliation)
- **Integrations**: External APIs (Telegram, OpenAI, FX)
- **Models**: Domain entities (Bet, Surebet, LedgerEntry)

---

## Service Layer Structure

```
src/
├── core/
│   ├── config.py               # Environment config, API keys
│   ├── database.py             # SQLite connection manager
│   └── types.py                # Shared type definitions (Decimal, enums)
├── services/
│   ├── bet_ingestion.py        # FR-1: OCR pipeline, bet creation
│   ├── bet_verification.py     # FR-2: Approval workflow, canonical event auto-creation, audit log
│   ├── surebet_matcher.py      # FR-3: Deterministic matching logic
│   ├── surebet_calculator.py   # FR-4: ROI calculation
│   ├── coverage_service.py     # FR-5: Coverage proof distribution
│   ├── settlement_engine.py    # FR-6: Core settlement math
│   ├── ledger_service.py       # Ledger entry creation, queries
│   ├── fx_manager.py           # FX rate caching, conversions
│   └── reconciliation.py       # FR-8: Health check calculations
├── integrations/
│   ├── telegram_bot.py         # Telegram polling loop, handlers
│   ├── openai_client.py        # GPT-4o OCR + normalization
│   └── fx_api_client.py        # External FX rate fetching
├── models/
│   ├── bet.py                  # Bet domain model
│   ├── surebet.py              # Surebet domain model
│   ├── ledger_entry.py         # Ledger entry domain model
│   └── enums.py                # BetStatus, SettlementState, etc.
└── utils/
    ├── decimal_helpers.py      # Decimal arithmetic utilities
    ├── datetime_helpers.py     # UTC ISO8601 formatting
    └── logging_config.py       # Structured logging setup
```

---

## Core Services

### 1. Bet Ingestion Service (FR-1)

**Responsibility:** Transform screenshots into structured bet records

**File:** `src/services/bet_ingestion.py`

**Key Methods:**

```python
class BetIngestionService:
    def __init__(self):
        self.db = get_db_connection()
        self.openai_client = OpenAIClient()

    def ingest_telegram_screenshot(
        self,
        screenshot_path: str,
        associate_id: int,
        bookmaker_id: int,
        telegram_message_id: int
    ) -> int:
        """
        1. Save screenshot to data/screenshots/ with unique filename
        2. Call OpenAI GPT-4o for OCR + normalization
        3. Create bets row with status='incoming'
        4. Return bet_id

        Filename format: {timestamp}_{associate_id}_{bookmaker_id}.png
        """
        # Save screenshot
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{associate_id}_{bookmaker_id}.png"
        screenshot_full_path = os.path.join("data/screenshots", filename)
        shutil.copy(screenshot_path, screenshot_full_path)

        # OCR extraction
        extracted_data = self.openai_client.extract_bet_from_screenshot(screenshot_full_path)

        # Create bet record
        cursor = self.db.cursor()
        cursor.execute("""
            INSERT INTO bets (
                associate_id, bookmaker_id, status, ingestion_source,
                telegram_message_id, screenshot_path,
                canonical_event_id, market_code, period_scope, line_value, side,
                stake, odds, payout, currency, kickoff_time_utc,
                normalization_confidence, is_multi, is_supported,
                model_version_extraction, model_version_normalization
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            associate_id, bookmaker_id, "incoming", "telegram",
            telegram_message_id, screenshot_full_path,
            extracted_data.get("canonical_event_id"),
            extracted_data.get("market_code"),
            extracted_data.get("period_scope"),
            str(extracted_data.get("line_value")),  # Decimal as TEXT
            extracted_data.get("side"),
            str(extracted_data.get("stake")),  # Decimal as TEXT
            str(extracted_data.get("odds")),
            str(extracted_data.get("payout")),
            extracted_data.get("currency"),
            extracted_data.get("kickoff_time_utc"),
            str(extracted_data.get("normalization_confidence")),
            1 if extracted_data.get("is_multi") else 0,
            0 if extracted_data.get("is_multi") else 1,  # Multi not supported
            extracted_data.get("model_version_extraction"),
            extracted_data.get("model_version_normalization")
        ))
        self.db.commit()
        return cursor.lastrowid

    def ingest_manual_screenshot(
        self,
        screenshot_bytes: bytes,
        associate_id: int,
        bookmaker_id: int,
        note: Optional[str] = None
    ) -> int:
        """
        Same as Telegram path, but ingestion_source='manual_upload'
        """
        # Save screenshot
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{associate_id}_{bookmaker_id}.png"
        screenshot_full_path = os.path.join("data/screenshots", filename)
        with open(screenshot_full_path, "wb") as f:
            f.write(screenshot_bytes)

        # OCR extraction
        extracted_data = self.openai_client.extract_bet_from_screenshot(screenshot_full_path)

        # Create bet record (same as Telegram, but ingestion_source='manual_upload')
        # ... (similar INSERT query)
```

**Error Handling:**
- OCR failure: Create bet with `normalization_confidence=0.0`, note="OCR failed"
- Invalid screenshot: Raise `ValueError`, caught by UI layer

---

### 2. Bet Verification Service (FR-2)

**Responsibility:** Approval/rejection workflow with audit trail

**File:** `src/services/bet_verification.py`

**Key Methods:**

```python
class BetVerificationService:
    def approve_bet(self, bet_id: int, edits: Optional[Dict] = None):
        """
        1. If edits provided, update bet fields
        2. Log edits to verification_audit table
        3. Update bet status to 'verified'
        4. Trigger surebet matching attempt
        """
        cursor = self.db.cursor()

        if edits:
            # Log audit trail
            cursor.execute("""
                INSERT INTO verification_audit (
                    bet_id, field_name, old_value, new_value, edited_by, edited_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, ...)

            # Apply edits
            for field, new_value in edits.items():
                cursor.execute(f"UPDATE bets SET {field} = ? WHERE id = ?", (new_value, bet_id))

        # Mark verified
        cursor.execute("UPDATE bets SET status = 'verified' WHERE id = ?", (bet_id,))
        self.db.commit()

        # Attempt matching
        SurebetMatcher().attempt_match(bet_id)

    def reject_bet(self, bet_id: int, reason: str):
        """
        Mark bet as rejected (no matching attempt)
        """
        cursor = self.db.cursor()
        cursor.execute("UPDATE bets SET status = 'rejected' WHERE id = ?", (bet_id,))
        # Optional: Log rejection reason
        self.db.commit()
```

---

### 3. Surebet Matcher (FR-3)

**Responsibility:** Deterministically group opposite bets into surebets

**File:** `src/services/surebet_matcher.py`

**Key Logic:**

```python
class SurebetMatcher:
    def attempt_match(self, bet_id: int) -> Optional[int]:
        """
        After bet verified, check for opposing bets:
        1. Query verified bets with same canonical_event_id, market_code, period_scope, line_value
        2. Find logical opposite side (OVER vs UNDER, YES vs NO, TEAM_A vs TEAM_B)
        3. If match found:
           - Create/update surebets row
           - Insert surebet_bets links with side='A' or side='B'
           - Update bet status to 'matched'
        4. Return surebet_id or None
        """
        cursor = self.db.cursor()

        # Load current bet
        bet = cursor.execute("SELECT * FROM bets WHERE id = ?", (bet_id,)).fetchone()

        # Find opposing bets
        opposite_side = self._get_opposite_side(bet["side"])
        opposing_bets = cursor.execute("""
            SELECT * FROM bets
            WHERE canonical_event_id = ?
            AND market_code = ?
            AND period_scope = ?
            AND line_value = ?
            AND side = ?
            AND status = 'verified'
        """, (
            bet["canonical_event_id"],
            bet["market_code"],
            bet["period_scope"],
            bet["line_value"],
            opposite_side
        )).fetchall()

        if opposing_bets:
            # Create surebet
            cursor.execute("""
                INSERT INTO surebets (canonical_event_id, market_code, period_scope, line_value, status)
                VALUES (?, ?, ?, ?, 'open')
            """, (bet["canonical_event_id"], bet["market_code"], bet["period_scope"], bet["line_value"]))
            surebet_id = cursor.lastrowid

            # Link current bet (determine side)
            my_side = self.determine_side(bet["side"])
            cursor.execute("""
                INSERT INTO surebet_bets (surebet_id, bet_id, side)
                VALUES (?, ?, ?)
            """, (surebet_id, bet_id, my_side))

            # Link opposing bets
            opposing_side_label = "B" if my_side == "A" else "A"
            for opp_bet in opposing_bets:
                cursor.execute("""
                    INSERT INTO surebet_bets (surebet_id, bet_id, side)
                    VALUES (?, ?, ?)
                """, (surebet_id, opp_bet["id"], opposing_side_label))

            # Mark all bets as matched
            bet_ids = [bet_id] + [b["id"] for b in opposing_bets]
            placeholders = ",".join("?" * len(bet_ids))
            cursor.execute(f"UPDATE bets SET status = 'matched' WHERE id IN ({placeholders})", bet_ids)

            self.db.commit()
            return surebet_id

        return None

    def determine_side(self, side_enum: str) -> Literal["A", "B"]:
        """
        Deterministic side assignment:
        - A: OVER, YES, TEAM_A
        - B: UNDER, NO, TEAM_B

        THIS MAPPING NEVER CHANGES AFTER INITIAL ASSIGNMENT
        """
        if side_enum in ("OVER", "YES", "TEAM_A"):
            return "A"
        elif side_enum in ("UNDER", "NO", "TEAM_B"):
            return "B"
        else:
            raise ValueError(f"Unknown side: {side_enum}")

    def _get_opposite_side(self, side: str) -> str:
        mapping = {
            "OVER": "UNDER",
            "UNDER": "OVER",
            "YES": "NO",
            "NO": "YES",
            "TEAM_A": "TEAM_B",
            "TEAM_B": "TEAM_A"
        }
        return mapping[side]
```

**Critical Invariant:** Once `surebet_bets.side` is set, it NEVER changes (settlement logic depends on this)

---

### 4. Surebet Calculator (FR-4)

**Responsibility:** Calculate worst-case profit and ROI

**File:** `src/services/surebet_calculator.py`

```python
class SurebetCalculator:
    def calculate_roi(self, surebet_id: int) -> Dict[str, Any]:
        """
        1. Load all bets for surebet
        2. Convert all stakes to EUR using cached FX
        3. Calculate profit if Side A wins
        4. Calculate profit if Side B wins
        5. worst_case_profit_eur = min(profit_if_A, profit_if_B)
        6. roi = worst_case_profit_eur / total_staked_eur
        7. Classify: ✅ / 🟡 / ❌
        """
        cursor = self.db.cursor()
        bets = cursor.execute("""
            SELECT b.*, sb.side
            FROM bets b
            JOIN surebet_bets sb ON b.id = sb.bet_id
            WHERE sb.surebet_id = ?
        """, (surebet_id,)).fetchall()

        fx_manager = FXManager()
        total_staked_eur = Decimal("0")
        side_a_payout_eur = Decimal("0")
        side_b_payout_eur = Decimal("0")

        for bet in bets:
            # Convert to EUR
            stake_eur = fx_manager.convert_to_eur(
                Decimal(bet["stake"]),
                bet["currency"],
                fx_manager.get_fx_rate(bet["currency"], date.today())
            )
            payout_eur = fx_manager.convert_to_eur(
                Decimal(bet["payout"]),
                bet["currency"],
                fx_manager.get_fx_rate(bet["currency"], date.today())
            )

            total_staked_eur += stake_eur

            if bet["side"] == "A":
                side_a_payout_eur += payout_eur
            else:
                side_b_payout_eur += payout_eur

        profit_if_a = side_a_payout_eur - total_staked_eur
        profit_if_b = side_b_payout_eur - total_staked_eur
        worst_case_profit_eur = min(profit_if_a, profit_if_b)
        roi = worst_case_profit_eur / total_staked_eur if total_staked_eur > 0 else Decimal("0")

        # Classification
        if worst_case_profit_eur < 0:
            label = "❌"
        elif roi < Decimal("0.02"):  # 2% threshold
            label = "🟡"
        else:
            label = "✅"

        return {
            "worst_case_profit_eur": worst_case_profit_eur,
            "total_staked_eur": total_staked_eur,
            "roi": roi,
            "label": label
        }
```

---

### 5. Settlement Engine (FR-6)

**Responsibility:** Calculate equal-split settlements and write ledger entries

**File:** `src/services/settlement_engine.py`

**Critical Settlement Math:**

```python
class SettlementEngine:
    def settle_surebet(
        self,
        surebet_id: int,
        base_outcome: Literal["A_WON", "B_WON"],
        overrides: Dict[int, str],  # bet_id -> "WON"/"LOST"/"VOID"
        operator_note: str
    ) -> str:
        """
        1. Load all bets for surebet
        2. Apply base outcome + individual overrides
        3. Calculate per-bet net_gain_eur
        4. Calculate surebet_profit_eur = sum(all net_gain_eur)
        5. Determine N (participant count with admin seat logic)
        6. Calculate per_surebet_share_eur = surebet_profit_eur / N
        7. For each associate, write BET_RESULT ledger entry
        8. Mark surebet/bets as settled
        9. Return settlement_batch_id
        """
        cursor = self.db.cursor()
        bets = cursor.execute("""
            SELECT b.*, sb.side
            FROM bets b
            JOIN surebet_bets sb ON b.id = sb.bet_id
            WHERE sb.surebet_id = ?
        """, (surebet_id,)).fetchall()

        # Apply outcomes
        for bet in bets:
            if bet["id"] in overrides:
                bet["outcome"] = overrides[bet["id"]]
            else:
                # Apply base outcome
                if base_outcome == "A_WON":
                    bet["outcome"] = "WON" if bet["side"] == "A" else "LOST"
                else:
                    bet["outcome"] = "WON" if bet["side"] == "B" else "LOST"

        # Calculate net_gain_eur for each bet
        fx_manager = FXManager()
        surebet_profit_eur = Decimal("0")
        bet_results = []

        for bet in bets:
            stake = Decimal(bet["stake"])
            payout = Decimal(bet["payout"])
            fx_rate = fx_manager.get_fx_rate(bet["currency"], date.today())

            if bet["outcome"] == "WON":
                net_gain_native = payout - stake
                principal_returned_native = stake
            elif bet["outcome"] == "LOST":
                net_gain_native = -stake
                principal_returned_native = Decimal("0")
            else:  # VOID
                net_gain_native = Decimal("0")
                principal_returned_native = stake

            net_gain_eur = fx_manager.convert_to_eur(net_gain_native, bet["currency"], fx_rate)
            principal_returned_eur = fx_manager.convert_to_eur(principal_returned_native, bet["currency"], fx_rate)

            surebet_profit_eur += net_gain_eur
            bet_results.append({
                "bet": bet,
                "fx_rate": fx_rate,
                "net_gain_eur": net_gain_eur,
                "principal_returned_eur": principal_returned_eur
            })

        # Determine N (participants)
        unique_associates = set(bet["associate_id"] for bet in bets)
        admin_staked = any(bet["associate_id"] == ADMIN_ASSOCIATE_ID for bet in bets)
        n = len(unique_associates) if admin_staked else len(unique_associates) + 1

        # Calculate per-surebet share
        per_surebet_share_eur = surebet_profit_eur / n

        # Create ledger entries
        settlement_batch_id = str(uuid.uuid4())
        for result in bet_results:
            bet = result["bet"]
            cursor.execute("""
                INSERT INTO ledger_entries (
                    type, associate_id, bookmaker_id,
                    amount_native, native_currency, fx_rate_snapshot, amount_eur,
                    settlement_state, principal_returned_eur, per_surebet_share_eur,
                    surebet_id, bet_id, settlement_batch_id,
                    created_at_utc, created_by, note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                "BET_RESULT",
                bet["associate_id"],
                bet["bookmaker_id"],
                str(result["net_gain_native"]),
                bet["currency"],
                str(result["fx_rate"]),
                str(result["net_gain_eur"]),
                bet["outcome"],
                str(result["principal_returned_eur"]),
                str(per_surebet_share_eur),
                surebet_id,
                bet["id"],
                settlement_batch_id,
                datetime.utcnow().isoformat() + "Z",
                "local_user",
                operator_note
            ))

        # Mark settled
        cursor.execute("UPDATE surebets SET status = 'settled' WHERE id = ?", (surebet_id,))
        bet_ids = [b["id"] for b in bets]
        placeholders = ",".join("?" * len(bet_ids))
        cursor.execute(f"UPDATE bets SET status = 'settled' WHERE id IN ({placeholders})", bet_ids)

        self.db.commit()
        return settlement_batch_id
```

**Key Settlement Rules:**
- **Admin Seat Logic**: If admin did NOT stake, they get +1 seat in split (and eat losses equally)
- **VOID Handling**: VOID bets have `net_gain_eur=0`, `principal_returned_eur=stake`, but STILL participate in split
- **Frozen FX**: `fx_rate_snapshot` stored at settlement time, NEVER recalculated

---

### 6. FX Manager

**File:** `src/services/fx_manager.py`

```python
class FXManager:
    def get_fx_rate(self, currency: str, target_date: date) -> Decimal:
        """
        1. Check fx_rates_daily table for (currency, target_date)
        2. If found, return cached rate
        3. If not found, fetch from external API, cache, return
        4. If API fails, return last known rate
        """
        cursor = self.db.cursor()
        cached = cursor.execute("""
            SELECT eur_per_unit FROM fx_rates_daily
            WHERE currency = ? AND rate_date = ?
        """, (currency, target_date.isoformat())).fetchone()

        if cached:
            return Decimal(cached["eur_per_unit"])

        # Fetch from API
        try:
            api_client = FXAPIClient()
            rate = api_client.fetch_rate(currency, target_date)
            # Cache
            cursor.execute("""
                INSERT INTO fx_rates_daily (currency, rate_date, eur_per_unit)
                VALUES (?, ?, ?)
            """, (currency, target_date.isoformat(), str(rate)))
            self.db.commit()
            return rate
        except Exception as e:
            logger.warning(f"FX API failed: {e}. Using last known rate.")
            # Fallback to last known rate
            last_known = cursor.execute("""
                SELECT eur_per_unit FROM fx_rates_daily
                WHERE currency = ?
                ORDER BY rate_date DESC
                LIMIT 1
            """, (currency,)).fetchone()
            if last_known:
                return Decimal(last_known["eur_per_unit"])
            else:
                raise ValueError(f"No FX rate available for {currency}")

    def convert_to_eur(
        self,
        amount_native: Decimal,
        currency: str,
        fx_rate_snapshot: Decimal
    ) -> Decimal:
        """
        Simple conversion: amount_native * fx_rate_snapshot
        NEVER query current FX rate for old transactions!
        """
        return amount_native * fx_rate_snapshot
```

---

### 7. Reconciliation Service (FR-8)

**File:** `src/services/reconciliation.py`

```python
class ReconciliationService:
    def calculate_associate_health(self, associate_id: int) -> Dict[str, Decimal]:
        """
        Calculate:
        - NET_DEPOSITS_EUR
        - CURRENT_HOLDING_EUR
        - SHOULD_HOLD_EUR
        - DELTA
        - Human explanation
        """
        cursor = self.db.cursor()

        # NET_DEPOSITS_EUR
        deposits = cursor.execute("""
            SELECT SUM(
                CASE
                    WHEN type = 'DEPOSIT' THEN CAST(amount_eur AS REAL)
                    WHEN type = 'WITHDRAWAL' THEN -CAST(amount_eur AS REAL)
                    ELSE 0
                END
            ) AS net_deposits_eur
            FROM ledger_entries
            WHERE associate_id = ?
            AND type IN ('DEPOSIT', 'WITHDRAWAL')
        """, (associate_id,)).fetchone()
        net_deposits_eur = Decimal(deposits["net_deposits_eur"] or "0")

        # SHOULD_HOLD_EUR (entitlement)
        entitlement = cursor.execute("""
            SELECT SUM(
                CAST(principal_returned_eur AS REAL) +
                CAST(per_surebet_share_eur AS REAL)
            ) AS should_hold_eur
            FROM ledger_entries
            WHERE associate_id = ?
            AND type = 'BET_RESULT'
        """, (associate_id,)).fetchone()
        should_hold_eur = Decimal(entitlement["should_hold_eur"] or "0")

        # CURRENT_HOLDING_EUR
        holdings = cursor.execute("""
            SELECT SUM(CAST(amount_eur AS REAL)) AS current_holding_eur
            FROM ledger_entries
            WHERE associate_id = ?
        """, (associate_id,)).fetchone()
        current_holding_eur = Decimal(holdings["current_holding_eur"] or "0")

        # DELTA
        delta = current_holding_eur - should_hold_eur

        # Explanation
        if delta > Decimal("10"):  # Threshold: €10
            explanation = f"Holding €{delta} more than entitlement (group float you should collect)"
        elif delta < Decimal("-10"):
            explanation = f"Short €{-delta} (someone else holding your money)"
        else:
            explanation = "Balanced ✅"

        return {
            "net_deposits_eur": net_deposits_eur,
            "current_holding_eur": current_holding_eur,
            "should_hold_eur": should_hold_eur,
            "delta": delta,
            "explanation": explanation
        }
```

---

## Domain Models

### Bet Model

```python
# src/models/bet.py
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

@dataclass
class Bet:
    id: int
    associate_id: int
    bookmaker_id: int
    status: str  # incoming, verified, matched, settled, rejected
    ingestion_source: str  # telegram, manual_upload
    telegram_message_id: Optional[int]
    screenshot_path: str
    canonical_event_id: Optional[int]
    market_code: str
    period_scope: str
    line_value: Decimal
    side: str
    stake: Decimal
    odds: Decimal
    payout: Decimal
    currency: str
    kickoff_time_utc: str
    normalization_confidence: Decimal
    is_multi: bool
    is_supported: bool
    created_at_utc: str
```

### Surebet Model

```python
# src/models/surebet.py
@dataclass
class Surebet:
    id: int
    canonical_event_id: int
    market_code: str
    period_scope: str
    line_value: Decimal
    status: str  # open, settled
    created_at_utc: str

    def load_bets(self):
        """Load all bets linked to this surebet"""
        # Query surebet_bets + bets
```

---

## Error Handling Strategy

### Service-Level Errors

```python
# Custom exceptions
class BetIngestionError(Exception):
    pass

class SettlementError(Exception):
    pass

# Usage
try:
    bet_id = BetIngestionService().ingest_telegram_screenshot(...)
except BetIngestionError as e:
    logger.error(f"Ingestion failed: {e}")
    # Queue for manual retry
```

### Database Errors

```python
try:
    cursor.execute(...)
    db.commit()
except sqlite3.IntegrityError as e:
    logger.error(f"Foreign key violation: {e}")
    db.rollback()
    raise
```

---

**End of Document**

---

## Change Notes — YF & Exit Settlement Alignment (2025-11-13)

- Reconciliation read models should expose `ND`, `FS`, `YF`, `TB`, and `Δ` and map legacy `should_hold_eur` fields to `yf_eur` in APIs/UI models.
- Standardize ND computation across services: `WITHDRAWAL` rows are stored negative; `DEPOSIT` positive; compute ND by summing signed values (remove double-negation in per‑bookmaker logic).
- Add an application operation: `settle_associate_now(associate_id, as_of_utc)` that computes Δ at cutoff and writes a single balancing `DEPOSIT` (if Δ < 0) or `WITHDRAWAL` (if Δ > 0) entry, returning a receipt payload for CSV/UX rendering.
- No schema changes; reuse `ledger_entries` and existing statement math; add a version string `YF‑v1` to export helpers for footnotes.
