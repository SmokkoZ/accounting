# Data Model Specification

**Parent Document**: [PRD Main](../prd.md)
**Version**: v4
**Last Updated**: 2025-10-29

---

## Overview

The Surebet Accounting System uses SQLite with WAL mode for local-first, append-only data storage. All currency values are stored as TEXT Decimals, and all timestamps are UTC ISO8601 with "Z".

---

## Core Principles

1. **Append-Only Ledger**: Financial data is never edited; corrections are forward-only
2. **Frozen FX**: Each ledger row captures its own `fx_rate_snapshot` at creation time
3. **Audit Trail**: Every money-impacting action creates immutable ledger entries
4. **Deterministic Side Assignment**: `surebet_bets.side` ("A" or "B") never changes after creation

---

## Schema Definitions

### associates

Represents trusted partners (including the admin/operator).

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Auto-increment ID |
| `display_alias` | TEXT | NOT NULL, UNIQUE | Human-readable name (e.g., "Marco", "You") |
| `home_currency` | TEXT | NOT NULL | ISO currency code (e.g., "EUR", "AUD", "GBP") |
| `multibook_chat_id` | TEXT | NULLABLE | Telegram chat ID for multibook coverage messages |
| `metadata_json` | TEXT | NULLABLE | Additional data (JSON) |
| `created_at_utc` | TEXT | NOT NULL | UTC ISO8601 "Z" |
| `updated_at_utc` | TEXT | NOT NULL | UTC ISO8601 "Z" |

**Notes**:
- Admin is also an associate
- `home_currency` implies the currency for their bookmakers
- If admin didn't stake in a surebet, they still get one equal-split seat

**Example**:
```sql
INSERT INTO associates (display_alias, home_currency, multibook_chat_id, created_at_utc, updated_at_utc)
VALUES ('You', 'EUR', '-1001234567890', '2025-10-29T10:00:00Z', '2025-10-29T10:00:00Z');
```

---

### bookmakers

Bookmaker accounts per associate.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Auto-increment ID |
| `associate_id` | INTEGER | FOREIGN KEY → associates.id, NOT NULL | Owner of this bookmaker account |
| `bookmaker_name` | TEXT | NOT NULL | e.g., "Bet365", "Ladbrokes", "Sportsbet" |
| `parsing_profile` | TEXT | NULLABLE | OCR hints (JSON) for this bookmaker's screenshot format |
| `created_at_utc` | TEXT | NOT NULL | UTC ISO8601 "Z" |
| `updated_at_utc` | TEXT | NOT NULL | UTC ISO8601 "Z" |

**Constraints**:
- `UNIQUE(associate_id, bookmaker_name)` — each associate can only have one account per bookmaker name

**Notes**:
- Currency is implied by the associate's `home_currency`
- `parsing_profile` can help OCR (e.g., known layout hints)

**Example**:
```sql
INSERT INTO bookmakers (associate_id, bookmaker_name, created_at_utc, updated_at_utc)
VALUES (1, 'Bet365', '2025-10-29T10:00:00Z', '2025-10-29T10:00:00Z');
```

---

### canonical_events

Normalized sporting events used for matching and settlement ordering.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Auto-increment ID |
| `normalized_event_name` | TEXT | NOT NULL | e.g., "Grêmio vs Juventude" |
| `league` | TEXT | NULLABLE | e.g., "Brazil Serie A" |
| `kickoff_time_utc` | TEXT | NOT NULL | UTC ISO8601 "Z" |
| `hash_key` | TEXT | UNIQUE, NOT NULL | Deduplication key (e.g., hash of name + kickoff) |
| `created_at_utc` | TEXT | NOT NULL | UTC ISO8601 "Z" |

**Notes**:
- Used in Incoming Bets dropdown/search
- Used for settlement ordering (oldest kickoff first)
- `hash_key` prevents duplicate event entries

**Example**:
```sql
INSERT INTO canonical_events (normalized_event_name, league, kickoff_time_utc, hash_key, created_at_utc)
VALUES ('Grêmio vs Juventude', 'Brazil Serie A', '2025-10-30T18:00:00Z', 'abc123hash', '2025-10-29T10:00:00Z');
```

---

### canonical_markets

Market type definitions.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Auto-increment ID |
| `market_code` | TEXT | UNIQUE, NOT NULL | e.g., "FIRST_HALF_TOTAL_CORNERS_OVER_UNDER" |
| `description` | TEXT | NULLABLE | Human-readable description |
| `created_at_utc` | TEXT | NOT NULL | UTC ISO8601 "Z" |

**Example Market Codes**:
- `FIRST_HALF_TOTAL_CORNERS_OVER_UNDER`
- `ASIAN_HANDICAP`
- `RED_CARD_YES_NO_FULL_MATCH`
- `TOTAL_GOALS_OVER_UNDER`
- `BOTH_TEAMS_TO_SCORE_YES_NO`

**Example**:
```sql
INSERT INTO canonical_markets (market_code, description, created_at_utc)
VALUES ('FIRST_HALF_TOTAL_CORNERS_OVER_UNDER', 'First half total corners over/under', '2025-10-29T10:00:00Z');
```

---

### bets

Individual bet records from screenshot ingestion through settlement.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Auto-increment ID |
| `associate_id` | INTEGER | FOREIGN KEY → associates.id, NOT NULL | Who placed this bet |
| `bookmaker_id` | INTEGER | FOREIGN KEY → bookmakers.id, NOT NULL | Which bookmaker |
| `timestamp_received_utc` | TEXT | NOT NULL | When ingested |
| `screenshot_path` | TEXT | NOT NULL | Path under `data/screenshots/` |
| `telegram_message_id` | TEXT | NULLABLE | NULL if manual upload |
| `ingestion_source` | TEXT | NOT NULL | `"telegram"` or `"manual_upload"` |
| `status` | TEXT | NOT NULL | `"incoming"`, `"verified"`, `"matched"`, `"settled"`, `"rejected"` |

**OCR / Extraction**:

| Column | Type | Description |
|--------|------|-------------|
| `raw_extraction_text` | TEXT | Raw OCR output |
| `structured_candidate_json` | TEXT | GPT-4o structured extraction (JSON) |
| `extraction_confidence` | REAL | OCR confidence score (0.0 - 1.0) |
| `model_version_extraction` | TEXT | e.g., "gpt-4o-2025-10-15" |

**Normalized / Approved**:

| Column | Type | Description |
|--------|------|-------------|
| `canonical_event_id` | INTEGER | FOREIGN KEY → canonical_events.id, NULLABLE until approved |
| `event_display_name` | TEXT | e.g., "Grêmio vs Juventude" |
| `market_code` | TEXT | e.g., "FIRST_HALF_TOTAL_CORNERS_OVER_UNDER" |
| `period_scope` | TEXT | `"FULL_MATCH"`, `"FIRST_HALF"`, `"SECOND_HALF"` |
| `line_value` | TEXT | Decimal as TEXT: `"6.5"`, `"2.5"`, `"-0.5"` |
| `side` | TEXT | `"OVER"`, `"UNDER"`, `"YES"`, `"NO"`, `"TEAM_A"`, `"TEAM_B"` |
| `stake_normalized` | TEXT | Decimal as TEXT |
| `odds_normalized` | TEXT | Decimal as TEXT |
| `potential_win_normalized` | TEXT | Decimal as TEXT |
| `is_supported` | INTEGER | 0 or 1 (0 if accumulator/multi) |
| `is_multi` | INTEGER | 0 or 1 (1 if multi-leg bet) |
| `normalization_confidence` | REAL | Normalization confidence score (0.0 - 1.0) |
| `model_version_normalization` | TEXT | e.g., "gpt-4o-2025-10-15" |

**Financial Snapshot at Ingest**:

| Column | Type | Description |
|--------|------|-------------|
| `stake_native` | TEXT | Decimal as TEXT (original currency) |
| `payout_native` | TEXT | Decimal as TEXT (original currency) |
| `native_currency` | TEXT | ISO currency code (e.g., "AUD") |

**Operational**:

| Column | Type | Description |
|--------|------|-------------|
| `linked_surebet_id` | INTEGER | FOREIGN KEY → surebets.id, NULLABLE until matched |
| `settlement_state` | TEXT | `"WON"`, `"LOST"`, `"VOID"`, or NULL until settlement |
| `created_at_utc` | TEXT | UTC ISO8601 "Z" |
| `updated_at_utc` | TEXT | UTC ISO8601 "Z" |
| `last_modified_by` | TEXT | e.g., "local_user" |

**Notes**:
- `is_multi=1` bets are flagged as `is_supported=0` and never match into surebets
- All edits during approval are logged in `verification_audit`

**Example**:
```sql
INSERT INTO bets (associate_id, bookmaker_id, timestamp_received_utc, screenshot_path, telegram_message_id, ingestion_source, status, ...)
VALUES (1, 1, '2025-10-29T10:30:00Z', 'data/screenshots/bet_123.png', '456789', 'telegram', 'incoming', ...);
```

---

### surebets

Grouped opposing bets forming a surebet.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Auto-increment ID |
| `canonical_event_id` | INTEGER | FOREIGN KEY → canonical_events.id, NOT NULL | Which event |
| `market_code` | TEXT | NOT NULL | Which market |
| `period_scope` | TEXT | NOT NULL | `"FULL_MATCH"`, `"FIRST_HALF"`, `"SECOND_HALF"` |
| `line_value` | TEXT | NOT NULL | Decimal as TEXT |
| `status` | TEXT | NOT NULL | `"open"`, `"settled"` |
| `created_at_utc` | TEXT | NOT NULL | UTC ISO8601 "Z" |
| `updated_at_utc` | TEXT | NOT NULL | UTC ISO8601 "Z" |

**Constraints**:
- `UNIQUE(canonical_event_id, market_code, period_scope, line_value)` — only one surebet per unique market/line combination

**Notes**:
- `worst_case_profit_eur` and ROI are computed dynamically using FX rates, not stored
- All opposing bets (e.g., A+B vs C) are treated as ONE surebet, not multiple pairwise surebets

**Example**:
```sql
INSERT INTO surebets (canonical_event_id, market_code, period_scope, line_value, status, created_at_utc, updated_at_utc)
VALUES (1, 'FIRST_HALF_TOTAL_CORNERS_OVER_UNDER', 'FIRST_HALF', '6.5', 'open', '2025-10-29T10:30:00Z', '2025-10-29T10:30:00Z');
```

---

### surebet_bets

Junction table linking bets to surebets with deterministic side assignment.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `surebet_id` | INTEGER | FOREIGN KEY → surebets.id, NOT NULL | Which surebet |
| `bet_id` | INTEGER | FOREIGN KEY → bets.id, NOT NULL | Which bet |
| `side` | TEXT | NOT NULL | `"A"` or `"B"` |

**Constraints**:
- `PRIMARY KEY (surebet_id, bet_id)`
- `UNIQUE(bet_id)` — each bet belongs to at most one surebet

**Side Mapping (MUST NEVER FLIP)**:
- `side="A"` = OVER / YES / TEAM_A
- `side="B"` = UNDER / NO / TEAM_B

**Notes**:
- This mapping is set once at matching time and is immutable
- Settlement logic relies on this deterministic assignment

**Example**:
```sql
INSERT INTO surebet_bets (surebet_id, bet_id, side)
VALUES (1, 10, 'A'), (1, 11, 'B');
```

---

### ledger_entries

Append-only financial ledger (single source of truth for money movements).

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Auto-increment ID |
| `associate_id` | INTEGER | FOREIGN KEY → associates.id, NOT NULL | Who this entry affects |
| `bookmaker_id` | INTEGER | FOREIGN KEY → bookmakers.id, NULLABLE | Which bookmaker (NULL for non-bookmaker entries) |
| `surebet_id` | INTEGER | FOREIGN KEY → surebets.id, NULLABLE | Which surebet (for BET_RESULT only) |
| `bet_id` | INTEGER | FOREIGN KEY → bets.id, NULLABLE | Which bet (for BET_RESULT only) |
| `type` | TEXT | NOT NULL | `"BET_RESULT"`, `"DEPOSIT"`, `"WITHDRAWAL"`, `"BOOKMAKER_CORRECTION"` |
| `settlement_state` | TEXT | NULLABLE | `"WON"`, `"LOST"`, `"VOID"` (for BET_RESULT only; else NULL) |
| `amount_native` | TEXT | NOT NULL | Decimal as TEXT (original currency) |
| `native_currency` | TEXT | NOT NULL | ISO currency code |
| `fx_rate_snapshot` | TEXT | NOT NULL | Decimal as TEXT (EUR per 1 unit of native currency at creation) |
| `amount_eur` | TEXT | NOT NULL | Decimal as TEXT (converted to EUR using `fx_rate_snapshot`) |
| `principal_returned_eur` | TEXT | NULLABLE | Decimal as TEXT (stake returned via WON/VOID; BET_RESULT only) |
| `per_surebet_share_eur` | TEXT | NULLABLE | Decimal as TEXT (equal-split slice; BET_RESULT only) |
| `settlement_batch_id` | TEXT | NULLABLE | Groups rows from single settlement confirm click |
| `note` | TEXT | NULLABLE | e.g., "settlement batch 2025-10-28", "late VOID correction" |
| `created_at_utc` | TEXT | NOT NULL | UTC ISO8601 "Z" |
| `created_by` | TEXT | NOT NULL | e.g., "local_user" |

**System Law #1 (Append-Only)**:
- Rows are NEVER edited or deleted
- Corrections are forward-only (new BOOKMAKER_CORRECTION rows)

**System Law #2 (Frozen FX)**:
- Each row captures its own `fx_rate_snapshot` at creation time
- All reconciliation math uses these frozen snapshots
- We never "revalue" old rows if FX changes

**Ledger Types**:

#### 1. BET_RESULT
- Written on settlement confirm
- One row per (associate, bet)
- Includes: `settlement_state`, `principal_returned_eur`, `per_surebet_share_eur`, `settlement_batch_id`

#### 2. DEPOSIT
- Written when funding event accepted
- Positive `amount_eur` increases associate's holdings

#### 3. WITHDRAWAL
- Written when withdrawal accepted
- Negative `amount_eur` decreases associate's holdings

#### 4. BOOKMAKER_CORRECTION
- Manual forward adjustment
- Reconciles modeled vs. claimed balance OR late VOID / grading fix
- Requires `note` explaining reason

**Example**:
```sql
-- BET_RESULT
INSERT INTO ledger_entries (associate_id, bookmaker_id, surebet_id, bet_id, type, settlement_state, amount_native, native_currency, fx_rate_snapshot, amount_eur, principal_returned_eur, per_surebet_share_eur, settlement_batch_id, note, created_at_utc, created_by)
VALUES (1, 1, 1, 10, 'BET_RESULT', 'WON', '95.00', 'AUD', '0.62', '58.90', '50.00', '4.45', 'batch_001', 'settlement batch 2025-10-29', '2025-10-29T18:00:00Z', 'local_user');

-- DEPOSIT
INSERT INTO ledger_entries (associate_id, bookmaker_id, surebet_id, bet_id, type, settlement_state, amount_native, native_currency, fx_rate_snapshot, amount_eur, principal_returned_eur, per_surebet_share_eur, settlement_batch_id, note, created_at_utc, created_by)
VALUES (1, 1, NULL, NULL, 'DEPOSIT', NULL, '200.00', 'AUD', '0.62', '124.00', NULL, NULL, NULL, 'manual deposit confirmation', '2025-10-29T10:00:00Z', 'local_user');
```

---

### verification_audit

Audit trail for bet approval/editing.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Auto-increment ID |
| `bet_id` | INTEGER | FOREIGN KEY → bets.id, NOT NULL | Which bet was edited |
| `diff_before_after` | TEXT | NOT NULL | JSON showing field changes |
| `note` | TEXT | NULLABLE | Optional note from operator |
| `created_at_utc` | TEXT | NOT NULL | UTC ISO8601 "Z" |
| `actor` | TEXT | NOT NULL | e.g., "local_user" |

**Example**:
```sql
INSERT INTO verification_audit (bet_id, diff_before_after, note, created_at_utc, actor)
VALUES (10, '{"stake": {"old": "50.00", "new": "51.00"}}', 'Corrected OCR error', '2025-10-29T10:30:00Z', 'local_user');
```

---

### multibook_message_log

Log of coverage proof messages sent to associates' multibook chats.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Auto-increment ID |
| `associate_id` | INTEGER | FOREIGN KEY → associates.id, NOT NULL | Which associate's multibook chat |
| `surebet_id` | INTEGER | FOREIGN KEY → surebets.id, NOT NULL | Which surebet |
| `message_type` | TEXT | NOT NULL | e.g., "COVERAGE_PROOF" |
| `forwarded_bet_ids` | TEXT | NOT NULL | JSON list of bet IDs whose screenshots were forwarded |
| `message_body` | TEXT | NULLABLE | JSON snapshot of message text sent |
| `sent_timestamp_utc` | TEXT | NOT NULL | UTC ISO8601 "Z" |
| `telegram_message_id_sent` | TEXT | NULLABLE | Telegram message ID |
| `delivery_status` | TEXT | NOT NULL | `"SENT"`, `"FAILED"`, `"RETRYING"` |
| `retry_count` | INTEGER | DEFAULT 0 | Number of retry attempts |

**Example**:
```sql
INSERT INTO multibook_message_log (associate_id, surebet_id, message_type, forwarded_bet_ids, message_body, sent_timestamp_utc, telegram_message_id_sent, delivery_status, retry_count)
VALUES (1, 1, 'COVERAGE_PROOF', '[11, 12]', '{"text": "You\'re covered for..."}', '2025-10-29T10:30:00Z', '789012', 'SENT', 0);
```

---

### bookmaker_balance_checks

Associate-reported bookmaker balances (for reconciliation).

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Auto-increment ID |
| `bookmaker_id` | INTEGER | FOREIGN KEY → bookmakers.id, NOT NULL | Which bookmaker |
| `associate_id` | INTEGER | FOREIGN KEY → associates.id, NOT NULL | Who reported this |
| `reported_amount_native` | TEXT | NOT NULL | Decimal as TEXT (what they claim is in the app) |
| `native_currency` | TEXT | NOT NULL | ISO currency code |
| `reported_at_utc` | TEXT | NOT NULL | UTC ISO8601 "Z" |
| `noted_by` | TEXT | NOT NULL | e.g., "local_user" |
| `note` | TEXT | NULLABLE | Optional context |
| `telegram_message_id` | TEXT | NULLABLE | If reported via Telegram |

**Notes**:
- These checks do NOT auto-create corrections
- Operator decides whether to post a BOOKMAKER_CORRECTION based on delta
- Preserves System Law #1 (append-only)

**Example**:
```sql
INSERT INTO bookmaker_balance_checks (bookmaker_id, associate_id, reported_amount_native, native_currency, reported_at_utc, noted_by, note)
VALUES (1, 1, '312.50', 'AUD', '2025-10-29T09:00:00Z', 'local_user', 'Morning balance check');
```

---

### fx_rates_daily

Daily currency → EUR conversion cache.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Auto-increment ID |
| `currency_code` | TEXT | NOT NULL | ISO currency code (e.g., "AUD", "GBP", "EUR") |
| `rate_to_eur` | TEXT | NOT NULL | Decimal as TEXT (how many EUR per 1 unit of this currency) |
| `fetched_at_utc` | TEXT | NOT NULL | UTC ISO8601 "Z" |
| `source` | TEXT | NULLABLE | e.g., "exchangerate-api.com" |
| `created_at_utc` | TEXT | NOT NULL | UTC ISO8601 "Z" |

**Constraints**:
- `UNIQUE(currency_code, fetched_at_utc)` — one rate per currency per fetch time

**Notes**:
- One FX rate per currency per day is sufficient
- If no fresh rate today, reuse most recent known
- When creating ledger rows, stamp latest known rate into `fx_rate_snapshot`
- All math internally is in EUR
- We never "re-FX" the past (System Law #2)

**Example**:
```sql
INSERT INTO fx_rates_daily (currency_code, rate_to_eur, fetched_at_utc, source, created_at_utc)
VALUES ('AUD', '0.62', '2025-10-29T00:00:00Z', 'exchangerate-api.com', '2025-10-29T00:05:00Z');
```

---

## Reconciliation Derived Fields

These are **computed fields** (not stored), calculated from ledger entries:

### NET_DEPOSITS_EUR
**Formula**:
```sql
SELECT SUM(CASE WHEN type='DEPOSIT' THEN amount_eur ELSE 0 END) -
       SUM(CASE WHEN type='WITHDRAWAL' THEN amount_eur ELSE 0 END)
FROM ledger_entries
WHERE associate_id = ?
```

**Meaning**: How much cash the associate personally funded into the operation.

---

### SHOULD_HOLD_EUR (Entitlement)
**Formula**:
```sql
SELECT SUM(principal_returned_eur + per_surebet_share_eur)
FROM ledger_entries
WHERE associate_id = ? AND type='BET_RESULT'
```

**Meaning**: How much of the pool belongs to them after all settled surebets.

**Intuition**: "If we froze the world after all settled bets, this is how much of the pot is yours."

---

### CURRENT_HOLDING_EUR
**Formula**:
```sql
SELECT SUM(
    CASE
        WHEN type='BET_RESULT' THEN principal_returned_eur + per_surebet_share_eur
        WHEN type='DEPOSIT' THEN amount_eur
        WHEN type='WITHDRAWAL' THEN -amount_eur
        WHEN type='BOOKMAKER_CORRECTION' THEN amount_eur
    END
)
FROM ledger_entries
WHERE associate_id = ?
```

**Meaning**: What the model thinks they're physically holding across all their bookmakers right now.

---

### DELTA
**Formula**:
```
DELTA = CURRENT_HOLDING_EUR - SHOULD_HOLD_EUR
```

**Interpretation**:
- `DELTA > 0`: Holding more than entitlement → parking group float (should transfer out)
- `DELTA ≈ 0`: Balanced (ideal state)
- `DELTA < 0`: Holding less than entitlement → someone else is holding their money

---

### RAW_PROFIT_EUR (for Monthly Statements)
**Formula**:
```
RAW_PROFIT_EUR = SHOULD_HOLD_EUR - NET_DEPOSITS_EUR
```

**Meaning**: How far ahead the associate is compared to what they funded. Can be positive or negative. This is split 50/50 between you and them.

---

## ER Diagram (Simplified)

```
associates
    ├─> bookmakers (1:N)
    │   ├─> bets (1:N)
    │   └─> bookmaker_balance_checks (1:N)
    └─> ledger_entries (1:N)

canonical_events
    ├─> bets (1:N via canonical_event_id)
    └─> surebets (1:N)

canonical_markets
    └─> (reference only, no FK)

surebets
    ├─> surebet_bets (1:N)
    │   └─> bets (N:1)
    └─> ledger_entries (1:N)

bets
    ├─> verification_audit (1:N)
    └─> ledger_entries (1:N)

fx_rates_daily
    └─> (used to populate fx_rate_snapshot in ledger_entries)
```

---

## Indexes (Performance Optimization)

```sql
-- Fast lookups by status
CREATE INDEX idx_bets_status ON bets(status);

-- Fast surebet matching
CREATE INDEX idx_bets_event_market ON bets(canonical_event_id, market_code, period_scope, line_value, status);

-- Fast ledger queries by associate
CREATE INDEX idx_ledger_associate ON ledger_entries(associate_id, type, created_at_utc);

-- Fast settlement ordering
CREATE INDEX idx_events_kickoff ON canonical_events(kickoff_time_utc);

-- Fast FX lookups
CREATE INDEX idx_fx_currency_fetch ON fx_rates_daily(currency_code, fetched_at_utc DESC);
```

---

## Data Lifecycle

### 1. Bet Ingestion
```
Telegram/Manual → bets (status='incoming')
```

### 2. Approval
```
bets (status='incoming') → verification_audit → bets (status='verified')
```

### 3. Matching
```
bets (status='verified') → surebets + surebet_bets → bets (status='matched')
```

### 4. Settlement
```
bets (status='matched') → ledger_entries (type='BET_RESULT') → bets (status='settled')
surebets (status='open') → surebets (status='settled')
```

### 5. Reconciliation
```
ledger_entries → compute NET_DEPOSITS_EUR, SHOULD_HOLD_EUR, CURRENT_HOLDING_EUR, DELTA
bookmaker_balance_checks → compare with CURRENT_HOLDING_EUR → optional BOOKMAKER_CORRECTION
```

### 6. Monthly Statements
```
ledger_entries → compute NET_DEPOSITS_EUR, SHOULD_HOLD_EUR, RAW_PROFIT_EUR → display
```

---

## Migration Strategy

### Initial Schema Setup

```sql
-- See schema.sql for full DDL
-- Run migrations in order:
-- 001_initial_schema.sql
-- 002_add_indexes.sql
-- 003_seed_canonical_markets.sql
```

### Seed Data

Pre-populate `canonical_markets` with common market codes:
```sql
INSERT INTO canonical_markets (market_code, description, created_at_utc) VALUES
('FIRST_HALF_TOTAL_CORNERS_OVER_UNDER', 'First half total corners over/under', '2025-10-29T00:00:00Z'),
('ASIAN_HANDICAP', 'Asian handicap', '2025-10-29T00:00:00Z'),
('RED_CARD_YES_NO_FULL_MATCH', 'Red card yes/no full match', '2025-10-29T00:00:00Z'),
('TOTAL_GOALS_OVER_UNDER', 'Total goals over/under', '2025-10-29T00:00:00Z'),
('BOTH_TEAMS_TO_SCORE_YES_NO', 'Both teams to score yes/no', '2025-10-29T00:00:00Z');
```

---

**End of Data Model Specification**
