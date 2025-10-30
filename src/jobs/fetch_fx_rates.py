"""
Background job for fetching daily FX rates.

This script is designed to be run as a cron job at midnight UTC
to update the FX rates in the database.
"""

import asyncio
import sys
from datetime import datetime
from decimal import Decimal

import structlog

from src.core.config import Config
from src.core.database import get_db_connection
from src.integrations.fx_api_client import fetch_daily_fx_rates
from src.services.fx_manager import store_fx_rate, format_timestamp_utc

# Configure structured logging
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
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


def insert_sample_fx_rates() -> None:
    """
    Insert sample FX rates for testing purposes.

    This function populates the fx_rates_daily table with the sample rates
    specified in the story acceptance criteria.
    """
    sample_rates = {
        "EUR": Decimal("1.0"),
        "AUD": Decimal("0.60"),
        "GBP": Decimal("1.15"),
        "USD": Decimal("0.92"),
    }

    timestamp = format_timestamp_utc()
    today = datetime.utcnow().strftime("%Y-%m-%d")

    conn = get_db_connection()
    try:
        for currency, rate in sample_rates.items():
            conn.execute(
                """
                INSERT OR REPLACE INTO fx_rates_daily 
                (currency_code, rate_to_eur, fetched_at_utc, date, created_at_utc)
                VALUES (?, ?, ?, ?, ?)
            """,
                (currency, str(rate), timestamp, today, timestamp),
            )

        conn.commit()

        logger.info(
            "sample_fx_rates_inserted",
            currencies=list(sample_rates.keys()),
            date=today,
            timestamp=timestamp,
        )

    except Exception as e:
        logger.error("sample_fx_rates_insert_failed", error=str(e))
        raise
    finally:
        conn.close()


async def update_fx_rates_daily() -> bool:
    """
    Update FX rates from external API.

    Returns:
        True if successful, False otherwise
    """
    logger.info("fx_rate_update_started")

    try:
        success = await fetch_daily_fx_rates()

        if success:
            logger.info("fx_rate_update_completed_successfully")
        else:
            logger.error("fx_rate_update_failed")

        return success

    except Exception as e:
        logger.error("fx_rate_update_exception", error=str(e), exc_info=True)
        return False


def main() -> None:
    """
    Main entry point for the FX rate update job.

    This function:
    1. Validates configuration
    2. Inserts sample rates if requested
    3. Fetches and stores latest rates from API
    """
    # Validate configuration
    try:
        Config.validate()
    except ValueError as e:
        logger.error("configuration_validation_failed", error=str(e))
        sys.exit(1)

    # Check if we should insert sample rates
    if len(sys.argv) > 1 and sys.argv[1] == "--sample":
        logger.info("inserting_sample_fx_rates")
        insert_sample_fx_rates()
        return

    # Update rates from API
    success = asyncio.run(update_fx_rates_daily())

    if not success:
        logger.error("fx_rate_update_job_failed")
        sys.exit(1)

    logger.info("fx_rate_update_job_completed")


if __name__ == "__main__":
    main()
