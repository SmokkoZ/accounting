"""
Matching service for suggesting canonical events and markets for incoming bets.

The service exposes a single `suggest_for_bet` entry point that returns
high-confidence suggestions which can be surfaced in the UI for one-click
approval and batch workflows.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from rapidfuzz import fuzz

from src.domain.market_taxonomy import CANONICAL_MARKETS
from src.services.event_normalizer import EventNormalizer


def _parse_iso8601(timestamp: Optional[str]) -> Optional[datetime]:
    """Parse timestamp with optional trailing Z into aware datetime."""
    if not timestamp:
        return None
    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None


def _hours_between(a: Optional[datetime], b: Optional[datetime]) -> Optional[float]:
    """Return absolute hour difference between datetimes."""
    if not a or not b:
        return None
    delta = abs(a - b)
    return delta.total_seconds() / 3600.0


def _words_from_code(code: str) -> str:
    """Convert canonical codes like TOTAL_GOALS_OVER_UNDER to readable text."""
    return code.replace("_", " ").title()


@dataclass
class EventSuggestion:
    """Suggested canonical event for a bet."""

    event_id: int
    name: str
    kickoff_time_utc: Optional[str]
    similarity: float
    reason: str
    pair_key_match: bool
    hours_apart: Optional[float]

    HIGH_CONFIDENCE_THRESHOLD = 92.0

    @property
    def is_high_confidence(self) -> bool:
        """True when similarity is strong enough to auto-approve."""
        if self.similarity >= self.HIGH_CONFIDENCE_THRESHOLD:
            return True
        return self.pair_key_match and self.similarity >= 85.0

    def option_label(self) -> str:
        """Format option label like the existing dropdown."""
        date_part = self.kickoff_time_utc[:10] if self.kickoff_time_utc else "TBD"
        return f"{self.name} ({date_part})"


@dataclass
class MarketSuggestion:
    """Suggested canonical market for a bet."""

    canonical_market_id: int
    market_code: str
    description: str
    score: float
    reason: str
    period_scope: Optional[str]
    side: Optional[str]
    line_value: Optional[str]

    HIGH_CONFIDENCE_THRESHOLD = 90.0

    @property
    def is_high_confidence(self) -> bool:
        """True when score is strong enough to auto-approve."""
        return self.score >= self.HIGH_CONFIDENCE_THRESHOLD

    def option_label(self) -> str:
        """Format option label like the existing dropdown."""
        return f"{self.description} ({self.market_code})"


@dataclass
class MatchingSuggestions:
    """Aggregate suggestions for a single bet."""

    events: List[EventSuggestion]
    markets: List[MarketSuggestion]

    def best_auto_payload(self, bet: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Return approval payload when both event and market are high confidence."""
        event = next((e for e in self.events if e.is_high_confidence), None)
        market = next((m for m in self.markets if m.is_high_confidence), None)
        if not event or not market:
            return None

        stake_raw = bet.get("stake") or bet.get("stake_original")
        odds_raw = bet.get("odds") or bet.get("odds_original")

        stake = str(stake_raw) if stake_raw is not None else "0"
        odds = str(odds_raw) if odds_raw is not None else "1.0"

        payout = bet.get("payout")
        if not payout and stake_raw is not None and odds_raw is not None:
            try:
                payout = str(Decimal(str(stake_raw)) * Decimal(str(odds_raw)))
            except (InvalidOperation, ValueError):
                payout = None
        currency = bet.get("currency") or bet.get("stake_currency") or "EUR"

        payload = {
            "auto_approval": True,
            "canonical_event_id": event.event_id,
            "canonical_event_name": event.name,
            "canonical_event_kickoff": event.kickoff_time_utc,
            "market_code": market.market_code,
            "canonical_market_id": market.canonical_market_id,
            "period_scope": market.period_scope,
            "line_value": market.line_value,
            "side": market.side,
            "stake_original": stake,
            "odds_original": odds,
            "payout": str(payout) if payout is not None else None,
            "currency": currency,
        }
        return payload


class MatchingService:
    """Service that computes fuzzy matching suggestions for incoming bets."""

    EVENT_LOOKBACK_DAYS = 3
    MAX_EVENT_CANDIDATES = 40
    MAX_MARKET_SUGGESTIONS = 5

    def __init__(self, db: sqlite3.Connection):
        self.db = db
        self.db.row_factory = sqlite3.Row

    def suggest_for_bet(self, bet: Dict[str, Any]) -> MatchingSuggestions:
        """Compute event and market suggestions for the provided bet."""
        events = self._suggest_events(bet)
        markets = self._suggest_markets(bet)
        return MatchingSuggestions(events=events, markets=markets)

    # ------------------------------------------------------------------
    # Event suggestions
    # ------------------------------------------------------------------

    def _suggest_events(self, bet: Dict[str, Any]) -> List[EventSuggestion]:
        raw_event = bet.get("selection_text") or bet.get("canonical_event")
        if not raw_event:
            return []

        normalized_input = EventNormalizer.normalize_event_name(raw_event)
        if not normalized_input:
            return []

        kickoff_input = _parse_iso8601(bet.get("kickoff_time_utc"))
        pair = EventNormalizer.compute_pair_key(normalized_input)
        pair_key = pair[2] if pair else None

        suggestions: List[EventSuggestion] = []
        seen_ids: set[int] = set()

        # Always include already linked canonical event first (if any).
        existing_id = bet.get("canonical_event_id")
        if existing_id:
            row = self.db.execute(
                """
                SELECT id, normalized_event_name, kickoff_time_utc, pair_key
                FROM canonical_events
                WHERE id = ?
                """,
                (existing_id,),
            ).fetchone()
            if row:
                suggestions.append(
                    EventSuggestion(
                        event_id=int(row["id"]),
                        name=row["normalized_event_name"],
                        kickoff_time_utc=row["kickoff_time_utc"],
                        similarity=100.0,
                        reason="Already linked",
                        pair_key_match=bool(pair_key and row["pair_key"] == pair_key),
                        hours_apart=_hours_between(kickoff_input, _parse_iso8601(row["kickoff_time_utc"])),
                    )
                )
                seen_ids.add(int(row["id"]))

        candidate_rows = self._fetch_event_candidates(pair_key, kickoff_input)

        for row in candidate_rows:
            event_id = int(row["id"])
            if event_id in seen_ids:
                continue

            candidate_name = row["normalized_event_name"]
            candidate_kickoff = row["kickoff_time_utc"]
            similarity = float(
                fuzz.token_set_ratio(normalized_input, candidate_name or "")
            )

            pair_match = bool(pair_key and row["pair_key"] == pair_key)
            kickoff_candidate = _parse_iso8601(candidate_kickoff)
            hours_apart = _hours_between(kickoff_input, kickoff_candidate)

            # Boost score for pair-key matches and close kickoff times.
            if pair_match:
                similarity = min(100.0, similarity + 5.0)
            if hours_apart is not None:
                if hours_apart <= 4:
                    similarity = min(100.0, similarity + 4.0)
                elif hours_apart <= 12:
                    similarity = min(100.0, similarity + 2.0)

            reason = "Pair key match" if pair_match else "Fuzzy name match"
            if hours_apart is not None:
                reason += f", {hours_apart:.1f}h apart"

            suggestions.append(
                EventSuggestion(
                    event_id=event_id,
                    name=candidate_name,
                    kickoff_time_utc=candidate_kickoff,
                    similarity=similarity,
                    reason=reason,
                    pair_key_match=pair_match,
                    hours_apart=hours_apart,
                )
            )
            seen_ids.add(event_id)

        # Sort by similarity descending, then by earliest time difference.
        suggestions.sort(
            key=lambda s: (
                s.similarity,
                -(s.hours_apart or 9999.0),
            ),
            reverse=True,
        )

        return suggestions[:5]

    def _fetch_event_candidates(
        self, pair_key: Optional[str], kickoff_input: Optional[datetime]
    ) -> List[sqlite3.Row]:
        """Fetch candidate canonical events by pair-key and kickoff proximity."""
        candidates: List[sqlite3.Row] = []
        seen: set[int] = set()

        if pair_key:
            rows = self.db.execute(
                """
                SELECT id, normalized_event_name, kickoff_time_utc, pair_key
                FROM canonical_events
                WHERE pair_key = ?
                ORDER BY updated_at_utc DESC
                LIMIT ?
                """,
                (pair_key, self.MAX_EVENT_CANDIDATES),
            ).fetchall()
            for row in rows:
                event_id = int(row["id"])
                if event_id not in seen:
                    candidates.append(row)
                    seen.add(event_id)

        if kickoff_input:
            window_start = (kickoff_input - timedelta(days=self.EVENT_LOOKBACK_DAYS)).isoformat().replace(
                "+00:00", "Z"
            )
            window_end = (kickoff_input + timedelta(days=self.EVENT_LOOKBACK_DAYS)).isoformat().replace(
                "+00:00", "Z"
            )
            rows = self.db.execute(
                """
                SELECT id, normalized_event_name, kickoff_time_utc, pair_key
                FROM canonical_events
                WHERE kickoff_time_utc IS NOT NULL
                  AND kickoff_time_utc BETWEEN ? AND ?
                ORDER BY ABS(julianday(kickoff_time_utc) - julianday(?))
                LIMIT ?
                """,
                (window_start, window_end, kickoff_input.isoformat().replace("+00:00", "Z"), self.MAX_EVENT_CANDIDATES),
            ).fetchall()
            for row in rows:
                event_id = int(row["id"])
                if event_id not in seen:
                    candidates.append(row)
                    seen.add(event_id)

        # Fallback: pull most recent canonical events if we still have no candidates.
        if not candidates:
            rows = self.db.execute(
                """
                SELECT id, normalized_event_name, kickoff_time_utc, pair_key
                FROM canonical_events
                ORDER BY updated_at_utc DESC
                LIMIT ?
                """,
                (self.MAX_EVENT_CANDIDATES,),
            ).fetchall()
            for row in rows:
                event_id = int(row["id"])
                if event_id not in seen:
                    candidates.append(row)
                    seen.add(event_id)

        return candidates

    # ------------------------------------------------------------------
    # Market suggestions
    # ------------------------------------------------------------------

    def _suggest_markets(self, bet: Dict[str, Any]) -> List[MarketSuggestion]:
        markets: List[MarketSuggestion] = []

        canonical_markets = self._load_canonical_markets()
        if not canonical_markets:
            return markets

        market_hint = self._build_market_hint(bet)
        selected_code = (
            str(bet.get("market_code")).upper().strip()
            if bet.get("market_code")
            else None
        )

        for market in canonical_markets:
            market_code = market["market_code"]
            description = market["description"]
            candidate_text = f"{market_code} {description}"

            if selected_code and market_code == selected_code:
                score = 100.0
                reason = "Matches extracted market code"
            else:
                score = float(
                    fuzz.token_set_ratio(market_hint, candidate_text)
                    if market_hint
                    else 0.0
                )
                reason = "Fuzzy description match" if market_hint else "Candidate"

            markets.append(
                MarketSuggestion(
                    canonical_market_id=int(market["id"]),
                    market_code=market_code,
                    description=description,
                    score=score,
                    reason=reason,
                    period_scope=bet.get("period_scope"),
                    side=bet.get("side"),
                    line_value=str(bet.get("line_value"))
                    if bet.get("line_value") is not None
                    else None,
                )
            )

        # Sort by score descending and keep top results.
        markets.sort(key=lambda m: m.score, reverse=True)
        return markets[: self.MAX_MARKET_SUGGESTIONS]

    def _load_canonical_markets(self) -> List[sqlite3.Row]:
        return self.db.execute(
            """
            SELECT id, market_code, description
            FROM canonical_markets
            ORDER BY description
            """
        ).fetchall()

    def _build_market_hint(self, bet: Dict[str, Any]) -> str:
        parts: List[str] = []

        market_code = bet.get("market_code")
        if market_code:
            parts.append(_words_from_code(str(market_code)))

        # Normalized descriptions from taxonomy help when code is missing.
        if market_code and market_code in CANONICAL_MARKETS:
            parts.append(CANONICAL_MARKETS[market_code])

        market_type = bet.get("market_type")
        if market_type and market_type != market_code:
            parts.append(str(market_type).replace("_", " ").title())

        if bet.get("period_scope"):
            parts.append(str(bet["period_scope"]).replace("_", " ").title())

        if bet.get("side"):
            parts.append(str(bet["side"]).title())

        if bet.get("line_value"):
            parts.append(str(bet["line_value"]))

        return " ".join(parts).strip()
