"""
Normalized market taxonomy and synonyms for soccer and tennis two-way markets.

This module defines the canonical market codes supported by the MVP and a
synonym map used by the market normalizer to map bookmaker-specific labels
to normalized codes and period scopes.
"""

from __future__ import annotations

from typing import Dict, List, Tuple
import re
import unicodedata


# Base canonical markets used for seeding (multi-sport + general two-way soccer)
BASE_CANONICAL_MARKETS: Dict[str, str] = {
    # Core football/soccer markets
    "MATCH_WINNER": "Match Winner / 1X2 / Moneyline",
    "DRAW_NO_BET": "Draw No Bet",
    "DOUBLE_CHANCE": "Double Chance (1X, X2, 12)",
    "TOTAL_GOALS_OVER_UNDER": "Total Goals Over/Under",
    "BOTH_TEAMS_TO_SCORE": "Both Teams to Score (BTTS)",
    "TEAM_TOTAL_GOALS": "Team Total Goals Over/Under",
    "ASIAN_HANDICAP": "Asian Handicap",
    "EUROPEAN_HANDICAP": "European Handicap / 3-Way Handicap",
    "HALF_TIME_RESULT": "Half Time Result (1X2)",
    "HALF_TIME_FULL_TIME": "Half Time / Full Time",
    "SECOND_HALF_WINNER": "Second Half Winner",
    # Popular football props
    "FIRST_GOAL_SCORER": "First Goal Scorer",
    "LAST_GOAL_SCORER": "Last Goal Scorer",
    "ANYTIME_GOAL_SCORER": "Anytime Goal Scorer",
    "FIRST_HALF_GOALS_OU": "First Half Goals Over/Under",
    "SECOND_HALF_GOALS_OU": "Second Half Goals Over/Under",
    "CORRECT_SCORE": "Correct Score",
    "WINNING_MARGIN": "Winning Margin",
    "TOTAL_CORNERS": "Total Corners Over/Under",
    "TOTAL_CARDS": "Total Cards Over/Under",
    "CLEAN_SHEET": "To Keep a Clean Sheet",
    "TO_WIN_TO_NIL": "To Win to Nil",
    # Niche football bets
    "CORNER_HANDICAP": "Corner Handicap",
    "FIRST_CORNER": "First Corner",
    "CORNER_MATCH_BET": "Corner Match Bet",
    "TOTAL_BOOKINGS": "Total Booking Points",
    "PLAYER_TO_BE_BOOKED": "Player to be Booked",
    "SENDING_OFF": "Sending Off / Red Card",
    "ODD_EVEN_GOALS": "Odd/Even Total Goals",
    "GOALS_IN_BOTH_HALVES": "Goals Scored in Both Halves",
    "TEAM_TO_SCORE_FIRST": "Team to Score First",
    "TEAM_TO_SCORE_LAST": "Team to Score Last",
    # Other sports (still two-way focus)
    "TENNIS_MATCH_WINNER": "Tennis - Match Winner",
    "TENNIS_SET_BETTING": "Tennis - Correct Score in Sets",
    "TENNIS_TOTAL_GAMES": "Tennis - Total Games Over/Under",
    "BASKETBALL_MONEYLINE": "Basketball - Moneyline",
    "BASKETBALL_HANDICAP": "Basketball - Point Spread",
    "BASKETBALL_TOTAL_POINTS": "Basketball - Total Points Over/Under",
    "NFL_MONEYLINE": "NFL - Moneyline",
    "NFL_SPREAD": "NFL - Point Spread",
    "NFL_TOTAL_POINTS": "NFL - Total Points Over/Under",
    "BASEBALL_MONEYLINE": "Baseball - Moneyline",
    "BASEBALL_RUN_LINE": "Baseball - Run Line",
    "HOCKEY_MONEYLINE": "Hockey - Moneyline",
    "HOCKEY_PUCK_LINE": "Hockey - Puck Line",
    # Catch-all
    "OTHER": "Other / Unclassified Market",
    "CUSTOM": "Custom Market",
}


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


def get_all_canonical_market_definitions() -> Dict[str, str]:
    """Return primary market definitions merged with two-way taxonomy entries."""
    definitions: Dict[str, str] = dict(BASE_CANONICAL_MARKETS)
    definitions.update(CANONICAL_MARKETS)
    return definitions


# Period normalization
def _strip_accents(text: str) -> str:
    """Return ASCII-only uppercase string without diacritics."""
    normalized = unicodedata.normalize("NFKD", text)
    return normalized.encode("ascii", "ignore").decode("ascii")


def _team_tokens(team: str | None) -> List[str]:
    """Build searchable tokens for a team name."""
    if not team:
        return []
    cleaned = _strip_accents(team).upper()
    cleaned = re.sub(r"[^A-Z0-9 ]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return []
    tokens: List[str] = [cleaned]
    compact = cleaned.replace(" ", "")
    if len(compact) >= 3:
        tokens.append(compact)
    for part in cleaned.split(" "):
        if len(part) >= 3:
            tokens.append(part)
    deduped: List[str] = []
    for tok in tokens:
        if tok not in deduped:
            deduped.append(tok)
    return deduped


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
    # Romanian
    "MECI": "FULL_MATCH",
    "MECI INTREG": "FULL_MATCH",
    "MECI ÎNTREG": "FULL_MATCH",
    "PRIMA REPRIZA": "FIRST_HALF",
    "REPRIZA 1": "FIRST_HALF",
    "1 REPRIZA": "FIRST_HALF",
    "REPRIZA I": "FIRST_HALF",
    "A DOUA REPRIZA": "SECOND_HALF",
    "REPRIZA 2": "SECOND_HALF",
    "2 REPRIZA": "SECOND_HALF",
    "REPRIZA II": "SECOND_HALF",
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
    ("NUMERO DEI CARTELLINI NELL'INCONTRO", "TOTAL_CARDS_OVER_UNDER", None),
    ("U/O CARTELLINI INCONTRO", "TOTAL_CARDS_OVER_UNDER", None),
    # Corners
    ("TOTAL CORNERS", "TOTAL_CORNERS_OVER_UNDER", None),
    ("CORNERS OVER/UNDER", "TOTAL_CORNERS_OVER_UNDER", None),
    ("OVER/UNDER CORNERS", "TOTAL_CORNERS_OVER_UNDER", None),
    ("UNDER/OVER CORNERS", "TOTAL_CORNERS_OVER_UNDER", None),
    ("CALCI D'ANGOLO", "TOTAL_CORNERS_OVER_UNDER", None),
    ("CALCI D'ANGOLO - 2 SCELTE", "TOTAL_CORNERS_OVER_UNDER", None),
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
    ("CALCI D'ANGOLO DELLA SQUADRA", "HOME_TEAM_TOTAL_CORNERS_OVER_UNDER", None),
    ("U/O ANGOLI SQUADRA", "HOME_TEAM_TOTAL_CORNERS_OVER_UNDER", None),
    ("U/O ANGOLI TEAM 1", "HOME_TEAM_TOTAL_CORNERS_OVER_UNDER", None),
    ("U/O ANGOLI TEAM 2", "AWAY_TEAM_TOTAL_CORNERS_OVER_UNDER", None),
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
    ("GOAL", "BOTH_TEAMS_TO_SCORE", None),
    ("NO GOAL", "BOTH_TEAMS_TO_SCORE", None),
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
    ("RIMBORSO IN CASO DI PARITA'", "DRAW_NO_BET", None),
    ("RIMBORSO IN CASO DI PARITA", "DRAW_NO_BET", None),
    ("RIMBORSO IN CASO DI PARITÀ", "DRAW_NO_BET", None),
    ("RIMBORSO IN CASO DI PARIT�", "DRAW_NO_BET", None),
    ("1 DNB", "DRAW_NO_BET", None),
    ("2 DNB", "DRAW_NO_BET", None),
    ("TEAM 1 DNB", "DRAW_NO_BET", None),
    ("TEAM 2 DNB", "DRAW_NO_BET", None),
    ("RIMBORSO SE PARI", "DRAW_NO_BET", None),
    ("RIMBORSO PARI", "DRAW_NO_BET", None),
    ("DOPPIA CHANCE", "DOUBLE_CHANCE", None),
    ("DOPPIA CHANCE IN", "DOUBLE_CHANCE", None),
    ("DOPPIA CHANCE OUT", "DOUBLE_CHANCE", None),
    ("DOPPIA CHANCE IN/OUT", "DOUBLE_CHANCE", None),
    ("CASA O PAREGGIO", "DOUBLE_CHANCE", None),
    ("PAREGGIO O OSPITE", "DOUBLE_CHANCE", None),
    ("CASA O OSPITE", "DOUBLE_CHANCE", None),
    ("1X", "DOUBLE_CHANCE", None),
    ("X2", "DOUBLE_CHANCE", None),
    ("12", "DOUBLE_CHANCE", None),
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
    ("TOTALE GOAL SQUADRA CASA", "HOME_TEAM_TOTAL_GOALS_OVER_UNDER", None),
    ("TOT GOAL CASA", "HOME_TEAM_TOTAL_GOALS_OVER_UNDER", None),
    ("U/O GOAL TEAM 1", "HOME_TEAM_TOTAL_GOALS_OVER_UNDER", None),
    ("AWAY TEAM GOALS", "AWAY_TEAM_TOTAL_GOALS_OVER_UNDER", None),
    ("TEAM B GOALS", "AWAY_TEAM_TOTAL_GOALS_OVER_UNDER", None),
    ("OSPITE GOL", "AWAY_TEAM_TOTAL_GOALS_OVER_UNDER", None),
    ("UNDER/OVER OSPITE", "AWAY_TEAM_TOTAL_GOALS_OVER_UNDER", None),
    ("OVER/UNDER OSPITE", "AWAY_TEAM_TOTAL_GOALS_OVER_UNDER", None),
    ("UNDER/OVER SQUADRA OSPITE", "AWAY_TEAM_TOTAL_GOALS_OVER_UNDER", None),
    ("OVER/UNDER SQUADRA OSPITE", "AWAY_TEAM_TOTAL_GOALS_OVER_UNDER", None),
    ("TOTALE GOAL SQUADRA OSPITE", "AWAY_TEAM_TOTAL_GOALS_OVER_UNDER", None),
    ("TOT GOAL OSPITE", "AWAY_TEAM_TOTAL_GOALS_OVER_UNDER", None),
    ("U/O GOAL TEAM 2", "AWAY_TEAM_TOTAL_GOALS_OVER_UNDER", None),

    # Team cards O/U (Home/Away)
    ("HOME CARDS", "HOME_TEAM_TOTAL_CARDS_OVER_UNDER", None),
    ("HOME BOOKINGS", "HOME_TEAM_TOTAL_CARDS_OVER_UNDER", None),
    ("TEAM A CARDS", "HOME_TEAM_TOTAL_CARDS_OVER_UNDER", None),
    ("CARTELLINI CASA", "HOME_TEAM_TOTAL_CARDS_OVER_UNDER", None),
    ("UNDER/OVER CARTELLINI CASA", "HOME_TEAM_TOTAL_CARDS_OVER_UNDER", None),
    ("OVER/UNDER CARTELLINI CASA", "HOME_TEAM_TOTAL_CARDS_OVER_UNDER", None),
    ("CARTELLINI DELLA SQUADRA CASA", "HOME_TEAM_TOTAL_CARDS_OVER_UNDER", None),
    ("U/O CARTELLINI SQUADRA 1", "HOME_TEAM_TOTAL_CARDS_OVER_UNDER", None),
    ("AWAY CARDS", "AWAY_TEAM_TOTAL_CARDS_OVER_UNDER", None),
    ("AWAY BOOKINGS", "AWAY_TEAM_TOTAL_CARDS_OVER_UNDER", None),
    ("TEAM B CARDS", "AWAY_TEAM_TOTAL_CARDS_OVER_UNDER", None),
    ("CARTELLINI OSPITE", "AWAY_TEAM_TOTAL_CARDS_OVER_UNDER", None),
    ("UNDER/OVER CARTELLINI OSPITE", "AWAY_TEAM_TOTAL_CARDS_OVER_UNDER", None),
    ("OVER/UNDER CARTELLINI OSPITE", "AWAY_TEAM_TOTAL_CARDS_OVER_UNDER", None),
    ("CARTELLINI DELLA SQUADRA OSPITE", "AWAY_TEAM_TOTAL_CARDS_OVER_UNDER", None),
    ("U/O CARTELLINI SQUADRA 2", "AWAY_TEAM_TOTAL_CARDS_OVER_UNDER", None),

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


def find_market_code_from_label(
    label: str | None,
    *,
    home_team: str | None = None,
    away_team: str | None = None,
) -> Tuple[str | None, str | None]:
    """Return (market_code, implied_period) for a raw market label.

    Heuristics:
    - Token-aware O/U detection to handle numeric inserts (e.g., "Over/Under 2.5 Goals").
    - Italian + English keywords supported.
    - Fallback to substring synonym list.
    """
    if not label:
        return None, None

    up = label.strip().upper()
    search_text = _strip_accents(up)
    home_tokens = _team_tokens(home_team)
    away_tokens = _team_tokens(away_team)

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
        return any(
            token in up_simplified
            for token in ["OVER/UNDER", "UNDER/OVER", "O/U", "PESTE/SUB", "SUB/PESTE"]
        )

    def any_in(s: str, candidates: List[str]) -> bool:
        return any(c in s for c in candidates)

    def has_team_indicator(*, home: bool) -> bool:
        base_tokens = (
            ["HOME", "TEAM A", "CASA", "SQUADRA CASA", "ACASA", "GAZDA", "ECHIPA GAZDA"]
            if home
            else ["AWAY", "TEAM B", "OSPITE", "TRASFERTA", "SQUADRA OSPITE", "DEPLASARE", "OASPETE", "ECHIPA OASPETE"]
        )
        dynamic_tokens = home_tokens if home else away_tokens
        tokens = base_tokens + dynamic_tokens
        return any_in(search_text, tokens)

    def has_threshold_language() -> bool:
        return any_in(
            up,
            [
                " OVER",
                "UNDER",
                " PIU",
                " PIU'",
                " PI\u00D9",
                " MENO",
                " OR MORE",
                " OR LESS",
                " +",
                " -",
                " PESTE",
                " SUB",
            ],
        )

    def has_even_odd_tokens() -> bool:
        return any_in(up_simplified, ["PARI", "DISPARI", "ODD", "EVEN"])

    goals_keywords = ["GOALS", "GOAL", "GOL", "GOLS", "GOLURI"]

    # Goals O/U (total and team)
    if has_ou() and any_in(up_simplified, goals_keywords):
        if has_team_indicator(home=True) and not has_team_indicator(home=False):
            return "HOME_TEAM_TOTAL_GOALS_OVER_UNDER", implied_period
        if has_team_indicator(home=False) and not has_team_indicator(home=True):
            return "AWAY_TEAM_TOTAL_GOALS_OVER_UNDER", implied_period
        return "TOTAL_GOALS_OVER_UNDER", implied_period

    corners_keywords = ["CORNERS", "CORNER", "CALCI D'ANGOLO", "ANGOLI", "CORNERE", "LOVITURI DE COLT"]

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
    if has_ou() and any_in(up_simplified, ["CARDS", "CARD", "CARTELLINI", "AMMONIZIONI", "BOOKINGS", "CARTONASE", "CARTONAS"]):
        return "TOTAL_CARDS_OVER_UNDER", implied_period

    # Shots on target O/U (total + team detection)
    shots_on_target_keywords = ["SHOTS ON TARGET", "SOT", "TIRI IN PORTA", "SUTURI PE POARTA"]
    if (has_ou() or has_threshold_language()) and any_in(up_simplified, shots_on_target_keywords):
        home_flag = has_team_indicator(home=True)
        away_flag = has_team_indicator(home=False)
        if home_flag and not away_flag:
            return "HOME_TEAM_TOTAL_SHOTS_ON_TARGET_OVER_UNDER", implied_period
        if away_flag and not home_flag:
            return "AWAY_TEAM_TOTAL_SHOTS_ON_TARGET_OVER_UNDER", implied_period
        return "TOTAL_SHOTS_ON_TARGET_OVER_UNDER", implied_period

    # Team-specific shots on target mention even without explicit threshold tokens (e.g., "by Nantes")
    if any_in(up_simplified, shots_on_target_keywords):
        home_flag = has_team_indicator(home=True)
        away_flag = has_team_indicator(home=False)
        if home_flag and not away_flag:
            return "HOME_TEAM_TOTAL_SHOTS_ON_TARGET_OVER_UNDER", implied_period
        if away_flag and not home_flag:
            return "AWAY_TEAM_TOTAL_SHOTS_ON_TARGET_OVER_UNDER", implied_period

    # Shots O/U (generic totals + team)
    shots_keywords = ["SHOTS", "TIRI", "SUTURI"]
    if (has_ou() or has_threshold_language()) and any_in(up_simplified, shots_keywords):
        home_flag = has_team_indicator(home=True)
        away_flag = has_team_indicator(home=False)
        if home_flag and not away_flag:
            return "HOME_TEAM_TOTAL_SHOTS_OVER_UNDER", implied_period
        if away_flag and not home_flag:
            return "AWAY_TEAM_TOTAL_SHOTS_OVER_UNDER", implied_period
        return "TOTAL_SHOTS_OVER_UNDER", implied_period

    # Team-specific shots mention even without explicit threshold text
    if any_in(up_simplified, shots_keywords):
        home_flag = has_team_indicator(home=True)
        away_flag = has_team_indicator(home=False)
        if home_flag and not away_flag:
            return "HOME_TEAM_TOTAL_SHOTS_OVER_UNDER", implied_period
        if away_flag and not home_flag:
            return "AWAY_TEAM_TOTAL_SHOTS_OVER_UNDER", implied_period

    # --- Team-specific CARDS O/U (detect even without explicit 'O/U' if threshold language appears)
    cards_keywords = ["CARDS", "CARD", "CARTELLINI", "AMMONIZIONI", "BOOKINGS", "CARTONASE", "CARTONAS"]
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

    # OFFSIDES O/U (total + team)
    offsides_keywords = ["OFFSIDES", "FUORIGIOCO", "OFFSIDE", "OFSAID", "OFSAIT"]
    if has_ou() and any_in(up_simplified, offsides_keywords):
        if has_team_indicator(home=True) and not has_team_indicator(home=False):
            return "HOME_TEAM_TOTAL_OFFSIDES_OVER_UNDER", implied_period
        if has_team_indicator(home=False) and not has_team_indicator(home=True):
            return "AWAY_TEAM_TOTAL_OFFSIDES_OVER_UNDER", implied_period
        return "TOTAL_OFFSIDES_OVER_UNDER", implied_period

    # FOULS O/U (total + team)
    fouls_keywords = ["FOULS", "FALLI", "FAULT", "FAULTURI"]
    if has_ou() and any_in(up_simplified, fouls_keywords):
        if has_team_indicator(home=True) and not has_team_indicator(home=False):
            return "HOME_TEAM_TOTAL_FOULS_OVER_UNDER", implied_period
        if has_team_indicator(home=False) and not has_team_indicator(home=True):
            return "AWAY_TEAM_TOTAL_FOULS_OVER_UNDER", implied_period
        return "TOTAL_FOULS_OVER_UNDER", implied_period

    # Team "to score" / "no goal" using explicit team name or side wording
    if any_in(search_text, [" TO SCORE", " SEGNA ", " MARCHEAZA", " INSCRIE "]):
        home_flag = has_team_indicator(home=True)
        away_flag = has_team_indicator(home=False)
        if home_flag and not away_flag:
            return "HOME_TEAM_TO_SCORE", implied_period
        if away_flag and not home_flag:
            return "AWAY_TEAM_TO_SCORE", implied_period

    if any_in(
        up_simplified,
        [" NO GOAL", " NO GOL", " DOES NOT SCORE", " DOESN'T SCORE", " DOESNT SCORE", " NU MARCHEAZA", " NU INSCRIE"],
    ):
        home_flag = has_team_indicator(home=True)
        away_flag = has_team_indicator(home=False)
        if home_flag and not away_flag:
            return "HOME_TEAM_TO_SCORE", implied_period
        if away_flag and not home_flag:
            return "AWAY_TEAM_TO_SCORE", implied_period

    # Team Yes/No props (no O/U)
    if any_in(up_simplified, ["HOME TEAM TO SCORE", "TEAM A TO SCORE", "SEGNA CASA", "ECHIPA GAZDA MARCHEAZA", "GAZDA MARCHEAZA", "ECHIPA GAZDA INSCRIE", "GAZDA INSCRIE"]):
        return "HOME_TEAM_TO_SCORE", implied_period
    if any_in(up_simplified, ["AWAY TEAM TO SCORE", "TEAM B TO SCORE", "SEGNA OSPITE", "ECHIPA OASPETE MARCHEAZA", "OASPETE MARCHEAZA", "ECHIPA OASPETE INSCRIE", "OASPETE INSCRIE"]):
        return "AWAY_TEAM_TO_SCORE", implied_period
    if any_in(up_simplified, ["HOME CLEAN SHEET", "PORTA INVIOLATA CASA", "GAZDA NU PRIMESTE GOL", "ECHIPA GAZDA NU PRIMESTE GOL"]):
        return "HOME_TEAM_CLEAN_SHEET", implied_period
    if any_in(up_simplified, ["AWAY CLEAN SHEET", "PORTA INVIOLATA OSPITE", "OASPETE NU PRIMESTE GOL", "ECHIPA OASPETE NU PRIMESTE GOL"]):
        return "AWAY_TEAM_CLEAN_SHEET", implied_period
    if any_in(up_simplified, ["HOME RED CARD", "CARTELLINO ROSSO CASA", "GAZDA CARTONAS ROSU", "ECHIPA GAZDA CARTONAS ROSU"]):
        return "HOME_TEAM_RED_CARD", implied_period
    if any_in(up_simplified, ["AWAY RED CARD", "CARTELLINO ROSSO OSPITE", "OASPETE CARTONAS ROSU", "ECHIPA OASPETE CARTONAS ROSU"]):
        return "AWAY_TEAM_RED_CARD", implied_period

    # Yes/No popular markets (without explicit O/U)
    if any_in(up_simplified, ["CARTELLINO ROSSO", "ESPULSIONE", "RED CARD", "CARTONAS ROSU", "ELIMINARE"]):
        return "RED_CARD_AWARDED", implied_period
    if any_in(up_simplified, ["CALCIO DI RIGORE", "RIGORE", "PENALTY IN MATCH", "PENALTY AWARDED", "PENALTY", "PENALTI"]):
        return "PENALTY_AWARDED", implied_period
    if any_in(up_simplified, ["BTTS", "BOTH TEAMS TO SCORE", "ENTRAMBE LE SQUADRE SEGNANO", "GOAL/NOGOAL", "GOL/NOGOL", "AMBELE MARCHEAZA", "AMBELE ECHIPE MARCHEAZA"]):
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
