# Epic 5: Corrections & Reconciliation - Implementation Guide

**Epic Reference:** [Epic 5: Corrections & Reconciliation](./epic-5-corrections-reconciliation.md)
**Status:** Ready for Implementation
**Estimated Duration:** 5-6 days
**Developer:** Full-Stack

---

## Overview

Epic 5 implements **forward-only error correction** and **real-time financial health monitoring**. It provides:
1. **Post-Settlement Correction Interface** (Story 5.1): Fix errors without breaking ledger immutability
2. **Reconciliation Dashboard** (Story 5.2): See who's overholding vs. who's short
3. **Bookmaker Balance Drilldown** (Story 5.3): Compare modeled vs. reported balances
4. **Pending Funding Events** (Story 5.4): Accept/reject deposits and withdrawals
5. **Associate Operations Hub** (Story 5.5): Manage associates, bookmakers, balances, and funding from one page

**CRITICAL**: All corrections are **forward-only** (System Law #1 preserved). No UPDATE or DELETE on existing ledger entries.

**Architecture Principles**:
- Corrections are NEW ledger entries (entry_type = 'BOOKMAKER_CORRECTION')
- DELTA = CURRENT_HOLDING_EUR - SHOULD_HOLD_EUR reveals who owes whom
- FX rates frozen at correction time (not historical)
- All math uses Decimal precision (no float)

---

## Prerequisites

Before starting Epic 5, ensure:
- [x] **Epic 0** complete: Database schema, FX utilities
- [x] **Epic 4** complete: Settlement with BET_RESULT ledger entries
- At least 2 settled surebets in database
- FX rates available for all currencies

**Database State Required**:
- `ledger_entries` table with BET_RESULT rows
- `associates` and `bookmakers` tables populated
- `fx_rates_daily` has current rates

---

## Task Breakdown

### Story 5.1: Post-Settlement Correction Interface

**Goal**: Apply forward-only corrections for late VOIDs, grading errors, or bookmaker deductions.

#### Task 5.1.1: Correction Form Component
**File**: `src/streamlit_app/pages/05_Corrections.py`

```python
"""
Corrections page for applying forward-only ledger adjustments.
"""
import streamlit as st
from decimal import Decimal
from typing import Optional

from src.data.database import get_db_connection
from src.data.repositories.associate_repository import AssociateRepository
from src.data.repositories.bookmaker_repository import BookmakersRepository
from src.data.repositories.ledger_repository import LedgerEntryRepository
from src.domain.correction_service import CorrectionService
from src.streamlit_app.components.corrections.correction_form import render_correction_form
from src.streamlit_app.components.corrections.corrections_list import render_corrections_list

st.set_page_config(
    page_title="Corrections - Surebet Accounting",
    page_icon="🔧",
    layout="wide"
)

st.title("🔧 Post-Settlement Corrections")
st.caption("Apply forward-only corrections without editing history")

# Info banner
st.info("""
**Forward-Only Corrections**: All corrections create NEW ledger entries.
Historical entries are NEVER edited or deleted (System Law #1).

- **Positive amount**: Increases associate's holdings (e.g., late refund, voided bet)
- **Negative amount**: Decreases holdings (e.g., bookmaker fee, grading error)
""")

# Initialize repositories and services
db_path = "data/surebet.db"
associate_repo = AssociateRepository(db_path)
bookmaker_repo = BookmakersRepository(db_path)
ledger_repo = LedgerEntryRepository(db_path)
correction_service = CorrectionService(ledger_repo, associate_repo, bookmaker_repo)

# Layout: Form (top) + History (bottom)
st.subheader("Apply New Correction")

# Render correction form
render_correction_form(
    correction_service=correction_service,
    associate_repo=associate_repo,
    bookmaker_repo=bookmaker_repo
)

st.divider()

# Render corrections history
st.subheader("Recent Corrections (Last 30 Days)")
render_corrections_list(ledger_repo)
```

---

#### Task 5.1.2: Correction Form Component
**File**: `src/streamlit_app/components/corrections/correction_form.py`

```python
"""
Correction form component.
"""
import streamlit as st
from decimal import Decimal, InvalidOperation
from typing import Optional

from src.data.repositories.associate_repository import AssociateRepository
from src.data.repositories.bookmaker_repository import BookmakersRepository
from src.domain.correction_service import CorrectionService

SUPPORTED_CURRENCIES = ["EUR", "USD", "GBP", "AUD", "CAD"]

def render_correction_form(
    correction_service: CorrectionService,
    associate_repo: AssociateRepository,
    bookmaker_repo: BookmakersRepository
):
    """Render correction entry form."""

    # Load associates
    associates = associate_repo.get_all()
    if not associates:
        st.warning("No associates found. Please create associates first.")
        return

    associate_options = {a.display_alias: a.associate_id for a in associates}

    with st.form("correction_form", clear_on_submit=True):
        col1, col2 = st.columns(2)

        with col1:
            # Associate selector
            selected_alias = st.selectbox(
                "Associate",
                options=list(associate_options.keys()),
                help="Select the associate to apply correction for"
            )
            associate_id = associate_options[selected_alias]

            # Load bookmakers for selected associate
            bookmakers = bookmaker_repo.get_by_associate(associate_id)
            if not bookmakers:
                st.warning(f"No bookmakers found for {selected_alias}")
                bookmaker_id = None
            else:
                bookmaker_options = {b.name: b.bookmaker_id for b in bookmakers}
                selected_bookmaker = st.selectbox(
                    "Bookmaker",
                    options=list(bookmaker_options.keys()),
                    help="Select the bookmaker account for this correction"
                )
                bookmaker_id = bookmaker_options[selected_bookmaker]

        with col2:
            # Amount input
            amount_str = st.text_input(
                "Amount (Native Currency)",
                value="",
                help="Positive = increases holdings (refund), Negative = decreases (deduction)"
            )

            # Currency selector
            currency = st.selectbox(
                "Currency",
                options=SUPPORTED_CURRENCIES,
                help="Currency for the correction amount"
            )

        # Note field (full width)
        note = st.text_area(
            "Note (Required)",
            value="",
            height=100,
            help="Explanation for this correction (e.g., 'Late VOID for Bet #123')"
        )

        # Submit button
        submitted = st.form_submit_button("✅ Apply Correction", type="primary")

        if submitted:
            # Validation
            errors = []

            if not bookmaker_id:
                errors.append("Bookmaker is required")

            if not amount_str or amount_str.strip() == "":
                errors.append("Amount is required")
            else:
                try:
                    amount_native = Decimal(amount_str.strip())
                    if amount_native == 0:
                        errors.append("Amount cannot be zero")
                except InvalidOperation:
                    errors.append("Amount must be a valid number")
                    amount_native = None

            if not note or note.strip() == "":
                errors.append("Note is required")

            if errors:
                for error in errors:
                    st.error(f"❌ {error}")
            else:
                # Apply correction
                try:
                    entry_id = correction_service.apply_correction(
                        associate_id=associate_id,
                        bookmaker_id=bookmaker_id,
                        amount_native=amount_native,
                        native_currency=currency,
                        note=note.strip()
                    )

                    st.success(f"✅ Correction applied successfully! Ledger entry #{entry_id} created.")
                    st.balloons()
                    st.rerun()

                except Exception as e:
                    st.error(f"❌ Failed to apply correction: {e}")
```

---

#### Task 5.1.3: Corrections List Component
**File**: `src/streamlit_app/components/corrections/corrections_list.py`

```python
"""
Recent corrections list component.
"""
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

from src.data.repositories.ledger_repository import LedgerEntryRepository

def render_corrections_list(ledger_repo: LedgerEntryRepository):
    """Render list of recent corrections."""

    # Load corrections from last 30 days
    cutoff_date = (datetime.utcnow() - timedelta(days=30)).isoformat()
    corrections = ledger_repo.get_corrections_since(cutoff_date)

    if not corrections:
        st.info("No corrections in the last 30 days")
        return

    # Convert to DataFrame
    df_data = []
    for corr in corrections:
        # Parse timestamp
        try:
            ts = datetime.fromisoformat(corr.created_at_utc.replace('Z', '+00:00'))
            ts_display = ts.strftime("%Y-%m-%d %H:%M UTC")
        except:
            ts_display = corr.created_at_utc

        # Format amounts
        amount_native_str = f"{corr.amount_native} {corr.native_currency}" if corr.amount_native else "N/A"
        amount_eur_str = f"€{corr.amount_eur}"

        df_data.append({
            "Entry ID": corr.entry_id,
            "Timestamp": ts_display,
            "Associate": corr.associate_id,  # TODO: Join with associate name
            "Bookmaker": corr.bookmaker_id,  # TODO: Join with bookmaker name
            "Amount (Native)": amount_native_str,
            "Amount (EUR)": amount_eur_str,
            "FX Rate": corr.fx_rate_snapshot,
            "Note": corr.note or ""
        })

    df = pd.DataFrame(df_data)

    # Display table
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Entry ID": st.column_config.NumberColumn(width="small"),
            "Timestamp": st.column_config.TextColumn(width="medium"),
            "Note": st.column_config.TextColumn(width="large")
        }
    )

    st.caption(f"**{len(corrections)} corrections** in last 30 days")
```

---

#### Task 5.1.4: Correction Service
**File**: `src/domain/correction_service.py`

```python
"""
Correction service for forward-only ledger adjustments.
"""
import logging
from decimal import Decimal
from datetime import datetime

from src.data.repositories.ledger_repository import LedgerEntryRepository
from src.data.repositories.associate_repository import AssociateRepository
from src.data.repositories.bookmaker_repository import BookmakersRepository
from src.utils.fx_utils import get_fx_rate
from src.utils.timestamp_utils import format_timestamp_utc

logger = logging.getLogger(__name__)

class CorrectionService:
    """Service for applying forward-only corrections."""

    def __init__(
        self,
        ledger_repo: LedgerEntryRepository,
        associate_repo: AssociateRepository,
        bookmaker_repo: BookmakersRepository
    ):
        self.ledger_repo = ledger_repo
        self.associate_repo = associate_repo
        self.bookmaker_repo = bookmaker_repo

    def apply_correction(
        self,
        associate_id: int,
        bookmaker_id: int,
        amount_native: Decimal,
        native_currency: str,
        note: str
    ) -> int:
        """
        Apply forward-only correction by creating new ledger entry.

        CRITICAL: This does NOT edit existing entries. Creates new entry_type='BOOKMAKER_CORRECTION'.

        Args:
            associate_id: Associate to apply correction for
            bookmaker_id: Bookmaker account
            amount_native: Amount in native currency (positive = increase, negative = decrease)
            native_currency: Currency code (EUR, USD, GBP, etc.)
            note: Explanation for correction

        Returns:
            entry_id of created ledger entry

        Raises:
            ValueError: If validation fails
        """
        # Validation
        if amount_native == 0:
            raise ValueError("Correction amount cannot be zero")

        # Verify associate exists
        associate = self.associate_repo.get_by_id(associate_id)
        if not associate:
            raise ValueError(f"Associate {associate_id} not found")

        # Verify bookmaker exists and belongs to associate
        bookmaker = self.bookmaker_repo.get_by_id(bookmaker_id)
        if not bookmaker:
            raise ValueError(f"Bookmaker {bookmaker_id} not found")
        if bookmaker.associate_id != associate_id:
            raise ValueError(
                f"Bookmaker {bookmaker_id} does not belong to associate {associate_id}"
            )

        # Get current FX rate (frozen at this moment)
        fx_rate = get_fx_rate(native_currency, datetime.utcnow().date())

        # Calculate EUR amount
        amount_eur = (amount_native * fx_rate).quantize(Decimal("0.01"))

        # Create ledger entry
        timestamp_utc = format_timestamp_utc()

        entry_id = self.ledger_repo.create_correction(
            associate_id=associate_id,
            bookmaker_id=bookmaker_id,
            amount_native=amount_native,
            native_currency=native_currency,
            fx_rate_snapshot=fx_rate,
            amount_eur=amount_eur,
            created_at_utc=timestamp_utc,
            created_by="local_user",
            note=note
        )

        logger.info(
            f"Correction applied: Entry #{entry_id}, "
            f"Associate {associate_id}, Bookmaker {bookmaker_id}, "
            f"Amount: {amount_native} {native_currency} (€{amount_eur})"
        )

        return entry_id
```

---

#### Task 5.1.5: Extend Ledger Repository (Corrections)
**File**: `src/data/repositories/ledger_repository.py` (add methods)

```python
# Add to existing LedgerEntryRepository class:

def create_correction(
    self,
    associate_id: int,
    bookmaker_id: int,
    amount_native: Decimal,
    native_currency: str,
    fx_rate_snapshot: Decimal,
    amount_eur: Decimal,
    created_at_utc: str,
    created_by: str,
    note: str
) -> int:
    """
    Create BOOKMAKER_CORRECTION ledger entry.

    Returns:
        entry_id of created entry
    """
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO ledger_entries (
            entry_type, associate_id, bookmaker_id,
            surebet_id, bet_id, settlement_batch_id, settlement_state,
            amount_native, native_currency,
            fx_rate_snapshot, amount_eur,
            principal_returned_eur, per_surebet_share_eur,
            created_at_utc, created_by, note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        "BOOKMAKER_CORRECTION",
        associate_id,
        bookmaker_id,
        None,  # surebet_id
        None,  # bet_id
        None,  # settlement_batch_id
        None,  # settlement_state
        str(amount_native),
        native_currency,
        str(fx_rate_snapshot),
        str(amount_eur),
        None,  # principal_returned_eur
        None,  # per_surebet_share_eur
        created_at_utc,
        created_by,
        note
    ))

    entry_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return entry_id

def get_corrections_since(self, cutoff_date_utc: str) -> List[LedgerEntry]:
    """Get all corrections since cutoff date."""
    conn = sqlite3.connect(self.db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM ledger_entries
        WHERE entry_type = 'BOOKMAKER_CORRECTION'
        AND created_at_utc >= ?
        ORDER BY created_at_utc DESC
    """, (cutoff_date_utc,))

    rows = cursor.fetchall()
    conn.close()

    return [self._row_to_entry(dict(row)) for row in rows]

def create_funding_event(
    self,
    entry_type: str,  # 'DEPOSIT' or 'WITHDRAWAL'
    associate_id: int,
    amount_native: Decimal,
    native_currency: str,
    fx_rate_snapshot: Decimal,
    amount_eur: Decimal,
    created_at_utc: str,
    created_by: str,
    note: Optional[str] = None
) -> int:
    """
    Create DEPOSIT or WITHDRAWAL ledger entry.

    Returns:
        entry_id of created entry
    """
    if entry_type not in ['DEPOSIT', 'WITHDRAWAL']:
        raise ValueError(f"Invalid entry_type: {entry_type}")

    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO ledger_entries (
            entry_type, associate_id, bookmaker_id,
            surebet_id, bet_id, settlement_batch_id, settlement_state,
            amount_native, native_currency,
            fx_rate_snapshot, amount_eur,
            principal_returned_eur, per_surebet_share_eur,
            created_at_utc, created_by, note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        entry_type,
        associate_id,
        None,  # bookmaker_id (funding is associate-level)
        None,  # surebet_id
        None,  # bet_id
        None,  # settlement_batch_id
        None,  # settlement_state
        str(amount_native),
        native_currency,
        str(fx_rate_snapshot),
        str(amount_eur),
        None,  # principal_returned_eur
        None,  # per_surebet_share_eur
        created_at_utc,
        created_by,
        note
    ))

    entry_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return entry_id
```

---

### Story 5.2: Reconciliation Dashboard (Associate View)

**Goal**: Show NET_DEPOSITS, SHOULD_HOLD, CURRENT_HOLDING, DELTA for each associate.

#### Task 5.2.1: Reconciliation Page
**File**: `src/streamlit_app/pages/06_Reconciliation.py`

```python
"""
Reconciliation dashboard showing financial health per associate.
"""
import streamlit as st

from src.data.repositories.ledger_repository import LedgerEntryRepository
from src.domain.reconciliation_service import ReconciliationService
from src.streamlit_app.components.reconciliation.associate_summary import render_associate_summary
from src.streamlit_app.components.reconciliation.bookmaker_drilldown import render_bookmaker_drilldown

st.set_page_config(
    page_title="Reconciliation - Surebet Accounting",
    page_icon="📊",
    layout="wide"
)

st.title("📊 Reconciliation Dashboard")
st.caption("Financial health: who's overholding vs. who's short")

# Initialize services
db_path = "data/surebet.db"
ledger_repo = LedgerEntryRepository(db_path)
reconciliation_service = ReconciliationService(ledger_repo)

# Refresh button
col1, col2, col3 = st.columns([2, 1, 1])
with col3:
    if st.button("🔄 Refresh", use_container_width=True):
        st.rerun()

st.divider()

# Associate Summary
st.subheader("Associate Summary")
render_associate_summary(reconciliation_service)

st.divider()

# Bookmaker Drilldown
st.subheader("Bookmaker Balance Drilldown")
render_bookmaker_drilldown(reconciliation_service)
```

---

#### Task 5.2.2: Reconciliation Service
**File**: `src/domain/reconciliation_service.py`

```python
"""
Reconciliation service for calculating financial health metrics.
"""
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional

from src.data.repositories.ledger_repository import LedgerEntryRepository

logger = logging.getLogger(__name__)

@dataclass
class AssociateBalance:
    """Financial health for one associate."""
    associate_id: int
    associate_alias: str
    net_deposits_eur: Decimal
    should_hold_eur: Decimal
    current_holding_eur: Decimal
    delta_eur: Decimal
    status: str  # "overholder", "balanced", "short"
    status_icon: str  # 🔴, 🟢, 🟠

@dataclass
class BookmakersBalance:
    """Balance for one bookmaker account."""
    associate_id: int
    associate_alias: str
    bookmaker_id: int
    bookmaker_name: str
    modeled_balance_eur: Decimal
    modeled_balance_native: Optional[Decimal]
    reported_balance_native: Optional[Decimal]
    native_currency: str
    difference_eur: Optional[Decimal]
    difference_native: Optional[Decimal]
    status: str  # "balanced", "minor_mismatch", "major_mismatch"
    status_icon: str  # 🟢, 🟡, 🔴
    checked_at_utc: Optional[str]

class ReconciliationService:
    """Service for calculating reconciliation metrics."""

    DELTA_THRESHOLD_EUR = Decimal("10.00")  # ±€10 is "balanced"
    MINOR_MISMATCH_EUR = Decimal("10.00")
    MAJOR_MISMATCH_EUR = Decimal("50.00")

    def __init__(self, ledger_repo: LedgerEntryRepository):
        self.ledger_repo = ledger_repo

    def get_associate_balances(self) -> List[AssociateBalance]:
        """
        Calculate NET_DEPOSITS, SHOULD_HOLD, CURRENT_HOLDING, DELTA for all associates.

        Returns:
            List of AssociateBalance sorted by DELTA (largest overholders first)
        """
        balances = []

        # Query ledger for all associates
        associate_data = self.ledger_repo.get_associate_aggregates()

        for data in associate_data:
            associate_id = data['associate_id']
            associate_alias = data.get('associate_alias', f'Associate {associate_id}')

            # NET_DEPOSITS_EUR: Sum of DEPOSIT minus WITHDRAWAL
            net_deposits_eur = data.get('net_deposits_eur', Decimal("0.00"))

            # SHOULD_HOLD_EUR: Sum of principal_returned + per_surebet_share from BET_RESULT
            should_hold_eur = data.get('should_hold_eur', Decimal("0.00"))

            # CURRENT_HOLDING_EUR: Sum of amount_eur from all entry types
            current_holding_eur = data.get('current_holding_eur', Decimal("0.00"))

            # DELTA
            delta_eur = current_holding_eur - should_hold_eur

            # Status determination
            if delta_eur > self.DELTA_THRESHOLD_EUR:
                status = "overholder"
                status_icon = "🔴"
            elif delta_eur < -self.DELTA_THRESHOLD_EUR:
                status = "short"
                status_icon = "🟠"
            else:
                status = "balanced"
                status_icon = "🟢"

            balances.append(AssociateBalance(
                associate_id=associate_id,
                associate_alias=associate_alias,
                net_deposits_eur=net_deposits_eur,
                should_hold_eur=should_hold_eur,
                current_holding_eur=current_holding_eur,
                delta_eur=delta_eur,
                status=status,
                status_icon=status_icon
            ))

        # Sort by DELTA descending (largest overholders first)
        balances.sort(key=lambda b: b.delta_eur, reverse=True)

        return balances

    def get_explanation(self, balance: AssociateBalance) -> str:
        """
        Generate human-readable explanation for associate balance.

        Returns:
            Explanation string
        """
        if balance.status == "overholder":
            return (
                f"{balance.associate_alias} is holding €{abs(balance.delta_eur):.2f} more than their entitlement. "
                f"They funded €{balance.net_deposits_eur:.2f} total and are entitled to €{balance.should_hold_eur:.2f}, "
                f"but currently hold €{balance.current_holding_eur:.2f} in bookmaker accounts. "
                f"**Collect €{abs(balance.delta_eur):.2f} from them.**"
            )
        elif balance.status == "short":
            return (
                f"{balance.associate_alias} is short €{abs(balance.delta_eur):.2f}. "
                f"They funded €{balance.net_deposits_eur:.2f} and are entitled to €{balance.should_hold_eur:.2f}, "
                f"but only hold €{balance.current_holding_eur:.2f} in bookmaker accounts. "
                f"**Someone else is holding their €{abs(balance.delta_eur):.2f}.**"
            )
        else:
            return (
                f"{balance.associate_alias} is balanced. "
                f"They funded €{balance.net_deposits_eur:.2f}, are entitled to €{balance.should_hold_eur:.2f}, "
                f"and hold €{balance.current_holding_eur:.2f}. "
                f"Delta: €{balance.delta_eur:.2f} (within threshold)."
            )

    def get_bookmaker_balances(self) -> List[BookmakersBalance]:
        """
        Get modeled vs. reported balances for all bookmaker accounts.

        Returns:
            List of BookmakersBalance sorted by difference (largest first)
        """
        bookmaker_data = self.ledger_repo.get_bookmaker_aggregates()
        balances = []

        for data in bookmaker_data:
            # Status determination
            difference_eur = data.get('difference_eur')

            if difference_eur is None:
                status = "no_check"
                status_icon = "❓"
            elif abs(difference_eur) < self.MINOR_MISMATCH_EUR:
                status = "balanced"
                status_icon = "🟢"
            elif abs(difference_eur) < self.MAJOR_MISMATCH_EUR:
                status = "minor_mismatch"
                status_icon = "🟡"
            else:
                status = "major_mismatch"
                status_icon = "🔴"

            balances.append(BookmakersBalance(
                associate_id=data['associate_id'],
                associate_alias=data.get('associate_alias', f"Associate {data['associate_id']}"),
                bookmaker_id=data['bookmaker_id'],
                bookmaker_name=data.get('bookmaker_name', f"Bookmaker {data['bookmaker_id']}"),
                modeled_balance_eur=data.get('modeled_balance_eur', Decimal("0.00")),
                modeled_balance_native=data.get('modeled_balance_native'),
                reported_balance_native=data.get('reported_balance_native'),
                native_currency=data.get('native_currency', 'EUR'),
                difference_eur=difference_eur,
                difference_native=data.get('difference_native'),
                status=status,
                status_icon=status_icon,
                checked_at_utc=data.get('checked_at_utc')
            ))

        # Sort by absolute difference (largest first)
        balances.sort(
            key=lambda b: abs(b.difference_eur) if b.difference_eur else Decimal("0.00"),
            reverse=True
        )

        return balances
```

---

#### Task 5.2.3: Extend Ledger Repository (Aggregates)
**File**: `src/data/repositories/ledger_repository.py` (add methods)

```python
# Add to existing LedgerEntryRepository class:

def get_associate_aggregates(self) -> List[dict]:
    """
    Get aggregated financial metrics for all associates.

    Returns:
        List of dicts with keys:
        - associate_id
        - associate_alias
        - net_deposits_eur
        - should_hold_eur
        - current_holding_eur
    """
    conn = sqlite3.connect(self.db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            le.associate_id,
            a.display_alias AS associate_alias,

            -- NET_DEPOSITS_EUR
            SUM(CASE WHEN le.entry_type='DEPOSIT' THEN le.amount_eur ELSE 0 END) -
            SUM(CASE WHEN le.entry_type='WITHDRAWAL' THEN ABS(le.amount_eur) ELSE 0 END) AS net_deposits_eur,

            -- SHOULD_HOLD_EUR
            SUM(CASE
                WHEN le.entry_type='BET_RESULT'
                THEN COALESCE(le.principal_returned_eur, 0) + COALESCE(le.per_surebet_share_eur, 0)
                ELSE 0
            END) AS should_hold_eur,

            -- CURRENT_HOLDING_EUR
            SUM(le.amount_eur) AS current_holding_eur

        FROM ledger_entries le
        LEFT JOIN associates a ON le.associate_id = a.associate_id
        GROUP BY le.associate_id, a.display_alias
    """)

    rows = cursor.fetchall()
    conn.close()

    results = []
    for row in rows:
        results.append({
            'associate_id': row['associate_id'],
            'associate_alias': row['associate_alias'],
            'net_deposits_eur': Decimal(row['net_deposits_eur'] or "0.00"),
            'should_hold_eur': Decimal(row['should_hold_eur'] or "0.00"),
            'current_holding_eur': Decimal(row['current_holding_eur'] or "0.00")
        })

    return results

def get_bookmaker_aggregates(self) -> List[dict]:
    """
    Get modeled balances and balance check data for all bookmaker accounts.

    Returns:
        List of dicts with bookmaker balance info
    """
    conn = sqlite3.connect(self.db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            le.associate_id,
            a.display_alias AS associate_alias,
            le.bookmaker_id,
            bm.name AS bookmaker_name,
            bm.currency AS native_currency,

            -- Modeled balance (EUR)
            SUM(le.amount_eur) AS modeled_balance_eur,

            -- Balance check data (if exists)
            bbc.balance_native AS reported_balance_native,
            bbc.checked_at_utc

        FROM ledger_entries le
        LEFT JOIN associates a ON le.associate_id = a.associate_id
        LEFT JOIN bookmakers bm ON le.bookmaker_id = bm.bookmaker_id
        LEFT JOIN bookmaker_balance_checks bbc
            ON le.associate_id = bbc.associate_id
            AND le.bookmaker_id = bbc.bookmaker_id
        WHERE le.bookmaker_id IS NOT NULL
        GROUP BY le.associate_id, le.bookmaker_id, a.display_alias, bm.name, bm.currency, bbc.balance_native, bbc.checked_at_utc
    """)

    rows = cursor.fetchall()
    conn.close()

    results = []
    for row in rows:
        modeled_eur = Decimal(row['modeled_balance_eur'] or "0.00")
        reported_native = Decimal(row['reported_balance_native']) if row['reported_balance_native'] else None

        # Calculate difference if reported balance exists
        if reported_native is not None:
            # Get FX rate to convert
            from src.utils.fx_utils import get_fx_rate
            from datetime import datetime

            fx_rate = get_fx_rate(row['native_currency'], datetime.utcnow().date())
            modeled_native = (modeled_eur / fx_rate).quantize(Decimal("0.01"))
            difference_native = reported_native - modeled_native
            difference_eur = (difference_native * fx_rate).quantize(Decimal("0.01"))
        else:
            modeled_native = None
            difference_native = None
            difference_eur = None

        results.append({
            'associate_id': row['associate_id'],
            'associate_alias': row['associate_alias'],
            'bookmaker_id': row['bookmaker_id'],
            'bookmaker_name': row['bookmaker_name'],
            'native_currency': row['native_currency'],
            'modeled_balance_eur': modeled_eur,
            'modeled_balance_native': modeled_native,
            'reported_balance_native': reported_native,
            'difference_eur': difference_eur,
            'difference_native': difference_native,
            'checked_at_utc': row['checked_at_utc']
        })

    return results
```

---

#### Task 5.2.4: Associate Summary Component
**File**: `src/streamlit_app/components/reconciliation/associate_summary.py`

```python
"""
Associate summary table component.
"""
import streamlit as st
import pandas as pd

from src.domain.reconciliation_service import ReconciliationService

def render_associate_summary(reconciliation_service: ReconciliationService):
    """Render associate balance summary table."""

    balances = reconciliation_service.get_associate_balances()

    if not balances:
        st.info("No associates with ledger entries found")
        return

    # Build DataFrame
    df_data = []
    for balance in balances:
        df_data.append({
            "Associate": balance.associate_alias,
            "NET_DEPOSITS_EUR": f"€{balance.net_deposits_eur:.2f}",
            "SHOULD_HOLD_EUR": f"€{balance.should_hold_eur:.2f}",
            "CURRENT_HOLDING_EUR": f"€{balance.current_holding_eur:.2f}",
            "DELTA": f"{balance.status_icon} €{balance.delta_eur:+.2f}",
            "Status": balance.status.replace('_', ' ').title(),
            "_balance_obj": balance  # Hidden for expandable details
        })

    df = pd.DataFrame(df_data)

    # Display table
    st.dataframe(
        df.drop(columns=['_balance_obj']),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Associate": st.column_config.TextColumn(width="medium"),
            "DELTA": st.column_config.TextColumn(width="medium"),
            "Status": st.column_config.TextColumn(width="small")
        }
    )

    # Expandable details
    st.caption("**Expand for detailed explanations:**")

    for i, balance in enumerate(balances):
        with st.expander(f"{balance.status_icon} {balance.associate_alias} - DELTA: €{balance.delta_eur:+.2f}"):
            explanation = reconciliation_service.get_explanation(balance)
            st.markdown(explanation)

            # Show breakdown
            st.markdown("**Breakdown:**")
            st.markdown(f"- Net Deposits: €{balance.net_deposits_eur:.2f}")
            st.markdown(f"- Should Hold (Entitlement): €{balance.should_hold_eur:.2f}")
            st.markdown(f"- Current Holding: €{balance.current_holding_eur:.2f}")
            st.markdown(f"- **DELTA**: €{balance.delta_eur:+.2f}")

    # Export to CSV
    if st.button("📥 Export to CSV"):
        csv = df.drop(columns=['_balance_obj']).to_csv(index=False)
        st.download_button(
            label="Download CSV",
            data=csv,
            file_name="reconciliation_summary.csv",
            mime="text/csv"
        )
```

---

### Story 5.3: Bookmaker Balance Drilldown

#### Task 5.3.1: Bookmaker Drilldown Component
**File**: `src/streamlit_app/components/reconciliation/bookmaker_drilldown.py`

```python
"""
Bookmaker balance drilldown component.
"""
import streamlit as st
import pandas as pd
from datetime import datetime

from src.domain.reconciliation_service import ReconciliationService

def render_bookmaker_drilldown(reconciliation_service: ReconciliationService):
    """Render bookmaker balance comparison table."""

    balances = reconciliation_service.get_bookmaker_balances()

    if not balances:
        st.info("No bookmaker ledger entries found")
        return

    # Build DataFrame
    df_data = []
    for balance in balances:
        # Format modeled balance
        if balance.modeled_balance_native:
            modeled_display = f"€{balance.modeled_balance_eur:.2f} ({balance.modeled_balance_native:.2f} {balance.native_currency})"
        else:
            modeled_display = f"€{balance.modeled_balance_eur:.2f}"

        # Format reported balance
        if balance.reported_balance_native:
            reported_eur = balance.modeled_balance_eur + (balance.difference_eur or Decimal("0.00"))
            reported_display = f"{balance.reported_balance_native:.2f} {balance.native_currency} (€{reported_eur:.2f})"
        else:
            reported_display = "Not checked"

        # Format difference
        if balance.difference_eur is not None:
            difference_display = f"{balance.status_icon} €{balance.difference_eur:+.2f}"
        else:
            difference_display = "—"

        # Last checked
        if balance.checked_at_utc:
            try:
                checked_dt = datetime.fromisoformat(balance.checked_at_utc.replace('Z', '+00:00'))
                checked_display = checked_dt.strftime("%Y-%m-%d %H:%M UTC")
            except:
                checked_display = balance.checked_at_utc
        else:
            checked_display = "Never"

        df_data.append({
            "Associate": balance.associate_alias,
            "Bookmaker": balance.bookmaker_name,
            "Modeled Balance": modeled_display,
            "Reported Balance": reported_display,
            "Difference": difference_display,
            "Last Checked": checked_display,
            "Status": balance.status.replace('_', ' ').title(),
            "_balance_obj": balance
        })

    df = pd.DataFrame(df_data)

    # Display table
    st.dataframe(
        df.drop(columns=['_balance_obj']),
        use_container_width=True,
        hide_index=True
    )

    st.caption(f"**{len(balances)} bookmaker accounts**")

    # Filter: Show only mismatches
    if st.checkbox("Show only mismatches"):
        mismatches = [b for b in balances if b.status in ['minor_mismatch', 'major_mismatch']]
        if mismatches:
            st.warning(f"⚠️ {len(mismatches)} bookmaker(s) with mismatches")
        else:
            st.success("✅ No mismatches found")

    # Manual balance entry form (Story 5.3)
    render_balance_check_form()

def render_balance_check_form():
    """Render manual balance entry form."""
    st.divider()
    st.subheader("Update Bookmaker Balance")

    with st.form("balance_check_form"):
        col1, col2, col3 = st.columns(3)

        with col1:
            # TODO: Load associates and bookmakers dynamically
            st.selectbox("Associate", options=["Admin", "Partner A"])

        with col2:
            st.selectbox("Bookmaker", options=["Bet365", "Pinnacle"])

        with col3:
            st.number_input("Reported Balance", min_value=0.0, value=0.0)

        submitted = st.form_submit_button("Update Balance")

        if submitted:
            st.info("Balance check saved (implementation pending)")
```

---

#### Task 5.3.2: Bookmaker Balance Checks Repository
**File**: `src/data/repositories/bookmaker_balance_check_repository.py`

```python
"""
Repository for bookmaker_balance_checks table.
"""
import sqlite3
from decimal import Decimal
from typing import Optional
from dataclasses import dataclass

@dataclass
class BookmakersBalanceCheck:
    """Represents a bookmaker balance check entry."""
    check_id: int
    associate_id: int
    bookmaker_id: int
    balance_native: Decimal
    currency: str
    checked_at_utc: str

class BookmakersBalanceCheckRepository:
    """Repository for bookmaker balance checks."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def upsert(
        self,
        associate_id: int,
        bookmaker_id: int,
        balance_native: Decimal,
        currency: str,
        checked_at_utc: str
    ) -> int:
        """
        Insert or update balance check for associate+bookmaker.

        Returns:
            check_id
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Check if exists
        cursor.execute("""
            SELECT check_id FROM bookmaker_balance_checks
            WHERE associate_id = ? AND bookmaker_id = ?
        """, (associate_id, bookmaker_id))

        row = cursor.fetchone()

        if row:
            # Update
            cursor.execute("""
                UPDATE bookmaker_balance_checks
                SET balance_native = ?, currency = ?, checked_at_utc = ?
                WHERE associate_id = ? AND bookmaker_id = ?
            """, (str(balance_native), currency, checked_at_utc, associate_id, bookmaker_id))
            check_id = row[0]
        else:
            # Insert
            cursor.execute("""
                INSERT INTO bookmaker_balance_checks (
                    associate_id, bookmaker_id, balance_native, currency, checked_at_utc
                ) VALUES (?, ?, ?, ?, ?)
            """, (associate_id, bookmaker_id, str(balance_native), currency, checked_at_utc))
            check_id = cursor.lastrowid

        conn.commit()
        conn.close()

        return check_id

    def get_by_bookmaker(self, associate_id: int, bookmaker_id: int) -> Optional[BookmakersBalanceCheck]:
        """Get most recent balance check for bookmaker."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM bookmaker_balance_checks
            WHERE associate_id = ? AND bookmaker_id = ?
        """, (associate_id, bookmaker_id))

        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        return BookmakersBalanceCheck(
            check_id=row['check_id'],
            associate_id=row['associate_id'],
            bookmaker_id=row['bookmaker_id'],
            balance_native=Decimal(row['balance_native']),
            currency=row['currency'],
            checked_at_utc=row['checked_at_utc']
        )
```

---

#### Task 5.3.3: Database Migration (Balance Checks Table)
**File**: `migrations/005_create_bookmaker_balance_checks.sql`

```sql
-- Migration 005: Create bookmaker_balance_checks table
-- Stores operator-entered live balances from bookmaker websites

CREATE TABLE IF NOT EXISTS bookmaker_balance_checks (
    check_id INTEGER PRIMARY KEY AUTOINCREMENT,
    associate_id INTEGER NOT NULL REFERENCES associates(associate_id),
    bookmaker_id INTEGER NOT NULL REFERENCES bookmakers(bookmaker_id),
    balance_native TEXT NOT NULL,  -- Decimal stored as TEXT
    currency TEXT NOT NULL,
    checked_at_utc TEXT NOT NULL,  -- ISO8601 timestamp
    UNIQUE(associate_id, bookmaker_id)  -- One row per bookmaker (upsert on update)
);

CREATE INDEX IF NOT EXISTS idx_balance_checks_associate
ON bookmaker_balance_checks(associate_id);

CREATE INDEX IF NOT EXISTS idx_balance_checks_bookmaker
ON bookmaker_balance_checks(bookmaker_id);
```

---

### Story 5.4: Pending Funding Events

**Goal**: Manual entry and approval of deposits/withdrawals.

#### Task 5.4.1: Funding Events Component
**File**: `src/streamlit_app/components/reconciliation/funding_events.py`

```python
"""
Pending funding events component.
"""
import streamlit as st
from decimal import Decimal, InvalidOperation

from src.data.repositories.associate_repository import AssociateRepository
from src.data.repositories.ledger_repository import LedgerEntryRepository
from src.domain.funding_service import FundingService

SUPPORTED_CURRENCIES = ["EUR", "USD", "GBP", "AUD", "CAD"]

def render_funding_events(
    funding_service: FundingService,
    associate_repo: AssociateRepository,
    ledger_repo: LedgerEntryRepository
):
    """Render funding events section."""

    st.subheader("💰 Pending Funding Events")
    st.caption("Manually enter deposits and withdrawals for associates")

    # Manual entry form
    with st.form("funding_form"):
        col1, col2, col3 = st.columns(3)

        # Load associates
        associates = associate_repo.get_all()
        associate_options = {a.display_alias: a.associate_id for a in associates}

        with col1:
            selected_alias = st.selectbox("Associate", options=list(associate_options.keys()))
            associate_id = associate_options[selected_alias]

            event_type = st.radio("Event Type", options=["DEPOSIT", "WITHDRAWAL"])

        with col2:
            amount_str = st.text_input("Amount (Positive)", value="")
            currency = st.selectbox("Currency", options=SUPPORTED_CURRENCIES)

        with col3:
            note = st.text_area("Note (Optional)", value="", height=100)

        submitted = st.form_submit_button("➕ Add Funding Event")

        if submitted:
            # Validation
            try:
                amount = Decimal(amount_str.strip())
                if amount <= 0:
                    st.error("Amount must be positive")
                else:
                    # Add to drafts (session state)
                    if 'funding_drafts' not in st.session_state:
                        st.session_state.funding_drafts = []

                    st.session_state.funding_drafts.append({
                        'associate_id': associate_id,
                        'associate_alias': selected_alias,
                        'event_type': event_type,
                        'amount': amount,
                        'currency': currency,
                        'note': note.strip() or None
                    })

                    st.success(f"✅ {event_type} added to pending list")
                    st.rerun()

            except InvalidOperation:
                st.error("Invalid amount")

    # Pending list
    if 'funding_drafts' in st.session_state and st.session_state.funding_drafts:
        st.divider()
        st.subheader("Pending Events")

        for i, draft in enumerate(st.session_state.funding_drafts):
            with st.container():
                col1, col2, col3 = st.columns([2, 1, 1])

                with col1:
                    st.markdown(f"""
                    **{draft['event_type']}** - {draft['associate_alias']}
                    Amount: {draft['amount']} {draft['currency']}
                    Note: {draft['note'] or '(none)'}
                    """)

                with col2:
                    if st.button("✅ Accept", key=f"accept_{i}"):
                        # Accept funding event
                        try:
                            entry_id = funding_service.accept_funding_event(
                                event_type=draft['event_type'],
                                associate_id=draft['associate_id'],
                                amount=draft['amount'],
                                currency=draft['currency'],
                                note=draft['note']
                            )

                            st.success(f"✅ Funding event accepted! Entry #{entry_id}")
                            st.session_state.funding_drafts.pop(i)
                            st.rerun()

                        except Exception as e:
                            st.error(f"Failed to accept: {e}")

                with col3:
                    if st.button("❌ Reject", key=f"reject_{i}"):
                        st.session_state.funding_drafts.pop(i)
                        st.success("Funding event rejected")
                        st.rerun()

                st.divider()

    # Recent funding history
    st.divider()
    st.subheader("Recent Funding History (Last 30 Days)")

    from datetime import datetime, timedelta
    cutoff = (datetime.utcnow() - timedelta(days=30)).isoformat()

    deposits = ledger_repo.get_funding_events_since(cutoff, 'DEPOSIT')
    withdrawals = ledger_repo.get_funding_events_since(cutoff, 'WITHDRAWAL')

    all_events = deposits + withdrawals
    all_events.sort(key=lambda e: e.created_at_utc, reverse=True)

    if all_events:
        for event in all_events:
            st.markdown(f"""
            - **{event.entry_type}** (Entry #{event.entry_id}): {event.amount_native} {event.native_currency} (€{event.amount_eur})
              Associate: {event.associate_id} | {event.created_at_utc}
            """)
    else:
        st.info("No funding events in last 30 days")
```

---

#### Task 5.4.2: Funding Service
**File**: `src/domain/funding_service.py`

```python
"""
Funding service for deposit/withdrawal management.
"""
import logging
from decimal import Decimal
from datetime import datetime

from src.data.repositories.ledger_repository import LedgerEntryRepository
from src.utils.fx_utils import get_fx_rate
from src.utils.timestamp_utils import format_timestamp_utc

logger = logging.getLogger(__name__)

class FundingService:
    """Service for managing funding events (deposits/withdrawals)."""

    def __init__(self, ledger_repo: LedgerEntryRepository):
        self.ledger_repo = ledger_repo

    def accept_funding_event(
        self,
        event_type: str,  # 'DEPOSIT' or 'WITHDRAWAL'
        associate_id: int,
        amount: Decimal,
        currency: str,
        note: Optional[str] = None
    ) -> int:
        """
        Accept funding event and create ledger entry.

        Args:
            event_type: 'DEPOSIT' or 'WITHDRAWAL'
            associate_id: Associate receiving/sending funds
            amount: Positive amount in native currency
            currency: Currency code
            note: Optional note

        Returns:
            entry_id of created ledger entry

        Raises:
            ValueError: If validation fails
        """
        if event_type not in ['DEPOSIT', 'WITHDRAWAL']:
            raise ValueError(f"Invalid event_type: {event_type}")

        if amount <= 0:
            raise ValueError("Amount must be positive")

        # Get current FX rate
        fx_rate = get_fx_rate(currency, datetime.utcnow().date())

        # For WITHDRAWAL, amount should be negative in ledger
        if event_type == 'WITHDRAWAL':
            amount_native = -amount
        else:
            amount_native = amount

        # Calculate EUR amount
        amount_eur = (amount_native * fx_rate).quantize(Decimal("0.01"))

        # Create ledger entry
        timestamp_utc = format_timestamp_utc()

        entry_id = self.ledger_repo.create_funding_event(
            entry_type=event_type,
            associate_id=associate_id,
            amount_native=amount_native,
            native_currency=currency,
            fx_rate_snapshot=fx_rate,
            amount_eur=amount_eur,
            created_at_utc=timestamp_utc,
            created_by="local_user",
            note=note
        )

        logger.info(
            f"Funding event accepted: {event_type}, Entry #{entry_id}, "
            f"Associate {associate_id}, Amount: {amount} {currency} (€{amount_eur})"
        )

        return entry_id
```

---

#### Task 5.4.3: Extend Ledger Repository (Funding Events Query)
**File**: `src/data/repositories/ledger_repository.py` (add method)

```python
# Add to existing LedgerEntryRepository class:

def get_funding_events_since(self, cutoff_date_utc: str, event_type: str) -> List[LedgerEntry]:
    """Get all funding events (DEPOSIT or WITHDRAWAL) since cutoff date."""
    conn = sqlite3.connect(self.db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM ledger_entries
        WHERE entry_type = ?
        AND created_at_utc >= ?
        ORDER BY created_at_utc DESC
    """, (event_type, cutoff_date_utc))

    rows = cursor.fetchall()
    conn.close()

    return [self._row_to_entry(dict(row)) for row in rows]
```

---

### Story 5.5: Associate Operations Hub

**Goal**: Deliver a unified Streamlit workspace where operators can search, audit, and act on associates, bookmakers, balances, and funding transactions without navigation hops.

#### Task 5.5.1: Associate Operations Page Shell
**File**: `src/ui/pages/8_associate_operations.py`

```python
import streamlit as st

from src.services.bookmaker_balance_service import BookmakerBalanceService
from src.services.funding_transaction_service import FundingTransactionService
from src.ui.components.associate_hub.filters import render_filter_bar
from src.ui.components.associate_hub.listing import render_associate_listing
from src.ui.components.associate_hub.drawer import render_detail_drawer

def render_page() -> None:
    """Entry point for the associate operations hub."""
    st.set_page_config(page_title="Associate Operations", layout="wide")
    st.title("Associate Operations Hub")

    if "associate_hub_state" not in st.session_state:
        st.session_state.associate_hub_state = {
            "filters": {},
            "selected_associate_id": None,
            "selected_bookmaker_id": None,
        }

    filters = render_filter_bar(st.session_state.associate_hub_state)

    with BookmakerBalanceService() as balance_service:
        balances = balance_service.get_bookmaker_balances()

    funding_service = FundingTransactionService()
    render_associate_listing(
        balances=balances,
        hub_state=st.session_state.associate_hub_state,
        funding_service=funding_service,
        filters=filters,
    )

    render_detail_drawer(
        balances=balances,
        hub_state=st.session_state.associate_hub_state,
        funding_service=funding_service,
    )
```

- Register the page within `src/ui/app.py` to expose it in the navigation (e.g., `"8_Associate_Operations"` route).
- Use cached queries or memoized services so that filter changes do not execute redundant SQL.
- Provide empty-state messaging (e.g., "No associates match your filters") when result sets are empty.

#### Task 5.5.2: Filter, Listing, and Drawer Components
**Files**: `src/ui/components/associate_hub/filters.py`, `src/ui/components/associate_hub/listing.py`, `src/ui/components/associate_hub/drawer.py`

- `filters.render_filter_bar(state)` renders:
  - Text search for alias/bookmaker/chat id
  - Multi-select toggles for admin flag, associate active status, bookmaker active status, and currency
  - Sort dropdown (alias, DELTA, last activity) with ascending/descending switch
  - Persists selections back into `state["filters"]`
- `listing.render_associate_listing(...)` aggregates balances per associate, renders summary rows with badges, and exposes expandable bookmaker tables including modeled vs reported balance, DELTA, last balance check, and action buttons (Edit, Manage Balance, Deposit, Withdraw).
- `drawer.render_detail_drawer(...)` displays when `state["selected_associate_id"]` is set and contains tabs:
  - **Profile**: edit associate + bookmaker metadata using validators from Stories 7.1-7.3.
  - **Balances**: embed Story 5.3 balance history helper with CRUD actions scoped to the selection.
  - **Transactions**: show deposit/withdraw modals and recent ledger activity (Story 5.4 data).
- Ensure Streamlit callbacks mutate state then call `st.rerun()` to refresh the UI without losing filters.

#### Task 5.5.3: Funding Transaction Service
**File**: `src/services/funding_transaction_service.py`

```python
from decimal import Decimal
from typing import Optional

from src.core.database import get_db_connection
from src.services.fx_manager import get_fx_rate, convert_to_eur
from src.utils.database_utils import transactional

class FundingTransactionService:
    """Write DEPOSIT/WITHDRAWAL ledger entries originated from the hub."""

    def record_transaction(
        self,
        *,
        associate_id: int,
        amount_native: Decimal,
        native_currency: str,
        event_type: str,
        created_by: str = "local_user",
        bookmaker_id: Optional[int] = None,
        note: Optional[str] = None,
    ) -> int:
        if event_type not in {"DEPOSIT", "WITHDRAWAL"}:
            raise ValueError("Unsupported funding event type")

        with transactional(get_db_connection()) as conn:
            fx_rate = get_fx_rate(native_currency, None)
            amount_eur = convert_to_eur(amount_native, native_currency, fx_rate)
            cursor = conn.execute(
                """
                INSERT INTO ledger_entries (
                    entry_type,
                    associate_id,
                    bookmaker_id,
                    amount_native,
                    native_currency,
                    fx_rate_snapshot,
                    amount_eur,
                    note,
                    created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_type,
                    associate_id,
                    bookmaker_id,
                    str(amount_native),
                    native_currency,
                    str(fx_rate),
                    str(amount_eur),
                    note,
                    created_by,
                ),
            )
            return cursor.lastrowid
```

- Return the inserted ledger entry id so the UI can display confirmation metadata.
- Include helper methods for fetching recent transactions per associate/bookmaker.

#### Task 5.5.4: Hub Repository Layer
**File**: `src/repositories/associate_hub_repository.py`

- Create SQL helpers that join associates, bookmakers, latest balance checks, and ledger aggregates.
- Key methods:
  - `list_associates_with_metrics(filters)` → returns admin flag, currency, bookmaker count, NET_DEPOSITS_EUR, SHOULD_HOLD_EUR, CURRENT_HOLDING_EUR, DELTA, last activity timestamp.
  - `list_bookmakers_for_associate(associate_id)` → returns parsing profile, modeled vs reported balance, latest balance check, active status.
- Use the same connection + dict-row pattern as other repositories for consistency.

#### Task 5.5.5: Navigation and Legacy Alignment

- Update navigation registry (`src/ui/app.py`) so the new hub is discoverable.
- Refactor existing admin/balance pages to consume the shared components (filters, modals) to avoid divergence.
- Feature flag access (e.g., `st.session_state.get("feature_enable_associate_hub", True)`) until parity is confirmed.
- Add toast helpers for deposit/withdraw success/failure and ensure metrics re-compute after each transaction.

#### Validation Checklist
- Hub loads with same associate/bookmaker counts as legacy pages.
- Filters adjust listing without clearing the open drawer.
- Deposit/withdraw actions create ledger entries and refresh NET_DEPOSITS/DELTA badges instantly.
- Balance check CRUD executes end-to-end from the drawer.
- Profile edits persist and reflect in the listing/search results.

---

### Testing

#### Task 5.5.1: Unit Tests for Reconciliation Service
**File**: `tests/unit/domain/test_reconciliation_service.py`

```python
"""
Unit tests for ReconciliationService.
"""
import pytest
from decimal import Decimal

from src.domain.reconciliation_service import ReconciliationService

class MockLedgerRepo:
    """Mock ledger repository."""

    def get_associate_aggregates(self):
        return [
            {
                'associate_id': 1,
                'associate_alias': 'Admin',
                'net_deposits_eur': Decimal('2000.00'),
                'should_hold_eur': Decimal('2100.00'),
                'current_holding_eur': Decimal('2800.00')  # Overholder: +700
            },
            {
                'associate_id': 2,
                'associate_alias': 'Partner A',
                'net_deposits_eur': Decimal('1500.00'),
                'should_hold_eur': Decimal('1600.00'),
                'current_holding_eur': Decimal('1400.00')  # Short: -200
            },
            {
                'associate_id': 3,
                'associate_alias': 'Partner B',
                'net_deposits_eur': Decimal('1000.00'),
                'should_hold_eur': Decimal('1005.00'),
                'current_holding_eur': Decimal('1003.00')  # Balanced: -2
            }
        ]

    def get_bookmaker_aggregates(self):
        return []

def test_associate_balances_calculation():
    """Test DELTA calculation for associates."""
    service = ReconciliationService(ledger_repo=MockLedgerRepo())

    balances = service.get_associate_balances()

    assert len(balances) == 3

    # Admin: overholder
    admin = next(b for b in balances if b.associate_alias == 'Admin')
    assert admin.delta_eur == Decimal('700.00')  # 2800 - 2100
    assert admin.status == "overholder"
    assert admin.status_icon == "🔴"

    # Partner A: short
    partner_a = next(b for b in balances if b.associate_alias == 'Partner A')
    assert partner_a.delta_eur == Decimal('-200.00')  # 1400 - 1600
    assert partner_a.status == "short"
    assert partner_a.status_icon == "🟠"

    # Partner B: balanced
    partner_b = next(b for b in balances if b.associate_alias == 'Partner B')
    assert partner_b.delta_eur == Decimal('-2.00')  # 1003 - 1005
    assert partner_b.status == "balanced"  # Within ±€10 threshold
    assert partner_b.status_icon == "🟢"

def test_explanation_overholder():
    """Test explanation for overholder."""
    service = ReconciliationService(ledger_repo=MockLedgerRepo())
    balances = service.get_associate_balances()

    admin = next(b for b in balances if b.associate_alias == 'Admin')
    explanation = service.get_explanation(admin)

    assert "holding €700.00 more than their entitlement" in explanation
    assert "Collect €700.00 from them" in explanation

def test_explanation_short():
    """Test explanation for short associate."""
    service = ReconciliationService(ledger_repo=MockLedgerRepo())
    balances = service.get_associate_balances()

    partner_a = next(b for b in balances if b.associate_alias == 'Partner A')
    explanation = service.get_explanation(partner_a)

    assert "short €200.00" in explanation
    assert "Someone else is holding their €200.00" in explanation

def test_sorting_by_delta():
    """Test balances sorted by DELTA (largest overholders first)."""
    service = ReconciliationService(ledger_repo=MockLedgerRepo())
    balances = service.get_associate_balances()

    # Should be sorted: Admin (+700), Partner B (-2), Partner A (-200)
    assert balances[0].associate_alias == 'Admin'
    assert balances[1].associate_alias == 'Partner B'
    assert balances[2].associate_alias == 'Partner A'
```

---

#### Task 5.5.2: Integration Test for Corrections Flow
**File**: `tests/integration/test_corrections_flow.py`

```python
"""
Integration test for corrections flow.
"""
import pytest
import sqlite3
from decimal import Decimal
from pathlib import Path

from src.domain.correction_service import CorrectionService
from src.data.repositories.ledger_repository import LedgerEntryRepository
from src.data.repositories.associate_repository import AssociateRepository
from src.data.repositories.bookmaker_repository import BookmakersRepository

@pytest.fixture
def test_db(tmp_path):
    """Create test database with schema."""
    db_path = tmp_path / "test_corrections.db"

    # Run schema creation
    with open("schema.sql", 'r') as f:
        schema = f.read()

    conn = sqlite3.connect(str(db_path))
    conn.executescript(schema)

    # Insert test data
    cursor = conn.cursor()
    cursor.execute("INSERT INTO associates (associate_id, display_alias) VALUES (1, 'Admin')")
    cursor.execute("INSERT INTO bookmakers (bookmaker_id, associate_id, name, currency) VALUES (1, 1, 'Bet365', 'AUD')")
    cursor.execute("INSERT INTO fx_rates_daily (currency, rate, date) VALUES ('AUD', '0.60', date('now'))")
    conn.commit()
    conn.close()

    return str(db_path)

def test_apply_correction(test_db):
    """Test applying forward-only correction."""

    # Initialize services
    ledger_repo = LedgerEntryRepository(test_db)
    associate_repo = AssociateRepository(test_db)
    bookmaker_repo = BookmakersRepository(test_db)

    service = CorrectionService(ledger_repo, associate_repo, bookmaker_repo)

    # Apply correction
    entry_id = service.apply_correction(
        associate_id=1,
        bookmaker_id=1,
        amount_native=Decimal('100.00'),  # +100 AUD refund
        native_currency='AUD',
        note='Late VOID correction for Bet #123'
    )

    # Verify ledger entry created
    entries = ledger_repo.get_all()
    assert len(entries) == 1

    entry = entries[0]
    assert entry.entry_type == 'BOOKMAKER_CORRECTION'
    assert entry.associate_id == 1
    assert entry.bookmaker_id == 1
    assert entry.amount_native == Decimal('100.00')
    assert entry.native_currency == 'AUD'
    assert entry.fx_rate_snapshot == Decimal('0.60')
    assert entry.amount_eur == Decimal('60.00')  # 100 * 0.60
    assert entry.note == 'Late VOID correction for Bet #123'

def test_correction_immutability(test_db):
    """Test that corrections don't allow UPDATE."""

    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()

    # Insert correction
    cursor.execute("""
        INSERT INTO ledger_entries (
            entry_type, associate_id, bookmaker_id,
            amount_native, native_currency, fx_rate_snapshot, amount_eur,
            created_at_utc, created_by, note
        ) VALUES ('BOOKMAKER_CORRECTION', 1, 1, '100.00', 'AUD', '0.60', '60.00', '2025-01-01T00:00:00Z', 'test', 'Test')
    """)
    conn.commit()

    # Attempt UPDATE (should fail)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        cursor.execute("UPDATE ledger_entries SET amount_eur = '999.99' WHERE entry_id = 1")
        conn.commit()

    conn.close()
```

---

### Manual Testing

#### Task 5.6: Manual UAT Procedures
**File**: `docs/testing/epic-5-uat-procedures.md`

```markdown
# Epic 5: Corrections & Reconciliation - User Acceptance Testing

## Prerequisites
- Database with settled surebets (ledger entries exist)
- At least 2 associates with different balances
- FX rates populated

---

## Scenario 1: Late VOID Correction

**Objective**: Apply forward-only correction for late refund.

### Steps:
1. Open Corrections page
2. Fill form:
   - Associate: Partner A
   - Bookmaker: Bet365
   - Amount: 100 (positive)
   - Currency: AUD
   - Note: "Late VOID correction for Bet #123"
3. Click "Apply Correction"

### Expected Results:
- ✅ Success message: "Correction applied. Ledger entry created."
- ✅ Entry appears in Recent Corrections list
- ✅ Entry shows: +100 AUD, FX snapshot, note
- ✅ Reconciliation dashboard shows Partner A's CURRENT_HOLDING increased

### SQL Verification:
```sql
SELECT * FROM ledger_entries
WHERE entry_type = 'BOOKMAKER_CORRECTION'
ORDER BY created_at_utc DESC
LIMIT 1;
-- Should show new correction with frozen FX rate
```

---

## Scenario 2: Identify Overholder

**Objective**: Use DELTA to identify who's overholding.

### Steps:
1. Open Reconciliation page
2. Review Associate Summary table
3. Find associate with 🔴 status (DELTA > +€10)
4. Expand row for detailed explanation

### Expected Results:
- ✅ Table shows NET_DEPOSITS, SHOULD_HOLD, CURRENT_HOLDING, DELTA
- ✅ Overholders have 🔴 icon and positive DELTA
- ✅ Short associates have 🟠 icon and negative DELTA
- ✅ Balanced associates have 🟢 icon
- ✅ Explanation clearly states: "Collect €X from them" (overholder) or "Someone else holding their €X" (short)

---

## Scenario 3: Bookmaker Balance Mismatch

**Objective**: Compare modeled vs. reported balance.

### Steps:
1. Open Reconciliation page
2. Scroll to Bookmaker Drilldown
3. Manually check Bet365 website: balance is $450 AUD
4. In drilldown table, see modeled balance: €500 (approx $830 AUD)
5. Update balance:
   - Associate: Admin
   - Bookmaker: Bet365
   - Reported Balance: 450
6. Click "Update Balance"

### Expected Results:
- ✅ Difference calculated: -€X (modeled higher than reported)
- ✅ Status icon: 🔴 (major mismatch) or 🟡 (minor)
- ✅ "Apply Correction" button pre-fills correction form
- ✅ After correction: difference becomes €0, status 🟢

---

## Scenario 4: Accept Deposit

**Objective**: Record deposit and verify NET_DEPOSITS updates.

### Steps:
1. Open Reconciliation page (Story 5.4 section)
2. Enter funding event:
   - Associate: Partner B
   - Type: DEPOSIT
   - Amount: 500
   - Currency: EUR
   - Note: "Bank transfer 2025-10-30"
3. Click "Add Funding Event"
4. Review in pending list
5. Click "Accept"

### Expected Results:
- ✅ Ledger entry created: entry_type = 'DEPOSIT'
- ✅ Reconciliation dashboard updates:
   - NET_DEPOSITS_EUR increases by €500
   - SHOULD_HOLD_EUR unchanged
   - DELTA worsens (more short, since deposit doesn't immediately go to bookmakers)

### SQL Verification:
```sql
SELECT * FROM ledger_entries
WHERE entry_type = 'DEPOSIT'
ORDER BY created_at_utc DESC
LIMIT 1;
```

---

## Scenario 5: Reject Withdrawal

**Objective**: Discard incorrect funding event.

### Steps:
1. Add withdrawal event:
   - Associate: Admin
   - Type: WITHDRAWAL
   - Amount: 1000 EUR
2. Click "Add Funding Event"
3. Review in pending list
4. Click "Reject"

### Expected Results:
- ✅ Draft removed from pending list
- ✅ No ledger entry created
- ✅ Success message: "Funding event discarded"

---

## Scenario 6: Export Reconciliation to CSV

**Objective**: Export associate summary for external review.

### Steps:
1. Open Reconciliation page
2. Click "Export to CSV" button
3. Download file

### Expected Results:
- ✅ CSV file downloaded
- ✅ Contains columns: Associate, NET_DEPOSITS_EUR, SHOULD_HOLD_EUR, CURRENT_HOLDING_EUR, DELTA, Status
- ✅ Data matches displayed table

---

## Post-Testing Validation

### Ledger Integrity:
```sql
-- All corrections should have entry_type = 'BOOKMAKER_CORRECTION'
SELECT COUNT(*) FROM ledger_entries WHERE entry_type = 'BOOKMAKER_CORRECTION';

-- Deposits should be positive, withdrawals negative
SELECT entry_type, SUM(amount_eur) FROM ledger_entries
WHERE entry_type IN ('DEPOSIT', 'WITHDRAWAL')
GROUP BY entry_type;
```

### Math Validation:
```sql
-- DELTA = CURRENT_HOLDING - SHOULD_HOLD
-- Manually verify with calculator for one associate
```

---

## Sign-Off

- [ ] Scenario 1: Late VOID correction passed
- [ ] Scenario 2: Overholder identified passed
- [ ] Scenario 3: Balance mismatch handled passed
- [ ] Scenario 4: Deposit accepted passed
- [ ] Scenario 5: Withdrawal rejected passed
- [ ] Scenario 6: CSV export passed
- [ ] Ledger integrity verified
- [ ] Math validation passed

**Tester Signature:** _______________
**Date:** _______________
```

---

## Deployment Checklist

### Pre-Deployment

- [ ] Migration 005 applied (bookmaker_balance_checks table)
- [ ] Append-only triggers from Epic 4 still active
- [ ] At least 2 settled surebets in database
- [ ] FX rates current

### Code Deployment

- [ ] All Story 5.1-5.5 files created
- [ ] Unit tests pass
- [ ] Integration test passes

### Post-Deployment

- [ ] Corrections page loads
- [ ] Reconciliation dashboard calculates correctly
- [ ] Apply correction successfully
- [ ] Accept funding event successfully
- [ ] Associate Operations hub page loads, filters work, and funding actions persist
- [ ] Export CSV works

---

## Troubleshooting Guide

### Issue: "DELTA calculation incorrect"

**Cause:** SQL aggregation error

**Fix:**
```sql
-- Manually verify with:
SELECT
  associate_id,
  SUM(CASE WHEN entry_type='DEPOSIT' THEN amount_eur ELSE 0 END) AS deposits,
  SUM(CASE WHEN entry_type='WITHDRAWAL' THEN amount_eur ELSE 0 END) AS withdrawals,
  SUM(CASE WHEN entry_type='BET_RESULT' THEN amount_eur ELSE 0 END) AS bet_results
FROM ledger_entries
GROUP BY associate_id;
```

### Issue: "Correction amount has wrong sign"

**Cause:** User entered negative when should be positive

**Fix:** Update UI labels: "Positive = increases, Negative = decreases"

### Issue: "Bookmaker drilldown shows no data"

**Cause:** No balance checks entered

**Fix:** Manually enter at least one bookmaker balance via form

---

## Success Criteria

- [x] All corrections forward-only (no UPDATE/DELETE)
- [x] DELTA calculation accurate
- [x] Overholders/short associates identifiable in <30 seconds
- [x] Deposits/withdrawals update NET_DEPOSITS correctly
- [x] All 6 UAT scenarios pass

---

## Related Documents

- [Epic 5: Corrections & Reconciliation](./epic-5-corrections-reconciliation.md)
- [PRD: FR-7 (Post-Settlement Corrections)](../prd.md#fr-7)
- [PRD: FR-8 (Reconciliation)](../prd.md#fr-8)
- [Epic 4: Settlement](./epic-4-implementation-guide.md)
- [Epic 6: Reporting](./epic-6-implementation-guide.md)

---

**End of Epic 5 Implementation Guide**
