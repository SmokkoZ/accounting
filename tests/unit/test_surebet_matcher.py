"""
Unit tests for SurebetMatcher service.

Tests cover:
- Deterministic side assignment
- Matching opposite-side bets
- Multiple bets on same side
- Idempotency
- Unsupported bet filtering
- Edge cases and error handling
"""

import pytest
import sqlite3
from datetime import datetime

from src.services.surebet_matcher import SurebetMatcher
from src.core.schema import create_schema
from src.core.seed_data import insert_seed_data


@pytest.fixture
def test_db():
    """Create an in-memory test database."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    insert_seed_data(conn)
    yield conn
    conn.close()


@pytest.fixture
def matcher(test_db):
    """Create a SurebetMatcher instance with test database."""
    return SurebetMatcher(test_db)


@pytest.fixture
def canonical_event(test_db):
    """Create a canonical event for testing."""
    cursor = test_db.execute(
        """
        INSERT INTO canonical_events (
            normalized_event_name, sport, league, kickoff_time_utc
        )
        VALUES ('Team A vs Team B', 'football', 'Premier League', '2025-11-01T15:00:00Z')
        """
    )
    test_db.commit()
    return cursor.lastrowid


def create_verified_bet(
    db,
    canonical_event_id,
    market_code="TOTAL_GOALS_OVER_UNDER",
    period_scope="FULL_MATCH",
    line_value="2.5",
    side="OVER",
    is_supported=1,
):
    """Helper to create a verified bet."""
    cursor = db.execute(
        """
        INSERT INTO bets (
            associate_id, bookmaker_id, status, stake_eur, odds,
            currency, stake_original, odds_original, payout,
            canonical_event_id, market_code, period_scope, line_value,
            side, is_supported, ingestion_source
        )
        VALUES (?, ?, 'verified', '100.00', '1.90', 'USD', '100.00', '1.90', '190.00',
                ?, ?, ?, ?, ?, ?, 'telegram')
        """,
        (
            1,
            1,
            canonical_event_id,
            market_code,
            period_scope,
            line_value,
            side,
            is_supported,
        ),
    )
    db.commit()
    return cursor.lastrowid


class TestDeterministicSideAssignment:
    """Test deterministic side assignment (A/B mapping)."""

    def test_determine_side_over_maps_to_a(self, matcher):
        """Given: OVER side; When: determine_side called; Then: returns 'A'"""
        assert matcher.determine_side("OVER") == "A"

    def test_determine_side_under_maps_to_b(self, matcher):
        """Given: UNDER side; When: determine_side called; Then: returns 'B'"""
        assert matcher.determine_side("UNDER") == "B"

    def test_determine_side_yes_maps_to_a(self, matcher):
        """Given: YES side; When: determine_side called; Then: returns 'A'"""
        assert matcher.determine_side("YES") == "A"

    def test_determine_side_no_maps_to_b(self, matcher):
        """Given: NO side; When: determine_side called; Then: returns 'B'"""
        assert matcher.determine_side("NO") == "B"

    def test_determine_side_team_a_maps_to_a(self, matcher):
        """Given: TEAM_A side; When: determine_side called; Then: returns 'A'"""
        assert matcher.determine_side("TEAM_A") == "A"

    def test_determine_side_team_b_maps_to_b(self, matcher):
        """Given: TEAM_B side; When: determine_side called; Then: returns 'B'"""
        assert matcher.determine_side("TEAM_B") == "B"

    def test_determine_side_invalid_raises_error(self, matcher):
        """Given: Invalid side; When: determine_side called; Then: raises ValueError"""
        with pytest.raises(ValueError, match="Unknown side enum"):
            matcher.determine_side("INVALID_SIDE")


class TestMatchingAlgorithm:
    """Test matching algorithm with opposite-side bets."""

    def test_match_over_with_under(self, matcher, test_db, canonical_event):
        """
        Given: Verified OVER bet and verified UNDER bet on same event/market
        When: attempt_match called on OVER bet
        Then: Surebet created, both bets linked with correct sides, status updated to 'matched'
        """
        # Arrange
        bet_over_id = create_verified_bet(
            test_db, canonical_event, side="OVER"
        )
        bet_under_id = create_verified_bet(
            test_db, canonical_event, side="UNDER"
        )

        # Act
        surebet_id = matcher.attempt_match(bet_over_id)

        # Assert
        assert surebet_id is not None

        # Check surebet created
        surebet = test_db.execute(
            "SELECT * FROM surebets WHERE id = ?", (surebet_id,)
        ).fetchone()
        assert surebet is not None
        assert surebet["status"] == "open"
        assert surebet["canonical_event_id"] == canonical_event
        assert surebet["market_code"] == "TOTAL_GOALS_OVER_UNDER"

        # Check bet links
        links = test_db.execute(
            "SELECT * FROM surebet_bets WHERE surebet_id = ? ORDER BY bet_id",
            (surebet_id,),
        ).fetchall()
        assert len(links) == 2
        assert links[0]["bet_id"] == bet_over_id
        assert links[0]["side"] == "A"  # OVER -> A
        assert links[1]["bet_id"] == bet_under_id
        assert links[1]["side"] == "B"  # UNDER -> B

        # Check bet statuses updated
        bet_over = test_db.execute(
            "SELECT status FROM bets WHERE id = ?", (bet_over_id,)
        ).fetchone()
        bet_under = test_db.execute(
            "SELECT status FROM bets WHERE id = ?", (bet_under_id,)
        ).fetchone()
        assert bet_over["status"] == "matched"
        assert bet_under["status"] == "matched"

    def test_match_yes_with_no(self, matcher, test_db, canonical_event):
        """
        Given: YES and NO bets on same event/market
        When: attempt_match called
        Then: Bets matched with correct side assignment
        """
        # Arrange
        bet_yes_id = create_verified_bet(
            test_db,
            canonical_event,
            market_code="BOTH_TEAMS_TO_SCORE",
            line_value=None,
            side="YES",
        )
        bet_no_id = create_verified_bet(
            test_db,
            canonical_event,
            market_code="BOTH_TEAMS_TO_SCORE",
            line_value=None,
            side="NO",
        )

        # Act
        surebet_id = matcher.attempt_match(bet_yes_id)

        # Assert
        assert surebet_id is not None

        links = test_db.execute(
            "SELECT * FROM surebet_bets WHERE surebet_id = ? ORDER BY bet_id",
            (surebet_id,),
        ).fetchall()
        assert len(links) == 2
        assert links[0]["side"] == "A"  # YES -> A
        assert links[1]["side"] == "B"  # NO -> B

    def test_match_team_a_with_team_b(self, matcher, test_db, canonical_event):
        """
        Given: TEAM_A and TEAM_B bets on same event/market
        When: attempt_match called
        Then: Bets matched with correct side assignment
        """
        # Arrange
        bet_team_a_id = create_verified_bet(
            test_db,
            canonical_event,
            market_code="MATCH_WINNER",
            line_value=None,
            side="TEAM_A",
        )
        bet_team_b_id = create_verified_bet(
            test_db,
            canonical_event,
            market_code="MATCH_WINNER",
            line_value=None,
            side="TEAM_B",
        )

        # Act
        surebet_id = matcher.attempt_match(bet_team_a_id)

        # Assert
        assert surebet_id is not None

        links = test_db.execute(
            "SELECT * FROM surebet_bets WHERE surebet_id = ? ORDER BY bet_id",
            (surebet_id,),
        ).fetchall()
        assert len(links) == 2
        assert links[0]["side"] == "A"  # TEAM_A -> A
        assert links[1]["side"] == "B"  # TEAM_B -> B

    def test_no_match_without_opposite_side(self, matcher, test_db, canonical_event):
        """
        Given: Only OVER bet (no UNDER bet)
        When: attempt_match called
        Then: No surebet created, bet remains 'verified'
        """
        # Arrange
        bet_over_id = create_verified_bet(
            test_db, canonical_event, side="OVER"
        )

        # Act
        surebet_id = matcher.attempt_match(bet_over_id)

        # Assert
        assert surebet_id is None

        # Bet should still be verified
        bet = test_db.execute(
            "SELECT status FROM bets WHERE id = ?", (bet_over_id,)
        ).fetchone()
        assert bet["status"] == "verified"

    def test_match_requires_same_canonical_event(
        self, matcher, test_db, canonical_event
    ):
        """
        Given: OVER and UNDER bets on different events
        When: attempt_match called
        Then: No match created
        """
        # Arrange
        # Create second event
        cursor = test_db.execute(
            """
            INSERT INTO canonical_events (
                normalized_event_name, sport, league, kickoff_time_utc
            )
            VALUES ('Team C vs Team D', 'football', 'Premier League', '2025-11-01T15:00:00Z')
            """
        )
        test_db.commit()
        event2_id = cursor.lastrowid

        bet_over_id = create_verified_bet(
            test_db, canonical_event, side="OVER"
        )
        bet_under_id = create_verified_bet(
            test_db, event2_id, side="UNDER"
        )

        # Act
        surebet_id = matcher.attempt_match(bet_over_id)

        # Assert
        assert surebet_id is None

    def test_match_requires_same_market_code(
        self, matcher, test_db, canonical_event
    ):
        """
        Given: OVER and UNDER bets on different markets
        When: attempt_match called
        Then: No match created
        """
        # Arrange
        bet_over_id = create_verified_bet(
            test_db,
            canonical_event,
            market_code="TOTAL_GOALS_OVER_UNDER",
            side="OVER",
        )
        bet_under_id = create_verified_bet(
            test_db,
            canonical_event,
            market_code="FIRST_HALF_TOTAL_GOALS",
            side="UNDER",
        )

        # Act
        surebet_id = matcher.attempt_match(bet_over_id)

        # Assert
        assert surebet_id is None

    def test_match_requires_same_line_value(
        self, matcher, test_db, canonical_event
    ):
        """
        Given: OVER 2.5 and UNDER 3.5
        When: attempt_match called
        Then: No match created (different line values)
        """
        # Arrange
        bet_over_id = create_verified_bet(
            test_db, canonical_event, line_value="2.5", side="OVER"
        )
        bet_under_id = create_verified_bet(
            test_db, canonical_event, line_value="3.5", side="UNDER"
        )

        # Act
        surebet_id = matcher.attempt_match(bet_over_id)

        # Assert
        assert surebet_id is None


class TestMultipleBetsOnSameSide:
    """Test handling multiple bets on same side (A1 + A2 vs B1)."""

    def test_multiple_overs_vs_single_under(
        self, matcher, test_db, canonical_event
    ):
        """
        Given: Two OVER bets (A1, A2) and one UNDER bet (B1)
        When: Each bet triggers matching (simulating approval workflow)
        Then: All three bets linked to same surebet with correct sides
        """
        # Arrange
        bet_over1_id = create_verified_bet(
            test_db, canonical_event, side="OVER"
        )
        bet_over2_id = create_verified_bet(
            test_db, canonical_event, side="OVER"
        )
        bet_under_id = create_verified_bet(
            test_db, canonical_event, side="UNDER"
        )

        # Act - match each bet (simulates approval workflow where each approved bet triggers matching)
        surebet_id_1 = matcher.attempt_match(bet_over1_id)
        surebet_id_2 = matcher.attempt_match(bet_over2_id)

        # Assert - both should return same surebet_id
        assert surebet_id_1 is not None
        assert surebet_id_2 == surebet_id_1

        # Check all bets linked to same surebet
        links = test_db.execute(
            "SELECT * FROM surebet_bets WHERE surebet_id = ? ORDER BY bet_id",
            (surebet_id_1,),
        ).fetchall()
        assert len(links) == 3

        # Verify side assignments
        bet_ids_to_sides = {link["bet_id"]: link["side"] for link in links}
        assert bet_ids_to_sides[bet_over1_id] == "A"
        assert bet_ids_to_sides[bet_over2_id] == "A"
        assert bet_ids_to_sides[bet_under_id] == "B"

        # All bets should be matched
        for bet_id in [bet_over1_id, bet_over2_id, bet_under_id]:
            bet = test_db.execute(
                "SELECT status FROM bets WHERE id = ?", (bet_id,)
            ).fetchone()
            assert bet["status"] == "matched"


class TestMatchingIdempotency:
    """Test idempotent matching (re-running on already matched bet)."""

    def test_attempt_match_on_already_matched_bet(
        self, matcher, test_db, canonical_event
    ):
        """
        Given: Bet already matched to a surebet
        When: attempt_match called again
        Then: Returns existing surebet_id, no duplicate links created
        """
        # Arrange
        bet_over_id = create_verified_bet(
            test_db, canonical_event, side="OVER"
        )
        bet_under_id = create_verified_bet(
            test_db, canonical_event, side="UNDER"
        )

        # First match
        surebet_id_1 = matcher.attempt_match(bet_over_id)

        # Act - attempt to match again
        surebet_id_2 = matcher.attempt_match(bet_over_id)

        # Assert
        assert surebet_id_1 == surebet_id_2

        # Verify no duplicate links
        links = test_db.execute(
            "SELECT COUNT(*) as count FROM surebet_bets WHERE bet_id = ?",
            (bet_over_id,),
        ).fetchone()
        assert links["count"] == 1

    def test_attempt_match_on_verified_bet_multiple_times(
        self, matcher, test_db, canonical_event
    ):
        """
        Given: Verified bet without opposite
        When: attempt_match called multiple times
        Then: Returns None each time, no state corruption
        """
        # Arrange
        bet_over_id = create_verified_bet(
            test_db, canonical_event, side="OVER"
        )

        # Act
        result1 = matcher.attempt_match(bet_over_id)
        result2 = matcher.attempt_match(bet_over_id)

        # Assert
        assert result1 is None
        assert result2 is None

        # Bet should still be verified
        bet = test_db.execute(
            "SELECT status FROM bets WHERE id = ?", (bet_over_id,)
        ).fetchone()
        assert bet["status"] == "verified"


class TestUnsupportedBetFiltering:
    """Test filtering of unsupported bet types."""

    def test_unsupported_bet_not_matched(
        self, matcher, test_db, canonical_event
    ):
        """
        Given: Unsupported bet (is_supported=0) with opposite verified bet
        When: attempt_match called on unsupported bet
        Then: No match created
        """
        # Arrange
        bet_over_id = create_verified_bet(
            test_db, canonical_event, side="OVER", is_supported=0
        )
        bet_under_id = create_verified_bet(
            test_db, canonical_event, side="UNDER", is_supported=1
        )

        # Act
        surebet_id = matcher.attempt_match(bet_over_id)

        # Assert
        assert surebet_id is None

        # Bet should remain verified (not matched)
        bet = test_db.execute(
            "SELECT status FROM bets WHERE id = ?", (bet_over_id,)
        ).fetchone()
        assert bet["status"] == "verified"

    def test_matching_query_excludes_unsupported_candidates(
        self, matcher, test_db, canonical_event
    ):
        """
        Given: Supported OVER bet and unsupported UNDER bet
        When: attempt_match called on OVER bet
        Then: No match created (unsupported candidate excluded)
        """
        # Arrange
        bet_over_id = create_verified_bet(
            test_db, canonical_event, side="OVER", is_supported=1
        )
        bet_under_id = create_verified_bet(
            test_db, canonical_event, side="UNDER", is_supported=0
        )

        # Act
        surebet_id = matcher.attempt_match(bet_over_id)

        # Assert
        assert surebet_id is None


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_attempt_match_on_nonexistent_bet(self, matcher):
        """
        Given: Bet ID that doesn't exist
        When: attempt_match called
        Then: Raises ValueError
        """
        with pytest.raises(ValueError, match="Bet .* not found"):
            matcher.attempt_match(99999)

    def test_attempt_match_on_incoming_bet(
        self, matcher, test_db, canonical_event
    ):
        """
        Given: Bet in 'incoming' status
        When: attempt_match called
        Then: Returns None (not verified yet)
        """
        # Arrange
        cursor = test_db.execute(
            """
            INSERT INTO bets (
                associate_id, bookmaker_id, status, stake_eur, odds,
                currency, stake_original, odds_original, payout,
                canonical_event_id, market_code, period_scope, line_value,
                side, is_supported, ingestion_source
            )
            VALUES (?, ?, 'incoming', '100.00', '1.90', 'USD', '100.00', '1.90', '190.00',
                    ?, 'TOTAL_GOALS_OVER_UNDER', 'FULL_MATCH', '2.5', 'OVER', 1, 'telegram')
            """,
            (1, 1, canonical_event),
        )
        test_db.commit()
        bet_id = cursor.lastrowid

        # Act
        surebet_id = matcher.attempt_match(bet_id)

        # Assert
        assert surebet_id is None

    def test_bet_missing_canonical_event_id(
        self, matcher, test_db
    ):
        """
        Given: Verified bet without canonical_event_id
        When: attempt_match called
        Then: Returns None (missing required field)
        """
        # Arrange
        cursor = test_db.execute(
            """
            INSERT INTO bets (
                associate_id, bookmaker_id, status, stake_eur, odds,
                currency, stake_original, odds_original, payout,
                canonical_event_id, market_code, period_scope, line_value,
                side, is_supported, ingestion_source
            )
            VALUES (?, ?, 'verified', '100.00', '1.90', 'USD', '100.00', '1.90', '190.00',
                    NULL, 'TOTAL_GOALS_OVER_UNDER', 'FULL_MATCH', '2.5', 'OVER', 1, 'telegram')
            """,
            (1, 1),
        )
        test_db.commit()
        bet_id = cursor.lastrowid

        # Act
        surebet_id = matcher.attempt_match(bet_id)

        # Assert
        assert surebet_id is None

    def test_match_with_null_line_values(
        self, matcher, test_db, canonical_event
    ):
        """
        Given: YES and NO bets with NULL line_value
        When: attempt_match called
        Then: Bets matched successfully
        """
        # Arrange
        bet_yes_id = create_verified_bet(
            test_db,
            canonical_event,
            market_code="BOTH_TEAMS_TO_SCORE",
            line_value=None,
            side="YES",
        )
        bet_no_id = create_verified_bet(
            test_db,
            canonical_event,
            market_code="BOTH_TEAMS_TO_SCORE",
            line_value=None,
            side="NO",
        )

        # Act
        surebet_id = matcher.attempt_match(bet_yes_id)

        # Assert
        assert surebet_id is not None

        # Check surebet has NULL line_value
        surebet = test_db.execute(
            "SELECT line_value FROM surebets WHERE id = ?", (surebet_id,)
        ).fetchone()
        assert surebet["line_value"] is None

    def test_add_bet_to_existing_surebet(
        self, matcher, test_db, canonical_event
    ):
        """
        Given: Existing surebet with A and B sides, new A-side bet arrives
        When: attempt_match called on new bet
        Then: New bet added to existing surebet
        """
        # Arrange - Create initial surebet with 1 OVER and 1 UNDER
        bet_over1_id = create_verified_bet(
            test_db, canonical_event, side="OVER"
        )
        bet_under_id = create_verified_bet(
            test_db, canonical_event, side="UNDER"
        )
        surebet_id_initial = matcher.attempt_match(bet_over1_id)

        # Create new OVER bet
        bet_over2_id = create_verified_bet(
            test_db, canonical_event, side="OVER"
        )

        # Act
        surebet_id_new = matcher.attempt_match(bet_over2_id)

        # Assert
        assert surebet_id_new == surebet_id_initial  # Same surebet

        # Check all 3 bets linked
        links = test_db.execute(
            "SELECT COUNT(*) as count FROM surebet_bets WHERE surebet_id = ?",
            (surebet_id_initial,),
        ).fetchone()
        assert links["count"] == 3
