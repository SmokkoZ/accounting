"""
FX API Client for the Surebet Accounting System.

This module handles fetching FX rates from external APIs.
"""

import httpx
import structlog
from decimal import Decimal
from typing import Dict, Optional
from urllib.parse import urlencode, urljoin

from src.core.config import Config
from src.services.fx_manager import store_fx_rate, format_timestamp_utc

logger = structlog.get_logger()


class FXAPIClient:
    """Client for fetching FX rates from external APIs."""

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        """
        Initialize the FX API client.

        Args:
            api_key: API key for the FX service
            base_url: Base URL for the FX API
        """
        self.api_key = api_key or Config.FX_API_KEY
        self.base_url = base_url or Config.FX_API_BASE_URL

        if not self.api_key:
            logger.warning("fx_api_no_key", message="No FX API key configured")

    def _build_request(self) -> tuple[str, dict]:
        """
        Build the request URL and headers for the configured FX provider.

        Supports both v6 path-style keys and v4 query/header-based endpoints.

        Returns:
            (url, headers)
        """
        base = (self.base_url or "").rstrip("/") + "/"
        headers: dict = {}

        # v6 style: https://v6.exchangerate-api.com/v6/{API_KEY}/latest/EUR
        if "v6.exchangerate-api.com" in base:
            url = f"{base}{self.api_key}/latest/EUR"
            return url, headers  # no header required

        # v4 style: https://api.exchangerate-api.com/v4/latest/EUR?apiKey=KEY
        if "api.exchangerate-api.com" in base:
            url = f"{base}EUR?" + urlencode({"apiKey": self.api_key})
            return url, headers

        # Generic fallback: base + EUR with header apikey
        url = f"{base}EUR"
        headers = {"apikey": self.api_key} if self.api_key else {}
        return url, headers

    async def fetch_rates_from_exchangerate_api(self) -> Dict[str, Decimal]:
        """
        Fetch FX rates from Exchangerate-API.com.

        Returns:
            Dictionary mapping currency codes to EUR rates

        Raises:
            httpx.HTTPError: If API request fails
            ValueError: If API response is invalid
        """
        if not self.api_key:
            raise ValueError("FX API key is required to fetch rates")

        # Build URL/headers based on configured provider
        url, headers = self._build_request()

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=headers)
                response.raise_for_status()

                data = response.json()

                if "rates" not in data:
                    raise ValueError("Invalid API response: missing 'rates' field")

                # Convert rates to Decimal
                rates = {}
                for currency, rate in data["rates"].items():
                    try:
                        # API returns rate as 1 EUR = X currency
                        # We need rate as X currency = 1 EUR
                        rates[currency] = (Decimal("1") / Decimal(str(rate))).quantize(
                            Decimal("0.000001")
                        )
                    except (InvalidOperation, ValueError) as e:
                        logger.warning(
                            "fx_rate_conversion_failed",
                            currency=currency,
                            rate=rate,
                            error=str(e),
                        )
                        continue

                logger.info(
                    "fx_rates_fetched",
                    source="exchangerate-api.com",
                    currencies_count=len(rates),
                )

                return rates

            except httpx.HTTPError as e:
                logger.error("fx_api_http_error", url=url, error=str(e))
                raise
            except ValueError as e:
                logger.error("fx_api_invalid_response", url=url, error=str(e))
                raise

    def store_fetched_rates(
        self, rates: Dict[str, Decimal], source: str = "exchangerate-api.com"
    ) -> None:
        """
        Store fetched FX rates in the database.

        Args:
            rates: Dictionary mapping currency codes to EUR rates
            source: Source of the rates
        """
        timestamp = format_timestamp_utc()

        for currency, rate in rates.items():
            try:
                store_fx_rate(
                    currency=currency,
                    rate_to_eur=rate,
                    fetched_at_utc=timestamp,
                    source=source,
                )
            except Exception as e:
                logger.error(
                    "fx_rate_store_failed",
                    currency=currency,
                    rate=str(rate),
                    error=str(e),
                )

        logger.info("fx_rates_stored", source=source, count=len(rates), timestamp=timestamp)

    async def fetch_and_store_rates(self) -> bool:
        """
        Fetch rates from API and store them in database.

        Returns:
            True if successful, False otherwise
        """
        try:
            rates = await self.fetch_rates_from_exchangerate_api()
            self.store_fetched_rates(rates)
            return True
        except Exception as e:
            logger.error("fx_fetch_and_store_failed", error=str(e))
            return False


async def fetch_daily_fx_rates() -> bool:
    """
    Convenience function to fetch and store daily FX rates.

    Returns:
        True if successful, False otherwise
    """
    client = FXAPIClient()
    return await client.fetch_and_store_rates()


# Import Decimal for error handling
from decimal import InvalidOperation
