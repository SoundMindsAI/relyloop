# chore_env_guard_extend_deny_pattern — Idea

**Date:** 2026-05-13
**Status:** Idea — deferred GPT-5.5 review finding on PR #94
**Origin:** GPT-5.5 final-review Low-severity finding #3 against
[`scripts/ci/check-no-env-files.sh`](../../../../scripts/ci/check-no-env-files.sh) introduced in PR #94
(`bug_env_file_corrupted_during_session`).
**Depends on:** `bug_env_file_corrupted_during_session` (PR #94) — the
filename-pattern guard whose denylist this idea extends.

## Problem

The shipped guard regex matches `(\.env(\.[^/]+)?|\.envrc)$` — i.e. bare
`.env`, dotted `.env.<x>`, and `.envrc`. It does **not** match plausible
backup/rotation spellings that an editor or user-side script could produce:

- `.env-old` (dash separator)
- `.env_bak` (underscore separator)
- `.env~` (tilde — common editor backup suffix)
- `.env.swp` / `.env.swo` (vim swap files — *do* match the current regex, so already caught)

The risk surface is real but speculative — the original incident
(`bug_env_file_corrupted_during_session`) was a *dotted* rotation
(`.env.old`), and `.gitignore` lines 153-157 only enumerate dotted spellings
(`.env`, `.env.old`, `.env.bak`, `.env.local`, `.envrc`). The guard and the
gitignore are currently consistent: both catch dotted, both miss non-dotted.

## Proposed capabilities

### Broaden the deny regex

Expand `DENY_REGEX` to also match `.env` followed by `_`, `-`, or `~` plus
optional content. Tentative pattern:

```bash
DENY_REGEX='(^|/)(\.env([._\-~][^/]*)?|\.envrc)$'
```

False-positive checks (must continue to PASS the existing test suite):

- `.environment.yml` → `.env` + `ironment.yml`; `i` not in `[._\-~]`. ✓
- `.envoy.conf` → `.env` + `oy.conf`; `o` not in `[._\-~]`. ✓
- `foo.env` / `docs/foo.env` → preceding char is letter, not `(^|/)`. ✓

New deny cases to add to `test_check_no_env_files.sh`:

- `.env-old`
- `.env_bak`
- `.env~`
- `backend/.env-prod` (subdirectory variant)

### Parallel `.gitignore` update

To keep the guard and the gitignore aligned, extend `.gitignore` at the
same time:

```gitignore
.env-*
.env_*
.env~
```

Without this, a non-dotted variant would still slip past local
`git add -A` even with the guard in CI.

## Scope signals

- **Backend:** none
- **Frontend:** none
- **Migration:** none
- **Config:** `scripts/ci/check-no-env-files.sh` (regex), `scripts/ci/test_check_no_env_files.sh` (4 new cases), `.gitignore` (3 new patterns)
- **Audit events:** N/A

## Why deferred

The shipped guard fully addresses the **documented** incident pattern
(`.env.old`, dotted). Non-dotted variants are theoretical bypass surface
that has never been observed in this codebase or its dependencies. Mixing
the regex broadening + parallel `.gitignore` updates + their test cases
into PR #94 would blur the PR's scope (the focused defense for an
observed incident vs. a speculative pattern-broadening exercise).

A separate PR keeps each change reviewable and the test suite shape clean
(this is the file pattern review will land on).

## Relationship to other work

- Extends `bug_env_file_corrupted_during_session` (PR #94) — same defense
  surface, broader pattern.
- Could land alongside `chore_ci_gitleaks_workflow_step` if a single PR
  covers both content-scan + broader filename pattern.
- Independent of `chore_ci_gitignore_paths_ignore_gap` (workflow-level
  paths-ignore is a separate failure mode).
