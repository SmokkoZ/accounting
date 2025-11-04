# Epic 5: Corrections & Reconciliation

**Status:** Not Started
**Priority:** P0 (MVP Critical)
**Estimated Duration:** 5-6 days
**Owner:** Tech Lead
**Phase:** 5 (Core Features)
**PRD Reference:** FR-7 (Post-Settlement Corrections), FR-8 (Reconciliation & Health Check)

---

## Epic Goal

Build forward-only correction workflows and a real-time reconciliation dashboard that shows who's overholding group float vs. who's short. This epic provides **financial health visibility** and error recovery mechanisms.

---

## Business Value

### Operator Benefits
- **Error Recovery**: Fix mistakes without breaking ledger immutability
- **Daily Health Check**: See who owes whom at a glance
- **Bookmaker Reconciliation**: Compare modeled balances vs. live balances
- **Funding Management**: Accept/reject deposit and withdrawal events

### System Benefits
- **Ledger Integrity**: Corrections are forward-only (System Law #1 preserved)
- **Transparency**: DELTA calculations show exact holding discrepancies
- **Auditability**: Every correction logged with note

**Success Metric**: 100% of reconciliation math correct, operator can identify imbalances in <30 seconds.

---

## Epic Description

### Context

Epic 4 writes `BET_RESULT` ledger entries. Over time, errors occur:
- Late VOID notifications (bet settled as LOST, later refunded)
- Grading mistakes (operator picks wrong outcome)
- Bookmaker balance mismatches (missing transactions)

Traditional systems "reopen" settlements and edit history. **This system uses forward corrections** (System Law #1).

### What's Being Built

Five interconnected components:

1. **Post-Settlement Correction Interface** (Story 5.1)
   - Manual correction form
   - Write `BOOKMAKER_CORRECTION` ledger rows
   - Never reopen surebets

2. **Reconciliation Dashboard (Associate View)** (Story 5.2)
   - Per-associate summary: NET_DEPOSITS, SHOULD_HOLD, CURRENT_HOLDING, DELTA
   - Color-coded health: 🔴 overholding, 🟢 balanced, 🟠 short
   - Human-readable explanations

3. **Bookmaker Balance Drilldown** (Story 5.3)
   - Per-bookmaker modeled vs. reported balance
   - "Apply correction" button pre-fills correction form

4. **Pending Funding Events** (Story 5.4)
   - Manual entry for deposit/withdrawal
   - Accept → writes `DEPOSIT`/`WITHDRAWAL` ledger rows
   - Reject → discards draft

5. **Associate Operations Hub** (Story 5.5)
   - Single admin surface for associate, bookmaker, and balance operations
   - Inline transactions (deposit/withdraw) with ledger persistence
   - Advanced filtering, sorting, and detail drawers for rapid triage

### Integration Points

**Upstream Dependencies:**
- Epic 4 (Settlement): Produces `BET_RESULT` ledger entries
- Phase 0 FX system: Converts corrections to EUR

**Downstream Consumers:**
- Epic 6 (Reporting): Uses reconciliation math for monthly statements

---

## Stories

### Story 5.1: Post-Settlement Correction Interface

**As the operator**, I want to apply forward-only corrections for late VOIDs or grading errors without reopening surebets so ledger integrity is preserved.

**Acceptance Criteria:**
- [ ] "Corrections" page with manual correction form:
  - **Associate selector**: Dropdown from `associates.display_alias`
  - **Bookmaker selector**: Filtered by associate's bookmakers
  - **Amount**: Number input (native currency, can be positive or negative)
    - Positive: Increases associate's holdings (e.g., late refund)
    - Negative: Decreases holdings (e.g., late deduction)
  - **Currency selector**: Dropdown (AUD, GBP, EUR, USD, etc.)
  - **Note field**: Required text area (e.g., "Late VOID correction for Bet #123")
  - **"Apply Correction" button**
- [ ] On "Apply Correction" click:
  - Validation:
    - Associate, bookmaker, amount, currency, note all required
    - Amount != 0
  - Get current FX rate: `fx_rate = get_fx_rate(currency, today)`
  - Insert `ledger_entries` row:
    ```sql
    INSERT INTO ledger_entries (
      entry_type,
      associate_id,
      bookmaker_id,
      surebet_id,            -- NULL (corrections are standalone)
      bet_id,                -- NULL
      settlement_state,      -- NULL
      amount_native,         -- from form
      native_currency,       -- from form
      fx_rate_snapshot,      -- current rate, frozen at this moment
      amount_eur,            -- amount_native * fx_rate_snapshot
      principal_returned_eur,-- NULL
      per_surebet_share_eur, -- NULL
      settlement_batch_id,   -- NULL
      created_at_utc,        -- current timestamp
      created_by,            -- 'local_user'
      note                   -- from form
    ) VALUES (...)
    ```
  - Success message: "Correction applied. Ledger entry created."
  - Form clears
- [ ] Corrections list:
  - Show recent corrections (last 30 days)
  - Display: timestamp, associate, bookmaker, amount (native + EUR), note
  - Sortable by timestamp
- [ ] **CRITICAL**: No UPDATE/DELETE on old ledger rows
  - Corrections are ALWAYS forward-only additions

**Technical Notes:**
- Use current FX rate (not historical) for correction snapshot
- Log correction event to console
- Consider adding "Correction Reason" dropdown for categorization (future)

---

### Story 5.2: Reconciliation Dashboard (Associate View)

**As the operator**, I want to see who's overholding group float vs. who's short at a glance so I know who owes whom.

**Acceptance Criteria:**
- [ ] "Reconciliation" page displays per-associate summary table:

  **Columns:**

  1. **Associate Name**: `display_alias` from `associates`

  2. **NET_DEPOSITS_EUR**: How much cash they personally funded
     - Formula: `SUM(DEPOSIT.amount_eur) - SUM(WITHDRAWAL.amount_eur)`
     - Explanation: "Cash you put in"

  3. **SHOULD_HOLD_EUR** (Entitlement): How much of the pool belongs to them
     - Formula: `SUM(principal_returned_eur + per_surebet_share_eur)` from all `BET_RESULT` rows
     - Explanation: "Your share of the pot"

  4. **CURRENT_HOLDING_EUR**: What model thinks they're physically holding
     - Formula: Sum of ALL ledger entries for this associate:
       - `SUM(amount_eur)` from `BET_RESULT` rows
       - `+ SUM(amount_eur)` from `DEPOSIT` rows
       - `- SUM(amount_eur)` from `WITHDRAWAL` rows (amount_eur is negative)
       - `+ SUM(amount_eur)` from `BOOKMAKER_CORRECTION` rows (can be + or -)
     - Explanation: "What you're holding in bookmaker accounts"

  5. **DELTA**: `CURRENT_HOLDING_EUR - SHOULD_HOLD_EUR`
     - Color coding:
       - **🔴 Red** if `DELTA > +€10`: "Holding +€X group float (collect from them)"
       - **🟢 Green** if `-€10 <= DELTA <= +€10`: "Balanced"
       - **🟠 Orange** if `DELTA < -€10`: "Short €X (someone else holding their money)"
     - Explanation text shown on hover or below number

  6. **Status Icon**: Visual indicator (🔴 / 🟢 / 🟠)

- [ ] Table features:
  - Sortable by DELTA (show largest overholders first)
  - Collapsible rows (expand for details)
  - Export to CSV button

- [ ] Human-readable explanation per associate (hover tooltip or expandable):
  - Example (overholder):
    ```
    Partner A is holding €800 more than their entitlement.
    They funded €1000 total and are entitled to €1200,
    but currently hold €2000 in bookmaker accounts.
    Collect €800 from them.
    ```
  - Example (short):
    ```
    Partner B is short €300.
    They funded €500 and are entitled to €700,
    but only hold €400 in bookmaker accounts.
    Someone else is holding their €300.
    ```

- [ ] Refresh button: Recalculate all balances on demand

**Technical Notes:**
- Aggregate queries on `ledger_entries` grouped by `associate_id`
- Cache calculations (recalculate on page load or manual refresh)
- Round to 2 decimal places for display
- Test with negative entitlements (associates in loss position)

---

### Story 5.3: Bookmaker Balance Drilldown

**As the operator**, I want to compare modeled bookmaker balances against reported live balances to identify missing transactions.

**Acceptance Criteria:**
- [ ] Reconciliation page includes per-bookmaker drilldown (expandable rows or separate tab):

  **For each bookmaker (grouped by associate + bookmaker):**

  1. **Modeled Balance**:
     - Query: `SUM(amount_eur)` from all `ledger_entries` WHERE `associate_id=X AND bookmaker_id=Y`
     - Convert to native currency: `modeled_native = modeled_eur / fx_rate`
     - Display: "€XXX (YYY AUD)" where YYY is approximate native equivalent

  2. **Reported Live Balance**:
     - From `bookmaker_balance_checks` table:
       - Operator manually enters live balance from bookmaker website
       - Fields: `associate_id`, `bookmaker_id`, `balance_native`, `currency`, `checked_at_utc`
     - Display: "ZZZ AUD (€AAA)" with timestamp "Last checked: 1 hour ago"

  3. **Difference**:
     - `difference_native = reported_native - modeled_native`
     - `difference_eur = difference_native * fx_rate`
     - Color coding:
       - **🟢 Green** if `|difference_eur| < €10`: "Balanced"
       - **🟡 Yellow** if `10 <= |difference_eur| < 50`: "Minor mismatch"
       - **🔴 Red** if `|difference_eur| >= 50`: "Major mismatch - investigate"

  4. **"Apply Correction" button**:
     - Pre-fills correction form (Story 5.1) with:
       - Associate: X
       - Bookmaker: Y
       - Amount: `difference_native` (to bring modeled in line with reported)
       - Currency: bookmaker's currency
       - Note: "Balance reconciliation for [bookmaker] on [date]"
     - Operator reviews and confirms

- [ ] Manual balance entry form (inline):
  - Associate selector, bookmaker selector
  - Balance amount (native currency)
  - "Update Balance" button
  - Inserts/updates `bookmaker_balance_checks` row

- [ ] Bookmaker drilldown table features:
  - Sortable by difference (largest first)
  - Filter: show only mismatches
  - Timestamp of last balance check

**Technical Notes:**
- `bookmaker_balance_checks` table schema:
  ```sql
  CREATE TABLE bookmaker_balance_checks (
    check_id INTEGER PRIMARY KEY AUTOINCREMENT,
    associate_id INTEGER NOT NULL REFERENCES associates(associate_id),
    bookmaker_id INTEGER NOT NULL REFERENCES bookmakers(bookmaker_id),
    balance_native TEXT NOT NULL,  -- Decimal
    currency TEXT NOT NULL,
    checked_at_utc TEXT NOT NULL,
    UNIQUE(associate_id, bookmaker_id)  -- One row per bookmaker, UPDATE on new check
  );
  ```
- Balance checks do NOT auto-create corrections (operator decides)

---

### Story 5.4: Pending Funding Events

**As the operator**, I want to review and approve deposit/withdrawal events so associate balances reflect cash movements.

**Acceptance Criteria:**
- [ ] "Pending Funding" section at top of Reconciliation page

  **Manual Entry Form** (for MVP, no Telegram auto-capture):
  - **Associate selector**: Dropdown
  - **Event type**: Radio buttons (DEPOSIT | WITHDRAWAL)
  - **Amount**: Number input (native currency, positive only)
  - **Currency selector**: Dropdown
  - **Note**: Optional text field (e.g., "Bank transfer from Partner A")
  - **"Add Funding Event" button**: Creates draft entry

- [ ] Pending funding list:
  - Shows draft entries (in-memory or separate `funding_drafts` table)
  - Display: timestamp, associate, type, amount, currency, note
  - Actions: **Accept** | **Reject** buttons

- [ ] On "Accept":
  - Get current FX rate: `fx_rate = get_fx_rate(currency, today)`
  - Insert `ledger_entries` row:
    ```sql
    INSERT INTO ledger_entries (
      entry_type,            -- 'DEPOSIT' or 'WITHDRAWAL'
      associate_id,
      bookmaker_id,          -- NULL (funding is associate-level, not bookmaker-specific)
      surebet_id,            -- NULL
      bet_id,                -- NULL
      settlement_state,      -- NULL
      amount_native,         -- from form (positive for DEPOSIT, negative for WITHDRAWAL)
      native_currency,       -- from form
      fx_rate_snapshot,      -- current rate
      amount_eur,            -- amount_native * fx_rate_snapshot
      principal_returned_eur,-- NULL
      per_surebet_share_eur, -- NULL
      settlement_batch_id,   -- NULL
      created_at_utc,        -- current timestamp
      created_by,            -- 'local_user'
      note                   -- from form
    ) VALUES (...)
    ```
  - Remove from drafts list
  - Success message: "Funding event accepted. Ledger entry created."
  - Reconciliation dashboard updates immediately (NET_DEPOSITS_EUR changes)

- [ ] On "Reject":
  - Remove from drafts list
  - No ledger write
  - Success message: "Funding event discarded."

- [ ] Funding history (below form):
  - Show recent accepted DEPOSIT/WITHDRAWAL rows (last 30 days)
  - Display: timestamp, associate, type, amount (native + EUR), note

**Technical Notes:**
- For WITHDRAWAL, `amount_native` should be negative in ledger (or store positive and handle sign in queries)
- Consider bookmaker-specific funding (future): associate deposits to specific bookmaker account
- Pending drafts can be in-memory (session state) or separate table

---

### Story 5.5: Associate Operations Hub

**As the operator**, I want a single hub for all associate, bookmaker, balance, and funding actions so I can administer the network without bouncing across multiple pages.

**Acceptance Criteria:**
- [ ] "Associate Operations" page available from the admin navigation and preloaded with associates (`associates` table) and their bookmakers.
- [ ] Persistent filter/sort bar anchored at the top with:
  - Text search (matches associate alias, bookmaker name, chat id).
  - Multi-select filters: Associate status (admin vs non-admin, active vs inactive), bookmaker active state, currency.
  - Sorting controls for alias A→Z/Z→A, DELTA high→low, last-activity newest→oldest.
- [ ] Associate rows/cards display at-a-glance metrics: admin badge, home currency, bookmaker count, NET_DEPOSITS_EUR, SHOULD_HOLD_EUR, CURRENT_HOLDING_EUR, DELTA with status badge colors reused from Story 5.2.
- [ ] Expanding an associate reveals a bookmaker table with columns for name, active status, parsing profile snippet, modeled vs reported balance, DELTA, latest balance check timestamp, and action buttons (Edit, Manage Balance, Deposit, Withdraw).
- [ ] "Manage Balance" action opens a drawer/modal that:
  - Shows latest reported vs modeled balance with delta badges.
  - Lists historical balance checks with CRUD operations (reuse validators from Story 5.3).
  - Surfaces ledger history for the associate/bookmaker pair for quick auditing.
- [ ] "Deposit" and "Withdraw" actions trigger a shared modal capturing amount, currency, optional bookmaker override, and note. On submit the flow:
  - Validates using existing funding rules (amount > 0, currency allowed, note optional).
  - Calls a new service helper that writes `DEPOSIT`/`WITHDRAWAL` ledger rows with FX snapshot and associates optional bookmaker linkage.
  - Updates aggregate metrics and activity tables without a full Streamlit rerun (session-state diff).
- [ ] Drawer includes "Profile" tab for editing associate metadata (alias, currency, admin flag, chat id) and per-bookmaker fields (name, parsing profile, active flag) with validations reused from Story 5.1/7.x components.
- [ ] Lists support column sorting and pagination for rosters > 25 entities, with sticky headers on scroll.
- [ ] Graceful empty states and inline alerts explain when no associates/bookmakers match the filters.

**Technical Notes:**
- Centralize shared loaders/actions in `src/ui/components/associate_hub/` so legacy pages (Stories 7.1-7.3) can gradually adopt them.
- Reuse `BookmakerBalanceService` for modeled vs reported numbers and Story 5.3 balance check helpers.
- Maintain selected associate/bookmaker and filters in `st.session_state` to prevent losing context on reruns.
- Gate the new page behind a config flag until parity with existing Admin/Balance pages is validated.

---

## User Acceptance Testing Scenarios

### Scenario 1: Late VOID Correction
1. Operator settled Surebet #10 yesterday: Bet #50 (Partner A) marked LOST
2. Today, bookmaker refunds stake (late VOID)
3. Operator goes to Corrections page
4. Enters:
   - Associate: Partner A
   - Bookmaker: Bet365
   - Amount: +100 AUD
   - Currency: AUD
   - Note: "Late VOID correction for Bet #50"
5. Clicks "Apply Correction"
6. Ledger entry created: `BOOKMAKER_CORRECTION`, +100 AUD, FX snapshot frozen
7. Reconciliation dashboard shows Partner A's CURRENT_HOLDING_EUR increased by ~€60

**Expected Result**: Correction applied without reopening surebet, ledger preserved.

---

### Scenario 2: Identify Overholder
1. Operator opens Reconciliation dashboard
2. Sees:
   ```
   | Associate | NET_DEPOSITS | SHOULD_HOLD | CURRENT_HOLDING | DELTA    | Status |
   |-----------|--------------|-------------|-----------------|----------|--------|
   | Admin     | €2000        | €2100       | €2800           | +€700 🔴 | Overholder |
   | Partner A | €1500        | €1600       | €1400           | -€200 🟠 | Short      |
   ```
3. Expands Admin row: "Holding €700 more than entitlement. Collect from Admin."
4. Operator contacts admin to transfer €700 to Partner A's account

**Expected Result**: DELTA highlights who owes whom clearly.

---

### Scenario 3: Bookmaker Balance Mismatch
1. Operator goes to Bookmaker Drilldown
2. Sees:
   ```
   | Bookmaker     | Modeled Balance | Reported Balance | Difference  | Status |
   |---------------|-----------------|------------------|-------------|--------|
   | Bet365 (Admin)| €500            | €450             | -€50 🟡     | Minor  |
   ```
3. Operator checks bookmaker website: confirms €450 is correct
4. Clicks "Apply Correction" → form pre-filled with -€50
5. Adds note: "Missing transaction - bookmaker fee deducted"
6. Submits correction
7. Modeled balance updates to €450, difference now €0 🟢

**Expected Result**: Bookmaker mismatches correctable via pre-filled form.

---

### Scenario 4: Accept Deposit
1. Partner A transfers €500 to admin's bank account
2. Operator goes to Pending Funding section
3. Enters:
   - Associate: Partner A
   - Type: DEPOSIT
   - Amount: 500 EUR
   - Note: "Bank transfer 2025-10-30"
4. Clicks "Add Funding Event" → appears in pending list
5. Reviews → clicks "Accept"
6. Ledger entry created: `DEPOSIT`, +€500
7. Reconciliation dashboard updates:
   - NET_DEPOSITS_EUR: €1500 → €2000
   - SHOULD_HOLD_EUR: unchanged
   - CURRENT_HOLDING_EUR: unchanged (deposit doesn't affect bookmaker holdings yet)
   - DELTA: worsens (now more short)

**Expected Result**: Deposits tracked separately from bookmaker holdings.

---

### Scenario 5: Operate Entirely from the Associate Hub
1. Operator launches the "Associate Operations" page from the sidebar.
2. Uses the search filter to locate "Partner A" and toggles the status filter to show active associates only.
3. Expands Partner A's row to review bookmaker cards and sees mismatch badge on Bet365.
4. Clicks "Manage Balance" for Bet365, reviews history, and adds a new balance check with €1,200 reported balance.
5. Without leaving the drawer, switches to the "Transactions" tab, selects "Deposit", and submits a €300 EUR deposit with note "Top-up before weekend".
6. Confirmation toast appears, NET_DEPOSITS_EUR and DELTA metrics refresh, and the transaction appears in recent ledger activity.
7. Operator edits Partner A's alias via the "Profile" tab, saves, and the list reflects the change while retaining current filters.

**Expected Result**: Operator performs balance update, funding entry, and profile edit on one page without navigation.

---

## Technical Considerations

### Reconciliation Math Definitions

**NET_DEPOSITS_EUR**: Personal funding
```sql
SELECT
  associate_id,
  SUM(CASE WHEN entry_type='DEPOSIT' THEN amount_eur ELSE 0 END) -
  SUM(CASE WHEN entry_type='WITHDRAWAL' THEN amount_eur ELSE 0 END) AS net_deposits_eur
FROM ledger_entries
GROUP BY associate_id;
```

**SHOULD_HOLD_EUR**: Entitlement (what they're owed)
```sql
SELECT
  associate_id,
  SUM(principal_returned_eur + per_surebet_share_eur) AS should_hold_eur
FROM ledger_entries
WHERE entry_type='BET_RESULT'
GROUP BY associate_id;
```

**CURRENT_HOLDING_EUR**: Physical holdings
```sql
SELECT
  associate_id,
  SUM(amount_eur) AS current_holding_eur
FROM ledger_entries
WHERE entry_type IN ('BET_RESULT', 'DEPOSIT', 'WITHDRAWAL', 'BOOKMAKER_CORRECTION')
GROUP BY associate_id;
```

**DELTA**: Discrepancy
```sql
DELTA = CURRENT_HOLDING_EUR - SHOULD_HOLD_EUR
```

### Correction vs. Deposit Semantics

**Correction (BOOKMAKER_CORRECTION)**:
- Fixes errors in *existing* bookmaker holdings
- Examples: late VOID, missing transaction, grading error
- Affects: CURRENT_HOLDING_EUR
- Does NOT affect: NET_DEPOSITS_EUR or SHOULD_HOLD_EUR

**Deposit (DEPOSIT)**:
- Records *new* cash funding from associate
- Examples: bank transfer, cash deposit
- Affects: NET_DEPOSITS_EUR, CURRENT_HOLDING_EUR (indirectly, when placed as bet)
- Does NOT affect: SHOULD_HOLD_EUR (until bets settle)

**Withdrawal (WITHDRAWAL)**:
- Records cash taken out by associate
- Affects: NET_DEPOSITS_EUR, CURRENT_HOLDING_EUR

### Performance Optimization

**Potential Bottleneck**: Aggregating `ledger_entries` on every page load.

**Solutions**:
- **Option A**: Materialized view (SQLite doesn't support natively, manual refresh)
- **Option B**: Cached calculation with TTL=5 minutes
- **Option C**: Real-time aggregation (acceptable for <10k ledger rows)

**Recommendation**: Start with Option C, optimize if slow (>2s page load).

---

## Dependencies

### Upstream (Blockers)
- **Epic 4**: Settlement complete
  - `BET_RESULT` ledger entries exist
- **Phase 0**: FX system, database schema

### Downstream (Consumers)
- **Epic 6**: Monthly Statements
  - Uses reconciliation math (NET_DEPOSITS, SHOULD_HOLD, etc.)

---

## Definition of Done

Epic 5 is complete when ALL of the following are verified:

### Functional Validation
- [ ] All 5 stories (5.1-5.5) marked complete with passing acceptance criteria
- [ ] Corrections apply forward-only (no UPDATE/DELETE on ledger)
- [ ] Reconciliation dashboard calculates DELTA correctly
- [ ] Bookmaker balance mismatches identifiable
- [ ] Deposits/withdrawals update NET_DEPOSITS_EUR correctly
- [ ] Associate Operations hub provides unified CRUD, balance checks, and funding actions with real-time metric refresh

### Technical Validation
- [ ] Reconciliation math verified with calculator
- [ ] All ledger entry types (BET_RESULT, DEPOSIT, WITHDRAWAL, BOOKMAKER_CORRECTION) aggregate correctly
- [ ] FX snapshots stored in correction rows
- [ ] No float rounding errors (all Decimal)

### User Testing
- [ ] All 5 UAT scenarios pass
- [ ] Operator can identify overholders/short associates in <30 seconds
- [ ] Corrections applied successfully

### Handoff Readiness
- [ ] Epic 6 team can use reconciliation math for statements

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Reconciliation math errors | Medium | High | Unit tests with known scenarios; manual calculator verification |
| Correction amount wrong sign | Medium | Medium | Clear UI labels ("+ increases holdings, - decreases") |
| DELTA threshold too sensitive | Low | Low | Make threshold configurable (€10 default) |
| Performance slow with many ledger rows | Low | Medium | Cache calculations; optimize queries with indexes |
| Deposit/withdrawal semantics confusing | Medium | Low | Clear documentation; operator training |

---

## Success Metrics

### Completion Criteria
- All 5 stories delivered with passing acceptance criteria
- Epic 5 "Definition of Done" checklist 100% complete
- Zero blockers for Epic 6 (Reporting)

### Quality Metrics
- **Math Accuracy**: 100% reconciliation math correct
- **Correction Success**: 0 errors applying corrections
- **Health Check Speed**: Operator identifies imbalances in <30 seconds
- **Ledger Integrity**: 0 UPDATE/DELETE on old rows

---

## Related Documents

- [PRD: FR-7 (Post-Settlement Corrections)](../prd.md#fr-7-post-settlement-corrections)
- [PRD: FR-8 (Reconciliation & Health Check)](../prd.md#fr-8-reconciliation--health-check)
- [PRD: Reconciliation Glossary](../prd.md#appendix-c-reconciliation-glossary)
- [Epic 4: Coverage Proof & Settlement](./epic-4-coverage-settlement.md)
- [Epic 6: Reporting & Audit](./epic-6-reporting-audit.md)
- [Implementation Roadmap](./implementation-roadmap.md)

---

## Notes

### Why Forward-Only Corrections Matter

**Anti-Pattern** (traditional systems):
1. Discover error in historical settlement
2. Reopen surebet
3. Edit old ledger rows
4. Recalculate everything downstream

**Problems**:
- Audit trail lost (what was the original decision?)
- Complex cascade (changing one row affects many)
- Concurrency issues (what if two corrections overlap?)

**This System's Approach**:
1. Discover error
2. Write NEW correction row forward
3. Ledger history shows: original decision + correction

**Benefits**:
- Complete audit trail (see both mistake and fix)
- Simple (no cascade recalculation)
- Append-only integrity (System Law #1)

### DELTA as Financial Health

**DELTA > 0** (Overholder):
- Associate is holding MORE than they're entitled to
- They're sitting on group float
- Action: Collect excess from them

**DELTA < 0** (Short):
- Associate is entitled to MORE than they're holding
- Someone else is holding their money
- Action: Transfer money to them

**DELTA ≈ 0** (Balanced):
- Associate's holdings match entitlement
- Ideal state

**System Goal**: Keep all DELTAs near zero through regular reconciliation and transfers.

---

**End of Epic**
