"""Keyboard shortcut helpers shared across Streamlit pages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Mapping, MutableMapping, Optional, Sequence


@dataclass(frozen=True)
class ShortcutHelpRow:
    """Structured description for a keyboard shortcut shown in the overlay."""

    category: str
    key: str
    label: str
    description: str


def resolve_hotkey_toggle_state(
    session_state: MutableMapping[str, object],
    *,
    session_key: str,
    requested_state: Optional[bool],
    default_enabled: bool = True,
) -> bool:
    """
    Determine the persisted toggle state for keyboard shortcuts.

    Args:
        session_state: Streamlit ``st.session_state`` mapping (or a stand-in for tests).
        session_key: Key used to persist the toggle in ``session_state``.
        requested_state: Optional override requested by the browser (e.g., sessionStorage).
        default_enabled: Default when no prior preference exists.

    Returns:
        Boolean indicating whether shortcuts should be enabled.
    """
    if session_key in session_state:
        return bool(session_state[session_key])

    if requested_state is not None:
        session_state[session_key] = bool(requested_state)
        return bool(requested_state)

    session_state[session_key] = bool(default_enabled)
    return bool(default_enabled)


def build_hotkey_help_rows() -> List[ShortcutHelpRow]:
    """
    Return the ordered rows rendered inside the keyboard shortcut overlay.

    Includes the incoming bets workflow shortcuts plus reminders that the
    Telegram oversight UI mirrors the same approve/reject semantics.
    """
    return [
        ShortcutHelpRow(
            category="Incoming Bets Queue",
            key="A",
            label="Approve selection",
            description="Approves all selected bets using the same payload the Telegram bot would submit.",
        ),
        ShortcutHelpRow(
            category="Incoming Bets Queue",
            key="R",
            label="Reject selection",
            description="Rejects the selected bets with the usual audit trail update.",
        ),
        ShortcutHelpRow(
            category="Incoming Bets Queue",
            key="E",
            label="Jump to edit form",
            description="Scrolls to the first bet's inline edit form so you can Tab through fields.",
        ),
        ShortcutHelpRow(
            category="Incoming Bets Queue",
            key="/",
            label="Focus search",
            description="Focuses the bet search bar to filter by alias, bookmaker, or selection text.",
        ),
        ShortcutHelpRow(
            category="Incoming Bets Queue",
            key="?",
            label="Shortcut & help overlay",
            description="Opens this overlay. Press Escape to close and resume hotkeys.",
        ),
        ShortcutHelpRow(
            category="Telegram Oversight",
            key="A / R",
            label="Mirror bot actions",
            description="Approving or rejecting here writes to the same Telegram audit log used by the bot.",
        ),
        ShortcutHelpRow(
            category="Telegram Oversight",
            key="Force Ingest",
            label="Shift focus",
            description="Use Force Ingest + justification to mimic Telegram overrides when triaging chats.",
        ),
    ]


def group_shortcuts_by_category(
    rows: Sequence[ShortcutHelpRow],
) -> Mapping[str, List[ShortcutHelpRow]]:
    """Group help rows by their category for easier rendering."""
    grouped: dict[str, List[ShortcutHelpRow]] = {}
    for row in rows:
        grouped.setdefault(row.category, []).append(row)
    return grouped


__all__ = [
    "ShortcutHelpRow",
    "build_hotkey_help_rows",
    "group_shortcuts_by_category",
    "resolve_hotkey_toggle_state",
]
