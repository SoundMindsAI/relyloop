# /healthz degraded → 503 blocks the UI when running an engine subset

**Date:** 2026-06-18
**Status:** Idea — bug captured during live operator use of the engine-subset feature
**Priority:** P1 — makes the just-shipped engine-subset feature's UI **unusable** for any subset that excludes ES or OS. The api never becomes `healthy`, so `ui` + `worker` (which gate on `depends_on: api: service_healthy`) never start. The only "workaround" is to run all three engines, which defeats the purpose of the subset feature. Confirmed reproducible (see below). (Dial down to P2 if the operator judges the feature's opt-in newness lowers urgency.)
**Origin:** Surfaced 2026-06-18 while running `RELYLOOP_ENGINES=solr make up` (the just-shipped [`feat_selective_engine_startup_and_demo`](../../../implemented_features/2026_06_17_feat_selective_engine_startup_and_demo/feature_spec.md) + [`feat_engine_version_selection`](../../../implemented_features/2026_06_18_feat_engine_version_selection/feature_spec.md)). Operator selected Solr-only; the `api` container went `unhealthy` and `ui` + `worker` never started.

## Problem

`/healthz` returns HTTP **503** whenever the `elasticsearch` or `opensearch` subsystem probe reports `unreachable` — even when the operator **intentionally** excluded that engine via `RELYLOOP_ENGINES`. The `api` Compose healthcheck is `curl -fs http://localhost:8000/healthz` ([docker-compose.yml:203](../../../../docker-compose.yml#L203)); `curl -f` fails on a 503, so the api healthcheck fails, the container is marked `unhealthy`, and `ui` + `worker` (which both declare `depends_on: api: condition: service_healthy` — [docker-compose.yml:237-239](../../../../docker-compose.yml#L237) for ui, the worker block likewise) **never start**.

Net effect: an operator who runs a legitimate, supported engine subset (`RELYLOOP_ENGINES=solr`, `es`, `es,solr`, etc.) gets a stack whose **UI never comes up** until they either run all three engines or clear the excluded-engine state.

### Root cause

[`backend/app/api/health.py:164-180`](../../../../backend/app/api/health.py#L164-L180) `overall_status()` hardcodes ES + OS as unconditionally-blocking:

```python
blocking_down = (
    s.db == "down"
    or s.redis == "down"
    or s.elasticsearch == "unreachable"   # <-- blocks even when ES is intentionally not running
    or s.opensearch == "unreachable"      # <-- same
    or s.solr == "unreachable"            # Solr already has the right pattern (see below)
)
```

**Solr already solved this** — it has a `not_configured` non-blocking opt-out (the comment at [health.py:175-178](../../../../backend/app/api/health.py#L175-L178): "operators can run the stack without Solr"). But ES and OS have **no equivalent opt-out**: when their container isn't running they report `unreachable`, not `not_configured`, so they trip `degraded`.

The health check predates the engine-subset feature (it was written when all three engines always ran). Now that engine subsets are a supported, advertised feature, the `elasticsearch`/`opensearch` blocking logic is stale.

### Observed `/healthz` body (Solr-only stack)

```json
{
  "status": "degraded",
  "subsystems": {
    "db": "ok", "redis": "ok", "openai": "configured",
    "elasticsearch": "unreachable",
    "opensearch": "unreachable",
    "solr": "not_configured",
    "elasticsearch_clusters": { "registered": 6, "healthy": 0, "unreachable": 6 }
  }
}
```

(The 6 unreachable registered clusters are a separate, secondary symptom — leftover ES/OS demo clusters in a persisted DB. They are NOT what trips the 503; the `overall_status` logic only keys on the *subsystem* probes, not the cluster aggregate. A `make reset` clears the clusters but does NOT fix the 503, because ES/OS subsystem probes are still `unreachable`.)

### Confirmed reproducible (2026-06-18)

Ran `make reset && RELYLOOP_ENGINES=solr make up` (clean slate). Result:

- `elasticsearch_clusters` dropped to `registered: 0` — the stale clusters are gone.
- `/healthz` is **still 503 / `degraded`** with `elasticsearch: unreachable`, `opensearch: unreachable`.
- `api` container: `Up (unhealthy)`. `ui` + `worker`: stuck at `Created` — never started.

This proves the root cause is the `overall_status` subsystem-probe logic (ES/OS hardcoded as blocking), NOT the stale clusters — a reset cannot fix it. A Solr-only stack's UI is unreachable until this is addressed.

(A transient `redis: down` was observed immediately post-reset but self-cleared within minutes — a startup-timing artifact, not a bug; redis pings in ~5ms from the api container and `/healthz` reports `redis: ok` once warm. Noted here only so a future debugger doesn't chase it.)

## Proposed capabilities

Make the `/healthz` blocking-engine set **engine-selection-aware** so an intentionally-excluded engine doesn't degrade the stack.

### A. Add a "not selected" non-blocking state for ES/OS (recommended)

Mirror Solr's `not_configured` opt-out. The engine subsystem probe reports a non-blocking state (`not_configured` / `not_selected`) when the engine isn't part of the operator's selection, and `overall_status` treats it as non-blocking — exactly as it already does for Solr.

The probe needs to know what the operator selected. Options for the signal (a fork for the spec):
- **A1:** read `COMPOSE_PROFILES` (install.sh already exports it) from the api container's environment.
- **A2:** read `RELYLOOP_ENGINES` directly (now loaded from `.env` after `bug_install_sh_env_file_not_loaded`).
- **A3:** infer from registered clusters / a settings field.

A1 is the most faithful (it's the literal source of truth for which engine services Compose started) but requires plumbing `COMPOSE_PROFILES` into the api container's env (it currently isn't passed to `api`). A2 is simpler but `RELYLOOP_ENGINES` isn't currently in the api env either. Either way this needs a one-line `environment:` addition in `docker-compose.yml`.

### B. (Alternative, weaker) Loosen the `ui`/`worker` depends_on

Drop `condition: service_healthy` → `condition: service_started` on the api dependency so the UI starts even when the api is degraded. **Not recommended** — it lets the UI come up against a genuinely-broken api (db down, etc.), removing a real safety gate. The right fix is "the api shouldn't be *degraded* for an intentionally-absent engine," not "let the UI ignore degraded."

## Scope signals

- **Backend:** ~30-60 LOC. `overall_status()` + the engine subsystem probe in `health.py`; add a `not_configured`/`not_selected` state for ES/OS; read the selection signal from settings/env.
- **Infra / Compose:** one `environment:` line to pass `COMPOSE_PROFILES` (or `RELYLOOP_ENGINES`) into the `api` service.
- **Tests:** unit tests for `overall_status` (ES excluded + unreachable → ok, not degraded; ES selected + unreachable → degraded); contract test for the `/healthz` 200-vs-503 status code under a subset selection.
- **Docs:** `infra_foundation` §7.3 documents the `/healthz` shape — note the new non-blocking state. Update `local-dev.md` "Selecting a subset of engines" trade-offs (it currently says "/healthz reports the unselected engines as unreachable — that's expected, not a problem"; that line is now half-true — it's expected, but it currently DOES break the UI).
- **Migration:** none.
- **Audit events:** N/A.

## Why not fixed inline now

Captured as an idea rather than fixed on the spot because:
- It needs a **design decision** on the selection signal (A1 vs A2 vs A3) + a Compose env-plumbing change — a small fork, but a real one a spec should lock.
- It touches the `/healthz` contract documented in `infra_foundation` §7.3, which per CLAUDE.md Absolute Rule #6 wants a spec patch first.
- The discovery surfaced during operator use of an unrelated task (running a Solr-only demo), not during work on the health endpoint.

## Relationship to other work

- **Direct consequence of** [`feat_selective_engine_startup_and_demo`](../../../implemented_features/2026_06_17_feat_selective_engine_startup_and_demo/feature_spec.md) (engine subsets) + [`feat_engine_version_selection`](../../../implemented_features/2026_06_18_feat_engine_version_selection/feature_spec.md). Those features made engine subsets selectable; this bug is the `/healthz` side that didn't get updated to match.
- The `local-dev.md` "Selecting a subset of engines" trade-off note will need a one-line correction when this ships (it currently understates the impact).
