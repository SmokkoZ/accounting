import types

import pytest

from src.ui.utils import feature_flags


def _clear_caches() -> None:
    """Ensure cached detections re-evaluate per test."""
    feature_flags._compute_feature_matrix.cache_clear()
    feature_flags.get_streamlit_version.cache_clear()
    feature_flags._get_streamlit_version_obj.cache_clear()


def test_feature_registry_contains_expected_keys():
    expected = {
        "fragment",
        "dialog",
        "popover",
        "navigation",
        "page_link",
        "write_stream",
        "pdf",
        "status",
        "toast",
        "data_editor",
        "column_config",
        "query_params",
    }
    assert set(feature_flags.FEATURES.keys()) == expected


def test_all_flags_detects_streamlit_attributes(monkeypatch):
    stub = types.SimpleNamespace(
        fragment=object(),
        dialog=None,
        popover=None,
        navigation=object(),
        page_link=None,
        write_stream=None,
        pdf=None,
        status=object(),
        toast=None,
        data_editor=object(),
        column_config=object(),
        query_params=None,
        __version__="1.40.0",
    )
    monkeypatch.setattr(feature_flags, "st", stub)
    _clear_caches()

    flags = feature_flags.all_flags()
    assert flags["fragment"] is True
    assert flags["dialog"] is False
    assert flags["navigation"] is True


def test_query_params_detection_handles_falsey_object(monkeypatch):
    class EmptyQueryParams:
        def __len__(self) -> int:
            return 0

    stub = types.SimpleNamespace(
        query_params=EmptyQueryParams(),
        __version__="1.35.0",
    )
    monkeypatch.setattr(feature_flags, "st", stub)
    _clear_caches()

    assert feature_flags.has("query_params") is True


def test_version_helpers_use_streamlit_version(monkeypatch):
    stub = types.SimpleNamespace(__version__="1.40.0")
    monkeypatch.setattr(feature_flags, "st", stub)
    _clear_caches()

    assert feature_flags.get_streamlit_version() == "1.40.0"
    assert feature_flags.is_minimum_version("1.30.0") is True
    assert feature_flags.is_recommended_version("1.46.0") is False


def test_get_feature_status_includes_recommendations(monkeypatch):
    fake_flags = {name: (idx % 2 == 0) for idx, name in enumerate(feature_flags.FEATURES)}
    monkeypatch.setattr(feature_flags, "all_flags", lambda: dict(fake_flags))
    monkeypatch.setattr(feature_flags, "is_minimum_version", lambda: True)
    monkeypatch.setattr(feature_flags, "is_recommended_version", lambda: False)
    monkeypatch.setattr(feature_flags, "get_streamlit_version", lambda: "1.40.0")

    status = feature_flags.get_feature_status()
    assert status["version"]["current"] == "1.40.0"
    assert status["version"]["minimum_met"] is True
    assert status["version"]["recommended_met"] is False
    assert status["compatibility_mode"] == "degraded"
    assert status["upgrade_needed"] is True

    fragment_info = status["features"]["fragment"]
    assert "required_for" in fragment_info
    assert "fallback_available" in fragment_info
    assert status["recommendations"], "Expected at least one recommendation"


def test_get_upgrade_recommendations_empty_when_fully_supported(monkeypatch):
    monkeypatch.setattr(feature_flags, "is_recommended_version", lambda: True)
    assert feature_flags.get_upgrade_recommendations([]) == []
