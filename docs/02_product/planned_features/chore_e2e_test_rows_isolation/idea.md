# Isolate E2E test rows so they don't leak into the operator UI

**Date:** 2026-05-21 (updated 2026-05-21 post-PR-184)
**Status:** Idea — operator-UI pollution root cause; downstream symptom catch already shipped
**Priority:** P0 — last of the 4 study2-incident follow-ups (PR #182 commit `56b67e7` labels this "UPSTREAM"). PR #184 (`ce3fcf4`, merged 2026-05-21) shipped `feat_study_target_judgment_mismatch_guard` which closes the data-correctness half: `POST /studies` now rejects mismatched cluster/target. Together (1)+(4) was the 95% promise from PR #182's commit body; (1) is in, this is (4). The remaining gap is operator-visible: the create-study modal still surfaces `e2e-*` rows in dropdowns, and post-PR-184 they share target naming with real data so the operator can no longer eyeball-distinguish them (see PR #184 drive-by `seedJudgmentList` target='products' change).
**Origin:** While verifying `feat_pr_metric_confidence` Epic 2 end-to-end (PR #180 local verification), the operator created a study via the UI and discovered the create-study modal offered `e2e-jl-54b2bb64` as a selectable judgment list. The operator chose it; the study burned 4.5 minutes on 1000 zero-metric trials because that judgment list was authored against a different ES index (`e2e-target`, not `docs-articles`). The downstream symptom is now caught at the validator layer ([`2026_05_21_feat_study_target_judgment_mismatch_guard`](../../00_overview/implemented_features/2026_05_21_feat_study_target_judgment_mismatch_guard/feature_spec.md), PR #184) — but the *upstream* question is why the E2E-test artifact was visible in the operator's UI in the first place. Validators catch the data; isolation closes the source.
**Depends on:** None. (Coordinates with the now-shipped target-mismatch guard but is not blocked by anything in flight.)

## Problem

Multiple seed paths emit rows into the operator-visible `clusters` / `query_sets` / `query_templates` / `judgment_lists` / `studies` tables:

- **Playwright `seedFullChain()`** — emits `e2e-cluster-*`, `e2e-qs-*`, `e2e-tmpl-*`, `e2e-jl-*` rows on every E2E run. The spec runs daily during local dev + on every CI PR. None of the helpers delete what they create. Over time the dev DB accumulates dozens of `e2e-*` rows.
- **`/api/v1/_test/studies/seed-completed`** — the test-only endpoint (`feat_pr_metric_confidence` Story 2.3 extended this) inserts a study + 2 trials + digest + proposal per call. Every Playwright test that exercises the digest panel + confidence panel triggers one. Never cleaned up.
- **`make seed-demo`** — emits realistic `acme-products-prod`, `news-search-staging`, etc. clusters with bake-in judgments. Two run modes:
  - **Explicit `make seed-demo FORCE=1`** — destructive: TRUNCATE clusters CASCADE + reseed.
  - **Auto-seed on fresh `make up`** — added by PR #182 (commit `56b67e7`, 2026-05-21). `scripts/install.sh:95` invokes `python3 scripts/seed_meaningful_demos.py --if-empty` which counts `clusters` rows and skips if any exist. So on a fresh DB the modal already shows the 4 meaningful-demo clusters; on an existing DB nothing happens. This shifts Approach C's framing — auto-seed is now actual behavior, not hypothetical.

The list endpoints (`GET /clusters`, `GET /judgment-lists`, etc.) show ALL rows uniformly. The create-study modal's dropdowns show ALL `complete`/`active` rows. The operator has no UI affordance distinguishing "real data I created" from "test artifact some Playwright run left behind."

Same shape played out on the recent `feat_cluster_target_filter` PR's verification (state.md mentions PR #169 `make seed-demo` was created to address "the gap where integration tests kept wiping the dev DB with no durable reseed mechanism"). That fix handled the *erasure* problem; this one handles the *accumulation* problem.

## Proposed capabilities

Three approaches, in increasing order of intrusiveness. Pick one or layer them.

### A. Auto-cleanup at test teardown (simplest, recommended)

Extend the existing Playwright seed helpers to register every row they create against a `cleanupRegistry` in `ui/tests/e2e/helpers/seed.ts`. After the suite runs, `playwright.config.ts`'s `globalTeardown` walks the registry and DELETEs in FK-safe order via the public API. (Note: Playwright's `globalTeardown` is a once-per-suite hook, not per-spec. For per-spec cleanup, use a project `teardown` or an `afterAll` in a shared base test.)

- **Pros:** No backend changes. Existing seeds keep working unchanged. Cleanup runs only on E2E exit, so a failed test still leaves rows behind for debugging — but the *next* successful run cleans them up.
- **Cons:** Requires every helper to register cleanup; future seed helpers must remember to register. A globalTeardown crash leaves rows behind.

### B. Namespaced rows + UI filter (more robust)

Rows seeded by Playwright carry a `__test_only` flag (new column on every operator-visible table) or a `name` prefix the UI filters out. The list endpoints + create-study modal dropdowns hide rows where the flag is set OR the prefix matches `^e2e[-_]`.

- **Pros:** Robust to test crashes — rows can accumulate forever without leaking into operator workflows. Clean separation of test data from real data without coupling the UI to backend cleanup.
- **Cons:** Schema migration on 5+ tables OR convention burden ("never use `e2e-` as a real cluster name prefix"). Backend API change to support the filter. Test code AND the UI both have to know about the convention.

### C. Auto-truncate test rows on `make up` (most intrusive)

`make up` already invokes `scripts/seed_meaningful_demos.py --if-empty` on a fresh stack (PR #182, 2026-05-21) — but only when the `clusters` table is empty. Extension: add a "test row purge" step that DELETEs rows matching the `e2e-` prefix as part of an explicit operator action (e.g. a new `make purge-test-rows` target, or a new flag on `seed-demo`), separate from the auto-seed-if-empty path.

- **Pros:** No backend or test code changes. Aligns with the `make seed-demo` convention of "give me a fresh, predictable dev stack." The destructive operation is operator-driven, not automatic.
- **Cons:** Doesn't help during CI runs (CI doesn't invoke `make up` or `make seed-demo`). Requires the operator to remember to run it. **Compatibility with PR #182's auto-seed-if-empty:** must NOT auto-purge in `--if-empty` mode (would defeat the "skip if any cluster exists" guard); purge belongs on the explicit `--force` path or a separate target.

### Recommended path: A + the now-shipped create-study modal filter from `feat_study_target_judgment_mismatch_guard`

Approach A handles the accumulation. The mismatch guard ([`feature_spec.md`](../../00_overview/implemented_features/2026_05_21_feat_study_target_judgment_mismatch_guard/feature_spec.md), shipped 2026-05-21 in PR #184) handles the case where rows do leak through — but only catches the cluster/target-mismatch case, not the same-target-but-no-real-doc-IDs case that's now MORE likely after PR #184's drive-by `seedJudgmentList` default change (`target='e2e-target'` → `'products'`). The convention-based eyeball-check no longer works post-PR-184 — e2e rows now share target names with real data. Together: backend rejection + UI prefilter + test-row cleanup close the operator-confusion gap without a migration.

### Tests

- Playwright: add a smoke test that runs after the suite and asserts `e2e-*` rows do not exist (validates the cleanup teardown ran).
- Integration: verify the public DELETE endpoints used by cleanup support cascade ordering (cluster → query_set → judgment_list → study → trial → proposal → digest).

## Scope signals

- **Backend:** approach A requires adding DELETE endpoints for entities that don't have them today. Current per-row DELETE inventory (re-measured 2026-05-21): `queries` ([`query_sets.py:483`](../../../../backend/app/api/v1/query_sets.py#L483)), `clusters` (soft-delete, [`clusters.py:280`](../../../../backend/app/api/v1/clusters.py#L280)), `conversations` ([`conversations.py:192`](../../../../backend/app/api/v1/conversations.py#L192)). Still-missing endpoints: `studies`, `judgment_lists`, `query_templates`, `proposals`, `digests`. Estimate ~80 LOC + contract tests + integration tests + a per-entity decision on whether DELETE is operator-facing or test-only-gated (e.g., behind `/api/v1/_test/...` like the existing `seed-completed` endpoint). For approach B, ~5 column migrations + ~5 endpoint filters.
- **Frontend:** none for A. ~30 LOC per dropdown for B.
- **Test code:** ~80 LOC of cleanup registry + globalTeardown for A. Per-helper registration calls scattered across 6 helpers (~30 LOC).
- **Migration:** none for A or C; 5+ migrations for B.
- **Config:** none.
- **Audit events:** N/A (only test-only rows; not user-mutations).
- **Estimated size (approach A):** medium — ~80 LOC backend (DELETE endpoints not present today) + ~90-150 LOC of cleanup-registry + teardown wiring + ~120 LOC of contract/integration tests for the new DELETEs. 2-3 hours total. The backend DELETE endpoints are the discovery cost that initially looked free; once they land they're also reusable by other test-cleanup paths.

## Why this matters beyond the one incident

The "test row leakage" surface is recurring. Multiple recent PRs surface similar effects:

- `feat_create_study_search_space_builder` (PR #163, 2026-05-20) had to add filter-by-cluster-id to `judgment-lists` because the modal showed cross-cluster lists.
- `feat_create_study_target_autocomplete` (PR #165, 2026-05-20) had to disambiguate target-name lookups because indexes from E2E seeds appeared in autocomplete.
- `feat_study_target_judgment_mismatch_guard` (PR #184, 2026-05-21) added two new 422 error codes (`JUDGMENT_CLUSTER_MISMATCH`, `JUDGMENT_TARGET_MISMATCH`) at `POST /studies` AND bundled a `seedJudgmentList` default change from `'e2e-target'` to `'products'` so the new validator didn't reject chained E2E POSTs. The validator catches the mismatch; the drive-by means e2e rows now match real-data target naming, making them harder to spot visually.
- The original `study2` incident is now caught at the validator layer post-PR-184, but the same-target-disjoint-doc-IDs failure mode (where e2e seeds match a real target name but have no real doc IDs in the index) is still possible.

Each of the first three is a downstream patch addressing a symptom. The root cause is the same: the operator-visible row inventory is polluted by test fixtures. A one-time cleanup investment compounds, and post-PR-184 the value compounds further because the convention-based eyeball-check (`e2e-target`) no longer works.

## Relationship to other work

- **Closes the upstream of:** [`2026_05_21_feat_study_target_judgment_mismatch_guard`](../../00_overview/implemented_features/2026_05_21_feat_study_target_judgment_mismatch_guard/feature_spec.md) (shipped PR #184 2026-05-21). That guard catches the cluster/target mismatch in the validator; this one prevents the leak in the first place AND covers the same-target-disjoint-doc-IDs case the guard can't.
- **Composes with:** `make seed-demo` (PR #169) — that handles "test isolation rebooted my real data"; this handles "test fixtures polluted my real data." Also composes with the new `scripts/install.sh:95` auto-seed-if-empty path (PR #182) — purge belongs on a separate operator-driven trigger, never auto.
- **Coordinates with (still planned):** [`feat_study_preflight_overlap_probe`](../feat_study_preflight_overlap_probe/idea.md) (catches same-target-but-no-overlap at create) + [`feat_orchestrator_zero_streak_abort`](../feat_orchestrator_zero_streak_abort/idea.md) (mid-flight abort after N zero-metric trials). Together with the now-shipped target-mismatch guard, these three sibling layers + this isolation chore close ~99% of the "study cannot produce signal" surface.
- **Pattern precedent:** the `feat_pr_metric_confidence` Story 2.3 helper extension is the most recent place where a test endpoint grew new params without a cleanup path; first-principles fix would benefit any future helper extensions.
