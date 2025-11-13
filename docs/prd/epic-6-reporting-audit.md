# Epic 6: Reporting & Audit

**Status:** Not Started
**Priority:** P0 (MVP Critical)
**Estimated Duration:** 3-4 days
**Owner:** Tech Lead
**Phase:** 6 (Final MVP Features)
**PRD Reference:** FR-9 (Ledger Export), FR-10 (Monthly Statements)

---

## Epic Goal

Build comprehensive CSV export functionality and partner-facing monthly statement generation. This epic provides **transparency** and **reporting** capabilities for audit, backup, and stakeholder communication.

---

## Business Value

### Operator Benefits
- **Audit Trail**: Complete ledger exportable to CSV for external audit or Excel analysis
- **Backup**: Regular exports serve as ledger backup (disaster recovery)
- **Partner Communication**: Generate human-readable statements for associates
- **Transparency**: Show partners how entitlement is calculated

### System Benefits
- **External Tool Integration**: CSV format compatible with spreadsheets, accounting software
- **Data Portability**: Not locked into application (ledger is exportable)
- **Compliance**: Auditable financial records

**Success Metric**: 100% of ledger rows exportable, monthly statements accurate and understandable by non-technical associates.

---

## Epic Description

### Context

Epics 4-5 populate `ledger_entries` with financial transactions. The ledger is the **single source of truth**.

For **audit and backup**, operator needs:
- Full ledger export to CSV (all rows, all fields, with readable joins)

For **partner communication**, operator needs:
- Monthly statements showing: funding, entitlement, profit, 50/50 split
- Internal-only reconciliation data (DELTA)

### What's Being Built

Two reporting tools:

1. **Complete Ledger CSV Export** (Story 6.1)
   - Export all `ledger_entries` rows
   - Join with associates, bookmakers, surebets
   - Output to `data/exports/ledger_{timestamp}.csv`

2. **Monthly Statement Generator** (Story 6.2)
   - Per-associate summary report
   - Cutoff date selector (end of month)
   - Human-readable profit/loss explanation
   - Internal-only DELTA display
   - **CRITICAL**: Read-only (no ledger writes)

### Integration Points

**Upstream Dependencies:**
- Epic 4 (Settlement): Produces `BET_RESULT` rows
- Epic 5 (Reconciliation): Defines reconciliation math (NET_DEPOSITS, SHOULD_HOLD, etc.)

**Downstream Consumers:**
- None (Epic 6 is terminal - outputs data out of system)

---

## Stories

### Story 6.1: Complete Ledger CSV Export

**As the operator**, I want to export the full ledger to CSV for external audit or backup so I have a portable copy of financial history.

**Acceptance Criteria:**
- [ ] "Export" page with "Export Full Ledger" button
- [ ] On click:
  - Query all `ledger_entries` rows (no filtering, include all entry types)
  - Join with related tables:
    - `associates.display_alias` (associate name)
    - `bookmakers.name` (bookmaker name)
    - `surebets.surebet_id` (for traceability)
    - `bets.bet_id` (for traceability)
  - Generate CSV with columns:
    ```
    entry_id, entry_type, associate_alias, bookmaker_name,
    surebet_id, bet_id, settlement_batch_id,
    settlement_state,
    amount_native, native_currency, fx_rate_snapshot, amount_eur,
    principal_returned_eur, per_surebet_share_eur,
    created_at_utc, created_by, note
    ```
  - Write to: `data/exports/ledger_{timestamp}.csv`
    - `{timestamp}` = ISO8601 with seconds (e.g., `ledger_20251030_143045.csv`)
  - Success message: "Ledger exported: {file_path}" (clickable link)
- [ ] CSV format:
  - Header row with column names
  - All numeric fields formatted as strings (preserve Decimal precision)
  - NULL values as empty strings
  - UTF-8 encoding
  - Comma delimiter, double-quote escaping
- [ ] Export validation:
  - Row count in CSV matches `ledger_entries` table row count
  - Spot-check: first and last rows match database
- [ ] Export history (below button):
  - List recent exports (last 10)
  - Display: timestamp, filename, row count, file size
  - "Re-download" link for each

**Technical Notes:**
- Use Python `csv` module or pandas `to_csv()`
- Handle large ledgers (10k+ rows): stream to file, don't load all into memory
- Test with UTF-8 special characters (e.g., associate names with accents)
- Consider compression (`.csv.gz`) for large files (future)

---

### Story 6.2: Monthly Statement Generator

**As the operator**, I want to generate per-associate statements showing funding, entitlement, and 50/50 split so I can share profit reports with partners.

**Acceptance Criteria:**
- [ ] "Monthly Statements" page with:

  **Input Panel:**
  - **Associate selector**: Dropdown from `associates.display_alias`
  - **Cutoff date picker**: Default to end of current month (e.g., "2025-10-31 23:59:59 UTC")
    - Note: "All transactions up to and including this date"
  - **"Generate Statement" button**

  **Output Panel (after clicking Generate):**

  **1. Statement Header:**
  ```
  Monthly Statement for [Associate Name]
  Period ending: [Cutoff Date]
  Generated: [Current Timestamp]
  ```

  **2. Partner-Facing Section (Shareable):**

  - **Funding Summary:**
    - `NET_DEPOSITS_EUR = SUM(DEPOSIT.amount_eur) - SUM(WITHDRAWAL.amount_eur)` up to cutoff
    - Display: "You funded: €X,XXX.XX total"
    - Explanation: "This is the cash you personally put in."

  - **Entitlement Summary:**
    - `SHOULD_HOLD_EUR = SUM(principal_returned_eur + per_surebet_share_eur)` from all BET_RESULT rows up to cutoff
    - Display: "You're entitled to: €X,XXX.XX"
    - Explanation: "If we froze time right now, this much of the pot is yours."

  - **Profit/Loss Summary:**
    - `RAW_PROFIT_EUR = SHOULD_HOLD_EUR - NET_DEPOSITS_EUR`
    - Display:
      - If positive: "Your profit: €X,XXX.XX" (green)
      - If negative: "Your loss: €X,XXX.XX" (red)
    - Explanation: "How far ahead/behind you are compared to what you funded."

  - **50/50 Split Calculation:**
    - Display: "Our deal is 50/50, so:"
      - "Your share: €XXX.XX (half of profit)"
      - "Admin share: €XXX.XX (half of profit)"
    - Note: "This is for transparency. In our system, profit is already split equally through per-surebet shares."

  **3. Internal-Only Section (NOT for partners):**

  - **Current Holdings:**
    - `CURRENT_HOLDING_EUR = SUM(all ledger entries)` up to cutoff
    - Display: "Currently holding: €X,XXX.XX"
    - Explanation: "What model thinks you're physically holding in bookmaker accounts."

  - **Reconciliation Delta:**
    - `DELTA = CURRENT_HOLDING_EUR - SHOULD_HOLD_EUR`
    - Display:
      - If DELTA > 0: "🔴 Holding €XXX more than entitlement (collect from associate)"
      - If DELTA ≈ 0: "🟢 Balanced"
      - If DELTA < 0: "🟠 Short €XXX (owed to associate)"

  **4. Export Options:**
  - "Copy to Clipboard" button (partner-facing section only)
  - "Export to PDF" button (future, for now just text)
  - "Export to CSV" button (detailed transaction list for this associate)

- [ ] Validation:
  - Cutoff date cannot be in future
  - Associate required
- [ ] **CRITICAL**: Monthly statements are **presentation ONLY**
  - Do NOT create ledger entries
  - Do NOT modify entitlement math
  - Read-only queries

**Technical Notes:**
- Use Epic 5 reconciliation math (same formulas)
- Filter ledger queries: `WHERE created_at_utc <= cutoff`
- Format currency with commas (e.g., "€1,234.56")
- Round to 2 decimal places for display
- Consider templating system (Jinja2) for statement formatting (future)

---

## User Acceptance Testing Scenarios

### Scenario 1: Full Ledger Export
1. Operator goes to Export page
2. Clicks "Export Full Ledger"
3. CSV generated: `ledger_20251030_143045.csv`
4. Success message: "Ledger exported: data/exports/ledger_20251030_143045.csv"
5. Operator opens CSV:
   - Header row: `entry_id, entry_type, associate_alias, ...`
   - 150 data rows (matches database: `SELECT COUNT(*) FROM ledger_entries`)
   - Spot-check row 1: entry_id=1, entry_type='BET_RESULT', associate='Admin', amount_eur='95.00'
   - All fields populated correctly
6. Operator loads into Excel: no errors, Decimal precision preserved

**Expected Result**: CSV contains complete ledger, no data loss, Excel-compatible.

---

### Scenario 2: Monthly Statement (Profitable Associate)
1. Operator goes to Monthly Statements page
2. Selects:
   - Associate: "Partner A"
   - Cutoff: "2025-10-31 23:59:59 UTC"
3. Clicks "Generate Statement"
4. Statement displays:
   ```
   Monthly Statement for Partner A
   Period ending: 2025-10-31 23:59:59 UTC
   Generated: 2025-11-01 09:00:00 UTC

   --- Partner-Facing Section ---
   You funded: €2,000.00 total
   This is the cash you personally put in.

   You're entitled to: €2,300.00
   If we froze time right now, this much of the pot is yours.

   Your profit: €300.00
   How far ahead you are compared to what you funded.

   Our deal is 50/50, so:
   Your share: €150.00 (half of profit)
   Admin share: €150.00 (half of profit)

   --- Internal-Only Section ---
   Currently holding: €2,500.00
   What model thinks you're physically holding in bookmaker accounts.

   🔴 Holding €200 more than entitlement (collect from associate)
   ```
5. Operator copies partner-facing section to clipboard
6. Operator sends to Partner A via secure channel (Signal/WhatsApp)

**Expected Result**: Statement accurate, human-readable, DELTA highlights issue.

---

### Scenario 3: Monthly Statement (Loss Position)
1. Operator selects Associate: "Partner B", Cutoff: "2025-10-31"
2. Statement displays:
   ```
   You funded: €1,000.00 total
   You're entitled to: €850.00
   Your loss: €150.00 (red text)

   Our deal is 50/50, so:
   Your share of loss: €75.00
   Admin share of loss: €75.00

   --- Internal-Only ---
   Currently holding: €800.00
   🟠 Short €50 (owed to associate)
   ```
3. Operator sees Partner B is down €150 overall, and also short €50 in holdings

**Expected Result**: Loss displayed correctly, negative profit shown in red.

---

### Scenario 4: Statement at Different Cutoffs
1. Operator generates statement for "Partner A" at cutoff "2025-09-30"
2. NET_DEPOSITS = €1,500 (only deposits before Sept 30)
3. SHOULD_HOLD = €1,600 (only settled bets before Sept 30)
4. RAW_PROFIT = €100
5. Operator generates again at cutoff "2025-10-31"
6. NET_DEPOSITS = €2,000 (includes October deposit)
7. SHOULD_HOLD = €2,300 (includes October bets)
8. RAW_PROFIT = €300

**Expected Result**: Cutoff date filters correctly, historical statements reproducible.

---

## Technical Considerations

### CSV Export Performance

**Potential Issue**: Exporting 10k+ ledger rows takes >10 seconds.

**Solutions**:
- **Streaming**: Use `csv.writer()` with file handle, don't load all rows into memory
- **Progress bar**: Show "Exporting... X/Y rows"
- **Background task**: Use Streamlit `@st.cache_data` or async export

**Recommendation**: Start with synchronous export, optimize if >5s.

### Monthly Statement Semantics

**Key Principle**: Statements are **snapshots**, not transactions.

- **Do NOT** create ledger entries when generating statement
- **Do NOT** modify entitlement math
- **Purpose**: Present existing data in human-readable format

**Analogy**: Like a bank statement - shows transactions that already happened, doesn't create new transactions.

### 50/50 Split Display

**Important Nuance**:
- The PRD states: "Our deal is 50/50, so €Z/2 each"
- BUT the system already does equal-split through `per_surebet_share_eur`
- The "50/50" in statement is **explanatory**, not a recalculation

**Display Logic**:
```python
raw_profit_eur = should_hold_eur - net_deposits_eur
if raw_profit_eur >= 0:
    # Profit case
    your_share = raw_profit_eur / 2
    admin_share = raw_profit_eur / 2
else:
    # Loss case
    your_share_of_loss = abs(raw_profit_eur) / 2
    admin_share_of_loss = abs(raw_profit_eur) / 2
```

**Note**: This is for presentation. Actual entitlement comes from `SHOULD_HOLD_EUR`.

### Cutoff Date Edge Cases

**Midnight Boundary**:
- Cutoff: "2025-10-31 23:59:59 UTC" includes all Oct 31 transactions
- Next cutoff: "2025-11-30 23:59:59 UTC" includes all November

**Partial Settlements**:
- If surebet settled at 2025-10-31 14:00, all BET_RESULT rows have `created_at_utc = 2025-10-31 14:00`
- Cutoff: "2025-10-31 12:00" EXCLUDES this settlement
- Cutoff: "2025-10-31 23:59:59" INCLUDES this settlement

**Test**: Generate statements before and after settlement to verify cutoff works.

---

## Dependencies

### Upstream (Blockers)
- **Epic 5**: Reconciliation complete
  - Reconciliation math formulas defined
  - Ledger populated with diverse entry types
- **Epic 4**: Settlement complete
  - `BET_RESULT` rows exist

### Downstream (Consumers)
- None (Epic 6 is terminal)

---

## Definition of Done

Epic 6 is complete when ALL of the following are verified:

### Functional Validation
- [ ] All 2 stories (6.1-6.2) marked complete with passing acceptance criteria
- [ ] Full ledger exportable to CSV
- [ ] CSV includes all rows with correct joins
- [ ] Monthly statements generate correctly
- [ ] Cutoff date filtering works
- [ ] 50/50 split displayed accurately

### Technical Validation
- [ ] CSV row count matches database
- [ ] Decimal precision preserved in CSV
- [ ] Statement math verified with calculator
- [ ] Cutoff date edge cases tested
- [ ] No ledger writes during statement generation (read-only)

### User Testing
- [ ] All 4 UAT scenarios pass
- [ ] Operator can generate statements for multiple associates
- [ ] Statements understandable by non-technical user

### MVP Completion
- [ ] Epic 6 is the **final MVP epic**
- [ ] All 10 Functional Requirements (FR-1 to FR-10) implemented
- [ ] System is feature-complete for MVP

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| CSV export fails with large ledgers | Low | Medium | Streaming write; test with 10k+ rows |
| Statement math disagrees with reconciliation | Low | High | Use same formulas as Epic 5; unit tests |
| Cutoff date confusion (timezone issues) | Medium | Low | Always use UTC; display timezone in UI |
| Partner misinterprets 50/50 split | Medium | Low | Clear explanations; operator training |
| Decimal precision lost in CSV | Low | Medium | Format as strings; test with Excel |

---

## Success Metrics

### Completion Criteria
- All 2 stories delivered with passing acceptance criteria
- Epic 6 "Definition of Done" checklist 100% complete
- **MVP is complete** (Epics 0-6 all done)

### Quality Metrics
- **Export Accuracy**: 100% of ledger rows in CSV
- **Statement Accuracy**: Math matches reconciliation dashboard
- **User Comprehension**: Non-technical associates understand statements
- **Audit Readiness**: CSV loadable in Excel without errors

---

## Related Documents

- [PRD: FR-9 (Ledger Export)](../prd.md#fr-9-ledger-export)
- [PRD: FR-10 (Monthly Statements)](../prd.md#fr-10-monthly-statements-partner-reports)
- [PRD: Reconciliation Glossary](../prd.md#appendix-c-reconciliation-glossary)
- [Epic 5: Corrections & Reconciliation](./epic-5-corrections-reconciliation.md)
- [Implementation Roadmap](./implementation-roadmap.md)

---

## Notes

### Why CSV Export Matters

**Disaster Recovery**:
- If SQLite database corrupts, CSV exports serve as backup
- Ledger can be reimported from CSV

**External Audit**:
- Accountants prefer spreadsheets (Excel, Google Sheets)
- CSV is universal format

**Data Portability**:
- Not locked into custom application
- Can migrate to different system using CSV

**Recommendation**: Export ledger weekly as backup routine.

### Monthly Statement as Communication Tool

**Purpose**: Build trust with associates through transparency.

**Best Practices**:
1. Generate monthly (end of month)
2. Share partner-facing section only (hide DELTA)
3. Explain any large swings (e.g., "You had 10 winning bets this month")
4. Use statement as starting point for discussion

**Anti-Pattern**: Don't use statements to argue about money - ledger is source of truth, not statement.

### MVP Completion Celebration

Epic 6 is the **final epic** for MVP. When this epic is done:

✅ **All 10 Functional Requirements implemented**
✅ **All 6 System Laws enforced**
✅ **End-to-end workflow complete**: Screenshot → Settlement → Reconciliation → Export
✅ **System is production-ready** for single operator

**Next Steps Post-MVP**:
- User acceptance testing with real bets
- Bug fixes and polish
- Performance optimization
- Future enhancements (see Roadmap Phase 7+)

🎉 **Congratulations on reaching MVP!** 🎉

---

**End of Epic**

---

## Change Notes — YF & Exit Settlement Alignment (2025-11-13)

- Statements adopt `Your Fair Balance (YF) = ND + FS`; replace “Should Hold” labels in summaries while keeping historical references mapped.
- CSV exports add YF and an “Exit Payout” (`−Δ`) row for exit cutoffs with footer `Model: YF‑v1 (YF=ND+FS; Δ=TB−YF)`; values exclude operator fees/taxes.
- Standardize ND sign handling: withdrawals negative, deposits positive; test identities `YF − ND == FS` and `Δ = TB − YF`.
- No schema changes; existing calculators reused; changes are labels, notes, and one additional export row at exit.
