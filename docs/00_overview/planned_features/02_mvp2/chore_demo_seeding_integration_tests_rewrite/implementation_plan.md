# Implementation Plan — Rewrite `test_demo_seeding` integration tests for the async-flow handler

**Date:** 2026-05-31
**Status:** Ready for Execution
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy source(s):** [`CLAUDE.md`](../../../../../CLAUDE.md) §"Integration Test Mocking Policy", §"Testing Conventions"; [`docs/05_quality/testing.md`](../../../../05_quality/testing.md)

---

## 0) Planning principles

- Spec traceability first: every story/task maps to FR IDs and AC IDs.
- Test-only chore. The sole permitted production edit is the **optional** D-3 base-URL settings field; the suite MUST pass with or without it (Story 0).
- **Inline worker invocation** (D-1): `await run_demo_reseed(ctx)` runs in the test process so the advisory lock is held on a connection in the same process — this is what makes AC-16's `pg_locks` pinning observer and AC-12's cleanup-gate contention work. NO separate Arq subprocess.
- **Arq singleton-dedup discipline** (cycle-3 High): the inline harness never consumes the queued job, so the `arq:job:demo_reseed:singleton` + `arq:result:demo_reseed:singleton` keys persist (~24h TTL) and silently drop the next POST's enqueue. Clear them (a) before each test, and (b) **between consecutive POSTs within a single test**.
- Summary counts are runtime values: `len(SCENARIOS) + rich_count` (5 with the rich ESCI scenario, 4 when skipped for no OpenAI key / missing `samples/`). Every assertion reads the runtime `summary.clusters_created`, never a hardcoded number.
- Fail-loud tests: assert explicit status codes, the full error envelope, and recorded sequences — not just a single key.
- Heavy CI lane only: every case skips gracefully via the existing `postgres_reachable()` + `_engine_reachable()` module-level gates when dependencies are unbound.

## 1) Scope traceability (FR → epics/stories)

| FR ID | Epic/Story | AC IDs | Notes |
|---|---|---|---|
| FR-1 (async-flow harness fixture) | Epic 1 / Story 1.1 | AC-12, AC-16, (all) | Module-scoped uvicorn + function-scoped driver; clears status key + Arq singleton dedup keys before each test |
| FR-2 (POST-then-poll helper) | Epic 1 / Story 1.2 | AC-1, AC-2, AC-13, AC-15, AC-Async | Asserts 202 + initial `running`; drives inline to terminal; clears dedup keys after each inline run |
| FR-3 (rewrite 9 cases) | Epic 2 / Stories 2.1–2.9 | AC-1, AC-2, AC-3, AC-5, AC-12, AC-13, AC-14, AC-15, AC-16 | Each asserts terminal Redis/poll status + post-run DB counts |
| FR-4 (re-home per-call timeout) | Epic 3 / Story 3.1 | AC-4 (worker layer) | Worker-side timeout → terminal `failed` + cleanup log |
| FR-5 (AC-Async polling transition) | Epic 2 / Story 2.10 | AC-Async | `status_set` recording spy proves monotonic `scenarios_completed` |
| FR-6 (worker-registration + enqueue guard) | Epic 2 / Story 2.11 | AC-Reg | `WorkerSettings.functions` resolvable + POST enqueues `run_demo_reseed`/`demo_reseed:singleton` |
| D-3 (optional production refactor) | Epic 0 / Story 0.1 (**optional**) | — | `Settings.relyloop_worker_api_base_url`; suite must pass with OR without it |

**Phase boundaries:** Single-phase. No deferred-phase tracking file required (spec §3 "Phase boundaries"; §19 confirms no deferred FRs).

## 2) Delivery structure

Structure: **Epic → Story → Tasks → DoD** (test-only; stories omit Endpoints/Schemas sections per the template's allowance for test/refactor stories, but the two endpoints under test are documented once in §2a below).

### 2a) Endpoints under test (no new endpoints; documented for contract fidelity)

| Method | Path | Behavior asserted | Error codes asserted |
|---|---|---|---|
| `POST` | `/api/v1/_test/demo/reseed` | **202** + initial `ReseedStatusResponse{status:"running", scenarios_total:len(SCENARIOS)+1, scenarios_completed:0, current_step:"enqueued — waiting for worker"}`; enqueues `run_demo_reseed` with `_job_id="demo_reseed:singleton"` | `SEED_IN_PROGRESS` (409, retryable=true), `ARQ_POOL_UNAVAILABLE` (503, retryable=true) |
| `GET` | `/api/v1/_test/demo/reseed/status` | **200** + current Redis `ReseedStatusResponse`; absent key → `{status:"idle"}` | — (never 404 in-dev) |

Verified: `backend/app/api/v1/_test.py:588-685` (POST), `:688-722` (GET), `_err` helper `:79-92`.

### Conventions (project-specific)

```
- Integration tests mock ONLY external services (engine HTTP API for AC-5/AC-14, OpenAI if rich
  scenario runs). DB, repos, services, the orchestrator, and the worker run for real.
- Inline worker invocation: `await run_demo_reseed(ctx)` with ctx = {"redis": <real handle>}.
  The worker's get_engine()/get_session_factory() resolve to the same process-wide engine the
  test queries (this is what makes AC-16/AC-12 observable). Confirmed: demo_reseed.py:114-117.
- The cleanup gate the worker reads is `backend.app.services.demo_seeding._demo_reseed_cleanup_test_gate`
  (module global, read at demo_seeding.py:492). The worker's run_demo_reseed_cleanup reads the
  demo_seeding module attribute — so AC-12 MUST patch `demo_seeding._demo_reseed_cleanup_test_gate`,
  NOT the `_test._demo_reseed_cleanup_test_gate` re-export (which the worker never reads).
- The cleanup gate offload is `await asyncio.to_thread(_demo_reseed_cleanup_test_gate.wait)`
  (demo_seeding.py:493) — preserve the threading.Event + to_thread design so the inline async
  task stays free to issue the concurrent POST and later .set() the gate.
- Status writes funnel through `demo_seeding.status_set(redis, status)` (demo_seeding.py:390). The
  AC-Async spy monkeypatches THIS symbol; it captures the handler's initial seed, every per-phase
  worker write (via the worker's `_redis_status_cb` closure at demo_reseed.py:161-162), and the
  terminal write.
- Arq dedup keys for _job_id="demo_reseed:singleton": "arq:job:demo_reseed:singleton",
  "arq:result:demo_reseed:singleton", "arq:in-progress:demo_reseed:singleton" (arq 0.28.0
  job_key_prefix/result_key_prefix/in_progress_key_prefix). Clear all three.
- Skip gates: reuse `postgres_reachable()` (conftest) + module-local `_engine_reachable()`.
- No new error codes, no new endpoints, no schema change, no migration.
```

### AI Agent Execution Protocol

0. Read `architecture.md` + `state.md` before Story 1.1.
1. Verify story outcome + interfaces + DoD.
2. Implement the harness fixtures first (Epic 1), then the rewritten cases (Epic 2), then the re-homed timeout (Epic 3). Story 0.1 (optional D-3) is independent and may be done first or skipped.
3. Run `make test-integration` targeted at the two files (`-k demo_seeding`) on the dev stack (after `docker compose stop api` locally) or in the heavy CI lane.
4. N/A — no frontend.
5. N/A — no E2E.
6. Update `state.md` known-debt after the final story.
7. N/A — no schema change / migration.
8. Attach evidence: pytest output for both files (skip markers removed), `make lint`, `make typecheck`.

---

## Epic 0 — Optional production ergonomics refactor (D-3)

> **The entire suite MUST pass with or without this epic.** If skipped, the harness redirects the worker's API base URL via `monkeypatch` of the worker's `httpx.AsyncClient` construction (fallback in D-3). If adopted, the harness uses a clean settings override. Treat Story 0.1 as optional — no test in Epics 1–3 may depend on the settings field existing.

### Story 0.1 — Settings-resolvable worker API base URL (**optional**)
**Outcome:** The worker reads its API self-call base URL from `Settings.relyloop_worker_api_base_url` (default `"http://api:8000"`) instead of the hardcoded literal at `demo_reseed.py:154`, so the harness redirects via env override rather than patching `httpx.AsyncClient`.

**New files** — none.

**Modified files**

| File | Change |
|---|---|
| `backend/app/core/settings.py` | Add `relyloop_worker_api_base_url: str = Field(default="http://api:8000", ...)` (mirror the existing `demo_reseed_per_call_http_timeout_s` field shape at `settings.py:282`) |
| `backend/workers/demo_reseed.py` | Replace `base_url="http://api:8000"` (`:154`) with `base_url=settings.relyloop_worker_api_base_url` (`settings` is already in scope at `:114`) |
| `docs/03_runbooks/local-dev.md` and/or `docs/03_runbooks/parallel-worktrees.md` | One line noting `relyloop_worker_api_base_url` if the field is added (spec §15) |

**Key interfaces**
```python
# backend/app/core/settings.py — new field on Settings
relyloop_worker_api_base_url: str  # default "http://api:8000"
```

**Tasks**
1. Add the settings field with the documented default and a docstring (`# Worker self-call base URL; overridden to 127.0.0.1:8000 by the demo-reseed integration harness`).
2. Read it in `run_demo_reseed` at the `httpx.AsyncClient(base_url=...)` construction (`demo_reseed.py:152-156`).
3. Add the one-line runbook note.

**Definition of Done (DoD)**
- `Settings.relyloop_worker_api_base_url` exists with default `"http://api:8000"`; worker reads it.
- Existing worker tests still green (no behavior change at the default).
- `make lint` + `make typecheck` clean.
- **If this story is skipped**, Story 1.1's base-URL redirection uses the `monkeypatch`-of-client-construction fallback and the rest of the plan is unaffected.

---

## Epic 1 — Async-flow test harness (FR-1, FR-2)

### Story 1.1 — Async-flow harness fixtures
**Outcome:** A module-scoped in-process uvicorn (on `127.0.0.1:8000`) plus a function-scoped driver fixture that yields `(client, ctx, db_engine)` and clears the Redis status key + Arq singleton dedup keys before each test, with the legacy `_stub_cluster_credentials` and `_patch_engine_for_test_host` autouse fixtures carried forward.

**New files** — none (fixtures live inside `test_demo_seeding.py`).

**Modified files**

| File | Change |
|---|---|
| `backend/tests/integration/test_demo_seeding.py` | Replace the module docstring + skip marker block; replace the `demo_reseed_client` fixture with the async-flow harness fixtures (`demo_reseed_base_url` module-scoped, `demo_reseed_client` function-scoped, `_arq_ctx` function-scoped, `_clean_demo_state_before_each` extended to clear the status key + dedup keys). Keep `_stub_cluster_credentials` + `_patch_engine_for_test_host` + `db_engine` + `_make_test_engine` + `_table_count` + `_truncate_all_demo_tables` verbatim. |

**Key interfaces (fixtures + helpers)**
```python
# test_demo_seeding.py
@pytest_asyncio.fixture(scope="module")
async def demo_reseed_base_url() -> AsyncIterator[str]: ...   # running_uvicorn() — unchanged

@pytest_asyncio.fixture
async def demo_reseed_client(demo_reseed_base_url: str) -> AsyncIterator[httpx.AsyncClient]: ...

@pytest_asyncio.fixture
async def arq_ctx() -> AsyncIterator[dict[str, Any]]:
    # Build a real Redis handle from settings.redis_url; yield {"redis": <handle>}.
    # Suitable for `await run_demo_reseed(ctx)`. Skip the test if Redis is unbound.
    ...

async def _clear_singleton_dedup_keys(redis: Redis) -> None:
    # DELETE arq:job:demo_reseed:singleton, arq:result:demo_reseed:singleton,
    # arq:in-progress:demo_reseed:singleton. Idempotent (DEL on absent key is a no-op).
    ...

async def _clear_status_key(redis: Redis) -> None:
    # DELETE DEMO_RESEED_STATUS_KEY so a prior `running`/`complete` never leaks a 409.
    ...
```

**Tasks**
1. Rewrite the module docstring to describe the async POST→poll contract (drop the "smoke test once it lands" reference per the "no legacy preservation" rule; the smoke test never landed and is out of scope per spec §3).
2. Remove the module-level `pytest.mark.skip` (keep `pytest.mark.integration`).
3. Add the `arq_ctx` fixture: `redis = Redis.from_url(get_settings().redis_url, decode_responses=False)`; if Redis is unreachable, `pytest.skip(...)`; yield `{"redis": redis}`; `await redis.aclose()` in teardown.
4. Extend `_clean_demo_state_before_each` to also clear `DEMO_RESEED_STATUS_KEY` + the three singleton dedup keys (use the `arq_ctx` Redis handle, or a short-lived handle if the fixture isn't depended on).
5. Implement the base-URL redirection: **if Story 0.1 adopted**, set `os.environ["RELYLOOP_WORKER_API_BASE_URL"] = "http://127.0.0.1:8000"` (surviving the autouse `_clear_settings_caches`, mirroring `_stub_cluster_credentials`'s env-var pattern); **else** `patch.object` the worker's client construction (wrap `httpx.AsyncClient` so the `api` client's `base_url` is rewritten to `http://127.0.0.1:8000`).
6. Keep `_stub_cluster_credentials` + `_patch_engine_for_test_host` autouse fixtures unchanged.

**Definition of Done (DoD)**
- The module-level skip marker is removed; `pytest.mark.integration` retained.
- `arq_ctx` yields a usable `{"redis": <handle>}` and skips cleanly when Redis is unbound.
- `_clean_demo_state_before_each` clears `DEMO_RESEED_STATUS_KEY` + all three singleton dedup keys before each test (asserted indirectly: AC-2/AC-12 multi-POST cases pass).
- Base-URL redirection works with AND without Story 0.1 (the AC-1 happy path passes either way — proven in Story 2.1).

### Story 1.2 — POST-then-poll helper with between-POST dedup clearing
**Outcome:** A helper `post_and_run_to_terminal(client, ctx)` that POSTs `/api/v1/_test/demo/reseed`, asserts **202** + the initial `running` status (`scenarios_total == len(SCENARIOS)+1`, **not** a `ReseedSummary`), drives the job inline via `await run_demo_reseed(ctx)`, clears the singleton dedup keys, and returns the terminal `ReseedStatusResponse` read from `GET /status`.

**New files** — none.

**Modified files**

| File | Change |
|---|---|
| `backend/tests/integration/test_demo_seeding.py` | Add `post_and_run_to_terminal()` + `_get_status()` helpers |

**Key interfaces**
```python
async def _get_status(client: httpx.AsyncClient) -> dict[str, Any]:
    r = await client.get("/api/v1/_test/demo/reseed/status")
    assert r.status_code == 200, r.text
    return r.json()

async def post_and_run_to_terminal(
    client: httpx.AsyncClient, ctx: dict[str, Any]
) -> dict[str, Any]:
    # 1. POST → assert 202 + initial running (scenarios_completed==0,
    #    scenarios_total == len(SCENARIOS)+1, current_step set, summary is None).
    # 2. await run_demo_reseed(ctx)  # inline; runs the orchestrator for real.
    # 3. await _clear_singleton_dedup_keys(ctx["redis"])  # FR-2: between-POST cleanup.
    # 4. Return GET /status (terminal complete/failed payload).
    ...
```

**Tasks**
1. Implement `_get_status` + `post_and_run_to_terminal`.
2. In step 1, import `SCENARIOS` from `backend.app.services.demo_seeding` and assert `scenarios_total == len(SCENARIOS) + 1`. Assert `status == "running"`, `scenarios_completed == 0`, `summary is None`.
3. In step 3, clear the singleton dedup keys **after** the inline run returns (so the next POST in the same test enqueues cleanly — the inline harness never consumed the queued job, so the key would otherwise persist for ~24h).

**Definition of Done (DoD)**
- The helper asserts the POST returns 202 + initial `running` status (not a summary).
- The helper drives the job to terminal inline and returns the terminal status.
- The helper clears the singleton dedup keys after each inline run (proven faithful by AC-2/AC-12/AC-Reg passing with real second/third enqueues).

---

## Epic 2 — Rewrite the 9 cases + AC-Async + AC-Reg (FR-3, FR-5, FR-6)

### Story 2.1 — AC-1: Happy path on a clean DB
**Outcome:** POST→inline-run→terminal `complete`; `summary` counters equal `len(SCENARIOS)+rich_count` / `len(results)+rich_count`; DB row counts match the runtime `summary.clusters_created` (`N`), with `==` for `clusters`/`proposals`/`query_sets` and `>=N` for `query_templates`/`judgment_lists`/`studies`/`digests`.

**Modified files:** `test_demo_seeding.py` — rewrite `test_reseed_happy_path_on_clean_db`.

**Tasks**
1. Call `terminal = await post_and_run_to_terminal(client, ctx)`; assert `terminal["status"] == "complete"`, `terminal["summary"] is not None`, `terminal["scenarios_completed"] == terminal["scenarios_total"]`.
2. Bind `N = terminal["summary"]["clusters_created"]`. Assert `terminal["summary"]["query_sets_created"] == N`, `studies_completed == proposals_created` (= `len(results)+rich_count`).
3. Assert DB counts against `N`: `clusters == N`, `proposals == N`, `query_sets == N`; `query_templates >= N`, `judgment_lists >= N`, `studies >= N`, `digests >= N`.
4. **D-4 finalization:** confirm `==` vs `>=` per table by reading the rich-scenario inserts. Verified during planning: the summary symmetry is `clusters_and_qsets = len(SCENARIOS)+rich_count` and `studies_and_proposals = len(results)+rich_count` (`demo_seeding.py:1618-1620`); the rich path registers its own query set (`rich/post_query_set`), so `query_sets == N`. `clusters`/`proposals` track `N` exactly. Tables the rich/UBI re-entry may augment (`query_templates`, `judgment_lists`, `studies`, `digests`) use `>=N`. The implementer MUST re-read the rich-scenario inserts before finalizing each `==`/`>=` choice and leave a comment citing `demo_seeding.py:1618-1626`.

**DoD**
- Terminal `complete` with populated `summary`; `scenarios_completed == scenarios_total`.
- DB counts asserted against runtime `summary.clusters_created` (NOT a hardcoded 4 or 5) — passes whether the rich scenario ran (`N==5`) or was skipped (`N==4`).

### Story 2.2 — AC-2: Replaces pre-existing demo state
**Outcome:** A second reseed produces a `clusters.id` set disjoint from the first (UUIDv7 freshness after `TRUNCATE ... RESTART IDENTITY CASCADE`).

**Modified files:** `test_demo_seeding.py` — rewrite `test_reseed_replaces_populated_demo_state`.

**Tasks**
1. First `post_and_run_to_terminal`; assert `complete`; capture `first_ids = {SELECT id FROM clusters}`.
2. Second `post_and_run_to_terminal` (the helper already cleared the dedup keys after the first run, so the second POST enqueues cleanly); assert `complete`; capture `second_ids`.
3. Assert `first_ids.isdisjoint(second_ids)` and both non-empty. Cite `backend/app/db/models/cluster.py:49` (UUIDv7 PK) in a comment.

**DoD**
- Both terminal statuses `complete`; the two cluster-id sets are disjoint.
- The second POST's enqueue is a real `Job` (not `None`) — proven by the run reaching terminal (relies on Story 1.2's between-POST dedup clearing).

### Story 2.3 — AC-3: Concurrent reseed returns 409
**Outcome:** A second POST issued while a `running` Redis status is present returns **409** with the full `SEED_IN_PROGRESS` envelope; the dedicated 503 `ARQ_POOL_UNAVAILABLE` micro-case is also covered.

**Modified files:** `test_demo_seeding.py` — rewrite `test_concurrent_reseed_returns_409`; add `test_reseed_arq_pool_unavailable_returns_503`.

**Tasks**
1. 409 case: seed a `running` status via `await status_set(redis, ReseedStatusResponse(status="running", started_at=_now_iso(), scenarios_total=len(SCENARIOS)+1, scenarios_completed=0))` (fresh `started_at` so `reseed_status_is_stale()==False`). Issue one POST; assert **409**; assert `body["detail"]["error_code"] == "SEED_IN_PROGRESS"`, `body["detail"]["message"]` non-empty, `body["detail"]["retryable"] is True`. Do NOT drive the worker.
2. 503 case: temporarily null `app.state.arq_pool` (or boot the harness without one); POST; assert **503**; assert `body["detail"]["error_code"] == "ARQ_POOL_UNAVAILABLE"`, `retryable is True`. Restore `arq_pool` in teardown.

**DoD**
- 409 asserts all three envelope keys (not just `error_code`).
- 503 `ARQ_POOL_UNAVAILABLE` envelope asserted (both POST failure envelopes covered).
- Status key cleared afterward so the next test doesn't 409 unexpectedly.

### Story 2.4 — AC-5: Mid-loop engine failure → terminal `failed` + cleanup
**Outcome:** With the engine HTTP layer monkeypatched to 500 on a target scenario step, the inline run drives terminal `failed` with the offending substring in `failed_reason`, and `run_demo_reseed_cleanup` ran (asserted via the `demo_reseed_cleanup_truncated` caplog line).

**Modified files:** `test_demo_seeding.py` — rewrite `test_reseed_mid_flight_engine_failure_*` to the inline contract.

**Tasks**
1. `caplog.set_level(logging.INFO, logger="backend.app.services.demo_seeding")`.
2. Monkeypatch the **engine** request path (e.g., `httpx.AsyncClient.put`, counting only `:9200`/`:9201`-targeted calls, raising `httpx.ConnectError`/500 past a threshold) — mirror the legacy counting-put pattern at the old `test_demo_seeding.py:457-471`. Do NOT patch internal service functions.
3. POST → assert 202 → `await run_demo_reseed(ctx)` (do not use `post_and_run_to_terminal`'s success-assert path; this run fails) → read `GET /status`.
4. Assert `terminal["status"] == "failed"`; `failed_reason` contains the offending step substring; the `demo_reseed_cleanup_truncated` record is in `caplog`.

**DoD**
- Terminal `failed` with the right `failed_reason` substring; cleanup log asserted via caplog.

### Story 2.5 — AC-12: Cleanup-while-locked blocks a concurrent reseed
**Outcome:** A first reseed forced to fail mid-loop, with cleanup gated by `demo_seeding._demo_reseed_cleanup_test_gate` (a `threading.Event`) so the worker holds the advisory lock while cleanup waits; a concurrent second POST returns **409 SEED_IN_PROGRESS**; after the gate releases and the first run finishes (`failed`), a third POST + inline run reaches `complete`.

**Modified files:** `test_demo_seeding.py` — rewrite `test_cleanup_while_locked_blocks_concurrent_reseed` to the inline-task contract.

**Tasks**
1. Patch `demo_seeding._demo_reseed_cleanup_test_gate` with a `threading.Event` (`gate`). **Critical:** patch on `backend.app.services.demo_seeding`, NOT `_test` — the worker's `run_demo_reseed_cleanup` reads the `demo_seeding` module global (`demo_seeding.py:492`). Also wrap/spy the cleanup to set a `cleanup_entered` event (patch `demo_seeding.run_demo_reseed_cleanup` or detect via a caplog poll on `demo_reseed_cleanup_truncated`'s precursor — prefer a wrapper that sets `cleanup_entered` before delegating).
2. Force the first run to fail mid-loop (engine-500 injection or a forced `RuntimeError` in the orchestrator's per-scenario seed path — mirror legacy `_fail_first_seed`).
3. Launch the first run as a background task: `task_a = asyncio.create_task(run_demo_reseed(ctx))`. The worker's `status_set("running")` is what makes the concurrent POST 409.
4. Wait (bounded loop, ~20s ceiling, fail loudly) for `cleanup_entered`. The gate's `to_thread` offload (`demo_seeding.py:493`) keeps the loop free.
5. Issue the second POST (against the same in-process app) → assert **409 SEED_IN_PROGRESS** (full envelope).
6. `gate.set()` → `await task_a`; assert the first run reached terminal `failed` via `GET /status`.
7. Clear the singleton dedup keys (the first run's `ctx` never consumed its queued job). Third POST + `await run_demo_reseed(ctx)` → assert terminal `complete`.

**DoD**
- Gate patched on `demo_seeding` (the module the worker reads).
- Second POST 409s while the lock is held; third POST + inline run reaches `complete`.
- The `to_thread` offload is preserved (no in-loop `event.wait()` deadlock).

### Story 2.6 — AC-13: TRUNCATE commits before any self-call (log ordering)
**Outcome:** The `demo_reseed_truncate_committed` caplog record's index precedes the first `demo_reseed_api_call_started` record with `client=="api"` and `/api/v1/clusters` in its `url`.

**Modified files:** `test_demo_seeding.py` — rewrite `test_truncate_commits_before_first_self_call` to drive the inline worker.

**Tasks**
1. `caplog.set_level(logging.INFO, ...)` for `backend.app.services.demo_seeding` (the orchestrator logs both records — `demo_seeding.py:1202` for truncate, `:307` for `demo_reseed_api_call_started`).
2. `post_and_run_to_terminal` (happy path); assert `complete`.
3. Reuse the legacy index-ordering assertion logic verbatim (find truncate idx, find first api/`/api/v1/clusters` call idx, assert `truncate_idx < first_cluster_call_idx`).

**DoD**
- Truncate-committed log precedes the first api-client `/api/v1/clusters` call log.

### Story 2.7 — AC-14: Natural failure cleanup is deterministic
**Outcome:** After the engine-500 injection (same as AC-5) drives terminal `failed`, post-failure DB row counts for the cleanup-wiped demo tables are 0.

**Modified files:** `test_demo_seeding.py` — rewrite `test_natural_failure_cleanup_*` to the inline contract.

**Tasks**
1. Apply the AC-5 engine-failure injection; POST + `await run_demo_reseed(ctx)`.
2. Assert terminal `failed` via `GET /status`.
3. Assert `_table_count(db_engine, "clusters") == 0`, `studies == 0`, `query_sets == 0` (the tables `run_demo_reseed_cleanup` TRUNCATEs — `_TRUNCATE_DEMO_TABLES_SQL`).

**DoD**
- Terminal `failed`; cleanup-wiped tables are 0.

### Story 2.8 — AC-15: Dual-client contract — no role mixing
**Outcome:** API-targeted calls go through the API client (relative `/api/v1/...` against the harness base URL); engine calls hit `:9200`/`:9201` with the correct basic auth; no role mixing — proven by a request-recording spy/transport on `httpx.AsyncClient.send`.

**Modified files:** `test_demo_seeding.py` — rewrite `test_dual_client_contract_no_role_mixing` to drive the inline worker.

**Tasks**
1. Record requests via a `patch.object(httpx.AsyncClient, "send", recording_send)` wrapper (mirror legacy `:518-525`).
2. `post_and_run_to_terminal`; assert `complete`.
3. Partition recorded URLs by port: api self-calls hit the harness base (`:8000`), engine hits `:9200`/`:9201`. Assert each set non-empty and no cross-contamination (`:9200`/`:9201` never in api set; `:8000` never in engine set). Auth-header correctness is proven indirectly by the happy path completing (a wrong auth 401s the ES PUT → terminal `failed`), per the legacy note.

**DoD**
- Recorded request partition shows api/engine separation with no role mixing; happy path completes.

### Story 2.9 — AC-16: Advisory lock pinned to one Postgres connection
**Outcome:** A `pg_locks` observer (polling the advisory `(classid, objid)` from `DEMO_RESEED_LOCK_KEY` every 200ms) records at least one observation, the lock-holding pid never changes, and after the inline worker returns the lock is gone.

**Modified files:** `test_demo_seeding.py` — rewrite `test_advisory_lock_pinned_to_one_connection` to run the worker inline as a background task.

**Tasks**
1. Keep `_pg_locks_key_parts` + the observer coroutine verbatim (legacy `:557-596`).
2. Launch `task = asyncio.create_task(run_demo_reseed(ctx))` (inline; holds the lock on `get_engine().connect()` in the test process). Start the observer task concurrently.
3. `await task`; stop the observer; assert `observed_pids` non-empty, `len(set(observed_pids)) == 1`, and the post-run `pg_locks` query returns no rows.
4. Note: the worker also seeds `running` via `status_set`; clear the status key + dedup keys after.

**DoD**
- Observer saw the lock; pid constant; lock released after the inline worker returns.

### Story 2.10 — AC-Async: Polling transition `running → complete`, monotonic `scenarios_completed`
**Outcome:** A `status_set` recording spy captures every status write; the sequence starts `running` (`scenarios_completed==0`), `scenarios_completed` never decreases, and ends `complete` (`scenarios_completed==scenarios_total`, populated `summary`).

**New/Modified files:** `test_demo_seeding.py` — add `test_polling_transition_running_to_complete_monotonic`.

**Tasks**
1. Monkeypatch `backend.app.services.demo_seeding.status_set` with a spy that appends a copy of each `ReseedStatusResponse` (specifically `scenarios_completed` + `status`) then delegates to the real `status_set`. **Mandatory** — the Redis key is single-overwritten, so start+end reads cannot prove monotonicity.
2. POST (seeds the initial `running`) → `await run_demo_reseed(ctx)` (each per-phase write flows through the spy via the worker's `_redis_status_cb` closure → `status_set`).
3. Assert: first recorded status `running` with `scenarios_completed==0`; the `scenarios_completed` sequence is non-decreasing (`all(b>=a for a,b in pairwise)`); last recorded `complete` with `scenarios_completed==scenarios_total` and `summary` populated.

**DoD**
- Recorded sequence proves monotonic non-decrease + `running→complete` with the populated terminal summary.

### Story 2.11 — AC-Reg: Worker-registration + enqueue guard
**Outcome:** `"run_demo_reseed"` is resolvable in `WorkerSettings.functions` (unwrapping `arq.func(...)`), AND the POST handler is observed to enqueue `run_demo_reseed` with `_job_id="demo_reseed:singleton"`.

**New/Modified files:** `test_demo_seeding.py` — add `test_worker_registration_and_enqueue_guard`.

**Tasks**
1. Import `WorkerSettings` from `backend.workers.all`; for each entry in `.functions`, resolve the underlying coroutine name (`getattr(f, "coroutine", f).__name__` for `arq.func(...)` wrappers, else `f.__name__`). Assert `"run_demo_reseed"` is among them. (Verified registered today at `all.py:251`.)
2. Spy on the app's `arq_pool.enqueue_job` (`patch.object(app.state.arq_pool, "enqueue_job", wraps=...)` or a recording wrapper); issue one POST; assert it was called once with first positional arg `"run_demo_reseed"` and `_job_id="demo_reseed:singleton"`.
3. Clear the status key + dedup keys afterward (the spied enqueue may or may not be consumed — this test does not run the worker).

**DoD**
- `run_demo_reseed` resolvable in `WorkerSettings.functions` (drop-registration regression fails CI).
- POST observed enqueuing `run_demo_reseed` / `demo_reseed:singleton` (silent-enqueue-failure regression fails CI).

---

## Epic 3 — Re-home the per-call timeout case (FR-4)

### Story 3.1 — AC-4: Worker-side per-call timeout → terminal `failed` + cleanup
**Outcome:** A per-call HTTP timeout inside the worker (`demo_reseed_per_call_http_timeout_s` exceeded) drives the terminal status to `failed` with a timeout-flavored `failed_reason`, and `run_demo_reseed_cleanup` is attempted (asserted via the `demo_reseed_cleanup_truncated` caplog line).

**Modified files**

| File | Change |
|---|---|
| `backend/tests/integration/test_demo_seeding_timeout.py` | Remove the module-level skip marker; rewrite `test_reseed_per_call_timeout_returns_503` → `test_worker_per_call_timeout_drives_failed_and_cleanup` against the inline worker. Update the module docstring (drop the "503 on the POST" framing — the POST returns 202 before any per-call timeout). Carry forward `_stub_cluster_credentials` + `_patch_engine_for_test_host` + the function-scoped `running_uvicorn` fixture + the `arq_ctx`/dedup-clear helpers (import the shared ones from `test_demo_seeding` or duplicate the minimal `arq_ctx`). |

**Tasks**
1. Remove the `pytest.mark.skip` (keep `pytest.mark.integration`).
2. Force a self-call to exceed the per-call timeout: monkeypatch `test_seeding.seed_study_completed_with_digest` (+ the `_test` re-import) to `asyncio.sleep(5)` — mirror legacy `:175-184`.
3. Set the per-call timeout to 1s WITHOUT weakening the production `ge=30` validator: `settings.__dict__["demo_reseed_per_call_http_timeout_s"] = 1` on the lru_cached `Settings` instance (legacy pattern at `:178-180`), restored in `finally`. The worker reads this at `demo_reseed.py:145` (`httpx.Timeout(settings.demo_reseed_per_call_http_timeout_s)`).
4. `caplog.set_level(logging.INFO, logger="backend.app.services.demo_seeding")`. POST → `await run_demo_reseed(ctx)`.
5. Assert terminal `GET /status` is `failed`; `failed_reason` is timeout-flavored (contains `Timeout`/`ReadTimeout`/`ConnectTimeout` — confirm the exact class via the worker's `failed_reason=f"{type(exc).__name__}: ..."` at `demo_reseed.py:191`, which formats `httpx.ReadTimeout` etc.). Assert `demo_reseed_cleanup_truncated` is in `caplog` (the worker's failure branch calls `run_demo_reseed_cleanup` at `demo_reseed.py:184`).

**DoD**
- Module-level skip marker removed.
- Terminal `failed` with a timeout-flavored `failed_reason`; cleanup log asserted.
- The production `ge=30` validator is NOT weakened (override via `__dict__`, restored in `finally`).

---

## 3) Testing workstream (required)

This chore **is** the test work. Coverage by layer:

### 3.1 Unit tests
- Location: `backend/tests/unit/services/test_demo_seeding_status.py` — **unchanged** (11 functions). No removal, no duplication. This plan adds only the integration layer the unit tests cannot reach.

### 3.2 Integration tests
- Location: `backend/tests/integration/test_demo_seeding.py` + `test_demo_seeding_timeout.py`.
- Tasks:
  - [ ] Story 1.1 — harness fixtures (uvicorn + driver + status/dedup clearing) — `test_demo_seeding.py`
  - [ ] Story 1.2 — `post_and_run_to_terminal` + `_get_status` helpers — `test_demo_seeding.py`
  - [ ] Stories 2.1–2.9 — rewrite the 9 cases (AC-1, 2, 3, 5, 12, 13, 14, 15, 16) — `test_demo_seeding.py`
  - [ ] Story 2.10 — AC-Async — `test_demo_seeding.py`
  - [ ] Story 2.11 — AC-Reg — `test_demo_seeding.py`
  - [ ] Story 3.1 — AC-4 worker-timeout — `test_demo_seeding_timeout.py`
- DoD:
  - [ ] All AC-* pass in the heavy CI lane; both module-level skip markers removed; cases skip gracefully when Postgres/ES/OS/Redis are unbound.

### 3.3 Contract tests
- Location: `backend/tests/contract/` — **unchanged**. `test_test_endpoint_guard.py:213` (404 guard) + `test_openapi_surface.py:116` (202 surface) already assert the endpoint shape. The rewrite must not contradict them (POST=202). No new contract test required (no new endpoint/error code).

### 3.4 E2E tests
- N/A — the home-button reseed UI flow is covered by its own feature's E2E. This chore is backend integration only.

### 3.5 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `backend/tests/integration/test_demo_seeding.py` | module skip (`:53`); 9 sync-flow cases asserting `status_code == 200` + `body["clusters_created"]` | 9 | Rewrite to async POST→inline-run→poll; remove skip (Stories 1.1–2.11) |
| `backend/tests/integration/test_demo_seeding_timeout.py` | module skip (`:44`); 1 sync 503-on-POST timeout case | 1 | Re-home to worker-side timeout; remove skip (Story 3.1) |
| `backend/tests/unit/services/test_demo_seeding_status.py` | unit coverage of Redis helpers + Pydantic shape | 11 | **No change** — covers a different layer (no real Postgres/Arq); not duplicated by this plan |
| `backend/tests/contract/test_test_endpoint_guard.py` | 404 env-guard for the POST | 1 | **No change** — env-guard contract is orthogonal to the async-flow rewrite |
| `backend/tests/contract/test_openapi_surface.py` | 202 OpenAPI surface for the POST | 1 | **No change** — the rewrite asserts 202, consistent with this |

### 3.5b Migration verification
- N/A — no schema change, no migration.

### 3.6 CI gates
- [ ] `make test-integration` (heavy lane; targeted `-k "demo_seeding"` for fast iteration)
- [ ] `make lint`
- [ ] `make typecheck`
- [ ] `make test-unit` (regression — confirm the unchanged unit file still passes)

---

## 4) Documentation update workstream

### 4.0 Core context files
- **`state.md`** — [ ] drop the "demo-reseed async flow has no integration coverage" known-debt entry once merged (spec §15).
- **`architecture.md`** — no change (no new service/layer/flow; the async flow itself already shipped in PR #286).
- **`CLAUDE.md`** — no change, UNLESS Story 0.1 (D-3) is adopted: then add `relyloop_worker_api_base_url` to the env-var notes if appropriate (one line; optional).

### 4.1–4.5
- `docs/01–04`: N/A.
- `docs/03_runbooks/`: one line for `relyloop_worker_api_base_url` ONLY if Story 0.1 is adopted (spec §15).
- `docs/05_quality/testing.md`: N/A — test-layer convention unchanged; this fills an existing gap.

**Documentation DoD**
- [ ] `state.md` known-debt entry dropped.
- [ ] If Story 0.1 adopted: one-line settings note added; else no doc change.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals
- Optional: collapse the worker's hardcoded API base URL literal into a settings field (Story 0.1, D-3). Bounded to one field + one line.

### 5.2 Planned refactor tasks
- [ ] (Optional) Story 0.1 — `Settings.relyloop_worker_api_base_url`.
- [ ] Share `arq_ctx` + dedup-clear helpers between the two test files (import from `test_demo_seeding` or a small `_demo_reseed_helpers.py` if duplication is awkward — implementer's call; keep it minimal).

### 5.3 Refactor guardrails
- [ ] No production behavior change at the default (Story 0.1 default == current literal).
- [ ] Lint/typecheck green.
- [ ] No expansion of product scope — test-only.
- [ ] The suite passes with OR without Story 0.1.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| Postgres + ES + OS service containers | Stories 2.1–3.1 | implemented (GHA `pr.yml`) | tests skip via `postgres_reachable()`/`_engine_reachable()` |
| Redis (status key + `ctx["redis"]`) | Story 1.1 + all | implemented | `arq_ctx` skips when Redis unbound |
| `cluster_credentials.yaml` via `CLUSTER_CREDENTIALS_FILE` | cluster-create probe | implemented (`_stub_cluster_credentials` autouse) | probe 503s → carried-forward fixture prevents this |
| In-process uvicorn (`running_uvicorn()`) | Story 1.1 | implemented (`_demo_reseed_uvicorn.py`) | self-call fails → harness asserts loudly |
| `127.0.0.1:8000` free (local) | local runs | operator-owned | `_assert_port_free` raises a named RuntimeError |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Arq singleton dedup silently drops a second/third POST's enqueue | H (without mitigation) | H | Clear `arq:job:`/`arq:result:`/`arq:in-progress:demo_reseed:singleton` before each test AND between POSTs (Stories 1.1, 1.2) |
| AC-12 patches the cleanup gate on the wrong module (`_test` vs `demo_seeding`) | M | H | Plan explicitly directs patching `demo_seeding._demo_reseed_cleanup_test_gate` (the symbol the worker reads at `demo_seeding.py:492`) |
| Naive in-loop `event.wait()` deadlocks the inline-task design | M | H | Preserve the `to_thread` offload (`demo_seeding.py:493`); never replace with a blocking in-loop wait |
| AC-16 reseed finishes faster than the 200ms poll | L | M | Real studies run for minutes; legacy observer's "increase workload if flaky" note carried forward |
| Rich scenario runs in CI when an OpenAI key is present → `N==5` not 4 | M | L (by design) | All counts read runtime `summary.clusters_created`; `>=` for augmentable tables (Story 2.1, D-4) |
| Base-URL redirection differs by D-3 adoption | L | L | Story 1.1 implements both paths; AC-1 passes either way |

### Failure mode catalog

| Failure mode | Trigger | Expected behavior | Recovery |
|---|---|---|---|
| Stale `running` status leaks into next test | prior test didn't clear status key | next POST 409s unexpectedly | `_clean_demo_state_before_each` clears `DEMO_RESEED_STATUS_KEY` |
| Second POST's enqueue dropped | singleton dedup key persists | `enqueue_job` returns `None`, masking a real regression | between-POST dedup clearing (Story 1.2) |
| Worker init crash mid-run | settings/engine/client construction fails | worker barrier flips Redis status to `failed` + re-raises | terminal `failed` observable via `GET /status` (already production behavior) |
| Inline task deadlock | in-loop `event.wait()` | test hangs to its ceiling | bounded wait loops + `to_thread` offload preserved |

## 7) Sequencing and parallelization

### Suggested sequence
1. Epic 0 (optional D-3) — independent; do first or skip.
2. Epic 1 (harness fixtures + helper) — blocks Epic 2/3.
3. Epic 2 (rewrite 9 cases + AC-Async + AC-Reg).
4. Epic 3 (re-home timeout).
5. Docs (`state.md` known-debt drop).

### Parallelization opportunities
- Epic 0 is fully independent of Epics 1–3.
- Within Epic 2, Stories 2.1–2.11 are independent once Epic 1 lands (each is a self-contained test function), but they share the single test file — serialize edits to avoid merge churn.

## 8) Rollout and cutover plan
- No runtime rollout — test-only. Cutover = removing both skip markers and landing the rewrite. No feature flag, no migration, no external system.

## 9) Execution tracker

### Current sprint
- [ ] Story 0.1 (optional) — `Settings.relyloop_worker_api_base_url`
- [ ] Story 1.1 — harness fixtures
- [ ] Story 1.2 — POST-then-poll helper
- [ ] Stories 2.1–2.11 — rewrite cases + AC-Async + AC-Reg
- [ ] Story 3.1 — worker-timeout re-home
- [ ] Docs — drop `state.md` known-debt entry

### Blocked items
- None.

## 10) Story-by-Story Verification Gate (Agent Checklist)

Before marking any story complete:
- [ ] Files modified match story scope (`Modified files` table)
- [ ] Terminal-status assertions read runtime `summary.*` (not hardcoded counts) where applicable
- [ ] Inline worker invocation used (no Arq subprocess); dedup keys cleared per FR-1/FR-2
- [ ] AC-12 patches `demo_seeding._demo_reseed_cleanup_test_gate` (not `_test`)
- [ ] Commands executed and passed:
    - [ ] `make test-integration` (targeted `-k demo_seeding`)
    - [ ] `make test-unit` (regression on the unchanged unit file)
    - [ ] `make lint`
    - [ ] `make typecheck`
- [ ] No schema change → no migration verification needed
- [ ] `state.md` known-debt entry dropped in the same PR

## 11) Plan consistency review (performed)

1. **Spec ↔ plan endpoint count:** spec §7.1 lists 2 endpoints (POST + GET); both documented in plan §2a and asserted across Stories 1.2/2.1/2.3. ✔
2. **Spec ↔ plan error code coverage:** spec §7.5 lists `SEED_IN_PROGRESS` (409) + the `failed`-terminal `failed_reason` prefix; plus `ARQ_POOL_UNAVAILABLE` (503) in §7.1. AC-3 (Story 2.3) asserts both 409 and 503 envelopes; AC-5/AC-14/AC-4 assert the `failed_reason`. No new error codes. ✔
3. **Spec ↔ plan FR coverage:** all 6 FRs + optional D-3 mapped in §1; each assigned to ≥1 story. ✔
4. **Story internal consistency:** no two stories own the same new file (all edits land in 2 existing test files; helpers single-owned by Stories 1.1/1.2). Modified files verified to exist: `test_demo_seeding.py`, `test_demo_seeding_timeout.py`, `_demo_reseed_uvicorn.py`, `settings.py`, `demo_reseed.py`. ✔
5. **Test file count:** 2 integration files (both in §3.2), 0 new contract/e2e, 1 unchanged unit file (§3.5). ✔
6. **Gate arithmetic:** 11 ACs (1, 2, 3, 5, 12, 13, 14, 15, 16, Async, Reg) + AC-4 (timeout file) = 12 AC assertions across 12 test stories (Stories 2.1–2.11 + 3.1). AC-3's Story 2.3 carries two cases (409 + 503 micro-case). ✔
7. **Open questions resolved:** spec §19 — none blocking; D-4 (`==` vs `>=` per table) resolved during planning (Story 2.1 task 4) by reading `demo_seeding.py:1618-1626`. ✔
8. **Infra path verification:** no migration dir / router registration involved (test-only). Settings field shape verified against `settings.py:282`. ✔
9. **Frontend data plumbing:** N/A — no frontend. ✔
10. **Persistence scope:** N/A — no localStorage/sessionStorage. ✔
11. **Enumerated value contract audit:** the only enumerated field is `ReseedStatusResponse.status` (`idle`/`running`/`complete`/`failed`), grounded at `demo_seeding.py:204` (`ReseedStatusLiteral`); no frontend option list added (spec §7.4). Tests assert these literals against the backend `Literal`. ✔
12. **Admin/ceiling audit:** N/A (no admin model in MVP2). ✔
13. **Audit-event audit:** N/A — test-only chore mutates no audited state; `audit_log` not touched (spec §6). ✔

**Cross-model review:** Skipped per operator decision (Opus-only internal passes for this feature). GPT-5.5 cross-model review was NOT run for this plan. Two internal Opus passes (Pass 1 plan-internal consistency + Pass 2 codebase accuracy) were performed; the codebase claims below were verified by reading the cited files.

### Verification ledger (codebase accuracy — Pass 2)

| Claim | Verified by | Status |
|---|---|---|
| POST returns 202 + initial `running` status; enqueues `_job_id="demo_reseed:singleton"` | `_test.py:588-685` | Verified |
| GET `/status` returns 200; absent → `{status:"idle"}` | `_test.py:688-722` | Verified |
| `_err` envelope `{error_code, message, retryable}` | `_test.py:79-92` (referenced) + 409/503 raises `:630,641` | Verified |
| `run_demo_reseed(ctx)` takes only `ctx`; builds `_redis_status_cb` → `status_set` | `demo_reseed.py:63,161-162` | Verified |
| Worker hardcodes `base_url="http://api:8000"` | `demo_reseed.py:154` | Verified |
| Worker reads `httpx.Timeout(settings.demo_reseed_per_call_http_timeout_s)` | `demo_reseed.py:145` | Verified |
| Worker failure branch calls `run_demo_reseed_cleanup` + writes `failed` | `demo_reseed.py:184-198` | Verified |
| `run_demo_reseed` registered in `WorkerSettings.functions` via `func(...)` | `all.py:251` | Verified |
| `_demo_reseed_cleanup_test_gate` is a `demo_seeding` module global read at `:492`; offloaded via `to_thread` at `:493` | `demo_seeding.py:472,492-493` | Verified |
| `_test` re-exports `_demo_reseed_cleanup_test_gate`/`_run_demo_reseed_cleanup` but worker reads the `demo_seeding` global | `_test.py:44,50` + `demo_seeding.py:492` | **Verified — plan directs patching `demo_seeding`, not `_test`** |
| `status_set` is the single funnel at `demo_seeding.py:390`; `DEMO_RESEED_STATUS_KEY="demo_reseed:status"` | `demo_seeding.py:114,390` | Verified |
| Summary counts = `len(SCENARIOS)+rich_count` / `len(results)+rich_count` | `demo_seeding.py:1618-1626` | Verified |
| `ReseedStatusLiteral = Literal["idle","running","complete","failed"]` | `demo_seeding.py:204` | Verified |
| `running_uvicorn()` boots on `127.0.0.1:8000`, applies migrations, asserts port free | `_demo_reseed_uvicorn.py:136-151` | Verified |
| `_stub_cluster_credentials` + `_patch_engine_for_test_host` autouse fixtures exist | `test_demo_seeding.py:109-201` | Verified |
| Arq 0.28.0 dedup key prefixes (`arq:job:`/`arq:result:`/`arq:in-progress:`) | `python3 -c "import arq"` → 0.28.0 | Verified (prefix convention) |
| `Settings.relyloop_worker_api_base_url` does NOT yet exist (Story 0.1 adds it) | `grep settings.py` — only `demo_reseed_per_call_http_timeout_s:282` | Verified — new field |

---

## 12) Definition of plan done

- [x] Every FR mapped to stories/tasks/tests (§1).
- [x] Every story includes Modified files, Key interfaces (where applicable), Tasks, DoD.
- [x] Test layers scoped: integration (deliverable), unit (unchanged), contract (unchanged), E2E (N/A).
- [x] Documentation updates planned (`state.md` known-debt drop; optional D-3 note).
- [x] Lean refactor scope + guardrails explicit (optional D-3, suite passes either way).
- [x] Epic gates measurable.
- [x] Story-by-Story Verification Gate included.
- [x] Plan consistency review performed; no unresolved findings. Cross-model review skipped per operator decision (logged in §11).
