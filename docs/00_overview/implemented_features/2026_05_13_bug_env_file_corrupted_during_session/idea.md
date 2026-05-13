# bug_env_file_corrupted_during_session — Idea

**Date:** 2026-05-09
**Status:** Idea — captured during `infra_foundation` Story 4.4 implementation
**Origin:** PR for `infra_foundation` (Story 4.4); user `.env` was renamed to
`.env.old` and replaced with an empty `.env` at some point during the
implementation session. Discovered when `git add -A` swept `.env.old` into the
staged set and the gitleaks pre-commit hook risked exposing the contained
OpenAI API key.

## Problem

The user's working `.env` (containing the OpenAI API key referenced by
[`CLAUDE.md`](../../../CLAUDE.md) "Cross-model review policy") was renamed to
`.env.old` during the agent's implementation session. A new empty `.env` was
created at the same timestamp.

- `.env.old` mtime: 2026-05-09 16:03 (180 bytes, contains real `OPENAI_API_KEY`)
- `.env` mtime: 2026-05-09 16:03 (0 bytes)
- `.env.example` mtime: 2026-05-09 16:02 (3011 bytes — this PR's deliverable)

No pre-commit hook, agent action, or known tool in the repo writes `.env.old`.
The only proximate event was the agent creating `.env.example` at 16:02 from
the implementation-plan template.

Plausible causes (none verified):

1. An IDE / editor "rename + new" operation triggered by saving `.env.example`
   adjacent to `.env`.
2. A user-side tool (1Password CLI, direnv, asdf) doing periodic backup-and-
   refresh of `.env` files.
3. A spontaneous filesystem event coincidentally at the same minute as the
   `.env.example` write.

## Risk

`.env` files are gitignored but `.env.old` was not — until this PR added
`.env.old` to [`.gitignore`](../../../.gitignore). A naive `git add -A` on the
working tree would have staged the rotated key. The gitleaks pre-commit hook
*should* have caught it, but the timing of the second commit attempt left
some doubt about whether the hook chain ran to completion. Defense-in-depth:
keep both the gitignore entry AND the gitleaks scan.

## Why deferred

Out of scope for `infra_foundation`. The `.gitignore` patch in this PR is a
defensive containment, not a root-cause fix. Investigating the rename
mechanism requires reproducing the issue (likely needs the same IDE / tool
configuration the user had at session start) and is unrelated to the MVP1
infra surface.

## Proposed work

1. **Reproduce.** Run a minimal `Write` of `.env.example` adjacent to a
   non-empty `.env` in a clean shell + IDE state; observe whether `.env.old`
   appears.
2. **Audit local tooling.** Inventory direnv / 1Password CLI / asdf / VS Code
   extensions that touch `.env` files. Document any rotation behaviors.
3. **Add a CI guard.** A workflow step that fails if `.env.old`, `.env.bak`,
   or any `.env.*` (except `.env.example`) appears in the diff would prevent
   accidental commit even if `.gitignore` is misconfigured downstream.

## Scope signals

- Backend: none
- Frontend: none
- Migration: none
- Config: `.gitignore` (already patched in this PR — defensive only)
- CI: optional new guard in `.github/workflows/pr.yml`

## Depends on

`infra_foundation` (this PR) — establishes `.env.example` as the canonical
template that triggered the rename.
