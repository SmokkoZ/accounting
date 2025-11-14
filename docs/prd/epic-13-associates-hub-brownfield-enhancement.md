# Epic 13: Associates Hub - Brownfield Enhancement

## Epic Goal

Create a unified "Associates Hub" page that replaces the current Admin & Associates and non-Telegram parts of the Associate Operations Hub, making it the primary place to add/edit associates and their bookmakers, while still exposing key financial metrics and history in a safe, table-centric, inline-edit-friendly UI.

## Epic Description

**Existing System Context**

- Current relevant functionality:
  - "Admin & Associates" page for managing associates and bookmakers via inline-edit tables and filters.
  - "Associate Operations Hub" for viewing ND/YF/TB/Δ, balances, and funding transactions, plus Telegram-related workflows.
- Technology stack:
  - Python, Streamlit UI, SQLite, single-user desktop-style app, existing balance and funding data model.
- Integration points:
  - Existing associates and bookmakers tables.
  - Derived metrics pipeline (ND, YF, TB, Δ).
  - Funding transactions (deposits/withdrawals) and balance history views.
  - Telegram-related workflows (funding drafts, OCR, coverage proof) that will move to a separate "Telegram Hub" page and are out of scope here.

**Enhancement Details**

- Introduce a single "Associates Hub" page with three tabs:
  - Management (default, config-first).
  - Overview (operational/financial view on ND/YF/TB/Δ and quick funding actions).
  - Balance History (historical analytics and export).
- Management tab:
  - Top section: "Associates Management" table (st.data_editor-style) for adding and editing associate-level config (alias, home currency, flags, notes, limits, chats).
  - Lower section: "Bookmaker Management" table filtered by selected associate(s) or "All".
  - Clear separation between editable config fields and read-only derived metrics (ND, YF, TB, Δ, last activity).
  - Actions per associate: open a shared detail view (drawer/modal), jump to Overview with the associate selected, or jump to Balance History pre-filtered.
  - "Add associate" flow: insert a new inline-editable row, then guide the operator to add bookmakers for that associate in the Bookmaker Management section.
- Overview tab:
  - Focused on ND/YF/TB/Δ across associates, with filters by alias, status (balanced/overholding/short), currency, and risk.
  - Summaries of how many associates are balanced/overholding/short.
  - Per-associate row/card showing ND, YF, TB, Δ with quick actions: open detail view, create deposit/withdraw via dialog, jump back to Management.
- Balance History tab:
  - Historical view of balances and related metrics, with filters for associate, bookmaker, and date range.
  - Charts of ND/TB/Δ over time, plus a tabular view.
  - Export of history data in `.xlsx` format (aligned with existing XLSX export direction).
- Shared detail view (drawer/modal):
  - Accessible from both Management and Overview.
  - Tabs inside: Profile, Balances, Funding Transactions.
  - Funding Transactions tab exposes a read-only table of past funding transactions plus explicit "New Deposit" / "New Withdrawal" dialogs (direction, amount, currency, optional bookmaker, note, confirm).
  - No financial changes via direct numeric cell edits; all money movements flow through explicit actions/dialogs.
- Behavioural constraints and UX rules:
  - Management-first: the app "feels" like a config console; Overview and Balance History build on this config.
  - Clear visual distinction between editable config fields and derived/read-only metrics (e.g. color, icons, disabled styling).
  - Master–detail pattern: Management drives selection; Overview and Balance History reuse the same selected associate context.
  - Bookmaker reassignment is allowed but requires an explicit confirmation when the bookmaker has non-zero active balances.
  - No role-based gating (single-user app), but flows remain explicit and safe for financial operations.
- Out of scope (explicitly):
  - Telegram funding draft approval workflows.
  - OCR ingestion pipelines.
  - Coverage proof workflows.
  - All Telegram-specific operations will be handled on a separate "Telegram Hub" page.

## Stories

1. **Story 13.1: Management Tab - Associates & Bookmaker Configuration**
   - Create an "Associates Hub" page with a Management tab as the default view.
   - Implement an "Associates Management" table with inline-editable config fields:
     - Alias, home currency, admin flag, active flag, multibook chat ID, internal notes, risk-related limits (e.g. max stake per surebet, max total exposure per bookmaker), preferred balance report chat.
   - Display read-only metrics in the same table: ND, YF, TB, Δ (color-coded by status), bookmaker count, last activity timestamp.
   - Implement an Actions column per associate with:
     - "Details" (opens the shared associate detail view).
     - "Go to Overview" (switches to Overview tab with this associate pre-selected).
     - "View history" (switches to Balance History tab pre-filtered to this associate).
   - Add search and filter controls (by alias, status, currency, risk flag) and sorting (alias, ND, Δ, last activity).
   - Implement an "Add associate" flow:
     - Clicking "Add associate" inserts a new row (top or bottom) with editable required fields and clear validation.
     - Saving a new associate persists it and updates both associates and bookmakers contexts.
   - Implement a "Bookmaker Management" table beneath the associates table:
     - Filter by selected associate(s) (default) or "All".
     - Editable fields include: display name, associated associate, currency, active flag, bookmaker chat ID(s), multibook/coverage chat, region/risk level, internal notes.
     - Read-only columns include: active balances (if any), last used date.
     - "Add bookmaker" adds a new row scoped to the currently selected associate.
   - Lock ND, YF, TB, Δ and other derived fields from inline editing; they must be visually recognized as read-only.

2. **Story 13.2: Overview Tab & Shared Associate Detail + Funding Dialogs**
   - Add an Overview tab to the Associates Hub that:
     - Preserves the currently selected associate from the Management tab when navigated via "Go to Overview".
     - Shows high-level filters: search by alias/bookmaker, status (balanced/overholding/short), currency, region/risk.
     - Displays a summary of balanced/overholding/short associates.
   - Display associates as rows or cards showing ND, YF, TB, Δ and key status cues.
   - Implement per-associate quick actions:
     - "Details" (opens the shared associate detail view).
     - "Deposit" and "Withdraw" (open funding dialogs).
     - "Go to Management" (returns to Management tab with the same associate selected).
   - Implement the shared associate detail view as a drawer/modal that:
     - Is accessible from both Management and Overview, with the same layout and fields.
     - Includes Profile, Balances, and Funding Transactions sub-tabs.
     - Shows config fields consistent with Management (alias, currency, flags, limits, chat IDs) and allows saving changes.
     - Shows current balances and ND/YF/TB/Δ as read-only metrics.
   - Implement funding dialogs for deposits and withdrawals:
     - Direction (Deposit/Withdraw), amount, currency, optional bookmaker, note, confirmation.
     - On confirm, create a funding transaction and refresh the Balances, Overview, and Management data.
   - Ensure that no money movements are possible via inline table edits; funding must go through these dialogs.

3. **Story 13.3: Balance History Tab & Deep Linking**
   - Add a Balance History tab to the Associates Hub with:
     - Filters for associate (required or inherited from navigation), bookmaker, date range, and metric type.
     - Charts showing ND, TB, Δ over time, with hover tooltips for exact values.
     - A table of balance history entries including timestamps, associated transactions, and relevant metrics.
   - Implement deep linking from Management:
     - "View history" action navigates to the Balance History tab with the selected associate (and optionally bookmaker) pre-filtered.
   - Implement deep linking from Overview:
     - "View history" from an associate card/row navigates to Balance History with the same context.
   - Provide an export option for balance history:
     - Export the currently filtered history to `.xlsx` (default/preferred format).
   - Ensure that navigating back to Management or Overview preserves the selected associate context.

## Compatibility Requirements

- [x] Existing associates and bookmakers data models remain unchanged; any new fields are additive and backward compatible.
- [x] Existing APIs and back-end entry points are either reused or extended without breaking changes.
- [x] ND, YF, TB, Δ and related derived metrics continue to be computed using existing logic; no change to financial semantics.
- [x] Money-moving operations (deposits/withdrawals) remain explicit actions and are not triggered via inline cell edits.
- [x] Existing balance history storage is reused; new views are layered on top of current data.
- [x] Role-based access is not introduced; flows remain suitable for a single-user app.
- [x] Bookmaker reassignment triggers a confirmation step when non-zero active balances exist, to avoid accidental misassignment.

## Risk Mitigation

- Primary Risk: Operator confusion during migration from multiple pages to the new hub.
  - Mitigation: Maintain a table-centric, inline-edit experience closely resembling Admin & Associates; add clear tab labels and contextual tooltips; optionally keep legacy pages behind a feature flag during transition.
- Risk: Accidental misconfiguration or reassignment of bookmakers with active balances.
  - Mitigation: Explicit confirmation dialog when reassigning bookmakers with non-zero balances; clear warnings about impact; undo/rollback support where feasible (e.g. reassign back, no data loss).
- Risk: Financial errors due to accidental edits on derived numeric fields.
  - Mitigation: Lock all derived numeric fields (ND, YF, TB, Δ) as read-only; use distinct visual styling and tooltips; confine money moves to explicit funding dialogs.
- Risk: Performance or usability regressions when aggregating data into a single page.
  - Mitigation: Reuse existing queries; paginate tables; lazy-load heavy views (e.g. charts) and maintain simple, fast filters.

## Definition of Done

- [ ] "Associates Hub" page exists with Management, Overview, and Balance History tabs; Management is the default tab.
- [ ] Management tab allows adding and editing associates and their bookmakers via table-centric, inline-edit flows, with clear separation between editable config fields and derived metrics.
- [ ] Overview tab surfaces ND/YF/TB/Δ per associate and supports quick financial actions (deposit/withdraw) and navigation back to Management.
- [ ] Balance History tab shows historical metrics with filters, charts, and `.xlsx` export, and supports deep linking from Management and Overview.
- [ ] Shared associate detail view and funding dialogs are implemented and reachable from both Management and Overview, with all money movements happening via explicit dialogs.
- [ ] All non-Telegram functionality from Admin & Associates and the Associate Operations Hub is available within the new tabs, with Telegram-related workflows explicitly excluded.
- [ ] No breaking changes to existing data models or business logic; derived metrics remain correct; money movements are explicit and traceable.

## Validation Checklist

**Scope Validation**
- [ ] Epic can be completed in 1–3 stories (as defined above).
- [ ] Enhancement relies on existing architecture and patterns (Streamlit tables, dialogs, existing metrics, and history).
- [ ] Integration complexity is manageable (mainly UI aggregation and reuse of existing data flows).
- [ ] Telegram-specific functionality is clearly out of scope and planned for a separate "Telegram Hub".

**Risk Assessment**
- [ ] Operator workflows for associate/bookmaker configuration are not degraded compared to current Admin & Associates.
- [ ] Money-moving operations remain explicit and auditable.
- [ ] Bookmaker reassignment with active balances is guarded by confirmation.
- [ ] Performance remains acceptable for typical associate/bookmaker counts.

**Completeness Check**
- [ ] Epic goal is clear and achievable with the defined stories.
- [ ] Stories cover Management, operational Overview, and historical Balance History views.
- [ ] Success criteria are measurable (e.g., ability to add/edit associates and bookmakers, perform deposits/withdrawals, navigate to history, export `.xlsx`).
- [ ] Dependencies and affected areas are identified (legacy pages, metrics pipeline, funding transactions, balance history).

## Story Manager Handoff

Please develop detailed user stories and dev tasks for this brownfield epic. Key considerations:

- Existing system:
  - Python + Streamlit UI, SQLite for data, existing Admin & Associates and Associate Operations Hub pages, current ND/YF/TB/Δ derivation, funding transactions, and balance history.
- Integration points:
  - New "Associates Hub" page with three tabs that consolidates and reorganizes existing non-Telegram functionality.
  - Reuse of existing tables, metrics, funding transaction logic, and history data, with UI refactoring and new flows for Management-first navigation.
- Patterns to follow:
  - Table-centric, inline-edit config for associates and bookmakers on the Management tab.
  - Derived metrics as read-only, visually distinct fields.
  - Explicit dialogs for any money-moving operations (no inline numeric edits).
  - Master–detail navigation, with shared associate selection across tabs and deep linking to Balance History.
- Compatibility and safety:
  - No new roles; single-user context, but financial actions must remain explicit.
  - Bookmaker reassignment confirmation when balances exist.
  - Balance History and any Management/History exports should use `.xlsx` where practical, consistent with existing XLSX direction in the app.

The epic should maintain and improve current operational capabilities while centralizing associate and bookmaker configuration into a single, safe, and intuitive "Associates Hub" experience.

