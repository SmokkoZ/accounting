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


def test_normalize_team_specific_corners_away():
    db = _db()
    norm = MarketNormalizer(db)
    result = norm.normalize(
        sport="football",
        market_label="7 Or More Corners - Away Team Over Corners",
        market_code_guess=None,
        period_scope_text=None,
        side_text="OVER",
        line_value=None,
    )
    assert result["market_code"] == "AWAY_TEAM_TOTAL_CORNERS_OVER_UNDER"
    assert result["side"] == "OVER"


def test_normalize_team_specific_corners_home():
    db = _db()
    norm = MarketNormalizer(db)
    result = norm.normalize(
        sport="football",
        market_label="Corner Totals - Home Team Under",
        market_code_guess=None,
        period_scope_text=None,
        side_text="UNDER",
        line_value="5.5",
    )
    assert result["market_code"] == "HOME_TEAM_TOTAL_CORNERS_OVER_UNDER"
    assert result["side"] == "UNDER"


def test_normalize_home_goals_under_over_italian():
    db = _db()
    norm = MarketNormalizer(db)
    result = norm.normalize(
        sport="football",
        market_label="Under/Over Casa (gol squadra casa)",
        market_code_guess=None,
        period_scope_text=None,
        side_text="Over",
        line_value="1.5",
    )
    assert result["market_code"] == "HOME_TEAM_TOTAL_GOALS_OVER_UNDER"
    assert result["side"] == "OVER"


def test_normalize_corners_even_odd_pari():
    db = _db()
    norm = MarketNormalizer(db)
    result = norm.normalize(
        sport="football",
        market_label="Angoli Pari/Dispari (totali)",
        market_code_guess=None,
        period_scope_text=None,
        side_text="Pari",
        line_value=None,
    )
    assert result["market_code"] == "TOTAL_CORNERS_EVEN_ODD"
    assert result["side"] == "EVEN"


def test_normalize_double_chance_label():
    db = _db()
    norm = MarketNormalizer(db)
    result = norm.normalize(
        sport="football",
        market_label="Doppia Chance 1X",
        market_code_guess=None,
        period_scope_text=None,
        side_text="1X",
        line_value=None,
    )
    assert result["market_code"] == "DOUBLE_CHANCE"
    assert result["side"] == "1X"


def test_normalize_dnb_italian_label():
    db = _db()
    norm = MarketNormalizer(db)
    result = norm.normalize(
        sport="football",
        market_label="Rimborso in caso di parità",
        market_code_guess=None,
        period_scope_text=None,
        side_text="Team 1 DNB",
        line_value=None,
    )
    assert result["market_code"] == "DRAW_NO_BET"
    assert result["side"] == "TEAM 1 DNB"


def test_normalize_home_shots_on_target_by_team_label():
    db = _db()
    norm = MarketNormalizer(db)
    result = norm.normalize(
        sport="football",
        market_label="Total Shots on Target by Nantes (Settled using Opta data)",
        market_code_guess=None,
        period_scope_text=None,
        side_text="Under",
        line_value="2.5",
        event_name="Nantes vs Lille",
    )
    assert result["market_code"] == "HOME_TEAM_TOTAL_SHOTS_ON_TARGET_OVER_UNDER"
    assert result["side"] == "UNDER"


def test_normalize_away_shots_on_target_by_team_label():
    db = _db()
    norm = MarketNormalizer(db)
    result = norm.normalize(
        sport="football",
        market_label="Total Shots on Target by Lille (Settled using Opta data)",
        market_code_guess=None,
        period_scope_text=None,
        side_text="Over",
        line_value="1.5",
        event_name="Nantes vs Lille",
    )
    assert result["market_code"] == "AWAY_TEAM_TOTAL_SHOTS_ON_TARGET_OVER_UNDER"
    assert result["side"] == "OVER"


def test_normalize_home_total_shots_by_team_label():
    db = _db()
    norm = MarketNormalizer(db)
    result = norm.normalize(
        sport="football",
        market_label="Total Shots by Nantes",
        market_code_guess=None,
        period_scope_text=None,
        side_text="under",
        line_value="8.5",
        event_name="Nantes vs Lille",
    )
    assert result["market_code"] == "HOME_TEAM_TOTAL_SHOTS_OVER_UNDER"
    assert result["side"] == "UNDER"


def test_normalize_romanian_total_goals_label():
    db = _db()
    norm = MarketNormalizer(db)
    result = norm.normalize(
        sport="football",
        market_label="Peste/Sub 2.5 goluri",
        market_code_guess=None,
        period_scope_text="Meci intreg",
        side_text="peste",
        line_value="2.5",
    )
    assert result["market_code"] == "TOTAL_GOALS_OVER_UNDER"
    assert result["period_scope"] == "FULL_MATCH"
    assert result["side"] == "OVER"


def test_normalize_romanian_home_corners_label():
    db = _db()
    norm = MarketNormalizer(db)
    result = norm.normalize(
        sport="football",
        market_label="Cornere gazda peste 4.5",
        market_code_guess=None,
        period_scope_text=None,
        side_text="peste",
        line_value="4.5",
    )
    assert result["market_code"] == "HOME_TEAM_TOTAL_CORNERS_OVER_UNDER"
    assert result["side"] == "OVER"


def test_normalize_romanian_away_to_score_no():
    db = _db()
    norm = MarketNormalizer(db)
    result = norm.normalize(
        sport="football",
        market_label="Oaspete marcheaza?",
        market_code_guess=None,
        period_scope_text=None,
        side_text="nu",
        line_value=None,
        event_name="Farul vs CFR Cluj",
    )
    assert result["market_code"] == "AWAY_TEAM_TO_SCORE"
    assert result["side"] == "NO"
