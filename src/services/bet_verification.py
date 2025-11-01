"""
Bet verification service for approval and rejection workflows.

This module handles the verification of incoming bets, including:
- Inline field editing
- Approval with audit logging
- Rejection with optional reason
- Field validation
"""

import sqlite3
import structlog
import re
from datetime import datetime, UTC, timedelta
from typing import Dict, Any, Optional, List, Tuple
from decimal import Decimal
from rapidfuzz import fuzz

logger = structlog.get_logger()


class BetVerificationService:
    """Service for verifying and editing incoming bets."""

    def __init__(self, db: sqlite3.Connection):
        """Initialize the bet verification service.

        Args:
            db: SQLite database connection
        """
        self.db = db
        self.db.row_factory = sqlite3.Row

    def approve_bet(
        self,
        bet_id: int,
        edited_fields: Optional[Dict[str, Any]] = None,
        verified_by: str = "local_user",
    ) -> None:
        """Approve a bet and optionally apply edits.

        This method now includes automatic canonical event creation when the bet
        doesn't have a canonical_event_id assigned.

        Args:
            bet_id: ID of the bet to approve
            edited_fields: Dictionary of field_name -> new_value for edited fields
            verified_by: Identifier of the person approving (default: "local_user")

        Raises:
            ValueError: If bet not found or already processed
        """
        # Load current bet
        bet = self._load_bet(bet_id)
        if not bet:
            raise ValueError(f"Bet {bet_id} not found")

        if bet["status"] != "incoming":
            raise ValueError(
                f"Bet {bet_id} already processed (status: {bet['status']})"
            )

        # Initialize edited_fields if None
        if edited_fields is None:
            edited_fields = {}

        # Extract optional manual event name override (used for auto-create fallback)
        event_name_override = edited_fields.pop("_event_name_override", None)
        if event_name_override:
            event_name_override = event_name_override.strip() or None
            if event_name_override:
                # Store override on bet so future reviews see it
                edited_fields.setdefault("selection_text", event_name_override)

        # Resolve event name candidate for auto-create logic
        event_name_candidate = event_name_override or bet.get("selection_text")

        # Auto-create canonical event if not set and bet has required data
        if (
            not bet.get("canonical_event_id")
            and "canonical_event_id" not in edited_fields
        ):
            # Check if bet has required fields for event creation
            has_event_name = event_name_candidate and len(event_name_candidate) >= 5
            has_kickoff = bet.get("kickoff_time_utc")

            if has_event_name and has_kickoff:
                try:
                    # Extract sport from edited fields or default to football
                    sport = edited_fields.get("sport", "football")
                    competition = edited_fields.get("league")

                    # Attempt to create/match canonical event
                    event_id = self.get_or_create_canonical_event(
                        bet_id=bet_id,
                        event_name=event_name_candidate,
                        sport=sport,
                        competition=competition,
                    )

                    # Add event_id to edited fields
                    edited_fields["canonical_event_id"] = event_id

                    # Log audit trail for auto-created event
                    self.db.execute(
                        """
                        INSERT INTO verification_audit (bet_id, actor, action, diff_before, diff_after)
                        VALUES (?, ?, 'MODIFIED', ?, ?)
                        """,
                        (
                            bet_id,
                            "auto",
                            "canonical_event_id=NULL",
                            f"canonical_event_id={event_id}",
                        ),
                    )

                    logger.info(
                        "canonical_event_auto_assigned",
                        bet_id=bet_id,
                        event_id=event_id,
                        verified_by=verified_by,
                    )
                except Exception as e:
                    # If event creation fails, log error and keep bet in incoming status
                    logger.error(
                        "canonical_event_creation_failed",
                        bet_id=bet_id,
                        error=str(e),
                        verified_by=verified_by,
                    )
                    raise ValueError(f"Failed to create canonical event: {str(e)}")

        # Validate edited fields
        if edited_fields:
            self._validate_bet_fields(edited_fields)

        # Log edits to verification_audit
        if edited_fields:
            self._log_edits(bet_id, bet, edited_fields, verified_by)

        # Apply edits and update status
        self._apply_bet_updates(bet_id, edited_fields, verified_by, "verified")

        logger.info("bet_approved", bet_id=bet_id, verified_by=verified_by)

        # Attempt to match bet with opposite-side candidates
        try:
            from src.services.surebet_matcher import SurebetMatcher

            matcher = SurebetMatcher(self.db)
            surebet_id = matcher.attempt_match(bet_id)

            if surebet_id:
                logger.info(
                    "bet_auto_matched",
                    bet_id=bet_id,
                    surebet_id=surebet_id,
                    verified_by=verified_by,
                )
        except Exception as e:
            # Log matching failure but don't block approval
            logger.error(
                "matching_failed",
                bet_id=bet_id,
                error=str(e),
                verified_by=verified_by,
            )

    def reject_bet(
        self,
        bet_id: int,
        rejection_reason: Optional[str] = None,
        verified_by: str = "local_user",
    ) -> None:
        """Reject a bet with optional reason.

        Args:
            bet_id: ID of the bet to reject
            rejection_reason: Optional human-readable reason for rejection
            verified_by: Identifier of the person rejecting (default: "local_user")

        Raises:
            ValueError: If bet not found or already processed
        """
        # Load current bet
        bet = self._load_bet(bet_id)
        if not bet:
            raise ValueError(f"Bet {bet_id} not found")

        if bet["status"] != "incoming":
            raise ValueError(
                f"Bet {bet_id} already processed (status: {bet['status']})"
            )

        # Log rejection to verification_audit
        self.db.execute(
            """
            INSERT INTO verification_audit (bet_id, actor, action, notes)
            VALUES (?, ?, 'REJECTED', ?)
            """,
            (bet_id, verified_by, rejection_reason or "No reason provided"),
        )

        # Update bet status
        timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        self.db.execute(
            """
            UPDATE bets
            SET status = 'rejected',
                updated_at_utc = ?
            WHERE id = ?
            """,
            (timestamp, bet_id),
        )

        self.db.commit()
        logger.info(
            "bet_rejected",
            bet_id=bet_id,
            reason=rejection_reason,
            verified_by=verified_by,
        )

    def load_canonical_events(self) -> List[Dict[str, Any]]:
        """Load all canonical events for dropdown.

        Returns:
            List of canonical events with id, name, and kickoff time
        """
        cursor = self.db.execute(
            """
            SELECT id, normalized_event_name, kickoff_time_utc, league, sport
            FROM canonical_events
            ORDER BY kickoff_time_utc DESC
            """
        )
        return [dict(row) for row in cursor.fetchall()]

    def load_canonical_markets(self) -> List[Dict[str, Any]]:
        """Load all canonical markets for dropdown.

        Returns:
            List of canonical markets with id, code, and description
        """
        cursor = self.db.execute(
            """
            SELECT id, market_code, description
            FROM canonical_markets
            ORDER BY description
            """
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_or_create_canonical_event(
        self,
        bet_id: int,
        event_name: Optional[str] = None,
        sport: Optional[str] = None,
        competition: Optional[str] = None,
        kickoff_time_utc: Optional[str] = None,
    ) -> int:
        """Auto-create or fuzzy-match canonical event for a bet.

        This method attempts to find an existing canonical event using fuzzy matching.
        If no suitable match is found (>80% similarity within ±24h), a new event is created.

        Args:
            bet_id: ID of the bet to create/match event for
            event_name: Event name (if None, extracted from bet's selection_text)
            sport: Sport type (e.g., "football", "tennis")
            competition: Optional competition/league name
            kickoff_time_utc: ISO8601 timestamp with Z suffix

        Returns:
            Event ID (either matched or newly created)

        Raises:
            ValueError: If required fields are missing or invalid
        """
        # Load bet data if event_name/kickoff not provided
        bet = self._load_bet(bet_id)
        if not bet:
            raise ValueError(f"Bet {bet_id} not found")

        # Extract event data from bet if not provided
        if not event_name:
            event_name = bet.get("selection_text")
        if not kickoff_time_utc:
            kickoff_time_utc = bet.get("kickoff_time_utc")

        # Validate required fields
        if not event_name or len(event_name) < 5:
            raise ValueError("Event name is required (minimum 5 characters)")
        if not kickoff_time_utc:
            raise ValueError("Kickoff time is required")
        if not self._validate_iso8601_utc(kickoff_time_utc):
            raise ValueError(
                "Kickoff time must be in ISO8601 format with Z suffix (YYYY-MM-DDTHH:MM:SSZ)"
            )

        # Try fuzzy matching first
        if sport and kickoff_time_utc:
            matched_event_id = self._fuzzy_match_existing_event(
                event_name, sport, kickoff_time_utc
            )
            if matched_event_id:
                logger.info(
                    "canonical_event_matched",
                    bet_id=bet_id,
                    event_id=matched_event_id,
                    event_name=event_name,
                )
                return matched_event_id

        # No match found, create new event
        event_id = self._create_canonical_event(
            event_name, sport or "football", competition, kickoff_time_utc
        )
        logger.info(
            "canonical_event_auto_created",
            bet_id=bet_id,
            event_id=event_id,
            event_name=event_name,
            match_attempted=bool(sport),
        )
        return event_id

    def _fuzzy_match_existing_event(
        self, event_name: str, sport: str, kickoff_time_utc: str
    ) -> Optional[int]:
        """Fuzzy match existing events using rapidfuzz.

        Searches for events with the same sport within ±24 hours of kickoff time,
        then uses fuzzy string matching to find similar event names.

        Args:
            event_name: Event name to match against
            sport: Sport type (must match exactly)
            kickoff_time_utc: ISO8601 timestamp for time window filtering

        Returns:
            Event ID if match found with >80% similarity, None otherwise
        """
        # Parse kickoff time
        try:
            kickoff_dt = datetime.fromisoformat(kickoff_time_utc.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            logger.warning("invalid_kickoff_time", kickoff_time=kickoff_time_utc)
            return None

        # Calculate time window (±24 hours)
        time_start = (
            (kickoff_dt - timedelta(hours=24)).isoformat().replace("+00:00", "Z")
        )
        time_end = (kickoff_dt + timedelta(hours=24)).isoformat().replace("+00:00", "Z")

        # Query events in time window with matching sport
        cursor = self.db.execute(
            """
            SELECT id, normalized_event_name, kickoff_time_utc
            FROM canonical_events
            WHERE sport = ?
              AND kickoff_time_utc >= ?
              AND kickoff_time_utc <= ?
            """,
            (sport, time_start, time_end),
        )
        candidates = cursor.fetchall()

        if not candidates:
            return None

        # Normalize input event name
        normalized_input = self._normalize_event_name(event_name)

        # Find best match using fuzzy matching
        best_match_id = None
        best_score = 0.0

        for row in candidates:
            candidate_id = row[0]
            candidate_name = row[1]
            normalized_candidate = self._normalize_event_name(candidate_name)

            # Calculate similarity score
            score = fuzz.ratio(normalized_input, normalized_candidate)

            if score > best_score:
                best_score = score
                best_match_id = candidate_id

        # Return match if above threshold (80%)
        if best_score > 80.0:
            logger.info(
                "fuzzy_match_found",
                event_id=best_match_id,
                similarity=best_score,
                input_name=event_name,
            )
            return best_match_id

        logger.debug(
            "fuzzy_match_no_match",
            best_score=best_score,
            threshold=80.0,
            candidates_checked=len(candidates),
        )
        return None

    def _normalize_event_name(self, name: str) -> str:
        """Normalize event name for fuzzy matching.

        Args:
            name: Raw event name

        Returns:
            Normalized name (lowercase, punctuation removed, whitespace normalized)
        """
        # Lowercase
        normalized = name.lower()
        # Remove punctuation
        normalized = re.sub(r"[^\w\s]", "", normalized)
        # Normalize whitespace
        normalized = " ".join(normalized.split())
        return normalized

    def _create_canonical_event(
        self,
        event_name: str,
        sport: str,
        competition: Optional[str],
        kickoff_time_utc: str,
    ) -> int:
        """Create new canonical event row with validation.

        Args:
            event_name: Event name (min 5 chars)
            sport: Sport type (required)
            competition: Optional competition/league name (max 100 chars)
            kickoff_time_utc: ISO8601 timestamp with Z suffix

        Returns:
            Newly created event_id

        Raises:
            ValueError: If validation fails
        """
        # Validate event_name
        if not event_name or len(event_name) < 5:
            raise ValueError("Event name must be at least 5 characters")

        # Validate sport (required, from predefined list)
        valid_sports = ["football", "tennis", "basketball", "cricket", "rugby"]
        if not sport or sport.lower() not in valid_sports:
            raise ValueError(
                f"Sport is required and must be one of: {', '.join(valid_sports)}"
            )

        # Validate competition length
        if competition and len(competition) > 100:
            raise ValueError("Competition name must not exceed 100 characters")

        # Validate kickoff time format
        if not self._validate_iso8601_utc(kickoff_time_utc):
            raise ValueError(
                "Kickoff time must be in ISO8601 format with Z suffix (YYYY-MM-DDTHH:MM:SSZ)"
            )

        # Insert new event
        cursor = self.db.execute(
            """
            INSERT INTO canonical_events (normalized_event_name, sport, league, kickoff_time_utc)
            VALUES (?, ?, ?, ?)
            """,
            (event_name, sport.lower(), competition, kickoff_time_utc),
        )
        self.db.commit()
        event_id = cursor.lastrowid

        if event_id is None:
            raise ValueError("Failed to create canonical event: no ID returned")

        logger.info(
            "canonical_event_created",
            event_id=event_id,
            event_name=event_name,
            sport=sport,
            competition=competition,
        )
        return event_id

    def _validate_iso8601_utc(self, timestamp: str) -> bool:
        """Validate ISO8601 UTC timestamp format.

        Args:
            timestamp: Timestamp string to validate

        Returns:
            True if valid ISO8601 with Z suffix, False otherwise
        """
        if not timestamp or not timestamp.endswith("Z"):
            return False

        try:
            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            return True
        except (ValueError, AttributeError):
            return False

    def create_canonical_event(
        self,
        event_name: str,
        kickoff_time_utc: str,
        league: Optional[str] = None,
        sport: Optional[str] = None,
    ) -> int:
        """Create a new canonical event (legacy method for backwards compatibility).

        Args:
            event_name: Normalized event name (e.g., "Team A vs Team B")
            kickoff_time_utc: ISO8601 timestamp with Z suffix
            league: Optional league name
            sport: Optional sport name

        Returns:
            ID of the newly created event
        """
        return self._create_canonical_event(
            event_name, sport or "football", league, kickoff_time_utc
        )

    def get_valid_sides_for_market(self, market_code: Optional[str]) -> List[str]:
        """Get valid side values for a given market type.

        Args:
            market_code: Market code (e.g., "TOTAL_GOALS_OVER_UNDER")

        Returns:
            List of valid side values
        """
        # Define side mappings for different market types
        over_under_markets = [
            "TOTAL_GOALS_OVER_UNDER",
            "FIRST_HALF_TOTAL_GOALS",
            "SECOND_HALF_TOTAL_GOALS",
            "TOTAL_CARDS_OVER_UNDER",
            "TOTAL_CORNERS_OVER_UNDER",
            "TOTAL_SHOTS_OVER_UNDER",
            "TOTAL_SHOTS_ON_TARGET_OVER_UNDER",
            "TOTAL_GAMES_OVER_UNDER",
        ]
        yes_no_markets = [
            "BOTH_TEAMS_TO_SCORE",
            "RED_CARD_AWARDED",
            "PENALTY_AWARDED",
        ]
        team_markets = ["MATCH_WINNER", "ASIAN_HANDICAP", "DRAW_NO_BET"]

        if not market_code:
            return ["OVER", "UNDER", "YES", "NO", "TEAM_A", "TEAM_B"]

        if market_code in over_under_markets:
            return ["OVER", "UNDER"]
        elif market_code in yes_no_markets:
            return ["YES", "NO"]
        elif market_code in team_markets:
            return ["TEAM_A", "TEAM_B"]
        else:
            # Default: all possible sides
            return ["OVER", "UNDER", "YES", "NO", "TEAM_A", "TEAM_B"]

    def _load_bet(self, bet_id: int) -> Optional[Dict[str, Any]]:
        """Load bet by ID."""
        cursor = self.db.execute("SELECT * FROM bets WHERE id = ?", (bet_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def _validate_bet_fields(self, fields: Dict[str, Any]) -> None:
        """Validate edited bet fields.

        Args:
            fields: Dictionary of field_name -> value

        Raises:
            ValueError: If validation fails
        """
        # Validate stake
        if "stake_original" in fields:
            stake = Decimal(str(fields["stake_original"]))
            if stake <= 0:
                raise ValueError("Stake must be greater than 0")

        # Validate odds
        if "odds_original" in fields:
            odds = Decimal(str(fields["odds_original"]))
            if odds < Decimal("1.0"):
                raise ValueError("Odds must be greater than or equal to 1.0")

        # Validate payout >= stake
        if "payout" in fields and "stake_original" in fields:
            stake = Decimal(str(fields["stake_original"]))
            payout = Decimal(str(fields["payout"]))
            if payout < stake:
                raise ValueError("Payout must be greater than or equal to stake")

        # Validate required fields
        if "canonical_event_id" in fields and not fields["canonical_event_id"]:
            raise ValueError("Canonical event is required")

        if "currency" in fields and not fields["currency"]:
            raise ValueError("Currency is required")

    def _log_edits(
        self,
        bet_id: int,
        old_bet: Dict[str, Any],
        edited_fields: Dict[str, Any],
        actor: str,
    ) -> None:
        """Log field changes to verification_audit table.

        Args:
            bet_id: Bet ID
            old_bet: Original bet data
            edited_fields: Dictionary of edited fields
            actor: Person making the edits
        """
        # Build diff strings
        diff_before = []
        diff_after = []

        for field_name, new_value in edited_fields.items():
            old_value = old_bet.get(field_name)
            if old_value != new_value:
                diff_before.append(f"{field_name}={old_value}")
                diff_after.append(f"{field_name}={new_value}")

        diff_before_str = "; ".join(diff_before) if diff_before else None
        diff_after_str = "; ".join(diff_after) if diff_after else None

        # Insert audit entry
        self.db.execute(
            """
            INSERT INTO verification_audit (bet_id, actor, action, diff_before, diff_after)
            VALUES (?, ?, 'MODIFIED', ?, ?)
            """,
            (bet_id, actor, diff_before_str, diff_after_str),
        )

    def _apply_bet_updates(
        self,
        bet_id: int,
        edited_fields: Optional[Dict[str, Any]],
        verified_by: str,
        new_status: str,
    ) -> None:
        """Apply field updates and change bet status.

        Args:
            bet_id: Bet ID
            edited_fields: Dictionary of field updates (can be None)
            verified_by: Person verifying
            new_status: New status ('verified' or 'rejected')
        """
        timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")

        # Build UPDATE query dynamically
        update_fields = ["status = ?", "updated_at_utc = ?"]
        params: List[Any] = [new_status, timestamp]

        if edited_fields:
            for field_name, value in edited_fields.items():
                # Convert Decimal to string for storage
                if isinstance(value, Decimal):
                    value = str(value)
                update_fields.append(f"{field_name} = ?")
                params.append(value)

        params.append(bet_id)  # WHERE clause parameter

        query = f"""
            UPDATE bets
            SET {', '.join(update_fields)}
            WHERE id = ?
        """

        self.db.execute(query, params)

        # Log verification action
        self.db.execute(
            """
            INSERT INTO verification_audit (bet_id, actor, action)
            VALUES (?, ?, 'VERIFIED')
            """,
            (bet_id, verified_by),
        )

        self.db.commit()
