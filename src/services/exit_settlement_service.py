"""
Exit Settlement Service

Provides the application operation required by Story 11.2 to settle an associate
at a cutoff, write the balancing ledger entry, and emit a receipt artifact that
can be surfaced by the UI and CSV exports.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Optional

import structlog

from src.services.funding_transaction_service import (
    FundingTransaction,
    FundingTransactionError,
    FundingTransactionService,
)
from src.services import settlement_constants as _settlement_constants
from src.services.statement_service import StatementCalculations, StatementService
from src.utils.datetime_helpers import utc_now_iso

logger = structlog.get_logger()
DEFAULT_RECEIPT_ROOT = Path("data/exports/receipts")

SETTLEMENT_NOTE_PREFIX = getattr(
    _settlement_constants, "SETTLEMENT_NOTE_PREFIX", "Settle Associate Now"
)
SETTLEMENT_TOLERANCE = getattr(
    _settlement_constants, "SETTLEMENT_TOLERANCE", Decimal("0.01")
)
SETTLEMENT_MODEL_VERSION = getattr(
    _settlement_constants, "SETTLEMENT_MODEL_VERSION", "YF-v1"
)
SETTLEMENT_MODEL_FOOTNOTE = getattr(
    _settlement_constants,
    "SETTLEMENT_MODEL_FOOTNOTE",
    "Model: YF-v1 (YF = ND + FS; I'' = TB - YF). Values exclude operator fees/taxes.",
)


@dataclass
class SettlementReceipt:
    """Structured metadata for the generated receipt artifact."""

    associate_id: int
    associate_alias: str
    cutoff_utc: str
    entry_id: Optional[int]
    entry_type: Optional[str]
    amount_eur: Decimal
    imbalance_before_eur: Decimal
    imbalance_after_eur: Decimal
    exit_payout_after_eur: Decimal
    note: str
    generated_at: str
    version: str
    markdown: str
    file_path: Optional[Path]


@dataclass
class ExitSettlementResult:
    """Result payload returned by the ExitSettlementService."""

    entry_id: Optional[int]
    entry_type: Optional[str]
    amount_eur: Decimal
    delta_before: Decimal
    delta_after: Decimal
    note: str
    was_posted: bool
    updated_calculations: StatementCalculations
    receipt: SettlementReceipt


class ExitSettlementService:
    """Application service that executes Settle Associate Now."""

    def __init__(
        self,
        *,
        statement_service: Optional[StatementService] = None,
        receipt_root: Optional[Path] = None,
    ) -> None:
        self.statement_service = statement_service or StatementService()
        self.receipt_root = Path(receipt_root) if receipt_root else DEFAULT_RECEIPT_ROOT
        self.logger = logger.bind(service="exit_settlement_service")

    def settle_associate_now(
        self,
        associate_id: int,
        cutoff_date: str,
        *,
        calculations: Optional[StatementCalculations] = None,
        created_by: str = "system",
    ) -> ExitSettlementResult:
        """
        Execute the exit settlement flow for an associate at a cutoff.

        Args:
            associate_id: Target associate identifier.
            cutoff_date: ISO8601 cutoff timestamp (inclusive).
            calculations: Optional pre-computed statement snapshot.
            created_by: Operator identifier persisted on the ledger entry.
        """
        calc = calculations or self.statement_service.generate_statement(
            associate_id, cutoff_date
        )
        delta_before = self._quantize(calc.i_double_prime_eur)
        amount_eur = self._quantize(abs(delta_before))

        if amount_eur <= SETTLEMENT_TOLERANCE:
            note = "Associate already balanced - no ledger entry created."
            receipt = self._build_receipt(
                calc=calc,
                cutoff_date=cutoff_date,
                entry_id=None,
                entry_type=None,
                amount=Decimal("0.00"),
                delta_before=delta_before,
                delta_after=delta_before,
                note=note,
                was_posted=False,
            )
            return ExitSettlementResult(
                entry_id=None,
                entry_type=None,
                amount_eur=Decimal("0.00"),
                delta_before=delta_before,
                delta_after=delta_before,
                note=note,
                was_posted=False,
                updated_calculations=calc,
                receipt=receipt,
            )

        entry_type = "WITHDRAWAL" if delta_before > 0 else "DEPOSIT"
        settlement_note = f"{SETTLEMENT_NOTE_PREFIX} ({cutoff_date})"

        entry_id = self._post_transaction(
            associate_id=associate_id,
            entry_type=entry_type,
            amount_eur=amount_eur,
            created_by=created_by,
            note=settlement_note,
            cutoff_date=cutoff_date,
        )

        updated_calc = self.statement_service.generate_statement(associate_id, cutoff_date)
        delta_after = self._quantize(updated_calc.i_double_prime_eur)

        if abs(delta_after) > SETTLEMENT_TOLERANCE:
            raise RuntimeError(
                f"Exit settlement did not zero imbalance. Remaining delta: {delta_after}"
            )

        receipt = self._build_receipt(
            calc=updated_calc,
            cutoff_date=cutoff_date,
            entry_id=entry_id,
            entry_type=entry_type,
            amount=amount_eur,
            delta_before=delta_before,
            delta_after=delta_after,
            note=settlement_note,
            was_posted=True,
        )

        return ExitSettlementResult(
            entry_id=entry_id,
            entry_type=entry_type,
            amount_eur=amount_eur,
            delta_before=delta_before,
            delta_after=delta_after,
            note=settlement_note,
            was_posted=True,
            updated_calculations=updated_calc,
            receipt=receipt,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _post_transaction(
        self,
        *,
        associate_id: int,
        entry_type: str,
        amount_eur: Decimal,
        created_by: str,
        note: str,
        cutoff_date: str,
    ) -> int:
        funding_service = FundingTransactionService()
        try:
            transaction = FundingTransaction(
                associate_id=associate_id,
                bookmaker_id=None,
                transaction_type=entry_type,
                amount_native=amount_eur,
                native_currency="EUR",
                note=note,
                created_by=created_by,
            )
            entry_id = funding_service.record_transaction(
                transaction, created_at_override=cutoff_date
            )
            self.logger.info(
                "exit_settlement_posted",
                associate_id=associate_id,
                entry_id=entry_id,
                entry_type=entry_type,
                amount=str(amount_eur),
                cutoff=cutoff_date,
            )
            return int(entry_id)
        except (FundingTransactionError, ValueError) as exc:
            raise RuntimeError(f"Failed to post settlement entry: {exc}") from exc
        finally:
            funding_service.close()

    def _build_receipt(
        self,
        *,
        calc: StatementCalculations,
        cutoff_date: str,
        entry_id: Optional[int],
        entry_type: Optional[str],
        amount: Decimal,
        delta_before: Decimal,
        delta_after: Decimal,
        note: str,
        was_posted: bool,
    ) -> SettlementReceipt:
        generated_at = utc_now_iso()
        markdown = self._render_receipt_markdown(
            calc=calc,
            cutoff_date=cutoff_date,
            entry_id=entry_id,
            entry_type=entry_type,
            amount=amount,
            delta_before=delta_before,
            delta_after=delta_after,
            note=note,
            generated_at=generated_at,
            was_posted=was_posted,
        )
        file_path = self._persist_receipt(calc.associate_id, cutoff_date, markdown)

        return SettlementReceipt(
            associate_id=calc.associate_id,
            associate_alias=calc.associate_name,
            cutoff_utc=cutoff_date,
            entry_id=entry_id,
            entry_type=entry_type,
            amount_eur=self._quantize(amount),
            imbalance_before_eur=self._quantize(delta_before),
            imbalance_after_eur=self._quantize(delta_after),
            exit_payout_after_eur=self._quantize(calc.exit_payout_eur),
            note=note,
            generated_at=generated_at,
            version=SETTLEMENT_MODEL_VERSION,
            markdown=markdown,
            file_path=file_path,
        )

    def _render_receipt_markdown(
        self,
        *,
        calc: StatementCalculations,
        cutoff_date: str,
        entry_id: Optional[int],
        entry_type: Optional[str],
        amount: Decimal,
        delta_before: Decimal,
        delta_after: Decimal,
        note: str,
        generated_at: str,
        was_posted: bool,
    ) -> str:
        lines = [
            f"# Exit Settlement Receipt ({SETTLEMENT_MODEL_VERSION})",
            "",
            "| Field | Value |",
            "| --- | --- |",
            f"| Associate | {calc.associate_name} (ID {calc.associate_id}) |",
            f"| Cutoff (UTC) | {cutoff_date} |",
            f"| Operation Time | {generated_at} |",
            f"| Ledger Entry ID | {entry_id if entry_id is not None else '—'} |",
            f"| Entry Type | {entry_type or '—'} |",
            f"| Amount (EUR) | {self._quantize(amount):,.2f} |",
            f"| Imbalance Before I'' | {self._quantize(delta_before):,.2f} |",
            f"| Imbalance After I'' | {self._quantize(delta_after):,.2f} |",
            f"| Exit Payout (-I'') | {self._quantize(calc.exit_payout_eur):,.2f} |",
            f"| Note | {note} |",
            f"| Posted? | {'Yes' if was_posted else 'No'} |",
            "",
            f"> {SETTLEMENT_MODEL_FOOTNOTE}",
        ]
        return "\n".join(lines)

    def _persist_receipt(self, associate_id: int, cutoff_date: str, markdown: str) -> Optional[Path]:
        try:
            cutoff_dt = self._parse_cutoff(cutoff_date)
        except ValueError:
            cutoff_dt = datetime.now(timezone.utc)

        target_dir = self.receipt_root / str(associate_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{cutoff_dt.strftime('%Y%m%d')}_exit.md"
        target_path = target_dir / filename

        try:
            target_path.write_text(markdown, encoding="utf-8")
            return target_path
        except OSError as exc:
            self.logger.warning(
                "exit_receipt_write_failed",
                associate_id=associate_id,
                cutoff=cutoff_date,
                error=str(exc),
            )
            return None

    def _parse_cutoff(self, cutoff_date: str) -> datetime:
        if cutoff_date.endswith("Z"):
            cutoff_date = cutoff_date[:-1] + "+00:00"
        return datetime.fromisoformat(cutoff_date)

    @staticmethod
    def _quantize(value: Decimal) -> Decimal:
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
