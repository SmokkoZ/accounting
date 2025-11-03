# Epic 7: System Administration (Associate & Bookmaker Management)

**Status:** Not Started
**Priority:** P1 (Post-MVP Enhancement)
**Estimated Duration:** 3-4 days
**Owner:** Tech Lead
**Phase:** 2 (Administration Features)
**PRD Reference:** FR-11 (System Administration)

---

## Epic Goal

Build a web-based administrative interface for managing associates, bookmakers, and balance checks. This epic provides a comfortable, user-friendly UI alternative to Telegram bot commands for system administration tasks.

---

## Business Value

### Operator Benefits
- **Improved UX**: Comfortable web interface vs. Telegram command-line style
- **Visual Feedback**: See all associates/bookmakers in organized tables with search/filter
- **Error Prevention**: Form validation prevents typos and duplicate entries
- **Faster Operations**: No need to remember Telegram command syntax
- **Balance Tracking**: Easy-to-use interface for recording bookmaker balances

### System Benefits
- **Dual-Channel Access**: Both web UI and Telegram bot write to same database
- **Redundancy**: If Telegram is unavailable, admin can still manage system
- **Data Integrity**: Web UI enforces same validation as Telegram bot
- **No Migration Needed**: Uses existing database tables (no schema changes)

**Success Metric**: Admin completes associate/bookmaker setup 3x faster via web UI vs. Telegram commands.

---

## Epic Description

### Context

Currently, the only way to manage associates and bookmakers is via Telegram bot admin commands:
- `/add_associate <alias> [currency]` - Create new associate
- `/add_bookmaker <associate_alias> <bookmaker_name>` - Add bookmaker to associate
- `/list_associates` - View all associates
- `/list_bookmakers [associate_alias]` - View bookmakers

This works but is:
- **Uncomfortable**: Command-line style interface
- **Error-prone**: Easy to mistype aliases or currencies
- **Limited**: No easy way to view/edit multiple records at once
- **No balance management**: Can't add/edit bookmaker balances via Telegram

### What's Being Built

A new Streamlit page (`7_admin_associates.py`) with three main sections:

1. **Associate Management** (Story 7.1)
   - View all associates in table format
   - Add new associate (form with validation)
   - Edit existing associate (inline or modal)
   - Delete associate (with validation: prevent if has bets)
   - Search/filter by alias or currency

2. **Bookmaker Management** (Story 7.2)
   - View bookmakers per associate (nested/expandable view)
   - Add bookmaker to associate
   - Edit bookmaker (name, parsing profile, active status)
   - Delete bookmaker (with warning if has bets)
   - Display Telegram chat registration status

3. **Balance Management** (Story 7.3)
   - View balance check history per bookmaker
   - Add new balance check (date, amount, currency)
   - Edit existing balance check
   - Delete balance check
   - Display latest balance vs. modeled balance

### Integration Points

**Upstream Dependencies:**
- Epic 0 (Foundation): Database schema (`associates`, `bookmakers`, `bookmaker_balance_checks` tables already exist)
- Existing Telegram bot: Continues to work alongside web UI

**Downstream Consumers:**
- Epic 1 (Bet Ingestion): Manual upload panel uses associate/bookmaker dropdowns
- Epic 2 (Bet Review): Bet editing uses associate/bookmaker selectors
- Epic 3 (Surebet Matching): Filtering by associate
- Epic 5 (Reconciliation): Per-associate balance calculations

### Key Design Decisions

1. **No Authentication**: App is single-user admin only (no login required)
2. **Shared Database**: Both web UI and Telegram write to same tables (no sync needed)
3. **Hard Deletes Allowed**: Bookmakers/associates can be deleted (with validation)
4. **No Bulk Operations**: One-at-a-time CRUD is sufficient
5. **No Audit Trail**: Simple timestamps only (no change log)
6. **Telegram Preserved**: Existing bot commands continue to work

---

## Stories

### Story 7.1: Associate Management UI

**As the operator**, I want a web interface to view, add, edit, and delete associates so I don't have to use Telegram commands for system administration.

**Acceptance Criteria:**

**View Associates**
- [ ] Display table of all associates with columns:
  - Display Alias (clickable to expand)
  - Home Currency (ISO code)
  - Admin Flag (✓ or blank)
  - Bookmaker Count (e.g., "2")
  - Created Date (formatted as "2025-11-02")
  - Actions: [Edit] [Delete] buttons
- [ ] Implement search/filter by alias (case-insensitive)
- [ ] Sort by alias (alphabetically) by default
- [ ] Display counter: "Total Associates: X"

**Add Associate**
- [ ] "Add Associate" button opens modal/form with fields:
  - **Display Alias**: Text input (required, unique validation)
  - **Home Currency**: Dropdown (EUR, GBP, USD, AUD, etc.)
  - **Is Admin**: Checkbox (default: unchecked)
  - **Multibook Chat ID**: Text input (optional, Telegram chat for coverage proof)
- [ ] Validation:
  - Alias must be unique (check against existing)
  - Alias must not be empty
  - Currency must be valid ISO code
- [ ] On save:
  - `INSERT INTO associates (display_alias, home_currency, is_admin, multibook_chat_id, created_at_utc, updated_at_utc) VALUES (?, ?, ?, ?, datetime('now') || 'Z', datetime('now') || 'Z')`
  - Display success message: "✅ Associate '<alias>' created"
  - Refresh table to show new associate
- [ ] On validation error:
  - Display error message: "❌ Alias already exists" or "❌ Invalid currency"

**Edit Associate**
- [ ] "Edit" button opens form pre-populated with current values
- [ ] Allow editing:
  - Display Alias (with unique validation)
  - Home Currency
  - Is Admin flag
  - Multibook Chat ID
- [ ] On save:
  - `UPDATE associates SET display_alias = ?, home_currency = ?, is_admin = ?, multibook_chat_id = ?, updated_at_utc = datetime('now') || 'Z' WHERE id = ?`
  - Display success message: "✅ Associate updated"
- [ ] Validate alias uniqueness (excluding current record)

**Delete Associate**
- [ ] "Delete" button shows warning modal:
  - "⚠️ Are you sure you want to delete '<alias>'?"
- [ ] Pre-delete validation:
  - Check if associate has any bets: `SELECT COUNT(*) FROM bets WHERE associate_id = ?`
  - Check if associate has any ledger entries: `SELECT COUNT(*) FROM ledger_entries WHERE associate_id = ?`
  - If count > 0: Display error "❌ Cannot delete associate with existing bets/ledger entries"
- [ ] If validation passes:
  - `DELETE FROM associates WHERE id = ?`
  - Cascade deletes bookmakers (ON DELETE CASCADE in schema)
  - Display success message: "✅ Associate '<alias>' deleted"

**Technical Notes:**
- Use `st.data_editor()` or custom table component
- Leverage Streamlit session state for modal management
- Query fresh data on every page load (no caching)

---

### Story 7.2: Bookmaker Management UI

**As the operator**, I want to manage bookmakers per associate via web interface so I can easily add, edit, and delete bookmaker accounts.

**Acceptance Criteria:**

**View Bookmakers**
- [ ] Associate table rows are expandable (▶/▼ toggle)
- [ ] When expanded, show nested bookmaker table:
  - Bookmaker Name
  - Active Status (✅ Active / ⚠️ Inactive)
  - Parsing Profile (truncated if long)
  - Telegram Chat Status ("Registered" or "Not Registered")
  - Latest Balance (from `bookmaker_balance_checks`)
  - Actions: [Edit] [Delete] buttons
- [ ] Display counter: "Bookmakers: X" per associate

**Add Bookmaker**
- [ ] "Add Bookmaker" button per associate opens form:
  - **Bookmaker Name**: Text input (required)
  - **Parsing Profile**: Textarea (optional JSON for OCR hints)
  - **Is Active**: Checkbox (default: checked)
- [ ] Validation:
  - Bookmaker name must not be empty
  - Unique constraint: (associate_id, bookmaker_name) must be unique
  - If parsing_profile provided, validate JSON format (optional)
- [ ] On save:
  - `INSERT INTO bookmakers (associate_id, bookmaker_name, parsing_profile, is_active, created_at_utc, updated_at_utc) VALUES (?, ?, ?, ?, datetime('now') || 'Z', datetime('now') || 'Z')`
  - Display success message: "✅ Bookmaker '<name>' added to '<associate_alias>'"
  - Refresh bookmaker list

**Edit Bookmaker**
- [ ] "Edit" button opens form pre-populated with:
  - Bookmaker Name (editable)
  - Parsing Profile (editable)
  - Is Active (checkbox)
- [ ] On save:
  - `UPDATE bookmakers SET bookmaker_name = ?, parsing_profile = ?, is_active = ?, updated_at_utc = datetime('now') || 'Z' WHERE id = ?`
  - Validate unique constraint on (associate_id, bookmaker_name)
  - Display success message: "✅ Bookmaker updated"

**Delete Bookmaker**
- [ ] "Delete" button shows warning modal:
  - "⚠️ Are you sure you want to delete '<bookmaker_name>'?"
- [ ] Pre-delete validation:
  - Check if bookmaker has any bets: `SELECT COUNT(*) FROM bets WHERE bookmaker_id = ?`
  - If count > 0: Show warning "⚠️ This bookmaker has X bets. Deleting will orphan these records. Continue?"
  - Require explicit confirmation if bets exist
- [ ] On confirm:
  - `DELETE FROM bookmakers WHERE id = ?`
  - Cascade deletes chat registrations (if any)
  - Display success message: "✅ Bookmaker '<name>' deleted"
- [ ] If bets exist but user cancels: No action

**Telegram Chat Registration Display**
- [ ] Query `chat_registrations` table:
  - `SELECT chat_id, is_active FROM chat_registrations WHERE bookmaker_id = ?`
- [ ] Display status:
  - "✅ Registered (Chat ID: 123456)" if active registration exists
  - "⚠️ Not Registered" if no active registration
  - "🔴 Inactive Registration" if `is_active = FALSE`
- [ ] Optional: Link to Telegram chat (if multibook_chat_id available)

**Technical Notes:**
- Use nested `st.expander()` components for expandable rows
- Validate unique (associate_id, bookmaker_name) constraint
- Handle orphaned chat registrations gracefully

---

### Story 7.3: Balance Management UI

**As the operator**, I want to record and view bookmaker balance checks via web interface so I can track balance history and reconcile accounts.

**Acceptance Criteria:**

**View Balance History**
- [ ] New tab/section: "Balance History"
- [ ] Filters:
  - **Associate**: Dropdown (all associates)
  - **Bookmaker**: Dropdown (filtered by selected associate)
  - **Date Range**: Date picker (optional, default: last 30 days)
- [ ] Display table:
  - Check Date (formatted: "2025-11-02 14:30 UTC")
  - Native Amount (e.g., "€1,250.00")
  - Native Currency (e.g., "EUR")
  - EUR Equivalent (e.g., "€1,250.00")
  - FX Rate Used (e.g., "1.000000")
  - Note (free text)
  - Actions: [Edit] [Delete] buttons
- [ ] Sort by check_date_utc DESC (newest first)
- [ ] Display summary:
  - **Latest Balance**: Most recent check (highlighted)
  - **Modeled Balance**: Calculate from ledger entries (same logic as Reconciliation page)
  - **Difference**: Latest - Modeled (color-coded: green if match, red if mismatch)

**Add Balance Check**
- [ ] "Add Balance Check" button opens form:
  - **Associate**: Dropdown (required)
  - **Bookmaker**: Dropdown (filtered by associate, required)
  - **Check Date**: Date/time picker (default: now)
  - **Balance Amount**: Decimal input (required)
  - **Currency**: Auto-filled from associate's home_currency (editable)
  - **Note**: Text input (optional, e.g., "Daily check", "After settlement")
- [ ] On save:
  - Fetch current FX rate for currency → EUR (use FXManager service)
  - Calculate `balance_eur = balance_native * fx_rate`
  - `INSERT INTO bookmaker_balance_checks (associate_id, bookmaker_id, balance_native, native_currency, balance_eur, fx_rate_used, check_date_utc, created_at_utc, note) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now') || 'Z', ?)`
  - Display success message: "✅ Balance check recorded"
  - Refresh table

**Edit Balance Check**
- [ ] "Edit" button opens form pre-populated with:
  - Balance Amount (editable)
  - Check Date (editable)
  - Note (editable)
  - Currency (editable)
- [ ] On save:
  - Re-fetch FX rate for updated date/currency
  - Recalculate `balance_eur`
  - `UPDATE bookmaker_balance_checks SET balance_native = ?, native_currency = ?, balance_eur = ?, fx_rate_used = ?, check_date_utc = ?, note = ? WHERE id = ?`
  - Display success message: "✅ Balance check updated"

**Delete Balance Check**
- [ ] "Delete" button shows confirmation:
  - "⚠️ Delete this balance check?"
- [ ] On confirm:
  - `DELETE FROM bookmaker_balance_checks WHERE id = ?`
  - Display success message: "✅ Balance check deleted"

**Modeled Balance Calculation**
- [ ] Query ledger entries for selected associate + bookmaker:
  ```sql
  SELECT SUM(amount_eur) AS modeled_balance_eur
  FROM ledger_entries
  WHERE associate_id = ? AND bookmaker_id = ?
  ```
- [ ] Convert to native currency using latest FX rate
- [ ] Display alongside latest balance check
- [ ] Calculate difference:
  - `delta = latest_balance_eur - modeled_balance_eur`
  - If `abs(delta) < 1.0`: Green "✅ Balanced"
  - If `delta > 1.0`: Red "❌ Overholding €X"
  - If `delta < -1.0`: Orange "⚠️ Short €X"

**Technical Notes:**
- Reuse `FXManager` service for rate fetching
- Store FX rate snapshot (never recalculate past checks)
- Display currency symbols correctly (€, £, $, etc.)

---

## Database Schema (No Changes Required)

Epic 7 uses **existing tables only**. No migrations needed.

### Existing Tables Used

**`associates` Table** (Story 7.1)
```sql
CREATE TABLE IF NOT EXISTS associates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    display_alias TEXT NOT NULL UNIQUE,
    home_currency TEXT NOT NULL DEFAULT 'EUR',
    multibook_chat_id TEXT,
    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
    created_at_utc TEXT NOT NULL DEFAULT (datetime('now') || 'Z'),
    updated_at_utc TEXT NOT NULL DEFAULT (datetime('now') || 'Z')
);
```

**`bookmakers` Table** (Story 7.2)
```sql
CREATE TABLE IF NOT EXISTS bookmakers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    associate_id INTEGER NOT NULL,
    bookmaker_name TEXT NOT NULL,
    parsing_profile TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at_utc TEXT NOT NULL DEFAULT (datetime('now') || 'Z'),
    updated_at_utc TEXT NOT NULL DEFAULT (datetime('now') || 'Z'),
    FOREIGN KEY (associate_id) REFERENCES associates(id) ON DELETE CASCADE,
    UNIQUE(associate_id, bookmaker_name)
);
```

**`bookmaker_balance_checks` Table** (Story 7.3)
```sql
CREATE TABLE IF NOT EXISTS bookmaker_balance_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    associate_id INTEGER NOT NULL,
    bookmaker_id INTEGER NOT NULL,
    balance_native DECIMAL(15,2) NOT NULL,
    native_currency TEXT NOT NULL,
    balance_eur DECIMAL(15,2) NOT NULL,
    fx_rate_used DECIMAL(10,6) NOT NULL,
    check_date_utc TEXT NOT NULL,
    created_at_utc TEXT NOT NULL DEFAULT (datetime('now') || 'Z'),
    note TEXT,
    FOREIGN KEY (associate_id) REFERENCES associates(id),
    FOREIGN KEY (bookmaker_id) REFERENCES bookmakers(id)
);
```

**`chat_registrations` Table** (Story 7.2 - read-only)
```sql
CREATE TABLE IF NOT EXISTS chat_registrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL UNIQUE,
    associate_id INTEGER NOT NULL,
    bookmaker_id INTEGER NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at_utc TEXT NOT NULL DEFAULT (datetime('now') || 'Z'),
    updated_at_utc TEXT NOT NULL DEFAULT (datetime('now') || 'Z'),
    FOREIGN KEY (associate_id) REFERENCES associates(id),
    FOREIGN KEY (bookmaker_id) REFERENCES bookmakers(id)
);
```

---

## Integration with Telegram Bot

### Coexistence Strategy

**Epic 7 web UI and Telegram bot are equal citizens** writing to the same database. No synchronization logic needed.

### Telegram Bot Commands (Unchanged)

These commands continue to work exactly as before:

```
/add_associate <alias> [currency]
  → INSERT INTO associates ...

/add_bookmaker <associate_alias> <bookmaker_name>
  → INSERT INTO bookmakers ...

/list_associates
  → SELECT * FROM associates ...

/list_bookmakers [associate_alias]
  → SELECT * FROM bookmakers WHERE associate_id = ...
```

### Interaction Scenarios

**Scenario 1: Add via Telegram, view via Web**
```
Admin: /add_associate "Partner D" CAD
Bot: ✅ Associate "Partner D" created (ID: 4)

Admin opens web UI → sees "Partner D" in table
```

**Scenario 2: Add via Web, use in Telegram**
```
Admin clicks [+ Add Associate] on web
Fills: Alias="Partner E", Currency="JPY"
Saves → INSERT INTO associates ...

Admin: /add_bookmaker "Partner E" "William Hill"
Bot: ✅ Bookmaker added
```

**Scenario 3: Delete bookmaker via Web**
```
Admin deletes "Bet365" bookmaker via web UI
→ DELETE FROM bookmakers WHERE id = 5

Telegram chat registration orphaned:
SELECT * FROM chat_registrations WHERE bookmaker_id = 5
→ Returns row with chat_id = "123456"

Next photo sent to that chat:
Bot: ❌ Invalid registration (bookmaker not found)
```

### Edge Case Handling

**Orphaned Chat Registrations**
- When bookmaker deleted via web UI, chat_registrations may become orphaned
- Telegram bot photo handler should gracefully handle missing bookmaker:
  ```python
  bookmaker = db.execute("SELECT * FROM bookmakers WHERE id = ?", (bookmaker_id,)).fetchone()
  if not bookmaker:
      return "❌ This chat's bookmaker was deleted. Please /register again."
  ```

**Concurrent Modifications**
- Both systems use same database file (WAL mode allows concurrent reads)
- Writes are serialized by SQLite (no special handling needed)
- Web UI queries fresh data on every page load (no caching conflicts)

---

## UI Layout Reference

### Page Structure: `7_admin_associates.py`

```
┌─────────────────────────────────────────────────────┐
│ 🧑‍💼 Associate & Bookmaker Management                 │
├─────────────────────────────────────────────────────┤
│ Tab 1: Associates & Bookmakers                      │
│ ┌─────────────────────────────────────────────────┐│
│ │ [+ Add Associate]      🔍 Search: [_______]    ││
│ │                                                 ││
│ │ Total Associates: 3                             ││
│ │                                                 ││
│ │ ┌───────────────────────────────────────────┐  ││
│ │ │ Alias    │ Currency │ Admin │ Bookmakers │  ││
│ │ ├───────────────────────────────────────────┤  ││
│ │ │ ▼ Admin    │ EUR │ ✓ │ 2 │ [Edit][Delete]│  ││
│ │ │   ├─ Bet365   (✅ Active)                 │  ││
│ │ │   │   Chat: ✅ Registered (123456)        │  ││
│ │ │   │   Balance: €1,250 (2025-11-02)        │  ││
│ │ │   │   [Edit] [Delete] [+ Balance Check]   │  ││
│ │ │   └─ Pinnacle (✅ Active)                 │  ││
│ │ │       Chat: ⚠️ Not Registered              │  ││
│ │ │       Balance: €3,400 (2025-11-02)        │  ││
│ │ │       [Edit] [Delete] [+ Balance Check]   │  ││
│ │ ├───────────────────────────────────────────┤  ││
│ │ │ ▶ Partner A │ EUR │  │ 2 │ [Edit][Delete]│  ││
│ │ ├───────────────────────────────────────────┤  ││
│ │ │ ▶ Partner B │ GBP │  │ 1 │ [Edit][Delete]│  ││
│ │ └───────────────────────────────────────────┘  ││
│ └─────────────────────────────────────────────────┘│
│                                                     │
│ Tab 2: Balance History                              │
│ ┌─────────────────────────────────────────────────┐│
│ │ Associate: [Admin ▼]   Bookmaker: [Bet365 ▼]   ││
│ │ Date Range: [Last 30 days ▼]                   ││
│ │                                                 ││
│ │ Current Status:                                 ││
│ │ ┌─────────────────────────────────────────────┐││
│ │ │ Latest Balance:   €1,250.00 (2025-11-02)   │││
│ │ │ Modeled Balance:  €1,248.50                 │││
│ │ │ Difference:       +€1.50 ✅ Balanced        │││
│ │ └─────────────────────────────────────────────┘││
│ │                                                 ││
│ │ [+ Add Balance Check]                           ││
│ │                                                 ││
│ │ Balance Check History:                          ││
│ │ ┌─────────────────────────────────────────────┐││
│ │ │ Date       │ Native │ EUR    │ Note  │ ...  │││
│ │ ├─────────────────────────────────────────────┤││
│ │ │ 2025-11-02 │ €1,250 │ €1,250 │ Daily │[E][D]│││
│ │ │ 2025-11-01 │ €1,100 │ €1,100 │ ...   │[E][D]│││
│ │ │ 2025-10-31 │ €950   │ €950   │ ...   │[E][D]│││
│ │ └─────────────────────────────────────────────┘││
│ └─────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────┘
```

### Modal: Add Associate

```
┌─────────────────────────────────┐
│ Add New Associate               │
├─────────────────────────────────┤
│ Display Alias: *                │
│ [___________________________]   │
│                                 │
│ Home Currency: *                │
│ [EUR ▼]                         │
│                                 │
│ Is Admin: [ ] Yes               │
│                                 │
│ Multibook Chat ID: (optional)   │
│ [___________________________]   │
│                                 │
│        [Cancel]  [Save]         │
└─────────────────────────────────┘
```

### Modal: Add Bookmaker

```
┌─────────────────────────────────┐
│ Add Bookmaker to "Admin"        │
├─────────────────────────────────┤
│ Bookmaker Name: *               │
│ [___________________________]   │
│                                 │
│ Parsing Profile: (optional)     │
│ [___________________________]   │
│ (JSON format for OCR hints)     │
│                                 │
│ Is Active: [✓] Yes              │
│                                 │
│        [Cancel]  [Save]         │
└─────────────────────────────────┘
```

### Modal: Add Balance Check

```
┌─────────────────────────────────┐
│ Add Balance Check               │
├─────────────────────────────────┤
│ Associate: Admin                │
│ Bookmaker: Bet365               │
│                                 │
│ Check Date: *                   │
│ [2025-11-02 14:30 UTC ▼]       │
│                                 │
│ Balance Amount (EUR): *         │
│ [1250.00________________]       │
│                                 │
│ Currency:                       │
│ [EUR ▼]                         │
│                                 │
│ Note:                           │
│ [Daily check____________]       │
│                                 │
│        [Cancel]  [Save]         │
└─────────────────────────────────┘
```

---

## Validation Rules

### Associate Validation

| Field | Rule | Error Message |
|-------|------|---------------|
| Display Alias | Not empty | "❌ Alias is required" |
| Display Alias | Unique | "❌ Alias already exists" |
| Display Alias | Max 50 chars | "❌ Alias too long (max 50)" |
| Home Currency | Valid ISO code | "❌ Invalid currency code" |

### Bookmaker Validation

| Field | Rule | Error Message |
|-------|------|---------------|
| Bookmaker Name | Not empty | "❌ Name is required" |
| Bookmaker Name | Unique per associate | "❌ Bookmaker already exists for this associate" |
| Parsing Profile | Valid JSON (if provided) | "❌ Invalid JSON format" |

### Balance Check Validation

| Field | Rule | Error Message |
|-------|------|---------------|
| Balance Amount | Positive number | "❌ Balance must be positive" |
| Balance Amount | Max 2 decimal places | "❌ Max 2 decimal places" |
| Check Date | Not future date | "⚠️ Future date (confirm?)" |

---

## Delete Validation Logic

### Can Delete Associate?

```python
def can_delete_associate(db: sqlite3.Connection, associate_id: int) -> tuple[bool, str]:
    """
    Check if associate can be safely deleted.

    Returns:
        (can_delete: bool, reason: str)
    """
    cursor = db.cursor()

    # Check bets
    bet_count = cursor.execute(
        "SELECT COUNT(*) FROM bets WHERE associate_id = ?",
        (associate_id,)
    ).fetchone()[0]

    # Check ledger entries
    ledger_count = cursor.execute(
        "SELECT COUNT(*) FROM ledger_entries WHERE associate_id = ?",
        (associate_id,)
    ).fetchone()[0]

    if bet_count > 0 or ledger_count > 0:
        return False, f"Associate has {bet_count} bets and {ledger_count} ledger entries"

    return True, "OK"
```

### Can Delete Bookmaker?

```python
def can_delete_bookmaker(db: sqlite3.Connection, bookmaker_id: int) -> tuple[bool, str, int]:
    """
    Check if bookmaker can be deleted.

    Returns:
        (can_delete: bool, warning: str, bet_count: int)
    """
    cursor = db.cursor()

    bet_count = cursor.execute(
        "SELECT COUNT(*) FROM bets WHERE bookmaker_id = ?",
        (bookmaker_id,)
    ).fetchone()[0]

    if bet_count > 0:
        return True, f"⚠️ This bookmaker has {bet_count} bets. Deleting will orphan these records.", bet_count

    return True, "OK", 0
```

---

## Success Criteria (Epic-Level)

Epic 7 is complete when ALL of the following work:

**Story 7.1: Associate Management**
- [ ] View all associates in sortable table
- [ ] Search/filter associates by alias
- [ ] Add new associate with validation
- [ ] Edit existing associate
- [ ] Delete associate (with validation preventing deletion if bets exist)

**Story 7.2: Bookmaker Management**
- [ ] View bookmakers per associate (nested/expandable)
- [ ] Add bookmaker with unique constraint validation
- [ ] Edit bookmaker (name, profile, active status)
- [ ] Delete bookmaker (with warning if bets exist)
- [ ] Display Telegram chat registration status

**Story 7.3: Balance Management**
- [ ] View balance check history per bookmaker
- [ ] Add new balance check with FX conversion
- [ ] Edit balance check with FX recalculation
- [ ] Delete balance check
- [ ] Display modeled vs. latest balance with delta

**Integration**
- [ ] Telegram bot commands continue to work
- [ ] Web UI and Telegram bot write to same tables
- [ ] No data conflicts or synchronization issues
- [ ] Page loads in <2 seconds with 100+ associates

**UX**
- [ ] Forms validate input before submission
- [ ] Success/error messages display clearly
- [ ] Tables are sortable and searchable
- [ ] Mobile-responsive (basic Streamlit responsiveness)

---

## Non-Functional Requirements

### Performance
- Page load: <2 seconds (even with 100+ associates)
- Associate search: <500ms
- Form submission: <1 second

### Usability
- Forms use clear labels and placeholders
- Validation errors display inline (red text below field)
- Success messages auto-dismiss after 3 seconds
- Delete confirmations require explicit click

### Compatibility
- Works in Chrome, Firefox, Safari (latest versions)
- Streamlit default mobile responsiveness

---

## Out of Scope (Not in Epic 7)

The following are explicitly **NOT included** in Epic 7:

- ❌ Authentication/login system (app is single-user admin only)
- ❌ Role-based access control (no partners, only admin)
- ❌ Audit trail/change log (beyond created_at/updated_at timestamps)
- ❌ Bulk operations (CSV import/export of associates/bookmakers)
- ❌ Complex synchronization logic (both systems share DB)
- ❌ Database schema changes (uses existing tables)
- ❌ Telegram bot modifications (bot continues unchanged)
- ❌ Bookmaker balance auto-sync (manual entry only)
- ❌ Advanced search (full-text, regex)
- ❌ Data visualization (charts, graphs)

---

## Testing Checklist

### Story 7.1: Associate Management

**Add Associate**
- [ ] Can add associate with valid alias, currency
- [ ] Cannot add duplicate alias
- [ ] Cannot add empty alias
- [ ] Admin flag persists correctly
- [ ] Multibook chat ID is optional

**Edit Associate**
- [ ] Can edit alias (if unique)
- [ ] Can change currency
- [ ] Can toggle admin flag
- [ ] Cannot change alias to existing alias
- [ ] Updated timestamp changes

**Delete Associate**
- [ ] Can delete associate with no bets/ledger entries
- [ ] Cannot delete associate with bets
- [ ] Cannot delete associate with ledger entries
- [ ] Cascades to bookmakers (ON DELETE CASCADE)

**View Associates**
- [ ] All associates display correctly
- [ ] Search filters work
- [ ] Sort by alias works
- [ ] Counter shows correct count

### Story 7.2: Bookmaker Management

**Add Bookmaker**
- [ ] Can add bookmaker to associate
- [ ] Cannot add duplicate (associate_id, bookmaker_name)
- [ ] Parsing profile JSON validates
- [ ] Active status defaults to TRUE

**Edit Bookmaker**
- [ ] Can edit name (if unique per associate)
- [ ] Can toggle active status
- [ ] Can update parsing profile

**Delete Bookmaker**
- [ ] Can delete bookmaker with no bets
- [ ] Shows warning if bets exist
- [ ] Deletes successfully after confirmation

**Telegram Chat Status**
- [ ] Displays "Registered" if chat_registrations row exists
- [ ] Displays "Not Registered" if no row
- [ ] Displays correct chat_id

### Story 7.3: Balance Management

**Add Balance Check**
- [ ] Can add balance check with FX conversion
- [ ] FX rate fetched from FXManager
- [ ] Balance EUR calculated correctly
- [ ] Note is optional

**Edit Balance Check**
- [ ] Can edit balance amount
- [ ] FX recalculated on currency/date change
- [ ] Balance EUR updates correctly

**Delete Balance Check**
- [ ] Can delete balance check
- [ ] No orphaned records

**Modeled Balance**
- [ ] Calculates correctly from ledger_entries
- [ ] Delta displays with correct color coding
- [ ] EUR conversion uses latest FX rate

### Integration Testing

**Telegram → Web**
- [ ] Associate added via Telegram appears in web UI
- [ ] Bookmaker added via Telegram appears in web UI

**Web → Telegram**
- [ ] Associate added via web can be used in Telegram commands
- [ ] Bookmaker added via web can be referenced in Telegram

**Concurrent Modifications**
- [ ] No data corruption when both systems used simultaneously
- [ ] Latest write wins (standard SQLite behavior)

---

## Risks & Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Orphaned chat registrations after bookmaker delete | Medium | Low | Display warning in UI, bot handles gracefully |
| Unique constraint violations | Low | Low | Pre-validate in UI before INSERT |
| FX API unavailable during balance check | Low | Medium | Reuse last known rate, show warning |
| User deletes wrong associate/bookmaker | Medium | Medium | Require confirmation, show warning if bets exist |
| Large table performance (1000+ associates) | Low | Low | Implement pagination if needed (post-MVP) |

---

## Dependencies

### Upstream Dependencies
- Epic 0: Database schema created
- Existing Telegram bot implementation

### Downstream Consumers
- Epic 1: Manual upload uses associate/bookmaker dropdowns
- Epic 2: Bet review uses associate/bookmaker selectors
- Epic 5: Reconciliation uses balance checks

---

## Acceptance Checklist

Before marking Epic 7 as complete:

- [ ] All Story 7.1 acceptance criteria met
- [ ] All Story 7.2 acceptance criteria met
- [ ] All Story 7.3 acceptance criteria met
- [ ] Telegram bot commands still work
- [ ] No schema migrations required
- [ ] Page loads in <2 seconds
- [ ] Forms validate correctly
- [ ] Delete confirmations work
- [ ] Balance checks calculate FX correctly
- [ ] Code reviewed and tested
- [ ] Documentation updated (if needed)

---

## Document Control

**Version History**:

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| v1.0 | 2025-11-03 | Sarah (PO Agent) | Initial Epic 7 specification |

---

**End of Document**
