# Bug fix — `bug_smoke_followup_clone_e2e_flakes`

**Source idea:** [idea.md](./idea.md)
**Branch:** `bug/smoke-followup-swap-template-wrong-template-id`
**Type:** bug fix — trivial (the bug-fix skill was technically overkill per its own "When to use" table, but the user invoked `--ship` so the ceremony rides along with the fix)
**Date:** 2026-05-26

## Problem

The smoke job has been red on `ui/tests/e2e/followup_run.spec.ts:111` (`swap_template followup → Run → modal opens with swap-target template + creates study with template_id=B (AC-12)`) for 5+ consecutive main-branch CI runs. The test's final assertion `expect(newStudy!.template_id).toBe(swapTarget.id)` was failing with `Received: undefined`.

The hypothesis in the idea was "payload-shape regression in the followup → study conversion." Empirical reproduction proved otherwise: the test asserts against a `template_id` field that **does not exist on the API response shape it's reading**. Production code is correct; the test has a wrong assumption.

## Reproduction

```bash
cd ui && npx playwright test tests/e2e/followup_run.spec.ts:111 --workers=1
```

Pre-fix: `expect(received).toBe(expected) Expected: "019e667c-90b1-7253-a518-382da1d84263" Received: undefined`. Post-fix: passes.

## Root cause

- **Owning layer:** E2E test (not backend, not UI).
- **Origin:** [`ui/tests/e2e/followup_run.spec.ts:178-180`](../../../../ui/tests/e2e/followup_run.spec.ts#L178-L180) — typed the `GET /studies` response as `Array<{ id; name; template_id }>`. Then asserted `template_id` on the result.
- **Mismatch:** [`backend/app/api/v1/schemas.py:721-731`](../../../../backend/app/api/v1/schemas.py#L721-L731) — `StudySummary` (the list-view shape) intentionally omits `template_id`. Only `{id, name, cluster_id, status, best_metric, created_at, completed_at}` is exposed. `template_id` lives on `StudyDetail` ([schemas.py:687-712](../../../../backend/app/api/v1/schemas.py#L687-L712)), returned by `GET /studies/{id}`.
- The new study **was** created correctly with the swap target's `template_id` (verified by inspecting the created row's id from the list endpoint and fetching its detail). The assertion just couldn't see it.

## Fix design (locked decisions)

1. **Fix the test, not the API.** The list-view payload trim is intentional — `StudySummary` is the canonical narrow shape for the `/studies` table. Adding `template_id` to widen it for one test's convenience would expand the API surface for no caller benefit. Cites: CLAUDE.md "Don't add features beyond what the task requires" + the existing pattern in `ListResponse` schemas across `proposals.py`, `judgments.py`, etc. (all use narrow summary shapes).
2. **Two-step fetch in the test:** find the new study by name in the list response (only `name` is needed — `name` is in `StudySummary`), then `GET /studies/{id}` for the detail check. Cites: existing pattern in `study-clone.spec.ts` and `signup_flow.spec.ts` (find-by-name in list, fetch detail for asserting full-shape fields).
3. **Inline comment naming the schema split** so the next contributor doesn't repeat the mistake.

## Regression test plan

The existing E2E test IS the regression test once fixed. No new test needed — adding "test that the list endpoint does NOT return template_id" would be defending against an over-strict response shape that's not the bug here.

| Layer | Path | What it asserts |
|---|---|---|
| E2E (Playwright) | [`ui/tests/e2e/followup_run.spec.ts:174-194`](../../../../ui/tests/e2e/followup_run.spec.ts#L174-L194) | After "Run this followup" on a `swap_template` digest item, the created study (fetched via `GET /studies/{id}`) has `template_id == swapTarget.id`. |

## Rollout

- **Test-only change.** No production code modified.
- **Idea-scope narrowing:** the original idea bundled three failing tests. Preflight (2026-05-26) verified two of them (`followup_run.spec.ts:28` and `study-clone.spec.ts:24`) have stopped recurring on main and are effectively resolved-by-attrition. This fix closes the remaining one (`followup_run.spec.ts:111`), so the folder can finalize after merge — no `phase*_idea.md` remains.
- **Demo unblock:** the user's tomorrow demo can now safely show the swap-template followup workflow without risk of the (false-positive) smoke failure recurring.

## Tangential observations

- The idea's original hypothesis ("payload-shape regression in the followup → study conversion") was a reasonable guess from the test name + assertion text, but wrong. The production code path has been working correctly all along. Worth keeping in mind for future smoke-flake triage: always reproduce locally before assuming the bug is in the layer the test name implies.
