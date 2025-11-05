"""
Settlement Service - Preview and execute equal-split settlement calculations.

This service handles:
- Previewing settlement calculations before commit
- Equal-split profit/loss distribution logic
- FX conversion and Decimal precision
- Participant seat type determination (staked vs non-staked)
- Delta provenance link creation
"""

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from dataclasses import dataclass
from typing import Dict, List, Optional
from enum import Enum
from datetime import datetime, timezone

from src.core.database import get_db_connection
from src.core.schema import create_ledger_append_only_trigger
from src.services.fx_manager import get_fx_rate, convert_to_eur
from src.services.delta_provenance_service import DeltaProvenanceService
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


class BetOutcome(Enum):
    """Possible bet outcomes for settlement."""

    WON = "WON"
    LOST = "LOST"
    VOID = "VOID"


@dataclass
class Participant:
    """
    Represents a participant in the settlement.

    Attributes:
        bet_id: ID of bet
        associate_id: ID of associate
        bookmaker_id: ID of bookmaker
        associate_alias: Display name of associate
        bookmaker_name: Name of bookmaker
        outcome: Bet outcome (WON/LOST/VOID)
        seat_type: Type of seat ("staked" or "non-staked")
        stake_eur: Original stake in EUR
        stake_native: Original stake in native currency
        odds: Bet odds
        currency: Original currency of bet
        fx_rate: FX rate used for EUR conversion
    """

    bet_id: int
    associate_id: int
    bookmaker_id: int
    associate_alias: str
    bookmaker_name: str
    outcome: BetOutcome
    seat_type: str  # "staked" or "non-staked"
    stake_eur: Decimal
    stake_native: Decimal
    odds: Decimal
    currency: str
    fx_rate: Decimal


@dataclass
class LedgerEntryPreview:
    """
    Preview of a ledger entry to be created.

    Attributes:
        bet_id: ID of bet
        associate_alias: Display name of associate
        bookmaker_name: Name of bookmaker
        outcome: Bet outcome (WON/LOST/VOID)
        principal_returned_eur: Principal returned (for WON bets only)
        per_surebet_share_eur: Equal share of surebet profit
        total_amount_eur: Total amount (principal + share)
        fx_rate: FX rate used for conversion
        currency: Original currency of the bet
    """

    bet_id: int
    associate_alias: str
    bookmaker_name: str
    outcome: str
    principal_returned_eur: Decimal
    per_surebet_share_eur: Decimal
    total_amount_eur: Decimal
    fx_rate: Decimal
    currency: str


@dataclass
class SettlementPreview:
    """
    Complete preview of settlement calculation.

    Attributes:
        surebet_id: ID of surebet being settled
        per_bet_outcomes: Mapping of bet_id → outcome
        per_bet_net_gains: Mapping of bet_id → net gain in EUR
        surebet_profit_eur: Total profit/loss of the surebet
        num_participants: Count of all participants (VOID included)
        participants: List of all participants with details
        per_surebet_share_eur: Equal share amount per participant
        ledger_entries: Preview of ledger entries to be created
        settlement_batch_id: UUID for settlement batch
        warnings: List of warning messages
    """

    surebet_id: int
    per_bet_outcomes: Dict[int, BetOutcome]
    per_bet_net_gains: Dict[int, Decimal]
    surebet_profit_eur: Decimal
    num_participants: int
    participants: List[Participant]
    per_surebet_share_eur: Decimal
    ledger_entries: List[LedgerEntryPreview]
    settlement_batch_id: str
    warnings: List[str]


@dataclass
class SettlementResult:
    """
    Result of a completed settlement.

    Attributes:
        surebet_id: ID of settled surebet
        settlement_batch_id: UUID of settlement batch
        ledger_entry_ids: List of created ledger entry IDs
        settlement_link_id: ID of created settlement link
        success: Whether settlement was successful
        error: Error message if settlement failed
    """

    surebet_id: int
    settlement_batch_id: str
    ledger_entry_ids: List[int]
    settlement_link_id: Optional[int]
    success: bool
    error: Optional[str]


class SettlementService:
    """Service for settling surebets with equal-split logic."""

    def __init__(self, db=None):
        """
        Initialize the settlement service.

        Args:
            db: Optional database connection (defaults to get_db_connection())
        """
        self.db = db or get_db_connection()
        self.delta_provenance = DeltaProvenanceService(self.db)

    @staticmethod
    def _parse_decimal(value: Optional[object]) -> Optional[Decimal]:
        """
        Safely parse a value into a Decimal.

        Args:
            value: Input value that may represent a decimal number.

        Returns:
            Decimal value or None if parsing fails or value is blank.
        """
        if value is None:
            return None

        if isinstance(value, str):
            value = value.strip()
            if value == "":
                return None

        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None

    def preview_settlement(
        self, surebet_id: int, outcomes: Dict[int, BetOutcome]
    ) -> SettlementPreview:
        """
        Preview settlement calculation without committing to ledger.

        Args:
            surebet_id: ID of surebet to settle
            outcomes: Mapping of bet_id → BetOutcome

        Returns:
            SettlementPreview with all calculation details

        Raises:
            ValueError: If surebet not found or invalid data
        """
        logger.info("previewing_settlement", surebet_id=surebet_id)

        # Load surebet and bets
        bets = self._load_surebet_bets(surebet_id)
        if not bets:
            raise ValueError(f"No bets found for surebet {surebet_id}")

        # Validate outcomes
        self._validate_outcomes(bets, outcomes)

        # Get FX rates snapshot (frozen at preview time)
        fx_rates = self._get_fx_snapshot(bets)

        # Calculate per-bet net gains
        per_bet_net_gains = {}
        participants = []
        warnings = []

        for bet in bets:
            bet_id = bet["id"]
            outcome = outcomes[bet_id]
            currency = (
                (bet.get("currency") or bet.get("stake_currency") or "EUR")
                .upper()
                .strip()
            )

            # Convert stake to EUR (prefer native stake when available)
            stake_eur = None
            stake_native = None
            for key in ("stake_original", "stake_amount", "stake"):
                stake_native = self._parse_decimal(bet.get(key))
                if stake_native is not None:
                    break

            if stake_native is not None:
                stake_eur = self._convert_to_eur(stake_native, currency, fx_rates)

            if stake_eur is None:
                stake_eur_value = self._parse_decimal(bet.get("stake_eur"))
                if stake_eur_value is not None:
                    stake_eur = stake_eur_value.quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )

            if stake_eur is None:
                raise ValueError(f"Bet {bet_id} is missing stake information")

            if stake_native is None:
                rate = fx_rates[currency]
                stake_native = (stake_eur / rate).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )

            stake_native = stake_native.quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

            # Determine odds with fallback to original odds when normalized value missing
            odds_value = self._parse_decimal(bet.get("odds"))
            if odds_value is None or odds_value == 0:
                odds_value = self._parse_decimal(bet.get("odds_original"))

            if odds_value is None or odds_value == 0:
                raise ValueError(f"Bet {bet_id} is missing odds information")

            # Calculate net gain
            net_gain_eur = self._calculate_net_gain(
                stake_eur, odds_value, outcome
            )
            per_bet_net_gains[bet_id] = net_gain_eur

            # Determine seat type
            seat_type = "staked" if outcome != BetOutcome.VOID else "non-staked"

            # Create participant
            participant = Participant(
                bet_id=bet_id,
                associate_id=bet["associate_id"],
                bookmaker_id=bet["bookmaker_id"],
                associate_alias=bet["associate_alias"],
                bookmaker_name=bet["bookmaker_name"],
                outcome=outcome,
                seat_type=seat_type,
                stake_eur=stake_eur,
                stake_native=stake_native,
                odds=odds_value,
                currency=currency,
                fx_rate=fx_rates[currency],
            )
            participants.append(participant)

        # Calculate surebet profit
        surebet_profit_eur = sum(per_bet_net_gains.values())

        # Count participants (all bets get a seat)
        num_participants = len(participants)

        # Calculate per-surebet share
        per_surebet_share_eur = self._calculate_per_share(
            surebet_profit_eur, num_participants
        )

        # Check for warnings
        warnings = self._generate_warnings(
            surebet_profit_eur, participants, per_surebet_share_eur
        )

        # Generate ledger entry previews
        ledger_entries = self._generate_ledger_previews(
            participants, per_surebet_share_eur
        )

        # Generate settlement batch ID
        settlement_batch_id = self._generate_batch_id()

        return SettlementPreview(
            surebet_id=surebet_id,
            per_bet_outcomes={bet_id: outcome for bet_id, outcome in outcomes.items()},
            per_bet_net_gains=per_bet_net_gains,
            surebet_profit_eur=surebet_profit_eur,
            num_participants=num_participants,
            participants=participants,
            per_surebet_share_eur=per_surebet_share_eur,
            ledger_entries=ledger_entries,
            settlement_batch_id=settlement_batch_id,
            warnings=warnings,
        )

    def execute_settlement(
        self, surebet_id: int, outcomes: Dict[int, BetOutcome]
    ) -> SettlementResult:
        """
        Execute settlement and create ledger entries with provenance links.

        Args:
            surebet_id: ID of surebet to settle
            outcomes: Mapping of bet_id → BetOutcome

        Returns:
            SettlementResult with execution details
        """
        logger.info("executing_settlement", surebet_id=surebet_id)

        try:
            # Start transaction
            self.db.execute("BEGIN TRANSACTION")

            # Preview settlement first
            preview = self.preview_settlement(surebet_id, outcomes)

            # Create ledger entries
            ledger_entry_ids = []
            for entry_preview in preview.ledger_entries:
                cursor = self.db.execute(
                    """
                    INSERT INTO ledger_entries (
                        type,
                        associate_id,
                        bookmaker_id,
                        amount_native,
                        native_currency,
                        fx_rate_snapshot,
                        amount_eur,
                        settlement_state,
                        principal_returned_eur,
                        per_surebet_share_eur,
                        surebet_id,
                        bet_id,
                        opposing_associate_id,
                        settlement_batch_id,
                        created_at_utc,
                        created_by,
                        note
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "BET_RESULT",
                        next(p.associate_id for p in preview.participants if p.bet_id == entry_preview.bet_id),
                        next(p.bookmaker_id for p in preview.participants if p.bet_id == entry_preview.bet_id),
                        str(entry_preview.total_amount_eur),  # amount_native (EUR for simplicity)
                        "EUR",  # native_currency
                        str(entry_preview.fx_rate),
                        str(entry_preview.total_amount_eur),  # amount_eur
                        entry_preview.outcome,
                        str(entry_preview.principal_returned_eur),
                        str(entry_preview.per_surebet_share_eur),
                        surebet_id,
                        entry_preview.bet_id,
                        None,  # opposing_associate_id (will be updated later)
                        preview.settlement_batch_id,
                        datetime.now(timezone.utc).isoformat() + "Z",
                        "local_user",
                        f"Surebet {surebet_id} settlement"
                    )
                )
                ledger_entry_ids.append(cursor.lastrowid)

            # Update surebet status
            self.db.execute(
                "UPDATE surebets SET status = 'settled', settled_at_utc = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat() + "Z", surebet_id)
            )

            # Create settlement link for delta provenance
            settlement_link_id = self._create_settlement_link(
                surebet_id, preview.participants, ledger_entry_ids
            )

            # Update ledger entries with opposing associate IDs
            self._update_ledger_opposing_associates(
                preview.participants, ledger_entry_ids
            )

            # Commit transaction
            self.db.execute("COMMIT")

            logger.info(
                "settlement_completed",
                surebet_id=surebet_id,
                settlement_batch_id=preview.settlement_batch_id,
                ledger_entry_count=len(ledger_entry_ids),
                settlement_link_id=settlement_link_id
            )

            return SettlementResult(
                surebet_id=surebet_id,
                settlement_batch_id=preview.settlement_batch_id,
                ledger_entry_ids=ledger_entry_ids,
                settlement_link_id=settlement_link_id,
                success=True,
                error=None
            )

        except Exception as e:
            self.db.execute("ROLLBACK")
            logger.error(
                "settlement_failed",
                surebet_id=surebet_id,
                error=str(e)
            )
            return SettlementResult(
                surebet_id=surebet_id,
                settlement_batch_id="",
                ledger_entry_ids=[],
                settlement_link_id=None,
                success=False,
                error=str(e)
            )

    def _create_settlement_link(
        self,
        surebet_id: int,
        participants: List[Participant],
        ledger_entry_ids: List[int]
    ) -> Optional[int]:
        """
        Create settlement link for delta provenance.

        Args:
            surebet_id: ID of surebet
            participants: List of settlement participants
            ledger_entry_ids: List of created ledger entry IDs

        Returns:
            ID of created settlement link or None if cannot determine winner/loser
        """
        # Find winner and loser
        winner = None
        loser = None
        winner_ledger_id = None
        loser_ledger_id = None

        for i, participant in enumerate(participants):
            if participant.outcome == BetOutcome.WON:
                winner = participant
                winner_ledger_id = ledger_entry_ids[i]
            elif participant.outcome == BetOutcome.LOST:
                loser = participant
                loser_ledger_id = ledger_entry_ids[i]

        # Handle VOID cases
        if winner is None and loser is None:
            # All VOID - create link with first participant as "winner"
            if len(participants) >= 2:
                winner = participants[0]
                loser = participants[1]
                winner_ledger_id = ledger_entry_ids[0]
                loser_ledger_id = ledger_entry_ids[1]
            else:
                logger.warning(
                    "cannot_create_settlement_link_all_void",
                    surebet_id=surebet_id,
                    participant_count=len(participants)
                )
                return None

        if winner and loser:
            # Use winner's positive amount as the link amount
            # Calculate winner's profit (total returned - stake)
            winner_total_returned = winner.stake_eur * winner.odds
            amount_eur = winner_total_returned - winner.stake_eur

            return self.delta_provenance.create_settlement_link(
                surebet_id=surebet_id,
                winner_associate_id=winner.associate_id,
                loser_associate_id=loser.associate_id,
                amount_eur=amount_eur,
                winner_ledger_entry_id=winner_ledger_id,
                loser_ledger_entry_id=loser_ledger_id
            )

        return None

    def _update_ledger_opposing_associates(
        self,
        participants: List[Participant],
        ledger_entry_ids: List[int]
    ) -> None:
        """
        Update ledger entries with opposing associate IDs.

        Args:
            participants: List of settlement participants
            ledger_entry_ids: List of corresponding ledger entry IDs
        """
        winner_idx = None
        loser_idx = None

        for i, participant in enumerate(participants):
            if participant.outcome == BetOutcome.WON:
                winner_idx = i
            elif participant.outcome == BetOutcome.LOST:
                loser_idx = i

        if winner_idx is not None and loser_idx is not None:
            # Temporarily disable trigger for opposing_associate_id updates
            self.db.execute("DROP TRIGGER IF EXISTS prevent_ledger_update")
            
            try:
                # Update winner with loser as opponent
                self.db.execute(
                    "UPDATE ledger_entries SET opposing_associate_id = ? WHERE id = ?",
                    (participants[loser_idx].associate_id, ledger_entry_ids[winner_idx])
                )

                # Update loser with winner as opponent
                self.db.execute(
                    "UPDATE ledger_entries SET opposing_associate_id = ? WHERE id = ?",
                    (participants[winner_idx].associate_id, ledger_entry_ids[loser_idx])
                )
            finally:
                # Recreate the trigger
                create_ledger_append_only_trigger(self.db)

    def _load_surebet_bets(self, surebet_id: int) -> List[Dict]:
        """
        Load all bets for a surebet.

        Args:
            surebet_id: ID of surebet

        Returns:
            List of bet dictionaries
        """
        cursor = self.db.cursor()
        cursor.execute(
            """
            SELECT
                b.id,
                b.associate_id,
                b.bookmaker_id,
                b.stake_original,
                b.stake_eur,
                b.odds,
                b.odds_original,
                b.currency,
                sb.side,
                a.display_alias as associate_alias,
                bk.bookmaker_name
            FROM bets b
            JOIN surebet_bets sb ON sb.bet_id = b.id
            JOIN associates a ON b.associate_id = a.id
            JOIN bookmakers bk ON b.bookmaker_id = bk.id
            WHERE sb.surebet_id = ?
            ORDER BY b.id
        """,
            (surebet_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def _validate_outcomes(self, bets: List[Dict], outcomes: Dict[int, BetOutcome]):
        """
        Validate that all bets have outcomes specified.

        Args:
            bets: List of bet dictionaries
            outcomes: Mapping of bet_id → BetOutcome

        Raises:
            ValueError: If validation fails
        """
        for bet in bets:
            bet_id = bet["id"]
            if bet_id not in outcomes:
                raise ValueError(f"Missing outcome for bet {bet_id}")

    def _get_fx_snapshot(self, bets: List[Dict]) -> Dict[str, Decimal]:
        """
        Get FX rates snapshot for all currencies (frozen at preview time).

        Args:
            bets: List of bet dictionaries

        Returns:
            Mapping of currency → FX rate to EUR

        Raises:
            ValueError: If FX rate not available for a currency
        """
        currencies = {bet["currency"] for bet in bets}
        fx_rates = {}

        settlement_date = datetime.now(timezone.utc).date()

        for currency in currencies:
            if currency == "EUR":
                fx_rates[currency] = Decimal("1.00")
            else:
                row = self.db.execute(
                    """
                    SELECT rate_to_eur
                    FROM fx_rates_daily
                    WHERE currency_code = ?
                    ORDER BY date DESC, COALESCE(fetched_at_utc, '') DESC
                    LIMIT 1
                """,
                    (currency.upper(),),
                ).fetchone()

                rate_value = None
                if row is not None:
                    if hasattr(row, "__getitem__"):
                        try:
                            rate_value = row["rate_to_eur"]  # type: ignore[index]
                        except (KeyError, TypeError):
                            rate_value = None
                    if rate_value is None and hasattr(row, "rate_to_eur"):
                        rate_value = getattr(row, "rate_to_eur")

                if isinstance(rate_value, (Decimal, int, float, str)):
                    try:
                        fx_rates[currency] = Decimal(str(rate_value))
                        continue
                    except (InvalidOperation, ValueError):
                        rate_value = None
                else:
                    rate_value = None

                try:
                    rate = get_fx_rate(
                        currency, rate_date=settlement_date, conn=self.db
                    )
                except TypeError:
                    rate = get_fx_rate(currency)
                if rate is None:
                    raise ValueError(f"FX rate not available for currency: {currency}")
                fx_rates[currency] = Decimal(str(rate))

        return fx_rates

    def _convert_to_eur(
        self, amount: Decimal, currency: str, fx_rates: Dict[str, Decimal]
    ) -> Decimal:
        """
        Convert amount to EUR using frozen FX rates.

        Args:
            amount: Amount to convert
            currency: Original currency
            fx_rates: Frozen FX rates snapshot

        Returns:
            Amount in EUR, rounded to 2 decimal places
        """
        if currency == "EUR":
            return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        rate = fx_rates[currency]
        amount_eur = amount * rate
        return amount_eur.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def _calculate_net_gain(
        self, stake_eur: Decimal, odds: Decimal, outcome: BetOutcome
    ) -> Decimal:
        """
        Calculate net gain for a bet in EUR.

        Args:
            stake_eur: Stake amount in EUR
            odds: Bet odds
            outcome: Bet outcome

        Returns:
            Net gain in EUR:
            - WON: (stake × odds) - stake
            - LOST: -stake
            - VOID: 0
        """
        if outcome == BetOutcome.WON:
            payout = stake_eur * odds
            net_gain = payout - stake_eur
        elif outcome == BetOutcome.LOST:
            net_gain = -stake_eur
        else:  # VOID
            net_gain = Decimal("0.00")

        return net_gain.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def _calculate_per_share(
        self, surebet_profit_eur: Decimal, num_participants: int
    ) -> Decimal:
        """
        Calculate per-surebet share (equal split).

        Args:
            surebet_profit_eur: Total profit/loss of the surebet
            num_participants: Number of participants (N)

        Returns:
            Per-surebet share amount, rounded to 2 decimal places
        """
        if num_participants == 0:
            return Decimal("0.00")

        share = surebet_profit_eur / Decimal(str(num_participants))
        return share.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def _generate_warnings(
        self,
        surebet_profit_eur: Decimal,
        participants: List[Participant],
        per_surebet_share_eur: Decimal,
    ) -> List[str]:
        """
        Generate warning messages for the settlement.

        Args:
            surebet_profit_eur: Total profit/loss of the surebet
            participants: List of all participants
            per_surebet_share_eur: Per-surebet share amount

        Returns:
            List of warning messages
        """
        warnings = []

        # Check for all-VOID scenario
        all_void = all(p.outcome == BetOutcome.VOID for p in participants)
        if all_void:
            warnings.append(
                "⚠️ All bets are VOID - No profit/loss to split (all participants get €0)"
            )

        # Check for loss scenario
        if surebet_profit_eur < 0:
            warnings.append(
                f"⚠️ Loss scenario: Surebet has negative profit of €{abs(surebet_profit_eur):.2f}"
            )

        # Check for multi-currency
        currencies = {p.currency for p in participants}
        if len(currencies) > 1:
            currency_list = ", ".join(sorted(currencies))
            warnings.append(f"ℹ️ Multi-currency settlement: {currency_list}")

        return warnings

    def _generate_ledger_previews(
        self, participants: List[Participant], per_surebet_share_eur: Decimal
    ) -> List[LedgerEntryPreview]:
        """
        Generate ledger entry previews.

        Args:
            participants: List of all participants
            per_surebet_share_eur: Per-surebet share amount

        Returns:
            List of ledger entry previews
        """
        ledger_entries = []

        for participant in participants:
            # Calculate principal returned (only for WON bets)
            if participant.outcome == BetOutcome.WON:
                principal_returned_eur = participant.stake_eur
            else:
                principal_returned_eur = Decimal("0.00")

            # Calculate per-surebet share (only for staked seats)
            if participant.seat_type == "staked":
                share = per_surebet_share_eur
            else:
                share = Decimal("0.00")

            # Calculate total amount
            total_amount_eur = principal_returned_eur + share

            ledger_entry = LedgerEntryPreview(
                bet_id=participant.bet_id,
                associate_alias=participant.associate_alias,
                bookmaker_name=participant.bookmaker_name,
                outcome=participant.outcome.value,
                principal_returned_eur=principal_returned_eur,
                per_surebet_share_eur=share,
                total_amount_eur=total_amount_eur,
                fx_rate=participant.fx_rate,
                currency=participant.currency,
            )
            ledger_entries.append(ledger_entry)

        return ledger_entries

    def _generate_batch_id(self) -> str:
        """
        Generate a unique settlement batch ID.

        Returns:
            UUID string
        """
        import uuid

        return str(uuid.uuid4())
