# `seed_meaningful_demos.py` silently swallows ES bulk-index errors

**Date:** 2026-05-28
**Status:** Idea — captured during `bug_smoke_seed_es_unavailable_shards_race` Phase 2.5 tangential sweep
**Priority:** P2 — latent. Affects operators running `make seed-demo` locally; same `unavailable_shards_exception` race that broke CI's `seed-es` step will silently corrupt the seeded demo data here, with no logs and no exit-code signal.
**Origin:** Surfaced while tracing the bulk-error handling in `seed_es.py`. The sibling script `scripts/seed_meaningful_demos.py` has its OWN bulk-index loop using `urllib.request` (not httpx) that never inspects the response body — fundamentally the same write-allocation race exposed in [bug_smoke_seed_es_unavailable_shards_race](../../../implemented_features/2026_05_29_bug_smoke_seed_es_unavailable_shards_race/idea.md), but unguarded.
**Depends on:** None.

> **PREFLIGHT (2026-06-05) — stale citations corrected; design locked.** Live audit:
> - **Line drift:** the bulk loop is at `scripts/seed_meaningful_demos.py` **~2549-2571** (`seed_rich_scenario`), not 917-935 (that range is now news-scenario doc fixtures).
> - **Sibling moved:** the retry reference is `backend/app/scripts/seed_es.py` (`_bulk_with_retry`/`_first_bulk_error`/`BULK_RETRY_ATTEMPTS`), NOT a top-level `scripts/seed_es.py` (which doesn't exist). It uses **httpx**; this script uses **urllib** — so the shared-helper "bonus" is rejected (see below).
> - **Decisions locked:** Option A (parse + retry) over B; **standalone urllib helper** (no `scripts/_es_bulk.py` extraction — the two scripts use different HTTP libs and `backend` already imports `SCENARIOS` *from* this script, so importing backend here risks a cycle); injectable `send`/`sleep` for unit-testability. Full rationale in [bug_fix.md](./bug_fix.md).
> - **Verifiability:** `scripts.seed_meaningful_demos` is importable in tests (demo_seeding + `test_scenarios_ubi_config.py` already import it), so the new unit test runs offline via `.venv/bin/pytest`.

## Problem

[`scripts/seed_meaningful_demos.py` ~2549-2571](../../../../../scripts/seed_meaningful_demos.py) bulk-indexes 1000 Amazon ESCI products into a dedicated index per demo scenario:

```python
with urllib.request.urlopen(req, timeout=60) as resp:
    resp.read()  # ← response body is read then discarded
```

ES bulk semantics return HTTP 200 even when the primary shard is INITIALIZING — the error lives in the JSON body. `seed_meaningful_demos.py` doesn't parse the body, so:

- `unavailable_shards_exception` on cold ES → silently produces a partial / empty index for that scenario.
- Mapping bugs → silently produces a partial index too.
- `_refresh` call still succeeds (no-op on empty index), so downstream operator perception is "demo seeded successfully."

Net: operators running `make seed-demo` get incomplete demo data with no signal. Studies created against the demo cluster will return zero results or fewer-than-expected hits, looking like a configuration problem.

**Why latent now:** [`chore_drop_demo_seed_from_ci`](../../../implemented_features/2026_05_28_chore_drop_demo_seed_from_ci/idea.md) removed `make seed-demo FORCE=1` from `pr.yml`, so CI doesn't exercise this path. Local-dev operators still hit it via the home page's "Reset to demo state" button + the `chore_tutorial_polish` walkthrough.

## Proposed capabilities

Two options:

### Option A — Apply the same retry pattern as `seed_es.py` (recommended)

Mirror the fix landed in `bug_smoke_seed_es_unavailable_shards_race`:
1. Read the bulk response body, parse JSON
2. If `payload["errors"]` is True, inspect `first_error["type"]`
3. Retry on `unavailable_shards_exception` only — 3 attempts × 2s
4. Fail loudly with logger.error on other errors or exhausted retries

Bonus: extract `_bulk_with_retry` into a shared `scripts/_es_bulk.py` so both scripts use the same helper. This is the "share the helper" follow-up the bug_smoke_seed_es_unavailable_shards_race bug_fix.md called out but deferred.

### Option B — Bare minimum: parse + fail-loud, no retry

Just check `payload.get("errors")` and exit non-zero with a clear message. Doesn't fix the cold-start race, but at least operators see the failure.

## Scope signals

- **Backend:** ~30 LOC if Option A standalone; ~50 LOC if A + shared helper extraction (touches both scripts).
- **Frontend:** N/A.
- **Migration:** N/A.
- **Config:** N/A.
- **Tests:** ~5 unit tests parallel to the ones in `backend/tests/unit/scripts/test_seed_es_retry.py`.

## Relationship to other work

- **Mirror of [`bug_smoke_seed_es_unavailable_shards_race`](../../../implemented_features/2026_05_29_bug_smoke_seed_es_unavailable_shards_race/idea.md)** — same root cause, different script, different HTTP library. Pick this up after the sibling bug ships so the retry pattern is established.
- **Composes with the "extract `_bulk_with_retry` to shared module" refactor** the bug_smoke fix noted but deferred — best to land both together.
- **Surfaces on `make seed-demo` only.** Not a CI blocker; affects local operator first-impression quality.
