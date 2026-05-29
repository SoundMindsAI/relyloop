# Idea — drop `push: branches: [main]` trigger from `pr.yml`

**Date:** 2026-05-27 (preflighted 2026-05-28 — most of the original scope shipped overnight via sibling PRs; this rewrite narrows to the residual work)
**Status:** Idea — partially superseded. The original 2026-05-27 capture treated this as a single multi-axis problem; three of the four cost contributors have shipped or were never true. The residual scope is one workflow-trigger change. See "What already shipped" below before reading the original problem narrative.
**Type:** `infra_`
**Priority:** P2 — original P1 was justified by ~20 consecutive red `main` runs and 15-minute timeouts. After PR #290 + PR #291 + PR #294, wall clock is ~5–6m and the dominant failure mode is the separately-tracked [`bug_smoke_seed_es_unavailable_shards_race`](../bug_smoke_seed_es_unavailable_shards_race/idea.md). The residual change is a small trigger-surface tweak; not P1-painful anymore.

## Origin

Surfaced while watching CI on PR #285 (`feat_index_document_browser`). The substantive checks (lint, typecheck, pytest unit+integration+contract with coverage, frontend tests, docker buildx) all passed; only the `smoke (operator-path tutorial flow)` job was cancelled mid-step. The user asked whether the seed step ("Seed meaningful demos") had been failing since it was added — confirming this turned up a pattern: `pr.yml` runs on `main` had been failing or cancelled for ~20 consecutive pushes between 2026-05-23 and 2026-05-27.

## What already shipped (sibling PRs retiring most of the original scope)

The 2026-05-28 sweep retired most of this idea's capabilities. Cross-reference before scoping any work here:

| Original scope item | Shipped via | Effect |
|---|---|---|
| Make `seed-demo` idempotent (original Phase A #1) | [PR #290](https://github.com/SoundMindsAI/relyloop/pull/290) — [`chore_drop_demo_seed_from_ci`](../../implemented_features/2026_05_28_chore_drop_demo_seed_from_ci/idea.md) | `make seed-demo` step removed entirely from `pr.yml`. The 2 dashboard E2E specs that depended on it (`dashboard.spec.ts`, `dashboard-reseed.spec.ts`) are gated out via Playwright `testIgnore` when `process.env.CI` is set. ~30–60s wall clock recovered. |
| Concurrency block with `cancel-in-progress: true` (original Phase A #2) | Already present at [`.github/workflows/pr.yml:41-44`](../../../../../.github/workflows/pr.yml#L41-L44) (predated this idea — the 2026-05-27 capture missed it). | Concurrency works at workflow level, not job level — the entire `pr` workflow cancels superseded runs cleanly. |
| Reduce wall-clock cost driving the 15-minute timeout (original Phase B "Additional data point") | [PR #291](https://github.com/SoundMindsAI/relyloop/pull/291) — [`chore_ci_perf_buildx_artifact_image_cache_xdist`](../../implemented_features/2026_05_28_chore_ci_perf_buildx_artifact_image_cache_xdist/idea.md) | docker-buildx artifact handoff + base-image cache + pytest-xdist. `docker compose up -d` cut from ~10m → 21–90s on warm cache. Recent main runs finish in ~5–6m wall clock (verified on PRs #292/#293/#294, well under the `timeout-minutes: 15` ceiling at [`pr.yml:321`](../../../../../.github/workflows/pr.yml#L321)). |
| Quarantine specific dashboard Playwright flakes (original Phase B) | PR #290 (testIgnore gating) + [`bug_smoke_dashboard_demo_state_locator_missing`](../../implemented_features/2026_05_26_bug_smoke_dashboard_demo_state_locator_missing/idea.md) + [`bug_smoke_followup_clone_e2e_flakes`](../../implemented_features/2026_05_26_bug_smoke_followup_clone_e2e_flakes/idea.md) | The Playwright failures that drove the original idea (dashboard specs against missing demo data) are gone. The new dominant failure mode is ES-shard activation, tracked separately. |
| Paths-filter docs-only out of smoke (original Phase C) | Already present at workflow level — [`pr.yml:23-28`](../../../../../.github/workflows/pr.yml#L23-L28) (pull_request) + [`pr.yml:31-36`](../../../../../.github/workflows/pr.yml#L31-L36) (push). | Docs-only PRs skip the whole `pr` workflow (and therefore the smoke job) via top-level `paths-ignore`. The "Phase C split" goal is partially achieved without a new workflow file. |

The new dominant failure mode on main is [`bug_smoke_seed_es_unavailable_shards_race`](../bug_smoke_seed_es_unavailable_shards_race/idea.md) — ES 9.4.1 primary shard takes >1 minute to activate on cold GHA runners, exposed by PR #291's compose-up speedup that removed the prior ambient warmup. That bug is owned separately; do not roll it into this idea.

## Residual scope (what's actually left)

One change, narrow scope, ~20 LOC:

**Drop `push: branches: [main]` from `pr.yml`'s trigger surface.** The workflow at [`pr.yml:29-36`](../../../../../.github/workflows/pr.yml#L29-L36) still re-runs the entire pipeline on every merge to main, even though the exact SHA already passed the same gate on the PR. Every merge therefore contributes a redundant ~5–6m smoke run whose only signal is "the merge commit's tests still pass," which the PR's pre-merge run already established. Two-axis cost: (a) GHA minutes burnt on redundant work; (b) the `pr` workflow's red badge on `main` keeps reflecting transient post-merge flakes instead of real regressions, eroding signal.

### Implementation sketch

In [`.github/workflows/pr.yml`](../../../../../.github/workflows/pr.yml):

```yaml
on:
  pull_request:
    branches: [main]
    paths-ignore: [...]   # unchanged
  # DELETE the push: trigger entirely (lines 29-36).
```

Risk surface (low):
- **Branch protection.** GitHub branch protection on `main` requires named status checks to pass. If the protection list includes `pr / smoke`, dropping the push trigger means the post-merge run never produces that status. Verify the protection set lists only PR-context checks before dropping. ([CLAUDE.md `infra_foundation` §7.5](../../../../CLAUDE.md) lists branch protection setup as an operator handoff item — confirm the configured list with the operator.)
- **Staging deploy trigger.** If any other workflow keys off `pr.yml`'s push:main run (e.g., conditional deploy job), it'd break. Greppable via `workflow_run.workflows`.

### Alternative considered (and rejected)

Phase C from the original capture proposed "split smoke into a separate workflow that runs only on pull_request, gated behind paths-filter." With wall clock now at ~5–6m (vs the original ~15m timeout regime), the split costs more (new workflow file, duplicated setup, harder CI debugging) than the benefit. Revisit only if wall clock regresses past 10m.

## Open questions for /spec-gen

- **Branch protection check.** Confirm with operator that the `main` branch protection rule lists only PR-context status checks (e.g., `pr / backend`, `pr / smoke`, `pr / frontend`) and not separate push-context checks. If the latter exist, dropping `push: branches: [main]` would leave them perpetually pending. Default recommendation: drop the trigger and update the protection rule in the same step.

## Related ideas

- [`infra_ci_smoke_makeup`](../../implemented_features/2026_05_13_infra_ci_smoke_makeup/idea.md) — CLAUDE.md Bug Fix Protocol's call for an operator-path `make up` smoke gate after `infra_foundation` PR #4's first-run-testing incident. That idea is the upstream — the smoke job exists because of it; this idea is about tuning the trigger surface, not removing the gate.
- [`bug_smoke_seed_es_unavailable_shards_race`](../bug_smoke_seed_es_unavailable_shards_race/idea.md) — the current dominant failure mode on `main` smoke runs. P1. Owned separately.
- [`chore_drop_demo_seed_from_ci`](../../implemented_features/2026_05_28_chore_drop_demo_seed_from_ci/idea.md) (shipped) — retired this idea's Phase A #1 and Phase B Playwright concerns.
- [`chore_ci_perf_buildx_artifact_image_cache_xdist`](../../implemented_features/2026_05_28_chore_ci_perf_buildx_artifact_image_cache_xdist/idea.md) (shipped) — retired the 15-minute timeout pressure that motivated Phase B.

## Scope signals

- Workflow-only change — ~20 LOC delete in `.github/workflows/pr.yml`.
- Cross-coordination with operator on branch-protection rule list (one-line check).
- No code changes; no migration; no tests beyond confirming CI still gates PRs.
