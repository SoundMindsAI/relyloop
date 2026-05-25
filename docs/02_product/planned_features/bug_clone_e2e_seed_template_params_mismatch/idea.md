---
name: bug-clone-e2e-seed-template-params-mismatch
description: Seed helpers produce a clone-mode source study whose search_space.params don't match the seeded template's declared_params — blocks Step-4 Next, blocking the clone-to-submit round-trip in E2E
metadata:
  type: bug
---

# Bug — clone E2E: seed-template/seed-study `declared_params` ↔ `search_space.params` mismatch blocks Step-4 → Step-5 transition

**Date:** 2026-05-25
**Status:** Idea — surfaced during `feat_study_clone_narrow_bounds` Story 1.4 (E2E spec authoring).
**Priority:** P2 — does not affect production behavior (server-side `validate_against_template` catches the inconsistency before a real client could ship it), but blocks E2E coverage of the clone → submit → persisted-shape round trip for both v1 clone (`feat_study_clone_from_previous` `ui/tests/e2e/study-clone.spec.ts`) and the new narrow-bounds spec (`ui/tests/e2e/study-clone-narrow-bounds.spec.ts`).

## Origin

- Spotted: `feat_study_clone_narrow_bounds` Story 1.4 (PR opening 2026-05-25). The new spec calls `seedFullChain` + `seedStudyCompletedWithDigest` and walks the clone modal. Step 3 → Step 4 transition (`step-next` button → `handleStep4Next`) fires `validateSearchSpaceAgainstTemplate`, which finds `title.boost` in the prefilled search-space but only `boost` in the seeded template's `declared_params`, raises `Param 'title.boost' is not declared by template…`, and refuses to advance.
- Pre-existing: the v1 clone spec (`ui/tests/e2e/study-clone.spec.ts`) hits the same wall today against the current local stack. Both specs share the same fixture path; both are blocked at the same point.

## Problem

Two helpers produce inconsistent fixture state:

- [`ui/tests/e2e/helpers/seed.ts:296-321`](../../../ui/tests/e2e/helpers/seed.ts) `seedTemplate` posts a template with `declared_params: { boost: 'float' }`.
- [`backend/app/services/test_seeding.py:75-93`](../../../backend/app/services/test_seeding.py) `seed_study_completed_with_digest` calls `repo.create_study(..., search_space={"params": {"title.boost": {"type": "float", ...}}})` — i.e., it writes a `title.boost` param into the study's `search_space`, NOT the `boost` param the template declares.

Both paths bypass the API endpoint and write via the repo layer, so neither layer's `validate_against_template` (Pydantic / `chore_create_study_wizard_polish` Story 1.1) ever runs on the seeded row. The resulting state passes through DB FK checks but violates the wire-level invariant the frontend wizard enforces at Step 4.

When the clone E2E opens the modal with that source study, the prefilled `search_space_text` carries `title.boost` and `templateBody.declared_params` carries `boost`. `handleStep4Next` calls `validateSearchSpaceAgainstTemplate`, which returns:

> `Param 'title.boost' is not declared by template 'e2e-tpl-<sha>'. Declared params: ['boost'].`

`setSearchSpaceError(error); if (error) return;` → transition aborts, submit button never appears, the spec's `step-next → step-5 → click Create study` chain dies on the `step-next` click.

## Why deferred

Out of scope for `feat_study_clone_narrow_bounds`. The narrow-bounds spec doesn't change either helper, doesn't change the modal's validator, and doesn't change the wire contract. Fixing the inconsistency is a fixture cleanup that benefits two E2E specs (v1 clone + narrow-bounds) and any future spec that wants to walk the clone wizard end-to-end.

## Proposed remediation paths (pick one)

1. **Tighten the backend seed.** Change `seed_study_completed_with_digest` to write `search_space.params.boost` (matching the template's `declared_params`). The digest's `recommended_config` already matches the search_space param name conventionally, so it needs the same rename (`title.boost` → `boost`). Cheapest fix; preserves the existing helper signature.
2. **Parameterize the seed.** Add an optional `search_space_param_name: str = "boost"` arg to `seed_study_completed_with_digest` so individual tests can pin it. Bigger surface; only worth it if multiple specs need different param names.
3. **Accept search_space + recommended_config as opts.** Widen the helper to allow callers to pass the full JSON shapes. Most flexible; ugliest signature; only justified if (1) and (2) prove too rigid.

Path 1 is the recommended default. The current `title.boost` name is arbitrary — no test depends on the dot-namespacing — so renaming to `boost` is a no-op for every other consumer of `seed_study_completed_with_digest`.

## Scope signals

- **Backend:** ~5 LOC (rename two string literals in `test_seeding.py:84-88` and `:188`).
- **Frontend:** 0 LOC.
- **Migration:** none.
- **Config:** none.
- **Audit events:** none (pre-MVP2).
- **Tests:** the v1 clone spec at `ui/tests/e2e/study-clone.spec.ts` should pass through to Step 5 and submit successfully once the fixture aligns. The narrow-bounds spec can extend back to the full submit + round-trip assertion that AC-12 originally specified.

## Relationship to other work

- **Hard depends on** nothing — drop-in fixture fix.
- **Unblocks** the round-trip path in both `study-clone.spec.ts` and `study-clone-narrow-bounds.spec.ts`. After this lands, both specs can assert the persisted `parent_study_id` (v1) and the narrowed `search_space.params.boost.low/high` (narrow-bounds) via the post-submit `GET /api/v1/studies/{new_id}`.

## Why this is benign in production

A real operator's path is `POST /api/v1/studies` (the API endpoint), which calls `validate_against_template` server-side and rejects the mismatch with 400 `SEARCH_SPACE_UNKNOWN_PARAM` before any inconsistency can land in the DB. The seed helpers bypass that validation deliberately (for speed — the integration test at `backend/tests/integration/test_test_seeding.py` covers the repo-level write path; full API exercise would slow each seed by a network hop). The bug is **test-fixture-only**.
