"""
Configuration management for the Surebet Accounting System.

This module handles loading and validating environment variables.
"""

import os
from typing import Optional

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


def _int_env(key: str, default: int) -> int:
    value = os.getenv(key)
    if value is None or value.strip() == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _float_env(key: str, default: float) -> float:
    value = os.getenv(key)
    if value is None or value.strip() == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


class Config:
    """Configuration class with environment variables."""

    # Database
    DB_PATH: str = os.getenv("DB_PATH", "data/surebet.db")
    STAKE_AT_PLACEMENT: bool = os.getenv("STAKE_AT_PLACEMENT", "false").strip().lower() in (
        "1",
        "true",
        "yes",
        "y",
    )

    # Telegram
    TELEGRAM_BOT_TOKEN: Optional[str] = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_ADMIN_CHAT_ID: Optional[str] = os.getenv("TELEGRAM_ADMIN_CHAT_ID")
    # Comma-separated Telegram user IDs who can run admin commands anywhere
    TELEGRAM_ADMIN_USER_IDS: set[int] = set(
        int(x)
        for x in (os.getenv("TELEGRAM_ADMIN_USER_IDS") or "").replace(" ", "").split(",")
        if x.isdigit()
    )
    TELEGRAM_MAX_RPS: int = _int_env("TELEGRAM_MAX_RPS", 15)
    TELEGRAM_PER_CHAT_RPS: float = _float_env("TELEGRAM_PER_CHAT_RPS", 1.0)

    # OpenAI
    OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY")

    # FX API
    FX_API_KEY: Optional[str] = os.getenv("FX_API_KEY")
    FX_API_BASE_URL: str = os.getenv(
        "FX_API_BASE_URL", "https://api.exchangerate-api.com/v4/latest/"
    )

    # Paths
    SCREENSHOT_DIR: str = os.getenv("SCREENSHOT_DIR", "data/screenshots")
    EXPORT_DIR: str = os.getenv("EXPORT_DIR", "data/exports")
    LOG_DIR: str = os.getenv("LOG_DIR", "data/logs")

    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # Event creation/normalization
    AUTO_CREATE_EVENT_ON_OCR: bool = os.getenv("AUTO_CREATE_EVENT_ON_OCR", "true").lower() in ("1", "true", "yes", "y")
    OCR_EVENT_CONFIDENCE_THRESHOLD: float = float(os.getenv("OCR_EVENT_CONFIDENCE_THRESHOLD", "0.90"))

    @classmethod
    def validate(cls) -> None:
        """
        Validate that required configuration is present.

        Raises:
            ValueError: If required configuration is missing.
        """
        # For now, only validate database path since other APIs might be optional
        if not cls.DB_PATH:
            raise ValueError("DB_PATH must be configured")

        # Validate optional but recommended configs
        if not cls.TELEGRAM_BOT_TOKEN:
            print("WARNING: TELEGRAM_BOT_TOKEN not configured - Telegram features will be disabled")

        if not cls.OPENAI_API_KEY:
            print("WARNING: OPENAI_API_KEY not configured - OCR features will be disabled")

        if not cls.FX_API_KEY:
            print("WARNING: FX_API_KEY not configured - FX features will be disabled")
