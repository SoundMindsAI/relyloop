# Idea — `pr.yml` smoke job is chronically failing on `main`

**Date:** 2026-05-27
**Status:** Idea — captured during feat_index_document_browser CI watch (PR #285)
**Type:** `infra_`
**Priority:** P1 — ~20 consecutive post-merge runs failing / cancelled; the `pr` workflow's red badge on `main` no longer signals real regressions.

## Origin

Surfaced while watching CI on PR #285. The substantive checks (lint, typecheck,
pytest unit+integration+contract with coverage, frontend tests, docker buildx)
all passed; only the `smoke (operator-path tutorial flow)` job got
cancelled mid-step. The user asked whether the seed step that gets cancelled
("Seed meaningful demos") had been failing since it was added — confirming
this turned up a pattern: `pr.yml` runs on `main` have been failing or
cancelled for ~20 consecutive pushes.

## Problem

Recent `pr.yml` runs on `main` (newest first):

| Date | Conclusion |
|---|---|
| 2026-05-27 | cancelled (×3) |
| 2026-05-26 | **success** (1) ← only green run in the sample |
| 2026-05-26 | failure (×11) |
| 2026-05-25 | failure (×4) |

Sampling 5 of these via `gh run view ... --json jobs`:

- 5/5 had every other job (`backend`, `backend (fast lane)`, `frontend`,
  `docker buildx`) → **success**.
- 5/5 had `smoke (operator-path tutorial flow)` → `cancelled` (3) or
  `failure` (2).

The hard failures (`gh run view 26478434314 --log-failed`) are in the
`Run Playwright E2E` step — not in the seed-demo step itself. The
cancellations come from concurrency policy: when a new push lands while
the long-running smoke job is mid-`seed-demo` or mid-Playwright, GHA
cancels the in-flight one.

Net effect: the `pr` workflow's status on `main` has been red since
roughly 2026-05-23 (the date PR #188 — `feat_home_first_run_demo_nudge` —
landed the `seed-demo` step + the dashboard E2E specs that depend on it).
The signal-to-noise ratio is now zero; a real backend regression would
land green-on-everything-except-smoke and be indistinguishable from the
current state.

## Multi-axis cost contributors

Why this is the way it is — not a single bug but a layered cost stack:

1. **`make seed-demo FORCE=1`** at [`.github/workflows/pr.yml:409`](../../../.github/workflows/pr.yml) re-seeds 4 clusters + scenarios unconditionally on every run. It does not check for existing data even though the rows are idempotent under upsert semantics. Costs ~30-60s of wall-clock per run.

2. **Playwright E2E in the smoke job** (added by PR #188 + subsequent
   guide-screenshot work) runs *after* seed-demo and brings up a full
   browser-based test stack. Multi-minute step; chronic flakes per the
   failures cited above.

3. **Concurrency policy.** `pr.yml` has no explicit `concurrency:` block,
   so GHA applies the default — newer pushes don't cancel older ones,
   but the `push: main` trigger fires on every merge. The cancellations
   we see are because a separate concurrency mechanism (Compose port
   contention? mid-step kill?) is severing in-flight runs.

4. **Trigger surface.** `pr.yml` runs on BOTH `pull_request` and
   `push: branches: [main]`. Each merge to main re-runs the entire smoke
   gate even though that exact SHA already passed (or failed) on the PR.

## Why deferred (not inline-fixed during feat_index_document_browser)

- Fix is multi-axis (seed step + Playwright + concurrency + trigger
  surface) — not a 60-minute inline change.
- The feat_index_document_browser PR's substantive checks all pass; the
  smoke flake is independent of the feature.
- Diagnosing root cause of the Playwright failures requires reading the
  Playwright report from a failed CI run, which is upload-artifact-gated
  and time-bounded by GHA retention.

## Proposed capabilities (when this is picked up)

Phase A — cheap signal recovery:
1. **Make `seed-demo` idempotent** — skip when the 4 demo clusters already
   exist (check rows count + slug parity before re-running).
2. **Add `concurrency:` block to `pr.yml`** with `cancel-in-progress: true`
   for the `pr-refs/pull/<n>/merge` group so superseded PR runs cancel
   cleanly without leaving in-flight smoke runs stranded.
3. **Drop `push: branches: [main]`** from the smoke job's trigger — the
   PR run on the same SHA already gated the merge. Post-merge re-runs are
   redundant and contribute most of the noise.

Phase B — Playwright flake bisect:
4. Diagnose the specific Playwright failures from the most recent hard
   failure's report artifact (e.g., `gh run download 26478434314 --name
   playwright-report`).
5. Either fix the underlying flake or quarantine the unstable specs
   behind a CI-skip marker until the fix lands.

**Additional data point (added 2026-05-27 from PR #284 CI watch):** the
cancellation mode on main-branch runs is **not** Playwright flake — it is
a hard job-level timeout. Five consecutive `pr.yml` runs on `main`
(`135f19ab` 02:03 UTC → `1a477168` 12:00 UTC → `6ff9c211` 12:59 UTC →
`7a5bc42a` 16:48 UTC → `5a90f826` 19:15 UTC, all 2026-05-27) each
cancelled at 15m17–21s wall clock — matching the
`timeout-minutes: 15` setting at
[`.github/workflows/pr.yml:309`](../../../../../.github/workflows/pr.yml#L309).
The smoke job's wall-clock work has exceeded 15 minutes for at least
~17 hours of continuous merges, so the cancellation is the timeout
hitting, not concurrency or Playwright. (Concurrency cancellation does
also occur on PR-branch runs that get superseded by a later push —
that's a separate mode visible only in the PR-branch run history.)

Diagnostic implication: Phase B should also profile *what's taking >15
minutes* (the seed-demo step? the Playwright suite? Compose stack
bring-up?) before deciding between (a) raise the timeout, (b) reduce
wall clock by parallelizing or skipping steps, (c) split the job.

Phase C — split smoke job:
6. Move the seed-demo + Playwright steps into a separate, opt-in workflow
   that runs only on `pull_request` (not `push: main`), and gate it
   behind a `paths-filter` so docs-only PRs don't trigger it. The
   PR-blocking pytest/lint/typecheck checks stay in `pr.yml`.

## Scope signals

- Workflow-only changes (Phase A) — ~50 LOC across `.github/workflows/pr.yml`.
- Playwright bisect (Phase B) — open-ended; depends on what the report shows.
- Workflow split (Phase C) — ~1 new workflow file + edits to `pr.yml`'s
  trigger / paths.

## Related ideas

- [`infra_ci_smoke_makeup`](../infra_ci_smoke_makeup/idea.md) (if exists)
  — the CLAUDE.md Bug Fix Protocol's call for an operator-path
  `make up` smoke gate after infra_foundation PR #4's first-run-testing
  incident. That idea is upstream of this one; the current smoke job is
  the answer it produced.
