# Epic 3: Surebet Matching & Safety

**Status:** Not Started
**Priority:** P0 (MVP Critical)
**Estimated Duration:** 5-6 days
**Owner:** Tech Lead
**Phase:** 3 (Core Features)
**PRD Reference:** FR-3 (Deterministic Surebet Matching), FR-4 (Surebet Safety Check)

---

## Epic Goal

Build a deterministic matching engine that automatically pairs verified bets into surebets based on strict matching rules, then classifies each surebet's risk profile using worst-case EUR profit and ROI calculations. This epic is the **core intelligence** of the system.

---

## Business Value

### Operator Benefits
- **Automation**: No manual pairing of opposite-side bets
- **Risk Visibility**: Instant identification of unsafe surebets (❌) before settlement
- **Confidence**: Deterministic matching prevents false positives
- **Audit Trail**: Side assignments (A/B) frozen at creation time

### System Benefits
- **Correctness**: Strict matching rules eliminate mismatched bets
- **Safety**: ROI classification catches data entry errors early
- **Scalability**: Handles multiple bets on same side (A1+A2 vs B1)

**Success Metric**: 100% of valid opposite-side bets matched, 0% false matches, all unsafe surebets flagged.

---

## Epic Description

### Context

Epic 2 produces `bets` with `status="verified"`. These bets are ready for matching.

A **surebet** is a group of opposite-side bets on the same event/market/line where:
- Betting on **all possible outcomes** guarantees profit (or minimizes loss)
- For two-way markets: OVER vs UNDER, YES vs NO, TEAM_A vs TEAM_B

**Matching Rules (Non-Negotiable):**
1. Same `canonical_event_id`
2. Same `market_code`
3. Same `period_scope`
4. Same `line_value` (or both NULL)
5. Opposite logical side

**Side Assignment Rules (Immutable):**
- `side="A"` → OVER, YES, TEAM_A
- `side="B"` → UNDER, NO, TEAM_B
- Once assigned, NEVER changes (even if operator edits bet later)

### What's Being Built

Three interconnected components:

1. **Deterministic Matching Engine** (Story 3.1)
   - Triggered on bet approval (Epic 2 → `status="verified"`)
   - Finds opposite-side bets using strict matching
   - Creates/updates `surebets` rows
   - Links bets via `surebet_bets` with immutable side assignment

2. **Worst-Case EUR Profit Calculation** (Story 3.2)
   - Calculates profit for each possible outcome (Side A wins, Side B wins)
   - Determines worst-case profit and ROI
   - Stores results in `surebets` table (or calculates on-demand)

3. **Surebet Safety UI** (Story 3.3)
   - Visual surebet dashboard with risk badges
   - ✅ Green: Safe (positive ROI)
   - 🟡 Yellow: Low ROI (positive but <threshold)
   - ❌ Red: Unsafe (negative worst-case profit)
   - Displays EUR calculations for transparency

### Integration Points

**Upstream Dependencies:**
- Epic 2 (Bet Review): Produces `status="verified"` bets
- Phase 0 FX system: Converts currencies to EUR

**Downstream Consumers:**
- Epic 4 (Coverage Proof & Settlement): Consumes `status="open"` surebets

---

## Stories

### Story 3.1: Deterministic Matching Engine

**As the system**, I want verified bets to be automatically paired into surebets using strict matching rules so the operator doesn't have to manually group bets.

**Acceptance Criteria:**
- [ ] Matching trigger: On bet approval (Epic 2 sets `status="verified"`)
  - Call matching function: `attempt_match_bet(bet_id)`
- [ ] Matching algorithm:
  1. Query for opposite-side candidates:
     ```sql
     SELECT * FROM bets
     WHERE status = 'verified'
       AND canonical_event_id = <current_bet.canonical_event_id>
       AND market_code = <current_bet.market_code>
       AND period_scope = <current_bet.period_scope>
       AND (line_value = <current_bet.line_value> OR (line_value IS NULL AND <current_bet.line_value> IS NULL))
       AND side IN (<opposite_sides>)  -- e.g., if current is OVER, check for UNDER
     ```
  2. If candidates found:
     - Check if surebet already exists (query `surebets` joined with `surebet_bets`)
     - If exists: Add current bet to existing surebet
     - If not exists: Create new `surebets` row with `status="open"`
  3. Insert into `surebet_bets`:
     - `surebet_id`, `bet_id`
     - `side` (deterministic assignment):
       - If bet.side IN ('OVER', 'YES', 'TEAM_A'): `side="A"`
       - If bet.side IN ('UNDER', 'NO', 'TEAM_B'): `side="B"`
     - `created_at_utc`
  4. Update matched bets: Set `status="matched"`
- [ ] **CRITICAL**: `surebet_bets.side` is immutable
  - Enforce with database constraint (prevent UPDATE)
  - Or application-level check: raise error if side update attempted
- [ ] Handle multiple bets on same side:
  - Example: A1 + A2 vs B1 → ONE surebet, not multiple pairwise
  - All Side A bets linked with `side="A"`, all Side B with `side="B"`
- [ ] Unsupported bet types never matched:
  - Query excludes `is_supported=0` (e.g., accumulators)
- [ ] Matching idempotency: Re-running match on already-matched bet does nothing

**Technical Notes:**
- Consider database transaction: Match + create surebet + link bets atomically
- Log matching events: "Bet #123 matched into Surebet #45"
- Performance: Index on `(canonical_event_id, market_code, period_scope, line_value, side, status)`

---

### Story 3.2: Worst-Case EUR Profit Calculation

**As the operator**, I want to see worst-case profit and ROI for each surebet to identify risky bets before settlement.

**Acceptance Criteria:**
- [ ] Calculation function: `calculate_surebet_risk(surebet_id) -> dict`
  - Query all bets linked to surebet via `surebet_bets`
  - For each bet, convert to EUR using cached FX:
    - `stake_eur = bet.stake * get_fx_rate(bet.currency, today)`
    - `payout_eur = bet.payout * get_fx_rate(bet.currency, today)`
  - Calculate Side A wins scenario:
    - `profit_if_A_wins = (sum of Side A payouts in EUR) - (sum of ALL stakes in EUR)`
  - Calculate Side B wins scenario:
    - `profit_if_B_wins = (sum of Side B payouts in EUR) - (sum of ALL stakes in EUR)`
  - `worst_case_profit_eur = min(profit_if_A_wins, profit_if_B_wins)`
  - `total_staked_eur = sum(all stakes in EUR)`
  - `roi = worst_case_profit_eur / total_staked_eur * 100`  # as percentage
- [ ] ROI classification thresholds (configurable):
  - **Safe (✅)**: `worst_case_profit_eur >= 0` AND `roi >= 1.0%`
  - **Low ROI (🟡)**: `worst_case_profit_eur >= 0` BUT `roi < 1.0%`
  - **Unsafe (❌)**: `worst_case_profit_eur < 0` (guaranteed loss)
- [ ] Storage options:
  - **Option A**: Store calculated values in `surebets` table:
    - Add columns: `worst_case_profit_eur`, `total_staked_eur`, `roi`, `risk_classification`
    - Recalculate on bet addition/removal
  - **Option B**: Calculate on-demand in UI (no storage)
  - **Recommendation**: Option A for performance (cached calculations)
- [ ] Trigger recalculation:
  - When new bet added to surebet
  - When bet removed (e.g., operator corrects match)
  - When FX rates updated (daily)

**Technical Notes:**
- Use Phase 0 FX utilities: `get_fx_rate(currency, date)`
- All EUR calculations in `Decimal` (no float)
- Handle missing FX rates: Use last known rate with warning
- Log warnings if ROI calculation fails

---

### Story 3.3: Surebet Safety Dashboard UI

**As the operator**, I want visual indicators showing which surebets are safe vs. risky so I can prioritize review.

**Acceptance Criteria:**
- [ ] "Surebets" Streamlit page displays all `status="open"` surebets
  - Query: `SELECT * FROM surebets WHERE status='open' ORDER BY kickoff_time_utc ASC`
- [ ] Each surebet card/row displays:
  - **Event name**: From `canonical_events` (e.g., "Man Utd vs Arsenal")
  - **Market details**: `market_code`, `period_scope`, `line_value`
  - **Kickoff time**: Formatted local time (e.g., "2025-11-01 15:00")
  - **Side A bets**: List of associate aliases, bookmakers, stakes, odds
    - Example: "Admin @ Bet365: $100 @ 1.90"
  - **Side B bets**: List of associate aliases, bookmakers, stakes, odds
    - Example: "Partner A @ Pinnacle: £80 @ 2.10"
  - **EUR Calculations**:
    - "Worst-case profit: €XX.XX"
    - "Total staked: €YYY.YY"
    - "ROI: Z.Z%"
  - **Risk badge** (prominent, color-coded):
    - ✅ Green "Safe" if Safe classification
    - 🟡 Yellow "Low ROI" if Low ROI classification
    - ❌ Red "UNSAFE" if Unsafe classification (highlight prominently)
  - **Actions**: Buttons for Epic 4 (coverage proof, settlement)
- [ ] Counters at top:
  - "Open surebets: X"
  - "Unsafe surebets (❌): Y"
- [ ] Sorting options:
  - By kickoff time (default)
  - By ROI (lowest first - risky at top)
  - By total staked (largest first)
- [ ] Filter options:
  - Show only unsafe (❌)
  - Show by associate
- [ ] Drill-down: Click surebet → expand to show:
  - Screenshot links for all bets
  - Detailed EUR calculation breakdown:
    - "If Side A wins: €X profit"
    - "If Side B wins: €Y profit"
    - "Worst case: €Z"
  - FX rates used (transparency)

**Technical Notes:**
- Use `st.metric()` for EUR values
- Use `st.expander()` for drill-down details
- Color-code cards with CSS: red border for ❌, green for ✅
- Cache surebet query with TTL=5s

---

## User Acceptance Testing Scenarios

### Scenario 1: Perfect Surebet (Safe)
1. Operator approves two bets:
   - Bet A: OVER 2.5 @ 1.95, stake €100
   - Bet B: UNDER 2.5 @ 2.10, stake €100
2. Matching engine pairs into Surebet #1
3. Risk calculation:
   - If A wins: (€195) - (€200) = -€5
   - If B wins: (€210) - (€200) = +€10
   - Worst-case: -€5 (ROI: -2.5%)
   - Classification: ❌ Unsafe
4. Dashboard shows red badge "UNSAFE"
5. Operator investigates: notices stakes unbalanced, corrects Bet A to €95
6. Recalculation: worst-case now +€2.50, ROI: 1.3%
7. Classification updates to ✅ Safe

**Expected Result**: Unsafe surebet flagged before settlement, operator corrects proactively.

---

### Scenario 2: Multi-Bet Surebet (A1+A2 vs B)
1. Operator approves three bets:
   - Bet A1: TEAM_A @ 1.80, stake €50 (Admin @ Bet365)
   - Bet A2: TEAM_A @ 1.85, stake €30 (Partner A @ Pinnacle)
   - Bet B: TEAM_B @ 2.20, stake €90 (Partner B @ Sportsbet)
2. Matching engine creates ONE surebet:
   - Side A: A1 + A2 (€80 total staked)
   - Side B: B (€90 staked)
3. Risk calculation:
   - If A wins: (€50×1.80 + €30×1.85) - (€170) = €145.50 - €170 = -€24.50
   - If B wins: (€90×2.20) - (€170) = €198 - €170 = +€28
   - Worst-case: -€24.50 (ROI: -14.4%)
   - Classification: ❌ Unsafe
4. Dashboard shows multi-bet surebet as unsafe

**Expected Result**: System handles multiple bets on same side correctly.

---

### Scenario 3: Currency Conversion
1. Operator approves two bets:
   - Bet A: OVER 2.5 @ 1.90, stake 150 AUD (FX: 0.60 EUR per AUD)
   - Bet B: UNDER 2.5 @ 2.00, stake 100 GBP (FX: 1.15 EUR per GBP)
2. Matching engine pairs into surebet
3. Risk calculation converts to EUR:
   - Stake A: 150 × 0.60 = €90
   - Payout A: (150 × 1.90) × 0.60 = €171
   - Stake B: 100 × 1.15 = €115
   - Payout B: (100 × 2.00) × 1.15 = €230
   - Total staked: €205
   - If A wins: €171 - €205 = -€34
   - If B wins: €230 - €205 = +€25
   - Worst-case: -€34 (ROI: -16.6%)
   - Classification: ❌ Unsafe
4. Dashboard shows EUR values for transparency

**Expected Result**: Multi-currency surebets calculated correctly in EUR.

---

### Scenario 4: Safe Low-ROI Surebet
1. Operator approves two bets:
   - Bet A: YES @ 2.02, stake €100
   - Bet B: NO @ 2.02, stake €100
2. Risk calculation:
   - If A wins: €202 - €200 = +€2 (ROI: 1.0%)
   - If B wins: €202 - €200 = +€2 (ROI: 1.0%)
   - Worst-case: +€2 (ROI: 1.0%)
   - Classification: ✅ Safe (exactly at threshold)
3. Dashboard shows green "Safe" badge
4. Operator notes low ROI but proceeds

**Expected Result**: Low-ROI but positive surebets classified as safe.

---

## Technical Considerations

### Matching Algorithm Complexity

**Naive Approach** (O(n²)):
- On each bet approval, scan all verified bets for matches
- Works for MVP (<1000 bets/day)

**Optimized Approach** (O(log n)):
- Index on `(canonical_event_id, market_code, period_scope, line_value, side, status)`
- Use hash map for in-memory matching (future)

**Recommendation**: Start with naive, optimize if slow.

### Side Assignment Immutability

**Why Critical:**
- Settlement (Epic 4) uses `surebet_bets.side` to determine WON/LOST
- If side flips after settlement, ledger becomes inconsistent

**Enforcement:**
- Database: `CREATE TRIGGER prevent_side_update ...`
- Application: Raise exception if UPDATE attempted on `surebet_bets.side`
- Testing: Unit test verifies immutability

### FX Rate Staleness

**Risk**: FX rates cached daily, may be 24h old during matching.

**Mitigation**:
- Matching uses cached rates (acceptable for classification)
- Settlement (Epic 4) uses fresh snapshot (critical for ledger)
- Dashboard shows "FX rates as of {date}" for transparency

---

## Dependencies

### Upstream (Blockers)
- **Epic 2**: Bet Review complete
  - `status="verified"` bets exist
- **Phase 0**: FX system working
  - Currency conversion utilities available

### Downstream (Consumers)
- **Epic 4**: Coverage Proof & Settlement
  - Reads from `status="open"` surebets

---

## Definition of Done

Epic 3 is complete when ALL of the following are verified:

### Functional Validation
- [ ] All 3 stories (3.1-3.3) marked complete with passing acceptance criteria
- [ ] Verified bets automatically paired into surebets
- [ ] Side assignments (A/B) correct and immutable
- [ ] Multi-bet surebets (A1+A2 vs B) handled correctly
- [ ] ROI calculated correctly with currency conversion
- [ ] Dashboard displays surebets with risk badges

### Technical Validation
- [ ] No false matches (100% accuracy)
- [ ] Side immutability enforced (unit test)
- [ ] FX conversion uses Decimal (no float errors)
- [ ] Matching performance acceptable (<1s per bet)

### User Testing
- [ ] All 4 UAT scenarios pass
- [ ] Unsafe surebets visually prominent
- [ ] Operator can drill down into EUR calculations

### Handoff Readiness
- [ ] Epic 4 team can query `status="open"` surebets
- [ ] Risk classifications meaningful for settlement prioritization

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| False matches (wrong event/market) | Low | High | Strict matching rules; unit tests with edge cases |
| Side assignment flips after creation | Low | Critical | Database constraint + application-level check |
| FX rate staleness causes misclassification | Medium | Medium | Show "FX as of {date}" in UI; acceptable for classification |
| Multi-bet matching logic bug | Medium | High | Comprehensive testing with 3+ bets on same side |
| Matching performance degrades | Low | Medium | Database indexes; optimize if >1s per match |

---

## Success Metrics

### Completion Criteria
- All 3 stories delivered with passing acceptance criteria
- Epic 3 "Definition of Done" checklist 100% complete
- Zero blockers for Epic 4 (Settlement)

### Quality Metrics
- **Match Accuracy**: 100% of valid opposite-side bets matched
- **False Positive Rate**: 0% (no incorrect matches)
- **Risk Detection**: 100% of unsafe surebets flagged (❌)
- **Side Immutability**: 0 side flips after creation

---

## Related Documents

- [PRD: FR-3 (Deterministic Surebet Matching)](../prd.md#fr-3-deterministic-surebet-matching)
- [PRD: FR-4 (Surebet Safety Check)](../prd.md#fr-4-surebet-safety-check-roi-classification)
- [Epic 2: Bet Review & Approval](./epic-2-bet-review.md)
- [Epic 4: Coverage Proof & Settlement](./epic-4-coverage-settlement.md)
- [Implementation Roadmap](./implementation-roadmap.md)

---

## Notes

### Why Deterministic Matching Matters

Manual pairing is error-prone:
- Operator might miss opposite side → unmatched bet
- Operator might pair wrong events → false surebet
- Operator might flip sides → settlement chaos

**Deterministic matching** eliminates human error and provides:
- **Consistency**: Same inputs always produce same output
- **Auditability**: Match logic encoded in code, not operator memory
- **Speed**: Instant pairing vs. manual review

### Side Assignment as System Law

While not listed in PRD's "6 System Laws," side immutability is equally critical:

**System Law #7 (Implicit)**: Side assignments (A/B) in `surebet_bets` are immutable after creation.

Violating this law breaks:
- Settlement profit calculations (Epic 4)
- Ledger integrity (Epic 5)
- Historical analysis (future)

**Treat side assignments as sacred.**

---

**End of Epic**
