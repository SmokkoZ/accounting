"""
Saved-view state helpers for persisting filters and toggles.

This module keeps Streamlit query parameters and local preference files in sync
so operators can reload pages and retain their preferred configuration.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence, Union

from src.ui.helpers import url_state

logger = logging.getLogger(__name__)

_PREF_ENV_VAR = "FINAL_APP_PREFERENCES_DIR"
_DEFAULT_PREF_DIR = Path(".streamlit") / "preferences"
_HASH_PREFIX = "saved_view::"
_EXPIRATION_DAYS = 30
_UNSET = object()
_TRUTHY_VALUES = {"1", "true", "yes", "on", "enabled", "compact"}
_FALSY_VALUES = {"0", "false", "no", "off", "disabled"}


@dataclass(frozen=True)
class SavedViewSnapshot:
    """Snapshot of saved filter/toggle state sourced from URL/local prefs."""

    bookmaker: Optional[List[str]] = None
    bet_type: Optional[str] = None
    confidence: Optional[str] = None
    compact: Optional[bool] = None
    auto: Optional[bool] = None

    def merge(self, fallback: "SavedViewSnapshot") -> "SavedViewSnapshot":
        """Return a new snapshot preferring current values over fallback."""

        def choose(primary: Optional[Any], secondary: Optional[Any]) -> Optional[Any]:
            return secondary if primary is None else primary

        primary_bookmakers = self.bookmaker
        if primary_bookmakers is not None:
            primary_bookmakers = list(primary_bookmakers)
        fallback_bookmakers = fallback.bookmaker
        if fallback_bookmakers is not None:
            fallback_bookmakers = list(fallback_bookmakers)

        return SavedViewSnapshot(
            bookmaker=primary_bookmakers if primary_bookmakers is not None else fallback_bookmakers,
            bet_type=choose(self.bet_type, fallback.bet_type),
            confidence=choose(self.confidence, fallback.confidence),
            compact=choose(self.compact, fallback.compact),
            auto=choose(self.auto, fallback.auto),
        )


class SavedViewManager:
    """
    Persist and hydrate saved-view state for a given Streamlit page slug.
    """

    def __init__(self, slug: str, *, expiration_days: int = _EXPIRATION_DAYS) -> None:
        self.slug = slug
        self._expiration = expiration_days
        self._path = _resolve_pref_path(slug)
        self._hash_salt = f"{_HASH_PREFIX}{slug}"
        self._file_state = self._load_file_state()
        self._query_snapshot = self._load_query_snapshot()

    def get_snapshot(self, *, bookmaker_options: Optional[Sequence[str]] = None) -> SavedViewSnapshot:
        """
        Return the merged saved state, prioritising query params over file cache.

        Args:
            bookmaker_options: Optional iterable of bookmaker labels used to
                decode hashed local preferences.
        """
        file_snapshot = self._snapshot_from_file(bookmaker_options)
        return self._query_snapshot.merge(file_snapshot)

    def save(
        self,
        *,
        bookmakers: Union[Sequence[str], None, object] = _UNSET,
        bet_type: Union[str, None, object] = _UNSET,
        confidence: Union[str, None, object] = _UNSET,
        compact: Union[bool, None, object] = _UNSET,
        auto: Union[bool, None, object] = _UNSET,
    ) -> None:
        """
        Update persisted preferences with the provided values.

        Pass ``None`` to clear a value or omit the argument to keep the current
        stored value unchanged.
        """
        updates: Dict[str, Optional[Any]] = {}

        if bookmakers is not _UNSET:
            list_value = bookmakers if isinstance(bookmakers, Sequence) or bookmakers is None else None
            updates["bookmaker"] = self._encode_sensitive_list(list_value)
        if bet_type is not _UNSET:
            updates["bet_type"] = bet_type
        if confidence is not _UNSET:
            updates["confidence"] = confidence
        if compact is not _UNSET:
            updates["compact"] = compact
        if auto is not _UNSET:
            updates["auto"] = auto

        if not updates:
            return

        changed = self._apply_file_updates(updates)
        if changed:
            self._write_file()

    def _snapshot_from_file(
        self,
        bookmaker_options: Optional[Sequence[str]],
    ) -> SavedViewSnapshot:
        if not self._file_state:
            return SavedViewSnapshot()

        decoded_bookmakers: Optional[List[str]] = None
        if bookmaker_options:
            decoded_bookmakers = self._decode_sensitive_list(self._file_state.get("bookmaker"), bookmaker_options)

        return SavedViewSnapshot(
            bookmaker=decoded_bookmakers,
            bet_type=self._file_state.get("bet_type"),
            confidence=self._file_state.get("confidence"),
            compact=self._file_state.get("compact"),
            auto=self._file_state.get("auto"),
        )

    def _apply_file_updates(self, updates: Mapping[str, Optional[Any]]) -> bool:
        changed = False
        for key, value in updates.items():
            if value is None:
                if key in self._file_state:
                    self._file_state.pop(key, None)
                    changed = True
                continue

            existing = self._file_state.get(key)
            if isinstance(existing, list) and isinstance(value, list) and existing == value:
                continue
            if existing == value:
                continue
            self._file_state[key] = value
            changed = True

        return changed

    def _encode_sensitive_list(self, values: Union[Sequence[str], None]) -> Optional[List[str]]:
        if not values:
            return None
        encoded: List[str] = []
        seen = set()
        for value in values:
            if not value:
                continue
            token = self._hash_label(str(value))
            if token in seen:
                continue
            encoded.append(token)
            seen.add(token)
        return encoded or None

    def _decode_sensitive_list(
        self,
        hashed_values: Optional[Sequence[str]],
        options: Sequence[str],
    ) -> Optional[List[str]]:
        if not hashed_values:
            return None
        lookup = {self._hash_label(option): option for option in options if option}
        decoded: List[str] = []
        for token in hashed_values:
            resolved = lookup.get(token)
            if resolved and resolved not in decoded:
                decoded.append(resolved)
        return decoded or None

    def _hash_label(self, label: str) -> str:
        data = f"{self._hash_salt}:{label}".encode("utf-8")
        return hashlib.sha1(data).hexdigest()

    def _load_file_state(self) -> Dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("saved_view_preferences_corrupt", slug=self.slug, error=str(exc))
            return {}

        timestamp = payload.get("updated_at")
        if isinstance(timestamp, str) and self._is_expired(timestamp):
            try:
                self._path.unlink(missing_ok=True)
            except OSError:
                pass
            return {}

        state = payload.get("state")
        if not isinstance(state, MutableMapping):
            return {}
        # copy to plain dict for mutation
        return dict(state)

    def _write_file(self) -> None:
        data = {
            "updated_at": datetime.now(tz=UTC).isoformat(),
            "state": self._file_state,
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("saved_view_preferences_write_failed", slug=self.slug, error=str(exc))

    def _is_expired(self, timestamp: str) -> bool:
        try:
            updated_at = datetime.fromisoformat(timestamp)
        except ValueError:
            return True

        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)

        return datetime.now(tz=UTC) - updated_at > timedelta(days=self._expiration)

    def _load_query_snapshot(self) -> SavedViewSnapshot:
        params = url_state.read_query_params()
        bookmaker_values = _coerce_str_list(params.get("bookmaker"))
        bet_type = _coerce_single_value(params.get("bet"))
        confidence = _coerce_single_value(params.get("confidence"))
        compact = _parse_bool(params.get("compact"))
        auto = _parse_bool(params.get("auto"))

        return SavedViewSnapshot(
            bookmaker=bookmaker_values,
            bet_type=bet_type,
            confidence=confidence,
            compact=compact,
            auto=auto,
        )


def _resolve_pref_path(slug: str) -> Path:
    override = os.environ.get(_PREF_ENV_VAR)
    directory = Path(override) if override else _DEFAULT_PREF_DIR
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    token = hashlib.sha1(f"{_HASH_PREFIX}{slug}".encode("utf-8")).hexdigest()
    return directory / f"{token}.json"


def _coerce_str_list(value: Any) -> Optional[List[str]]:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = url_state.normalize_query_value(value)
        return [normalized] if normalized else None
    if isinstance(value, Sequence):
        items: List[str] = []
        for entry in value:
            normalized = url_state.normalize_query_value(entry)
            if normalized:
                items.append(normalized)
        return items or None
    normalized_value = url_state.normalize_query_value(value)
    return [normalized_value] if normalized_value else None


def _coerce_single_value(value: Any) -> Optional[str]:
    normalized = url_state.normalize_query_value(value)
    return normalized if normalized else None


def _parse_bool(value: Any) -> Optional[bool]:
    normalized = url_state.normalize_query_value(value)
    if normalized is None:
        return None
    lowered = normalized.lower()
    if lowered in _TRUTHY_VALUES:
        return True
    if lowered in _FALSY_VALUES:
        return False
    return None


__all__ = ["SavedViewManager", "SavedViewSnapshot"]
