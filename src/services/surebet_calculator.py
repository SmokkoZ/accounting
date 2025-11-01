"""
Surebet risk calculation service for worst-case EUR profit analysis.

This module handles the calculation of worst-case profit and ROI for surebets:
- EUR conversion using cached FX rates
- Profit scenarios for Side A wins vs Side B wins
- Risk classification (Safe/Low ROI/Unsafe)
"""

import sqlite3
import structlog
from datetime import date
from decimal import Decimal
from typing import Dict, Any, List, Tuple, Optional

from src.services.fx_manager import convert_to_eur

logger = structlog.get_logger()


# Risk classification thresholds (configurable)
SAFE_ROI_THRESHOLD = Decimal("1.0")  # 1.0% minimum ROI for safe classification


class SurebetRiskCalculator:
    """Service for calculating worst-case profit and ROI for surebets."""

    def __init__(self, db: sqlite3.Connection):
        """Initialize the surebet risk calculator service.

        Args:
            db: SQLite database connection
        """
        self.db = db
        self.db.row_factory = sqlite3.Row

    def calculate_surebet_risk(self, surebet_id: int) -> Dict[str, Any]:
        """
        Calculate worst-case profit and ROI for a surebet.

        This method:
        1. Query all bets linked to surebet via surebet_bets
        2. Convert all stakes/payouts to EUR using cached FX rates
        3. Calculate profit scenarios for Side A wins vs Side B wins
        4. Determine worst-case profit (minimum of both scenarios)
        5. Calculate ROI percentage
        6. Classify risk level (Safe/Low ROI/Unsafe)
        7. Return comprehensive risk analysis dict

        Args:
            surebet_id: ID of the surebet to analyze

        Returns:
            Dictionary containing:
                - worst_case_profit_eur: Decimal (minimum profit across scenarios)
                - total_staked_eur: Decimal (total amount staked)
                - roi: Decimal (return on investment as percentage)
                - risk_classification: str (Safe/Low ROI/Unsafe)
                - profit_if_a_wins: Decimal (profit if Side A wins)
                - profit_if_b_wins: Decimal (profit if Side B wins)
                - side_a_count: int (number of Side A bets)
                - side_b_count: int (number of Side B bets)
                - color_code: str (emoji for UI display)

        Raises:
            ValueError: If surebet not found or has no linked bets
        """
        # Load surebet to validate it exists
        surebet = self._load_surebet(surebet_id)
        if not surebet:
            raise ValueError(f"Surebet {surebet_id} not found")

        # Query all bets linked to this surebet
        bets_with_sides = self._load_surebet_bets(surebet_id)

        if not bets_with_sides:
            raise ValueError(f"Surebet {surebet_id} has no linked bets")

        # Separate bets by surebet side
        side_a_bets = [b for b in bets_with_sides if b["surebet_side"] == "A"]
        side_b_bets = [b for b in bets_with_sides if b["surebet_side"] == "B"]

        # Convert all stakes and payouts to EUR
        side_a_eur = self._convert_bets_to_eur(side_a_bets)
        side_b_eur = self._convert_bets_to_eur(side_b_bets)

        # Calculate profit scenarios
        profit_if_a_wins, profit_if_b_wins = self._calculate_profit_scenarios(
            side_a_eur, side_b_eur
        )

        # Calculate worst-case profit and total staked
        worst_case_profit_eur = min(profit_if_a_wins, profit_if_b_wins)
        total_staked_eur = sum(b["stake_eur"] for b in side_a_eur + side_b_eur)

        # Calculate ROI percentage (avoid division by zero)
        if total_staked_eur > Decimal("0"):
            roi = (worst_case_profit_eur / total_staked_eur) * Decimal("100")
        else:
            roi = Decimal("0")

        # Classify risk
        risk_data = self._classify_risk(worst_case_profit_eur, roi)

        # Return comprehensive risk analysis
        return {
            "worst_case_profit_eur": worst_case_profit_eur,
            "total_staked_eur": total_staked_eur,
            "roi": roi,
            "risk_classification": risk_data["classification"],
            "color_code": risk_data["color_code"],
            "profit_if_a_wins": profit_if_a_wins,
            "profit_if_b_wins": profit_if_b_wins,
            "side_a_count": len(side_a_bets),
            "side_b_count": len(side_b_bets),
        }

    def _get_fx_rate(self, currency: str, conversion_date: date) -> Decimal:
        """
        Get FX rate for a currency on a specific date.

        Args:
            currency: ISO currency code
            conversion_date: Date for FX rate lookup

        Returns:
            Decimal representing the rate to EUR

        Raises:
            ValueError: If no FX rate available for currency
        """
        if currency.upper() == "EUR":
            return Decimal("1.0")

        # Try to get rate for the specific date
        cursor = self.db.execute(
            """
            SELECT rate_to_eur FROM fx_rates_daily
            WHERE currency_code = ? AND date = ?
            ORDER BY date DESC, fetched_at_utc DESC
            LIMIT 1
            """,
            (currency.upper(), conversion_date.strftime("%Y-%m-%d")),
        )

        row = cursor.fetchone()
        if row:
            return Decimal(row["rate_to_eur"])

        # Fallback to most recent rate
        cursor = self.db.execute(
            """
            SELECT rate_to_eur, date FROM fx_rates_daily
            WHERE currency_code = ?
            ORDER BY date DESC, fetched_at_utc DESC
            LIMIT 1
            """,
            (currency.upper(),),
        )

        row = cursor.fetchone()
        if row:
            logger.warning(
                "fx_rate_fallback_used",
                currency=currency,
                requested_date=conversion_date.strftime("%Y-%m-%d"),
                used_date=row["date"],
            )
            return Decimal(row["rate_to_eur"])

        raise ValueError(f"No FX rate found for currency: {currency}")

    def _convert_to_eur(
        self, amount: Decimal, currency: str, conversion_date: date
    ) -> Decimal:
        """
        Convert amount to EUR using FX rate with fallback handling.

        Args:
            amount: Amount in native currency
            currency: ISO currency code
            conversion_date: Date for FX rate lookup

        Returns:
            Amount converted to EUR as Decimal

        Raises:
            ValueError: If no FX rate available for currency (even fallback)
        """
        try:
            fx_rate = self._get_fx_rate(currency, conversion_date)
            return convert_to_eur(amount, currency, fx_rate)
        except ValueError as e:
            logger.error(
                "fx_rate_missing",
                currency=currency,
                date=conversion_date.isoformat(),
                error=str(e),
            )
            raise

    def _convert_bets_to_eur(self, bets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Convert all bet stakes and payouts to EUR.

        Args:
            bets: List of bet dictionaries with currency, stake, payout

        Returns:
            List of bet dictionaries with added stake_eur and payout_eur fields
        """
        converted_bets = []

        for bet in bets:
            currency = bet.get("currency", "EUR")

            # Use stake in original currency or fallback to EUR stake
            if bet.get("stake_original"):
                stake_native = Decimal(bet["stake_original"])
            else:
                # If no original stake, assume stake_eur is the native currency
                stake_native = Decimal(bet["stake_eur"])

            # Calculate payout in native currency
            if bet.get("payout"):
                payout_native = Decimal(bet["payout"])
            else:
                # payout = stake * odds (in native currency)
                odds = Decimal(bet.get("odds_original") or bet["odds"])
                payout_native = stake_native * odds

            # For EUR, no conversion needed
            if currency == "EUR":
                stake_eur = stake_native
                payout_eur = payout_native
            else:
                # Convert to EUR using today's FX rate
                today = date.today()
                stake_eur = self._convert_to_eur(stake_native, currency, today)
                payout_eur = self._convert_to_eur(payout_native, currency, today)

            converted_bets.append(
                {
                    **bet,
                    "stake_eur": stake_eur,
                    "payout_eur": payout_eur,
                }
            )

        return converted_bets

    def _calculate_profit_scenarios(
        self, side_a_bets: List[Dict[str, Any]], side_b_bets: List[Dict[str, Any]]
    ) -> Tuple[Decimal, Decimal]:
        """
        Calculate profit for both Side A wins and Side B wins scenarios.

        Profit calculation:
        - If Side A wins: (sum of Side A payouts) - (sum of ALL stakes)
        - If Side B wins: (sum of Side B payouts) - (sum of ALL stakes)

        Args:
            side_a_bets: List of Side A bets with stake_eur and payout_eur
            side_b_bets: List of Side B bets with stake_eur and payout_eur

        Returns:
            Tuple of (profit_if_a_wins, profit_if_b_wins)
        """
        # Calculate total stakes from both sides
        total_stakes = sum(b["stake_eur"] for b in side_a_bets + side_b_bets)

        # Calculate Side A wins scenario
        side_a_payouts = sum(b["payout_eur"] for b in side_a_bets)
        profit_if_a_wins = side_a_payouts - total_stakes

        # Calculate Side B wins scenario
        side_b_payouts = sum(b["payout_eur"] for b in side_b_bets)
        profit_if_b_wins = side_b_payouts - total_stakes

        return profit_if_a_wins, profit_if_b_wins

    def _classify_risk(self, worst_profit: Decimal, roi: Decimal) -> Dict[str, str]:
        """
        Classify surebet risk based on profit and ROI thresholds.

        Classification rules:
        - Safe (✅): worst_case_profit_eur >= 0 AND roi >= 1.0%
        - Low ROI (🟡): worst_case_profit_eur >= 0 BUT roi < 1.0%
        - Unsafe (❌): worst_case_profit_eur < 0 (guaranteed loss)

        Args:
            worst_profit: Worst-case profit in EUR
            roi: ROI as percentage

        Returns:
            Dictionary with 'classification' and 'color_code' keys
        """
        if worst_profit < Decimal("0"):
            return {
                "classification": "Unsafe",
                "color_code": "❌",
            }
        elif roi >= SAFE_ROI_THRESHOLD:
            return {
                "classification": "Safe",
                "color_code": "✅",
            }
        else:
            return {
                "classification": "Low ROI",
                "color_code": "🟡",
            }

    def _load_surebet(self, surebet_id: int) -> Optional[Dict[str, Any]]:
        """Load surebet by ID.

        Args:
            surebet_id: Surebet ID

        Returns:
            Surebet dictionary or None if not found
        """
        cursor = self.db.execute("SELECT * FROM surebets WHERE id = ?", (surebet_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def _load_surebet_bets(self, surebet_id: int) -> List[Dict[str, Any]]:
        """Load all bets linked to a surebet with side assignments.

        Args:
            surebet_id: Surebet ID

        Returns:
            List of bet dictionaries with 'surebet_side' field from surebet_bets junction
        """
        cursor = self.db.execute(
            """
            SELECT
                b.*,
                sb.side as surebet_side
            FROM bets b
            JOIN surebet_bets sb ON b.id = sb.bet_id
            WHERE sb.surebet_id = ?
            """,
            (surebet_id,),
        )
        return [dict(row) for row in cursor.fetchall()]
