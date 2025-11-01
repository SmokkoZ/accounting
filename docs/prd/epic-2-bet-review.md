# Epic 2: Bet Review & Approval

**Status:** Not Started
**Priority:** P0 (MVP Critical)
**Estimated Duration:** 3-4 days
**Owner:** Tech Lead
**Phase:** 2 (Core Features)
**PRD Reference:** FR-2 (Bet Review & Approval)

---

## Epic Goal

Build a unified review queue and approval workflow that allows the operator to verify, correct, and approve/reject incoming bets from all sources (Telegram + manual) before they enter the matching pipeline. This epic ensures human-in-the-loop quality control.

---

## Business Value

### Operator Benefits
- **Quality Gate**: Catch OCR errors before they propagate into settlements
- **Confidence**: Visual verification with screenshot preview
- **Efficiency**: Inline editing eliminates round-trip corrections
- **Audit Trail**: Every approval logged with timestamps and field changes

### System Benefits
- **Data Accuracy**: Only verified bets reach matching pipeline (Epic 3)
- **Error Prevention**: Malformed bets rejected before causing downstream issues
- **Traceability**: `verification_audit` table links corrections to operator actions

**Success Metric**: 95% of bets reviewed within 2 minutes of ingestion, <1% verification errors.

---

## Epic Description

### Context

Epic 1 produces `bets` with `status="incoming"` from:
- Telegram screenshots (with OCR extraction)
- Manual uploads (with OCR extraction)

Some extractions are high-confidence (✅), others are low-confidence (⚠) or failed (NULL fields).

Before bets can be matched into surebets (Epic 3), the operator must:
1. **Review** extracted data against screenshot
2. **Correct** any OCR errors inline
3. **Approve** (→ `status="verified"`) or **Reject** (→ `status="rejected"`)

### What's Being Built

Two interconnected UI components:

1. **Incoming Bets Queue** (Story 2.1)
   - Unified view of all `status="incoming"` bets
   - Screenshot preview with extracted data overlay
   - Confidence badges (✅ high, ⚠ low)
   - Source icons (📱 Telegram, 📤 manual)
   - Counters: waiting review, approved today, rejected today

2. **Inline Editing & Approval** (Story 2.2)
   - Click-to-edit any extracted field
   - Dropdown selectors for canonical values
   - Approve/Reject buttons with audit logging
   - Keyboard shortcuts for power users

### Integration Points

**Upstream Dependencies:**
- Epic 1 (Bet Ingestion): Produces `status="incoming"` bets

**Downstream Consumers:**
- Epic 3 (Surebet Matching): Consumes `status="verified"` bets

---

## Stories

### Story 2.1: Incoming Bets Queue UI

**As the operator**, I want a unified queue showing all incoming bets (Telegram + manual) for review so I can verify OCR extractions.

**Acceptance Criteria:**
- [ ] "Incoming Bets" Streamlit page displays all `status="incoming"` bets
  - Query: `SELECT * FROM bets WHERE status='incoming' ORDER BY created_at_utc DESC`
- [ ] Each bet displayed as card/row with:
  - **Screenshot preview**: Thumbnail (click to enlarge modal)
  - **Associate & Bookmaker**: `display_alias` + `bookmaker.name`
  - **Ingestion source**: Icon badge (📱 Telegram | 📤 Manual)
  - **Event guess**: Text display of `canonical_event` (editable in Story 2.2)
  - **Market details**: `market_code`, `period_scope`, `line_value`, `side`
  - **Financial**: `stake @ odds = payout` (currency displayed)
  - **Kickoff time**: `kickoff_time_utc` formatted local time
  - **Confidence badge**:
    - ✅ Green "High Confidence" if `normalization_confidence >= 0.8`
    - ⚠ Yellow "Low Confidence" if `normalization_confidence < 0.8`
    - ❌ Red "Extraction Failed" if extracted fields are NULL
  - **Timestamp**: "Received X minutes ago"
  - **Special flags**:
    - 🚫 "Accumulator - Not Supported" if `is_multi=1`
    - 📝 "Operator note: {note}" if `operator_note` exists (manual uploads)
- [ ] Counters at top of page (real-time):
  - **Waiting review**: Count of `status='incoming'`
  - **Approved today**: Count of `status='verified'` WHERE `verified_at_utc >= today`
  - **Rejected today**: Count of `status='rejected'` WHERE `verified_at_utc >= today`
- [ ] Pagination or infinite scroll if >20 bets
- [ ] Filter options (nice-to-have):
  - By associate
  - By confidence level
  - By ingestion source

**Technical Notes:**
- Use `st.columns()` for card layout
- Use `st.image()` for screenshot preview
- Use `st.expander()` for full-size screenshot modal
- Cache database queries with `@st.cache_data(ttl=5)`

---

### Story 2.2: Inline Editing & Approval Workflow

**As the operator**, I want to correct OCR errors and approve/reject bets inline so I don't have to navigate away from the review queue.

**Acceptance Criteria:**
- [ ] Each bet card has "Edit Mode" toggle or inline edit fields:
  - **Canonical Event**: Dropdown/searchbox
    - Populated from `canonical_events` table (existing events)
    - Includes "Create New Event" option → modal to add new event
    - Display as: "Team A vs Team B (2025-10-30)"
  - **Market Code**: Dropdown
    - Values from `canonical_markets` table (e.g., "TOTAL_GOALS_OVER_UNDER")
    - Display human-readable labels (e.g., "Total Goals Over/Under")
  - **Period Scope**: Dropdown
    - Fixed values: "FULL_MATCH", "FIRST_HALF", "SECOND_HALF", "FIRST_QUARTER", etc.
  - **Line Value**: Number input
    - Decimal or half-decimal (e.g., "2.5", "+0.5")
    - Allow NULL for markets without lines
  - **Side**: Dropdown
    - Logical sides: "OVER", "UNDER", "YES", "NO", "TEAM_A", "TEAM_B"
    - Filtered by market type (e.g., O/U markets only show OVER/UNDER)
  - **Stake**: Number input (native currency)
  - **Odds**: Number input (decimal format)
  - **Payout**: Number input (native currency)
  - **Currency**: Dropdown (AUD, GBP, EUR, USD, etc.)
- [ ] "Approve" button (green):
  - On click:
    - Validate all required fields populated
    - Log edits to `verification_audit` table:
      - `bet_id`, `field_name`, `old_value`, `new_value`, `edited_at_utc`, `edited_by="local_user"`
    - Update `bets`:
      - Set `status="verified"`
      - Set `verified_at_utc=<current_timestamp>`
      - Set `verified_by="local_user"`
    - Remove bet from queue
    - Show success toast: "Bet approved"
    - Decrement "Waiting review" counter
    - Increment "Approved today" counter
- [ ] "Reject" button (red):
  - On click:
    - Show modal: "Reject this bet?" with optional rejection reason text field
    - Update `bets`:
      - Set `status="rejected"`
      - Set `verified_at_utc=<current_timestamp>`
      - Set `verified_by="local_user"`
      - Set `rejection_reason=<optional_note>`
    - Remove bet from queue
    - Show success toast: "Bet rejected"
    - Decrement "Waiting review" counter
    - Increment "Rejected today" counter
- [ ] Keyboard shortcuts (power user feature):
  - `A`: Approve current bet
  - `R`: Reject current bet
  - `↓`: Next bet in queue
  - `↑`: Previous bet in queue
- [ ] Field validation:
  - Stake > 0
  - Odds > 1.0
  - Payout >= Stake (sanity check for winning bets)
  - Currency selected
  - Canonical event selected
- [ ] Audit log visible to operator (future admin page):
  - Query: `SELECT * FROM verification_audit WHERE bet_id=<current> ORDER BY edited_at_utc`

**Technical Notes:**
- Use `st.selectbox()` for dropdowns
- Use `st.number_input()` for numeric fields
- Use `st.button()` with `key` parameter to avoid duplicate widget IDs
- Consider using Streamlit session state for edit mode toggle
- Validate on client side before DB write

---

### Story 2.3: Canonical Event Auto-Creation

**As the system**, I want to automatically create canonical events from OCR-extracted data when the operator approves a bet so that matching (Epic 3) has the required canonical_event_id.

**Acceptance Criteria:**
- [ ] When operator approves bet (Story 2.2) with `canonical_event_id = NULL`:
  - System extracts event data from OCR fields:
    - `event_name` from bet's extracted event text
    - `sport` from bet's sport classification
    - `kickoff_time_utc` from bet's extracted kickoff time
    - `competition` (optional) from bet's competition text
- [ ] Before creating new event, perform fuzzy matching check:
  - Query existing `canonical_events` for similar event within ±24h of kickoff
  - Use fuzzy string matching (e.g., Levenshtein distance) on event_name
  - If match confidence > 80%: Use existing event_id
  - If match confidence ≤ 80%: Create new event
- [ ] Fuzzy matching algorithm:
  - Normalize event names (lowercase, remove punctuation)
  - Calculate similarity score using `rapidfuzz` library
  - Match threshold: 80% similarity
  - Time window: ±24 hours of kickoff_time_utc
- [ ] If no match found, create new `canonical_events` row:
  - `INSERT INTO canonical_events (event_name, sport, competition, kickoff_time_utc)`
  - Return newly created `event_id`
- [ ] Update bet record with `canonical_event_id` before changing status to "verified"
- [ ] Manual override option in UI:
  - "Create New Event" button in bet card dropdown
  - Opens modal with fields: event_name, sport, competition, kickoff_time_utc
  - Operator can manually create event if auto-match fails
  - Modal pre-fills OCR-extracted values for easy editing
- [ ] Validation:
  - event_name: Required, min 5 chars
  - sport: Required, from predefined list (FOOTBALL, TENNIS, BASKETBALL, etc.)
  - kickoff_time_utc: Required, ISO8601 format with "Z" suffix
  - competition: Optional, max 100 chars
- [ ] Error handling:
  - If event creation fails (DB error), show error message
  - Bet remains in "incoming" status (not approved)
  - Log error for debugging
- [ ] Audit logging:
  - Log canonical event creation to `verification_audit` table
  - Fields: `bet_id`, `field_name="canonical_event_id"`, `old_value=NULL`, `new_value=<event_id>`, `edited_by="auto|local_user"`

**Technical Notes:**
- Extend `BetVerificationService` in `src/services/bet_verification.py`
- Add method: `get_or_create_canonical_event(bet_id) -> int`
- Use fuzzy matching library: `rapidfuzz` (faster than fuzzywuzzy)
- Fuzzy matching query:
  ```sql
  SELECT id, event_name, kickoff_time_utc
  FROM canonical_events
  WHERE sport = <bet.sport>
    AND ABS(julianday(kickoff_time_utc) - julianday(<bet.kickoff_time_utc>)) <= 1
  ```
  Then filter in Python with `rapidfuzz.fuzz.ratio()`
- Transaction: Create event + update bet.canonical_event_id atomically
- UI modal: Use `st.dialog()` for "Create New Event" form

---

## User Acceptance Testing Scenarios

### Scenario 1: High-Confidence Bet (Quick Approve)
1. Operator opens "Incoming Bets" page
2. Sees bet with ✅ "High Confidence" badge
3. Reviews screenshot + extracted data: All correct
4. Clicks "Approve" (no edits needed)
5. Bet moves to `status="verified"`, disappears from queue
6. Counter updates: "Waiting review: 4 → 3", "Approved today: 12 → 13"

**Expected Result**: High-confidence bets approved in <10 seconds.

---

### Scenario 2: Low-Confidence Bet (Inline Correction)
1. Operator sees bet with ⚠ "Low Confidence" badge
2. Reviews screenshot: OCR extracted wrong odds (1.85 instead of 1.95)
3. Clicks odds field, corrects to 1.95
4. Payout auto-recalculates (optional enhancement)
5. Clicks "Approve"
6. Bet verified, edit logged in `verification_audit`

**Expected Result**: Low-confidence bets correctable inline without extra screens.

---

### Scenario 3: Extraction Failed (Manual Entry)
1. Operator sees bet with ❌ "Extraction Failed" (all fields NULL)
2. Opens screenshot in modal (full size)
3. Manually enters all fields:
   - Event: "Manchester United vs Arsenal (2025-11-01)"
   - Market: "Total Goals Over/Under"
   - Period: "Full Match"
   - Line: 2.5
   - Side: "Over"
   - Stake: 100 AUD @ 1.90 = 190 AUD
4. Clicks "Approve"
5. Bet verified despite failed OCR

**Expected Result**: Failed extractions don't block workflow, operator can enter data manually.

---

### Scenario 4: Reject Accumulator
1. Operator sees bet with 🚫 "Accumulator - Not Supported"
2. Recognizes multi-leg bet
3. Clicks "Reject"
4. Modal: "Reject this bet?" → enters reason "Accumulator not supported"
5. Bet rejected, removed from queue

**Expected Result**: Unsupported bet types rejected cleanly.

---

### Scenario 5: Create New Event
1. Operator reviewing bet: Event not in dropdown (upcoming match)
2. Selects "Create New Event" from dropdown
3. Modal opens: Enter teams, sport, kickoff time
4. Submits → new `canonical_events` row created
5. Dropdown updates, new event selectable
6. Continues approval workflow

**Expected Result**: Operator can create new events on-the-fly without leaving review queue.

---

## Technical Considerations

### Audit Trail Design

**`verification_audit` Table Schema:**
```sql
CREATE TABLE verification_audit (
  audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
  bet_id INTEGER NOT NULL REFERENCES bets(bet_id),
  field_name TEXT NOT NULL,          -- e.g., "odds", "canonical_event_id"
  old_value TEXT,                     -- JSON or string representation
  new_value TEXT NOT NULL,            -- JSON or string representation
  edited_at_utc TEXT NOT NULL,        -- ISO8601 timestamp
  edited_by TEXT NOT NULL DEFAULT 'local_user'
);
```

**Use Cases:**
- Debugging: "Why was this bet's odds changed?"
- Quality control: "How often does operator correct OCR?"
- Model improvement: "Which fields have highest error rate?"

### Inline Edit UX Patterns

**Option A: Always-On Edit Fields**
- Pro: No mode switching, fastest workflow
- Con: Cluttered UI, accidental edits

**Option B: Toggle Edit Mode**
- Pro: Clean view, intentional edits
- Con: Extra click per bet

**Recommendation**: Start with Option A (always-on), gather feedback.

### Performance Optimization

**Potential Bottlenecks:**
- Loading 100+ screenshots on page load → lazy load thumbnails
- Database query on every Streamlit rerun → cache with TTL=5s
- Large screenshot files → generate thumbnails on upload

**Optimization:**
- Pre-generate 200px thumbnails in Story 1.2 (ingestion)
- Use `st.experimental_fragment` for bet cards (Streamlit 1.33+)

---

## Dependencies

### Upstream (Blockers)
- **Epic 1**: Bet Ingestion complete
  - `status="incoming"` bets exist in database
  - Screenshots saved to disk
  - Confidence scoring populated

### Downstream (Consumers)
- **Epic 3**: Surebet Matching
  - Reads from `status="verified"` queue produced by this epic

---

## Definition of Done

Epic 2 is complete when ALL of the following are verified:

### Functional Validation
- [ ] All 3 stories (2.1-2.3) marked complete with passing acceptance criteria
- [ ] Incoming Bets queue displays all `status="incoming"` bets
- [ ] Screenshot previews load correctly
- [ ] Inline editing works for all fields
- [ ] Approve workflow updates `status="verified"` and logs edits
- [ ] Reject workflow updates `status="rejected"` with reason
- [ ] Counters update in real-time

### Technical Validation
- [ ] `verification_audit` table logs all edits
- [ ] Canonical event creation modal works
- [ ] Field validation prevents invalid data
- [ ] Keyboard shortcuts functional (nice-to-have)

### User Testing
- [ ] All 5 UAT scenarios pass
- [ ] Operator can review 20 bets in <5 minutes
- [ ] No data loss on approve/reject

### Handoff Readiness
- [ ] Epic 3 team can query `status="verified"` bets
- [ ] Audit trail queryable for debugging

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Operator overwhelmed by 100+ pending bets | Medium | Medium | Prioritization: show low-confidence bets first; add filters |
| Accidental approval of incorrect bet | Medium | High | Confirmation modal for approve; undo feature (future) |
| Canonical event dropdown too large | Low | Low | Add search/filter; recent events at top |
| Inline editing buggy (Streamlit state) | Medium | Medium | Thorough testing; fallback to edit modal |

---

## Success Metrics

### Completion Criteria
- All 3 stories delivered with passing acceptance criteria
- Epic 2 "Definition of Done" checklist 100% complete
- Zero blockers for Epic 3 (Surebet Matching)

### Quality Metrics
- **Review Speed**: 95% of bets reviewed within 2 minutes of ingestion
- **Accuracy**: <1% of verified bets require post-approval correction
- **Audit Coverage**: 100% of edits logged in `verification_audit`
- **Rejection Rate**: <10% of incoming bets rejected (implies good OCR quality)

---

## Related Documents

- [PRD: FR-2 (Bet Review & Approval)](../prd.md#fr-2-bet-review--approval)
- [Epic 1: Bet Ingestion Pipeline](./epic-1-bet-ingestion.md)
- [Epic 3: Surebet Matching & Safety](./epic-3-surebet-matching.md)
- [Implementation Roadmap](./implementation-roadmap.md)

---

## Notes

### Why Human-in-the-Loop Matters

While OCR provides 80%+ accuracy, the remaining 20% can cause:
- **Incorrect settlements**: Wrong odds → wrong profit calculations
- **Failed matches**: Typo in event name → surebet never paired
- **Financial loss**: Misread stake → incorrect entitlement

Epic 2 is the **quality gate** that prevents these downstream errors.

**Rule of Thumb**: Spend 30 seconds reviewing each bet to save 10 minutes debugging settlement errors later.

### Future Enhancements (Post-MVP)

- **Auto-approve high-confidence bets**: If `normalization_confidence >= 0.95`, skip review
- **Bulk approve**: Select multiple bets, approve all at once
- **Undo approve**: Operator realizes mistake, click "Undo" within 5 minutes
- **Mobile review**: Approve bets from phone while away from desk

---

**End of Epic**
