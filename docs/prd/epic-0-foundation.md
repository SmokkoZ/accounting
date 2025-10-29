# Epic 0: Foundation & Infrastructure

**Status:** Not Started
**Priority:** P0 (Blocker for all other epics)
**Estimated Duration:** 3-5 days
**Owner:** Tech Lead
**Phase:** 0 (Foundation)

---

## Epic Goal

Establish the technical foundation and infrastructure required for the Surebet Accounting System, including project setup, database schema, core utilities, and Telegram bot scaffold. This epic creates the baseline that all subsequent features will build upon.

---

## Business Value

This epic delivers zero end-user functionality but is **critical infrastructure** that:
- Enables all future development by providing stable foundation
- Enforces System Laws (append-only ledger, frozen FX, Decimal precision)
- Validates technology stack choices before feature development begins
- Reduces risk of architecture changes mid-project

**Success Metric**: All Phase 1+ developers can start work without environmental blockers.

---

## Epic Description

### Context

This is a **greenfield project** building a local-first accounting system from scratch. Before implementing any features, we must establish:
- Development environment and project structure
- Database schema with all 11 core tables
- Currency conversion system with frozen snapshots
- Telegram bot infrastructure for screenshot ingestion

### What's Being Built

Four foundational components:

1. **Project Setup** (Story 0.1)
   - Python 3.12 environment with dependencies
   - Streamlit application scaffold
   - Folder structure for data, screenshots, exports
   - Version control and documentation

2. **Core Data Model** (Story 0.2)
   - SQLite database with WAL mode
   - All 11 tables per PRD schema
   - Seed data for testing (2 associates, 4 bookmakers)
   - Schema validation

3. **FX Rate System** (Story 0.3)
   - Currency → EUR conversion with Decimal precision
   - Daily rate caching in `fx_rates_daily`
   - Snapshot utilities for ledger entries
   - UTC timestamp handling

4. **Telegram Bot Scaffold** (Story 0.4)
   - Bot connection with polling mode
   - Chat ID registration
   - Screenshot receipt handler (no OCR yet)
   - Basic command handlers

### System Laws Enforced

This epic establishes enforcement of:
- **Law #1**: Append-only ledger (schema constraints prevent UPDATE/DELETE)
- **Law #2**: Frozen FX snapshots (utility functions enforce snapshot storage)
- All currency math in Decimal (no float)
- All timestamps in UTC ISO8601 with "Z"

---

## Stories

### Story 0.1: Project Setup & Scaffolding

**As a developer**, I want a working development environment so I can begin implementing features.

**Acceptance Criteria:**
- [ ] Python 3.12 virtual environment created
- [ ] `requirements.txt` with core dependencies:
  - `streamlit>=1.28.0`
  - `python-telegram-bot>=20.0`
  - `sqlite3` (built-in)
  - `openai>=1.0.0` (for future OCR)
  - `python-dotenv` (for API keys)
- [ ] Folder structure created:
  - `data/` (SQLite DB location)
  - `data/screenshots/` (bet screenshots)
  - `data/exports/` (CSV exports)
  - `docs/` (PRD, architecture)
  - `src/` or app root (Python modules)
- [ ] `app.py` Streamlit scaffold runs at `localhost:8501`
- [ ] `.gitignore` excludes `data/`, `.env`, `__pycache__`
- [ ] `README.md` with setup instructions
- [ ] `.env.example` template for API keys

**Technical Notes:**
- Use `venv` or `conda` for isolation
- Pin dependency versions for reproducibility
- Streamlit config: `st.set_page_config(layout="wide")`

---

### Story 0.2: Core Database Schema

**As the system**, I want all 11 core tables created with proper constraints so data integrity is enforced.

**Acceptance Criteria:**
- [ ] SQLite database created at `data/surebet.db` with WAL mode enabled
- [ ] Schema script (`schema.sql` or Python migration) creates tables:
  - `associates` (trusted partners including admin)
  - `bookmakers` (accounts per associate)
  - `canonical_events` (normalized sporting events)
  - `canonical_markets` (market type definitions)
  - `bets` (individual bet records with status state machine)
  - `surebets` (grouped opposing bets)
  - `surebet_bets` (junction table with side assignment)
  - `ledger_entries` (append-only financial ledger)
  - `verification_audit` (bet approval history)
  - `multibook_message_log` (coverage proof delivery)
  - `bookmaker_balance_checks` (associate-reported balances)
  - `fx_rates_daily` (currency conversion cache)
- [ ] Key constraints enforced:
  - `ledger_entries` has NO UPDATE/DELETE triggers (append-only enforced)
  - `surebet_bets.side` immutable after INSERT
  - All currency fields stored as TEXT (Decimal serialization)
  - All timestamps stored as TEXT in ISO8601 format with "Z"
- [ ] Seed data inserted:
  - 2 associates: "Admin" (you) and "Partner A"
  - 4 bookmakers: 2 per associate (e.g., Bet365, Pinnacle)
  - 2 canonical markets: "TOTAL_GOALS_OVER_UNDER", "ASIAN_HANDICAP"
- [ ] Schema validation script confirms all tables exist with correct columns

**Technical Notes:**
- Use `PRAGMA journal_mode=WAL` for SQLite
- Reference PRD "Data Model" section for full schema
- Consider using SQLAlchemy ORM vs. raw SQL (document choice)

---

### Story 0.3: FX Rate System

**As the system**, I want a currency conversion system that caches rates and freezes snapshots for ledger entries.

**Acceptance Criteria:**
- [ ] `fx_rates_daily` table populated with sample rates:
  - EUR (base): 1.0
  - AUD: 0.60
  - GBP: 1.15
  - USD: 0.92
  - Date: today (UTC)
- [ ] Utility function: `get_fx_rate(currency: str, date: date) -> Decimal`
  - Returns rate for currency on date
  - If no rate exists for date, returns last known rate with warning
  - Raises error if no rate ever exists for currency
- [ ] Utility function: `convert_to_eur(amount: Decimal, currency: str, fx_rate: Decimal) -> Decimal`
  - Converts native currency to EUR using provided snapshot rate
  - Returns Decimal with 2 decimal places
  - Formula: `amount * fx_rate`
- [ ] Utility function: `format_timestamp_utc() -> str`
  - Returns current timestamp as ISO8601 with "Z" (e.g., "2025-10-29T14:30:00Z")
- [ ] All functions use `Decimal` from Python stdlib (no float)
- [ ] Unit tests verify:
  - Decimal precision (no rounding errors)
  - Snapshot immutability (old rates preserved)
  - Fallback to last known rate

**Technical Notes:**
- Store Decimal as TEXT using `str(decimal_value)`
- Load from TEXT using `Decimal(text_value)`
- Future: Add API integration for live rates (not MVP)

---

### Story 0.4: Telegram Bot Scaffold

**As the operator**, I want the Telegram bot to receive screenshots and save them locally so I can begin testing ingestion.

**Acceptance Criteria:**
- [ ] Telegram bot token stored in `.env` as `TELEGRAM_BOT_TOKEN`
- [ ] Bot runs in polling mode (not webhook) using `python-telegram-bot` v20+
- [ ] Bot handles `/start` command: replies "Surebet Bot Ready"
- [ ] Bot handles `/help` command: lists available commands
- [ ] Bot registers bookmaker chat IDs (manual config or `/register` command)
- [ ] Bot handles photo messages:
  - Saves screenshot to `data/screenshots/{timestamp}_{chat_id}.png`
  - Creates placeholder `bets` row with:
    - `status="incoming"`
    - `ingestion_source="telegram"`
    - `telegram_message_id=<message_id>`
    - `associate_id`, `bookmaker_id` (looked up via chat_id)
    - All extracted fields NULL (OCR added in Phase 1)
  - Replies to sender: "Screenshot received. Awaiting OCR processing."
- [ ] Bot logs all errors to console
- [ ] Bot can be stopped gracefully with Ctrl+C

**Technical Notes:**
- Use `ApplicationBuilder().token(TOKEN).build()` pattern
- Map chat IDs to (associate, bookmaker) pairs in config file or DB table
- No OCR/AI in this story - just file save and DB placeholder
- Reference: https://docs.python-telegram-bot.org/

---

## Dependencies

### Upstream
None - this is the foundation epic.

### Downstream
All subsequent epics (1-6) depend on Phase 0 completion:
- **Epic 1** (Bet Ingestion) requires: Stories 0.2, 0.4
- **Epic 2** (Bet Review) requires: Story 0.2
- **Epic 3** (Surebet Matching) requires: Stories 0.2, 0.3
- **Epic 4** (Settlement) requires: Stories 0.2, 0.3
- **Epic 5** (Reconciliation) requires: Stories 0.2, 0.3
- **Epic 6** (Reporting) requires: Stories 0.2, 0.3

---

## Technical Considerations

### Technology Stack Validation

This epic validates the chosen stack:
- **Python 3.12**: Confirm available on accountant machine
- **Streamlit**: Confirm runs on localhost (no cloud deployment)
- **SQLite**: Confirm WAL mode works on Windows/Mac/Linux
- **Telegram Bot**: Confirm polling mode works (no webhook server needed)

If any technology fails validation, escalate immediately.

### Performance Baseline

Establish performance expectations:
- Database queries: <100ms for single-table reads
- Streamlit page load: <2s for empty pages
- Telegram bot: <5s screenshot receipt-to-save
- FX conversion: <10ms per calculation

### Security Considerations

- [ ] `.env` file excluded from git (API keys protected)
- [ ] Database file (`data/surebet.db`) excluded from git
- [ ] Screenshot folder (`data/screenshots/`) excluded from git
- [ ] Telegram bot token rotatable without code changes

---

## Definition of Done

Phase 0 is complete when ALL of the following are verified:

### Functional Validation
- [ ] All 4 stories (0.1-0.4) marked complete
- [ ] Streamlit app loads without errors at `localhost:8501`
- [ ] Database contains all 11 tables with seed data
- [ ] FX conversion utilities work with Decimal precision
- [ ] Telegram bot receives screenshots and saves to disk

### Technical Validation
- [ ] Schema validation script passes
- [ ] Unit tests for FX utilities pass
- [ ] Database file size <1MB (seed data only)
- [ ] No Python warnings or errors on startup
- [ ] `requirements.txt` pinned versions install cleanly

### Handoff Readiness
- [ ] README.md setup instructions work for new developer
- [ ] `.env.example` documents all required API keys
- [ ] Sample screenshot successfully saved via Telegram
- [ ] Phase 1 team can begin work immediately

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| SQLite WAL mode unsupported on target OS | Low | High | Test on accountant machine in first day; fallback to DELETE mode if needed |
| Telegram bot token rejected/banned | Low | High | Use test bot initially; whitelist approved chats only |
| Decimal precision issues | Medium | High | Unit test all FX calculations; verify no float conversion |
| Python 3.12 unavailable | Low | Medium | Document minimum Python 3.10; avoid 3.12-specific features |

---

## Success Metrics

### Completion Criteria
- All 4 stories delivered with passing acceptance criteria
- Phase 0 "Definition of Done" checklist 100% complete
- Zero blockers for Phase 1 team

### Quality Metrics
- Zero database schema errors
- Zero Decimal → float conversion bugs
- 100% of Telegram screenshots successfully saved

---

## Related Documents

- [PRD: Surebet Accounting System](../prd.md)
- [PRD: Data Model](../prd/data-model.md) *(if exists)*
- [Architecture: Tech Stack](../architecture/tech-stack.md)
- [Implementation Roadmap](./implementation-roadmap.md)

---

## Notes

### Why Foundation Matters

While this epic delivers zero user features, it is the **most critical phase** for project success:

1. **Enforces System Laws**: Append-only ledger and frozen FX are architectural decisions that cannot be retrofitted
2. **Prevents Rework**: Getting schema right now avoids costly migrations later
3. **Establishes Patterns**: Decimal precision and UTC timestamps set project-wide standards
4. **De-risks Technology**: Validates Streamlit + SQLite + Telegram stack before heavy investment

**Do not skip or rush Phase 0.** Every hour invested here saves 10 hours in later phases.

---

**End of Epic**
