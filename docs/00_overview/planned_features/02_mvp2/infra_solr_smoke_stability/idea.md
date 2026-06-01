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

### Capability B — Solr smoke-runner stability

Concretely, the work is:

1. **Capture logs.** Rerun the smoke job on a branch that intentionally lets Solr come up, capture `docker compose logs solr` from the failure surface. The existing failure-diagnostics upload at [`pr.yml:716-728`](../../../../../.github/workflows/pr.yml#L716-L728) covers `api worker postgres redis elasticsearch ui` but NOT `solr` — first sub-task is to ADD `solr` to that list so future failures auto-capture.
2. **Pick the lever, in priority order** (cheapest first):
   - **Lever 1 (heap-cap):** Set `SOLR_HEAP_SIZE=256m` in the smoke job's `env:` block (matching the backend job's `ES_JAVA_OPTS: -Xms256m -Xmx256m` at [`pr.yml:287`](../../../../../.github/workflows/pr.yml#L287)). Compose's `solr` service reads `${SOLR_HEAP_SIZE:-512m}` ([`docker-compose.yml:274`](../../../../../docker-compose.yml#L274)) — the override slot already exists.
   - **Lever 2 (start_period):** Bump the Solr healthcheck `start_period` from `30s` ([`docker-compose.yml:285`](../../../../../docker-compose.yml#L285)) to `60s` or `90s`. Solr 10 + LTR module first-load on a cold runner can take longer than ES/OS on the same hardware.
   - **Lever 3 (tolerance):** Make the smoke job tolerant of Solr being down — drop `solr` from any healthcheck the smoke step gates on, drop it from the `make up` boot expectation, accept "Solr crashed, other engines green" as smoke success. This is the last-resort lever because it gives up the per-PR signal that Solr can boot.
3. **Verify on a green smoke run** before declaring Phase 2 done.

The lever choice is the unresolved decision — it should be locked in the Phase 2 spec based on the log evidence.

## Scope signals

- **Backend:** none.
- **Frontend:** none.
- **Migration:** none.
- **Config:** smoke job environment (one new env var, or a YAML edit to the healthcheck block).
- **Audit events:** N/A (no state mutations, pre-MVP2 anyway).

## Why deferred

The lever choice depends on log evidence that doesn't exist yet. Bundling a "we don't know what the fix is" item into Phase 1 would have delayed the unblock for the backend job (which has a clean, known fix). Splitting lets Phase 1 ship with high confidence and lets Phase 2 be driven by data.

## Relationship to other work

- Pairs with `infra_solr_ci_readiness` Phase 1 ([shipped spec](../../../implemented_features/2026_06_01_infra_solr_ci_readiness/feature_spec.md)). Phase 1 fixed the `backend` job; this work fixes the `smoke` job. Together they take `pr.yml` from "red on every branch" to "green on every branch."
- Sibling [`chore_solr_post_pipeline_followups`](../chore_solr_post_pipeline_followups/idea.md) tracks the live-Solr integration tests scaffolded but not exercised when Solr shipped. Phase 2 doesn't touch those — it's purely about runner stability.
- Independent of [`bug_reseed_failure_blocks_retry_arq_singleton_dedup`](../bug_reseed_failure_blocks_retry_arq_singleton_dedup/idea.md) — that bug is in the reseed Arq-dedup path, not the smoke/CI path.
