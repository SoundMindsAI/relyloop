# Compress `state.md` so it stays a true fast-path context document

**Date:** 2026-05-25
**Status:** Idea — tangential observation surfaced during `/impl-execute` for `infra_agent_sibling_worktree_isolation` (Phase 1, this PR).
**Priority:** P2 — every agent session pays for this; growing slowly but not yet breaking workflows.
**Origin:** Noticed during the `/impl-execute` Pre-execution Step 1 ("read CLAUDE.md, architecture.md, state.md") for the sibling-worktree feature: the `Read` tool refused to load `state.md` whole because the file (360 KB / ~92K tokens at the time of this writing) exceeds the 256 KB cap. I had to fall back to offset-based reads and skip most of the historical content. CLAUDE.md describes `state.md` as the "fast-path context document" — but at this size, it's the slowest doc in the repo to load.
**Depends on:** None.

## Problem

`state.md` is structured around two concerns conflated into one file:

1. **Active state** — the file's stated purpose per [`CLAUDE.md` §"Active Work — Read This First"](../../../../../CLAUDE.md) and §"Compressed Context First": current branch, what just shipped, what's in flight, what's queued, Alembic head, known fragility. Should be readable in one tool call, no offset/limit fiddling.
2. **Historical recent-changes log** — append-only running diary of every feature merge since `infra_foundation` (PR #4, 2026-05-09). One feature → one large paragraph documenting decisions, GPT-5.5 cycle counts, CI-fix anecdotes, etc. Useful as a rolling commit-meta archive, NOT as fast-path context.

The Read tool's 256 KB cap (verified at `state.md` 360 KB → "exceeds maximum allowed size") means agents cannot load the active-state portion without also paying for ~30 features of historical narrative. This works against the document's stated purpose:

> Read this first. Snapshots the active branch, what just shipped, what's in flight, what's queued.

If a "snapshot" requires offset-based reads to find, it's not a snapshot.

## Proposed capabilities

### A. Split `state.md` into two files

Keep `state.md` as the snapshot:
- `**Current focus:**`, `**Active branch:**`, `**Last updated:**`
- Last 5 merges as one-liner bullets (slug → PR → date)
- Active priorities / what's in flight / what's queued
- Alembic head + any known fragility

Move the historical narrative to `state_history.md` (or `docs/00_overview/state_history.md`):
- Pre-existing recent-changes paragraphs, ordered most-recent first
- New entries land here, NOT in `state.md`
- Truncated/trimmed entries acceptable — the canonical record is `git log`

Update `CLAUDE.md` §"Active Work" to point at `state.md` for fast-path and `state_history.md` for "what shipped when, with what reasoning."

### B. Document the snapshot-vs-history convention

Add a section to `CLAUDE.md` (or update the existing pointer text) explaining:
- `state.md` is for AT-MOST-ONE-PAGE active state; new-feature entries land in `state_history.md` instead
- Threshold: if `state.md` grows past N lines (say 100), prune the oldest "recent changes" rows to `state_history.md` in the same PR
- Pre-commit hook (optional, possibly out of scope) that warns if `state.md` exceeds the threshold

### C. Migration: one-shot prune

Identify the cut-line: where does "active" end and "historical archive" begin? Tentatively, keep the entries for the last ~5 merges in `state.md`; move everything older to `state_history.md`. The cut is reversible (one `git mv` undo).

## Scope signals

- **Backend:** None.
- **Frontend:** None.
- **Migration:** None (file-level, not schema).
- **Config:** Optional pre-commit hook (out of scope for v1; capture as Phase 2).
- **Audit events:** N/A.

## Why deferred

Two reasons this idea defers rather than ships inline with the sibling-worktree PR:

1. **Cross-subsystem scope.** The sibling-worktree feature is about CLAUDE.md guidance + a regression test. Compressing `state.md` would mix unrelated concerns into one PR — reviewer cognitive load multiplies and the actual feature gets buried.
2. **Requires operator judgment.** What counts as "active state" vs. "historical archive" is a judgment call only the operator can make. Examples that aren't obvious without input:
   - Should the "Last updated" stay at the top of `state.md` or move to the history file? (Probably top.)
   - Keep last 5 merges or last 10? (Threshold choice.)
   - Should `state_history.md` be in `docs/00_overview/` (sibling to `implemented_features/`) or stay at repo root next to `state.md`? (Architectural choice — see [`docs/00_overview/`](../../) for the existing implemented-features convention.)
   - Pre-commit hook: warn-only or block? (Workflow tax trade-off.)

The rubric's "implement-over-defer" calls for this work if it's ≤60 min AND no operator-judgment fork. This idea hits the operator-judgment hard-stop — defer is correct.

## Relationship to other work

- **Coordinates with** the `CLAUDE.md` §"Compressed Context First" guidance — Eric's intent (per that section) is that `state.md` IS the compressed context. The current file size defeats that.
- **Possible future coordination:** if RelyLoop ever ships a "live state dashboard" surface (separate from the markdown), `state.md` becomes a generated artifact rather than a hand-maintained one. Out of scope for this idea.
- **Independent of** the sibling-worktree work that surfaced it — different file, different concern, different rationale.
