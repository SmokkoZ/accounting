# Epic 9: Telegram Bot Funding & Balance Statements

**Status:** Not Started
**Priority:** P1 (High Value Ops UX)
**Estimated Duration:** 2–3 days
**Owner:** Product Owner (Sarah)
**Phase:** 2 (Operations Enhancements)
**PRD Reference:** FR-12 (Bot Operations & Messaging)

---

## Epic Goal

Enable associates and admins to manage funding operations directly from Telegram chats and provide automated balance statements per bookmaker chat, with safe rate‑limited global distribution.

---

## Business Value

- Faster funding operations: simple "deposit 500" / "withdraw 500" from chat
- Lower operator overhead: associates self‑serve; admin approves in Streamlit
- Fewer errors: chat↔bookmaker linkage removes the need to specify bookmaker
- Transparency: one‑tap balance and pending status to partners
- Scalable daily comms: global statements to all chats with safe throttling

**Success Metrics**
- >90% of funding ops initiated via Telegram within 2 weeks
- <2 minutes median approval time for associate‑initiated funding
- <1% failed or retried messages when sending daily statements

---

## Epic Description

### Context

- Chat registrations link Telegram `chat_id` → `(associate_id, bookmaker_id)` (see `chat_registrations` table in `src/core/schema.py:691`).
- Funding drafts and approvals exist in Streamlit (Story 5.4) via `FundingService` (associate‑level by design; `bookmaker_id=None`).
- Balance history exists via `bookmaker_balance_checks` and UI (Story 7.3).

### What's Being Built

1) Telegram funding commands (per registered chat/bookmaker):
   - Text messages: "deposit 500" or "withdraw 500" (decimals allowed)
   - If sender is admin (admin chat or admin user): auto‑approve → create ledger entry immediately (type `DEPOSIT`/`WITHDRAWAL`) with `bookmaker_id` from chat registration and native currency equal to associate's `home_currency`.
   - If sender is associate: create a "funding draft" tied to `(associate_id, bookmaker_id)` → appears in Streamlit for approval.

2) Streamlit approvals (funding drafts panel):
   - List pending drafts originating from Telegram with details: associate alias, bookmaker, amount, currency, note, created time, source chat.
   - Actions: Accept (writes `ledger_entries`) or Reject (discard).
   - On Accept: optional confirmation message to the originating Telegram chat.

3) Balance statement messaging:
   - Streamlit button: "Send Balance to This Chat" on a bookmaker context sends: "DD/MM/YY Balance: {latest_balance_native} {CUR}, pending balance: {pending_native} {CUR}."
   - Pending balance definition: sum of stake amounts on bets for `(associate_id, bookmaker_id)` with status in {`verified`, `matched`} (not `settled`, not `incoming`). Display in associate's `home_currency`.
   - Balance source: latest row from `bookmaker_balance_checks` for `(associate_id, bookmaker_id)`; if none exists, show "Balance: N/A" and send only pending.

4) Global daily statement:
   - Streamlit button: "Send Daily Statements to All Chats" iterates every active registration and sends the same balance/pending message to its chat.
   - Uses rate‑limited async sending with retry/backoff on HTTP 429 (Telegram).

### Data & Services

- New: extend funding workflows to be bookmaker‑aware when source is Telegram chat.
- New: persist funding drafts to DB (recommended) to survive app restarts: `funding_drafts(id, chat_id, associate_id, bookmaker_id, type, amount_native, native_currency, note, created_at_utc, source='telegram')`.
- Reuse: `ledger_entries` for final approved writes; `fx_rates_daily` for EUR conversion snapshots; `bookmaker_balance_checks` and `bets` for statement values.

### Key Design Decisions

1. Bookmaker‑scoped funding via chat registrations; admin auto‑approve, associate requires approval.
2. Currency = associate `home_currency`; no bookmaker argument needed in chat.
3. Pending balance excludes `incoming` bets; includes `verified` and `matched` only.
4. Messaging observability: log message id, errors, and retry decisions per chat.
5. Rate limiting: token‑bucket style with per‑chat throttle and global cap; honor `retry_after` on 429.

---

## Stories

- Story 9.1: Telegram Funding Commands (Deposit/Withdraw)
- Story 9.2: Streamlit Funding Approvals (Telegram Drafts)
- Story 9.3: Per‑Chat Balance & Pending Message Button
- Story 9.4: Global Daily Statements (All Chats)
- Story 9.5: Telegram Rate‑Limiting & Delivery Reliability
- Story 9.6: Telegram Confirm Before Ingest

See `docs/stories/9.1.telegram-funding-commands.md` through `9.6.telegram-confirm-before-ingest.md`.

---

## Non‑Functional Requirements

- Safety: never edit past ledger rows (append‑only)
- Idempotency: avoid double‑posting messages and double‑accepting drafts
- Reliability: queue + retry with exponential backoff; drop‑safe on restart
- Performance: global daily run finishes in <2 minutes for 750 chats
- Observability: structured logs with chat_id, associate_alias, bookmaker_name

---

## Risks & Mitigations

- Parsing free‑text amounts → restrict to simple patterns ("deposit 500", "withdraw 250.75"); reply with guidance on invalid input.
- Missing balance checks → still send pending only; prompt admin to record balances.
- Telegram rate limits → conservative global cap; handle 429 `retry_after` gracefully; per‑chat throttle to 1 msg/sec.
- Duplicate drafts → dedupe by (chat_id, amount, type, created_at±30s) if needed.

---

## Dependencies

- `chat_registrations` mapping exists (schema ok)
- Extend `FundingService` (or add `BookmakerFundingService`) for bookmaker‑scoped drafts/entries
- Streamlit admin pages to expose approvals and send buttons
- Telegram bot integration for text handlers and message sending utilities

---

## Out of Scope

- Automatic bookmaker scraping for balances
- Multi‑currency per bookmaker (currency comes from associate)

---

**End of Epic 9**
