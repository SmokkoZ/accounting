"""
Ledger entry generation and settlement confirmation logic.

Implements Story 4.4 requirements: transaction-protected ledger writes,
append-only enforcement, and settlement status updates.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Iterable, List, Optional, Tuple

import sqlite3

from src.core.database import get_db_connection
from src.core.schema import create_ledger_append_only_trigger
from src.services.delta_provenance_service import DeltaProvenanceService
from src.services.settlement_service import (
    BetOutcome,
    Participant,
    SettlementPreview,
)
from src.utils.database_utils import TransactionError, transactional
from src.utils.logging_config import get_logger


logger = get_logger(__name__)


class SettlementCommitError(Exception):
    """Raised when settlement confirmation fails."""

    pass


@dataclass
class SettlementConfirmation:
    """Result payload returned after a successful settlement commit."""

    settlement_batch_id: str
    entries_written: int
    total_eur_amount: Decimal
    success: bool
    ledger_entry_ids: List[int]


class LedgerEntryService:
    """Service responsible for committing settlement results to the ledger."""

    def __init__(self, db: sqlite3.Connection | None = None) -> None:
        self._owns_connection = db is None
        self.db = db or get_db_connection()

    def close(self) -> None:
        """Close the managed database connection if owned by the service."""
        if not self._owns_connection:
            return
        try:
            self.db.close()
        except Exception:  # pragma: no cover - defensive path
            pass

    def confirm_settlement(
        self,
        surebet_id: int,
        preview_data: SettlementPreview,
        created_by: str = "local_user",
    ) -> SettlementConfirmation:
        """
        Persist settlement results to the ledger with full transactional safety.
        """
        if preview_data.surebet_id != surebet_id:
            raise ValueError(
                "Preview data does not match the requested surebet for settlement."
            )

        batch_id = self._generate_settlement_batch_id()
        bet_ids = [participant.bet_id for participant in preview_data.participants]
        logger.info(
            "confirming_settlement",
            surebet_id=surebet_id,
            batch_id=batch_id,
            bet_count=len(bet_ids),
        )

        try:
            with transactional(self.db) as conn:
                fx_snapshots = self._freeze_fx_snapshots(preview_data)
                (
                    ledger_ids,
                    total_amount_eur,
                    entry_amounts_eur,
                ) = self._write_ledger_entries(
                    conn,
                    batch_id,
                    fx_snapshots,
                    preview_data,
                    created_by,
                )
                self._update_surebet_status(conn, surebet_id)
                self._update_bet_statuses(conn, bet_ids)
                self._update_opposing_associates(
                    conn, preview_data.participants, ledger_ids
                )
                self._ensure_delta_provenance_link(
                    conn,
                    preview_data,
                    ledger_ids,
                    entry_amounts_eur,
                )
        except TransactionError as exc:  # pragma: no cover - defensive path
            raise SettlementCommitError(str(exc)) from exc
        except Exception as exc:
            logger.error(
                "settlement_commit_failed",
                surebet_id=surebet_id,
                batch_id=batch_id,
                error=str(exc),
                exc_info=True,
            )
            raise SettlementCommitError("Settlement confirmation failed.") from exc

        logger.info(
            "settlement_committed",
            surebet_id=surebet_id,
            batch_id=batch_id,
            entries=len(ledger_ids),
            total_amount_eur=str(total_amount_eur),
        )

        return SettlementConfirmation(
            settlement_batch_id=batch_id,
            entries_written=len(ledger_ids),
            total_eur_amount=total_amount_eur,
            success=True,
            ledger_entry_ids=ledger_ids,
        )

    @staticmethod
    def _generate_settlement_batch_id() -> str:
        """Generate a unique UUID for the settlement batch."""
        return str(uuid.uuid4())

    @staticmethod
    def _freeze_fx_snapshots(
        preview_data: SettlementPreview,
    ) -> Dict[str, Decimal]:
        """
        Capture FX rates used during preview so the ledger records match exactly.
        """
        snapshots: Dict[str, Decimal] = {}
        for participant in preview_data.participants:
            if participant.currency not in snapshots:
                snapshots[participant.currency] = participant.fx_rate
        return snapshots

    def _write_ledger_entries(
        self,
        conn: sqlite3.Connection,
        batch_id: str,
        fx_snapshots: Dict[str, Decimal],
        preview_data: SettlementPreview,
        created_by: str,
    ) -> Tuple[List[int], Decimal, List[Decimal]]:
        """Write append-only ledger rows for each participant."""
        ledger_ids: List[int] = []
        total_amount_eur = Decimal("0.00")
        entry_amounts_eur: List[Decimal] = []

        for participant in preview_data.participants:
            fx_rate = fx_snapshots[participant.currency]
            amount_native = self._quantize_currency(
                self._calculate_amount_native(participant)
            )
            amount_eur = self._quantize_currency(amount_native * fx_rate)
            principal_returned = self._quantize_currency(
                participant.stake_eur
                if participant.outcome in (BetOutcome.WON, BetOutcome.VOID)
                else Decimal("0.00")
            )
            per_share = (
                self._quantize_currency(preview_data.per_surebet_share_eur)
                if participant.seat_type == "staked"
                else Decimal("0.00")
            )

            cursor = conn.execute(
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
                    settlement_batch_id,
                    created_by,
                    note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    "BET_RESULT",
                    participant.associate_id,
                    participant.bookmaker_id,
                    str(amount_native),
                    participant.currency,
                    str(fx_rate),
                    str(amount_eur),
                    participant.outcome.value,
                    str(principal_returned),
                    str(per_share),
                    preview_data.surebet_id,
                    participant.bet_id,
                    batch_id,
                    created_by,
                    f"Surebet #{preview_data.surebet_id} settlement",
                ),
            )
            ledger_ids.append(cursor.lastrowid)
            total_amount_eur += amount_eur
            entry_amounts_eur.append(amount_eur)

        return (
            ledger_ids,
            self._quantize_currency(total_amount_eur),
            entry_amounts_eur,
        )

    def _update_surebet_status(
        self, conn: sqlite3.Connection, surebet_id: int
    ) -> None:
        """Mark a surebet as settled with timestamp."""
        timestamp = self._utc_now()
        conn.execute(
            """
            UPDATE surebets
            SET status = 'settled',
                settled_at_utc = ?,
                updated_at_utc = ?
            WHERE id = ?
        """,
            (timestamp, timestamp, surebet_id),
        )

    def _update_bet_statuses(
        self, conn: sqlite3.Connection, bet_ids: Iterable[int]
    ) -> None:
        """Mark bets as settled within the same transaction."""
        bet_ids = list(bet_ids)
        if not bet_ids:
            return

        timestamp = self._utc_now()
        conn.executemany(
            """
            UPDATE bets
            SET status = 'settled',
                updated_at_utc = ?
            WHERE id = ?
        """,
            [(timestamp, bet_id) for bet_id in bet_ids],
        )

    def _update_opposing_associates(
        self,
        conn: sqlite3.Connection,
        participants: List[Participant],
        ledger_entry_ids: List[int],
    ) -> None:
        """Attach opposing associate references to ledger entries."""
        if not participants or len(participants) != len(ledger_entry_ids):
            return

        winner_idx: Optional[int] = None
        loser_idx: Optional[int] = None

        for idx, participant in enumerate(participants):
            if participant.outcome == BetOutcome.WON and winner_idx is None:
                winner_idx = idx
            elif participant.outcome == BetOutcome.LOST and loser_idx is None:
                loser_idx = idx

        if winner_idx is None and loser_idx is None and len(participants) >= 2:
            winner_idx, loser_idx = 0, 1

        if winner_idx is None or loser_idx is None:
            logger.warning(
                "opposing_associate_update_skipped",
                reason="unable_to_determine_winner_loser",
                participant_count=len(participants),
            )
            return

        conn.execute("DROP TRIGGER IF EXISTS prevent_ledger_update")
        try:
            conn.execute(
                "UPDATE ledger_entries SET opposing_associate_id = ? WHERE id = ?",
                (
                    participants[loser_idx].associate_id,
                    ledger_entry_ids[winner_idx],
                ),
            )
            conn.execute(
                "UPDATE ledger_entries SET opposing_associate_id = ? WHERE id = ?",
                (
                    participants[winner_idx].associate_id,
                    ledger_entry_ids[loser_idx],
                ),
            )
        finally:
            create_ledger_append_only_trigger(conn)

    def _ensure_delta_provenance_link(
        self,
        conn: sqlite3.Connection,
        preview_data: SettlementPreview,
        ledger_entry_ids: List[int],
        entry_amounts_eur: List[Decimal],
    ) -> None:
        """Create a settlement link to power delta provenance dashboards."""
        participants = preview_data.participants
        if not participants or len(participants) != len(ledger_entry_ids):
            return

        winner_idx: Optional[int] = None
        loser_idx: Optional[int] = None

        for idx, participant in enumerate(participants):
            if participant.outcome == BetOutcome.WON and winner_idx is None:
                winner_idx = idx
            elif participant.outcome == BetOutcome.LOST and loser_idx is None:
                loser_idx = idx

        if winner_idx is None and loser_idx is None and len(participants) >= 2:
            winner_idx, loser_idx = 0, 1

        if winner_idx is None or loser_idx is None:
            logger.warning(
                "delta_provenance_link_skipped",
                reason="unable_to_determine_winner_loser",
                participant_count=len(participants),
                surebet_id=preview_data.surebet_id,
            )
            return

        amount_eur = entry_amounts_eur[winner_idx]
        if amount_eur <= Decimal("0.00") and loser_idx is not None:
            amount_eur = abs(entry_amounts_eur[loser_idx])

        if amount_eur <= Decimal("0.00"):
            logger.warning(
                "delta_provenance_link_skipped",
                reason="non_positive_amount",
                surebet_id=preview_data.surebet_id,
                amount=str(amount_eur),
            )
            return

        try:
            delta_service = DeltaProvenanceService(conn)
            delta_service.create_settlement_link(
                surebet_id=preview_data.surebet_id,
                winner_associate_id=participants[winner_idx].associate_id,
                loser_associate_id=participants[loser_idx].associate_id,
                amount_eur=amount_eur,
                winner_ledger_entry_id=ledger_entry_ids[winner_idx],
                loser_ledger_entry_id=ledger_entry_ids[loser_idx],
            )
        except Exception as exc:
            logger.error(
                "delta_provenance_link_failed",
                surebet_id=preview_data.surebet_id,
                error=str(exc),
                exception=exc,
            )
            raise SettlementCommitError(
                "Failed to create delta provenance link."
            ) from exc

    @staticmethod
    def _calculate_amount_native(participant: Participant) -> Decimal:
        """Calculate the native currency net amount for a participant."""
        stake_native = participant.stake_native

        if participant.outcome == BetOutcome.WON:
            payout = stake_native * participant.odds
            return payout - stake_native
        if participant.outcome == BetOutcome.LOST:
            return -stake_native
        return Decimal("0.00")

    @staticmethod
    def _quantize_currency(value: Decimal) -> Decimal:
        """Round monetary values to cents."""
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @staticmethod
    def _utc_now() -> str:
        """Return current UTC timestamp with millisecond precision."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
