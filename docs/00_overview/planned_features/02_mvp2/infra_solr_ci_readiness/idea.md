# infra_solr_ci_readiness — make Apache Solr a first-class CI engine (backend service container + smoke stability)

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

### Capability A — Solr service container in the backend job
Add a `solr` service to the `backend` job (mirror the Compose service: image, `SOLR_MODULES=ltr`, health check, published port 8983). The hard part is that GHA `services:` containers can't easily run the Compose `command`/init that uploads a configset + creates the collection — so either (a) bootstrap the configset/collection in a job step after the container is healthy, or (b) have `test_demo_seeding_ubi_full` (and `demo_seeding.py`) treat Solr as **optional**: probe reachability and skip the Solr scenario with a logged warning when absent (the same skip pattern the test already uses for Elasticsearch at `test_demo_seeding_ubi_full.py:142`). Option (b) is lighter and also makes the reseed robust for operators who don't run Solr.

### Capability B — Solr smoke stability
Diagnose the `solr-1 exited (1)` crash on the runner (capture `docker compose logs solr`). Likely fixes: cap `SOLR_HEAP`/`SOLR_JAVA_MEM` for the runner, lengthen the healthcheck `start_period`, or make the smoke job tolerant of Solr being down if Solr isn't on the tutorial path it exercises.

### Capability C — Reseed engine-tolerance (composes with A/B)
Make `reseed_demo_state` skip any engine scenario whose engine is unreachable rather than hard-failing the whole reseed — relates to `bug_reseed_failure_blocks_retry_arq_singleton_dedup`. Turns a hard CI failure into a logged partial-seed and improves operator UX.

## Why deferred (not fixed inline in PR #364)

Out of scope for the spec/plan batch + the two authorized bug fixes. It's genuine CI/infra work with a real risk surface (Solr-in-GHA stability is fiddly) and partially operator/shared-infra territory (workflow service containers). Fixing it inline would have ballooned a docs-heavy PR into a CI-infra investigation.

## Scope signals

- **CI workflow:** `.github/workflows/pr.yml` (backend `services:` + smoke job). **Product:** `demo_seeding.py` reseed engine-tolerance (Capability C). **Tests:** `test_demo_seeding_ubi_full.py` skip-guard.
- **No migration. No frontend.**

## Relationship to other work

- Direct consequence of `infra_adapter_solr` (#336) + `feat_demo_reseed_solr_and_steplog` (#348) shipping without CI plumbing.
- Composes with `bug_reseed_failure_blocks_retry_arq_singleton_dedup` (Capability C).
- Sibling `chore_solr_post_pipeline_followups` tracks other Solr follow-ons but not this CI gap.
