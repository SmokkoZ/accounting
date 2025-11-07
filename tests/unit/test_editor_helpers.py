"""Unit tests for src.ui.helpers.editor utilities."""

from __future__ import annotations

import pandas as pd
import pytest

from src.ui.helpers import editor


def test_build_associates_dataframe_normalizes_columns() -> None:
    records = [
        {
            "id": 1,
            "display_alias": "Alice",
            "home_currency": "eur",
            "is_admin": 1,
            "bookmaker_count": None,
        }
    ]

    frame = editor.build_associates_dataframe(records)

    assert list(editor.ASSOCIATE_COLUMNS) == list(frame.columns)
    assert frame.loc[0, "home_currency"] == "eur"
    assert bool(frame.loc[0, "is_admin"]) is True
    assert bool(frame.loc[0, "is_active"]) is False
    assert frame.loc[0, "bookmaker_count"] == 0


def test_build_bookmakers_dataframe_includes_chat_id_column() -> None:
    records = [
        {
            "id": 7,
            "associate_id": 3,
            "bookmaker_name": "Bet365",
            "parsing_profile": None,
            "bookmaker_chat_id": "-123456",
            "is_active": None,
        }
    ]

    frame = editor.build_bookmakers_dataframe(records)

    assert list(editor.BOOKMAKER_COLUMNS) == list(frame.columns)
    assert frame.loc[0, "bookmaker_chat_id"] == "-123456"
    assert bool(frame.loc[0, "is_active"]) is True


def test_validate_bookmaker_row_rejects_invalid_chat_id() -> None:
    is_valid, errors = editor.validate_bookmaker_row(
        {"bookmaker_name": "Test", "bookmaker_chat_id": "not123"}
    )

    assert is_valid is False
    assert any("Chat ID" in err for err in errors)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, True),
        ("", True),
        ("50", True),
        ("12.5", True),
        ("101", False),
        ("-1", False),
        ("1.234", False),
        ("abc", False),
    ],
)
def test_validate_share_percentage(value, expected) -> None:
    result, _ = editor.validate_share_percentage(value)
    assert result is expected


def test_get_selected_row_ids_returns_ids() -> None:
    frame = pd.DataFrame([{"id": 10}, {"id": 20}, {"id": 30}])
    state = {"selection": {"rows": [0, 2]}}

    selected = editor.get_selected_row_ids(state, frame)

    assert selected == [10, 30]


def test_get_selected_row_ids_handles_nested_selection_mapping() -> None:
    frame = pd.DataFrame([{"id": 10}, {"id": 20}, {"id": 30}])
    state = {"selection": {"rows": {"selected_rows": [1]}}}

    selected = editor.get_selected_row_ids(state, frame)

    assert selected == [20]


def test_get_selected_row_ids_handles_dict_entries() -> None:
    frame = pd.DataFrame([{"id": 10}, {"id": 20}, {"id": 30}])
    state = {"selection": {"rows": [{"index": 2}]}}

    selected = editor.get_selected_row_ids(state, frame)

    assert selected == [30]


def test_filter_bookmakers_by_associates_filters_dataframe() -> None:
    frame = pd.DataFrame(
        [
            {"id": 1, "associate_id": 1},
            {"id": 2, "associate_id": 2},
            {"id": 3, "associate_id": 1},
        ]
    )

    filtered = editor.filter_bookmakers_by_associates(frame, [1])

    assert len(filtered) == 2
    assert filtered["associate_id"].tolist() == [1, 1]


def test_extract_editor_changes_handles_empty_state() -> None:
    changes = editor.extract_editor_changes(None)
    assert changes.edited_rows == {}
    assert changes.added_rows == []
    assert changes.deleted_rows == []


def test_validate_bookmaker_row_detects_missing_name() -> None:
    is_valid, errors = editor.validate_bookmaker_row({"bookmaker_name": ""})
    assert is_valid is False
    assert any("required" in err.lower() for err in errors)
