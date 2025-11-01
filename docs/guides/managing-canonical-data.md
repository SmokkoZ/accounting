# Managing Canonical Data

This guide explains how to manage canonical events and markets in the Surebet Accounting System.

## Overview

**Canonical data** normalizes betting information:
- **Canonical Events**: Standardized event names (e.g., "Manchester City vs Liverpool")
- **Canonical Markets**: Standardized market types (e.g., "Total Goals Over/Under")

This ensures bets from different bookmakers can be matched for surebet identification.

---

## Canonical Markets

### Current Coverage

The system includes **47 markets** across 5 tiers:

**Tier 1: Most Common (Football)** - Covers ~80% of betting volume
- Match Winner / 1X2
- Total Goals O/U
- Both Teams to Score
- Asian Handicap
- Draw No Bet
- Double Chance
- And more...

**Tier 2: Popular Markets** - Covers ~15% of volume
- Goal Scorers (First, Last, Anytime)
- Correct Score
- Corners
- Cards
- Half-time markets

**Tier 3: Niche Football Markets**
- Corner Handicaps
- Booking Points
- Odd/Even Goals
- Time of First Goal

**Tier 4: Other Sports**
- Tennis (Match Winner, Sets, Games)
- Basketball (Moneyline, Spread, Totals)
- American Football (NFL markets)
- Baseball, Hockey, etc.

**Tier 5: Catch-All**
- OTHER - For unclassified markets
- CUSTOM - For custom/special markets

### Adding New Markets

#### Method 1: Using the Management Script

```bash
# Seed all comprehensive markets
python scripts/manage_canonical_data.py seed-markets

# This adds 47 common markets covering most betting scenarios
```

#### Method 2: Manual SQL Insert

```sql
INSERT INTO canonical_markets (market_code, description) VALUES
('MARKET_CODE', 'Human Readable Description');
```

#### Method 3: Future Enhancement

In future, add a UI in the admin panel to manage markets:
- Add new market
- Edit market description
- Mark markets as inactive
- View market usage statistics

### Market Naming Conventions

**Market Code Format:**
- UPPERCASE_SNAKE_CASE
- Descriptive and unambiguous
- Sport prefix for sport-specific markets (e.g., `TENNIS_`, `NBA_`)

**Examples:**
- `MATCH_WINNER` - Generic across sports
- `TOTAL_GOALS_OVER_UNDER` - Football-specific
- `TENNIS_SET_BETTING` - Tennis-specific

---

## Canonical Events

### Current Status

**Current Approach**: Manual creation
- Operator creates events when approving first bet
- Limited to 2 sample events currently

**Problem**: Not scalable for high volume

### Automatic Event Creation (Recommended Implementation)

#### Option A: Auto-Create on Approval (Easy Win)

**How it works:**
1. OCR extracts event name: "Lens vs Paris FC"
2. Operator approves bet and selects "Create New Event"
3. System auto-creates canonical event with:
   - Normalized event name from OCR
   - Kickoff time from OCR
   - League from OCR
   - Sport from OCR
4. Links bet to new event

**Implementation:**
```python
# In BetVerificationService.approve_bet()
if canonical_event_id is None and event_name_from_ocr:
    # Auto-create new event
    canonical_event_id = self.create_canonical_event(
        event_name=event_name_from_ocr,
        kickoff_time_utc=bet['kickoff_time_utc'],
        league=bet.get('league'),
        sport=bet.get('sport', 'football')
    )
```

**Pros:**
- ✅ Easy to implement
- ✅ Works immediately
- ✅ Operator controls creation

**Cons:**
- ⚠️ Can create duplicates ("Man City" vs "Manchester City")
- ⚠️ Requires operator action

#### Option B: Smart Event Matching (Better)

**How it works:**
1. OCR extracts: "Man City vs Liverpool"
2. System searches for similar events:
   - "Manchester City vs Liverpool" (95% match)
3. Suggests existing event to operator
4. If no match, auto-creates

**Implementation:**
```python
def find_or_create_event(event_name: str, threshold=0.8):
    # Fuzzy match against existing events
    matches = fuzzy_match(event_name, existing_events)

    if matches and matches[0].score > threshold:
        return matches[0].event_id
    else:
        # Create new
        return create_canonical_event(event_name)
```

**Libraries to use:**
- `fuzzywuzzy` - String similarity matching
- `thefuzz` - Modern fork of fuzzywuzzy
- `python-Levenshtein` - Fast string distance

**Pros:**
- ✅ Prevents duplicates
- ✅ Learns over time
- ✅ Can run automatically

**Cons:**
- ⚠️ Needs tuning (threshold)
- ⚠️ False positives possible

#### Option C: Event Normalization Service (Best Long-Term)

**How it works:**
1. Maintain team name mappings:
   ```
   "Man City" → "Manchester City"
   "Man Utd" → "Manchester United"
   "PSG" → "Paris Saint-Germain"
   ```

2. Normalize before matching:
   ```python
   ocr_event = "Man City vs PSG"
   normalized = normalize_teams(ocr_event)
   # Result: "Manchester City vs Paris Saint-Germain"
   ```

3. Match on normalized name

**Data sources:**
- Manual mapping file (JSON/CSV)
- External API (The Sports DB, API-Football)
- Machine learning model

**Pros:**
- ✅ Most accurate
- ✅ Professional-grade
- ✅ Handles all edge cases

**Cons:**
- ⚠️ Requires initial data setup
- ⚠️ Maintenance overhead
- ⚠️ May need paid API

### Managing Events via Script

```bash
# Create a new event
python scripts/manage_canonical_data.py create-event \
  "Real Madrid vs Barcelona" \
  "2025-11-15T20:00:00Z" \
  "La Liga" \
  "football"

# Find similar events
python scripts/manage_canonical_data.py find-similar "Real Madrid"

# Import events from CSV
python scripts/manage_canonical_data.py import-events events.csv
```

### CSV Import Format

Create `events.csv`:
```csv
event_name,kickoff_time_utc,league,sport
"Manchester City vs Liverpool,2025-11-01T15:00:00Z,Premier League,football"
"Real Madrid vs Barcelona,2025-11-15T20:00:00Z,La Liga,football"
"PSG vs Marseille,2025-11-08T19:00:00Z,Ligue 1,football"
```

Then import:
```bash
python scripts/manage_canonical_data.py import-events events.csv
```

---

## Recommended Workflow

### For Production Use

1. **Week 1-2: Manual Mode**
   - Manually create events as needed
   - Build up canonical event database
   - Learn common patterns

2. **Week 3-4: Implement Auto-Create (Option A)**
   - Add auto-create on "Create New Event" selection
   - Monitor for duplicates
   - Manually merge duplicates

3. **Month 2: Implement Smart Matching (Option B)**
   - Add fuzzy matching
   - Set threshold at 85%
   - Review and adjust

4. **Month 3+: Normalization Service (Option C)**
   - Build team name mappings
   - Integrate external API if needed
   - Full automation

---

## Database Queries

### Check Current Data

```sql
-- Count markets
SELECT COUNT(*) FROM canonical_markets;

-- List all markets
SELECT market_code, description FROM canonical_markets ORDER BY description;

-- Count events
SELECT COUNT(*) FROM canonical_events;

-- Recent events
SELECT normalized_event_name, league, kickoff_time_utc
FROM canonical_events
ORDER BY created_at_utc DESC
LIMIT 10;

-- Find duplicate events
SELECT normalized_event_name, COUNT(*) as count
FROM canonical_events
GROUP BY normalized_event_name
HAVING count > 1;
```

### Clean Up Duplicates

```sql
-- Find duplicates
SELECT id, normalized_event_name FROM canonical_events
WHERE normalized_event_name IN (
    SELECT normalized_event_name
    FROM canonical_events
    GROUP BY normalized_event_name
    HAVING COUNT(*) > 1
)
ORDER BY normalized_event_name, id;

-- Merge duplicates (keep oldest, update bets to point to it)
-- 1. Update bets
UPDATE bets SET canonical_event_id = <keep_id> WHERE canonical_event_id = <duplicate_id>;

-- 2. Delete duplicate
DELETE FROM canonical_events WHERE id = <duplicate_id>;
```

---

## Best Practices

### Market Coverage

1. **Start with Tier 1 markets** (most common)
2. **Add Tier 2 when needed** (as you see them in bets)
3. **Use OTHER for unknowns** (then classify later)
4. **Review monthly** - Add new markets based on usage

### Event Management

1. **Normalize team names early** - "Man City" → "Manchester City"
2. **Include league in name** if ambiguous - "Arsenal vs Chelsea (Premier League)"
3. **Use consistent date format** - ISO8601 with Z suffix
4. **Set kickoff times accurately** - Important for surebet timing
5. **Tag with sport** - Helps with filtering and reports

### Data Quality

1. **Review weekly** - Check for duplicates
2. **Merge duplicates promptly** - Prevents surebet matching issues
3. **Archive old events** - After settlement date + 30 days
4. **Validate on import** - Check data before bulk imports

---

## Future Enhancements

### Phase 1: Admin UI (Epic 4)
- View all canonical markets
- Add new market types
- Edit market descriptions
- View market usage stats

### Phase 2: Event Auto-Creation (Epic 4 or 5)
- Auto-create events on approval
- Fuzzy matching to suggest existing events
- Operator confirmation before creating

### Phase 3: Event Normalization API
- Integrate with sports data API
- Auto-populate upcoming events
- Team name normalization
- Live score updates

### Phase 4: Machine Learning
- Learn from operator corrections
- Auto-suggest canonical matches
- Confidence scoring
- Anomaly detection

---

## Troubleshooting

### "Market dropdown is empty"
```bash
# Check if markets exist
sqlite3 data/surebet.db "SELECT COUNT(*) FROM canonical_markets;"

# If zero, run seeding
python scripts/manage_canonical_data.py seed-markets
```

### "Can't find my event"
```bash
# Search for similar events
python scripts/manage_canonical_data.py find-similar "Team Name"

# Create manually if needed
python scripts/manage_canonical_data.py create-event \
  "Exact Event Name" "2025-11-01T20:00:00Z" "League" "sport"
```

### "Duplicate events"
```sql
-- Find duplicates
SELECT normalized_event_name, COUNT(*)
FROM canonical_events
GROUP BY normalized_event_name
HAVING COUNT(*) > 1;

-- Merge manually via SQL (see Clean Up Duplicates section above)
```

---

## Summary

**Quick Start:**
```bash
# Seed all markets (run once)
python scripts/manage_canonical_data.py seed-markets

# Create events as needed
python scripts/manage_canonical_data.py create-event \
  "Event Name" "2025-11-01T20:00:00Z" "League" "sport"
```

**Recommended Path:**
1. Use manual creation initially
2. Implement auto-create (Option A) in Epic 3-4
3. Add smart matching (Option B) in Epic 4-5
4. Consider normalization service (Option C) for scale

**Current Coverage:**
- ✅ 47 canonical markets (covers 95%+ of common bets)
- ⚠️ 2 sample events (needs scaling solution)
- 🎯 Next: Implement auto-event creation
