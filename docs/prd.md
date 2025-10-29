# Product Requirements Document: Surebet Accounting System

**Version:** v4
**Status:** Draft
**Last Updated:** 2025-10-29
**Owner:** Product Manager (John)
**Stakeholders:** Solo Operator/Administrator

---

## Executive Summary

The Surebet Accounting System is a local-first, single-operator MVP designed to replace manual spreadsheet-based arbitrage betting operations with an automated, auditable system. The application streamlines the entire lifecycle of surebet management—from bet ingestion via Telegram screenshots (or manual upload) to settlement, reconciliation, and partner statement generation.

### Key Value Propositions

- **Automated Bet Ingestion**: OCR + GPT-4o extracts structured bet data from screenshots sent via Telegram or uploaded manually
- **Deterministic Surebet Matching**: Automatically groups opposite sides of two-way markets based on strict matching rules
- **Transparent Settlement**: Equal-split profit/loss distribution with frozen FX rates and append-only ledger
- **Real-time Reconciliation**: Track who's holding group float vs. who's short across all associates and bookmakers
- **Monthly Statements**: Generate human-readable partner reports showing funding, entitlement, and 50/50 profit splits

### Target User

Single operator managing a trusted network of associates betting on two-way arbitrage opportunities across multiple bookmakers and currencies.

---

## Problem Statement

### Current State (Pain Points)

Today, the operator manually manages surebet operations through:

1. **Manual coordination**: DM each associate separately with betting instructions
2. **Screenshot chaos**: Screenshots forwarded across multiple Telegram chats
3. **Spreadsheet hell**: Manual tracking of stakes, settlements, balances, and FX conversions
4. **Reconciliation nightmares**: Manually calculating who's holding group money vs. who's short
5. **Settlement errors**: Prone to mistakes when calculating equal splits, admin shares, and currency conversions
6. **No audit trail**: Difficult to trace historical decisions or verify calculations

### Desired State

A local application that:

- Automatically ingests bet screenshots from Telegram (and supports manual uploads for off-platform bets)
- Normalizes bet data using AI with human approval workflow
- Deterministically groups opposite sides into surebets
- Calculates worst-case EUR profit and ROI for each surebet
- Handles settlement with equal-split logic, admin share, and VOID handling
- Maintains an append-only ledger with frozen FX snapshots
- Shows real-time reconciliation: who's overholding vs. short
- Generates monthly partner statements in plain language

---

## User Personas

### Primary Persona: The Operator (You)

**Role**: Administrator + Accountant
**Responsibilities**:
- Spot arbitrage opportunities using external software
- Coordinate betting instructions to associates
- Verify bet screenshots and approve/correct data
- Match opposite sides into surebets
- Settle matches and grade outcomes
- Reconcile bookmaker balances
- Generate partner statements

**Key Needs**:
- Single source of truth for all betting activity
- Confidence in settlement calculations (equal splits, admin share, VOID handling)
- Visibility into who's holding group float vs. who's short
- Audit trail for all money movements
- Human-readable partner reports

### Secondary Persona: Associates (Trusted Partners)

**Role**: Bet placers
**Characteristics**:
- Trusted human friends, no adversarial relationship
- Use different currencies (AUD, GBP, EUR, etc.)
- Send bet screenshots via Telegram (or occasionally via WhatsApp/in-person photos)
- Occasionally deposit or withdraw funds

**Key Needs**:
- Simple interface (Telegram for bet submission)
- Coverage proof (screenshots of opposite side bets)
- Clear monthly statements showing their funding and profit share

---

## System Laws (Non-Negotiable Constraints)

These are contractual rules the system MUST enforce 100% of the time:

### 1. Append-Only Ledger
Money-impacting history is never edited in place. Fixes are forward adjustments (BOOKMAKER_CORRECTION). No rewrites.

### 2. Frozen FX
Every ledger row stores the `fx_rate_snapshot` used at creation. All EUR math later uses that snapshot. We never "revalue" old rows if FX changes.

### 3. Equal-Split Settlement
After a surebet is graded, total profit/loss in EUR is split into equal slices:
- If you (admin) DID stake, you're just another participant
- If you did NOT stake, you still get exactly one extra seat in the split as coordinator, and that seat also eats losses
- There is never a second skim/fee

### 4. VOID Still Participates
VOID means stake refunded (net_gain_eur = 0), but that associate is still considered part of the surebet for splitting profit/loss. If an entire surebet is VOID on all sides, we still produce BET_RESULT rows with zeros so entitlement history is continuous.

### 5. Manual Truth About Match Results
You decide who won. The system does not auto-grade sports results.

### 6. No Silent Messaging
Bot only sends screenshots into multibook chats when you explicitly press "Send coverage proof." It never DMs results or balances on its own.

---

## Functional Requirements

### FR-1: Bet Ingestion

#### FR-1.1: Telegram Ingestion (Primary Path)
**Priority**: P0 (MVP Critical)

**Description**: Automatically ingest bet screenshots sent to Telegram bookmaker chats.

**Acceptance Criteria**:
- One Telegram chat per bookmaker (maps to `associate_id + bookmaker_id`)
- One multibook chat per associate (for coverage proof delivery)
- When associate sends screenshot:
  - Bot saves screenshot under `data/screenshots/`
  - Creates `bets` row with `status="incoming"`
  - Sets `ingestion_source="telegram"`
  - Sets `telegram_message_id`
  - Runs OCR + GPT-4o to extract:
    - `canonical_event` guess
    - `market_code`, `period_scope`, `line_value`, `side`
    - `stake`, `odds`, `payout`, `currency`
    - `kickoff_time_utc` guess
    - `normalization_confidence` score
    - `model_version_extraction`, `model_version_normalization`
- Accumulators/multis are flagged as `is_multi=1`, `is_supported=0` (never matched)

#### FR-1.2: Manual Upload (Secondary Path)
**Priority**: P0 (MVP Critical)

**Description**: Support manual screenshot upload for off-Telegram bets (WhatsApp, camera photos, etc.).

**Acceptance Criteria**:
- "Incoming Bets" page includes "Upload Manual Bet" panel with:
  - Screenshot file picker
  - Associate selector (dropdown by `display_alias`)
  - Bookmaker selector (filtered by associate's bookmakers)
  - Optional free-text note
- On "Import & OCR" click:
  - Save screenshot under `data/screenshots/`
  - Create `bets` row with `status="incoming"`, `ingestion_source="manual_upload"`, `telegram_message_id=NULL`
  - Run same OCR/normalization pipeline as Telegram
  - Bet appears in Incoming Bets queue identically to Telegram bets

---

### FR-2: Bet Review & Approval

**Priority**: P0 (MVP Critical)

**Description**: Single queue for reviewing all incoming bets (Telegram + manual) with approval/rejection workflow.

**Acceptance Criteria**:
- "Incoming Bets" page shows all bets with `status="incoming"` regardless of `ingestion_source`
- Each bet displays:
  - Screenshot preview
  - Associate, bookmaker
  - Event guess (editable dropdown/search)
  - `market_code`, `period_scope`, `line_value`, `side`
  - Stake, odds, payout
  - Confidence badge: ✅ (high) or ⚠ (low)
- Operator can:
  - Inline edit any field (stake, odds, payout, canonical_event_id, market_code, period_scope, line_value, side)
  - Approve → `status="verified"` (all edits logged in `verification_audit`)
  - Reject → `status="rejected"`
- Counters display:
  - Waiting review: X
  - Approved today: Y
  - Rejected today: Z
- Nothing is auto-approved silently

**Nice-to-Have (MVP-Optional)**:
- "Likely matches" dropdown for `canonical_event_id` based on upcoming events

---

### FR-3: Deterministic Surebet Matching

**Priority**: P0 (MVP Critical)

**Description**: Automatically group verified bets into surebets based on strict matching rules.

**Acceptance Criteria**:
- After bet is `verified`, attempt matching using:
  - Same `canonical_event_id`
  - Same `market_code`
  - Same `period_scope`
  - Same `line_value`
  - Opposite logical side:
    - OVER vs UNDER
    - YES vs NO
    - TEAM_A vs TEAM_B
- On match:
  - Create/update `surebets` row with `status="open"`
  - Insert bet links into `surebet_bets` with deterministic `side` mapping:
    - `side="A"` = OVER / YES / TEAM_A
    - `side="B"` = UNDER / NO / TEAM_B
  - Set matched bets to `status="matched"`
- Treat entire opposing set as ONE surebet (e.g., A+B vs C = one surebet, not multiple pairwise)
- `surebet_bets.side` MUST NEVER flip after initial assignment

---

### FR-4: Surebet Safety Check (ROI Classification)

**Priority**: P0 (MVP Critical)

**Description**: Calculate and display worst-case EUR profit and ROI for each surebet.

**Acceptance Criteria**:
- For each `surebet`, using EUR values via cached FX:
  - Compute `profit_if_A_wins_eur`
  - Compute `profit_if_B_wins_eur`
  - `worst_case_profit_eur = min(profit_if_A_wins, profit_if_B_wins)`
  - `total_staked_eur`
  - `ROI = worst_case_profit_eur / total_staked_eur`
- Label:
  - ✅ if `worst_case_profit_eur ≥ 0` and ROI ≥ threshold
  - 🟡 if `worst_case_profit_eur ≥ 0` but ROI < threshold
  - ❌ if `worst_case_profit_eur < 0`
- Display: worst-case EUR profit, total EUR staked, ROI classification

---

### FR-5: Coverage Proof Distribution

**Priority**: P0 (MVP Critical)

**Description**: Manually send coverage proof screenshots to associates' multibook chats.

**Acceptance Criteria**:
- "Send coverage proof" button on each open surebet
- On click:
  - For each associate on Side A: send all Side B screenshots to their multibook chat
  - For each associate on Side B: send all Side A screenshots to their multibook chat
  - Message text: "You're covered for [EVENT / MARKET LINE]. Opposite side attached."
- Log to `multibook_message_log`:
  - Which screenshots forwarded
  - Timestamp
  - Telegram message ID
- No automatic messaging (System Law #6)
- No screenshot anonymization

---

### FR-6: Settlement & Grading

**Priority**: P0 (MVP Critical)

**Description**: Settle surebets in kickoff order with WON/LOST/VOID grading and equal-split calculation.

**Acceptance Criteria**:
- Settlement page lists surebets sorted by `kickoff_time_utc` (oldest first)
- For selected surebet, display:
  - Both sides with associate alias, bookmaker, stake@odds, screenshot link
- Operator picks base outcome:
  - "Side A WON / Side B LOST" or vice versa
- Operator can override individual bets to WON / LOST / VOID
- Preview shows:
  - `surebet_profit_eur` (can be positive or negative)
  - N (participant count, including admin seat if operator didn't stake)
  - `per_surebet_share_eur`
  - `principal_returned_eur` per associate
  - Each associate's updated entitlement from this surebet
  - FX rate snapshot
  - VOID rule warning ("VOID still participates in split")
- On confirm (with modal "This is permanent"):
  - Create one `settlement_batch_id` for this click
  - For each associate's bets, write `ledger_entries` row of type `"BET_RESULT"`:
    - `settlement_state` (WON/LOST/VOID)
    - `amount_native`, `native_currency`
    - `fx_rate_snapshot` (Decimal EUR per 1 unit native at this moment)
    - `amount_eur` (bet's net gain/loss in EUR)
    - `principal_returned_eur` (stake returned via WON/VOID)
    - `per_surebet_share_eur` (equal-split seat from this surebet)
    - `associate_id`, `bookmaker_id`, `surebet_id`, `bet_id`
    - `settlement_batch_id`, `created_at_utc`, `created_by="local_user"`, `note`
  - Mark `surebet.status="settled"` and bets `status="settled"`
- Edge case: All bets VOID → still write BET_RESULT rows with zeros
- No automatic DM of results to associates
- Counters display:
  - Settled today: C
  - Still open (unsettled): D

---

### FR-7: Post-Settlement Corrections

**Priority**: P0 (MVP Critical)

**Description**: Support forward-only corrections for late VOIDs, grading errors, or balance mismatches.

**Acceptance Criteria**:
- Never reopen old surebets
- Create forward-only `ledger_entries` row of type `"BOOKMAKER_CORRECTION"`:
  - `amount_native`, `native_currency`
  - `fx_rate_snapshot`, `amount_eur`
  - `associate_id`, `bookmaker_id`
  - `created_at_utc`, `created_by="local_user"`
  - `note` (e.g., "late VOID correction", "misclick fix")
- Honors System Law #1 (append-only ledger)

---

### FR-8: Reconciliation & Health Check

**Priority**: P0 (MVP Critical)

**Description**: Daily reconciliation showing who's overholding vs. short, with pending funding events and bookmaker balance checks.

**Acceptance Criteria**:

#### Pending Funding Events
- Show parsed "deposit X" / "withdraw Y" drafts OR manual entry fields
- Accept → write DEPOSIT/WITHDRAWAL ledger rows
- Reject → discard

#### Per Associate Summary
Display canonical reconciliation fields:
- **NET_DEPOSITS_EUR**: How much cash they personally funded
  `(Sum of DEPOSIT.amount_eur) - (Sum of WITHDRAWAL.amount_eur)`
- **SHOULD_HOLD_EUR** (Entitlement): How much of the pool belongs to them
  `SUM(principal_returned_eur + per_surebet_share_eur)` across their BET_RESULT rows
- **CURRENT_HOLDING_EUR**: What the model thinks they're physically holding
  Sum of all ledger entries (BET_RESULT + DEPOSIT + WITHDRAWAL + BOOKMAKER_CORRECTION) converted via `fx_rate_snapshot`
- **DELTA**: `CURRENT_HOLDING_EUR - SHOULD_HOLD_EUR`
  - `DELTA > 0`: Holding group float (red)
  - `DELTA ≈ 0`: Balanced (green)
  - `DELTA < 0`: Short / someone else holding their money (orange)
- Human explanation string: "Holding +€800 more than entitlement (group float you should collect)"

#### Per Bookmaker Drilldown
- Modeled balance (native + EUR)
- Reported live balance (from `bookmaker_balance_checks`)
- Difference
- "Apply correction" button → writes BOOKMAKER_CORRECTION row

**Note**: `bookmaker_balance_checks` rows do NOT auto-create corrections. Operator decides manually.

---

### FR-9: Ledger Export

**Priority**: P0 (MVP Critical)

**Description**: Export complete auditable ledger to CSV.

**Acceptance Criteria**:
- Export all `ledger_entries` joined with:
  - Associate alias
  - Bookmaker name
  - `surebet_id`, `bet_id`, `settlement_batch_id`
  - `fx_rate_snapshot`
- Output to: `data/exports/ledger_<timestamp>.csv`
- CSV is the audit trail

---

### FR-10: Monthly Statements (Partner Reports)

**Priority**: P0 (MVP Critical)

**Description**: Generate per-associate summary statements for period end (e.g., "End of October 2025").

**Acceptance Criteria**:
- For each associate at cutoff timestamp, calculate:
  1. **NET_DEPOSITS_EUR**: `(Sum DEPOSIT.amount_eur) - (Sum WITHDRAWAL.amount_eur)` up to cutoff
     "How much cash you personally put in."
  2. **SHOULD_HOLD_EUR**: `SUM(principal_returned_eur + per_surebet_share_eur)` across all BET_RESULT rows up to cutoff
     "If we froze time right now, this much of the pot is yours."
  3. **RAW_PROFIT_EUR**: `SHOULD_HOLD_EUR - NET_DEPOSITS_EUR`
     "How far ahead you are compared to what you funded." (Can be negative)
- Presentation format (what you'd DM):
  - "You funded €X total."
  - "Right now you're entitled to €Y."
  - "That means you're up €Z overall."
  - "Our deal is 50/50, so €Z/2 each."
- Internal-only (visible to operator):
  - `CURRENT_HOLDING_EUR`
  - `DELTA = CURRENT_HOLDING_EUR - SHOULD_HOLD_EUR`
- Monthly Statements:
  - Do NOT change entitlement math
  - Do NOT create ledger rows
  - Are presentation only

---

## Data Model

See [Data Model Document](docs/prd/data-model.md) for complete schema specifications.

### Core Tables Summary

| Table | Purpose |
|-------|---------|
| `associates` | Trusted partners (including admin) |
| `bookmakers` | Bookmaker accounts per associate |
| `canonical_events` | Normalized sporting events |
| `canonical_markets` | Market type definitions |
| `bets` | Individual bet records (incoming → verified → matched → settled) |
| `surebets` | Grouped opposing bets |
| `surebet_bets` | Junction table linking bets to surebets with side assignment |
| `ledger_entries` | Append-only financial ledger (BET_RESULT, DEPOSIT, WITHDRAWAL, BOOKMAKER_CORRECTION) |
| `verification_audit` | Bet approval/edit history |
| `multibook_message_log` | Coverage proof delivery log |
| `bookmaker_balance_checks` | Associate-reported balances |
| `fx_rates_daily` | Currency → EUR conversion cache |

---

## Technical Architecture

### Deployment Model (Non-Negotiable)

- **Single machine** ("accountant machine")
- **Single human operator** (you)
- **No login / no RBAC / no multi-tenant**
- **App is local-only**
- **Data is local-only**

### Local Components

- **Telegram bot**: Polling mode, `python-telegram-bot` v20+
- **Streamlit app**: UI at `localhost:8501`
- **SQLite DB**: `data/surebet.db` (WAL mode)
- **Screenshot storage**: `data/screenshots/`
- **Ledger exports**: `data/exports/`
- **FX cache**: `fx_rates_daily` table in SQLite

### External Dependencies

- **OCR / LLM**: GPT-4o for extraction and normalization
- **FX API**: Currency → EUR conversions (cached locally)

### Technology Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.12 |
| UI Framework | Streamlit |
| Database | SQLite (WAL mode) |
| Telegram Integration | python-telegram-bot v20+ |
| OCR/AI | GPT-4o (OpenAI API) |
| Currency Math | Decimal (stored as TEXT) |
| Timestamps | UTC ISO8601 with "Z" |

### Key Technical Constraints

- All currency math in `Decimal` stored as TEXT
- All timestamps stored as UTC ISO8601 with "Z"
- Append-only ledger (System Law #1)
- Frozen FX snapshots (System Law #2)
- One FX rate per currency per day (reuse last known if no fresh rate)
- All EUR math is one-way (native → EUR at snapshot time)

---

## User Interface

### Page 1: Incoming Bets

**Sections**:

1. **Upload Manual Bet Panel**
   - File input for screenshot
   - Associate dropdown
   - Bookmaker dropdown (filtered by associate)
   - "Import & OCR" button

2. **Incoming Bets Queue**
   - All bets with `status="incoming"` (both Telegram and manual)
   - Screenshot preview
   - Associate, bookmaker
   - Event guess (editable)
   - Market details (market_code, period_scope, line_value, side)
   - Stake, odds, payout
   - Confidence badge: ✅ / ⚠
   - Inline editing
   - Approve / Reject buttons
   - Counters: Waiting review, Approved today, Rejected today

### Page 2: Surebets & Settlement

**Tab 1: Open & Coverage**
- Each open surebet shows:
  - Side A bets (associate, bookmaker, stake@odds)
  - Side B bets
  - Worst-case EUR profit
  - Total EUR staked
  - ROI classification: ✅ / 🟡 / ❌
  - Kickoff time
  - "Send coverage proof" button
- Counters: Open surebets, Unsafe surebets (❌)

**Tab 2: Settle**
- Surebets sorted by kickoff time (oldest first)
- Select surebet → view bets, screenshots, stakes, odds
- Choose outcome: "Side A WON / Side B LOST" etc.
- Override individual bets (WON / LOST / VOID)
- Preview: surebet_profit_eur, N, per_surebet_share_eur, principal_returned_eur, FX snapshot, VOID warning
- Confirm button (modal: "This is permanent")
- Counters: Settled today, Still open

### Page 3: Reconciliation / Health Check

**Sections**:

1. **Pending Funding Events**
   - Deposit/withdrawal drafts
   - Accept / Reject buttons

2. **Per Associate Summary**
   - NET_DEPOSITS_EUR
   - CURRENT_HOLDING_EUR
   - SHOULD_HOLD_EUR
   - DELTA (color-coded with explanation)

3. **Per Bookmaker Drilldown**
   - Modeled balance (native + EUR)
   - Reported balance
   - Difference
   - "Apply correction" button

### Page 4: Export

- Export ledger to CSV
- Output: `data/exports/ledger_<timestamp>.csv`

### Page 5: Monthly Statements

- Associate selector
- Cutoff date picker
- Display:
  - NET_DEPOSITS_EUR
  - SHOULD_HOLD_EUR
  - RAW_PROFIT_EUR
  - Human-readable 50/50 explanation
- Internal-only: CURRENT_HOLDING_EUR, DELTA

---

## Settlement Math Reference

See [Settlement Math Specification](docs/prd/settlement-math.md) for detailed formulas.

### Quick Reference

**Per Bet P/L in EUR**:
- WON: `net_gain_eur = payout_eur - stake_eur`
- LOST: `net_gain_eur = -stake_eur`
- VOID: `net_gain_eur = 0`

**Surebet Profit**:
- `surebet_profit_eur = sum(all bets' net_gain_eur)`

**Participants for Split**:
- If admin staked: `N = len(betting_participants)`
- If admin did NOT stake: `N = len(betting_participants) + 1`

**Equal Split**:
- `per_surebet_share_eur = surebet_profit_eur / N`

**Principal Returned**:
- `principal_returned_eur = sum(stake_eur for WON/VOID bets)`

**Entitlement Component**:
- `entitlement_component_eur = principal_returned_eur + per_surebet_share_eur`

---

## Success Metrics

### MVP Success Criteria (Definition of Done)

The MVP is complete when ALL of the following work locally:

1. ✅ Telegram bot ingestion of screenshots
2. ✅ Manual upload panel on Incoming Bets (screenshot → OCR → queue)
3. ✅ Incoming Bets review with manual correction
4. ✅ Deterministic surebet grouping (strict matching on event, market, period, line, opposite side)
5. ✅ ROI-based surebet safety labels (✅ / 🟡 / ❌)
6. ✅ Manual "Send coverage proof" logged in `multibook_message_log`
7. ✅ Settlement sorted by `kickoff_time_utc` with:
   - WON / LOST / VOID overrides
   - Equal-split math with admin seat logic
   - All-VOID still generating BET_RESULT rows
   - Single-click confirm producing ledger rows with shared `settlement_batch_id`
   - Confirm modal ("This action is permanent")
8. ✅ Append-only ledger with frozen `fx_rate_snapshot`
9. ✅ Reconciliation / Health Check page showing:
   - NET_DEPOSITS_EUR, CURRENT_HOLDING_EUR, SHOULD_HOLD_EUR, DELTA
   - Pending DEPOSIT/WITHDRAWAL drafts to Accept/Reject
   - Per-bookmaker modeled vs reported balance with "Apply correction"
10. ✅ CSV export of full ledger
11. ✅ Monthly Statements page generating partner-facing summaries

### Operational Success Metrics (Post-MVP)

- **Time Savings**: Reduce settlement time from 30+ min to <5 min per surebet
- **Error Reduction**: Zero settlement calculation errors vs. ~10% in spreadsheets
- **Reconciliation Speed**: Morning health check in <2 min vs. 20+ min manually
- **Audit Confidence**: 100% of financial decisions traceable in ledger

---

## MVP-Optional Features (Out of Scope for v1)

The following are explicitly **not required** for MVP but may be considered in future iterations:

- Telegram auto-capture of deposit/withdrawal intents (manual entry is acceptable)
- "Likely matches" dropdown for `canonical_event_id` (bare minimum is search dropdown)
- Automatic settlement result DMs to associates
- Multi-operator support
- Cloud deployment
- Mobile app
- Real-time surebet opportunity detection (external software assumed)

---

## Risks & Assumptions

### Assumptions

1. Operator has access to external arbitrage detection software
2. Associates are trusted human friends (no adversarial relationship)
3. Only two-way markets (Over/Under, Yes/No, Team A/Team B)
4. Operator manually confirms match results (no auto-grading)
5. All associates have stable Telegram access
6. OCR + GPT-4o provides >80% accuracy for high-confidence bets

### Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| OCR accuracy < 80% | Medium | High | Manual correction workflow with confidence badges |
| GPT-4o API downtime | Low | Medium | Queue bets for processing when API recovers |
| FX API unavailable | Low | Low | Reuse last known rate (cached in `fx_rates_daily`) |
| Telegram bot banned | Low | High | Polling mode + whitelist trusted chats only |
| SQLite corruption | Low | High | WAL mode + regular backup exports |
| Complex multi-leg bets | Medium | Low | Flag as `is_multi=1`, `is_supported=0` (never match) |

---

## Appendices

### Appendix A: Ledger Entry Types

| Type | When Created | Key Fields |
|------|--------------|------------|
| `BET_RESULT` | Settlement confirm | `settlement_state`, `principal_returned_eur`, `per_surebet_share_eur`, `settlement_batch_id` |
| `DEPOSIT` | Funding event accept | `amount_native`, `fx_rate_snapshot`, `amount_eur` |
| `WITHDRAWAL` | Funding event accept | `amount_native`, `fx_rate_snapshot`, `amount_eur` |
| `BOOKMAKER_CORRECTION` | Manual balance fix | `amount_native`, `fx_rate_snapshot`, `amount_eur`, `note` |

### Appendix B: Market Code Examples

- `FIRST_HALF_TOTAL_CORNERS_OVER_UNDER`
- `ASIAN_HANDICAP`
- `RED_CARD_YES_NO_FULL_MATCH`
- `TOTAL_GOALS_OVER_UNDER`
- `BOTH_TEAMS_TO_SCORE_YES_NO`

### Appendix C: Reconciliation Glossary

| Term | Definition | Formula |
|------|------------|---------|
| **NET_DEPOSITS_EUR** | Cash personally funded | `SUM(DEPOSIT) - SUM(WITHDRAWAL)` |
| **SHOULD_HOLD_EUR** | Entitlement after equal splits | `SUM(principal_returned_eur + per_surebet_share_eur)` |
| **CURRENT_HOLDING_EUR** | Modeled physical holdings | Sum of all ledger entries via `fx_rate_snapshot` |
| **DELTA** | Over/under holding | `CURRENT_HOLDING_EUR - SHOULD_HOLD_EUR` |
| **RAW_PROFIT_EUR** | Net P/L vs. funding | `SHOULD_HOLD_EUR - NET_DEPOSITS_EUR` |

---

## Document Control

**Version History**:

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| v4 | 2025-10-29 | John (PM Agent) | Initial PRD based on final-project.md specification |

**Approvals**:

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Product Owner | TBD | - | - |
| Tech Lead | TBD | - | - |
| Stakeholder | TBD | - | - |

---

**End of Document**
