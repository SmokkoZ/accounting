"""
Workflow helper for approving Telegram funding drafts with notification auditing.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Optional

from src.repositories.notification_audit_repository import (
    NotificationAuditRepository,
)
from src.services.funding_service import FundingDraft, FundingService
from src.services.telegram_notifier import (
    TelegramNotificationError,
    TelegramNotificationResult,
    TelegramNotifier,
)
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class ApprovalOutcome:
    """Result of attempting to approve a funding draft."""

    ledger_id: int
    notification_attempted: bool = False
    notification_result: Optional[TelegramNotificationResult] = None


class TelegramApprovalWorkflow:
    """
    Coordinates FundingService acceptance with Telegram notifications and auditing.
    """

    def __init__(
        self,
        *,
        funding_service: Optional[FundingService] = None,
        notifier_factory: Optional[Callable[[], TelegramNotifier]] = None,
        audit_repository: Optional[NotificationAuditRepository] = None,
    ) -> None:
        self._funding_service = funding_service or FundingService()
        self._notifier_factory = notifier_factory or TelegramNotifier
        self._audit_repository = audit_repository or NotificationAuditRepository()
        self._owns_funding_service = funding_service is None
        self._owns_audit_repo = audit_repository is None

    def close(self) -> None:
        """Dispose owned resources."""
        if self._owns_funding_service:
            self._funding_service.close()
        if self._owns_audit_repo:
            self._audit_repository.close()

    def approve(
        self,
        *,
        draft: FundingDraft,
        notify_sender: bool,
        operator_id: str,
    ) -> ApprovalOutcome:
        """Approve a draft and optionally notify the originating chat."""
        ledger_id = self._funding_service.accept_funding_draft(
            draft.draft_id, created_by=operator_id
        )
        outcome = ApprovalOutcome(ledger_id=ledger_id)

        if notify_sender:
            result = self._attempt_notification(
                draft=draft,
                ledger_id=ledger_id,
                operator_id=operator_id,
            )
            outcome = ApprovalOutcome(
                ledger_id=ledger_id,
                notification_attempted=True,
                notification_result=result,
            )
        return outcome

    def _attempt_notification(
        self,
        *,
        draft: FundingDraft,
        ledger_id: int,
        operator_id: str,
    ) -> TelegramNotificationResult:
        """Send Telegram notification and persist an audit record."""
        chat_id = draft.chat_id
        if not chat_id:
            detail = "chat_id missing on draft"
            self._log_attempt(
                draft_id=draft.draft_id,
                chat_id=None,
                ledger_id=ledger_id,
                operator_id=operator_id,
                status="failed",
                detail=detail,
            )
            logger.warning(
                "telegram_notify_chat_missing",
                draft_id=draft.draft_id,
                ledger_id=ledger_id,
            )
            return TelegramNotificationResult(success=False, error_message=detail)

        try:
            notifier = self._notifier_factory()
        except TelegramNotificationError as exc:
            detail = str(exc)
            self._log_attempt(
                draft_id=draft.draft_id,
                chat_id=str(chat_id),
                ledger_id=ledger_id,
                operator_id=operator_id,
                status="failed",
                detail=detail,
            )
            logger.warning(
                "telegram_notify_not_configured",
                draft_id=draft.draft_id,
                chat_id=chat_id,
                error=detail,
            )
            return TelegramNotificationResult(success=False, error_message=detail)

        message = self._build_notification_message(draft, ledger_id)
        result = notifier.send_plaintext(str(chat_id), message)
        status = "sent" if result.success else "failed"
        self._log_attempt(
            draft_id=draft.draft_id,
            chat_id=str(chat_id),
            ledger_id=ledger_id,
            operator_id=operator_id,
            status=status,
            detail=result.error_message,
        )

        log_args = {
            "draft_id": draft.draft_id,
            "chat_id": chat_id,
            "ledger_id": ledger_id,
            "message_id": result.message_id,
        }
        if result.success:
            logger.info("telegram_draft_notification_sent", **log_args)
        else:
            logger.warning(
                "telegram_draft_notification_failed",
                error=result.error_message,
                **log_args,
            )
        return result

    @staticmethod
    def _build_notification_message(draft: FundingDraft, ledger_id: int) -> str:
        """Return a compact, human-readable message for Telegram."""
        amount = TelegramApprovalWorkflow._format_amount(draft.amount_native)
        return (
            f"✅ {draft.event_type.title()} of {amount} {draft.currency.upper()} "
            f"was approved and recorded. Ledger #{ledger_id}."
        )

    @staticmethod
    def _format_amount(value: Decimal) -> str:
        quantized = value.quantize(Decimal("0.01"))
        return f"{quantized.normalize():f}".rstrip("0").rstrip(".") or "0"

    def _log_attempt(
        self,
        *,
        draft_id: str,
        chat_id: Optional[str],
        ledger_id: int,
        operator_id: str,
        status: str,
        detail: Optional[str],
    ) -> None:
        """Persist the audit record for the notification attempt."""
        self._audit_repository.record_attempt(
            draft_id=draft_id,
            chat_id=chat_id,
            ledger_id=ledger_id,
            operator_id=operator_id,
            status=status,
            detail=detail,
        )


__all__ = [
    "ApprovalOutcome",
    "TelegramApprovalWorkflow",
]
