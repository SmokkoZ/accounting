# Epic 4: Coverage Proof & Settlement

**Status:** Not Started
**Priority:** P0 (MVP Critical)
**Estimated Duration:** 7-9 days
**Owner:** Tech Lead
**Phase:** 4 (Core Features)
**PRD Reference:** FR-5 (Coverage Proof Distribution), FR-6 (Settlement & Grading)

---

## Epic Goal

Build the coverage proof distribution workflow and the equal-split settlement engine with frozen FX snapshots and append-only ledger writes. This epic is the **financial heart** of the system where money movements are recorded permanently.

---

## Business Value

### Operator Benefits
- **Trust Building**: Associates see coverage proof (opposite-side screenshots)
- **Settlement Confidence**: Preview equal-split math before committing
- **Audit Trail**: Every settlement logged with frozen FX rates
- **Chronological Order**: Settle oldest bets first (by kickoff time)

### System Benefits
- **Immutability**: Settlements written to append-only ledger (System Law #1)
- **FX Integrity**: Frozen snapshots prevent revaluation (System Law #2)
- **Fair Distribution**: Equal-split logic with admin seat (System Law #3)
- **VOID Handling**: VOID bets participate in split (System Law #4)

**Success Metric**: 100% of settlements produce correct ledger entries, zero calculation errors, all System Laws enforced.

---

## Epic Description

### Context

Epic 3 produces `surebets` with `status="open"`. Associates have placed bets but don't know if opposite sides are covered.

**Before settlement**, operator must:
1. Send **coverage proof** (opposite-side screenshots) to associates' multibook Telegram chats
2. Wait for event to finish (sports outcome known)

**At settlement**, operator must:
3. Grade bets (WON / LOST / VOID) based on event outcome
4. Calculate equal-split profit/loss distribution
5. Write **permanent ledger entries** with frozen FX snapshots

### What's Being Built

Four interconnected components:

1. **Manual Coverage Proof Distribution** (Story 4.1)
   - "Send coverage proof" button per surebet
   - Forward opposite-side screenshots to multibook chats
   - Log deliveries in `multibook_message_log`

2. **Settlement Interface (Kickoff Order)** (Story 4.2)
   - Surebets sorted by `kickoff_time_utc` (oldest first)
   - Select surebet → view bets, screenshots, stakes, odds
   - Choose outcome (Side A WON, Side B WON, etc.)
   - Override individual bets (WON / LOST / VOID)

3. **Equal-Split Preview & Confirmation** (Story 4.3)
   - Calculate `surebet_profit_eur`, `per_surebet_share_eur`, `principal_returned_eur`
   - Show admin seat logic (N participants)
   - Preview FX rate snapshot
   - Confirm modal: "This is permanent"

4. **Ledger Entry Generation** (Story 4.4)
   - On confirm: write `BET_RESULT` rows for each bet
   - Freeze FX snapshot
   - Mark surebet and bets as `status="settled"`
   - Handle all-VOID edge case

### Integration Points

**Upstream Dependencies:**
- Epic 3 (Surebet Matching): Produces `status="open"` surebets
- Phase 0 FX system: Snapshot rates for ledger
- Phase 0 Telegram bot: Send coverage screenshots

**Downstream Consumers:**
- Epic 5 (Reconciliation): Reads `ledger_entries` for balance calculations

---

## Stories

### Story 4.1: Manual Coverage Proof Distribution

**As the operator**, I want to send opposite-side screenshots to associates' multibook chats for coverage proof so they know their bets are covered.

**Acceptance Criteria:**
- [ ] Each `status="open"` surebet on dashboard has "Send coverage proof" button
- [ ] On click:
  - For each **Side A associate**:
    - Query all Side B bet screenshots
    - Send to associate's **multibook Telegram chat** (one chat per associate, shows bets from all bookmakers)
    - Message text: "You're covered for [EVENT / MARKET LINE]. Opposite side attached."
    - Attach all Side B screenshots as photo group
  - For each **Side B associate**:
    - Query all Side A bet screenshots
    - Send to associate's multibook Telegram chat
    - Same message format
  - Insert log entry into `multibook_message_log`:
    - `surebet_id`, `associate_id`, `telegram_message_id`, `screenshot_paths` (JSON array), `sent_at_utc`
- [ ] Button disabled after first click: "Coverage proof sent ✓"
  - Re-send available via "Re-send coverage proof" option (confirmation modal)
- [ ] **No automatic sending** (System Law #6): Operator MUST click button
- [ ] **No screenshot anonymization**: Associates see raw opposite screenshots (bookmaker names visible)
- [ ] Error handling:
  - If Telegram API fails: show error, log failure, allow retry
  - If multibook chat not configured: show error "Multibook chat missing for [associate]"

**Technical Notes:**
- Query multibook chat IDs from config or `telegram_chat_mappings` table
- Use Telegram `send_media_group()` for multiple screenshots
- Store message ID for traceability
- Consider rate limiting (10 messages/minute per chat)

---

### Story 4.2: Settlement Interface (Kickoff Order)

**As the operator**, I want to settle surebets in chronological kickoff order with WON/LOST/VOID grading so I process events as they complete.

**Acceptance Criteria:**
- [ ] "Settle" tab on Surebets page
  - Query: `SELECT * FROM surebets WHERE status='open' ORDER BY kickoff_time_utc ASC`
  - Display as list: oldest first
- [ ] Each surebet shows:
  - Event name, market, line
  - Kickoff time (past events highlighted: "Completed X hours ago")
  - Side A bets:
    - Associate alias, bookmaker name
    - Stake @ odds (e.g., "€100 @ 1.95")
    - Screenshot link (click to open)
  - Side B bets (same format)
- [ ] Select surebet → opens settlement panel:
  - **Base outcome selection** (radio buttons):
    - ⚪ "Side A WON / Side B LOST"
    - ⚪ "Side B WON / Side A LOST"
  - **Individual bet overrides** (checkboxes):
    - For each bet: dropdown "WON | LOST | VOID"
    - Default: matches base outcome
    - Example: If "Side A WON" selected, all Side A bets default to WON, Side B to LOST
    - Operator can override: "Bet #5 (Side B) actually VOID (late cancel)"
- [ ] Validation:
  - At least one outcome selected (prevent empty submission)
  - Warn if all bets VOID: "All bets VOID - proceed?"
- [ ] Counters at bottom:
  - "Settled today: C"
  - "Still open (unsettled): D"

**Technical Notes:**
- Use `st.radio()` for base outcome
- Use `st.selectbox()` for individual overrides
- Highlight past kickoff times with color coding (overdue for settlement)
- Consider "Quick settle" mode: approve base outcome without reviewing every bet

---

### Story 4.3: Equal-Split Preview & Confirmation

**As the operator**, I want to preview equal-split math before creating permanent ledger entries so I can catch errors before they're irreversible.

**Acceptance Criteria:**
- [ ] Settlement preview panel displays:

  **1. Per-Bet Net Gain/Loss in EUR:**
  - For each bet, calculate net gain in EUR:
    - **WON**: `net_gain_eur = (payout - stake) * fx_rate`
    - **LOST**: `net_gain_eur = -stake * fx_rate`
    - **VOID**: `net_gain_eur = 0`
  - Display per bet: "Bet #5 (Partner A @ Bet365): -€100 (LOST)"

  **2. Surebet Profit/Loss:**
  - `surebet_profit_eur = sum(all bets' net_gain_eur)`
  - Display: "Total surebet profit: €XX.XX" (green if positive, red if negative)

  **3. Participant Count (N):**
  - Query: How many unique associates placed bets in this surebet?
  - **If admin (you) staked**: `N = number of betting participants`
  - **If admin did NOT stake**: `N = number of betting participants + 1` (admin gets extra seat as coordinator)
  - Display: "N participants (including admin seat): X"

  **4. Equal Split:**
  - `per_surebet_share_eur = surebet_profit_eur / N`
  - Display: "Each seat gets: €YY.YY" (can be negative if surebet lost)

  **5. Per-Associate Breakdown:**
  - For each associate in surebet:
    - **Principal returned**: `sum(stake_eur for this associate's WON/VOID bets)`
    - **Surebet share**: `per_surebet_share_eur` (one seat)
    - **Entitlement component**: `principal_returned + per_surebet_share`
  - Display table:
    ```
    | Associate | Principal Returned | Surebet Share | Entitlement Component |
    |-----------|--------------------|--------------|-----------------------|
    | Admin     | €100               | +€5          | €105                  |
    | Partner A | €95                | +€5          | €100                  |
    ```

  **6. FX Rate Snapshot:**
  - Display rates that will be frozen:
    ```
    AUD: 0.60 EUR per AUD (as of 2025-10-30)
    GBP: 1.15 EUR per GBP (as of 2025-10-30)
    ```

  **7. VOID Warning:**
  - If any bet is VOID, show warning: "⚠ VOID bets still participate in split (they get seat but €0 net gain)"
  - If all bets VOID, show: "⚠ All bets VOID - ledger rows will be created with zeros"

- [ ] "Confirm Settlement" button (red, prominent):
  - On click: modal confirmation
    - Title: "Permanent Settlement"
    - Text: "This action is permanent and cannot be undone. Ledger entries will be created with frozen FX rates. Proceed?"
    - Buttons: "Cancel" | "Confirm Settlement"
- [ ] Keyboard shortcut: Ctrl+Enter to confirm (power user)

**Technical Notes:**
- Use current FX rates for preview (will be frozen on confirm)
- All calculations in `Decimal` (no float)
- Highlight negative entitlements in red
- Show sum check: "Total entitlement distributed: €XXX" (should equal total returned + profit distributed)

---

### Story 4.4: Ledger Entry Generation

**As the system**, I want settlement confirmation to write permanent append-only ledger rows so financial history is immutable.

**Acceptance Criteria:**
- [ ] On confirmation:

  **1. Generate Settlement Batch ID:**
  - `settlement_batch_id = UUID()` (unique identifier for this settlement event)

  **2. Freeze FX Rates:**
  - For each currency in surebet:
    - `fx_snapshot = get_fx_rate(currency, today)`
  - Store as JSON or separate snapshot table

  **3. Write Ledger Entries:**
  - For EACH bet in surebet, insert `ledger_entries` row:
    ```sql
    INSERT INTO ledger_entries (
      entry_type,
      associate_id,
      bookmaker_id,
      surebet_id,
      bet_id,
      settlement_state,         -- 'WON' | 'LOST' | 'VOID'
      amount_native,            -- net gain/loss in bookmaker currency
      native_currency,          -- e.g., 'AUD'
      fx_rate_snapshot,         -- Decimal (EUR per 1 unit native)
      amount_eur,               -- net gain/loss in EUR
      principal_returned_eur,   -- stake returned via WON/VOID
      per_surebet_share_eur,    -- equal-split seat from this surebet
      settlement_batch_id,
      created_at_utc,           -- current timestamp ISO8601
      created_by,               -- 'local_user'
      note                      -- optional: e.g., "Match #123 settlement"
    ) VALUES (...)
    ```
  - **Field Calculations:**
    - `entry_type = 'BET_RESULT'`
    - `settlement_state`: WON | LOST | VOID (from Story 4.2)
    - `amount_native`:
      - WON: `payout - stake` (in native currency)
      - LOST: `-stake`
      - VOID: `0`
    - `amount_eur = amount_native * fx_rate_snapshot`
    - `principal_returned_eur`:
      - WON or VOID: `stake * fx_rate_snapshot`
      - LOST: `0`
    - `per_surebet_share_eur`: From Story 4.3 calculation (equal split)

  **4. Update Surebet Status:**
  - `UPDATE surebets SET status='settled', settled_at_utc=<now> WHERE surebet_id=<current>`

  **5. Update Bet Status:**
  - `UPDATE bets SET status='settled' WHERE bet_id IN (<all bets in surebet>)`

  **6. Edge Case - All Bets VOID:**
  - Still write `BET_RESULT` rows with:
    - `amount_native = 0`, `amount_eur = 0`
    - `principal_returned_eur = stake * fx_rate` (stakes refunded)
    - `per_surebet_share_eur = 0 / N = 0`
  - Ensures entitlement history is continuous (System Law #4)

- [ ] Transaction atomicity: All ledger writes + status updates in single DB transaction
  - If any write fails, rollback entire settlement
- [ ] **No DMs sent** (System Law #6): Operator manually shares results if desired
- [ ] Counters update:
  - "Settled today: +1"
  - "Still open: -1"
- [ ] Success message: "Settlement recorded. Batch ID: {uuid}"

**Technical Notes:**
- Use database transaction: `BEGIN TRANSACTION ... COMMIT`
- Log settlement event to console: "Settled Surebet #X, Batch ID: {uuid}"
- Store FX snapshot in ledger row (TEXT field with Decimal string)
- Verify SUM(per_surebet_share_eur) = surebet_profit_eur (sanity check)

---

## User Acceptance Testing Scenarios

### Scenario 1: Perfect Surebet (Positive Profit)
1. Operator selects Surebet #1 (Man Utd vs Arsenal, O/U 2.5)
2. Bets:
   - Bet A: Admin @ Bet365, OVER 2.5, €100 @ 1.95 (AUD 167)
   - Bet B: Partner A @ Pinnacle, UNDER 2.5, €100 @ 2.05 (GBP 87)
3. Outcome: Match finishes 3-1 (OVER 2.5 wins)
4. Operator selects: "Side A WON / Side B LOST"
5. Preview shows:
   - Bet A net gain: +€95 (WON)
   - Bet B net gain: -€100 (LOST)
   - Surebet profit: -€5
   - N = 2 (admin staked, so no extra seat)
   - Per-share: -€2.50 each
   - Admin entitlement: €100 (principal) - €2.50 (share) = €97.50
   - Partner A entitlement: €0 (principal) - €2.50 (share) = -€2.50
6. Operator confirms
7. Ledger entries created:
   - Admin BET_RESULT: amount_eur=+95, principal=100, share=-2.50
   - Partner A BET_RESULT: amount_eur=-100, principal=0, share=-2.50

**Expected Result**: Settlement creates correct ledger entries, entitlements sum correctly.

---

### Scenario 2: VOID Bet Participation
1. Surebet #2 (Tennis match, Winner Market)
2. Bets:
   - Bet A: Admin, TEAM_A, €100 @ 1.90
   - Bet B: Partner A, TEAM_B, €100 @ 2.00
3. Outcome: Match canceled (VOID)
4. Operator overrides both bets to VOID
5. Preview shows:
   - Bet A net gain: €0 (VOID)
   - Bet B net gain: €0 (VOID)
   - Surebet profit: €0
   - N = 2
   - Per-share: €0 each
   - Admin entitlement: €100 (principal) + €0 (share) = €100
   - Partner A entitlement: €100 (principal) + €0 (share) = €100
6. Warning: "All bets VOID - ledger rows will be created with zeros"
7. Operator confirms
8. Ledger entries created with zeros

**Expected Result**: VOID bets create ledger rows (System Law #4), stakes refunded.

---

### Scenario 3: Admin Non-Staker (Extra Seat)
1. Surebet #3 (Soccer match, Asian Handicap)
2. Bets:
   - Bet A: Partner A, TEAM_A +0.5, €100 @ 1.95
   - Bet B: Partner B, TEAM_B -0.5, €100 @ 1.95
3. Admin did NOT place bets
4. Outcome: TEAM_A wins (Bet A WON, Bet B LOST)
5. Preview shows:
   - Bet A net gain: +€95 (WON)
   - Bet B net gain: -€100 (LOST)
   - Surebet profit: -€5
   - N = 3 (Partner A + Partner B + Admin seat)
   - Per-share: -€1.67 each
   - Partner A entitlement: €100 (principal) - €1.67 (share) = €98.33
   - Partner B entitlement: €0 (principal) - €1.67 (share) = -€1.67
   - Admin entitlement: €0 (principal) - €1.67 (share) = -€1.67 (coordinator loss share)
6. Operator confirms
7. Ledger entries include admin BET_RESULT with share=-€1.67 (even though no bet)

**Expected Result**: Admin gets seat and shares loss (System Law #3).

---

### Scenario 4: Multi-Currency Surebet
1. Surebet #4 (Cricket match, Total Runs O/U)
2. Bets:
   - Bet A: Partner A @ Bet365, OVER 250.5, 200 AUD @ 1.90 (FX: 0.60)
   - Bet B: Partner B @ Sportsbet, UNDER 250.5, 100 GBP @ 2.00 (FX: 1.15)
3. Outcome: OVER wins (275 runs)
4. Operator selects: "Side A WON / Side B LOST"
5. Preview converts to EUR:
   - Stake A: 200 × 0.60 = €120
   - Payout A: (200 × 1.90) × 0.60 = €228
   - Net gain A: +€108
   - Stake B: 100 × 1.15 = €115
   - Net gain B: -€115
   - Surebet profit: -€7
   - N = 3 (admin gets seat, didn't stake)
   - Per-share: -€2.33
6. FX snapshot displayed: "AUD 0.60, GBP 1.15 (as of 2025-10-30)"
7. Operator confirms
8. Ledger entries store frozen FX: `fx_rate_snapshot='0.60'` for AUD row, `'1.15'` for GBP row

**Expected Result**: Multi-currency handled correctly, FX frozen (System Law #2).

---

## Technical Considerations

### Equal-Split Calculation Precision

**Formula (Critical):**
```python
surebet_profit_eur = sum(bet.net_gain_eur for bet in surebet_bets)

# Determine N
admin_staked = any(bet.associate_id == ADMIN_ID for bet in surebet_bets)
if admin_staked:
    N = len(set(bet.associate_id for bet in surebet_bets))
else:
    N = len(set(bet.associate_id for bet in surebet_bets)) + 1

per_surebet_share_eur = surebet_profit_eur / N

# Per bet
for bet in surebet_bets:
    principal_returned_eur = (
        bet.stake * bet.fx_rate_snapshot if bet.state in ['WON', 'VOID'] else Decimal('0')
    )
    entitlement_component = principal_returned_eur + per_surebet_share_eur
```

**Decimal Precision:**
- Use `Decimal` with `ROUND_HALF_UP` for division
- Store to 2 decimal places in EUR
- Verify: SUM(entitlement_components) ≈ SUM(all stakes returned) + surebet_profit (within €0.01 rounding)

### Frozen FX Snapshot Storage

**Option A: JSON field in ledger_entries**
```json
{
  "AUD": "0.60",
  "GBP": "1.15"
}
```

**Option B: Separate `fx_snapshots` table**
```sql
CREATE TABLE fx_snapshots (
  snapshot_id INTEGER PRIMARY KEY,
  settlement_batch_id TEXT UNIQUE,
  snapshot_data TEXT,  -- JSON
  created_at_utc TEXT
);
```

**Recommendation**: Option A (JSON field) for simplicity, each row has its own rate.

### Append-Only Enforcement

**Database Level:**
```sql
-- No triggers allowing UPDATE or DELETE on ledger_entries
CREATE TRIGGER prevent_ledger_update
BEFORE UPDATE ON ledger_entries
BEGIN
  SELECT RAISE(ABORT, 'Ledger is append-only. Use corrections table.');
END;
```

**Application Level:**
- No UPDATE/DELETE statements in code
- Only INSERT allowed
- Code review enforces this rule

---

## Dependencies

### Upstream (Blockers)
- **Epic 3**: Surebet Matching complete
  - `status="open"` surebets exist
- **Phase 0**: Telegram bot, FX system, database schema ready

### Downstream (Consumers)
- **Epic 5**: Reconciliation
  - Reads `ledger_entries` for balance calculations

---

## Definition of Done

Epic 4 is complete when ALL of the following are verified:

### Functional Validation
- [ ] All 4 stories (4.1-4.4) marked complete with passing acceptance criteria
- [ ] Coverage proof manually sent with logging
- [ ] Settlement UI sorted by kickoff time
- [ ] Equal-split math correct (verified with calculator)
- [ ] VOID bets handled correctly (zero gain, still participate)
- [ ] All-VOID edge case produces ledger rows
- [ ] Ledger entries created with frozen FX snapshots
- [ ] Admin seat logic works (staked vs. non-staked)

### Technical Validation
- [ ] Append-only ledger enforced (no UPDATE/DELETE)
- [ ] FX snapshot stored in each ledger row
- [ ] Settlement batch IDs group related entries
- [ ] Transaction atomicity (rollback on failure)
- [ ] All EUR calculations use Decimal

### User Testing
- [ ] All 4 UAT scenarios pass
- [ ] Operator can settle 5 surebets end-to-end
- [ ] Entitlements sum correctly (no rounding errors >€0.01)

### Handoff Readiness
- [ ] Epic 5 team can query `ledger_entries` for reconciliation
- [ ] Ledger export (Epic 6) has data to export

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Equal-split math errors | Medium | Critical | Extensive testing; preview panel for operator verification |
| FX snapshot not frozen | Low | Critical | Unit tests verify snapshot immutability; code review |
| Ledger corruption (UPDATE/DELETE) | Low | Critical | Database triggers prevent; code review enforces append-only |
| Admin seat logic bug | Medium | High | Test both scenarios (admin staked vs. non-staked) thoroughly |
| All-VOID edge case missed | Medium | Medium | Specific test case; warning in preview panel |
| Transaction rollback fails | Low | High | Test error scenarios; manual DB backup before first settlement |

---

## Success Metrics

### Completion Criteria
- All 4 stories delivered with passing acceptance criteria
- Epic 4 "Definition of Done" checklist 100% complete
- Zero blockers for Epic 5 (Reconciliation)

### Quality Metrics
- **Settlement Accuracy**: 0 calculation errors
- **FX Integrity**: 100% of ledger rows have frozen snapshots
- **Append-Only Compliance**: 0 UPDATE/DELETE on ledger_entries
- **System Law Enforcement**: All 6 laws validated

---

## Related Documents

- [PRD: FR-5 (Coverage Proof Distribution)](../prd.md#fr-5-coverage-proof-distribution)
- [PRD: FR-6 (Settlement & Grading)](../prd.md#fr-6-settlement--grading)
- [PRD: Settlement Math Specification](../prd/settlement-math.md) *(if exists)*
- [PRD: System Laws](../prd.md#system-laws-non-negotiable-constraints)
- [Epic 3: Surebet Matching & Safety](./epic-3-surebet-matching.md)
- [Epic 5: Corrections & Reconciliation](./epic-5-corrections-reconciliation.md)
- [Implementation Roadmap](./implementation-roadmap.md)

---

## Notes

### Why Settlement is Irreversible

Once settlement creates ledger entries, they are **permanent** (System Law #1).

**Rationale:**
- **Audit Integrity**: Changing history breaks trust
- **Entitlement Math**: Downstream reconciliation depends on immutable ledger
- **Simplicity**: Forward corrections (Epic 5) are cleaner than in-place edits

**If operator makes mistake**: Use Epic 5 corrections (BOOKMAKER_CORRECTION) to adjust forward, never edit ledger.

### Admin Seat Philosophy

The admin seat logic (System Law #3) ensures:
- **Fairness**: If admin stakes, they're just another participant
- **Coordination Fee**: If admin doesn't stake, they still share profit/loss for coordinating
- **Shared Risk**: Admin also eats losses (not just skim profits)

**Example:**
- Surebet loses €10
- 2 partners staked, admin didn't
- Each participant (Partner A, Partner B, Admin) loses €3.33

This is **not a traditional fee** but true equal partnership.

---

**End of Epic**
