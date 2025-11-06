"""
Normalized market taxonomy and synonyms for soccer and tennis two-way markets.

This module defines the canonical market codes supported by the MVP and a
synonym map used by the market normalizer to map bookmaker-specific labels
to normalized codes and period scopes.
"""

from __future__ import annotations

from typing import Dict, List, Tuple
import re


# Canonical market codes (two-way focus)
CANONICAL_MARKETS: Dict[str, str] = {
    # Soccer Over/Under
    "TOTAL_GOALS_OVER_UNDER": "Total Goals Over/Under (Full Match)",
    "FIRST_HALF_TOTAL_GOALS": "1st Half Total Goals Over/Under",
    "SECOND_HALF_TOTAL_GOALS": "2nd Half Total Goals Over/Under",
    "TOTAL_CARDS_OVER_UNDER": "Total Cards Over/Under (Bookings)",
    "TOTAL_CORNERS_OVER_UNDER": "Total Corners Over/Under",
    "HOME_TEAM_TOTAL_CORNERS_OVER_UNDER": "Home Team Total Corners Over/Under",
    "AWAY_TEAM_TOTAL_CORNERS_OVER_UNDER": "Away Team Total Corners Over/Under",
    "TOTAL_SHOTS_OVER_UNDER": "Total Shots Over/Under",
    "TOTAL_SHOTS_ON_TARGET_OVER_UNDER": "Total Shots on Target Over/Under",
    # Soccer yes/no
    "BOTH_TEAMS_TO_SCORE": "Both Teams To Score (Yes/No)",
    "RED_CARD_AWARDED": "Red Card Awarded (Yes/No)",
    "PENALTY_AWARDED": "Penalty Awarded (Yes/No)",
    # Soccer team-side two-way
    "DRAW_NO_BET": "Draw No Bet (Home/Away)",
    "ASIAN_HANDICAP": "Asian Handicap",
    # Tennis
    "MATCH_WINNER": "Match Winner (Two-Way)",
    "TOTAL_GAMES_OVER_UNDER": "Total Games Over/Under (Match)",
   
    # Team totals (goals)
    "HOME_TEAM_TOTAL_GOALS_OVER_UNDER": "Home Team Total Goals Over/Under",
    "AWAY_TEAM_TOTAL_GOALS_OVER_UNDER": "Away Team Total Goals Over/Under",

    # Team totals (cards / bookings)
    "HOME_TEAM_TOTAL_CARDS_OVER_UNDER": "Home Team Total Cards Over/Under",
    "AWAY_TEAM_TOTAL_CARDS_OVER_UNDER": "Away Team Total Cards Over/Under",

    # Team totals (shots)
    "HOME_TEAM_TOTAL_SHOTS_OVER_UNDER": "Home Team Total Shots Over/Under",
    "AWAY_TEAM_TOTAL_SHOTS_OVER_UNDER": "Away Team Total Shots Over/Under",
    "HOME_TEAM_TOTAL_SHOTS_ON_TARGET_OVER_UNDER": "Home Team Total Shots on Target Over/Under",
    "AWAY_TEAM_TOTAL_SHOTS_ON_TARGET_OVER_UNDER": "Away Team Total Shots on Target Over/Under",

    # Match props O/U (teams & totals commonly offered)
    "TOTAL_OFFSIDES_OVER_UNDER": "Total Offsides Over/Under",
    "HOME_TEAM_TOTAL_OFFSIDES_OVER_UNDER": "Home Team Total Offsides Over/Under",
    "AWAY_TEAM_TOTAL_OFFSIDES_OVER_UNDER": "Away Team Total Offsides Over/Under",

    "TOTAL_FOULS_OVER_UNDER": "Total Fouls Over/Under",
    "HOME_TEAM_TOTAL_FOULS_OVER_UNDER": "Home Team Total Fouls Over/Under",
    "AWAY_TEAM_TOTAL_FOULS_OVER_UNDER": "Away Team Total Fouls Over/Under",

    # Team yes/no (two-way)
    "HOME_TEAM_TO_SCORE": "Home Team To Score (Yes/No)",
    "AWAY_TEAM_TO_SCORE": "Away Team To Score (Yes/No)",
    "HOME_TEAM_CLEAN_SHEET": "Home Team Clean Sheet (Yes/No)",
    "AWAY_TEAM_CLEAN_SHEET": "Away Team Clean Sheet (Yes/No)",
    "HOME_TEAM_RED_CARD": "Home Team Red Card Awarded (Yes/No)",
    "AWAY_TEAM_RED_CARD": "Away Team Red Card Awarded (Yes/No)",

    # Even/Odd markets
    "TOTAL_GOALS_EVEN_ODD": "Total Goals Even/Odd",
    "HOME_TEAM_GOALS_EVEN_ODD": "Home Team Goals Even/Odd",
    "AWAY_TEAM_GOALS_EVEN_ODD": "Away Team Goals Even/Odd",
    "TOTAL_CORNERS_EVEN_ODD": "Total Corners Even/Odd",

}


# Period normalization
PERIOD_SYNONYMS: Dict[str, str] = {
    # English
    "FULL_MATCH": "FULL_MATCH",
    "FULL TIME": "FULL_MATCH",
    "FULLTIME": "FULL_MATCH",
    "FT": "FULL_MATCH",
    "MATCH": "FULL_MATCH",
    "REGULATION TIME": "FULL_MATCH",
    "1ST HALF": "FIRST_HALF",
    "FIRST HALF": "FIRST_HALF",
    "H1": "FIRST_HALF",
    "2ND HALF": "SECOND_HALF",
    "SECOND HALF": "SECOND_HALF",
    "H2": "SECOND_HALF",
    # Italian
    "PARTITA INTERA": "FULL_MATCH",
    "TEMPO PIENO": "FULL_MATCH",
    "TEMPO REGOLAMENTARE": "FULL_MATCH",
    "PRIMO TEMPO": "FIRST_HALF",
    "1 TEMPO": "FIRST_HALF",
    "1T": "FIRST_HALF",
    "SECONDO TEMPO": "SECOND_HALF",
    "2 TEMPO": "SECOND_HALF",
    "2T": "SECOND_HALF",
}


# Market label synonyms to normalized code with optional implied period
# Order matters (checked in sequence for matching)
MARKET_SYNONYMS: List[Tuple[str, str, str | None]] = [
    # Double chance / Draw no bet / BTTS high-usage markets
    ("DOUBLE CHANCE", "DOUBLE_CHANCE", None),
    ("DOPPIA CHANCE", "DOUBLE_CHANCE", None),
    ("1X2 DOPPIA CHANCE", "DOUBLE_CHANCE", None),
    ("GOAL/NO GOAL", "BOTH_TEAMS_TO_SCORE", None),
    ("GOAL / NO GOAL", "BOTH_TEAMS_TO_SCORE", None),
    ("GOL/NO GOL", "BOTH_TEAMS_TO_SCORE", None),
    ("GOL / NO GOL", "BOTH_TEAMS_TO_SCORE", None),
    ("GG/NG", "BOTH_TEAMS_TO_SCORE", None),

    # Soccer goals O/U
    ("OVER/UNDER GOALS", "TOTAL_GOALS_OVER_UNDER", None),
    ("UNDER/OVER", "TOTAL_GOALS_OVER_UNDER", None),
    ("TOTAL GOALS", "TOTAL_GOALS_OVER_UNDER", None),
    ("GOALS OVER/UNDER", "TOTAL_GOALS_OVER_UNDER", None),
    ("GOALS O/U", "TOTAL_GOALS_OVER_UNDER", None),
    ("GOL TOTALI", "TOTAL_GOALS_OVER_UNDER", None),
    ("TOTALE GOL", "TOTAL_GOALS_OVER_UNDER", None),
    ("1ST HALF GOALS", "FIRST_HALF_TOTAL_GOALS", "FIRST_HALF"),
    ("FIRST HALF GOALS", "FIRST_HALF_TOTAL_GOALS", "FIRST_HALF"),
    ("2ND HALF GOALS", "SECOND_HALF_TOTAL_GOALS", "SECOND_HALF"),
    ("SECOND HALF GOALS", "SECOND_HALF_TOTAL_GOALS", "SECOND_HALF"),
    ("PRIMO TEMPO GOL", "FIRST_HALF_TOTAL_GOALS", "FIRST_HALF"),
    ("SECONDO TEMPO GOL", "SECOND_HALF_TOTAL_GOALS", "SECOND_HALF"),
    # Cards / bookings
    ("TOTAL CARDS", "TOTAL_CARDS_OVER_UNDER", None),
    ("BOOKINGS", "TOTAL_CARDS_OVER_UNDER", None),
    ("CARDS OVER/UNDER", "TOTAL_CARDS_OVER_UNDER", None),
    ("CARTELLINI", "TOTAL_CARDS_OVER_UNDER", None),
    ("CARTELLINI TOTALI", "TOTAL_CARDS_OVER_UNDER", None),
    ("AMMONIZIONI", "TOTAL_CARDS_OVER_UNDER", None),
    # Corners
    ("TOTAL CORNERS", "TOTAL_CORNERS_OVER_UNDER", None),
    ("CORNERS OVER/UNDER", "TOTAL_CORNERS_OVER_UNDER", None),
    ("OVER/UNDER CORNERS", "TOTAL_CORNERS_OVER_UNDER", None),
    ("UNDER/OVER CORNERS", "TOTAL_CORNERS_OVER_UNDER", None),
    ("CALCI D'ANGOLO", "TOTAL_CORNERS_OVER_UNDER", None),
    ("UNDER/OVER CALCI D'ANGOLO", "TOTAL_CORNERS_OVER_UNDER", None),
    ("OVER/UNDER CALCI D'ANGOLO", "TOTAL_CORNERS_OVER_UNDER", None),
    ("ANGOLI", "TOTAL_CORNERS_OVER_UNDER", None),
    ("ANGOLI TOTALI", "TOTAL_CORNERS_OVER_UNDER", None),
    ("CORNERS TOTALI", "TOTAL_CORNERS_OVER_UNDER", None),
    ("NUMERO CALCI D'ANGOLO DELLA SQUADRA", "HOME_TEAM_TOTAL_CORNERS_OVER_UNDER", None),
    ("HOME TEAM CORNERS", "HOME_TEAM_TOTAL_CORNERS_OVER_UNDER", None),
    ("AWAY TEAM CORNERS", "AWAY_TEAM_TOTAL_CORNERS_OVER_UNDER", None),
    ("CORNERS CASA", "HOME_TEAM_TOTAL_CORNERS_OVER_UNDER", None),
    ("CORNERS OSPITE", "AWAY_TEAM_TOTAL_CORNERS_OVER_UNDER", None),
    ("ANGOLI CASA", "HOME_TEAM_TOTAL_CORNERS_OVER_UNDER", None),
    ("ANGOLI OSPITE", "AWAY_TEAM_TOTAL_CORNERS_OVER_UNDER", None),
    ("UNDER/OVER ANGOLI CASA", "HOME_TEAM_TOTAL_CORNERS_OVER_UNDER", None),
    ("UNDER/OVER ANGOLI OSPITE", "AWAY_TEAM_TOTAL_CORNERS_OVER_UNDER", None),
    ("OVER/UNDER ANGOLI CASA", "HOME_TEAM_TOTAL_CORNERS_OVER_UNDER", None),
    ("OVER/UNDER ANGOLI OSPITE", "AWAY_TEAM_TOTAL_CORNERS_OVER_UNDER", None),
    # Shots
    ("TOTAL SHOTS ON TARGET", "TOTAL_SHOTS_ON_TARGET_OVER_UNDER", None),
    ("SHOTS ON TARGET", "TOTAL_SHOTS_ON_TARGET_OVER_UNDER", None),
    ("SOT", "TOTAL_SHOTS_ON_TARGET_OVER_UNDER", None),
    ("TOTAL SHOTS", "TOTAL_SHOTS_OVER_UNDER", None),
    ("SHOTS OVER/UNDER", "TOTAL_SHOTS_OVER_UNDER", None),
    ("TIRI IN PORTA", "TOTAL_SHOTS_ON_TARGET_OVER_UNDER", None),
    ("TIRI", "TOTAL_SHOTS_OVER_UNDER", None),
    # Yes/No soccer
    ("BOTH TEAMS TO SCORE", "BOTH_TEAMS_TO_SCORE", None),
    ("BTTS", "BOTH_TEAMS_TO_SCORE", None),
    ("ENTRAMBE LE SQUADRE SEGNANO", "BOTH_TEAMS_TO_SCORE", None),
    ("GOAL/NOGOAL", "BOTH_TEAMS_TO_SCORE", None),
    ("GOL/NOGOL", "BOTH_TEAMS_TO_SCORE", None),
    ("RED CARD", "RED_CARD_AWARDED", None),
    ("RED CARD AWARDED", "RED_CARD_AWARDED", None),
    ("CARTELLINO ROSSO", "RED_CARD_AWARDED", None),
    ("ESPULSIONE", "RED_CARD_AWARDED", None),
    ("PENALTY AWARDED", "PENALTY_AWARDED", None),
    ("PENALTY IN MATCH", "PENALTY_AWARDED", None),
    ("CALCIO DI RIGORE", "PENALTY_AWARDED", None),
    ("RIGORE", "PENALTY_AWARDED", None),
    # Two-way team markets
    ("DRAW NO BET", "DRAW_NO_BET", None),
    ("DNB", "DRAW_NO_BET", None),
    ("PAREGGIO NESSUNA SCOMMESSA", "DRAW_NO_BET", None),
    ("PAREGGIO RIMBORSO", "DRAW_NO_BET", None),
    ("ASIAN HANDICAP", "ASIAN_HANDICAP", None),
    ("HANDICAP", "ASIAN_HANDICAP", None),
    ("HANDICAP ASIATICO", "ASIAN_HANDICAP", None),
    # Tennis
    ("MATCH WINNER", "MATCH_WINNER", None),
    ("TO WIN MATCH", "MATCH_WINNER", None),
    ("MONEYLINE", "MATCH_WINNER", None),
    ("VINCENTE INCONTRO", "MATCH_WINNER", None),
    ("VINCENTE PARTITA", "MATCH_WINNER", None),
    ("TOTAL GAMES", "TOTAL_GAMES_OVER_UNDER", None),
    ("GAMES OVER/UNDER", "TOTAL_GAMES_OVER_UNDER", None),
    ("GIOCHI TOTALI", "TOTAL_GAMES_OVER_UNDER", None),
    ("GIOCHI O/U", "TOTAL_GAMES_OVER_UNDER", None),
    # --- ADD these entries to MARKET_SYNONYMS ---

    # Team goals O/U (Home/Away)
    ("HOME TEAM GOALS", "HOME_TEAM_TOTAL_GOALS_OVER_UNDER", None),
    ("TEAM A GOALS", "HOME_TEAM_TOTAL_GOALS_OVER_UNDER", None),
    ("CASA GOL", "HOME_TEAM_TOTAL_GOALS_OVER_UNDER", None),
    ("UNDER/OVER CASA", "HOME_TEAM_TOTAL_GOALS_OVER_UNDER", None),
    ("OVER/UNDER CASA", "HOME_TEAM_TOTAL_GOALS_OVER_UNDER", None),
    ("UNDER/OVER SQUADRA CASA", "HOME_TEAM_TOTAL_GOALS_OVER_UNDER", None),
    ("OVER/UNDER SQUADRA CASA", "HOME_TEAM_TOTAL_GOALS_OVER_UNDER", None),
    ("AWAY TEAM GOALS", "AWAY_TEAM_TOTAL_GOALS_OVER_UNDER", None),
    ("TEAM B GOALS", "AWAY_TEAM_TOTAL_GOALS_OVER_UNDER", None),
    ("OSPITE GOL", "AWAY_TEAM_TOTAL_GOALS_OVER_UNDER", None),
    ("UNDER/OVER OSPITE", "AWAY_TEAM_TOTAL_GOALS_OVER_UNDER", None),
    ("OVER/UNDER OSPITE", "AWAY_TEAM_TOTAL_GOALS_OVER_UNDER", None),
    ("UNDER/OVER SQUADRA OSPITE", "AWAY_TEAM_TOTAL_GOALS_OVER_UNDER", None),
    ("OVER/UNDER SQUADRA OSPITE", "AWAY_TEAM_TOTAL_GOALS_OVER_UNDER", None),

    # Team cards O/U (Home/Away)
    ("HOME CARDS", "HOME_TEAM_TOTAL_CARDS_OVER_UNDER", None),
    ("HOME BOOKINGS", "HOME_TEAM_TOTAL_CARDS_OVER_UNDER", None),
    ("TEAM A CARDS", "HOME_TEAM_TOTAL_CARDS_OVER_UNDER", None),
    ("CARTELLINI CASA", "HOME_TEAM_TOTAL_CARDS_OVER_UNDER", None),
    ("UNDER/OVER CARTELLINI CASA", "HOME_TEAM_TOTAL_CARDS_OVER_UNDER", None),
    ("OVER/UNDER CARTELLINI CASA", "HOME_TEAM_TOTAL_CARDS_OVER_UNDER", None),
    ("AWAY CARDS", "AWAY_TEAM_TOTAL_CARDS_OVER_UNDER", None),
    ("AWAY BOOKINGS", "AWAY_TEAM_TOTAL_CARDS_OVER_UNDER", None),
    ("TEAM B CARDS", "AWAY_TEAM_TOTAL_CARDS_OVER_UNDER", None),
    ("CARTELLINI OSPITE", "AWAY_TEAM_TOTAL_CARDS_OVER_UNDER", None),
    ("UNDER/OVER CARTELLINI OSPITE", "AWAY_TEAM_TOTAL_CARDS_OVER_UNDER", None),
    ("OVER/UNDER CARTELLINI OSPITE", "AWAY_TEAM_TOTAL_CARDS_OVER_UNDER", None),

    # Team shots O/U
    ("HOME SHOTS ON TARGET", "HOME_TEAM_TOTAL_SHOTS_ON_TARGET_OVER_UNDER", None),
    ("TEAM A SHOTS ON TARGET", "HOME_TEAM_TOTAL_SHOTS_ON_TARGET_OVER_UNDER", None),
    ("TIRI IN PORTA CASA", "HOME_TEAM_TOTAL_SHOTS_ON_TARGET_OVER_UNDER", None),
    ("AWAY SHOTS ON TARGET", "AWAY_TEAM_TOTAL_SHOTS_ON_TARGET_OVER_UNDER", None),
    ("TEAM B SHOTS ON TARGET", "AWAY_TEAM_TOTAL_SHOTS_ON_TARGET_OVER_UNDER", None),
    ("TIRI IN PORTA OSPITE", "AWAY_TEAM_TOTAL_SHOTS_ON_TARGET_OVER_UNDER", None),

    ("HOME SHOTS", "HOME_TEAM_TOTAL_SHOTS_OVER_UNDER", None),
    ("TEAM A SHOTS", "HOME_TEAM_TOTAL_SHOTS_OVER_UNDER", None),
    ("TIRI CASA", "HOME_TEAM_TOTAL_SHOTS_OVER_UNDER", None),
    ("AWAY SHOTS", "AWAY_TEAM_TOTAL_SHOTS_OVER_UNDER", None),
    ("TEAM B SHOTS", "AWAY_TEAM_TOTAL_SHOTS_OVER_UNDER", None),
    ("TIRI OSPITE", "AWAY_TEAM_TOTAL_SHOTS_OVER_UNDER", None),

    # Even/Odd totals
    ("PARI/DISPARI (TOTALE GOL)", "TOTAL_GOALS_EVEN_ODD", None),
    ("PARI/DISPARI GOL", "TOTAL_GOALS_EVEN_ODD", None),
    ("GOL PARI/DISPARI", "TOTAL_GOALS_EVEN_ODD", None),
    ("ODD/EVEN GOALS", "TOTAL_GOALS_EVEN_ODD", None),
    ("GOALS ODD/EVEN", "TOTAL_GOALS_EVEN_ODD", None),
    ("CASA PARI/DISPARI", "HOME_TEAM_GOALS_EVEN_ODD", None),
    ("PARI/DISPARI CASA", "HOME_TEAM_GOALS_EVEN_ODD", None),
    ("TEAM A ODD/EVEN GOALS", "HOME_TEAM_GOALS_EVEN_ODD", None),
    ("OSPITE PARI/DISPARI", "AWAY_TEAM_GOALS_EVEN_ODD", None),
    ("PARI/DISPARI OSPITE", "AWAY_TEAM_GOALS_EVEN_ODD", None),
    ("TEAM B ODD/EVEN GOALS", "AWAY_TEAM_GOALS_EVEN_ODD", None),
    ("PARI/DISPARI ANGOLI", "TOTAL_CORNERS_EVEN_ODD", None),
    ("ANGOLI PARI/DISPARI", "TOTAL_CORNERS_EVEN_ODD", None),
    ("ODD/EVEN CORNERS", "TOTAL_CORNERS_EVEN_ODD", None),

    # Offsides O/U (totals + team)
    ("TOTAL OFFSIDES", "TOTAL_OFFSIDES_OVER_UNDER", None),
    ("OFFSIDES OVER/UNDER", "TOTAL_OFFSIDES_OVER_UNDER", None),
    ("FUORIGIOCO", "TOTAL_OFFSIDES_OVER_UNDER", None),
    ("HOME OFFSIDES", "HOME_TEAM_TOTAL_OFFSIDES_OVER_UNDER", None),
    ("TEAM A OFFSIDES", "HOME_TEAM_TOTAL_OFFSIDES_OVER_UNDER", None),
    ("FUORIGIOCO CASA", "HOME_TEAM_TOTAL_OFFSIDES_OVER_UNDER", None),
    ("AWAY OFFSIDES", "AWAY_TEAM_TOTAL_OFFSIDES_OVER_UNDER", None),
    ("TEAM B OFFSIDES", "AWAY_TEAM_TOTAL_OFFSIDES_OVER_UNDER", None),
    ("FUORIGIOCO OSPITE", "AWAY_TEAM_TOTAL_OFFSIDES_OVER_UNDER", None),

    # Fouls O/U (totals + team)
    ("TOTAL FOULS", "TOTAL_FOULS_OVER_UNDER", None),
    ("FOULS OVER/UNDER", "TOTAL_FOULS_OVER_UNDER", None),
    ("FALLI", "TOTAL_FOULS_OVER_UNDER", None),
    ("HOME FOULS", "HOME_TEAM_TOTAL_FOULS_OVER_UNDER", None),
    ("TEAM A FOULS", "HOME_TEAM_TOTAL_FOULS_OVER_UNDER", None),
    ("FALLI CASA", "HOME_TEAM_TOTAL_FOULS_OVER_UNDER", None),
    ("AWAY FOULS", "AWAY_TEAM_TOTAL_FOULS_OVER_UNDER", None),
    ("TEAM B FOULS", "AWAY_TEAM_TOTAL_FOULS_OVER_UNDER", None),
    ("FALLI OSPITE", "AWAY_TEAM_TOTAL_FOULS_OVER_UNDER", None),

    # Team to score (Yes/No)
    ("HOME TEAM TO SCORE", "HOME_TEAM_TO_SCORE", None),
    ("TEAM A TO SCORE", "HOME_TEAM_TO_SCORE", None),
    ("SEGNA CASA", "HOME_TEAM_TO_SCORE", None),
    ("AWAY TEAM TO SCORE", "AWAY_TEAM_TO_SCORE", None),
    ("TEAM B TO SCORE", "AWAY_TEAM_TO_SCORE", None),
    ("SEGNA OSPITE", "AWAY_TEAM_TO_SCORE", None),

    # Clean sheet (Yes/No)
    ("HOME CLEAN SHEET", "HOME_TEAM_CLEAN_SHEET", None),
    ("PORTA INVIOLATA CASA", "HOME_TEAM_CLEAN_SHEET", None),
    ("AWAY CLEAN SHEET", "AWAY_TEAM_CLEAN_SHEET", None),
    ("PORTA INVIOLATA OSPITE", "AWAY_TEAM_CLEAN_SHEET", None),

    # Team red card (Yes/No)
    ("HOME RED CARD", "HOME_TEAM_RED_CARD", None),
    ("CARTELLINO ROSSO CASA", "HOME_TEAM_RED_CARD", None),
    ("AWAY RED CARD", "AWAY_TEAM_RED_CARD", None),
    ("CARTELLINO ROSSO OSPITE", "AWAY_TEAM_RED_CARD", None),

]


def normalize_period(label: str | None) -> str | None:
    if not label:
        return None
    key = label.strip().upper()
    return PERIOD_SYNONYMS.get(key, None)


def find_market_code_from_label(label: str | None) -> Tuple[str | None, str | None]:
    """Return (market_code, implied_period) for a raw market label.

    Heuristics:
    - Token-aware O/U detection to handle numeric inserts (e.g., "Over/Under 2.5 Goals").
    - Italian + English keywords supported.
    - Fallback to substring synonym list.
    """
    if not label:
        return None, None

    up = label.strip().upper()

    # quick implied period
    implied_period = None
    if any(
        p in up
        for p in [
            "FULL TIME",
            "FULLTIME",
            "FT",
            "MATCH",
            "PARTITA INTERA",
            "TEMPO REGOLAMENTARE",
            "TEMPO PIENO",
        ]
    ):
        implied_period = "FULL_MATCH"
    if any(p in up for p in ["FIRST HALF", "1ST HALF", "PRIMO TEMPO", "1 TEMPO", "1T"]):
        implied_period = implied_period or "FIRST_HALF"
    if any(
        p in up for p in ["SECOND HALF", "2ND HALF", "SECONDO TEMPO", "2 TEMPO", "2T"]
    ):
        implied_period = implied_period or "SECOND_HALF"

    # Normalize by removing decimals to make patterns robust
    up_simplified = re.sub(r"[0-9]+[\.,]?[0-9]*", " ", up)

    def has_ou() -> bool:
        return ("OVER/UNDER" in up_simplified) or ("UNDER/OVER" in up_simplified) or ("O/U" in up_simplified)

    def any_in(s: str, candidates: List[str]) -> bool:
        return any(c in s for c in candidates)

    def has_team_indicator(*, home: bool) -> bool:
        tokens = (
            ["HOME", "TEAM A", "CASA", "SQUADRA CASA"]
            if home
            else ["AWAY", "TEAM B", "OSPITE", "TRASFERTA", "SQUADRA OSPITE"]
        )
        return any_in(up, tokens)

    def has_threshold_language() -> bool:
        return any_in(
            up,
            [
                " OVER",
                "UNDER",
                " PIU",
                " PIU'",
                " PIÙ",
                " MENO",
                " OR MORE",
                " OR LESS",
                " +",
                " -",
            ],
        )

    def has_even_odd_tokens() -> bool:
        return any_in(up_simplified, ["PARI", "DISPARI", "ODD", "EVEN"])

    goals_keywords = ["GOALS", "GOAL", "GOL", "GOLS"]

    # Goals O/U (total and team)
    if has_ou() and any_in(up_simplified, goals_keywords):
        if has_team_indicator(home=True) and not has_team_indicator(home=False):
            return "HOME_TEAM_TOTAL_GOALS_OVER_UNDER", implied_period
        if has_team_indicator(home=False) and not has_team_indicator(home=True):
            return "AWAY_TEAM_TOTAL_GOALS_OVER_UNDER", implied_period
        return "TOTAL_GOALS_OVER_UNDER", implied_period

    corners_keywords = ["CORNERS", "CORNER", "CALCI D'ANGOLO", "ANGOLI"]

    # Corners O/U (total + team)
    if has_ou() and any_in(up_simplified, corners_keywords):
        if has_team_indicator(home=True) and not has_team_indicator(home=False):
            return "HOME_TEAM_TOTAL_CORNERS_OVER_UNDER", implied_period
        if has_team_indicator(home=False) and not has_team_indicator(home=True):
            return "AWAY_TEAM_TOTAL_CORNERS_OVER_UNDER", implied_period
        return "TOTAL_CORNERS_OVER_UNDER", implied_period

    # Team-specific corners (detect even without explicit "over/under")
    if any_in(up_simplified, corners_keywords) and has_threshold_language():
        if has_team_indicator(home=True) and not has_team_indicator(home=False):
            return "HOME_TEAM_TOTAL_CORNERS_OVER_UNDER", implied_period
        if has_team_indicator(home=False) and not has_team_indicator(home=True):
            return "AWAY_TEAM_TOTAL_CORNERS_OVER_UNDER", implied_period

    # If label explicitly mentions corners with team indicators plus "over"/"under" wording
    if any_in(up_simplified, corners_keywords) and has_threshold_language():
        if has_team_indicator(home=True):
            return "HOME_TEAM_TOTAL_CORNERS_OVER_UNDER", implied_period
        if has_team_indicator(home=False):
            return "AWAY_TEAM_TOTAL_CORNERS_OVER_UNDER", implied_period
        return "TOTAL_CORNERS_OVER_UNDER", implied_period

    # Cards O/U
    if has_ou() and any_in(up_simplified, ["CARDS", "CARD", "CARTELLINI", "AMMONIZIONI", "BOOKINGS"]):
        return "TOTAL_CARDS_OVER_UNDER", implied_period

    # Shots on target O/U
    if has_ou() and any_in(up_simplified, ["SHOTS ON TARGET", "SOT", "TIRI IN PORTA"]):
        return "TOTAL_SHOTS_ON_TARGET_OVER_UNDER", implied_period

    # Shots O/U (generic)
    if has_ou() and any_in(up_simplified, ["SHOTS", "TIRI"]):
        return "TOTAL_SHOTS_OVER_UNDER", implied_period

    # --- Team-specific CARDS O/U (detect even without explicit 'O/U' if threshold language appears)
    cards_keywords = ["CARDS", "CARD", "CARTELLINI", "AMMONIZIONI", "BOOKINGS"]
    if any_in(up_simplified, cards_keywords) and has_threshold_language():
        if has_team_indicator(home=True) and not has_team_indicator(home=False):
            return "HOME_TEAM_TOTAL_CARDS_OVER_UNDER", implied_period
        if has_team_indicator(home=False) and not has_team_indicator(home=True):
            return "AWAY_TEAM_TOTAL_CARDS_OVER_UNDER", implied_period

    # Team-specific GOALS O/U
    if has_even_odd_tokens():
        if any_in(up_simplified, corners_keywords):
            return "TOTAL_CORNERS_EVEN_ODD", implied_period
        if any_in(up_simplified, goals_keywords):
            if has_team_indicator(home=True) and not has_team_indicator(home=False):
                return "HOME_TEAM_GOALS_EVEN_ODD", implied_period
            if has_team_indicator(home=False) and not has_team_indicator(home=True):
                return "AWAY_TEAM_GOALS_EVEN_ODD", implied_period
            return "TOTAL_GOALS_EVEN_ODD", implied_period

    # Team-specific SHOTS ON TARGET O/U
    if has_ou() and any_in(up_simplified, ["SHOTS ON TARGET", "SOT", "TIRI IN PORTA"]):
        if has_team_indicator(home=True) and not has_team_indicator(home=False):
            return "HOME_TEAM_TOTAL_SHOTS_ON_TARGET_OVER_UNDER", implied_period
        if has_team_indicator(home=False) and not has_team_indicator(home=True):
            return "AWAY_TEAM_TOTAL_SHOTS_ON_TARGET_OVER_UNDER", implied_period

    # Team-specific SHOTS O/U
    if has_ou() and any_in(up_simplified, ["SHOTS", "TIRI"]):
        if has_team_indicator(home=True) and not has_team_indicator(home=False):
            return "HOME_TEAM_TOTAL_SHOTS_OVER_UNDER", implied_period
        if has_team_indicator(home=False) and not has_team_indicator(home=True):
            return "AWAY_TEAM_TOTAL_SHOTS_OVER_UNDER", implied_period

    # OFFSIDES O/U (total + team)
    offsides_keywords = ["OFFSIDES", "FUORIGIOCO"]
    if has_ou() and any_in(up_simplified, offsides_keywords):
        if has_team_indicator(home=True) and not has_team_indicator(home=False):
            return "HOME_TEAM_TOTAL_OFFSIDES_OVER_UNDER", implied_period
        if has_team_indicator(home=False) and not has_team_indicator(home=True):
            return "AWAY_TEAM_TOTAL_OFFSIDES_OVER_UNDER", implied_period
        return "TOTAL_OFFSIDES_OVER_UNDER", implied_period

    # FOULS O/U (total + team)
    fouls_keywords = ["FOULS", "FALLI"]
    if has_ou() and any_in(up_simplified, fouls_keywords):
        if has_team_indicator(home=True) and not has_team_indicator(home=False):
            return "HOME_TEAM_TOTAL_FOULS_OVER_UNDER", implied_period
        if has_team_indicator(home=False) and not has_team_indicator(home=True):
            return "AWAY_TEAM_TOTAL_FOULS_OVER_UNDER", implied_period
        return "TOTAL_FOULS_OVER_UNDER", implied_period

    # Team Yes/No props (no O/U)
    if any_in(up_simplified, ["HOME TEAM TO SCORE", "TEAM A TO SCORE", "SEGNA CASA"]):
        return "HOME_TEAM_TO_SCORE", implied_period
    if any_in(up_simplified, ["AWAY TEAM TO SCORE", "TEAM B TO SCORE", "SEGNA OSPITE"]):
        return "AWAY_TEAM_TO_SCORE", implied_period
    if any_in(up_simplified, ["HOME CLEAN SHEET", "PORTA INVIOLATA CASA"]):
        return "HOME_TEAM_CLEAN_SHEET", implied_period
    if any_in(up_simplified, ["AWAY CLEAN SHEET", "PORTA INVIOLATA OSPITE"]):
        return "AWAY_TEAM_CLEAN_SHEET", implied_period
    if any_in(up_simplified, ["HOME RED CARD", "CARTELLINO ROSSO CASA"]):
        return "HOME_TEAM_RED_CARD", implied_period
    if any_in(up_simplified, ["AWAY RED CARD", "CARTELLINO ROSSO OSPITE"]):
        return "AWAY_TEAM_RED_CARD", implied_period

    # Yes/No popular markets (without explicit O/U)
    if any_in(up_simplified, ["CARTELLINO ROSSO", "ESPULSIONE", "RED CARD"]):
        return "RED_CARD_AWARDED", implied_period
    if any_in(up_simplified, ["CALCIO DI RIGORE", "RIGORE", "PENALTY IN MATCH", "PENALTY AWARDED"]):
        return "PENALTY_AWARDED", implied_period
    if any_in(up_simplified, ["BTTS", "BOTH TEAMS TO SCORE", "ENTRAMBE LE SQUADRE SEGNANO", "GOAL/NOGOAL", "GOL/NOGOL"]):
        return "BOTH_TEAMS_TO_SCORE", implied_period

    # Team two-way
    if any_in(up_simplified, ["DOUBLE CHANCE", "DOPPIA CHANCE"]):
        return "DOUBLE_CHANCE", implied_period
    if any_in(up_simplified, ["DRAW NO BET", "DNB", "PAREGGIO NESSUNA SCOMMESSA", "PAREGGIO RIMBORSO"]):
        return "DRAW_NO_BET", implied_period
    if any_in(up_simplified, ["ASIAN HANDICAP", "HANDICAP ASIATICO", "HANDICAP"]):
        return "ASIAN_HANDICAP", implied_period

    # Tennis
    if any_in(up_simplified, ["MATCH WINNER", "TO WIN MATCH", "MONEYLINE", "VINCENTE INCONTRO", "VINCENTE PARTITA"]):
        return "MATCH_WINNER", implied_period
    if has_ou() and any_in(up_simplified, ["TOTAL GAMES", "GAMES", "GIOCHI"]):
        return "TOTAL_GAMES_OVER_UNDER", implied_period

    # Fallback to synonym substrings
    for needle, code, syn_period in MARKET_SYNONYMS:
        if needle in up:
            return code, syn_period or implied_period

    return None, implied_period
