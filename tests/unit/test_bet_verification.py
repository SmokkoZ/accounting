"""
Unit tests for BetVerificationService.

Tests cover:
- Bet approval workflow
- Bet rejection workflow
- Field validation
- Audit logging
- Canonical event/market loading
"""

import pytest
import sqlite3
from decimal import Decimal
from datetime import datetime

from src.services.bet_verification import BetVerificationService
from src.core.database import get_db_connection
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
def verification_service(test_db):
    """Create a BetVerificationService instance with test database."""
    return BetVerificationService(test_db)


@pytest.fixture
def sample_bet(test_db):
    """Create a sample incoming bet for testing."""
    cursor = test_db.execute(
        """
        INSERT INTO bets (
            associate_id, bookmaker_id, status, stake_eur, odds, currency,
            stake_original, odds_original, payout, ingestion_source
        ) VALUES (?, ?, 'incoming', '100.00', '1.90', 'AUD', '100.00', '1.90', '190.00', 'manual_upload')
        """,
        (1, 1),
    )
    test_db.commit()
    return cursor.lastrowid


class TestBetApproval:
    """Test bet approval workflow."""

    def test_approve_bet_without_edits(self, verification_service, sample_bet, test_db):
        """Test approving a bet without any edits."""
        # Arrange
        bet_id = sample_bet

        # Act
        verification_service.approve_bet(bet_id)

        # Assert
        bet = test_db.execute("SELECT * FROM bets WHERE id = ?", (bet_id,)).fetchone()
        assert bet["status"] == "verified"
        assert bet["updated_at_utc"] is not None

        # Check audit log
        audit = test_db.execute(
            "SELECT * FROM verification_audit WHERE bet_id = ? AND action = 'VERIFIED'",
            (bet_id,),
        ).fetchone()
        assert audit is not None
        assert audit["actor"] == "local_user"

    def test_approve_bet_with_edits(self, verification_service, sample_bet, test_db):
        """Test approving a bet with field edits."""
        # Arrange
        bet_id = sample_bet
        edited_fields = {
            "market_code": "TOTAL_GOALS_OVER_UNDER",
            "period_scope": "FULL_MATCH",
            "line_value": "2.5",
            "side": "OVER",
            "stake_original": "150.00",
            "odds_original": "2.00",
            "payout": "300.00",
            "currency": "GBP",
        }

        # Act
        verification_service.approve_bet(bet_id, edited_fields)

        # Assert
        bet = test_db.execute("SELECT * FROM bets WHERE id = ?", (bet_id,)).fetchone()
        assert bet["status"] == "verified"
        assert bet["market_code"] == "TOTAL_GOALS_OVER_UNDER"
        assert bet["period_scope"] == "FULL_MATCH"
        assert bet["line_value"] == "2.5"
        assert bet["side"] == "OVER"
        assert bet["stake_original"] == "150.00"
        assert bet["odds_original"] == "2.00"
        assert bet["payout"] == "300.00"
        assert bet["currency"] == "GBP"

        # Check audit log for modification
        audit = test_db.execute(
            "SELECT * FROM verification_audit WHERE bet_id = ? AND action = 'MODIFIED'",
            (bet_id,),
        ).fetchone()
        assert audit is not None
        assert "market_code" in audit["diff_after"]

    def test_approve_bet_already_processed(
        self, verification_service, sample_bet, test_db
    ):
        """Test that approving an already processed bet raises ValueError."""
        # Arrange
        bet_id = sample_bet
        test_db.execute("UPDATE bets SET status = 'verified' WHERE id = ?", (bet_id,))
        test_db.commit()

        # Act & Assert
        with pytest.raises(ValueError, match="already processed"):
            verification_service.approve_bet(bet_id)

    def test_approve_bet_not_found(self, verification_service):
        """Test that approving a non-existent bet raises ValueError."""
        # Act & Assert
        with pytest.raises(ValueError, match="not found"):
            verification_service.approve_bet(99999)


class TestBetRejection:
    """Test bet rejection workflow."""

    def test_reject_bet_without_reason(self, verification_service, sample_bet, test_db):
        """Test rejecting a bet without providing a reason."""
        # Arrange
        bet_id = sample_bet

        # Act
        verification_service.reject_bet(bet_id)

        # Assert
        bet = test_db.execute("SELECT * FROM bets WHERE id = ?", (bet_id,)).fetchone()
        assert bet["status"] == "rejected"

        # Check audit log
        audit = test_db.execute(
            "SELECT * FROM verification_audit WHERE bet_id = ? AND action = 'REJECTED'",
            (bet_id,),
        ).fetchone()
        assert audit is not None
        assert audit["notes"] == "No reason provided"

    def test_reject_bet_with_reason(self, verification_service, sample_bet, test_db):
        """Test rejecting a bet with a custom reason."""
        # Arrange
        bet_id = sample_bet
        reason = "Poor OCR quality - manual entry required"

        # Act
        verification_service.reject_bet(bet_id, reason)

        # Assert
        bet = test_db.execute("SELECT * FROM bets WHERE id = ?", (bet_id,)).fetchone()
        assert bet["status"] == "rejected"

        # Check audit log
        audit = test_db.execute(
            "SELECT * FROM verification_audit WHERE bet_id = ? AND action = 'REJECTED'",
            (bet_id,),
        ).fetchone()
        assert audit is not None
        assert audit["notes"] == reason

    def test_reject_bet_already_processed(
        self, verification_service, sample_bet, test_db
    ):
        """Test that rejecting an already processed bet raises ValueError."""
        # Arrange
        bet_id = sample_bet
        test_db.execute("UPDATE bets SET status = 'rejected' WHERE id = ?", (bet_id,))
        test_db.commit()

        # Act & Assert
        with pytest.raises(ValueError, match="already processed"):
            verification_service.reject_bet(bet_id)


class TestFieldValidation:
    """Test field validation logic."""

    def test_validate_stake_positive(self, verification_service, sample_bet):
        """Test that stake must be greater than 0."""
        # Arrange
        edited_fields = {"stake_original": "-10.00"}

        # Act & Assert
        with pytest.raises(ValueError, match="Stake must be greater than 0"):
            verification_service.approve_bet(sample_bet, edited_fields)

    def test_validate_odds_minimum(self, verification_service, sample_bet):
        """Test that odds must be >= 1.0."""
        # Arrange
        edited_fields = {"odds_original": "0.5"}

        # Act & Assert
        with pytest.raises(
            ValueError, match="Odds must be greater than or equal to 1.0"
        ):
            verification_service.approve_bet(sample_bet, edited_fields)

    def test_validate_payout_vs_stake(self, verification_service, sample_bet):
        """Test that payout must be >= stake."""
        # Arrange
        edited_fields = {"stake_original": "100.00", "payout": "50.00"}

        # Act & Assert
        with pytest.raises(
            ValueError, match="Payout must be greater than or equal to stake"
        ):
            verification_service.approve_bet(sample_bet, edited_fields)

    def test_validate_canonical_event_required(self, verification_service, sample_bet):
        """Test that canonical_event_id is required if provided as empty."""
        # Arrange
        edited_fields = {"canonical_event_id": None}

        # Act & Assert
        with pytest.raises(ValueError, match="Canonical event is required"):
            verification_service.approve_bet(sample_bet, edited_fields)

    def test_validate_currency_required(self, verification_service, sample_bet):
        """Test that currency is required if provided as empty."""
        # Arrange
        edited_fields = {"currency": ""}

        # Act & Assert
        with pytest.raises(ValueError, match="Currency is required"):
            verification_service.approve_bet(sample_bet, edited_fields)


class TestCanonicalDataLoading:
    """Test loading canonical events and markets."""

    def test_load_canonical_events(self, verification_service, test_db):
        """Test loading canonical events."""
        # Arrange
        test_db.execute(
            """
            INSERT INTO canonical_events (normalized_event_name, kickoff_time_utc, league, sport)
            VALUES ('Team A vs Team B', '2025-10-30T19:00:00Z', 'Premier League', 'Football')
            """
        )
        test_db.commit()

        # Act
        events = verification_service.load_canonical_events()

        # Assert
        assert len(events) > 0
        assert any(e["normalized_event_name"] == "Team A vs Team B" for e in events)

    def test_load_canonical_markets(self, verification_service, test_db):
        """Test loading canonical markets."""
        # Arrange
        test_db.execute(
            """
            INSERT OR IGNORE INTO canonical_markets (market_code, description)
            VALUES ('MATCH_WINNER', 'Match Winner')
            """
        )
        test_db.commit()

        # Act
        markets = verification_service.load_canonical_markets()

        # Assert
        assert len(markets) > 0
        # Check for markets added by seed data
        assert any(
            m["market_code"]
            in ["TOTAL_GOALS_OVER_UNDER", "ASIAN_HANDICAP", "MATCH_WINNER"]
            for m in markets
        )

    def test_create_canonical_event(self, verification_service, test_db):
        """Test creating a new canonical event."""
        # Act
        event_id = verification_service.create_canonical_event(
            event_name="Team C vs Team D",
            kickoff_time_utc="2025-11-01T15:00:00Z",
            league="La Liga",
            sport="football",
        )

        # Assert
        assert event_id > 0
        event = test_db.execute(
            "SELECT * FROM canonical_events WHERE id = ?", (event_id,)
        ).fetchone()
        assert event["normalized_event_name"] == "Team C vs Team D"
        assert event["kickoff_time_utc"] == "2025-11-01T15:00:00Z"
        assert event["league"] == "La Liga"
        assert event["sport"] == "football"


class TestMarketSideFiltering:
    """Test side filtering based on market type."""

    def test_over_under_markets_only_show_over_under(self, verification_service):
        """Test that over/under markets only show OVER/UNDER sides."""
        # Act
        sides = verification_service.get_valid_sides_for_market(
            "TOTAL_GOALS_OVER_UNDER"
        )

        # Assert
        assert sides == ["OVER", "UNDER"]

    def test_yes_no_markets_only_show_yes_no(self, verification_service):
        """Test that yes/no markets only show YES/NO sides."""
        # Act
        sides = verification_service.get_valid_sides_for_market("BOTH_TEAMS_TO_SCORE")

        # Assert
        assert sides == ["YES", "NO"]

    def test_team_markets_only_show_teams(self, verification_service):
        """Test that team markets only show TEAM_A/TEAM_B sides."""
        # Act
        sides = verification_service.get_valid_sides_for_market("MATCH_WINNER")

        # Assert
        assert sides == ["TEAM_A", "TEAM_B"]

    def test_unknown_market_shows_all_sides(self, verification_service):
        """Test that unknown markets show all possible sides."""
        # Act
        sides = verification_service.get_valid_sides_for_market("UNKNOWN_MARKET")

        # Assert
        assert "OVER" in sides
        assert "UNDER" in sides
        assert "YES" in sides
        assert "NO" in sides
        assert "TEAM_A" in sides
        assert "TEAM_B" in sides


class TestAuditLogging:
    """Test audit logging functionality."""

    def test_audit_log_created_on_approval(
        self, verification_service, sample_bet, test_db
    ):
        """Test that audit log entry is created on approval."""
        # Act
        verification_service.approve_bet(sample_bet)

        # Assert
        audit_entries = test_db.execute(
            "SELECT * FROM verification_audit WHERE bet_id = ?", (sample_bet,)
        ).fetchall()
        assert len(audit_entries) == 1
        assert audit_entries[0]["action"] == "VERIFIED"

    def test_audit_log_captures_field_changes(
        self, verification_service, sample_bet, test_db
    ):
        """Test that audit log captures field changes."""
        # Arrange
        edited_fields = {
            "market_code": "TOTAL_GOALS_OVER_UNDER",
            "side": "OVER",
            "stake_original": "200.00",
        }

        # Act
        verification_service.approve_bet(sample_bet, edited_fields)

        # Assert
        audit = test_db.execute(
            "SELECT * FROM verification_audit WHERE bet_id = ? AND action = 'MODIFIED'",
            (sample_bet,),
        ).fetchone()
        assert audit is not None
        assert "market_code" in audit["diff_after"]
        assert "side" in audit["diff_after"]
        assert "stake_original" in audit["diff_after"]

    def test_audit_log_created_on_rejection(
        self, verification_service, sample_bet, test_db
    ):
        """Test that audit log entry is created on rejection."""
        # Arrange
        reason = "Test rejection reason"

        # Act
        verification_service.reject_bet(sample_bet, reason)

        # Assert
        audit = test_db.execute(
            "SELECT * FROM verification_audit WHERE bet_id = ? AND action = 'REJECTED'",
            (sample_bet,),
        ).fetchone()
        assert audit is not None
        assert audit["notes"] == reason


class TestFuzzyEventMatching:
    """Test fuzzy matching functionality for canonical events."""

    def test_fuzzy_match_exact_name_same_sport_within_24h(
        self, verification_service, test_db
    ):
        """Test that exact event names with same sport within 24h match."""
        # Arrange
        test_db.execute(
            """
            INSERT INTO canonical_events (normalized_event_name, sport, kickoff_time_utc)
            VALUES ('Manchester United vs Liverpool', 'football', '2025-11-01T15:00:00Z')
            """
        )
        test_db.commit()

        # Act
        matched_id = verification_service._fuzzy_match_existing_event(
            event_name="Manchester United vs Liverpool",
            sport="football",
            kickoff_time_utc="2025-11-01T16:00:00Z",  # 1 hour later
        )

        # Assert
        assert matched_id is not None

    def test_fuzzy_match_similar_name_high_similarity(
        self, verification_service, test_db
    ):
        """Test that similar names (>80%) match within time window."""
        # Arrange
        test_db.execute(
            """
            INSERT INTO canonical_events (normalized_event_name, sport, kickoff_time_utc)
            VALUES ('Man United vs Liverpool', 'football', '2025-11-01T15:00:00Z')
            """
        )
        test_db.commit()

        # Act
        matched_id = verification_service._fuzzy_match_existing_event(
            event_name="Manchester United vs Liverpool FC",
            sport="football",
            kickoff_time_utc="2025-11-01T15:30:00Z",
        )

        # Assert - should match due to high similarity
        assert matched_id is not None

    def test_fuzzy_match_different_name_low_similarity(
        self, verification_service, test_db
    ):
        """Test that dissimilar names (<80%) do not match."""
        # Arrange
        test_db.execute(
            """
            INSERT INTO canonical_events (normalized_event_name, sport, kickoff_time_utc)
            VALUES ('Manchester United vs Liverpool', 'football', '2025-11-01T15:00:00Z')
            """
        )
        test_db.commit()

        # Act
        matched_id = verification_service._fuzzy_match_existing_event(
            event_name="Chelsea vs Arsenal",
            sport="football",
            kickoff_time_utc="2025-11-01T15:00:00Z",
        )

        # Assert
        assert matched_id is None

    def test_fuzzy_match_same_name_different_sport(self, verification_service, test_db):
        """Test that events with same name but different sport do not match."""
        # Arrange
        test_db.execute(
            """
            INSERT INTO canonical_events (normalized_event_name, sport, kickoff_time_utc)
            VALUES ('Warriors vs Lakers', 'basketball', '2025-11-01T15:00:00Z')
            """
        )
        test_db.commit()

        # Act
        matched_id = verification_service._fuzzy_match_existing_event(
            event_name="Warriors vs Lakers",
            sport="football",  # Different sport
            kickoff_time_utc="2025-11-01T15:00:00Z",
        )

        # Assert
        assert matched_id is None

    def test_fuzzy_match_outside_24h_window(self, verification_service, test_db):
        """Test that events outside ±24h window do not match."""
        # Arrange
        test_db.execute(
            """
            INSERT INTO canonical_events (normalized_event_name, sport, kickoff_time_utc)
            VALUES ('Manchester United vs Liverpool', 'football', '2025-11-01T15:00:00Z')
            """
        )
        test_db.commit()

        # Act - 25 hours later
        matched_id = verification_service._fuzzy_match_existing_event(
            event_name="Manchester United vs Liverpool",
            sport="football",
            kickoff_time_utc="2025-11-02T16:00:00Z",  # 25 hours later
        )

        # Assert
        assert matched_id is None

    def test_fuzzy_match_within_24h_boundary(self, verification_service, test_db):
        """Test that events exactly at 24h boundary match."""
        # Arrange
        test_db.execute(
            """
            INSERT INTO canonical_events (normalized_event_name, sport, kickoff_time_utc)
            VALUES ('Manchester United vs Liverpool', 'football', '2025-11-01T15:00:00Z')
            """
        )
        test_db.commit()

        # Act - exactly 24 hours later
        matched_id = verification_service._fuzzy_match_existing_event(
            event_name="Manchester United vs Liverpool",
            sport="football",
            kickoff_time_utc="2025-11-02T15:00:00Z",  # Exactly 24h later
        )

        # Assert
        assert matched_id is not None

    def test_fuzzy_match_normalizes_punctuation(self, verification_service, test_db):
        """Test that punctuation differences don't prevent matching."""
        # Arrange
        test_db.execute(
            """
            INSERT INTO canonical_events (normalized_event_name, sport, kickoff_time_utc)
            VALUES ('Man. United vs. Liverpool', 'football', '2025-11-01T15:00:00Z')
            """
        )
        test_db.commit()

        # Act
        matched_id = verification_service._fuzzy_match_existing_event(
            event_name="Man United vs Liverpool",  # No periods
            sport="football",
            kickoff_time_utc="2025-11-01T15:00:00Z",
        )

        # Assert
        assert matched_id is not None


class TestEventCreation:
    """Test canonical event creation functionality."""

    def test_create_event_with_all_fields(self, verification_service, test_db):
        """Test creating event with all fields populated."""
        # Act
        event_id = verification_service._create_canonical_event(
            event_name="Arsenal vs Chelsea",
            sport="football",
            competition="Premier League",
            kickoff_time_utc="2025-11-05T17:30:00Z",
        )

        # Assert
        assert event_id > 0
        event = test_db.execute(
            "SELECT * FROM canonical_events WHERE id = ?", (event_id,)
        ).fetchone()
        assert event["normalized_event_name"] == "Arsenal vs Chelsea"
        assert event["sport"] == "football"
        assert event["league"] == "Premier League"
        assert event["kickoff_time_utc"] == "2025-11-05T17:30:00Z"

    def test_create_event_without_optional_competition(
        self, verification_service, test_db
    ):
        """Test creating event without competition field."""
        # Act
        event_id = verification_service._create_canonical_event(
            event_name="Team A vs Team B",
            sport="tennis",
            competition=None,
            kickoff_time_utc="2025-11-06T14:00:00Z",
        )

        # Assert
        assert event_id > 0
        event = test_db.execute(
            "SELECT * FROM canonical_events WHERE id = ?", (event_id,)
        ).fetchone()
        assert event["league"] is None

    def test_create_event_validates_min_name_length(self, verification_service):
        """Test that event name must be at least 5 characters."""
        # Act & Assert
        with pytest.raises(ValueError, match="at least 5 characters"):
            verification_service._create_canonical_event(
                event_name="A B",  # Only 3 characters
                sport="football",
                competition=None,
                kickoff_time_utc="2025-11-01T15:00:00Z",
            )

    def test_create_event_validates_sport_required(self, verification_service):
        """Test that sport is required."""
        # Act & Assert
        with pytest.raises(ValueError, match="Sport is required"):
            verification_service._create_canonical_event(
                event_name="Team A vs Team B",
                sport="",  # Empty sport
                competition=None,
                kickoff_time_utc="2025-11-01T15:00:00Z",
            )

    def test_create_event_validates_sport_from_list(self, verification_service):
        """Test that sport must be from predefined list."""
        # Act & Assert
        with pytest.raises(ValueError, match="must be one of"):
            verification_service._create_canonical_event(
                event_name="Team A vs Team B",
                sport="invalid_sport",  # Not in list
                competition=None,
                kickoff_time_utc="2025-11-01T15:00:00Z",
            )

    def test_create_event_validates_competition_max_length(self, verification_service):
        """Test that competition must not exceed 100 characters."""
        # Act & Assert
        with pytest.raises(ValueError, match="must not exceed 100 characters"):
            verification_service._create_canonical_event(
                event_name="Team A vs Team B",
                sport="football",
                competition="a" * 101,  # 101 characters
                kickoff_time_utc="2025-11-01T15:00:00Z",
            )

    def test_create_event_validates_kickoff_format(self, verification_service):
        """Test that kickoff time must be ISO8601 with Z suffix."""
        # Act & Assert
        with pytest.raises(ValueError, match="ISO8601 format with Z suffix"):
            verification_service._create_canonical_event(
                event_name="Team A vs Team B",
                sport="football",
                competition=None,
                kickoff_time_utc="2025-11-01 15:00:00",  # Wrong format
            )

    def test_create_event_validates_kickoff_requires_z_suffix(
        self, verification_service
    ):
        """Test that kickoff time must have Z suffix."""
        # Act & Assert
        with pytest.raises(ValueError, match="ISO8601 format with Z suffix"):
            verification_service._create_canonical_event(
                event_name="Team A vs Team B",
                sport="football",
                competition=None,
                kickoff_time_utc="2025-11-01T15:00:00",  # Missing Z
            )


class TestGetOrCreateCanonicalEvent:
    """Test the orchestration method for getting or creating events."""

    @pytest.fixture
    def bet_with_event_data(self, test_db):
        """Create a bet with event data for testing."""
        cursor = test_db.execute(
            """
            INSERT INTO bets (
                associate_id, bookmaker_id, status, stake_eur, odds, currency,
                selection_text, kickoff_time_utc, ingestion_source
            ) VALUES (?, ?, 'incoming', '100.00', '1.90', 'AUD',
                      'Manchester United vs Liverpool', '2025-11-01T15:00:00Z', 'manual_upload')
            """,
            (1, 1),
        )
        test_db.commit()
        return cursor.lastrowid

    def test_get_or_create_matches_existing_event(
        self, verification_service, bet_with_event_data, test_db
    ):
        """Test that existing event is matched instead of creating new one."""
        # Arrange - create existing event
        test_db.execute(
            """
            INSERT INTO canonical_events (normalized_event_name, sport, kickoff_time_utc)
            VALUES ('Manchester United vs Liverpool', 'football', '2025-11-01T15:00:00Z')
            """
        )
        test_db.commit()
        existing_event_id = test_db.execute(
            "SELECT id FROM canonical_events ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]

        # Act
        event_id = verification_service.get_or_create_canonical_event(
            bet_id=bet_with_event_data, sport="football"
        )

        # Assert - should return existing event ID, not create new one
        assert event_id == existing_event_id

        # Verify only one event exists
        event_count = test_db.execute(
            "SELECT COUNT(*) FROM canonical_events"
        ).fetchone()[0]
        assert event_count == 1

    def test_get_or_create_creates_new_event_when_no_match(
        self, verification_service, bet_with_event_data, test_db
    ):
        """Test that new event is created when no match found."""
        # Act
        event_id = verification_service.get_or_create_canonical_event(
            bet_id=bet_with_event_data, sport="football"
        )

        # Assert
        assert event_id > 0
        event = test_db.execute(
            "SELECT * FROM canonical_events WHERE id = ?", (event_id,)
        ).fetchone()
        assert event["normalized_event_name"] == "Manchester United vs Liverpool"
        assert event["sport"] == "football"

    def test_get_or_create_validates_event_name_length(
        self, verification_service, test_db
    ):
        """Test that event name validation is applied."""
        # Arrange - bet with short event name
        cursor = test_db.execute(
            """
            INSERT INTO bets (
                associate_id, bookmaker_id, status, stake_eur, odds, currency,
                selection_text, kickoff_time_utc, ingestion_source
            ) VALUES (?, ?, 'incoming', '100.00', '1.90', 'AUD', 'A B', '2025-11-01T15:00:00Z', 'manual_upload')
            """,
            (1, 1),
        )
        test_db.commit()
        bet_id = cursor.lastrowid

        # Act & Assert
        with pytest.raises(ValueError, match="minimum 5 characters"):
            verification_service.get_or_create_canonical_event(
                bet_id=bet_id, sport="football"
            )

    def test_get_or_create_validates_kickoff_required(
        self, verification_service, test_db
    ):
        """Test that kickoff time is required."""
        # Arrange - bet without kickoff time
        cursor = test_db.execute(
            """
            INSERT INTO bets (
                associate_id, bookmaker_id, status, stake_eur, odds, currency,
                selection_text, ingestion_source
            ) VALUES (?, ?, 'incoming', '100.00', '1.90', 'AUD', 'Team A vs Team B', 'manual_upload')
            """,
            (1, 1),
        )
        test_db.commit()
        bet_id = cursor.lastrowid

        # Act & Assert
        with pytest.raises(ValueError, match="Kickoff time is required"):
            verification_service.get_or_create_canonical_event(
                bet_id=bet_id, sport="football"
            )


class TestApprovalWithAutoEventCreation:
    """Test approval workflow with automatic event creation."""

    @pytest.fixture
    def bet_without_event(self, test_db):
        """Create a bet without canonical_event_id."""
        cursor = test_db.execute(
            """
            INSERT INTO bets (
                associate_id, bookmaker_id, status, stake_eur, odds, currency,
                selection_text, kickoff_time_utc, canonical_event_id, ingestion_source
            ) VALUES (?, ?, 'incoming', '100.00', '1.90', 'AUD',
                      'Arsenal vs Chelsea', '2025-11-05T17:30:00Z', NULL, 'manual_upload')
            """,
            (1, 1),
        )
        test_db.commit()
        return cursor.lastrowid

    def test_approve_creates_event_when_missing(
        self, verification_service, bet_without_event, test_db
    ):
        """Test that approval automatically creates event when missing."""
        # Act
        verification_service.approve_bet(bet_without_event)

        # Assert - bet should have canonical_event_id
        bet = test_db.execute(
            "SELECT * FROM bets WHERE id = ?", (bet_without_event,)
        ).fetchone()
        assert bet["canonical_event_id"] is not None
        assert bet["status"] == "verified"

        # Verify event was created
        event = test_db.execute(
            "SELECT * FROM canonical_events WHERE id = ?", (bet["canonical_event_id"],)
        ).fetchone()
        assert event is not None
        assert event["normalized_event_name"] == "Arsenal vs Chelsea"

    def test_approve_logs_auto_event_creation_to_audit(
        self, verification_service, bet_without_event, test_db
    ):
        """Test that auto event creation is logged to audit trail."""
        # Act
        verification_service.approve_bet(bet_without_event)

        # Assert - check audit log
        audit = test_db.execute(
            """
            SELECT * FROM verification_audit
            WHERE bet_id = ? AND actor = 'auto' AND action = 'MODIFIED'
            """,
            (bet_without_event,),
        ).fetchone()
        assert audit is not None
        assert "canonical_event_id" in audit["diff_after"]

    def test_approve_keeps_existing_event_if_set(self, verification_service, test_db):
        """Test that approval doesn't change existing canonical_event_id."""
        # Arrange - create event and bet with event_id
        cursor = test_db.execute(
            """
            INSERT INTO canonical_events (normalized_event_name, sport, kickoff_time_utc)
            VALUES ('Liverpool vs Arsenal', 'football', '2025-11-06T20:00:00Z')
            """
        )
        existing_event_id = cursor.lastrowid

        cursor = test_db.execute(
            """
            INSERT INTO bets (
                associate_id, bookmaker_id, status, stake_eur, odds, currency,
                selection_text, canonical_event_id, ingestion_source
            ) VALUES (?, ?, 'incoming', '100.00', '1.90', 'AUD',
                      'Liverpool vs Arsenal', ?, 'manual_upload')
            """,
            (1, 1, existing_event_id),
        )
        test_db.commit()
        bet_id = cursor.lastrowid

        # Act
        verification_service.approve_bet(bet_id)

        # Assert - event_id should remain unchanged
        bet = test_db.execute("SELECT * FROM bets WHERE id = ?", (bet_id,)).fetchone()
        assert bet["canonical_event_id"] == existing_event_id

        # No auto-creation audit entry
        audit = test_db.execute(
            """
            SELECT * FROM verification_audit
            WHERE bet_id = ? AND actor = 'auto'
            """,
            (bet_id,),
        ).fetchone()
        assert audit is None

    def test_approve_fails_if_event_creation_fails(self, verification_service, test_db):
        """Test that approval fails if event creation fails."""
        # Arrange - bet with invalid kickoff time
        cursor = test_db.execute(
            """
            INSERT INTO bets (
                associate_id, bookmaker_id, status, stake_eur, odds, currency,
                selection_text, kickoff_time_utc, ingestion_source
            ) VALUES (?, ?, 'incoming', '100.00', '1.90', 'AUD',
                      'Team A vs Team B', 'invalid_date', 'manual_upload')
            """,
            (1, 1),
        )
        test_db.commit()
        bet_id = cursor.lastrowid

        # Act & Assert
        with pytest.raises(ValueError, match="Failed to create canonical event"):
            verification_service.approve_bet(bet_id)

        # Bet should remain in incoming status
        bet = test_db.execute("SELECT * FROM bets WHERE id = ?", (bet_id,)).fetchone()
        assert bet["status"] == "incoming"
