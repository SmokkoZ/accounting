"""
Surebet Accounting System - Streamlit shell.

Adopts modern Streamlit capabilities (navigation, feature flags, fragments)
while preserving compatibility with older versions (1.30+). Pages are defined
declaratively and executed via dynamic imports when the built-in navigation API
is not available.
"""

from __future__ import annotations

import importlib.util
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Sequence

import streamlit as st

from src.ui.utils.feature_flags import has

# Configure app-wide layout and theme once.
st.set_page_config(
    page_title="Surebet Accounting System",
    page_icon=":material/monitoring:",
    layout="wide",
    initial_sidebar_state="expanded",
)


BASE_DIR = Path(__file__).parent


@dataclass(frozen=True)
class PageSpec:
    """Metadata describing a Streamlit page."""

    title: str
    section: str
    icon: str = ":material/article:"
    script: Optional[str] = None
    description: str = ""
    renderer: Optional[Callable[[], None]] = None

    def to_navigation_page(self) -> "st.Page":
        """Convert this spec into a Streamlit Page for modern navigation."""
        if not self.script:
            raise ValueError(f"Page '{self.title}' does not define a script.")
        return st.Page(
            self.script,
            title=self.title,
            icon=self.icon,
        )

    @property
    def script_path(self) -> Optional[Path]:
        if not self.script:
            return None
        return BASE_DIR / self.script


def _render_placeholder(name: str, message: str) -> None:
    st.header(name)
    st.info(message)


def _group_by_section(pages: Sequence[PageSpec]) -> "OrderedDict[str, List[PageSpec]]":
    grouped: "OrderedDict[str, List[PageSpec]]" = OrderedDict()
    for page in pages:
        grouped.setdefault(page.section, []).append(page)
    return grouped


PAGE_REGISTRY: Sequence[PageSpec] = (
    PageSpec(
        title="Dashboard",
        section="Overview",
        icon=":material/monitoring:",
        script="pages/0_dashboard.py",
        description="Operations overview and quick links.",
    ),
    PageSpec(
        title="Associate Operations Hub",
        section="Operations",
        icon=":material/groups_3:",
        script="pages/8_associate_operations.py",
        description="Manage associates, bookmakers, and funding transactions.",
    ),
    PageSpec(
        title="Associates Hub",
        section="Operations",
        icon=":material/diversity_3:",
        script="pages/7_associates_hub.py",
        description="Configure associates and bookmakers with inline editing.",
    ),
    PageSpec(
        title="Incoming Bets",
        section="Operations",
        icon=":material/inbox:",
        script="pages/1_incoming_bets.py",
        description="Review and triage incoming bets.",
    ),
    PageSpec(
        title="Ingested betslips",
        section="Operations",
        icon=":material/task_alt:",
        script="pages/3_verified_bets_queue.py",
        description="Process settlement actions, confirmations, and corrections.",
    ),
    PageSpec(
        title="Surebets Summary",
        section="Operations",
        icon=":material/target:",
        script="pages/2_surebets_summary.py",
        description="Monitor verified surebets, coverage proofs, and risk.",
    ),
    PageSpec(
        title="Surebets Ready for Settlement",
        section="Operations",
        icon=":material/receipt_long:",
        script="pages/2b_surebets_ready_for_settlement.py",
        description="Finalize surebets once coverage proof is complete.",
    ),
    PageSpec(
        title="Corrections",
        section="Operations",
        icon=":material/edit_note:",
        script="pages/5_corrections.py",
        description="Track and resolve corrections.",
    ),
    PageSpec(
        title="Reconciliation",
        section="Finance",
        icon=":material/account_balance:",
        script="pages/6_reconciliation.py",
        description="Run reconciliation checks and variance analysis.",
    ),
    PageSpec(
        title="Admin & Associates",
        section="Administration",
        icon=":material/admin_panel_settings:",
        script="pages/7_admin_associates.py",
        description="Administer associates and permissions.",
    ),
    PageSpec(
        title="Delta Provenance",
        section="Finance",
        icon=":material/source:",
        script="pages/delta_provenance.py",
        description="View associate delta breakdown by counterparty and surebet.",
    ),
    PageSpec(
        title="Balance Management",
        section="Finance",
        icon=":material/account_balance_wallet:",
        script="pages/balance_management.py",
        description="Monitor bookmaker balances and ledger state.",
    ),
    PageSpec(
        title="Export",
        section="Operations",
        icon=":material/ios_share:",
        script="pages/5_export.py",
        description="Excel export workflow for ledger data and audit trails.",
    ),
    PageSpec(
        title="Statements",
        section="Finance",
        icon=":material/contract:",
        script="pages/6_statements.py",
        description="Generate monthly partner statements with funding, entitlement, and reconciliation.",
    ),
    PageSpec(
        title="Signal Broadcaster",
        section="Telegram",
        icon=":material/campaign:",
        script="pages/8_signal_broadcaster.py",
        description="Compose, preview, and send raw signals to Telegram chats.",
    ),
    PageSpec(
        title="Pending Photos",
        section="Telegram",
        icon=":material/photo_library:",
        script="pages/telegram_pending_photos.py",
        description="Monitor confirm-before-ingest queue with TTL countdowns and actions.",
    ),
    PageSpec(
        title="Coverage Proof Outbox",
        section="Telegram",
        icon=":material/outbox:",
        script="pages/telegram_coverage_proof_outbox.py",
        description="Review coverage proof deliveries and manage Telegram resends.",
    ),
    PageSpec(
        title="Rate Limiting",
        section="Telegram",
        icon=":material/speed:",
        script="pages/telegram_rate_limiting.py",
        description="Inspect chat cooldowns to avoid Telegram API limits.",
    ),
)


def _dynamic_run(page: PageSpec) -> None:
    """Fallback loader that executes a Streamlit page script inline."""
    if page.renderer:
        page.renderer()
        return

    script_path = page.script_path
    if not script_path:
        st.error(f"No implementation configured for '{page.title}'.")
        return

    if not script_path.exists():
        st.error(f"Page script not found: {script_path}")
        return

    try:
        module_name = f"ui_page_{script_path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, script_path)
        if spec is None or spec.loader is None:
            raise ImportError("Unable to resolve module specification.")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[attr-defined]

        main_fn = getattr(module, "main", None)
        if callable(main_fn):
            main_fn()
    except Exception as exc:  # pragma: no cover - surface to UI
        st.error(f"Error loading page '{page.title}': {exc}")


def _render_sidebar(pages: Sequence[PageSpec], use_modern_navigation: bool = False) -> None:
    # Only show "Navigation" title when we have navigation content to display
    if not use_modern_navigation and has("page_link"):
        st.sidebar.title("Navigation")
        st.sidebar.caption("Quick links")
        for page in pages:
            if page.script:
                st.sidebar.page_link(page.script, label=page.title, icon=page.icon)
        st.sidebar.divider()

    st.sidebar.caption("Use the dashboard for at-a-glance status.")


def _render_footer() -> None:
    st.markdown("---")
    st.caption(
        f"© 2025 Surebet Accounting System · Last refreshed "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )


def _render_navigation_with_pages() -> None:
    """Use Streamlit's native navigation when available."""
    nav_structure: "OrderedDict[str, List['st.Page']]" = OrderedDict()
    for section, pages in _group_by_section(PAGE_REGISTRY).items():
        entries: List["st.Page"] = []
        for page_spec in pages:
            if not page_spec.script:
                continue
            entries.append(page_spec.to_navigation_page())
        if entries:
            nav_structure[section] = entries

    navigation = st.navigation(nav_structure)
    navigation.run()


def _render_navigation_fallback() -> None:
    """Render legacy sidebar navigation with dynamic imports."""
    st.title("Surebet Accounting System")
    st.caption("Operator console for bet ingestion, settlement, and reconciliation.")
    st.divider()

    page_titles = [page.title for page in PAGE_REGISTRY]
    default_index = page_titles.index("Dashboard") if "Dashboard" in page_titles else 0
    selected_title = st.sidebar.selectbox(
        "Select a page:", options=page_titles, index=default_index
    )

    selected_page = next(page for page in PAGE_REGISTRY if page.title == selected_title)

    if selected_page.description:
        st.caption(selected_page.description)

    _dynamic_run(selected_page)


def main() -> None:
    use_modern_navigation = has("navigation")
    _render_sidebar(PAGE_REGISTRY, use_modern_navigation)

    if use_modern_navigation:
        _render_navigation_with_pages()
    else:
        _render_navigation_fallback()

    _render_footer()


if __name__ == "__main__":
    main()
