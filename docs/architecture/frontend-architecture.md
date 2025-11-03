# Frontend Architecture

**Version:** v4
**Last Updated:** 2025-10-29
**Parent Document:** [Architecture Overview](../architecture.md)

---

## Overview

The frontend is a **Streamlit-based web application** running at `localhost:8501`. It provides a simple, operator-focused interface for bet ingestion, surebet management, settlement, and reconciliation.
Please note: The `use_column_width` parameter has been deprecated and will be removed in a future release. Please utilize the `use_container_width` parameter instead;
for `use_container_width=True`, use `width='stretch'`. For `use_container_width=False`, use `width='content'`.

---

## Streamlit Application Structure

```
src/ui/
├── app.py                      # Main entry point, page router
├── pages/
│   ├── 1_incoming_bets.py      # FR-1, FR-2: Ingestion & review
│   ├── 2_surebets.py           # FR-3, FR-4, FR-5: Matching & coverage
│   ├── 3_settlement.py         # FR-6, FR-7: Settlement & corrections
│   ├── 4_reconciliation.py     # FR-8: Health check, funding events
│   ├── 5_export.py             # FR-9: Ledger CSV export
│   ├── 6_statements.py         # FR-10: Monthly partner reports
│   └── 7_admin_associates.py   # FR-11: Associate & bookmaker management
├── components/
│   ├── bet_card.py             # Reusable bet display component
│   ├── surebet_table.py        # Surebet summary table
│   ├── settlement_preview.py   # Settlement calculation preview
│   ├── reconciliation_card.py  # Per-associate summary card
│   └── associate_forms.py      # Associate/bookmaker form components (FR-11)
└── utils/
    ├── formatters.py           # EUR formatting, date display
    ├── validators.py           # Input validation helpers
    └── state_management.py     # Streamlit session state helpers
```

---

## Design Principles

### 1. Single-Page-Per-Workflow
Each functional requirement maps to one Streamlit page.

**Mapping:**
- FR-1, FR-2 → `1_incoming_bets.py`
- FR-3, FR-4, FR-5 → `2_surebets.py`
- FR-6, FR-7 → `3_settlement.py`
- FR-8 → `4_reconciliation.py`
- FR-9 → `5_export.py`
- FR-10 → `6_statements.py`
- FR-11 → `7_admin_associates.py`

### 2. Stateless Widgets
- Streamlit reruns the entire script on every interaction
- Minimize session state usage (only for active selections, modals)
- Always query fresh data from database on page load

### 3. Direct Database Queries
- No ORM complexity
- Direct SQLite queries via `sqlite3` module
- Simple, transparent data access

### 4. Component Reusability
- Extract common UI patterns into `components/`
- Keep pages focused on workflow logic
- Share formatting/validation utilities

---

## Page Designs

### Page 1: Incoming Bets (FR-1, FR-2)

**URL:** `http://localhost:8501/1_incoming_bets`

**Purpose:** Manual upload + review/approval of incoming bets (Telegram and manual)

**Layout:**

```
┌───────────────────────────────────────────────────────────┐
│ 📥 Incoming Bets                                           │
├───────────────────────────────────────────────────────────┤
│                                                            │
│ ┌─ Upload Manual Bet ──────────────────────────────────┐ │
│ │ Screenshot:  [Choose File]                           │ │
│ │ Associate:   [Alice ▼]                               │ │
│ │ Bookmaker:   [Bet365 (Alice) ▼]                      │ │
│ │ Note:        [Optional...]                           │ │
│ │             [Import & OCR]                           │ │
│ └──────────────────────────────────────────────────────┘ │
│                                                            │
│ ┌─ Incoming Queue ─────────────────────────────────────┐ │
│ │ 🔍 Waiting review: 5 | ✅ Approved today: 12         │ │
│ │                                                       │ │
│ │ ┌─ Bet #1234 ─────────────────────────────────────┐ │ │
│ │ │ [Screenshot Preview]                            │ │ │
│ │ │ Alice → Bet365 (AUD)                            │ │ │
│ │ │ Event: [Manchester United vs Liverpool ▼] ✅   │ │ │
│ │ │ Market: TOTAL_GOALS_OVER_UNDER                  │ │ │
│ │ │ Period: FULL_MATCH | Line: 2.5 | Side: OVER    │ │ │
│ │ │ Stake: 100 | Odds: 1.91 | Payout: 191          │ │ │
│ │ │ [✓ Approve] [✗ Reject]                          │ │ │
│ │ └─────────────────────────────────────────────────┘ │ │
│ │                                                       │ │
│ │ ┌─ Bet #1235 ─────────────────────────────────────┐ │ │
│ │ │ ... (next bet)                                   │ │ │
│ │ └─────────────────────────────────────────────────┘ │ │
│ └───────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────┘
```

**Key Components:**

```python
# src/ui/pages/1_incoming_bets.py
import streamlit as st
from src.services.bet_ingestion import BetIngestionService
from src.services.bet_verification import BetVerificationService

def render_manual_upload_panel():
    with st.expander("📤 Upload Manual Bet", expanded=False):
        screenshot = st.file_uploader("Screenshot", type=["png", "jpg", "jpeg"])
        associate_id = st.selectbox("Associate", options=load_associates())
        bookmaker_id = st.selectbox("Bookmaker", options=load_bookmakers(associate_id))
        note = st.text_input("Note (optional)")

        if st.button("Import & OCR"):
            bet_id = BetIngestionService().ingest_manual_screenshot(
                screenshot.read(), associate_id, bookmaker_id, note
            )
            st.success(f"Bet #{bet_id} created! Processing OCR...")
            st.rerun()

def render_incoming_queue():
    st.subheader("Incoming Queue")

    # Counters
    col1, col2, col3 = st.columns(3)
    col1.metric("Waiting Review", count_incoming())
    col2.metric("Approved Today", count_approved_today())
    col3.metric("Rejected Today", count_rejected_today())

    # Bet cards
    incoming_bets = load_incoming_bets()  # status='incoming'
    for bet in incoming_bets:
        render_bet_card(bet, editable=True)

def render_bet_card(bet, editable=False):
    with st.container():
        col1, col2 = st.columns([1, 2])

        with col1:
            st.image(bet.screenshot_path, width=200)

        with col2:
            st.markdown(f"**{bet.associate_name}** → {bet.bookmaker_name} ({bet.currency})")

            if editable:
                bet.canonical_event_id = st.selectbox(
                    "Event", options=load_events(), key=f"event_{bet.id}"
                )
                # Event Creation Modal (Story 2.3)
                @st.dialog("Create New Event")
                def create_event_modal(bet):
                    """
                    Modal for manual canonical event creation.
                    Pre-fills OCR-extracted values from bet.
                    """
                    event_name = st.text_input(
                        "Event Name",
                        value=bet.extracted_event_name or "",
                        placeholder="e.g., Manchester United vs Liverpool"
                    )

                    sport = st.selectbox(
                        "Sport",
                        options=["FOOTBALL", "TENNIS", "BASKETBALL", "CRICKET", "RUGBY"],
                        index=0
                    )

                    competition = st.text_input(
                        "Competition (Optional)",
                        value=bet.extracted_competition or "",
                        placeholder="e.g., Premier League, ATP Masters"
                    )

                    kickoff_time = st.text_input(
                        "Kickoff Time (UTC)",
                        value=bet.kickoff_time_utc or "",
                        placeholder="YYYY-MM-DDTHH:MM:SSZ"
                    )

                    if st.button("Create Event", type="primary"):
                        # Validation
                        if not event_name or len(event_name) < 5:
                            st.error("Event name must be at least 5 characters")
                            return

                        if not validate_iso8601_utc(kickoff_time):
                            st.error("Invalid kickoff time format. Use YYYY-MM-DDTHH:MM:SSZ")
                            return

                        # Create event via service layer
                        verification_service = BetVerificationService(get_db_connection())
                        event_id = verification_service._create_canonical_event(
                            event_name=event_name,
                            sport=sport,
                            competition=competition or None,
                            kickoff_time_utc=kickoff_time
                        )

                        if event_id:
                            st.success(f"Event created: {event_name}")
                            st.rerun()
                        else:
                            st.error("Failed to create event. Check logs.")
                # ... other editable fields

            st.write(f"Market: {bet.market_code}")
            st.write(f"Period: {bet.period_scope} | Line: {bet.line_value} | Side: {bet.side}")
            st.write(f"Stake: {bet.stake} | Odds: {bet.odds} | Payout: {bet.payout}")

            if editable:
                col_approve, col_reject = st.columns(2)
                if col_approve.button("✓ Approve", key=f"approve_{bet.id}"):
                    BetVerificationService().approve_bet(bet.id)
                    st.rerun()
                if col_reject.button("✗ Reject", key=f"reject_{bet.id}"):
                    BetVerificationService().reject_bet(bet.id)
                    st.rerun()
```

---

### Page 2: Surebets (FR-3, FR-4, FR-5)

**URL:** `http://localhost:8501/2_surebets`

**Purpose:** View open surebets, ROI classification, send coverage proof

**Tabs:**
1. **Open & Coverage** - View open surebets, send coverage proof
2. **All Surebets** - Historical view

**Layout (Tab 1: Open & Coverage):**

```
┌───────────────────────────────────────────────────────────┐
│ 🎯 Surebets                                                │
│ [Open & Coverage] [All Surebets]                          │
├───────────────────────────────────────────────────────────┤
│ Open: 8 | Unsafe (❌): 2                                  │
│                                                            │
│ ┌─ Surebet #45 ──────────────────────────────────────────┐│
│ │ Man Utd vs Liverpool | Total Goals Over/Under 2.5      ││
│ │ Kickoff: 2025-10-30 19:00 UTC                          ││
│ │                                                         ││
│ │ Side A (OVER 2.5):                                     ││
│ │   Alice @ Bet365: 100 AUD @ 1.91                       ││
│ │   Bob @ Sportsbet: 50 AUD @ 1.95                       ││
│ │                                                         ││
│ │ Side B (UNDER 2.5):                                    ││
│ │   Charlie @ Betfair: 120 GBP @ 2.10                    ││
│ │                                                         ││
│ │ 💰 Worst-case profit: €12.50 | Staked: €250 | ROI: 5% ✅│
│ │                                                         ││
│ │ [📤 Send Coverage Proof]                                ││
│ └─────────────────────────────────────────────────────────┘│
└───────────────────────────────────────────────────────────┘
```

**Key Components:**

```python
# src/ui/pages/2_surebets.py
def render_open_surebets_tab():
    st.subheader("Open Surebets")

    col1, col2 = st.columns(2)
    col1.metric("Open Surebets", count_open_surebets())
    col2.metric("Unsafe (❌)", count_unsafe_surebets())

    open_surebets = load_open_surebets()
    for surebet in open_surebets:
        render_surebet_card(surebet, show_coverage_button=True)

def render_surebet_card(surebet, show_coverage_button=False):
    with st.container():
        st.markdown(f"### Surebet #{surebet.id}")
        st.write(f"{surebet.event_name} | {surebet.market_name}")
        st.write(f"Kickoff: {surebet.kickoff_time_utc}")

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Side A:**")
            for bet in surebet.side_a_bets:
                st.write(f"{bet.associate} @ {bet.bookmaker}: {bet.stake} {bet.currency} @ {bet.odds}")

        with col2:
            st.markdown("**Side B:**")
            for bet in surebet.side_b_bets:
                st.write(f"{bet.associate} @ {bet.bookmaker}: {bet.stake} {bet.currency} @ {bet.odds}")

        # ROI classification
        roi_data = calculate_roi(surebet.id)
        st.metric(
            f"{roi_data['label']} Worst-case profit",
            f"€{roi_data['worst_case_profit_eur']}",
            f"ROI: {roi_data['roi']}%"
        )

        if show_coverage_button:
            if st.button(f"📤 Send Coverage Proof", key=f"coverage_{surebet.id}"):
                send_coverage_proof(surebet.id)
                st.success("Coverage proof sent to all associates!")
```

---

### Page 3: Settlement (FR-6, FR-7)

**URL:** `http://localhost:8501/3_settlement`

**Purpose:** Settle surebets with WON/LOST/VOID grading

**Layout:**

```
┌───────────────────────────────────────────────────────────┐
│ ⚖️ Settlement                                              │
├───────────────────────────────────────────────────────────┤
│ Settled today: 3 | Unsettled: 8                           │
│                                                            │
│ Select Surebet (sorted by kickoff): [Surebet #45 ▼]       │
│                                                            │
│ ┌─ Surebet #45 Details ──────────────────────────────────┐│
│ │ Man Utd vs Liverpool | Total Goals Over/Under 2.5      ││
│ │                                                         ││
│ │ Side A (OVER 2.5):                                     ││
│ │   [Screenshot] Alice @ Bet365: 100 AUD @ 1.91          ││
│ │   [Screenshot] Bob @ Sportsbet: 50 AUD @ 1.95          ││
│ │                                                         ││
│ │ Side B (UNDER 2.5):                                    ││
│ │   [Screenshot] Charlie @ Betfair: 120 GBP @ 2.10       ││
│ └─────────────────────────────────────────────────────────┘│
│                                                            │
│ Outcome: (•) Side A WON / Side B LOST                     │
│          ( ) Side B WON / Side A LOST                     │
│                                                            │
│ Individual Overrides:                                      │
│   Bet #1234 (Alice): [AUTO ▼]  (WON / LOST / VOID)        │
│   Bet #1235 (Bob):   [AUTO ▼]                             │
│   Bet #1236 (Charlie): [AUTO ▼]                           │
│                                                            │
│ ┌─ Settlement Preview ────────────────────────────────────┐│
│ │ Surebet Profit (EUR): €12.50                           ││
│ │ Participants (N): 3                                    ││
│ │ Per-surebet share: €4.17                               ││
│ │                                                         ││
│ │ Alice:                                                  ││
│ │   Principal returned: €150 (100 AUD @ 1.50)            ││
│ │   Per-surebet share: €4.17                             ││
│ │   Total entitlement: €154.17                           ││
│ │ ... (Bob, Charlie)                                      ││
│ └─────────────────────────────────────────────────────────┘│
│                                                            │
│ [⚠️ SETTLE (Permanent)]                                    │
│                                                            │
│ ⚠️ Click again to confirm. This action is PERMANENT.      │
└───────────────────────────────────────────────────────────┘
```

**Key Components:**

```python
# src/ui/pages/3_settlement.py
def render_settlement_page():
    st.title("⚖️ Settlement")

    col1, col2 = st.columns(2)
    col1.metric("Settled Today", count_settled_today())
    col2.metric("Unsettled", count_unsettled())

    # Select surebet (sorted by kickoff)
    unsettled = load_unsettled_surebets_sorted_by_kickoff()
    selected_id = st.selectbox("Select Surebet", options=unsettled)

    if selected_id:
        surebet = load_surebet_with_bets(selected_id)

        # Display bets with screenshots
        st.subheader("Side A")
        for bet in surebet.side_a:
            col1, col2 = st.columns([1, 3])
            col1.image(bet.screenshot_path, width=150)
            col2.write(f"{bet.associate} @ {bet.bookmaker}: {bet.stake} {bet.currency} @ {bet.odds}")

        st.subheader("Side B")
        for bet in surebet.side_b:
            col1, col2 = st.columns([1, 3])
            col1.image(bet.screenshot_path, width=150)
            col2.write(f"{bet.associate} @ {bet.bookmaker}: {bet.stake} {bet.currency} @ {bet.odds}")

        # Outcome selection
        base_outcome = st.radio("Outcome", ["Side A WON / Side B LOST", "Side B WON / Side A LOST"])

        # Individual overrides
        st.subheader("Individual Overrides")
        overrides = {}
        for bet in surebet.all_bets:
            overrides[bet.id] = st.selectbox(
                f"Bet #{bet.id} ({bet.associate})",
                options=["AUTO", "WON", "LOST", "VOID"],
                key=f"override_{bet.id}"
            )

        # Preview
        preview = calculate_settlement_preview(surebet, base_outcome, overrides)
        render_settlement_preview(preview)

        # Confirm with modal
        if st.button("⚠️ SETTLE (Permanent)", type="primary"):
            if st.session_state.get("confirm_modal"):
                settlement_batch_id = settle_surebet(surebet, base_outcome, overrides)
                st.success(f"Settled! Batch ID: {settlement_batch_id}")
                st.session_state.confirm_modal = False
                st.rerun()
            else:
                st.session_state.confirm_modal = True
                st.warning("⚠️ Click again to confirm. This action is PERMANENT.")
```

---

### Page 4: Reconciliation (FR-8)

**URL:** `http://localhost:8501/4_reconciliation`

**Purpose:** Daily health check, pending funding events, bookmaker balance checks

**Layout:**

```
┌───────────────────────────────────────────────────────────┐
│ 🏥 Reconciliation / Health Check                          │
├───────────────────────────────────────────────────────────┤
│ ┌─ Pending Funding Events ────────────────────────────────┐│
│ │ 📥 Deposit draft: Alice deposited 500 AUD              ││
│ │    [✓ Accept] [✗ Reject]                               ││
│ │ 📤 Withdrawal draft: Bob withdrew 200 GBP              ││
│ │    [✓ Accept] [✗ Reject]                               ││
│ └─────────────────────────────────────────────────────────┘│
│                                                            │
│ ┌─ Per Associate Summary ─────────────────────────────────┐│
│ │ Alice                                                   ││
│ │   NET_DEPOSITS_EUR: €1,200                             ││
│ │   CURRENT_HOLDING_EUR: €1,800                          ││
│ │   SHOULD_HOLD_EUR: €1,000                              ││
│ │   🔴 DELTA: +€800                                       ││
│ │   ⚠️ Holding €800 more than entitlement (group float)  ││
│ │                                                         ││
│ │ Bob                                                     ││
│ │   NET_DEPOSITS_EUR: €500                               ││
│ │   CURRENT_HOLDING_EUR: €520                            ││
│ │   SHOULD_HOLD_EUR: €520                                ││
│ │   🟢 DELTA: €0                                          ││
│ │   ✅ Balanced!                                          ││
│ └─────────────────────────────────────────────────────────┘│
│                                                            │
│ ┌─ Bookmaker Drilldown (Alice) ───────────────────────────┐│
│ │ Bet365:                                                 ││
│ │   Modeled balance: 1,200 AUD (€800)                    ││
│ │   Reported balance: 1,150 AUD (€767)                   ││
│ │   Difference: -50 AUD (-€33)                           ││
│ │   [Apply Correction]                                    ││
│ └─────────────────────────────────────────────────────────┘│
└───────────────────────────────────────────────────────────┘
```

---

### Page 5: Export (FR-9)

**URL:** `http://localhost:8501/5_export`

**Purpose:** Export ledger to CSV

**Layout:**

```
┌───────────────────────────────────────────────────────────┐
│ 📦 Export                                                  │
├───────────────────────────────────────────────────────────┤
│ Export full ledger to CSV for backup and audit.           │
│                                                            │
│ [Download Ledger CSV]                                      │
│                                                            │
│ Last export: 2025-10-28 08:00 UTC                         │
│ File: data/exports/ledger_20251028_080000.csv             │
└───────────────────────────────────────────────────────────┘
```

---

### Page 6: Monthly Statements (FR-10)

**URL:** `http://localhost:8501/6_statements`

**Purpose:** Generate partner-facing summaries

**Layout:**

```
┌───────────────────────────────────────────────────────────┐
│ 📊 Monthly Statements                                      │
├───────────────────────────────────────────────────────────┤
│ Associate: [Alice ▼]                                       │
│ Cutoff Date: [2025-10-31] (end of October)                │
│                                                            │
│ [Generate Statement]                                       │
│                                                            │
│ ┌─ Statement Preview ─────────────────────────────────────┐│
│ │ Alice - October 2025                                    ││
│ │                                                         ││
│ │ You funded: €1,200 total                               ││
│ │ Right now you're entitled to: €1,000                   ││
│ │ That means you're down: -€200 overall                  ││
│ │ Our deal is 50/50, so that's -€100 each.              ││
│ └─────────────────────────────────────────────────────────┘│
│                                                            │
│ Internal-only (operator view):                             │
│   CURRENT_HOLDING_EUR: €1,800                             │
│   DELTA: +€800 (holding group float)                      │
└───────────────────────────────────────────────────────────┘
```

---

## Reusable Components

### Bet Card Component

```python
# src/ui/components/bet_card.py
def render_bet_card(bet, editable=False, show_screenshot=True):
    with st.container():
        if show_screenshot:
            col1, col2 = st.columns([1, 3])
            col1.image(bet.screenshot_path, width=200)
        else:
            col2 = st

        col2.markdown(f"**{bet.associate_name}** → {bet.bookmaker_name}")
        col2.write(f"Stake: {bet.stake} {bet.currency} @ {bet.odds}")
        # ... rest of bet details
```

### Settlement Preview Component

```python
# src/ui/components/settlement_preview.py
def render_settlement_preview(preview):
    st.subheader("Settlement Preview")

    st.metric("Surebet Profit (EUR)", f"€{preview['surebet_profit_eur']}")
    st.metric("Participants (N)", preview['n'])
    st.metric("Per-surebet share", f"€{preview['per_surebet_share_eur']}")

    for associate in preview['associates']:
        with st.expander(associate['name']):
            st.write(f"Principal returned: €{associate['principal_returned_eur']}")
            st.write(f"Per-surebet share: €{associate['per_surebet_share_eur']}")
            st.write(f"Total entitlement: €{associate['entitlement_eur']}")
```

---

## State Management Strategy

### Minimize Session State

**Only use `st.session_state` for:**
1. Active surebet selection (carry between tabs)
2. Inline edit buffers (temporary field edits)
3. Confirmation modals (two-click confirm)

**Example:**
```python
# Confirmation modal pattern
if st.button("⚠️ SETTLE"):
    if st.session_state.get("confirm_modal"):
        # Actually settle
        settle_surebet(...)
        st.session_state.confirm_modal = False
    else:
        # First click: show warning
        st.session_state.confirm_modal = True
        st.warning("Click again to confirm")
```

### Prefer Database as Truth

Always query fresh data on page load:
```python
def render_page():
    # BAD: Caching in session state
    # if "bets" not in st.session_state:
    #     st.session_state.bets = load_bets()

    # GOOD: Always query fresh
    bets = load_incoming_bets()
    for bet in bets:
        render_bet_card(bet)
```

---

## Utilities

### Formatters

```python
# src/ui/utils/formatters.py
def format_eur(amount):
    return f"€{amount:,.2f}"

def format_currency(amount, currency):
    return f"{amount:,.2f} {currency}"

def format_utc_datetime(iso_string):
    dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
    return dt.strftime("%Y-%m-%d %H:%M UTC")
```

### Validators

```python
# src/ui/utils/validators.py
def validate_decimal_input(value):
    try:
        Decimal(value)
        return True
    except:
        return False

def validate_positive_amount(value):
    return Decimal(value) > 0
```

---

## Performance Considerations

### Streamlit Rerun Behavior

- Streamlit reruns entire script on every interaction
- Keep database queries simple (SQLite is fast for MVP scale)
- No need for caching (hundreds of records, not thousands)

### Deprecation Warning

- The `use_column_width` parameter has been deprecated and will be removed in a future release. Please utilize the `use_container_width` parameter instead
- for `use_container_width=True`, use `width='stretch'`. For `use_container_width=False`, use `width='content'`.
### Image Display

- Screenshots displayed at fixed width (200px thumbnails)
- Full-size preview on click (future enhancement)

---

**End of Document**
