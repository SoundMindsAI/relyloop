# chore_ci_gitleaks_workflow_step — Idea

**Date:** 2026-05-13
**Status:** Idea — captured while implementing `bug_env_file_corrupted_during_session`
**Origin:** Surfaced during `/bug-fix` Phase 3 root-cause trace. `grep gitleaks
.github/workflows/pr.yml` returned empty even though gitleaks is configured in
[.pre-commit-config.yaml](../../../../.pre-commit-config.yaml).
**Depends on:** None (parallel to `bug_env_file_corrupted_during_session`)

## Problem

Gitleaks runs only as a pre-commit hook locally. Pre-commit is opt-in (the
contributor must run `pre-commit install`); on a fresh clone or a contributor
who skips the install, nothing scans commit content for secrets. CI is the
universal backstop, and CI does not currently invoke gitleaks.

The new filename-pattern guard from `bug_env_file_corrupted_during_session`
catches `.env*` filenames but not:

- An `OPENAI_API_KEY=sk-...` line accidentally pasted into a `.md` doc.
- A leaked Postgres URL inside a Compose override at an arbitrary path.
- Any high-entropy / known-credential pattern outside the `.env*` filename
  convention.

Defense-in-depth pairing: filename guard (this PR) + content scan (this idea).

## Proposed capabilities

### Add gitleaks step to pr.yml

- Pin to the same `gitleaks` version that pre-commit uses (`v8.21.2` per
  `.pre-commit-config.yaml`).
- Run as part of the `secrets-files-guard` job (or its own fast job)
  alongside the filename guard.
- Scan PR diff only (not full history) — keeps cost minimal.
- Use the project's existing `.gitleaks.toml` config if present, else the
  shipped defaults.

### Document override path

- Runbook entry for how to allowlist a false-positive (the canonical example
  is `OPENAI_BASE_URL` URLs that resemble secrets but aren't).

## Scope signals

- **Backend:** none
- **Frontend:** none
- **Migration:** none
- **Config:** `.github/workflows/pr.yml` (or split workflow), optional `.gitleaks.toml`
- **Audit events:** N/A

## Why deferred

The filename guard shipped in `bug_env_file_corrupted_during_session` closes
the specific failure mode that motivated the bug (rotated `.env.old` smuggled
past `.gitignore`). Content scanning is a separate, broader concern that
deserves its own design discussion (false-positive policy, scan scope,
performance budget). Not a blocker for the bug fix.

## Relationship to other work

- Complements `bug_env_file_corrupted_during_session` (filename pattern
  defense) by adding content-pattern defense.
- Coordinate with `chore_ci_gitignore_paths_ignore_gap` — same workflow file
  changes; could land in a single PR.
