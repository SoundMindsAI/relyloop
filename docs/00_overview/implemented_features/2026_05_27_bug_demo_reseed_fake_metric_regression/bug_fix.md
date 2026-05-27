# Bug fix — home-page reseed button writes hardcoded fake metric

**Date:** 2026-05-27
**Status:** Complete (PR #286, merged 2026-05-27 as squash `5a90f82`)
**Branch:** `bug/demo-reseed-fake-metric-regression` (deleted post-merge)

## Problem

The "Reset to demo state" button on the home dashboard
([`ui/src/components/dashboard/reset-demo-state-button.tsx:48`](../../../../ui/src/components/dashboard/reset-demo-state-button.tsx)) POSTs to `/api/v1/_test/demo/reseed`. That handler calls `reseed_demo_state()` at [`backend/app/services/demo_seeding.py:281`](../../../../backend/app/services/demo_seeding.py), whose step 2h at line 494 calls `POST /api/v1/_test/studies/seed-completed` — a test-only shortcut that **hardcodes `primary_metric=0.487` and `best_metric=0.487`** ([`backend/app/services/test_seeding.py:127, 155`](../../../../backend/app/services/test_seeding.py)) for every scenario.

User reproduction (2026-05-27): clicked the button, observed all 4 seeded studies showing `best_metric=0.487` to 3 decimals — the signature of the test-seed shortcut.

The CLI script (`make seed-demo`, [`scripts/seed_meaningful_demos.py:697`](../../../../scripts/seed_meaningful_demos.py)) was rewritten in an earlier PR to skip the test-seed shortcut and instead POST a real study that the Arq worker runs to completion — producing **real per-scenario metrics** from real trials against the seeded ES corpus. The button's service path never got the same treatment, so the reseed regressed back to fake data the moment the operator used it.

## Repro

1. `make up` against a clean stack.
2. Click "Reset to demo state" on `/` (home dashboard).
3. Wait ~10s for the synchronous response.
4. Navigate to `/studies`.
5. Observe: every study row shows `best_metric=0.487`. Click any study; the digest narrative is identical across all 4.

Expected: each of the 4 scenarios produces a distinct `best_metric` reflecting its actual Optuna TPE search against its judgments, and each digest narrative reflects its real metric delta.

## Root cause

Bifurcated demo-seed code paths:

- **CLI** (`scripts/seed_meaningful_demos.py:697-866`) — real study create + 12-trial Arq run + LLM digest. Real metrics.
- **Button** (`backend/app/services/demo_seeding.py:494-506`) — calls `_test/studies/seed-completed`, which inserts pre-canned rows including the 0.487 metric. Fake metrics.

The two paths diverged in PR #281 (the CLI side moved to real studies) without a matching update to `demo_seeding.py`. The button's hardcoded path is the unchanged-since-PR-#228 implementation.

## Fix design

### Why not a one-liner

The button currently returns synchronously in ~10s because the fake-seed path is fast. Switching to the real-study path means:

- 4 scenarios × 12 trials × ~2-5s each = **30-90s per scenario**, ~2-6 minutes total wall-clock.
- The button's existing 180s client-side abort would frequently timeout.
- Even if extended, holding a single HTTP connection open for 6 minutes is brittle (proxy timeouts, browser refresh, etc.).
- The Postgres advisory lock held for the duration would lock the demo subsystem for that long.

The right move is to convert the endpoint to an **async enqueue + status-poll** pattern, matching the existing convention from judgment generation (`backend/app/services/agent_judgments_dispatch.py:215`) and PR opening (`backend/app/services/agent_proposals_dispatch.py:141`).

### Locked design forks

These are decisions that future agents shouldn't have to relitigate:

**D-1. Status persistence: Redis key, not a new `demo_reseed_runs` table.**
Reseed is a singleton operation (enforced by the existing Postgres advisory lock). No history is meaningful — only the *current* run's status matters. A `demo_reseed_runs` table would be overkill: 1 row per reseed, no joins, no queries against history. Redis fits: TTL clears stale failures, single key per status, matches the existing advisory-lock-via-Postgres pattern (the lock prevents concurrent reseeds; the status key prevents concurrent polls from observing stale data).

**D-2. Status key shape.** Single Redis key `demo_reseed:status` with JSON value:

```json
{
  "status": "running" | "complete" | "failed",
  "started_at": "2026-05-27T16:50:00Z",
  "finished_at": null | "2026-05-27T16:53:42Z",
  "scenarios_total": 4,
  "scenarios_completed": 2,
  "current_step": "seeding acme-products-prod (trial 7/12)",
  "failed_reason": null | "string",
  "summary": null | { ReseedSummary shape on completion }
}
```

TTL: 1 hour. The next reseed overwrites the key — no historical accumulation.

**D-3. Arq job key.** `demo_reseed:<started_at_iso>` — deterministic so the same operator clicking twice in 100ms can't double-enqueue. The advisory lock is the ultimate dedup; the deterministic job key is belt-and-suspenders.

**D-4. POST contract.** Currently `200 OK` + `ReseedSummary` (sync). New: `202 Accepted` + `ReseedStatusResponse` with `status="running"` + initial counters. The frontend's `apiClient` already treats 202 as success.

**D-5. GET status endpoint.** `GET /api/v1/_test/demo/reseed/status` — returns `ReseedStatusResponse`. When the Redis key is absent (no reseed has ever run, or the TTL expired post-completion), returns `{status: "idle"}` rather than 404. This makes frontend polling trivially safe.

**D-6. Real-study seeding code path.** The CLI's logic at `scripts/seed_meaningful_demos.py:766-866` is factored into a new helper `seed_one_scenario(scenario, api_client, status_callback)` in `backend/app/services/demo_seeding.py`. The CLI is updated to call this helper too, eliminating drift. Status callback fires after each scenario phase so Redis status stays current.

**D-7. Worker timeout.** The Arq job gets a hard timeout of 600s (10 min). If trials don't complete in that window, the job marks status `failed` with `failed_reason="worker timeout"` and releases the advisory lock.

**D-8. Frontend polling.** TanStack Query with `refetchInterval` callback returning `2_000` (2s) while `status === "running"` and `false` otherwise. Matches the proposal-PR-open polling pattern at `ui/src/app/proposals/[id]/page.tsx:460`.

**D-9. Polling endpoint authentication.** Inherits `_require_development_env` from the existing reseed endpoint — same dev-only gate, no separate auth.

**D-10. Stop-existing-button-trail.** The existing button's 180s client-side abort goes away — POST returns immediately so there's nothing to abort. The dialog stays open with a progress indicator until the polled status flips to `complete` or `failed`.

### Implementation slice

1. **Bug folder + design doc** (this file) — done.
2. **Backend: extract `seed_one_scenario_real_study()` helper** out of `scripts/seed_meaningful_demos.py:697-866` into `backend/app/services/demo_seeding.py`. Accepts `(scenario, api_client, status_callback)`. CLI updated to import + call it.
3. **Backend: Redis status helpers** in `backend/app/services/demo_seeding.py`: `_status_set(redis, payload)` and `_status_get(redis) -> ReseedStatusResponse | None`.
4. **Backend: Arq job** `run_demo_reseed_job` in `backend/workers/demo_reseed.py` (new module). Acquires the advisory lock, calls `reseed_demo_state()` with the real-study helper, writes status throughout.
5. **Backend: route handler changes** — `POST /api/v1/_test/demo/reseed` now enqueues + returns 202. New `GET /api/v1/_test/demo/reseed/status` returns the Redis-backed status.
6. **Backend: tests** — unit for helpers, integration for the full flow (the existing flow tests at `backend/tests/integration/test_demo_reseed*.py` need updating).
7. **Frontend: hook + button rewrite** — `useDemoReseedStatus` polling hook + reset-demo-state-button consumes it for progress display.
8. **Frontend: tests** — vitest cases for the polling state machine.
9. **Regression test** — explicit assertion that `best_metric` differs across scenarios after a reseed (catches the bug in CI forever).

### Regression test

The pivotal test that codifies this bug's signature, in `backend/tests/integration/test_demo_reseed_real_studies.py`:

```python
async def test_reseed_produces_distinct_per_scenario_best_metrics(
    async_client: httpx.AsyncClient,
) -> None:
    """Hardcoded 0.487 across all 4 scenarios is the bug signature this fixes."""
    resp = await async_client.post("/api/v1/_test/demo/reseed")
    assert resp.status_code == 202
    # Poll until complete (or 5-min ceiling).
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        status = (await async_client.get("/api/v1/_test/demo/reseed/status")).json()
        if status["status"] in ("complete", "failed"):
            break
        await asyncio.sleep(2)
    assert status["status"] == "complete", status
    # The bug signature: all 4 studies sharing best_metric=0.487.
    studies = (await async_client.get("/api/v1/studies?limit=10")).json()["data"]
    metrics = {round(s["best_metric"], 3) for s in studies if s["best_metric"] is not None}
    assert len(metrics) >= 3, (
        f"All 4 demo studies share best_metric={metrics} — the fake-seed regression "
        f"this bug fixes. Each scenario must produce a distinct metric from its own "
        f"real Optuna trials."
    )
    assert 0.487 not in metrics or len(metrics) >= 2, (
        f"The historical hardcoded 0.487 must not be the only metric across scenarios."
    )
```

## Rollout

- This is a dev-only endpoint (`_require_development_env`) — no staging / production blast radius.
- The migration: zero — Redis key + new worker module + endpoint additions, no schema change.
- Existing operators on `main` are running the fake-data button until this lands. Once merged, the next "Reset to demo state" click will block ~3-6 min waiting for real trials — a worse UX moment than today, but the resulting data is real.

## Why not a workaround

The user wanted the right fix (option 2 from the design discussion). Option 1 was "synchronous wait + bumped timeout" which would have kept the bug pattern (same data path) and just hidden the UX cliff. Option 3 was "ship the bug folder, fix later" — but the operator hit this in their working state and wants the data, not a TODO.
