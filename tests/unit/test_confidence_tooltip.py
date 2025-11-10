"""Unit tests for the confidence tooltip rendering path."""

from src.ui.components import bet_card
from src.ui.utils import formatters


def test_confidence_tooltip_uses_formatter_copy(monkeypatch):
    """Ensure tooltip markup reuses formatter text and stays accessible."""
    captured = {}

    def fake_markdown(markup: str, *, unsafe_allow_html: bool) -> None:
        captured["html"] = markup
        captured["unsafe"] = unsafe_allow_html

    monkeypatch.setattr(bet_card.st, "markdown", fake_markdown)

    bet_card._render_confidence_rationale_badge("bet-42", 0.88)

    _, _, _, tooltip_text = formatters.format_confidence_badge(0.88)
    html = captured["html"]

    assert captured["unsafe"] is True
    assert tooltip_text in html
    assert 'aria-describedby="confidence-tooltip-bet-42-sr"' in html
    assert 'class="sr-only"' in html
    assert 'confidence-tooltip-bet-42' in html
    assert 'data-confidence="0.8800"' in html
    assert f'title="{tooltip_text}"' in html
