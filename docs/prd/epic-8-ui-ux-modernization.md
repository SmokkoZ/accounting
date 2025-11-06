# Epic 8: UI/UX Modernization (BMAD Format)

**Status:** Not Started  
**Priority:** P1 (Post‑MVP Enhancement)  
**Estimated Duration:** 6–9 days  
**Owner:** Frontend Lead  
**Phase:** 7 (Modernization & Performance)  
**PRD Reference:** Frontend v5.1 UI/UX Modernization

---

## Epic Goal

Modernize the Streamlit frontend to leverage v5.1+ features with a cohesive dark theme, modern interaction patterns, and **snappy performance on heavy datasets** via fragments, short‑TTL caching, pagination, thumbnailing, and DB indexes.

---

## Business Value

### Operator Benefits
- **Speed & Responsiveness:** Fast clicks, partial reruns, and smoother tables even with 10k+ rows
- **Clarity:** Consistent dark theme and reusable UI primitives improve readability
- **Confidence:** Modern dialogs, progress indicators, and streaming feedback reduce anxiety on long operations

### System Benefits
- **Maintainability:** Centralized caching/utils and reusable components reduce duplication
- **Scalability:** Pagination, indexes, and thumbnailing keep performance predictable as data grows
- **Compatibility:** Feature flags provide graceful degradation on older Streamlit versions

**Success Metric:** Median click‑to‑paint reduced on heavy pages; non‑data UI interactions avoid full reruns; qualitative UX feedback improves.

---

## Epic Description

This epic upgrades the UI/UX layer with: a global dark theme and styling primitives; modern navigation; dialogs and popovers; fragments for selective reruns; typed editors; streaming/progress components; feature‑flagged compatibility; workflow UX improvements; and systemic performance hardening (caching, pagination, thumbnails, DB indexes).

---

## Integration Points

**Upstream Dependencies**
- Existing Streamlit pages for ingestion, review, matching, reconciliation, statements
- SQLite schema and data access utilities

**Downstream Consumers**
- All operator workflows (ingestion → settlement → reconciliation → reporting)
- Admin/Diagnostics panels for feature flags and performance

---

## Stories

### Story 8.1: Foundation — Theme and Global Styling
**As a** system operator, **I want** a modern, consistent dark theme, **so that** the app feels professional and readable.

**Acceptance Criteria**
1. `.streamlit/config.toml` with dark theme and fonts
2. `src/ui/ui_styles.css` with cards, pills, toolbars, tables
3. `src/ui/ui_components.py` with `card()` and `metric_compact()` helpers
4. Global CSS is loaded on all pages
5. Replace deprecated `use_column_width` with `use_container_width=True`
6. Validate no functional regressions

---

### Story 8.2: Navigation Modernization
**As a** system operator, **I want** declarative navigation with `st.navigation` and `st.Page`, **so that** workflows are quick to access.

**Acceptance Criteria**
1. `src/ui/app.py` defines pages with `st.Page`
2. Fallback navigation for older Streamlit versions
3. Strategic `st.page_link` cross‑links
4. Icons and titles standardized
5. Works in dev/prod, preserves page functionality

---

### Story 8.3: Interaction Patterns — Dialogs and Popovers
**As a** system operator, **I want** confirmations and compact action menus, **so that** critical operations are safer and quicker.

**Acceptance Criteria**
1. `src/ui/helpers/dialogs.py` with `@st.dialog` wrappers
2. Settlement confirmation via dialog (replaces two‑click flow)
3. Canonical event creation dialog in incoming bets
4. Per‑row `st.popover` action menus in surebets/admin tables
5. Correction application dialog in reconciliation
6. Feature flags + fallbacks for older versions
7. All destructive actions require explicit confirmation

---

### Story 8.4: Performance — Fragments & Partial Reruns
**As a** system operator, **I want** selective reruns, **so that** tables/queues update without full page reloads.

**Acceptance Criteria**
1. `src/ui/helpers/fragments.py` with `@st.fragment` helpers
2. Incoming bets queue wrapped in fragment (optional auto‑refresh via flag)
3. Surebets table isolated in fragment (filters only re‑render table area)
4. Reconciliation associate cards and statements/exports isolated in fragments
5. Stable fragment state (no lost inputs)
6. Non‑data UI interactions must not trigger full reruns
7. Lightweight perf‑timer logging with on‑page debug toggle

---

### Story 8.5: Data Editing Modernization
**As a** system administrator, **I want** typed, validated editors, **so that** CRUD is intuitive and safe.

**Acceptance Criteria**
1. Associates: `st.data_editor` with `column_config`
2. Bookmakers: typed selects + validation
3. Master‑detail (bookmakers filtered by selected associate)
4. Bulk selection for associate deactivation
5. `num_rows="fixed"` where strict CRUD is required
6. Read‑only ID columns, disabled editing
7. Validate share percentages, currency codes, etc.

---

### Story 8.6: Streaming & Progress Indicators
**As a** system operator, **I want** visible progress/streaming, **so that** long jobs feel controlled.

**Acceptance Criteria**
1. `st.write_stream` for OCR progress in incoming bets
2. Export job progress with step‑by‑step logs
3. `st.status` for settlement/reconciliation
4. `st.toast` for success notifications
5. `st.pdf` previews for slips/statements
6. Robust error states + retries
7. Tested with varied data sizes

---

### Story 8.7: Feature Flags & Version Compatibility
**As a** system maintainer, **I want** feature detection and fallbacks, **so that** older versions degrade gracefully.

**Acceptance Criteria**
1. `src/ui/utils/feature_flags.py` for detection
2. Fallbacks for fragment/dialog/popover etc.
3. Version‑specific logic across the UI
4. Works on Streamlit 1.30+ baseline
5. Docs on minimum versions and degraded modes
6. Admin panel shows upgrade recommendations

---

### Story 8.8: UX Enhancements & Workflow Improvements
**As a** system operator, **I want** consistent patterns and recovery tools, **so that** I can work faster and fix mistakes quickly.

**Acceptance Criteria**
1. "Reset page state" helper
2. Advanced controls under `st.expander("Advanced")`
3. Use `st.form` to gate filter submissions and prevent mid‑typing reruns
4. Resolve‑events triage with confidence indicators + bulk actions
5. Timezone‑aware display (UTC storage, Perth local display)
6. Diagnostics under Admin → Advanced
7. All destructive flows have clear confirmations
8. Consistent UX across pages

---

### Story 8.9: Performance Hardening — Caching, Pagination, Thumbnails, DB Indexes
**As a** system operator, **I want** fast tables and light images, **so that** daily operations feel instant.

**Acceptance Criteria**
1. Centralized caching (`src/ui/cache.py`): `@st.cache_resource` for DB, `@st.cache_data(ttl=5)` wrapper `query_df(sql, params=())`
2. Pagination (25/50/100): `LIMIT/OFFSET`, total count, per‑table session state
3. Thumbnails (`src/ui/media.py`): `make_thumb(path, w=300)`; list views show thumbs, full images on demand
4. Form‑gated filters in incoming/verified/reconciliation pages
5. Rerun guardrails: `safe_rerun(reason)` helper; remove ad‑hoc reruns in render loops
6. Remove `sleep` and noisy logs from hot paths (flagged if needed)
7. SQLite indexes migration: `idx_bets_status_created`, `idx_surebets_status_created`, `idx_ledger_surebet`, `idx_ledger_created`; verify with `EXPLAIN`
8. Perf dashboard: Admin → Advanced shows last 50 timings; “UI Performance Playbook” docs
9. Benchmarks (non‑blocking): 10k bets → filter apply to first paint ≤ 1.5s; expanders/popovers feel instant

**Deliverables**
- `src/ui/cache.py`, `src/ui/media.py`, `src/ui/utils/perf.py`
- Index migration SQL, refactors on heavy pages
- Admin perf panel + short README section

---

## Technical Considerations

- Streamlit ≥ 1.46 recommended; fallbacks for ≥ 1.30 via feature flags  
- Caching uses short TTLs to balance freshness and speed  
- Thumbnailing assumes local image assets  
- UTC for storage; display in Australia/Perth for operator‑facing times

---

## Dependencies

- Streamlit application foundation (Epics 0–7)  
- Reconciliation/Statements pages for fragmentization and caching  
- `streamlit-pdf` for PDF previews

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Fragment state loss or unexpected reruns | Medium | Medium | State guards, fragment boundaries, integration tests |
| Pagination/caching inconsistencies | Medium | Medium | Single `query_df` entry‑point, cache bust on writes |
| Index migration mistakes | Low | High | Idempotent migrations, verify query plans with `EXPLAIN` |
| Older Streamlit versions | Medium | Low | Feature flags + documented fallbacks |
| Image processing overhead | Low | Medium | Cached thumbnails, background generation if needed |

---

## Testing Checklist

- [ ] Global theme/styles load on every page (no regressions)  
- [ ] Navigation via `st.navigation` works; links are consistent  
- [ ] Dialogs/popovers replace ad‑hoc confirms; all destructive ops confirmed  
- [ ] Fragments isolate heavy regions; non‑data UI avoids full reruns  
- [ ] Data editors enforce types/validation; IDs are read‑only  
- [ ] Streaming/progress visible for OCR/exports/settlement/reconciliation  
- [ ] Feature flags correctly degrade on Streamlit 1.30+  
- [ ] UX enhancements (forms, reset, advanced panels) applied consistently  
- [ ] Caching/pagination/thumbnails reduce render time; perf panel reports timings  
- [ ] Indexes exist and are used (checked with `EXPLAIN`)  

---

## Definition of Done

- All stories 8.1–8.9 acceptance criteria pass  
- Performance benchmarks observed on a 10k‑row dataset (non‑blocking thresholds met or documented gaps)  
- No full‑page reruns on non‑data interactions in heavy views  
- Admin perf dashboard and “UI Performance Playbook” documented  
- Feature flags clearly documented with minimum supported version and fallbacks

---

## Related Documents

- UI Performance Playbook (new, this epic)  
- Admin → Advanced (Feature Flags & Perf) panel notes  
- Reconciliation and Statements pages (fragmentization targets)

---

## Document Control

**Version:** v2.0 (BMAD‑aligned)  
**Date:** 2025-11-06 00:41:46Z  
**Author:** PO/Architect (BMAD)  
**Changes:** Reformatted Epic 8 to match BMAD epic structure and integrated acceptance criteria, dependencies, risks, DoD, and testing checklist.
