"""
Database schema definition for the Surebet Accounting System.

This module defines all 11 core tables with proper constraints and indexes.
"""

import sqlite3
from typing import List


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
    create_ledger_entries_table(conn)
    create_verification_audit_table(conn)
    create_multibook_message_log_table(conn)
    create_bookmaker_balance_checks_table(conn)
    create_fx_rates_daily_table(conn)
    create_chat_registrations_table(conn)

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
            status TEXT NOT NULL DEFAULT 'incoming',
            stake_eur TEXT NOT NULL,
            odds TEXT NOT NULL,
            currency TEXT NOT NULL DEFAULT 'EUR',
            fx_rate_to_eur TEXT DEFAULT '1.0',
            stake_original TEXT,
            odds_original TEXT,
            payout TEXT,
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
            canonical_event_id INTEGER NOT NULL,
            canonical_market_id INTEGER,
            market_code TEXT NOT NULL,
            period_scope TEXT NOT NULL,
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


def create_surebet_bets_table(conn: sqlite3.Connection) -> None:
    """Create the surebet_bets junction table."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS surebet_bets (
            surebet_id INTEGER NOT NULL,
            bet_id INTEGER NOT NULL,
            side TEXT NOT NULL,
            created_at_utc TEXT NOT NULL DEFAULT (datetime('now') || 'Z'),
            PRIMARY KEY (surebet_id, bet_id),
            FOREIGN KEY (surebet_id) REFERENCES surebets(id) ON DELETE CASCADE,
            FOREIGN KEY (bet_id) REFERENCES bets(id) ON DELETE CASCADE,
            CHECK (side IN ('A', 'B'))
        )
    """
    )


def create_ledger_entries_table(conn: sqlite3.Connection) -> None:
    """Create the ledger_entries table."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ledger_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            associate_id INTEGER NOT NULL,
            surebet_id INTEGER,
            bet_id INTEGER,
            type TEXT NOT NULL,
            amount_eur TEXT NOT NULL,
            fx_rate_snapshot TEXT NOT NULL,
            balance_after_eur TEXT,
            reference TEXT,
            notes TEXT,
            created_at_utc TEXT NOT NULL DEFAULT (datetime('now') || 'Z'),
            FOREIGN KEY (associate_id) REFERENCES associates(id),
            FOREIGN KEY (surebet_id) REFERENCES surebets(id),
            FOREIGN KEY (bet_id) REFERENCES bets(id),
            CHECK (type IN ('STAKE', 'WINNINGS', 'REFUND', 'ADJUSTMENT', 'DEPOSIT', 'WITHDRAWAL'))
        )
    """
    )

    # Indexes for ledger queries
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ledger_associate_id 
        ON ledger_entries(associate_id)
    """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ledger_created_at 
        ON ledger_entries(created_at_utc)
    """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ledger_type 
        ON ledger_entries(type)
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


def create_bookmaker_balance_checks_table(conn: sqlite3.Connection) -> None:
    """Create the bookmaker_balance_checks table."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bookmaker_balance_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            associate_id INTEGER NOT NULL,
            bookmaker_id INTEGER NOT NULL,
            balance_eur TEXT NOT NULL,
            check_date TEXT NOT NULL,
            notes TEXT,
            created_at_utc TEXT NOT NULL DEFAULT (datetime('now') || 'Z'),
            FOREIGN KEY (associate_id) REFERENCES associates(id),
            FOREIGN KEY (bookmaker_id) REFERENCES bookmakers(id),
            UNIQUE(associate_id, bookmaker_id, check_date)
        )
    """
    )

    # Index for balance history
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_balance_checks_bookmaker_date 
        ON bookmaker_balance_checks(bookmaker_id, check_date)
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
