# Runbook: debugging `POST /api/v1/_test/demo/reseed`

Operator playbook for the demo-state reseed endpoint
(`feat_home_demo_reseed_endpoint`). Covers how to call the endpoint,
inspect the Postgres advisory lock, decode each error envelope, and
recover from the two terminal failure modes (`SEED_FAILED` on a normal
mid-flight error vs. `SEED_FAILED` on the `httpx.ReadTimeout` edge).

## Quick reference

| Symptom | First check |
|---|---|
| Dashboard "Reset to demo state" toast says `SEED_IN_PROGRESS` (409) | Another reseed is in flight; wait ~10s then retry. If it never frees, inspect `pg_locks` (next section). |
| Dashboard toast says `Reseed failed: SEED_FAILED` | Mid-flight error during the orchestration. Check `make logs api` for `demo_reseed_failed`. If the failure was on the `httpx.ReadTimeout` edge: `docker compose restart api` before retry. |
| Dashboard toast says "Reseed in progress or unreachable — refresh the page in a moment" | Client-side 180s abort OR raw network failure. Backend may still be running. Refresh; do NOT click the button again. |
| `POST /api/v1/_test/demo/reseed` returns 404 `RESOURCE_NOT_FOUND` outside dev | Expected — the endpoint is gated by `Settings.environment == "development"`. Staging/production set `ENVIRONMENT=staging`/`production` so the endpoint disappears. |
| `make logs api` shows `demo_reseed_advisory_unlock_returned_false` | The Postgres session reported the lock was not held when unlock fired. Indicates a code-path bug (the `acquired` sentinel was true but the lock vanished); file a bug. |

## Endpoint contract

```text
POST /api/v1/_test/demo/reseed   (empty body)
  200 → { "clusters_created": 4, "query_sets_created": 4,
          "studies_completed": 4, "proposals_created": 4,
          "duration_ms": <int> }
  404 → { "detail": { "error_code": "RESOURCE_NOT_FOUND", ... } }
        (when ENVIRONMENT != "development")
  409 → { "detail": { "error_code": "SEED_IN_PROGRESS",
                      "message": "...", "retryable": true } }
  503 → { "detail": { "error_code": "SEED_FAILED",
                      "message": "...", "retryable": true } }
```

Manual call from inside the API container (the handler self-calls
`http://localhost:8000`, so an in-container curl uses the same loopback):

```bash
docker compose exec api curl -sS -X POST \
  -H 'Content-Type: application/json' \
  http://localhost:8000/api/v1/_test/demo/reseed -d '{}'
```

Manual call from the host shell:

```bash
curl -sS -X POST -H 'Content-Type: application/json' \
  http://localhost:8000/api/v1/_test/demo/reseed -d '{}'
```

## Inspecting the advisory lock

The route handler acquires a Postgres session-level advisory lock on a
dedicated pinned `AsyncConnection`. The lock key is derived from
`blake2b("demo:reseed")` → signed int64. To list live advisory locks
(across all connections):

```bash
docker compose exec postgres psql -U relyloop -d relyloop -c \
  "SELECT pid, locktype, mode, granted, classid, objid
   FROM pg_locks WHERE locktype = 'advisory';"
```

If a reseed is in flight you'll see exactly one row with `granted = t`.
After the handler returns, the row disappears.

If the API process crashed mid-reseed, the session-level lock auto-
releases when the connection closes. If the row lingers anyway (e.g.,
because the Postgres backend hasn't yet noticed the dead client), force
a release with:

```bash
docker compose restart postgres
```

(The lock is session-scoped; restarting Postgres terminates every
connection.)

## Error-code playbook

### `SEED_IN_PROGRESS` (409)

Another reseed is holding the lock. Two normal cases:

1. **Operator double-clicked the dashboard button.** Wait — the in-flight
   request will release the lock when it finishes (success OR cleanup).
   The toast wording explicitly tells the user to wait.
2. **Concurrent automated reseeds.** Same — wait. The retry semantics
   are the same as case 1.

Abnormal cases (escalate if observed):

* The lock is held but no `demo_reseed_started` log line appears within
  the last 10 minutes. Indicates a connection leak; rotate the API
  container.

### `SEED_FAILED` (503) — normal mid-flight failure

A self-call to `/api/v1/*` or an engine PUT/POST returned non-2xx, or
the API process raised. The route handler's cleanup pass ran
(TRUNCATEs the 10 demo tables + DELETEs the 4 demo indices). Demo state
is consistent after the handler returns.

**Recovery:** retry the reseed. No restart needed.

Diagnostic logs to inspect:

```bash
docker compose logs api | grep -E 'demo_reseed_(failed|cleanup|api_call_started)' | tail -30
```

You should see:

1. `demo_reseed_started`
2. `demo_reseed_truncate_committed`
3. A sequence of `demo_reseed_api_call_started` entries.
4. `demo_reseed_failed extra={exc_class=..., exc=...}` — root cause.
5. `demo_reseed_cleanup_truncated` — cleanup TRUNCATEd successfully.
6. `demo_reseed_advisory_unlock extra={released=True}`.

### `SEED_FAILED` (503) — `httpx.ReadTimeout` edge

A single self-call exceeded `demo_reseed_per_call_http_timeout_s`
(default 120s; configurable 30..600). The handler unwound and returned
503, but the server-side handler invoked by the timed-out self-call
**may still be completing** in the background. That late commit can
race a naive retry's cleanup pass and produce inconsistent state
(per spec §10 Threat 4).

**Recovery: required restart.** Before retrying, run:

```bash
docker compose restart api
```

This terminates the abandoned server-side handler and clears its
pending writes. Then re-fire the reseed:

```bash
curl -sS -X POST -H 'Content-Type: application/json' \
  http://localhost:8000/api/v1/_test/demo/reseed -d '{}'
```

How to distinguish a ReadTimeout from other 503s: look for
`exc_class=ReadTimeout` (or `exc_class=TimeoutException`) in the
`demo_reseed_failed` log line. If the exception class is anything else
(`ConnectError`, `HTTPStatusError`, etc.), the normal-recovery path
applies — no restart needed.

## Configuring the per-call timeout

The only knob is `Settings.demo_reseed_per_call_http_timeout_s` (default
120, range 30..600 per FR-4b). To override locally, set the env var on
`docker compose up`:

```bash
DEMO_RESEED_PER_CALL_HTTP_TIMEOUT_S=180 docker compose up -d api
```

Per FR-4 there is **no outer wall-clock timeout**; this is the only
timeout. The orchestrator runs to natural completion. A value below
30 or above 600 fails at boot with a Pydantic `ValidationError`.

## When the host-shell CLI is a better tool

If repeated reseed calls are needed (e.g., during demo prep with iterative
fixture changes) AND the dashboard toast UI gets in the way, fall back to
the host-shell CLI:

```bash
make seed-demo FORCE=1
```

The CLI runs against the same Postgres + ES + OS containers but does
NOT acquire the advisory lock, so a concurrent dashboard reseed could
race the CLI. Pick one OR the other for any given reseed window.

## Related references

* [`docs/00_overview/planned_features/feat_home_demo_reseed_endpoint/feature_spec.md`](../00_overview/planned_features/feat_home_demo_reseed_endpoint/feature_spec.md)
* [`docs/01_architecture/api-conventions.md`](../01_architecture/api-conventions.md) — `SEED_IN_PROGRESS` + `SEED_FAILED` envelope rows.
* [`backend/app/services/demo_seeding.py`](../../backend/app/services/demo_seeding.py) — orchestrator + `DEMO_RESEED_LOCK_KEY` derivation.
* [`backend/app/api/v1/_test.py`](../../backend/app/api/v1/_test.py) — route handler `reseed_demo` + cleanup helper.
