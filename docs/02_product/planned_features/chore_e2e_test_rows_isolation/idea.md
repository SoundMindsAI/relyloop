# Isolate E2E test rows so they don't leak into the operator UI

**Date:** 2026-05-21
**Status:** Idea — root cause behind the "study2 ran 1000 zero-metric trials" incident
**Origin:** While verifying `feat_pr_metric_confidence` Epic 2 end-to-end, the operator created a study via the UI and discovered the create-study modal offered `e2e-jl-54b2bb64` as a selectable judgment list. The operator chose it; the study burned 4.5 minutes on 1000 zero-metric trials because that judgment list was authored against a different ES index (`e2e-target`, not `docs-articles`). The downstream fix is at the validator layer ([`feat_study_target_judgment_mismatch_guard`](../feat_study_target_judgment_mismatch_guard/idea.md)) — but the *upstream* question is why the E2E-test artifact was visible in the operator's UI in the first place.
**Depends on:** None.

## Problem

Multiple seed paths emit rows into the operator-visible `clusters` / `query_sets` / `query_templates` / `judgment_lists` / `studies` tables:

- **Playwright `seedFullChain()`** — emits `e2e-cluster-*`, `e2e-qs-*`, `e2e-tmpl-*`, `e2e-jl-*` rows on every E2E run. The spec runs daily during local dev + on every CI PR. None of the helpers delete what they create. Over time the dev DB accumulates dozens of `e2e-*` rows.
- **`/api/v1/_test/studies/seed-completed`** — the test-only endpoint (`feat_pr_metric_confidence` Story 2.3 extended this) inserts a study + 2 trials + digest + proposal per call. Every Playwright test that exercises the digest panel + confidence panel triggers one. Never cleaned up.
- **`make seed-demo`** — emits realistic `acme-products-prod`, `news-search-staging`, etc. clusters with bake-in judgments. Idempotent (TRUNCATE clusters CASCADE + reseed) when invoked, but only runs on operator demand.

The list endpoints (`GET /clusters`, `GET /judgment-lists`, etc.) show ALL rows uniformly. The create-study modal's dropdowns show ALL `complete`/`active` rows. The operator has no UI affordance distinguishing "real data I created" from "test artifact some Playwright run left behind."

Same shape played out on the recent `feat_cluster_target_filter` PR's verification (state.md mentions PR #169 `make seed-demo` was created to address "the gap where integration tests kept wiping the dev DB with no durable reseed mechanism"). That fix handled the *erasure* problem; this one handles the *accumulation* problem.

## Proposed capabilities

Three approaches, in increasing order of intrusiveness. Pick one or layer them.

### A. Auto-cleanup at test teardown (simplest, recommended)

Extend the existing Playwright seed helpers to register every row they create against a `cleanupRegistry` in `ui/tests/e2e/helpers/seed.ts`. After each spec file runs, `playwright.config.ts`'s `globalTeardown` walks the registry and DELETEs in FK-safe order via the public API.

- **Pros:** No backend changes. Existing seeds keep working unchanged. Cleanup runs only on E2E exit, so a failed test still leaves rows behind for debugging — but the *next* successful run cleans them up.
- **Cons:** Requires every helper to register cleanup; future seed helpers must remember to register. A globalTeardown crash leaves rows behind.

### B. Namespaced rows + UI filter (more robust)

Rows seeded by Playwright carry a `__test_only` flag (new column on every operator-visible table) or a `name` prefix the UI filters out. The list endpoints + create-study modal dropdowns hide rows where the flag is set OR the prefix matches `^e2e[-_]`.

- **Pros:** Robust to test crashes — rows can accumulate forever without leaking into operator workflows. Clean separation of test data from real data without coupling the UI to backend cleanup.
- **Cons:** Schema migration on 5+ tables OR convention burden ("never use `e2e-` as a real cluster name prefix"). Backend API change to support the filter. Test code AND the UI both have to know about the convention.

### C. Auto-truncate test rows on `make up` (most intrusive)

`make up` runs `make seed-demo` automatically, which already TRUNCATEs clusters CASCADE. Add a "test row purge" step that DELETEs rows matching the `e2e-` prefix as part of the same idempotent reseed.

- **Pros:** No backend or test code changes. Aligns with the `make up` convention of "give me a fresh, predictable dev stack."
- **Cons:** Destructive — purges rows in operator workflows that happen to start with `e2e-`. Doesn't help during CI runs (CI doesn't invoke `make up`).

### Recommended path: A + the create-study modal filter from `feat_study_target_judgment_mismatch_guard`

Approach A handles the accumulation. The mismatch guard handles the case where rows do leak through. Together they close the operator-confusion gap without a migration.

### Tests

- Playwright: add a smoke test that runs after the suite and asserts `e2e-*` rows do not exist (validates the cleanup teardown ran).
- Integration: verify the public DELETE endpoints used by cleanup support cascade ordering (cluster → query_set → judgment_list → study → trial → proposal → digest).

## Scope signals

- **Backend:** none for approach A. For approach B, ~5 column migrations + ~5 endpoint filters.
- **Frontend:** none for A. ~30 LOC per dropdown for B.
- **Test code:** ~80 LOC of cleanup registry + globalTeardown for A. Per-helper registration calls scattered across 6 helpers (~30 LOC).
- **Migration:** none for A or C; 5+ migrations for B.
- **Config:** none.
- **Audit events:** N/A (only test-only rows; not user-mutations).
- **Estimated size (approach A):** small-to-medium — 90-150 LOC + ~30 minutes to wire teardown + register every existing helper. The mechanical lift of writing per-helper cleanup registrations dominates.

## Why this matters beyond the one incident

The "test row leakage" surface is recurring. Multiple recent PRs surface similar effects:

- `feat_create_study_search_space_builder` (PR #163) had to add filter-by-cluster-id to `judgment-lists` because the modal showed cross-cluster lists.
- `feat_create_study_target_autocomplete` (PR #165) had to disambiguate target-name lookups because indexes from E2E seeds appeared in autocomplete.
- The current incident with `study2` running 1000 zero-trials.

Each of these is a downstream patch addressing a symptom. The root cause is the same: the operator-visible row inventory is polluted by test fixtures. A one-time cleanup investment compounds.

## Relationship to other work

- **Closes the upstream of:** [`feat_study_target_judgment_mismatch_guard`](../feat_study_target_judgment_mismatch_guard/idea.md). That guard catches the leak in the validator; this one prevents the leak in the first place.
- **Composes with:** `make seed-demo` (PR #169) — that handles "test isolation rebooted my real data"; this handles "test fixtures polluted my real data."
- **Pattern precedent:** the `feat_pr_metric_confidence` Story 2.3 helper extension is the most recent place where a test endpoint grew new params without a cleanup path; first-principles fix would benefit any future helper extensions.
