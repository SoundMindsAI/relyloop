# Reject studies where judgment_list.target ≠ study.target (deterministic fail-fast)

**Date:** 2026-05-21
**Status:** Idea — surfaced post-merge of `feat_pr_metric_confidence`
**Origin:** Operator created study `019e4be6-207e-7c32-9889-f6c3003f57c2` ("study2") which ran 1000 trials in 4.5 minutes with `best_metric=0.0`, `n_queries=2`, all confidence sub-fields populated correctly per FR-7 — but every trial scored exactly 0.0. Root cause: `study.target = "docs-articles"` but `judgment_list.target = "e2e-target"` (the judgment list was an E2E-test leftover generated against a different ES index). The judgment doc IDs had zero overlap with what `docs-articles` could return, so pytrec_eval scored 0 on every (params, query) pair — by construction.
**Depends on:** None — the field comparison runs purely against data already in memory at `POST /studies`.

## Problem

The existing POST `/studies` validator at [`backend/app/api/v1/studies.py:238`](../../../../backend/app/api/v1/studies.py#L238) enforces `judgment_list.query_set_id == body.query_set_id` (cross-set anti-enumeration). It does NOT enforce that the judgment list was *generated against* the same target index/collection the study queries. This is the entire failure mode here:

- A `JudgmentList` row carries a `target` field — the index/collection name the judgments were authored against.
- A `Study` row carries its own `target` field — the index the orchestrator's adapter queries.
- When these mismatch, the judgments' doc IDs (which are index-scoped) cannot appear in the study's search results. pytrec_eval has nothing to score → NDCG=0 deterministically.
- Optuna's TPE sampler still happily explores the search space; trials complete; the persisted shape looks valid to the API and the UI. The operator has no way to tell from the surface that the entire study was unanswerable from the moment of creation.

This isn't a probabilistic mismatch like "the right judgment list but stale judgments" — it's a deterministic guarantee of zero signal. Catching it at create time costs one string comparison.

## Proposed capabilities

### Backend: new validation in POST /studies

After the existing FK resolution + the `query_set_id` consistency check:

```python
if judgment_list.target != body.target:
    raise _err(
        422,
        "JUDGMENT_TARGET_MISMATCH",
        f"judgment_list target={judgment_list.target!r} does not match "
        f"study target={body.target!r}; judgments would have no overlap "
        f"with search results from the study's target. Use a judgment "
        f"list generated against {body.target!r} or change study.target "
        f"to {judgment_list.target!r}.",
        False,
    )
```

New error code `JUDGMENT_TARGET_MISMATCH` registered in `docs/01_architecture/api-conventions.md` (or wherever the canonical code list lives).

### Frontend: filter the judgment-list dropdown

In the create-study modal's judgment-list picker:

- When the user has selected a `target` (Step 1), only show judgment lists where `judgment_list.target === selectedTarget`.
- When zero judgment lists match, show an empty-state pointing at the path to generate a new one against the right target.
- When no target is selected yet, show all `complete` judgment lists but render an inline hint that the list will be filtered after Step 1.

Catches the bug in-UI before the user can even submit.

### Tests

- Backend: 1 contract test for the new 422 + `JUDGMENT_TARGET_MISMATCH` error code envelope.
- Backend: 1 integration test for a study POST with mismatched targets returning 422.
- Frontend: 1 vitest case for the dropdown's target-aware filtering.

## Scope signals

- **Backend:** `backend/app/api/v1/studies.py` (~10 LOC), `docs/01_architecture/api-conventions.md` error-code table (1 row), 2 tests.
- **Frontend:** `ui/src/components/studies/create-study-modal.tsx` (~30 LOC for the filter + empty-state copy), 1 vitest.
- **Migration:** none.
- **Config:** none.
- **Audit events:** N/A (just a validation rejection — pre-MVP2 audit log not active).
- **Estimated size:** small — ~80 LOC total + ~50 LOC of tests. 30-60 minutes including the contract + integration tests.

## Why this is the highest-leverage fail-fast

| Mismatch surface | Catchable here? |
|---|---|
| `judgment_list.target ≠ study.target` (this PR's case) | **Yes, deterministically** |
| Same target, judgment list stale relative to index re-keying | No — needs the preflight overlap probe (`feat_study_preflight_overlap_probe`) |
| Judgment list intentionally subset of target docs | No — that's a valid degraded case |

Three of those four scenarios fail-fast cleanly with the simple equality check. The remaining ones require deeper signal — they're tracked in the sibling ideas below.

## Relationship to other work

- **Sibling:** [`feat_study_preflight_overlap_probe`](../feat_study_preflight_overlap_probe/idea.md) — runs one representative query against the target at POST time, checks doc-ID overlap with the judgment list. Catches the same-target-but-disjoint-docs case this guard can't.
- **Sibling:** [`feat_orchestrator_zero_streak_abort`](../feat_orchestrator_zero_streak_abort/idea.md) — defense-in-depth: aborts the study after N consecutive trials scoring 0.0. Catches everything the create-time guards miss.
- **Sibling:** [`chore_e2e_test_rows_isolation`](../chore_e2e_test_rows_isolation/idea.md) — the upstream problem of *why* an `e2e-jl-*` row was visible in the operator's UI in the first place.
- **Spec precedent:** `feat_study_lifecycle` already validates `judgment_list.query_set_id == study.query_set_id` with a `VALIDATION_ERROR`. This adds a sibling check on the same boundary.
