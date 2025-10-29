# Data Flows & Sequence Diagrams

**Version:** v4
**Last Updated:** 2025-10-29
**Parent Document:** [Architecture Overview](../architecture.md)

---

## Overview

This document illustrates key data flows through the system using sequence diagrams and flow charts.

---

## Flow 1: Telegram Screenshot Ingestion (FR-1)

```mermaid
sequenceDiagram
    participant Associate
    participant TelegramAPI
    participant Bot as Telegram Bot
    participant Ingest as BetIngestionService
    participant OpenAI as GPT-4o
    participant DB as SQLite

    Associate->>TelegramAPI: Send screenshot to bookmaker chat
    TelegramAPI->>Bot: Photo update (message_id: 123456)

    Bot->>Bot: Check if chat is whitelisted
    alt Chat not whitelisted
        Bot->>TelegramAPI: Reply "Not authorized"
        TelegramAPI->>Associate: Warning message
    else Chat whitelisted
        Bot->>Bot: Download photo
        Bot->>Ingest: ingest_telegram_screenshot()

        Ingest->>DB: Save screenshot path
        Ingest->>OpenAI: Extract bet data (OCR)
        OpenAI-->>Ingest: JSON (event, market, odds, confidence)

        Ingest->>DB: INSERT bets (status='incoming')
        Ingest-->>Bot: bet_id

        Bot->>TelegramAPI: Reply "Bet received! ID: 123"
        TelegramAPI-->>Associate: Confirmation
    end
```

**Key Points:**
- Bot whitelists chats to prevent unauthorized ingestion
- OCR runs immediately (async)
- If OCR fails, bet created with `confidence=0.0`

---

## Flow 2: Manual Screenshot Upload (FR-1.2)

```mermaid
sequenceDiagram
    participant Operator
    participant UI as Streamlit UI
    participant Ingest as BetIngestionService
    participant OpenAI as GPT-4o
    participant DB as SQLite

    Operator->>UI: Select screenshot file
    Operator->>UI: Choose associate + bookmaker
    Operator->>UI: Click "Import & OCR"

    UI->>Ingest: ingest_manual_screenshot()
    Ingest->>DB: Save screenshot to data/screenshots/
    Ingest->>OpenAI: Extract bet data
    OpenAI-->>Ingest: JSON (event, market, odds)
    Ingest->>DB: INSERT bets (status='incoming', source='manual_upload')
    Ingest-->>UI: bet_id

    UI-->>Operator: "Bet #123 created! Check Incoming Bets page."
```

**Difference from Telegram Flow:**
- `ingestion_source='manual_upload'`
- `telegram_message_id=NULL`
- Otherwise identical pipeline

---

## Flow 3: Bet Review & Approval (FR-2)

```mermaid
sequenceDiagram
    participant Operator
    participant UI as Streamlit UI
    participant Verify as BetVerificationService
    participant Matcher as SurebetMatcher
    participant DB as SQLite

    Operator->>UI: Open "Incoming Bets" page
    UI->>DB: SELECT * FROM bets WHERE status='incoming'
    DB-->>UI: List of incoming bets

    UI-->>Operator: Display bet cards (screenshot + OCR data)

    alt Operator approves bet
        Operator->>UI: Edit fields (if needed)
        Operator->>UI: Click "Approve"

        UI->>Verify: approve_bet(bet_id, edits)

        alt Edits provided
            Verify->>DB: INSERT verification_audit (old/new values)
            Verify->>DB: UPDATE bets (apply edits)
        end

        Verify->>DB: UPDATE bets SET status='verified'
        Verify->>Matcher: attempt_match(bet_id)

        Matcher->>DB: Query verified bets (same event/market/line, opposite side)

        alt Match found
            Matcher->>DB: INSERT surebets (status='open')
            Matcher->>DB: INSERT surebet_bets (link bets with side='A'/'B')
            Matcher->>DB: UPDATE bets SET status='matched'
            Matcher-->>Verify: surebet_id
        else No match
            Matcher-->>Verify: None
        end

        Verify-->>UI: Success
        UI-->>Operator: "Bet approved!"

    else Operator rejects bet
        Operator->>UI: Click "Reject"
        UI->>Verify: reject_bet(bet_id)
        Verify->>DB: UPDATE bets SET status='rejected'
        Verify-->>UI: Success
        UI-->>Operator: "Bet rejected"
    end
```

**Key Points:**
- All edits logged in `verification_audit`
- Matching attempted immediately after verification
- If no opposing bet found, bet remains `verified` (waits for match)

---

## Flow 4: Surebet Settlement (FR-6)

```mermaid
sequenceDiagram
    participant Operator
    participant UI as Streamlit UI
    participant Engine as SettlementEngine
    participant FX as FXManager
    participant DB as SQLite

    Operator->>UI: Open "Settlement" page
    UI->>DB: SELECT * FROM surebets WHERE status='open' ORDER BY kickoff_time_utc
    DB-->>UI: List of unsettled surebets

    Operator->>UI: Select surebet
    UI->>DB: Load bets for surebet (with screenshots)
    DB-->>UI: Bets (Side A + Side B)

    UI-->>Operator: Display bets + screenshots

    Operator->>UI: Choose outcome ("Side A WON")
    Operator->>UI: Override individual bets (if needed)
    UI-->>Operator: Preview settlement (profit, shares, entitlements)

    Operator->>UI: Click "SETTLE"
    UI-->>Operator: Confirm modal ("This is PERMANENT")
    Operator->>UI: Click again to confirm

    UI->>Engine: settle_surebet(surebet_id, outcome, overrides)

    Engine->>DB: Load all bets for surebet
    Engine->>Engine: Apply outcome + overrides
    Engine->>Engine: Calculate net_gain_eur per bet

    loop For each bet's currency
        Engine->>FX: get_fx_rate(currency, today)
        FX->>DB: Check fx_rates_daily cache
        alt Cached
            FX-->>Engine: Cached rate
        else Not cached
            FX->>ExternalAPI: Fetch rate
            ExternalAPI-->>FX: Rate
            FX->>DB: INSERT fx_rates_daily
            FX-->>Engine: Fresh rate
        end
    end

    Engine->>Engine: Calculate surebet_profit_eur
    Engine->>Engine: Determine N (participants + admin seat)
    Engine->>Engine: Calculate per_surebet_share_eur

    Engine->>Engine: Generate settlement_batch_id (UUID)

    loop For each associate's bets
        Engine->>DB: INSERT ledger_entries (type='BET_RESULT')
    end

    Engine->>DB: UPDATE surebets SET status='settled'
    Engine->>DB: UPDATE bets SET status='settled'

    Engine-->>UI: settlement_batch_id
    UI-->>Operator: "Settled! Batch ID: abc-123"
```

**Key Points:**
- Settlement creates **one ledger entry per associate** (not per bet, but grouped)
- All entries share `settlement_batch_id` for grouping
- FX rates frozen at settlement time (never recalculated)

---

## Flow 5: Coverage Proof Delivery (FR-5)

```mermaid
sequenceDiagram
    participant Operator
    participant UI as Streamlit UI
    participant Coverage as CoverageProofService
    participant Bot as Telegram Bot
    participant TelegramAPI
    participant DB as SQLite

    Operator->>UI: Open "Surebets" page
    Operator->>UI: Select surebet
    Operator->>UI: Click "Send Coverage Proof"

    UI->>Coverage: send_coverage_proof(surebet_id)

    Coverage->>DB: Load surebet + all bets + screenshots
    Coverage->>Coverage: Group bets by side (A vs B)

    loop For each associate on Side A
        Coverage->>DB: Get multibook chat_id for associate
        Coverage->>Coverage: Collect all Side B screenshots
        Coverage->>Bot: send_media_group(chat_id, screenshots)
        Bot->>TelegramAPI: Send photos with caption
        TelegramAPI-->>Bot: message_id
        Coverage->>DB: INSERT multibook_message_log
    end

    loop For each associate on Side B
        Coverage->>DB: Get multibook chat_id
        Coverage->>Coverage: Collect all Side A screenshots
        Coverage->>Bot: send_media_group(chat_id, screenshots)
        Bot->>TelegramAPI: Send photos
        Coverage->>DB: INSERT multibook_message_log
    end

    Coverage-->>UI: Success
    UI-->>Operator: "Coverage proof sent to all associates!"
```

**Key Points:**
- Manual trigger only (no automatic messaging)
- Each associate receives opposite side's screenshots
- All sends logged in `multibook_message_log`

---

## Flow 6: Reconciliation Calculation (FR-8)

```mermaid
graph TD
    A[Reconciliation Page] -->|Query| B[Load all ledger_entries for associate]

    B --> C{Filter by type}

    C -->|DEPOSIT / WITHDRAWAL| D[SUM amount_eur]
    D --> E[NET_DEPOSITS_EUR]

    C -->|BET_RESULT| F[SUM principal_returned_eur + per_surebet_share_eur]
    F --> G[SHOULD_HOLD_EUR]

    C -->|All types| H[SUM amount_eur]
    H --> I[CURRENT_HOLDING_EUR]

    G --> J{Calculate DELTA}
    I --> J

    J --> K[DELTA = CURRENT_HOLDING_EUR - SHOULD_HOLD_EUR]

    K -->|DELTA > 0| L[Holding group float]
    K -->|DELTA ≈ 0| M[Balanced ✅]
    K -->|DELTA < 0| N[Short someone else holding your money]

    L --> O[Display to operator]
    M --> O
    N --> O
```

**SQL Queries:**

```sql
-- NET_DEPOSITS_EUR
SELECT SUM(
    CASE
        WHEN type = 'DEPOSIT' THEN CAST(amount_eur AS REAL)
        WHEN type = 'WITHDRAWAL' THEN -CAST(amount_eur AS REAL)
        ELSE 0
    END
) FROM ledger_entries WHERE associate_id = ?;

-- SHOULD_HOLD_EUR
SELECT SUM(
    CAST(principal_returned_eur AS REAL) + CAST(per_surebet_share_eur AS REAL)
) FROM ledger_entries WHERE associate_id = ? AND type = 'BET_RESULT';

-- CURRENT_HOLDING_EUR
SELECT SUM(CAST(amount_eur AS REAL))
FROM ledger_entries WHERE associate_id = ?;
```

---

## Flow 7: Monthly Statement Generation (FR-10)

```mermaid
sequenceDiagram
    participant Operator
    participant UI as Streamlit UI
    participant Statements as StatementService
    participant DB as SQLite

    Operator->>UI: Open "Monthly Statements" page
    Operator->>UI: Select associate
    Operator->>UI: Choose cutoff date (e.g., 2025-10-31)
    Operator->>UI: Click "Generate Statement"

    UI->>Statements: generate_statement(associate_id, cutoff_date)

    Statements->>DB: Query ledger_entries WHERE created_at_utc <= cutoff
    DB-->>Statements: Ledger entries

    Statements->>Statements: Calculate NET_DEPOSITS_EUR
    Statements->>Statements: Calculate SHOULD_HOLD_EUR
    Statements->>Statements: Calculate RAW_PROFIT_EUR = SHOULD_HOLD - DEPOSITS

    Statements->>Statements: Format human-readable text
    Note over Statements: "You funded €X total.\nYou're entitled to €Y.\nThat's €Z profit.\n50/50 split: €Z/2 each."

    Statements-->>UI: Statement (partner-facing + internal)

    UI-->>Operator: Display statement
    Note over Operator: Internal view also shows CURRENT_HOLDING_EUR and DELTA
```

**Important:** Statements are **presentation-only**, they do NOT:
- Create ledger entries
- Change entitlement math
- Trigger any database writes

---

## Flow 8: Append-Only Ledger Correction (FR-7)

```mermaid
sequenceDiagram
    participant Operator
    participant UI as Streamlit UI
    participant Ledger as LedgerService
    participant DB as SQLite

    Note over Operator: Discovers late VOID (bet was settled as LOST, but should be VOID)

    Operator->>UI: Open "Reconciliation" page
    Operator->>UI: Select associate + bookmaker
    Operator->>UI: Click "Apply Correction"

    UI-->>Operator: Correction form (amount, currency, note)

    Operator->>UI: Enter correction (-50 AUD, "Late VOID correction")
    Operator->>UI: Confirm

    UI->>Ledger: create_correction(associate_id, bookmaker_id, amount, currency, note)

    Ledger->>FX: get_fx_rate('AUD', today)
    FX-->>Ledger: fx_rate_snapshot

    Ledger->>DB: INSERT ledger_entries (type='BOOKMAKER_CORRECTION')
    Note over DB: amount_native=-50, amount_eur=-33.33, fx_rate_snapshot=1.50

    Ledger-->>UI: Success
    UI-->>Operator: "Correction applied! Ledger updated."

    Note over DB: Original BET_RESULT entry NEVER deleted or modified (append-only)
```

**Key Principle:** Never reopen old surebets. All fixes are forward-only adjustments.

---

## Data Lifecycle Summary

```
┌─────────────────────────────────────────────────────────────┐
│ 1. INGESTION (Telegram or Manual)                           │
│    Screenshot → OCR → bets (status='incoming')              │
└────────────┬────────────────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. VERIFICATION (Operator Approval)                         │
│    Operator edits → bets (status='verified')                │
│    → verification_audit logged                              │
└────────────┬────────────────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. MATCHING (Automatic)                                     │
│    Opposite bet found → surebets (status='open')            │
│    → surebet_bets links created                             │
│    → bets (status='matched')                                │
└────────────┬────────────────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. SETTLEMENT (Operator Confirms)                           │
│    Choose outcome → ledger_entries (type='BET_RESULT')      │
│    → surebets (status='settled')                            │
│    → bets (status='settled')                                │
└────────────┬────────────────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. RECONCILIATION (Daily Health Check)                      │
│    Calculate DELTA per associate                            │
│    → Flag anomalies                                         │
│    → Apply corrections if needed                            │
└────────────┬────────────────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────────┐
│ 6. EXPORT (Backup & Audit)                                  │
│    Export ledger → CSV (data/exports/)                      │
│    Generate monthly statements                              │
└─────────────────────────────────────────────────────────────┘
```

---

**End of Document**
