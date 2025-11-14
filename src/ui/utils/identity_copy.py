"""
Identity copy helpers for ND/FS/YF rollout messaging.

Provides a single place to read the `SUREBET_YF_COPY_ROLLOUT` toggle and surface
consistent labels, tooltips, and rollout guidance across the Streamlit UI.
"""

from __future__ import annotations

import os
from functools import lru_cache

ROLLOUT_ENV_KEY = "SUREBET_YF_COPY_ROLLOUT"
LEGACY_VALUES = {"legacy", "off", "false", "0", "disabled"}


@lru_cache(maxsize=1)
def _rollout_mode() -> str:
    """Return the normalized rollout mode."""
    raw = os.getenv(ROLLOUT_ENV_KEY, "enabled").strip().lower()
    return raw or "enabled"


def refresh_rollout_mode_cache() -> None:
    """Clear memoized rollout state (useful for tests)."""
    _rollout_mode.cache_clear()  # type: ignore[attr-defined]


def is_yf_copy_enabled() -> bool:
    """True when the UI should prefer the new 'Your Fair Balance' wording."""
    return _rollout_mode() not in LEGACY_VALUES


def identity_label() -> str:
    """Primary label for the entitlement identity metric."""
    return "Your Fair Balance (YF)" if is_yf_copy_enabled() else "Should Hold"


def identity_symbol() -> str:
    """Abbreviated symbol used inside formulas."""
    return "YF" if is_yf_copy_enabled() else "Should Hold"


def identity_tooltip() -> str:
    """Tooltip for entitlement metrics."""
    if is_yf_copy_enabled():
        return "Identity target: ND + FS"
    return "Legacy 'Should Hold' entitlement (ND + FS)."


def identity_formula() -> str:
    """Readable formula for the entitlement identity."""
    return "YF = ND + FS" if is_yf_copy_enabled() else "Should Hold = ND + FS"


def identity_caption_text() -> str:
    """Caption describing how entitlement and imbalance relate."""
    if is_yf_copy_enabled():
        return "YF = ND + FS. TB - YF = I'' (imbalance). Exit payout (-I'') zeroes the associate before exit."
    return (
        "Should Hold = ND + FS. TB - Should Hold = I'' (imbalance). "
        "Set SUREBET_YF_COPY_ROLLOUT=enabled to switch the UI copy to YF."
    )


def identity_anchor_sentence() -> str:
    """Sentence used near Settle Associate actions that explains the anchor metric."""
    if is_yf_copy_enabled():
        return "Your Fair Balance (YF = ND + FS) anchors this action."
    return (
        "Legacy Should Hold (ND + FS entitlement) anchors this action until the "
        "`SUREBET_YF_COPY_ROLLOUT` flag is enabled."
    )


def identity_rollout_note() -> str:
    """Guidance on how to toggle the rollout flag for operations."""
    if is_yf_copy_enabled():
        return (
            "Set `SUREBET_YF_COPY_ROLLOUT=legacy` to temporarily retain the 'Should Hold' label "
            "during partner enablement."
        )
    return (
        "Legacy 'Should Hold' copy is active; set `SUREBET_YF_COPY_ROLLOUT=enabled` once associates "
        "are ready for the YF terminology."
    )


__all__ = [
    "identity_anchor_sentence",
    "identity_caption_text",
    "identity_formula",
    "identity_label",
    "identity_rollout_note",
    "identity_symbol",
    "identity_tooltip",
    "is_yf_copy_enabled",
    "refresh_rollout_mode_cache",
]
