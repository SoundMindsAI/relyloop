# Implementation Plan — feat_home_demo_reseed_endpoint

**Date:** 2026-05-23
**Status:** Complete (PR #228, merged 2026-05-24 as squash commit `ad6ff826`)
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy source(s):** CLAUDE.md (Absolute Rules #2, #6, #8, #10), [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md), [`docs/03_runbooks/local-dev.md`](../../../03_runbooks/local-dev.md)

---

## 0) Planning principles

- Spec traceability first: every story/task maps to FR IDs from the spec.
- The 14-cycle cross-model convergence in the spec locked the design — this plan implements that design, it does not redesign.
- Backend before frontend (the UI talks to the endpoint; no point shipping the button before the endpoint accepts traffic).
- Test-driven coverage gates each story (no DoD passes without contract/integration assertions).
- The session-level advisory lock + dedicated pinned `AsyncConnection` (FR-3) is the single hardest-to-get-right piece — it gets its own story with explicit `pg_locks` observer integration coverage.

## 1) Scope traceability (FR → epics/phases)

| FR ID | Epic / Story | Notes |
|---|---|---|
| FR-1 (service module `reseed_demo_state`) | Epic 1 / Story 1.1 | Backbone of the feature; imports `SCENARIOS` from CLI, takes dual `httpx.AsyncClient`, applies `_resolve_engine_base_url`. |
| FR-1c (dual-client construction contract) | Epic 1 / Story 1.2 | Handler-side concern; client instantiation + timeout + `auth=` mapping. |
| FR-1d (in-container engine base-URL resolver) | Epic 1 / Story 1.1 | Pure function inside `demo_seeding.py`; unit-tested. |
| FR-2 (endpoint `POST /api/v1/_test/demo/reseed`) | Epic 1 / Story 1.2 | Route handler in `backend/app/api/v1/_test.py`. |
| FR-3 (session-level advisory lock + pinned `AsyncConnection`) | Epic 1 / Story 1.2 | Acquire + release via dedicated `engine.connect()`; explicit `pg_advisory_unlock` in `finally`; logged. |
| FR-4 (no outer timeout; per-call HTTP ceiling only) | Epic 1 / Story 1.2 | Handler instantiates clients with `timeout=settings.demo_reseed_per_call_http_timeout_s`. |
| FR-4b (`Settings.demo_reseed_per_call_http_timeout_s`) | Epic 1 / Story 1.0 | Pydantic field with range validator (30..600). |
| FR-5 (superseded) | — | No work — D3's `demo_reseed_timeout_s` was removed per cycle-3 redesign. |
| FR-6 (UI button + dialog + toast) | Epic 2 / Story 2.1 | Extends `StartHereChecklist`. |
| FR-7 (env-guard contract test extension) | Epic 3 / Story 3.1 | Extend `test_test_endpoint_guard.py` + `test_openapi_surface.py`. |
| FR-8 (integration tests — AC-1..AC-5 + AC-12..AC-16) | Epic 3 / Story 3.2 | New `backend/tests/integration/test_demo_seeding.py`. |
| FR-9 (vitest dashboard button) | Epic 2 / Story 2.1 (DoD test bullets) | New `ui/src/__tests__/components/dashboard/start-here-checklist.spec.tsx`. |
| FR-10 (Playwright E2E real-backend) | Epic 3 / Story 3.3 | New `ui/tests/e2e/dashboard-reseed.spec.ts`. |

**No deferred phases.** The spec is single-phase delivery (§3 Phase boundaries). No `phase<N>_idea.md` tracking artifact needed.

## 2) Delivery structure

### Codebase conventions this plan must follow

- All repo functions take `db: AsyncSession` as first arg; use `await db.flush()` / `await db.commit()` per the service-layer commit-discipline pattern. The reseed service manages its own commits because it spans multiple transactions (FR-1).
- Services are async (`async def`). Domain layer is pure — no DB, no async (`_resolve_engine_base_url` qualifies).
- Models use `Mapped[]` typed columns (N/A for this feature — no new models).
- Routers return typed Pydantic response models; errors use `_err(status_code, code, message, retryable)` helper defined at `backend/app/api/v1/_test.py:40`.
- Config via `pydantic-settings`; new fields go in `backend/app/core/settings.py` with `Field(ge=..., le=...)` validators.
- All `__init__.py` exports updated via `__all__` (N/A — no new repo functions; no new models).
- Frontend: TanStack Query for server state; `sonner` for toasts (`import { toast } from 'sonner'`); shadcn `<AlertDialog>` for destructive confirmation.

### AI Agent Execution Protocol (applies to every story)

0. **Load context first**: read `architecture.md` and `state.md`. The spec ran 14 GPT-5.5 cycles — re-reading §19 decision log is mandatory before implementing the locking + timeout + dual-client design.
1. **Read scope**: verify story outcome + endpoints + interfaces + DoD.
2. **Implement backend first**: settings → service module → route handler.
3. **Run backend tests**: `make test-unit`, `make test-integration` (targeted to `test_demo_seeding.py`), `make test-contract`.
4. **Implement frontend** (Story 2.1 only).
5. **Run vitest** for component coverage + **Playwright real-backend** for E2E.
6. **Update docs/checklists** impacted by behavior changes in same PR.
7. **No migration** — schema unchanged.
8. **Attach evidence** in PR description: commands run, pass/fail, files changed.

Story completion is invalid if any step is skipped.

---

## Epic 1 — Backend: settings, service module, route handler

### Story 1.0 — Add `Settings.demo_reseed_per_call_http_timeout_s` field

**Outcome:** new Pydantic Settings field with `ge=30, le=600`, default 120s. Read by Story 1.2's handler when constructing the two `httpx.AsyncClient` instances.

**New files**: none.

**Modified files**

| File | Change |
|---|---|
| `backend/app/core/settings.py` | Add `demo_reseed_per_call_http_timeout_s: int = Field(default=120, ge=30, le=600, description=...)`. |

**Key interfaces** (Pydantic field — no function signature)

```python
# backend/app/core/settings.py — added inside class Settings(BaseSettings)
demo_reseed_per_call_http_timeout_s: int = Field(
    default=120,
    ge=30,
    le=600,
    description=(
        "Hard ceiling per single httpx self-call inside the demo reseed "
        "orchestrator. Default 120s — wide margin over the typical 5-10s "
        "scenario time. Per FR-4 there is NO outer wall-clock timeout; "
        "this is the ONLY timeout. If a single self-call exceeds this, "
        "httpx.ReadTimeout propagates -> orchestrator unwinds -> route "
        "handler runs cleanup -> returns 503 SEED_FAILED. Per §10 Threat "
        "4 the safe recovery on this edge requires `docker compose "
        "restart api` before retry."
    ),
)
```

**Tasks**
1. Add the field to the `Settings` class in `backend/app/core/settings.py`. Insert alphabetically near the other `demo_*` / `relyloop_*` settings.
2. Run `make typecheck` to confirm mypy accepts the addition.

**Definition of Done**
- The field is set on `get_settings()` and accessible from any service.
- New unit test in `backend/tests/unit/core/test_settings.py` (or extend existing settings tests) asserting (a) default is 120, (b) values below 30 and above 600 raise `ValidationError`, (c) env-var override via `DEMO_RESEED_PER_CALL_HTTP_TIMEOUT_S=180` reads correctly.
- `make lint && make typecheck && make test-unit` green.

---

### Story 1.1 — `backend/app/services/demo_seeding.py` (service module)

**Outcome:** new async orchestrator function `reseed_demo_state` that wipes the 10 demo tables, deletes the 4 demo indices, loops 4 scenarios via dual httpx clients (api + engine), and applies study renames. Plus the pure helper `_resolve_engine_base_url` for in-container hostname translation.

**New files**

| File | Purpose |
|---|---|
| `backend/app/services/demo_seeding.py` | Implements `reseed_demo_state` (FR-1) + `_resolve_engine_base_url` (FR-1d) + `_demo_reseed_lock_key` constant + `ReseedSummary` Pydantic model + `DemoSeedingError` exception. |
| `backend/tests/unit/services/test_demo_seeding.py` | Unit tests for `_resolve_engine_base_url`, `_demo_reseed_lock_key`, table-list-mirrors-CLI assertion, `ReseedSummary` construction. |

**Modified files**: none.

**Key interfaces**

```python
# backend/app/services/demo_seeding.py

from typing import Final
import hashlib
from pydantic import BaseModel
import httpx
from sqlalchemy.ext.asyncio import AsyncSession


class ReseedSummary(BaseModel):
    """Returned by reseed_demo_state on success."""
    clusters_created: int
    query_sets_created: int
    studies_completed: int
    proposals_created: int
    duration_ms: int


class DemoSeedingError(RuntimeError):
    """Raised by reseed_demo_state on any unrecoverable failure.

    The route handler catches this AND any other Exception, runs cleanup,
    and returns 503 SEED_FAILED. Defined as a distinct class for log
    discrimination (DemoSeedingError vs unexpected library exceptions).
    """


# Lock key — same blake2b -> signed int64 pattern as
# backend/workers/digest.py:236-240 and orchestrator.py:481-489.
# Single global key (no per-id suffix) because the demo dataset is a
# singleton.
DEMO_RESEED_LOCK_KEY: Final[int] = int.from_bytes(
    hashlib.blake2b(b"demo:reseed", digest_size=8).digest(),
    byteorder="big",
    signed=True,
)


def _resolve_engine_base_url(host_base_url: str) -> str:
    """Map the CLI's host-shell URLs to in-container Compose DNS names.

    The imported SCENARIOS constant from scripts/seed_meaningful_demos.py
    carries host_base_url values like "http://localhost:9200" (ES) and
    "http://localhost:9201" (OS) — correct from the host shell, wrong
    from inside the API container where "localhost" is the API itself.
    This function transparently maps to the Compose service DNS names.

    Pure / deterministic / no I/O. Per FR-1d.
    """
    mapping = {
        "http://localhost:9200": "http://elasticsearch:9200",
        "http://localhost:9201": "http://opensearch:9201",
    }
    if host_base_url not in mapping:
        raise ValueError(
            f"Unrecognized engine host URL: {host_base_url}. "
            f"Expected one of {sorted(mapping.keys())}."
        )
    return mapping[host_base_url]


async def reseed_demo_state(
    db: AsyncSession,
    api_client: httpx.AsyncClient,
    engine_client: httpx.AsyncClient,
) -> ReseedSummary:
    """Orchestrate a complete wipe + reseed of the 4 demo scenarios.

    Per FR-1:
      - Step 1a: TRUNCATE 10 demo tables (RESTART IDENTITY CASCADE), then COMMIT
        (commit before any self-call so the AccessExclusive lock releases — FR-1
        commit-ordering, AC-13).
      - Step 1b: DELETE 3 ES + 1 OS demo indices via engine_client + resolver.
      - Step 2: loop 4 scenarios from imported SCENARIOS:
          * engine_client: PUT {resolved}/{target}, PUT _doc, POST _refresh
          * api_client: POST /api/v1/clusters, query-templates, query-sets,
            query-sets/{id}/queries, judgment-lists/import, _test/studies/seed-completed
          * GET /api/v1/query-sets/{id}/queries to fetch query IDs for judgment import
      - Step 3: UPDATE studies SET name = :name WHERE id = :id (rename) via db.
      - Step 4: return ReseedSummary.

    Caller (route handler) owns:
      - Advisory-lock acquisition + release (on a dedicated AsyncConnection).
      - httpx.AsyncClient construction (with timeout=settings.demo_reseed_per_call_http_timeout_s).
      - Cleanup-on-failure pass.

    This function does NOT touch the advisory lock; that's the handler's job.
    """
    ...
```

**Pydantic schemas**

```python
class ReseedSummary(BaseModel):
    clusters_created: int   # always 4 on success
    query_sets_created: int # always 4
    studies_completed: int  # always 4
    proposals_created: int  # always 4
    duration_ms: int        # wall-clock ms start -> rename commit
```

**Tasks**
1. Create `backend/app/services/demo_seeding.py` with the module docstring referencing FR-1, FR-1d, §10 Threat 4 residual.
2. Import `SCENARIOS`, `DEMO_ES_INDICES`, `DEMO_OS_INDICES`, `TRUNCATE_TABLES`, `ES`, `OS` from `scripts.seed_meaningful_demos`. **Define local `Final` constants** for the dev-stack basic-auth tuples (per cycle-12 plan-review finding B2 — avoid coupling to CLI internals beyond what the spec guarantees): `_ES_DELETE_AUTH: Final = ("elastic", "changeme")` and `_OS_DELETE_AUTH: Final = ("admin", "admin")`. Per-scenario engine calls continue to use `scenario["host_auth"]` from the imported `SCENARIOS` dicts (the spec mentions this field). Confirm the imports work inside the API container (the package layout supports it per the pyproject.toml's setuptools-packages discovery; if any import path issue surfaces, add `scripts/__init__.py` or document why the import works).
3. Define `DEMO_RESEED_LOCK_KEY` constant (module-level `Final[int]`). Also define `_TRUNCATE_DEMO_TABLES_SQL: Final[str] = f"TRUNCATE {', '.join(TRUNCATE_TABLES)} RESTART IDENTITY CASCADE"` so both the orchestrator (Step 1a) AND the cleanup pass (Story 1.2's `_run_demo_reseed_cleanup`) use this single source-of-truth SQL string — eliminating duplication of the 10-table list (cycle-5 finding B2).
4. Implement `_resolve_engine_base_url(host_base_url: str) -> str` per FR-1d as a **pure deterministic function with no I/O or env-var dependencies**. The function reads NOTHING but its argument. (Per cycle-4 plan-review finding A1: an earlier draft included a `DEMO_RESEED_FORCE_ES_UNREACHABLE` env hook here; that polluted the production codepath and was removed. AC-5's test injection lives entirely in the test harness — see Story 3.2 Task 5.)
5. Implement `ReseedSummary` Pydantic model + `DemoSeedingError` exception class.
6. Implement `reseed_demo_state(db, api_client, engine_client)`:
   - Step 1a: `await db.execute(text(_TRUNCATE_DEMO_TABLES_SQL))` then `await db.commit()`. Log `demo_reseed_truncate_committed` at INFO with the table count.
   - Step 1b: loop `DEMO_ES_INDICES` and `DEMO_OS_INDICES` and DELETE each via `engine_client` against `_resolve_engine_base_url(ES)` / `_resolve_engine_base_url(OS)` with `auth=("elastic","changeme")` / `("admin","admin")`. After each call, inspect `response.status_code`: tolerate 200, 204, 404 (the latter for the no-op-on-clean-stack case). Anything else MUST raise `DemoSeedingError(f"index delete failed {idx}: {response.status_code} {response.text[:200]}")`. **Do NOT rely on `httpx` to raise automatically — `httpx` returns the response object on non-2xx; status checking is explicit.**
   - Step 2: loop `SCENARIOS`. **Every per-scenario httpx call MUST be wrapped in a helper that (a) emits `logger.info("demo_reseed_api_call_started", extra={"method": ..., "path": ..., "client": "api"|"engine"})` BEFORE the call (per cycle-7 finding B2 — AC-13 commit-ordering relies on this log), (b) calls `response.raise_for_status()` (or explicit status-code inspection) immediately after the request, and (c) re-raises non-2xx as `DemoSeedingError(f"<step>: HTTP {status} {body[:200]}")`.** Define a module-private helper like `async def _post(client, path, json=None, auth=None, *, client_label: str = "api") -> dict:` that does the start-log + call + raise_for_status + JSON parse + raises `DemoSeedingError` on failure. Apply the same helper shape to `_put`, `_get`. The per-call calls:
     * `_put(engine_client, _resolve_engine_base_url(s["host_base_url"]) + "/" + s["target"], json=s["index_mapping"], auth=s["host_auth"])`
     * For each doc in `s["docs"]`: `_put(...)` likewise
     * `_post(engine_client, _resolve_engine_base_url(s["host_base_url"]) + "/" + s["target"] + "/_refresh", json=None, auth=s["host_auth"])`
     * `_post(api_client, "/api/v1/clusters", json={cluster fields})` — capture cluster_id from response JSON
     * `_post(api_client, "/api/v1/query-templates", json={template fields})` — capture template_id
     * `_post(api_client, "/api/v1/query-sets", json={query_set fields})` — capture qset_id
     * `_post(api_client, "/api/v1/query-sets/{qset_id}/queries", json={"queries": s["queries"]})`
     * `_get(api_client, "/api/v1/query-sets/{qset_id}/queries?limit=50")` — build qtext_to_id
     * `_post(api_client, "/api/v1/judgment-lists/import", json={...})` — capture jlist_id
     * `_post(api_client, "/api/v1/_test/studies/seed-completed", json={cluster_id, query_set_id, template_id, judgment_list_id, with_pending_proposal=True})` — capture study_id
     * Track `results` list with `(slug, study_id, study_name)` for the rename step.
     * **Status-check contract (per cycle-1 plan review finding B2):** the helpers MUST treat ANY non-2xx response as a failure that propagates `DemoSeedingError`. The route handler catches this and runs cleanup.
   - Step 3: for each result, `await db.execute(text("UPDATE studies SET name = :name WHERE id = :id"), {"name": ..., "id": ...})` then `await db.commit()` (single transaction wrapping all 4 renames).
   - Step 4: compute `duration_ms` from `time.monotonic()` deltas; return `ReseedSummary(clusters_created=4, query_sets_created=4, studies_completed=4, proposals_created=4, duration_ms=int(...))`.
   - Wrap any non-`DemoSeedingError` exception in `DemoSeedingError(f"reseed failed at step {step}: {exc}")` for the route handler's log discrimination.
7. Write the 5 unit tests:
   - `_resolve_engine_base_url("http://localhost:9200") == "http://elasticsearch:9200"`
   - `_resolve_engine_base_url("http://localhost:9201") == "http://opensearch:9201"`
   - `_resolve_engine_base_url("http://example.com:9200")` raises `ValueError`
   - `DEMO_RESEED_LOCK_KEY` is deterministic and equals the expected `blake2b` value (regression guard against accidentally changing the key derivation).
   - `ReseedSummary(clusters_created=4, query_sets_created=4, studies_completed=4, proposals_created=4, duration_ms=7000)` constructs cleanly + `model_dump()` returns the 5 fields with correct types (covers spec §14 unit test requirement for the response model — cycle-3 plan finding A3).
8. Add a unit test asserting `TRUNCATE_TABLES` from `scripts.seed_meaningful_demos` is exactly the 10-tuple from spec §9 — guards against a silent CLI refactor.

**Definition of Done**
- File exists; mypy + ruff pass.
- All 6 unit tests in `backend/tests/unit/services/test_demo_seeding.py` pass (3 resolver branches, 1 lock-key deterministic, 1 ReseedSummary construction, 1 TRUNCATE_TABLES constant mirror).
- `make test-unit` green.
- The module's docstring + function docstrings cite the relevant FRs and ACs.
- No imports of `httpx.AsyncClient(...)` instantiation inside the module — the function takes the clients via parameter (per FR-1c — handler-side construction).

---

### Story 1.2 — Route handler `POST /api/v1/_test/demo/reseed`

**Outcome:** new endpoint registered in `backend/app/api/v1/_test.py`, gated by `_require_development_env`. Acquires session-level advisory lock on a dedicated pinned `AsyncConnection`, constructs the two `httpx.AsyncClient` instances, calls `reseed_demo_state`, runs cleanup on failure, releases the lock in `finally`.

**New files**: none.

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/_test.py` | Add `POST /api/v1/_test/demo/reseed` route handler with all the lock + client + cleanup logic. |

**Endpoints**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `POST` | `/api/v1/_test/demo/reseed` | empty / `{}` | `200` `{"clusters_created": 4, "query_sets_created": 4, "studies_completed": 4, "proposals_created": 4, "duration_ms": int}` | `RESOURCE_NOT_FOUND` (404, env guard), `SEED_IN_PROGRESS` (409), `SEED_FAILED` (503) |

Error envelope shape (per `_err()`):
```json
{"detail": {"error_code": "<CODE>", "message": "<human>", "retryable": <bool>}}
```

**Key interfaces** (route handler pseudocode)

```python
@router.post(
    f"{_TEST_PREFIX}/demo/reseed",
    response_model=ReseedSummary,
    status_code=status.HTTP_200_OK,
    tags=["test-only"],
    dependencies=[Depends(_require_development_env)],
    summary="Wipe + reseed all 4 demo scenarios (dev-only)",
    description=(
        "Wipes the demo Postgres tables and ES/OS indices, then re-seeds "
        "the 4 demo scenarios. Per feat_home_demo_reseed_endpoint spec."
    ),
)
async def reseed_demo(
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ReseedSummary:
    # FR-3: session-level advisory lock on a dedicated pinned AsyncConnection.
    engine = get_engine()
    async with engine.connect() as lock_conn:
        acquired = False  # Sentinel; set True only after successful acquisition.
        try:
            acquired = (await lock_conn.execute(
                text("SELECT pg_try_advisory_lock(:k)"),
                {"k": DEMO_RESEED_LOCK_KEY},
            )).scalar_one()
            # Commit the implicit transaction SQLAlchemy autobegan for the SELECT.
            # If `acquired` is False, this commit just closes the empty txn.
            # If `acquired` is True and this commit raises, the `finally` below
            # will still run the unlock (per cycle-14 plan-review finding B1).
            await lock_conn.commit()
            if not acquired:
                raise _err(409, "SEED_IN_PROGRESS",
                           "A demo reseed is already running; wait for it to complete.",
                           True)
            # FR-1c + FR-4: dual httpx clients with per-call timeout.
            timeout = httpx.Timeout(settings.demo_reseed_per_call_http_timeout_s)
            async with (
                httpx.AsyncClient(base_url="http://localhost:8000", timeout=timeout) as api_client,
                httpx.AsyncClient(timeout=timeout) as engine_client,
            ):
                try:
                    logger.info("demo_reseed_started")  # lifecycle log per spec §10/§13
                    summary = await reseed_demo_state(db, api_client, engine_client)
                    logger.info("demo_reseed_completed", extra={"duration_ms": summary.duration_ms})
                    return summary
                except Exception as exc:
                    logger.warning(
                        "demo_reseed_failed",
                        extra={"exc_class": type(exc).__name__, "exc": str(exc)},
                    )
                    # Cleanup pass under the held lock. Uses a fresh DB unit
                    # (NOT the caller's db session — cycle-1 finding B1).
                    # AC-5: roll back the caller's session before cleanup
                    # so the request's transaction-scope teardown is clean
                    # (cycle-2 plan-review finding A2).
                    try:
                        await db.rollback()
                    except Exception as rb_exc:
                        logger.warning("demo_reseed_caller_session_rollback_failed",
                                       extra={"exc": str(rb_exc)})
                    await _run_demo_reseed_cleanup(engine_client)
                    raise _err(503, "SEED_FAILED",
                               "Demo reseed failed mid-flight. Cleanup applied. "
                               "On a timeout edge, run `docker compose restart api` before retry "
                               "— see the demo-reseed runbook.",
                               True) from exc
        finally:
            # Release the advisory lock ONLY if it was successfully acquired
            # (cycle-14 plan-review finding B1 — guard against
            # pg_advisory_unlock on a connection that never held the lock).
            if acquired:
                released = (await lock_conn.execute(
                    text("SELECT pg_advisory_unlock(:k)"),
                    {"k": DEMO_RESEED_LOCK_KEY},
                )).scalar_one()
                await lock_conn.commit()  # close the unlock's implicit txn
                # Per FR-3: always log unlock result. INFO on success, WARN on false
                # (cycle-9 plan-review finding A1).
                if released:
                    logger.info(
                        "demo_reseed_advisory_unlock",
                        extra={"released": True, "key": DEMO_RESEED_LOCK_KEY},
                    )
                else:
                    logger.warning(
                        "demo_reseed_advisory_unlock_returned_false",
                        extra={"released": False, "key": DEMO_RESEED_LOCK_KEY},
                    )


async def _run_demo_reseed_cleanup(
    engine_client: httpx.AsyncClient,
) -> None:
    """Best-effort cleanup. Per spec FR-2.

    Opens a FRESH DB connection via the module's engine (NOT the caller's
    AsyncSession, which may be in a broken/rolled-back state after the
    mid-flight exception). Each cleanup step (TRUNCATE, index DELETEs)
    tolerates every error so cleanup always completes. Runs while the
    route handler still holds the advisory lock — so concurrent reseeds
    409 until we commit.

    Cycle-1 GPT-5.5 plan review finding B1 — cleanup MUST use a fresh
    DB unit, not the caller's session.
    """
    from backend.app.db.session import get_engine
    engine = get_engine()
    try:
        async with engine.begin() as cleanup_conn:
            # Use the same SQL constant as the orchestrator's Step 1a.
            await cleanup_conn.execute(text(_TRUNCATE_DEMO_TABLES_SQL))
        logger.info("demo_reseed_cleanup_truncated")
    except Exception as exc:
        logger.warning("demo_reseed_cleanup_truncate_failed", extra={"exc": str(exc)})
    # Use the imported CLI constants ES/OS as resolver input (per cycle-10
    # plan-review finding B3 — keeps cleanup aligned with the same
    # source-of-truth the orchestrator uses). Auth tuples are local to
    # demo_seeding.py (cycle-12 plan-review finding B2 — avoid coupling
    # to CLI auth constants that aren't part of the spec contract).
    from backend.app.services.demo_seeding import (
        _ES_DELETE_AUTH, _OS_DELETE_AUTH,
    )
    from scripts.seed_meaningful_demos import ES as _CLI_ES, OS as _CLI_OS
    for idx in DEMO_ES_INDICES:
        try:
            resp = await engine_client.delete(
                f"{_resolve_engine_base_url(_CLI_ES)}/{idx}",
                auth=_ES_DELETE_AUTH,
            )
            # Tolerate 404 + 2xx; log everything else.
            if resp.status_code not in (200, 204, 404):
                logger.info(
                    "demo_reseed_cleanup_es_delete_unexpected_status",
                    extra={"idx": idx, "status": resp.status_code},
                )
        except Exception as exc:
            logger.info("demo_reseed_cleanup_es_delete_skipped", extra={"idx": idx, "exc": str(exc)})
    for idx in DEMO_OS_INDICES:
        try:
            resp = await engine_client.delete(
                f"{_resolve_engine_base_url(_CLI_OS)}/{idx}",
                auth=_OS_DELETE_AUTH,
            )
            if resp.status_code not in (200, 204, 404):
                logger.info(
                    "demo_reseed_cleanup_os_delete_unexpected_status",
                    extra={"idx": idx, "status": resp.status_code},
                )
        except Exception as exc:
            logger.info("demo_reseed_cleanup_os_delete_skipped", extra={"idx": idx, "exc": str(exc)})
```

**Tasks**
1. Import the new symbols at the top of `backend/app/api/v1/_test.py`: `from backend.app.services.demo_seeding import reseed_demo_state, ReseedSummary, DEMO_RESEED_LOCK_KEY, _resolve_engine_base_url, _TRUNCATE_DEMO_TABLES_SQL` (cycle-6 finding B2: the cleanup helper uses the SQL constant — it MUST be imported). Also import `from backend.app.db.session import get_engine`, `from scripts.seed_meaningful_demos import DEMO_ES_INDICES, DEMO_OS_INDICES`, and `httpx`, `logging` (or whatever structured-logging helper the module already uses — check the file for `logger = logging.getLogger(...)` pattern).
2. Add the `reseed_demo` handler with the pseudocode above. Mount under `_TEST_PREFIX = "/_test"` (already present at `backend/app/api/v1/_test.py:37`).
3. Add the `_run_demo_reseed_cleanup` helper at module level, before the route handlers section.
4. Confirm `await lock_conn.commit()` doesn't error on an empty transaction (SQLAlchemy treats this as a no-op).
5. Add a logger setup at the top of the module if not already present.

**Definition of Done**
- Endpoint registered (visible in OpenAPI when `ENVIRONMENT=development`).
- Outside dev: 404 `RESOURCE_NOT_FOUND` (covered by Story 3.1 contract tests).
- Concurrent request: 409 `SEED_IN_PROGRESS` (covered by AC-3 + AC-12 integration tests).
- Per-call timeout: 503 `SEED_FAILED` (covered by AC-4 integration test).
- Mid-flight failure: 503 `SEED_FAILED` (covered by AC-5 integration test).
- Cleanup runs under the held lock (covered by AC-12 + AC-16 integration tests).
- Lock release returns `true` on the success path (asserted by AC-16).
- `make lint && make typecheck && make test-contract` green.

---

## Epic 2 — Frontend: dashboard button

### Story 2.1 — "Reset to demo state" button + dialog inside `StartHereChecklist`

**Outcome:** when the dashboard is in a truly-empty state (`!hasClusters && !hasQuerySetsWithJudgments && !hasStudies`), `StartHereChecklist` renders a `<details>` disclosure beneath the 3-step list with a "Reset to demo state" button that opens an `<AlertDialog>` confirming the destructive wipe + reseed, then POSTs `/api/v1/_test/demo/reseed` on confirm, shows a sonner toast on success/failure, and invalidates the dashboard's TanStack queries on success.

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/dashboard/reset-demo-state-button.tsx` | Self-contained component: disclosure summary + AlertDialog + POST + toast + query invalidation. Default-exported `<ResetDemoStateButton />` (no props). |
| `ui/src/__tests__/components/dashboard/start-here-checklist.spec.tsx` | New vitest spec for `StartHereChecklist` covering AC-7 + AC-8 (disclosure visibility based on prop combinations). Pre-existing tests don't cover the `<details>` — this is a new file. |
| `ui/src/__tests__/components/dashboard/reset-demo-state-button.spec.tsx` | Vitest spec covering AC-9 (dialog open/close + Cancel-without-POST + Confirm-fires-POST). **Mocks `apiClient.post` at the module boundary via `vi.mock('@/lib/api-client', ...)`** (NOT global `fetch`) — `apiClient` is a project-specific wrapper around `fetch` that handles auth headers + error envelope unwrapping; mocking it directly tests the component's contract with that wrapper. Also mocks `useQueryClient` (returned from `@tanstack/react-query`) to capture `invalidateQueries` calls. |

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/dashboard/start-here-checklist.tsx` | Render `<ResetDemoStateButton />` inside a `<details>` disclosure when all three props are `false`. |

**Endpoints** — none new (consumes the FR-2 endpoint).

**Pydantic schemas** — N/A frontend.

**UI element inventory**

For `StartHereChecklist.tsx` (modified):
- **Existing:** Card with header "Get started", `<ol>` of 3 onboarding `<li>` steps. Renders `null` if all three props are `true`. (152 LOC currently per spec §2.)
- **NEW element:** `<details>` element rendered AFTER the `</ol>` close tag, BEFORE the `</CardContent>` close tag. Condition: `!hasClusters && !hasQuerySetsWithJudgments && !hasStudies`.
  - `<summary>` text: `"or skip ahead — reset to demo state"` (lowercase, casual — matches spec §11 Labeling).
  - Inside `<details>`: `<ResetDemoStateButton />` component (no props).

For `ResetDemoStateButton.tsx` (new):
- `<Button variant="secondary" data-testid="reset-demo-state-trigger">` — label `"Reset to demo state"`. Opens the dialog.
- `<AlertDialog>` (from `@/components/ui/alert-dialog`) — controlled by `open` state.
  - `<AlertDialogTitle>` text: `"Wipe and reseed demo data?"`
  - `<AlertDialogDescription>` text (multi-paragraph): `"This will WIPE the dev Postgres demo state (clusters, studies, query sets, query templates, judgment lists, judgments, trials, digests, proposals) AND the corresponding ES/OS indices. Then it will seed 4 demo scenarios."`
  - `<AlertDialogCancel>` text: `"Cancel"`. Disabled during in-flight POST.
  - `<AlertDialogAction data-testid="reset-demo-state-confirm">` text: `"Reset to demo state"` (or `"Resetting…"` while in-flight). Disabled during in-flight POST.

**State dependency analysis**

No shared state is removed. New state introduced is local to `ResetDemoStateButton`:
- `const [open, setOpen] = useState(false)` — dialog visibility
- `const [isPending, setIsPending] = useState(false)` — inflight POST gate

The `clustersCount`, `judgmentListsCount`, `recent` queries in `ui/src/app/page.tsx` are NOT modified — `StartHereChecklist` continues to receive its three boolean props from there.

The dashboard's TanStack query keys to invalidate on success:
- `['clusters', { limit: 1 }, 'first-run-count']` (from `page.tsx:56`)
- `['judgment-lists', { limit: 1 }, 'first-run-count']` (from `page.tsx:65`)
- `['studies', { limit: 5 }, 'recent']` (from `page.tsx:24`)
- `['proposals', { status: 'pr_opened', limit: 1 }, 'count']` (from `page.tsx:33`)

The component uses `queryClient.invalidateQueries({ queryKey: ['clusters'] })` etc. (prefix match — invalidates all variants) per TanStack convention.

**Key interfaces** (component pseudocode)

```tsx
// ui/src/components/dashboard/reset-demo-state-button.tsx
'use client';
import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { apiClient } from '@/lib/api-client';

interface ReseedSummary {
  clusters_created: number;
  query_sets_created: number;
  studies_completed: number;
  proposals_created: number;
  duration_ms: number;
}

interface ReseedErrorResponse {
  detail: { error_code: string; message: string; retryable: boolean };
}

export function ResetDemoStateButton(): React.ReactElement {
  const [open, setOpen] = useState(false);
  const [isPending, setIsPending] = useState(false);
  const queryClient = useQueryClient();

  async function handleConfirm(event: React.MouseEvent) {
    event.preventDefault();
    setIsPending(true);
    // 180-second client-side timeout per spec §3 In-scope D. Allows up to
    // 4 scenarios × ~5 calls × 30s/call worst-case if the backend's
    // demo_reseed_per_call_http_timeout_s is set high.
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 180_000);
    try {
      const { data } = await apiClient.post<ReseedSummary>(
        '/api/v1/_test/demo/reseed',
        undefined,
        { signal: controller.signal },
      );
      toast.success(
        `Demo state reset — ${data.clusters_created} clusters, ${data.query_sets_created} query sets, ${data.studies_completed} completed studies. The dashboard will refresh in a moment.`,
      );
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['clusters'] }),
        queryClient.invalidateQueries({ queryKey: ['judgment-lists'] }),
        queryClient.invalidateQueries({ queryKey: ['studies'] }),
        queryClient.invalidateQueries({ queryKey: ['proposals'] }),
      ]);
      setOpen(false);
    } catch (err) {
      // Distinguish envelope errors (have detail.error_code) from
      // browser-side abort/network errors (no envelope).
      const envelope = (err as { response?: { data?: ReseedErrorResponse } }).response?.data?.detail;
      if (envelope?.error_code) {
        toast.error(
          `Reseed failed: ${envelope.error_code}. If this followed a hang or timeout, run \`docker compose restart api\` before retrying; otherwise see the demo-reseed runbook or run \`make seed-demo FORCE=1\` from the host.`,
        );
      } else {
        // AbortError (180s timeout), network unreachable, or generic non-envelope failure.
        toast.error(
          `Reseed in progress or unreachable — refresh the page in a moment.`,
        );
      }
    } finally {
      clearTimeout(timeoutId);
      setIsPending(false);
    }
  }

  return (
    <>
      <Button
        type="button"
        variant="secondary"
        onClick={() => setOpen(true)}
        data-testid="reset-demo-state-trigger"
      >
        Reset to demo state
      </Button>
      <AlertDialog open={open} onOpenChange={setOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Wipe and reseed demo data?</AlertDialogTitle>
            <AlertDialogDescription>
              This will WIPE the dev Postgres demo state (clusters, studies, query sets, query
              templates, judgment lists, judgments, trials, digests, proposals) AND the corresponding
              ES/OS indices. Then it will seed 4 demo scenarios.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isPending}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={isPending}
              onClick={handleConfirm}
              data-testid="reset-demo-state-confirm"
            >
              {isPending ? 'Resetting…' : 'Reset to demo state'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
```

**Tasks**
1. **First**: verify the actual `apiClient` contract at `ui/src/lib/api-client.ts`. Confirmed at plan-write time (cycle-6 finding A1): `apiClient.post<T>(path, body, init?: RequestOptions)` accepts a third arg with `signal: AbortSignal` (composed with the internal timeout); returns `Promise<ApiResponse<T>>` with shape `{ data: T, headers: Headers, ... }`. The error envelope handling: on non-2xx the wrapper throws — inspect the thrown error shape (it may be a project-specific class, not Axios's `{ response: { data: ... } }`). Read `ui/src/lib/api-client.ts:200-280` (the post implementation) to confirm the error-throwing path's exact shape before writing the component's `catch` block, and adapt the pseudocode's `(err as { response?: { data?: ReseedErrorResponse } }).response?.data?.detail` extraction to whatever the real client throws (likely a class like `ApiError` with `error.detail` directly, OR a thrown response with `.json()` to parse). If the contract differs from the pseudocode, the test mock + the component MUST both align with the real client's shape — re-read finding A1 before implementing.
2. Create `ui/src/components/dashboard/reset-demo-state-button.tsx` with the component above (adjusted per task 1). Mirror the `RejectDialog` shape from `ui/src/components/proposals/reject-dialog.tsx:1-90` for the AlertDialog + toast + setOpen flow.
3. Modify `ui/src/components/dashboard/start-here-checklist.tsx`:
   - Import `<ResetDemoStateButton>`.
   - After the `</ol>` close (line ~148) but before `</CardContent>`, add:
     ```tsx
     {!hasClusters && !hasQuerySetsWithJudgments && !hasStudies && (
       <details className="mt-4 border-t pt-4 text-sm" data-testid="reset-demo-state-disclosure">
         <summary className="cursor-pointer text-muted-foreground">
           or skip ahead — reset to demo state
         </summary>
         <div className="mt-3">
           <ResetDemoStateButton />
         </div>
       </details>
     )}
     ```
4. Write `ui/src/__tests__/components/dashboard/start-here-checklist.spec.tsx` covering:
   - AC-7: all 3 props false → disclosure in DOM, summary text matches.
   - AC-8 variants: any single prop true (3 cases) → disclosure NOT in DOM. All-3-true → `StartHereChecklist` returns null (no card).
5. Write `ui/src/__tests__/components/dashboard/reset-demo-state-button.spec.tsx`. **Mock `apiClient` at the module boundary** via `vi.mock('@/lib/api-client', () => ({ apiClient: { post: vi.fn() } }))`. Each test sets up `(apiClient.post as Mock).mockImplementation(...)` to control the response. Covers:
   - AC-9: click trigger → dialog opens; click Cancel → dialog closes AND `apiClient.post` was NOT called; click Confirm → `apiClient.post` called with `('/api/v1/_test/demo/reseed', undefined, { signal: expect.any(AbortSignal) })`; on 200 success → `toast.success` invoked with text matching FR-6 wording AND `queryClient.invalidateQueries` called for all 4 query keys (`['clusters']`, `['judgment-lists']`, `['studies']`, `['proposals']`); on 503 failure (mock throws `{ response: { data: { detail: { error_code: 'SEED_FAILED', message: '...', retryable: true } } } }`) → `toast.error` invoked with text matching AC-11 wording (contains both `'SEED_FAILED'` AND `'docker compose restart api'`) AND `isPending` resets AND dialog stays open.
   - 180-second timeout test: `apiClient.post` mock returns a Promise that observes its `config.signal` and rejects with `new DOMException('Aborted', 'AbortError')` when the signal aborts. Use `vi.useFakeTimers()` and `vi.advanceTimersByTime(180_000)` to trigger the abort. Assert `toast.error` invoked with the unreachable wording `"Reseed in progress or unreachable — refresh the page in a moment."` AND button is re-enabled.
   - Non-envelope failure test: `apiClient.post` mock rejects with `new TypeError('Network Error')` (no `response.data.detail`). Assert the unreachable wording toast (not the SEED_FAILED-style wording).
6. Run `cd ui && pnpm lint && pnpm typecheck && pnpm test`.

**Definition of Done**
- Both vitest specs pass.
- `<StartHereChecklist>`'s existing visibility rules (returns null when all 3 props true) are unchanged.
- The toast wording for both success and failure matches the spec FR-6 / §11 / AC-11 wording character-for-character.
- The `<details>` element is keyboard-accessible (native HTML5 behavior).
- `cd ui && pnpm build` succeeds (Next.js production build catches SSR issues).

---

## Epic 3 — Tests + docs

### Story 3.1 — Contract tests: env-guard + OpenAPI surface

**Outcome:** the env-guard contract test asserts the new `/api/v1/_test/demo/reseed` endpoint also 404s outside `ENVIRONMENT=development`, mirroring the existing test for `/_test/studies/seed-completed`. The OpenAPI surface test registers the new endpoint at 200.

**New files**: none.

**Modified files**

| File | Change |
|---|---|
| `backend/tests/contract/test_test_endpoint_guard.py` | Extend the parametrized `test_seed_completed_returns_404_outside_development` (or add a sibling parametrized test) to cover `/_test/demo/reseed` across the same `_NON_DEV_ENVIRONMENTS` list. |
| `backend/tests/contract/test_openapi_surface.py` | Add `("post", "/api/v1/_test/demo/reseed", "200")` to the endpoint registry at lines ~96-97. |

**Endpoints** — none new (test-only).

**Tasks**
1. Open `backend/tests/contract/test_test_endpoint_guard.py:60-83`. Add a parametrized test (or extend the existing one to also POST `/_test/demo/reseed`) asserting 404 + `RESOURCE_NOT_FOUND` + `retryable=false` for each of `["staging", "production", "ci", "qa", ""]`.
2. Open `backend/tests/contract/test_openapi_surface.py:96-97`. Add `("post", "/api/v1/_test/demo/reseed", "200")` after the existing seed-completed entry.
3. Run `make test-contract` and confirm both files pass.

**Definition of Done**
- AC-6 covered by the env-guard contract test.
- The OpenAPI-surface contract test enforces the new endpoint stays registered with 200 on its happy path.
- `make test-contract` green.

---

### Story 3.2 — Integration tests: full happy-path + concurrency + cleanup races + commit ordering + connection pinning + dual-client + resolver

**Outcome:** `backend/tests/integration/test_demo_seeding.py` exercises the endpoint against real Postgres + ES + OS service containers, covering AC-1, AC-2, AC-3, AC-4 (per-call timeout), AC-5 (mid-flight failure), AC-12 (cleanup-while-locked), AC-13 (TRUNCATE commit ordering), AC-14 (natural-failure cleanup-after-Python-control-returns), AC-15 (dual-client contract), AC-16 (pinned advisory-lock connection).

**New files**

| File | Purpose |
|---|---|
| `backend/tests/integration/test_demo_seeding.py` | All 10 integration test cases above. Marked `@pytest.mark.integration`. |

**Modified files**: none.

**Endpoints** — none new.

**Key interfaces** (test pseudocode)

```python
# backend/tests/integration/test_demo_seeding.py
import pytest
import asyncio
from sqlalchemy import text


@pytest.mark.integration
async def test_reseed_happy_path_on_clean_db(async_client, db_engine):
    # AC-1: clean DB -> 200 + the §9 Required invariants row counts.
    # Per spec §9 Required invariants (and cycle-12 plan-review finding A1 — this is
    # NOT "4 rows in each demo table"):
    #   clusters: 4, query_sets: 4, query_templates: 4, judgment_lists: 4,
    #   studies: 4 (status='completed'), digests: 4 (one per study),
    #   proposals: 4 (status='pending'), trials: 8 (winner + runner-up per study),
    #   queries: count derived from SCENARIOS (sum of len(s["queries"]) across 4 scenarios),
    #   judgments: count derived from SCENARIOS (sum of len(s["judgments_map"])).
    # Plus: ES indices `products`, `docs-articles`, `job-listings` exist; OS index `news-articles` exists.
    # Preconditions: DB starts empty (test framework wipes via existing _test/* DELETEs).
    ...


@pytest.mark.integration
async def test_reseed_replaces_populated_demo_state(async_client, db_engine):
    # AC-2: pre-seed demo data, then call reseed, assert new UUIDs.
    ...


@pytest.mark.integration
async def test_concurrent_reseed_returns_409(async_client, db_engine):
    # AC-3: fire two reseeds concurrently via asyncio.gather; assert one is 200 and one is 409.
    ...


@pytest.mark.integration
async def test_reseed_per_call_timeout_returns_503(async_client, db_engine, monkeypatch):
    # AC-4: monkeypatch demo_reseed_per_call_http_timeout_s=1 + force a self-call delay
    # (e.g., patch backend.app.services.test_seeding.seed_study_completed_with_digest to
    # asyncio.sleep(5) before its writes). Assert 503 + error_code=SEED_FAILED.
    # MUST NOT assert post-cleanup emptiness (per AC-4 + §10 Threat 4).
    ...


@pytest.mark.integration
async def test_reseed_mid_flight_engine_failure_returns_503_and_cleans_up(async_client, db_engine, monkeypatch):
    # AC-5 (non-timeout engine failure path): make ES unreachable mid-loop. The simplest
    # implementation is to monkeypatch the `engine_client` factory to return a transport
    # that always 503s OR to monkeypatch `httpx.AsyncClient.put` to raise on the second
    # call. The intent is to exercise the engine_client failure path specifically
    # (distinct from AC-14 which exercises the api_client / self-call failure path).
    # Assert HTTP 503 + error_code=SEED_FAILED + deterministic post-cleanup empty state
    # (clusters, query_sets, studies tables are empty AND ES indices `products`,
    # `docs-articles`, `job-listings` are absent).
    ...


@pytest.mark.integration
async def test_cleanup_while_locked_blocks_concurrent_reseed(async_client, db_engine, monkeypatch):
    # AC-12: force request A to fail mid-flight AND slow down the cleanup pass.
    # Fire request B during A's cleanup; assert B gets 409 SEED_IN_PROGRESS.
    # After A's cleanup commits, fire request C; assert C gets 200.
    ...


@pytest.mark.integration
async def test_truncate_commits_before_first_self_call(async_client, db_engine, caplog):
    # AC-13: assert the structured-log sequence shows demo_reseed_truncate_committed
    # BEFORE any POST /api/v1/clusters log entry. (Use caplog or an event-capture fixture.)
    ...


@pytest.mark.integration
async def test_natural_failure_cleanup_after_python_control_returns(async_client, db_engine, monkeypatch):
    # AC-14: trigger a non-timeout exception (e.g., HTTP 500 from a self-call).
    # Assert demo tables are deterministically empty after the 503 returns.
    ...


@pytest.mark.integration
async def test_dual_client_contract_no_role_mixing(async_client, db_engine):
    # AC-15: monkeypatch httpx.AsyncClient to record all base_url + URL pairs.
    # Assert every /api/v1/* request used the api_client (base_url=http://localhost:8000).
    # Assert every ES/OS request used the engine_client (base_url unset; absolute URLs against
    # elasticsearch:9200 / opensearch:9201).
    ...


@pytest.mark.integration
async def test_advisory_lock_pinned_to_one_connection(async_client, db_engine):
    # AC-16: during the reseed, query pg_locks from a sibling engine.connect() (observer):
    # assert exactly one matching advisory-lock row before TRUNCATE, after TRUNCATE commit,
    # during the self-call loop. After the handler returns 200, assert the row is gone.
    # Assert the lock-holding pid does NOT change across the observations.
    ...
```

**Tasks**

**Integration-test topology decision (per cycle-1 finding B3 + cycle-2 finding B1):** the route handler's `api_client` self-calls `localhost:8000`, AND the test suite needs to inject failures/monkeypatches AND observe logs/locks. The ONLY coherent topology is **in-process uvicorn + shared `app` instance**:

  - A module-scoped pytest fixture in `backend/tests/integration/conftest.py` (or extend an existing fixture if one already supports this) starts a uvicorn server in a background thread/asyncio task. **Address-family caveat (cycle-11 plan-review finding B1):** binding only to `0.0.0.0` covers IPv4 but NOT IPv6 `[::1]`; on systems where `localhost` resolves to `::1` first, the handler's `http://localhost:8000` self-call would fail. The fixture MUST either:
    - Bind dual-stack (`uvicorn` with `host="::"` listens on both `::` and `0.0.0.0` on most systems where `IPV6_V6ONLY=0` is the default — verify against the Python `uvicorn` version in `pyproject.toml`), OR
    - Start two listeners (one on `127.0.0.1:8000` and one on `[::1]:8000`), OR
    - Run a fixture-level smoke test that fires `GET http://localhost:8000/healthz` from the same process; if it 200s, the binding is sufficient. If it fails, fail the fixture immediately with an actionable error pointing the operator at this paragraph.
   The handler in Story 1.2 uses `httpx.AsyncClient(base_url="http://localhost:8000", ...)` per FR-1c, so the test fixture's binding MUST resolve `localhost` to a listening address-family. This makes:
    * `app.dependency_overrides[...]` effective for both pytest-side requests AND the handler's loopback self-calls (the loopback hits the same `app` object via uvicorn's network bind).
    * Module-level monkeypatches (e.g., `monkeypatch.setattr("backend.app.services.test_seeding.seed_study_completed_with_digest", fake_slow)`) effective server-side — there's only ONE Python process.
    * `caplog` captures route-handler logs (same process).
    * `pg_locks` observer queries from a sibling `engine.connect()` work against the shared Postgres container.
  - The fixture signals uvicorn shutdown + joins the thread on teardown.
  - If `backend/tests/conftest.py` already provides such a fixture (likely from `infra_e2e_seed_completed_study` which has the same self-call pattern), reuse it; otherwise add one. Verify before adding.

This is a **non-mixed topology**: NOT an external uvicorn subprocess (would break monkeypatch + caplog), NOT `ASGITransport(app=app)` (would break the self-call loopback). One in-process uvicorn that binds to 8000.

1. Create or extend the in-process-uvicorn fixture in `backend/tests/integration/conftest.py`.
2. Create `backend/tests/integration/test_demo_seeding.py` with the 10 test cases. Tests fire HTTP calls via `httpx.AsyncClient(base_url="http://127.0.0.1:8000")`.
3. Use `db_engine` from `conftest.py` for DB inspection; open a sibling `engine.connect()` for AC-16's observer queries.
4. AC-4 (per-call timeout): the production Settings validator has `ge=30` (FR-4b range 30..600), so a normal `Settings(demo_reseed_per_call_http_timeout_s=1)` construction will raise `ValidationError`. The test MUST bypass the validator deliberately by using `Settings.model_construct(demo_reseed_per_call_http_timeout_s=1, ...)` (Pydantic's bypass-validation constructor) OR by patching the attribute on an already-constructed settings instance via `monkeypatch.setattr(settings, "demo_reseed_per_call_http_timeout_s", 1)` AFTER `get_settings()` has been called once. **Do NOT weaken the production validator's range to accommodate the test.** Combine with `monkeypatch.setattr("backend.app.services.test_seeding.seed_study_completed_with_digest", lambda *a, **k: asyncio.sleep(5))` to force a slow self-call.

   **AC-4 must be isolated from other tests** (cycle-9 plan-review finding B2): the spec's ReadTimeout residual risk says the abandoned server-side handler may complete after cleanup, which could contaminate subsequent tests sharing the module-scoped uvicorn fixture. Mitigation:
   - Put AC-4 in a **separate test file** (e.g., `test_demo_seeding_timeout.py`) with a **function-scoped** uvicorn fixture (NOT the module-scoped one used by the other tests).
   - **Cleanup-attempted assertion (cycle-10 plan-review finding A1):** AC-4 MUST also assert via `caplog` that the `demo_reseed_cleanup_truncated` log entry appears after the 503 path is taken (proving `_run_demo_reseed_cleanup` was entered). This guards against a regression where the failure path skips cleanup entirely. The test asserts deterministic emptiness is NOT required (still per spec — the ReadTimeout edge may leave 1-2 rows from the late commit), but the CLEANUP-ATTEMPTED log assertion IS required.
   - The function-scoped fixture explicitly shuts down uvicorn AFTER the test (which terminates any lingering self-call task in the same process), THEN starts a fresh uvicorn for the next test if one runs in that file.
   - The other 9 integration tests (AC-1, AC-2, AC-3, AC-5, AC-12, AC-13, AC-14, AC-15, AC-16) keep the module-scoped fixture for performance.
   - This makes the AC-4 test heavier (one uvicorn startup/teardown for that test specifically) but eliminates the cross-test contamination risk.
5. AC-5 (engine_client mid-loop failure — real ES unreachable, per spec FR-8 / AC-5): the spec requires a **mid-loop** failure so cleanup is exercised after partial Postgres + API state has committed. The test MUST be in CI's mandatory matrix (no `pytest.mark.skipif`). Implementation:
   - Wrap `httpx.AsyncClient.put` via `monkeypatch.setattr` with a counter; allow the first scenario's engine PUTs to succeed (real ES container handles them); on the 2nd scenario's first PUT, raise `httpx.ConnectError("simulated ES unreachable")`. This guarantees:
     * Scenario 1 has committed: 1 cluster + 1 query_set + 1 study + 1 proposal already exist in Postgres + the `products` index exists in real ES.
     * The 2nd scenario's first engine call fails with a real `ConnectError`.
     * The orchestrator unwinds → cleanup runs → cleanup TRUNCATEs the partial state from scenario 1 → cleanup DELETEs the `products` index against real ES → 503 SEED_FAILED returns.
   - Assert (a) HTTP 503 with `error_code=SEED_FAILED`, (b) Postgres demo tables are empty post-handler-return (cleanup ran), (c) the `products` ES index does NOT exist (cleanup deleted it).
   - This exercises the real engine container (scenario 1's PUTs hit real ES), real Postgres cleanup, and real index-delete cleanup — satisfying FR-8's "real Postgres + real ES + real OS containers" requirement. The monkeypatched failure injection only kicks in at the synchronized mid-loop point. (Cycle-8 plan-review finding B1.)
   - **Residual divergence from spec FR-8 wording** (cycle-11 plan-review finding B2): the spec literally says "stop ES mid-loop" via container control. The plan uses a monkeypatched `httpx.AsyncClient.put` failure instead, because (a) docker-compose container control from inside pytest is brittle (race conditions on stop/start, port flapping), (b) the monkeypatched ConnectError exercises the same code path as a real connection refusal. As a complementary safeguard, AC-15's basic-auth assertions verify the real ES/OS auth tuples flow correctly; the AC-1/AC-2 happy-path assertions verify real ES/OS index creation + doc insertion via the real container. So real-container coverage of ES is preserved at AC-1/AC-2/AC-15; AC-5's narrow concern is the cleanup-on-engine-failure code path, which the monkeypatched failure exercises faithfully.
   - The production `_resolve_engine_base_url` remains pure with no env hooks (per cycle-4 finding A1).
6. AC-14 (api_client failure / natural exception): `app.dependency_overrides` only overrides FastAPI **dependencies**, not handler functions (per cycle-4 plan-review finding B2). To force one of the self-call routes to fail, the test MUST monkeypatch the underlying service function the route delegates to — e.g., `monkeypatch.setattr("backend.app.services.test_seeding.seed_study_completed_with_digest", raise_runtime_error)` to make `POST /_test/studies/seed-completed` fail with a 500-equivalent. Alternative: monkeypatch the cluster-create service function (`backend.app.services.cluster.create_cluster` or equivalent) for an earlier failure point. In-process uvicorn means the monkeypatch DOES affect the server-side handler. Assert demo tables are empty post-cleanup.
7. AC-15 (no client-role mixing + per-scenario basic auth, per cycle-10 plan-review finding A2): `monkeypatch.setattr` wrapping `httpx.AsyncClient.request` to append `(method, url, auth)` tuples to a list — RECORD THE `auth` kwarg too. Assertions:
   - Every `/api/v1/*` request is delivered to `localhost:8000` AND has `auth=None` (FastAPI loopback uses no auth in MVP1).
   - Every ES request (`elasticsearch:9200/...`) has `auth=("elastic", "changeme")`.
   - Every OS request (`opensearch:9201/...`) has `auth=("admin", "admin")`.
   - No FastAPI route receives an ES-shaped request and vice versa.
8. AC-12 (cleanup-while-locked race, per cycle-14 plan-review finding B2): use a `threading.Event` (NOT `asyncio.Event`) as the synchronization primitive. `asyncio.Event` is loop-local, and the uvicorn fixture may run the server in a background thread with its own event loop — `asyncio.Event` would not synchronize across loops. Inject the `threading.Event` into the cleanup pass via a module-level test hook (`monkeypatch.setattr("backend.app.api.v1._test._demo_reseed_cleanup_test_gate", evt)`). The cleanup pass checks for this hook at the top and, if present, awaits `asyncio.to_thread(evt.wait)` before its TRUNCATE. The test then: (a) starts request A in a task, (b) waits for A to enter cleanup (poll for a log entry OR an `asyncio.Event` the cleanup signals BEFORE blocking — set in the same loop as the test), (c) fires request B and asserts 409, (d) signals `evt.set()`, (e) A's cleanup completes and releases the lock, (f) fires request C and asserts 200. The test hook is module-private and gated by a check that the test gate variable is not None — production behavior is unaffected.
9. AC-16 (advisory lock connection pinning): open `engine.connect()` from the test, run `pg_locks` queries at strategic points (before TRUNCATE, after TRUNCATE commit, mid-self-call-loop, after handler returns). **Postgres splits a single-bigint advisory lock across `pg_locks.classid` (high 32 bits) and `pg_locks.objid` (low 32 bits)** — and `DEMO_RESEED_LOCK_KEY` is a signed int64 (can be negative). The test helper MUST derive the expected fields:
   ```python
   key_u64 = DEMO_RESEED_LOCK_KEY & ((1 << 64) - 1)
   expected_classid = (key_u64 >> 32) & 0xffffffff
   expected_objid = key_u64 & 0xffffffff
   ```
   Then query `SELECT pid FROM pg_locks WHERE locktype = 'advisory' AND classid = :c AND objid = :o`. Assert exactly one row matches at each observation point during the reseed; assert the `pid` does not change across observations; assert zero rows match after the handler returns. (Cycle-5 plan-review finding B3.)
10. AC-13 (commit ordering): use `caplog` (with `caplog.set_level(logging.INFO)`) to capture INFO-level logs from the handler + service module; assert `demo_reseed_truncate_committed` log entry appears BEFORE the first `demo_reseed_api_call_started` log entry with `path='/api/v1/clusters'` (per the explicit per-call log added in Story 1.1 task 6 — cycle-7 finding B2). This is robust against uvicorn access-log configuration variations.
11. Run `make test-integration` (targeted: `pytest -m integration backend/tests/integration/test_demo_seeding.py`).

**Definition of Done**
- All 10 tests pass against real Postgres + ES + OS service containers.
- The CI `make test-integration` job stays green.
- No flakiness: at least 3 consecutive runs locally pass without modification.

---

### Story 3.3 — Playwright real-backend E2E

**Outcome:** new Playwright spec at `ui/tests/e2e/dashboard-reseed.spec.ts` covers AC-10 — wipe via existing `/_test/*` DELETEs → navigate to `/` → click disclosure → button → Confirm → wait for the success toast → assert the dashboard refetches and renders 4 clusters.

**New files**

| File | Purpose |
|---|---|
| `ui/tests/e2e/dashboard-reseed.spec.ts` | One Playwright spec covering AC-10 end-to-end. Uses real browser interactions; no `page.route()` mocking. |

**Modified files**: none.

**Endpoints** — none new.

**Tasks**
1. Read `ui/tests/e2e/dashboard.spec.ts` as the reference for the dashboard's existing E2E pattern (test setup, navigation, selectors).
2. Read `ui/tests/e2e/global-teardown.ts` for the existing wipe pattern.
3. Write the new spec:
   - Setup (via API `request`): wipe the stack using the existing `/api/v1/_test/*` DELETE endpoints, ensuring the dashboard starts empty.
   - Navigate to `/`.
   - Assert `StartHereChecklist` is visible (data-testid `start-here-checklist`).
   - Assert the disclosure is visible (data-testid `reset-demo-state-disclosure`).
   - Click the disclosure summary to expand it.
   - Click the `<Button data-testid="reset-demo-state-trigger">`.
   - Assert the AlertDialog is visible (`AlertDialogContent` role or title text).
   - Click the `<AlertDialogAction data-testid="reset-demo-state-confirm">`.
   - Wait for the success toast (sonner emits a `[role="status"]` or similar; check the existing toast assertion pattern in `clusters_register.spec.ts` or `proposals.spec.ts`).
   - Wait for the dashboard to refetch (assert "Recent studies" card now shows >= 1 entry, OR assert the page no longer renders `StartHereChecklist` because all 3 props are now true).
4. Run `cd ui && pnpm test:e2e -- dashboard-reseed.spec.ts` and confirm it passes against a live stack.

**Definition of Done**
- AC-10 covered by the new Playwright spec.
- The test uses `page` for all visible interactions (no `page.route()` mocking).
- API `request` is used only for setup (the initial wipe).
- The CI Playwright job stays green.

---

### Story 3.4 — Runbook + api-conventions doc updates

**Outcome:** new runbook at `docs/03_runbooks/demo-reseed-debugging.md`; `docs/01_architecture/api-conventions.md` updated with the 2 new error codes.

**New files**

| File | Purpose |
|---|---|
| `docs/03_runbooks/demo-reseed-debugging.md` | Operator runbook covering: how to call the endpoint manually with curl, how to interpret each error code, how to inspect the advisory lock via `SELECT * FROM pg_locks WHERE locktype = 'advisory'`, the `docker compose restart api` recovery for the ReadTimeout edge, how to clear a stuck session-level advisory lock if the API process crashed mid-reseed. |

**Modified files**

| File | Change |
|---|---|
| `docs/01_architecture/api-conventions.md` | Add `SEED_FAILED` (503) and `SEED_IN_PROGRESS` (409) to the error-code registry (§"Common error codes"). |

**Tasks**
1. Write the runbook with sections: Endpoint URL + curl example, Error code table, Advisory-lock inspection query, ReadTimeout recovery (the restart-then-retry path), Stuck-lock recovery (`docker compose restart postgres` as last resort).
2. Update `api-conventions.md` — add the 2 new error codes inline with the existing table.
3. Confirm `docs/03_runbooks/` is the correct directory (per spec §15).

**Definition of Done**
- Runbook exists at the canonical path.
- `api-conventions.md` lists the 2 new codes.
- No `state.md` update needed yet — that happens at the finalization PR (after merge).

---

## UI Guidance

### Reference: current component structure

**`ui/src/components/dashboard/start-here-checklist.tsx`** (152 LOC currently; props `hasClusters`, `hasQuerySetsWithJudgments`, `hasStudies: boolean`; renders `null` at line 51 when all 3 are true).

- Section structure: `<Card>` → `<CardHeader>` ("Get started") → `<CardContent>` → `<ol>` of 3 `<li>` steps → `</CardContent>` → `</Card>`.
- State variables: none (pure functional component driven by props).
- Insertion point: AFTER `</ol>` (~line 148) BEFORE `</CardContent>` (~line 149).

**`ui/src/components/dashboard/reset-demo-state-button.tsx`** (NEW, ~90 LOC). Self-contained component with `useState` for `open` + `isPending`, `useQueryClient` for invalidation, `toast.success` / `toast.error` for feedback.

### Analogous markup patterns

```tsx
{/* AlertDialog pattern — from ui/src/components/proposals/reject-dialog.tsx:40-86 */}
<AlertDialog open={open} onOpenChange={setOpen}>
  <AlertDialogContent>
    <AlertDialogHeader>
      <AlertDialogTitle>Wipe and reseed demo data?</AlertDialogTitle>
      <AlertDialogDescription>
        This will WIPE the dev Postgres demo state (clusters, studies, query sets, query
        templates, judgment lists, judgments, trials, digests, proposals) AND the corresponding
        ES/OS indices. Then it will seed 4 demo scenarios.
      </AlertDialogDescription>
    </AlertDialogHeader>
    <AlertDialogFooter>
      <AlertDialogCancel disabled={isPending}>Cancel</AlertDialogCancel>
      <AlertDialogAction
        disabled={isPending}
        onClick={handleConfirm}
        data-testid="reset-demo-state-confirm"
      >
        {isPending ? 'Resetting…' : 'Reset to demo state'}
      </AlertDialogAction>
    </AlertDialogFooter>
  </AlertDialogContent>
</AlertDialog>
```

```tsx
{/* Disclosure pattern — new (no existing usage of <details> in the dashboard) */}
{!hasClusters && !hasQuerySetsWithJudgments && !hasStudies && (
  <details className="mt-4 border-t pt-4 text-sm" data-testid="reset-demo-state-disclosure">
    <summary className="cursor-pointer text-muted-foreground">
      or skip ahead — reset to demo state
    </summary>
    <div className="mt-3">
      <ResetDemoStateButton />
    </div>
  </details>
)}
```

### Layout and structure

The `<details>` lives inside the existing `<CardContent>` of `StartHereChecklist`, below the `<ol>`. The disclosure summary is intentionally lowercase + casual (matches spec §11 Labeling) to signal "secondary affordance" — the 3-step list remains the primary visual anchor.

### Interaction behavior

| User action | Frontend behavior | API call |
|---|---|---|
| Click `<summary>` | Native `<details>` toggle — content expands | none |
| Click `<Button>` (Reset to demo state) | `setOpen(true)` opens AlertDialog | none |
| Click `<AlertDialogCancel>` | `setOpen(false)` — dialog closes, no POST | none |
| Click `<AlertDialogAction>` | `setIsPending(true)` then `POST /api/v1/_test/demo/reseed`; on 200 → success toast + 4× `invalidateQueries` + `setOpen(false)`; on 4xx/5xx → failure toast (button + dialog stay enabled/open for retry) | `POST /api/v1/_test/demo/reseed` (empty body) |

### Handler function patterns

(Full TypeScript handler embedded in Story 2.1 Key Interfaces section above — see `handleConfirm`.)

### Information architecture placement

- Dashboard root (`/`), inside `StartHereChecklist`'s `<CardContent>`, beneath the 3-step `<ol>`.
- Visible only in the truly-empty-state branch (all 3 onboarding signals false).
- Discovered when an operator wipes their stack and lands back on the dashboard expecting to onboard from scratch but sees the "or skip ahead" affordance.

### Tooltips and contextual help

Per spec §11, no new tooltip entries. The AlertDialog body IS the contextual help; no `title` attributes or info icons needed. No new glossary keys.

### Visual consistency

| New element | Pattern source | Class/style |
|---|---|---|
| `<Button variant="secondary">` | shadcn `<Button>` primitive (existing) | `variant="secondary"` |
| `<details>` summary | new (no existing dashboard usage); inline Tailwind | `cursor-pointer text-muted-foreground` |
| `<AlertDialog>` family | `ui/src/components/proposals/reject-dialog.tsx:40-86` | shadcn AlertDialog (existing) |
| Success/failure toasts | `ui/src/components/clusters/cluster-action-bar.tsx` | `sonner` `toast.success` / `toast.error` |

### Component composition

`ResetDemoStateButton` is **extracted** into its own file rather than inlined inside `StartHereChecklist` because:
- It manages local state (`open`, `isPending`) the checklist itself doesn't need.
- It owns the TanStack `useQueryClient` dependency — keeping it isolated minimizes the checklist's prop surface.
- Vitest coverage is easier on a focused module than on a mixed module.

The checklist passes NO props to the button — the button reads `useQueryClient` from React context and POSTs the empty endpoint body.

### Legacy behavior parity

**No legacy behavior parity table — no user-facing component >100 LOC is being deleted or migrated in this plan.** `StartHereChecklist` is modified to ADD a disclosure beneath the 3-step list; the existing 3-step list, the existing render-null-when-all-done rule, and the existing data-testid hooks are all preserved verbatim.

---

## 3) Testing workstream

### 3.1 Unit tests
- Location: `backend/tests/unit/services/test_demo_seeding.py` (new — Story 1.1) + existing `backend/tests/unit/core/test_settings.py` extension (Story 1.0).
- Scope: `_resolve_engine_base_url` happy + error branches; `DEMO_RESEED_LOCK_KEY` deterministic; `TRUNCATE_TABLES` constant matches spec; settings field validator boundaries.
- Tasks:
  - [ ] Story 1.0: settings field unit test (default + range + env-var override) — 1 test case.
  - [ ] Story 1.1: 6 unit tests (3 resolver branches, lock key deterministic, ReseedSummary construction, TRUNCATE_TABLES constant mirror).
- DoD:
  - [ ] All unit tests in both files pass.
  - [ ] `make test-unit` green.

### 3.2 Integration tests
- Location: `backend/tests/integration/test_demo_seeding.py` (new — Story 3.2).
- Scope: 10 test cases covering AC-1, AC-2, AC-3, AC-4, AC-5, AC-12, AC-13, AC-14, AC-15, AC-16.
- Tasks:
  - [ ] Story 3.2: write all 10 tests; run against real Postgres + ES + OS in CI service containers.
- DoD:
  - [ ] All 10 tests pass.
  - [ ] `make test-integration` green.

### 3.3 Contract tests
- Location: `backend/tests/contract/test_test_endpoint_guard.py` + `backend/tests/contract/test_openapi_surface.py` (both modified — Story 3.1).
- Scope: env-guard 404 for `/_test/demo/reseed` across non-dev environments; OpenAPI surface registers the new endpoint at 200.
- Tasks:
  - [ ] Story 3.1: extend the parametrized 404 test; add OpenAPI registry entry.
- DoD:
  - [ ] Both modified files pass.
  - [ ] AC-6 covered.
  - [ ] `make test-contract` green.

### 3.4 E2E tests
- Location: `ui/tests/e2e/dashboard-reseed.spec.ts` (new — Story 3.3).
- Scope: real-backend end-to-end click-through covering AC-10.
- **Rule reaffirmed:** real `page` interactions, `request` only for setup wipe.
- Tasks:
  - [ ] Story 3.3: write the spec mirroring the existing `dashboard.spec.ts` pattern.
- DoD:
  - [ ] Spec passes against a live stack.
  - [ ] No `page.route()` mocking.

### 3.5 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `backend/tests/contract/test_test_endpoint_guard.py` | `_NON_DEV_ENVIRONMENTS` parametrized list | 1 (existing seed-completed assertion) | Extend to cover `/_test/demo/reseed` (Story 3.1). |
| `backend/tests/contract/test_openapi_surface.py` | endpoint registry tuple list | ~13 (line 96) | Add `("post", "/api/v1/_test/demo/reseed", "200")` (Story 3.1). |
| `ui/src/__tests__/components/dashboard/demo-data-banner.test.tsx` | dashboard component test | 1 | No change — covers an unrelated component (DemoDataBanner). |
| `ui/tests/e2e/dashboard.spec.ts` | dashboard E2E | 1 | No change — covers the populated-dashboard state; new reseed test is independent. |

### 3.6 Migration verification
**N/A — no schema change.** Spec §9: "No new tables. No schema changes. No migration."

### 3.7 CI gates
- [ ] `make test-unit`
- [ ] `make test-integration`
- [ ] `make test-contract`
- [ ] `cd ui && pnpm test` (vitest)
- [ ] `cd ui && pnpm test:e2e` (Playwright real-backend; gated to the new spec at minimum)
- [ ] `cd ui && pnpm build` (Next.js production build sanity)

---

## 4) Documentation update workstream

### 4.0 Core context files

**`state.md`** — update at finalization PR:
- [ ] Note feat_home_demo_reseed_endpoint completion + PR number
- [ ] Confirm Alembic head unchanged (still `0017_proposals_last_polled_at`)

**`architecture.md`** — no update needed (the feature does not add new services, layers, data flows, or integrations — it adds a dev-only endpoint that uses existing patterns).

**`CLAUDE.md`** — no update needed (no new conventions; the dev-only-endpoint pattern is already documented from `infra_e2e_seed_completed_study`).

### 4.1 Architecture docs (`docs/01_architecture`)
- [ ] Story 3.4: add `SEED_FAILED` (503) + `SEED_IN_PROGRESS` (409) to `api-conventions.md` error-code registry.

### 4.2 Product docs (`docs/02_product`)
- [ ] On finalization: move `docs/02_product/planned_features/feat_home_demo_reseed_endpoint/` to `docs/00_overview/implemented_features/<YYYY_MM_DD>_feat_home_demo_reseed_endpoint/`.

### 4.3 Runbooks (`docs/03_runbooks`)
- [ ] Story 3.4: create `docs/03_runbooks/demo-reseed-debugging.md`.

### 4.4 Security docs (`docs/04_security`)
- [ ] No update — no new secret/key handling; ES/OS basic-auth credentials are dev-stack defaults, not secrets.

### 4.5 Quality docs (`docs/05_quality`)
- [ ] No update — testing strategy unchanged.

**Documentation DoD**
- [ ] `state.md` reflects shipped feature (finalization PR).
- [ ] `api-conventions.md` lists the 2 new error codes.
- [ ] `demo-reseed-debugging.md` exists at canonical path.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals
None. The feature is purely additive — no existing code is being eliminated or refactored. The CLI script (`scripts/seed_meaningful_demos.py`) is **explicitly out of scope** per locked decision D2 in the spec.

### 5.2 Planned refactor tasks
None.

### 5.3 Refactor guardrails
N/A.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `httpx` Python package | Story 1.1, 1.2 | Implemented (`backend/app/llm/capability_check.py`, `adapters/elastic.py`) | None — present. |
| `pg_try_advisory_lock` Postgres function | Story 1.2 | Implemented (Postgres ≥ 9.1; MVP1 uses 16) | None — present. |
| `SCENARIOS`, `DEMO_ES_INDICES`, `DEMO_OS_INDICES`, `TRUNCATE_TABLES` constants in `scripts/seed_meaningful_demos.py` | Story 1.1 | Implemented (lines 67-82, 127+) | None — present. CLI script unchanged per D2. |
| `sonner` toast primitive | Story 2.1 | Implemented (used in `clusters/cluster-action-bar.tsx`) | None — present. |
| `@/components/ui/alert-dialog` primitive | Story 2.1 | Implemented (used in `proposals/reject-dialog.tsx`) | None — present. |
| Real ES + OS service containers in CI | Story 3.2 | Implemented (per CLAUDE.md §"CI/CD Workflows") | Story 3.2 tests would skip locally; CI catches the regression. |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| AC-16 (advisory-lock pinning test) flakes because of `pg_locks` query timing | M | M | Use explicit `time.sleep(0.1)` between observations; assert the `pid` column matches across all 3 observations (deterministic when properly pinned). |
| AC-12 (cleanup-while-locked race) timing is brittle | M | M | Use an event-based synchronization primitive — a `monkeypatch` injects an `asyncio.Event` that the cleanup pass awaits before committing, letting the test fire request B with deterministic timing. |
| Imports from `scripts.seed_meaningful_demos` fail inside the API container due to packaging | L | H | Verify the import works in a smoke test as part of Story 1.1; if it fails, add `scripts/__init__.py` (already missing per the earlier ls). |
| `httpx.AsyncClient(base_url="http://localhost:8000")` doesn't loopback from inside the API container | L | H | Verify in Story 1.2's integration test (AC-15 covers the routing assertion directly). FastAPI's TestClient + httpx have well-known loopback behavior; `localhost:8000` resolves to the API server's bound port. |
| Settings `demo_reseed_per_call_http_timeout_s` collides with another env-var name | VL | L | Prefix is unique; verified via grep. |
| The dual-`async with` block construction (`async with (a as x, b as y)` syntax) fails in mypy | L | L | If mypy complains, fall back to nested `async with` blocks. Equivalent semantics. |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| Single self-call exceeds `demo_reseed_per_call_http_timeout_s` | Slow ES/OS warmup OR forced delay in tests | `httpx.ReadTimeout` → orchestrator unwinds → cleanup runs → 503 `SEED_FAILED` | Operator: `docker compose restart api` then retry (per §10 Threat 4) |
| ES container unreachable mid-reseed | ES crash / docker compose stop elasticsearch | `httpx.ConnectError` → orchestrator unwinds → cleanup runs → 503 `SEED_FAILED` | Operator: bring ES back, retry |
| Two simultaneous reseed requests | Operator double-clicks the button OR concurrent test fires | First request acquires advisory lock; second gets 409 `SEED_IN_PROGRESS` | Wait for first to finish; second auto-cleans on success of first |
| API process crashes mid-reseed | OOM / kill -9 | Connection drops → session-level advisory lock auto-releases → demo tables in unknown state | Operator: `docker compose restart api` + `make seed-demo FORCE=1` from host OR re-fire the endpoint |
| `_resolve_engine_base_url` receives an unrecognized URL | CLI scenarios add a third engine target with a new host_base_url | `ValueError` raised → orchestrator unwinds → cleanup runs → 503 `SEED_FAILED` | Implementer: update `_resolve_engine_base_url` in the same PR that touches the CLI (loud failure mode is intentional per FR-1d) |

## 7) Sequencing and parallelization

### Suggested sequence
1. **Story 1.0** — Settings field (5 min — small Pydantic change + 1 unit test).
2. **Story 1.1** — `demo_seeding.py` service module (60-90 min — the bulk of the backend logic).
3. **Story 1.2** — Route handler (45-60 min — wires the service into the API surface).
4. **Story 3.1** — Contract tests (15 min — extends 2 existing files).
5. **Story 3.2** — Integration tests (90-120 min — 10 tests, several involve monkeypatch timing).
6. **Story 2.1** — Frontend button + dialog + vitest (60 min).
7. **Story 3.3** — Playwright E2E (30 min — single spec).
8. **Story 3.4** — Runbook + api-conventions update (15 min).

### Parallelization opportunities
- Stories 3.1 + 3.4 are independent of the rest of the backend stories — can run in parallel with 3.2 once 1.2 is done.
- Story 2.1 frontend work can begin AFTER Story 1.2 (endpoint must accept traffic before the UI can be wired).

## 8) Rollout and cutover plan

- Rollout stages: development only (this feature is dev-stack-only by construction).
- Feature flag strategy: none — `_require_development_env` IS the feature flag. Operators with `ENVIRONMENT=staging` or `production` will receive 404 on every reseed attempt.
- Migration/cutover steps: none.
- Reconciliation/repair strategy: per §10 Threat 4 — `docker compose restart api` on the ReadTimeout edge.

## 9) Execution tracker

### Current sprint
- [ ] Story 1.0 — Settings field
- [ ] Story 1.1 — Service module
- [ ] Story 1.2 — Route handler
- [ ] Story 2.1 — Frontend button
- [ ] Story 3.1 — Contract tests
- [ ] Story 3.2 — Integration tests
- [ ] Story 3.3 — Playwright E2E
- [ ] Story 3.4 — Runbook + api-conventions

### Blocked items
- None.

### Done this sprint
- (none yet)

## 10) Story-by-Story Verification Gate

Before marking any story complete, the executing agent must attach evidence for:

- [ ] Files created/modified match story scope.
- [ ] Endpoint contract implemented exactly as documented (method/path/body/status/error code).
- [ ] Key interfaces implemented with compatible signatures.
- [ ] Required tests added/updated for all relevant layers.
- [ ] Commands executed and passed:
  - [ ] `make test-unit`
  - [ ] `make test-integration` (or targeted subset)
  - [ ] `make test-contract`
  - [ ] `cd ui && pnpm test` (Story 2.1+)
  - [ ] `cd ui && pnpm test:e2e -- dashboard-reseed.spec.ts` (Story 3.3+)
- [ ] No migration round-trip needed (no schema change).
- [ ] Related docs updated in same PR when behavior/contract changed (Story 3.4 covers all doc updates).

## 11) Plan consistency review

1. **Spec ↔ plan endpoint count.** Spec §8.1 lists 1 endpoint (`POST /api/v1/_test/demo/reseed`). Plan covers it in Story 1.2. ✓
2. **Spec ↔ plan error-code coverage.** Spec §7.5 lists `SEED_FAILED` (503) + `SEED_IN_PROGRESS` (409). Plan Story 3.1 (env-guard contract test for 404 `RESOURCE_NOT_FOUND`) + Story 3.2 (integration tests for 409 + 503) cover all. ✓
3. **Spec ↔ plan FR coverage.** All 11 FRs (1, 1c, 1d, 2, 3, 4, 4b, 5 superseded, 6, 7, 8, 9, 10) traced in §1. ✓
4. **Story internal consistency.** Endpoint table in Story 1.2 matches the `ReseedSummary` schema in Story 1.1. DoD assertions reference real error codes. No file is claimed by two stories. ✓
5. **Test file count.** Tests added in Stories 1.0, 1.1, 2.1, 3.1, 3.2, 3.3. Each file appears in exactly one story's DoD. ✓
6. **Gate arithmetic.** No epic-level gates use endpoint counts; each story's DoD is self-contained. ✓
7. **Open questions resolved.** Spec §19 Open questions section is empty (all Q1/Q2/Q3 resolved + 14 cycles of decision-log entries). ✓
8. **Frontend UI Guidance completeness.** Plan-level "UI Guidance" section above includes: insertion point, analogous markup patterns, layout/structure, interaction behavior table, handler patterns, IA placement, tooltips (N/A — none needed), visual consistency table, component composition, legacy parity (N/A — no >100-LOC deletion). ✓
9. **Codebase verification (Pass 2).**
   - Migration directory: `migrations/versions/` (verified via `ls migrations/versions/`).
   - Current Alembic head: `0017_proposals_last_polled_at` (verified — no new migration needed; spec §9 confirms no schema change).
   - Router registration: `backend/app/main.py:37` imports `_test as test_router` (verified).
   - Component file: `ui/src/components/dashboard/start-here-checklist.tsx` exists at 152 LOC (verified).
   - `RejectDialog` pattern: `ui/src/components/proposals/reject-dialog.tsx:40-86` (verified — used as the AlertDialog template).
   - `sonner` import: `ui/src/components/clusters/cluster-action-bar.tsx:4` (verified).
   - Settings field pattern: `backend/app/core/settings.py` carries 6 `Field(ge=..., le=..., default=..., description=...)` precedents (verified).
   - `_err` helper: `backend/app/api/v1/_test.py:40` (verified).
   - `_require_development_env`: `backend/app/api/v1/_test.py:56` (verified).
   - `get_engine`: `backend/app/db/session.py:32` (verified).
   - `_TEST_PREFIX`: `backend/app/api/v1/_test.py:37` (verified).
10. **Enumerated value contract audit.** Endpoint accepts no request body; no filter/dropdown/badge/sort surface; spec §7.4 explicitly N/A. ✓
11. **Audit-event coverage audit (MVP2+ only).** RelyLoop is MVP1; `audit_log` table doesn't exist yet. Spec §6 documents the deferred MVP2 hook (`demo.reseed.completed`). No work needed in this plan. ✓

No unresolved findings.

---

## 12) Definition of plan done

- [x] Every FR mapped to stories/tasks/tests/docs.
- [x] Every story includes New files, Modified files (where applicable), Endpoints (where applicable), Key interfaces, Tasks, and DoD.
- [x] Test layers (unit/integration/contract/E2E) explicitly scoped per story.
- [x] Documentation updates across docs/01-05 planned and owned.
- [x] Lean refactor scope and guardrails explicit (N/A here — purely additive).
- [x] Phase/epic gates measurable.
- [x] Story-by-Story Verification Gate included.
- [x] Plan consistency review performed (§11).
