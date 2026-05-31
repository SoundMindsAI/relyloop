# Feature Specification — Rewrite `test_demo_seeding` integration tests for the async-flow handler

**Date:** 2026-05-31
**Status:** Draft
**Owners:** RelyLoop maintainers (test infrastructure)
**Related docs:**
- [`idea.md`](idea.md) — origin brief
- [`bug_demo_reseed_fake_metric_regression`](../../../implemented_features/2026_05_27_bug_demo_reseed_fake_metric_regression/bug_fix.md) — the PR that converted the handler to async and listed this rewrite as a follow-up
- [`bug_demo_reseed_button_silent_enqueue_failure`](../../../implemented_features/2026_05_29_bug_demo_reseed_button_silent_enqueue_failure/idea.md) — a real regression this suite would have caught

---

## 1) Purpose

`POST /api/v1/_test/demo/reseed` was converted from a synchronous handler (200 + `ReseedSummary` returned inline) to an async Arq-enqueue + Redis-polling flow in PR #286 (`bug_demo_reseed_fake_metric_regression`). The 9 integration tests at `backend/tests/integration/test_demo_seeding.py` plus the 1 timeout test at `backend/tests/integration/test_demo_seeding_timeout.py` assert the *old* synchronous contract and are currently skipped via module-level `pytestmark` (lines 53 and 44 respectively). The async flow has zero integration coverage.

- **Problem:** The async contract (POST → 202 + initial `ReseedStatusResponse`; worker writes Redis status after each phase; GET `/status` polls; terminal `complete`/`failed`) is untested against real Postgres + Arq. Three concrete regression classes ship silently today: reverting the POST to synchronous, forgetting to register `run_demo_reseed` in `WorkerSettings.functions`, and breaking the Redis status-key persistence path.
- **Outcome:** The 9 skipped cases are rewritten to the async "POST + poll-until-terminal" shape, the timeout case is re-homed to the worker layer, a new `AC-Async` case asserts the `running → complete` polling transition with monotonically non-decreasing `scenarios_completed`, and the module-level skip markers are removed so the suite runs in the heavy CI lane.
- **Non-goal:** No production code change to the reseed flow itself. This is a test-only chore. (One small *optional* production ergonomics refactor is scoped in §3 — making the worker's API base URL settings-resolvable so the harness doesn't have to monkeypatch a hardcoded literal — but the rewrite must work with or without it.)

## 2) Current state audit

### Existing implementations

- `backend/app/api/v1/_test.py:588-685` — `POST /api/v1/_test/demo/reseed`. Returns **202 ACCEPTED** + an initial `ReseedStatusResponse{status:"running", scenarios_total:5, scenarios_completed:0, current_step:"enqueued — waiting for worker"}`. Seeds the Redis status key, then `arq_pool.enqueue_job("run_demo_reseed", _job_id="demo_reseed:singleton")`. Returns **409 SEED_IN_PROGRESS** (retryable=True) when the current Redis status is `running` and not stale; **503 ARQ_POOL_UNAVAILABLE** when `request.app.state.arq_pool` is `None`.
- `backend/app/api/v1/_test.py:688-722` — `GET /api/v1/_test/demo/reseed/status`. Returns **200** + `ReseedStatusResponse`; absent key → `{status:"idle"}` (never 404).
- `backend/workers/demo_reseed.py:63-256` — `run_demo_reseed(ctx)`. Acquires the Postgres advisory lock on a dedicated `engine.connect()` connection, constructs two `httpx.AsyncClient`s (API at `http://api:8000`, engine unscoped), runs `reseed_demo_state` with a Redis-writing `StatusCallback`, calls `run_demo_reseed_cleanup(engine_client)` on failure under the held lock, writes terminal `complete`/`failed` status, releases the lock in `finally`. Top-level `except Exception` barrier flips status to `failed` on init-region crashes and re-raises so Arq records `JobExecutionFailed`.
- `backend/app/services/demo_seeding.py` — orchestrator (`reseed_demo_state`), Redis status helpers (`status_set`/`status_get`/`reseed_status_is_stale`/`_now_iso`), `ReseedStatusResponse`/`ReseedSummary` Pydantic models, `run_demo_reseed_cleanup`, the AC-12 cleanup gate `_demo_reseed_cleanup_test_gate`, and `_resolve_engine_base_url`. The orchestrator emits `demo_reseed_truncate_committed` (AC-13 ordering proof) and per-call `demo_reseed_api_call_started` logs.
- `backend/workers/all.py:WorkerSettings.functions` — **`run_demo_reseed` IS registered** today via `func(run_demo_reseed, timeout=DEMO_RESEED_JOB_TIMEOUT_S, max_tries=1)`. The "forgot to register" regression in §1 is a *future* risk the new suite must guard against, not a present defect.
- `backend/tests/integration/_demo_reseed_uvicorn.py` — `running_uvicorn()` context manager: boots uvicorn on `127.0.0.1:8000` (the literal the old in-API-container handler self-called), applies migrations, asserts the port is free and `localhost` resolves to IPv4. The new harness builds on this.
- `backend/tests/unit/services/test_demo_seeding_status.py` — **11** unit test functions (several parametrized) covering the `ReseedStatusResponse` Pydantic shape, the `_build_search_space` builder, `status_get`/`status_set` round-trip, and `reseed_status_is_stale`. Does **not** cover the end-to-end flow against real Postgres + Arq.
- `backend/tests/contract/test_test_endpoint_guard.py:213` + `test_openapi_surface.py:116` — contract tests already assert the env-guard 404 and the OpenAPI `202` surface for the POST. No rewrite needed; the integration rewrite complements these.

### Navigation and link impact

N/A — test-only chore, no UI or routing change.

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `backend/tests/integration/test_demo_seeding.py` | module-level `pytest.mark.skip` (line 53); 9 sync-flow `async def test_*` asserting `status_code == 200` + `body["clusters_created"]` etc. | 9 cases | Rewrite to async POST→poll; remove the skip marker |
| `backend/tests/integration/test_demo_seeding_timeout.py` | module-level `pytest.mark.skip` (line 44); 1 sync per-call-timeout case | 1 case | Re-home the timeout assertion to the worker layer; remove the skip marker |

### Existing behaviors affected by scope change

- **AC-12 (cleanup-while-locked) and AC-16 (advisory-lock pinning):** In the *old* sync flow the advisory lock + cleanup ran inside the route handler (same in-process uvicorn the test owned), so the test observed `pg_locks` and injected the cleanup gate against the handler. In the *new* async flow **both live in the worker** (`run_demo_reseed`'s `engine.connect()` lock-conn + its `run_demo_reseed_cleanup` call). Current: handler-side lock/cleanup. New: worker-side. Decision needed: **yes — resolved in §19 (inline worker invocation in-process).**
- **AC-3 (concurrent 409):** Old flow raced two POSTs through the handler's advisory lock. New flow: the *handler* returns 409 based on the **Redis status** being `running` (not the Postgres advisory lock — the lock is now worker-side). The rewrite asserts 409 against a `running` Redis status seeded by an in-flight (or inline-held) first reseed.

---

## 3) Scope

### In scope

- Rewrite the 9 cases in `test_demo_seeding.py` to the async POST→poll-until-terminal contract (AC-1, AC-2, AC-3, AC-5, AC-12, AC-13, AC-14, AC-15, AC-16 — renumbering preserved from the legacy file for traceability).
- Re-home the 1 timeout case (`test_demo_seeding_timeout.py`) to assert the **worker-side** per-call timeout behavior (the timeout now lives in `run_demo_reseed`'s `httpx.Timeout(settings.demo_reseed_per_call_http_timeout_s)`), not the POST handler.
- Add **AC-Async**: assert the `GET /status` polling endpoint observes the `running → complete` transition with `scenarios_completed` monotonically non-decreasing.
- Add an **async-flow harness fixture** that drives `run_demo_reseed` inline in the test process so the lock-conn, cleanup, and `pg_locks` observation all share the test's Postgres engine and the in-process uvicorn `app`.
- Remove both module-level `pytest.mark.skip` markers.
- **Optional production ergonomics refactor (decision in §19, D-3):** introduce a settings-resolvable worker API base URL (e.g., `Settings.relyloop_worker_api_base_url`, default `"http://api:8000"`) so the harness points the worker's self-call at `127.0.0.1:8000` via settings override instead of monkeypatching the hardcoded literal at `demo_reseed.py:154`. If adopted, this is the only production-code line touched and is covered by the existing worker tests + the new AC-Async happy path.

### Out of scope

- Any change to `reseed_demo_state`, the worker's lock/cleanup logic, the Redis status shape, or the route handler's status codes.
- A real-Arq-process worker fixture (a separate `arq` subprocess consuming the queue). Rejected in §19 D-1 — the inline-invocation path observes every assertion the lock-contention ACs need without the ~30-min ES+Arq subprocess cost.
- A `backend/tests/smoke/` real-stack demo-reseed test (the legacy docstring referenced one "once it lands"; it never landed and is not in scope here — capture separately if desired, but the heavy-lane integration suite is sufficient for the regressions in §1).

### API convention check

Conventions per [`docs/01_architecture/api-conventions.md`](../../../../01_architecture/api-conventions.md). This chore adds **no new endpoints** — it tests two existing ones:

- **Endpoint prefix:** `/api/v1/_test/...` (test-only surface, gated by `_require_development_env`). Verified in `backend/app/api/v1/_test.py:76`.
- **Error envelope:** `{ "detail": { "error_code": "<CODE>", "message": "<human>", "retryable": <bool> } }` — verified at `_test.py:79-92` (`_err` helper) and the inline 409/503 raises. Tests assert this exact shape.

### Phase boundaries

Single-phase. No deferred-phase tracking file required.

## 4) Product principles and constraints

- **Test-only.** No change to production reseed behavior. The sole permitted production edit is the optional D-3 base-URL refactor (one settings field + one worker line), and the suite must pass with or without it.
- **Heavy CI lane.** These tests require Postgres + ES + OpenSearch service containers and Redis. They run only when `SKIP_HEAVY_CI` is not `true` (the heavy lane). Each test must skip gracefully via the existing `postgres_reachable()` + `_engine_reachable()` module-level gates when its dependencies are unbound, mirroring the legacy file.
- **Deterministic, no wall-clock polling flakiness.** The harness must drive the worker to a terminal state deterministically (inline `await run_demo_reseed(ctx)`) rather than sleeping for an unbounded real-worker pickup. Bounded poll loops (with a ceiling that fails loudly) are acceptable only for asserting the *intermediate* `running` observation in AC-Async.
- **Mocking policy (CLAUDE.md §"Integration Test Mocking Policy"):** mock only external services (the engine HTTP API failure injection for AC-5/AC-14, and OpenAI if the rich scenario is exercised). DB, repos, services, the orchestrator, and the worker run for real.

### Anti-patterns

- **Do not** assert the POST returns a `ReseedSummary` — it returns 202 + an initial `ReseedStatusResponse`. The summary only appears in the terminal `complete` status payload's `summary` field.
- **Do not** spin up a separate `arq` worker subprocess to consume the queue — it costs ~30 min of ES+Arq setup per run and makes the lock-contention ACs observe a *different* process's connection, defeating the `pg_locks` pinning assertion. Drive the worker inline in-process instead.
- **Do not** monkeypatch internal service/worker functions to fake terminal state. The worker must run `reseed_demo_state` for real; only the **engine HTTP layer** is mocked for failure-injection cases (AC-5/AC-14).
- **Do not** observe `pg_locks` from an engine in a *different* OS process than the one holding the lock. The inline worker invocation must hold the lock on a connection from an engine the test can also query — same process, same Postgres container.
- **Do not** weaken the production `demo_reseed_per_call_http_timeout_s` validator (`ge=...`) to force the worker-timeout case. Use `model_construct` or a settings override that bypasses the validator only in the test, exactly as the legacy timeout test did.
- **Do not** leave a stale `running` Redis status key between tests — it would make a later test's POST 409 unexpectedly. The per-test cleanup fixture must clear `DEMO_RESEED_STATUS_KEY`.

## 5) Assumptions and dependencies

- Dependency: **Postgres + Elasticsearch + OpenSearch service containers** (heavy CI lane).
  - Why required: the orchestrator indexes docs into ES/OS and runs real studies against Postgres.
  - Status: implemented (GHA `pr.yml` provisions them).
  - Risk if missing: tests skip via `postgres_reachable()` / `_engine_reachable()` gates (no false failure).
- Dependency: **Redis** for the status key + the Arq pool.
  - Why required: status persistence and (for the POST path) `arq_pool`.
  - Status: implemented.
  - Risk if missing: the harness can fall back to a `Redis.from_url(settings.redis_url)` handle in the inline `ctx`; if Redis is unbound the test skips.
- Dependency: **`cluster_credentials.yaml`** mounted via `CLUSTER_CREDENTIALS_FILE` so the in-orchestrator `POST /api/v1/clusters` probe resolves `local-es`/`local-opensearch`.
  - Status: implemented as an autouse fixture in both legacy files; carried into the rewrite unchanged.
- Dependency: **in-process uvicorn** (`running_uvicorn()`), so the worker's `api_client` self-call and the test client hit the same `app` and monkeypatches/`caplog` apply to both.
  - Status: implemented at `_demo_reseed_uvicorn.py`.

## 6) Actors and roles

- Primary actor(s): the test runner (CI / developer). No product actor.
- Role model: N/A — single-tenant install, no auth surface.

### Authorization

N/A — single-tenant install, no auth surface. The reseed endpoints are gated solely by `_require_development_env` (404 outside `ENVIRONMENT=development`), already covered by `test_test_endpoint_guard.py`.

### Audit events

N/A — `audit_log` lands at MVP3, and this is a test-only chore that mutates no audited state.

## 7) Functional requirements

### FR-1: Async-flow harness fixture

- Requirement:
  - The system **MUST** provide a fixture (module-scoped uvicorn + function-scoped driver) that:
    - boots `running_uvicorn()` on `127.0.0.1:8000`;
    - builds a real Redis handle and an inline `ctx` dict (`{"redis": <handle>}`) suitable for `await run_demo_reseed(ctx)`;
    - points the worker's API `httpx.AsyncClient` base URL at `http://127.0.0.1:8000` (via the D-3 settings override if adopted, else via a `monkeypatch` of the worker's client construction);
    - clears `DEMO_RESEED_STATUS_KEY` **and** the Arq singleton dedup keys (`arq:job:demo_reseed:singleton` + `arq:result:demo_reseed:singleton` + the in-progress key) before each test, so a prior test's enqueue-dedup state or stale `running` status never leaks into the next test's 409/enqueue logic.
    - **Critical (cycle-3 fix):** the singleton dedup keys MUST also be cleared **between consecutive POSTs within a single test** (see FR-2). Arq's `enqueue_job` returns `None` and silently drops the enqueue if `arq:job:demo_reseed:singleton` OR `arq:result:demo_reseed:singleton` already exists (`ArqRedis.enqueue_job` checks `pipe.exists(job_key, result_key)`). Because the inline harness never lets a real worker consume the queued job, the first POST's `arq:job:demo_reseed:singleton` key persists (≈24h TTL) and would cause the second POST's enqueue to be dropped — masking a genuine "second enqueue failed" regression and breaking AC-Reg's enqueue spy on multi-POST cases (AC-2, AC-12, AC-Reg). The POST-then-poll helper owns this cleanup.
  - The fixture **MUST** carry forward the legacy `_stub_cluster_credentials` and `_patch_engine_for_test_host` patches (resolver + `SCENARIOS` base_url rewrite to `127.0.0.1` loopback ports) so engine self-calls and the cluster-create probe reach the CI service containers.
- Notes: The worker holds the advisory lock on its own `engine.connect()`; because `await run_demo_reseed(ctx)` runs in the test process, `get_engine()` returns the same process-wide engine the test's `db_engine` fixture queries, so the AC-16 `pg_locks` observer sees the lock-holding pid.

### FR-2: POST-then-poll helper

- Requirement:
  - The system **MUST** provide a helper that POSTs `/api/v1/_test/demo/reseed`, asserts **202** + an initial `running` `ReseedStatusResponse`, then drives the enqueued job to terminal state (`await run_demo_reseed(ctx)` inline) and returns the final `ReseedStatusResponse` read from `GET /status`.
  - The helper **MUST** assert the POST body is the initial status (`status=="running"`, `scenarios_total==len(SCENARIOS)+1`), **not** a `ReseedSummary`.
  - **The helper MUST clear the Arq singleton dedup keys (`arq:job:demo_reseed:singleton`, `arq:result:demo_reseed:singleton`, in-progress key) after the inline run returns**, so a subsequent POST in the same test enqueues cleanly rather than being silently dropped by Arq's `_job_id` dedup (the inline harness never consumes the queued job, so the singleton key would otherwise persist for its full ≈24h TTL). This makes AC-2's second reseed, AC-12's third POST, and AC-Reg's enqueue spy faithful — each POST's `enqueue_job` returns a real `Job`, not `None`.

### FR-3: Rewrite the 9 cases to the async contract

- Requirement:
  - The system **MUST** rewrite AC-1, AC-2, AC-3, AC-5, AC-12, AC-13, AC-14, AC-15, AC-16 to the async contract per §12. Each asserts the **terminal** Redis/poll status and the post-run DB row counts (where applicable) rather than the POST's synchronous body.

### FR-4: Re-home the per-call timeout case to the worker layer

- Requirement:
  - The system **MUST** assert that a per-call HTTP timeout inside the worker (`demo_reseed_per_call_http_timeout_s` exceeded) drives the terminal status to `failed` with a timeout-flavored `failed_reason`, and that `run_demo_reseed_cleanup` is attempted (assert the `demo_reseed_cleanup_truncated` log line via `caplog`).
- Notes: The legacy assertion (503 SEED_FAILED on the POST) no longer applies — the POST returns 202 before any per-call timeout can occur.

### FR-5: AC-Async polling-transition assertion (new)

- Requirement:
  - The system **MUST** add a case asserting that during a reseed, the recorded status-write sequence shows `scenarios_completed` that never decreases, starts at `running` (`scenarios_completed==0`), and ends at `complete` with `scenarios_completed == scenarios_total` and a populated `summary`. The sequence is captured by monkeypatching `backend.app.services.demo_seeding.status_set` with a recording spy (see Notes) — NOT by injecting a callback into `run_demo_reseed`, which takes only `ctx`.
- Notes: The Redis status key is a single overwritten value, so reading it only at start and end cannot by itself prove monotonicity across the worker's intermediate writes. **Injection surface:** `run_demo_reseed(ctx)` takes only `ctx` and builds its own `_redis_status_cb` closure internally (`demo_reseed.py:161`), which — like the handler's initial seed and the worker's terminal writes — funnels through `backend.app.services.demo_seeding.status_set(redis, status)` (`demo_reseed.py:162,185` + the orchestrator's per-phase `await status_callback(...)` which the closure forwards to `status_set`). The test therefore records the sequence by **monkeypatching `demo_seeding.status_set`** with a spy that appends each `ReseedStatusResponse` then delegates to the real `status_set` — this captures every status write (initial `running`, each per-phase update, terminal `complete`) without injecting anything into the worker signature and without a production change. The test then asserts monotonic non-decrease over the recorded `scenarios_completed` sequence. The spy is mandatory. The sequence MUST start with a `running` observation (`scenarios_completed==0`) and end with `complete` (`scenarios_completed==scenarios_total`, populated `summary`). A real interleaved poll mid-run is not required and would be flaky; the recorded sequence is the deterministic source of truth.

### FR-6: Worker-registration + enqueue guard

- Requirement:
  - The system **MUST** assert that `"run_demo_reseed"` is resolvable as a registered Arq function in `WorkerSettings.functions` (unwrapping `arq.func(...)` wrappers) so a future drop of the registration fails CI.
  - The system **MUST** also assert that the POST handler actually enqueues that job: by spying on the app's `arq_pool.enqueue_job`, verify the POST calls it with name `"run_demo_reseed"` and `_job_id="demo_reseed:singleton"`. This closes the "POST stopped enqueuing / enqueues the wrong name" gap that the inline-invocation harness would otherwise miss (since the harness drives `run_demo_reseed` directly rather than consuming the queued job).
- Notes: Together these close the "forgets to register `run_demo_reseed`" AND the silent-enqueue-failure regression classes in §1 without a real Arq worker subprocess.

## 8) API and data contract baseline

### 7.1 Endpoint surface

No new endpoints. The suite exercises the two existing ones:

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `POST` | `/api/v1/_test/demo/reseed` | Enqueue reseed; 202 + initial status | `SEED_IN_PROGRESS` (409), `ARQ_POOL_UNAVAILABLE` (503), `RESOURCE_NOT_FOUND` (404 outside dev) |
| `GET` | `/api/v1/_test/demo/reseed/status` | Poll current Redis status | `RESOURCE_NOT_FOUND` (404 outside dev) |

### 7.2 Contract rules

- 409/503 bodies **MUST** carry `detail.error_code` + `detail.retryable` (verified at `_test.py:79-92`).
- The POST status code is **202** (not 200); the GET is **200** with `{status:"idle"}` when absent.

### 7.3 Response examples

POST success (initial enqueue, **202**):
```json
{
  "status": "running",
  "started_at": "2026-05-31T12:00:00Z",
  "finished_at": null,
  "scenarios_total": 5,
  "scenarios_completed": 0,
  "current_step": "enqueued — waiting for worker",
  "failed_reason": null,
  "summary": null
}
```

GET status, terminal success (**200**):
```json
{
  "status": "complete",
  "started_at": "2026-05-31T12:00:00Z",
  "finished_at": "2026-05-31T12:04:30Z",
  "scenarios_total": 5,
  "scenarios_completed": 5,
  "current_step": null,
  "failed_reason": null,
  "summary": {
    "clusters_created": 4,
    "query_sets_created": 4,
    "studies_completed": 4,
    "proposals_created": 4,
    "duration_ms": 270000
  }
}
```

POST concurrent-reseed failure (**409**):
```json
{
  "detail": {
    "error_code": "SEED_IN_PROGRESS",
    "message": "A demo reseed is already running. Poll GET /api/v1/_test/demo/reseed/status for progress.",
    "retryable": true
  }
}
```

GET status, terminal failure (**200**, after a worker-side failure):
```json
{
  "status": "failed",
  "started_at": "2026-05-31T12:00:00Z",
  "finished_at": "2026-05-31T12:00:12Z",
  "scenarios_total": 0,
  "scenarios_completed": 0,
  "current_step": null,
  "failed_reason": "DemoSeedingError: products/put_index: HTTP 500 ...",
  "summary": null
}
```

### 7.4 Enumerated value contracts

| Field | Accepted values (exact) | Backend source of truth | Frontend call site(s) |
|---|---|---|---|
| `ReseedStatusResponse.status` | `idle`, `running`, `complete`, `failed` | `backend/app/services/demo_seeding.py:204` (`ReseedStatusLiteral = Literal["idle","running","complete","failed"]`) | N/A — test-only; the frontend `useDemoReseedStatus` hook reads these but no new option list is added by this chore |

Note: this chore adds no frontend option list. The table grounds the status values the tests assert against the backend `Literal`.

### 7.5 Error code catalog

No new error codes. Tests assert existing `SEED_IN_PROGRESS` (409) and (for the worker-init-failure barrier) the `failed` terminal status `failed_reason` prefix.

## 9) Data model and state transitions

N/A — no schema change. The only persisted state touched is the demo tables (`TRUNCATE_TABLES`) the reseed already wipes/repopulates and the Redis status key, both pre-existing.

### Required invariants (asserted by tests, not introduced)

- The terminal `summary` counts equal `len(SCENARIOS) + rich_count` for `clusters_created`/`query_sets_created` and `len(results) + rich_count` for `studies_completed`/`proposals_created`, where `rich_count` is `1` when the rich ESCI scenario succeeded and `0` when it was skipped (no OpenAI key or missing `samples/`). Verified at `demo_seeding.py:1618-1626`. On the happy path this is **5** when the rich scenario runs and **4** when it is skipped. `scenarios_total == len(SCENARIOS) + 1` (= 5) regardless — it counts the *attempted* total, including the rich scenario.
- The advisory lock (`DEMO_RESEED_LOCK_KEY`) is held by exactly one Postgres backend pid for the lock's lifetime (AC-16) and is released after the worker returns.
- `scenarios_completed` is monotonically non-decreasing across status writes (AC-Async).

### State transitions (status enum, asserted)

`idle → running → {complete | failed}`. The handler seeds `running`; the worker writes `complete` or `failed`.

## 10) Security, privacy, and compliance

- Threats: none new — test-only. The endpoints remain dev-gated (404 outside development), already contract-tested.
- Secrets: the harness mounts dev-stack basic-auth credentials (`elastic/changeme`, `admin/admin`) for ES/OS via `cluster_credentials.yaml`, identical to the legacy fixtures and the local Compose contract. No real secrets.
- Auditability / retention: N/A.

## 11) UX flows and edge cases

N/A — test-only chore, no UI. (Tooltip inventory, IA, progressive disclosure all N/A.)

## 12) Given/When/Then acceptance criteria

> AC numbering preserves the legacy file's IDs for traceability. AC-4 remains in the timeout file (FR-4). AC-6–AC-11 never existed in this suite (they belong to other features); the gaps are intentional.

### AC-1: Happy path on a clean DB
- Given an empty demo DB (per-test TRUNCATE) and reachable ES/OS.
- When the harness POSTs `/api/v1/_test/demo/reseed` and drives `run_demo_reseed` inline to terminal.
- Then the POST returns **202** with an initial `running` status (`scenarios_completed==0`, `scenarios_total==5`); the terminal `GET /status` is `complete` with a populated `summary`; and the `summary` counters equal `len(SCENARIOS) + rich_count` (clusters/query_sets) and `len(results) + rich_count` (studies/proposals) — i.e. **4** when the rich scenario was skipped, **5** when it ran (`demo_seeding.py:1618-1626`).
- Then DB row counts match the same `4`-or-`5` cardinality: `clusters == N`, `query_sets == N`, `query_templates >= N`, `judgment_lists >= N`, `studies >= N`, `digests >= N`, `proposals == N`, where `N == summary.clusters_created`.
- Example values: when the rich scenario runs, `summary.clusters_created == 5` and `clusters` table count `== 5`; when skipped, both `== 4`. The terminal `scenarios_completed == scenarios_total`.
- Note: the test reads `summary.clusters_created` from the terminal status and asserts the table counts against **that** value (not a hardcoded `4`), so the case passes deterministically whether or not the rich ESCI scenario succeeds in CI (which depends on the OpenAI key + `samples/` availability). `>=` is used for tables the rich scenario may augment beyond the small-scenario cardinality (templates/qsets/judgment-lists/studies/digests when extra rows from the UBI re-entry or rich path land); `==` for `clusters` and `proposals`, which track `summary.*_created` exactly. Exact per-table relations are finalized in the implementation plan by reading the rich-scenario inserts — see §19 D-4.

### AC-2: Replaces pre-existing demo state
- Given a populated demo DB (one prior successful reseed).
- When a second reseed runs inline to terminal.
- Then the terminal status is `complete` and the new `clusters.id` set is disjoint from the prior set. Disjointness holds because `clusters.id` is a **UUIDv7** primary key generated fresh on every insert (`backend/app/db/models/cluster.py:49`) — the prior rows are removed by the reseed's `TRUNCATE ... RESTART IDENTITY CASCADE` and the new rows get brand-new UUIDs. (`RESTART IDENTITY` resets any *sequence* columns but is irrelevant to the UUID PK; the disjointness comes from UUID freshness, not identity reset.) Mirrors the legacy assertion at the old `test_demo_seeding.py:334`.

### AC-3: Concurrent reseed returns 409
- Given a reseed whose Redis status is `running` (seeded by the handler's pre-enqueue write, or by an inline in-flight first run).
- When a second POST is issued before the first reaches a terminal state.
- Then the second POST returns **409** with the full envelope `{detail:{error_code:"SEED_IN_PROGRESS", message:<non-empty>, retryable:true}}` — the test asserts all three keys (`error_code`, a non-empty `message`, `retryable is True`), not just `error_code`.
- Note: in the async flow the 409 derives from the **Redis** `running` status + `reseed_status_is_stale()==False`, not the Postgres advisory lock. The test seeds `running` via `status_set` (or the first POST) and asserts the second POST 409s without driving the worker.
- Coverage note: the **503 `ARQ_POOL_UNAVAILABLE`** branch (`request.app.state.arq_pool is None`) is exercised by a small dedicated micro-case that boots the harness without an arq_pool on app.state (or temporarily nulls it) and asserts the 503 envelope shape — so both POST failure envelopes are covered.

### AC-5: Mid-loop engine failure → terminal `failed` + cleanup
- Given the engine HTTP layer is monkeypatched to return HTTP 500 on a specific scenario's index/doc call.
- When the worker runs inline.
- Then the terminal `GET /status` is `failed` with a `failed_reason` containing the offending step substring, and `run_demo_reseed_cleanup` ran (assert the `demo_reseed_cleanup_truncated` log via `caplog`).

### AC-12: Cleanup-while-locked blocks a concurrent reseed
- Given a first reseed forced to fail mid-loop, with the cleanup pass gated by `_demo_reseed_cleanup_test_gate` (a `threading.Event`) so the worker holds the advisory lock while cleanup waits.
- When, during that window, a second POST is issued.
- Then the second POST returns **409 SEED_IN_PROGRESS** (the first worker's Redis status is still `running` and the advisory lock is still held); after the gate is released and the first worker finishes (terminal `failed`), a third POST + inline run succeeds (terminal `complete`).
- Note: because the worker runs inline, the test launches the first `run_demo_reseed(ctx)` as a background `asyncio.Task`, waits on the cleanup-entered event, fires the second POST, then releases the gate and awaits the task. The first run's `status_set("running")` is what makes the second POST 409. The cleanup gate does **not** block the event loop despite being a synchronous `threading.Event`: the production code waits on it via `await asyncio.to_thread(_demo_reseed_cleanup_test_gate.wait)` (`demo_seeding.py:493`), which offloads the blocking `.wait()` to a worker thread so the loop stays free for the test coroutine to issue the second POST and later `.set()` the gate. The implementer MUST preserve this `to_thread` offload — a naive in-loop `event.wait()` would deadlock the inline-task design.

### AC-13: TRUNCATE commits before any self-call (log ordering)
- Given `caplog` capturing `backend.app.services.demo_seeding` at INFO.
- When a reseed runs inline.
- Then the `demo_reseed_truncate_committed` record's index precedes the first `demo_reseed_api_call_started` record with `client=="api"` and `/api/v1/clusters` in its `url`.

### AC-14: Natural failure cleanup is deterministic
- Given the same engine-500 injection as AC-5.
- When the worker runs inline to a terminal `failed`.
- Then post-failure DB row counts for the demo tables are 0 (cleanup TRUNCATE ran) — asserted on the same tables the cleanup pass wipes.

### AC-15: Dual-client contract — no role mixing, correct basic auth
- Given the worker's two `httpx.AsyncClient`s (API at the harness-overridden base URL; engine unscoped with per-call basic auth).
- When a reseed runs inline.
- Then API-targeted calls go through the API client (relative `/api/v1/...` paths against the base URL) and engine calls carry the correct basic-auth tuple — asserted by a request-recording transport/spy on each client, verifying no engine call lands on the API base URL and vice versa.
- Note: the legacy test inspected client construction; the rewrite asserts the same separation via the worker's actual two-client construction (recorded by wrapping/ spying the clients the harness injects, or by a transport recorder).

### AC-16: Advisory lock pinned to one Postgres connection
- Given a `pg_locks` observer polling for the advisory `(classid, objid)` derived from `DEMO_RESEED_LOCK_KEY` every 200ms, and the worker run inline as a background task.
- When the reseed runs.
- Then the observer records at least one observation, the lock-holding pid never changes (`len(set(pids)) == 1`), and after the worker returns the lock is gone.
- Note: the inline worker holds the lock on `get_engine().connect()` in the test process; the observer queries the same Postgres container via `db_engine`, so the pid is observable.

### AC-Async: Polling transition `running → complete`, `scenarios_completed` monotonic
- Given a happy-path reseed with a mandatory `status_callback` spy recording every `ReseedStatusResponse`.
- When the handler seeds the initial `running` status and the worker runs inline to `complete`.
- Then the recorded callback sequence shows `scenarios_completed` never decreasing; the first recorded status is `running` (`scenarios_completed==0`); and the terminal status is `complete` with `scenarios_completed==scenarios_total` and a populated `summary`. Asserting only the start + end Redis reads is insufficient (single overwritten key) — the spy's recorded sequence is required.

### AC-Reg: Worker registration + enqueue guard (FR-6)
- Given `WorkerSettings.functions` and a spy on the enqueue path.
- When the test (a) resolves each `WorkerSettings.functions` entry's underlying coroutine (unwrapping `arq.func(...)` wrappers) and (b) issues a POST `/api/v1/_test/demo/reseed` with the app's `arq_pool.enqueue_job` wrapped by a recording spy.
- Then (a) `"run_demo_reseed"` is among the registered function names (fails if a future change drops the registration), AND (b) the POST is observed to call `enqueue_job` with the function name `"run_demo_reseed"` and `_job_id="demo_reseed:singleton"`. Together these close the "forgot to register" and "POST enqueues the wrong/no job" regression classes without needing a real Arq subprocess to consume the queue.

## 13) Non-functional requirements

- Performance: inline invocation targets ~minutes per happy-path case (real studies run), well under the legacy `180s` client timeouts. The suite runs only in the heavy CI lane; total added wall-clock is bounded by the number of happy-path cases that run a full reseed (AC-1, AC-2, AC-13, AC-15, AC-16, AC-Async) vs. failure cases that short-circuit (AC-3, AC-5, AC-12, AC-14).
- Reliability: every case skips gracefully when Postgres/ES/OS/Redis are unbound (existing module-level gates). No flaky wall-clock sleeps for terminal detection — inline `await` is deterministic.
- Operability: failures surface the worker's `failed_reason` and `caplog` records; the harness asserts loudly (named RuntimeErrors) when uvicorn or the port is mis-set.

## 14) Test strategy requirements (spec-level)

This feature **is** the test work. The "minimum coverage by layer" maps to the rewritten suite:

- **Unit tests** (`backend/tests/unit/services/test_demo_seeding_status.py`): unchanged (11 functions). The chore does not remove or duplicate unit coverage; it adds the integration layer the unit tests cannot reach (real Postgres + Arq + Redis persistence).
- **Integration tests** (`backend/tests/integration/test_demo_seeding.py` + `test_demo_seeding_timeout.py`): the deliverable. 9 rewritten cases + AC-Async + AC-Reg in the main file; 1 re-homed worker-timeout case in the timeout file. Skip markers removed.
- **Contract tests** (`backend/tests/contract/`): unchanged — `test_test_endpoint_guard.py` + `test_openapi_surface.py` already assert the 404 guard and the 202 surface. No new contract test required, but the rewrite must not contradict them (POST=202).
- **E2E tests**: N/A — the home-button reseed UI flow is covered by its own feature's E2E; this chore is backend integration only.

### Async-flow harness design (the meat)

- **Topology:** module-scoped `running_uvicorn()` on `127.0.0.1:8000`; function-scoped driver fixture yielding `(client, ctx, db_engine)`.
- **Inline worker invocation:** the driver provides a callable `run_to_terminal()` that does `await run_demo_reseed(ctx)` where `ctx = {"redis": <handle>}`. The worker's `get_engine()`/`get_session_factory()` resolve to the same process-wide engine the test queries — this is what makes AC-16's `pg_locks` pinning observable and AC-12's gate work in-process. (Decision D-1.)
- **API base-URL redirection:** the worker hardcodes `base_url="http://api:8000"` at `demo_reseed.py:154`. The harness must redirect it to `http://127.0.0.1:8000`. Two implementation options, resolved in D-3: (a) introduce `Settings.relyloop_worker_api_base_url` (default `"http://api:8000"`) and have the worker read it — the harness then sets the env override; or (b) `monkeypatch` the worker's client construction. **Recommended: (a)** — a 2-line production refactor that removes a magic literal and makes the test a clean settings override (no patching of `httpx.AsyncClient`).
- **Engine reachability:** carry forward the legacy `_patch_engine_for_test_host` (resolver passthrough + `SCENARIOS.base_url` rewrite to `127.0.0.1:9200`/`9201`) and `_stub_cluster_credentials` autouse fixtures verbatim.
- **Per-test cleanup:** wipe demo tables + ES/OS indices (existing `_clean_demo_state_before_each`) **and** clear `DEMO_RESEED_STATUS_KEY` plus the Arq `demo_reseed:singleton` job/result/in-progress keys so neither a prior `running`/`complete` status nor a stale enqueue-dedup entry leaks into the next test's 409/enqueue logic.
- **Between-POST cleanup (within a test):** the POST-then-poll helper clears the Arq `demo_reseed:singleton` dedup keys after each inline run, so multi-POST cases (AC-2, AC-12, AC-Reg) enqueue cleanly rather than hitting Arq's silent `_job_id` dedup-drop (the inline harness never consumes the queued job, so the key persists otherwise). See FR-1/FR-2.
- **Failure injection (AC-5/AC-14):** monkeypatch the **engine** `httpx.AsyncClient` request path (or the orchestrator's `_put`/`_post` engine calls) to raise/return 500 on a target step. Do not patch internal service functions to short-circuit terminal state.

## 15) Documentation update requirements

- `docs/03_runbooks/`: no new runbook. If the D-3 settings field is added, note `relyloop_worker_api_base_url` in the local-dev / parallel-worktrees env notes (one line) — otherwise N/A.
- `docs/05_quality/testing.md`: N/A — the test-layer convention is unchanged; this chore fills an existing gap rather than adding a new layer.
- `state.md`: refresh "known debt" to drop the "demo-reseed async flow has no integration coverage" entry once merged.
- All other `docs/01–04`: N/A.

## 16) Rollout and migration readiness

- Feature flags / staged rollout: N/A.
- Migration/backfill: none.
- Operational readiness gates: the rewritten suite must pass in the heavy CI lane (Postgres + ES + OS + Redis service containers). Locally, `docker compose stop api` is required first (the harness owns `127.0.0.1:8000`) — already documented in `_demo_reseed_uvicorn.py`'s `_assert_port_free`.
- Release gate: `make test-integration` green for `test_demo_seeding.py` + `test_demo_seeding_timeout.py` with the skip markers removed; `make lint` + `make typecheck` clean; if D-3 adopted, the existing worker tests + new AC cases green.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 | AC-12, AC-16, (all) | Harness fixture | `test_demo_seeding.py` fixtures | `state.md` |
| FR-2 | AC-1, AC-2, AC-13, AC-15, AC-Async | POST+poll helper | `test_demo_seeding.py` | — |
| FR-3 | AC-1, AC-2, AC-3, AC-5, AC-12, AC-13, AC-14, AC-15, AC-16 | Rewrite 9 cases | `test_demo_seeding.py` | — |
| FR-4 | AC-4 (timeout, worker layer) | Re-home timeout | `test_demo_seeding_timeout.py` | — |
| FR-5 | AC-Async | New polling-transition case | `test_demo_seeding.py` | — |
| FR-6 | AC-Reg | Registration guard | `test_demo_seeding.py` | — |

## 18) Definition of feature done

- [ ] All AC-* (1, 2, 3, 5, 12, 13, 14, 15, 16, Async, Reg + the re-homed timeout AC-4) pass in the heavy CI lane.
- [ ] Both module-level `pytest.mark.skip` markers removed.
- [ ] `make test-integration`, `make lint`, `make typecheck` green.
- [ ] If D-3 adopted: `Settings.relyloop_worker_api_base_url` added with default `"http://api:8000"`, worker reads it, existing worker tests still green.
- [ ] `state.md` known-debt entry dropped.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

- None blocking. D-4 (exact `==` vs `>=` per table in AC-1) is resolved at implementation-plan time by reading the rich-scenario inserts; it does not block the plan's interface design.

### Decision log

- 2026-05-31 — **D-1: Drive the worker inline (`await run_demo_reseed(ctx)`) in the test process; do NOT spin a separate Arq worker subprocess.** Rationale: a real worker subprocess costs ~30 min ES+Arq setup per CI run and, fatally for AC-16/AC-12, holds the advisory lock on a connection in a *different* OS process — the `pg_locks` pinning observer and the in-process cleanup gate would observe a different backend. Inline invocation runs the worker for real (orchestrator + studies + Redis writes all execute) in ~minutes, shares the process-wide SQLAlchemy engine so `pg_locks` is observable, and keeps `caplog`/monkeypatch applicable. The lock-contention ACs (AC-12, AC-16) are fully satisfied inline: AC-12 launches the inline worker as a background `asyncio.Task` and uses the existing `_demo_reseed_cleanup_test_gate` to hold the lock while a concurrent POST 409s; AC-16's observer queries the same Postgres container the inline worker locks. No separate worker process is required.
- 2026-05-31 — **D-2: AC-3/AC-12 assert the 409 from the Redis `running` status, not the Postgres advisory lock.** Rationale: in the async flow the handler's concurrency guard is the Redis status (`status=="running" and not stale`), not the advisory lock (which moved to the worker). The lock still gates the *worker* from double-running; the handler gates the *enqueue*. Tests assert the handler-side 409 by seeding/holding a `running` status.
- 2026-05-31 — **D-3: Redirect the worker's API base URL via a settings field (recommended) rather than monkeypatching the hardcoded literal.** The worker hardcodes `base_url="http://api:8000"` at `demo_reseed.py:154`. Adding `Settings.relyloop_worker_api_base_url` (default `"http://api:8000"`) and reading it in the worker is a ~2-line production refactor that turns the harness redirect into a clean env override (no `httpx.AsyncClient` patching). If the reviewer prefers zero production change, the fallback is a `monkeypatch` of the worker's client construction; the rewrite must work either way. Recommended default: adopt the settings field.
- 2026-05-31 — **D-4: AC-1 asserts table counts against the runtime `summary.clusters_created` value (`N` = `len(SCENARIOS) + rich_count`, i.e. 4 when the rich scenario is skipped, 5 when it runs), NOT a hardcoded constant.** `clusters` and `proposals` tables track `N` with `==`; `query_templates` / `judgment_lists` / `studies` / `digests` use `>=N` because the rich path + the UBI re-entry (Story 2.3) may add rows beyond the small-scenario cardinality. `query_sets` also tracks `N` with `==` per the orchestrator's `clusters_and_qsets` symmetry (`demo_seeding.py:1619,1623`), but the implementer MUST confirm `==` vs `>=` for `query_sets` by reading whether `_seed_rich_scenario` registers a distinct query set (it does — `rich/post_query_set` at `demo_seeding.py:983`, counted in `rich_count`). This is a test-assertion detail finalized in the implementation plan by reading the rich-scenario inserts; it does not block planning. (Supersedes the earlier draft that hardcoded `==4` — see cycle-2 correction.)
