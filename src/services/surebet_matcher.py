"""
Surebet matching service for pairing opposite-side verified bets.

This module handles the automatic matching of verified bets into surebets:
- Deterministic side assignment (A/B)
- Matching opposite-side candidates
- Creating and linking surebets
- Idempotent operation
"""

import sqlite3
import structlog
from datetime import datetime, UTC
from decimal import Decimal
from typing import Optional, Literal, List, Dict, Any, Tuple

from src.services.stake_ledger_service import StakeLedgerService

logger = structlog.get_logger()


class SurebetMatcher:
    """Service for automatically matching verified bets into surebets."""

    def __init__(self, db: sqlite3.Connection):
        """Initialize the surebet matcher service.

        Args:
            db: SQLite database connection
        """
        self.db = db
        self.db.row_factory = sqlite3.Row
        # Import here to avoid circular dependency
        from src.services.surebet_calculator import SurebetRiskCalculator

        self.risk_calculator = SurebetRiskCalculator(db)

    def attempt_match(self, bet_id: int) -> Optional[int]:
        """
        Attempt to match a verified bet with opposite-side candidates.

        This method:
        1. Loads the bet and validates it's in 'verified' status
        2. Queries for opposite-side candidates with matching event/market criteria
        3. Creates new surebet or adds to existing surebet
        4. Links bets with deterministic side assignment (A/B)
        5. Updates matched bets to 'matched' status

        Args:
            bet_id: ID of the verified bet to match

        Returns:
            surebet_id if match was created/updated, None if no match possible

        Raises:
            ValueError: If bet not found or invalid status
        """
        # Idempotency check: Return early if bet already matched
        bet = self._load_bet(bet_id)
        if not bet:
            raise ValueError(f"Bet {bet_id} not found")

        if bet["status"] == "matched":
            logger.debug("bet_already_matched", bet_id=bet_id)
            return self._get_surebet_id_for_bet(bet_id)

        if bet["status"] != "verified":
            logger.warning(
                "bet_not_verified",
                bet_id=bet_id,
                status=bet["status"],
            )
            return None

        # Skip unsupported bet types
        if not bet["is_supported"]:
            logger.debug("bet_unsupported", bet_id=bet_id)
            return None

        # Skip if missing required fields for matching
        if not self._has_required_fields(bet):
            logger.debug(
                "bet_missing_required_fields",
                bet_id=bet_id,
                canonical_event_id=bet.get("canonical_event_id"),
                market_code=bet.get("market_code"),
                side=bet.get("side"),
            )
            return None

        # Query for opposite-side candidates (both verified and already matched)
        candidates = self._query_opposite_side_candidates(bet)

        if not candidates:
            logger.debug(
                "no_opposite_candidates",
                bet_id=bet_id,
                canonical_event_id=bet["canonical_event_id"],
                market_code=bet["market_code"],
            )
            return None

        # Check if surebet already exists for these candidates
        surebet_id = self._find_or_create_surebet(bet, candidates)

        # Link current bet to surebet with deterministic side assignment
        self._link_bet_to_surebet(bet_id, bet["side"], surebet_id)

        # Update bet status to 'matched'
        self._update_bet_status(bet_id, "matched")

        # Update all linked candidate bets to 'matched' status
        for candidate in candidates:
            candidate_id = candidate["id"]
            if candidate["status"] != "matched":
                self._link_bet_to_surebet(
                    candidate_id, candidate["side"], surebet_id
                )
                self._update_bet_status(candidate_id, "matched")

        logger.info(
            "bet_matched",
            bet_id=bet_id,
            surebet_id=surebet_id,
            candidate_count=len(candidates),
        )

        # Calculate and store risk analysis for the surebet
        self._update_surebet_risk(surebet_id)

        return surebet_id

    def determine_side(self, side_enum: str) -> Literal["A", "B"]:
        """
        Deterministic side assignment for surebet pairing.

        Maps bet side enums to canonical surebet sides A/B:
        - Side A: OVER, YES, TEAM_A
        - Side B: UNDER, NO, TEAM_B

        THIS MAPPING IS IMMUTABLE - never changes after initial assignment.

        Args:
            side_enum: Bet side from bets.side field

        Returns:
            "A" or "B" for surebet side assignment

        Raises:
            ValueError: If side_enum is not recognized
        """
        if side_enum in ("OVER", "YES", "TEAM_A"):
            return "A"
        elif side_enum in ("UNDER", "NO", "TEAM_B"):
            return "B"
        else:
            raise ValueError(f"Unknown side enum: {side_enum}")

    def _get_opposite_sides(self, side: str) -> Tuple[str, ...]:
        """Get logical opposite sides for a given bet side.

        Args:
            side: Bet side (OVER, UNDER, YES, NO, TEAM_A, TEAM_B)

        Returns:
            Tuple of opposite side values

        Examples:
            OVER → (UNDER,)
            YES → (NO,)
            TEAM_A → (TEAM_B,)
        """
        opposites = {
            "OVER": ("UNDER",),
            "UNDER": ("OVER",),
            "YES": ("NO",),
            "NO": ("YES",),
            "TEAM_A": ("TEAM_B",),
            "TEAM_B": ("TEAM_A",),
        }

        if side not in opposites:
            logger.warning("unknown_side_for_opposite", side=side)
            return ()

        return opposites[side]

    def _query_opposite_side_candidates(
        self, bet: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Query database for opposite-side candidates that can form a surebet.

        Matches on:
        - canonical_event_id (same event)
        - market_code (same market type)
        - period_scope (same period)
        - line_value (same line, or both NULL)
        - opposite side (logical complement)
        - is_supported = 1 (only supported bet types)
        - status IN ('verified', 'matched') (ready to be matched or already matched)

        Args:
            bet: Current bet dictionary

        Returns:
            List of candidate bet dictionaries
        """
        opposite_sides = self._get_opposite_sides(bet["side"])

        if not opposite_sides:
            return []

        # Build query with dynamic IN clause for opposite sides
        placeholders = ",".join("?" * len(opposite_sides))

        # Handle NULL line_value matching
        line_value = bet.get("line_value")
        if line_value is None:
            line_clause = "line_value IS NULL"
            params = [
                bet["canonical_event_id"],
                bet["market_code"],
                bet["period_scope"],
                *opposite_sides,
            ]
        else:
            line_clause = "line_value = ?"
            params = [
                bet["canonical_event_id"],
                bet["market_code"],
                bet["period_scope"],
                line_value,
                *opposite_sides,
            ]

        query = f"""
            SELECT * FROM bets
            WHERE status IN ('verified', 'matched')
              AND is_supported = 1
              AND canonical_event_id = ?
              AND market_code = ?
              AND period_scope = ?
              AND {line_clause}
              AND side IN ({placeholders})
        """

        cursor = self.db.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def _has_required_fields(self, bet: Dict[str, Any]) -> bool:
        """Check if bet has all required fields for matching.

        Args:
            bet: Bet dictionary

        Returns:
            True if all required fields present, False otherwise
        """
        required = ["canonical_event_id", "market_code", "period_scope", "side"]
        return all(bet.get(field) is not None for field in required)

    def _find_or_create_surebet(
        self, bet: Dict[str, Any], candidates: List[Dict[str, Any]]
    ) -> int:
        """Find existing surebet or create new one.

        Checks if any candidates are already linked to a surebet with matching criteria.
        If found, returns that surebet_id. Otherwise, creates new surebet.

        Args:
            bet: Current bet
            candidates: List of opposite-side candidates

        Returns:
            surebet_id (existing or newly created)
        """
        # Check if any candidate is already in a surebet with matching criteria
        for candidate in candidates:
            existing_surebet_id = self._get_surebet_id_for_bet(candidate["id"])
            if existing_surebet_id:
                # Verify surebet matches our criteria
                surebet = self._load_surebet(existing_surebet_id)
                if (
                    surebet
                    and surebet["canonical_event_id"] == bet["canonical_event_id"]
                    and surebet["market_code"] == bet["market_code"]
                    and surebet["period_scope"] == bet["period_scope"]
                    and surebet["line_value"] == bet.get("line_value")
                ):
                    logger.debug(
                        "using_existing_surebet",
                        surebet_id=existing_surebet_id,
                        bet_id=bet["id"],
                    )
                    return existing_surebet_id

        # No existing surebet found, create new one
        return self._create_surebet(bet)

    def _create_surebet(self, bet: Dict[str, Any]) -> int:
        """Create new surebet row.

        Args:
            bet: Bet with event/market criteria

        Returns:
            Newly created surebet_id
        """
        timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")

        cursor = self.db.execute(
            """
            INSERT INTO surebets (
                canonical_event_id,
                canonical_market_id,
                market_code,
                period_scope,
                line_value,
                status,
                created_at_utc
            )
            VALUES (?, ?, ?, ?, ?, 'open', ?)
            """,
            (
                bet["canonical_event_id"],
                bet.get("canonical_market_id"),
                bet["market_code"],
                bet["period_scope"],
                bet.get("line_value"),
                timestamp,
            ),
        )
        self.db.commit()
        surebet_id = cursor.lastrowid

        logger.info(
            "surebet_created",
            surebet_id=surebet_id,
            canonical_event_id=bet["canonical_event_id"],
            market_code=bet["market_code"],
        )

        return surebet_id

    def _link_bet_to_surebet(
        self, bet_id: int, bet_side: str, surebet_id: int
    ) -> None:
        """Link bet to surebet with deterministic side assignment.

        Args:
            bet_id: Bet ID to link
            bet_side: Bet side enum (OVER, UNDER, etc.)
            surebet_id: Surebet ID to link to
        """
        # Check if link already exists (idempotency)
        cursor = self.db.execute(
            """
            SELECT surebet_id FROM surebet_bets
            WHERE surebet_id = ? AND bet_id = ?
            """,
            (surebet_id, bet_id),
        )
        if cursor.fetchone():
            logger.debug(
                "bet_already_linked",
                bet_id=bet_id,
                surebet_id=surebet_id,
            )
            return

        # Determine side (A or B)
        side = self.determine_side(bet_side)

        # Insert link
        self.db.execute(
            """
            INSERT INTO surebet_bets (surebet_id, bet_id, side)
            VALUES (?, ?, ?)
            """,
            (surebet_id, bet_id, side),
        )
        self.db.commit()

        logger.debug(
            "bet_linked_to_surebet",
            bet_id=bet_id,
            surebet_id=surebet_id,
            side=side,
        )

    def _update_bet_status(self, bet_id: int, status: str) -> None:
        """Update bet status.

        Args:
            bet_id: Bet ID
            status: New status value
        """
        timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")

        try:
            self.db.execute(
                """
                UPDATE bets
                SET status = ?, updated_at_utc = ?
                WHERE id = ?
                """,
                (status, timestamp, bet_id),
            )

            if status == "matched":
                bet_snapshot = self._load_bet(bet_id)
                if bet_snapshot:
                    stake_service = StakeLedgerService(self.db)
                    stake_service.sync_bet_stake(
                        bet=bet_snapshot,
                        created_by="surebet_matcher",
                        note=f"Stake capture during matching (bet #{bet_id})",
                        release_when_missing=False,
                    )

            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        logger.debug("bet_status_updated", bet_id=bet_id, status=status)

    def _load_bet(self, bet_id: int) -> Optional[Dict[str, Any]]:
        """Load bet by ID.

        Args:
            bet_id: Bet ID

        Returns:
            Bet dictionary or None if not found
        """
        cursor = self.db.execute("SELECT * FROM bets WHERE id = ?", (bet_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def _load_surebet(self, surebet_id: int) -> Optional[Dict[str, Any]]:
        """Load surebet by ID.

        Args:
            surebet_id: Surebet ID

        Returns:
            Surebet dictionary or None if not found
        """
        cursor = self.db.execute(
            "SELECT * FROM surebets WHERE id = ?", (surebet_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def _get_surebet_id_for_bet(self, bet_id: int) -> Optional[int]:
        """Get surebet ID for a given bet (if linked).

        Args:
            bet_id: Bet ID

        Returns:
            surebet_id or None if not linked
        """
        cursor = self.db.execute(
            "SELECT surebet_id FROM surebet_bets WHERE bet_id = ?", (bet_id,)
        )
        row = cursor.fetchone()
        return row["surebet_id"] if row else None

    def _update_surebet_risk(self, surebet_id: int) -> None:
        """Calculate and store risk analysis for a surebet.

        This method is called after bet matching to ensure surebet risk metrics
        are up-to-date. It calculates worst-case profit, ROI, and risk classification.

        Args:
            surebet_id: Surebet ID to update
        """
        try:
            # Calculate risk using risk calculator
            risk_data = self.risk_calculator.calculate_surebet_risk(surebet_id)

            # Update surebet with calculated values
            timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")

            self.db.execute(
                """
                UPDATE surebets
                SET worst_case_profit_eur = ?,
                    total_staked_eur = ?,
                    roi = ?,
                    risk_classification = ?,
                    updated_at_utc = ?
                WHERE id = ?
                """,
                (
                    str(risk_data["worst_case_profit_eur"]),
                    str(risk_data["total_staked_eur"]),
                    str(risk_data["roi"]),
                    risk_data["risk_classification"],
                    timestamp,
                    surebet_id,
                ),
            )
            self.db.commit()

            logger.info(
                "surebet_risk_updated",
                surebet_id=surebet_id,
                risk_classification=risk_data["risk_classification"],
                roi=str(risk_data["roi"]),
                worst_case_profit_eur=str(risk_data["worst_case_profit_eur"]),
            )

        except Exception as e:
            logger.error(
                "surebet_risk_update_failed",
                surebet_id=surebet_id,
                error=str(e),
            )
            # Don't fail the matching operation if risk calculation fails
            # This is a non-critical enhancement
