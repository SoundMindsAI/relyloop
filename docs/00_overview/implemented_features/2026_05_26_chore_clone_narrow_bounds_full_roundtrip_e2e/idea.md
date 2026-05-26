# Chore — extend `study-clone-narrow-bounds.spec.ts` to full clone→narrow→submit round-trip

**Date:** 2026-05-26
**Status:** Idea — surfaced during `/bug-fix` for `bug_clone_e2e_seed_template_params_mismatch` (PR landing 2026-05-26).
**Priority:** P2 — adds an E2E gate that's not currently present but isn't blocking anything. The narrowing algorithm itself is unit-tested at `ui/src/__tests__/lib/narrow-bounds.test.ts`; this would add the missing browser-level round-trip coverage.
**Origin:** Bug fix for `bug_clone_e2e_seed_template_params_mismatch`. Before that fix, the spec deliberately stopped at the textarea assertion because Step-4 Next was blocked by the seed-helper/template mismatch. The fix unblocks the submit step, so the spec CAN now be extended — but doing so in the same PR would have been scope creep.
**Depends on:** `bug_clone_e2e_seed_template_params_mismatch` (PR landing 2026-05-26) merging. Once that's in, this spec extension can land any time.

## Problem

[`ui/tests/e2e/study-clone-narrow-bounds.spec.ts`](../../../../ui/tests/e2e/study-clone-narrow-bounds.spec.ts) currently stops after asserting the textarea's narrowed JSON (Step 5 of the spec's 6-step plan from its own docblock). The 6th step ("Submit; assert the new study's persisted `search_space` carries the same narrowed bounds — FR-12: server accepted the rewrite") was deferred because the now-fixed seed-helper bug blocked Step 4 Next.

After the bug fix lands, the spec should extend to:

1. After `checkbox.check()` + parsing the narrowed textarea, click `step-next` to advance to Step 5 (objective + config — these should be prefilled from the source study).
2. Click `Create study`.
3. Wait for the `POST /api/v1/studies` response; assert it's 201 and capture the new study id.
4. `GET /api/v1/studies/{new_id}` via `request` helper.
5. Assert the persisted `search_space.params.boost.low` is the clamped `[2.0, 3.0]` range (FR-12) AND `parent_study_id == sourceId` (FR-9 lineage round-trip).

The pattern is established in `ui/tests/e2e/study-clone.spec.ts:24` — that test does the exact same submit+GET round-trip for the non-narrowed clone path.

## Why deferred

The bug-fix PR (`bug_clone_e2e_seed_template_params_mismatch`) was strict-scope: rename `title.boost` → `boost` in the seed helper + co-located consumers. Extending the narrow-bounds spec was out of scope because:

1. It's adding new test coverage, not fixing a bug.
2. It would inflate the PR's diff with assertions unrelated to the rename.
3. The spec is currently passing (it asserts what it can up to the blocked point); extending it would change what's asserted in a way that needs its own review.

## Scope signals

- **Backend:** None.
- **Frontend:** None (spec file only).
- **Migration:** None.
- **Tests:** ~30 LOC extension to `ui/tests/e2e/study-clone-narrow-bounds.spec.ts` mirroring the submit+GET pattern in `ui/tests/e2e/study-clone.spec.ts:24`.

## Relationship to other work

- **Hard depends on** `bug_clone_e2e_seed_template_params_mismatch` (PR landing 2026-05-26) — without that fix, Step-4 Next stays blocked.
- **Independent of** `bug_smoke_followup_clone_e2e_flakes` and `bug_smoke_dashboard_demo_state_locator_missing` — those are about CI smoke red on unrelated specs; this extension can land while those are still red.
