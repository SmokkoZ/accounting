from __future__ import annotations

from decimal import Decimal
from typing import List, Tuple

from src.ui.helpers import dialogs
from src.ui.helpers.dialogs import ActionItem


class StubStreamlit:
    """Lightweight stub to simulate Streamlit behaviour for dialog helpers."""

    def __init__(self) -> None:
        self.session_state = {}
        self.captions: List[str] = []
        self.button_calls: List[Tuple[str, str]] = []
        self.button_responses: List[bool] = []
        self.popover_calls: List[Tuple[str, dict]] = []
        self.rerun_calls = 0

    def caption(self, message: str) -> None:
        self.captions.append(message)

    def button(self, label: str, key: str | None = None, **kwargs) -> bool:
        self.button_calls.append((label, key or ""))
        if self.button_responses:
            return self.button_responses.pop(0)
        return False

    def rerun(self) -> None:
        self.rerun_calls += 1

    def popover(self, label: str, **kwargs):
        self.popover_calls.append((label, kwargs))
        stub = self

        class _Context:
            def __enter__(self_inner):
                return stub

            def __exit__(self_inner, exc_type, exc, tb):
                return False

        return _Context()


def test_render_action_menu_fallback_emits_action(monkeypatch):
    stub = StubStreamlit()
    stub.button_responses = [True]

    monkeypatch.setattr(dialogs, "st", stub)
    monkeypatch.setattr(dialogs.feature_flags, "supports_popovers", lambda: False)

    actions = [ActionItem(key="edit", label="Edit")]

    # First invocation simulates the click and schedules a rerun
    result = dialogs.render_action_menu(key="menu", label="Actions", actions=actions)
    assert result is None
    assert stub.rerun_calls == 1
    assert stub.captions == ["Actions"]

    # Second invocation should surface the stored action
    result = dialogs.render_action_menu(key="menu", label="Actions", actions=actions)
    assert result == "edit"
    assert "menu__payload" not in stub.session_state


def test_render_action_menu_popover_path(monkeypatch):
    stub = StubStreamlit()
    stub.button_responses = [True]

    monkeypatch.setattr(dialogs, "st", stub)
    monkeypatch.setattr(dialogs.feature_flags, "supports_popovers", lambda: True)

    actions = [ActionItem(key="delete", label="Delete")]

    dialogs.render_action_menu(key="menu", label="Actions", actions=actions)
    assert stub.popover_calls == [("Actions", {"use_container_width": True})]

    result = dialogs.render_action_menu(key="menu", label="Actions", actions=actions)
    assert result == "delete"


def test_validate_canonical_event_inputs_detects_errors():
    errors = dialogs._validate_canonical_event_inputs(  # pylint: disable=protected-access
        event_name="abc",
        competition="X" * 101,
        kickoff_time="2025-11-06T12:00:00",
    )
    assert "Event name must be at least 5 characters long." in errors
    assert "Competition name must not exceed 100 characters." in errors
    assert "Kickoff time must end with 'Z' (UTC timezone)." in errors


def test_validate_canonical_event_inputs_success():
    errors = dialogs._validate_canonical_event_inputs(  # pylint: disable=protected-access
        event_name="Valid Event",
        competition="League",
        kickoff_time="2025-11-06T12:00:00Z",
    )
    assert errors == []


def test_validate_correction_inputs_parses_values():
    result = dialogs._validate_correction_inputs(  # pylint: disable=protected-access
        amount_value="+10.50",
        currency="eur",
        note="Adjustment",
    )
    assert result["errors"] == []
    assert result["amount_native"] == Decimal("10.50")
    assert result["currency"] == "EUR"
    assert result["note"] == "Adjustment"


def test_validate_correction_inputs_reports_errors():
    result = dialogs._validate_correction_inputs(  # pylint: disable=protected-access
        amount_value="abc",
        currency="",
        note="",
    )
    assert "Correction amount must be a valid decimal number." in result["errors"]
    assert "Currency is required." in result["errors"]
    assert "A note is required for audit purposes." in result["errors"]
