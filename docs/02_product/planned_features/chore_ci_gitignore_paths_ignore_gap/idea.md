# chore_ci_gitignore_paths_ignore_gap — Idea

**Date:** 2026-05-13
**Status:** Idea — captured while implementing `bug_env_file_corrupted_during_session`
**Origin:** Surfaced during `/bug-fix` Phase 5 implementation of the
`secrets-files-guard` job in [.github/workflows/pr.yml](../../../../.github/workflows/pr.yml).
**Depends on:** `bug_env_file_corrupted_during_session` (this PR) — the
`secrets-files-guard` job whose effectiveness this gap limits.

## Problem

`.github/workflows/pr.yml` has a `paths-ignore` filter that skips the entire
workflow when *every* changed path matches:

```yaml
paths-ignore:
  - 'docs/**'
  - '*.md'
  - '.gitignore'
  - 'LICENSE'
  - 'release-notes-*.md'
```

Two failure modes follow:

1. **`.gitignore`-only PR** — a PR that removes `.env.old` (or any other
   `.env*` line) from `.gitignore` and nothing else does **not** trigger the
   workflow at all. Neither the new `secrets-files-guard` nor any other check
   runs. The human reviewer is the sole defense.
2. **`docs/.env.old`** — a `.env*` file placed under `docs/` matches
   `docs/**` and the workflow is skipped. The guard never runs.

Neither is a realistic attack today (both are obvious in code review), but
they undermine the defense-in-depth claim of the `secrets-files-guard` job
shipped in `bug_env_file_corrupted_during_session`.

## Proposed capabilities

### Tighten paths-ignore

- Remove `.gitignore` from `paths-ignore`. `.gitignore` changes are
  security-relevant; they should always trigger at least the guard job.
- Optionally narrow `docs/**` to `docs/**/*.md` so a non-markdown file
  smuggled into `docs/` still triggers CI.
- Verify the change does not re-introduce noise for docs-only PRs (the
  guard job costs ≤30s; backend/frontend should stay path-filtered).

### Or split the guard out

- Alternative: move `secrets-files-guard` into a *separate workflow file*
  with no `paths-ignore`. Always runs on every PR, regardless of which
  paths changed. Keeps the heavy `pr.yml` jobs path-filtered for cost.

## Scope signals

- **Backend:** none
- **Frontend:** none
- **Migration:** none
- **Config:** `.github/workflows/pr.yml` (or new `.github/workflows/secrets-files-guard.yml`)
- **Audit events:** N/A

## Why deferred

Out of scope for the immediate bug fix — the `secrets-files-guard` job
itself is the primary defense and is already shipping. The paths-ignore gap
is a known second-order limitation that should be closed in a follow-up but
does not block the bug-fix PR.

## Relationship to other work

- Extends `bug_env_file_corrupted_during_session` — same defense-in-depth
  intent, narrower fix.
- Coordinate with `chore_ci_gitleaks_workflow_step` if both land — gitleaks
  in CI is the content-scanning peer to this filename-pattern guard.
