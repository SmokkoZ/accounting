import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.ui.helpers import saved_views, url_state


def test_update_query_params_updates_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyStreamlit:
        def __init__(self) -> None:
            self.query_params: Dict[str, Any] = {}

    dummy = DummyStreamlit()

    monkeypatch.setattr(url_state, "st", dummy)
    monkeypatch.setattr(url_state.feature_flags, "has", lambda name: name == "query_params")

    changed = url_state.update_query_params({"bookmaker": ["Alpha", "Bravo"], "bet": "single"})
    assert changed is True
    assert dummy.query_params["bookmaker"] == ["Alpha", "Bravo"]
    assert dummy.query_params["bet"] == ["single"]

    changed = url_state.update_query_params({"bookmaker": None})
    assert changed is True
    assert "bookmaker" not in dummy.query_params

    # No change should return False
    assert url_state.update_query_params({"bet": "single"}) is False


def test_update_query_params_uses_experimental_setters(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: Dict[str, List[str]] = {}

    def fake_get() -> Dict[str, List[str]]:
        return {"confidence": ["high"]}

    def fake_set(**kwargs: List[str]) -> None:
        captured.update(kwargs)

    class DummyStreamlit:
        experimental_get_query_params = staticmethod(fake_get)
        experimental_set_query_params = staticmethod(fake_set)

    monkeypatch.setattr(url_state, "st", DummyStreamlit())
    monkeypatch.setattr(url_state.feature_flags, "has", lambda name: False)

    assert url_state.update_query_params({"confidence": "low"}) is True
    assert captured["confidence"] == ["low"]


def test_saved_view_manager_persists_and_decodes_bookmakers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FINAL_APP_PREFERENCES_DIR", str(tmp_path))
    monkeypatch.setattr(saved_views.url_state, "read_query_params", lambda: {})

    manager = saved_views.SavedViewManager(slug="incoming-bets-test")
    manager.save(
        bookmakers=["Alpha", "Bravo"],
        bet_type="multi",
        confidence="high",
        compact=True,
        auto=False,
    )

    fresh_manager = saved_views.SavedViewManager(slug="incoming-bets-test")
    snapshot = fresh_manager.get_snapshot(bookmaker_options=["Alpha", "Bravo", "Charlie"])

    assert snapshot.bookmaker == ["Alpha", "Bravo"]
    assert snapshot.bet_type == "multi"
    assert snapshot.confidence == "high"
    assert snapshot.compact is True
    assert snapshot.auto is False


def test_saved_view_prefers_query_params_over_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FINAL_APP_PREFERENCES_DIR", str(tmp_path))
    monkeypatch.setattr(
        saved_views.url_state,
        "read_query_params",
        lambda: {"bookmaker": ["QueryOnly"], "bet": "single", "confidence": "low", "auto": "0"},
    )

    manager = saved_views.SavedViewManager(slug="incoming-bets-override")
    manager.save(bookmakers=["Stored"], bet_type="multi", confidence="high", auto=True)

    snapshot = saved_views.SavedViewManager(slug="incoming-bets-override").get_snapshot(
        bookmaker_options=["Stored", "QueryOnly"]
    )

    assert snapshot.bookmaker == ["QueryOnly"]
    assert snapshot.bet_type == "single"
    assert snapshot.confidence == "low"
    assert snapshot.auto is False


def test_saved_view_file_expires_after_30_days(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FINAL_APP_PREFERENCES_DIR", str(tmp_path))
    monkeypatch.setattr(saved_views.url_state, "read_query_params", lambda: {})

    slug = "incoming-bets-expire"
    manager = saved_views.SavedViewManager(slug=slug)
    manager.save(confidence="high")

    token = hashlib.sha1(f"saved_view::{slug}".encode("utf-8")).hexdigest()
    pref_path = tmp_path / f"{token}.json"
    data = json.loads(pref_path.read_text())
    data["updated_at"] = (datetime.now(tz=UTC) - timedelta(days=31)).isoformat()
    pref_path.write_text(json.dumps(data))

    expired_manager = saved_views.SavedViewManager(slug=slug)
    assert expired_manager.get_snapshot().confidence is None
    assert not pref_path.exists()
