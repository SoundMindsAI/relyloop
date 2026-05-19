# Add `prettier --check` to CI's frontend job

**Date:** 2026-05-19
**Status:** Idea — surfaced during `/impl-execute --ad-hoc` of `infra_e2e_wire_seed_helper_into_studies_spec`.
**Origin:** While committing the bug-fix branch for the proposals `?study_id=` filter, the pre-commit `prettier-ui` hook flagged 2 files in [`ui/src/components/common/entity-select.tsx`](../../../../ui/src/components/common/entity-select.tsx) and [`ui/src/__tests__/components/common/form-select-discipline.test.tsx`](../../../../ui/src/__tests__/components/common/form-select-discipline.test.tsx) as prettier-drifted. Those files shipped in PR #136 (`chore_form_dropdown_primitive`, merged 2026-05-18) and have not been touched since. CI on that PR passed cleanly — yet the pre-commit hook on a follow-up commit, running the same prettier version (`3.8.3` per `ui/pnpm-lock.yaml`), found drift.
**Depends on:** None.

## Problem

`.github/workflows/pr.yml`'s `frontend` job runs:

```yaml
- name: ESLint (next lint)
  run: pnpm --dir ui lint
- name: tsc --noEmit
  run: pnpm --dir ui typecheck
- name: vitest
  run: pnpm --dir ui test
- name: Production build (next build)
  run: pnpm --dir ui build
```

**There is no `prettier --check` step.** The pre-commit hook at `.pre-commit-config.yaml` runs `pnpm --dir ui exec prettier --check src package.json tsconfig.json eslint.config.mjs .prettierrc.json` on every commit, but it is enforced only on the contributor's machine. Any path that bypasses the hook — `git commit --no-verify`, hosted git-via-API edits, certain agent harnesses that invoke `git` without the husky/pre-commit shim, or a contributor on a fresh checkout who hasn't run `pre-commit install` — lets drift through CI undetected.

PR #136 is the demonstrated regression: 2 files shipped with formatting that the same prettier version rejects on re-check, and CI did not catch it. The drift was caught on the follow-up bug-fix branch's commit and inline-fixed in commit [`3088987`](https://github.com/SoundMindsAI/relyloop/commit/3088987) under a `style:` prefix. Without this gate, the next drift surfaces the same way: blocking an unrelated PR's commit and forcing the contributor to detour into a `style:` cleanup commit.

## Proposed work

Add a `Format check (prettier)` step to the `frontend` job in [`.github/workflows/pr.yml`](../../../../.github/workflows/pr.yml), positioned before ESLint:

```yaml
- name: Format check (prettier)
  run: pnpm --dir ui exec prettier --check src package.json tsconfig.json eslint.config.mjs .prettierrc.json
```

Exact argument list copied from the pre-commit hook entry so the two gates check identical surface. The hook in `.pre-commit-config.yaml` is the source of truth — if the hook's argument list changes in the future, this CI step should be updated to match.

## Scope signals

- **Backend:** none.
- **Frontend:** none beyond CI config.
- **Migration:** none.
- **Config:** ~3-LOC YAML addition to `pr.yml`.
- **Audit events:** none.
- **Tests:** N/A — this *is* the test.
- **CI cost impact:** prettier --check on the ui/ tree completes in <5s on a warm pnpm cache. Negligible.

## Why now (not skip, not defer)

- **Cheap fix, clear regression class.** ~3 LOC, single file, no new dependencies.
- **Already paid the cost once** (PR #136 → drift → discovered on next contributor's commit → 10 min of debugging + a separate `style:` commit). Closing this gap now prevents the same dance on the next prettier-drift incident.
- **Doesn't fit a feature.** This is `chore_` infra cleanup. Could land in any future PR but is too small to warrant `/pipeline` scaffolding; ad-hoc PR is the right shape.

## Relationship to other work

- **Sibling check (clean):** no overlapping planned features. `chore_ci_gitignore_paths_ignore_gap` and `chore_ci_gitleaks_workflow_step` (both already shipped) address adjacent CI gaps; this is the analogous formatting-check gap.
- **Touches:** [`.github/workflows/pr.yml`](../../../../.github/workflows/pr.yml) frontend job only. No backend, no UI source, no docs.
