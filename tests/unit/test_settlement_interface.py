"""
Unit tests for settlement interface helper functions.

Tests cover:
- Time calculation since kickoff
- Default bet outcome assignment
- Settlement validation logic
- Database queries for settlement data
"""

import pytest
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Literal, Optional
import sqlite3


# ========================================
# Duplicate Functions for Testing
# (These mirror the implementation in 2_verified_bets.py)
# ========================================


def calculate_time_since_kickoff(kickoff_time_utc: str) -> Dict[str, any]:  # type: ignore[valid-type]
    """
    Calculate time elapsed since kickoff.

    Args:
        kickoff_time_utc: ISO8601 UTC timestamp with Z suffix

    Returns:
        Dict with 'elapsed_hours', 'is_past', and 'display_text'
    """
    try:
        # Parse UTC timestamp (remove 'Z' suffix for datetime parsing)
        kickoff_dt = datetime.fromisoformat(kickoff_time_utc.replace("Z", "+00:00"))
        now = datetime.now(kickoff_dt.tzinfo)
        delta = now - kickoff_dt

        elapsed_hours = delta.total_seconds() / 3600
        is_past = elapsed_hours > 0

        if elapsed_hours < 1:
            display_text = (
                "Starting soon"
                if elapsed_hours > -1
                else f"In {abs(int(elapsed_hours))}h"
            )
        elif elapsed_hours < 24:
            display_text = f"Completed {int(elapsed_hours)}h ago"
        else:
            days = int(elapsed_hours / 24)
            display_text = f"Completed {days}d ago"

        return {
            "elapsed_hours": elapsed_hours,
            "is_past": is_past,
            "display_text": display_text,
        }
    except Exception:
        return {"elapsed_hours": 0, "is_past": False, "display_text": "Unknown"}


def get_default_bet_outcomes(
    bets: Dict[str, List[Dict]], base_outcome: Literal["A_WON", "B_WON"]
) -> Dict[int, str]:
    """
    Get default bet outcomes based on base outcome selection.

    Args:
        bets: Dictionary with 'A' and 'B' side bets
        base_outcome: Which side won ("A_WON" or "B_WON")

    Returns:
        Dictionary mapping bet_id to outcome ("WON", "LOST", "VOID")
    """
    outcomes = {}

    if base_outcome == "A_WON":
        # Side A bets default to WON
        for bet in bets.get("A", []):
            outcomes[bet["bet_id"]] = "WON"
        # Side B bets default to LOST
        for bet in bets.get("B", []):
            outcomes[bet["bet_id"]] = "LOST"
    else:  # B_WON
        # Side A bets default to LOST
        for bet in bets.get("A", []):
            outcomes[bet["bet_id"]] = "LOST"
        # Side B bets default to WON
        for bet in bets.get("B", []):
            outcomes[bet["bet_id"]] = "WON"

    return outcomes


def validate_settlement_submission(
    base_outcome: Optional[str], bet_outcomes: Dict[int, str]
) -> tuple[bool, str]:
    """
    Validate settlement submission before processing.

    Args:
        base_outcome: Selected base outcome ("A_WON" or "B_WON" or None)
        bet_outcomes: Dictionary of bet outcomes

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Check base outcome selected
    if not base_outcome:
        return False, "Please select a base outcome (Side A WON or Side B WON)"

    # Check if all bets are VOID
    if bet_outcomes:
        all_void = all(outcome == "VOID" for outcome in bet_outcomes.values())
        if all_void:
            return (
                False,
                "WARNING: All bets marked VOID. Please confirm this is correct.",
            )

    return True, ""


# ========================================
# Test Classes
# ========================================


class TestTimeCalculations:
    """Test kickoff time calculations and display text generation."""

    def test_past_kickoff_hours_ago(self):
        """Test kickoff time completed less than 24 hours ago."""
        # Create timestamp 5 hours ago
        kickoff = (datetime.utcnow() - timedelta(hours=5)).isoformat() + "Z"
        result = calculate_time_since_kickoff(kickoff)

        assert result["is_past"] is True
        assert result["elapsed_hours"] > 4
        assert result["elapsed_hours"] < 6
        assert "ago" in result["display_text"]

    def test_past_kickoff_days_ago(self):
        """Test kickoff time completed more than 24 hours ago."""
        # Create timestamp 48 hours ago
        kickoff = (datetime.utcnow() - timedelta(hours=48)).isoformat() + "Z"
        result = calculate_time_since_kickoff(kickoff)

        assert result["is_past"] is True
        assert result["elapsed_hours"] > 47
        assert "d ago" in result["display_text"]

    def test_future_kickoff(self):
        """Test future kickoff time."""
        # Create timestamp 3 hours in future
        kickoff = (datetime.utcnow() + timedelta(hours=3)).isoformat() + "Z"
        result = calculate_time_since_kickoff(kickoff)

        assert result["is_past"] is False
        assert result["elapsed_hours"] < 0

    def test_starting_soon(self):
        """Test kickoff time within next hour."""
        # Create timestamp 30 minutes in future
        kickoff = (datetime.utcnow() + timedelta(minutes=30)).isoformat() + "Z"
        result = calculate_time_since_kickoff(kickoff)

        assert result["is_past"] is False
        assert (
            "Starting soon" in result["display_text"] or "In" in result["display_text"]
        )


class TestDefaultOutcomeAssignment:
    """Test default bet outcome assignment based on base outcome."""

    def test_side_a_won_defaults(self):
        """Test when Side A wins, A bets are WON and B bets are LOST."""
        bets = {
            "A": [{"bet_id": 1}, {"bet_id": 2}],
            "B": [{"bet_id": 3}, {"bet_id": 4}],
        }

        outcomes = get_default_bet_outcomes(bets, "A_WON")

        assert outcomes[1] == "WON"
        assert outcomes[2] == "WON"
        assert outcomes[3] == "LOST"
        assert outcomes[4] == "LOST"

    def test_side_b_won_defaults(self):
        """Test when Side B wins, B bets are WON and A bets are LOST."""
        bets = {
            "A": [{"bet_id": 10}, {"bet_id": 11}],
            "B": [{"bet_id": 20}, {"bet_id": 21}],
        }

        outcomes = get_default_bet_outcomes(bets, "B_WON")

        assert outcomes[10] == "LOST"
        assert outcomes[11] == "LOST"
        assert outcomes[20] == "WON"
        assert outcomes[21] == "WON"

    def test_empty_side(self):
        """Test outcome assignment when one side has no bets."""
        bets = {
            "A": [{"bet_id": 100}],
            "B": [],
        }

        outcomes = get_default_bet_outcomes(bets, "A_WON")

        assert outcomes[100] == "WON"
        assert len(outcomes) == 1


class TestSettlementValidation:
    """Test settlement submission validation logic."""

    def test_validation_passes_with_base_outcome(self):
        """Test validation passes when base outcome is selected."""
        is_valid, error = validate_settlement_submission("A_WON", {1: "WON", 2: "LOST"})

        assert is_valid is True
        assert error == ""

    def test_validation_fails_without_base_outcome(self):
        """Test validation fails when no base outcome selected."""
        is_valid, error = validate_settlement_submission(None, {1: "WON"})

        assert is_valid is False
        assert "select a base outcome" in error.lower()

    def test_validation_warns_all_void(self):
        """Test validation warns when all bets are VOID."""
        is_valid, error = validate_settlement_submission(
            "A_WON", {1: "VOID", 2: "VOID"}
        )

        assert is_valid is False
        assert "void" in error.lower()

    def test_validation_passes_mixed_outcomes(self):
        """Test validation passes with mix of WON/LOST/VOID."""
        is_valid, error = validate_settlement_submission(
            "B_WON", {1: "LOST", 2: "WON", 3: "VOID"}
        )

        assert is_valid is True
        assert error == ""


class TestDatabaseQueries:
    """Test settlement interface database query patterns."""

    @pytest.fixture
    def test_db(self):
        """Create in-memory test database with minimal schema."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row

        # Create minimal schema
        conn.execute(
            """
            CREATE TABLE canonical_events (
                id INTEGER PRIMARY KEY,
                normalized_event_name TEXT,
                kickoff_time_utc TEXT,
                sport TEXT,
                league TEXT
            )
        """
        )

        conn.execute(
            """
            CREATE TABLE surebets (
                id INTEGER PRIMARY KEY,
                canonical_event_id INTEGER,
                market_code TEXT,
                period_scope TEXT,
                line_value TEXT,
                status TEXT,
                settled_at_utc TEXT,
                coverage_proof_sent_at_utc TEXT,
                created_at_utc TEXT
            )
        """
        )

        yield conn
        conn.close()

    def test_count_open_surebets(self, test_db):
        """Test counting open surebets."""
        # Insert test data
        test_db.execute(
            """INSERT INTO canonical_events (id, normalized_event_name, kickoff_time_utc, sport, league)
               VALUES (1, 'Test Event', '2025-11-05T20:00:00Z', 'Football', 'Test League')"""
        )

        test_db.execute(
            """INSERT INTO surebets (id, canonical_event_id, market_code, period_scope, status, created_at_utc)
               VALUES (1, 1, 'TOTAL_POINTS', 'FULL_MATCH', 'open', '2025-11-03T10:00:00Z')"""
        )

        test_db.execute(
            """INSERT INTO surebets (id, canonical_event_id, market_code, period_scope, status, created_at_utc)
               VALUES (2, 1, 'TOTAL_POINTS', 'FULL_MATCH', 'settled', '2025-11-03T09:00:00Z')"""
        )

        test_db.commit()

        # Query
        count = test_db.execute(
            "SELECT COUNT(*) as cnt FROM surebets WHERE status = 'open'"
        ).fetchone()["cnt"]

        assert count == 1

    def test_count_settled_today(self, test_db):
        """Test counting settled surebets today."""
        today_start = (
            datetime.utcnow()
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .isoformat()
            + "Z"
        )

        # Insert test data
        test_db.execute(
            """INSERT INTO canonical_events (id, normalized_event_name, kickoff_time_utc, sport, league)
               VALUES (1, 'Test Event', '2025-11-05T20:00:00Z', 'Football', 'Test League')"""
        )

        test_db.execute(
            f"""INSERT INTO surebets (id, canonical_event_id, market_code, period_scope, status, settled_at_utc, created_at_utc)
               VALUES (1, 1, 'TOTAL_POINTS', 'FULL_MATCH', 'settled', '{today_start}', '2025-11-03T10:00:00Z')"""
        )

        test_db.execute(
            """INSERT INTO surebets (id, canonical_event_id, market_code, period_scope, status, settled_at_utc, created_at_utc)
               VALUES (2, 1, 'TOTAL_POINTS', 'FULL_MATCH', 'settled', '2025-10-01T10:00:00Z', '2025-10-01T09:00:00Z')"""
        )

        test_db.commit()

        # Query
        count = test_db.execute(
            """SELECT COUNT(*) as cnt FROM surebets
               WHERE status = 'settled' AND settled_at_utc >= ?""",
            (today_start,),
        ).fetchone()["cnt"]

        assert count == 1

    def test_kickoff_time_sorting(self, test_db):
        """Test that surebets are sorted by kickoff time (oldest first)."""
        # Insert events with different kickoff times
        test_db.execute(
            """INSERT INTO canonical_events (id, normalized_event_name, kickoff_time_utc, sport, league)
               VALUES
               (1, 'Event 1', '2025-11-05T20:00:00Z', 'Football', 'League A'),
               (2, 'Event 2', '2025-11-04T18:00:00Z', 'Football', 'League B'),
               (3, 'Event 3', '2025-11-06T22:00:00Z', 'Football', 'League C')"""
        )

        test_db.execute(
            """INSERT INTO surebets (id, canonical_event_id, market_code, period_scope, status, created_at_utc)
               VALUES
               (1, 1, 'TOTAL_POINTS', 'FULL_MATCH', 'open', '2025-11-03T10:00:00Z'),
               (2, 2, 'TOTAL_POINTS', 'FULL_MATCH', 'open', '2025-11-03T09:00:00Z'),
               (3, 3, 'TOTAL_POINTS', 'FULL_MATCH', 'open', '2025-11-03T11:00:00Z')"""
        )

        test_db.commit()

        # Query with kickoff time sort
        rows = test_db.execute(
            """
            SELECT s.id, e.kickoff_time_utc
            FROM surebets s
            JOIN canonical_events e ON s.canonical_event_id = e.id
            WHERE s.status = 'open'
            ORDER BY e.kickoff_time_utc ASC
        """
        ).fetchall()

        # Should be sorted: Event 2 (Nov 4), Event 1 (Nov 5), Event 3 (Nov 6)
        assert rows[0]["id"] == 2
        assert rows[1]["id"] == 1
        assert rows[2]["id"] == 3
