"""
Seed data insertion for the Surebet Accounting System.

This module inserts initial data required for the system to function.
"""

import sqlite3
from decimal import Decimal
from typing import Dict, Any

from src.utils.datetime_helpers import utc_now_iso


def insert_seed_data(conn: sqlite3.Connection) -> None:
    """
    Insert all seed data into the database.

    Args:
        conn: SQLite database connection.
    """
    # Insert in dependency order
    associate_ids = insert_associates(conn)
    bookmaker_ids = insert_bookmakers(conn, associate_ids)
    market_ids = insert_canonical_markets(conn)

    print("Seed data inserted successfully")


def insert_associates(conn: sqlite3.Connection) -> Dict[str, int]:
    """
    Insert initial associate data.

    Args:
        conn: SQLite database connection.

    Returns:
        Dictionary mapping associate names to their IDs.
    """
    associates = [
        {
            "id": 1,
            "display_alias": "Admin",
            "home_currency": "EUR",
            "is_admin": True,
            "created_at_utc": utc_now_iso(),
        },
        {
            "id": 2,
            "display_alias": "Seed Partner",
            "home_currency": "EUR",
            "is_admin": False,
            "created_at_utc": utc_now_iso(),
        },
    ]

    associate_ids = {}

    for associate in associates:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO associates 
            (id, display_alias, home_currency, is_admin, created_at_utc)
            VALUES (?, ?, ?, ?, ?)
        """,
            (
                associate["id"],
                associate["display_alias"],
                associate["home_currency"],
                associate["is_admin"],
                associate["created_at_utc"],
            ),
        )

        if cursor.rowcount:
            associate_ids[associate["display_alias"]] = associate["id"]
        else:
            # If already exists, get the ID
            cursor = conn.execute(
                """
                SELECT id FROM associates WHERE display_alias = ?
            """,
                (associate["display_alias"],),
            )
            associate_ids[associate["display_alias"]] = cursor.fetchone()[0]

    return associate_ids  # type: ignore[return-value]


def insert_bookmakers(conn: sqlite3.Connection, associate_ids: Dict[str, int]) -> Dict[str, int]:
    """
    Insert initial bookmaker data.

    Args:
        conn: SQLite database connection.
        associate_ids: Dictionary mapping associate names to their IDs.

    Returns:
        Dictionary mapping bookmaker names to their IDs.
    """
    bookmakers = [
        {
            "id": 1,
            "associate_key": "Admin",
            "bookmaker_name": "Bet365",
            "parsing_profile": "bet365_standard",
            "created_at_utc": utc_now_iso(),
        },
        {
            "id": 2,
            "associate_key": "Admin",
            "bookmaker_name": "Pinnacle",
            "parsing_profile": "pinnacle_standard",
            "created_at_utc": utc_now_iso(),
        },
        {
            "id": 3,
            "associate_key": "Seed Partner",
            "bookmaker_name": "Bet365",
            "parsing_profile": "bet365_standard",
            "created_at_utc": utc_now_iso(),
        },
        {
            "id": 4,
            "associate_key": "Seed Partner",
            "bookmaker_name": "Pinnacle",
            "parsing_profile": "pinnacle_standard",
            "created_at_utc": utc_now_iso(),
        },
    ]

    bookmaker_ids = {}

    for bookmaker in bookmakers:
        associate_key = bookmaker["associate_key"]
        if associate_key not in associate_ids:
            continue

        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO bookmakers 
            (id, associate_id, bookmaker_name, parsing_profile, created_at_utc)
            VALUES (?, ?, ?, ?, ?)
        """,
            (
                bookmaker["id"],
                associate_ids[associate_key],
                bookmaker["bookmaker_name"],
                bookmaker["parsing_profile"],
                bookmaker["created_at_utc"],
            ),
        )

        key = f"{bookmaker['bookmaker_name']} ({associate_key})"
        if cursor.rowcount:
            bookmaker_ids[key] = bookmaker["id"]
        else:
            # If already exists, get the ID
            cursor = conn.execute(
                """
                SELECT id FROM bookmakers 
                WHERE associate_id = ? AND bookmaker_name = ?
            """,
                (associate_ids[associate_key], bookmaker["bookmaker_name"]),
            )
            bookmaker_ids[key] = cursor.fetchone()[0]

    return bookmaker_ids


def insert_canonical_markets(conn: sqlite3.Connection) -> Dict[str, int]:
    """
    Insert initial canonical market data.

    Args:
        conn: SQLite database connection.

    Returns:
        Dictionary mapping market codes to their IDs.
    """
    markets = [
        # Soccer Over/Under
        {"market_code": "TOTAL_GOALS_OVER_UNDER", "description": "Total Goals Over/Under", "created_at_utc": utc_now_iso()},
        {"market_code": "FIRST_HALF_TOTAL_GOALS", "description": "1st Half Total Goals Over/Under", "created_at_utc": utc_now_iso()},
        {"market_code": "SECOND_HALF_TOTAL_GOALS", "description": "2nd Half Total Goals Over/Under", "created_at_utc": utc_now_iso()},
        {"market_code": "TOTAL_CARDS_OVER_UNDER", "description": "Total Cards Over/Under (Bookings)", "created_at_utc": utc_now_iso()},
        {"market_code": "TOTAL_CORNERS_OVER_UNDER", "description": "Total Corners Over/Under", "created_at_utc": utc_now_iso()},
        {"market_code": "TOTAL_SHOTS_OVER_UNDER", "description": "Total Shots Over/Under", "created_at_utc": utc_now_iso()},
        {"market_code": "TOTAL_SHOTS_ON_TARGET_OVER_UNDER", "description": "Total Shots on Target Over/Under", "created_at_utc": utc_now_iso()},
        # Soccer Yes/No and team two-way
        {"market_code": "BOTH_TEAMS_TO_SCORE", "description": "Both Teams To Score (Yes/No)", "created_at_utc": utc_now_iso()},
        {"market_code": "RED_CARD_AWARDED", "description": "Red Card Awarded (Yes/No)", "created_at_utc": utc_now_iso()},
        {"market_code": "PENALTY_AWARDED", "description": "Penalty Awarded (Yes/No)", "created_at_utc": utc_now_iso()},
        {"market_code": "DRAW_NO_BET", "description": "Draw No Bet (Home/Away)", "created_at_utc": utc_now_iso()},
        {"market_code": "ASIAN_HANDICAP", "description": "Asian Handicap", "created_at_utc": utc_now_iso()},
        # Tennis
        {"market_code": "MATCH_WINNER", "description": "Match Winner (Two-Way)", "created_at_utc": utc_now_iso()},
        {"market_code": "TOTAL_GAMES_OVER_UNDER", "description": "Total Games Over/Under (Match)", "created_at_utc": utc_now_iso()},
    ]

    market_ids = {}

    for market in markets:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO canonical_markets 
            (market_code, description, created_at_utc)
            VALUES (?, ?, ?)
        """,
            (market["market_code"], market["description"], market["created_at_utc"]),
        )

        if cursor.lastrowid:
            market_ids[market["market_code"]] = cursor.lastrowid
        else:
            # If already exists, get the ID
            cursor = conn.execute(
                """
                SELECT id FROM canonical_markets WHERE market_code = ?
            """,
                (market["market_code"],),
            )
            market_ids[market["market_code"]] = cursor.fetchone()[0]

    return market_ids


def insert_sample_fx_rates(conn: sqlite3.Connection) -> None:
    """
    Insert sample FX rates for common currencies.

    Args:
        conn: SQLite database connection.
    """
    from datetime import datetime, timedelta

    # Sample rates as of today
    rates = [
        {"currency_code": "USD", "rate_to_eur": "0.92"},
        {"currency_code": "GBP", "rate_to_eur": "1.16"},
        {"currency_code": "AUD", "rate_to_eur": "0.61"},
        {"currency_code": "CAD", "rate_to_eur": "0.68"},
        {"currency_code": "JPY", "rate_to_eur": "0.0062"},
    ]

    today = datetime.utcnow().strftime("%Y-%m-%d")

    for rate in rates:
        conn.execute(
            """
            INSERT OR IGNORE INTO fx_rates_daily 
            (currency_code, rate_to_eur, date, fetched_at_utc)
            VALUES (?, ?, ?, ?)
        """,
            (rate["currency_code"], rate["rate_to_eur"], today, utc_now_iso()),
        )


def get_seed_data_summary(conn: sqlite3.Connection) -> Dict[str, int]:
    """
    Get a summary of seed data counts.

    Args:
        conn: SQLite database connection.

    Returns:
        Dictionary with table names and their record counts.
    """
    tables = [
        "associates",
        "bookmakers",
        "canonical_markets",
        "canonical_events",
        "bets",
        "surebets",
        "surebet_bets",
        "ledger_entries",
        "verification_audit",
        "multibook_message_log",
        "bookmaker_balance_checks",
        "fx_rates_daily",
    ]

    summary = {}

    for table in tables:
        try:
            cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
            summary[table] = cursor.fetchone()[0]
        except sqlite3.OperationalError:
            summary[table] = 0

    return summary

