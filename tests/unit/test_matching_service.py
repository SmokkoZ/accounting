"""
Unit tests for MatchingService event and market suggestions.
"""

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from src.core.schema import create_schema
from src.core.seed_data import insert_seed_data
from src.services.event_normalizer import EventNormalizer
from src.services.matching_service import MatchingService


@pytest.fixture
def test_db():
    """Provide an in-memory database with seeded data."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    insert_seed_data(conn)
    yield conn
    conn.close()


@pytest.fixture
def matching_service(test_db):
    """Create a MatchingService instance for tests."""
    return MatchingService(test_db)


def _insert_canonical_event(
    conn: sqlite3.Connection, name: str, kickoff_time: str
) -> int:
    normalized = EventNormalizer.normalize_event_name(name)
    team1, team2, pair_key = EventNormalizer.compute_pair_key(normalized)  # type: ignore[arg-type]
    cursor = conn.execute(
        """
        INSERT INTO canonical_events (
            normalized_event_name,
            sport,
            team1_slug,
            team2_slug,
            pair_key,
            kickoff_time_utc
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (normalized, "football", team1, team2, pair_key, kickoff_time),
    )
    conn.commit()
    return int(cursor.lastrowid)


def test_suggest_for_bet_returns_high_confidence_event_and_market(
    matching_service: MatchingService, test_db: sqlite3.Connection
) -> None:
    """MatchingService should surface high-confidence suggestions when data aligns."""
    kickoff = datetime.now(UTC).replace(microsecond=0)
    kickoff_iso = kickoff.isoformat().replace("+00:00", "Z")

    event_id = _insert_canonical_event(
        test_db, "Manchester United vs Liverpool", kickoff_iso
    )

    bet = {
        "bet_id": 42,
        "selection_text": "Man United vs Liverpool",
        "kickoff_time_utc": kickoff_iso,
        "market_code": "TOTAL_GOALS_OVER_UNDER",
        "period_scope": "FULL_MATCH",
        "line_value": "2.5",
        "side": "OVER",
        "stake": "100.00",
        "odds": "1.95",
        "payout": "195.00",
        "currency": "AUD",
    }

    suggestions = matching_service.suggest_for_bet(bet)

    assert suggestions.events, "Expected event suggestions"
    top_event = suggestions.events[0]
    assert top_event.event_id == event_id
    assert top_event.is_high_confidence

    assert suggestions.markets, "Expected market suggestions"
    top_market = suggestions.markets[0]
    assert top_market.market_code == "TOTAL_GOALS_OVER_UNDER"
    assert top_market.is_high_confidence

    payload = suggestions.best_auto_payload(bet)
    assert payload is not None
    assert payload["canonical_event_id"] == event_id
    assert payload["market_code"] == "TOTAL_GOALS_OVER_UNDER"


def test_best_auto_payload_requires_high_confidence(
    matching_service: MatchingService
) -> None:
    """Without matching data, MatchingService should not auto-approve."""
    bet = {
        "bet_id": 7,
        "selection_text": "Unmatched Team A vs Team B",
        "kickoff_time_utc": (datetime.now(UTC) + timedelta(days=10))
        .isoformat()
        .replace("+00:00", "Z"),
        "market_code": None,
        "period_scope": None,
        "line_value": None,
        "side": None,
        "stake": "50.00",
        "odds": "2.10",
        "payout": "105.00",
        "currency": "EUR",
    }

    suggestions = matching_service.suggest_for_bet(bet)
    assert suggestions.events == []
    assert suggestions.markets
    assert suggestions.best_auto_payload(bet) is None
