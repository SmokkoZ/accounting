# Surebet Accounting System - Greenfield Implementation Roadmap

**Version:** 1.0
**Created:** 2025-10-29
**Owner:** Product Manager (John)
**Project Type:** Greenfield MVP
**Target Delivery:** Phased incremental releases

---

## Document Purpose

This roadmap provides a **phased implementation plan** for building the Surebet Accounting System from scratch. It organizes the 10 Functional Requirements from the PRD into logical delivery phases, respecting technical dependencies and enabling incremental value delivery.

---

## Implementation Philosophy

### Greenfield Approach

- **Foundation First**: Establish core data model and infrastructure before features
- **Vertical Slices**: Each phase delivers end-to-end functionality
- **Incremental Value**: Each phase produces a working (though incomplete) system
- **System Laws Enforced**: All phases respect the 6 non-negotiable constraints from PRD

### Phase Completion Criteria

Each phase is considered complete when:
- ✅ All stories are implemented with passing acceptance criteria
- ✅ Core functionality is manually tested end-to-end
- ✅ System Laws are enforced (append-only ledger, frozen FX, etc.)
- ✅ Data model is validated with real test data
- ✅ Next phase can begin without rework

---

## Phase 0: Foundation & Infrastructure

**Duration:** 3-5 days
**Goal:** Establish technical foundation before feature development

### Deliverables

#### 0.1 Project Setup
- Python 3.12 virtual environment
- Streamlit app scaffold (`app.py` running at localhost:8501)
- SQLite database initialization (`data/surebet.db` with WAL mode)
- Folder structure: `data/screenshots/`, `data/exports/`
- Requirements.txt with core dependencies

#### 0.2 Core Data Model
- All 11 core tables created (see PRD Data Model section):
  - `associates`, `bookmakers`, `canonical_events`, `canonical_markets`
  - `bets`, `surebets`, `surebet_bets`
  - `ledger_entries`, `verification_audit`
  - `multibook_message_log`, `bookmaker_balance_checks`, `fx_rates_daily`
- Schema validation script
- Seed data for testing (2 associates, 4 bookmakers)

#### 0.3 FX Rate System
- `fx_rates_daily` table populated with sample rates
- FX utility functions:
  - `get_fx_rate(currency, date) -> Decimal`
  - `convert_to_eur(amount, currency, fx_rate) -> Decimal`
- Decimal precision handling (stored as TEXT)
- UTC timestamp utilities (ISO8601 with "Z")

#### 0.4 Telegram Bot Scaffold
- `python-telegram-bot` v20+ integration
- Polling mode configuration
- Chat ID registration for bookmaker chats
- Basic command handlers (`/start`, `/help`)
- Screenshot receipt handler (no OCR yet, just file save)

### Success Criteria
- ✅ Streamlit app loads without errors
- ✅ Database schema created successfully
- ✅ Seed data inserted (2 associates, 4 bookmakers)
- ✅ Telegram bot connects and receives messages
- ✅ Screenshots saved to `data/screenshots/`
- ✅ FX conversion works correctly with Decimal math

### Dependencies
None (this is the foundation)

---

## Phase 1: Bet Ingestion Pipeline

**Duration:** 5-7 days
**Goal:** Automated + manual bet capture with AI extraction
**PRD Coverage:** FR-1 (Bet Ingestion)

### Stories

#### 1.1 Telegram Screenshot Ingestion
**As the operator**, I want screenshots sent to Telegram bookmaker chats to be automatically saved and queued for processing.

**Acceptance Criteria:**
- Associate sends screenshot to bookmaker-specific Telegram chat
- Bot saves screenshot to `data/screenshots/{timestamp}_{associate}_{bookmaker}.png`
- Creates `bets` row with `status="incoming"`, `ingestion_source="telegram"`
- Sets `telegram_message_id` for traceability
- No OCR yet (extracted fields remain NULL)

#### 1.2 OCR + GPT-4o Extraction Pipeline
**As the operator**, I want bet screenshots to be automatically parsed using GPT-4o vision to extract structured bet data.

**Acceptance Criteria:**
- Extraction service calls GPT-4o with screenshot
- Extracts and populates `bets` fields:
  - `canonical_event` (best guess), `market_code`, `period_scope`, `line_value`, `side`
  - `stake`, `odds`, `payout`, `currency`
  - `kickoff_time_utc` (best guess)
  - `normalization_confidence` (0.0-1.0)
  - `model_version_extraction`, `model_version_normalization`
- Flags accumulators: `is_multi=1`, `is_supported=0`
- Extraction errors logged, bet remains `status="incoming"` with NULL fields

#### 1.3 Manual Upload Panel (UI)
**As the operator**, I want to manually upload screenshots from WhatsApp/camera for off-Telegram bets.

**Acceptance Criteria:**
- "Incoming Bets" page includes "Upload Manual Bet" panel with:
  - File picker (PNG/JPG)
  - Associate dropdown (from `associates.display_alias`)
  - Bookmaker dropdown (filtered by selected associate's bookmakers)
  - Optional note field
- "Import & OCR" button triggers same pipeline as Telegram
- Creates `bets` row with `ingestion_source="manual_upload"`, `telegram_message_id=NULL`
- Bet appears in Incoming Bets queue identically to Telegram bets

### Success Criteria
- ✅ Telegram bets flow from chat → screenshot saved → `bets` table
- ✅ OCR extracts bet data with >80% accuracy for high-confidence bets
- ✅ Manual upload works for WhatsApp/camera photos
- ✅ All bets land in unified `status="incoming"` queue
- ✅ Accumulators flagged as unsupported

### Dependencies
- Phase 0 complete (Telegram bot scaffold, database schema)

---

## Phase 2: Bet Review & Approval

**Duration:** 3-4 days
**Goal:** Human-in-the-loop verification with inline editing
**PRD Coverage:** FR-2 (Bet Review & Approval)

### Stories

#### 2.1 Incoming Bets Queue (UI)
**As the operator**, I want a unified queue showing all incoming bets (Telegram + manual) for review.

**Acceptance Criteria:**
- "Incoming Bets" page displays all `status="incoming"` bets
- Each bet card shows:
  - Screenshot preview (click to enlarge)
  - Associate display alias, bookmaker name
  - Event guess (text display, editable in 2.2)
  - Market details: `market_code`, `period_scope`, `line_value`, `side`
  - Financial: stake, odds, payout, currency
  - Confidence badge: ✅ (≥0.8) or ⚠ (<0.8)
  - Ingestion source icon: 📱 (Telegram) or 📤 (manual)
  - Timestamp
- Counters at top:
  - "Waiting review: X"
  - "Approved today: Y"
  - "Rejected today: Z"

#### 2.2 Inline Editing & Approval
**As the operator**, I want to correct OCR errors and approve/reject bets inline.

**Acceptance Criteria:**
- Each bet has inline edit mode for:
  - `canonical_event_id` (dropdown/search of upcoming events)
  - `market_code`, `period_scope`, `line_value`, `side` (dropdowns)
  - `stake`, `odds`, `payout` (number inputs)
- "Approve" button:
  - Writes all edits to `verification_audit` table
  - Sets `status="verified"`
  - Bet moves to matching queue
- "Reject" button:
  - Sets `status="rejected"`
  - Optional rejection reason
  - Bet hidden from queue
- Edits are logged with timestamp and field changes

### Success Criteria
- ✅ All incoming bets visible in unified queue
- ✅ Operator can correct any extracted field
- ✅ Approval creates audit trail in `verification_audit`
- ✅ Rejected bets removed from queue
- ✅ Counters update in real-time

### Dependencies
- Phase 1 complete (bets flowing into `status="incoming"`)

---

## Phase 3: Surebet Matching & Safety

**Duration:** 5-6 days
**Goal:** Deterministic pairing + ROI classification
**PRD Coverage:** FR-3 (Surebet Matching), FR-4 (Safety Check)

### Stories

#### 3.1 Deterministic Matching Engine
**As the system**, I want verified bets to be automatically paired into surebets using strict matching rules.

**Acceptance Criteria:**
- On bet approval (→ `status="verified"`), trigger matching logic:
  - Match on: `canonical_event_id`, `market_code`, `period_scope`, `line_value`
  - Opposite logical side:
    - OVER ↔ UNDER
    - YES ↔ NO
    - TEAM_A ↔ TEAM_B
- On match found:
  - Create/update `surebets` row with `status="open"`
  - Insert into `surebet_bets` with deterministic side assignment:
    - `side="A"` for OVER / YES / TEAM_A
    - `side="B"` for UNDER / NO / TEAM_B
  - Set matched bets to `status="matched"`
- Treat multiple bets on same side as ONE group (A1+A2 vs B1 = one surebet)
- **Critical:** `surebet_bets.side` NEVER changes after initial assignment

#### 3.2 Worst-Case EUR Profit Calculation
**As the operator**, I want to see worst-case profit and ROI for each surebet to identify unsafe bets.

**Acceptance Criteria:**
- For each `surebets` row, calculate using cached FX rates:
  - `profit_if_A_wins_eur = (sum of Side A payouts in EUR) - (sum of all stakes in EUR)`
  - `profit_if_B_wins_eur = (sum of Side B payouts in EUR) - (sum of all stakes in EUR)`
  - `worst_case_profit_eur = min(profit_if_A_wins, profit_if_B_wins)`
  - `total_staked_eur = sum(all stakes in EUR)`
  - `roi = worst_case_profit_eur / total_staked_eur`
- Store in `surebets` table (or calculate on-demand)

#### 3.3 Surebet Safety UI
**As the operator**, I want visual indicators showing which surebets are safe vs. risky.

**Acceptance Criteria:**
- "Surebets" page lists all `status="open"` surebets
- Each surebet displays:
  - Event name, market, line
  - Side A bets (associate, bookmaker, stake@odds)
  - Side B bets (associate, bookmaker, stake@odds)
  - Worst-case EUR profit
  - Total EUR staked
  - ROI percentage
  - Safety badge:
    - ✅ Green if `worst_case_profit_eur ≥ 0` AND `roi ≥ threshold` (e.g., 1%)
    - 🟡 Yellow if `worst_case_profit_eur ≥ 0` but `roi < threshold`
    - ❌ Red if `worst_case_profit_eur < 0` (guaranteed loss)
  - Kickoff time
- Counter: "Unsafe surebets: X" (❌ count)

### Success Criteria
- ✅ Verified bets automatically paired into surebets
- ✅ No false matches (strict matching rules enforced)
- ✅ Side assignments (A/B) never flip after creation
- ✅ ROI calculated correctly with FX conversions
- ✅ Operator can visually identify risky surebets

### Dependencies
- Phase 2 complete (bets reaching `status="verified"`)
- Phase 0 FX system working

---

## Phase 4: Coverage Proof & Settlement

**Duration:** 7-9 days
**Goal:** Coverage distribution + equal-split settlement
**PRD Coverage:** FR-5 (Coverage Proof), FR-6 (Settlement & Grading)

### Stories

#### 4.1 Manual Coverage Proof Distribution
**As the operator**, I want to send opposite-side screenshots to associates' multibook chats for coverage proof.

**Acceptance Criteria:**
- Each open surebet has "Send coverage proof" button
- On click:
  - For each Side A associate: send all Side B screenshots to their multibook Telegram chat
  - For each Side B associate: send all Side A screenshots to their multibook Telegram chat
  - Message text: "You're covered for [EVENT / MARKET LINE]. Opposite side attached."
- Log to `multibook_message_log`:
  - `surebet_id`, `associate_id`, `telegram_message_id`, `screenshot_paths`, `sent_at_utc`
- No automatic sending (System Law #6)
- No screenshot anonymization (associates see raw opposite screenshots)

#### 4.2 Settlement Interface (Kickoff Order)
**As the operator**, I want to settle surebets in chronological kickoff order with WON/LOST/VOID grading.

**Acceptance Criteria:**
- "Settle" tab on Surebets page
- Lists `status="open"` surebets sorted by `kickoff_time_utc` (oldest first)
- Select surebet → shows:
  - Side A bets: associate, bookmaker, stake@odds, screenshot link
  - Side B bets: associate, bookmaker, stake@odds, screenshot link
- Operator selects base outcome:
  - "Side A WON / Side B LOST"
  - "Side B WON / Side A LOST"
- Operator can override individual bets to WON / LOST / VOID (checkbox toggles)

#### 4.3 Equal-Split Preview & Confirmation
**As the operator**, I want to preview equal-split math before creating permanent ledger entries.

**Acceptance Criteria:**
- Settlement preview panel shows:
  - Per-bet net gain/loss in EUR:
    - WON: `payout_eur - stake_eur`
    - LOST: `-stake_eur`
    - VOID: `0`
  - `surebet_profit_eur = sum(all bets' net_gain_eur)` (can be negative)
  - Participant count N:
    - If admin staked: `N = betting_participants`
    - If admin did NOT stake: `N = betting_participants + 1` (admin seat)
  - `per_surebet_share_eur = surebet_profit_eur / N` (equal split)
  - For each associate:
    - `principal_returned_eur` (stakes from WON/VOID bets)
    - `per_surebet_share_eur` (their seat in the split)
    - Updated entitlement component: `principal_returned + per_surebet_share`
  - FX rate snapshot (current rates at confirm time)
  - VOID warning: "VOID bets still participate in split"
- "Confirm Settlement" button with modal: "This action is permanent and cannot be undone. Proceed?"

#### 4.4 Ledger Entry Generation
**As the system**, I want settlement confirmation to write permanent append-only ledger rows.

**Acceptance Criteria:**
- On confirmation:
  - Generate single `settlement_batch_id = UUID()`
  - For EACH associate's bets in this surebet, write `ledger_entries` row:
    - `entry_type = "BET_RESULT"`
    - `associate_id`, `bookmaker_id`, `surebet_id`, `bet_id`
    - `settlement_state` (WON/LOST/VOID)
    - `amount_native` (net gain/loss in bookmaker currency)
    - `native_currency`
    - `fx_rate_snapshot` (Decimal EUR per 1 unit native, frozen at confirm time)
    - `amount_eur` (net gain/loss in EUR)
    - `principal_returned_eur` (stake returned via WON/VOID)
    - `per_surebet_share_eur` (equal-split seat from this surebet)
    - `settlement_batch_id`, `created_at_utc`, `created_by="local_user"`, `note`
  - Mark `surebets.status="settled"`
  - Mark all linked bets `status="settled"`
- Edge case: All bets VOID → still write BET_RESULT rows with zeros
- No DMs sent to associates (System Law #6)
- Counters update:
  - "Settled today: C"
  - "Still open: D"

### Success Criteria
- ✅ Coverage proof manually sent with logging
- ✅ Settlement UI sorted by kickoff time
- ✅ Equal-split math correct (including admin seat logic)
- ✅ VOID bets handled correctly (zero gain, but still participate)
- ✅ Ledger entries created with frozen FX snapshots
- ✅ Settlement is irreversible (append-only enforced)

### Dependencies
- Phase 3 complete (surebets created and classified)
- Phase 0 FX system and ledger schema ready

---

## Phase 5: Corrections & Reconciliation

**Duration:** 5-6 days
**Goal:** Forward-only fixes + real-time health check
**PRD Coverage:** FR-7 (Post-Settlement Corrections), FR-8 (Reconciliation)

### Stories

#### 5.1 Post-Settlement Correction Interface
**As the operator**, I want to apply forward-only corrections for late VOIDs or grading errors without reopening surebets.

**Acceptance Criteria:**
- "Corrections" page with form:
  - Associate selector
  - Bookmaker selector
  - Amount (native currency)
  - Currency selector
  - Note field (required, e.g., "Late VOID correction for Bet #123")
- "Apply Correction" button writes `ledger_entries` row:
  - `entry_type = "BOOKMAKER_CORRECTION"`
  - `amount_native`, `native_currency`
  - `fx_rate_snapshot` (current rate at correction time)
  - `amount_eur` (converted using snapshot)
  - `associate_id`, `bookmaker_id`
  - `surebet_id = NULL`, `bet_id = NULL` (corrections are standalone)
  - `created_at_utc`, `created_by="local_user"`, `note`
- No editing of old ledger rows (System Law #1: append-only)

#### 5.2 Reconciliation Dashboard (Associate View)
**As the operator**, I want to see who's overholding group float vs. who's short at a glance.

**Acceptance Criteria:**
- "Reconciliation" page displays per-associate summary table:
  - **NET_DEPOSITS_EUR**: `SUM(DEPOSIT.amount_eur) - SUM(WITHDRAWAL.amount_eur)`
    - Explanation: "Cash they personally funded"
  - **SHOULD_HOLD_EUR** (Entitlement): `SUM(principal_returned_eur + per_surebet_share_eur)` from BET_RESULT rows
    - Explanation: "Their share of the pool"
  - **CURRENT_HOLDING_EUR**: Sum of ALL ledger entries (BET_RESULT + DEPOSIT + WITHDRAWAL + BOOKMAKER_CORRECTION) in EUR via `fx_rate_snapshot`
    - Explanation: "What model thinks they're physically holding"
  - **DELTA**: `CURRENT_HOLDING_EUR - SHOULD_HOLD_EUR`
    - Color coding:
      - 🔴 Red if `DELTA > 0`: "Holding +€X group float (collect from them)"
      - 🟢 Green if `DELTA ≈ 0`: "Balanced"
      - 🟠 Orange if `DELTA < 0`: "Short €X (someone else holding their money)"
  - Human-readable explanation for each associate

#### 5.3 Bookmaker Balance Drilldown
**As the operator**, I want to compare modeled bookmaker balances against reported live balances.

**Acceptance Criteria:**
- Reconciliation page includes per-bookmaker drilldown (expandable rows):
  - Modeled balance (sum of ledger entries for this associate+bookmaker):
    - Native currency amount
    - EUR equivalent
  - Reported live balance (from `bookmaker_balance_checks` table):
    - Manually entered by operator
    - Timestamp of last check
  - Difference: `modeled - reported`
  - "Apply Correction" button → opens correction form pre-filled with:
    - Associate + bookmaker
    - Amount = difference
    - Note = "Balance reconciliation for [bookmaker] on [date]"

#### 5.4 Pending Funding Events
**As the operator**, I want to review and approve deposit/withdrawal events.

**Acceptance Criteria:**
- "Pending Funding" section at top of Reconciliation page
- Manual entry form (for MVP, no Telegram parsing):
  - Associate selector
  - Event type: DEPOSIT / WITHDRAWAL
  - Amount (native currency)
  - Currency selector
  - Note (optional)
- "Accept" button writes `ledger_entries` row:
  - `entry_type = "DEPOSIT"` or `"WITHDRAWAL"`
  - `amount_native`, `native_currency`, `fx_rate_snapshot`, `amount_eur`
  - `associate_id`, `bookmaker_id = NULL`
  - `created_at_utc`, `created_by="local_user"`, `note`
- "Reject" button discards entry
- Accepted events immediately update NET_DEPOSITS_EUR and CURRENT_HOLDING_EUR

#### 5.5 Associate Operations Hub
**As the operator**, I want a single operations hub to manage associates, bookmakers, balances, and funding actions without bouncing between pages.

**Acceptance Criteria:**
- "Associate Operations" admin page with persistent filter bar (search, admin flag, active status, currency, sort controls).
- Associate summary rows display admin badge, home currency, bookmaker count, NET_DEPOSITS_EUR, SHOULD_HOLD_EUR, CURRENT_HOLDING_EUR, and DELTA with color-coded status.
- Expanding an associate shows bookmaker table including modeled vs reported balance, latest balance check timestamp, mismatch badge, and action buttons (Edit, Manage Balance, Deposit, Withdraw).
- Detail drawer enables:
  - Editing associate/bookmaker metadata with existing validation rules.
  - Managing balance checks (list, add, edit, delete) via Story 5.3 components.
  - Recording deposits and withdrawals through a shared flow that writes ledger entries instantly.
- Session state preserves filters and current selection so actions refresh metrics without losing context.

### Success Criteria
- ✅ Corrections can be applied without reopening settlements
- ✅ All corrections logged with notes and frozen FX
- ✅ Reconciliation dashboard shows DELTA with color coding
- ✅ Bookmaker balance mismatches visible and correctable
- ✅ Deposits/withdrawals update entitlement math correctly
- ✅ Associate operations hub consolidates CRUD, balance, and funding workflows

### Dependencies
- Phase 4 complete (ledger entries being created)
- Some settled surebets for meaningful reconciliation data

---

## Phase 6: Reporting & Audit

**Duration:** 3-4 days
**Goal:** CSV export + partner statements
**PRD Coverage:** FR-9 (Ledger Export), FR-10 (Monthly Statements)

### Stories

#### 6.1 Complete Ledger CSV Export
**As the operator**, I want to export the full ledger to CSV for external audit or backup.

**Acceptance Criteria:**
- "Export" page with "Export Full Ledger" button
- Generates CSV at `data/exports/ledger_{timestamp}.csv` with columns:
  - `entry_id`, `entry_type`, `associate_alias`, `bookmaker_name`
  - `surebet_id`, `bet_id`, `settlement_batch_id`
  - `amount_native`, `native_currency`, `fx_rate_snapshot`, `amount_eur`
  - `principal_returned_eur`, `per_surebet_share_eur`
  - `settlement_state`, `created_at_utc`, `created_by`, `note`
- Includes ALL `ledger_entries` rows (BET_RESULT, DEPOSIT, WITHDRAWAL, BOOKMAKER_CORRECTION)
- Joins with `associates.display_alias` and `bookmakers.name`
- Success message with file path displayed

#### 6.2 Monthly Statement Generator
**As the operator**, I want to generate per-associate statements showing funding, entitlement, and 50/50 split.

**Acceptance Criteria:**
- "Monthly Statements" page with:
  - Associate selector
  - Cutoff date picker (default: end of current month)
- "Generate Statement" button calculates as of cutoff:
  1. **NET_DEPOSITS_EUR**: `(Sum DEPOSIT) - (Sum WITHDRAWAL)` up to cutoff
  2. **SHOULD_HOLD_EUR**: `SUM(principal_returned_eur + per_surebet_share_eur)` from BET_RESULT rows up to cutoff
  3. **RAW_PROFIT_EUR**: `SHOULD_HOLD_EUR - NET_DEPOSITS_EUR`
- Display in human-readable format:
  - "You funded: €{NET_DEPOSITS_EUR}"
  - "You're entitled to: €{SHOULD_HOLD_EUR}"
  - "Your profit: €{RAW_PROFIT_EUR}" (green if positive, red if negative)
  - "Our 50/50 split: €{RAW_PROFIT_EUR / 2} each"
- Internal-only section (visible to operator):
  - `CURRENT_HOLDING_EUR`
  - `DELTA = CURRENT_HOLDING_EUR - SHOULD_HOLD_EUR`
- **Critical Note**: Monthly statements are PRESENTATION ONLY
  - Do NOT create ledger entries
  - Do NOT change entitlement math
  - Do NOT affect reconciliation

### Success Criteria
- ✅ Full ledger exportable to CSV
- ✅ CSV includes all ledger rows with proper joins
- ✅ Monthly statements show correct 50/50 math
- ✅ Statements are read-only (no ledger writes)
- ✅ Operator can generate statements for any past cutoff date

### Dependencies
- Phase 5 complete (ledger populated with meaningful data)
- Reconciliation math validated

---

## MVP Acceptance Criteria

The system is considered **MVP complete** when ALL of the following pass:

### Functional Completeness
- ✅ Phase 0-6 all marked complete
- ✅ All 10 Functional Requirements (FR-1 through FR-10) implemented
- ✅ End-to-end flow works: screenshot → ingestion → review → matching → coverage → settlement → reconciliation → export

### System Laws Enforced
- ✅ **Law #1**: Ledger is append-only (no UPDATE/DELETE on `ledger_entries`)
- ✅ **Law #2**: All ledger rows have frozen `fx_rate_snapshot`
- ✅ **Law #3**: Equal-split settlement with admin seat logic works correctly
- ✅ **Law #4**: VOID bets participate in split (verified with all-VOID test case)
- ✅ **Law #5**: Manual grading workflow enforced (no auto-grading)
- ✅ **Law #6**: No silent messaging (coverage proof requires manual click)

### Data Integrity
- ✅ All currency math uses Decimal (no float rounding errors)
- ✅ All timestamps in UTC ISO8601 with "Z"
- ✅ Surebet side assignments (A/B) never flip after creation
- ✅ Settlement batch IDs group related ledger entries

### User Experience
- ✅ Operator can complete full workflow without developer assistance
- ✅ All Streamlit pages load without errors
- ✅ Telegram bot receives and processes screenshots
- ✅ Manual upload works for off-Telegram bets
- ✅ Reconciliation dashboard shows meaningful DELTA with color coding
- ✅ Monthly statements readable by non-technical associates

### Testing Coverage
- ✅ Happy path tested with 5+ real surebets (2-sided markets)
- ✅ Edge cases tested:
  - All-VOID surebet
  - Admin-staked vs. non-staked
  - Multi-bet on same side (A1+A2 vs B1)
  - Negative ROI surebet (❌ classification)
  - Late VOID correction (forward-only)
- ✅ Reconciliation math verified manually with calculator

---

## Post-MVP Enhancements (Out of Scope)

These features are explicitly **deferred** to future iterations:

### Phase 7: Automation (Future)
- Telegram auto-capture of deposit/withdrawal intents
- "Likely matches" dropdown for `canonical_event_id`
- Automatic settlement result DMs to associates
- Batch settlement (multiple surebets at once)

### Phase 8: Intelligence (Future)
- Real-time surebet opportunity detection
- Odds movement tracking
- Historical ROI analytics
- Bookmaker profitability reports

### Phase 9: Scale (Future)
- Multi-operator support (RBAC, login)
- Cloud deployment (currently local-only)
- Mobile app for associates
- Web API for external integrations

### Phase 10: Brownfield – Epic 12 (Future)
- Reference: [Epic 12: Signal Broadcaster & Styled Excel Exports](epic-12-signal-broadcaster-and-styled-excel-exports.md)
- Objectives:
  - Add a “Signal Broadcaster” page to paste raw surebet text and send it unchanged to selected Telegram chats with optional presets and exact preview.
  - Replace CSV downloads with styled Excel (.xlsx) exports: bold shaded headers, readable column widths, color cues for deposits/withdrawals, numeric typing for number columns.
- Dependencies:
  - Existing Telegram bot and chat ID mapping in DB/config
  - Existing export data pipelines (swap writer to XLSX with styling)
- Success Criteria:
  - Broadcast sends exact raw text to intended chats and surfaces per-chat success/failure
  - Excel files open cleanly with styling applied; data/ordering match prior CSV, numeric columns behave as numbers
- Estimated Duration: 2–4 days

---

## Risk Mitigation

### High-Risk Areas

| Risk | Phase | Mitigation Strategy |
|------|-------|---------------------|
| OCR accuracy < 80% | Phase 1 | Implement confidence scoring + manual review in Phase 2 |
| Equal-split math errors | Phase 4 | Preview panel + manual calculator verification before MVP sign-off |
| FX rate staleness | Phase 0 | Cache last known rate, warn if >24h old |
| Side assignment flips | Phase 3 | Immutable `surebet_bets.side` enforced in schema (foreign key constraints) |
| Settlement irreversibility | Phase 4 | Prominent modal warning + corrections workflow in Phase 5 |
| Reconciliation confusion | Phase 5 | Human-readable explanations + color-coded DELTA |

### Rollback Plan

Each phase is independently rollback-able:
- **Phase 1-2**: Delete `bets` table contents, no ledger impact
- **Phase 3-4**: Delete `surebets` and `surebet_bets`, ledger preserved if no settlements
- **Phase 5-6**: Corrections and exports are read-only, no rollback needed

**Critical:** Once Phase 4 settlement creates ledger entries, those are **permanent** (append-only). Only forward corrections allowed.

---

## Delivery Timeline Estimate

| Phase | Duration | Cumulative |
|-------|----------|------------|
| Phase 0: Foundation | 3-5 days | 5 days |
| Phase 1: Ingestion | 5-7 days | 12 days |
| Phase 2: Review | 3-4 days | 16 days |
| Phase 3: Matching | 5-6 days | 22 days |
| Phase 4: Settlement | 7-9 days | 31 days |
| Phase 5: Reconciliation | 5-6 days | 37 days |
| Phase 6: Reporting | 3-4 days | 41 days |
| **Total MVP** | **~6 weeks** | **41 days** |

**Assumptions:**
- Single developer working full-time
- No major blockers (GPT-4o API stable, Telegram bot approved)
- Testing included in phase durations
- Buffer for unknowns (~20% padding)

---

## Next Steps

### Immediate Actions (To Begin Phase 0)

1. ✅ Review this roadmap with stakeholders
2. ✅ Confirm technology stack (Python 3.12, Streamlit, SQLite)
3. ✅ Set up development environment
4. ✅ Initialize git repository
5. ✅ Create project folder structure
6. ✅ Begin Phase 0.1: Project Setup

### Handoff to Development

**Development Team**: Start with Phase 0 Foundation. Each phase should be completed and manually tested before moving to the next. Use the "Phase Completion Criteria" checklist to validate readiness.

**Product Manager**: Schedule phase reviews at completion of Phases 0, 2, 4, and 6 (milestones).

---

## Document Control

**Revision History:**

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-10-29 | John (PM Agent) | Initial greenfield roadmap created from PRD v4 |
| 1.1 | 2025-11-13 | Sarah (PO Agent) | Added Post-MVP Phase 10 referencing Epic 12 (Signal Broadcaster & Styled Excel exports) |

**Approvals:**

| Role | Name | Date | Status |
|------|------|------|--------|
| Product Owner | TBD | - | Pending |
| Tech Lead | TBD | - | Pending |

---

**End of Roadmap**
