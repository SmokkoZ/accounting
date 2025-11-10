"""Tests for event normalization utilities."""

from src.services.event_normalizer import EventNormalizer


def test_normalize_event_name_bayern_club_bruges() -> None:
    """Ensure normalization avoids runaway alias expansion."""
    raw = "Bayern Munich vs Club Bruges"

    normalized = EventNormalizer.normalize_event_name(raw)
    assert normalized == "Bayern Munich vs Club Bruges"

    # Idempotence guard: running normalization again should keep the same value.
    assert EventNormalizer.normalize_event_name(normalized) == normalized


def test_normalize_preserves_hyphenated_club_names() -> None:
    """Hyphenated club names should not create phantom teams."""
    raw = "Lens vs Paris Saint-Germain Fc"

    normalized = EventNormalizer.normalize_event_name(raw)
    assert normalized == "Lens vs Paris Saint-Germain Fc"
    assert EventNormalizer.split_teams(normalized) == (
        "Lens",
        "Paris Saint-Germain Fc",
    )


def test_normalize_removes_duplicate_team_phrase() -> None:
    """Duplicate team strings should collapse to a single occurrence."""
    raw = "Eintracht Frankfurt Eintracht Frankfurt vs Bayern Munich"

    normalized = EventNormalizer.normalize_event_name(raw)
    assert normalized == "Eintracht Frankfurt vs Bayern Munich"


def test_normalize_collapses_repeated_word_within_team() -> None:
    """Duplicate trailing tokens are stripped from team names."""
    raw = "Real Madrid Madrid vs Barcelona"

    normalized = EventNormalizer.normalize_event_name(raw)
    assert normalized == "Real Madrid vs Barcelona"
