# Data Architecture

**Version:** v4
**Last Updated:** 2025-10-29
**Parent Document:** [Architecture Overview](../architecture.md)

---

## Overview

The data layer uses **SQLite in WAL mode** with an **append-only ledger** for all financial transactions. The schema is designed for data integrity, auditability, and deterministic calculations.

---

## Database Technology

### SQLite Configuration

```python
# src/core/database.py
import sqlite3

def init_db(db_path: str = "data/surebet.db"):
    conn = sqlite3.connect(db_path, check_same_thread=False)

    # Enable foreign keys
    conn.execute("PRAGMA foreign_keys = ON")

    # Enable WAL mode (Write-Ahead Logging) for crash resistance
    conn.execute("PRAGMA journal_mode = WAL")

    # Balance safety vs performance
    conn.execute("PRAGMA synchronous = NORMAL")

    # Row factory for dict-like access
    conn.row_factory = sqlite3.Row

    return conn
```

**Why WAL Mode?**
- Better concurrency (readers don't block writers)
- Crash-resistant (power loss only affects uncommitted writes)
- Faster writes (sequential append to WAL file)

---

## Schema Design Principles

### 1. Decimal as TEXT
All currency values stored as TEXT to preserve exact precision

```sql
stake TEXT NOT NULL  -- "100.50" not 100.5 (float)
```

### 2. UTC Timestamps
All `*_utc` columns store ISO8601 with "Z" suffix

```sql
created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
```

### 3. Explicit Enums via CHECK Constraints
No magic strings

```sql
status TEXT NOT NULL CHECK (status IN ('incoming', 'verified', 'matched', 'settled', 'rejected'))
```

### 4. Foreign Keys Enforced
Referential integrity guaranteed

```sql
associate_id INTEGER NOT NULL REFERENCES associates(id) ON DELETE RESTRICT
```

### 5. Composite Indexes
Optimized for common query patterns

```sql
CREATE INDEX idx_bets_status_date ON bets(status, created_at_utc);
```

---

## Core Tables

### associates

**Purpose:** Trusted partners (including admin)

```sql
CREATE TABLE associates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    display_alias TEXT NOT NULL UNIQUE,  -- "Alice", "Bob", "Admin"
    is_admin INTEGER NOT NULL DEFAULT 0, -- 0 or 1 (boolean)
    created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    note TEXT
);

CREATE INDEX idx_associates_alias ON associates(display_alias);
```

**Sample Data:**
```sql
INSERT INTO associates (id, display_alias, is_admin) VALUES
(1, 'Admin', 1),
(2, 'Alice', 0),
(3, 'Bob', 0),
(4, 'Charlie', 0);
```

---

### bookmakers

**Purpose:** Bookmaker accounts per associate

```sql
CREATE TABLE bookmakers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    associate_id INTEGER NOT NULL REFERENCES associates(id) ON DELETE CASCADE,
    bookmaker_name TEXT NOT NULL,  -- "Bet365", "Sportsbet", "Betfair"
    account_currency TEXT NOT NULL, -- "AUD", "GBP", "EUR"
    created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    note TEXT,

    UNIQUE (associate_id, bookmaker_name)
);

CREATE INDEX idx_bookmakers_associate ON bookmakers(associate_id);
```

**Sample Data:**
```sql
INSERT INTO bookmakers (associate_id, bookmaker_name, account_currency) VALUES
(2, 'Bet365', 'AUD'),
(2, 'Sportsbet', 'AUD'),
(3, 'Betfair', 'GBP'),
(4, 'Ladbrokes', 'EUR');
```

---

### canonical_events

**Purpose:** Normalized sporting events

```sql
CREATE TABLE canonical_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_name TEXT NOT NULL,  -- "Manchester United vs Liverpool"
    sport TEXT NOT NULL,        -- "FOOTBALL", "TENNIS", "BASKETBALL"
    competition TEXT,           -- "Premier League", "ATP Masters"
    kickoff_time_utc TEXT NOT NULL,
    created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_events_kickoff ON canonical_events(kickoff_time_utc);
CREATE INDEX idx_events_sport ON canonical_events(sport);
```

---

### canonical_markets

**Purpose:** Market type definitions (reference data)

```sql
CREATE TABLE canonical_markets (
    market_code TEXT PRIMARY KEY,  -- "TOTAL_GOALS_OVER_UNDER"
    display_name TEXT NOT NULL,    -- "Total Goals Over/Under"
    description TEXT,
    valid_sides TEXT NOT NULL      -- JSON: ["OVER", "UNDER"]
);
```

**Sample Data:**
```sql
INSERT INTO canonical_markets (market_code, display_name, valid_sides) VALUES
('TOTAL_GOALS_OVER_UNDER', 'Total Goals Over/Under', '["OVER","UNDER"]'),
('ASIAN_HANDICAP', 'Asian Handicap', '["TEAM_A","TEAM_B"]'),
('BOTH_TEAMS_TO_SCORE_YES_NO', 'Both Teams To Score', '["YES","NO"]');
```

---

### bets

**Purpose:** Individual bet records

```sql
CREATE TABLE bets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Ownership
    associate_id INTEGER NOT NULL REFERENCES associates(id),
    bookmaker_id INTEGER NOT NULL REFERENCES bookmakers(id),

    -- Status workflow: incoming → verified → matched → settled (or rejected)
    status TEXT NOT NULL CHECK (status IN ('incoming', 'verified', 'matched', 'settled', 'rejected')),

    -- Ingestion metadata
    ingestion_source TEXT NOT NULL CHECK (ingestion_source IN ('telegram', 'manual_upload')),
    telegram_message_id INTEGER,  -- NULL if manual_upload
    screenshot_path TEXT NOT NULL,

    -- Event & market normalization
    canonical_event_id INTEGER REFERENCES canonical_events(id),
    market_code TEXT NOT NULL,
    period_scope TEXT NOT NULL CHECK (period_scope IN ('FULL_MATCH', 'FIRST_HALF', 'SECOND_HALF')),
    line_value TEXT,  -- Decimal (e.g., "2.5" for Over/Under 2.5)
    side TEXT NOT NULL CHECK (side IN ('OVER', 'UNDER', 'YES', 'NO', 'TEAM_A', 'TEAM_B')),

    -- Bet details (all Decimal as TEXT)
    stake TEXT NOT NULL,
    odds TEXT NOT NULL,
    payout TEXT NOT NULL,
    currency TEXT NOT NULL,  -- "AUD", "GBP", "EUR"

    -- Event timing
    kickoff_time_utc TEXT,

    -- OCR metadata
    normalization_confidence TEXT,  -- Decimal 0.0-1.0
    is_multi INTEGER NOT NULL DEFAULT 0,  -- 1 if accumulator/parlay
    is_supported INTEGER NOT NULL DEFAULT 1,  -- 0 if multi (never matched)
    model_version_extraction TEXT,
    model_version_normalization TEXT,

    -- Audit trail
    created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    verified_at_utc TEXT,
    note TEXT
);

CREATE INDEX idx_bets_status ON bets(status);
CREATE INDEX idx_bets_associate ON bets(associate_id);
CREATE INDEX idx_bets_event ON bets(canonical_event_id);
CREATE INDEX idx_bets_status_date ON bets(status, created_at_utc);
```

---

### surebets

**Purpose:** Grouped opposing bets

```sql
CREATE TABLE surebets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Matching key (same values as constituent bets)
    canonical_event_id INTEGER NOT NULL REFERENCES canonical_events(id),
    market_code TEXT NOT NULL,
    period_scope TEXT NOT NULL,
    line_value TEXT,

    -- Status: open → settled
    status TEXT NOT NULL CHECK (status IN ('open', 'settled')),

    -- Audit trail
    created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    settled_at_utc TEXT
);

CREATE INDEX idx_surebets_status ON surebets(status);
CREATE INDEX idx_surebets_event ON surebets(canonical_event_id);
```

---

### surebet_bets

**Purpose:** Junction table linking bets to surebets with side assignment

```sql
CREATE TABLE surebet_bets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    surebet_id INTEGER NOT NULL REFERENCES surebets(id) ON DELETE CASCADE,
    bet_id INTEGER NOT NULL REFERENCES bets(id) ON DELETE CASCADE,

    -- Side assignment: 'A' or 'B' (IMMUTABLE after creation)
    side TEXT NOT NULL CHECK (side IN ('A', 'B')),

    UNIQUE (surebet_id, bet_id)
);

CREATE INDEX idx_surebet_bets_surebet ON surebet_bets(surebet_id);
CREATE INDEX idx_surebet_bets_bet ON surebet_bets(bet_id);
```

**Critical Constraint:** `side` column NEVER changes after initial assignment (settlement logic depends on this stability)

---

### ledger_entries (CRITICAL TABLE)

**Purpose:** Append-only financial ledger

```sql
CREATE TABLE ledger_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Entry type: BET_RESULT, DEPOSIT, WITHDRAWAL, BOOKMAKER_CORRECTION
    type TEXT NOT NULL CHECK (type IN ('BET_RESULT', 'DEPOSIT', 'WITHDRAWAL', 'BOOKMAKER_CORRECTION')),

    -- Who and where
    associate_id INTEGER NOT NULL REFERENCES associates(id),
    bookmaker_id INTEGER REFERENCES bookmakers(id),  -- NULL for DEPOSIT/WITHDRAWAL

    -- Native currency amounts (Decimal as TEXT)
    amount_native TEXT NOT NULL,
    native_currency TEXT NOT NULL,

    -- EUR conversion (FROZEN at creation time - System Law #2)
    fx_rate_snapshot TEXT NOT NULL,  -- Decimal: EUR per 1 unit native
    amount_eur TEXT NOT NULL,         -- Decimal: amount_native * fx_rate_snapshot

    -- BET_RESULT specific fields (NULL for other types)
    settlement_state TEXT CHECK (settlement_state IN ('WON', 'LOST', 'VOID') OR settlement_state IS NULL),
    principal_returned_eur TEXT,     -- Decimal: stake returned if WON/VOID
    per_surebet_share_eur TEXT,      -- Decimal: equal-split seat
    surebet_id INTEGER REFERENCES surebets(id),
    bet_id INTEGER REFERENCES bets(id),
    settlement_batch_id TEXT,        -- UUID linking all rows from one settlement

    -- Audit trail (IMMUTABLE - append-only, System Law #1)
    created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    created_by TEXT NOT NULL DEFAULT 'local_user',
    note TEXT
);

CREATE INDEX idx_ledger_associate ON ledger_entries(associate_id);
CREATE INDEX idx_ledger_type ON ledger_entries(type);
CREATE INDEX idx_ledger_date ON ledger_entries(created_at_utc);
CREATE INDEX idx_ledger_batch ON ledger_entries(settlement_batch_id);
```

**Ledger Invariants (CRITICAL):**
1. **No UPDATE or DELETE** after creation (append-only)
2. **Frozen FX snapshots** (never recalculate `amount_eur`)
3. **Settlement batch ID** links all entries from one settlement
4. **VOID rows still created** (even if all bets VOID, write BET_RESULT rows with zeros)

---

### verification_audit

**Purpose:** Bet approval/edit history

```sql
CREATE TABLE verification_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bet_id INTEGER NOT NULL REFERENCES bets(id),
    field_name TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    edited_by TEXT NOT NULL DEFAULT 'local_user',
    edited_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_audit_bet ON verification_audit(bet_id);
```

---

### multibook_message_log

**Purpose:** Coverage proof delivery log

```sql
CREATE TABLE multibook_message_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    surebet_id INTEGER NOT NULL REFERENCES surebets(id),
    associate_id INTEGER NOT NULL REFERENCES associates(id),
    telegram_message_id INTEGER NOT NULL,
    screenshots_sent TEXT NOT NULL,  -- JSON array of paths
    sent_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_multibook_surebet ON multibook_message_log(surebet_id);
```

---

### bookmaker_balance_checks

**Purpose:** Associate-reported balances for reconciliation

```sql
CREATE TABLE bookmaker_balance_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    associate_id INTEGER NOT NULL REFERENCES associates(id),
    bookmaker_id INTEGER NOT NULL REFERENCES bookmakers(id),
    reported_balance_native TEXT NOT NULL,  -- Decimal
    reported_currency TEXT NOT NULL,
    checked_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    note TEXT
);

CREATE INDEX idx_balance_checks_bookmaker ON bookmaker_balance_checks(bookmaker_id);
```

**Note:** These rows do NOT auto-create corrections. Operator manually decides to apply corrections.

---

### fx_rates_daily

**Purpose:** Currency → EUR conversion cache

```sql
CREATE TABLE fx_rates_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    currency TEXT NOT NULL,       -- "AUD", "GBP", "USD"
    rate_date TEXT NOT NULL,      -- ISO8601 date (YYYY-MM-DD)
    eur_per_unit TEXT NOT NULL,   -- Decimal: EUR per 1 unit of currency
    source TEXT,                  -- "exchangerate-api", "ecb", etc.
    fetched_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    UNIQUE (currency, rate_date)
);

CREATE UNIQUE INDEX idx_fx_currency_date ON fx_rates_daily(currency, rate_date);
```

**Caching Strategy:**
- One rate per currency per day (midnight UTC cutoff)
- Reuse last known rate if API unavailable
- All ledger entries store `fx_rate_snapshot` used at creation time

---

## Query Patterns

### Reconciliation Queries (FR-8)

#### NET_DEPOSITS_EUR

```sql
SELECT
    SUM(
        CASE
            WHEN type = 'DEPOSIT' THEN CAST(amount_eur AS REAL)
            WHEN type = 'WITHDRAWAL' THEN -CAST(amount_eur AS REAL)
            ELSE 0
        END
    ) AS net_deposits_eur
FROM ledger_entries
WHERE associate_id = ?
AND type IN ('DEPOSIT', 'WITHDRAWAL');
```

#### SHOULD_HOLD_EUR (Entitlement)

```sql
SELECT
    SUM(
        CAST(principal_returned_eur AS REAL) +
        CAST(per_surebet_share_eur AS REAL)
    ) AS should_hold_eur
FROM ledger_entries
WHERE associate_id = ?
AND type = 'BET_RESULT';
```

#### CURRENT_HOLDING_EUR

```sql
SELECT
    SUM(CAST(amount_eur AS REAL)) AS current_holding_eur
FROM ledger_entries
WHERE associate_id = ?;
```

#### DELTA

```sql
-- Calculated: CURRENT_HOLDING_EUR - SHOULD_HOLD_EUR
```

---

### Common Queries

#### Get Incoming Bets for Review

```sql
SELECT * FROM bets
WHERE status = 'incoming'
ORDER BY created_at_utc DESC;
```

#### Get Open Surebets Sorted by Kickoff

```sql
SELECT s.*, e.event_name, e.kickoff_time_utc
FROM surebets s
JOIN canonical_events e ON s.canonical_event_id = e.id
WHERE s.status = 'open'
ORDER BY e.kickoff_time_utc ASC;
```

#### Get All Bets for Surebet with Side Assignment

```sql
SELECT b.*, sb.side
FROM bets b
JOIN surebet_bets sb ON b.id = sb.bet_id
WHERE sb.surebet_id = ?
ORDER BY sb.side, b.associate_id;
```

#### Export Full Ledger

```sql
SELECT
    le.id,
    le.type,
    a.display_alias AS associate,
    bk.bookmaker_name,
    le.amount_native,
    le.native_currency,
    le.fx_rate_snapshot,
    le.amount_eur,
    le.settlement_state,
    le.principal_returned_eur,
    le.per_surebet_share_eur,
    le.surebet_id,
    le.bet_id,
    le.settlement_batch_id,
    le.created_at_utc,
    le.note
FROM ledger_entries le
JOIN associates a ON le.associate_id = a.id
LEFT JOIN bookmakers bk ON le.bookmaker_id = bk.id
ORDER BY le.created_at_utc ASC;
```

---

## Database Initialization

### Schema Creation Script

```python
# src/core/database.py
def create_schema(conn):
    """Create all tables with indexes"""

    # Enable foreign keys first
    conn.execute("PRAGMA foreign_keys = ON")

    # Create tables in dependency order
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS associates (...);
        CREATE TABLE IF NOT EXISTS bookmakers (...);
        CREATE TABLE IF NOT EXISTS canonical_events (...);
        CREATE TABLE IF NOT EXISTS canonical_markets (...);
        CREATE TABLE IF NOT EXISTS bets (...);
        CREATE TABLE IF NOT EXISTS surebets (...);
        CREATE TABLE IF NOT EXISTS surebet_bets (...);
        CREATE TABLE IF NOT EXISTS ledger_entries (...);
        CREATE TABLE IF NOT EXISTS verification_audit (...);
        CREATE TABLE IF NOT EXISTS multibook_message_log (...);
        CREATE TABLE IF NOT EXISTS bookmaker_balance_checks (...);
        CREATE TABLE IF NOT EXISTS fx_rates_daily (...);

        -- Create all indexes
        CREATE INDEX IF NOT EXISTS idx_bets_status ON bets(status);
        -- ... (all other indexes)
    """)

    conn.commit()
```

---

## Data Migration Strategy

### Backup Before Changes

```bash
# Backup SQLite file
cp data/surebet.db data/surebet.db.backup_$(date +%Y%m%d_%H%M%S)

# Export full ledger
sqlite3 data/surebet.db ".mode csv" ".output data/exports/ledger_backup.csv" "SELECT * FROM ledger_entries;"
```

### Schema Migrations

```python
# Future: Use alembic or simple version tracking
CREATE TABLE schema_version (
    version INTEGER PRIMARY KEY,
    applied_at_utc TEXT NOT NULL
);

INSERT INTO schema_version (version) VALUES (1);
```

---

## Performance Optimization

### Expected Data Volumes (1 Year)

| Table | Rows (Est.) | Size |
|-------|-------------|------|
| `bets` | ~6,000 | ~2 MB |
| `surebets` | ~2,400 | ~100 KB |
| `ledger_entries` | ~7,200 | ~3 MB |
| `fx_rates_daily` | ~365 | ~20 KB |
| Total | ~16,000 | ~5 MB |

**Conclusion:** SQLite easily handles this scale. No query optimization needed for MVP.

### Index Coverage

All common queries covered by indexes:
- `status` filters (incoming bets, open surebets)
- `associate_id` lookups (reconciliation)
- `created_at_utc` sorting (settlement by kickoff)
- `surebet_id` joins (ledger entries per surebet)

---

## Data Integrity Checks

### Foreign Key Validation

```sql
PRAGMA foreign_key_check;
```

### Ledger Balance Check

```sql
-- Verify: Sum of all ledger entries per associate matches expected
SELECT
    associate_id,
    SUM(CAST(amount_eur AS REAL)) AS total_eur
FROM ledger_entries
GROUP BY associate_id;
```

---

**End of Document**
