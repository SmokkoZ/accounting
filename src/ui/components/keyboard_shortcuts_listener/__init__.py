"""Thin wrapper to expose the keyboard shortcuts listener custom component."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import streamlit.components.v1 as components

_COMPONENT_DIR = Path(__file__).parent / "frontend" / "build"
_keyboard_listener_component = components.declare_component(
    "keyboard_shortcuts_listener",
    path=str(_COMPONENT_DIR),
)


def keyboard_shortcuts_listener(**kwargs: Any) -> Optional[Dict[str, Any]]:
    """
    Render the keyboard listener component and return emitted events.

    The component returns dictionaries such as
    ``{\"event\": \"hotkey\", \"action\": \"approve\"}``.
    """
    return _keyboard_listener_component(**kwargs, default=None)


__all__ = ["keyboard_shortcuts_listener"]
