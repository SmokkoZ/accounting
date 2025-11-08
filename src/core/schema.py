"""
Database schema definition for the Surebet Accounting System.

This module defines all 12 core tables with proper constraints and indexes.
"""

import sqlite3
from typing import List, Set


def create_schema(conn: sqlite3.Connection) -> None:
    """
    Create all database tables with proper constraints and indexes.

    Args:
        conn: SQLite database connection.
    """
    # Create tables in dependency order
    create_associates_table(conn)
    create_bookmakers_table(conn)
    create_canonical_events_table(conn)
    create_canonical_markets_table(conn)
    create_bets_table(conn)
    create_extraction_log_table(conn)
    create_surebets_table(conn)
    create_surebet_bets_table(conn)
    create_surebet_settlement_links_table(conn)
    create_ledger_entries_table(conn)
    create_verification_audit_table(conn)
    create_multibook_message_log_table(conn)
    create_bookmaker_balance_checks_table(conn)
    create_fx_rates_daily_table(conn)
    create_chat_registrations_table(conn)
    create_funding_drafts_table(conn)
    create_notification_audit_table(conn)

    # Create triggers for data integrity
    create_ledger_append_only_trigger(conn)
    create_surebet_bets_side_immutable_trigger(conn)

    print("Database schema created successfully")


def create_associates_table(conn: sqlite3.Connection) -> None:
    """Create the associates table."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS associates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            display_alias TEXT NOT NULL UNIQUE,
            home_currency TEXT NOT NULL DEFAULT 'EUR',
            multibook_chat_id TEXT,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            is_admin BOOLEAN NOT NULL DEFAULT FALSE,
            created_at_utc TEXT NOT NULL DEFAULT (datetime('now') || 'Z'),
            updated_at_utc TEXT NOT NULL DEFAULT (datetime('now') || 'Z')
        )
    """
    )

    # Index for quick lookup by alias
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_associates_display_alias 
        ON associates(display_alias)
    """
    )

    # Backfill is_active column for existing databases
    cursor = conn.execute("PRAGMA table_info(associates)")
    column_names = {row[1] for row in cursor.fetchall()}
    if "is_active" not in column_names:
        conn.execute(
            "ALTER TABLE associates ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE"
        )


def create_bookmakers_table(conn: sqlite3.Connection) -> None:
    """Create the bookmakers table."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bookmakers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            associate_id INTEGER NOT NULL,
            bookmaker_name TEXT NOT NULL,
            parsing_profile TEXT,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at_utc TEXT NOT NULL DEFAULT (datetime('now') || 'Z'),
            updated_at_utc TEXT NOT NULL DEFAULT (datetime('now') || 'Z'),
            FOREIGN KEY (associate_id) REFERENCES associates(id) ON DELETE CASCADE,
            UNIQUE(associate_id, bookmaker_name)
        )
    """
    )

    # Index for quick lookup by associate
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_bookmakers_associate_id 
        ON bookmakers(associate_id)
    """
    )


def create_canonical_events_table(conn: sqlite3.Connection) -> None:
    """Create the canonical_events table."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS canonical_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            normalized_event_name TEXT NOT NULL,
            league TEXT,
            sport TEXT,
            team1_slug TEXT,
            team2_slug TEXT,
            pair_key TEXT,
            kickoff_time_utc TEXT,
            created_at_utc TEXT NOT NULL DEFAULT (datetime('now') || 'Z'),
            updated_at_utc TEXT NOT NULL DEFAULT (datetime('now') || 'Z')
        )
    """
    )

    # Index for event lookup
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_canonical_events_name 
        ON canonical_events(normalized_event_name)
    """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_canonical_events_kickoff 
        ON canonical_events(kickoff_time_utc)
    """
    )

    # Backfill columns for existing databases (ALTER TABLE adds if missing)
    cursor = conn.execute("PRAGMA table_info(canonical_events)")
    existing = {row[1] for row in cursor.fetchall()}
    to_add = []
    if "team1_slug" not in existing:
        to_add.append(("team1_slug", "TEXT"))
    if "team2_slug" not in existing:
        to_add.append(("team2_slug", "TEXT"))
    if "pair_key" not in existing:
        to_add.append(("pair_key", "TEXT"))
    for col, typ in to_add:
        conn.execute(f"ALTER TABLE canonical_events ADD COLUMN {col} {typ}")

    # Pair key index for normalized event matching
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_canonical_events_pair_key
        ON canonical_events(sport, pair_key)
        """
    )


def create_canonical_markets_table(conn: sqlite3.Connection) -> None:
    """Create the canonical_markets table."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS canonical_markets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market_code TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL,
            created_at_utc TEXT NOT NULL DEFAULT (datetime('now') || 'Z')
        )
    """
    )


def create_bets_table(conn: sqlite3.Connection) -> None:
    """Create the bets table."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            associate_id INTEGER NOT NULL,
            bookmaker_id INTEGER NOT NULL,
            canonical_event_id INTEGER,
            canonical_market_id INTEGER,
            event_id INTEGER,
            market_type TEXT,
            selection TEXT,
            status TEXT NOT NULL DEFAULT 'incoming',
            resolve_status TEXT NOT NULL DEFAULT 'needs_review',
            stake_eur TEXT DEFAULT '0.00',
            stake_amount TEXT,
            stake_currency TEXT,
            odds TEXT NOT NULL,
            currency TEXT NOT NULL DEFAULT 'EUR',
            fx_rate_to_eur TEXT DEFAULT '1.0',
            stake_original TEXT,
            odds_original TEXT,
            payout TEXT,
            confidence_score REAL DEFAULT 0.0,
            selection_text TEXT,
            market_code TEXT,
            period_scope TEXT,
            line_value TEXT,
            side TEXT,
            kickoff_time_utc TEXT,
            screenshot_path TEXT,
            telegram_message_id TEXT,
            ingestion_source TEXT NOT NULL DEFAULT 'manual_upload',
            ocr_confidence REAL DEFAULT 0.0,
            normalization_confidence TEXT,
            is_multi BOOLEAN NOT NULL DEFAULT FALSE,
            is_supported BOOLEAN NOT NULL DEFAULT TRUE,
            model_version_extraction TEXT,
            model_version_normalization TEXT,
            created_at_utc TEXT NOT NULL DEFAULT (datetime('now') || 'Z'),
            updated_at_utc TEXT NOT NULL DEFAULT (datetime('now') || 'Z'),
            FOREIGN KEY (associate_id) REFERENCES associates(id),
            FOREIGN KEY (bookmaker_id) REFERENCES bookmakers(id),
            FOREIGN KEY (canonical_event_id) REFERENCES canonical_events(id),
            FOREIGN KEY (canonical_market_id) REFERENCES canonical_markets(id),
            CHECK (status IN ('incoming', 'verified', 'matched', 'settled', 'rejected')),
            CHECK (ingestion_source IN ('telegram', 'manual_upload'))
        )
    """
    )

    # Indexes for common queries
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_bets_status 
        ON bets(status)
    """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_bets_associate_id 
        ON bets(associate_id)
    """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_bets_canonical_event_id
        ON bets(canonical_event_id)
    """
    )

    # Ensure resolve_status column exists for older databases
    cursor = conn.execute("PRAGMA table_info(bets)")
    existing_columns = {row[1] for row in cursor.fetchall()}
    if "resolve_status" not in existing_columns:
        conn.execute(
            "ALTER TABLE bets ADD COLUMN resolve_status TEXT NOT NULL DEFAULT 'needs_review'"
        )
    if "confidence_score" not in existing_columns:
        conn.execute(
            "ALTER TABLE bets ADD COLUMN confidence_score REAL DEFAULT 0.0"
        )


def create_extraction_log_table(conn: sqlite3.Connection) -> None:
    """Create the extraction_log table for OCR/AI extraction audit trail."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS extraction_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bet_id INTEGER NOT NULL,
            model_version TEXT NOT NULL,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            total_tokens INTEGER,
            extraction_duration_ms INTEGER,
            confidence_score TEXT,
            raw_response TEXT,
            error_message TEXT,
            created_at_utc TEXT NOT NULL DEFAULT (datetime('now') || 'Z'),
            FOREIGN KEY (bet_id) REFERENCES bets(id) ON DELETE CASCADE
        )
    """
    )

    # Index for bet lookup
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_extraction_log_bet_id
        ON extraction_log(bet_id)
    """
    )


def create_surebets_table(conn: sqlite3.Connection) -> None:
    """Create the surebets table."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS surebets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_event_id INTEGER,
            canonical_market_id INTEGER,
            market_code TEXT,
            period_scope TEXT,
            line_value TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            total_stake_eur TEXT,
            expected_profit_eur TEXT,
            actual_profit_eur TEXT,
            settled_at_utc TEXT,
            worst_case_profit_eur TEXT,
            total_staked_eur TEXT,
            roi TEXT,
            risk_classification TEXT,
            coverage_proof_sent_at_utc TEXT,
            created_at_utc TEXT NOT NULL DEFAULT (datetime('now') || 'Z'),
            updated_at_utc TEXT NOT NULL DEFAULT (datetime('now') || 'Z'),
            FOREIGN KEY (canonical_event_id) REFERENCES canonical_events(id),
            FOREIGN KEY (canonical_market_id) REFERENCES canonical_markets(id),
            CHECK (status IN ('open', 'matched', 'settled', 'cancelled'))
        )
    """
    )

    # Index for status lookup
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_surebets_status
        ON surebets(status)
    """
    )

    # Backfill coverage_proof_sent_at_utc column for existing databases
    cursor = conn.execute("PRAGMA table_info(surebets)")
    existing = {row[1] for row in cursor.fetchall()}
    if "coverage_proof_sent_at_utc" not in existing:
        conn.execute("ALTER TABLE surebets ADD COLUMN coverage_proof_sent_at_utc TEXT")


def create_surebet_bets_table(conn: sqlite3.Connection) -> None:
    """Create the surebet_bets junction table."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS surebet_bets (
            surebet_id INTEGER NOT NULL,
            bet_id INTEGER NOT NULL,
            side TEXT DEFAULT 'A',
            created_at_utc TEXT NOT NULL DEFAULT (datetime('now') || 'Z'),
            PRIMARY KEY (surebet_id, bet_id),
            FOREIGN KEY (surebet_id) REFERENCES surebets(id) ON DELETE CASCADE,
            FOREIGN KEY (bet_id) REFERENCES bets(id) ON DELETE CASCADE,
            CHECK (side IN ('A', 'B'))
        )
    """
    )


def create_surebet_settlement_links_table(conn: sqlite3.Connection) -> None:
    """Create the surebet_settlement_links table for delta provenance tracking."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS surebet_settlement_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            surebet_id INTEGER NOT NULL,
            winner_associate_id INTEGER NOT NULL,
            loser_associate_id INTEGER NOT NULL,
            amount_eur TEXT NOT NULL,
            winner_ledger_entry_id INTEGER NOT NULL,
            loser_ledger_entry_id INTEGER NOT NULL,
            created_at_utc TEXT NOT NULL DEFAULT (datetime('now') || 'Z'),
            FOREIGN KEY (surebet_id) REFERENCES surebets(id),
            FOREIGN KEY (winner_associate_id) REFERENCES associates(id),
            FOREIGN KEY (loser_associate_id) REFERENCES associates(id),
            FOREIGN KEY (winner_ledger_entry_id) REFERENCES ledger_entries(id),
            FOREIGN KEY (loser_ledger_entry_id) REFERENCES ledger_entries(id)
        )
    """
    )

    # Indexes for quick lookups by associate
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_surebet_links_winner 
        ON surebet_settlement_links(winner_associate_id)
    """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_surebet_links_loser 
        ON surebet_settlement_links(loser_associate_id)
    """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_surebet_links_surebet 
        ON surebet_settlement_links(surebet_id)
    """
    )


def create_ledger_entries_table(conn: sqlite3.Connection) -> None:
    """Create the ledger_entries table."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ledger_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL CHECK (type IN ('BET_RESULT', 'DEPOSIT', 'WITHDRAWAL', 'BOOKMAKER_CORRECTION')),
            associate_id INTEGER NOT NULL REFERENCES associates(id),
            bookmaker_id INTEGER REFERENCES bookmakers(id),
            amount_native TEXT NOT NULL,
            native_currency TEXT NOT NULL,
            fx_rate_snapshot TEXT NOT NULL,
            amount_eur TEXT NOT NULL,
            settlement_state TEXT CHECK (settlement_state IN ('WON', 'LOST', 'VOID') OR settlement_state IS NULL),
            principal_returned_eur TEXT,
            per_surebet_share_eur TEXT,
            surebet_id INTEGER REFERENCES surebets(id),
            bet_id INTEGER,
            opposing_associate_id INTEGER REFERENCES associates(id),
            settlement_batch_id TEXT,
            created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            created_by TEXT NOT NULL DEFAULT 'local_user',
            note TEXT
        )
    """
    )

    # Backfill legacy schemas to match current contract
    cursor = conn.execute("PRAGMA table_info(ledger_entries)")
    existing = {row[1] for row in cursor.fetchall()}
    required = {
        "type",
        "associate_id",
        "bookmaker_id",
        "amount_native",
        "native_currency",
        "fx_rate_snapshot",
        "amount_eur",
        "settlement_state",
        "principal_returned_eur",
        "per_surebet_share_eur",
        "surebet_id",
        "bet_id",
        "settlement_batch_id",
        "created_at_utc",
        "created_by",
        "note",
    }

    if not required.issubset(existing):
        migrate_legacy_ledger_entries(conn, existing)

    # Backfill opposing_associate_id column for existing databases
    if "opposing_associate_id" not in existing:
        conn.execute("ALTER TABLE ledger_entries ADD COLUMN opposing_associate_id INTEGER REFERENCES associates(id)")

    # Indexes for ledger queries
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ledger_associate 
        ON ledger_entries(associate_id)
    """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ledger_type 
        ON ledger_entries(type)
    """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ledger_date 
        ON ledger_entries(created_at_utc)
    """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ledger_batch 
        ON ledger_entries(settlement_batch_id)
        """
    )


def create_verification_audit_table(conn: sqlite3.Connection) -> None:
    """Create the verification_audit table."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS verification_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bet_id INTEGER NOT NULL,
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            diff_before TEXT,
            diff_after TEXT,
            notes TEXT,
            created_at_utc TEXT NOT NULL DEFAULT (datetime('now') || 'Z'),
            FOREIGN KEY (bet_id) REFERENCES bets(id) ON DELETE CASCADE,
            CHECK (action IN ('CREATED', 'VERIFIED', 'REJECTED', 'MODIFIED'))
        )
    """
    )

    # Index for bet lookup
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_verification_audit_bet_id 
        ON verification_audit(bet_id)
    """
    )


def create_multibook_message_log_table(conn: sqlite3.Connection) -> None:
    """Create the multibook_message_log table."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS multibook_message_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            associate_id INTEGER NOT NULL,
            surebet_id INTEGER NOT NULL,
            message_type TEXT NOT NULL,
            delivery_status TEXT NOT NULL DEFAULT 'pending',
            message_id TEXT,
            error_message TEXT,
            sent_at_utc TEXT,
            created_at_utc TEXT NOT NULL DEFAULT (datetime('now') || 'Z'),
            FOREIGN KEY (associate_id) REFERENCES associates(id),
            FOREIGN KEY (surebet_id) REFERENCES surebets(id) ON DELETE CASCADE,
            CHECK (message_type IN ('COVERAGE_PROOF', 'SETTLEMENT_NOTICE')),
            CHECK (delivery_status IN ('pending', 'sent', 'failed'))
        )
    """
    )

    # Index for delivery status
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_multibook_delivery_status 
        ON multibook_message_log(delivery_status)
    """
    )


def migrate_legacy_ledger_entries(conn: sqlite3.Connection, existing_columns: Set[str]) -> None:
    """Upgrade legacy ledger_entries table to the current schema."""
    conn.execute("ALTER TABLE ledger_entries RENAME TO ledger_entries_legacy")

    conn.execute(
        """
        CREATE TABLE ledger_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL CHECK (type IN ('BET_RESULT', 'DEPOSIT', 'WITHDRAWAL', 'BOOKMAKER_CORRECTION')),
            associate_id INTEGER NOT NULL REFERENCES associates(id),
            bookmaker_id INTEGER REFERENCES bookmakers(id),
            amount_native TEXT NOT NULL,
            native_currency TEXT NOT NULL,
            fx_rate_snapshot TEXT NOT NULL,
            amount_eur TEXT NOT NULL,
            settlement_state TEXT CHECK (settlement_state IN ('WON', 'LOST', 'VOID') OR settlement_state IS NULL),
            principal_returned_eur TEXT,
            per_surebet_share_eur TEXT,
            surebet_id INTEGER REFERENCES surebets(id),
            bet_id INTEGER,
            opposing_associate_id INTEGER REFERENCES associates(id),
            settlement_batch_id TEXT,
            created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            created_by TEXT NOT NULL DEFAULT 'local_user',
            note TEXT
        )
    """
    )

    # Determine legacy column names for note/created_by if present
    has_notes = "notes" in existing_columns
    has_created_by = "created_by" in existing_columns

    conn.execute(
        f"""
        INSERT INTO ledger_entries (
            id,
            type,
            associate_id,
            bookmaker_id,
            amount_native,
            native_currency,
            fx_rate_snapshot,
            amount_eur,
            settlement_state,
            principal_returned_eur,
            per_surebet_share_eur,
            surebet_id,
            bet_id,
            settlement_batch_id,
            created_at_utc,
            created_by,
            note
        )
        SELECT
            id,
            type,
            associate_id,
            NULL AS bookmaker_id,
            COALESCE(amount_eur, '0.00') AS amount_native,
            'EUR' AS native_currency,
            fx_rate_snapshot,
            amount_eur,
            settlement_state,
            COALESCE(principal_returned_eur, '0.00'),
            COALESCE(per_surebet_share_eur, '0.00'),
            surebet_id,
            bet_id,
            settlement_batch_id,
            created_at_utc,
            { "created_by" if has_created_by else "'local_user'" } AS created_by,
            { "notes" if has_notes else "note" if "note" in existing_columns else "''" } AS note
        FROM ledger_entries_legacy
    """
    )

    conn.execute("DROP TABLE ledger_entries_legacy")

    # Recreate indexes after migration
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ledger_associate 
        ON ledger_entries(associate_id)
    """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ledger_type 
        ON ledger_entries(type)
    """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ledger_date 
        ON ledger_entries(created_at_utc)
    """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ledger_batch 
        ON ledger_entries(settlement_batch_id)
    """
    )

def create_bookmaker_balance_checks_table(conn: sqlite3.Connection) -> None:
    """Create the bookmaker_balance_checks table."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bookmaker_balance_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            associate_id INTEGER NOT NULL,
            bookmaker_id INTEGER NOT NULL,
            balance_native TEXT NOT NULL,
            native_currency TEXT NOT NULL,
            balance_eur TEXT NOT NULL,
            fx_rate_used TEXT NOT NULL,
            check_date_utc TEXT NOT NULL,
            note TEXT,
            created_at_utc TEXT NOT NULL DEFAULT (datetime('now') || 'Z'),
            FOREIGN KEY (associate_id) REFERENCES associates(id),
            FOREIGN KEY (bookmaker_id) REFERENCES bookmakers(id),
            UNIQUE(associate_id, bookmaker_id, check_date_utc)
        )
    """
    )

    # Index for balance history
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_balance_checks_bookmaker_date 
        ON bookmaker_balance_checks(bookmaker_id, check_date_utc)
    """
    )


def create_fx_rates_daily_table(conn: sqlite3.Connection) -> None:
    """Create the fx_rates_daily table."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS fx_rates_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            currency_code TEXT NOT NULL,
            rate_to_eur TEXT NOT NULL,
            fetched_at_utc TEXT NOT NULL,
            date TEXT NOT NULL,
            created_at_utc TEXT NOT NULL DEFAULT (datetime('now') || 'Z'),
            UNIQUE(currency_code, date)
        )
    """
    )

    # Index for currency lookup
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_fx_rates_currency_date 
        ON fx_rates_daily(currency_code, date)
    """
    )


def create_ledger_append_only_trigger(conn: sqlite3.Connection) -> None:
    """Create trigger to prevent UPDATE/DELETE on ledger_entries (System Law #1)."""
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS prevent_ledger_update
        BEFORE UPDATE ON ledger_entries
        BEGIN
            SELECT RAISE(ABORT, 'Cannot update ledger_entries - append-only table (System Law #1)');
        END
    """
    )

    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS prevent_ledger_delete
        BEFORE DELETE ON ledger_entries
        BEGIN
            SELECT RAISE(ABORT, 'Cannot delete from ledger_entries - append-only table (System Law #1)');
        END
    """
    )


def create_surebet_bets_side_immutable_trigger(conn: sqlite3.Connection) -> None:
    """Create trigger to prevent changes to surebet_bets.side after INSERT."""
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS prevent_surebet_bets_side_update
        BEFORE UPDATE OF side ON surebet_bets
        BEGIN
            SELECT RAISE(ABORT, 'Cannot modify surebet_bets.side - immutable after creation');
        END
    """
    )


def create_chat_registrations_table(conn: sqlite3.Connection) -> None:
    """Create the chat_registrations table."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_registrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL UNIQUE,
            associate_id INTEGER NOT NULL,
            bookmaker_id INTEGER NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at_utc TEXT NOT NULL DEFAULT (datetime('now') || 'Z'),
            updated_at_utc TEXT NOT NULL DEFAULT (datetime('now') || 'Z'),
            FOREIGN KEY (associate_id) REFERENCES associates(id),
            FOREIGN KEY (bookmaker_id) REFERENCES bookmakers(id)
        )
    """
    )

    # Index for quick lookup by chat_id
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_registrations_chat_id
        ON chat_registrations(chat_id)
        """
    )


def create_funding_drafts_table(conn: sqlite3.Connection) -> None:
    """Create the funding_drafts table for persistent draft storage."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS funding_drafts (
            id TEXT PRIMARY KEY,
            chat_id TEXT,
            associate_id INTEGER NOT NULL,
            associate_alias TEXT NOT NULL,
            bookmaker_id INTEGER NOT NULL,
            bookmaker_name TEXT NOT NULL,
            event_type TEXT NOT NULL CHECK (event_type IN ('DEPOSIT','WITHDRAWAL')),
            amount_native TEXT NOT NULL,
            native_currency TEXT NOT NULL,
            note TEXT,
            source TEXT NOT NULL DEFAULT 'manual',
            created_at_utc TEXT NOT NULL DEFAULT (datetime('now') || 'Z'),
            FOREIGN KEY (associate_id) REFERENCES associates(id),
            FOREIGN KEY (bookmaker_id) REFERENCES bookmakers(id)
        )
    """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_funding_drafts_assoc_bookmaker
        ON funding_drafts(associate_id, bookmaker_id)
    """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_funding_drafts_created_at
        ON funding_drafts(created_at_utc DESC)
    """
    )


def create_notification_audit_table(conn: sqlite3.Connection) -> None:
    """Create audit trail for Telegram notification attempts."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS notification_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            draft_id TEXT NOT NULL,
            chat_id TEXT,
            ledger_id INTEGER,
            operator_id TEXT,
            status TEXT NOT NULL CHECK (status IN ('sent','failed')),
            detail TEXT,
            needs_follow_up BOOLEAN NOT NULL DEFAULT 0,
            created_at_utc TEXT NOT NULL DEFAULT (datetime('now') || 'Z'),
            FOREIGN KEY (ledger_id) REFERENCES ledger_entries(id)
        )
    """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_notification_audit_followup
        ON notification_audit(needs_follow_up, created_at_utc DESC)
    """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_notification_audit_draft
        ON notification_audit(draft_id)
    """
    )


def get_all_table_names(conn: sqlite3.Connection) -> List[str]:
    """
    Get a list of all table names in the database.

    Args:
        conn: SQLite database connection.

    Returns:
        List of table names.
    """
    cursor = conn.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type='table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
    """
    )

    return [row[0] for row in cursor.fetchall()]
