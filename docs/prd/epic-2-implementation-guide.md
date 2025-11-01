# Epic 2: Bet Review & Approval - Implementation Guide

**Epic Reference**: [epic-2-bet-review.md](./epic-2-bet-review.md)
**Status**: Ready for Development
**Estimated Effort**: 3-4 days (1 developer)

---

## Overview

This guide provides detailed, step-by-step implementation instructions for Epic 2. Follow this sequentially after completing Epic 1 (Bet Ingestion).

**Epic Goal**: Build unified review queue with inline editing and approval workflow for quality control.

**Prerequisites**:
- âœ… Epic 1 complete and tested
- âœ… `status="incoming"` bets exist in database
- âœ… Screenshots saved and accessible
- âœ… Streamlit app running from Epic 1

---

## Code Structure

### New/Modified Files for Epic 2

```
Final_App/
â”œâ”€â”€ src/
â”‚   â”œâ”€â”€ database/
â”‚   â”‚   â”œâ”€â”€ models.py                   # UPDATE: Add verification_audit table
â”‚   â”‚   â””â”€â”€ repositories/
â”‚   â”‚       â”œâ”€â”€ bet_repository.py       # UPDATE: Add approve/reject methods
â”‚   â”‚       â”œâ”€â”€ event_repository.py     # NEW: Canonical events CRUD
â”‚   â”‚       â””â”€â”€ audit_repository.py     # NEW: Verification audit logging
â”‚   â”œâ”€â”€ streamlit_app/
â”‚   â”‚   â”œâ”€â”€ pages/
â”‚   â”‚   â”‚   â””â”€â”€ 1_incoming_bets.py      # UPDATE: Add edit/approve UI (from Epic 1)
â”‚   â”‚   â”œâ”€â”€ components/
â”‚   â”‚   â”‚   â”œâ”€â”€ bet_card.py             # NEW: Individual bet card component
â”‚   â”‚   â”‚   â”œâ”€â”€ inline_editor.py        # NEW: Inline editing component
â”‚   â”‚   â”‚   â””â”€â”€ event_modal.py          # NEW: Create new event modal
â”‚   â”‚   â””â”€â”€ utils/
â”‚   â”‚       â”œâ”€â”€ validators.py           # NEW: Field validation logic
â”‚   â”‚       â””â”€â”€ formatters.py           # NEW: Display formatters
â”‚   â””â”€â”€ domain/
â”‚       â”œâ”€â”€ __init__.py
â”‚       â””â”€â”€ bet_approval.py             # NEW: Business logic for approval
â”œâ”€â”€ tests/
â”‚   â”œâ”€â”€ unit/
â”‚   â”‚   â”œâ”€â”€ test_validators.py          # NEW: Validation tests
â”‚   â”‚   â”œâ”€â”€ test_bet_approval.py        # NEW: Approval logic tests
â”‚   â”‚   â””â”€â”€ test_audit_repository.py    # NEW: Audit tests
â”‚   â””â”€â”€ integration/
â”‚       â””â”€â”€ test_approval_flow.py       # NEW: End-to-end approval test
â””â”€â”€ config/
    â””â”€â”€ market_codes.yaml               # NEW: Market type definitions
```

---

## Database Schema Updates

### Task 0: Create Verification Audit Table

**File**: `migrations/002_create_verification_audit.sql` (NEW)

**Implementation**:
```sql
-- Verification audit table for tracking bet edits
CREATE TABLE IF NOT EXISTS verification_audit (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    bet_id INTEGER NOT NULL,
    field_name TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT NOT NULL,
    edited_at_utc TEXT NOT NULL,
    edited_by TEXT NOT NULL DEFAULT 'local_user',
    FOREIGN KEY (bet_id) REFERENCES bets(bet_id)
);

CREATE INDEX idx_verification_audit_bet_id ON verification_audit(bet_id);
CREATE INDEX idx_verification_audit_edited_at ON verification_audit(edited_at_utc);
```

**Run Migration**:
```python
# In Python REPL or migration script
from src.database.db import get_session

session = get_session()
with open("migrations/002_create_verification_audit.sql", 'r') as f:
    session.execute(f.read())
session.commit()
```

---

## Story 2.1: Incoming Bets Queue UI

### Implementation Tasks

#### Task 2.1.1: Create Display Formatters

**File**: `src/streamlit_app/utils/formatters.py` (NEW)

**Implementation**:
```python
"""Display formatting utilities for Streamlit UI."""
from datetime import datetime
from typing import Optional
from decimal import Decimal

def format_timestamp_relative(timestamp_utc: str) -> str:
    """Format timestamp as relative time (e.g., '5 minutes ago')."""
    try:
        dt = datetime.fromisoformat(timestamp_utc.replace('Z', '+00:00'))
        now = datetime.utcnow()
        delta = now - dt

        seconds = delta.total_seconds()
        if seconds < 60:
            return f"{int(seconds)} seconds ago"
        elif seconds < 3600:
            return f"{int(seconds / 60)} minutes ago"
        elif seconds < 86400:
            return f"{int(seconds / 3600)} hours ago"
        else:
            return f"{int(seconds / 86400)} days ago"
    except:
        return timestamp_utc

def format_confidence_badge(confidence: Optional[float]) -> tuple:
    """Return (emoji, label, color) for confidence level.

    Returns:
        Tuple of (emoji, label, st.color_name)
    """
    if confidence is None:
        return ("âŒ", "Failed", "error")
    elif confidence >= 0.8:
        return ("âœ…", f"High ({confidence:.0%})", "success")
    elif confidence >= 0.5:
        return ("âš ï¸", f"Medium ({confidence:.0%})", "warning")
    else:
        return ("âŒ", f"Low ({confidence:.0%})", "error")

def format_currency_amount(amount: Optional[Decimal], currency: str) -> str:
    """Format currency amount with symbol."""
    if amount is None:
        return "N/A"

    currency_symbols = {
        "AUD": "$",
        "GBP": "Â£",
        "EUR": "â‚¬",
        "USD": "$"
    }

    symbol = currency_symbols.get(currency, currency)
    return f"{symbol}{amount:,.2f}"

def format_bet_summary(stake: Optional[Decimal], odds: Optional[Decimal],
                       payout: Optional[Decimal], currency: str) -> str:
    """Format bet as 'stake @ odds = payout'."""
    if not all([stake, odds, payout]):
        return "Incomplete bet data"

    return f"{format_currency_amount(stake, currency)} @ {odds} = {format_currency_amount(payout, currency)}"

def format_market_display(market_code: Optional[str]) -> str:
    """Convert internal market code to human-readable."""
    if not market_code:
        return "(not extracted)"

    # Map internal codes to display names
    market_display = {
        "TOTAL_GOALS_OVER_UNDER": "Total Goals O/U",
        "ASIAN_HANDICAP": "Asian Handicap",
        "MATCH_WINNER": "Match Winner",
        "BOTH_TEAMS_TO_SCORE": "Both Teams to Score",
        "FIRST_HALF_TOTAL_GOALS": "1H Total Goals",
    }

    return market_display.get(market_code, market_code.replace("_", " ").title())
```

**Tests** (`tests/unit/test_formatters.py`):
```python
import pytest
from src.streamlit_app.utils.formatters import (
    format_confidence_badge, format_currency_amount, format_bet_summary
)
from decimal import Decimal

def test_confidence_badge_high():
    emoji, label, color = format_confidence_badge(0.9)
    assert emoji == "âœ…"
    assert "High" in label
    assert color == "success"

def test_confidence_badge_low():
    emoji, label, color = format_confidence_badge(0.3)
    assert emoji == "âŒ"
    assert "Low" in label

def test_currency_formatting():
    assert format_currency_amount(Decimal("100.50"), "GBP") == "Â£100.50"
    assert format_currency_amount(Decimal("1000"), "EUR") == "â‚¬1,000.00"

def test_bet_summary():
    summary = format_bet_summary(Decimal("100"), Decimal("1.90"), Decimal("190"), "AUD")
    assert "AUD 100.00 @ 1.90 = AUD 190.00" in summary
```

---

#### Task 2.1.2: Create Bet Card Component

**File**: `src/streamlit_app/components/bet_card.py` (NEW)

**Implementation**:
```python
"""Bet card component for displaying incoming bets."""
import streamlit as st
from typing import Dict, Any
from pathlib import Path
from src.streamlit_app.utils.formatters import (
    format_timestamp_relative,
    format_confidence_badge,
    format_bet_summary,
    format_market_display
)

def render_bet_card(bet: Dict[str, Any], show_actions: bool = True):
    """Render a single bet card with screenshot preview and details.

    Args:
        bet: Dictionary containing bet data (from database query)
        show_actions: Whether to show approve/reject buttons
    """
    with st.container():
        # Create 3-column layout: screenshot | details | actions
        col1, col2, col3 = st.columns([1, 3, 1])

        with col1:
            # Screenshot preview
            _render_screenshot_preview(bet)

        with col2:
            # Bet details
            _render_bet_details(bet)

        with col3:
            # Confidence badge and actions
            _render_bet_actions(bet, show_actions)

        st.markdown("---")

def _render_screenshot_preview(bet: Dict[str, Any]):
    """Render screenshot preview with click-to-enlarge."""
    screenshot_path = bet.get('screenshot_path')

    if screenshot_path and Path(screenshot_path).exists():
        # Thumbnail
        st.image(screenshot_path, width=150, caption="Click to enlarge")

        # Full-size modal (using expander)
        with st.expander("ðŸ” View Full Size"):
            st.image(screenshot_path, use_column_width=True)
    else:
        st.warning("Screenshot\nnot found")

def _render_bet_details(bet: Dict[str, Any]):
    """Render bet details section."""
    # Header: Bet ID, Associate, Bookmaker
    st.markdown(f"**Bet #{bet['bet_id']}** - {bet['associate']} @ {bet['bookmaker']}")

    # Source icon and timestamp
    source_icon = "ðŸ“±" if bet['ingestion_source'] == "telegram" else "ðŸ“¤"
    timestamp_rel = format_timestamp_relative(bet['created_at_utc'])
    st.caption(f"{source_icon} {bet['ingestion_source']} â€¢ {timestamp_rel}")

    # Extracted data
    if bet['canonical_event']:
        st.write(f"**Event:** {bet['canonical_event']}")
        st.write(f"**Market:** {format_market_display(bet['market_code'])}")

        # Market details
        details = []
        if bet['period_scope']:
            details.append(bet['period_scope'].replace("_", " ").title())
        if bet['line_value']:
            details.append(f"Line: {bet['line_value']}")
        if bet['side']:
            details.append(f"Side: {bet['side']}")
        if details:
            st.caption(" â€¢ ".join(details))

        # Financial summary
        bet_summary = format_bet_summary(
            bet['stake'], bet['odds'], bet['payout'], bet['currency']
        )
        st.write(f"**Bet:** {bet_summary}")

        # Kickoff time
        if bet.get('kickoff_time_utc'):
            st.caption(f"â° Kickoff: {bet['kickoff_time_utc']}")
    else:
        st.warning("âš ï¸ **Extraction failed** - manual entry required")

    # Special flags
    if bet.get('is_multi'):
        st.error("ðŸš« **Accumulator - Not Supported**")

    if bet.get('operator_note'):
        st.info(f"ðŸ“ Note: {bet['operator_note']}")

def _render_bet_actions(bet: Dict[str, Any], show_actions: bool):
    """Render confidence badge and action buttons."""
    # Confidence badge
    emoji, label, color = format_confidence_badge(bet.get('normalization_confidence'))
    st.markdown(f"{emoji} **{label}**")

    if show_actions:
        st.markdown("---")

        # Approve button (green)
        if st.button("âœ… Approve", key=f"approve_{bet['bet_id']}", type="primary"):
            st.session_state[f"approve_bet_{bet['bet_id']}"] = True
            st.rerun()

        # Reject button (red)
        if st.button("âŒ Reject", key=f"reject_{bet['bet_id']}"):
            st.session_state[f"reject_bet_{bet['bet_id']}"] = True
            st.rerun()
```

---

#### Task 2.1.3: Update Incoming Bets Page (Enhanced Queue)

**File**: `src/streamlit_app/pages/1_incoming_bets.py` (UPDATE from Epic 1)

**Implementation**:
```python
"""Incoming Bets page - enhanced with bet cards and counters."""
import streamlit as st
from src.database.db import get_session
from src.streamlit_app.components.manual_upload import render_manual_upload_panel
from src.streamlit_app.components.bet_card import render_bet_card

st.set_page_config(page_title="Incoming Bets", layout="wide")

st.title("ðŸ“¥ Incoming Bets")

# Manual upload panel (from Epic 1)
with st.expander("ðŸ“¤ Upload Manual Bet", expanded=False):
    render_manual_upload_panel()

st.markdown("---")

# Counters
session = get_session()
counts_query = """
    SELECT
        SUM(CASE WHEN status='incoming' THEN 1 ELSE 0 END) as waiting,
        SUM(CASE WHEN status='verified' AND date(verified_at_utc)=date('now') THEN 1 ELSE 0 END) as approved_today,
        SUM(CASE WHEN status='rejected' AND date(verified_at_utc)=date('now') THEN 1 ELSE 0 END) as rejected_today
    FROM bets
"""
counts = session.execute(counts_query).fetchone()

col1, col2, col3 = st.columns(3)
col1.metric("â³ Waiting Review", counts.waiting or 0)
col2.metric("âœ… Approved Today", counts.approved_today or 0)
col3.metric("âŒ Rejected Today", counts.rejected_today or 0)

st.markdown("---")

# Filter options (optional)
with st.expander("ðŸ” Filters", expanded=False):
    filter_col1, filter_col2 = st.columns(2)

    with filter_col1:
        # Filter by associate
        associates = session.execute("SELECT DISTINCT display_alias FROM associates ORDER BY display_alias").fetchall()
        associate_filter = st.multiselect(
            "Filter by Associate",
            options=["All"] + [a.display_alias for a in associates],
            default=["All"]
        )

    with filter_col2:
        # Filter by confidence
        confidence_filter = st.selectbox(
            "Filter by Confidence",
            options=["All", "High (â‰¥80%)", "Medium (50-79%)", "Low (<50%)", "Failed"],
            index=0
        )

st.markdown("---")

# Incoming bets queue
st.subheader("ðŸ“‹ Bets Awaiting Review")

# Build query with filters
query = """
    SELECT
        b.bet_id,
        b.screenshot_path,
        a.display_alias as associate,
        bk.name as bookmaker,
        b.ingestion_source,
        b.canonical_event,
        b.market_code,
        b.period_scope,
        b.line_value,
        b.side,
        b.stake,
        b.odds,
        b.payout,
        b.currency,
        b.kickoff_time_utc,
        b.normalization_confidence,
        b.is_multi,
        b.operator_note,
        b.created_at_utc
    FROM bets b
    JOIN associates a ON b.associate_id = a.associate_id
    JOIN bookmakers bk ON b.bookmaker_id = bk.bookmaker_id
    WHERE b.status = 'incoming'
"""

# Apply filters
if "All" not in associate_filter and associate_filter:
    placeholders = ','.join(['?' for _ in associate_filter])
    query += f" AND a.display_alias IN ({placeholders})"

# Apply confidence filter
if confidence_filter != "All":
    if confidence_filter == "High (â‰¥80%)":
        query += " AND b.normalization_confidence >= 0.8"
    elif confidence_filter == "Medium (50-79%)":
        query += " AND b.normalization_confidence >= 0.5 AND b.normalization_confidence < 0.8"
    elif confidence_filter == "Low (<50%)":
        query += " AND b.normalization_confidence < 0.5"
    elif confidence_filter == "Failed":
        query += " AND b.normalization_confidence IS NULL"

query += " ORDER BY b.created_at_utc DESC"

# Execute query
if "All" not in associate_filter and associate_filter:
    incoming_bets = session.execute(query, associate_filter).fetchall()
else:
    incoming_bets = session.execute(query).fetchall()

if not incoming_bets:
    st.info("âœ¨ No bets awaiting review! Queue is empty.")
else:
    st.caption(f"Showing {len(incoming_bets)} bet(s)")

    # Render each bet card
    for bet in incoming_bets:
        bet_dict = dict(bet._mapping)  # Convert Row to dict
        render_bet_card(bet_dict, show_actions=True)

# Auto-refresh option
st.markdown("---")
if st.checkbox("ðŸ”„ Auto-refresh every 30 seconds"):
    import time
    time.sleep(30)
    st.rerun()
```

---

## Story 2.2: Inline Editing & Approval Workflow

### Implementation Tasks

#### Task 2.2.1: Create Field Validators

**File**: `src/streamlit_app/utils/validators.py` (NEW)

**Implementation**:
```python
"""Validation logic for bet fields."""
from decimal import Decimal, InvalidOperation
from typing import Optional, Tuple

def validate_stake(stake: Optional[Decimal]) -> Tuple[bool, Optional[str]]:
    """Validate stake amount.

    Returns:
        (is_valid, error_message)
    """
    if stake is None:
        return False, "Stake is required"
    if stake <= 0:
        return False, "Stake must be greater than 0"
    return True, None

def validate_odds(odds: Optional[Decimal]) -> Tuple[bool, Optional[str]]:
    """Validate odds value."""
    if odds is None:
        return False, "Odds are required"
    if odds < 1.0:
        return False, "Odds must be â‰¥ 1.0"
    return True, None

def validate_payout(payout: Optional[Decimal], stake: Optional[Decimal]) -> Tuple[bool, Optional[str]]:
    """Validate payout amount."""
    if payout is None:
        return False, "Payout is required"
    if stake and payout < stake:
        return False, "Payout should be â‰¥ stake (sanity check)"
    return True, None

def validate_currency(currency: Optional[str]) -> Tuple[bool, Optional[str]]:
    """Validate currency code."""
    if not currency:
        return False, "Currency is required"

    valid_currencies = ["AUD", "GBP", "EUR", "USD", "NZD", "CAD"]
    if currency not in valid_currencies:
        return False, f"Currency must be one of: {', '.join(valid_currencies)}"

    return True, None

def validate_canonical_event(canonical_event_id: Optional[int]) -> Tuple[bool, Optional[str]]:
    """Validate canonical event selection."""
    if not canonical_event_id:
        return False, "Event selection is required"
    return True, None

def validate_all_fields(bet_data: dict) -> Tuple[bool, list]:
    """Validate all required fields.

    Returns:
        (all_valid, list_of_errors)
    """
    errors = []

    # Validate each field
    validations = [
        validate_stake(bet_data.get('stake')),
        validate_odds(bet_data.get('odds')),
        validate_payout(bet_data.get('payout'), bet_data.get('stake')),
        validate_currency(bet_data.get('currency')),
        validate_canonical_event(bet_data.get('canonical_event_id'))
    ]

    for is_valid, error_msg in validations:
        if not is_valid:
            errors.append(error_msg)

    return len(errors) == 0, errors
```

**Tests** (`tests/unit/test_validators.py`):
```python
import pytest
from decimal import Decimal
from src.streamlit_app.utils.validators import (
    validate_stake, validate_odds, validate_payout, validate_all_fields
)

def test_validate_stake_valid():
    is_valid, error = validate_stake(Decimal("100"))
    assert is_valid
    assert error is None

def test_validate_stake_zero():
    is_valid, error = validate_stake(Decimal("0"))
    assert not is_valid
    assert "greater than 0" in error

def test_validate_odds_too_low():
    is_valid, error = validate_odds(Decimal("0.5"))
    assert not is_valid
    assert "â‰¥ 1.0" in error

def test_validate_payout_less_than_stake():
    is_valid, error = validate_payout(Decimal("90"), Decimal("100"))
    assert not is_valid
    assert "â‰¥ stake" in error

def test_validate_all_fields():
    bet_data = {
        'stake': Decimal("100"),
        'odds': Decimal("1.90"),
        'payout': Decimal("190"),
        'currency': "AUD",
        'canonical_event_id': 1
    }
    all_valid, errors = validate_all_fields(bet_data)
    assert all_valid
    assert len(errors) == 0
```

---

#### Task 2.2.2: Create Event Repository

**File**: `src/database/repositories/event_repository.py` (NEW)

**Implementation**:
```python
"""Repository for canonical events."""
from sqlalchemy.orm import Session
from typing import List, Optional
from src.database.models import CanonicalEvent
from src.utils.timestamp import utc_now_iso

class EventRepository:
    """Handles canonical event database operations."""

    def __init__(self, session: Session):
        self.session = session

    def get_all_events(self, limit: int = 100) -> List[CanonicalEvent]:
        """Get all canonical events, most recent first."""
        return self.session.query(CanonicalEvent)\
            .order_by(CanonicalEvent.kickoff_time_utc.desc())\
            .limit(limit)\
            .all()

    def search_events(self, search_term: str, limit: int = 20) -> List[CanonicalEvent]:
        """Search events by name."""
        search_pattern = f"%{search_term}%"
        return self.session.query(CanonicalEvent)\
            .filter(CanonicalEvent.event_name.like(search_pattern))\
            .order_by(CanonicalEvent.kickoff_time_utc.desc())\
            .limit(limit)\
            .all()

    def create_event(
        self,
        event_name: str,
        sport: str,
        kickoff_time_utc: str
    ) -> CanonicalEvent:
        """Create a new canonical event."""
        event = CanonicalEvent(
            event_name=event_name,
            sport=sport,
            kickoff_time_utc=kickoff_time_utc,
            created_at_utc=utc_now_iso()
        )

        self.session.add(event)
        self.session.commit()
        self.session.refresh(event)
        return event

    def get_event_display_string(self, event: CanonicalEvent) -> str:
        """Format event for dropdown display."""
        # Format: "Man Utd vs Arsenal (2025-11-01)"
        kickoff_date = event.kickoff_time_utc.split('T')[0] if event.kickoff_time_utc else "TBD"
        return f"{event.event_name} ({kickoff_date})"
```

---

#### Task 2.2.3: Create Audit Repository

**File**: `src/database/repositories/audit_repository.py` (NEW)

**Implementation**:
```python
"""Repository for verification audit logging."""
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Any, Optional
from src.utils.timestamp import utc_now_iso

class AuditRepository:
    """Handles verification audit logging."""

    def __init__(self, session: Session):
        self.session = session

    def log_field_change(
        self,
        bet_id: int,
        field_name: str,
        old_value: Any,
        new_value: Any
    ):
        """Log a single field change."""
        # Convert values to strings for storage
        old_str = str(old_value) if old_value is not None else None
        new_str = str(new_value) if new_value is not None else None

        # Only log if value actually changed
        if old_str == new_str:
            return

        query = text("""
            INSERT INTO verification_audit
            (bet_id, field_name, old_value, new_value, edited_at_utc, edited_by)
            VALUES
            (:bet_id, :field_name, :old_value, :new_value, :edited_at_utc, :edited_by)
        """)

        self.session.execute(query, {
            'bet_id': bet_id,
            'field_name': field_name,
            'old_value': old_str,
            'new_value': new_str,
            'edited_at_utc': utc_now_iso(),
            'edited_by': 'local_user'
        })

    def log_multiple_changes(
        self,
        bet_id: int,
        changes: dict
    ):
        """Log multiple field changes at once.

        Args:
            bet_id: ID of bet being edited
            changes: Dict of {field_name: (old_value, new_value)}
        """
        for field_name, (old_value, new_value) in changes.items():
            self.log_field_change(bet_id, field_name, old_value, new_value)

        self.session.commit()

    def get_bet_audit_trail(self, bet_id: int) -> List[dict]:
        """Get audit trail for a specific bet."""
        query = text("""
            SELECT
                audit_id,
                field_name,
                old_value,
                new_value,
                edited_at_utc,
                edited_by
            FROM verification_audit
            WHERE bet_id = :bet_id
            ORDER BY edited_at_utc ASC
        """)

        result = self.session.execute(query, {'bet_id': bet_id})
        return [dict(row._mapping) for row in result.fetchall()]
```

---

#### Task 2.2.4: Create Bet Approval Business Logic

**File**: `src/domain/bet_approval.py` (NEW)

**Implementation**:
```python
"""Business logic for bet approval workflow."""
from decimal import Decimal
from typing import Dict, Any, Tuple
from sqlalchemy.orm import Session
from src.database.repositories.bet_repository import BetRepository
from src.database.repositories.audit_repository import AuditRepository
from src.utils.timestamp import utc_now_iso

class BetApprovalService:
    """Handles bet approval/rejection with audit logging."""

    def __init__(self, session: Session):
        self.session = session
        self.bet_repo = BetRepository(session)
        self.audit_repo = AuditRepository(session)

    def approve_bet(
        self,
        bet_id: int,
        edited_fields: Dict[str, Any]
    ) -> Tuple[bool, str]:
        """Approve a bet with optional field edits.

        Args:
            bet_id: ID of bet to approve
            edited_fields: Dictionary of {field_name: new_value} for edited fields

        Returns:
            (success, message)
        """
        try:
            # Get current bet
            bet = self.session.query(self.bet_repo.model).filter_by(bet_id=bet_id).one()

            # Track changes for audit
            changes = {}

            # Apply edits and track changes
            for field_name, new_value in edited_fields.items():
                old_value = getattr(bet, field_name, None)
                if old_value != new_value:
                    changes[field_name] = (old_value, new_value)
                    setattr(bet, field_name, new_value)

            # Update bet status
            changes['status'] = (bet.status, 'verified')
            bet.status = 'verified'
            bet.verified_at_utc = utc_now_iso()
            bet.verified_by = 'local_user'

            # Log all changes
            if changes:
                self.audit_repo.log_multiple_changes(bet_id, changes)

            self.session.commit()
            return True, f"Bet #{bet_id} approved successfully"

        except Exception as e:
            self.session.rollback()
            return False, f"Error approving bet: {str(e)}"

    def reject_bet(
        self,
        bet_id: int,
        rejection_reason: str = None
    ) -> Tuple[bool, str]:
        """Reject a bet.

        Args:
            bet_id: ID of bet to reject
            rejection_reason: Optional reason for rejection

        Returns:
            (success, message)
        """
        try:
            bet = self.session.query(self.bet_repo.model).filter_by(bet_id=bet_id).one()

            # Track status change
            changes = {'status': (bet.status, 'rejected')}

            # Update bet
            bet.status = 'rejected'
            bet.verified_at_utc = utc_now_iso()
            bet.verified_by = 'local_user'
            if rejection_reason:
                bet.rejection_reason = rejection_reason

            # Log change
            self.audit_repo.log_multiple_changes(bet_id, changes)

            self.session.commit()
            return True, f"Bet #{bet_id} rejected"

        except Exception as e:
            self.session.rollback()
            return False, f"Error rejecting bet: {str(e)}"
```

**Tests** (`tests/unit/test_bet_approval.py`):
```python
import pytest
from src.domain.bet_approval import BetApprovalService
from src.database.db import get_test_session

def test_approve_bet_with_edits():
    session = get_test_session()
    service = BetApprovalService(session)

    # Create test bet (assume helper function exists)
    bet = create_test_bet(session, status='incoming')

    # Approve with edits
    edits = {'odds': Decimal("1.95"), 'stake': Decimal("105")}
    success, message = service.approve_bet(bet.bet_id, edits)

    assert success
    assert bet.status == 'verified'
    assert bet.odds == Decimal("1.95")

    # Check audit trail
    audit_trail = service.audit_repo.get_bet_audit_trail(bet.bet_id)
    assert len(audit_trail) > 0
    assert any(a['field_name'] == 'odds' for a in audit_trail)

def test_reject_bet():
    session = get_test_session()
    service = BetApprovalService(session)

    bet = create_test_bet(session, status='incoming')

    success, message = service.reject_bet(bet.bet_id, "Accumulator not supported")

    assert success
    assert bet.status == 'rejected'
    assert bet.rejection_reason == "Accumulator not supported"
```

---

#### Task 2.2.5: Create Inline Editor Component

**File**: `src/streamlit_app/components/inline_editor.py` (NEW)

**Implementation**:
```python
"""Inline editing component for bet fields."""
import streamlit as st
from decimal import Decimal
from typing import Dict, Any
from src.database.db import get_session
from src.database.repositories.event_repository import EventRepository
from src.streamlit_app.utils.validators import validate_all_fields

def render_inline_editor(bet: Dict[str, Any]) -> Dict[str, Any]:
    """Render inline edit fields for a bet.

    Returns:
        Dictionary of edited field values
    """
    st.subheader(f"âœï¸ Edit Bet #{bet['bet_id']}")

    edited_values = {}

    # Canonical Event Selection
    st.markdown("#### Event")
    session = get_session()
    event_repo = EventRepository(session)

    events = event_repo.get_all_events(limit=50)
    event_options = {event_repo.get_event_display_string(e): e.canonical_event_id for e in events}
    event_options["âž• Create New Event"] = "CREATE_NEW"

    # Pre-select current event if exists
    current_event_display = None
    if bet.get('canonical_event_id'):
        for event in events:
            if event.canonical_event_id == bet['canonical_event_id']:
                current_event_display = event_repo.get_event_display_string(event)
                break

    selected_event_display = st.selectbox(
        "Event",
        options=list(event_options.keys()),
        index=list(event_options.keys()).index(current_event_display) if current_event_display else 0,
        key=f"event_{bet['bet_id']}"
    )

    if selected_event_display == "âž• Create New Event":
        # Show create new event modal (Task 2.2.6)
        from src.streamlit_app.components.event_modal import render_create_event_modal
        new_event = render_create_event_modal(bet['bet_id'])
        if new_event:
            edited_values['canonical_event_id'] = new_event.canonical_event_id
    else:
        edited_values['canonical_event_id'] = event_options[selected_event_display]

    # Market Details
    st.markdown("#### Market Details")
    col1, col2, col3 = st.columns(3)

    with col1:
        market_codes = [
            "TOTAL_GOALS_OVER_UNDER",
            "ASIAN_HANDICAP",
            "MATCH_WINNER",
            "BOTH_TEAMS_TO_SCORE"
        ]
        edited_values['market_code'] = st.selectbox(
            "Market Type",
            options=market_codes,
            index=market_codes.index(bet['market_code']) if bet.get('market_code') in market_codes else 0,
            key=f"market_{bet['bet_id']}"
        )

    with col2:
        period_scopes = ["FULL_MATCH", "FIRST_HALF", "SECOND_HALF"]
        edited_values['period_scope'] = st.selectbox(
            "Period",
            options=period_scopes,
            index=period_scopes.index(bet['period_scope']) if bet.get('period_scope') in period_scopes else 0,
            key=f"period_{bet['bet_id']}"
        )

    with col3:
        edited_values['line_value'] = st.number_input(
            "Line Value",
            value=float(bet['line_value']) if bet.get('line_value') else 0.0,
            step=0.5,
            format="%.1f",
            key=f"line_{bet['bet_id']}"
        )

    # Bet Side
    sides = ["OVER", "UNDER", "YES", "NO", "TEAM_A", "TEAM_B"]
    edited_values['side'] = st.selectbox(
        "Bet Side",
        options=sides,
        index=sides.index(bet['side']) if bet.get('side') in sides else 0,
        key=f"side_{bet['bet_id']}"
    )

    # Financial Details
    st.markdown("#### Financial Details")
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        edited_values['stake'] = Decimal(str(st.number_input(
            "Stake",
            value=float(bet['stake']) if bet.get('stake') else 0.0,
            min_value=0.0,
            step=10.0,
            format="%.2f",
            key=f"stake_{bet['bet_id']}"
        )))

    with col2:
        edited_values['odds'] = Decimal(str(st.number_input(
            "Odds",
            value=float(bet['odds']) if bet.get('odds') else 1.0,
            min_value=1.0,
            step=0.05,
            format="%.2f",
            key=f"odds_{bet['bet_id']}"
        )))

    with col3:
        edited_values['payout'] = Decimal(str(st.number_input(
            "Payout",
            value=float(bet['payout']) if bet.get('payout') else 0.0,
            min_value=0.0,
            step=10.0,
            format="%.2f",
            key=f"payout_{bet['bet_id']}"
        )))

    with col4:
        currencies = ["AUD", "GBP", "EUR", "USD"]
        edited_values['currency'] = st.selectbox(
            "Currency",
            options=currencies,
            index=currencies.index(bet['currency']) if bet.get('currency') in currencies else 0,
            key=f"currency_{bet['bet_id']}"
        )

    # Validation
    all_valid, errors = validate_all_fields(edited_values)

    if not all_valid:
        st.error("âŒ **Validation Errors:**")
        for error in errors:
            st.write(f"- {error}")

    return edited_values, all_valid
```

---

#### Task 2.2.6: Create Event Creation Modal

**File**: `src/streamlit_app/components/event_modal.py` (NEW)

**Implementation**:
```python
"""Modal for creating new canonical events."""
import streamlit as st
from src.database.db import get_session
from src.database.repositories.event_repository import EventRepository
from src.utils.timestamp import utc_now_iso

@st.dialog("Create New Event")
def render_create_event_modal(bet_id: int):
    """Render modal for creating a new canonical event.

    Returns:
        CanonicalEvent object if created, None otherwise
    """
    st.markdown("### Add New Sporting Event")

    # Event name
    event_name = st.text_input(
        "Event Name",
        placeholder="e.g., Manchester United vs Arsenal",
        help="Format: Team A vs Team B or Competitor 1 vs Competitor 2"
    )

    # Sport
    sports = ["Soccer", "Tennis", "Basketball", "Cricket", "Rugby", "Other"]
    sport = st.selectbox("Sport", options=sports)

    # Kickoff time
    kickoff_date = st.date_input("Match Date")
    kickoff_time = st.time_input("Kickoff Time (local)")

    # Combine date and time to UTC (simplified - assumes local is UTC for MVP)
    kickoff_datetime_utc = f"{kickoff_date.isoformat()}T{kickoff_time.isoformat()}:00Z"

    # Action buttons
    col1, col2 = st.columns(2)

    with col1:
        if st.button("Create Event", type="primary", use_container_width=True):
            if not event_name:
                st.error("Event name is required")
                return None

            try:
                session = get_session()
                repo = EventRepository(session)

                new_event = repo.create_event(
                    event_name=event_name,
                    sport=sport,
                    kickoff_time_utc=kickoff_datetime_utc
                )

                st.success(f"âœ… Event created: {event_name}")
                st.session_state[f"new_event_{bet_id}"] = new_event
                st.rerun()

            except Exception as e:
                st.error(f"Error creating event: {str(e)}")
                return None

    with col2:
        if st.button("Cancel", use_container_width=True):
            st.rerun()

    # Return newly created event from session state if exists
    return st.session_state.get(f"new_event_{bet_id}")
```

---

#### Task 2.2.7: Integrate Approval Workflow into Incoming Bets Page

**File**: `src/streamlit_app/pages/1_incoming_bets.py` (FINAL UPDATE)

Add after the bet card rendering loop:

```python
# Handle approval/rejection actions (triggered by session state)
for bet in incoming_bets:
    bet_dict = dict(bet._mapping)
    bet_id = bet_dict['bet_id']

    # Check if approve button was clicked
    if st.session_state.get(f"approve_bet_{bet_id}"):
        # Show editor modal
        with st.expander(f"âœï¸ Edit Bet #{bet_id}", expanded=True):
            from src.streamlit_app.components.inline_editor import render_inline_editor
            from src.domain.bet_approval import BetApprovalService

            edited_values, is_valid = render_inline_editor(bet_dict)

            col1, col2 = st.columns(2)

            with col1:
                if st.button(f"âœ… Confirm Approval - Bet #{bet_id}", disabled=not is_valid, type="primary"):
                    session = get_session()
                    approval_service = BetApprovalService(session)

                    success, message = approval_service.approve_bet(bet_id, edited_values)

                    if success:
                        st.success(message)
                        del st.session_state[f"approve_bet_{bet_id}"]
                        st.rerun()
                    else:
                        st.error(message)

            with col2:
                if st.button(f"Cancel - Bet #{bet_id}"):
                    del st.session_state[f"approve_bet_{bet_id}"]
                    st.rerun()

    # Check if reject button was clicked
    if st.session_state.get(f"reject_bet_{bet_id}"):
        with st.expander(f"âŒ Reject Bet #{bet_id}", expanded=True):
            st.warning("Are you sure you want to reject this bet?")

            rejection_reason = st.text_area(
                "Rejection Reason (optional)",
                placeholder="e.g., Accumulator not supported",
                key=f"rejection_reason_{bet_id}"
            )

            col1, col2 = st.columns(2)

            with col1:
                if st.button(f"âœ… Confirm Rejection - Bet #{bet_id}", type="primary"):
                    from src.domain.bet_approval import BetApprovalService

                    session = get_session()
                    approval_service = BetApprovalService(session)

                    success, message = approval_service.reject_bet(bet_id, rejection_reason)

                    if success:
                        st.success(message)
                        del st.session_state[f"reject_bet_{bet_id}"]
                        st.rerun()
                    else:
                        st.error(message)

            with col2:
                if st.button(f"Cancel - Bet #{bet_id}"):
                    del st.session_state[f"reject_bet_{bet_id}"]
                    st.rerun()
```

---

## Integration Testing

### End-to-End Approval Test

**File**: `tests/integration/test_approval_flow.py` (NEW)

**Implementation**:
```python
"""Integration test for bet approval flow."""
import pytest
from decimal import Decimal
from src.database.db import get_test_session
from src.domain.bet_approval import BetApprovalService
from src.database.repositories.audit_repository import AuditRepository

def test_full_approval_flow_with_edits():
    """Test complete approval flow: incoming â†’ edit â†’ approve â†’ verified."""
    session = get_test_session()

    # Create test bet (from Epic 1)
    from src.database.repositories.bet_repository import BetRepository
    repo = BetRepository(session)

    bet = repo.create_incoming_bet(
        associate_id=1,
        bookmaker_id=1,
        screenshot_path="data/screenshots/test.png",
        ingestion_source="manual_upload"
    )

    # Update with extraction results
    repo.update_extraction_results(bet.bet_id, {
        'canonical_event': "Test Event",
        'market_code': "TOTAL_GOALS_OVER_UNDER",
        'stake': Decimal("100"),
        'odds': Decimal("1.85"),  # Intentional error (will be corrected)
        'payout': Decimal("185"),
        'currency': "AUD",
        'confidence': 0.75
    })

    assert bet.status == "incoming"
    assert bet.odds == Decimal("1.85")

    # Approve with corrections
    approval_service = BetApprovalService(session)
    edits = {
        'odds': Decimal("1.95"),  # Corrected odds
        'payout': Decimal("195")  # Corrected payout
    }

    success, message = approval_service.approve_bet(bet.bet_id, edits)

    assert success
    session.refresh(bet)
    assert bet.status == "verified"
    assert bet.odds == Decimal("1.95")
    assert bet.verified_at_utc is not None

    # Verify audit trail
    audit_repo = AuditRepository(session)
    audit_trail = audit_repo.get_bet_audit_trail(bet.bet_id)

    assert len(audit_trail) >= 2  # odds and status changes
    assert any(a['field_name'] == 'odds' for a in audit_trail)
    assert any(a['old_value'] == '1.85' for a in audit_trail)
    assert any(a['new_value'] == '1.95' for a in audit_trail)

    print("âœ… Full approval flow test passed!")
    print(f"   Bet #{bet.bet_id} status: {bet.status}")
    print(f"   Audit trail entries: {len(audit_trail)}")
```

Run: `pytest tests/integration/test_approval_flow.py -v`

---

## Deployment Checklist

### Prerequisites

- [ ] Epic 1 complete and tested
- [ ] Database migration run (`verification_audit` table created)
- [ ] At least 5 test bets with `status="incoming"` exist

### Configuration

- [ ] `config/market_codes.yaml` created (optional reference data)
- [ ] Canonical events table seeded with upcoming matches
- [ ] Canonical markets table populated

### Testing

- [ ] Unit tests pass: `pytest tests/unit/ -v`
- [ ] Integration test passes: `pytest tests/integration/test_approval_flow.py -v`
- [ ] Manual UAT scenarios tested (all 5 from epic)

---

## Manual Testing Guide

### Test Scenario 1: Quick Approve (High Confidence)

**Setup**:
1. Have a bet with `normalization_confidence >= 0.8`
2. All fields extracted correctly

**Steps**:
1. Open "Incoming Bets" page
2. Locate bet with âœ… High badge
3. Review extracted data
4. Click "Approve" (no edits)
5. Verify bet disappears from queue
6. Check counter: "Approved Today" increments

**Expected**: Approval in <10 seconds, no errors

---

### Test Scenario 2: Edit and Approve (Low Confidence)

**Setup**:
1. Have a bet with intentional OCR error (e.g., odds 1.85 instead of 1.95)

**Steps**:
1. Open "Incoming Bets" page
2. Locate bet with âš ï¸ Low badge
3. Click "Approve"
4. Edit odds: change 1.85 â†’ 1.95
5. Click "Confirm Approval"
6. Verify bet approved with corrected value

**Expected**: Edit logged in audit trail, bet verified with new value

---

### Test Scenario 3: Reject Accumulator

**Setup**:
1. Have a bet with `is_multi=1`

**Steps**:
1. Locate bet with ðŸš« Accumulator flag
2. Click "Reject"
3. Enter reason: "Accumulator not supported"
4. Click "Confirm Rejection"
5. Verify bet disappears, counter updates

**Expected**: Bet rejected, reason logged

---

### Test Scenario 4: Create New Event

**Setup**:
1. Have a bet with unknown event

**Steps**:
1. Click "Approve"
2. In event dropdown, select "âž• Create New Event"
3. Modal opens
4. Enter: "Barcelona vs Real Madrid", Sport: Soccer, Date: tomorrow
5. Click "Create Event"
6. Verify event appears in dropdown
7. Complete approval

**Expected**: New event created, usable immediately

---

### Test Scenario 5: Validation Errors

**Setup**:
1. Any incoming bet

**Steps**:
1. Click "Approve"
2. Edit stake to 0 (invalid)
3. Attempt to confirm
4. Verify error message: "Stake must be greater than 0"
5. Button disabled until fixed

**Expected**: Validation prevents invalid data

---

## Troubleshooting

### Issue: Bet card not rendering

**Symptoms**: Blank space where bet should be

**Checks**:
1. Screenshot file exists? `ls data/screenshots/`
2. Query returning data? Check SQL
3. Streamlit error? Check console logs

**Fix**: Ensure Path imports correct, file permissions OK

---

### Issue: Approve button does nothing

**Symptoms**: Click approve, nothing happens

**Checks**:
1. Session state set? `st.write(st.session_state)`
2. Rerun triggered? Add debug `st.write("Clicked")`
3. Database write successful? Check transaction

**Fix**: Verify session state keys match button keys exactly

---

### Issue: Audit trail not logging

**Symptoms**: Edits not appearing in `verification_audit` table

**Checks**:
1. Table exists? `sqlite3 data/surebet.db ".tables"`
2. Insert failing silently? Add try/except logging
3. Commit called? Check `session.commit()`

**Fix**: Verify migration ran, add error handling

---

### Issue: Event dropdown empty

**Symptoms**: No events in dropdown

**Checks**:
1. Canonical events seeded? `SELECT COUNT(*) FROM canonical_events`
2. Query limit too low? Increase from 50 to 100
3. Repository returning data? Add debug print

**Fix**: Seed canonical_events table with test data

---

## Performance Optimization

### Lazy Load Screenshots

If >20 bets in queue:
- Load thumbnails on scroll (Streamlit `@st.fragment`)
- Generate 200px thumbnails on upload (Epic 1)
- Use `st.spinner()` for loading states

### Cache Database Queries

Add to top of page:
```python
@st.cache_data(ttl=5)
def get_incoming_bets():
    session = get_session()
    return session.execute(query).fetchall()
```

### Optimize Audit Logging

Batch insert audit entries:
```python
# Instead of N individual inserts
audit_repo.log_multiple_changes(bet_id, {
    'odds': (old, new),
    'stake': (old2, new2),
    # ...
})
```

---

## Next Steps

### After Epic 2 Completion

1. **Run Definition of Done** (from [epic-2-bet-review.md](./epic-2-bet-review.md))
2. **Measure Success Metrics**:
   - Review speed: Time to approve 20 bets
   - Accuracy: % of bets requiring post-approval correction
   - Audit coverage: % of edits logged
3. **Demo to Stakeholders**: Show inline editing workflow
4. **Prepare for Epic 3**: Ensure `status="verified"` bets exist

### Epic 3 Preview

Epic 3 (Surebet Matching) depends on:
- âœ… `status="verified"` bets available
- âœ… Multiple bets on same event
- âœ… Opposite sides (OVER/UNDER, YES/NO, TEAM_A/TEAM_B)

---

## Appendix: Quick Commands

### Check Approved Bets

```bash
sqlite3 data/surebet.db "SELECT bet_id, status, verified_at_utc FROM bets WHERE status='verified' ORDER BY verified_at_utc DESC LIMIT 10;"
```

### View Audit Trail

```bash
sqlite3 data/surebet.db "SELECT * FROM verification_audit WHERE bet_id=<ID> ORDER BY edited_at_utc;"
```

### Count Bets by Status

```bash
sqlite3 data/surebet.db "SELECT status, COUNT(*) as count FROM bets GROUP BY status;"
```

---

**End of Implementation Guide**
