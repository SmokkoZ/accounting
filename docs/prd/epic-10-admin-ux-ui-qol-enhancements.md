# Epic 10: Admin UX/UI & QoL Enhancements (Consolidate 9.4, 9.5, 9.6, 9.7 outcomes)

**Status:** Not Started
**Priority:** P1 (Operator Experience)
**Estimated Duration:** 3 weeks
**Owner:** Product Owner (Sarah)
**Phase:** 2 (Operations Enhancements)
**PRD Reference:** FR-12 (Telegram & Operations Dashboard)

---

## Epic Goal
Improve triage speed, clarity, and safety for the solo operator by refining navigation, Telegram oversight, triage workflows, rate-limit visibility, persistent UI preferences, and the Admin & Associates financial surfaces, aligning this work with the goals captured in `docs/front-end-spec.md:1`.

## Business Value
- Median triage time per bet stays below 10 seconds while preserving a deterministic, audited approval flow.
- Zero silent messaging; every Telegram delivery is operator-initiated and logged.
- Faster navigation, fewer misclicks, and shortcut-driven actions with measurable telemetry around the renamed Settlement flow and new help overlay.

## Epic Description
We consolidate the investments from Stories 9.4-9.9 into a single admin-facing epic:
1. Telegram oversight extends every `pending_photos` flow with TTL countdowns, force-ingest tooling, and a Coverage Proof outbox tied directly to `src/integrations/telegram_bot.py:1947-2209` and `src/services/coverage_proof_service.py:47`.
2. Incoming Bets triage gets compact mode, auto-refresh defaults, confidence rationale tooltips, and saved view persistence leveraging `src/ui/pages/1_incoming_bets.py:494,670`, `src/ui/components/bet_card.py:125,367`, and `src/ui/utils/feature_flags.py:89`.
3. Navigation shifts the Verified Bets Queue to "Settlement", surfaces a dedicated Telegram section, and refreshes the Admin & Associates listings to show live balances, pending exposure, and aggregate deposits per bookmaker (Story 9.8) via `src/repositories/associate_hub_repository.py:70` while introducing quick action panels, contextual menus, and shortcut reminders so the Associate Operations Hub can reach critical flows in one click.
4. Developer-visible rate-limiting settings and a real dashboard replace demo metrics at `src/ui/pages/0_dashboard.py:26`, adding high-visibility action buttons for sends that impact operations (global Telegram statements, FX rate refresh, etc.) while surfacing coverage proof thresholds from `src/services/coverage_proof_service.py:520`.
5. Ledger stake timing and statement math (Story 9.9) move stake capture to verification/matching, remove the implicit admin share so profits/losses split strictly across associates, and update statements to show per-associate deposits, withdrawals, bookmaker balances, and deltas so the operator can compute their own share offline.

## Stories
1. Story 10.1: Telegram Pending Photos Oversight
2. Story 10.2: Coverage Proof Outbox & Resend
3. Story 10.3: Incoming Bets Compact Mode
4. Story 10.4: Auto-refresh Default On
5. Story 10.5: Confidence Rationale Tooltip
6. Story 10.6: Navigation Rename & Telegram Section
7. Story 10.7: Keyboard Shortcuts + Help Overlay
8. Story 10.8: Saved Views & URL State
9. Story 10.9: Rate Limiting Settings UI
10. Story 10.10: Dashboard Real Metrics
11. Story 9.8: Ledger Stake Placement Refactor & Statement Rollup
12. Story 9.9: Admin Bookmaker Financial Columns


## Non-Functional Requirements
- Accessibility: Maintain AA contrast, keyboard navigation, tooltips, and toasts that work with screen readers.
- Observability: Every Telegram send or override logs operator, chat_id, message_id, and rate-limit state.
- Reliability: Auto refresh uses fragments only when supported to avoid spinner thrash; coverage proof rate-limit UI prevents bursts.
- Performance: Dashboard tiles refresh within one minute for waiting/approved counts with zero layout thrash.

## Risks & Mitigations
- Telegram API bursts: surface rate-limit metadata and disable resend until the service clock allows (see `src/services/coverage_proof_service.py:520`).
- Layout regressions: auto-refresh and compact mode reuse existing `render_bet_card` spacing to avoid visual drift.
- Hotkey collisions: disable shortcuts when inputs are focused, following the pattern in `src/ui/pages/8_associate_operations.py:477`.
- Legacy AssociateHub queries: move from JSON profile/created/updated columns to `balance`, `pending_balance`, and deposit totals so dashboards align with the new metrics, referencing `src/repositories/associate_hub_repository.py:70`.
- Settlement math regression: stake-at-placement plus “associate-only” profit splits must not double-count or omit ledger entries; follow `src/services/ledger_entry_service.py` coverage and gate behind a feature flag.

## Dependencies
- `docs/front-end-spec.md:1` for UX goals and navigation inventory.
- `src/core/schema.py:275` for `pending_photos` semantics.
- `src/integrations/telegram_bot.py:1947-2209` for TTL, auto-discard, and confirmation flows.
- `src/services/coverage_proof_service.py:47,520` for logging, resend, and rate-limit state.
- `src/repositories/associate_hub_repository.py:70` for scoreboard data plus the balance/pending/deposit columns.
- `src/services/ledger_entry_service.py`, `src/services/settlement_service.py`, `src/services/surebet_calculator.py`, and statements under `src/ui/pages/6_reconciliation.py` for stake-at-placement and associate-only allocations.
- `tests/unit/test_navigation_modernization.py:1`, `tests/unit/test_media_thumbnails.py:1`, and `tests/integration/test_telegram_approval_workflow.py:1` for regression coverage.

## Out of Scope
- PDF redesign or asynchronous statement exports.
- Retrofitting historical bets with stake entries (only new bets participate in the stake-at-placement rollout).
