# Canonical Event Creation Architecture

This note captures how canonical events are created, matched, and persisted in the Surebet Accounting System. Use it when extending ingestion, verification, or schema migration features to avoid regressions like the missing `pair_key` column that previously broke event creation.

## High-Level Flow

1. **OCR / Manual Input** produces a normalized event name.
2. **UI actions** (Streamlit: `src/ui/components/bet_card.py`, pages `1_incoming_bets.py`, `2_verified_bets.py`) let an operator approve a bet or open the _Create Event_ dialog.
3. **BetVerificationService** (`src/services/bet_verification.py`) receives the request and:
   - Normalizes the event label with `EventNormalizer`.
   - Attempts to match an existing canonical event by `pair_key`, normalized name, sport, and optional kickoff time.
   - Inserts a new row into `canonical_events` if no match is found.
4. **Database layer** (`src/core/database.py` + `src/core/schema.py`) ensures the schema is current (adds columns like `team*_slug` and `pair_key`) and writes the event to SQLite.
5. **Bet ingestion** (`src/services/bet_ingestion.py`) reuses the same service for automated OCR-triggered creation when confidence exceeds the configured threshold.

## Key Modules & Responsibilities

| File | Purpose |
| --- | --- |
| `src/core/database.py` | Creates SQLite connections and now guarantees that `create_schema()` runs once per process so new columns exist before business logic executes. |
| `src/core/schema.py` | Defines `canonical_events` schema, including backfill logic (`PRAGMA table_info` + `ALTER TABLE`) and indexes on `(sport, pair_key)` and names. |
| `src/services/event_normalizer.py` | Normalizes raw event strings, strips diacritics, computes team slugs, builds lexicographically sorted `pair_key`s, and loads alias overrides from `data/team_aliases.json`. |
| `src/services/bet_verification.py` | Core service for matching/creating canonical events. Provides `_create_canonical_event` (strict) and `_create_canonical_event_relaxed` (kickoff optional). Also exposes `get_or_create_canonical_event` for higher-level workflows. |
| `src/services/bet_ingestion.py` | Calls `BetVerificationService.get_or_create_canonical_event` during automated OCR ingestion. |
| `src/ui/components/bet_card.py` | Dialog and buttons that trigger event creation from the operator UI. |
| `src/core/schema_validation.py` | Validation helper ensuring `canonical_events` has expected columns if you want a hard check in migrations or scripts. |

## Detailed Create Path

1. **Normalization**
   - `EventNormalizer.normalize_event_name(raw_name, sport)` standardizes input (trim, lowercase, alias substitution, canonical "vs" separator).
   - `EventNormalizer.compute_pair_key(normalized_name)` returns `(team1_slug, team2_slug, pair_key)` with lexicographically sorted slugs to make lookups deterministic.

2. **Lookup** (`BetVerificationService.get_or_create_canonical_event`)
   - Immediate `pair_key` lookup: `SELECT id FROM canonical_events WHERE sport = ? AND pair_key = ? ORDER BY id DESC LIMIT 1`.
   - Relaxed normalized-name search (case-insensitive) if kickoff is missing/invalid.
   - Fuzzy matching fallback that compares similarity for events in the same sport and near the provided kickoff timestamp.
   - Final fallback: create a new canonical event.

3. **Insert** (`_create_canonical_event` / `_create_canonical_event_relaxed`)
   - Validates event name length, sport membership (`football`, `tennis`, `basketball`, `cricket`, `rugby`), optional competition length, and kickoff ISO-8601 format (strict variant only).
   - Inserts into `canonical_events` with normalized names, slugs, `pair_key`, and timestamp fields.
   - Logs success via `structlog` for observability.

4. **Persistence Guarantees**
   - `create_schema(conn)` defines the table with `pair_key TEXT` and creates indexes.
   - Backfill logic runs every time schema is created to add missing columns (e.g., when upgrading an existing DB). Ensuring `create_schema()` is invoked on connection prevents the “no such column: pair_key” regression.

## Team Alias Dataset (`data/team_aliases.json`)

- **Location**: `data/team_aliases.json`
- **Why it matters**: OCR output and bookmaker feeds often return inconsistent club names (for example, `"Arsenal SarandA-"`, `"1. fc kA¼ln"`). The alias map rewrites them to canonical forms so slug generation and `pair_key` matching stay deterministic.
- **Loading**: `EventNormalizer.load_aliases()` reads the file lazily, normalizes keys/values to lowercase ASCII, merges them with a small built-in alias set, caches the result, and reuses it for all subsequent normalization calls.
- **Maintenance**:
  - Keep the JSON valid and entries lowercase; the loader lowercases and strips diacritics before comparison.
  - Restart the backend (or manually reset `EventNormalizer._alias_cache`) after editing the file so changes take effect.
  - Treat the file as part of the deployable artifact. If it is deleted or corrupted, only the minimal built-in aliases remain, degrading match accuracy.
- **Version control**: Commit updates alongside code that depends on them and document notable additions when they affect matching behavior.

## Edge Cases & Guardrails

- **Schema drift**: Always acquire DB connections through `get_db_connection()`. Bypassing it skips the automatic schema ensure and risks missing columns or indexes.
- **Team parsing failures**: If normalization cannot split into two teams, `pair_key` becomes `None`. The service still inserts the event, but matching on pair key will be impossible. Investigate aliases if this happens frequently.
- **Kickoff validation**: Strict creation rejects timestamps missing the trailing `Z`. Use `_create_canonical_event_relaxed` (UI modal when kickoff unknown) to bypass the check safely.
- **Sport validation**: The allowed sports list is hard-coded. Adding a new sport requires updating both the UI options and validation arrays in `BetVerificationService`.
- **Re-running migrations**: `create_schema` prints “Database schema created successfully” every time. That makes sense in development but can be noisy in production logs—consider swapping to logging if needed.

## Recommended Checks After Changes

1. **Schema verification**: `python -c "import sqlite3; conn = sqlite3.connect('data/surebet.db'); print([row[1] for row in conn.execute('PRAGMA table_info(canonical_events)')])"` should list `pair_key`.
2. **Service smoke test**: `BetVerificationService._create_canonical_event` should succeed and produce a non-null `pair_key` for standard “Team A vs Team B” inputs.
3. **UI regression**: Approving a bet or using the “Create Event” modal should create events without raising `no such column` errors in logs.
4. **Seed re-run**: `initialize_database()` can be executed safely on a fresh DB to confirm schema + seed scripts stay compatible after changes.

## Future Enhancements to Consider

- Wrap schema validation (`schema_validation.validate_schema`) into an optional startup health check.
- Implement migrations (e.g., via Alembic) if schema changes become more complex than additive columns.
- Extend the `EventNormalizer` alias dataset for ambiguous team names, especially outside football.
- Add unit tests covering pair-key matching and creation flows to prevent accidental regressions when updating the service.

Use this document as a checklist whenever you modify canonical event logic, and update it if new flows (e.g., API-based ingestion) reuse the same primitives.
