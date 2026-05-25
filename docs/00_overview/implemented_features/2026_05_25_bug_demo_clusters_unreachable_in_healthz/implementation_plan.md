# Implementation Plan — Cluster health warmup at API startup

**Date:** 2026-05-24
**Status:** Complete (PR #236, merged 2026-05-25 as squash commit `70b2ae46`)
**Primary spec:** [feature_spec.md](feature_spec.md)
**Policy source(s):** [CLAUDE.md](../../../../CLAUDE.md) Absolute Rules #6 (`/healthz` unauthenticated), #10 (never log/expose secrets), #11 (`/healthz` per-probe 200ms budget); [llm-orchestration.md §"Capability check at startup"](../../../01_architecture/llm-orchestration.md) (the canonical fire-and-forget startup-task pattern this plan mirrors).

---

## 0) Planning principles

- Spec traceability first: every story/task maps to FR-1 through FR-7 and one of AC-1 through AC-11.
- Single epic, single phase — bounded bug fix.
- Sequencing locked by data flow: FR-7 (`get_or_probe_health` cache-write fix) ships first because Story 1.2's warmup depends on its post-fix behavior. Then warmup module → lifespan wiring → docs.
- Pattern reuse: mirror [`backend/app/llm/capability_check.py:404-431`](../../../../backend/app/llm/capability_check.py#L404-L431) `run_capability_check_background` exactly — same skip-on-empty pattern, same try/except boundaries, same shutdown semantics.

## 1) Scope traceability (FR → epics/phases)

| FR ID | Story | Notes |
|---|---|---|
| FR-1 (startup warmup spawned) | Story 1.2 (function) + Story 1.3 (lifespan wiring) | The warmup module + the `asyncio.create_task` call live in different files; both stories ship the FR together. |
| FR-2 (skip empty registry) | Story 1.2 | Early-exit branch inside the warmup function. |
| FR-3 (per-cluster timeout, no global) | Story 1.2 | Per-cluster try/except in the pagination loop. |
| FR-4 (clean shutdown — task cancel + DB session release) | Story 1.3 (lifespan-level cancel) + Story 1.2 (`async with db_factory()`) | Split per spec §19 D-10 across two test files. |
| FR-5 (one summary log) | Story 1.2 | Single INFO event `cluster_health_warmup_completed` with the locked-down field set (no `cache_hits`/`probed` per D-8). |
| FR-6 (Redis-unavailable degradation) | Story 1.2 | Redis ping at top of warmup per D-9; WARN `cluster_health_warmup_redis_unavailable` on failure; warmup proceeds. |
| FR-7 (CredentialsMissing cache-write) | Story 1.1 | Modify [`backend/app/services/cluster.py:202-209`](../../../../backend/app/services/cluster.py#L202-L209) to `await write_cached_health(...)` before returning the synthetic HealthStatus. Ships FIRST so Story 1.2 can rely on every `get_or_probe_health` branch caching its result. |

All 7 FRs covered. No deferred phases.

## 2) Delivery structure

**Epic → Story → Tasks → DoD** (single epic, four stories sequenced strictly).

### Story-level detail requirements

Every story below includes Outcome / New files / Modified files / Key interfaces (where applicable) / Tasks / DoD. Endpoints + Pydantic schemas are N/A (this PR adds no endpoint surface — backend-only background task + on-demand cache-write fix).

### Conventions

- Pydantic v2 + `from __future__ import annotations` headers in every new file.
- `from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker` — the canonical session-factory type per [`backend/app/db/session.py:23-24`](../../../../backend/app/db/session.py#L23-L24).
- Structlog calls use kwargs (`logger.warning("msg", key=value)`); never f-strings into the message.
- `asyncio.CancelledError` is ALWAYS allowed to propagate inside background tasks (matches `run_capability_check_background` precedent at [`capability_check.py:424`](../../../../backend/app/llm/capability_check.py#L424)).
- Type hints required on all new function signatures (mypy `--strict` in CI).

### AI Agent Execution Protocol

0. Read `CLAUDE.md`, `architecture.md`, `state.md`, the spec, and this plan before Story 1.1.
1. Read each story's full scope before implementing.
2. Implement in order: Story 1.1 (FR-7 service-layer fix) → Story 1.2 (warmup module + tests) → Story 1.3 (lifespan wiring + tests) → Story 1.4 (docs).
3. Run `make lint` + `make typecheck` + targeted `make test-unit` after each story.
4. Phase gate: full `make test-unit` + `make test-integration` (with service containers when available; service-container-skipped otherwise per existing precedent) + `make test-contract`.

---

## Epic 1 — Cluster health cache warmup at startup + complete `get_or_probe_health` cache coverage

### Story 1.1 — Cache the `CredentialsMissing` HealthStatus before returning (FR-7)

**Outcome:** Every branch of `get_or_probe_health` writes the cluster's `HealthStatus` to Redis at `cluster:health:{cluster_id}` (30s TTL) before returning. The `CredentialsMissing` exception branch — currently returns the synthetic `HealthStatus(status="unreachable", error="credentials resolution failed: ...")` WITHOUT writing — now writes the synthetic HealthStatus to cache before returning. Downstream effect: Story 1.2's warmup populates the cache even for credentials-missing clusters, and the existing `probe_registered_clusters` aggregate stops re-reporting cache-miss for them.

**New files**

| File | Purpose |
|---|---|
| [`backend/tests/unit/services/test_cluster_service.py`](../../../../backend/tests/unit/services/test_cluster_service.py) | New unit-test file for `get_or_probe_health`. No prior dedicated test file exists (verified: `find backend/tests/unit -name 'test_cluster*' → empty`; cluster service is currently exercised only via `backend/tests/integration/test_clusters_api.py`). AC-11 regression guard lives here. |

**Modified files**

| File | Change |
|---|---|
| [`backend/app/services/cluster.py`](../../../../backend/app/services/cluster.py) | Lines 202-209 (`except CredentialsMissing` block): assign the synthesized `HealthStatus` to a local variable `health`; `await write_cached_health(redis, cluster.id, health)`; `return health`. No new imports — `write_cached_health` is already imported at line 48. |

**Key interfaces**

```python
# backend/app/services/cluster.py — unchanged public signature
async def get_or_probe_health(redis: Redis, cluster: Cluster) -> HealthStatus:
    cached = await read_cached_health(redis, cluster.id)
    if cached is not None:
        return cached
    try:
        adapter = build_adapter(cluster)
    except CredentialsMissing as exc:
        # POST-FIX: synthesize, cache, return — was previously return-without-cache.
        health = HealthStatus(
            status="unreachable",
            checked_at=datetime.now(UTC).isoformat(),
            error=f"credentials resolution failed: {exc}",
        )
        await write_cached_health(redis, cluster.id, health)
        return health
    try:
        health = await adapter.health_check()
    finally:
        await adapter.aclose()
    await write_cached_health(redis, cluster.id, health)
    return health
```

**Tasks**

1. Edit [`backend/app/services/cluster.py:202-209`](../../../../backend/app/services/cluster.py#L202-L209) per Key interfaces above. Keep the `f"credentials resolution failed: {exc}"` error string verbatim — existing callers (logs, future operator-facing tooling) may grep for it.
2. Create [`backend/tests/unit/services/test_cluster_service.py`](../../../../backend/tests/unit/services/test_cluster_service.py) with these unit tests (per cycle-1 B1, AC-3 is a service-layer test, not a warmup-layer test — moved here from Story 1.2):
   - **AC-11 positive (CredentialsMissing writes cache):** Build a `Cluster` ORM instance with `auth_kind="es_basic"`, `credentials_ref="missing-ref-xyz"`; mock `build_adapter` to raise `CredentialsMissing("entry not found: missing-ref-xyz")`; mock `redis` with `read_cached_health → None` on first call AND a recorded `set` (or proxy the `write_cached_health` import). First call: assert returned `HealthStatus.status == "unreachable"`, `.error` contains `"missing-ref-xyz"`, AND `redis.set.call_count == 1` with `cache_key(cluster.id)` argument.
   - **AC-11 negative (second call is cache-hit, no re-build):** After the first call wrote the cache, monkeypatch `read_cached_health` to return the previously-set value; mock `build_adapter` to raise `pytest.fail("build_adapter must not be invoked on cache hit")`. Call `get_or_probe_health(redis, cluster)` again; assert it returns the cached HealthStatus without re-invoking `build_adapter`.
   - **AC-3 (cache-hit short-circuits `build_adapter` + `health_check`):** Configure `read_cached_health` to return a pre-built `HealthStatus(status="green", ...)`. Monkeypatch `backend.app.services.cluster.build_adapter` to a function that raises if called. Call `get_or_probe_health(redis, cluster)`; assert it returns the cached `HealthStatus("green")` AND `build_adapter` was NOT invoked AND no `adapter.health_check()` call ran. **This is the AC-3 service-layer test; it does NOT live in the warmup test file because the cache-first behavior is INSIDE `get_or_probe_health`, not inside the warmup.**
3. Run `.venv/bin/ruff format backend/app/services/cluster.py backend/tests/unit/services/test_cluster_service.py && .venv/bin/ruff check ... && .venv/bin/mypy backend/app/services/cluster.py` — all clean.
4. Run `.venv/bin/pytest backend/tests/unit/services/test_cluster_service.py -v` — both cases pass.

**Definition of Done (DoD)**

- [ ] [`backend/app/services/cluster.py:202-209`](../../../../backend/app/services/cluster.py#L202-L209) writes cache in the `CredentialsMissing` branch.
- [ ] AC-11 regression test in `test_cluster_service.py` passes (positive case: `write_cached_health` invoked once; negative case: second call doesn't re-build adapter).
- [ ] `make lint` + `make typecheck` + targeted `pytest` pass.
- [ ] Full `make test-unit` passes (no regression in existing tests — `read_cached_health` / `write_cached_health` consumers in `backend/app/api/v1/clusters.py` are read-only consumers and unaffected by this change).
- [ ] Coverage gate 80% maintained.
- [ ] No new branches in `get_or_probe_health` — the change is one assignment + one `await` in an existing branch.

---

### Story 1.2 — Add `run_cluster_health_warmup_background` service module (FR-1, FR-2, FR-3, FR-5, FR-6, FR-4 partial — DB session)

**Outcome:** A new fire-and-forget async function in [`backend/app/services/cluster_health_warmup.py`](../../../../backend/app/services/cluster_health_warmup.py) (created by this story) that pages through all registered clusters in 200-row windows, calls `cluster_svc.get_or_probe_health(redis, cluster)` for each, swallows per-cluster errors, emits one INFO summary on completion, and emits a WARN if Redis is unavailable at start (D-9). The function opens its DB session via `async with db_factory() as db:` so cancellation cleanly releases the session per FR-4. Logically self-contained — Story 1.3 will wire it into the lifespan.

**New files**

| File | Purpose |
|---|---|
| [`backend/app/services/cluster_health_warmup.py`](../../../../backend/app/services/cluster_health_warmup.py) | The warmup function. Mirrors the `run_capability_check_background` structure at [`backend/app/llm/capability_check.py:404-431`](../../../../backend/app/llm/capability_check.py#L404-L431). |
| [`backend/tests/unit/services/test_cluster_health_warmup.py`](../../../../backend/tests/unit/services/test_cluster_health_warmup.py) | Unit tests for the warmup function — covers AC-2, AC-3, AC-4, AC-5, AC-6 + FR-5 log shape + FR-6 Redis-ping branch + FR-4 mid-loop cancellation DB session release. |

**Modified files**

None.

**Key interfaces**

```python
# backend/app/services/cluster_health_warmup.py
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.core.logging import get_logger
from backend.app.db import repo
from backend.app.services import cluster as cluster_svc

if TYPE_CHECKING:
    # type-only — avoids circular imports at runtime
    ...

logger = get_logger(__name__)


async def run_cluster_health_warmup_background(
    db_factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
) -> None:
    """Fire-and-forget startup task that warms ``cluster:health:*`` for every
    registered cluster.

    Mirrors :func:`backend.app.llm.capability_check.run_capability_check_background`:
    propagates ``asyncio.CancelledError`` for clean shutdown; catches every
    other exception so a broken cluster / DB / Redis cannot crash the API.

    Behavior contract (per ``feature_spec.md`` §7 FR-1..FR-6):

    - Pings Redis once at the top (D-9). On failure: log
      ``cluster_health_warmup_redis_unavailable`` at WARN and proceed —
      ``cluster:health:*`` writes will silently fail in the cache helpers
      anyway, but per-cluster ``adapter.health_check()`` WARN logs still
      surface to the operator.
    - Opens the DB session via ``async with db_factory() as db:`` so the
      session is released on normal completion AND on
      ``asyncio.CancelledError`` propagation (Python context-manager
      protocol guarantee).
    - Empty registry: emit ``cluster_health_warmup_skipped`` INFO with
      ``count=0`` and exit without paginating.
    - Otherwise: page through ``repo.list_clusters(db, cursor=..., limit=200)``;
      for each cluster, call ``cluster_svc.get_or_probe_health(redis, cluster)``
      inside a per-cluster try/except. Swallow per-cluster errors (log WARN
      with cluster ID + name + short error string; never credentials).
    - Emit one ``cluster_health_warmup_completed`` INFO log on exit with
      ``count``, ``failures``, ``duration_ms``. NO ``cache_hits`` /
      ``probed`` counters (D-8: ``get_or_probe_health: HealthStatus``
      exposes no source distinction).
    """
    start = time.monotonic()
    # FR-6 / D-9: Redis ping before any work. Cache helpers swallow Redis
    # errors silently; the explicit ping is the operator-visible signal.
    # The positional message string is the structlog `event` field — that's
    # the stable identifier tests assert against (per cycle-1 A1 — using
    # `event_type=` as a kwarg duplicates the positional and confuses
    # structlog's event-field semantics).
    try:
        await redis_client.ping()
    except Exception as exc:  # noqa: BLE001 — Redis-down is non-fatal
        logger.warning(
            "cluster_health_warmup_redis_unavailable",
            error=str(exc),
        )
        # Continue — per-cluster probes still log if they fail.

    failures = 0
    count = 0
    try:
        async with db_factory() as db:
            registered = await repo.count_clusters(db)
            if registered == 0:
                logger.info("cluster_health_warmup_skipped", count=0)
                return

            cursor: tuple[object, str] | None = None
            while True:
                page = await repo.list_clusters(db, cursor=cursor, limit=200)
                if not page:
                    break
                for c in page:
                    count += 1
                    try:
                        await cluster_svc.get_or_probe_health(redis_client, c)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # noqa: BLE001 — per-cluster swallow
                        failures += 1
                        logger.warning(
                            "Cluster health warmup: per-cluster probe failed",
                            cluster_id=c.id,
                            cluster_name=c.name,
                            error=str(exc),
                        )
                if len(page) < 200:
                    break
                last = page[-1]
                cursor = (last.created_at, last.id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — task-level swallow
        logger.warning(
            "Cluster health warmup raised unexpectedly; swallowing",
            error=str(exc),
        )
        return

    duration_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "cluster_health_warmup_completed",
        count=count,
        failures=failures,
        duration_ms=duration_ms,
    )
```

**Tasks**

1. Create [`backend/app/services/cluster_health_warmup.py`](../../../../backend/app/services/cluster_health_warmup.py) with the function above. Use the exact structlog event names listed in Key interfaces (matches spec FR-5 / FR-6 / D-9 wording).
2. Create [`backend/tests/unit/services/test_cluster_health_warmup.py`](../../../../backend/tests/unit/services/test_cluster_health_warmup.py) with these test classes (each test maps to one or more ACs from the spec):

   ```python
   class TestEmptyRegistry:
       async def test_count_clusters_zero_skips_paginate(self):
           # AC-4: count → 0 yields skip log, list_clusters NOT called.
           ...

   class TestHappyPath:
       async def test_warmup_walks_all_clusters(self):
           # AC-2 + FR-5 log shape: 2 clusters, both probed, completion log
           # has count=2, failures=0, duration_ms >= 0.
           ...

       async def test_warmup_unaffected_by_get_or_probe_health_cache_hits(self):
           # The warmup just calls get_or_probe_health once per cluster. The
           # function's cache-first behavior is tested at the service layer
           # in test_cluster_service.py (AC-3 per cycle-1 B1). Here we just
           # assert the warmup completes cleanly when get_or_probe_health
           # returns cached values (mock it to return without crashing).
           ...

   class TestPerClusterFailures:
       async def test_one_cluster_raises_loop_continues(self):
           # AC-5: mock get_or_probe_health to raise for cluster[1] only.
           # Assert: clusters[0] + clusters[2] both completed; completion log
           # has count=3, failures=1; WARN log for cluster[1] fired with
           # cluster_id + cluster_name + error.
           ...

       async def test_task_level_exception_swallowed(self):
           # AC-6: mock repo.list_clusters to raise. Assert: no exception
           # propagates out of run_cluster_health_warmup_background; WARN
           # fires; function returns.
           ...

   class TestRedisDownAtStart:
       async def test_redis_ping_failure_logs_warn_and_continues(self):
           # FR-6 + D-9: mock redis.ping to raise; warmup STILL calls
           # get_or_probe_health for each cluster; WARN
           # cluster_health_warmup_redis_unavailable fires once before any
           # per-cluster work.
           ...

   class TestShutdownCancellation:
       async def test_cancellation_releases_db_session(self):
           # FR-4 D-10: build a fake async_sessionmaker whose context-manager
           # records __aexit__ invocation. Use TWO synchronization events
           # (per cycle-1 B3 — a fixed sleep is flaky on slow CI runners):
           #   - `entered_ctx = asyncio.Event()` — set inside the fake's
           #     __aenter__, signaling the warmup has entered `async with`.
           #   - `probe_started = asyncio.Event()` — set by the mocked
           #     get_or_probe_health BEFORE awaiting forever.
           # The test:
           #   task = asyncio.create_task(run_cluster_health_warmup_background(
           #       fake_factory, mock_redis))
           #   await probe_started.wait()  # synchronized: warmup is mid-loop
           #   task.cancel()
           #   with pytest.raises(asyncio.CancelledError):
           #       await task
           # Assert: entered_ctx.is_set() == True (warmup entered the DB
           # session) AND fake_session.exit_calls == 1 (context manager
           # __aexit__ ran during CancelledError propagation, releasing the
           # session).
           ...
   ```

   Use `structlog.testing.capture_logs()` for log assertions (existing pattern at [`backend/tests/unit/test_capability_check.py:195`](../../../../backend/tests/unit/test_capability_check.py#L195)).

3. Run `.venv/bin/ruff format backend/app/services/cluster_health_warmup.py backend/tests/unit/services/test_cluster_health_warmup.py && .venv/bin/ruff check ... && .venv/bin/mypy backend/app/services/cluster_health_warmup.py` — all clean.
4. Run `.venv/bin/pytest backend/tests/unit/services/test_cluster_health_warmup.py -v` — all 7 cases pass.

**Definition of Done (DoD)**

- [ ] [`backend/app/services/cluster_health_warmup.py`](../../../../backend/app/services/cluster_health_warmup.py) exists with `run_cluster_health_warmup_background(db_factory, redis_client) -> None`.
- [ ] All 7 unit-test cases pass (empty registry, happy path × 2, per-cluster fail × 2, Redis-ping-down, shutdown cancellation with DB session release).
- [ ] `make lint` + `make typecheck` + `make test-unit` pass.
- [ ] No call from Story 1.3 yet — this story is self-contained. Function is importable but not yet wired.
- [ ] Coverage gate 80% maintained (the new function has 100% branch coverage from the 7 cases).
- [ ] Structlog event names match the spec literals exactly (`cluster_health_warmup_skipped`, `cluster_health_warmup_completed`, `cluster_health_warmup_redis_unavailable`).

---

### Story 1.3 — Wire warmup into FastAPI lifespan (FR-1 spawn + FR-4 shutdown cancel)

**Outcome:** The FastAPI `lifespan` context manager in [`backend/app/main.py:59-132`](../../../../backend/app/main.py#L59-L132) spawns the warmup task via `asyncio.create_task` immediately after the capability-check task (line 85), and cancels/awaits/swallows it on shutdown in the same pattern (lines 121-131). No new conventions; mirrors the capability-check task exactly.

**New files**

| File | Purpose |
|---|---|
| [`backend/tests/unit/test_main_lifespan.py`](../../../../backend/tests/unit/test_main_lifespan.py) | Lifespan-level tests for AC-1 (both background tasks spawned) and AC-7 (shutdown cancel/await ordering). Split per D-10. |

**Modified files**

| File | Change |
|---|---|
| [`backend/app/main.py`](../../../../backend/app/main.py) | (a) Add `from backend.app.db.session import get_session_factory` to the import block at lines 33-49. (b) Add `from backend.app.services.cluster_health_warmup import run_cluster_health_warmup_background` to imports. (c) After line 91 (the `cap_task = asyncio.create_task(...)` block), capture `db_factory = get_session_factory()` and add `warmup_task = asyncio.create_task(run_cluster_health_warmup_background(db_factory, redis_client))`. (d) In the `finally` block at lines 113-131, add a mirrored cancel/await/swallow block for `warmup_task` after the capability-check shutdown (matching the existing pattern verbatim). |

**Key interfaces**

The lifespan hook gains one block (insertion point: between the existing `cap_task = ...` at line 91 and the `from arq.connections import ...` at line 99):

```python
# main.py — INSERT after line 91 (the cap_task assignment), BEFORE the arq import:
db_factory = get_session_factory()
warmup_task = asyncio.create_task(
    run_cluster_health_warmup_background(db_factory, redis_client)
)
```

And the shutdown block at lines 121-131 gains a parallel mirror (insertion point: after the existing `cap_task` cancel/await/swallow block, before `await redis_client.aclose()` at line 132):

```python
# main.py — INSERT after the cap_task shutdown block at lines 121-131:
if not warmup_task.done():
    warmup_task.cancel()
    try:
        await warmup_task
    except asyncio.CancelledError:
        pass
    except Exception as exc:  # noqa: BLE001 — shutdown swallow
        logger.warning(
            "Cluster health warmup task raised during shutdown",
            error=str(exc),
        )
```

**Tasks**

1. Edit [`backend/app/main.py`](../../../../backend/app/main.py) per the Key interfaces block above. Two import additions; one `asyncio.create_task` block in the lifespan setup; one cancel/await/swallow block in the shutdown.
2. Create [`backend/tests/unit/test_main_lifespan.py`](../../../../backend/tests/unit/test_main_lifespan.py) with these tests:

   ```python
   # Per cycle-2 B1: lifespan tests are NOT hermetic by default — entering
   # the real lifespan in main.py constructs a Redis client (line 84) AND
   # awaits arq.connections.create_pool (line 103) AND calls
   # get_session_factory() (after Story 1.3's edit). All four need to be
   # patched to fakes BEFORE entering the lifespan context, otherwise the
   # tests perform real infrastructure I/O / hang / become
   # environment-dependent.
   #
   # Common-fixture pattern:
   #   def _patch_lifespan_externals(monkeypatch):
   #       monkeypatch.setattr(main, "get_settings", lambda: _fake_settings())
   #       monkeypatch.setattr("redis.asyncio.Redis.from_url", lambda *a, **kw: _fake_redis())
   #       monkeypatch.setattr(main, "get_session_factory", lambda: _fake_factory())
   #       monkeypatch.setattr("arq.connections.create_pool", _fake_pool_factory)

   class TestLifespanSpawnsBothTasks:
       async def test_lifespan_spawns_capability_and_warmup_tasks(self, monkeypatch):
           # AC-1: patch externals (Redis, get_session_factory, arq.create_pool,
           # get_settings) per the common fixture above. Patch
           # run_capability_check_background AND run_cluster_health_warmup_background
           # to lightweight async coroutines that record invocation. Enter
           # the lifespan via `async with app.router.lifespan_context(app)`.
           # Assert: BOTH coroutines were invoked exactly once.
           ...

   class TestLifespanShutdownCancels:
       async def test_shutdown_cancels_warmup_task_if_running(self, monkeypatch):
           # AC-7 (lifespan side): per cycle-2 B2, use explicit cancel-seen
           # signaling instead of the weak "no warning" check. Patch the
           # warmup with:
           #
           #   started = asyncio.Event()
           #   cancel_seen = asyncio.Event()
           #   async def fake_warmup(db_factory, redis_client):
           #       started.set()
           #       try:
           #           await asyncio.Event().wait()  # block forever
           #       except asyncio.CancelledError:
           #           cancel_seen.set()
           #           raise
           #
           # Enter lifespan, await `started`, exit context. Assert:
           # `cancel_seen.is_set()` is True (cancellation was delivered AND
           # caught — proves main.py's cancel/await/swallow ran).
           ...

       async def test_shutdown_cancels_capability_task_unchanged(self, monkeypatch):
           # FR-4 regression: same pattern but for the capability task.
           # Proves Story 1.3's edit didn't break the existing shutdown
           # ordering.
           ...
   ```

   These tests are lifespan-level — they verify spawn + cancel ordering. The DB session release on cancellation is tested at the function level in Story 1.2's `TestShutdownCancellation::test_cancellation_releases_db_session`.

3. Run `.venv/bin/ruff format backend/app/main.py backend/tests/unit/test_main_lifespan.py && .venv/bin/ruff check ... && .venv/bin/mypy backend/app/main.py` — all clean.
4. Run `.venv/bin/pytest backend/tests/unit/test_main_lifespan.py -v` — all 3 cases pass.
5. **Operator-path verification (CLAUDE.md test-execute gate, strengthened per cycle-1 B5 + cycle-3 B1):** `make up` against the local stack; `make seed-clusters` (and/or `make seed-demo FORCE=1` if you want the 4 demos); **explicitly flush the Redis cache** to defeat the 30s TTL keeping it warm across restarts: `docker compose exec redis redis-cli --scan --pattern 'cluster:health:*' | xargs -r docker compose exec -T redis redis-cli del`. Verify cold: `docker compose exec redis redis-cli keys 'cluster:health:*'` returns empty. THEN `docker compose restart api`. **Bounded-poll** for the warmup-completion log (NOT a one-shot grep — the warmup is fire-and-forget per `main.py:85+82-91`, so a single grep can race the spawn): `timeout 15 sh -c 'until docker compose logs api --since 30s 2>/dev/null | grep -q cluster_health_warmup_completed; do sleep 0.25; done'`. Once that returns 0, `curl -s http://127.0.0.1:8000/healthz | jq '.subsystems.elasticsearch_clusters'`; verify `healthy: N` matches the seeded count. If `unreachable: N`, the warmup hit per-cluster errors — `docker compose logs api | grep 'cluster health warmup'` for per-cluster WARN entries. (For CI, the integration test in Story 1.2 covers this with the in-process equivalent.)

**Definition of Done (DoD)**

- [ ] `backend/app/main.py` spawns the warmup task in lifespan setup AND cancels it in lifespan teardown.
- [ ] Both new imports (`get_session_factory`, `run_cluster_health_warmup_background`) land cleanly.
- [ ] All 3 lifespan tests pass.
- [ ] Existing tests under `backend/tests/unit/test_health.py` and `backend/tests/unit/test_capability_check.py` continue to pass (no regression to the capability-check task lifecycle).
- [ ] `make lint` + `make typecheck` + `make test-unit` pass.
- [ ] Coverage gate 80% maintained.
- [ ] Operator-path verification confirms `/healthz` reports truthful counts within ~6s of api-container restart.

---

### Story 1.4 — Update `docs/01_architecture/data-model.md` with warmup paragraph

**Outcome:** Architecture doc reflects the dual cache-population paths (startup warmup + lazy on-demand) so future implementers / operators understand the design. Includes the race-window caveat ("/healthz reports `unreachable: N` for ~5s post-boot until warmup completes").

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| [`docs/01_architecture/data-model.md`](../../../01_architecture/data-model.md) | Append (or insert into the existing "Cluster health caching" section if present, otherwise create a new subsection adjacent to the existing cluster-table description) a paragraph describing: (a) the `cluster:health:*` 30s TTL; (b) the two cache-population paths — startup warmup (`run_cluster_health_warmup_background`) + lazy on-demand (`cluster_svc.get_or_probe_health` from `/api/v1/clusters` endpoints); (c) the `register_cluster` path also caches at registration time per `cluster.py:147+188`; (d) `/healthz` observable behavior — reports `unreachable: N` only during the ~5s race window post-boot until warmup completes. |

**Tasks**

1. Read the current state of [`docs/01_architecture/data-model.md`](../../../01_architecture/data-model.md) to find the right insertion point — either an existing "Cluster health caching" subsection (from the 2026-05-09 Decision Log) or adjacent to the cluster-table description.
2. Append the paragraph following the spec's §15 wording closely:

   ```markdown
   ### Cluster health caching

   The `cluster:health:{cluster_id}` Redis cache (30s TTL — Decision Log
   2026-05-09) is populated through THREE complementary paths:

   1. **Registration:** `register_cluster` in `backend/app/services/cluster.py`
      probes the cluster and writes the cached `HealthStatus` to Redis
      before returning the new cluster to the API caller (lines 147 + 188).
      So `POST /api/v1/clusters` always lands with a fresh cache row.
   2. **Lazy on-demand:** `cluster_svc.get_or_probe_health` reads the cache
      first; on miss, it probes and writes. Called from `GET /api/v1/clusters`
      (per-row in the list response) and `GET /api/v1/clusters/{id}`. Every
      branch — cache hit, successful probe, AND `CredentialsMissing` exception —
      ends with a populated cache row (the `CredentialsMissing` cache-write
      shipped in `bug_demo_clusters_unreachable_in_healthz`).
   3. **Startup warmup:** `run_cluster_health_warmup_background` (fire-and-
      forget background task spawned by `lifespan` in `backend/app/main.py`)
      pages through all registered clusters at API startup and calls
      `get_or_probe_health` for each. This closes the cold-cache gap
      between boot and the first `/api/v1/clusters` request, which would
      otherwise cause `/healthz` to report `elasticsearch_clusters.unreachable: N`
      for ~30s post-boot.

   **`/healthz` race-window caveat:** The aggregate `elasticsearch_clusters`
   field in `/healthz` is a cache-only read (per CLAUDE.md Absolute Rule #11 —
   no live probes inside the request budget). For roughly the first ~5
   seconds after API startup, while the warmup task is running, `/healthz`
   may still report cache-miss-as-unreachable for clusters the warmup hasn't
   yet reached. Operators polling `/healthz` immediately after `make up`
   should expect to see the count converge as the warmup completes.
   ```

3. Stage + commit. No tests for doc changes; markdown-lint may run via pre-commit.

**Definition of Done (DoD)**

- [ ] [`docs/01_architecture/data-model.md`](../../../01_architecture/data-model.md) contains the three-path cache-population description + race-window caveat.
- [ ] `make lint` passes (markdown-lint if enabled).
- [ ] No code/test changes in this story.

---

## 3) Testing workstream

Tests are co-located inside each story's DoD (RelyLoop convention). The cross-story inventory:

### 3.1 Unit tests

- Location: `backend/tests/unit/services/test_cluster_service.py` (NEW — Story 1.1), `backend/tests/unit/services/test_cluster_health_warmup.py` (NEW — Story 1.2), `backend/tests/unit/test_main_lifespan.py` (NEW — Story 1.3).
- Tasks:
  - [ ] **Story 1.1 (test_cluster_service.py):** 2 cases — AC-11 positive (CredentialsMissing writes cache) + AC-11 negative (second call is cache-hit, no re-build).
  - [ ] **Story 1.2 (test_cluster_health_warmup.py):** 7 cases — empty registry skip, happy-path walk-all, cache-first idempotency, per-cluster fail × 2, Redis ping fail, shutdown cancellation releases DB session.
  - [ ] **Story 1.3 (test_main_lifespan.py):** 3 cases — both tasks spawned (AC-1), shutdown cancels warmup, shutdown cancels capability-check unchanged.
- DoD:
  - [ ] All 12 new unit cases pass.
  - [ ] `cluster_health_warmup_completed` / `cluster_health_warmup_skipped` / `cluster_health_warmup_redis_unavailable` event names appear in tests exactly as in the warmup module (regression guard for D-9 wording).

### 3.2 Integration tests

- Location: [`backend/tests/integration/test_cluster_health_warmup.py`](../../../../backend/tests/integration/test_cluster_health_warmup.py) — NEW, marked `@pytest.mark.integration`.
- Tasks:
  - [ ] **AC-8 (end-to-end happy path):** Seed 2 clusters via the existing test-DB fixture; `await redis.delete(*cache_keys_for_seeded_clusters)` (explicit cold cache per cycle-1 B2); enter the structlog capture context BEFORE spawning the task (cycle-3 B2 — the completion event fires inside the task; the capture must be active before the task is created or the event is missed):

    ```python
    with structlog.testing.capture_logs() as logs:
        task = asyncio.create_task(
            run_cluster_health_warmup_background(session_factory, redis)
        )
        # Bounded polling — assertion fails clearly on flake instead of hanging:
        async def _completed() -> bool:
            return any(r.get("event") == "cluster_health_warmup_completed" for r in logs)
        await _wait_until(_completed, timeout=10.0, poll=0.05)
        await task  # ensure task is fully awaited (no pending-coroutine warning)
    ```

    Time-based `asyncio.sleep` is forbidden (cycle-1 B2 — flaky). Alternative: poll Redis `EXISTS` for the expected `cluster:health:{id}` keys (use this instead of `capture_logs` if the test framework's log capture conflicts with the warmup's logger configuration). Assert: `/healthz` (via `httpx.AsyncClient(transport=ASGITransport(app))`) returns `subsystems.elasticsearch_clusters == {"registered": 2, "healthy": 2, "unreachable": 0}`.
  - [ ] **AC-9 (backwards-compat — response contract unchanged):** Run the warmup, then issue `GET /api/v1/clusters?limit=200`; assert the response shape is identical to the pre-fix shape (no new fields; existing `ClusterSummary.health_check` populated). **Do not** assert "first list call → exactly N probe invocations" — that would conflict with cycle-1 B7 (warmup may pre-warm the cache; the cache-first design intentionally serves cached health on the first list call).
  - [ ] **AC-10 (post-warmup out-of-band-insert lazy-warm chain — 7 steps, fixes cycle-1 B4 missing-commit):** (1) run warmup → (2) assert `/healthz` `unreachable: 0` → (3) `await repo.create_cluster(db, name="post-warmup-cluster", ...)` (direct ORM, NOT `POST /api/v1/clusters`, per cycle-2 B1) → **(3.5) `await db.commit()`** — CRITICAL per cycle-1 B4: [`repo.create_cluster` at `backend/app/db/repo/cluster.py:39-45`](../../../../backend/app/db/repo/cluster.py#L39-L45) only flushes; the docstring states "Caller commits." Without this `await db.commit()`, the `/healthz` request runs in its own DB session and won't see the uncommitted row → (4) assert `/healthz` `unreachable: 1` (new cluster cache-miss) → (5) issue `GET /api/v1/clusters?limit=200` to trigger lazy warm → (6) assert `/healthz` `unreachable: 0` again.
- DoD:
  - [ ] All 3 integration cases pass under the existing service-container fixture (skip outside CI per existing precedent at `backend/tests/contract/test_clusters_api_contract.py`).
  - [ ] No flaky time-based waits; all assertions gated on deterministic signals.

### 3.3 Contract tests

N/A — no API surface change. The `ClusterAggregateHealth` response shape is unchanged (D-2).

### 3.4 E2E tests

N/A — no UI change. The dashboard banner failure flagged in the idea is decoupled (D-6) and out of scope.

### 3.5 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| [`backend/tests/unit/test_probes.py`](../../../../backend/tests/unit/test_probes.py) | `probe_registered_clusters` tests (2 cases: zero-clusters returns zeros, counts-by-cached-status) | 2 cases | No change — `probe_registered_clusters` semantics unchanged. The warmup populates the cache upstream; the aggregator behavior is identical. |
| [`backend/tests/unit/test_health.py`](../../../../backend/tests/unit/test_health.py) | `/healthz` response shape tests | ~16 cases | No change — `ClusterAggregateHealth` response shape unchanged per D-2. The startup warmup doesn't run inside test fixtures (lifespan-spawn is monkeypatched in test_main_lifespan.py only). |
| [`backend/tests/unit/test_capability_check.py`](../../../../backend/tests/unit/test_capability_check.py) | Capability-check task tests | ~23 cases | No change — Story 1.3 keeps the capability-check task lifecycle identical; new tests in `test_main_lifespan.py` verify that explicitly. |
| [`backend/tests/integration/test_clusters_api.py`](../../../../backend/tests/integration/test_clusters_api.py) | `/api/v1/clusters` endpoint tests | TBD via Pass 1 grep | If any test mocks `adapter.health_check` and asserts "first list call → N probes," update per AC-9 / cycle-1 B7 — the warmup may pre-warm the cache. (Likely no such test exists; verify in Story 1.3.) |
| [`backend/tests/integration/test_clusters_api_targets_errors.py`](../../../../backend/tests/integration/test_clusters_api_targets_errors.py) | Targets endpoint errors | TBD | Likely unaffected (different endpoint). |

### 3.6 Migration verification

N/A — no Alembic migration.

### 3.7 CI gates

- [ ] `make test-unit` (12 new unit cases pass + all 16+ existing pass)
- [ ] `make test-integration` (3 new integration cases pass when service containers available; skipped outside CI)
- [ ] `make test-contract` (no new contract cases; full suite stays green)
- [ ] `make lint` (ruff)
- [ ] `make typecheck` (mypy `--strict`)
- [ ] Coverage gate 80% maintained

---

## 4) Documentation update workstream

### 4.0 Core context files

- [ ] **`state.md`** — post-merge entry in "Most recent meaningful changes" (handled by `impl-execute` finalization, not in story scope).
- [ ] **`architecture.md`** — no update needed (the change is internal to existing cluster-health caching design; doc update lives in `data-model.md`).
- [ ] **`CLAUDE.md`** — no convention or absolute-rule changes.

### 4.1 Architecture docs (`docs/01_architecture`)

- [x] **Story 1.4:** Append the three-path cache-population subsection to `data-model.md` (per FR-4 / §15 of the spec).

### 4.2 Product docs (`docs/02_product`)

- [ ] Move the `bug_demo_clusters_unreachable_in_healthz/` folder to `docs/00_overview/implemented_features/<YYYY_MM_DD>_<short_name>/` after merge (handled by `impl-execute` finalization).

### 4.3 Runbooks (`docs/03_runbooks`)

- [ ] No new runbook needed. The structlog events `cluster_health_warmup_completed` / `cluster_health_warmup_skipped` / `cluster_health_warmup_redis_unavailable` are self-documenting and follow the existing capability-check log conventions.

### 4.4 Security docs (`docs/04_security`)

- [ ] No new security doc needed. The warmup is read-only against existing infrastructure; no new secrets, no new auth surfaces, no new data flows.

### 4.5 Quality docs (`docs/05_quality`)

- [ ] No quality-doc updates — `docs/05_quality/testing.md` 80% coverage gate is maintained, no new test layers introduced.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

None — this is a bounded bug fix. No code is being relocated.

### 5.2 Planned refactor tasks

None.

### 5.3 Refactor guardrails

- [x] No expansion of product scope (D-2, D-3 explicitly reject Option B and the cron).
- [x] Behavioral parity proven by tests (AC-9 backwards-compat + AC-3 cache-first preservation).
- [x] Lint/typecheck remain green.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `infra_adapter_elastic` (PR #16, merged) | All stories | Implemented | N/A |
| `infra_foundation` (PR #4, merged) | All stories | Implemented | N/A |
| Redis (cache subsystem) | Story 1.2 / FR-1 | Implemented | Redis-down → warmup logs WARN + continues; no regression vs status quo (FR-6 / D-9). |
| Postgres (cluster registry) | Story 1.2 (`count_clusters` + `list_clusters`) | Implemented | Postgres-down at startup → warmup task-level exception swallowed, logged WARN, API still starts (AC-6). |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Warmup blocks startup (synchronous await) | Low | High | AC-1 unit test asserts `asyncio.create_task` spawn (not await). FR-1 + §4 anti-patterns explicitly forbid synchronous-await wiring. |
| `get_or_probe_health` FR-7 change breaks existing consumers | Low | Low | Story 1.1 verified the only consumers (`list_clusters` + `get_cluster_detail` in `clusters.py`) just read the returned `HealthStatus`; the added `await write_cached_health` is invisible to them. Full integration test suite covers regression. |
| Shutdown cancellation leaks DB connection | Low | Medium | FR-4 / D-10 split — service-level test in Story 1.2 explicitly verifies `__aexit__` runs on `CancelledError` propagation through `async with db_factory() as db:`. |
| AC-8 integration test flakiness on slow CI runners | Low | Low | Deterministic signal (poll for the `cluster_health_warmup_completed` log event), NOT time-based sleep. Cycle-1 B2 explicitly forbade `asyncio.sleep(6)`. |
| Pre-existing `bug_demo_clusters_unreachable_in_healthz` smoke gate failure unrelated to this fix | High | Low | Cycle-1 D-6: the dashboard E2E failure is decoupled. The smoke gate will continue to fail post-merge on the banner test; admin-merge precedent set by PR #232 / PR #234. This PR fixes the `/healthz` side only. |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| Redis-down at warmup start | Redis container down or unreachable | Warmup logs `cluster_health_warmup_redis_unavailable` WARN; proceeds with per-cluster probes (cache writes silently no-op); completion log fires normally | Operator restarts Redis; next request lazy-warms via `get_or_probe_health`. |
| Postgres-down at warmup start | Postgres container down | `repo.count_clusters` raises; task-level except catches + WARN + swallows; warmup function returns. Other startup tasks unaffected | Operator restarts Postgres; next request flow normal. |
| One cluster's `health_check` times out | Slow/broken ES container | Per-cluster except catches the httpx error; WARN logs cluster ID; loop continues to next cluster | Self-recovers — TTL expires; next request re-probes. |
| Cluster has bad credentials | Missing entry in `cluster_credentials.yaml` | Post-Story-1.1: `get_or_probe_health` synthesizes `HealthStatus(unreachable, error=...)` AND writes to cache. `/healthz` reports the cluster as `unreachable` correctly with cached evidence | Operator fixes credentials; manual cache flush (`redis.delete cluster:health:*`) OR wait 30s for TTL. |
| Cancellation mid-loop | API container shutdown (SIGTERM) | `CancelledError` propagates through the warmup; `async with db_factory()` releases the DB session via `__aexit__`; task exits cleanly | None needed — shutdown is graceful. |

## 7) Sequencing and parallelization

### Suggested sequence

1. **Story 1.1** — FR-7 `get_or_probe_health` cache-write fix. Independent; ships first because Story 1.2's warmup depends on the post-fix invariant ("every branch writes cache").
2. **Story 1.2** — Warmup function + its unit tests. Self-contained; not yet wired.
3. **Story 1.3** — Lifespan wiring + main-lifespan tests. Depends on Story 1.2's function existing.
4. **Story 1.4** — Documentation. Independent; can be drafted in parallel with 1.2/1.3 but finalize after 1.3 lands so the doc reflects the implemented behavior.

### Parallelization opportunities

For a single agent / single PR, sequential execution is preferred. The bug is small enough that parallel branches would create more churn than they'd save.

## 8) Rollout and cutover plan

- **Rollout stages:** Single PR, single deploy via the standard PR → merge → CI flow.
- **Feature flag strategy:** None. The change is additive (a new background task) — existing consumers see no shape change.
- **Migration/cutover steps:** None. No Alembic migration. Redis cache rows are not migrated; the warmup just populates them earlier on the next boot.
- **Reconciliation/repair strategy:** None.

## 9) Execution tracker

### Current sprint

- [ ] Story 1.1 — Cache the `CredentialsMissing` HealthStatus before returning (FR-7)
- [ ] Story 1.2 — Add `run_cluster_health_warmup_background` service module
- [ ] Story 1.3 — Wire warmup into FastAPI lifespan
- [ ] Story 1.4 — Update `data-model.md` with warmup paragraph

### Blocked items

None.

### Done this sprint

(populated by `impl-execute` as stories complete)

## 10) Story-by-Story Verification Gate (Agent Checklist)

Before marking each story complete:

- [ ] Files created/modified match the story's tables.
- [ ] Function signatures match the Key interfaces blocks.
- [ ] All cited line numbers in the story match the actual file (verify by reading; numbers may shift after edits).
- [ ] Required tests pass: `.venv/bin/pytest <test_file> -v --tb=short`.
- [ ] `make lint` + `make typecheck` clean.
- [ ] No `make test-integration` required for Stories 1.1, 1.3, 1.4 (Story 1.2's integration tests are the only ones; they're service-container-gated).
- [ ] No `make e2e` required (no UI changes).
- [ ] Coverage gate (80%) maintained.
- [ ] Documentation update committed in the same story when behavior changed (Story 1.4 is its own story).

## 11) Plan consistency review

1. **Spec → plan endpoint count:** spec §8.1 lists 0 endpoints. Plan defines 0 endpoint tables. ✓
2. **Spec → plan FR coverage:** 7 FRs (FR-1..FR-7). All mapped in §1 traceability. ✓
3. **Spec → plan AC coverage:**
   - AC-1 → Story 1.3 (lifespan spawn test) ✓
   - AC-2 → Story 1.2 (warmup-walks-all test) ✓
   - AC-3 → Story 1.2 (cache-first idempotency test) ✓
   - AC-4 → Story 1.2 (empty-registry skip test) ✓
   - AC-5 → Story 1.2 (per-cluster fail × 2 tests) ✓
   - AC-6 → Story 1.2 (task-level exception swallowed test) ✓
   - AC-7 → Story 1.3 (lifespan-cancels-warmup test) + Story 1.2 (DB session release test) ✓
   - AC-8 → Story 1.2 integration test ✓
   - AC-9 → Story 1.2 integration test ✓
   - AC-10 → Story 1.2 integration test ✓
   - AC-11 → Story 1.1 unit test ✓
4. **Spec §19 decision coverage:** D-1 (warmup approach) → Story 1.2; D-2 (no shape change) → §5 refactor guardrails; D-3 (no cron) → §3 out-of-scope; D-7 (FR-7 in scope) → Story 1.1; D-8 (drop counters) → Story 1.2 Key interfaces (no `cache_hits`/`probed` fields); D-9 (Redis ping) → Story 1.2 Key interfaces top of function; D-10 (split tests) → Story 1.2 + Story 1.3 separate test files. ✓
5. **Story internal consistency:** Each story's Modified files matches its Tasks; Key interfaces match the Tasks. ✓
6. **Test file count:** 4 new test files — `test_cluster_service.py` (Story 1.1), `test_cluster_health_warmup.py` (Story 1.2 unit), `test_main_lifespan.py` (Story 1.3), `test_cluster_health_warmup.py` integration (Story 1.2 integration — note: same file name but different directory: `unit/services/` vs `integration/`). ✓
7. **Gate arithmetic:** Single epic, no phase gates beyond standard CI. ✓
8. **Open questions resolved:** §19 of the spec has zero open questions (all locked across cycles 1-3). ✓
9. **Plan ↔ codebase verification:**
   - `backend/app/services/cluster.py:192-215` `get_or_probe_health` ✓ (read)
   - `backend/app/services/cluster.py:48` `from backend.app.adapters.health_cache import ... write_cached_health` ✓ (already imported)
   - `backend/app/main.py:59-132` lifespan hook + insertion points ✓ (read)
   - `backend/app/main.py:33-49` import block ✓ (insertion target for new imports)
   - `backend/app/db/session.py:51` `get_session_factory() -> async_sessionmaker[AsyncSession]` ✓ (read)
   - `backend/app/db/repo/cluster.py:48,99` `list_clusters` + `count_clusters` signatures ✓ (read)
   - `backend/app/api/probes.py:118-132` paginated walk pattern to mirror ✓ (read)
   - `backend/app/llm/capability_check.py:404-431` `run_capability_check_background` template ✓ (read)
   - `backend/tests/unit/services/__init__.py` exists ✓
   - `backend/tests/unit/test_main_lifespan.py` does NOT exist — Story 1.3 creates it
   - `backend/tests/unit/services/test_cluster_service.py` does NOT exist — Story 1.1 creates it
   - `backend/tests/unit/test_capability_check.py:195` `structlog.testing.capture_logs()` precedent ✓ (read)
10. **Infrastructure path verification:** No new endpoints, no new migrations, no new routers. N/A.
11. **Frontend data plumbing:** N/A — no frontend scope.
12. **Persistence scope:** N/A — no `localStorage` / `sessionStorage`.
13. **Enumerated value contract audit:** N/A — no new enum / filter / dropdown values.
14. **Admin control audit:** N/A — MVP4+ rule.
15. **Audit-event coverage audit:** N/A — MVP2+ rule.

---

## 12) Definition of plan done

- [x] Every FR (FR-1..FR-7) mapped to stories/tasks/tests in §1.
- [x] Every story includes New files, Modified files, Tasks, DoD.
- [x] Test layers explicitly scoped (unit + integration; no contract / E2E / migration needed).
- [x] Documentation updates planned and owned (Story 1.4 + post-merge state.md/folder-move).
- [x] Lean refactor scope: explicitly none.
- [x] No epic/phase gates beyond standard CI.
- [x] Story-by-Story Verification Gate included (§10).
- [x] Plan consistency review (§11) performed with no unresolved findings.
- [ ] Cross-model review (Step 6) — pending GPT-5.5 cycle 1.
