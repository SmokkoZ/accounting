# Surebet Accounting System — final-project.md

Local Single-Operator MVP Spec (Updated)

## 0. Purpose

This document defines the exact MVP we will build.

It merges and resolves the previous brief, PRD, and architecture notes, and encodes the clarified real-world workflow rules, including admin share logic, FX usage, reconciliation, Monthly Statements, and now manual screenshot upload for off-Telegram slips.

**Critical context:**

* There is only ONE real user of the system: you.
* You act as:

  * **Admin** (send instructions, size stakes, match opposite sides, coordinate the network)
  * **Accountant** (verify slips, settle matches, reconcile balances)
* All associates are trusted human friends. There is no adversarial relationship.
* The app runs locally on your machine. No cloud, no multi-user.
* Associates can use different currencies. We convert everything into EUR to compare and split profit correctly.
* You ONLY build surebets with mirrored two-way markets:

  * Over/Under same line
  * Yes/No
  * Team A handicap vs Team B handicap
* You manually confirm match results / final stats.
* Profit or loss from each surebet is split equally across all involved parties using defined rules (including you, even if you didn’t personally stake).

You always need to know:

* Who is “holding too much” (sitting on group money)
* Who is short (“where is his money?”)
* Whether any bookmaker balance in the real world disagrees with what the system thinks

This MVP replaces spreadsheets and Telegram juggling. Build **exactly** this.

---

## 1. Real-world workflow we’re solving

### Today (manual reality)

1. You spot an arbitrage (surebet) using your own software.
2. You DM each associate separately with what to bet (market, selection, odds, stake).
3. Each associate confirms the odds are available and places the bet.
4. They send you a screenshot in that bookmaker’s Telegram chat (you + them + bot).
5. You forward screenshots to each associate’s multibook chat so everyone sees the opposite side exists.
6. After the match:

   * You check the actual result (cards over/under, red card yes/no, 1st half corners over/under, handicap result, etc.).
   * You figure out which side won.
   * You compute the group profit or loss in EUR.
   * You split that equally across all relevant parties (see §6).
   * You update who is holding how much money.
   * You ask each associate to confirm their bookmaker balances.
   * You fix differences manually in a spreadsheet.

This is slow and error-prone.

### After this MVP

* Screenshots sent to Telegram are ingested automatically and OCR’d.
* OCR + GPT-4o proposes structured bets:

  * event / canonical_event_id guess
  * market_code
  * period_scope
  * line_value
  * side
  * stake
  * odds
  * payout
  * currency
  * kickoff_time_utc guess
  * confidence score
* You review everything in ONE "Incoming Bets" queue:

  * High-confidence bets can be batch-approved.
  * Low-confidence bets can be corrected before approval.
* After approval, bets on opposite sides of the same market/line/scope are grouped into a surebet automatically (deterministic, no ML guesswork).
* Each surebet displays worst-case EUR profit and ROI classification (✅ / 🟡 / ❌).
* One button sends coverage proof screenshots (raw slips from both sides) to each associate’s private multibook chat.
* Settlement is done in kickoff order:

  * You declare who won.
  * You can mark bets WON / LOST / VOID.
  * The system calculates final P/L, the equal split, and the admin share (the admin is you).
  * You confirm once.
* The system writes append-only ledger rows with frozen FX snapshots.
* Reconciliation shows, for each associate (and you):

  * How much they’ve funded in
  * How much they’re currently holding
  * How much they SHOULD be holding after equal-split math
  * The delta
* Deposits/withdrawals can be declared in Telegram (“deposit 200”), and wait for your approval in the app.
  **Note:** Telegram auto-capture can be MVP-optional. Manual “Add deposit/withdrawal” button is OK for true MVP.
* Monthly Statements view can generate a simple “partner report” per associate that reads like normal human accounting (“you put in X, you’re entitled to Y now, so you’re up Z; we split Z 50/50”). See §10.
* Rare case: If a screenshot comes from outside Telegram (WhatsApp, camera photo, etc.), you can upload it manually (see §4.1 Manual Upload). It still ends up in Incoming Bets, same as Telegram ones.

---

## 2. Deployment model (non-negotiable)

* Single machine (“accountant machine”).
* Single human operator (you).
* No login / no RBAC / no multi-tenant.
* App is local-only.
* Data is local-only.

**Local components:**

* Telegram bot (polling mode, python-telegram-bot v20+)
* Streamlit app (UI, `localhost:8501`)
* SQLite DB file (`data/surebet.db`)
* Screenshot storage (`data/screenshots/`)
* Ledger export folder (`data/exports/`)
* FX cache table in SQLite to store per-currency → EUR conversions

**External calls:**

* OCR / LLM (GPT-4o, etc.) for extraction and normalization.
* FX API call to get currency → EUR conversions (cached locally in `fx_rates_daily`).

Everything else is offline and local.

---

## 3. System Laws (MUST NEVER BREAK)

These are contractual rules. The code must follow these 100% of the time.

1. **Append-only ledger.**
   Money-impacting history is never edited in place. Fixes are forward adjustments (BOOKMAKER_CORRECTION). No rewrites.

2. **Frozen FX.**
   Every ledger row stores the `fx_rate_snapshot` used at creation. All EUR math later uses *that snapshot*. We never “revalue” old rows if FX changes.

3. **Equal-split settlement.**
   After a surebet is graded, total profit/loss in EUR is split into equal slices:

   * If you (admin) DID stake, you’re just another participant.
   * If you did NOT stake, you still get exactly one extra seat in the split as coordinator, and that seat also eats losses.
     There is never a second skim/fee.

4. **VOID still participates.**
   VOID means stake refunded (net_gain_eur = 0), but that associate is still considered part of the surebet for splitting profit/loss.
   If an entire surebet is VOID on all sides, we *still* produce BET_RESULT rows with zeros so entitlement history is continuous.

5. **Manual truth about match results.**
   You decide who won. The system does not auto-grade sports results.

6. **No silent messaging.**
   Bot only sends screenshots into multibook chats when you explicitly press “Send coverage proof.” It never DMs results or balances on its own.

---

## 4. Core goals of the system (functional targets)

The system MUST let you do all of the following, locally:

### 4.1 Ingest bets from screenshots (Telegram OR manual upload)

#### Telegram path

* One Telegram chat per bookmaker (maps to `associate_id + bookmaker_id`).
* One multibook chat per associate (this is where coverage proof goes).
* Associate sends screenshot of a placed bet.
* Bot:

  * Saves screenshot under `data/screenshots/...`
  * Creates a `bets` row with `status="incoming"`
  * Sets `ingestion_source="telegram"`
  * Sets `telegram_message_id`
  * Runs OCR + GPT-4o to produce normalized candidates:

    * `canonical_event` guess
    * `market_code`
    * `period_scope` (`FULL_MATCH`, `FIRST_HALF`, `SECOND_HALF`)
    * `line_value` (TEXT decimal: `"6.5"`, `"2.5"`, `"-0.5"`)
    * `side` (`"OVER"`, `"UNDER"`, `"YES"`, `"NO"`, `"TEAM_A"`, `"TEAM_B"`)
    * `stake`, `odds`, `payout`
    * `kickoff_time_utc` guess
    * `normalization_confidence`
    * `model_version_extraction`, `model_version_normalization`
  * Accumulators / multis:

    * `is_multi=1`
    * `is_supported=0`
    * They never go into matching.

#### Manual Upload path (rare but supported and IN SCOPE for MVP)

Sometimes a bet screenshot comes from outside Telegram (WhatsApp, in-person photo, etc.).

**Incoming Bets page MUST include an "Upload Manual Bet" panel** with:

* Screenshot file picker
* Associate selector (dropdown of existing associates by `display_alias`)
* Bookmaker selector (dropdown filtered by that associate’s bookmakers)
* Optional free-text note for the operator

When you click “Import & OCR”:

1. The system saves the uploaded screenshot under `data/screenshots/...` (same as Telegram).
2. It creates a new `bets` row with:

   * `status="incoming"`
   * `associate_id` / `bookmaker_id` from your selections
   * `timestamp_received_utc=NOW`
   * `telegram_message_id=NULL`
   * `ingestion_source="manual_upload"`
3. It immediately runs the **same** OCR / normalization pipeline as Telegram ingestion to fill:

   * `raw_extraction_text`
   * `structured_candidate_json`
   * `extraction_confidence`
   * `normalization_confidence`
   * `model_version_extraction`
   * `model_version_normalization`
   * Guess of `canonical_event_id`, `market_code`, `period_scope`, `line_value`, `side`, `stake`, `odds`, `payout`, `kickoff_time_utc`

After that, the manually uploaded bet appears in the **Incoming Bets** queue with ✅ / ⚠ exactly like any Telegram bet.
From that point on it is treated 100% the same (approve/reject, matching, settlement, ledger).
No downstream logic needs to care if `ingestion_source` was `"manual_upload"` or `"telegram"` — it's only for audit/filtering.

> MVP note: We can force associate/bookmaker to be chosen from existing dropdowns. No need to build “create new associate” inline for v1.

---

### 4.2 Single "Incoming Bets" review/approval flow

* All new bets land in Incoming Bets (both Telegram and manual upload).
* High-confidence bets get a ✅ badge.
* Low-confidence bets show ⚠ and must be edited before approval.
* You can correct:

  * stake / odds / payout
  * `canonical_event_id`
  * `market_code`
  * `period_scope`
  * `line_value`
  * `side`
* Approve → `status="verified"`.
* Reject → `status="rejected"`.
* All edits are logged in `verification_audit`.
* Nothing is auto-approved silently.

(MVP-optional QoL: “likely matches” dropdown for `canonical_event_id`. Bare minimum is just a search dropdown of known upcoming events.)

### 4.3 Deterministic surebet grouping

After a bet is `verified`:

* We try to match it into a surebet using strict rules:

  * same `canonical_event_id`
  * same `market_code`
  * same `period_scope`
  * same `line_value`
  * opposite logical side:

    * OVER vs UNDER
    * YES vs NO
    * TEAM_A vs TEAM_B
* If matched:

  * Create/update a `surebets` row with `status="open"`
  * Insert bet links into `surebet_bets`
  * Set those bets to `status="matched"`

Important details:

* We treat the entire opposing set as ONE surebet.
  Example: if A and B are “NO RED CARD” and C is “YES RED CARD”, that’s one surebet: (A+B) vs (C). We do *not* explode it into multiple pairwise surebets.
* `surebet_bets.side` is deterministic and MUST NEVER flip later:

  * `"A"` = OVER / YES / TEAM_A
  * `"B"` = UNDER / NO / TEAM_B

### 4.4 Surebet safety check (ROI label)

For each `surebet`, using EUR values via cached FX:

* Compute:

  * `profit_if_A_wins_eur`
  * `profit_if_B_wins_eur`
  * `worst_case_profit_eur = min(those two)`
  * `total_staked_eur`
  * `ROI = worst_case_profit_eur / total_staked_eur`

* Label:

  * ✅ if `worst_case_profit_eur ≥ 0` and ROI ≥ threshold
  * 🟡 if `worst_case_profit_eur ≥ 0` but ROI < threshold
  * ❌ if `worst_case_profit_eur < 0`

We display worst-case EUR profit, total EUR staked, and ROI classification.

### 4.5 Manual coverage proof

* Button: “Send coverage proof.”
* For each associate on Side A:

  * Send all Side B screenshots into that associate’s multibook chat.
* For each associate on Side B:

  * Send all Side A screenshots.
* Message text:
  `"You’re covered for [EVENT / MARKET LINE]. Opposite side attached."`
* We log:

  * which screenshots we forwarded
  * timestamp
  * Telegram message id
  * in `multibook_message_log`

We DO NOT anonymize screenshots or auto-spam. You trigger it manually (System Law #6).

### 4.6 Settlement (grading outcomes)

Settlement happens in kickoff order.

* Settlement tab/page lists surebets sorted by `kickoff_time_utc` oldest-first (yesterday’s first).
* You pick a surebet. You see:

  * Both sides, each bet with:

    * associate alias
    * bookmaker
    * stake @ odds
    * screenshot link
* You pick base outcome:

  * “Side A WON / Side B LOST”
  * or “Side B WON / Side A LOST”
* You can override any individual bet to WON / LOST / VOID manually.

Before finalizing, preview shows:

* `surebet_profit_eur` (can be positive or negative)
* N (participant count, including admin seat if you didn’t stake)
* `per_surebet_share_eur`
* `principal_returned_eur` per associate
* each associate’s updated entitlement slice from this surebet
* the FX rate snapshot that will be used
* VOID rule warning (“VOID still participates in split”)

**Confirm (with a modal warning “This is permanent”):**

* Create one batch ID (`settlement_batch_id`) for this click.
* For each associate in that surebet, for each of their bets:

  * Write a `ledger_entries` row of type `"BET_RESULT"`:

    * `settlement_state` (`"WON"`, `"LOST"`, `"VOID"`)
    * `amount_native` / `native_currency`
    * `fx_rate_snapshot` (Decimal EUR per 1 unit native currency at this moment)
    * `amount_eur` (that bet’s net gain/loss in EUR)
    * `principal_returned_eur` (stake effectively back via WON/VOID)
    * `per_surebet_share_eur` (their equal-split seat from this surebet, same scalar for all participants in this surebet settlement)
    * `associate_id`, `bookmaker_id`, `surebet_id`, `bet_id`
    * `settlement_batch_id` (same for all rows from this confirm)
    * `created_at_utc`
    * `created_by="local_user"`
    * `note`
* Mark `surebet.status="settled"` and bets `status="settled"`.

Edge case: **All bets VOID**

* We STILL write BET_RESULT rows with:

  * `amount_eur = 0`
  * `per_surebet_share_eur = 0`
  * correct `principal_returned_eur`
* We do this to keep entitlement math and Monthly Statements continuous.

We do NOT DM associates automatically about results.

### 4.7 Post-settlement corrections

If you later discover:

* a late VOID,
* a grading error,
* or a mismatch between modeled bookmaker balance and what the associate swears is in the app:

We do NOT reopen old surebets.

Instead you create a forward-only `ledger_entries` row of type `"BOOKMAKER_CORRECTION"`:

* `amount_native`, `native_currency`
* `fx_rate_snapshot`, `amount_eur`
* `associate_id`, `bookmaker_id`
* `created_at_utc`
* `created_by="local_user"`
* `note` (e.g. “late VOID correction”, “misclick fix”)

This is how we reconcile without rewriting past rows (System Law #1).

---

## 5. Settlement math / definitions (canonical math)

Use these exact terms everywhere. They drive Reconciliation and Monthly Statements.

### 5.1 Compute realized P/L in EUR

Per bet:

* WON:

  * `payout_native = stake_native * odds`
  * Convert to EUR using FX snapshot
  * `stake_eur` = stake_native in EUR
  * `net_gain_eur = payout_eur - stake_eur`
* LOST:

  * `net_gain_eur = -stake_eur`
* VOID:

  * Stake refunded
  * `net_gain_eur = 0`

Sum across all bets in that surebet:

* `surebet_profit_eur`

  * Can be positive or negative

### 5.2 Determine participants for split

* `betting_participants` = all associates (including you if you staked) who had at least one bet in that surebet (WON / LOST / VOID)
* `admin` = you as coordinator

Rules:

* If you DID stake:
  `N = len(betting_participants)`
  You are already included. No extra admin seat.
* If you did NOT stake:
  `N = len(betting_participants) + 1`
  You get one extra seat as admin/coordinator.
  That extra seat participates in upside and also absorbs downside.
  There is never a second skim. (System Law #3)

### 5.3 Equal split

* `per_surebet_share_eur = surebet_profit_eur / N`
* Each participant gets exactly one seat worth of that value.
* If you didn’t stake but coordinated, you still get one seat worth of `per_surebet_share_eur`.

### 5.4 Principal returned

For each participant:

* `principal_returned_eur` = sum of the stake that effectively came back to them via WON or VOID, converted to EUR at settlement FX.

### 5.5 Entitlement slice from this surebet

For each participant, from this surebet:

`entitlement_component_eur = principal_returned_eur + per_surebet_share_eur`

When we write BET_RESULT rows into the ledger, we include:

* `principal_returned_eur`
* `per_surebet_share_eur`

Those two columns are enough to reconstruct how much each associate is entitled to “be holding” after all settled surebets.

---

## 6. Ledger model (append-only, auditable)

Every money-relevant event creates rows in `ledger_entries`.
We NEVER edit past rows. We only add forward corrections.

### Types in MVP

#### 1. BET_RESULT

Written on settlement confirm. One row per (associate, bet).

Fields:

* `type="BET_RESULT"`
* `settlement_state` (`"WON"`, `"LOST"`, `"VOID"`)
* `amount_native` / `native_currency`
* `fx_rate_snapshot` (Decimal: EUR per 1 unit of `native_currency` at settlement)
* `amount_eur` (that bet’s net gain/loss in EUR using that snapshot)
* `principal_returned_eur`
* `per_surebet_share_eur`
* `associate_id`
* `bookmaker_id`
* `surebet_id`
* `bet_id`
* `settlement_batch_id` (all rows created by one confirm click have the same value)
* `note` (e.g. “settlement batch 2025-10-28”)
* `created_at_utc` (UTC ISO8601 "Z")
* `created_by="local_user"`

#### 2. DEPOSIT / WITHDRAWAL

Created when you accept a funding event.

**MVP note:**
This can either:

* Come from parsed Telegram messages like “deposit 200” / “withdraw 150”, OR
* Be manually entered in the Reconciliation page (manual add is acceptable for true MVP; Telegram parsing is MVP-optional automation).

On Accept we write a real ledger row:

Fields:

* `type="DEPOSIT"` or `"WITHDRAWAL"`
* `amount_native` / `native_currency`
* `fx_rate_snapshot`
* `amount_eur`
* `associate_id`
* `bookmaker_id`
* `created_at_utc`
* `created_by="local_user"`
* `note` (“manual deposit confirmation”)
* `settlement_batch_id = NULL`

#### 3. BOOKMAKER_CORRECTION

Manual forward adjustment to reconcile modeled vs claimed balance OR a late VOID / grading fix.

Fields:

* `type="BOOKMAKER_CORRECTION"`
* `amount_native` / `native_currency`
* `fx_rate_snapshot`
* `amount_eur`
* `associate_id`
* `bookmaker_id`
* `created_at_utc`
* `created_by="local_user"`
* `note` (“late VOID correction”, “misclick fix”)
* `settlement_batch_id = NULL`

**Important:**
`bookmaker_balance_checks` rows (they say “my Ladbrokes is 312.50 right now”) do NOT auto-create corrections. You decide if/when to write a BOOKMAKER_CORRECTION row. That preserves System Law #1.

There is NO “re-open settlement” type in MVP.
No automatic DM of settlement results in MVP.

---

## 7. Reconciliation & balances (“Who is holding too much?”)

Reconciliation answers:

* Who is holding group float?
* Who is short?
* Which bookmaker balances disagree with reality?

We define canonical fields. These names MUST be used in code / UI / CSV:

1. **NET_DEPOSITS_EUR**
   How much cash they personally funded into the operation so far.
   `NET_DEPOSITS_EUR = (Sum of DEPOSIT.amount_eur) - (Sum of WITHDRAWAL.amount_eur)`

2. **SHOULD_HOLD_EUR** (Entitlement)
   How much of the pool belongs to them after all settled surebets so far.
   `SHOULD_HOLD_EUR = SUM_over_their_BET_RESULT_rows( principal_returned_eur + per_surebet_share_eur )`

   Intuition:
   “If we froze the world after all settled bets, this is how much of the pot is yours.”

   This already includes:

   * equal-split logic (including admin seat)
   * VOID handling
   * you taking one equal slice even if you didn’t stake, and you also eating losses

3. **CURRENT_HOLDING_EUR**
   What the model thinks they’re physically holding across all their bookmakers right now, after applying:

   * BET_RESULT
   * DEPOSIT
   * WITHDRAWAL
   * BOOKMAKER_CORRECTION
     each converted using the row’s own `fx_rate_snapshot`.

4. **DELTA**
   `DELTA = CURRENT_HOLDING_EUR - SHOULD_HOLD_EUR`

   * `DELTA > 0`:
     they are holding more than they should → they’re parking group float.
   * `DELTA < 0`:
     they are holding less than they should → someone else is effectively sitting on money that belongs to them, OR a correction is pending.

**Reconciliation / Health Check UI (morning routine):**

1. **Pending funding events**

   * Show parsed “deposit 200” / “withdraw 150” drafts OR manual entry fields.
   * Accept → write DEPOSIT/WITHDRAWAL ledger rows.
   * Reject → discard.

2. **Per Associate summary**

   * NET_DEPOSITS_EUR
   * CURRENT_HOLDING_EUR
   * SHOULD_HOLD_EUR
   * DELTA (color + explanation string)

     * “Holding +€800 more than entitlement (group float you should collect)”
     * “Holding -€200 less than entitlement (they’re owed €200 / someone else is parking their money)”
   * Green if DELTA ~ 0, red if large positive, orange if large negative.

3. **Per Bookmaker drilldown**

   * Modeled balance (native + EUR)
   * Reported live balance (from `bookmaker_balance_checks`)
   * Difference
   * Button “Apply correction” → writes BOOKMAKER_CORRECTION row to bring modeled in line.

---

## 8. Streamlit UI pages

We want the interface extremely simple. You can merge some of these into tabs if you want. Below is the conceptual layout.

### Page 1. Incoming Bets

Sections:

1. **Upload Manual Bet panel**

   * File input for screenshot.
   * Associate dropdown.
   * Bookmaker dropdown (limited to that associate).
   * “Import & OCR” button.
   * Creates `bets` row with `ingestion_source="manual_upload"`, runs OCR, pushes it into the same queue.

2. **Incoming Bets queue**

   * Shows all bets with `status="incoming"`, regardless of `ingestion_source` (`telegram` or `manual_upload`).
   * Screenshot preview.
   * Associate, bookmaker.
   * Event guess (editable dropdown/search).
   * `market_code / period_scope / line_value / side`.
   * Stake, odds, payout.
   * Confidence badge: ✅ (high) or ⚠ (low).
   * Inline edit for wrong fields.
   * Approve → `status="verified"` and log changes in `verification_audit`.
   * Reject → `status="rejected"`.
   * Counters:

     * `Waiting review: X`
     * `Approved today: Y`
     * `Rejected today: Z`

### Page 2. Surebets & Settlement

This can be one page with two tabs, or two pages. Behavior:

**Tab / View: Open & Coverage**

* For each `surebet` with `status="open"`:

  * Side A bets (associate alias, bookmaker, stake@odds)
  * Side B bets
  * worst-case EUR profit
  * total EUR staked
  * ROI classification: ✅ / 🟡 / ❌
  * `kickoff_time_utc`
  * Button: “Send coverage proof”

    * Sends raw screenshots across sides
    * Logs to `multibook_message_log`
* Counters:

  * `Open surebets: A`
  * `Unsafe surebets (❌): B`

**Tab / View: Settle**

* Surebets sorted by `kickoff_time_utc` oldest first (yesterday’s first).
* Pick one.
* Show bets, screenshots, stakes, odds, associate aliases.
* Choose outcome ("Side A WON / Side B LOST" etc.).
* Override specific bets to WON / LOST / VOID.
* Preview:

  * `surebet_profit_eur`
  * N (participant count including admin seat logic)
  * `per_surebet_share_eur`
  * `principal_returned_eur` per associate
  * each associate’s updated entitlement from this surebet
  * FX snapshot
  * VOID warning (“VOID still participates in split”)
* Confirm (with modal “This is permanent”):

  * Write BET_RESULT ledger rows with a shared `settlement_batch_id`.
  * Mark surebet/bets as settled.
* Counters:

  * `Settled today: C`
  * `Still open (unsettled): D`

### Page 3. Reconciliation / Health Check

* **Pending funding events:**

  * Show “deposit 200” / “withdraw 150” drafts (or let you key them in manually if Telegram parsing is not done yet).
  * Accept → create DEPOSIT/WITHDRAWAL ledger rows.
  * Reject → discard.
* **Per Associate summary:**

  * NET_DEPOSITS_EUR
  * CURRENT_HOLDING_EUR
  * SHOULD_HOLD_EUR
  * DELTA (green ≈0, red if holding group float, orange if short).
  * Include a human string like “Holding +€800 more than entitlement (group float you should collect)”.
* **Per Bookmaker drilldown:**

  * Modeled balance (native + EUR)
  * Reported live balance (from `bookmaker_balance_checks`)
  * Difference
  * Button “Apply correction” → writes BOOKMAKER_CORRECTION row (append-only).

### Page 4. Export

* Export all `ledger_entries` (joined with associate alias, bookmaker name, surebet_id, bet_id, settlement_batch_id, and fx_rate_snapshot) to CSV:

  * `data/exports/ledger_<timestamp>.csv`
* This CSV is the audit trail.

### Page 5. Monthly Statements (Partner Statements)

Purpose: generate a per-associate summary you can screenshot/send at period end (e.g. "End of October 2025").

For each associate and cutoff timestamp:

1. **NET_DEPOSITS_EUR**
   `(Sum of DEPOSIT.amount_eur) - (Sum of WITHDRAWAL.amount_eur)`
   “How much cash you personally put in.”

2. **SHOULD_HOLD_EUR**
   `SUM(principal_returned_eur + per_surebet_share_eur)` across all their BET_RESULT rows up to cutoff
   “If we froze time right now after all settled bets, this much of the pot is yours.”

3. **RAW_PROFIT_EUR**
   `RAW_PROFIT_EUR = SHOULD_HOLD_EUR - NET_DEPOSITS_EUR`
   “How far ahead you are compared to what you funded.”
   This can be positive or negative. You split that 50/50, always — you also eat losses.

**How you talk to them:**

* “You funded €X total.”
* “Right now you’re entitled to €Y.”
* “That means you’re up €Z overall.”
* “Our deal is 50/50, so €Z/2 each.”

Internal-only, visible to you:

* `CURRENT_HOLDING_EUR` = what they’re modeled to be physically holding right now across their bookmakers.
* `DELTA = CURRENT_HOLDING_EUR − SHOULD_HOLD_EUR`:

  * `DELTA > 0` ⇒ they’re sitting on extra group float.
  * `DELTA < 0` ⇒ they’re short / someone else is holding their value.

Monthly Statements:

* does NOT change entitlement math,
* does NOT create ledger rows,
* is just presentation.

---

## 9. Data model (key tables)

### associates

* `id (PK)`
* `display_alias`
* `home_currency`
* `multibook_chat_id`
* `metadata_json`
* `created_at_utc`
* `updated_at_utc`

Admin is also an associate:

* You may or may not stake.
* If you didn’t stake, you still get one equal-split seat at settlement and you also eat downside.

### bookmakers

* `id (PK)`
* `associate_id (FK → associates.id)`
* `bookmaker_name`
* `created_at_utc`
* `updated_at_utc`
* `parsing_profile` (optional OCR hints)

Currency implied by the associate’s `home_currency`.

### canonical_events

* `id (PK)`
* `normalized_event_name` (e.g. "Grêmio vs Juventude")
* `league`
* `kickoff_time_utc`
* `hash_key`
* `created_at_utc`

Used for Incoming Bets dropdown/search and settlement ordering.

### canonical_markets

* `id (PK)`
* `market_code`
  (e.g. `"FIRST_HALF_TOTAL_CORNERS_OVER_UNDER"`, `"ASIAN_HANDICAP"`, `"RED_CARD_YES_NO_FULL_MATCH"`)
* `description`
* `created_at_utc`

### bets

* `id (PK)`
* `associate_id (FK)`
* `bookmaker_id (FK)`
* `timestamp_received_utc`
* `screenshot_path`
* `telegram_message_id` (NULL if manual upload)
* `ingestion_source` (`"telegram"` | `"manual_upload"`)
* `status`: `"incoming" | "verified" | "matched" | "settled" | "rejected"`

**OCR / normalization:**

* `raw_extraction_text`
* `structured_candidate_json`
* `extraction_confidence`
* `model_version_extraction`

**Normalized / approved:**

* `canonical_event_id`
* `event_display_name`
* `market_code`
* `period_scope` (`"FULL_MATCH"|"FIRST_HALF"|"SECOND_HALF"`)
* `line_value` (TEXT Decimal: `"6.5"`, `"2.5"`, `"-0.5"`)
* `side` (`"OVER"|"UNDER"|"YES"|"NO"|"TEAM_A"|"TEAM_B"`)
* `stake_normalized` (TEXT Decimal)
* `odds_normalized` (TEXT Decimal)
* `potential_win_normalized` (TEXT Decimal)
* `is_supported` (0/1)
* `is_multi` (0/1; if 1 → `is_supported=0`, never matches)
* `normalization_confidence`
* `model_version_normalization`

**Financial snapshot at ingest:**

* `stake_native` (TEXT Decimal)
* `payout_native` (TEXT Decimal)
* `native_currency` (TEXT, e.g. "AUD")

**Operational:**

* `linked_surebet_id`
* `settlement_state` (`"WON"|"LOST"|"VOID"` or NULL until settlement)
* `created_at_utc`
* `updated_at_utc`
* `last_modified_by ("local_user")`

### surebets

* `id (PK)`
* `canonical_event_id`
* `market_code`
* `period_scope`
* `line_value`
* `status`: `"open" | "settled"`
* `created_at_utc`
* `updated_at_utc`

We compute `worst_case_profit_eur` / ROI dynamically using FX when displaying.

### surebet_bets

* `surebet_id (FK)`
* `bet_id (FK)`
* `side ("A"|"B")`

  * `"A"` = OVER / YES / TEAM_A
  * `"B"` = UNDER / NO / TEAM_B

`PRIMARY KEY (surebet_id, bet_id)`

This A/B mapping is fixed and must never flip later.

### ledger_entries

* `id (PK)`
* `associate_id (FK)`
* `bookmaker_id (FK nullable)`
* `surebet_id (FK nullable)`
* `bet_id (FK nullable)`
* `type ("BET_RESULT","DEPOSIT","WITHDRAWAL","BOOKMAKER_CORRECTION")`
* `settlement_state ("WON","LOST","VOID" for BET_RESULT; else NULL)`
* `amount_native` (TEXT Decimal)
* `native_currency` (TEXT)
* `fx_rate_snapshot` (TEXT Decimal; EUR per 1 unit of `native_currency` at row creation)
* `amount_eur` (TEXT Decimal; already converted at that snapshot)
* `principal_returned_eur` (TEXT Decimal; stake effectively back to them via WON/VOID)
* `per_surebet_share_eur` (TEXT Decimal; the equal-split slice for that associate from that surebet)
* `settlement_batch_id` (TEXT; groups rows created in the same confirm click)
* `note` ("settlement batch 2025-10-28", "manual deposit confirmation", "late VOID correction")
* `created_at_utc` (UTC ISO8601 "Z")
* `created_by ("local_user")`

These ledger rows are the single source of truth for:

* DEPOSIT/WITHDRAWAL funding history → NET_DEPOSITS_EUR
* Surebet entitlement per associate → SHOULD_HOLD_EUR = sum(principal_returned_eur + per_surebet_share_eur)
* Modeled bookmaker balances → CURRENT_HOLDING_EUR
* Monthly Statements math → RAW_PROFIT_EUR

### verification_audit

* `id (PK)`
* `bet_id (FK)`
* `diff_before_after` (TEXT/JSON)
* `note` (TEXT)
* `created_at_utc`
* `actor ("local_user")`

### multibook_message_log

* `id (PK)`
* `associate_id (FK)`
* `surebet_id (FK)`
* `message_type ("COVERAGE_PROOF")`
* `forwarded_bet_ids` (TEXT/JSON list of bet_ids)
* `message_body` (TEXT/JSON snapshot of text sent)
* `sent_timestamp_utc`
* `telegram_message_id_sent`
* `delivery_status ("SENT","FAILED","RETRYING")`
* `retry_count (INTEGER)`

### bookmaker_balance_checks

* `id (PK)`
* `bookmaker_id (FK)`
* `associate_id (FK)`
* `reported_amount_native` (TEXT Decimal; exact number they say is in the bookmaker app)
* `native_currency` (TEXT)
* `reported_at_utc` (UTC ISO8601 "Z")
* `noted_by ("local_user")`
* `note` (optional)
* `telegram_message_id` (optional)

Purpose:

* Store what they *claim* is in the bookmaker at that timestamp.
* This does NOT auto-change balances.
* You decide whether to post a BOOKMAKER_CORRECTION based on these.

### fx_rates_daily

* `id (PK)`
* `currency_code` ("AUD","GBP","EUR",...)
* `rate_to_eur` (TEXT Decimal; how many EUR per 1 unit of this currency)
* `fetched_at_utc`
* `source` (TEXT)
* `created_at_utc`

When we create a ledger row (settlement, deposit acceptance, withdrawal acceptance, correction), we stamp the latest known rate for that currency into that row’s `fx_rate_snapshot`.

If there's no fresh rate today, reuse the most recent known.
All math internally is in EUR. We never try to “re-FX” the past.

---

## 10. Monthly Statements / Partner Statements (Page 5)

Goal: generate a per-associate summary you can screenshot and send at period end (e.g. "End of October 2025").

For each associate at that cutoff timestamp:

1. **NET_DEPOSITS_EUR**
   = (Sum of DEPOSIT.amount_eur) - (Sum of WITHDRAWAL.amount_eur) up to cutoff
   “How much cash you personally put in.”

2. **SHOULD_HOLD_EUR**
   = SUM(principal_returned_eur + per_surebet_share_eur) across all their BET_RESULT rows up to cutoff
   “If we froze time right now after all settled bets, this much of the pot is yours.”

3. **RAW_PROFIT_EUR**
   = SHOULD_HOLD_EUR − NET_DEPOSITS_EUR
   “How far ahead you are compared to what you funded.”
   Can be positive or negative. Negative is allowed. You and them split that 50/50 either way — you also eat losses.

**How you present it to them (what you’d actually DM):**

* “You funded €X total.”
* “Right now you’re entitled to €Y.”
* “That means you’re up €Z overall.”
* “Our deal is 50/50, so €Z/2 each.”

Internal-only (visible to you, optional to show them):

* `CURRENT_HOLDING_EUR` = what they’re modeled to be physically holding right now across their bookmakers.
* `DELTA = CURRENT_HOLDING_EUR − SHOULD_HOLD_EUR`

  * `DELTA > 0` ⇒ they’re sitting on extra group float.
  * `DELTA < 0` ⇒ they’re short / someone else is effectively holding their money.

Monthly Statements:

* does NOT change entitlement math,
* does NOT write ledger rows,
* is just presentation in human language.

---

## 11. Technical stack requirements

* Python 3.12
* Streamlit for UI
* `python-telegram-bot` v20+ in polling mode
* SQLite in WAL mode
* All currency math in `Decimal` stored as TEXT
* All timestamps stored as UTC ISO8601 with "Z"
* Local screenshots under `data/screenshots/`
* Append-only ledger (System Law #1)

FX handling:

* We only need one FX rate per currency per day.
* If we don't have a fresh rate that day, reuse the last known.
* All EUR math is one-way (native → EUR at snapshot time). We never “revalue” old rows.

---

## 12. Definition of done

The MVP is complete when ALL of this works locally:

1. Telegram bot ingestion of screenshots and (optionally) deposit/withdraw intent messages.
2. **Manual Upload panel** on Incoming Bets:

   * Upload screenshot from outside Telegram.
   * Select associate + bookmaker.
   * Run OCR.
   * Store as `ingestion_source="manual_upload"`.
   * Show that bet in the same Incoming Bets queue.
3. Incoming Bets review with manual correction.
4. Deterministic surebet grouping with strict match on
   (`canonical_event_id`, `market_code`, `period_scope`, `line_value`, and opposite `side`).
5. ROI-based surebet safety labels (✅ / 🟡 / ❌).
6. Manual “Send coverage proof”, logged in `multibook_message_log`.
7. Settlement sorted by `kickoff_time_utc`, including:

   * WON / LOST / VOID overrides
   * equal-split math with admin seat logic
   * all-VOID still generating BET_RESULT rows
   * single-click confirm producing ledger rows with a shared `settlement_batch_id`
   * confirm modal (“This action is permanent.”)
8. Append-only ledger with frozen `fx_rate_snapshot`.
9. Reconciliation / Health Check page showing:

   * NET_DEPOSITS_EUR
   * CURRENT_HOLDING_EUR
   * SHOULD_HOLD_EUR
   * DELTA with color and explanation
   * Pending DEPOSIT/WITHDRAWAL drafts to Accept/Reject (or manual add)
   * Per-bookmaker modeled vs reported balance with “Apply correction” (BOOKMAKER_CORRECTION)
10. CSV export of the full ledger.
11. Monthly Statements page that can generate partner-facing summaries per associate using:

    * NET_DEPOSITS_EUR
    * SHOULD_HOLD_EUR
    * RAW_PROFIT_EUR
    * and a simple 50/50 explanation, including negative cases.

---

## 13. One-sentence summary

This local tool ingests Telegram screenshots (and also lets you upload off-Telegram screenshots), normalizes bets with GPT-4o, lets you approve and correct them in one queue, groups opposite sides of two-way markets into deterministic surebets, checks each surebet’s worst-case EUR ROI, forwards coverage proof screenshots on demand, settles matches in kickoff order with one confirm (including VOID handling and the admin’s equal-split seat, even if the admin didn’t stake), writes every cent into an append-only ledger with frozen FX, shows who is overholding or short across the group, and can generate monthly partner statements that say in plain language: “you put in X, you’re entitled to Y, so your net P&L is Z — we split Z 50/50.”
