# Frontend Architecture

**Version:** v5  
**Last Updated:** 2025-11-04  
**Parent Document:** [Architecture Overview](../architecture.md)

---

## Changelog (from v4 → v5)
- **Navigation:** Adopt Streamlit’s declarative navigation (`st.navigation`, `st.Page`) and page links.  
- **Rerun control:** Use `@st.fragment` for partial reruns; switch confirm flows to `@st.dialog`.  
- **Inline actions:** Introduce `st.popover` for compact per-row actions.  
- **Tables/CRUD:** Standardize on `st.data_editor` with `column_config`, selection return data, and controlled edit modes.  
- **Streaming:** Use `st.write_stream` for log-like progress and LLM output.  
- **PDF slips:** Use `st.pdf` for in-app bet slip/statement preview.  
- **Deprecations:** Replace all `use_column_width=` with `use_container_width=True` (and `width='stretch'` semantics).  
- **Version-gating:** Add feature flags and fallbacks so the app runs on older Streamlit if needed.

> This document **keeps all v4 content** and augments it with recommended patterns and examples using recent Streamlit features. It’s written so agents can refactor incrementally.

---

## Overview
The frontend is a **Streamlit-based web application** running at `localhost:8501`. It provides a simple, operator‑focused interface for bet ingestion, surebet management, settlement, and reconciliation.

**Deprecation note**: `use_column_width` is deprecated. Use `use_container_width=True`.  
When you need layout hints, prefer `width='stretch'` for full-width containers and `width='content'` for compact elements (where supported by the specific API).

---

## Streamlit Version Targets & Feature Flags
Recommended baseline: **Streamlit ≥ 1.46**. The app includes fallbacks for ≥ **1.30**.

```python
# src/ui/utils/feature_flags.py
import streamlit as st

FEATURES = {{
    "fragment": hasattr(st, "fragment"),
    "dialog": hasattr(st, "dialog"),
    "popover": hasattr(st, "popover"),
    "navigation": hasattr(st, "navigation"),
    "page_link": hasattr(st, "page_link"),
    "write_stream": hasattr(st, "write_stream"),
    "pdf": hasattr(st, "pdf"),
}}

def has(name: str) -> bool:
    return bool(FEATURES.get(name, False))
```

**Usage**:
```python
from src.ui.utils.feature_flags import has
if has("dialog"):
    @st.dialog("Confirm action")
    def confirm_modal(...):
        ...
else:
    # Fallback: two-click confirm or expander pattern
    ...
```

---

## Streamlit Application Structure
*(unchanged from v4, keep files and responsibilities — add helper modules below)*

```
src/ui/
├── app.py                      # Main entry point, app shell & router
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
├── helpers/
│   ├── nav.py                  # st.navigation/links helpers (NEW)
│   ├── dialogs.py              # @st.dialog wrappers (NEW)
│   ├── fragments.py            # @st.fragment decorators (NEW)
│   └── editor.py               # data_editor configs & selection helpers (NEW)
└── utils/
    ├── formatters.py           # EUR formatting, date display
    ├── validators.py           # Input validation helpers
    ├── state_management.py     # Streamlit session state helpers
    └── feature_flags.py        # Feature detection (NEW)
```

---

## App Shell & Navigation

### A. Declarative navigation (preferred)
```python
# src/ui/app.py
import streamlit as st
from src.ui.helpers import nav

st.set_page_config(page_title="Surebet Ops Console", layout="wide")

if hasattr(st, "navigation"):
    pages = [
        st.Page("pages/1_incoming_bets.py", title="Incoming Bets", icon="📥"),
        st.Page("pages/2_surebets.py", title="Surebets", icon="🎯"),
        st.Page("pages/3_settlement.py", title="Settlement", icon="⚖️"),
        st.Page("pages/4_reconciliation.py", title="Reconciliation", icon="🏥"),
        st.Page("pages/5_export.py", title="Export", icon="📦"),
        st.Page("pages/6_statements.py", title="Statements", icon="📊"),
        st.Page("pages/7_admin_associates.py", title="Admin", icon="⚙️"),
    ]
    current = st.navigation(pages)
    current.run()
else:
    # Fallback: legacy multipage via /pages directory; show quick links
    st.title("Surebet Ops Console")
    if hasattr(st, "page_link"):
        st.page_link("pages/2_surebets.py", label="Go to Surebets", icon="🎯")
        st.page_link("pages/3_settlement.py", label="Go to Settlement", icon="⚖️")
```

### B. Page links (quick actions)
Use `st.page_link` inline for your most common cross-page jumps (e.g., after approving a bet, jump to the Resolve Queue).

---

## Interaction Model & Rerun Control

### A. Fragments for partial reruns
Wrap heavy sub-areas (tables, long lists, log areas) in `@st.fragment` so that **only that area reruns** on interaction.

```python
# src/ui/helpers/fragments.py
import streamlit as st

if hasattr(st, "fragment"):
    @st.fragment
    def render_review_queue(limit: int = 100):
        # loads items and renders table; filtering widgets inside this function
        ...
else:
    def render_review_queue(limit: int = 100):
        ...
```

You can also auto-rerun fragments (`run_every=5`) for polling job progress.

### B. Dialogs for confirm/override
Use `@st.dialog` for: SETTLE confirm, “Create canonical event”, “Apply correction”.

```python
# src/ui/helpers/dialogs.py
import streamlit as st

def confirm_settlement(on_confirm):
    if hasattr(st, "dialog"):
        @st.dialog("Confirm settlement")
        def modal():
            st.warning("This action is PERMANENT.")
            notes = st.text_area("Optional note")
            cols = st.columns(2)
            if cols[0].button("Confirm"):
                on_confirm(notes)
                st.rerun()  # closes dialog
            if cols[1].button("Cancel"):
                st.rerun()
        modal()
    else:
        # Fallback two-click confirm
        if st.button("⚠️ SETTLE (Permanent)"):
            if st.session_state.get("confirm_modal"):
                on_confirm("")
                st.session_state.confirm_modal = False
            else:
                st.session_state.confirm_modal = True
                st.warning("Click again to confirm.")
```

### C. Popovers for compact per-row actions
Great for small action menus on each row (e.g., “Deactivate”, “Override fixture”, “Copy”).

```python
if hasattr(st, "popover"):
    with st.popover("Actions"):
        st.button("Deactivate")
        st.button("Edit")
        st.button("Copy link")
```

---

## Data Editing & Tables (CRUD)

### A. Standardize on `st.data_editor`
- Use `column_config` for types and validation.  
- Use `num_rows="dynamic"` to allow add/remove rows when appropriate.  
- Use the return value (the edited frame) as the **only** source of truth for saving.  
- Pass `disabled=["id"]` or type-specific `disabled=True` to make columns read-only.

```python
import streamlit as st
import pandas as pd

df = pd.DataFrame([
    {"id":"a1","name":"Alice","default_currency":"EUR","share_pct":50.0,"active":True},
])

config = {
    "name": st.column_config.TextColumn("Name", required=True, width="medium"),
    "default_currency": st.column_config.SelectboxColumn("CCY", options=["EUR","AUD","GBP","RON"]),
    "share_pct": st.column_config.NumberColumn("Share %", min_value=0, max_value=100, step=0.5, format="%.1f"),
    "active": st.column_config.CheckboxColumn("Active"),
    "id": st.column_config.TextColumn("ID", disabled=True),
}

edited = st.data_editor(
    df, use_container_width=True, hide_index=True,
    column_config=config, num_rows="fixed"
)
```

### B. Selections & bulk actions
`st.dataframe` can emit selection data when selection events are enabled in your version (e.g., rerun on selection). Use it to implement bulk confirm/deactivate without extra checkbox columns.

```python
sel = st.dataframe(
    df, use_container_width=True,
    # in newer versions, selection events can trigger a rerun and return selection data
)
# sel may return a dict with selected rows/cols in supported versions
```

If selection events aren’t available, keep the explicit `CheckboxColumn("✓")` pattern.

---

## Streaming Output (logs, LLM, OCR progress)
Use `st.write_stream` to produce a typewriter-like log area without manual placeholders:

```python
import time, streamlit as st

def gen():
    for i in range(5):
        yield f"Step {i+1}/5…\n"
        time.sleep(0.5)

if hasattr(st, "write_stream"):
    st.write_stream(gen())
else:
    # fallback
    ph = st.empty()
    for chunk in gen():
        ph.write(chunk)
```

---

## PDF Previews (slips, statements)
Use `st.pdf` for inline PDF viewing (installed with `streamlit-pdf`).

```python
# pip install streamlit-pdf
import streamlit as st
if hasattr(st, "pdf"):
    st.pdf("data/slips/bet_1234.pdf", height=600)
else:
    st.info("Update Streamlit to a version with st.pdf or use an image preview.")
```

---

## Design Principles (kept, with additions)

### 1. Single‑Page‑Per‑Workflow
**Mapping remains:**  
- FR‑1, FR‑2 → `1_incoming_bets.py`  
- FR‑3, FR‑4, FR‑5 → `2_surebets.py`  
- FR‑6, FR‑7 → `3_settlement.py`  
- FR‑8 → `4_reconciliation.py`  
- FR‑9 → `5_export.py`  
- FR‑10 → `6_statements.py`  
- FR‑11 → `7_admin_associates.py`

### 2. Stateless-first, but scoped state allowed
- Keep `st.session_state` for **current selection**, **dialog state**, **filters**.  
- Use fragments to isolate reruns to hot areas (queues, tables, logs).

### 3. Data access
- Keep **direct SQLite** access for transparency.  
- Wrap writes in small functions that validate and log.

### 4. Component reusability
- Keep `components/` and add helper layers (dialogs, fragments, editor configs).

---

## Page Patterns (updated)

### Page 1: Incoming Bets (FR‑1, FR‑2)
- Manual upload form in an `st.form` to avoid mid-typing reruns.  
- “Create canonical event” → `@st.dialog`.  
- OCR/progress output → `st.write_stream` (or fragment with `run_every`).

### Page 2: Surebets (FR‑3, FR‑4, FR‑5)
- “Open & Coverage” tab shows metrics and cards.  
- Add a **fragment** around the live table so filtering doesn’t rerun the whole page.  
- For per-row actions (copy, send coverage), use `st.popover` menus.

### Page 3: Settlement (FR‑6, FR‑7)
- Outcome radio + overrides.  
- Final **Confirm** via `@st.dialog` modal.  
- Settlement preview uses a component and respects `use_container_width=True`.

### Page 4: Reconciliation (FR‑8)
- Per-associate summary cards remain.  
- “Apply Correction” uses a dialog.  
- Bookmaker drilldown table uses `st.data_editor` with read-only IDs.

### Page 5: Export (FR‑9)
- Button triggers export job; show streaming log of export steps.  
- Provide a direct `st.download_button` when ready.

### Page 6: Monthly Statements (FR‑10)
- Generate → show `st.pdf` preview and `st.download_button`.  
- Internal-only metrics under an `st.expander("Operator view")`.

### Page 7: Admin – Associates & Bookmakers (FR‑11)
- **Master → Detail** pattern: top associates editor, bottom bookmakers editor filtered by selection.  
- Use `column_config` for types, `num_rows="fixed"` unless you allow row adds.  
- Bulk deactivate via selection API or checkbox column.

---

## Utilities (kept)

### Formatters
- Keep currency and datetime helpers; ensure UTC normalization for storage.

### Validators
- Simple decimal/currency validation; expand with Pydantic if needed.

---

## Performance & Reliability

- Prefer **fragments** for heavy areas and polling.  
- Use `st.cache_data` for slow, read-only lookups (e.g., static alias lists) with a short TTL.  
- Keep images as thumbnails; open full-size in dialogs when needed.  
- Avoid global mutable state; prefer function‑local variables and explicit returns.

---

## Training Appendix: “New Streamlit Features” (for agents)

**1) `@st.fragment` (partial reruns)**  
- Encapsulate a section so widget interactions rerun only that function.  
- Use `run_every=5` for auto-refreshing queues/progress.  
**When to use:** review queues, job logs, large tables.

**2) `@st.dialog` (modal interactions)**  
- Build confirm/override flows in a modal that doesn’t disrupt the page.  
- Close by calling `st.rerun()` after success.  
**When to use:** SETTLE confirm, manual event creation, applying corrections.

**3) `st.popover` (compact menus)**  
- Small action menus attached to rows/buttons; opening/closing doesn’t rerun the app.  
**When to use:** per-row actions: copy, edit, deactivate.

**4) `st.data_editor` enhancements**  
- Use `column_config` to get type-aware editors (Text/Number/Select/Checkbox/Link).  
- Control editable vs read-only columns with `disabled`.  
- `num_rows="dynamic"` to allow adding/removing rows; otherwise keep `"fixed"` for strict CRUD.  
**When to use:** associates/bookmakers CRUD, alias tables.

**5) `st.dataframe` selections**  
- In newer versions, enable selection events and treat the return as input for bulk actions.  
**When to use:** bulk confirm/deactivate flows when you don’t need an editable grid.

**6) `st.write_stream` (stream logs/LLMs)**  
- Emit incremental output with typewriter effect; avoids manual placeholder juggling.  
**When to use:** OCR pipeline progress, export/statement build logs, LLM normalization traces.

**7) `st.pdf` (PDF viewer)**  
- Show PDF slips/statements inline. Requires `streamlit-pdf`.  
**When to use:** slip previews, monthly statements, audits.

**8) Navigation helpers**  
- `st.navigation` + `st.Page` to define top-level pages in code.  
- `st.page_link` for inline “go to …” links in success messages and dashboards.

**9) Layout hygiene**  
- Always call `st.set_page_config(layout="wide")`.  
- Prefer `use_container_width=True` for tables and wide controls.  
- Group advanced controls in `st.expander("Advanced")`.

**10) Feature flags & fallbacks**  
- Detect features with `hasattr(st, "...")`.  
- Provide graceful fallbacks (two-click confirm; legacy multipage sidebar; checkbox bulk‑select).

---

## Example: Resolve Queue refactor (fragments + dialog)
```python
import streamlit as st
from src.ui.helpers.fragments import render_review_queue
from src.ui.helpers.dialogs import confirm_settlement

st.title("✅ Resolve Events")

if hasattr(st, "fragment"):
    render_review_queue(limit=100)  # fragment reruns independently
else:
    # legacy: inline render
    ...

# Somewhere in row action:
def on_confirm(notes):
    settle_surebet(selected_id, notes)

confirm_settlement(on_confirm)
```

---

## Deprecations & Gotchas
- `use_column_width` → **remove**, now **use_container_width=True**.  
- Avoid storing large DataFrames in `st.session_state` (memory bloat and pickling costs).  
- Keep dialogs short-lived; call `st.rerun()` on success to close them.  
- Be careful with fragments: widgets must live **inside** the fragment body.

---

**End of Document**
