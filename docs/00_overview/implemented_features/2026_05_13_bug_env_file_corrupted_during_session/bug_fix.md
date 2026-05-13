# Bug fix — bug_env_file_corrupted_during_session

**Source idea:** [idea.md](./idea.md)
**Branch:** `bug/env-file-ci-guard`
**Type:** bug fix — medium (defense-in-depth scope; cause investigation deferred)
**Date:** 2026-05-13

## Problem

During the `infra_foundation` (PR #4) implementation session on 2026-05-09, the
user's `.env` (180 bytes, containing a real `OPENAI_API_KEY`) was renamed to
`.env.old` and replaced with an empty `.env`. The rotation happened at the same
timestamp the agent wrote `.env.example`, but no pre-commit hook, agent action,
or known repo tool writes `.env.old`. The `.env.example` was the new file; the
rotation came from somewhere on the user's local machine (IDE save behavior,
direnv/1Password CLI/asdf, or a coincidental FS event).

The near-miss: `.env.old` was not in `.gitignore` at the time, so a `git add -A`
would have staged the rotated key. The PR's `.gitignore` patch added `.env.old`
/`.env.bak`/`.env.local`/`.envrc`, but CI has **no filename-pattern guard** —
the only defense if `.gitignore` regresses or someone uses `git add -f` is the
human reviewer.

## Reproduction

**Original FS event:** cannot reproduce 4 days post-incident. `.env.old` is
gone (user restored `.env` at 17:11 on 2026-05-09); no recurrence in subsequent
PRs. Cause remains undetermined; classified as one-off and user-environment-
local. See "Open questions" below.

**Latent CI gap (this skill's scope):** a synthetic file list containing
`.env.old` should be rejected by a CI guard. Currently no such guard exists:

```bash
grep gitleaks .github/workflows/pr.yml   # returns empty — no content scan in CI
grep -E "env" .github/workflows/pr.yml    # only matches step-level `env:` blocks
```

After the fix, the regression test exercises the gap:

```bash
bash scripts/ci/test_check_no_env_files.sh
# 15 passed, 0 failed — synthetic .env.old / .env.local / .envrc inputs all rejected
```

## Root cause

Two distinct concerns:

- **Original FS event:** owning layer = **user's local filesystem / tooling**
  (IDE save flow, direnv, 1Password CLI, asdf, VS Code extensions). Agent has
  no visibility into the user's machine and cannot reproduce. Out of scope for
  code change.
- **Defense gap (this fix's target):** owning layer = **CI / repo policy**.
  Origin: [.github/workflows/pr.yml](../../../../.github/workflows/pr.yml)
  has no filename guard for `.env*` patterns. Propagation:
  [.gitignore:153-163](../../../../.gitignore#L153-L163) is the only structural
  defense, and gitleaks (in [.pre-commit-config.yaml](../../../../.pre-commit-config.yaml))
  is content-based — an empty `.env.old` would pass gitleaks even though it
  signals a rotated key.

## Fix design (locked decisions)

1. **Detection — `git diff --name-only` + grep regex.** Cheap, hermetic, no
   language runtime. Cites: [scripts/ci/verify_enum_source_of_truth.sh](../../../../scripts/ci/verify_enum_source_of_truth.sh)
   precedent (same `scripts/ci/<name>.sh` pure-bash shape).
2. **Pattern — deny `(^|/)(\.env(\.[^/]+)?|\.envrc)$`, allow `(^|/)\.env\.example$`.**
   Catches bare `.env`, dotted `.env.<x>`, and direnv's `.envrc`; subdir matches
   included; excludes `foo.env` / `.environment.yml` false-positives. Cites:
   idea.md §"Proposed work" item 3.
3. **Failure mode — hard fail with `::error::` annotation + runbook pointer.**
   Cites: CLAUDE.md Absolute Rule 10 (never log/expose secrets).
4. **Workflow position — standalone `secrets-files-guard` job, ~20s, parallel
   with `backend`/`frontend`/`docker`.** Independent PR check; no service
   containers needed. Cites: existing job-per-concern pattern in pr.yml.
5. **Diff filter — `--diff-filter=AM`.** Block additions + modifications;
   removals are not security risks.
6. **Regression test — `--from-stdin` mode + canned inputs in CI step.** Keeps
   the test in the same workflow run (`scripts/ci/test_check_no_env_files.sh`)
   so the guard's own logic is exercised before it runs against the real diff.

### Open questions (deferred to user)

These belong to the user's local environment, not the repo. They remain open
after this fix:

- **Which tool renamed `.env` → `.env.old`?** Recommended: next time the user
  observes a `.env` rotation, run `fs_usage -w -f filesys | grep '\.env'`
  before opening the IDE, then trigger the suspected action. The candidate
  list (from idea.md): IDE save handler, direnv, 1Password CLI, asdf, VS Code
  extension. If reproduced, file a follow-up bug under the offending tool.

## Regression test plan

| Layer | Path | What it asserts |
|---|---|---|
| CI guard | [scripts/ci/test_check_no_env_files.sh](../../../../scripts/ci/test_check_no_env_files.sh) | 15 cases — `.env.example` passes, bare `.env` / `.env.old` / `.env.bak` / `.env.local` / `.envrc` / nested variants all fail with exit 1. Run as a workflow step *before* the real-diff check so a broken guard regex is caught immediately. |

The test fails on `main` (script does not exist) and passes on this branch.
The workflow step (`secrets-files-guard` job) invokes the same test in CI.

## Rollout

Code-only change. No migration, no feature flag, no operator action. The new
job appears as a fast (≤30s) check in the PR check list; first PR on this
branch is its own smoke test. If the regex ever needs to allow a new template
filename (`.env.staging.example`, etc.), update `ALLOW_REGEX` in
`scripts/ci/check-no-env-files.sh` and add a test case.

## Tangential observations

- [chore_ci_gitignore_paths_ignore_gap](../chore_ci_gitignore_paths_ignore_gap/idea.md) —
  `pr.yml`'s `paths-ignore` includes `.gitignore` and `docs/**`, so a PR that
  *only* tampers with `.gitignore` (removing `.env.old`) or *only* adds
  `docs/.env.old` skips the workflow entirely. Reviewer is still the
  backstop; consider tightening paths-ignore.
- [chore_ci_gitleaks_workflow_step](../chore_ci_gitleaks_workflow_step/idea.md) —
  gitleaks is in `.pre-commit-config.yaml` but not invoked from CI. Local
  pre-commit is opt-in; CI should also run a content scan to complement the
  filename guard added here.
