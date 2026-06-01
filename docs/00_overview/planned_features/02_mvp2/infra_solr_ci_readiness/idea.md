# infra_solr_ci_readiness — unblock `pr.yml` against Solr (skip-on-unreachable in the reseed + smoke healthboot)

**Date:** 2026-06-01
**Status:** Idea — tangential discovery during the MVP2 backlog spec/plan batch (PR #364 CI).
**Type:** `infra_`
**Priority:** P1 — the full `pr.yml` backend + smoke jobs are deterministically red against any branch because Solr is not CI-ready. This blocks green CI on every PR until resolved (the same class of "green is impossible" problem that `bug_backend_suite_nondeterministic_caplog_isolation` addressed for the unit layer).

## Origin

Surfaced on PR #364 (MVP2 backlog batch). After fixing every in-scope failure (caplog isolation, contract allowlists, `click:0` drift, migration-0021 downgrade target), two failures remained, both Solr-CI-readiness issues, both pre-existing and unrelated to that PR's changes:

1. **`backend (lint + typecheck + tests + coverage)`** → `backend/tests/integration/test_demo_seeding_ubi_full.py::test_full_reseed_produces_8_lists_8_studies_per_rung_correct` fails with `httpx.ConnectError: [Errno -3] Temporary failure in name resolution`.
2. **`smoke (operator-path tutorial flow)`** → `make up` aborts at *Bring up the stack* with `container relyloop-solr-1 exited (1)` → `make: *** [Makefile:109: up] Error 1`.

## Problem

Solr shipped (`infra_adapter_solr`, PR #336, 2026-05-31) and the demo reseed was extended to seed a Solr scenario (`feat_demo_reseed_solr_and_steplog`, PR #348, 2026-05-31). But the CI plumbing was never updated for Solr:

- **Backend job has no Solr service container.** [`.github/workflows/pr.yml`](../../../../../.github/workflows/pr.yml) `backend` job `services:` defines `postgres:17`, `redis:8`, `elasticsearch:9.4.1`, `opensearchproject/opensearch:3.6.0` — **no Solr**. The demo reseed ([`backend/app/services/demo_seeding.py`](../../../../../backend/app/services/demo_seeding.py), host→compose URL map `http://localhost:8983 → http://solr:8983`) seeds the Solr scenario unconditionally, so `test_demo_seeding_ubi_full` `ConnectError`s on a host that doesn't resolve in the backend job's network.
- **Smoke's Solr container exits(1).** The smoke job runs the full Compose stack via `make up`; the `solr` service (`solr:10.0`, `SOLR_MODULES=ltr`, configset bootstrap) starts then immediately `exited (1)` on the GHA runner — likely heap/resource limits or the module/configset bootstrap failing under the runner's constraints. This is distinct from the backend gap: here Solr is *present* but unstable.

Net effect: post-2026-05-31, no full `pr.yml` run can go green on any branch. This was masked while `SKIP_HEAVY_CI=true` (2026-05-29 → 2026-05-31) and only surfaced once heavy CI was restored.

## Proposed capabilities

### Capability A — Skip-on-unreachable in the heavy-lane reseed test (locked: option B)
**Decision:** do NOT add a `solr` service container to the `backend` job. Instead, mirror the existing ES skip pattern at [`test_demo_seeding_ubi_full.py:142`](../../../../../backend/tests/integration/test_demo_seeding_ubi_full.py#L142) for Solr — probe reachability and skip the Solr scenario (with a logged warning) when absent. Implementation lives in both the test (skip the assertion that depends on the Solr scenario succeeding) and the product (`demo_seeding.py` orchestrator skips the Solr scenario when `http://solr:8983` is unreachable, mirroring how ES is handled today). This is Capability A's chosen approach; the original "(a) bootstrap configset/collection in a job step after the container is healthy" alternative was rejected as heavier-than-warranted given the existing ES skip precedent and the fact that no `test_solr_*` lane currently runs against the heavy-lane backend job.

**Why option (b) over (a):**
- Mirrors the ES pattern already in the test, keeping the integration-test skip-policy uniform across engines.
- Side-benefits operator UX: an operator who hasn't started Solr locally gets a logged partial-seed instead of a hard reseed failure (this is Capability C — now folded into A's product-side change).
- GHA `services:` containers don't run the Compose `command`/configset-upload step that real local Solr needs (`make seed-solr` uploads configsets to ZooKeeper) — bootstrapping that as a job step would either duplicate the seeding script or fragilely subset it.
- Keeps the backend job lean (Solr's image is the heaviest of the four engines).

### Capability B — Solr smoke stability (open: diagnose-first)
Diagnose the `solr-1 exited (1)` crash on the runner. Step 1 is **capture logs**: rerun smoke locally with `docker compose logs solr` to surface the real failure (heap OOM vs LTR module load vs `./data/solr` permission vs healthcheck timing). Likely fixes, in order of probability:
- Cap `SOLR_HEAP` for the runner — Solr's compose default is `${SOLR_HEAP_SIZE:-512m}` ([docker-compose.yml:274](../../../../../docker-compose.yml#L274)); the smoke runner is already memory-tight (ES + OS + Solr + Postgres + Redis + API + UI on one `ubuntu-24.04`). Mirror the backend job's `ES_JAVA_OPTS: -Xms256m -Xmx256m` pattern — set `SOLR_HEAP_SIZE=256m` in the smoke job environment.
- Lengthen the healthcheck `start_period` (currently `30s` at [docker-compose.yml:285](../../../../../docker-compose.yml#L285)) — Solr 10 + LTR module first-load on a cold runner can take longer than ES/OS.
- Last resort: make the smoke job tolerant of Solr being down (drop Solr from the compose-logs collection on failure, don't gate `make up` on Solr health). The tutorial path the smoke test exercises is ES-only today, so this is an acceptable fallback if the heap/timing fixes don't stabilize Solr.

Spec needs to commit to one path after seeing the logs; default lean is heap-cap → start_period → tolerance, in that order.

### Capability C — Folded into Capability A
The reseed engine-tolerance change (skip any engine scenario whose engine is unreachable rather than hard-failing) is now part of Capability A's product-side scope — the test-side skip and the orchestrator-side skip ship symmetrically so the reseed is engine-tolerant for both CI and operators. The earlier compose-with-`bug_reseed_failure_blocks_retry_arq_singleton_dedup` framing remains: when the orchestrator skips an unreachable engine cleanly, it's no longer a "failed reseed" that wedges the Arq singleton dedup — it's a "partial reseed" with all reachable engines green.

## Why deferred (not fixed inline in PR #364)

Out of scope for the spec/plan batch + the two authorized bug fixes. It's genuine CI/infra work with a real risk surface (Solr-in-GHA stability is fiddly) and partially operator/shared-infra territory (workflow service containers). Fixing it inline would have ballooned a docs-heavy PR into a CI-infra investigation.

## Scope signals

- **CI workflow:** `.github/workflows/pr.yml` (backend `services:` + smoke job). **Product:** `demo_seeding.py` reseed engine-tolerance (Capability C). **Tests:** `test_demo_seeding_ubi_full.py` skip-guard.
- **No migration. No frontend.**

## Relationship to other work

- Direct consequence of `infra_adapter_solr` (#336) + `feat_demo_reseed_solr_and_steplog` (#348) shipping without CI plumbing.
- Composes with [`bug_reseed_failure_blocks_retry_arq_singleton_dedup`](../bug_reseed_failure_blocks_retry_arq_singleton_dedup/idea.md): once the orchestrator skips unreachable engines instead of failing, the singleton-dedup wedge it documents stops triggering on a missing-Solr scenario. This idea fixes the root cause for one engine; the sibling addresses the broader Arq-result-cache wedge that would still bite for other failure modes.
- Sibling [`chore_solr_post_pipeline_followups`](../chore_solr_post_pipeline_followups/idea.md) tracks other Solr follow-ons (live-Solr integration tests, `make seed-solr` verification, `/healthz` solr probe) but not this CI gap — the two are coordinate-only, no ordering dependency.
- No conflict with the other Solr-touching MVP2 ideas — this is purely CI/test-skip + smoke healthboot.

## Decisions locked

- **D-1 (Capability A):** Skip-on-unreachable in both `test_demo_seeding_ubi_full.py` AND `backend/app/services/demo_seeding.py`. No `solr` service container in the GHA backend job. Mirrors the ES skip at [`test_demo_seeding_ubi_full.py:142`](../../../../../backend/tests/integration/test_demo_seeding_ubi_full.py#L142).
- **D-2 (Capability C folding):** The orchestrator-side and test-side skips ship together as one feature, not as separate phases. Keeping them in lock-step prevents drift between what CI sees and what operators see.

## Open questions for /spec-gen

- **Q-1 (Capability B path):** After capturing `docker compose logs solr` from a smoke-runner failure, which lever stabilizes Solr — heap-cap (`SOLR_HEAP_SIZE=256m`), longer `start_period`, or smoke-job tolerance for Solr-down? Recommended default: try heap-cap first (cheapest, matches ES/OS pattern), then escalate. /spec-gen should write the spec to commit to one path based on the observed log evidence.
- **Q-2 (skip-log granularity):** When the orchestrator skips Solr in CI, should it emit a single WARN line, an info-level structured event, or both? Recommended default: structured info event + one WARN line at the end of the reseed summarizing skipped engines (so the test can assert on the WARN, not transient INFO).
- **Q-3 (test-side: full skip vs partial-assert):** When Solr is unreachable in the heavy-lane test, do we skip the whole test (current ES pattern) or skip only the Solr-specific assertions and still validate ES + OS + the 7/8 lists path? Recommended default: skip only Solr-specific assertions — preserves the AC-1 8-list assertion when ES is reachable (which it always is in CI). This is a small but real deviation from the ES skip precedent and worth pinning in the spec.
