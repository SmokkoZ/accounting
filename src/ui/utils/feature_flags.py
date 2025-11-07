"""
Feature detection, version compatibility, and upgrade guidance helpers.

This module centralises all feature flag logic so the UI can conditionally
enable modern Streamlit APIs while still supporting the 1.30+ baseline. It
also exposes metadata for admin reporting and upgrade recommendations.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional

import streamlit as st
from packaging.version import InvalidVersion, Version

MIN_STREAMLIT_VERSION = "1.30.0"
RECOMMENDED_STREAMLIT_VERSION = "1.46.0"


@dataclass(frozen=True)
class FeatureDescriptor:
    """Describe a Streamlit capability we care about."""

    attribute: str
    description: str
    introduced: str
    has_fallback: bool = True


# Keys intentionally match the friendly feature names used across the UI.
FEATURES: Dict[str, FeatureDescriptor] = {
    "fragment": FeatureDescriptor(
        attribute="fragment",
        description="Partial reruns for heavy sections",
        introduced="1.30.0",
    ),
    "dialog": FeatureDescriptor(
        attribute="dialog",
        description="Modal confirmations and overrides",
        introduced="1.25.0",
    ),
    "popover": FeatureDescriptor(
        attribute="popover",
        description="Compact per-row action menus",
        introduced="1.29.0",
    ),
    "navigation": FeatureDescriptor(
        attribute="navigation",
        description="Declarative multipage navigation",
        introduced="1.34.0",
    ),
    "page_link": FeatureDescriptor(
        attribute="page_link",
        description="Inline cross-page navigation links",
        introduced="1.25.0",
    ),
    "write_stream": FeatureDescriptor(
        attribute="write_stream",
        description="Streaming progress/log rendering",
        introduced="1.32.0",
    ),
    "pdf": FeatureDescriptor(
        attribute="pdf",
        description="Inline PDF previews",
        introduced="1.32.0",
    ),
    "status": FeatureDescriptor(
        attribute="status",
        description="Persistent status/progress blocks",
        introduced="1.27.0",
    ),
    "toast": FeatureDescriptor(
        attribute="toast",
        description="Lightweight toast notifications",
        introduced="1.25.0",
    ),
    "data_editor": FeatureDescriptor(
        attribute="data_editor",
        description="Typed CRUD tables",
        introduced="1.19.0",
    ),
    "column_config": FeatureDescriptor(
        attribute="column_config",
        description="Column configuration helpers",
        introduced="1.19.0",
    ),
    "query_params": FeatureDescriptor(
        attribute="query_params",
        description="URL state management",
        introduced="1.23.0",
    ),
}


def _detect_feature(name: str) -> bool:
    descriptor = FEATURES.get(name)
    if not descriptor:
        return False
    return bool(getattr(st, descriptor.attribute, None))


@lru_cache(maxsize=1)
def _compute_feature_matrix() -> Dict[str, bool]:
    """Return a cached mapping of supported feature names to booleans."""
    return {name: _detect_feature(name) for name in FEATURES}


def all_flags() -> Dict[str, bool]:
    """Expose a copy of the current feature availability map."""
    return dict(_compute_feature_matrix())


def has(name: str) -> bool:
    """Check whether a given Streamlit feature exists."""
    return bool(_compute_feature_matrix().get(name, False))


def has_feature(name: str) -> bool:
    """Alias preserved for docs/tests."""
    return has(name)


def supports_dialogs() -> bool:
    """Return True when dialog support is available."""
    return has("dialog")


def supports_popovers() -> bool:
    """Return True when popover support is available."""
    return has("popover")


@lru_cache(maxsize=1)
def get_streamlit_version() -> Optional[str]:
    """Return the current Streamlit version string, if exposed."""
    return getattr(st, "__version__", None)


def _parse_version(value: Optional[str]) -> Optional[Version]:
    if not value:
        return None
    try:
        return Version(value)
    except InvalidVersion:
        return None


@lru_cache(maxsize=1)
def _get_streamlit_version_obj() -> Optional[Version]:
    return _parse_version(get_streamlit_version())


def is_minimum_version(min_version: str = MIN_STREAMLIT_VERSION) -> bool:
    """Return True when the runtime meets the documented minimum version."""
    current = _get_streamlit_version_obj()
    target = _parse_version(min_version)
    if current is None or target is None:
        return False
    return current >= target


def is_recommended_version(rec_version: str = RECOMMENDED_STREAMLIT_VERSION) -> bool:
    """Return True when the runtime meets the recommended version."""
    current = _get_streamlit_version_obj()
    target = _parse_version(rec_version)
    if current is None or target is None:
        return False
    return current >= target


def get_missing_features() -> List[str]:
    """Return a sorted list of unavailable features."""
    return sorted(name for name, enabled in _compute_feature_matrix().items() if not enabled)


def has_fallback(feature: str) -> bool:
    """Inform the admin panel whether a feature has a coded fallback."""
    descriptor = FEATURES.get(feature)
    return bool(descriptor and descriptor.has_fallback)


def get_feature_status() -> Dict[str, Any]:
    """Return a comprehensive snapshot for admin/debug tooling."""
    flags = all_flags()
    missing = [name for name, available in flags.items() if not available]

    feature_rows = {
        name: {
            "available": flags.get(name, False),
            "required_for": descriptor.description,
            "introduced": descriptor.introduced,
            "fallback_available": descriptor.has_fallback,
        }
        for name, descriptor in FEATURES.items()
    }

    recommended_met = is_recommended_version()
    version_info = {
        "current": get_streamlit_version(),
        "minimum_met": is_minimum_version(),
        "recommended_met": recommended_met,
        "minimum_required": MIN_STREAMLIT_VERSION,
        "recommended": RECOMMENDED_STREAMLIT_VERSION,
    }

    return {
        "version": version_info,
        "features": feature_rows,
        "missing": missing,
        "upgrade_needed": not recommended_met,
        "compatibility_mode": "full" if recommended_met else "degraded",
        "recommendations": get_upgrade_recommendations(missing),
    }


def get_upgrade_recommendations(missing: Optional[Iterable[str]] = None) -> List[str]:
    """Generate actionable upgrade nudges based on missing capabilities."""
    missing = list(missing) if missing is not None else get_missing_features()
    if not missing and is_recommended_version():
        return []

    recommendations: List[str] = []
    if not is_recommended_version():
        recommendations.append(
            f"Upgrade Streamlit to at least {RECOMMENDED_STREAMLIT_VERSION} to unlock the full UI."
        )

    for name in missing:
        descriptor = FEATURES.get(name)
        if not descriptor:
            continue
        recommendations.append(
            f"Enable '{name}' ({descriptor.description}) by upgrading to Streamlit {descriptor.introduced}+."
        )

    return recommendations


__all__ = [
    "FEATURES",
    "MIN_STREAMLIT_VERSION",
    "RECOMMENDED_STREAMLIT_VERSION",
    "all_flags",
    "get_feature_status",
    "get_missing_features",
    "get_streamlit_version",
    "get_upgrade_recommendations",
    "has",
    "has_feature",
    "has_fallback",
    "is_minimum_version",
    "is_recommended_version",
    "supports_dialogs",
    "supports_popovers",
]
