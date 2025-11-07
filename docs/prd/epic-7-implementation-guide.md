# Epic 7: System Administration - Implementation Guide

**Epic Reference**: [epic-7-system-administration.md](./epic-7-system-administration.md)
**Status**: Ready for Development
**Estimated Effort**: 3-4 days (1 developer)

---

## Overview

This guide provides detailed, step-by-step implementation instructions for Epic 7 (Associate & Bookmaker Management UI).

**Epic Goal**: Build web-based CRUD interface for associates, bookmakers, and balance checks.

**Prerequisites**:
- âœ… Database schema created (Epic 0)
- âœ… Existing Streamlit app structure
- âœ… Telegram bot operational (optional, for testing integration)
- âœ… FXManager service available (for Story 7.3 balance checks)

**Key Principle**: Epic 7 uses **existing tables only** (no migrations, no schema changes).

---

## Code Structure

### Recommended File Organization

```
Final_App/
â”œâ”€â”€ src/
â”‚   â”œâ”€â”€ ui/
â”‚   â”‚   â”œâ”€â”€ pages/
â”‚   â”‚   â”‚   â”œâ”€â”€ 1_incoming_bets.py         # Existing
â”‚   â”‚   â”‚   â”œâ”€â”€ 2_verified_bets.py          # Existing
â”‚   â”‚   â”‚   â”œâ”€â”€ 3_verified_bets_queue.py    # Existing
â”‚   â”‚   â”‚   â””â”€â”€ 7_admin_associates.py       # NEW (Story 7.1, 7.2, 7.3)
â”‚   â”‚   â””â”€â”€ components/
â”‚   â”‚       â”œâ”€â”€ bet_card.py                 # Existing
â”‚   â”‚       â”œâ”€â”€ manual_upload.py            # Existing
â”‚   â”‚       â””â”€â”€ associate_forms.py          # NEW (Story 7.1, 7.2)
â”‚   â”œâ”€â”€ services/
â”‚   â”‚   â”œâ”€â”€ bet_verification.py             # Existing
â”‚   â”‚   â”œâ”€â”€ fx_manager.py                   # Existing
â”‚   â”‚   â””â”€â”€ associate_management.py         # NEW (Story 7.1, 7.2, 7.3)
â”‚   â”œâ”€â”€ core/
â”‚   â”‚   â”œâ”€â”€ database.py                     # Existing
â”‚   â”‚   â””â”€â”€ schema.py                       # Existing (NO CHANGES)
â”‚   â””â”€â”€ integrations/
â”‚       â””â”€â”€ telegram_bot.py                 # Existing (NO CHANGES)
â”œâ”€â”€ tests/
â”‚   â””â”€â”€ unit/
â”‚       â”œâ”€â”€ test_associate_management.py    # NEW
â”‚       â””â”€â”€ test_admin_ui.py                # NEW (optional)
â””â”€â”€ docs/
    â””â”€â”€ prd/
        â”œâ”€â”€ epic-7-system-administration.md         # Created in Task 0
        â””â”€â”€ epic-7-implementation-guide.md          # This file
```

**Note**: No new database files, no schema migrations. All database tables already exist.

---

## Implementation Workflow

### Phase 1: Service Layer (Story 7.1, 7.2, 7.3)
1. Create `AssociateManagementService` class
2. Implement CRUD methods for associates
3. Implement CRUD methods for bookmakers
4. Implement CRUD methods for balance checks
5. Add validation logic

### Phase 2: UI Components (Story 7.1, 7.2)
1. Create reusable form components
2. Create validation helpers
3. Create UI formatters

### Phase 3: Streamlit Page (Story 7.1, 7.2, 7.3)
1. Create `7_admin_associates.py`
2. Implement Tab 1: Associates & Bookmakers
3. Implement Tab 2: Balance History
4. Add search/filter functionality

### Phase 4: Testing & Integration
1. Unit tests for service layer
2. Manual UI testing
3. Integration testing with Telegram bot

---

## Story 7.1: Associate Management UI

### Task 7.1.1: Create AssociateManagementService (Associates CRUD)

**File**: `src/services/associate_management.py`

**Implementation**:

```python
"""Service for managing associates, bookmakers, and balance checks."""
import sqlite3
from typing import Optional, List, Dict, Tuple
from decimal import Decimal
from datetime import datetime


class AssociateManagementService:
    """Handles CRUD operations for associates, bookmakers, and balance checks."""

    def __init__(self, db: sqlite3.Connection):
        """
        Initialize service with database connection.

        Args:
            db: SQLite database connection
        """
        self.db = db
        self.db.row_factory = sqlite3.Row

    # ============================================================================
    # ASSOCIATES CRUD
    # ============================================================================

    def get_all_associates(self, search_query: Optional[str] = None) -> List[Dict]:
        """
        Get all associates with optional search filter.

        Args:
            search_query: Optional search string (filters by alias, case-insensitive)

        Returns:
            List of associate dictionaries with bookmaker_count
        """
        cursor = self.db.cursor()

        query = """
            SELECT
                a.id,
                a.display_alias,
                a.home_currency,
                a.is_admin,
                a.multibook_chat_id,
                a.created_at_utc,
                a.updated_at_utc,
                COUNT(b.id) as bookmaker_count
            FROM associates a
            LEFT JOIN bookmakers b ON a.id = b.associate_id
        """

        params = []
        if search_query:
            query += " WHERE LOWER(a.display_alias) LIKE LOWER(?)"
            params.append(f"%{search_query}%")

        query += " GROUP BY a.id ORDER BY a.display_alias ASC"

        cursor.execute(query, params)
        rows = cursor.fetchall()
        cursor.close()

        return [dict(row) for row in rows]

    def get_associate_by_id(self, associate_id: int) -> Optional[Dict]:
        """Get associate by ID."""
        cursor = self.db.cursor()
        cursor.execute("SELECT * FROM associates WHERE id = ?", (associate_id,))
        row = cursor.fetchone()
        cursor.close()
        return dict(row) if row else None

    def create_associate(
        self,
        display_alias: str,
        home_currency: str,
        is_admin: bool = False,
        multibook_chat_id: Optional[str] = None
    ) -> int:
        """
        Create new associate.

        Args:
            display_alias: Unique alias (e.g., "Admin", "Partner A")
            home_currency: ISO currency code (e.g., "EUR", "GBP")
            is_admin: Admin flag
            multibook_chat_id: Optional Telegram chat ID for coverage proof

        Returns:
            New associate ID

        Raises:
            sqlite3.IntegrityError: If alias already exists
        """
        cursor = self.db.cursor()

        now_utc = datetime.utcnow().isoformat() + 'Z'

        cursor.execute("""
            INSERT INTO associates (
                display_alias, home_currency, is_admin, multibook_chat_id,
                created_at_utc, updated_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (display_alias, home_currency, is_admin, multibook_chat_id, now_utc, now_utc))

        self.db.commit()
        associate_id = cursor.lastrowid
        cursor.close()

        return associate_id

    def update_associate(
        self,
        associate_id: int,
        display_alias: str,
        home_currency: str,
        is_admin: bool,
        multibook_chat_id: Optional[str] = None
    ) -> None:
        """
        Update existing associate.

        Raises:
            sqlite3.IntegrityError: If alias already exists (on another record)
        """
        cursor = self.db.cursor()

        now_utc = datetime.utcnow().isoformat() + 'Z'

        cursor.execute("""
            UPDATE associates
            SET display_alias = ?, home_currency = ?, is_admin = ?,
                multibook_chat_id = ?, updated_at_utc = ?
            WHERE id = ?
        """, (display_alias, home_currency, is_admin, multibook_chat_id, now_utc, associate_id))

        self.db.commit()
        cursor.close()

    def can_delete_associate(self, associate_id: int) -> Tuple[bool, str]:
        """
        Check if associate can be safely deleted.

        Returns:
            (can_delete: bool, reason: str)
        """
        cursor = self.db.cursor()

        # Check bets
        cursor.execute("SELECT COUNT(*) FROM bets WHERE associate_id = ?", (associate_id,))
        bet_count = cursor.fetchone()[0]

        # Check ledger entries
        cursor.execute("SELECT COUNT(*) FROM ledger_entries WHERE associate_id = ?", (associate_id,))
        ledger_count = cursor.fetchone()[0]

        cursor.close()

        if bet_count > 0 or ledger_count > 0:
            return False, f"Associate has {bet_count} bets and {ledger_count} ledger entries"

        return True, "OK"

    def delete_associate(self, associate_id: int) -> None:
        """
        Delete associate (cascades to bookmakers).

        Note: Should call can_delete_associate() first to validate.
        """
        cursor = self.db.cursor()
        cursor.execute("DELETE FROM associates WHERE id = ?", (associate_id,))
        self.db.commit()
        cursor.close()

    # ============================================================================
    # BOOKMAKERS CRUD
    # ============================================================================

    def get_bookmakers_for_associate(self, associate_id: int) -> List[Dict]:
        """Get all bookmakers for an associate with chat registration status."""
        cursor = self.db.cursor()

        cursor.execute("""
            SELECT
                b.id,
                b.associate_id,
                b.bookmaker_name,
                b.parsing_profile,
                b.is_active,
                b.created_at_utc,
                b.updated_at_utc,
                cr.chat_id,
                cr.is_active as chat_is_active
            FROM bookmakers b
            LEFT JOIN chat_registrations cr ON b.id = cr.bookmaker_id
            WHERE b.associate_id = ?
            ORDER BY b.bookmaker_name ASC
        """, (associate_id,))

        rows = cursor.fetchall()
        cursor.close()

        return [dict(row) for row in rows]

    def create_bookmaker(
        self,
        associate_id: int,
        bookmaker_name: str,
        parsing_profile: Optional[str] = None,
        is_active: bool = True
    ) -> int:
        """
        Create new bookmaker.

        Raises:
            sqlite3.IntegrityError: If (associate_id, bookmaker_name) already exists
        """
        cursor = self.db.cursor()

        now_utc = datetime.utcnow().isoformat() + 'Z'

        cursor.execute("""
            INSERT INTO bookmakers (
                associate_id, bookmaker_name, parsing_profile, is_active,
                created_at_utc, updated_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (associate_id, bookmaker_name, parsing_profile, is_active, now_utc, now_utc))

        self.db.commit()
        bookmaker_id = cursor.lastrowid
        cursor.close()

        return bookmaker_id

    def update_bookmaker(
        self,
        bookmaker_id: int,
        bookmaker_name: str,
        parsing_profile: Optional[str],
        is_active: bool
    ) -> None:
        """Update existing bookmaker."""
        cursor = self.db.cursor()

        now_utc = datetime.utcnow().isoformat() + 'Z'

        cursor.execute("""
            UPDATE bookmakers
            SET bookmaker_name = ?, parsing_profile = ?, is_active = ?, updated_at_utc = ?
            WHERE id = ?
        """, (bookmaker_name, parsing_profile, is_active, now_utc, bookmaker_id))

        self.db.commit()
        cursor.close()

    def can_delete_bookmaker(self, bookmaker_id: int) -> Tuple[bool, str, int]:
        """
        Check if bookmaker can be deleted.

        Returns:
            (can_delete: bool, warning: str, bet_count: int)
        """
        cursor = self.db.cursor()

        cursor.execute("SELECT COUNT(*) FROM bets WHERE bookmaker_id = ?", (bookmaker_id,))
        bet_count = cursor.fetchone()[0]

        cursor.close()

        if bet_count > 0:
            return True, f"âš ï¸ This bookmaker has {bet_count} bets. Deleting will orphan these records.", bet_count

        return True, "OK", 0

    def delete_bookmaker(self, bookmaker_id: int) -> None:
        """Delete bookmaker (may orphan bets - caller should validate first)."""
        cursor = self.db.cursor()
        cursor.execute("DELETE FROM bookmakers WHERE id = ?", (bookmaker_id,))
        self.db.commit()
        cursor.close()

    # ============================================================================
    # BALANCE CHECKS CRUD
    # ============================================================================

    def get_balance_checks(
        self,
        associate_id: Optional[int] = None,
        bookmaker_id: Optional[int] = None,
        limit: int = 100
    ) -> List[Dict]:
        """
        Get balance checks with optional filters.

        Args:
            associate_id: Filter by associate
            bookmaker_id: Filter by bookmaker
            limit: Max rows to return

        Returns:
            List of balance check dictionaries
        """
        cursor = self.db.cursor()

        query = """
            SELECT
                bc.id,
                bc.associate_id,
                bc.bookmaker_id,
                bc.balance_native,
                bc.native_currency,
                bc.balance_eur,
                bc.fx_rate_used,
                bc.check_date_utc,
                bc.created_at_utc,
                bc.note,
                a.display_alias,
                b.bookmaker_name
            FROM bookmaker_balance_checks bc
            JOIN associates a ON bc.associate_id = a.id
            JOIN bookmakers b ON bc.bookmaker_id = b.id
            WHERE 1=1
        """

        params = []
        if associate_id:
            query += " AND bc.associate_id = ?"
            params.append(associate_id)
        if bookmaker_id:
            query += " AND bc.bookmaker_id = ?"
            params.append(bookmaker_id)

        query += " ORDER BY bc.check_date_utc DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()
        cursor.close()

        return [dict(row) for row in rows]

    def get_latest_balance(self, associate_id: int, bookmaker_id: int) -> Optional[Dict]:
        """Get most recent balance check for associate + bookmaker."""
        cursor = self.db.cursor()

        cursor.execute("""
            SELECT * FROM bookmaker_balance_checks
            WHERE associate_id = ? AND bookmaker_id = ?
            ORDER BY check_date_utc DESC
            LIMIT 1
        """, (associate_id, bookmaker_id))

        row = cursor.fetchone()
        cursor.close()

        return dict(row) if row else None

    def create_balance_check(
        self,
        associate_id: int,
        bookmaker_id: int,
        balance_native: Decimal,
        native_currency: str,
        fx_rate_used: Decimal,
        check_date_utc: str,
        note: Optional[str] = None
    ) -> int:
        """
        Create new balance check.

        Args:
            balance_native: Balance in native currency
            native_currency: Currency code (e.g., "EUR", "GBP")
            fx_rate_used: FX rate used (EUR per 1 unit native)
            check_date_utc: ISO8601 UTC timestamp

        Returns:
            New balance check ID
        """
        cursor = self.db.cursor()

        balance_eur = balance_native * fx_rate_used
        now_utc = datetime.utcnow().isoformat() + 'Z'

        cursor.execute("""
            INSERT INTO bookmaker_balance_checks (
                associate_id, bookmaker_id, balance_native, native_currency,
                balance_eur, fx_rate_used, check_date_utc, created_at_utc, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            associate_id, bookmaker_id, str(balance_native), native_currency,
            str(balance_eur), str(fx_rate_used), check_date_utc, now_utc, note
        ))

        self.db.commit()
        balance_check_id = cursor.lastrowid
        cursor.close()

        return balance_check_id

    def update_balance_check(
        self,
        balance_check_id: int,
        balance_native: Decimal,
        native_currency: str,
        fx_rate_used: Decimal,
        check_date_utc: str,
        note: Optional[str] = None
    ) -> None:
        """Update existing balance check."""
        cursor = self.db.cursor()

        balance_eur = balance_native * fx_rate_used

        cursor.execute("""
            UPDATE bookmaker_balance_checks
            SET balance_native = ?, native_currency = ?, balance_eur = ?,
                fx_rate_used = ?, check_date_utc = ?, note = ?
            WHERE id = ?
        """, (
            str(balance_native), native_currency, str(balance_eur),
            str(fx_rate_used), check_date_utc, note, balance_check_id
        ))

        self.db.commit()
        cursor.close()

    def delete_balance_check(self, balance_check_id: int) -> None:
        """Delete balance check."""
        cursor = self.db.cursor()
        cursor.execute("DELETE FROM bookmaker_balance_checks WHERE id = ?", (balance_check_id,))
        self.db.commit()
        cursor.close()

    def calculate_modeled_balance(self, associate_id: int, bookmaker_id: int) -> Decimal:
        """
        Calculate modeled balance from ledger entries.

        Returns:
            Balance in EUR (sum of all ledger entries)
        """
        cursor = self.db.cursor()

        cursor.execute("""
            SELECT COALESCE(SUM(CAST(amount_eur AS REAL)), 0.0) as total_eur
            FROM ledger_entries
            WHERE associate_id = ? AND bookmaker_id = ?
        """, (associate_id, bookmaker_id))

        row = cursor.fetchone()
        cursor.close()

        return Decimal(str(row[0]))
```

**Tests** (`tests/unit/test_associate_management.py`):

```python
"""Unit tests for AssociateManagementService."""
import pytest
import sqlite3
from decimal import Decimal
from src.services.associate_management import AssociateManagementService
from src.core.database import get_db_connection, initialize_database


@pytest.fixture
def db_connection():
    """Create in-memory test database."""
    conn = sqlite3.connect(":memory:")
    initialize_database(conn)
    yield conn
    conn.close()


@pytest.fixture
def service(db_connection):
    """Create service instance."""
    return AssociateManagementService(db_connection)


class TestAssociateCRUD:
    """Test associate CRUD operations."""

    def test_create_associate(self, service):
        """Test creating new associate."""
        associate_id = service.create_associate(
            display_alias="Test Associate",
            home_currency="USD",
            is_admin=False
        )
        assert associate_id > 0

        # Verify created
        associate = service.get_associate_by_id(associate_id)
        assert associate["display_alias"] == "Test Associate"
        assert associate["home_currency"] == "USD"
        assert associate["is_admin"] == False

    def test_create_duplicate_alias_fails(self, service):
        """Test duplicate alias raises error."""
        service.create_associate("Duplicate", "EUR")

        with pytest.raises(sqlite3.IntegrityError):
            service.create_associate("Duplicate", "GBP")

    def test_update_associate(self, service):
        """Test updating associate."""
        associate_id = service.create_associate("Original", "EUR")

        service.update_associate(
            associate_id=associate_id,
            display_alias="Updated",
            home_currency="GBP",
            is_admin=True
        )

        associate = service.get_associate_by_id(associate_id)
        assert associate["display_alias"] == "Updated"
        assert associate["home_currency"] == "GBP"
        assert associate["is_admin"] == True

    def test_can_delete_associate_with_no_bets(self, service):
        """Test can delete associate with no bets."""
        associate_id = service.create_associate("Deletable", "EUR")

        can_delete, reason = service.can_delete_associate(associate_id)
        assert can_delete is True
        assert reason == "OK"

    def test_delete_associate(self, service):
        """Test deleting associate."""
        associate_id = service.create_associate("ToDelete", "EUR")

        service.delete_associate(associate_id)

        associate = service.get_associate_by_id(associate_id)
        assert associate is None


class TestBookmakerCRUD:
    """Test bookmaker CRUD operations."""

    def test_create_bookmaker(self, service):
        """Test creating bookmaker."""
        associate_id = service.create_associate("Test", "EUR")

        bookmaker_id = service.create_bookmaker(
            associate_id=associate_id,
            bookmaker_name="Bet365",
            is_active=True
        )
        assert bookmaker_id > 0

    def test_get_bookmakers_for_associate(self, service):
        """Test getting bookmakers."""
        associate_id = service.create_associate("Test", "EUR")
        service.create_bookmaker(associate_id, "Bet365")
        service.create_bookmaker(associate_id, "Pinnacle")

        bookmakers = service.get_bookmakers_for_associate(associate_id)
        assert len(bookmakers) == 2

    def test_delete_bookmaker(self, service):
        """Test deleting bookmaker."""
        associate_id = service.create_associate("Test", "EUR")
        bookmaker_id = service.create_bookmaker(associate_id, "Bet365")

        service.delete_bookmaker(bookmaker_id)

        bookmakers = service.get_bookmakers_for_associate(associate_id)
        assert len(bookmakers) == 0


class TestBalanceCheckCRUD:
    """Test balance check CRUD operations."""

    def test_create_balance_check(self, service):
        """Test creating balance check."""
        associate_id = service.create_associate("Test", "EUR")
        bookmaker_id = service.create_bookmaker(associate_id, "Bet365")

        balance_check_id = service.create_balance_check(
            associate_id=associate_id,
            bookmaker_id=bookmaker_id,
            balance_native=Decimal("1000.00"),
            native_currency="EUR",
            fx_rate_used=Decimal("1.0"),
            check_date_utc="2025-11-03T10:00:00Z"
        )
        assert balance_check_id > 0

    def test_get_latest_balance(self, service):
        """Test getting latest balance."""
        associate_id = service.create_associate("Test", "EUR")
        bookmaker_id = service.create_bookmaker(associate_id, "Bet365")

        service.create_balance_check(
            associate_id, bookmaker_id, Decimal("1000"), "EUR",
            Decimal("1.0"), "2025-11-01T10:00:00Z"
        )
        service.create_balance_check(
            associate_id, bookmaker_id, Decimal("1500"), "EUR",
            Decimal("1.0"), "2025-11-02T10:00:00Z"
        )

        latest = service.get_latest_balance(associate_id, bookmaker_id)
        assert Decimal(latest["balance_native"]) == Decimal("1500")
```

**Validation**:
- [ ] All tests pass
- [ ] Service handles SQLite integrity errors gracefully
- [ ] Timestamps use UTC ISO8601 format
- [ ] Decimal values stored as TEXT

---

### Task 7.1.2: Create Streamlit Page (`7_admin_associates.py`)

**File**: `src/ui/pages/7_admin_associates.py`

**Implementation** (Story 7.1 - Associates tab only):

```python
"""Associate and Bookmaker Management UI."""
import streamlit as st
import sqlite3
from src.core.database import get_db_connection
from src.services.associate_management import AssociateManagementService


st.set_page_config(page_title="Associate Management", page_icon="ðŸ§‘â€ðŸ’¼")

# Initialize database connection
@st.cache_resource
def get_db():
    """Get database connection (cached)."""
    return get_db_connection()

db = get_db()
service = AssociateManagementService(db)


def main():
    """Main page layout."""
    st.title("ðŸ§‘â€ðŸ’¼ Associate & Bookmaker Management")

    # Tabs
    tab1, tab2 = st.tabs(["Associates & Bookmakers", "Balance History"])

    with tab1:
        render_associates_tab()

    with tab2:
        render_balance_history_tab()


def render_associates_tab():
    """Render associates and bookmakers tab."""
    st.header("Associates")

    # Search bar and Add button
    col1, col2 = st.columns([3, 1])
    with col1:
        search_query = st.text_input("ðŸ” Search by alias", key="search_associates")
    with col2:
        if st.button("âž• Add Associate", width="stretch"):
            st.session_state.show_add_associate_modal = True

    # Get associates
    associates = service.get_all_associates(search_query if search_query else None)
    st.write(f"**Total Associates:** {len(associates)}")

    # Display associates table
    for associate in associates:
        with st.expander(f"{'â–¼' if st.session_state.get(f'expand_{associate['id']}', False) else 'â–¶'} {associate['display_alias']}"):
            render_associate_row(associate)

    # Add Associate Modal
    if st.session_state.get("show_add_associate_modal", False):
        render_add_associate_modal()


def render_associate_row(associate: dict):
    """Render individual associate row with bookmakers."""
    col1, col2, col3, col4 = st.columns([2, 1, 1, 1])

    with col1:
        st.write(f"**Currency:** {associate['home_currency']}")
    with col2:
        st.write(f"**Admin:** {'âœ“' if associate['is_admin'] else ''}")
    with col3:
        st.write(f"**Bookmakers:** {associate['bookmaker_count']}")
    with col4:
        if st.button("âœï¸ Edit", key=f"edit_assoc_{associate['id']}"):
            st.session_state[f"edit_associate_{associate['id']}"] = True
        if st.button("ðŸ—‘ï¸ Delete", key=f"del_assoc_{associate['id']}"):
            handle_delete_associate(associate['id'], associate['display_alias'])

    # Show bookmakers if expanded
    if st.session_state.get(f'expand_{associate['id']}', False):
        render_bookmakers_for_associate(associate['id'])

    # Edit modal
    if st.session_state.get(f"edit_associate_{associate['id']}", False):
        render_edit_associate_modal(associate)


def render_bookmakers_for_associate(associate_id: int):
    """Render bookmakers for an associate."""
    st.subheader("Bookmakers")

    bookmakers = service.get_bookmakers_for_associate(associate_id)

    if not bookmakers:
        st.info("No bookmakers yet.")
    else:
        for bm in bookmakers:
            col1, col2, col3, col4 = st.columns([3, 2, 1, 1])
            with col1:
                st.write(f"**{bm['bookmaker_name']}**")
            with col2:
                status = "âœ… Active" if bm['is_active'] else "âš ï¸ Inactive"
                st.write(status)
            with col3:
                chat_status = "âœ… Registered" if bm['chat_id'] else "âš ï¸ Not Registered"
                st.write(chat_status)
            with col4:
                if st.button("ðŸ—‘ï¸", key=f"del_bm_{bm['id']}"):
                    handle_delete_bookmaker(bm['id'], bm['bookmaker_name'])

    if st.button("âž• Add Bookmaker", key=f"add_bm_{associate_id}"):
        st.session_state[f"show_add_bookmaker_{associate_id}"] = True


def render_add_associate_modal():
    """Modal for adding new associate."""
    with st.form("add_associate_form"):
        st.subheader("Add New Associate")

        display_alias = st.text_input("Display Alias *", max_chars=50)
        home_currency = st.selectbox("Home Currency *", ["EUR", "GBP", "USD", "AUD", "CAD", "JPY"])
        is_admin = st.checkbox("Is Admin")
        multibook_chat_id = st.text_input("Multibook Chat ID (optional)")

        col1, col2 = st.columns(2)
        with col1:
            submitted = st.form_submit_button("Save", width="stretch")
        with col2:
            canceled = st.form_submit_button("Cancel", width="stretch")

        if submitted:
            if not display_alias:
                st.error("âŒ Alias is required")
            else:
                try:
                    service.create_associate(
                        display_alias=display_alias,
                        home_currency=home_currency,
                        is_admin=is_admin,
                        multibook_chat_id=multibook_chat_id if multibook_chat_id else None
                    )
                    st.success(f"âœ… Associate '{display_alias}' created")
                    st.session_state.show_add_associate_modal = False
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("âŒ Alias already exists")

        if canceled:
            st.session_state.show_add_associate_modal = False
            st.rerun()


def render_edit_associate_modal(associate: dict):
    """Modal for editing associate."""
    with st.form(f"edit_associate_form_{associate['id']}"):
        st.subheader(f"Edit Associate: {associate['display_alias']}")

        display_alias = st.text_input("Display Alias *", value=associate['display_alias'])
        home_currency = st.selectbox(
            "Home Currency *",
            ["EUR", "GBP", "USD", "AUD", "CAD", "JPY"],
            index=["EUR", "GBP", "USD", "AUD", "CAD", "JPY"].index(associate['home_currency'])
        )
        is_admin = st.checkbox("Is Admin", value=bool(associate['is_admin']))
        multibook_chat_id = st.text_input(
            "Multibook Chat ID (optional)",
            value=associate['multibook_chat_id'] or ""
        )

        col1, col2 = st.columns(2)
        with col1:
            submitted = st.form_submit_button("Save", width="stretch")
        with col2:
            canceled = st.form_submit_button("Cancel", width="stretch")

        if submitted:
            try:
                service.update_associate(
                    associate_id=associate['id'],
                    display_alias=display_alias,
                    home_currency=home_currency,
                    is_admin=is_admin,
                    multibook_chat_id=multibook_chat_id if multibook_chat_id else None
                )
                st.success(f"âœ… Associate updated")
                st.session_state[f"edit_associate_{associate['id']}"] = False
                st.rerun()
            except sqlite3.IntegrityError:
                st.error("âŒ Alias already exists")

        if canceled:
            st.session_state[f"edit_associate_{associate['id']}"] = False
            st.rerun()


def handle_delete_associate(associate_id: int, display_alias: str):
    """Handle associate deletion with validation."""
    can_delete, reason = service.can_delete_associate(associate_id)

    if not can_delete:
        st.error(f"âŒ Cannot delete associate: {reason}")
    else:
        if st.button(f"âš ï¸ Confirm delete '{display_alias}'?", key=f"confirm_del_{associate_id}"):
            service.delete_associate(associate_id)
            st.success(f"âœ… Associate '{display_alias}' deleted")
            st.rerun()


def handle_delete_bookmaker(bookmaker_id: int, bookmaker_name: str):
    """Handle bookmaker deletion with warning."""
    can_delete, warning, bet_count = service.can_delete_bookmaker(bookmaker_id)

    if bet_count > 0:
        st.warning(warning)

    if st.button(f"âš ï¸ Confirm delete '{bookmaker_name}'?", key=f"confirm_del_bm_{bookmaker_id}"):
        service.delete_bookmaker(bookmaker_id)
        st.success(f"âœ… Bookmaker '{bookmaker_name}' deleted")
        st.rerun()


def render_balance_history_tab():
    """Render balance history tab (Story 7.3)."""
    st.header("Balance History")
    st.info("Balance management UI - To be implemented in Story 7.3")


if __name__ == "__main__":
    main()
```

**Validation**:
- [ ] Page loads without errors
- [ ] Can add new associate
- [ ] Duplicate alias shows error
- [ ] Can edit associate
- [ ] Can delete associate (with validation)
- [ ] Associates table displays correctly
- [ ] Search/filter works

---

## Story 7.2: Bookmaker Management UI

**(See Story 7.1 implementation above - bookmakers included in same page)**

Additional tasks for Story 7.2:

### Task 7.2.1: Add Bookmaker Form Component

**Add to `7_admin_associates.py`**:

```python
def render_add_bookmaker_modal(associate_id: int):
    """Modal for adding bookmaker."""
    with st.form(f"add_bookmaker_form_{associate_id}"):
        st.subheader("Add Bookmaker")

        bookmaker_name = st.text_input("Bookmaker Name *")
        parsing_profile = st.text_area("Parsing Profile (optional JSON)")
        is_active = st.checkbox("Is Active", value=True)

        col1, col2 = st.columns(2)
        with col1:
            submitted = st.form_submit_button("Save", width="stretch")
        with col2:
            canceled = st.form_submit_button("Cancel", width="stretch")

        if submitted:
            if not bookmaker_name:
                st.error("âŒ Bookmaker name is required")
            else:
                try:
                    service.create_bookmaker(
                        associate_id=associate_id,
                        bookmaker_name=bookmaker_name,
                        parsing_profile=parsing_profile if parsing_profile else None,
                        is_active=is_active
                    )
                    st.success(f"âœ… Bookmaker '{bookmaker_name}' added")
                    st.session_state[f"show_add_bookmaker_{associate_id}"] = False
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("âŒ Bookmaker already exists for this associate")

        if canceled:
            st.session_state[f"show_add_bookmaker_{associate_id}"] = False
            st.rerun()
```

**Validation**:
- [ ] Can add bookmaker to associate
- [ ] Duplicate bookmaker name (per associate) shows error
- [ ] Parsing profile is optional
- [ ] Active status defaults to TRUE

---

## Story 7.3: Balance Management UI

### Task 7.3.1: Implement Balance History Tab

**Add to `7_admin_associates.py`** (replace placeholder):

```python
def render_balance_history_tab():
    """Render balance history tab."""
    st.header("Balance History")

    # Filters
    col1, col2 = st.columns(2)

    with col1:
        associates = service.get_all_associates()
        associate_options = {a['id']: a['display_alias'] for a in associates}
        selected_associate_id = st.selectbox(
            "Associate",
            options=list(associate_options.keys()),
            format_func=lambda x: associate_options[x],
            key="balance_associate_filter"
        )

    with col2:
        if selected_associate_id:
            bookmakers = service.get_bookmakers_for_associate(selected_associate_id)
            bookmaker_options = {b['id']: b['bookmaker_name'] for b in bookmakers}

            if bookmaker_options:
                selected_bookmaker_id = st.selectbox(
                    "Bookmaker",
                    options=list(bookmaker_options.keys()),
                    format_func=lambda x: bookmaker_options[x],
                    key="balance_bookmaker_filter"
                )
            else:
                st.warning("No bookmakers for this associate")
                selected_bookmaker_id = None
        else:
            selected_bookmaker_id = None

    # Current status
    if selected_associate_id and selected_bookmaker_id:
        st.subheader("Current Status")

        latest_balance = service.get_latest_balance(selected_associate_id, selected_bookmaker_id)
        modeled_balance_eur = service.calculate_modeled_balance(selected_associate_id, selected_bookmaker_id)

        if latest_balance:
            latest_eur = Decimal(latest_balance['balance_eur'])
            delta = latest_eur - modeled_balance_eur

            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Latest Balance", f"â‚¬{latest_eur:,.2f}")
            with col2:
                st.metric("Modeled Balance", f"â‚¬{modeled_balance_eur:,.2f}")
            with col3:
                delta_label = "âœ… Balanced" if abs(delta) < 1.0 else f"{'âŒ' if delta > 1.0 else 'âš ï¸'} {delta:+,.2f} EUR"
                st.metric("Difference", delta_label)
        else:
            st.info("No balance checks recorded yet")

        # Add balance check button
        if st.button("âž• Add Balance Check"):
            st.session_state.show_add_balance_modal = True

        # Balance history table
        st.subheader("Balance Check History")
        balance_checks = service.get_balance_checks(
            associate_id=selected_associate_id,
            bookmaker_id=selected_bookmaker_id
        )

        if balance_checks:
            for bc in balance_checks:
                col1, col2, col3, col4, col5 = st.columns([2, 2, 2, 3, 1])
                with col1:
                    st.write(bc['check_date_utc'][:10])
                with col2:
                    st.write(f"{bc['balance_native']} {bc['native_currency']}")
                with col3:
                    st.write(f"â‚¬{Decimal(bc['balance_eur']):,.2f}")
                with col4:
                    st.write(bc['note'] or "")
                with col5:
                    if st.button("ðŸ—‘ï¸", key=f"del_bc_{bc['id']}"):
                        service.delete_balance_check(bc['id'])
                        st.success("âœ… Balance check deleted")
                        st.rerun()
        else:
            st.info("No balance checks yet")

        # Add balance check modal
        if st.session_state.get("show_add_balance_modal", False):
            render_add_balance_check_modal(selected_associate_id, selected_bookmaker_id)
```

**Validation**:
- [ ] Can filter by associate and bookmaker
- [ ] Latest balance displays correctly
- [ ] Modeled balance calculates from ledger
- [ ] Delta shows with correct color coding
- [ ] Can add balance check
- [ ] Can delete balance check

---

## Integration Testing

### Test Scenario 1: Telegram â†’ Web Integration

1. Add associate via Telegram: `/add_associate "Test Partner" GBP`
2. Open web UI â†’ verify "Test Partner" appears in table
3. Add bookmaker via web UI: "Bet365"
4. Telegram bot can now reference: `/list_bookmakers "Test Partner"`

### Test Scenario 2: Web â†’ Telegram Integration

1. Add associate via web UI: "Web Partner", EUR
2. Telegram: `/add_bookmaker "Web Partner" "Pinnacle"`
3. Web UI â†’ verify "Pinnacle" appears under "Web Partner"

### Test Scenario 3: Delete Bookmaker

1. Create associate + bookmaker via web
2. Delete bookmaker
3. Telegram chat registration orphaned (gracefully handled by bot)

---

## Deployment Checklist

Before marking Epic 7 complete:

- [ ] All Story 7.1 tests pass
- [ ] All Story 7.2 tests pass
- [ ] All Story 7.3 tests pass
- [ ] UI loads in <2 seconds
- [ ] Forms validate correctly
- [ ] Delete confirmations work
- [ ] Telegram bot still functional
- [ ] No schema migrations required
- [ ] Code reviewed
- [ ] Documentation updated

---

## Common Issues & Solutions

### Issue: Duplicate Alias Error Not Shown

**Solution**: Wrap `create_associate()` in try/except for `sqlite3.IntegrityError`

### Issue: Balance Check FX Rate Not Fetching

**Solution**: Ensure `FXManager` service is available and API key configured

### Issue: Orphaned Chat Registrations

**Solution**: Telegram bot should handle gracefully with error message

---

## Next Steps After Epic 7

After Epic 7 is complete:
1. Test integration with Epic 1 (manual upload uses associate/bookmaker dropdowns)
2. Test integration with Epic 5 (reconciliation uses balance checks)
3. Gather user feedback on UI/UX
4. Consider optional enhancements (pagination, bulk import, etc.)

---

## Document Control

**Version**: v1.0
**Date**: 2025-11-03
**Author**: Sarah (PO Agent)

---

**End of Implementation Guide**
