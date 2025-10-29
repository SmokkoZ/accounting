# Epic 1: Bet Ingestion Pipeline

**Status:** Not Started
**Priority:** P0 (MVP Critical)
**Estimated Duration:** 5-7 days
**Owner:** Tech Lead
**Phase:** 1 (Core Features)
**PRD Reference:** FR-1 (Bet Ingestion)

---

## Epic Goal

Build an automated bet ingestion pipeline that captures screenshots from Telegram or manual uploads, extracts structured bet data using GPT-4o vision, and queues bets for operator review. This epic establishes the primary data entry point for the entire system.

---

## Business Value

### Operator Benefits
- **Time Savings**: Eliminates manual data entry from screenshots
- **Accuracy**: AI extraction reduces transcription errors
- **Flexibility**: Supports both Telegram (primary) and manual upload (WhatsApp, photos)
- **Audit Trail**: Every bet links back to original screenshot with extraction metadata

### System Benefits
- **Structured Data**: Converts unstructured screenshots into queryable bet records
- **Quality Signals**: Confidence scoring helps operator prioritize review
- **Multi-source**: Handles Telegram, WhatsApp, camera photos uniformly

**Success Metric**: 90% of screenshots processed within 10 seconds, 80%+ accuracy for high-confidence extractions.

---

## Epic Description

### Context

Associates send bet screenshots via:
1. **Telegram** (primary): One chat per bookmaker, bot auto-ingests
2. **Manual upload** (secondary): WhatsApp forwards, camera photos uploaded via UI

Both paths must produce identical `bets` records with:
- Screenshot saved to disk
- OCR + GPT-4o extraction
- Confidence scoring
- Queue entry with `status="incoming"`

### What's Being Built

Three ingestion paths:

1. **Telegram Screenshot Ingestion** (Story 1.1)
   - Extends Phase 0 bot scaffold with DB writes
   - Maps chat IDs → (associate, bookmaker)
   - Triggers OCR pipeline automatically

2. **OCR + GPT-4o Extraction Pipeline** (Story 1.2)
   - Vision API call extracts bet fields
   - Normalizes market terminology
   - Scores extraction confidence
   - Flags unsupported bet types (accumulators)

3. **Manual Upload Panel** (Story 1.3)
   - Streamlit UI for off-Telegram bets
   - Associate/bookmaker selection
   - Triggers same OCR pipeline as Telegram

### Integration Points

**Upstream Dependencies:**
- Phase 0 database schema (`bets` table)
- Phase 0 Telegram bot scaffold
- Phase 0 Streamlit app

**Downstream Consumers:**
- Epic 2 (Bet Review) reads from `status="incoming"` queue

---

## Stories

### Story 1.1: Telegram Screenshot Ingestion

**As the operator**, I want screenshots sent to Telegram bookmaker chats to be automatically saved and processed so I don't have to manually handle every photo.

**Acceptance Criteria:**
- [ ] Extends Phase 0 bot photo handler to:
  - Save screenshot to `data/screenshots/{timestamp}_{associate_alias}_{bookmaker_name}.png`
  - Create `bets` row with:
    - `status="incoming"`
    - `ingestion_source="telegram"`
    - `telegram_message_id=<message_id>` (traceability)
    - `associate_id`, `bookmaker_id` (from chat ID mapping)
    - `screenshot_path` (relative path to saved file)
    - `created_at_utc` (current timestamp in ISO8601)
  - Trigger Story 1.2 OCR pipeline asynchronously
  - Reply to sender: "Processing screenshot..."
- [ ] Chat ID mapping configured:
  - Config file (`telegram_chats.yaml`) or DB table (`telegram_chat_mappings`)
  - Format: `chat_id: {associate_id: X, bookmaker_id: Y}`
  - Example: `chat_id=123456: {associate_id=1, bookmaker_id=1}` → "Admin + Bet365"
- [ ] Unknown chat IDs rejected with error message
- [ ] Screenshot file naming collision handled (add milliseconds to timestamp)

**Technical Notes:**
- Use `message.photo[-1].get_file()` for highest resolution
- Store relative paths in DB (not absolute) for portability
- Consider background queue (Celery/RQ) vs. inline processing

---

### Story 1.2: OCR + GPT-4o Extraction Pipeline

**As the system**, I want bet screenshots to be automatically parsed using GPT-4o vision to extract structured bet data with confidence scoring.

**Acceptance Criteria:**
- [ ] Extraction service function: `extract_bet_data(screenshot_path: str) -> dict`
  - Calls OpenAI GPT-4o with vision capability
  - Prompt engineering for bet extraction:
    - Identify sport, teams, event name → `canonical_event` guess
    - Extract market type → `market_code` (e.g., "TOTAL_GOALS_OVER_UNDER")
    - Extract period → `period_scope` (e.g., "FULL_MATCH", "FIRST_HALF")
    - Extract line/handicap → `line_value` (e.g., "2.5", "+0.5")
    - Extract bet side → `side` (e.g., "OVER", "UNDER", "TEAM_A")
    - Extract financial data → `stake`, `odds`, `payout`, `currency`
    - Extract kickoff time → `kickoff_time_utc` (best guess, ISO8601)
  - Returns extraction result with fields + confidence
- [ ] Confidence scoring logic:
  - High confidence (≥0.8): All required fields extracted cleanly
  - Low confidence (<0.8): Missing fields, OCR ambiguity, or unclear market type
  - Store as `normalization_confidence` (0.0-1.0 float)
- [ ] Model version tracking:
  - Store `model_version_extraction` (e.g., "gpt-4o-2024-11-20")
  - Store `model_version_normalization` (same or separate model)
- [ ] Accumulator/multi detection:
  - If bet contains multiple selections (multi-leg), set:
    - `is_multi=1`
    - `is_supported=0` (these bets never match into surebets)
  - Single-leg bets: `is_multi=0`, `is_supported=1`
- [ ] Error handling:
  - If API call fails: log error, leave extracted fields NULL
  - If timeout: retry once, then fail gracefully
  - Bet remains `status="incoming"` for manual entry
- [ ] Updates `bets` row with extracted fields
- [ ] Logs extraction metadata to separate table (`extraction_log`) or JSON field

**Technical Notes:**
- OpenAI API key from `.env` (`OPENAI_API_KEY`)
- Rate limiting: max 10 requests/minute (configurable)
- Cost tracking: log tokens used per extraction
- Consider fallback to Tesseract OCR if GPT-4o unavailable
- Prompt template versioning for reproducibility

**Prompt Engineering Guide:**
```
Extract structured bet data from this bookmaker screenshot:

Required fields:
- Event name (teams or competitors)
- Market type (e.g., "Total Goals Over/Under", "Asian Handicap")
- Period (e.g., "Full Match", "First Half")
- Line/Handicap value (e.g., "2.5", "+0.5")
- Bet side (e.g., "Over", "Under", "Team A")
- Stake amount and currency
- Odds (decimal format preferred)
- Potential payout and currency
- Kickoff time (if visible)

Also detect:
- Is this a single bet or accumulator/multi?
- Confidence in extraction (high/low)

Return JSON format with all fields.
```

---

### Story 1.3: Manual Upload Panel (UI)

**As the operator**, I want to manually upload screenshots from WhatsApp or camera photos for off-Telegram bets so all bets flow through the same pipeline.

**Acceptance Criteria:**
- [ ] "Incoming Bets" Streamlit page includes "Upload Manual Bet" panel:
  - **File picker**: Accepts PNG, JPG, JPEG (max 10MB)
  - **Associate dropdown**: Populated from `associates.display_alias` (e.g., "Admin", "Partner A")
  - **Bookmaker dropdown**: Dynamically filtered by selected associate
    - Query: `SELECT bookmakers.* WHERE associate_id=<selected>`
    - Display as `bookmaker.name` (e.g., "Bet365 AU")
  - **Optional note field**: Free text (e.g., "From WhatsApp group")
  - **"Import & OCR" button**: Triggers upload + OCR pipeline
- [ ] On "Import & OCR" click:
  - Save uploaded file to `data/screenshots/{timestamp}_manual_{associate}_{bookmaker}.png`
  - Create `bets` row with:
    - `status="incoming"`
    - `ingestion_source="manual_upload"`
    - `telegram_message_id=NULL` (not from Telegram)
    - `associate_id`, `bookmaker_id` (from dropdowns)
    - `screenshot_path`
    - `operator_note` (from note field)
    - `created_at_utc`
  - Call Story 1.2 OCR pipeline (same function as Telegram)
  - Show spinner: "Processing screenshot..."
  - On completion: success message "Bet added to review queue"
- [ ] Form validation:
  - File required
  - Associate required
  - Bookmaker required (must belong to selected associate)
- [ ] Bet appears in Incoming Bets queue identically to Telegram bets

**Technical Notes:**
- Use `st.file_uploader()` for file picker
- Use `st.selectbox()` with dynamic filtering for bookmakers
- Clear form after successful submission
- Handle large files gracefully (show progress bar if >1MB)

---

## User Acceptance Testing Scenarios

### Scenario 1: Telegram Happy Path
1. Associate sends bet screenshot to bookmaker-specific Telegram chat
2. Bot receives photo, saves to `data/screenshots/`
3. OCR extracts bet data (high confidence ≥0.8)
4. Bet appears in "Incoming Bets" queue with ✅ confidence badge
5. Operator reviews and approves (Epic 2)

**Expected Result**: Screenshot → `status="incoming"` in <10 seconds.

---

### Scenario 2: Manual Upload (WhatsApp)
1. Operator opens "Incoming Bets" page
2. Selects "Upload Manual Bet" panel
3. Chooses screenshot from WhatsApp forward
4. Selects associate "Partner A", bookmaker "Pinnacle GBP"
5. Adds note "From WhatsApp group"
6. Clicks "Import & OCR"
7. Bet processed identically to Telegram bet

**Expected Result**: Manual bet flows through same pipeline, appears in queue with `ingestion_source="manual_upload"`.

---

### Scenario 3: Accumulator Detection
1. Associate sends multi-leg accumulator screenshot
2. OCR detects multiple selections
3. Bet created with `is_multi=1`, `is_supported=0`
4. Bet appears in queue with warning badge "Accumulator - Not Supported"
5. Operator can review but cannot match into surebet (Epic 3 rejects)

**Expected Result**: Accumulators flagged, never matched.

---

### Scenario 4: OCR Failure (Low Confidence)
1. Associate sends blurry screenshot
2. OCR extracts partial data (missing odds, unclear market)
3. Bet created with `normalization_confidence=0.4`
4. Bet appears in queue with ⚠ low confidence badge
5. Operator corrects fields manually (Epic 2)

**Expected Result**: Low confidence bets queued for manual review, not auto-approved.

---

### Scenario 5: API Failure (GPT-4o Down)
1. Associate sends screenshot
2. OpenAI API call fails (timeout/error)
3. Bet created with all extracted fields NULL
4. Error logged to console/log file
5. Bet appears in queue with note "OCR failed - manual entry required"
6. Operator enters data manually (Epic 2)

**Expected Result**: System degrades gracefully, no data loss, operator notified.

---

## Technical Considerations

### API Rate Limiting

**OpenAI GPT-4o Limits:**
- Free tier: 3 requests/minute
- Paid tier: configurable (suggest 10 requests/minute)

**Mitigation:**
- Queue screenshots for batch processing if rate limited
- Show "X bets in OCR queue" counter in UI
- Consider Redis queue for asynchronous processing

### Cost Management

**GPT-4o Vision Pricing** (as of 2024):
- ~$0.01 per image (approximate)
- 100 bets/day = $1/day = $30/month

**Tracking:**
- Log tokens used per API call
- Show monthly cost in admin dashboard (future)
- Alert if costs exceed $50/month

### Error Recovery

**Failure Scenarios:**
1. **Telegram bot offline**: Screenshots queued when bot restarts
2. **GPT-4o API down**: Retry with exponential backoff, fallback to manual entry
3. **Screenshot corrupted**: Log error, skip OCR, queue for manual review
4. **Disk full**: Alert operator, prevent new screenshot saves

---

## Dependencies

### Upstream (Blockers)
- **Epic 0**: Phase 0 complete
  - Story 0.2: `bets` table exists
  - Story 0.4: Telegram bot scaffold working

### Downstream (Consumers)
- **Epic 2** (Bet Review): Reads from `status="incoming"` queue produced by this epic

---

## Definition of Done

Epic 1 is complete when ALL of the following are verified:

### Functional Validation
- [ ] All 3 stories (1.1-1.3) marked complete with passing acceptance criteria
- [ ] Telegram bets flow from chat → screenshot → OCR → `incoming` queue
- [ ] Manual upload works for off-Telegram screenshots
- [ ] OCR extracts bet data with ≥80% accuracy for clear screenshots
- [ ] Accumulators detected and flagged as unsupported
- [ ] Low confidence bets flagged for manual review

### Technical Validation
- [ ] GPT-4o API integration works (valid API key, rate limiting handled)
- [ ] Screenshot files saved to disk with correct naming
- [ ] Chat ID mapping configuration works
- [ ] Error handling prevents data loss (failed OCR doesn't block ingestion)

### User Testing
- [ ] All 5 UAT scenarios pass
- [ ] Operator can process 10 screenshots end-to-end
- [ ] Both Telegram and manual upload produce identical `bets` records

### Handoff Readiness
- [ ] Epic 2 team can query `status="incoming"` bets
- [ ] Screenshot paths resolve correctly in UI
- [ ] Confidence scoring meaningful (high vs. low)

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| OCR accuracy <80% | Medium | High | Manual correction workflow (Epic 2); iterative prompt engineering |
| GPT-4o API downtime | Low | Medium | Queue bets for processing when API recovers; fallback to manual entry |
| Rate limiting blocks ingestion | Medium | Medium | Asynchronous queue; show "Processing X bets..." counter |
| Screenshot storage fills disk | Low | High | Monitor disk usage; implement rotation policy (future) |
| Unknown chat ID sends screenshot | Medium | Low | Bot replies "Unregistered chat - contact admin" |

---

## Success Metrics

### Completion Criteria
- All 3 stories delivered with passing acceptance criteria
- Epic 1 "Definition of Done" checklist 100% complete
- Zero blockers for Epic 2 (Bet Review)

### Quality Metrics
- **OCR Accuracy**: ≥80% of high-confidence bets correct on first pass
- **Processing Time**: ≥90% of screenshots processed in <10 seconds
- **Error Rate**: <5% of ingestion attempts fail permanently
- **Coverage**: Both Telegram and manual upload paths working

---

## Related Documents

- [PRD: FR-1 (Bet Ingestion)](../prd.md#fr-1-bet-ingestion)
- [Epic 0: Foundation & Infrastructure](./epic-0-foundation.md)
- [Epic 2: Bet Review & Approval](./epic-2-bet-review.md)
- [Implementation Roadmap](./implementation-roadmap.md)

---

## Notes

### Why Dual Ingestion Paths Matter

While Telegram is the primary path (90% of bets), supporting manual upload is **critical** for:
- **Resilience**: Associates can send bets via WhatsApp if Telegram down
- **Ad-hoc scenarios**: In-person betting, phone photos
- **Onboarding**: New associates without Telegram can still participate

Treat both paths as first-class citizens with identical data quality.

### Prompt Engineering Iteration

OCR accuracy depends heavily on prompt quality. Budget time for:
- Testing with real bookmaker screenshots (10+ different bookmakers)
- Iterating on prompt wording to improve extraction
- Building bookmaker-specific prompt templates (future optimization)

**Tip**: Start with generic prompt, specialize later based on error patterns.

---

**End of Epic**
