"""
Persistence helpers for Telegram rate limit thresholds.

The UI and CoverageProofService share this module so operators can tune
coverage proof throughput without editing code.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional

from src.core.config import Config
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class ChatRateLimitSettings:
    """Operator-editable rate limit knobs for a multibook chat."""

    chat_id: str
    label: str
    messages_per_interval: int
    interval_seconds: int
    burst_allowance: int = 0

    @property
    def total_allowed(self) -> int:
        """Return the total events allowed inside the window including burst."""
        return self.messages_per_interval + self.burst_allowance

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dict."""
        return asdict(self)


class RateLimitSettingsStore:
    """JSON-backed store for chat-level rate limit settings."""

    def __init__(self, path: Optional[str] = None) -> None:
        default_path = getattr(
            Config, "RATE_LIMIT_SETTINGS_PATH", "data/rate_limit_settings.json"
        )
        self._path = Path(path or default_path)

    def load(
        self, defaults: Iterable[ChatRateLimitSettings]
    ) -> "OrderedDict[str, ChatRateLimitSettings]":
        """
        Return operator settings merged with defaults.

        Defaults keep their insertion order so the UI renders predictably.
        """
        profiles: "OrderedDict[str, ChatRateLimitSettings]" = OrderedDict(
            (profile.chat_id, profile) for profile in defaults
        )

        if not self._path.exists():
            return profiles

        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.warning(
                "rate_limit_settings_parse_failed",
                error=str(exc),
                path=str(self._path),
            )
            return profiles

        entries = payload.get("profiles", [])
        if not isinstance(entries, list):
            logger.warning(
                "rate_limit_settings_payload_invalid",
                path=str(self._path),
                payload_type=type(entries).__name__,
            )
            return profiles

        for entry in entries:
            try:
                profile = ChatRateLimitSettings(
                    chat_id=str(entry["chat_id"]),
                    label=str(entry.get("label") or entry["chat_id"]),
                    messages_per_interval=int(entry["messages_per_interval"]),
                    interval_seconds=int(entry["interval_seconds"]),
                    burst_allowance=int(entry.get("burst_allowance", 0)),
                )
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning(
                    "rate_limit_settings_entry_invalid",
                    error=str(exc),
                    entry=entry,
                )
                continue

            profiles[profile.chat_id] = profile

        return profiles

    def save(self, profiles: Iterable[ChatRateLimitSettings]) -> None:
        """Persist the supplied profiles in a deterministic order."""
        payload = {
            "profiles": [
                profile.to_dict()
                for profile in profiles
            ]
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temp_path.replace(self._path)
        logger.info(
            "rate_limit_settings_saved",
            path=str(self._path),
            profile_count=len(payload["profiles"]),
        )

    def current_version(self) -> float:
        """Return the on-disk modified timestamp for cache invalidation."""
        try:
            return self._path.stat().st_mtime
        except FileNotFoundError:
            return 0.0
