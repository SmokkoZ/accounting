from __future__ import annotations

import sqlite3

from src.services.market_normalizer import MarketNormalizer


def _db():
    conn = sqlite3.connect(":memory:")
    # Minimal schema for canonical_markets
    conn.execute(
        "CREATE TABLE canonical_markets (id INTEGER PRIMARY KEY, market_code TEXT UNIQUE, description TEXT, created_at_utc TEXT)"
    )
    return conn


def test_normalize_goals_ou_full_match():
    db = _db()
    norm = MarketNormalizer(db)
    result = norm.normalize(
        sport="football",
        market_label="Over/Under 2.5 Goals (Full Time)",
        market_code_guess=None,
        period_scope_text="FULL MATCH",
        side_text="Over",
        line_value="2.5",
    )
    assert result["market_code"] == "TOTAL_GOALS_OVER_UNDER"
    assert result["period_scope"] == "FULL_MATCH"
    assert result["side"] == "OVER"
    assert float(result["normalization_confidence"]) >= 0.7


def test_normalize_cards_ou_from_label():
    db = _db()
    norm = MarketNormalizer(db)
    result = norm.normalize(
        sport="soccer",
        market_label="Total Cards Over/Under",
        market_code_guess=None,
        period_scope_text=None,
        side_text="Under",
        line_value="4.5",
    )
    assert result["market_code"] == "TOTAL_CARDS_OVER_UNDER"
    assert result["side"] == "UNDER"


def test_normalize_tennis_match_winner_guess():
    db = _db()
    norm = MarketNormalizer(db)
    result = norm.normalize(
        sport="tennis",
        market_label=None,
        market_code_guess="MATCH_WINNER",
        period_scope_text=None,
        side_text="Player A",
        line_value=None,
    )
    assert result["market_code"] == "MATCH_WINNER"
    assert result["side"] == "TEAM_A"


def test_normalize_italian_corners_label_and_side():
    db = _db()
    norm = MarketNormalizer(db)
    result = norm.normalize(
        sport="football",
        market_label="Calci d'angolo totali over 4.5",
        market_code_guess=None,
        period_scope_text="Partita Intera",
        side_text="over",
        line_value="4.5",
    )
    assert result["market_code"] == "TOTAL_CORNERS_OVER_UNDER"
    assert result["period_scope"] == "FULL_MATCH"
    assert result["side"] == "OVER"


def test_normalize_italian_red_card_yes_no():
    db = _db()
    norm = MarketNormalizer(db)
    result = norm.normalize(
        sport="football",
        market_label="Cartellino rosso",
        market_code_guess=None,
        period_scope_text=None,
        side_text="sì",
        line_value=None,
    )
    assert result["market_code"] == "RED_CARD_AWARDED"
    assert result["side"] == "YES"
