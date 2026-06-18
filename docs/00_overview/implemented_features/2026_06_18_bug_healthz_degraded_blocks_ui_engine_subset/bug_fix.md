# Bug fix — bug_healthz_degraded_blocks_ui_engine_subset

**Release:** mvp2
**Status:** Complete (PR #559, merged 2026-06-18 `ad2992a4`)
**Source idea:** [idea.md](./idea.md)
**Branch:** `bug_healthz_degraded_blocks_ui_engine_subset`
**Type:** bug fix — medium (this skill's scope)
**Date:** 2026-06-18

## Problem

Running an engine subset that excludes ES or OS (e.g. `RELYLOOP_ENGINES=solr`) brings up a stack whose **UI never starts**. `/healthz` returns 503 because `overall_status` treats `elasticsearch`/`opensearch == "unreachable"` as blocking — even when the operator *intentionally* excluded that engine. The api healthcheck (`curl -fs /healthz`) fails on the 503, the api goes `unhealthy`, and `ui` + `worker` (which `depends_on: api: service_healthy`) never start. The fix makes the health check distinguish "deliberately not running" from "down".

## Reproduction

Live, before the fix: `RELYLOOP_ENGINES=solr make up` → `/healthz` 503 (`elasticsearch: unreachable`, `opensearch: unreachable`), `api` unhealthy, `ui`/`worker` stuck `Created`. A `make reset` does NOT help (the cause is the subsystem probes, not stale clusters).

Regression test (fails on `main`, passes on this branch):

```bash
pytest backend/tests/unit/test_health.py::TestEngineSelectionAware -v
pytest backend/tests/unit/core/test_settings_selected_engines.py -v
```

## Root cause

The `/healthz` blocking-engine logic predates the engine-subset feature and hardcodes ES/OS as unconditionally-blocking. Solr already had the right pattern (a `not_configured` non-blocking opt-out); ES/OS had no equivalent, so an intentionally-absent engine reported `unreachable` → `degraded`.

- Owning layer: API (health endpoint) + settings
- Origin: [health.py:170-179](../../../../backend/app/api/health.py#L170-L179) (`overall_status` blocking set) + [health.py:285-292](../../../../backend/app/api/health.py#L285-L292) (handler probes ES/OS unconditionally)
- Propagation: [docker-compose.yml:203](../../../../docker-compose.yml#L203) (`api` healthcheck `curl -fs`) → ui/worker `depends_on: api: service_healthy`

## Fix design (locked decisions)

1. **Engine-selection signal = `COMPOSE_PROFILES` via a `Settings` field.** New `Settings.compose_profiles` (env `COMPOSE_PROFILES`, default `es,os,solr`) + a `selected_engines` property. Cites: `COMPOSE_PROFILES` is install.sh's source of truth for which engine services Compose started; default preserves the all-engines behavior exactly.
2. **New non-blocking state `not_selected` for ES/OS** (distinct from Solr's `not_configured` — different cause: excluded-by-selection vs host-unset). Added to the ES/OS `Literal`s in `Subsystems`. Cites: mirrors the Solr opt-out precedent already in the model.
3. **Skip the probe for an unselected engine** (don't just reinterpret its result) — saves the 200ms probe timeout and avoids a spurious HTTP call. Result indices kept stable via a `_not_selected()` substitution in the gather list.
4. **`overall_status` body unchanged** — `"not_selected" != "unreachable"`, so it's non-blocking automatically; only the docstring/comments updated. Cites: minimal change per CLAUDE.md Bug Fix Protocol Step 3.
5. **Compose plumbing:** pass `COMPOSE_PROFILES: ${COMPOSE_PROFILES:-es,os,solr}` into the `api` service environment. Cites: the api container didn't previously receive it.
6. **Fail-safe fallback:** an empty/unrecognized `COMPOSE_PROFILES` → all engines selected (conservative, pre-fix behavior).
7. **Scope: ES/OS only.** Solr already non-blocks via `not_configured` (its host is unset by default), so it doesn't trip the bug; leaving it untouched keeps the fix minimal.

This touches the `/healthz` contract documented in `infra_foundation` §7.3 (a new non-blocking wire value); the contract addition is documented in the health.py field descriptions + the local-dev runbook trade-off note.

## Regression test plan

| Layer | Path | What it asserts |
|---|---|---|
| unit (settings) | `backend/tests/unit/core/test_settings_selected_engines.py` | `selected_engines` parses subsets; empty/unrecognized → all three (fail-safe) |
| unit (handler) | `backend/tests/unit/test_health.py::TestEngineSelectionAware` | excluded engines → `not_selected` + 200; probe is actually skipped; a SELECTED-but-down engine still 503s while an excluded peer is `not_selected` |
| contract | `backend/tests/contract/test_health_contract.py` (existing, unchanged) | `/healthz` response shape still valid |

Operator-path verified live: `RELYLOOP_ENGINES=solr make up` → `/healthz` 200, `elasticsearch: not_selected`, `opensearch: not_selected`, api healthy, ui+worker started.

## Rollout

Code + one Compose env line. No migration, no data backfill. Default (`COMPOSE_PROFILES` unset → `es,os,solr`) preserves current all-engines behavior byte-for-byte. OpenAPI snapshot regenerated (`not_selected` added to the ES/OS enum). Operators on an existing all-engines stack see no change.

## Tangential observations

None. (The transient `redis: down` seen during the original repro self-cleared and was confirmed not a bug — already noted in idea.md.)
