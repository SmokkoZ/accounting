"""
Associate Operations Hub (Story 5.5)

Unified operations workspace for reviewing associates, their bookmakers, balances,
and funding transactions. Modern Streamlit primitives (fragments, status blocks)
are used when available to improve responsiveness without breaking compatibility
with older runtimes.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import streamlit as st
from streamlit.errors import StreamlitAPIException

from src.repositories.associate_hub_repository import AssociateHubRepository
from src.services.bookmaker_balance_service import BookmakerBalanceService
from src.services.funding_transaction_service import FundingTransactionService
from src.services.funding_service import FundingDraft, FundingError, FundingService
from src.services.telegram_approval_workflow import TelegramApprovalWorkflow
from src.ui.components.associate_hub import (
    render_associate_listing,
    render_detail_drawer,
    render_filters,
    render_hub_dashboard,
    render_pagination_info,
    render_empty_state,
)
from src.ui.helpers.dialogs import open_dialog, render_confirmation_dialog
from src.ui.helpers.fragments import fragment
from src.ui.helpers.streaming import status_with_steps
from src.ui.ui_components import load_global_styles
from src.ui.utils.formatters import (
    format_currency_amount,
    format_utc_datetime_compact,
)
from src.ui.utils.state_management import safe_rerun
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

load_global_styles()

PAGE_TITLE = "Associate Operations Hub"
PAGE_ICON = ":material/groups_3:"

def _configure_page() -> None:
    """Set page config when allowed (ignored if already configured)."""
    try:
        st.set_page_config(
            page_title=PAGE_TITLE,
            page_icon=PAGE_ICON,
            layout="wide",
            initial_sidebar_state="expanded",
        )
    except StreamlitAPIException:
        # Main app already configured the shell.
        pass


_configure_page()

st.title(f"{PAGE_ICON} {PAGE_TITLE}")
st.markdown(
    "Manage associates, bookmakers, balances, and funding movements in one place. "
    "Filters persist across refreshes for fast back-to-back operations."
)

TELEGRAM_ALERTS_KEY = "telegram_panel_alerts"
TELEGRAM_ACCEPT_DIALOG_PREFIX = "telegram_accept_draft"
TELEGRAM_REJECT_DIALOG_PREFIX = "telegram_reject_draft"
TELEGRAM_NOTIFY_PREFIX = "telegram_notify_sender"


def _resolve_operator_identity() -> str:
    """Return the best operator identifier available for created_by."""
    candidate_keys = (
        "operator_name",
        "operator_email",
        "user_email",
        "user_display_name",
    )
    for key in candidate_keys:
        value = st.session_state.get(key)
        if value:
            return str(value)
    return "local_user"


def _push_telegram_panel_alert(level: str, message: str) -> None:
    """Persist toast-style feedback so it survives reruns."""
    queue: List[Tuple[str, str]] = st.session_state.setdefault(TELEGRAM_ALERTS_KEY, [])
    queue.append((level, message))


def _render_pending_telegram_panel() -> None:
    """Render the Pending Funding (Telegram) approvals panel."""
    st.markdown("### :material/smart_toy: Pending Funding (Telegram)")
    st.caption(
        "Review deposit/withdrawal drafts that originated from Telegram chats before they hit the ledger."
    )

    for level, message in st.session_state.pop(TELEGRAM_ALERTS_KEY, []):
        if level == "success":
            st.success(message, icon=":material/check_circle:")
        elif level == "warning":
            st.warning(message, icon=":material/warning:")
        elif level == "error":
            st.error(message, icon=":material/error:")
        else:
            st.info(message, icon=":material/info:")

    service = FundingService()
    try:
        drafts = service.get_pending_drafts(source="telegram")
    except FundingError as exc:
        st.error(f"Failed to load Telegram drafts: {exc}")
        logger.error("telegram_drafts_load_failed", error=str(exc), exc_info=True)
        return
    except Exception as exc:  # pragma: no cover - defensive path
        st.error("Unexpected error while loading Telegram drafts.")
        logger.error("telegram_drafts_load_unexpected", error=str(exc), exc_info=True)
        return
    finally:
        service.close()

    if not drafts:
        st.info("No Telegram funding drafts awaiting approval right now.")
        return

    for draft in drafts:
        _render_telegram_draft_card(draft)


def _render_telegram_draft_card(draft: FundingDraft) -> None:
    """Render a single Telegram draft entry with actions."""
    with st.container():
        header_cols = st.columns([2, 1, 1])

        with header_cols[0]:
            st.markdown(f"**{draft.associate_alias}** @ {draft.bookmaker_name}")
            amount_display = format_currency_amount(draft.amount_native, draft.currency)
            st.caption(f"{draft.event_type} · {amount_display}")

        with header_cols[1]:
            st.caption("Created At")
            st.write(format_utc_datetime_compact(draft.created_at_utc))

        with header_cols[2]:
            st.caption("Source")
            st.markdown(
                "<span style='background-color:#155bcb;color:white;padding:2px 8px;border-radius:4px;font-size:0.8rem;'>telegram</span>",
                unsafe_allow_html=True,
            )
            if draft.chat_id:
                st.caption("Chat ID")
                st.code(str(draft.chat_id), language="")
            else:
                st.caption("Chat ID unavailable")

        if draft.note:
            st.caption(f":material/sticky_note_2: {draft.note}")

        _render_telegram_draft_actions(draft)


def _render_telegram_draft_actions(draft: FundingDraft) -> None:
    """Render Notify/Accept/Reject controls for a Telegram draft."""
    action_cols = st.columns([2, 1, 1])
    notify_key = f"{TELEGRAM_NOTIFY_PREFIX}_{draft.draft_id}"
    if notify_key not in st.session_state:
        st.session_state[notify_key] = False

    with action_cols[0]:
        notify_help = (
            "Send a Telegram confirmation back to the originating chat."
            if draft.chat_id
            else "Chat ID missing on this draft; notification unavailable."
        )
        st.checkbox(
            "Notify sender",
            key=notify_key,
            disabled=not draft.chat_id,
            help=notify_help,
        )

    accept_dialog_key = f"{TELEGRAM_ACCEPT_DIALOG_PREFIX}_{draft.draft_id}"
    accept_payload_key = f"{accept_dialog_key}__payload"
    with action_cols[1]:
        if st.button(
            ":material/check: Accept",
            key=f"telegram_accept_btn_{draft.draft_id}",
            type="primary",
            use_container_width=True,
            help="Create a ledger entry and remove the draft.",
        ):
            st.session_state[accept_payload_key] = {
                "draft": draft,
                "notify": bool(st.session_state.get(notify_key, False)),
            }
            open_dialog(accept_dialog_key)

    pending_accept = st.session_state.get(accept_payload_key)
    if pending_accept:
        payload_draft: FundingDraft = pending_accept["draft"]
        decision = render_confirmation_dialog(
            key=accept_dialog_key,
            title="Approve Telegram Funding Draft",
            body=(
                f"Accept {payload_draft.event_type} of "
                f"{format_currency_amount(payload_draft.amount_native, payload_draft.currency)} "
                f"for {payload_draft.associate_alias} @ {payload_draft.bookmaker_name}? "
                "This will post a ledger entry with the bookmaker scope."
            ),
            confirm_label="Accept",
            confirm_type="primary",
        )
        if decision is True:
            _process_telegram_acceptance(
                draft=payload_draft,
                notify_sender=bool(pending_accept.get("notify")),
            )
            st.session_state.pop(accept_payload_key, None)
        elif decision is False:
            st.session_state.pop(accept_payload_key, None)

    reject_dialog_key = f"{TELEGRAM_REJECT_DIALOG_PREFIX}_{draft.draft_id}"
    reject_payload_key = f"{reject_dialog_key}__payload"
    with action_cols[2]:
        if st.button(
            ":material/close: Reject",
            key=f"telegram_reject_btn_{draft.draft_id}",
            type="secondary",
            use_container_width=True,
            help="Discard draft without touching the ledger.",
        ):
            st.session_state[reject_payload_key] = {"draft": draft}
            open_dialog(reject_dialog_key)

    pending_reject = st.session_state.get(reject_payload_key)
    if pending_reject:
        payload_draft: FundingDraft = pending_reject["draft"]
        decision = render_confirmation_dialog(
            key=reject_dialog_key,
            title="Reject Telegram Draft",
            body=(
                f"Reject {payload_draft.event_type} draft for "
                f"{payload_draft.associate_alias} @ {payload_draft.bookmaker_name}? "
                "The draft will be removed with no ledger entry."
            ),
            confirm_label="Reject",
            confirm_type="secondary",
        )
        if decision is True:
            _process_telegram_rejection(payload_draft)
            st.session_state.pop(reject_payload_key, None)
        elif decision is False:
            st.session_state.pop(reject_payload_key, None)


def _process_telegram_acceptance(*, draft: FundingDraft, notify_sender: bool) -> None:
    """Accept a Telegram draft, optionally notifying the originating chat."""
    created_by = _resolve_operator_identity()
    workflow = TelegramApprovalWorkflow()
    try:
        outcome = workflow.approve(
            draft=draft,
            notify_sender=notify_sender,
            operator_id=created_by,
        )
    except FundingError as exc:
        st.error(f"Failed to accept draft: {exc}")
        logger.error(
            "telegram_draft_accept_failed",
            draft_id=draft.draft_id,
            error=str(exc),
            exc_info=True,
        )
        return
    except Exception as exc:  # pragma: no cover - defensive path
        st.error("Unexpected error while accepting the draft.")
        logger.error(
            "telegram_draft_accept_unexpected",
            draft_id=draft.draft_id,
            error=str(exc),
            exc_info=True,
        )
        return
    finally:
        workflow.close()

    logger.info(
        "telegram_draft_accepted_via_ui",
        draft_id=draft.draft_id,
        ledger_id=outcome.ledger_id,
        created_by=created_by,
        notify_sender=notify_sender,
    )

    _push_telegram_panel_alert(
        "success",
        f"{draft.event_type} for {draft.associate_alias} approved (ledger #{outcome.ledger_id}).",
    )

    if notify_sender:
        result = outcome.notification_result
        if result and result.success:
            _push_telegram_panel_alert(
                "success",
                f"Sender notified in Telegram chat {draft.chat_id}.",
            )
        else:
            reason = ""
            if result and result.error_message:
                reason = f": {result.error_message}"
            target = draft.chat_id or "unknown chat"
            _push_telegram_panel_alert(
                "warning",
                f"Accepted but failed to notify chat {target}{reason}",
            )

    safe_rerun("telegram_accept")


def _process_telegram_rejection(draft: FundingDraft) -> None:
    """Reject a Telegram draft."""
    service = FundingService()
    try:
        service.reject_funding_draft(draft.draft_id)
    except FundingError as exc:
        st.error(f"Failed to reject draft: {exc}")
        logger.error(
            "telegram_draft_reject_failed",
            draft_id=draft.draft_id,
            error=str(exc),
            exc_info=True,
        )
        return
    except Exception as exc:  # pragma: no cover - defensive path
        st.error("Unexpected error while rejecting the draft.")
        logger.error(
            "telegram_draft_reject_unexpected",
            draft_id=draft.draft_id,
            error=str(exc),
            exc_info=True,
        )
        return
    finally:
        service.close()

    logger.info("telegram_draft_rejected_via_ui", draft_id=draft.draft_id)
    _push_telegram_panel_alert(
        "info",
        f"Draft for {draft.associate_alias} discarded.",
    )
    safe_rerun("telegram_reject")


def _load_associate_payload(
    repository: AssociateHubRepository, filter_state: Dict[str, object]
) -> Tuple[List[object], Dict[int, List[object]], int]:
    """Fetch associates, bookmakers, and total count for the current filters."""
    associates = repository.list_associates_with_metrics(
        search=filter_state.get("search"),
        admin_filter=filter_state.get("admin_filter"),
        associate_status_filter=filter_state.get("associate_status_filter"),
        bookmaker_status_filter=filter_state.get("bookmaker_status_filter"),
        currency_filter=filter_state.get("currency_filter"),
        sort_by=filter_state.get("sort_by"),
        limit=filter_state.get("page_size"),
        offset=filter_state.get("page", 0) * filter_state.get("page_size", 25),
    )

    associate_ids = [assoc.associate_id for assoc in associates]
    bookmakers: Dict[int, List[object]] = {}

    if associate_ids:
        for associate_id in associate_ids:
            items = repository.list_bookmakers_for_associate(associate_id)
            if items:
                bookmakers[associate_id] = items

    total_count = len(
        repository.list_associates_with_metrics(
            search=filter_state.get("search"),
            admin_filter=filter_state.get("admin_filter"),
            associate_status_filter=filter_state.get("associate_status_filter"),
            bookmaker_status_filter=filter_state.get("bookmaker_status_filter"),
            currency_filter=filter_state.get("currency_filter"),
            sort_by=filter_state.get("sort_by"),
        )
    )

    return associates, bookmakers, total_count


def main() -> None:
    """Render the Associate Operations Hub page."""
    try:
        repository = AssociateHubRepository()
        funding_service = FundingTransactionService()
        balance_service = BookmakerBalanceService()
    except Exception as exc:
        st.error(f"Failed to initialise services: {exc}")
        logger.error("services_initialization_failed", error=str(exc), exc_info=True)
        return

    _render_pending_telegram_panel()

    filter_state, should_refresh = render_filters(repository)

    if should_refresh:
        safe_rerun()
        return

    def render_listing_section() -> None:
        load_label = "Loading associate data..."
        payload: Dict[str, Any] = {}

        def _load_payload() -> None:
            (
                payload["associates"],
                payload["bookmakers"],
                payload["total_count"],
            ) = _load_associate_payload(repository, filter_state)

        try:
            for _ in status_with_steps(
                load_label,
                [("Fetch associates", _load_payload)],
                expanded=False,
            ):
                pass
        except Exception as exc:
            st.error(f"Failed to load associate data: {exc}")
            logger.error("data_loading_failed", error=str(exc), exc_info=True)
            return

        associates = payload.get("associates", [])
        bookmakers = payload.get("bookmakers", [])
        total_count = int(payload.get("total_count", 0))

        if associates:
            render_hub_dashboard(associates)
            render_associate_listing(associates, bookmakers)
            render_pagination_info(total_count, filter_state)
        else:
            render_empty_state(filter_state)

        if st.session_state.get("show_debug_info"):
            st.markdown("### Debug Info")
            st.write(f"Associates returned: {len(associates)}")
            st.write(f"Bookmakers loaded: {len(bookmakers)}")
            st.write(f"Current filter state: {filter_state}")

    @fragment("associate_hub.listing", run_every=60)
    def listing_fragment() -> None:
        render_listing_section()

    listing_fragment()

    # Drawer must render outside the fragment to avoid sidebar restrictions.
    render_detail_drawer(repository, funding_service, balance_service)


def handle_drawer_state() -> None:
    """Clear drawer state when the drawer is closed."""
    if not st.session_state.get("hub_drawer_open", False):
        for key in (
            "hub_drawer_associate_id",
            "hub_drawer_bookmaker_id",
            "hub_drawer_tab",
            "hub_funding_action",
        ):
            st.session_state.pop(key, None)


def handle_keyboard_shortcuts() -> None:
    """Apply keyboard shortcuts for power users."""
    if st.session_state.get("shortcut_reset_filters"):
        from src.ui.components.associate_hub.filters import update_filter_state

        update_filter_state(
            search="",
            admin_filter=[],
            associate_status_filter=[],
            bookmaker_status_filter=[],
            currency_filter=[],
            sort_by="alias_asc",
            page=0,
        )
        st.session_state.pop("shortcut_reset_filters")
        safe_rerun()


def validate_page_access() -> bool:
    """Placeholder access control hook."""
    return True


if __name__ == "__main__":
    if not validate_page_access():
        st.error("You do not have permission to access the Associate Operations Hub.")
        st.stop()

    handle_drawer_state()
    handle_keyboard_shortcuts()

    import time

    st.session_state["load_start_time"] = time.time()

    try:
        main()
    except Exception as exc:  # pragma: no cover - ensure visibility
        st.error(f"Unexpected error: {exc}")
        logger.error("page_error", error=str(exc), exc_info=True)
    finally:
        st.session_state["load_end_time"] = time.time()

    with st.sidebar:
        st.divider()
        st.markdown("### Tips")
        st.caption("- Search covers aliases, bookmakers, and chat IDs.")
        st.caption("- Expand rows to reveal bookmaker details and actions.")
        st.caption("- Funding actions are available within each associate drawer.")
        st.caption("- Filters persist across refreshes for rapid triage.")
        st.caption("- Press 'R' to reset filters when keyboard shortcuts are enabled.")

        st.divider()
        st.markdown("### Help")
        st.caption("Need assistance? Contact the system administrator.")

        if st.session_state.get("is_developer"):
            show_debug = st.checkbox(
                "Show Debug Info", value=st.session_state.get("show_debug_info", False)
            )
            st.session_state["show_debug_info"] = show_debug
