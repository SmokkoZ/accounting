# Epic 11: Your Fair Balance (YF) & Exit Settlement Alignment

## Epic Goal

Ensure associates never lose money by adopting a single financial identity across the system: YF = ND + FS, fixing ND sign consistency, unifying calculations in all views/exports, and adding an explicit Exit Settlement flow that zeroes Δ at deactivation.

## Epic Description

### Existing System Context

- Financial domains: Reconciliation, Statements, per-Bookmaker views, CSV exports.
- Services: StatementService (statements, exports), ledger/transactions, ROI snapshots, FX conversion.
- UI: Streamlit screens for statements/operations, admin tools, Telegram bot prompts for funding/withdrawals.
- Data: SQLite (default), CSV exports under `data/exports`, tests under `tests/integration` and `tests/unit`.

### Enhancement Details

- Adopt unified financial identity and labeling:
  - Your Fair Balance (YF) = Net Deposits (ND) + Fair Shares (FS)
  - Maintain imbalance: Δ = TB − YF, where TB is Total Bookmaker holdings
  - Rename “Should Hold” to “Your Fair Balance (YF)” across UI/CSVs/docs
- Net Deposits (ND) consistency:
  - Store WITHDRAWAL as negative amounts; DEPOSIT as positive
  - Compute ND by summing stored amounts for DEPOSIT/WITHDRAWAL (no double-negation)
- Fair Shares (FS):
  - Sum of per-surebet share (EUR) across associate’s surebets
  - Respect WON/LOST/VOID semantics already used by statement math
- Exit Settlement flow:
  - “Settle Associate Now” action on Statements/Operations screens at a cutoff date
  - Compute Δ at cutoff, post a single ledger entry (DEPOSIT if Δ < 0, WITHDRAWAL if Δ > 0) to make Δ = 0
  - Produce receipt (CSV/markdown snippet) and reflect the settlement in the export at the cutoff
- Reporting/UI updates:
  - Show ND, FS, YF, TB, Δ explicitly in headers/summary blocks
  - CSVs include YF and an “Exit Payout” row (−Δ) for exit exports
  - Add version stamp and definition footnote in exports to clarify YF model
- Documentation and tests:
  - Update tests to assert identities (e.g., YF − ND = FS) and ND sign handling
  - Update README/docs for definitions and label changes

## Stories

1. ND Sign Consistency and Identity Adoption
   - Standardize storage/read semantics: WITHDRAWAL negative, DEPOSIT positive
   - Apply YF = ND + FS in Reconciliation, Statements, Bookmaker views
   - Display ND/FS/YF/Δ in headers; Δ = TB − YF
   - Tests: mixed deposit/withdrawal scenarios; identity checks; VOID/WON/LOST coverage

2. Exit Settlement Flow and Receipt
   - Add “Settle Associate Now” operation that computes Δ at cutoff and posts a single balancing ledger entry
   - Generate receipt artifact and include “Exit Payout” row (−Δ) in exit CSV
   - Ensure post‑action Δ == 0 and exports reflect the settlement

3. Copy/CSV/Docs Alignment (Non‑schema)
   - Rename “Should Hold” to “Your Fair Balance (YF)” across UI, exports, docs
   - Add tooltips and release notes; add version stamp + definition footnote in CSVs
   - Backward compatibility notes; no schema changes required

## Compatibility Requirements

- [ ] No API surface changes required
- [ ] No database schema changes (semantics only)
- [ ] CSVs remain backward compatible; additional columns/rows are versioned and documented
- [ ] UI follows existing patterns (Streamlit components, consistent labels)
- [ ] Performance impact minimal; reuse existing statement math

## Risk Mitigation

- Primary Risk: Terminology shift may confuse users
  - Mitigation: Inline tooltips, release notes, temporary dual‑labeling
- Risk: Historical screenshots/CSVs compare differently
  - Mitigation: Version stamp + definition footnote; maintain prior exports unchanged
- Risk: Implementation drift in ND sign handling across services
  - Mitigation: Shared utility for ND computation and cross‑module tests

## Definition of Done

- [ ] All stories completed with acceptance criteria met
- [ ] Identity holds: YF = ND + FS and Δ = TB − YF in all views/exports
- [ ] Exit Settlement flow zeros Δ with a single balancing entry; receipt generated
- [ ] Tests updated and passing for mixed ND, VOID/WON/LOST, and export validation
- [ ] Documentation updated (README, user-facing labels, CSV notes)
- [ ] No regressions in existing features

## Validation Checklist

Scope Validation:
- [ ] Enhancement can be completed in 2–3 stories
- [ ] Follows existing patterns; no architectural changes
- [ ] Integration complexity is manageable

Risk Assessment:
- [ ] Risk to existing system is low
- [ ] Rollback plan: feature flag to hide YF labeling and disable “Settle Now” action
- [ ] Testing covers existing functionality and new identities

Completeness Check:
- [ ] Goal is clear and achievable
- [ ] Stories properly scoped; identities verified via tests
- [ ] Success criteria measurable (Δ after settlement == 0)

## Story Manager Handoff

Please develop detailed user stories for this brownfield epic. Key considerations:

- This is an enhancement to an existing system using Python 3.12, Streamlit UI, SQLite, Telegram bot for funding workflows
- Integration points: ledger service, StatementService (statements and CSV exports), per‑bookmaker holdings aggregation, tests at `tests/integration/test_statement_flow.py`
- Existing patterns to follow: reuse statement math and CSV generation helpers
- Critical compatibility requirements: no schema changes; maintain export compatibility with versioning and footnotes
- Each story must validate identities (YF, Δ) and ensure exit settlement zeroes Δ

The epic should maintain system integrity while delivering the guaranteed “never lose” experience at exit.

## Acceptance Criteria (Traceable)

- AC1: ND equals deposits − withdrawals everywhere; withdrawals stored negative; tests cover mixed deposit/withdrawal scenarios
- AC2: FS aggregates from BET_RESULT share fields; tests cover VOID/WON/LOST handling
- AC3: YF = ND + FS in Reconciliation, Statements, Bookmaker views, and CSVs; tests assert identities (YF − ND = FS)
- AC4: Δ = TB − YF; “Settle Associate Now” posts a single ledger entry to zero Δ; post‑action Δ == 0 and CSV reflects payout
- AC5: Backward compatibility notes updated; labels clarified; no schema changes required

## Decision Requests

1. Approve Option A (Full Alignment: YF = ND + FS globally) vs. alternative
2. Confirm mandatory “Exit Settlement” before associate deactivation
3. Approve label change to “Your Fair Balance” and showing ND/FS/YF/Δ
4. Approve correction of ND sign inconsistency in the per‑bookmaker view now

## Timeline

3–5 days (global formula updates, tests, copy, docs, and small UI refactors)

## Success Metrics

- 100% associates exiting with Δ = 0 (auto‑verified)
- No reported cases of associates receiving less than ND + FS at exit
- Reduced reconciliation time for exits (support/ops feedback)

