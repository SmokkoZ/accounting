"""
Surebet Accounting System - Streamlit shell.

Adopts modern Streamlit capabilities (navigation, feature flags, fragments)
while preserving compatibility with older versions (1.30+). Pages are defined
declaratively and executed via dynamic imports when the built-in navigation API
is not available.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence

import streamlit as st

from src.ui.utils.feature_flags import all_flags, has

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

    @property
    def script_path(self) -> Optional[Path]:
        if not self.script:
            return None
        return BASE_DIR / self.script


def _render_placeholder(name: str, message: str) -> None:
    st.header(name)
    st.info(message)


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
        title="Incoming Bets",
        section="Operations",
        icon=":material/inbox:",
        script="pages/1_incoming_bets.py",
        description="Review and triage incoming bets.",
    ),
    PageSpec(
        title="Surebets",
        section="Operations",
        icon=":material/target:",
        script="pages/2_verified_bets.py",
        description="Manage verified surebets and coverage.",
    ),
    PageSpec(
        title="Settlement Queue",
        section="Operations",
        icon=":material/task_alt:",
        script="pages/3_verified_bets_queue.py",
        description="Process settlement actions and corrections.",
    ),
    PageSpec(
        title="Corrections",
        section="Operations",
        icon=":material/edit:",
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
        icon=":material/manage_accounts:",
        script="pages/7_admin_associates.py",
        description="Administer associates and permissions.",
    ),
    PageSpec(
        title="Delta Provenance",
        section="Finance",
        icon=":material/account_tree:",
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
        icon=":material/file_upload:",
        script="pages/5_export.py",
        description="CSV export workflow for ledger data and audit trails.",
    ),
    PageSpec(
        title="Statements",
        section="Finance",
        icon=":material/description:",
        description="Monthly partner statements (coming soon).",
        renderer=lambda: _render_placeholder(
            "Statements", "Statements will be introduced in a future release."
        ),
    ),
)


def _group_by_section(pages: Iterable[PageSpec]) -> Dict[str, List[PageSpec]]:
    grouped: Dict[str, List[PageSpec]] = {}
    for page in pages:
        grouped.setdefault(page.section, []).append(page)
    return grouped


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


def _render_sidebar(pages: Sequence[PageSpec]) -> None:
    st.sidebar.title("Navigation")

    if has("page_link"):
        st.sidebar.caption("Quick links")
        for page in pages:
            if page.script:
                st.sidebar.page_link(page.script, label=page.title, icon=page.icon)
        st.sidebar.divider()

    st.sidebar.subheader("Feature flags")
    for name, supported in sorted(all_flags().items()):
        glyph = "✅" if supported else "⚪"
        st.sidebar.write(f"{glyph} `{name}`")

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
    grouped = _group_by_section(PAGE_REGISTRY)
    nav_structure: Dict[str, List["st.Page"]] = {}

    for section, pages in grouped.items():
        entries: List["st.Page"] = []
        for page in pages:
            if not page.script:
                continue
            entries.append(st.Page(page.script, title=page.title, icon=page.icon))
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
    _render_sidebar(PAGE_REGISTRY)

    if has("navigation"):
        _render_navigation_with_pages()
    else:
        _render_navigation_fallback()

    _render_footer()


if __name__ == "__main__":
    main()
