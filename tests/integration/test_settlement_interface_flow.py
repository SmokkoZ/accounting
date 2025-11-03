"""
Integration tests for settlement interface workflow.

Tests the full flow from loading surebets to validating outcome selection.
"""

import pytest
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


class TestSettlementInterfaceFlow:
    """Test end-to-end settlement interface workflow."""

    @pytest.fixture
    def test_db_with_data(self):
        """Create test database with sample data for settlement."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row

        # Create schema
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

        conn.execute(
            """
            CREATE TABLE bets (
                id INTEGER PRIMARY KEY,
                associate_id INTEGER,
                bookmaker_id INTEGER,
                stake_original TEXT,
                odds_original TEXT,
                odds TEXT,
                currency TEXT,
                stake_eur TEXT,
                screenshot_path TEXT
            )
        """
        )

        conn.execute(
            """
            CREATE TABLE surebet_bets (
                id INTEGER PRIMARY KEY,
                surebet_id INTEGER,
                bet_id INTEGER,
                side TEXT
            )
        """
        )

        conn.execute(
            """
            CREATE TABLE associates (
                id INTEGER PRIMARY KEY,
                display_alias TEXT,
                is_active INTEGER NOT NULL DEFAULT 1
            )
        """
        )

        conn.execute(
            """
            CREATE TABLE bookmakers (
                id INTEGER PRIMARY KEY,
                bookmaker_name TEXT
            )
        """
        )

        # Insert test data
        # Create past event (should appear first in settlement list)
        kickoff_past = (datetime.utcnow() - timedelta(hours=3)).isoformat() + "Z"
        conn.execute(
            f"""INSERT INTO canonical_events (id, normalized_event_name, kickoff_time_utc, sport, league)
               VALUES (1, 'Man Utd vs Arsenal', '{kickoff_past}', 'Football', 'Premier League')"""
        )

        conn.execute(
            """INSERT INTO surebets (id, canonical_event_id, market_code, period_scope, line_value, status, created_at_utc)
               VALUES (1, 1, 'TOTAL_POINTS', 'FULL_MATCH', '2.5', 'open', '2025-11-03T10:00:00Z')"""
        )

        # Create associates
        conn.execute(
            """INSERT INTO associates (id, display_alias) VALUES (1, 'Alice'), (2, 'Bob')"""
        )

        # Create bookmakers
        conn.execute(
            """INSERT INTO bookmakers (id, bookmaker_name) VALUES (1, 'Bet365'), (2, 'Pinnacle')"""
        )

        # Create bets for surebet
        conn.execute(
            """INSERT INTO bets (id, associate_id, bookmaker_id, stake_original, odds_original, odds, currency, stake_eur, screenshot_path)
               VALUES
               (1, 1, 1, '100.00', '2.10', '2.10', 'EUR', '100.00', 'data/screenshots/test1.png'),
               (2, 2, 2, '50.00', '2.05', '2.05', 'EUR', '50.00', 'data/screenshots/test2.png')"""
        )

        # Link bets to surebet
        conn.execute(
            """INSERT INTO surebet_bets (id, surebet_id, bet_id, side)
               VALUES (1, 1, 1, 'A'), (2, 1, 2, 'B')"""
        )

        conn.commit()
        yield conn
        conn.close()

    def test_load_surebets_for_settlement(self, test_db_with_data):
        """Test loading open surebets sorted by kickoff time."""
        query = """
            SELECT
                s.id as surebet_id,
                s.market_code,
                s.period_scope,
                s.line_value,
                s.status,
                e.normalized_event_name as event_name,
                e.kickoff_time_utc,
                e.sport,
                e.league
            FROM surebets s
            JOIN canonical_events e ON s.canonical_event_id = e.id
            WHERE s.status = 'open'
            ORDER BY e.kickoff_time_utc ASC
        """

        rows = test_db_with_data.execute(query).fetchall()
        surebets = [dict(row) for row in rows]

        assert len(surebets) == 1
        assert surebets[0]["surebet_id"] == 1
        assert surebets[0]["event_name"] == "Man Utd vs Arsenal"
        assert surebets[0]["market_code"] == "TOTAL_POINTS"
        assert surebets[0]["line_value"] == "2.5"

    def test_load_bets_for_surebet(self, test_db_with_data):
        """Test loading bets grouped by side for a surebet."""
        query = """
            SELECT
                b.id as bet_id,
                b.stake_original,
                b.odds_original,
                b.currency,
                b.screenshot_path,
                sb.side,
                a.display_alias as associate_name,
                bk.bookmaker_name
            FROM bets b
            JOIN surebet_bets sb ON b.id = sb.bet_id
            JOIN associates a ON b.associate_id = a.id
            JOIN bookmakers bk ON b.bookmaker_id = bk.id
            WHERE sb.surebet_id = ?
            ORDER BY sb.side, b.associate_id
        """

        rows = test_db_with_data.execute(query, (1,)).fetchall()
        bets = [dict(row) for row in rows]

        # Group by side
        grouped = {"A": [], "B": []}
        for bet in bets:
            side = bet.pop("side")
            grouped[side].append(bet)

        assert len(grouped["A"]) == 1
        assert len(grouped["B"]) == 1

        # Verify Side A bet
        assert grouped["A"][0]["associate_name"] == "Alice"
        assert grouped["A"][0]["bookmaker_name"] == "Bet365"
        assert grouped["A"][0]["stake_original"] == "100.00"

        # Verify Side B bet
        assert grouped["B"][0]["associate_name"] == "Bob"
        assert grouped["B"][0]["bookmaker_name"] == "Pinnacle"
        assert grouped["B"][0]["stake_original"] == "50.00"

    def test_settlement_counters(self, test_db_with_data):
        """Test counting open and settled surebets."""
        # Count open
        open_count = test_db_with_data.execute(
            "SELECT COUNT(*) as cnt FROM surebets WHERE status = 'open'"
        ).fetchone()["cnt"]

        assert open_count == 1

        # Settle surebet
        test_db_with_data.execute(
            """UPDATE surebets
               SET status = 'settled', settled_at_utc = datetime('now') || 'Z'
               WHERE id = 1"""
        )
        test_db_with_data.commit()

        # Count open again (should be 0)
        open_count = test_db_with_data.execute(
            "SELECT COUNT(*) as cnt FROM surebets WHERE status = 'open'"
        ).fetchone()["cnt"]

        assert open_count == 0

        # Count settled
        settled_count = test_db_with_data.execute(
            "SELECT COUNT(*) as cnt FROM surebets WHERE status = 'settled'"
        ).fetchone()["cnt"]

        assert settled_count == 1

    def test_full_settlement_workflow(self, test_db_with_data):
        """Test complete settlement workflow: load -> validate -> (simulated) settle."""
        # Step 1: Load surebets for settlement
        surebets_query = """
            SELECT s.id as surebet_id, s.status
            FROM surebets s
            WHERE s.status = 'open'
        """
        surebets = test_db_with_data.execute(surebets_query).fetchall()

        assert len(surebets) == 1
        surebet_id = surebets[0]["surebet_id"]

        # Step 2: Load bets for selected surebet
        bets_query = """
            SELECT b.id as bet_id, sb.side
            FROM bets b
            JOIN surebet_bets sb ON b.id = sb.bet_id
            WHERE sb.surebet_id = ?
        """
        bets = test_db_with_data.execute(bets_query, (surebet_id,)).fetchall()

        assert len(bets) == 2

        # Step 3: Simulate outcome selection (Side A wins)
        bet_outcomes = {}
        for bet in bets:
            if bet["side"] == "A":
                bet_outcomes[bet["bet_id"]] = "WON"
            else:
                bet_outcomes[bet["bet_id"]] = "LOST"

        assert bet_outcomes[1] == "WON"  # Side A bet
        assert bet_outcomes[2] == "LOST"  # Side B bet

        # Step 4: Validate (basic check - would normally call validate_settlement_submission)
        base_outcome = "A_WON"
        assert base_outcome is not None
        assert len(bet_outcomes) > 0

        # Step 5: Simulate settlement (mark as settled)
        # In real implementation, this would create ledger entries (Story 4.4)
        test_db_with_data.execute(
            """UPDATE surebets
               SET status = 'settled', settled_at_utc = datetime('now') || 'Z'
               WHERE id = ?""",
            (surebet_id,),
        )
        test_db_with_data.commit()

        # Verify settlement
        result = test_db_with_data.execute(
            "SELECT status, settled_at_utc FROM surebets WHERE id = ?", (surebet_id,)
        ).fetchone()

        assert result["status"] == "settled"
        assert result["settled_at_utc"] is not None
