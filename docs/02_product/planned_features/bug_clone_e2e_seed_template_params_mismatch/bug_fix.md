# Bug fix — `bug_clone_e2e_seed_template_params_mismatch`

**Source idea:** [idea.md](./idea.md)
**Branch:** `bug/smoke-green-again-bundle`
**Type:** bug fix — medium (this skill's scope)
**Date:** 2026-05-26

## Problem

Two e2e seed helpers produced **inconsistent fixture state**: `seedTemplate()` in [ui/tests/e2e/helpers/seed.ts:316](../../../../ui/tests/e2e/helpers/seed.ts#L316) declared `declared_params: { boost: 'float' }`, while `seed_study_completed_with_digest()` in [backend/app/services/test_seeding.py](../../../../backend/app/services/test_seeding.py) wrote `search_space.params.title.boost`. Both paths bypass `validate_against_template`, so the inconsistency landed in DB without server complaint — but when an E2E spec opened `CreateStudyModal` against that source study, the Step-4 client-side validator (`validateSearchSpaceAgainstTemplate`) raised `Param 'title.boost' is not declared by template — Declared params: ['boost']` and refused to advance.

Resulted in **3 of 6 currently-red smoke-stack failures** (the ones whose root cause is this single mismatch):

- `ui/tests/e2e/study-clone.spec.ts:24` — clones source, walks Step 4 → Next blocked
- `ui/tests/e2e/followup_run.spec.ts:28` — narrow followup with `NARROW_SEARCH_SPACE['title.boost']` literal hits the same validator wall
- `ui/tests/e2e/study-clone-narrow-bounds.spec.ts` — explicitly stops short of submit per a stale code comment citing this bug

The remaining 3 smoke failures (`followup_run.spec.ts:111` swap-template + `dashboard.spec.ts:47,63` + `dashboard-reseed.spec.ts:77`) have **different root causes** and are NOT in scope here. Their bug folders ([bug_smoke_followup_clone_e2e_flakes](../bug_smoke_followup_clone_e2e_flakes/idea.md) and [bug_smoke_dashboard_demo_state_locator_missing](../bug_smoke_dashboard_demo_state_locator_missing/idea.md)) stay open for separate focused PRs that can do live smoke-stack reproduction.

## Reproduction

```bash
# Pre-fix on main: validateSearchSpaceAgainstTemplate fails Step 4 → Next.
cd ui && pnpm playwright test \
  tests/e2e/study-clone.spec.ts \
  tests/e2e/followup_run.spec.ts:28 \
  tests/e2e/study-clone-narrow-bounds.spec.ts \
  --reporter=line --workers=1
```

The regression-guard substitute (no Playwright run in CI's unit lane): the rename brings `test_seeding.py`'s 9 `title.boost` literals into agreement with the template's `declared_params: { boost: 'float' }`. The integration test [`backend/tests/integration/test_test_seeding.py`](../../../../backend/tests/integration/test_test_seeding.py) exercises the seed endpoint end-to-end against Postgres and was updated in lockstep to declare `boost` (was `title.boost`) so the seed-write path stays internally consistent.

## Root cause

- **Owning layer:** test fixtures (cross-cutting backend + frontend).
- **Origin:** [backend/app/services/test_seeding.py:86,126,141,183,187,188,205,305,333](../../../../backend/app/services/test_seeding.py) — 9 occurrences of `title.boost` in the seed helper's search_space / trial params / narrative / parameter_importance / recommended_config / config_diff / followup-chain seed.
- **Propagation:** every E2E spec calling `seedStudyCompletedWithDigest()` inherits the mismatch. The dot-namespaced name is arbitrary (no test depends on it) per the bug folder's "Path 1 is the recommended default" — renaming to `boost` is the minimal-blast-radius fix.

## Fix design (locked decisions)

1. **Rename all 9 `title.boost` → `boost` in `test_seeding.py`** (Path 1 from idea.md). Cites: idea.md "Path 1 is the recommended default" + the bug being benign in production (server-side validator catches it via the real API path).
2. **Update tightly-coupled consumers in the same PR**: the integration test's `declared_params`, plus 3 E2E spec files that hard-code the literal in their own JSON shapes or assertions. Cites: the rename only solves the bug end-to-end if every co-located literal moves with the helper output. Leaving them stale would leave the smoke failures unchanged for `followup_run.spec.ts:28` (the spec hard-codes the name) and break `studies.spec.ts:173` (asserts the narrative literal).
3. **Do NOT touch `seedProposal()`'s default config_diff** at [ui/tests/e2e/helpers/seed.ts:656](../../../../ui/tests/e2e/helpers/seed.ts#L656). It's an independent helper for manual-proposal tests; its `title.boost` / `description.boost` literals don't flow through `seedTemplate()`'s validator path. Renaming would be scope creep with zero gating benefit.
4. **Do NOT touch the guide screenshot caption** at `ui/public/guides/02_review_a_proposal/metadata.json:26`. The caption describes a screenshot generated against pre-fix seed data; a guide-regen pipeline owns updating both together. Updating one would create a caption/screenshot mismatch.
5. **Do NOT touch `test_existing_row_read_compat.py:147`'s `title.boost` literal**. That test plants an arbitrary param-name literal into a synthetic Trial row to exercise JSONB read paths — it doesn't go through `seedTemplate()`'s validator and the literal name has no semantic content for what it's testing.
6. **Remove the now-stale "fixture inconsistency" comment block** in `study-clone-narrow-bounds.spec.ts` lines 84-100. The comment explained why the test stops short of submit; with the bug fixed the explanation is wrong and would confuse the next maintainer. Replace with a one-line note pointing at the remaining (out-of-scope) smoke-flake bug folders that still gate full round-trip coverage.

## Regression test plan

| Layer | Path | What it asserts |
|---|---|---|
| integration | [backend/tests/integration/test_test_seeding.py](../../../../backend/tests/integration/test_test_seeding.py) | The seed endpoint's full FK chain + the seed helper's search_space write stays internally consistent (template `declared_params={boost: ...}` matches `search_space.params.boost`). Updated declared_params in lockstep with the helper rename. |
| e2e | [ui/tests/e2e/study-clone.spec.ts:24](../../../../ui/tests/e2e/study-clone.spec.ts#L24) | Clone-from-source → Step 4 Next succeeds → submit creates lineage-linked study with `parent_study_id == sourceId`. Pre-fix: fails on Step 4 Next click. Post-fix: passes through to submit. |
| e2e | [ui/tests/e2e/followup_run.spec.ts:28](../../../../ui/tests/e2e/followup_run.spec.ts#L28) | Run-this-followup → modal opens prefilled → submit creates lineage-linked study. Pre-fix: same Step-4 validator wall via `NARROW_SEARCH_SPACE['title.boost']`. Post-fix: passes. |
| e2e | [ui/tests/e2e/studies.spec.ts:173](../../../../ui/tests/e2e/studies.spec.ts#L173) | Digest narrative assertion updated `'title.boost'` → `'boost'` (consumer of renamed helper). |

The Playwright tests run only in the `smoke (operator-path tutorial flow)` CI job (live stack). They can't be exercised by `make test-unit`. Local verification: `pnpm playwright test tests/e2e/study-clone.spec.ts --reporter=line --workers=1` against a running `make up` stack.

## Rollout

Code-only change. No migration, no env var, no operator action. Forward-only — once shipped, every smoke run will use the renamed param. Operators with stale local databases that contain seeded `title.boost` rows from a prior `make seed-demo` will see read-compat work fine (the read path is param-name-agnostic; see [`test_existing_row_read_compat.py`](../../../../backend/tests/integration/test_existing_row_read_compat.py)).

## Tangential observations

- [bug_smoke_followup_clone_e2e_flakes](../bug_smoke_followup_clone_e2e_flakes/idea.md) — 1 of its 3 listed failures (`followup_run.spec.ts:28`) resolves as a side effect of this fix. The other 2 (`followup_run.spec.ts:111` swap-template + `study-clone.spec.ts:24`) have separate root causes; `study-clone.spec.ts:24` ALSO resolves as a side effect (uses the renamed seed helper directly). The swap-template assertion failure remains open.
- [bug_smoke_dashboard_demo_state_locator_missing](../bug_smoke_dashboard_demo_state_locator_missing/idea.md) — unrelated; not addressed here.
