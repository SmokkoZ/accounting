# Epic 12: Signal Broadcaster & Styled Excel Exports - Brownfield Enhancement

## Epic Goal

Enable the operator to quickly broadcast raw surebet signals to chosen Telegram chats, and replace flat CSV exports with readable, styled Excel (.xlsx) files — without changing business logic or data.

## Epic Description

**Existing System Context**

- Current relevant functionality: Streamlit UI, Telegram bot for outbound messages, CSV exports for statements/reports, SQLite data with known chat mappings.
- Technology stack: Python, Streamlit, Telegram Bot API, SQLite, local-first app.
- Integration points: UI pages (new page for broadcasting), bot send routine (existing), export functions (replace CSV generation with XLSX).

**Enhancement Details**

- Signal Broadcaster page:
  - New Streamlit page to paste raw multi-line text and send as-is (same tabs/spaces/line breaks) to selected Telegram chats.
  - Chat multi-select supports search by associate/bookmaker and shows friendly labels (e.g., “Alice – SportsBet (AU)”).
  - Optional routing presets pre-fill typical chat combinations; selection remains editable.
  - Preview shows exactly what will be sent; Send posts to all selected chats and summarizes per-chat success/failure.

- Styled Excel exports:
  - Replace existing CSV downloads with .xlsx files that preserve current data/ordering but improve readability.
  - Apply bold, shaded header row; basic column width auto-fit; distinct positive/negative styling for deposits/withdrawals.
  - Ensure numeric columns are exported as numbers (not text) for easy summing/filtering in Excel.

## Stories

1. Story 1: Signal Broadcaster Page (paste → select chats/preset → preview → send)
   - Disabled Send if no text or no chats selected; helpful inline message.
   - Multi-select supports label search by associate/bookmaker; shows friendly labels.
   - Preview renders the exact outbound text (identical whitespace/tabs/line breaks).
   - Send posts the exact raw text via existing bot to each selected chat; no parsing or reformatting.
   - Success message includes count of chats; partial failures list which chats failed (label or ID).
   - No silent failures; errors visible in-page; operator can adjust and resend without reload.

2. Story 2: Replace CSV with Styled XLSX Exports
   - “Export CSV/Download CSV” becomes “Export Excel/Download Excel” and returns .xlsx files.
   - Columns/rows match current CSV content and ordering (unless refined later by design).
   - Header row is bold with a light background shade; basic column width adjustment for readability.
   - Deposits styled as positive (e.g., green tint/text); withdrawals as negative (e.g., red tint/text).
   - Numeric columns typed/formatted as numbers (not text); files open cleanly in Excel.
   - Export errors surface clear user feedback; no silent failure.

## Compatibility Requirements

- [x] Existing APIs remain unchanged
- [x] No database schema changes; semantics and labels only
- [x] UI changes follow existing Streamlit patterns (new page + button label updates)
- [x] Performance impact is minimal; reuse current data flows

## Risk Mitigation

- Primary Risk: Misrouting messages to unintended chats.
  - Mitigation: Explicit preview, friendly labels, and selection confirmation before send.
- Risk: Export styling could misclassify row types.
  - Mitigation: Style based on existing, deterministic transaction type fields; add test fixtures.
- Rollback Plan: Feature flag to hide the broadcaster page; retain CSV fallback behind a toggle if needed.

## Definition of Done

- [ ] Story 1 implemented and verified against acceptance criteria
- [ ] Story 2 implemented and verified against acceptance criteria
- [ ] No change to business logic or calculations
- [ ] Clear in-app success/error messages for both features
- [ ] Minimal documentation note added (new page location; exports now Excel)

## Validation Checklist

**Scope Validation**
- [x] Epic can be completed in 1–3 stories
- [x] No architectural documentation required
- [x] Enhancement follows existing patterns
- [x] Integration complexity manageable

**Risk Assessment**
- [x] Risk to existing system is low
- [x] Rollback plan is feasible
- [x] Testing approach covers broadcaster flows and export formatting
- [x] Team understands integration points (bot, UI, export functions)

**Completeness Check**
- [x] Epic goal is clear and achievable
- [x] Stories are properly scoped
- [x] Success criteria are measurable (per-chat send outcomes; Excel opens with styles/numerics)
- [x] Dependencies identified (bot config, chat mapping, export buttons)

## Story Manager Handoff

Please develop detailed user stories and dev tasks for this brownfield epic. Key considerations:

- Existing system: Python + Streamlit UI, Telegram bot already configured, SQLite with chat mappings; CSV exports in various pages.
- Integration points: new Streamlit page (broadcaster), existing bot send routine, export actions/buttons.
- Patterns to follow: reuse current UI conventions and export data pipelines; no schema or business-logic changes.
- Compatibility: one worksheet per export; preserve data fields/order; add basic styles and numeric typing.
- Verification: broadcaster sends exact raw text; Excel opens cleanly with headers styled and deposits/withdrawals colored; numeric columns behave as numbers.

