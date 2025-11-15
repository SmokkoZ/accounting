"""
Unit tests for src.ui.pages.7_associates_hub helpers.

Since Streamlit pages are loaded dynamically, tests import the module via
importlib to access helper functions without executing the full page.
"""

from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict

import pandas as pd
import pytest
from unittest.mock import Mock

from src.repositories.associate_hub_repository import (
    AssociateMetrics,
    BookmakerSummary,
)


@pytest.fixture(scope="module")
def associates_hub_module():
    """Load the Streamlit page module via spec loader."""
    import sys

    module_path = Path("src/ui/pages/7_associates_hub.py")
    sys.modules.setdefault("xlsxwriter", Mock())
    sys.modules.setdefault("xlsxwriter.utility", Mock())
    spec = importlib.util.spec_from_file_location(
        "associates_hub_page", module_path
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_associate_dataframe(associates_hub_module):
    """Ensure view-model builder exposes editable + read-only columns."""
    metric = AssociateMetrics(
        associate_id=1,
        associate_alias="Alice",
        home_currency="EUR",
        is_admin=True,
        is_active=True,
        telegram_chat_id="-100",
        bookmaker_count=3,
        active_bookmaker_count=2,
        net_deposits_eur=Decimal("1000.00"),
        should_hold_eur=Decimal("950.00"),
        fair_share_eur=Decimal("50.00"),
        current_holding_eur=Decimal("960.00"),
        balance_eur=Decimal("960.00"),
        pending_balance_eur=Decimal("40.00"),
        delta_eur=Decimal("10.00"),
        last_activity_utc="2025-01-01T00:00:00Z",
        status="balanced",
        status_color="#fff",
        internal_notes="note",
        max_surebet_stake_eur=Decimal("200.00"),
        max_bookmaker_exposure_eur=Decimal("500.00"),
        preferred_balance_chat_id="-200",
    )
    df = associates_hub_module._build_associate_dataframe([metric])
    assert list(df.columns) == [
        "id",
        "display_alias",
        "home_currency",
        "is_admin",
        "is_active",
        "multibook_chat_id",
        "internal_notes",
        "max_surebet_stake_eur",
        "max_bookmaker_exposure_eur",
        "preferred_balance_chat_id",
        "net_deposits_native",
        "yield_funds_native",
        "total_balance_native",
        "imbalance_native",
        "bookmaker_count",
        "action",
    ]
    row = df.iloc[0].to_dict()
    assert row["display_alias"] == "Alice"
    assert row["net_deposits_native"] == pytest.approx(1000.0)
    assert row["yield_funds_native"] == pytest.approx(950.0)
    assert row["total_balance_native"] == pytest.approx(960.0)
    assert row["action"] == ""


def test_build_bookmaker_dataframe(associates_hub_module):
    """Ensure bookmaker dataframe surfaces derived balances."""
    summary = BookmakerSummary(
        associate_id=1,
        bookmaker_id=2,
        bookmaker_name="Bookie",
        is_active=True,
        parsing_profile=None,
        native_currency="USD",
        account_currency="AUD",
        modeled_balance_eur=Decimal("300.00"),
        reported_balance_eur=Decimal("320.00"),
        delta_eur=Decimal("20.00"),
        last_balance_check_utc="2025-01-02T00:00:00Z",
        status="balanced",
        status_icon="✅",
        status_color="#fff",
        pending_balance_eur=Decimal("15.00"),
        bookmaker_chat_id="-1",
        coverage_chat_id="-2",
        region="EU",
        risk_level="Medium",
        internal_notes="note",
        associate_alias="Alpha",
        active_balance_native=Decimal("480.00"),
        pending_balance_native=Decimal("22.50"),
    )
    df, metadata = associates_hub_module._build_bookmaker_dataframe([summary])
    assert "active_balance_native" in df.columns
    row = df.iloc[0]
    assert row["associate_alias"] == "Alpha"
    assert row["account_currency"] == "AUD"
    assert row["active_balance_native"] == pytest.approx(480.0)
    assert row["active_balance_eur"] == pytest.approx(320.0)
    assert row["pending_balance_native"] == pytest.approx(22.5)
    assert metadata[2]["active_balance"] == Decimal("320.00")


def test_bookmaker_reassignment_requires_confirmation(
    associates_hub_module, monkeypatch
):
    """Verify reassignment queues confirmation when balances exist."""
    repository = Mock()
    repository.update_bookmaker = Mock()

    source_df = pd.DataFrame(
        [{"id": 5, "associate_id": 1, "bookmaker_name": "Bets", "account_currency": "EUR", "is_active": True}]
    )
    edited_df = pd.DataFrame(
        [{"id": 5, "associate_id": 2, "bookmaker_name": "Bets", "account_currency": "EUR", "is_active": True}]
    )
    state = {
        "edited_rows": {0: {"associate_id": 2}},
        "added_rows": [],
        "deleted_rows": [],
    }
    metadata = {
        5: {
            "associate_id": 1,
            "bookmaker_name": "Bets",
            "active_balance": Decimal("25.00"),
        }
    }
    associate_lookup = {1: "Alpha", 2: "Beta"}
    associate_currency_lookup = {1: "EUR", 2: "EUR"}
    queued: Dict[str, Any] = {}

    for method in ("info", "warning", "error", "success"):
        monkeypatch.setattr(
            associates_hub_module.st,
            method,
            lambda *args, **kwargs: None,
        )

    def fake_queue(payload: Dict[str, Any]) -> None:
        queued["payload"] = payload

    monkeypatch.setattr(
        associates_hub_module,
        "_queue_bookmaker_reassignment",
        fake_queue,
    )

    associates_hub_module._persist_bookmaker_changes(
        repository,
        source_df,
        edited_df,
        state,
        metadata=metadata,
        associate_lookup=associate_lookup,
        associate_currency_lookup=associate_currency_lookup,
    )

    assert "payload" in queued
    assert queued["payload"]["bookmaker_name"] == "Bets"
    assert queued["payload"]["current_alias"] == "Alpha"
    assert queued["payload"]["target_alias"] == "Beta"
    repository.update_bookmaker.assert_not_called()


def test_selection_picker_resets_selection_when_cleared(
    associates_hub_module, monkeypatch
):
    """Clearing the picker should drop all selected IDs immediately."""
    dataframe = pd.DataFrame(
        [
            {"id": 1, "display_alias": "Alpha"},
            {"id": 2, "display_alias": "Beta"},
        ]
    )

    monkeypatch.setattr(
        associates_hub_module.st,
        "multiselect",
        lambda *args, **kwargs: [],
    )

    result = associates_hub_module._render_selection_picker(dataframe, [1])
    assert result == []
