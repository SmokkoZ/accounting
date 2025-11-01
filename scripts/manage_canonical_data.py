"""
Manage canonical markets and events.

This script provides utilities for:
- Seeding canonical markets
- Creating canonical events
- Fuzzy matching events to prevent duplicates
- Bulk import from CSV

Usage:
    python scripts/manage_canonical_data.py seed-markets
    python scripts/manage_canonical_data.py create-event "Team A vs Team B" "2025-11-01T20:00:00Z"
    python scripts/manage_canonical_data.py import-events events.csv
"""

import sqlite3
import sys
from pathlib import Path
from typing import List, Tuple, Optional
from datetime import datetime
import csv

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.database import get_db_connection
from src.utils.datetime_helpers import utc_now_iso


def seed_canonical_markets(db: sqlite3.Connection) -> int:
    """Seed comprehensive list of canonical markets.

    Returns:
        Number of markets inserted
    """
    markets = [
        # Tier 1: Most Common (Football)
        ('MATCH_WINNER', 'Match Winner / 1X2 / Moneyline'),
        ('DRAW_NO_BET', 'Draw No Bet'),
        ('DOUBLE_CHANCE', 'Double Chance (1X, X2, 12)'),
        ('TOTAL_GOALS_OVER_UNDER', 'Total Goals Over/Under'),
        ('BOTH_TEAMS_TO_SCORE', 'Both Teams to Score (BTTS)'),
        ('TEAM_TOTAL_GOALS', 'Team Total Goals Over/Under'),
        ('ASIAN_HANDICAP', 'Asian Handicap'),
        ('EUROPEAN_HANDICAP', 'European Handicap / 3-Way Handicap'),
        ('HALF_TIME_RESULT', 'Half Time Result (1X2)'),
        ('HALF_TIME_FULL_TIME', 'Half Time / Full Time'),
        ('SECOND_HALF_WINNER', 'Second Half Winner'),

        # Tier 2: Popular
        ('FIRST_GOAL_SCORER', 'First Goal Scorer'),
        ('LAST_GOAL_SCORER', 'Last Goal Scorer'),
        ('ANYTIME_GOAL_SCORER', 'Anytime Goal Scorer'),
        ('FIRST_HALF_GOALS_OU', 'First Half Goals Over/Under'),
        ('SECOND_HALF_GOALS_OU', 'Second Half Goals Over/Under'),
        ('CORRECT_SCORE', 'Correct Score'),
        ('WINNING_MARGIN', 'Winning Margin'),
        ('TOTAL_CORNERS', 'Total Corners Over/Under'),
        ('TOTAL_CARDS', 'Total Cards Over/Under'),
        ('CLEAN_SHEET', 'To Keep a Clean Sheet'),
        ('TO_WIN_TO_NIL', 'To Win to Nil'),

        # Tier 3: Niche (Football)
        ('CORNER_HANDICAP', 'Corner Handicap'),
        ('FIRST_CORNER', 'First Corner'),
        ('CORNER_MATCH_BET', 'Corner Match Bet'),
        ('TOTAL_BOOKINGS', 'Total Booking Points'),
        ('PLAYER_TO_BE_BOOKED', 'Player to be Booked'),
        ('SENDING_OFF', 'Sending Off / Red Card'),
        ('ODD_EVEN_GOALS', 'Odd/Even Total Goals'),
        ('GOALS_IN_BOTH_HALVES', 'Goals Scored in Both Halves'),
        ('TEAM_TO_SCORE_FIRST', 'Team to Score First'),
        ('TEAM_TO_SCORE_LAST', 'Team to Score Last'),

        # Other Sports
        ('TENNIS_MATCH_WINNER', 'Tennis - Match Winner'),
        ('TENNIS_SET_BETTING', 'Tennis - Correct Score in Sets'),
        ('TENNIS_TOTAL_GAMES', 'Tennis - Total Games Over/Under'),
        ('BASKETBALL_MONEYLINE', 'Basketball - Moneyline'),
        ('BASKETBALL_HANDICAP', 'Basketball - Point Spread'),
        ('BASKETBALL_TOTAL_POINTS', 'Basketball - Total Points Over/Under'),
        ('NFL_MONEYLINE', 'NFL - Moneyline'),
        ('NFL_SPREAD', 'NFL - Point Spread'),
        ('NFL_TOTAL_POINTS', 'NFL - Total Points Over/Under'),
        ('BASEBALL_MONEYLINE', 'Baseball - Moneyline'),
        ('BASEBALL_RUN_LINE', 'Baseball - Run Line'),
        ('HOCKEY_MONEYLINE', 'Hockey - Moneyline'),
        ('HOCKEY_PUCK_LINE', 'Hockey - Puck Line'),

        # Catch-all
        ('OTHER', 'Other / Unclassified Market'),
        ('CUSTOM', 'Custom Market'),
    ]

    inserted = 0
    for market_code, description in markets:
        try:
            db.execute(
                """
                INSERT INTO canonical_markets (market_code, description)
                VALUES (?, ?)
                """,
                (market_code, description)
            )
            inserted += 1
        except sqlite3.IntegrityError:
            # Already exists
            pass

    db.commit()
    return inserted


def create_canonical_event(
    db: sqlite3.Connection,
    event_name: str,
    kickoff_time_utc: str,
    league: Optional[str] = None,
    sport: Optional[str] = "football"
) -> int:
    """Create a canonical event.

    Args:
        db: Database connection
        event_name: Normalized event name (e.g., "Team A vs Team B")
        kickoff_time_utc: ISO8601 timestamp with Z suffix
        league: Optional league name
        sport: Sport type (default: football)

    Returns:
        ID of created event
    """
    cursor = db.execute(
        """
        INSERT INTO canonical_events (normalized_event_name, league, sport, kickoff_time_utc)
        VALUES (?, ?, ?, ?)
        """,
        (event_name, league, sport, kickoff_time_utc)
    )
    db.commit()
    return cursor.lastrowid


def find_similar_events(
    db: sqlite3.Connection,
    event_name: str,
    threshold: float = 0.8
) -> List[Tuple[int, str, float]]:
    """Find similar canonical events using fuzzy matching.

    Args:
        db: Database connection
        event_name: Event name to match
        threshold: Similarity threshold (0.0 to 1.0)

    Returns:
        List of (id, name, similarity_score) tuples
    """
    # Simple implementation - can be enhanced with fuzzy matching library
    cursor = db.execute(
        """
        SELECT id, normalized_event_name, league, kickoff_time_utc
        FROM canonical_events
        WHERE normalized_event_name LIKE ?
        ORDER BY kickoff_time_utc DESC
        LIMIT 10
        """,
        (f"%{event_name}%",)
    )

    results = []
    for row in cursor.fetchall():
        # Simple similarity: exact substring match = 1.0, otherwise use Levenshtein
        similarity = 1.0 if event_name.lower() in row[1].lower() else 0.5
        if similarity >= threshold:
            results.append((row[0], row[1], similarity))

    return results


def import_events_from_csv(db: sqlite3.Connection, csv_path: str) -> int:
    """Import canonical events from CSV file.

    CSV format: event_name,kickoff_time_utc,league,sport
    Example: "Man City vs Liverpool,2025-11-01T15:00:00Z,Premier League,football"

    Args:
        db: Database connection
        csv_path: Path to CSV file

    Returns:
        Number of events imported
    """
    imported = 0
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                create_canonical_event(
                    db,
                    event_name=row['event_name'],
                    kickoff_time_utc=row['kickoff_time_utc'],
                    league=row.get('league'),
                    sport=row.get('sport', 'football')
                )
                imported += 1
                print(f"✅ Imported: {row['event_name']}")
            except Exception as e:
                print(f"❌ Failed to import {row.get('event_name', 'unknown')}: {e}")

    return imported


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]
    db = get_db_connection()

    if command == "seed-markets":
        print("Seeding canonical markets...")
        count = seed_canonical_markets(db)
        print(f"Inserted {count} markets")

        # Display summary
        cursor = db.execute("SELECT COUNT(*) FROM canonical_markets")
        total = cursor.fetchone()[0]
        print(f"Total markets in database: {total}")

    elif command == "create-event":
        if len(sys.argv) < 4:
            print("Usage: python scripts/manage_canonical_data.py create-event <event_name> <kickoff_time_utc> [league] [sport]")
            sys.exit(1)

        event_name = sys.argv[2]
        kickoff_time = sys.argv[3]
        league = sys.argv[4] if len(sys.argv) > 4 else None
        sport = sys.argv[5] if len(sys.argv) > 5 else "football"

        event_id = create_canonical_event(db, event_name, kickoff_time, league, sport)
        print(f"✅ Created event #{event_id}: {event_name}")

    elif command == "find-similar":
        if len(sys.argv) < 3:
            print("Usage: python scripts/manage_canonical_data.py find-similar <event_name>")
            sys.exit(1)

        event_name = sys.argv[2]
        matches = find_similar_events(db, event_name)

        if matches:
            print(f"🔍 Found {len(matches)} similar events:")
            for event_id, name, score in matches:
                print(f"  #{event_id}: {name} (similarity: {score:.0%})")
        else:
            print("❌ No similar events found")

    elif command == "import-events":
        if len(sys.argv) < 3:
            print("Usage: python scripts/manage_canonical_data.py import-events <csv_file>")
            sys.exit(1)

        csv_path = sys.argv[2]
        count = import_events_from_csv(db, csv_path)
        print(f"✅ Imported {count} events from {csv_path}")

    else:
        print(f"❌ Unknown command: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
