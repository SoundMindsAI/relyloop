# Preflight probe — check judgment doc-ID overlap with target before enqueueing the orchestrator

**Date:** 2026-05-21
**Status:** Idea — surfaced post-merge of `feat_pr_metric_confidence` as the defense-in-depth tier behind the target-mismatch guard
**Priority:** P1 — second tier of fail-fast, hardens residual cases the target-mismatch guard can't catch (re-indexed corpus, stale judgments). Ready when P0 clears.
**Origin:** Same operator session as [`feat_study_target_judgment_mismatch_guard`](../feat_study_target_judgment_mismatch_guard/idea.md). The deterministic target-name check catches the most common pathology (judgment list authored against a different index), but it doesn't catch the case where the judgment list's nominal `target` matches the study's `target` yet the doc IDs in the judgments are entirely disjoint from what the index can return. That happens after re-indexing with new doc IDs, after a `_reindex` with a transform, or whenever the operator regenerates an index without bumping its name.
**Depends on:** [`feat_study_target_judgment_mismatch_guard`](../feat_study_target_judgment_mismatch_guard/idea.md) (this is the layer behind it).

## Problem

The target-mismatch guard catches a string-equality mismatch. It misses these legitimate-looking-but-still-broken cases:

1. **Same target, re-indexed corpus.** Operator regenerates `docs-articles` via `_reindex` with new doc IDs. The old judgments still reference the old doc IDs. Top-K results from the index now don't intersect the judgments → NDCG=0 regardless of params.
2. **Same target, judgments authored on a stale sample.** A judgment list was generated against an index snapshot; the index has since rotated. The current state returns new doc IDs the judgments don't cover.
3. **Same target, but the queries themselves are wrong.** Operator copied an `e2e-*` query set whose strings ("e2e query 0") don't appear anywhere in the corpus. Index returns 0 hits for every query → NDCG=0.

All three look fine at create time: `judgment_list.target == study.target`, `judgment_count > 0`, `query_count > 0`. The orchestrator runs N trials, all score 0, and the operator burns budget on a study that couldn't possibly produce signal.

## Proposed capabilities

### Preflight probe at POST /studies

After the create-study validators pass, before staging the study row + enqueueing `start_study`:

1. Pick a representative query from the query set (the first query by `id` ascending **that has at least one judgment in the list** — deterministic + cheap, and avoids false-negative-overlap when query 0 happens to be unjudged). Implementation: a single `SELECT q.id, q.query_text FROM queries q JOIN judgments j ON j.query_id = q.id WHERE q.query_set_id = ? AND j.judgment_list_id = ? ORDER BY q.id ASC LIMIT 1`.
2. Use the cluster's `SearchAdapter` to render the query template + execute a single search at `top_k = min(50, max_judgments_per_qid * 5)`.
3. Pull all `judgments.doc_id` rows for that qid in the judgment list.
4. Compute the intersection between the returned doc IDs and the judged doc IDs.

Decision matrix:

| Intersection size | Action |
|---|---|
| 0 | **Reject** with `INSUFFICIENT_JUDGMENT_OVERLAP` (422). The study cannot produce signal — every trial will score 0. |
| 1-2 | **Warn** but allow. Surface as a `metric_delta_warning` field on the response so the UI can render a banner. May produce signal but the operator should regenerate judgments. |
| 3+ | **Allow.** Sufficient overlap; let the trials run. |

The probe runs in ~50ms (one search round-trip + one bounded JOIN against `judgments`). It's not on the hot path; only on study create. Cluster unreachable → fall through with a `WARN` log (don't block creation when the cluster's flaky — the orchestrator will surface that error per trial anyway).

### Spec / error code registration

New error code `INSUFFICIENT_JUDGMENT_OVERLAP` in the canonical list. Tooltip + glossary entry for the (future) UI banner.

### Tests

- Backend: integration test that seeds a study with judgments referencing non-existent doc IDs in a real ES index → POST returns 422 `INSUFFICIENT_JUDGMENT_OVERLAP`.
- Backend: integration test that seeds a judgment list whose doc IDs partially overlap (intersection size 1-2) → POST returns 201 + a warning field.
- Backend: integration test that the probe falls through gracefully on `ClusterUnreachableError` (study is created; orchestrator will fail trials with the same error code).
- Contract: error-envelope assertion for the new 422 code.

## Scope signals

- **Backend:** new helper `compute_judgment_overlap()` in `backend/app/services/study_state.py` or a new `backend/app/services/study_preflight.py` (~80 LOC). POST handler integration (~20 LOC). Optional new response field for the warning case. Tests: 3 integration + 1 contract.
- **Frontend:** optional small banner component for the partial-overlap warning. Not strictly required for v1.
- **Migration:** none.
- **Config:** Optionally a `STUDY_PREFLIGHT_OVERLAP_MIN: int = 3` setting if operators want to tune the floor. Default literal is fine for MVP1.
- **Audit events:** N/A.
- **Estimated size:** medium — ~150 LOC total + ~120 LOC of tests. 90-120 minutes including the integration tests against a real seeded ES + judgments.

## Why deferred behind the mismatch guard

The deterministic target check catches the majority of the bug surface (a string compare costs nothing). The overlap probe adds a real ES round-trip per study create — defensible but worth the operator decision-cost. It's also more brittle: the probe relies on `top_k` being large enough to surface the judged docs (which requires non-degenerate retrieval; if the template body is itself broken, the probe will false-positive on "no overlap").

Together the two layers cover ~95% of "study cannot produce signal" paths. The remaining percent is caught by [`feat_orchestrator_zero_streak_abort`](../feat_orchestrator_zero_streak_abort/idea.md).

## Relationship to other work

- **Depends on:** the target-mismatch guard (which removes the most common failure mode first).
- **Behind:** the orchestrator zero-streak abort (defense-in-depth for everything else).
- **Coordinates with:** the existing `infra_adapter_elastic` adapter — uses `SearchAdapter.search_batch` for the probe; no new adapter surface required.
