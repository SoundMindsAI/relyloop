# Preflight probe — check judgment doc-ID overlap with target before enqueueing the orchestrator

**Date:** 2026-05-21
**Status:** Idea — surfaced post-merge of `feat_pr_metric_confidence` as the defense-in-depth tier behind the target-mismatch guard
**Priority:** P1 — second tier of fail-fast, hardens residual cases the target-mismatch guard can't catch (re-indexed corpus, stale judgments). Ready when P0 clears.
**Origin:** Same operator session as [`feat_study_target_judgment_mismatch_guard`](../../../00_overview/implemented_features/2026_05_21_feat_study_target_judgment_mismatch_guard/feature_spec.md) (Tier 1, **shipped 2026-05-21 as PR #184**). The deterministic target-name check Tier 1 added catches the most common pathology (judgment list authored against a different index), but it doesn't catch the case where the judgment list's nominal `target` matches the study's `target` yet the doc IDs in the judgments are entirely disjoint from what the index can return. That happens after re-indexing with new doc IDs, after a `_reindex` with a transform, or whenever the operator regenerates an index without bumping its name.
**Depends on:** [`feat_study_target_judgment_mismatch_guard`](../../../00_overview/implemented_features/2026_05_21_feat_study_target_judgment_mismatch_guard/feature_spec.md) — **dep satisfied** (PR #184, merged 2026-05-21). This idea is the layer behind that one. The Tier 3 sibling [`feat_orchestrator_zero_streak_abort`](../../../00_overview/implemented_features/2026_05_22_feat_orchestrator_zero_streak_abort/feature_spec.md) **also shipped 2026-05-22 as PR #191** as the mid-flight tier behind this one; this idea now sits between two implemented guards.

## Problem

The target-mismatch guard catches a string-equality mismatch. It misses these legitimate-looking-but-still-broken cases:

1. **Same target, re-indexed corpus.** Operator regenerates `docs-articles` via `_reindex` with new doc IDs. The old judgments still reference the old doc IDs. Top-K results from the index now don't intersect the judgments → NDCG=0 regardless of params.
2. **Same target, judgments authored on a stale sample.** A judgment list was generated against an index snapshot; the index has since rotated. The current state returns new doc IDs the judgments don't cover.
3. **Same target, but the queries themselves are wrong.** Operator copied an `e2e-*` query set whose strings ("e2e query 0") don't appear anywhere in the corpus. Index returns 0 hits for every query → NDCG=0.

All three look fine at create time: `judgment_list.target == study.target`, `judgment_count > 0`, `query_count > 0`. The orchestrator runs N trials, all score 0, and the operator burns budget on a study that couldn't possibly produce signal.

## Proposed capabilities

### Preflight probe at POST /studies

After the create-study validators pass, before staging the study row + enqueueing `start_study`:

1. Pick a representative query from the query set (the first query by `id` ascending **that has at least one judgment in the list** — deterministic + cheap, and avoids false-negative-overlap when query 0 happens to be unjudged). Implementation: a single `SELECT q.id, q.query_text FROM queries q JOIN judgments j ON j.query_id = q.id WHERE q.query_set_id = ? AND j.judgment_list_id = ? ORDER BY q.id ASC LIMIT 1` against the existing `queries` + `judgments` tables (preflight grep confirmed columns at [`backend/app/db/models/query.py:30-34`](../../../../backend/app/db/models/query.py) + [`backend/app/db/models/judgment.py:59-69`](../../../../backend/app/db/models/judgment.py)).
2. Use the cluster's `SearchAdapter` (acquired via the existing [`backend/app/services/cluster.py:227`](../../../../backend/app/services/cluster.py) `acquire_adapter()` context manager — same pattern the cluster-targets endpoint uses) to render the query template + execute a single search at `top_k = min(50, max_judgments_per_qid * 5)`. **Definition of `max_judgments_per_qid`**: the count of `judgments.doc_id` rows for `(judgment_list_id = study.judgment_list_id, query_id = <chosen qid>)`. This is the upper bound of doc IDs the probe could possibly find an intersection against; the 5× safety factor accounts for the probe-target query template being slightly less precise than what Optuna will eventually search with. Resolve this count via the same SELECT used in step 1 (extend with `COUNT(*) OVER (PARTITION BY q.id)` or a second targeted SELECT).
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

## Why deferred behind the mismatch guard (status as of 2026-05-22)

The deterministic target check Tier 1 shipped (PR #184) catches the majority of the bug surface — a string compare costs nothing. The overlap probe adds a real ES round-trip per study create — defensible but worth the operator decision-cost. It's also more brittle: the probe relies on `top_k` being large enough to surface the judged docs (which requires non-degenerate retrieval; if the template body is itself broken, the probe will false-positive on "no overlap").

The Tier 3 sibling — [`feat_orchestrator_zero_streak_abort`](../../../00_overview/implemented_features/2026_05_22_feat_orchestrator_zero_streak_abort/feature_spec.md) — **also shipped 2026-05-22 (PR #191)** and now catches the residual "study burns budget on zero-signal trials" cases mid-flight. With Tiers 1 and 3 both live, this idea (Tier 2) is the remaining gap: it catches `(same target, doc IDs disjoint)` before any orchestrator budget is spent, which is strictly better operator UX than waiting 20 zero-metric trials for Tier 3 to fire.

Together the three layers cover ~95% of "study cannot produce signal" paths; this idea closes the gap between the create-time string check (Tier 1, free) and the mid-flight 20-trial detection (Tier 3, costs 20 trials of budget) by adding a single search-round-trip probe at create time.

## Relationship to other work

- **Depends on (satisfied):** [`feat_study_target_judgment_mismatch_guard`](../../../00_overview/implemented_features/2026_05_21_feat_study_target_judgment_mismatch_guard/feature_spec.md) — PR #184, merged 2026-05-21. Tier 1 removes the most common failure mode first.
- **Composes with (satisfied):** [`feat_orchestrator_zero_streak_abort`](../../../00_overview/implemented_features/2026_05_22_feat_orchestrator_zero_streak_abort/feature_spec.md) — PR #191, merged 2026-05-22. Tier 3 catches everything this probe misses (e.g., template-body breakage at edge param values that the probe's template-render wouldn't expose).
- **Coordinates with:** the existing `infra_adapter_elastic` adapter — uses `SearchAdapter.search_batch` for the probe via the existing [`acquire_adapter()`](../../../../backend/app/services/cluster.py) context manager; no new adapter surface required.
- **Coordinates with:** [`chore_guides_faq`](../chore_guides_faq/idea.md) (planned) — if the FAQ ships, the new `INSUFFICIENT_JUDGMENT_OVERLAP` rejection becomes a natural FAQ entry ("My study was rejected with INSUFFICIENT_JUDGMENT_OVERLAP — what now?"). Coordinate copy with the FAQ author when both are ready.

## Open questions for /spec-gen

The audit (`/idea-preflight`, 2026-05-22) identified two design forks that need a spec-time decision; default recommendations included so /spec-gen doesn't start from zero.

### Q1 — 3-tier matrix (0 / 1-2 / 3+) vs 2-tier (0 / ≥3)

The current proposal returns a 201 with a NEW `metric_delta_warning` field when intersection size is 1-2. Preflight grep confirmed RelyLoop has **no existing success-with-warning pattern** in any API route — every endpoint either returns the canonical happy-path response or the error envelope from [`api-conventions.md`](../../../01_architecture/api-conventions.md). Introducing a new envelope shape is a meaningful design commitment.

| Option | Pros | Cons |
|---|---|---|
| A. Keep the 3-tier matrix (introduce `metric_delta_warning`) | Lets operators proceed if they accept the weak signal; matches the idea's original design. | New envelope pattern not used elsewhere in the project — every future "warn-but-allow" feature will reference this as precedent. |
| **B. (recommended)** Collapse to 2-tier: 0 = reject (422), ≥3 = allow (201, no new field) | No new envelope pattern; simpler implementation; simpler spec/contract test. Operators with 1-2 overlap regenerate judgments — the same action they'd take after seeing the warning. | More aggressive — a study with overlap=2 might still produce some signal that the operator now can't see. |
| C. Move the warning to a separate `GET /api/v1/studies/{id}/preflight` endpoint | Avoids the envelope-pattern question entirely; preflight metadata stays inspectable. | Adds endpoint surface; nobody asked for it. |

**Recommended default for /spec-gen:** B. Revisit if operators ask for the granular signal post-ship.

### Q2 — Cluster-unreachable behavior

When the probe hits `ClusterUnreachableError`, the idea says "fall through with a WARN log; don't block creation." That's defensible (cluster outages are temporary; the orchestrator already handles per-trial failures), but it means an operator can create a study against an unreachable cluster and only learn from the orchestrator's first failure burst.

| Option | Behavior on probe ClusterUnreachableError |
|---|---|
| **A. (recommended)** Fall through with WARN log (idea's current proposal) | Study created. Orchestrator's existing per-trial failure handling catches the cluster issue. Consistent with cluster registration UX (a temporarily-unreachable cluster is still registerable). |
| B. Reject with existing `CLUSTER_UNREACHABLE` (503) code | Clearer to operator; saves the orchestrator from spinning up at all. But inconsistent with the cluster-registration philosophy and the rest of the codebase's "tolerate transient adapter failures at write time" pattern. |

**Recommended default for /spec-gen:** A (current proposal).
