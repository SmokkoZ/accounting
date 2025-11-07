"""
Market normalization service.

Takes raw OCR/LLM extraction (market_label, market_code guess, sport, period text,
side, line) and maps them to the project’s normalized market taxonomy.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, Optional, Tuple

import structlog

from src.domain.market_taxonomy import (
    CANONICAL_MARKETS,
    find_market_code_from_label,
    normalize_period,
)
from src.services.event_normalizer import EventNormalizer

logger = structlog.get_logger()


class MarketNormalizer:
    def __init__(self, db: sqlite3.Connection):
        self.db = db
        self.db.row_factory = sqlite3.Row

    def normalize(
        self,
        *,
        sport: Optional[str],
        market_label: Optional[str],
        market_code_guess: Optional[str],
        period_scope_text: Optional[str],
        side_text: Optional[str],
        line_value: Optional[str],
        event_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return normalized fields: market_code, canonical_market_id, period_scope, side, normalization_confidence.

        Strategy:
        1) Prefer explicit market_label mapping using synonyms.
        2) Fall back to a constrained mapping of model-provided market_code guess.
        3) Normalize period_scope and side casing.
        4) Ensure canonical_market_id exists (insert if missing, with description).
        """

        # Normalize inputs
        sport_norm = (sport or "").strip().lower()
        side_norm = self._normalize_side(side_text)
        period_norm = normalize_period(period_scope_text)

        # Extract team context from event when available
        normalized_event = (
            EventNormalizer.normalize_event_name(event_name, sport)
            if event_name
            else None
        )
        home_team: Optional[str] = None
        away_team: Optional[str] = None
        if normalized_event:
            teams = EventNormalizer.split_teams(normalized_event)
            if teams:
                home_team, away_team = teams

        # 1) Try mapping by raw market label (include team context if known)
        code, implied_period = find_market_code_from_label(
            market_label,
            home_team=home_team,
            away_team=away_team,
        )
        confidence = 0.9 if code else 0.0

        # 2) Fall back to guess if allowed and within our taxonomy
        if not code and market_code_guess:
            guess_up = market_code_guess.strip().upper()
            if guess_up in CANONICAL_MARKETS:
                code = guess_up
                confidence = max(confidence, 0.7)

        # Apply implied period if not already normalized
        if not period_norm and implied_period:
            period_norm = implied_period

        # Two-way focus: For soccer/tennis; if sport is other, keep confidence low
        if sport_norm and sport_norm not in ("football", "soccer", "tennis"):
            confidence = min(confidence, 0.5)

        # Final fallback: no mapping
        if not code:
            logger.info(
                "market_normalization_failed",
                sport=sport_norm,
                market_label=market_label,
                market_code_guess=market_code_guess,
            )
            return {
                "market_code": None,
                "canonical_market_id": None,
                "period_scope": period_norm,
                "side": side_norm,
                "normalization_confidence": str(round(confidence, 2)),
            }

        # Ensure canonical market exists and retrieve id
        market_id = self._ensure_canonical_market(code)

        return {
            "market_code": code,
            "canonical_market_id": market_id,
            "period_scope": period_norm,
            "side": side_norm,
            "normalization_confidence": str(round(confidence, 2)),
        }

    def _ensure_canonical_market(self, market_code: str) -> int:
        # Try find existing
        cur = self.db.execute(
            "SELECT id FROM canonical_markets WHERE market_code = ?",
            (market_code,),
        )
        row = cur.fetchone()
        if row:
            return int(row["id"])  # type: ignore[index]

        # Insert new (description from taxonomy, fallback to title)
        description = CANONICAL_MARKETS.get(
            market_code, market_code.replace("_", " ").title()
        )
        cur = self.db.execute(
            """
            INSERT INTO canonical_markets (market_code, description, created_at_utc)
            VALUES (?, ?, datetime('now') || 'Z')
            """,
            (market_code, description),
        )
        self.db.commit()
        return int(cur.lastrowid)

    @staticmethod
    def _normalize_side(side_text: Optional[str]) -> Optional[str]:
        if not side_text:
            return None
        s = side_text.strip().upper()
        mapping = {
            "O": "OVER",
            "U": "UNDER",
            "OVER": "OVER",
            "UNDER": "UNDER",
            "YES": "YES",
            "SI": "YES",
            "SÌ": "YES",
            "NO": "NO",
            "TEAM A": "TEAM_A",
            "TEAM B": "TEAM_B",
            "HOME": "TEAM_A",
            "AWAY": "TEAM_B",
            "CASA": "TEAM_A",
            "OSPITE": "TEAM_B",
            "TRASFERTA": "TEAM_B",
            "PIU": "OVER",
            "PIÙ": "OVER",
            "MENO": "UNDER",
            "PLAYER A": "TEAM_A",
            "PLAYER B": "TEAM_B",
            "PARI": "EVEN",
            "DISPARI": "ODD",
            "EVEN": "EVEN",
            "ODD": "ODD",
        }
        return mapping.get(s, s)
