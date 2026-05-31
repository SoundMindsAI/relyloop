# bug: `make seed-demo FORCE=1` — 3 scenarios fail with UBI_INSUFFICIENT_DATA

**Type:** bug
**Priority:** P2 (demo-only; does not affect the product/adapter code paths)
**Re-verify (2026-05-31):** the **async** home-button reseed (`demo_seeding.py`, the UI path) now completes **6/6 incl. UBI judgment generation on all scenarios** after `feat_demo_reseed_solr_and_steplog` (PR #348). This bug is about the **sync CLI** path (`make seed-demo FORCE=1` → `seed_meaningful_demos.py`) + the synthetic-event-count vs readiness-threshold, which #348 did not directly touch — but re-run the sync CLI to confirm the symptom persists before scoping; it may now be stale/resolved. Moved from `00_unsure/` to `02_mvp2/` 2026-05-31.
**Origin:** Surfaced during the infra_adapter_solr rework (2026-05-30), Phase 8, while
running `make seed-demo FORCE=1` to investigate pre-existing UBI demo failures.
**NOT caused by the Solr adapter** — the failing scenarios are all
Elasticsearch/OpenSearch, on code paths the Solr PR never touched.

## Symptom

`make seed-demo FORCE=1` exits non-zero with:

```
=== 3 scenario(s) FAILED — demo is incomplete ===
  acme-products-prod:    RuntimeError('ubi_judgments/acme-products-prod: failed (UBI_INSUFFICIENT_DATA)')
  corp-docs-search:      HTTPError 422: UBI_INSUFFICIENT_DATA
  jobs-marketplace-prod: RuntimeError('ubi_judgments/jobs-marketplace-prod: failed (UBI_INSUFFICIENT_DATA)')
```

The 2 non-UBI scenarios (news-search-staging, acme-products-rich-prod) complete fine.

## Root cause(s) — two distinct failure modes

### Mode A — `corp-docs-search` (synchronous 422): rung_1 undershoots the converter floor

- The scenario is configured `ubi_target_rung="rung_1"` + `converter="hybrid_ubi_llm"`
  ([scripts/seed_meaningful_demos.py:397-400](../../../../scripts/seed_meaningful_demos.py)).
- `RUNG_EVENT_COUNTS["rung_1"] = 50`
  ([backend/app/domain/demo/synthetic_ubi.py:43-58](../../../../backend/app/domain/demo/synthetic_ubi.py)).
- The generate-from-ubi sync gate requires **100** events in the window
  (observed in the 422 body: *"only 50 UBI events match the window … (required: 100)"*;
  threshold lives in [backend/app/services/agent_judgments_dispatch.py](../../../../backend/app/services/agent_judgments_dispatch.py) / `ubi_readiness.py`).
- 50 < 100 → **deterministic** failure, every run. This is a scenario-vs-threshold
  misconfiguration: a rung_1 (intentionally sparse, 50-event) scenario can never
  satisfy a 100-event converter floor.

### Mode B — `acme-products-prod` (rung_3, 528 events) + `jobs-marketplace-prod` (rung_2, 240 events): worker-side failure despite ample events

- Both have event counts well above 100 (528 and 240) yet fail with
  `UBI_INSUFFICIENT_DATA` raised by the **worker** after dispatch + polling
  ([backend/workers/judgments_ubi.py:406](../../../../backend/workers/judgments_ubi.py)),
  not the sync gate.
- The dispatch window is the **last 60 seconds**: `since = seed_anchor_iso - 60s`,
  `until = seed_anchor_iso` ([scripts/seed_meaningful_demos.py:1052-1053](../../../../scripts/seed_meaningful_demos.py)),
  where `seed_anchor_iso = datetime.now(UTC)` ([:912](../../../../scripts/seed_meaningful_demos.py)).
- **A window-mismatch hypothesis is ruled out:** `synthetic_ubi.py` pins the
  invariant *"All event timestamps fall inside `[seed_anchor − 60s, seed_anchor]`"*
  ([backend/app/domain/demo/synthetic_ubi.py:22](../../../../backend/app/domain/demo/synthetic_ubi.py)),
  and the demo passes the **same** `seed_anchor_iso` to both the fabricator and
  the dispatch window. So the events ARE inside the dispatched window — the 60s
  window is NOT the cause.
- The events also clear the **sync** count gate (rung_2 = 240, rung_3 ≈ 528/640;
  both > the 100 floor) — the sync gate passed; the failure is raised later by the
  **worker** ([backend/workers/judgments_ubi.py:406](../../../../backend/workers/judgments_ubi.py)).
- **Open question (genuinely needs investigation):** why does the worker's
  post-dispatch read see < threshold despite ≥240 in-window events? Candidates to
  check: (a) the converter's per-(query,doc) aggregation collapses 240 raw events
  into < threshold *rated pairs*; (b) a count-semantics mismatch between the sync
  gate (counts raw events) and the worker/`UbiReader` (counts something narrower —
  e.g. impressions-only, or distinct query-doc pairs); (c) a `mapping_strategy=reject`
  interaction. The fix must start by logging what the worker actually counts vs the
  240/528 written.

## Why deferred (not fixed in the Solr PR)

- Different subsystem: demo seeding + synthetic-UBI fabrication + the UBI worker —
  files the Solr adapter PR never touched. Mixing this fix into the Solr PR would
  break reviewability.
- Mode B needs investigation (confirm the timestamp-spread vs window mismatch) +
  regression tests at the domain (synthetic_ubi span) and integration (worker
  window) layers — > 60 min, cross-subsystem. Per CLAUDE.md's implement-vs-defer
  rubric this is a genuine idea-file case.

## Suggested fix (for the follow-up PR)

1. **Mode A:** either bump `corp-docs-search` to a rung that clears the 100-event
   floor, or lower the converter floor for the demo, or make the demo's
   `hybrid_ubi_llm` dispatch tolerate sparse UBI (it's *supposed* to — hybrid =
   "UBI rates the dense head, LLM fills the tail"; a sparse-UBI 422 may itself be
   a product bug worth checking against the hybrid converter's intent).
2. **Mode B:** widen the dispatch window in `seed_meaningful_demos.py` (e.g. ±1 day
   around `seed_anchor_iso`) OR pin `fabricate_ubi_for_scenario` to emit all event
   timestamps inside the dispatch window. Confirm by printing the min/max event
   timestamp vs the `since`/`until` the dispatch sends.
3. Add a guard test asserting every UBI-enabled demo scenario's `RUNG_EVENT_COUNTS`
   value ≥ the converter floor it dispatches against, so Mode A can't regress.

## Repro

```
make seed-demo FORCE=1     # exits 2; 3 scenarios fail as above
```
Full captured output was at /tmp/seeddemo.txt during the 2026-05-30 session.
