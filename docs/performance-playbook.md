# UI Performance Playbook

**Last Updated:** 2025-11-07  
**Owner:** Admin & Associates team

---

## Objectives

- Keep **page load times under 2 seconds** for primary workflows.
- Apply filters on datasets up to **10k records in ≤ 1.5 seconds**.
- Maintain **cache hit rate ≥ 80%** for read-heavy queries.
- Ensure **indexed queries cover ≥ 95%** of filtered lookups.

---

## Instrumentation

- Wrap expensive render paths with `track_timing("fragment_name")`.
- Review the new Performance Dashboard under **Admin → Advanced** to inspect the last 50 samples.
- Clear timing samples after a tuning session to measure improvements in isolation.

---

## Playbook

1. **Profile**
   - Enable the Performance Debug toggle.
   - Trigger the slow interaction three times to collect timing samples.
   - Capture metrics + screenshots in the dashboard before making changes.

2. **Diagnose**
   - Inspect SQL via `EXPLAIN QUERY PLAN` (use the migration notebook or `sqlite3` CLI).
   - Verify pagination is using `LIMIT/OFFSET` with the expected indexes.
   - Confirm thumbnails and large assets are served via `render_thumbnail`.

3. **Optimize**
   - Add or adjust indexes (see `scripts/migrations/idx_performance.sql`).
   - Extend caching windows via `query_df(... ttl=...)` only if data freshness allows.
   - Split heavy sections into fragments and gate auto-refresh to reduce reruns.

4. **Verify**
   - Re-run the same interaction three times, collect fresh timings, and compare to the baseline.
   - Run `pytest -k performance` to exercise the synthetic benchmarks.
   - Update this document with the action taken and the resulting metrics.

---

## Benchmark Results (Synthetic 10k Dataset)

Latest automated run (`scripts/benchmark_10k_bets.py`, seeded 10,000 rows):

| Scenario | Target | Result |
| --- | --- | --- |
| Filter 10k bets (cached) | ≤ 1.5s | **0.18s** |
| Paginate 5 windows (100 rows each) | ≤ 0.5s | **0.32s** |

Tests: `tests/performance/test_benchmark_10k_bets.py`

---

## Monitoring & Alerts

- All `track_timing()` calls automatically compare durations against the `PERFORMANCE_BUDGETS` map defined in `src/ui/utils/performance.py`.
- When a fragment exceeds its budget, an alert is pushed into session state and rendered inside the Admin ➜ Advanced ➜ Performance Dashboard.
- Use the **Clear Timing Samples** button in the dashboard to reset both metrics and alerts before a new tuning session.
- Regression guardrails: `tests/performance/test_performance_regression.py` verifies alert collection + reset, while `tests/unit/test_performance_utils.py` covers the lower-level primitives.

---

## Quick Remediation Checklist

- [ ] Queries run through `query_df` and share the cached connection.
- [ ] Pagination uses the shared helper with 25/50/100 row options.
- [ ] All screenshot previews rely on `render_thumbnail` for lightweight rendering.
- [ ] Auto-refresh guarded behind fragment support to avoid redundant reruns.
- [ ] Performance Dashboard shows target metrics in the green zone.

---

For deeper dives, coordinate with the infra channel or file a **Perf Ops** ticket template. Continuous tuning keeps the operator console feeling instant even as datasets grow.
