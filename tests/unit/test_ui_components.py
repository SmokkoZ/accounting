from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from src.ui import ui_components


class DummyStreamlit:
    def __init__(self) -> None:
        self.session_state: dict[str, object] = {}
        self.markdown_calls: list[tuple[str, bool]] = []
        self.warning_calls: list[str] = []
        self.error_calls: list[str] = []
        self.caption_calls: list[str] = []

    def markdown(self, content: str, unsafe_allow_html: bool = False) -> None:
        self.markdown_calls.append((content, unsafe_allow_html))

    def warning(self, message: str) -> None:  # pragma: no cover - defensive
        self.warning_calls.append(message)

    def error(self, message: str) -> None:  # pragma: no cover - defensive
        self.error_calls.append(message)

    def caption(self, content: str) -> None:
        self.caption_calls.append(content)


@pytest.fixture
def dummy_st(monkeypatch: pytest.MonkeyPatch) -> DummyStreamlit:
    dummy = DummyStreamlit()
    monkeypatch.setattr(ui_components, "st", dummy)
    return dummy


def test_load_global_styles_injects_css_once(
    dummy_st: DummyStreamlit, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    css_path = tmp_path / "ui_styles.css"
    css_path.write_text(".card {border: 0;}", encoding="utf-8")
    monkeypatch.setattr(ui_components, "_CSS_PATH", css_path)

    ui_components.load_global_styles()
    assert dummy_st.markdown_calls == [("<style>.card {border: 0;}</style>", True)]
    assert dummy_st.session_state["_global_styles_loaded"] is True

    ui_components.load_global_styles()
    assert len(dummy_st.markdown_calls) == 1  # cached


def test_metric_compact_renders_expected_markup(dummy_st: DummyStreamlit) -> None:
    ui_components.metric_compact("Open Surebets", "12", delta="+2 vs yesterday")

    assert len(dummy_st.markdown_calls) == 1
    content, unsafe = dummy_st.markdown_calls[0]
    assert unsafe is True
    assert "Open Surebets" in content
    assert "12" in content
    assert "+2 vs yesterday" in content


def test_card_context_manager_wraps_content(
    dummy_st: DummyStreamlit, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        ui_components, "load_global_styles", lambda force=False: None
    )

    with ui_components.card("Resolve Events", "Low-confidence matches"):
        ui_components.st.markdown("inner content")

    opening, _ = dummy_st.markdown_calls[0]
    closing, _ = dummy_st.markdown_calls[-1]

    assert '<div class="card">' in opening
    assert "</div>" == closing
    assert any("### Resolve Events" in call[0] for call in dummy_st.markdown_calls)
    assert dummy_st.caption_calls == ["Low-confidence matches"]
