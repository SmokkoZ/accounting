"""Unit tests for keyboard shortcut helper utilities."""

from __future__ import annotations

from src.ui.helpers import keyboard_shortcuts


def test_resolve_hotkey_toggle_state_prefers_existing_value() -> None:
    state = { "demo": False }
    result = keyboard_shortcuts.resolve_hotkey_toggle_state(
        state,
        session_key="demo",
        requested_state=True,
        default_enabled=True,
    )
    assert result is False
    assert state["demo"] is False


def test_resolve_hotkey_toggle_state_accepts_requested_override() -> None:
    state: dict[str, object] = {}
    result = keyboard_shortcuts.resolve_hotkey_toggle_state(
        state,
        session_key="demo",
        requested_state=False,
        default_enabled=True,
    )
    assert result is False
    assert state["demo"] is False


def test_resolve_hotkey_toggle_state_uses_default_when_empty() -> None:
    state: dict[str, object] = {}
    result = keyboard_shortcuts.resolve_hotkey_toggle_state(
        state,
        session_key="demo",
        requested_state=None,
        default_enabled=False,
    )
    assert result is False
    assert state["demo"] is False


def test_build_hotkey_help_rows_includes_expected_entries() -> None:
    rows = keyboard_shortcuts.build_hotkey_help_rows()
    key_pairs = {(row.category, row.key) for row in rows}
    assert ("Incoming Bets Queue", "A") in key_pairs
    assert ("Incoming Bets Queue", "/") in key_pairs
    assert any(row.category == "Telegram Oversight" for row in rows)
