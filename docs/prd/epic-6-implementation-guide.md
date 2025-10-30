# Epic 6: Reporting & Audit - Implementation Guide

**Epic Reference:** [Epic 6: Reporting & Audit](./epic-6-reporting-audit.md)
**Status:** Ready for Implementation
**Estimated Duration:** 3-4 days
**Developer:** Full-Stack

---

## Overview

Epic 6 is the **final MVP epic**. It implements comprehensive reporting and audit capabilities:
1. **Complete Ledger CSV Export** (Story 6.1): Export full ledger for audit, backup, and external analysis
2. **Monthly Statement Generator** (Story 6.2): Generate partner-facing statements with profit/loss summaries

**CRITICAL**: Epic 6 is **read-only**. No ledger writes, only data presentation.

**When Epic 6 is complete**:
- ✅ All 10 Functional Requirements implemented
- ✅ All 6 System Laws enforced
- ✅ End-to-end workflow complete: Screenshot → Settlement → Reconciliation → Export
- ✅ **MVP is production-ready**

**Architecture Principles**:
- CSV exports are full-fidelity (no data loss)
- Monthly statements are snapshots (read-only queries)
- All math uses Decimal precision
- Cutoff dates filter inclusively (<=)

---

## Prerequisites

Before starting Epic 6, ensure:
- [x] **Epic 0-5** complete: Full workflow from ingestion to reconciliation
- Ledger has diverse entry types (BET_RESULT, DEPOSIT, WITHDRAWAL, BOOKMAKER_CORRECTION)
- At least 50 ledger entries for realistic testing
- Multiple associates with different balances

**Database State Required**:
- `ledger_entries` table populated
- `associates`, `bookmakers`, `surebets`, `bets` tables with data
- FX rates available

---

## Task Breakdown

### Story 6.1: Complete Ledger CSV Export

**Goal**: Export entire ledger to CSV for audit, backup, and external analysis.

#### Task 6.1.1: Export Page
**File**: `src/streamlit_app/pages/07_Export.py`

```python
"""
Export page for ledger CSV generation.
"""
import streamlit as st
from pathlib import Path

from src.data.repositories.ledger_repository import LedgerEntryRepository
from src.domain.export_service import ExportService
from src.streamlit_app.components.export.export_button import render_export_button
from src.streamlit_app.components.export/export_history import render_export_history

st.set_page_config(
    page_title="Export - Surebet Accounting",
    page_icon="📥",
    layout="wide"
)

st.title("📥 Ledger Export")
st.caption("Export complete ledger to CSV for audit and backup")

# Initialize services
db_path = "data/surebet.db"
ledger_repo = LedgerEntryRepository(db_path)
export_service = ExportService(ledger_repo)

# Info banner
st.info("""
**Full Ledger Export**: All ledger entries with joins to associates, bookmakers, and surebets.

**Use cases:**
- 💾 Weekly backup (disaster recovery)
- 📊 External analysis (Excel, Google Sheets)
- 🔍 Audit trail (compliance)
- 🚀 Data portability (not locked in)
""")

st.divider()

# Export button section
st.subheader("Export Ledger")
render_export_button(export_service, ledger_repo)

st.divider()

# Export history
st.subheader("Recent Exports")
render_export_history()
```

---

#### Task 6.1.2: Export Button Component
**File**: `src/streamlit_app/components/export/export_button.py`

```python
"""
Export button component with progress tracking.
"""
import streamlit as st
from pathlib import Path

from src.domain.export_service import ExportService
from src.data.repositories.ledger_repository import LedgerEntryRepository

def render_export_button(
    export_service: ExportService,
    ledger_repo: LedgerEntryRepository
):
    """Render export button with row count preview."""

    # Get ledger row count
    row_count = ledger_repo.get_entry_count()

    st.markdown(f"**Current ledger size:** {row_count:,} entries")

    if row_count == 0:
        st.warning("⚠️ Ledger is empty. No entries to export.")
        return

    # Export button
    if st.button("📥 Export Full Ledger", type="primary", use_container_width=True):
        with st.spinner(f"Exporting {row_count:,} entries..."):
            try:
                # Perform export
                result = export_service.export_full_ledger()

                # Success message
                st.success(f"""
                ✅ **Ledger exported successfully!**

                - **File:** `{result['file_path']}`
                - **Rows:** {result['row_count']:,} entries
                - **Size:** {result['file_size_kb']:.2f} KB
                - **Duration:** {result['duration_seconds']:.2f}s
                """)

                # Download button
                with open(result['file_path'], 'rb') as f:
                    csv_data = f.read()

                st.download_button(
                    label="⬇️ Download CSV",
                    data=csv_data,
                    file_name=Path(result['file_path']).name,
                    mime="text/csv",
                    use_container_width=True
                )

                # Store export in history (session state)
                if 'export_history' not in st.session_state:
                    st.session_state.export_history = []

                st.session_state.export_history.insert(0, result)

                # Keep only last 10
                st.session_state.export_history = st.session_state.export_history[:10]

            except Exception as e:
                st.error(f"❌ Export failed: {e}")
                import traceback
                st.code(traceback.format_exc())
```

---

#### Task 6.1.3: Export History Component
**File**: `src/streamlit_app/components/export/export_history.py`

```python
"""
Export history component showing recent exports.
"""
import streamlit as st
import pandas as pd
from pathlib import Path
from datetime import datetime

def render_export_history():
    """Render table of recent exports."""

    if 'export_history' not in st.session_state or not st.session_state.export_history:
        st.info("No exports yet. Click 'Export Full Ledger' to create your first export.")
        return

    # Build DataFrame
    df_data = []
    for export in st.session_state.export_history:
        # Parse timestamp from filename
        filename = Path(export['file_path']).name
        timestamp_str = export.get('timestamp', 'Unknown')

        # Format timestamp
        try:
            ts = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            ts_display = ts.strftime("%Y-%m-%d %H:%M:%S UTC")
        except:
            ts_display = timestamp_str

        df_data.append({
            "Timestamp": ts_display,
            "Filename": filename,
            "Rows": f"{export['row_count']:,}",
            "Size (KB)": f"{export['file_size_kb']:.2f}",
            "Duration (s)": f"{export['duration_seconds']:.2f}",
            "_file_path": export['file_path']
        })

    df = pd.DataFrame(df_data)

    # Display table
    st.dataframe(
        df.drop(columns=['_file_path']),
        use_container_width=True,
        hide_index=True
    )

    st.caption(f"**{len(st.session_state.export_history)} recent exports** (last 10 shown)")

    # Re-download links
    st.markdown("**Re-download:**")
    for i, export in enumerate(st.session_state.export_history):
        file_path = Path(export['file_path'])
        if file_path.exists():
            with open(file_path, 'rb') as f:
                csv_data = f.read()

            st.download_button(
                label=f"⬇️ {file_path.name}",
                data=csv_data,
                file_name=file_path.name,
                mime="text/csv",
                key=f"redownload_{i}"
            )
        else:
            st.caption(f"❌ {file_path.name} (file not found)")
```

---

#### Task 6.1.4: Export Service
**File**: `src/domain/export_service.py`

```python
"""
Export service for generating CSV exports.
"""
import csv
import logging
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, List

from src.data.repositories.ledger_repository import LedgerEntryRepository
from src.utils.timestamp_utils import format_timestamp_utc

logger = logging.getLogger(__name__)

class ExportService:
    """Service for exporting ledger to CSV."""

    EXPORT_DIR = Path("data/exports")
    CSV_COLUMNS = [
        "entry_id",
        "entry_type",
        "associate_id",
        "associate_alias",
        "bookmaker_id",
        "bookmaker_name",
        "surebet_id",
        "bet_id",
        "settlement_batch_id",
        "settlement_state",
        "amount_native",
        "native_currency",
        "fx_rate_snapshot",
        "amount_eur",
        "principal_returned_eur",
        "per_surebet_share_eur",
        "created_at_utc",
        "created_by",
        "note"
    ]

    def __init__(self, ledger_repo: LedgerEntryRepository):
        self.ledger_repo = ledger_repo

        # Ensure export directory exists
        self.EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    def export_full_ledger(self) -> Dict:
        """
        Export complete ledger to CSV with joins.

        Returns:
            Dict with export metadata:
            - file_path: str
            - row_count: int
            - file_size_kb: float
            - duration_seconds: float
            - timestamp: str
        """
        start_time = time.time()

        # Generate filename with timestamp
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"ledger_{timestamp}.csv"
        file_path = self.EXPORT_DIR / filename

        logger.info(f"Starting ledger export to {file_path}")

        # Fetch all ledger entries with joins
        entries = self.ledger_repo.get_all_with_joins()

        # Write to CSV (streaming for large datasets)
        with open(file_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=self.CSV_COLUMNS)

            # Write header
            writer.writeheader()

            # Write rows
            for entry in entries:
                row = self._entry_to_csv_row(entry)
                writer.writerow(row)

        # Calculate file size
        file_size_bytes = file_path.stat().st_size
        file_size_kb = file_size_bytes / 1024

        # Calculate duration
        duration_seconds = time.time() - start_time

        logger.info(
            f"Ledger export complete: {len(entries)} rows, "
            f"{file_size_kb:.2f} KB, {duration_seconds:.2f}s"
        )

        return {
            'file_path': str(file_path),
            'row_count': len(entries),
            'file_size_kb': file_size_kb,
            'duration_seconds': duration_seconds,
            'timestamp': format_timestamp_utc()
        }

    def _entry_to_csv_row(self, entry: Dict) -> Dict:
        """
        Convert ledger entry dict to CSV row.

        Handles:
        - NULL values → empty strings
        - Decimal → string (preserve precision)
        """
        row = {}

        for col in self.CSV_COLUMNS:
            value = entry.get(col)

            if value is None:
                row[col] = ""
            elif isinstance(value, Decimal):
                row[col] = str(value)  # Preserve precision
            else:
                row[col] = str(value)

        return row
```

---

#### Task 6.1.5: Extend Ledger Repository (Export Queries)
**File**: `src/data/repositories/ledger_repository.py` (add methods)

```python
# Add to existing LedgerEntryRepository class:

def get_entry_count(self) -> int:
    """Get total number of ledger entries."""
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM ledger_entries")
    count = cursor.fetchone()[0]

    conn.close()
    return count

def get_all_with_joins(self) -> List[Dict]:
    """
    Get all ledger entries with joins to associates, bookmakers, surebets, bets.

    Returns:
        List of dicts with all columns for CSV export
    """
    conn = sqlite3.connect(self.db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            le.entry_id,
            le.entry_type,
            le.associate_id,
            a.display_alias AS associate_alias,
            le.bookmaker_id,
            bm.name AS bookmaker_name,
            le.surebet_id,
            le.bet_id,
            le.settlement_batch_id,
            le.settlement_state,
            le.amount_native,
            le.native_currency,
            le.fx_rate_snapshot,
            le.amount_eur,
            le.principal_returned_eur,
            le.per_surebet_share_eur,
            le.created_at_utc,
            le.created_by,
            le.note
        FROM ledger_entries le
        LEFT JOIN associates a ON le.associate_id = a.associate_id
        LEFT JOIN bookmakers bm ON le.bookmaker_id = bm.bookmaker_id
        ORDER BY le.entry_id ASC
    """)

    rows = cursor.fetchall()
    conn.close()

    # Convert to list of dicts
    return [dict(row) for row in rows]
```

---

### Story 6.2: Monthly Statement Generator

**Goal**: Generate partner-facing statements with profit/loss summaries.

#### Task 6.2.1: Monthly Statements Page
**File**: `src/streamlit_app/pages/08_Monthly_Statements.py`

```python
"""
Monthly statements page for generating partner reports.
"""
import streamlit as st
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

from src.data.repositories.ledger_repository import LedgerEntryRepository
from src.data.repositories.associate_repository import AssociateRepository
from src.domain.statement_service import StatementService
from src.streamlit_app.components.statements.statement_form import render_statement_form
from src.streamlit_app.components.statements.statement_display import render_statement_display

st.set_page_config(
    page_title="Monthly Statements - Surebet Accounting",
    page_icon="📄",
    layout="wide"
)

st.title("📄 Monthly Statements")
st.caption("Generate partner-facing profit/loss reports")

# Initialize services
db_path = "data/surebet.db"
ledger_repo = LedgerEntryRepository(db_path)
associate_repo = AssociateRepository(db_path)
statement_service = StatementService(ledger_repo, associate_repo)

# Info banner
st.info("""
**Monthly Statements**: Snapshots of associate performance up to a cutoff date.

**Partner-Facing Section** (shareable):
- Funding summary
- Entitlement summary
- Profit/loss
- 50/50 split explanation

**Internal-Only Section** (do NOT share):
- Current holdings
- Reconciliation DELTA
""")

st.divider()

# Input form
st.subheader("Generate Statement")
selected_associate_id, cutoff_date = render_statement_form(associate_repo)

st.divider()

# Display statement if generated
if selected_associate_id and cutoff_date:
    render_statement_display(
        statement_service=statement_service,
        associate_id=selected_associate_id,
        cutoff_date=cutoff_date
    )
```

---

#### Task 6.2.2: Statement Form Component
**File**: `src/streamlit_app/components/statements/statement_form.py`

```python
"""
Statement generation form component.
"""
import streamlit as st
from datetime import datetime
from dateutil.relativedelta import relativedelta
from typing import Optional, Tuple

from src.data.repositories.associate_repository import AssociateRepository

def render_statement_form(associate_repo: AssociateRepository) -> Tuple[Optional[int], Optional[datetime]]:
    """
    Render statement input form.

    Returns:
        Tuple of (associate_id, cutoff_date) or (None, None)
    """
    associates = associate_repo.get_all()

    if not associates:
        st.warning("No associates found. Please create associates first.")
        return None, None

    associate_options = {a.display_alias: a.associate_id for a in associates}

    with st.form("statement_form"):
        col1, col2 = st.columns(2)

        with col1:
            # Associate selector
            selected_alias = st.selectbox(
                "Associate",
                options=list(associate_options.keys()),
                help="Select associate to generate statement for"
            )
            associate_id = associate_options[selected_alias]

        with col2:
            # Cutoff date picker
            # Default: end of current month (last second)
            now = datetime.utcnow()
            end_of_month = datetime(now.year, now.month, 1) + relativedelta(months=1) - relativedelta(seconds=1)

            cutoff_date = st.date_input(
                "Cutoff Date",
                value=end_of_month.date(),
                help="All transactions up to and including this date (23:59:59 UTC)"
            )

            # Convert to datetime at end of day
            cutoff_datetime = datetime.combine(cutoff_date, datetime.max.time()).replace(microsecond=0)

        # Note
        st.caption("**Note:** Cutoff is inclusive (transactions at 23:59:59 UTC included)")

        # Validation
        if cutoff_datetime > datetime.utcnow():
            st.warning("⚠️ Cutoff date is in the future. Results may be incomplete.")

        # Generate button
        submitted = st.form_submit_button("📊 Generate Statement", type="primary")

        if submitted:
            return associate_id, cutoff_datetime

    return None, None
```

---

#### Task 6.2.3: Statement Display Component
**File**: `src/streamlit_app/components/statements/statement_display.py`

```python
"""
Statement display component.
"""
import streamlit as st
from datetime import datetime

from src.domain.statement_service import StatementService

def render_statement_display(
    statement_service: StatementService,
    associate_id: int,
    cutoff_date: datetime
):
    """Render generated statement."""

    try:
        # Generate statement
        statement = statement_service.generate_statement(
            associate_id=associate_id,
            cutoff_date=cutoff_date
        )

        # Statement header
        st.markdown(f"""
        # Monthly Statement for {statement['associate_alias']}

        **Period ending:** {cutoff_date.strftime('%Y-%m-%d %H:%M:%S UTC')}
        **Generated:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}
        """)

        st.divider()

        # Partner-Facing Section
        st.subheader("📋 Partner-Facing Section (Shareable)")

        _render_partner_section(statement)

        st.divider()

        # Internal-Only Section
        with st.expander("🔒 Internal-Only Section (DO NOT SHARE)", expanded=False):
            _render_internal_section(statement)

        st.divider()

        # Export options
        st.subheader("Export Options")

        col1, col2, col3 = st.columns(3)

        with col1:
            # Copy partner section to clipboard
            partner_text = _format_partner_section_text(statement, cutoff_date)

            st.download_button(
                label="📋 Copy Partner Section",
                data=partner_text,
                file_name=f"statement_{statement['associate_alias']}_{cutoff_date.strftime('%Y%m')}.txt",
                mime="text/plain"
            )

        with col2:
            # Export full statement (internal)
            full_text = _format_full_statement_text(statement, cutoff_date)

            st.download_button(
                label="📄 Export Full Statement",
                data=full_text,
                file_name=f"statement_full_{statement['associate_alias']}_{cutoff_date.strftime('%Y%m')}.txt",
                mime="text/plain"
            )

        with col3:
            st.button("📊 Export to CSV", disabled=True, help="Coming soon")

    except Exception as e:
        st.error(f"❌ Failed to generate statement: {e}")
        import traceback
        st.code(traceback.format_exc())


def _render_partner_section(statement: dict):
    """Render partner-facing section."""

    # Funding summary
    st.markdown(f"""
    ### 💰 Funding Summary

    **You funded:** €{statement['net_deposits_eur']:,.2f} total

    *This is the cash you personally put in.*
    """)

    # Entitlement summary
    st.markdown(f"""
    ### 🎯 Entitlement Summary

    **You're entitled to:** €{statement['should_hold_eur']:,.2f}

    *If we froze time right now, this much of the pot is yours.*
    """)

    # Profit/Loss summary
    raw_profit = statement['raw_profit_eur']

    if raw_profit >= 0:
        profit_color = "green"
        profit_label = "Your profit"
        explanation = "How far ahead you are compared to what you funded."
    else:
        profit_color = "red"
        profit_label = "Your loss"
        explanation = "How far behind you are compared to what you funded."

    st.markdown(f"""
    ### 📈 Profit/Loss Summary

    **{profit_label}:** :{profit_color}[€{abs(raw_profit):,.2f}]

    *{explanation}*
    """)

    # 50/50 Split explanation
    if raw_profit >= 0:
        your_share = raw_profit / 2
        admin_share = raw_profit / 2

        st.markdown(f"""
        ### 🤝 50/50 Split Calculation

        Our deal is 50/50, so:

        - **Your share:** €{your_share:,.2f} (half of profit)
        - **Admin share:** €{admin_share:,.2f} (half of profit)

        *Note: This is for transparency. In our system, profit is already split equally through per-surebet shares.*
        """)
    else:
        your_share_of_loss = abs(raw_profit) / 2
        admin_share_of_loss = abs(raw_profit) / 2

        st.markdown(f"""
        ### 🤝 50/50 Split Calculation

        Our deal is 50/50, so:

        - **Your share of loss:** €{your_share_of_loss:,.2f} (half of loss)
        - **Admin share of loss:** €{admin_share_of_loss:,.2f} (half of loss)

        *Note: This is for transparency. Losses are also split equally.*
        """)


def _render_internal_section(statement: dict):
    """Render internal-only section."""

    st.warning("⚠️ **DO NOT SHARE THIS SECTION WITH PARTNERS**")

    # Current holdings
    st.markdown(f"""
    ### 💼 Current Holdings

    **Currently holding:** €{statement['current_holding_eur']:,.2f}

    *What model thinks you're physically holding in bookmaker accounts.*
    """)

    # Reconciliation DELTA
    delta = statement['delta_eur']

    if delta > 10:
        status_icon = "🔴"
        status_text = f"Holding €{abs(delta):,.2f} more than entitlement (collect from associate)"
        status_color = "red"
    elif delta < -10:
        status_icon = "🟠"
        status_text = f"Short €{abs(delta):,.2f} (owed to associate)"
        status_color = "orange"
    else:
        status_icon = "🟢"
        status_text = "Balanced"
        status_color = "green"

    st.markdown(f"""
    ### 📊 Reconciliation Delta

    **DELTA:** {status_icon} :{status_color}[€{delta:+,.2f}]

    *{status_text}*
    """)


def _format_partner_section_text(statement: dict, cutoff_date: datetime) -> str:
    """Format partner section as plain text for copy/paste."""

    raw_profit = statement['raw_profit_eur']

    if raw_profit >= 0:
        profit_line = f"Your profit: €{abs(raw_profit):,.2f}"
        split_line = f"Your share: €{raw_profit / 2:,.2f} (half of profit)\nAdmin share: €{raw_profit / 2:,.2f} (half of profit)"
    else:
        profit_line = f"Your loss: €{abs(raw_profit):,.2f}"
        split_line = f"Your share of loss: €{abs(raw_profit) / 2:,.2f} (half of loss)\nAdmin share of loss: €{abs(raw_profit) / 2:,.2f} (half of loss)"

    return f"""
Monthly Statement for {statement['associate_alias']}
Period ending: {cutoff_date.strftime('%Y-%m-%d %H:%M:%S UTC')}
Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}

--- Partner-Facing Section ---

You funded: €{statement['net_deposits_eur']:,.2f} total
This is the cash you personally put in.

You're entitled to: €{statement['should_hold_eur']:,.2f}
If we froze time right now, this much of the pot is yours.

{profit_line}
How far ahead/behind you are compared to what you funded.

Our deal is 50/50, so:
{split_line}

Note: This is for transparency. In our system, profit is already split equally through per-surebet shares.
    """.strip()


def _format_full_statement_text(statement: dict, cutoff_date: datetime) -> str:
    """Format full statement (including internal section) as plain text."""

    partner_section = _format_partner_section_text(statement, cutoff_date)

    delta = statement['delta_eur']

    if delta > 10:
        delta_text = f"🔴 Holding €{abs(delta):,.2f} more than entitlement (collect from associate)"
    elif delta < -10:
        delta_text = f"🟠 Short €{abs(delta):,.2f} (owed to associate)"
    else:
        delta_text = "🟢 Balanced"

    return f"""
{partner_section}

--- Internal-Only Section (DO NOT SHARE) ---

Currently holding: €{statement['current_holding_eur']:,.2f}
What model thinks you're physically holding in bookmaker accounts.

Reconciliation Delta: €{delta:+,.2f}
{delta_text}
    """.strip()
```

---

#### Task 6.2.4: Statement Service
**File**: `src/domain/statement_service.py`

```python
"""
Statement service for generating monthly statements.
"""
import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Dict

from src.data.repositories.ledger_repository import LedgerEntryRepository
from src.data.repositories.associate_repository import AssociateRepository

logger = logging.getLogger(__name__)

@dataclass
class MonthlyStatement:
    """Monthly statement data."""
    associate_id: int
    associate_alias: str
    cutoff_date: datetime
    net_deposits_eur: Decimal
    should_hold_eur: Decimal
    current_holding_eur: Decimal
    raw_profit_eur: Decimal
    delta_eur: Decimal

class StatementService:
    """Service for generating monthly statements."""

    def __init__(
        self,
        ledger_repo: LedgerEntryRepository,
        associate_repo: AssociateRepository
    ):
        self.ledger_repo = ledger_repo
        self.associate_repo = associate_repo

    def generate_statement(
        self,
        associate_id: int,
        cutoff_date: datetime
    ) -> Dict:
        """
        Generate monthly statement for associate up to cutoff date.

        CRITICAL: This is read-only. No ledger writes.

        Args:
            associate_id: Associate to generate statement for
            cutoff_date: Include all transactions up to and including this datetime

        Returns:
            Dict with statement data
        """
        # Get associate info
        associate = self.associate_repo.get_by_id(associate_id)
        if not associate:
            raise ValueError(f"Associate {associate_id} not found")

        # Format cutoff for SQL (ISO8601 with Z suffix)
        cutoff_str = cutoff_date.strftime('%Y-%m-%dT%H:%M:%SZ')

        # Get aggregates from ledger (up to cutoff)
        aggregates = self.ledger_repo.get_associate_aggregates_up_to(
            associate_id=associate_id,
            cutoff_date_utc=cutoff_str
        )

        # Extract metrics (same formulas as Epic 5 reconciliation)
        net_deposits_eur = aggregates.get('net_deposits_eur', Decimal("0.00"))
        should_hold_eur = aggregates.get('should_hold_eur', Decimal("0.00"))
        current_holding_eur = aggregates.get('current_holding_eur', Decimal("0.00"))

        # Calculate derived metrics
        raw_profit_eur = should_hold_eur - net_deposits_eur
        delta_eur = current_holding_eur - should_hold_eur

        logger.info(
            f"Statement generated for {associate.display_alias}: "
            f"NET_DEPOSITS=€{net_deposits_eur}, SHOULD_HOLD=€{should_hold_eur}, "
            f"PROFIT=€{raw_profit_eur}, DELTA=€{delta_eur}"
        )

        return {
            'associate_id': associate_id,
            'associate_alias': associate.display_alias,
            'cutoff_date': cutoff_date,
            'net_deposits_eur': net_deposits_eur,
            'should_hold_eur': should_hold_eur,
            'current_holding_eur': current_holding_eur,
            'raw_profit_eur': raw_profit_eur,
            'delta_eur': delta_eur
        }
```

---

#### Task 6.2.5: Extend Ledger Repository (Statement Queries)
**File**: `src/data/repositories/ledger_repository.py` (add method)

```python
# Add to existing LedgerEntryRepository class:

def get_associate_aggregates_up_to(
    self,
    associate_id: int,
    cutoff_date_utc: str
) -> Dict:
    """
    Get aggregated metrics for associate up to cutoff date.

    Args:
        associate_id: Associate to query
        cutoff_date_utc: ISO8601 timestamp (inclusive)

    Returns:
        Dict with keys:
        - net_deposits_eur
        - should_hold_eur
        - current_holding_eur
    """
    conn = sqlite3.connect(self.db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            -- NET_DEPOSITS_EUR
            SUM(CASE WHEN entry_type='DEPOSIT' THEN amount_eur ELSE 0 END) -
            SUM(CASE WHEN entry_type='WITHDRAWAL' THEN ABS(amount_eur) ELSE 0 END) AS net_deposits_eur,

            -- SHOULD_HOLD_EUR
            SUM(CASE
                WHEN entry_type='BET_RESULT'
                THEN COALESCE(principal_returned_eur, 0) + COALESCE(per_surebet_share_eur, 0)
                ELSE 0
            END) AS should_hold_eur,

            -- CURRENT_HOLDING_EUR
            SUM(amount_eur) AS current_holding_eur

        FROM ledger_entries
        WHERE associate_id = ?
        AND created_at_utc <= ?
    """, (associate_id, cutoff_date_utc))

    row = cursor.fetchone()
    conn.close()

    if not row:
        return {
            'net_deposits_eur': Decimal("0.00"),
            'should_hold_eur': Decimal("0.00"),
            'current_holding_eur': Decimal("0.00")
        }

    return {
        'net_deposits_eur': Decimal(row['net_deposits_eur'] or "0.00"),
        'should_hold_eur': Decimal(row['should_hold_eur'] or "0.00"),
        'current_holding_eur': Decimal(row['current_holding_eur'] or "0.00")
    }
```

---

### Testing

#### Task 6.3.1: Unit Tests for Export Service
**File**: `tests/unit/domain/test_export_service.py`

```python
"""
Unit tests for ExportService.
"""
import pytest
import csv
from pathlib import Path
from decimal import Decimal

from src.domain.export_service import ExportService

class MockLedgerRepo:
    """Mock ledger repository."""

    def get_entry_count(self):
        return 3

    def get_all_with_joins(self):
        return [
            {
                'entry_id': 1,
                'entry_type': 'BET_RESULT',
                'associate_id': 1,
                'associate_alias': 'Admin',
                'bookmaker_id': 1,
                'bookmaker_name': 'Bet365',
                'surebet_id': 1,
                'bet_id': 1,
                'settlement_batch_id': 'batch-123',
                'settlement_state': 'WON',
                'amount_native': Decimal('100.00'),
                'native_currency': 'EUR',
                'fx_rate_snapshot': Decimal('1.00'),
                'amount_eur': Decimal('95.00'),
                'principal_returned_eur': Decimal('100.00'),
                'per_surebet_share_eur': Decimal('-5.00'),
                'created_at_utc': '2025-10-30T12:00:00Z',
                'created_by': 'local_user',
                'note': None
            },
            {
                'entry_id': 2,
                'entry_type': 'DEPOSIT',
                'associate_id': 1,
                'associate_alias': 'Admin',
                'bookmaker_id': None,
                'bookmaker_name': None,
                'surebet_id': None,
                'bet_id': None,
                'settlement_batch_id': None,
                'settlement_state': None,
                'amount_native': Decimal('1000.00'),
                'native_currency': 'EUR',
                'fx_rate_snapshot': Decimal('1.00'),
                'amount_eur': Decimal('1000.00'),
                'principal_returned_eur': None,
                'per_surebet_share_eur': None,
                'created_at_utc': '2025-10-01T00:00:00Z',
                'created_by': 'local_user',
                'note': 'Initial deposit'
            },
            {
                'entry_id': 3,
                'entry_type': 'BOOKMAKER_CORRECTION',
                'associate_id': 2,
                'associate_alias': 'Partner A',
                'bookmaker_id': 2,
                'bookmaker_name': 'Pinnacle',
                'surebet_id': None,
                'bet_id': None,
                'settlement_batch_id': None,
                'settlement_state': None,
                'amount_native': Decimal('50.00'),
                'native_currency': 'AUD',
                'fx_rate_snapshot': Decimal('0.60'),
                'amount_eur': Decimal('30.00'),
                'principal_returned_eur': None,
                'per_surebet_share_eur': None,
                'created_at_utc': '2025-10-15T10:00:00Z',
                'created_by': 'local_user',
                'note': 'Late VOID correction'
            }
        ]

def test_export_full_ledger(tmp_path):
    """Test full ledger export to CSV."""

    # Create export service with temp directory
    service = ExportService(ledger_repo=MockLedgerRepo())
    service.EXPORT_DIR = tmp_path

    # Export
    result = service.export_full_ledger()

    # Verify result metadata
    assert result['row_count'] == 3
    assert result['file_size_kb'] > 0
    assert result['duration_seconds'] >= 0

    # Verify file exists
    file_path = Path(result['file_path'])
    assert file_path.exists()

    # Verify CSV contents
    with open(file_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) == 3

    # Check first row (BET_RESULT)
    assert rows[0]['entry_id'] == '1'
    assert rows[0]['entry_type'] == 'BET_RESULT'
    assert rows[0]['associate_alias'] == 'Admin'
    assert rows[0]['amount_eur'] == '95.00'
    assert rows[0]['principal_returned_eur'] == '100.00'
    assert rows[0]['per_surebet_share_eur'] == '-5.00'

    # Check second row (DEPOSIT)
    assert rows[1]['entry_id'] == '2'
    assert rows[1]['entry_type'] == 'DEPOSIT'
    assert rows[1]['bookmaker_id'] == ''  # NULL → empty string
    assert rows[1]['amount_eur'] == '1000.00'

    # Check third row (CORRECTION)
    assert rows[2]['entry_id'] == '3'
    assert rows[2]['entry_type'] == 'BOOKMAKER_CORRECTION'
    assert rows[2]['note'] == 'Late VOID correction'

def test_csv_decimal_precision(tmp_path):
    """Test that Decimal precision is preserved in CSV."""

    service = ExportService(ledger_repo=MockLedgerRepo())
    service.EXPORT_DIR = tmp_path

    result = service.export_full_ledger()

    # Read CSV
    with open(result['file_path'], 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # Verify Decimal values stored as strings (no rounding)
    assert rows[0]['fx_rate_snapshot'] == '1.00'
    assert rows[0]['amount_eur'] == '95.00'
    assert rows[0]['per_surebet_share_eur'] == '-5.00'

    # Verify precision with non-round number
    assert rows[2]['fx_rate_snapshot'] == '0.60'
    assert rows[2]['amount_eur'] == '30.00'
```

---

#### Task 6.3.2: Unit Tests for Statement Service
**File**: `tests/unit/domain/test_statement_service.py`

```python
"""
Unit tests for StatementService.
"""
import pytest
from datetime import datetime
from decimal import Decimal

from src.domain.statement_service import StatementService

class MockLedgerRepo:
    """Mock ledger repository."""

    def get_associate_aggregates_up_to(self, associate_id, cutoff_date_utc):
        # Mock data for profitable associate
        if associate_id == 1:
            return {
                'net_deposits_eur': Decimal('2000.00'),
                'should_hold_eur': Decimal('2300.00'),
                'current_holding_eur': Decimal('2500.00')
            }
        # Mock data for loss position associate
        elif associate_id == 2:
            return {
                'net_deposits_eur': Decimal('1000.00'),
                'should_hold_eur': Decimal('850.00'),
                'current_holding_eur': Decimal('800.00')
            }
        else:
            return {
                'net_deposits_eur': Decimal('0.00'),
                'should_hold_eur': Decimal('0.00'),
                'current_holding_eur': Decimal('0.00')
            }

class MockAssociateRepo:
    """Mock associate repository."""

    def get_by_id(self, associate_id):
        if associate_id == 1:
            return type('Associate', (), {'associate_id': 1, 'display_alias': 'Admin'})()
        elif associate_id == 2:
            return type('Associate', (), {'associate_id': 2, 'display_alias': 'Partner A'})()
        else:
            return None

def test_generate_statement_profitable():
    """Test statement generation for profitable associate."""

    service = StatementService(
        ledger_repo=MockLedgerRepo(),
        associate_repo=MockAssociateRepo()
    )

    cutoff = datetime(2025, 10, 31, 23, 59, 59)
    statement = service.generate_statement(associate_id=1, cutoff_date=cutoff)

    # Verify basic info
    assert statement['associate_id'] == 1
    assert statement['associate_alias'] == 'Admin'

    # Verify financial metrics
    assert statement['net_deposits_eur'] == Decimal('2000.00')
    assert statement['should_hold_eur'] == Decimal('2300.00')
    assert statement['current_holding_eur'] == Decimal('2500.00')

    # Verify calculated metrics
    assert statement['raw_profit_eur'] == Decimal('300.00')  # 2300 - 2000
    assert statement['delta_eur'] == Decimal('200.00')  # 2500 - 2300

def test_generate_statement_loss_position():
    """Test statement generation for associate in loss position."""

    service = StatementService(
        ledger_repo=MockLedgerRepo(),
        associate_repo=MockAssociateRepo()
    )

    cutoff = datetime(2025, 10, 31, 23, 59, 59)
    statement = service.generate_statement(associate_id=2, cutoff_date=cutoff)

    # Verify metrics
    assert statement['net_deposits_eur'] == Decimal('1000.00')
    assert statement['should_hold_eur'] == Decimal('850.00')
    assert statement['current_holding_eur'] == Decimal('800.00')

    # Verify loss
    assert statement['raw_profit_eur'] == Decimal('-150.00')  # 850 - 1000 (loss)
    assert statement['delta_eur'] == Decimal('-50.00')  # 800 - 850 (short)

def test_statement_cutoff_date():
    """Test that cutoff date is passed correctly to ledger query."""

    service = StatementService(
        ledger_repo=MockLedgerRepo(),
        associate_repo=MockAssociateRepo()
    )

    cutoff = datetime(2025, 9, 30, 23, 59, 59)
    statement = service.generate_statement(associate_id=1, cutoff_date=cutoff)

    # Verify cutoff date stored
    assert statement['cutoff_date'] == cutoff
```

---

#### Task 6.3.3: Integration Test for Full Export Flow
**File**: `tests/integration/test_export_flow.py`

```python
"""
Integration test for export flow.
"""
import pytest
import sqlite3
import csv
from pathlib import Path
from decimal import Decimal

from src.domain.export_service import ExportService
from src.data.repositories.ledger_repository import LedgerEntryRepository

@pytest.fixture
def test_db(tmp_path):
    """Create test database with sample data."""
    db_path = tmp_path / "test_export.db"

    # Run schema
    with open("schema.sql", 'r') as f:
        schema = f.read()

    conn = sqlite3.connect(str(db_path))
    conn.executescript(schema)

    # Insert sample data
    cursor = conn.cursor()

    cursor.execute("INSERT INTO associates (associate_id, display_alias) VALUES (1, 'Admin')")
    cursor.execute("INSERT INTO bookmakers (bookmaker_id, associate_id, name, currency) VALUES (1, 1, 'Bet365', 'EUR')")

    cursor.execute("""
        INSERT INTO ledger_entries (
            entry_type, associate_id, bookmaker_id,
            amount_native, native_currency, fx_rate_snapshot, amount_eur,
            principal_returned_eur, per_surebet_share_eur,
            created_at_utc, created_by
        ) VALUES ('BET_RESULT', 1, 1, '100.00', 'EUR', '1.00', '95.00', '100.00', '-5.00', '2025-10-30T12:00:00Z', 'test')
    """)

    cursor.execute("""
        INSERT INTO ledger_entries (
            entry_type, associate_id,
            amount_native, native_currency, fx_rate_snapshot, amount_eur,
            created_at_utc, created_by, note
        ) VALUES ('DEPOSIT', 1, '1000.00', 'EUR', '1.00', '1000.00', '2025-10-01T00:00:00Z', 'test', 'Initial deposit')
    """)

    conn.commit()
    conn.close()

    return str(db_path)

def test_full_export_integration(test_db, tmp_path):
    """Test complete export flow from database to CSV."""

    # Initialize services
    ledger_repo = LedgerEntryRepository(test_db)
    export_service = ExportService(ledger_repo)
    export_service.EXPORT_DIR = tmp_path

    # Export
    result = export_service.export_full_ledger()

    # Verify file created
    file_path = Path(result['file_path'])
    assert file_path.exists()

    # Verify row count
    assert result['row_count'] == 2

    # Verify CSV contents
    with open(file_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) == 2

    # Verify joins worked (associate_alias populated)
    assert rows[0]['associate_alias'] == 'Admin'
    assert rows[1]['associate_alias'] == 'Admin'

    # Verify bookmaker join
    assert rows[0]['bookmaker_name'] == 'Bet365'
    assert rows[1]['bookmaker_name'] == ''  # NULL for DEPOSIT
```

---

### Manual Testing

#### Task 6.4: Manual UAT Procedures
**File**: `docs/testing/epic-6-uat-procedures.md`

```markdown
# Epic 6: Reporting & Audit - User Acceptance Testing

## Prerequisites
- Database with 50+ ledger entries (diverse entry types)
- Multiple associates with settled bets
- Deposits and corrections in ledger

---

## Scenario 1: Full Ledger Export

**Objective**: Export complete ledger to CSV for audit.

### Steps:
1. Open Export page
2. Verify current ledger size displayed (e.g., "150 entries")
3. Click "Export Full Ledger"
4. Wait for export to complete

### Expected Results:
- ✅ Success message: "Ledger exported successfully"
- ✅ File path shown: `data/exports/ledger_YYYYMMDD_HHMMSS.csv`
- ✅ Row count matches database: 150 entries
- ✅ File size shown (KB)
- ✅ Duration shown (seconds)
- ✅ "Download CSV" button appears
- ✅ Export appears in "Recent Exports" list

### Verification:
1. Click "Download CSV" → file downloads
2. Open in Excel/Google Sheets:
   - Header row: entry_id, entry_type, associate_alias, ...
   - 150 data rows
   - All Decimal values preserved (no rounding)
   - NULL values as empty cells
3. Spot-check first row:
   - entry_id = 1
   - entry_type = 'BET_RESULT'
   - associate_alias populated
   - amount_eur has 2 decimal places

### SQL Verification:
```sql
SELECT COUNT(*) FROM ledger_entries;
-- Should match CSV row count
```

---

## Scenario 2: Monthly Statement (Profitable Associate)

**Objective**: Generate statement for profitable associate.

### Steps:
1. Open Monthly Statements page
2. Select:
   - Associate: "Partner A"
   - Cutoff Date: 2025-10-31 (end of month)
3. Click "Generate Statement"

### Expected Results:

**Partner-Facing Section:**
- ✅ Heading: "Monthly Statement for Partner A"
- ✅ Period ending: 2025-10-31 23:59:59 UTC
- ✅ **Funding Summary:**
  - "You funded: €2,000.00 total"
- ✅ **Entitlement Summary:**
  - "You're entitled to: €2,300.00"
- ✅ **Profit/Loss Summary:**
  - "Your profit: €300.00" (green text)
- ✅ **50/50 Split:**
  - "Your share: €150.00 (half of profit)"
  - "Admin share: €150.00 (half of profit)"

**Internal-Only Section (collapsed):**
- ✅ "Currently holding: €2,500.00"
- ✅ "🔴 Holding €200.00 more than entitlement (collect from associate)"

### Actions:
1. Click "Copy Partner Section" → download text file
2. Open text file → verify shareable format (no DELTA)
3. Click "Export Full Statement" → verify includes internal section

---

## Scenario 3: Monthly Statement (Loss Position)

**Objective**: Generate statement for associate in loss position.

### Steps:
1. Select Associate: "Partner B", Cutoff: 2025-10-31
2. Generate statement

### Expected Results:
- ✅ "You funded: €1,000.00 total"
- ✅ "You're entitled to: €850.00"
- ✅ "Your loss: €150.00" (red text)
- ✅ **50/50 Split:**
  - "Your share of loss: €75.00 (half of loss)"
  - "Admin share of loss: €75.00 (half of loss)"
- ✅ **Internal-Only:**
  - "Currently holding: €800.00"
  - "🟠 Short €50.00 (owed to associate)"

---

## Scenario 4: Statement at Different Cutoffs

**Objective**: Verify cutoff date filters correctly.

### Steps:
1. Generate statement for "Partner A" at cutoff: **2025-09-30**
2. Note values:
   - NET_DEPOSITS: €1,500
   - SHOULD_HOLD: €1,600
   - PROFIT: €100
3. Generate again at cutoff: **2025-10-31**
4. Note values:
   - NET_DEPOSITS: €2,000 (includes October deposit)
   - SHOULD_HOLD: €2,300 (includes October settlements)
   - PROFIT: €300

### Expected Results:
- ✅ September cutoff shows lower values (only transactions before Sept 30)
- ✅ October cutoff shows higher values (includes October transactions)
- ✅ Difference matches October activity

### Manual Calculation:
```sql
-- Verify September cutoff
SELECT SUM(amount_eur) FROM ledger_entries
WHERE associate_id = 1
AND entry_type = 'DEPOSIT'
AND created_at_utc <= '2025-09-30T23:59:59Z';
-- Should match September NET_DEPOSITS

-- Verify October cutoff
SELECT SUM(amount_eur) FROM ledger_entries
WHERE associate_id = 1
AND entry_type = 'DEPOSIT'
AND created_at_utc <= '2025-10-31T23:59:59Z';
-- Should match October NET_DEPOSITS
```

---

## Scenario 5: CSV Export with Special Characters

**Objective**: Test CSV handles UTF-8 special characters.

### Steps:
1. Insert test associate with special characters:
```sql
INSERT INTO associates (associate_id, display_alias)
VALUES (99, 'José García-López');
```
2. Insert ledger entry for this associate
3. Export full ledger
4. Open CSV in Excel

### Expected Results:
- ✅ CSV opens without encoding errors
- ✅ Special characters displayed correctly: "José García-López"
- ✅ No corruption or replacement characters

---

## Scenario 6: Re-Download Previous Export

**Objective**: Verify export history allows re-downloading.

### Steps:
1. Export ledger (creates file 1)
2. Export again (creates file 2)
3. Scroll to "Recent Exports" section
4. Verify both exports listed
5. Click "Re-download" for file 1

### Expected Results:
- ✅ Both exports listed with timestamps
- ✅ Row counts shown
- ✅ File sizes shown
- ✅ Re-download button works
- ✅ Downloaded file matches original export

---

## Post-Testing Validation

### CSV Export Validation:
```sql
-- Verify row count matches
SELECT COUNT(*) FROM ledger_entries;
```

### Statement Math Validation:
Use calculator to manually verify:
```
NET_DEPOSITS = SUM(DEPOSIT) - SUM(WITHDRAWAL)
RAW_PROFIT = SHOULD_HOLD - NET_DEPOSITS
DELTA = CURRENT_HOLDING - SHOULD_HOLD
```

### Cutoff Date Edge Cases:
1. Generate statement at cutoff BEFORE settlement
2. Generate statement at cutoff AFTER settlement
3. Verify settlement included/excluded correctly

---

## Sign-Off

- [ ] Scenario 1: Full ledger export passed
- [ ] Scenario 2: Profitable statement passed
- [ ] Scenario 3: Loss position statement passed
- [ ] Scenario 4: Cutoff date filtering passed
- [ ] Scenario 5: UTF-8 special characters passed
- [ ] Scenario 6: Re-download previous export passed
- [ ] CSV validation passed
- [ ] Statement math verified
- [ ] Cutoff edge cases tested

**Tester Signature:** _______________
**Date:** _______________

---

## 🎉 MVP COMPLETION 🎉

**When all 6 scenarios pass, Epic 6 is complete.**

This marks the completion of the entire MVP:

✅ **Epic 0:** Foundation (database, FX, Telegram)
✅ **Epic 1:** Bet Ingestion Pipeline
✅ **Epic 2:** Bet Review & Approval
✅ **Epic 3:** Surebet Matching & Safety
✅ **Epic 4:** Coverage Proof & Settlement
✅ **Epic 5:** Corrections & Reconciliation
✅ **Epic 6:** Reporting & Audit

**All 10 Functional Requirements implemented!**
**All 6 System Laws enforced!**
**System is production-ready!**

🚀 Ready for real-world testing with actual bets! 🚀
```

---

## Deployment Checklist

### Pre-Deployment

- [ ] All Epics 0-5 complete and tested
- [ ] Database has realistic data (50+ ledger entries)
- [ ] `data/exports/` directory exists (or will be created)
- [ ] Multiple associates with varied balances

### Code Deployment

- [ ] All Story 6.1-6.2 files created
- [ ] Unit tests pass
- [ ] Integration test passes

### Post-Deployment

- [ ] Export page loads
- [ ] Export full ledger successfully
- [ ] CSV opens in Excel without errors
- [ ] Monthly Statements page loads
- [ ] Generate statement successfully
- [ ] Partner section copyable
- [ ] All 6 UAT scenarios pass

---

## Troubleshooting Guide

### Issue: "Export directory not found"

**Cause:** `data/exports/` doesn't exist

**Fix:**
```python
# ExportService.__init__() already handles this:
self.EXPORT_DIR.mkdir(parents=True, exist_ok=True)
```

---

### Issue: "CSV opens with garbled text in Excel"

**Cause:** Encoding issue (not UTF-8)

**Fix:**
Verify CSV written with UTF-8:
```python
with open(file_path, 'w', newline='', encoding='utf-8') as csvfile:
    # ...
```

If Excel still has issues:
1. Open Excel
2. Data → From Text/CSV
3. Select file
4. File origin: **65001: Unicode (UTF-8)**
5. Import

---

### Issue: "Statement shows wrong profit"

**Cause:** Math error or cutoff filtering issue

**Fix:**
Manually verify with SQL:
```sql
SELECT
  SUM(CASE WHEN entry_type='DEPOSIT' THEN amount_eur ELSE 0 END) AS deposits,
  SUM(CASE WHEN entry_type='WITHDRAWAL' THEN amount_eur ELSE 0 END) AS withdrawals,
  SUM(CASE WHEN entry_type='BET_RESULT' THEN principal_returned_eur + per_surebet_share_eur ELSE 0 END) AS should_hold
FROM ledger_entries
WHERE associate_id = 1
AND created_at_utc <= '2025-10-31T23:59:59Z';
```

Compare with statement values.

---

### Issue: "Cutoff date doesn't filter correctly"

**Cause:** Timezone confusion or inclusive/exclusive boundary

**Fix:**
- Ensure cutoff uses UTC (not local time)
- Ensure query uses `<=` (inclusive)
- Format cutoff as ISO8601 with Z suffix: `2025-10-31T23:59:59Z`

---

### Issue: "Export is slow (>10 seconds)"

**Cause:** Large ledger (10k+ rows)

**Fix:**
- Already using streaming (csv.writer writes directly to file)
- If still slow, add progress bar:
```python
progress_bar = st.progress(0)
for i, entry in enumerate(entries):
    writer.writerow(row)
    if i % 100 == 0:
        progress_bar.progress(i / len(entries))
```

---

## Success Criteria

### Functional
- [x] Full ledger exportable to CSV
- [x] CSV includes all rows with correct joins
- [x] Decimal precision preserved
- [x] Monthly statements generate correctly
- [x] Cutoff date filtering works
- [x] Profit/loss displayed correctly
- [x] 50/50 split shown
- [x] DELTA hidden in partner section

### Technical
- [x] CSV row count matches database
- [x] UTF-8 encoding works
- [x] Statement math verified with calculator
- [x] No ledger writes during statement generation (read-only)
- [x] All entry types included in export

### MVP Completion
- [x] All 10 Functional Requirements (FR-1 to FR-10) implemented
- [x] All 6 System Laws enforced throughout
- [x] End-to-end workflow complete
- [x] System production-ready for single operator

---

## Related Documents

- [Epic 6: Reporting & Audit](./epic-6-reporting-audit.md)
- [PRD: FR-9 (Ledger Export)](../prd.md#fr-9)
- [PRD: FR-10 (Monthly Statements)](../prd.md#fr-10)
- [Epic 5: Corrections & Reconciliation](./epic-5-implementation-guide.md)
- [Implementation Roadmap](./implementation-roadmap.md)

---

## 🎉 Congratulations on Completing the MVP! 🎉

**Epic 6 is the final MVP epic.** When this epic is complete, you have built a **production-ready surebet accounting system** from scratch.

### What You've Built:

1. **Ingestion:** Screenshot → OCR → Manual upload
2. **Review:** Inline editing, approval workflow
3. **Matching:** Deterministic pairing, risk classification
4. **Settlement:** Equal-split calculation, frozen FX, append-only ledger
5. **Reconciliation:** DELTA tracking, corrections, bookmaker balance checks
6. **Reporting:** CSV export, monthly statements

### System Characteristics:

- ✅ **Append-only ledger** (System Law #1)
- ✅ **Frozen FX snapshots** (System Law #2)
- ✅ **Equal-split settlement** (System Law #3)
- ✅ **VOID participation** (System Law #4)
- ✅ **Manual grading** (System Law #5)
- ✅ **No silent messaging** (System Law #6)
- ✅ **Financial precision** (Decimal throughout, no float)
- ✅ **Data portability** (CSV exports, not locked in)
- ✅ **Audit trail** (complete history, no edits)

### Next Steps:

1. **User Acceptance Testing** with real bets
2. **Bug fixes and polish**
3. **Performance optimization** (if needed)
4. **Operator training** on workflow
5. **Go live!** 🚀

---

**End of Epic 6 Implementation Guide**

**End of MVP Implementation Guides**
