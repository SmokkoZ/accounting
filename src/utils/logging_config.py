"""
Logging configuration for the Surebet Accounting System.

This module sets up structured logging with structlog.
"""

import sys
from typing import Any, Dict

import structlog
from structlog.stdlib import LoggerFactory

from src.core.config import Config


def configure_logging() -> None:
    """
    Configure structured logging for the application.

    Sets up structlog with console output and appropriate log levels.
    """
    # Configure structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = None) -> structlog.stdlib.BoundLogger:
    """
    Get a structured logger instance.

    Args:
        name: Optional name for the logger. If None, uses the calling module's name.

    Returns:
        Configured structured logger instance.
    """
    return structlog.get_logger(name)


# Configure logging when module is imported
configure_logging()
