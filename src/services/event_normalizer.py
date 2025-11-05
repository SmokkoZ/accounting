"""
Event normalization utilities.

Provides deterministic normalization of event names extracted from OCR across
bookmakers, languages, and formatting styles so we can reliably create/match
canonical events.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional, Dict
from pathlib import Path
import json


class EventNormalizer:
    """Normalize raw event names to a canonical string and slug."""

    _alias_cache: Optional[Dict[str, str]] = None

    @staticmethod
    def _project_root() -> Path:
        return Path(__file__).resolve().parents[2]

    @classmethod
    def load_aliases(cls) -> Dict[str, str]:
        """Load team aliases from data/team_aliases.json (lowercase keys).

        File format:
            {
              "san paolo": "sao paulo",
              "são paulo": "sao paulo"
            }
        """
        if cls._alias_cache is not None:
            return cls._alias_cache

        aliases_path = cls._project_root() / "data" / "team_aliases.json"
        mapping: Dict[str, str] = {}
        try:
            if aliases_path.exists():
                raw = json.loads(aliases_path.read_text(encoding="utf-8"))
                # Normalize keys/values to lowercase without diacritics for matching
                normalized: Dict[str, str] = {}
                for k, v in raw.items():
                    key = cls._strip_diacritics(str(k)).lower().strip()
                    val = cls._strip_diacritics(str(v)).lower().strip()
                    if key and val:
                        normalized[key] = val
                mapping = normalized
        except Exception:
            # Fall back to empty mapping if file invalid
            mapping = {}

        # Built-in minimal aliases (merged; file overrides take precedence)
        builtin = {
            "san paolo": "sao paulo",
            "são paulo": "sao paulo",
            "sao-paulo": "sao paulo",
            "sao_paulo": "sao paulo",
        }
        for k, v in builtin.items():
            mapping.setdefault(k, v)

        cls._alias_cache = mapping
        return cls._alias_cache

    @staticmethod
    def _strip_diacritics(text: str) -> str:
        return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")

    @staticmethod
    def normalize_event_name(raw: Optional[str], sport: Optional[str] = None) -> Optional[str]:
        """
        Normalize an event name to a stable, human-readable form.

        Rules applied:
        - Trim whitespace, collapse multiple spaces
        - Lowercase, then Title-Case for teams/words
        - Normalize separators to "vs" (supports: v, vs., -, —, –, :, @)
        - Remove stray punctuation around team names
        - Keep diacritics (no dependency); safe ASCII only can be added later

        Args:
            raw: Raw event string (e.g., "ATALANTA - LAZIO")
            sport: Optional sport context (unused today, reserved for sport-specific tweaks)

        Returns:
            Normalized string like "Atalanta vs Lazio", or None if input is falsy.
        """
        if not raw or not raw.strip():
            return None

        s = raw.strip()

        # Strip diacritics to stabilize across locales (e.g., São → Sao)
        s = EventNormalizer._strip_diacritics(s)

        # Normalize explicit "v"/"vs" separators first
        s = re.sub(r"\s+v\.?\s+", " vs ", s, flags=re.IGNORECASE)
        s = re.sub(r"\s+vs\.?\s+", " vs ", s, flags=re.IGNORECASE)

        # Convert alternate delimiters only if we still haven't found a "vs"
        if " vs " not in s.lower():
            s = re.sub(r"\s*[/@:]\s*", " vs ", s)

        # Treat dashes as separators only when we still lack a vs token
        if " vs " not in s.lower():
            s = re.sub(r"\s*[-\u2010-\u2015]\s*", " vs ", s)

        # Collapse whitespace
        s = re.sub(r"\s+", " ", s).strip()

        # Remove leading/trailing punctuation on tokens
        parts = [re.sub(r"^[^\w]+|[^\w]+$", "", p) for p in s.split(" ")]
        s = " ".join([p for p in parts if p])

        # Replace multi-word aliases first on the whole string (lowercased), then rebuild
        aliases = EventNormalizer.load_aliases()
        text = s.lower()

        # Apply alias replacements once using whitespace-delimited matching.
        # Handles multi-token aliases and avoids re-expanding teams that already
        # include the alias suffix (e.g., "Bayern Munich").
        for pat in sorted(aliases.keys(), key=len, reverse=True):
            repl = aliases[pat]
            pattern = r"(?<!\S)" + re.escape(pat) + r"(?!\S)"

            def _alias_replace(match: re.Match[str], *, pattern_pat=pat, replacement=repl) -> str:
                # If the replacement simply appends extra words to the alias and the
                # existing text already contains those words immediately after the match,
                # skip substitution to keep the string idempotent.
                if replacement.startswith(pattern_pat):
                    suffix = replacement[len(pattern_pat) :].strip()
                    if suffix:
                        tail = match.string[match.end() :]
                        if tail.startswith(" " + suffix):
                            return match.group(0)
                return replacement

            text = re.sub(pattern, _alias_replace, text)

        tokens = [tok for tok in text.split(" ") if tok]
        normalized_tokens = []
        for tok in tokens:
            lower_tok = tok.lower()
            if normalized_tokens and lower_tok == normalized_tokens[-1].lower():
                continue
            if lower_tok == "vs":
                normalized_tokens.append("vs")
            else:
                normalized_tokens.append(tok.title())

        s = " ".join(normalized_tokens)

        # Ensure single canonical separator
        s = re.sub(r"\s+vs\s+", " vs ", s, flags=re.IGNORECASE)

        return s

    @staticmethod
    def split_teams(normalized_event_name: Optional[str]) -> Optional[tuple[str, str]]:
        """Split a normalized event name into two team strings using 'vs'.

        Expects input already normalized with ' vs ' as the separator.
        """
        if not normalized_event_name:
            return None
        s = normalized_event_name.strip()
        # Ensure separator is normalized
        parts = [p.strip() for p in re.split(r"\s+vs\s+", s, flags=re.IGNORECASE)]
        if len(parts) != 2:
            return None
        return parts[0], parts[1]

    @staticmethod
    def team_slug(name: str) -> str:
        """Create a stable slug for a team name (lowercase, alnum+dashes)."""
        base = name.lower().strip()
        base = re.sub(r"[^a-z0-9]+", "-", base)
        base = re.sub(r"-+", "-", base).strip("-")
        return base

    @staticmethod
    def compute_pair_key(normalized_event_name: Optional[str]) -> Optional[tuple[str, str, str]]:
        """Compute (team1_slug, team2_slug, pair_key) from normalized event name.

        pair_key is lexicographically sorted 'teamA_slug|teamB_slug'.
        """
        teams = EventNormalizer.split_teams(normalized_event_name)
        if not teams:
            return None
        t1, t2 = teams
        s1 = EventNormalizer.team_slug(t1)
        s2 = EventNormalizer.team_slug(t2)
        a, b = sorted([s1, s2])
        pair_key = f"{a}|{b}"
        return s1, s2, pair_key

    @staticmethod
    def event_slug(normalized: Optional[str]) -> Optional[str]:
        """
        Build a slug from a normalized event name.
        """
        if not normalized:
            return None
        s = normalized.lower().strip()
        s = re.sub(r"\s+vs\s+", "-vs-", s)
        s = re.sub(r"[^a-z0-9]+", "-", s)
        s = re.sub(r"-+", "-", s).strip("-")
        return s
