"""
Schema validation for the Surebet Accounting System.

This module verifies that all tables exist with correct columns and constraints.
"""

import sqlite3
from typing import Dict, List, Tuple, Any


class SchemaValidationError(Exception):
    """Raised when schema validation fails."""

    pass


def validate_schema(conn: sqlite3.Connection) -> bool:
    """
    Validate the complete database schema.

    Args:
        conn: SQLite database connection.

    Returns:
        True if schema is valid.

    Raises:
        SchemaValidationError: If schema validation fails.
    """
    errors = []

    # Validate all tables exist
    errors.extend(validate_all_tables_exist(conn))

    # Validate table structures
    errors.extend(validate_table_structures(conn))

    # Validate constraints
    errors.extend(validate_constraints(conn))

    # Validate triggers
    errors.extend(validate_triggers(conn))

    # Validate indexes
    errors.extend(validate_indexes(conn))

    if errors:
        error_msg = "Schema validation failed:\n" + "\n".join(f"- {error}" for error in errors)
        raise SchemaValidationError(error_msg)

    print("Schema validation passed successfully")
    return True


def validate_all_tables_exist(conn: sqlite3.Connection) -> List[str]:
    """
    Validate that all required tables exist.

    Args:
        conn: SQLite database connection.

    Returns:
        List of error messages for missing tables.
    """
    required_tables = [
        "associates",
        "bookmakers",
        "canonical_events",
        "canonical_markets",
        "bets",
        "surebets",
        "surebet_bets",
        "ledger_entries",
        "verification_audit",
        "multibook_message_log",
        "bookmaker_balance_checks",
        "fx_rates_daily",
    ]

    cursor = conn.execute(
        """
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name NOT LIKE 'sqlite_%'
    """
    )

    existing_tables = {row[0] for row in cursor.fetchall()}
    errors = []

    for table in required_tables:
        if table not in existing_tables:
            errors.append(f"Missing required table: {table}")

    return errors


def validate_table_structures(conn: sqlite3.Connection) -> List[str]:
    """
    Validate that all tables have the correct columns.

    Args:
        conn: SQLite database connection.

    Returns:
        List of error messages for incorrect table structures.
    """
    expected_columns = {
        "associates": {
            "id": "INTEGER",
            "display_alias": "TEXT",
            "home_currency": "TEXT",
            "multibook_chat_id": "TEXT",
            "is_active": "BOOLEAN",  # SQLite stores BOOLEAN as INTEGER
            "is_admin": "BOOLEAN",  # SQLite stores BOOLEAN as INTEGER
            "created_at_utc": "TEXT",
            "updated_at_utc": "TEXT",
        },
        "bookmakers": {
            "id": "INTEGER",
            "associate_id": "INTEGER",
            "bookmaker_name": "TEXT",
            "parsing_profile": "TEXT",
            "is_active": "BOOLEAN",  # SQLite stores BOOLEAN as INTEGER
            "created_at_utc": "TEXT",
            "updated_at_utc": "TEXT",
        },
        "canonical_events": {
            "id": "INTEGER",
            "normalized_event_name": "TEXT",
            "league": "TEXT",
            "sport": "TEXT",
            "team1_slug": "TEXT",
            "team2_slug": "TEXT",
            "pair_key": "TEXT",
            "kickoff_time_utc": "TEXT",
            "created_at_utc": "TEXT",
            "updated_at_utc": "TEXT",
        },
        "canonical_markets": {
            "id": "INTEGER",
            "market_code": "TEXT",
            "description": "TEXT",
            "created_at_utc": "TEXT",
        },
        "bets": {
            "id": "INTEGER",
            "associate_id": "INTEGER",
            "bookmaker_id": "INTEGER",
            "canonical_event_id": "INTEGER",
            "canonical_market_id": "INTEGER",
            "status": "TEXT",
            "stake_eur": "TEXT",
            "odds": "TEXT",
            "currency": "TEXT",
            "fx_rate_to_eur": "TEXT",
            "stake_original": "TEXT",
            "odds_original": "TEXT",
            "selection_text": "TEXT",
            "screenshot_path": "TEXT",
            "ocr_confidence": "REAL",
            "is_multi": "BOOLEAN",  # SQLite stores BOOLEAN as INTEGER
            "created_at_utc": "TEXT",
            "updated_at_utc": "TEXT",
        },
        "surebets": {
            "id": "INTEGER",
            "canonical_event_id": "INTEGER",
            "canonical_market_id": "INTEGER",
            "market_code": "TEXT",
            "period_scope": "TEXT",
            "line_value": "TEXT",
            "status": "TEXT",
            "total_stake_eur": "TEXT",
            "expected_profit_eur": "TEXT",
            "actual_profit_eur": "TEXT",
            "settled_at_utc": "TEXT",
            "worst_case_profit_eur": "TEXT",
            "total_staked_eur": "TEXT",
            "roi": "TEXT",
            "risk_classification": "TEXT",
            "created_at_utc": "TEXT",
            "updated_at_utc": "TEXT",
        },
        "surebet_bets": {
            "surebet_id": "INTEGER",
            "bet_id": "INTEGER",
            "side": "TEXT",
            "created_at_utc": "TEXT",
        },
        "ledger_entries": {
            "id": "INTEGER",
            "type": "TEXT",
            "associate_id": "INTEGER",
            "bookmaker_id": "INTEGER",
            "amount_native": "TEXT",
            "native_currency": "TEXT",
            "fx_rate_snapshot": "TEXT",
            "amount_eur": "TEXT",
            "settlement_state": "TEXT",
            "principal_returned_eur": "TEXT",
            "per_surebet_share_eur": "TEXT",
            "surebet_id": "INTEGER",
            "bet_id": "INTEGER",
            "settlement_batch_id": "TEXT",
            "created_at_utc": "TEXT",
            "created_by": "TEXT",
            "note": "TEXT",
        },
        "verification_audit": {
            "id": "INTEGER",
            "bet_id": "INTEGER",
            "actor": "TEXT",
            "action": "TEXT",
            "diff_before": "TEXT",
            "diff_after": "TEXT",
            "notes": "TEXT",
            "created_at_utc": "TEXT",
        },
        "multibook_message_log": {
            "id": "INTEGER",
            "associate_id": "INTEGER",
            "surebet_id": "INTEGER",
            "message_type": "TEXT",
            "delivery_status": "TEXT",
            "message_id": "TEXT",
            "error_message": "TEXT",
            "sent_at_utc": "TEXT",
            "created_at_utc": "TEXT",
        },
        "bookmaker_balance_checks": {
            "id": "INTEGER",
            "associate_id": "INTEGER",
            "bookmaker_id": "INTEGER",
            "balance_native": "TEXT",
            "native_currency": "TEXT",
            "balance_eur": "TEXT",
            "fx_rate_used": "TEXT",
            "check_date_utc": "TEXT",
            "note": "TEXT",
            "created_at_utc": "TEXT",
        },
        "fx_rates_daily": {
            "id": "INTEGER",
            "currency_code": "TEXT",
            "rate_to_eur": "TEXT",
            "fetched_at_utc": "TEXT",
            "date": "TEXT",
            "created_at_utc": "TEXT",
        },
    }

    errors = []

    for table_name, expected_cols in expected_columns.items():
        try:
            cursor = conn.execute(f"PRAGMA table_info({table_name})")
            actual_cols = {row[1]: row[2] for row in cursor.fetchall()}

            # Check for missing columns
            for col_name, col_type in expected_cols.items():
                if col_name not in actual_cols:
                    errors.append(f"Table {table_name}: Missing column {col_name}")
                elif col_type == "BOOLEAN":
                    # SQLite stores BOOLEAN as BOOLEAN (which is actually INTEGER internally)
                    if not (
                        actual_cols[col_name].startswith("BOOLEAN")
                        or actual_cols[col_name].startswith("INTEGER")
                    ):
                        errors.append(
                            f"Table {table_name}: Column {col_name} has type {actual_cols[col_name]}, "
                            f"expected BOOLEAN (stored as INTEGER internally)"
                        )
                elif not actual_cols[col_name].startswith(col_type):
                    errors.append(
                        f"Table {table_name}: Column {col_name} has type {actual_cols[col_name]}, "
                        f"expected {col_type}"
                    )

            # Check for extra columns (optional, can be commented out)
            # for col_name in actual_cols:
            #     if col_name not in expected_cols:
            #         errors.append(f"Table {table_name}: Unexpected column {col_name}")

        except sqlite3.OperationalError as e:
            errors.append(f"Table {table_name}: {str(e)}")

    return errors


def validate_constraints(conn: sqlite3.Connection) -> List[str]:
    """
    Validate that all required constraints exist.

    Args:
        conn: SQLite database connection.

    Returns:
        List of error messages for missing constraints.
    """
    errors = []

    # Check foreign key constraints are enabled
    cursor = conn.execute("PRAGMA foreign_keys")
    fk_enabled = cursor.fetchone()[0]
    if not fk_enabled:
        errors.append("Foreign keys are not enabled")

    # Check unique constraints
    unique_constraints = [
        ("associates", "display_alias"),
        ("bookmakers", "associate_id, bookmaker_name"),
        ("fx_rates_daily", "currency_code, date"),
        ("bookmaker_balance_checks", "associate_id, bookmaker_id, check_date_utc"),
    ]

    for table, columns in unique_constraints:
        cursor = conn.execute(f"PRAGMA index_list({table})")
        indexes = cursor.fetchall()

        found_unique = False
        for index in indexes:
            if index[2]:  # unique flag
                cursor = conn.execute(f"PRAGMA index_info({index[1]})")
                index_cols = [row[2] for row in cursor.fetchall()]
                if index_cols == columns.split(", "):
                    found_unique = True
                    break

        if not found_unique:
            errors.append(f"Table {table}: Missing unique constraint on ({columns})")

    return errors


def validate_triggers(conn: sqlite3.Connection) -> List[str]:
    """
    Validate that all required triggers exist.

    Args:
        conn: SQLite database connection.

    Returns:
        List of error messages for missing triggers.
    """
    required_triggers = [
        "prevent_ledger_update",
        "prevent_ledger_delete",
        "prevent_surebet_bets_side_update",
    ]

    cursor = conn.execute(
        """
        SELECT name FROM sqlite_master 
        WHERE type='trigger' AND name NOT LIKE 'sqlite_%'
    """
    )

    existing_triggers = {row[0] for row in cursor.fetchall()}
    errors = []

    for trigger in required_triggers:
        if trigger not in existing_triggers:
            errors.append(f"Missing required trigger: {trigger}")

    return errors


def validate_indexes(conn: sqlite3.Connection) -> List[str]:
    """
    Validate that all required indexes exist.

    Args:
        conn: SQLite database connection.

    Returns:
        List of error messages for missing indexes.
    """
    required_indexes = [
        ("idx_associates_display_alias", "associates"),
        ("idx_bookmakers_associate_id", "bookmakers"),
        ("idx_canonical_events_name", "canonical_events"),
        ("idx_canonical_events_kickoff", "canonical_events"),
        ("idx_bets_status", "bets"),
        ("idx_bets_associate_id", "bets"),
        ("idx_bets_canonical_event_id", "bets"),
        ("idx_surebets_status", "surebets"),
        ("idx_ledger_associate", "ledger_entries"),
        ("idx_ledger_type", "ledger_entries"),
        ("idx_ledger_date", "ledger_entries"),
        ("idx_ledger_batch", "ledger_entries"),
        ("idx_verification_audit_bet_id", "verification_audit"),
        ("idx_multibook_delivery_status", "multibook_message_log"),
        ("idx_balance_checks_bookmaker_date", "bookmaker_balance_checks"),
        ("idx_fx_rates_currency_date", "fx_rates_daily"),
    ]

    cursor = conn.execute(
        """
        SELECT name, tbl_name FROM sqlite_master 
        WHERE type='index' AND name NOT LIKE 'sqlite_%'
    """
    )

    existing_indexes = {(row[0], row[1]) for row in cursor.fetchall()}
    errors = []

    for index_name, table_name in required_indexes:
        if (index_name, table_name) not in existing_indexes:
            errors.append(f"Missing required index: {index_name} on {table_name}")

    return errors


def get_schema_summary(conn: sqlite3.Connection) -> Dict[str, Any]:
    """
    Get a summary of the database schema.

    Args:
        conn: SQLite database connection.

    Returns:
        Dictionary with schema summary information.
    """
    summary: Dict[str, Any] = {}

    # Table counts
    cursor = conn.execute(
        """
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
    """
    )
    tables = [row[0] for row in cursor.fetchall()]

    summary["tables"] = {}
    for table in tables:
        cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
        summary["tables"][table] = cursor.fetchone()[0]

    # Trigger count
    cursor = conn.execute(
        """
        SELECT COUNT(*) FROM sqlite_master 
        WHERE type='trigger' AND name NOT LIKE 'sqlite_%'
    """
    )
    summary["triggers"] = cursor.fetchone()[0]

    # Index count
    cursor = conn.execute(
        """
        SELECT COUNT(*) FROM sqlite_master 
        WHERE type='index' AND name NOT LIKE 'sqlite_%'
    """
    )
    summary["indexes"] = cursor.fetchone()[0]

    # Foreign key status
    cursor = conn.execute("PRAGMA foreign_keys")
    summary["foreign_keys_enabled"] = bool(cursor.fetchone()[0])

    return summary
