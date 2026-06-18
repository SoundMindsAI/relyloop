# /healthz Solr subsystem ignores the local Solr container (always not_configured)

**Date:** 2026-06-18
**Status:** Idea — tangential observation, captured during the bug_healthz_degraded_blocks_ui_engine_subset fix
**Priority:** P2 — minor accuracy gap; non-blocking and pre-existing, but mildly confusing for subset-engine operators.
**Origin:** Noticed while implementing `bug_healthz_degraded_blocks_ui_engine_subset` (PR forthcoming). Cites the CLAUDE.md tangential-discoveries rubric row "Fix requires a separate subsystem … and no immediate path to inline" — the proper fix forks on `solr_host` semantics (which the SolrAdapter + demo seeding also read), so an inline fix would expand the PR's blast radius (the "fix while you're in there" trap).

## Problem

In a running stack — even a full three-engine stack — `/healthz` reports `subsystems.solr: "not_configured"` whenever `SOLR_HOST` is unset, which it always is for the `api` container: the `api` service `environment:` block in [`docker-compose.yml`](../../../../docker-compose.yml) does NOT set `SOLR_HOST`. So `settings.solr_host` is always `None` in the api → the Solr probe is skipped → `subsystems.solr` is always `not_configured`, regardless of whether the local `solr` container is up and healthy.

Concretely surfaced in a Solr-only stack (`RELYLOOP_ENGINES=solr`): the one engine that IS running (Solr) reports `not_configured`, while the two that are NOT running (ES/OS) report `not_selected` (after the engine-selection fix). An operator could reasonably expect the running Solr to report `reachable`.

This is **non-blocking** (`not_configured` doesn't trigger `degraded`), so it never broke anything — it's an accuracy/observability gap, not a failure. Distinct from `bug_healthz_degraded_blocks_ui_engine_subset`, which was about ES/OS *blocking* the stack.

- Owning layer: API (health endpoint) + Compose env + settings
- Origin: [`health.py:290-292`](../../../../backend/app/api/health.py#L290-L292) (`solr_base_url = … if settings.solr_host else None`) + the `api` service env in `docker-compose.yml` (no `SOLR_HOST`)

## Proposed capabilities

Make `/healthz` reflect the local Solr container's reachability when Solr is part of the operator's selection. Options (a fork for the spec/fix):

- **A. Pass `SOLR_HOST=solr` into the api env when `solr` is in `COMPOSE_PROFILES`.** Smallest change, but `solr_host` is currently an explicit opt-in (its description says "operators who don't want to run the Solr service leave this unset") and the SolrAdapter / demo seeding read it — setting it changes more than just /healthz. Needs a check of every `solr_host` consumer.
- **B. Add a selection-aware local-Solr probe** that mirrors the ES/OS hardcoded-URL pattern (`http://solr:8983`) gated on `"solr" in selected_engines`, independent of `solr_host` (which stays the "registered external Solr host" signal). Cleaner separation, slightly more code.

Recommended: **B** — keep `solr_host` meaning "externally-configured Solr host" and add a local-container probe gated on engine selection, consistent with how ES/OS are now handled.

## Scope signals

- **Backend:** ~20-40 LOC in `health.py` (+ maybe a `probe_solr` reuse). Possibly a `Subsystems.solr` Literal already has `reachable`/`unreachable`/`not_configured`; add `not_selected` for the excluded case.
- **Infra / Compose:** option A adds one env line; option B adds none.
- **Tests:** unit tests for the solr-selected-reachable / solr-excluded-not_selected cases.
- **Migration:** none.

## Why not fixed inline

The `bug_healthz_degraded_blocks_ui_engine_subset` PR was scoped to the ES/OS *blocking* bug (the thing that broke the UI). Solr's behavior there is unchanged and non-blocking, so folding a `solr_host`-semantics change into that PR would mix an accuracy improvement (with its own design fork + multi-consumer blast radius) into a focused bug fix — exactly the "fix while you're in there" anti-pattern. Captured here for a separate, deliberate pass.
