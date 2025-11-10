import json
import sqlite3
from pathlib import Path

from src.services.coverage_proof_service import CoverageProofService
from src.services.rate_limit_settings import (
    ChatRateLimitSettings,
    RateLimitSettingsStore,
)
from src.core import config as core_config


def test_store_returns_defaults_when_file_missing(tmp_path):
    path = tmp_path / "missing.json"
    store = RateLimitSettingsStore(path=str(path))
    defaults = [
        ChatRateLimitSettings(
            chat_id="__default__",
            label="All chats",
            messages_per_interval=10,
            interval_seconds=60,
            burst_allowance=2,
        ),
        ChatRateLimitSettings(
            chat_id="chat-ops",
            label="Ops Chat",
            messages_per_interval=8,
            interval_seconds=60,
            burst_allowance=1,
        ),
    ]

    profiles = store.load(defaults)

    assert list(profiles.keys()) == ["__default__", "chat-ops"]
    assert profiles["chat-ops"].messages_per_interval == 8


def test_store_merges_file_overrides(tmp_path):
    path = tmp_path / "rate_limits.json"
    payload = {
        "profiles": [
            {
                "chat_id": "__default__",
                "label": "All chats",
                "messages_per_interval": 5,
                "interval_seconds": 45,
                "burst_allowance": 1,
            },
            {
                "chat_id": "chat-vip",
                "label": "VIP",
                "messages_per_interval": 2,
                "interval_seconds": 60,
                "burst_allowance": 0,
            },
        ]
    }
    path.write_text(json.dumps(payload))

    defaults = [
        ChatRateLimitSettings(
            chat_id="__default__",
            label="All chats",
            messages_per_interval=10,
            interval_seconds=60,
            burst_allowance=2,
        )
    ]

    store = RateLimitSettingsStore(path=str(path))
    profiles = store.load(defaults)

    assert profiles["__default__"].messages_per_interval == 5
    assert "chat-vip" in profiles
    assert profiles["chat-vip"].burst_allowance == 0


def test_service_honors_persisted_thresholds(monkeypatch, tmp_path):
    path = tmp_path / "rate_limits.json"
    monkeypatch.setattr(core_config.Config, "RATE_LIMIT_SETTINGS_PATH", str(path))
    store = RateLimitSettingsStore(path=str(path))
    overrides = [
        ChatRateLimitSettings(
            chat_id="__default__",
            label="All chats",
            messages_per_interval=10,
            interval_seconds=60,
            burst_allowance=0,
        ),
        ChatRateLimitSettings(
            chat_id="chat-strict",
            label="Strict Chat",
            messages_per_interval=1,
            interval_seconds=60,
            burst_allowance=0,
        ),
    ]
    store.save(overrides)

    service = CoverageProofService(db=sqlite3.connect(":memory:"))

    allowed, wait_seconds = service._check_rate_limit("chat-strict")
    assert allowed is True
    assert wait_seconds == 0

    service._record_rate_limit("chat-strict")
    allowed, wait_seconds = service._check_rate_limit("chat-strict")
    assert allowed is False
    assert wait_seconds > 0

    service.close()


def test_store_falls_back_when_config_missing(monkeypatch):
    monkeypatch.delattr(core_config.Config, "RATE_LIMIT_SETTINGS_PATH", raising=False)
    store = RateLimitSettingsStore()

    assert store._path == Path("data/rate_limit_settings.json")
