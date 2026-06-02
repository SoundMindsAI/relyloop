# infra_solr_smoke_stability — stabilize Solr in the smoke job

**Date:** 2026-06-01
**Status:** Idea — deferred from `infra_solr_ci_readiness` Phase 1 because the right stabilization lever depends on log evidence from a smoke-runner failure
**Priority:** P1 — the `smoke` CI job stays red on every branch until this ships (`infra_solr_ci_readiness` Phase 1 only addressed the `backend` job's `pr.yml` failure)
**Origin:** Extracted from `infra_solr_ci_readiness` Phase 2 (FR-7 / D-5) — see [`feature_spec.md`](../../../implemented_features/2026_06_01_infra_solr_ci_readiness/feature_spec.md) §3. Phase 1 (shipped, PR #367) added test-skip + orchestrator skip-on-unreachable for the backend job; this work makes the smoke job's Solr container reliably boot.
**Depends on:** Phase 1 merged (so the contract of "Solr is allowed to be missing in CI" is established) + at least one captured smoke-runner failure log (`docker compose logs solr` from a smoke-job failure run; cite the run URL in the spec).

## Problem

After Phase 1 ships, the `pr.yml` `backend` job goes green (the heavy-lane reseed test no longer requires Solr). But the `smoke-test` job is independent — it runs `make up` which brings up the full Compose stack including the `solr` service ([`docker-compose.yml:271-285`](../../../../../docker-compose.yml#L271-L285)). On the GHA runner, `relyloop-solr-1 exited (1)` during boot, failing the smoke job at `Makefile:109`. Until smoke is green, no `pr.yml` run can fully pass.

The diagnostic step that gates this work is reading the actual `docker compose logs solr` from a failing smoke run. Without it, picking a lever is guesswork.

## Proposed capabilities

Concretely, the work is:

1. **Capture logs.** Rerun the smoke job on a branch that intentionally lets Solr come up, capture `docker compose logs solr` from the failure surface. The existing failure-diagnostics upload at [`pr.yml:716-728`](../../../../../.github/workflows/pr.yml#L716-L728) (the smoke-test job's "Collect docker compose logs on failure" step) covers `api worker postgres redis elasticsearch ui` but is missing **both** `solr` (line 271 in compose, the one this work is about) **and** `opensearch` (line 235 in compose, a pre-existing gap worth fixing in the same edit). First sub-task is to add both to that list so future smoke failures auto-capture.
2. **Pick the lever, in priority order** (cheapest first):
   - **Lever 1 (heap-cap):** Set `SOLR_HEAP_SIZE=256m` in the smoke job's `env:` block (matching the backend job's `ES_JAVA_OPTS: -Xms256m -Xmx256m` at [`pr.yml:287`](../../../../../.github/workflows/pr.yml#L287)). Compose's `solr` service reads `${SOLR_HEAP_SIZE:-512m}` ([`docker-compose.yml:274`](../../../../../docker-compose.yml#L274)) — the override slot already exists.
   - **Lever 2 (start_period):** Bump the Solr healthcheck `start_period` from `30s` ([`docker-compose.yml:285`](../../../../../docker-compose.yml#L285)) to `60s` or `90s`. Solr 10 + LTR module first-load on a cold runner can take longer than ES/OS on the same hardware.
   - **Lever 3 (tolerance):** Make the smoke job tolerant of Solr being down — drop `solr` from any healthcheck the smoke step gates on, drop it from the `make up` boot expectation, accept "Solr crashed, other engines green" as smoke success. This is the last-resort lever because it gives up the per-PR signal that Solr can boot.
3. **Verify on a green smoke run** before declaring the work done.

The lever choice is the unresolved decision — it should be locked in `feature_spec.md` based on the log evidence.

### Recommended sequencing — two PRs, not one

Sub-task 1 (adding `solr` + `opensearch` to the failure-diagnostics collect list) is a one-line YAML edit with zero risk. It can ship in a tiny standalone PR before the lever-choice work even begins — and it MUST ship first, because the lever choice depends on Solr logs from a failing smoke run that this fix is what produces. Lever PR is then driven by the captured evidence. Don't bundle them: a one-line diagnostic-capture PR can merge today; the lever PR waits on data.

## Scope signals

- **Backend:** none.
- **Frontend:** none.
- **Migration:** none.
- **Config:** smoke job environment (one new env var, or a YAML edit to the healthcheck block).
- **Audit events:** N/A (no state mutations, pre-MVP2 anyway).

## Why log evidence gates the lever choice

The three levers address three different failure modes: heap-cap addresses OOM-kill, start_period bump addresses healthcheck-races-startup, and tolerance bypasses the issue entirely. They are NOT interchangeable — picking the wrong one ships a fix that doesn't fix anything. Until we read what `docker compose logs solr` actually says when the smoke runner crashes the container, the lever choice is guesswork. That is why sub-task 1 (diagnostics capture) is sequenced first.

## Relationship to other work

- Pairs with `infra_solr_ci_readiness` Phase 1 ([shipped spec](../../../implemented_features/2026_06_01_infra_solr_ci_readiness/feature_spec.md)). Phase 1 fixed the `backend` job; this work fixes the `smoke` job. Together they take `pr.yml` from "red on every branch" to "green on every branch."
- Sibling [`chore_solr_post_pipeline_followups`](../chore_solr_post_pipeline_followups/idea.md) tracks the live-Solr integration tests scaffolded but not exercised when Solr shipped. This work doesn't touch those — it's purely about runner stability.
- **Coordinate with** [`chore_solr_cred_backfill_needs_api_restart`](../chore_solr_cred_backfill_needs_api_restart/idea.md). That chore is in the `make up` boot path: `scripts/install.sh` step 5a backfills the Solr cred into a running stack, but the `api` / `worker` settings cache memoizes the YAML at process start. The smoke job runs `make up` on a fresh runner (no pre-existing cred file, no pre-running api), so the cached-stale-creds failure mode does NOT trip there — but if smoke-stabilization work ever changes the boot ordering or pre-stages a cred file, re-check this. Today the two are independent.
- Independent of [`bug_reseed_failure_blocks_retry_arq_singleton_dedup`](../bug_reseed_failure_blocks_retry_arq_singleton_dedup/idea.md) — that bug is in the reseed Arq-dedup path, not the smoke/CI path.
