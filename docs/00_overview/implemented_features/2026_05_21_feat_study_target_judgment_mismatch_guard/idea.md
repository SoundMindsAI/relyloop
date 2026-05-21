# Reject studies where judgment_list.target ≠ study.target (deterministic fail-fast)

**Date:** 2026-05-21
**Status:** Idea — surfaced post-merge of `feat_pr_metric_confidence`
**Priority:** P0 — actively unblocking the "study cannot produce signal" failure class. ~80 LOC deterministic create-time reject; closes the literal study2 incident.
**Origin:** Operator created study `019e4be6-207e-7c32-9889-f6c3003f57c2` ("study2") which ran 1000 trials in 4.5 minutes with `best_metric=0.0`, `n_queries=2`, all confidence sub-fields populated correctly per FR-7 — but every trial scored exactly 0.0. Root cause: `study.target = "docs-articles"` but `judgment_list.target = "e2e-target"` (the judgment list was an E2E-test leftover generated against a different ES index). The judgment doc IDs had zero overlap with what `docs-articles` could return, so pytrec_eval scored 0 on every (params, query) pair — by construction.
**Depends on:** None — the field comparison runs purely against data already in memory at `POST /studies`.

## Problem

The existing POST `/studies` validator at [`backend/app/api/v1/studies.py:240-247`](../../../../backend/app/api/v1/studies.py#L240-L247) enforces `judgment_list.query_set_id == body.query_set_id` (cross-set anti-enumeration) and surfaces it via the generic `VALIDATION_ERROR` envelope. It does NOT enforce that the judgment list was *generated against* the same target index/collection the study queries. This is the entire failure mode here:

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

New error code `JUDGMENT_TARGET_MISMATCH` registered in BOTH the feature spec's §7.5 Error Code Catalog (canonical per [`api-conventions.md` §"Standard error codes"](../../../01_architecture/api-conventions.md)) AND echoed into [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md) alongside `SEARCH_SPACE_UNKNOWN_PARAM` / `SEARCH_SPACE_MISSING_DECLARED_PARAM` (the studies-endpoint precedent from `chore_create_study_wizard_polish`). HTTP 422, `retryable: false`.

### Backend: extend judgment-lists listing surface

The current `_summary()` builder at [`backend/app/api/v1/judgments.py:113-122`](../../../../backend/app/api/v1/judgments.py#L113-L122) omits `target` — only `_detail()` exposes it. Without `target` on the summary, the frontend dropdown has no way to filter or label by target. Two changes:

1. Add `target: str` to `JudgmentListSummary` (1 row in the Pydantic response model + 1 row in `_summary()`). Backwards-compatible additive field — no client breakage.
2. Add `?target=` query param to `GET /api/v1/judgment-lists` mirroring the existing `?cluster_id` / `?query_set_id` filters added by `bug_judgment_lists_listing_ignores_query_set_filter` (bundled in PR #163, see [`judgments.py:347-348`](../../../../backend/app/api/v1/judgments.py#L347-L348)). Apply the WHERE clause in `repo.list_judgment_lists` + `count_judgment_lists`.

This mirrors the established wire pattern (cluster_id + query_set_id are filterable; target joins them) and keeps the frontend from over-fetching + filtering client-side.

### Frontend: filter the judgment-list dropdown

In the create-study modal's judgment-list picker (Step 2, after Step 1 'Cluster + target' is gated complete per [`create-study-modal.tsx:384`](../../../../ui/src/components/studies/create-study-modal.tsx#L384) — `target` is always set by the time the user reaches the dropdown):

- Extend the `useJudgmentLists` call at [`create-study-modal.tsx:190-193`](../../../../ui/src/components/studies/create-study-modal.tsx#L190-L193) to pass `{ query_set_id, cluster_id: clusterId || undefined, target: target || undefined, limit: 200 }`. Backend `?target=` filter (added above) does the work server-side; the dropdown only renders matching rows.
- Empty-state copy when zero matches (`target_filter`-aware empty-state precedent at [`create-study-modal.tsx:557-559`](../../../../ui/src/components/studies/create-study-modal.tsx#L557-L559) for targets): "No judgment lists for target `<target>` on this cluster + query set. Generate a new one against `<target>` from /judgments." Includes a Next.js `<Link>` to the judgment-generation surface.
- **Cascade reset (FR-4 precedent):** when `target` changes via the Step-1 picker, reset `judgment_list_id` to `''` — mirror the existing `query_set_id`-change reset at [`create-study-modal.tsx:596`](../../../../ui/src/components/studies/create-study-modal.tsx#L596). Otherwise a stale judgment_list_id from a prior target survives and the dropdown shows an out-of-range value.

Catches the bug in-UI before the user can even submit. The backend 422 stays as the defense-in-depth net for non-modal callers (chat agent's `create_study` tool, direct API users).

### Tests

- Backend: 1 contract test for the new 422 + `JUDGMENT_TARGET_MISMATCH` error code envelope (asserting `detail.error_code` + `retryable: false`).
- Backend: 1 contract test for the extended `JudgmentListSummary` shape (asserts `target` field present).
- Backend: 1 integration test for a study POST with mismatched targets returning 422.
- Backend: 1 integration test for `GET /api/v1/judgment-lists?target=X` filtering correctly (seed lists with 2 different targets, assert only matches return).
- Frontend: 1 vitest case for the dropdown's target-aware filtering (mock the hook + assert only matching rows render).
- Frontend: 1 vitest case for the target-change cascade reset of `judgment_list_id`.

## Scope signals

- **Backend:** `backend/app/api/v1/studies.py` (~10 LOC for the new validator); `backend/app/api/v1/judgments.py` (~3 LOC for `target` on `_summary` + `?target=` route param); `backend/app/db/repo/judgment_list.py` (~5 LOC for the WHERE clause); response model edit for `JudgmentListSummary` (~1 LOC); `docs/01_architecture/api-conventions.md` error-code table (1 row); 4 tests.
- **Frontend:** `ui/src/components/studies/create-study-modal.tsx` (~30 LOC: filter prop on `useJudgmentLists`, empty-state copy + Link, target-change cascade reset); `ui/src/lib/api/judgments.ts` `JudgmentListsFilter` interface (~1 LOC); regenerated `ui/src/lib/types.ts` from OpenAPI; 2 vitest cases.
- **Migration:** none.
- **Config:** none.
- **Audit events:** N/A (just a validation rejection — pre-MVP2 audit log not active).
- **Estimated size:** small — ~100 LOC total + ~80 LOC of tests. 45-75 minutes including the contract + integration tests.

## Locked decisions

- **Specific error code, not generic.** New `JUDGMENT_TARGET_MISMATCH` (422, `retryable: false`). Symmetric with the studies-endpoint precedent (`SEARCH_SPACE_UNKNOWN_PARAM`, `SEARCH_SPACE_MISSING_DECLARED_PARAM`, `TARGETS_FORBIDDEN`). **Why:** machine-readable code lets the frontend render a targeted helper UI instead of a generic 422 toast.
- **Do NOT rename the existing `query_set_id`-mismatch code.** That check at [`studies.py:240-247`](../../../../backend/app/api/v1/studies.py#L240-L247) returns `VALIDATION_ERROR`; renaming it for symmetry would violate [`api-conventions.md:196`](../../../01_architecture/api-conventions.md) ("Do not rename `error_code` values once shipped"). Leave it as-is; only the new check gets the specific code.
- **Add `?target=` wire filter, not client-side filter.** Mirrors the `?cluster_id` / `?query_set_id` precedent. Frontend over-fetching + filtering would also lose the count semantics of the dropdown's "no matches" empty state.
- **Add `target` to `JudgmentListSummary` (additive).** Required so the empty-state copy can render the exact target string and so the dropdown can show target as a subtitle on each item (small UX win — future-proofs against the existing bug surface of cross-cluster name collisions).
- **Validator applies at POST `/studies` only — pre-existing rows are not retroactively rejected.** Existing queued/running studies that already passed the prior (weaker) check continue executing. This idea fixes the gate, not the past; mid-flight detection is owned by [`feat_orchestrator_zero_streak_abort`](../feat_orchestrator_zero_streak_abort/idea.md).
- **Frontend gate stays a soft UX layer, not a contract.** The backend 422 is the contract; the modal filter is a UX prefetch. Chat-agent `create_study` tool and direct API callers fall through to the same backend check (no separate enforcement needed).

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
