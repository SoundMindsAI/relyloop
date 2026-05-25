# Feature Specification — Cluster health warmup at API startup

**Date:** 2026-05-24
**Status:** Draft
**Owners:** soundminds.ai (engineering)
**Related docs:**
- [idea.md](idea.md)
- [`docs/01_architecture/data-model.md` §"Cluster health caching"](../../../01_architecture/data-model.md) (Decision Log 2026-05-09)
- [`backend/app/adapters/health_cache.py`](../../../../backend/app/adapters/health_cache.py)
- [Sibling bug — capability-check observability (shipped PR #234)](../../../00_overview/implemented_features/2026_05_24_bug_openai_capability_check_incapable_on_valid_key/feature_spec.md)

**Depends on:** [`infra_foundation`](../../../00_overview/implemented_features/2026_05_09_infra_foundation/) (shipped) · [`infra_adapter_elastic`](../../../00_overview/implemented_features/2026_05_10_infra_adapter_elastic/) (shipped — provides `cluster_svc.get_or_probe_health` + the `cluster:health:*` cache).

---

## 1) Purpose

- **Problem:** `/healthz` reports `elasticsearch_clusters: {registered: N, healthy: 0, unreachable: N}` for the first 30s after a fresh API boot, even when every registered cluster is actually green. Root cause confirmed during idea preflight: `probe_registered_clusters` at [`backend/app/api/probes.py:95-133`](../../../../backend/app/api/probes.py#L95-L133) is a **cache-only** aggregate that counts cache-miss as `unreachable`, and the `cluster:health:*` Redis cache is populated lazily — only on demand from `GET /api/v1/clusters` and `GET /api/v1/clusters/{id}`. The cache-only design is mandated by CLAUDE.md Absolute Rule #11 (`/healthz` <200ms p99). After boot, until something hits the cluster-list endpoint, the cache is empty and the operator sees a false-alarm `unreachable` count.
- **Outcome:** **After** the warmup task completes (typically within ~5 seconds of API startup, bounded by per-cluster `httpx` probe latency), `/healthz` reports the accurate `healthy` / `unreachable` aggregate for all registered clusters. **During** the race window (T=0 through warmup-completion), `/healthz` still reports `unreachable: N` for as-yet-unprobed clusters per the existing cache-miss-equals-unreachable semantics at [`probes.py:124-126`](../../../../backend/app/api/probes.py#L124-L126) — that behavior is unchanged. The fix shrinks the false-alarm window from "~30s + however long until the first /api/v1/clusters call" to "~5s post-boot." The smoke-cascade observability story shipped by [PR #234 (capability-check status code)](../../../00_overview/implemented_features/2026_05_24_bug_openai_capability_check_incapable_on_valid_key/) is now matched on the cluster side: operators no longer need to know that "hit `/api/v1/clusters` first to warm the cache" before trusting the aggregate.
- **Non-goal:** Not changing the `ClusterAggregateHealth` response shape (Option B in the idea was rejected — see §19 D-2). Not adding a periodic re-warmup cron (Option B sub-decision was rejected — see §19 D-3). Not changing the cache TTL (30s, unchanged). Not changing `/healthz`'s in-request behavior (still cache-only read, no live probes). Not investigating the separate dashboard banner E2E failure (that's a different bug — see §3 out-of-scope).

## 2) Current state audit

### Existing implementations

- [`backend/app/api/probes.py:95-133`](../../../../backend/app/api/probes.py#L95-L133): `probe_registered_clusters(db, redis)` — cache-only aggregate. Lines 124-126 count cache-miss as `unreachable`. This is the function emitting the false-alarm counts.
- [`backend/app/services/cluster.py:192-215`](../../../../backend/app/services/cluster.py#L192-L215): `get_or_probe_health(redis, cluster) -> HealthStatus` — the existing on-demand probe. Reads cache first; on miss, builds an adapter, calls `adapter.health_check()`, writes the cached result. **Today** it catches `CredentialsMissing` and synthesizes `HealthStatus(status="unreachable", ...)` but **returns without calling `write_cached_health`** (verified by reading the function body — the `return` at line 205-209 short-circuits before line 214). That means credentials-missing clusters re-probe (and re-fail) on every call. This spec extends the function to write the synthetic HealthStatus to cache on the credentials-missing path, so the cache lands with a value in **every** branch. See §3 in-scope FR-7 + §19 D-7.
- [`backend/app/adapters/health_cache.py`](../../../../backend/app/adapters/health_cache.py): the `cluster:health:{cluster_id}` Redis key (30s TTL) used by both the aggregator and the on-demand probe. No change needed.
- [`backend/app/db/repo/cluster.py:48-96`](../../../../backend/app/db/repo/cluster.py#L48-L96): `list_clusters` with cursor pagination, default limit clamped to 200. The warmup walks all clusters in the same 200-row paginated windows that `probe_registered_clusters` already uses (line 120 in probes.py).
- [`backend/app/main.py:59-132`](../../../../backend/app/main.py#L59-L132): existing FastAPI `lifespan` hook. Already spawns `run_capability_check_background` via `asyncio.create_task` at line 85. **The warmup task mirrors that pattern exactly.**
- [`backend/app/llm/capability_check.py:404-431`](../../../../backend/app/llm/capability_check.py#L404-L431): `run_capability_check_background` — the canonical fire-and-forget reference. Skips when `api_key` is empty/None; catches `Exception` so the API never crashes on capability-check failure; propagates `asyncio.CancelledError` for clean shutdown. **The warmup function follows the same template.**

### Navigation and link impact

N/A — backend-only feature. No UI routes change. No CLI commands change.

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| [`backend/tests/unit/test_probes.py`](../../../../backend/tests/unit/test_probes.py) | `probe_registered_clusters` tests using `_make_cap()` + cached-status fixtures | 2 cases (`test_zero_clusters_returns_zeros`, `test_counts_by_cached_status`) | No change — `probe_registered_clusters` semantics unchanged. The warmup is an upstream cache-population task; it doesn't alter the aggregator behavior. |
| [`backend/tests/unit/test_main_lifespan.py`](../../../../backend/tests/unit/test_main_lifespan.py) (if exists; otherwise the spec's FR-4 adds it) | Lifespan-hook startup tests | TBD via Pass 1 glob | Add cases: (a) warmup task is spawned; (b) warmup is skipped when `count_clusters == 0`; (c) warmup task is cancelled on shutdown if still running. |
| Existing integration tests touching `/api/v1/clusters` | First call populates cache as side effect | Multiple | No change — the existing on-demand warm path is unchanged. Tests that depend on a cold cache before their first request must continue to receive a cold cache; the startup warmup runs in a different process / different lifespan from individual test fixtures. (Verified in §5.) |

### Existing behaviors affected by scope change

- **`/healthz` first-poll-after-boot behavior:** Currently reports `unreachable: N` for ~30s (until the first `/api/v1/clusters` call populates the cache). Post-fix: reports `unreachable: N` for ~5s while the warmup task races against the first `/healthz` poll, then flips to truthful counts. The exact race window is non-deterministic but bounded by the per-cluster probe latency (typically 50-500ms per cluster against the local Compose engines).
- **Cluster registration after startup:** Continues to be lazy-warmed by the existing `get_or_probe_health` on-demand path. Per §19 D-3, no periodic re-warmup cron is added. A cluster registered post-boot remains `unreachable` in `/healthz` until something hits `/api/v1/clusters` for it — acceptable per the rationale in §19 D-3.
- **Shutdown behavior:** Lifespan now cancels TWO background tasks instead of one (capability + cluster-warmup). Existing capability-check cancel logic at `main.py:121-131` is extended to also cancel the warmup task.

---

## 3) Scope

### In scope

- Add `run_cluster_health_warmup_background(db_factory: async_sessionmaker[AsyncSession], redis_client: Redis) -> None` — a fire-and-forget background function in a new module [`backend/app/services/cluster_health_warmup.py`](../../../../backend/app/services/cluster_health_warmup.py) (created by this spec). Opens a DB session via `async with db_factory() as db:` (released cleanly on cancellation), pages through all registered clusters in 200-row windows (matching `probe_registered_clusters`'s pagination loop), calls `cluster_svc.get_or_probe_health(redis, cluster)` for each.
- Wire the warmup into [`backend/app/main.py:lifespan`](../../../../backend/app/main.py#L59-L132):
  - Add `from backend.app.db.session import get_session_factory` to the imports (line 33-49 block).
  - At ~line 85 (right after the capability-check `asyncio.create_task`), capture `db_factory = get_session_factory()` and spawn `warmup_task = asyncio.create_task(run_cluster_health_warmup_background(db_factory, redis_client))`.
  - Add `warmup_task` to the shutdown cancel/await/swallow loop (mirror `cap_task` handling at lines 121-131).
- **Expand scope to fix the `CredentialsMissing` cache-write gap (per cycle-1 A1):** modify [`backend/app/services/cluster.py:202-209`](../../../../backend/app/services/cluster.py#L202-L209) so the `except CredentialsMissing` branch assigns the synthesized `HealthStatus` to a local variable, awaits `write_cached_health(redis, cluster.id, health)`, then returns. This ensures every branch of `get_or_probe_health` populates the cache — otherwise the warmup would loop forever-fail on credentials-missing clusters (and `/healthz` would forever report them `unreachable`).
- Emit one INFO structlog event per warmup completion with the keys: `event` (stable identifier), `count` (clusters walked), `failures` (count of per-cluster exceptions caught and swallowed), `duration_ms` (wall-clock elapsed). **Note (per cycle-1 A2):** the warmup does NOT report `cache_hits` / `probed` because `get_or_probe_health` returns only `HealthStatus` and exposes no way to distinguish cache-hit from live-probe. Adding such a distinction would expand scope by changing the on-demand path's return shape; rejected per §19 D-8.
- Tests (unit + integration where service-container fixtures exist) covering: (a) warmup happy path, (b) warmup skipped when no clusters registered, (c) warmup handles per-cluster exceptions gracefully (continues loop, logs WARN, increments `failures`), (d) shutdown cancels the warmup task cleanly + the DB session is released, (e) backwards-compat: cache-first semantics of `get_or_probe_health` are preserved, (f) AC-10 post-startup cluster registration shows correct lazy-warm behavior, (g) `get_or_probe_health` CredentialsMissing branch now writes cache (regression guard for the §3 in-scope cache-write fix).
- Architecture-doc update — append a short subsection to [`docs/01_architecture/data-model.md`](../../../01_architecture/data-model.md) under "Cluster health caching" describing the startup warmup + the existing lazy-warm path as complementary fillers, and explicitly note that `/healthz` will report `unreachable: N` for the first ~5s post-boot until the warmup completes (the race-window caveat).

### Out of scope

- **Periodic re-warmup cron.** Per §19 D-3, clusters registered post-startup are lazy-warmed by the existing `get_or_probe_health` on-demand path. Operator-acceptable for MVP1 (post-boot cluster registration is rare; the 5-minute lazy-warm window is well-tolerated). A cron warmup is a follow-up if we ever see operator pain.
- **Changing `ClusterAggregateHealth` response shape (Option B from the idea).** Per §19 D-2, adding an `unprobed` field is a breaking change to `/healthz` consumers (smoke gate `_wait_healthy`, dashboard, operator scripts) with marginal benefit once warmup is in place. Rejected.
- **Doc-only Option C** (accepting current behavior with a note). Per §19 D-1, the operator experience is the bug — doc-only doesn't move it.
- **Changing the cache TTL.** Unchanged at 30s per the Decision Log 2026-05-09.
- **Changing `/healthz` in-request behavior.** It stays cache-only (CLAUDE.md Absolute Rule #11). No live probes inside the request budget.
- **Changing `get_or_probe_health`'s public signature or its normal cache-first / live-probe behavior.** The only in-scope semantic change is FR-7 (cache the synthetic `HealthStatus(unreachable)` in the `CredentialsMissing` exception branch before returning); the cache-hit path and successful-probe path are unchanged. Per cycle-3 GPT-5.5 A1 — the out-of-scope bullet previously over-claimed by saying "unchanged" without acknowledging FR-7.
- **Fixing the separate dashboard banner E2E failure** (`dashboard.spec.ts:57` / `dashboard-reseed.spec.ts:95`). Per the idea's "Decoupling from the banner E2E failure" section, that's a different bug with a different root cause (likely globalTeardown cluster-cleanup mid-suite). Tracked separately — a new bug folder should be opened by whoever investigates `ui/tests/e2e/global-teardown.ts:124-150`. Not in scope here.
- **Live-probing inside `/healthz`** to avoid the 5s warmup race window. Would violate Absolute Rule #11.
- **Frontend changes** (UI doesn't render `elasticsearch_clusters` today; that aggregate is operator-curl only).
- **Multi-tenancy.** MVP1 is single-tenant.

### API convention check

- **Endpoint prefix convention:** N/A — no new endpoints. The fix is a startup-task change.
- **Router namespace:** unchanged.
- **HTTP methods:** N/A.
- **Non-auth error envelope shape:** N/A — no new endpoints. The warmup is internal; failures are logged at WARN per the existing `get_or_probe_health` pattern.
- **Auth error shape:** N/A.

### Phase boundaries

Single phase — bounded bug fix. All FRs ship in one PR.

## 4) Product principles and constraints

- **CLAUDE.md Absolute Rule #11:** `/healthz` per-probe timeout = 200ms; total p99 < 500ms. The warmup runs **outside** `/healthz`'s request budget — fire-and-forget at startup via `asyncio.create_task`. Does NOT alter `/healthz`'s in-request behavior.
- **CLAUDE.md Absolute Rule #10:** Never log/expose secrets. The warmup logs cluster IDs + names + counts only — never credentials. The existing `get_or_probe_health` is the boundary that handles credential resolution and never leaks the resolved values.
- **CLAUDE.md Absolute Rule for startup tasks (precedent from PR #4 + FR-7):** Fire-and-forget background tasks at startup MUST NOT crash the API process on failure. Pattern: catch broad `Exception`, log at WARN, swallow. `asyncio.CancelledError` MUST propagate for clean shutdown.
- **Cache-first design:** The warmup populates the same Redis cache that `get_or_probe_health` writes to. No new cache key, no schema change, no migration. Pre-existing cache rows are respected (the warmup uses the existing cache-first logic in `get_or_probe_health:199-201`).
- **Bounded blast radius:** A slow / broken cluster (e.g., a deleted ES container the operator forgot to deregister) cannot delay startup. The warmup runs out-of-band and any single cluster's probe is independently timeboxed by the existing `httpx` per-call timeout on `adapter.health_check()`.

### Anti-patterns

- **Do not** make the warmup task block startup. It MUST be `asyncio.create_task`'d (not awaited synchronously inside the lifespan generator before `yield`). A slow/broken cluster cannot delay API readiness.
- **Do not** parallelize cluster probes with `asyncio.gather`. Per `probe_registered_clusters`'s precedent, sequential paginated walk is fine for MVP1 (~2-10 clusters). Parallel probes would race the engine adapters' shared `httpx.AsyncClient` lifecycle and complicate error reporting without solving a real performance problem.
- **Do not** add a periodic re-warmup cron in this PR (out of scope per §19 D-3).
- **Do not** change `probe_registered_clusters` to live-probe on cache miss (violates Absolute Rule #11).
- **Do not** swallow `asyncio.CancelledError` in the warmup task. It MUST propagate so shutdown is clean.
- **Do not** swallow `CredentialsMissing` at the warmup level — the underlying `get_or_probe_health` already catches it at `cluster.py:202-208` and writes `HealthStatus(status="unreachable", error=...)` to the cache. The warmup's job is to *trigger* that probe path, not duplicate its error handling.
- **Do not** log the resolved adapter credentials in the warmup's summary log. Cluster ID + name + a count are sufficient diagnostics.
- **Do not** widen the `Cluster` ORM model or add a "last warmed" column. The 30s Redis TTL is the source of truth for staleness.

## 5) Assumptions and dependencies

- Dependency: `infra_adapter_elastic` (shipped, PR #16)
  - Why required: provides `get_or_probe_health`, `cluster:health:*` cache, `build_adapter`, and the `Cluster` ORM model with `count_clusters` + `list_clusters`.
  - Status: Implemented.
  - Risk if missing: N/A — already merged.
- Dependency: `infra_foundation` (shipped, PR #4)
  - Why required: provides the lifespan + structlog + `get_settings` infrastructure.
  - Status: Implemented.
- Dependency: Redis (cache subsystem)
  - Why required: the cache the warmup populates.
  - Status: Implemented.
  - Risk if missing: Redis-down at startup — the warmup task logs WARN and swallows; `/healthz` continues to report `unreachable: N` (current behavior). No regression vs. status quo.

## 6) Actors and roles

- Primary actor: Operator running the local stack or production-ish deploy who polls `/healthz` after `make up` / `docker compose restart api`.
- Role model: N/A — single-tenant, no auth surface (MVP1).
- Permission boundaries: N/A.

### Authorization

N/A — single-tenant, no auth surface.

### Audit events

N/A — `audit_log` lands at MVP2. The warmup is read-only (probes + caches; no business-state mutations).

## 7) Functional requirements

### FR-1: Startup warmup of all registered clusters

- Requirement:
  - On API startup, the lifespan hook **MUST** spawn a `run_cluster_health_warmup_background` task via `asyncio.create_task`. The task **MUST NOT** be awaited inside the lifespan generator before `yield` — startup must not block on slow/unreachable cluster probes.
  - The task **MUST** accept `db_factory: async_sessionmaker[AsyncSession]` (resolved from `backend.app.db.session.get_session_factory()`) and `redis_client: Redis`. It **MUST** open a DB session via `async with db_factory() as db:` so the session is released on normal completion AND on `asyncio.CancelledError` during shutdown.
  - The task **MUST** page through all registered clusters in 200-row windows via the existing `repo.list_clusters(db, cursor=..., limit=200)` pagination loop (mirrors `probe_registered_clusters:118-132`).
  - For each cluster row, the task **MUST** call `cluster_svc.get_or_probe_health(redis_client, cluster)` — reusing the existing on-demand path so cache write logic, `CredentialsMissing` handling, and adapter lifecycle stay in ONE place. (Post-FR-7, the on-demand path writes cache for every branch.)
  - The task **MUST** swallow any per-cluster exception (log at WARN with the cluster ID and error message; continue to the next cluster). One broken cluster cannot stop the warmup of the others.
- Notes: This is the central FR. All other FRs support it.

### FR-2: Skip on empty registry

- Requirement:
  - When `repo.count_clusters(db) == 0`, the warmup task **MUST** exit early without paginating. Emit a single INFO log `cluster_health_warmup_skipped` with `count=0`.
- Notes: Mirrors `run_capability_check_background`'s empty-key skip pattern at [`capability_check.py:416-421`](../../../../backend/app/llm/capability_check.py#L416-L421). Common in dev/test environments before any cluster is registered.

### FR-3: Bounded by per-cluster timeout, no global timeout

- Requirement:
  - The warmup **MUST NOT** wrap the per-cluster probe loop in an `asyncio.wait_for(...)` global timeout. Per-cluster latency is bounded by the existing `httpx` per-call timeout inside `adapter.health_check()`. A global timeout would discard partial progress if one cluster is slow.
  - The warmup **MUST NOT** retry failed probes. `get_or_probe_health` already caches the `unreachable` outcome with the 30s TTL — retrying would be duplicate work.

### FR-4: Clean shutdown — DB session released, task cancelled

- Requirement:
  - The lifespan hook **MUST** cancel the warmup task on shutdown if it is still running, following the same pattern as the capability-check task at [`main.py:121-131`](../../../../backend/app/main.py#L121-L131).
  - `asyncio.CancelledError` raised by the warmup task during shutdown **MUST** be silently caught (matching the capability-check shutdown swallow at line 125-126).
  - The warmup function **MUST** open its DB session as a `async with db_factory() as db:` context manager so that the session is automatically released on the path through `CancelledError` propagation (Python's context-manager protocol guarantees `__aexit__` runs on `BaseException`). Cancellation **MUST NOT** leak a held DB connection.
  - Any non-CancelledError exception during shutdown **MUST** be logged at WARN and swallowed (matching capability-check pattern at lines 127-131).

### FR-5: Observability — one summary log on completion

- Requirement:
  - The warmup **MUST** emit exactly one INFO-level structlog event on successful completion (or "completion with per-cluster errors") with the keys: `event` (a stable identifier — `cluster_health_warmup_completed`), `count` (clusters walked), `failures` (count of per-cluster exceptions caught and swallowed), `duration_ms` (wall-clock elapsed).
  - The warmup **MUST NOT** attempt to report `cache_hits` vs `probed` counts. The existing `get_or_probe_health` return signature is `HealthStatus` — it exposes no way to distinguish a cache hit from a fresh probe. Adding such a distinction would change the on-demand path's contract for negligible operator value (rejected per §19 D-8).
  - On startup-skip per FR-2, the task **MUST** emit a single INFO event `cluster_health_warmup_skipped` with `count=0` and no other fields beyond the stable identifier.
  - Per-cluster failures **MUST** be logged at WARN with the cluster ID + cluster name + a short `error` string (no credentials).
- Notes: Operators correlate the warmup-completion timestamp with the first `/healthz` poll that returned truthful counts. This is the diagnostic surface that closes the loop for "why does `/healthz` say `unreachable: N` for ~5s after boot?".

### FR-6: Redis-unavailable graceful degradation

- Requirement:
  - When Redis is unavailable at warmup time, `read_cached_health` and `write_cached_health` both swallow exceptions silently (per [`backend/app/adapters/health_cache.py:38-46` + `:55-58`](../../../../backend/app/adapters/health_cache.py#L38-L58) — this is design intent: cache failure is non-fatal).
  - The warmup **MUST** still attempt all per-cluster probes (so the operator sees the WARN logs from `get_or_probe_health`'s own probe path) but **MUST NOT** assume any cache writes succeeded.
  - The warmup's completion log **MUST** fire normally — `/healthz` will continue to report `unreachable: N` because the cache is empty, but the operator can correlate the completion timestamp with the WARN-log-bearing per-cluster `error=Redis-down` entries (when those exist; today they don't because the cache helpers swallow silently — see open question Q1 below).

### FR-7: Plug the `get_or_probe_health` CredentialsMissing cache-write gap

- Requirement:
  - [`backend/app/services/cluster.py:202-209`](../../../../backend/app/services/cluster.py#L202-L209) **MUST** be modified so the `except CredentialsMissing` branch writes the synthesized `HealthStatus(status="unreachable", ...)` to cache via `write_cached_health(redis, cluster.id, health)` before returning. Today the branch returns without writing; that produces a degenerate state where credentials-missing clusters re-probe (and re-fail) on every call, AND `/healthz` permanently sees them as cache-miss-`unreachable` rather than cached-`unreachable`.
  - The synthesized `HealthStatus.error` field **MUST** continue to include the `CredentialsMissing` exception's message (today: `f"credentials resolution failed: {exc}"`) so operators reading the cached row understand why.
  - The change is **additive** — no existing call site of `get_or_probe_health` depends on the no-cache-write behavior; verified by reading the function's only consumers ([`backend/app/api/v1/clusters.py:182-188`](../../../../backend/app/api/v1/clusters.py#L182-L188) `get_cluster_detail` and `list_clusters` at line 245). Both consumers just read the returned `HealthStatus`.
- Notes: This is in-scope per cycle-1 GPT-5.5 finding A1. Without this fix, the warmup itself is broken for any cluster whose credentials_ref entry is missing from `cluster_credentials.yaml` — the warmup runs to completion but the cache is still empty.

## 8) API and data contract baseline

### 8.1 Endpoint surface

N/A — no new endpoints. No endpoint shapes change.

### 8.2 Contract rules

N/A — no endpoints in scope.

### 8.3 Response examples

The `/healthz` response shape is **unchanged**. The only observable behavior change is that the `elasticsearch_clusters.healthy` / `.unreachable` counts converge to the truthful values within ~5s of startup instead of waiting for the first `/api/v1/clusters` request.

Pre-fix behavior (within 30s of fresh boot, before any `/api/v1/clusters` call):
```json
"subsystems": {
  "elasticsearch_clusters": {"registered": 4, "healthy": 0, "unreachable": 4}
}
```

Post-fix behavior (~5s after a fresh boot, regardless of any prior `/api/v1/clusters` call):
```json
"subsystems": {
  "elasticsearch_clusters": {"registered": 4, "healthy": 4, "unreachable": 0}
}
```

### 8.4 Enumerated value contracts

No new enumerated values. The existing `HealthStatus.status` `Literal["green","yellow","red","unreachable"]` (at [`backend/app/adapters/protocol.py`](../../../../backend/app/adapters/protocol.py)) is unchanged. The aggregator's existing in/out mapping at `probes.py:124-126` is unchanged (counts "red" + "unreachable" as `unreachable`; cache-miss still counts as `unreachable` — but the cache is no longer empty for long enough to matter).

### 8.5 Error code catalog

N/A — no new error codes.

## 9) Data model and state transitions

### New/changed entities

**No schema change.** No new tables, no new columns, no new indices.

**Modified Pydantic models:** none.

**Redis cache key:** `cluster:health:{cluster_id}` (existing — unchanged). 30s TTL (unchanged).

### Required invariants

- The warmup **MUST** call `get_or_probe_health` (cache-first), NOT a direct `adapter.health_check()` — preserving the invariant that the cache is the source of truth for health-aggregate reads.
- The warmup task **MUST** complete (or be cancelled) before the lifespan generator returns. Otherwise dangling task warnings leak from asyncio on shutdown.

### State transitions

N/A — no state machine.

### Idempotency/replay behavior

The warmup is idempotent. Running it twice within the 30s TTL is a no-op (cache hits → no probes). Running it after the TTL expires re-probes. This is the same idempotency that the existing on-demand path has.

## 10) Security, privacy, and compliance

- **Threat 1:** A slow/unreachable cluster delays API startup. **Control:** The warmup task is `asyncio.create_task`'d, not awaited synchronously. Lifespan generator yields immediately. Bounded by per-cluster `httpx` timeout (the same one `get_or_probe_health` already uses).
- **Threat 2:** A broken cluster crashes the API process. **Control:** The warmup catches `Exception` at the per-cluster boundary AND at the task boundary (`run_cluster_health_warmup_background` wraps everything in try/except, mirrors `run_capability_check_background:422-431`).
- **Threat 3:** Credentials or response-body content leaks into log lines. **Control:** The warmup logs cluster ID, name, and counts only. Credential resolution stays inside `get_or_probe_health` and never crosses the warmup boundary. Adapter response bodies are never captured.
- **Secrets/key handling:** Unchanged — credentials live in mounted `*_FILE` secrets per CLAUDE.md Absolute Rule #2.
- **Auditability:** N/A — pre-MVP2.
- **Data retention:** The 30s Redis cache TTL is unchanged. The warmup writes to the existing cache.

## 11) UX flows and edge cases

### Information architecture

N/A — no UI.

### Tooltips and contextual help

N/A — no UI.

### Primary flows

1. **Operator polls `/healthz` 6 seconds after `make up`.**
   - At T=0 the API process starts. Lifespan spawns the warmup task.
   - At T=~3-5 seconds, the warmup completes (typical for 2-10 demo clusters against the local Compose engines).
   - At T=6, the operator's `curl /healthz` returns `elasticsearch_clusters: {registered: 4, healthy: 4, unreachable: 0}`. Diagnostic: "demo stack is fully healthy."
2. **CI smoke gate polls `/healthz` after `make seed-demo`.**
   - After `make seed-demo FORCE=1` completes, the api container has been running for ~30s.
   - The first `/healthz` poll returns truthful counts (the warmup completed long ago).
   - The smoke-logs.txt artifact captured at [`pr.yml:444-445`](../../../../.github/workflows/pr.yml#L444-L445) shows the correct aggregate.
3. **Operator registers a NEW cluster post-boot via `POST /api/v1/clusters`.**
   - `register_cluster` at [`backend/app/services/cluster.py:83-188`](../../../../backend/app/services/cluster.py#L83-L188) calls `adapter.health_check()` (line 147) AND `write_cached_health(redis, cluster.id, health)` (line 188) BEFORE returning the new cluster to the API caller.
   - So the cache row is populated IMMEDIATELY at registration time. `/healthz` reflects the new cluster's true health on the next poll.
   - **No "lazy-warm gap" for the normal POST path.** The gap from §19 D-3 applies only to (a) clusters whose cache row expired after 30s of no requests on a long-idle instance, and (b) direct out-of-band DB inserts that bypass `POST /api/v1/clusters` (e.g., a custom seed script that uses the ORM directly).

### Edge/error flows

- **Redis-down at startup:** Per D-9, the warmup pings Redis once at the top of `run_cluster_health_warmup_background` and emits WARN `cluster_health_warmup_redis_unavailable` with `error=str(exc)` on failure. The warmup then proceeds to per-cluster probes (so per-cluster `adapter.health_check()` results still appear in logs even though the cache helpers can't write). Cache helpers themselves remain silent on failure ([`health_cache.py:38-46` + `:55-58`](../../../../backend/app/adapters/health_cache.py#L38-L58) — that's design intent unchanged in this spec). The completion log fires normally with `failures=0` unless a per-cluster probe itself raised. `/healthz` continues to report cache-miss-equals-`unreachable` for all clusters because the writes silently fail. Operator sees `subsystems.redis: "down"` AND the explicit `cluster_health_warmup_redis_unavailable` WARN, which together tell the full story.
- **Postgres-down at startup:** `repo.count_clusters` raises. The warmup task catches the exception at its outer boundary, logs WARN, swallows. No regression.
- **One cluster has bad credentials:** `get_or_probe_health` catches `CredentialsMissing`, writes `HealthStatus(status="unreachable", error=...)` to cache. Warmup loop continues. `/healthz` reports the failing cluster as `unreachable` correctly; the other 3 demos show `healthy`.
- **All 4 clusters are broken:** Same as above × 4. `/healthz` correctly reports `healthy: 0, unreachable: 4`. The "false alarm" the fix targets is gone (the counts are now truthful, not a cache-miss artifact).
- **Cluster row count is 0 (fresh dev install pre-seed):** FR-2 skip — single INFO log, no probes attempted.
- **API container restart while a warmup is in progress:** Lifespan-cancel cancels the task per FR-4. Partial cache populated; next request lazy-warms the remainder.

## 12) Given/When/Then acceptance criteria

### AC-1: Warmup is spawned at startup

- **Given** the API process starts via the FastAPI lifespan hook,
- **When** the hook reaches the point where the capability-check task is spawned,
- **Then** a second `asyncio.create_task` is scheduled for the cluster-health warmup. Both tasks run concurrently; neither blocks the `yield` in the lifespan generator.
- **Example values:**
  - Verified by: a unit test that monkeypatches `asyncio.create_task` to count invocations during the lifespan hook + asserts the count incremented for both tasks.

### AC-2: Warmup walks all registered clusters

- **Given** 4 demo clusters are registered in the DB,
- **When** the warmup task runs to completion,
- **Then** `get_or_probe_health` is called once per cluster (4 invocations); each call writes a fresh `HealthStatus` to `cluster:health:{cluster_id}`.

### AC-3: Cache hits short-circuit (idempotency — at the `get_or_probe_health` layer, not the warmup layer)

- **Given** a `cluster:health:{cluster_id}` cache row already exists for cluster X (within the 30s TTL),
- **When** the warmup task encounters cluster X,
- **Then** `get_or_probe_health` returns the cached value without re-probing (no `build_adapter` call, no `health_check()` call); the warmup proceeds to the next cluster without crashing or duplicating work.
- **Note (per cycle-1 A2 + D-8):** the warmup does NOT track or report `cache_hits` vs `probed` counts — `get_or_probe_health: HealthStatus` exposes no source-of-value distinction. The cache-first behavior is unit-tested separately by preloading Redis and asserting `build_adapter` is not invoked.

### AC-4: Empty registry skips paginated walk

- **Given** no clusters are registered (`count_clusters(db) == 0`),
- **When** the warmup task runs,
- **Then** the task emits a single `cluster_health_warmup_skipped` INFO log with `count=0` and exits without paginating; `repo.list_clusters` is NOT called.

### AC-5: Per-cluster exceptions don't abort the loop

- **Given** clusters A, B, C are registered; `get_or_probe_health(A)` raises an unexpected exception (e.g., a transient DB error mid-probe),
- **When** the warmup task runs,
- **Then** the exception is caught at the per-cluster boundary, a WARN log fires with the cluster ID, and the loop continues to B and C. The completion log shows `failures=1, count=3`.

### AC-6: Task task-level exception swallowed; API doesn't crash

- **Given** the warmup task encounters a top-level exception (e.g., `repo.list_clusters` raises a connection error during pagination cursor recovery),
- **When** the task is running,
- **Then** the task's outer `try/except` (per the `run_capability_check_background` template) catches the exception, logs at WARN, and the task exits cleanly. The API process keeps serving requests — no traceback leaks to stderr.

### AC-7: Shutdown cancels in-flight warmup cleanly

- **Given** the warmup task is mid-loop (e.g., probing cluster #50 of 200) when the lifespan generator's `finally` block runs,
- **When** lifespan cancellation runs,
- **Then** `task.cancel()` fires; the task raises `asyncio.CancelledError`; the lifespan `await task` suppresses the CancelledError per the precedent at `main.py:125-126`. No `RuntimeWarning: coroutine was never awaited` leaks to logs.

### AC-8: `/healthz` reports truthful counts after warmup-completion log

- **Given** a freshly booted API with N healthy clusters registered AND the `cluster:health:*` Redis keys explicitly deleted before the API process starts (so the cache is genuinely cold, not warm from a prior boot within the 30s TTL),
- **When** the operator polls `/healthz` after observing the `cluster_health_warmup_completed` INFO log,
- **Then** `subsystems.elasticsearch_clusters.healthy == N` and `.unreachable == 0`.
- **Example values (integration test — service-container-skipped outside CI):**
  - Setup:
    1. Seed 2 clusters in the test DB via the existing `seed_clusters` fixture.
    2. `await redis.delete(*cache_keys)` — explicit cold cache (per cycle-1 B2 — a `docker compose restart` does NOT clear Redis; the cache is shared across container lifetimes within its 30s TTL window).
    3. Trigger the lifespan-equivalent: spawn `run_cluster_health_warmup_background(session_factory, redis)` directly.
    4. Wait for a **deterministic signal**: poll for the `cluster_health_warmup_completed` log event via structlog test-capture (or for the expected `cluster:health:*` keys to land in Redis). Time-based `asyncio.sleep(6)` is forbidden — flaky.
  - Assert: `curl /healthz | jq '.subsystems.elasticsearch_clusters'` returns `{"registered": 2, "healthy": 2, "unreachable": 0}`.

### AC-9: Backwards-compat — `/api/v1/clusters` response contract unchanged

- **Given** the new warmup is in place,
- **When** an `/api/v1/clusters` request runs,
- **Then** the response shape is identical (`ClusterSummary` schema, `health_check` field, cache-first cache semantics). **Note for test authors:** post-fix, the FIRST `/api/v1/clusters` request after startup may now find a warm cache entry (populated by the lifespan warmup) instead of triggering a live adapter probe. Tests that mock `adapter.health_check()` and assert "first list call → exactly N probe invocations" must either pre-flush `cluster:health:*` keys OR not depend on warmup-disabled timing. The response contract is unchanged — only the source of the first response's cached health may differ.

### AC-10: Cluster inserted out-of-band remains unreachable until lazy-warmed (per §19 D-3)

- **Given** the warmup completes; then a cluster row is inserted **directly via the ORM / a seed script** that bypasses `POST /api/v1/clusters` (which would otherwise probe + cache at registration time per [`cluster.py:147+188`](../../../../backend/app/services/cluster.py#L147-L188)),
- **When** the operator polls `/healthz` immediately,
- **Then** the out-of-band cluster shows as `unreachable` (cache miss — no registration probe ran for it). The first `GET /api/v1/clusters` warms it via the lazy path; subsequent `/healthz` polls show it as `healthy`. **This is the documented out-of-band-insert trade-off per §19 D-3 — not a bug.** Normal POST-created clusters do NOT exhibit this gap.
- **Test coverage (per cycle-1 B5 + cycle-2 B1):** integration test asserts the chain: (1) trigger warmup → (2) `/healthz` shows accurate counts → (3) insert a new cluster row via direct `repo.create_cluster` ORM call (NOT `POST /api/v1/clusters` — that would cache at registration and defeat the test) → (4) `/healthz` shows `unreachable` count incremented by 1 → (5) issue `GET /api/v1/clusters` to warm via lazy path → (6) `/healthz` now shows the new cluster as `healthy`.

### AC-11: `get_or_probe_health` CredentialsMissing branch writes cache (regression guard for FR-7)

- **Given** a cluster registered with `credentials_ref="missing-ref-xyz"` (no matching entry in `cluster_credentials.yaml`),
- **When** `get_or_probe_health(redis, cluster)` is called for the first time (cache miss),
- **Then** the function returns `HealthStatus(status="unreachable", error="credentials resolution failed: ...")` AND that `HealthStatus` is written to Redis at `cluster:health:{cluster_id}` with the 30s TTL. A second immediate call returns the cached value (verified by mock-redis `.set.call_count == 1` AND `.get.call_count == 2` AND `build_adapter` only invoked once).
- **Example values:**
  - Setup: monkeypatch `build_adapter` to raise `CredentialsMissing("entry not found: missing-ref-xyz")`.
  - First call: assert returned `HealthStatus.status == "unreachable"`, `.error` contains `"missing-ref-xyz"`, AND `redis.set.call_args.args[0] == cache_key(cluster.id)`.
  - Second call: assert `build_adapter` is NOT invoked again (cached value returned).

## 13) Non-functional requirements

- **Performance:**
  - Zero impact on `/healthz` per-request latency (200ms budget unchanged; warmup runs out-of-band).
  - Startup latency: the lifespan `yield` is reached in ≤100ms additional time after spawning the warmup task (just the `asyncio.create_task` overhead — sub-millisecond in practice).
  - Warmup walltime: 2-10 clusters × per-probe httpx round-trip (typical 50-500ms) = 0.1-5s in practice. The MVP1 production install will rarely exceed 10 clusters.
  - For deployments with hundreds of clusters: the warmup's serial loop walks ~1ms-of-CPU per cluster × N. Doesn't scale arbitrarily but is bounded; future optimization is a separate concern.
- **Reliability:**
  - The warmup CANNOT crash the API process (verified by AC-6).
  - The warmup CANNOT delay the lifespan `yield` (verified by AC-1).
  - A single broken cluster cannot abort the warmup for healthy peers (verified by AC-5).
- **Operability:**
  - One INFO summary log per warmup completion — operators correlate timestamps for first-truthful-`/healthz` reading.
  - No new env vars, no new mounted secrets, no new Compose services.
- **Accessibility/usability:** N/A.

## 14) Test strategy requirements (spec-level)

Minimum required coverage by layer:

- **Unit tests** for the warmup function ([`backend/tests/unit/services/test_cluster_health_warmup.py`](../../../../backend/tests/unit/services/test_cluster_health_warmup.py) — new file):
  - AC-2: walks all clusters, calls `get_or_probe_health` once per row (mock `get_or_probe_health` to record calls)
  - AC-3: cache hits short-circuit at the `get_or_probe_health` layer — the warmup makes the call regardless; the count of probes vs cache hits is NOT tracked by FR-5 (per cycle-1 A2 — the warmup is layer-agnostic). Test asserts the warmup completes without crash when `get_or_probe_health` returns cached values.
  - AC-4: empty registry — `count_clusters → 0` → skip with INFO log; `list_clusters` MUST NOT be called
  - AC-5: per-cluster exception caught, loop continues; WARN log includes cluster ID; completion log shows `failures > 0`
  - AC-6: top-level exception caught — `list_clusters` raises → task exits cleanly without leaking traceback
  - FR-5: completion-log shape — assert structured-log event includes `event`, `count`, `failures`, `duration_ms`
- **Unit tests for lifespan wiring + shutdown cancellation** ([`backend/tests/unit/test_main_lifespan.py`](../../../../backend/tests/unit/test_main_lifespan.py) — create file if absent; per cycle-1 B6 these tests belong in main-lifespan-scoped test file, NOT in the service-module test file):
  - AC-1: lifespan spawns BOTH the capability-check task AND the warmup task via `asyncio.create_task`
  - AC-7: lifespan shutdown cancels the warmup task; warmup function's `async with db_factory() as db:` releases the session on `CancelledError` (verified by mock `db_factory` whose `__aexit__` records invocation)
  - FR-4: capability-check task continues to be cancelled (no regression)
- **Unit tests for FR-7 cache-write fix** ([`backend/tests/unit/test_cluster_service.py`](../../../../backend/tests/unit/test_cluster_service.py) — add to existing file or create — verify in Pass 1 grep):
  - AC-11: `get_or_probe_health` with mocked `build_adapter` raising `CredentialsMissing` now writes the synthesized `HealthStatus` to cache; second call returns cached value
- **Integration tests** ([`backend/tests/integration/test_cluster_health_warmup.py`](../../../../backend/tests/integration/test_cluster_health_warmup.py) — new file, marked `@pytest.mark.integration`):
  - AC-8: end-to-end happy path — seed 2 clusters in test DB, explicit `redis.delete` of expected cache keys, spawn the warmup, wait for the `cluster_health_warmup_completed` log event (deterministic signal — no `asyncio.sleep`), verify `cluster:health:*` keys exist for both with the cached `HealthStatus`. Service-container-skipped outside CI per the existing `pytest.skip` precedent.
  - AC-9: backwards-compat — exercise `/api/v1/clusters` after warmup; verify response contract unchanged (no assertion on probe count — that's a known timing-source change per cycle-1 B7).
  - AC-10: post-startup new-cluster lazy-warm chain (the 6-step sequence in AC-10's test coverage block).
- **Contract tests:** N/A — no API surface change.
- **E2E tests:** N/A — no UI change.

### Test infrastructure prerequisites

- The new `backend/tests/unit/services/` directory likely doesn't exist (verify in Pass 1). The test file lands at that path, creating the directory.
- The new integration-test file follows the existing `@pytest.mark.integration` + service-container-skip pattern from `backend/tests/integration/test_clusters_api.py` (or sibling). No new pytest plugins / no new fixtures / no new conftest changes required.

## 15) Documentation update requirements

- `docs/01_architecture/data-model.md`: append a short paragraph to the "Cluster health caching" section (or create it adjacent to existing prose) covering: (a) the 30s `cluster:health:*` TTL; (b) the two cache-population paths (startup warmup + lazy on-demand from `GET /api/v1/clusters`); (c) the implication that `/healthz` reports `unreachable: N` for ~5s after boot until the warmup completes.
- `state.md`: post-merge entry in "Most recent meaningful changes" (handled by `impl-execute` finalization).
- `CLAUDE.md`: no convention or rule changes.

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** None. Single-PR ship. The change is purely additive (a new background task) — existing consumers see no shape change.
- **Migration/backfill expectations:** None for Postgres. The Redis cache rows are not "migrated"; the warmup just populates them earlier.
- **Operational readiness gates:**
  - `make lint` + `make typecheck` clean.
  - `make test-unit` + `make test-integration` clean.
  - 80% coverage gate maintained.
  - GPT-5.5 cross-model review passes.
- **Release gate:** CI green on the feature branch (in-scope jobs) + Gemini Code Assist findings adjudicated. **The smoke gate is expected to remain red on the dashboard banner test until the separate bug is fixed.** Per the §3 out-of-scope decision, smoke-failure on the banner is acceptable for this PR (admin-merge precedent set by PR #232 / PR #234).

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 (warmup spawned at startup) | AC-1, AC-2 | Add `run_cluster_health_warmup_background` + lifespan wiring | `backend/tests/unit/services/test_cluster_health_warmup.py` (warmup logic) + `backend/tests/unit/test_main_lifespan.py` (lifespan wiring) + integration | `docs/01_architecture/data-model.md` |
| FR-2 (skip empty registry) | AC-4 | Empty-registry early-exit branch | unit test | (same) |
| FR-3 (per-cluster timeout, no global) | AC-5 | Per-cluster try/except in loop | unit test | (same) |
| FR-4 (clean shutdown — task cancel + DB session release) | AC-7 | Lifespan-cancel task on shutdown + `async with db_factory()` releases on cancellation | lifespan test (cancel/await ordering) + service-level mid-loop cancellation test (DB session `__aexit__` invoked) | (same) |
| FR-5 (one summary log) | (asserted across AC-2/3/4/5) | Structured summary log emission | unit test | (same) |
| FR-6 (Redis-unavailable degradation) | (asserted at unit + integration) | Single ping-then-WARN at warmup start; warmup proceeds | `test_cluster_health_warmup.py` (Redis ping fail case) | (same) |
| FR-7 (CredentialsMissing cache-write fix) | AC-11 | Modify `cluster.py:202-209` to `write_cached_health` before return | `backend/tests/unit/test_cluster_service.py` (or `test_cluster.py`) | (same) |

## 18) Definition of feature done

- [ ] All acceptance criteria (AC-1 through AC-11) pass in CI.
- [ ] `make test-unit` + `make test-integration` + `make lint` + `make typecheck` are green on the feature branch.
- [ ] 80% coverage gate is maintained.
- [ ] `docs/01_architecture/data-model.md` updated per §15.
- [ ] GPT-5.5 cross-model review of the PR diff has no unresolved High findings.
- [ ] Gemini Code Assist line-level findings (if any) are adjudicated.
- [ ] On a deliberately-broken-cluster local repro, the warmup logs WARN, the API process keeps serving, and `/healthz` reports the broken cluster as `unreachable` correctly within ~5s of boot.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

None remaining — Q1 (Redis-ping-WARN) locked as D-9 below.

### Decision log

- **2026-05-24 (D-1) — Fix-path choice: Option A (startup warmup).** Per idea preflight recommended default. Picked over Option B (response-shape change) because B is breaking (existing `/healthz` consumers — smoke gate `_wait_healthy`, dashboard, operator scripts — would need to relearn the `unprobed` field). Picked over Option C (docs-only) because the operator experience IS the bug. Rationale: Option A mirrors the existing `run_capability_check_background` pattern shipped in PR #4 + reused in PR #234 — minimal scope, zero new conventions. Sourced from idea.md "Suggested fix paths" + Open Questions Q1. Affects FR-1, §3 in-scope.
- **2026-05-24 (D-2) — No `ClusterAggregateHealth` shape change (Option B rejected).** Adding an `unprobed` field would be a breaking change to `/healthz` consumers (smoke gate `_wait_healthy`, dashboard, operator scripts). Once the warmup completes within ~5s of boot, the false-alarm "unreachable" count is gone, so `unprobed` would mostly be `0` in steady state — marginal value. Rejected. Affects §3 out-of-scope.
- **2026-05-24 (D-3) — No periodic re-warmup cron.** Clusters inserted out-of-band (direct ORM / seed-script — NOT `POST /api/v1/clusters`, which probes + caches at registration time per [`cluster.py:147+188`](../../../../backend/app/services/cluster.py#L147-L188)) are lazy-warmed by the existing `get_or_probe_health` on-demand path. Cache TTL expiry on a long-idle instance is the other case (30s window between requests). Operator-acceptable for MVP1 — out-of-band inserts are dev-time, and idle 30s gaps don't matter to operators not polling. A cron warmup adds an Arq job, a new env var, and a new failure mode for negligible benefit. Rejected. Affects FR-1, §3 out-of-scope, AC-10. **Clarification per cycle-2 B1:** AC-10's test path uses direct ORM insert (NOT `POST`) — the normal POST registration path closes the gap at registration time.
- **2026-05-24 (D-4) — Sequential loop, not `asyncio.gather`.** The warmup walks clusters serially in 200-row paginated windows. Parallel probing would complicate shared httpx-client lifecycle and error reporting, and the latency budget for the warmup is the lifespan task's wall-clock time — not the operator's request time. MVP1 holds 2-10 clusters; serial is fine. Sourced from §4 anti-patterns.
- **2026-05-24 (D-5) — Reuse `get_or_probe_health`, do NOT bypass to direct `adapter.health_check()`.** The warmup is just an upstream trigger of the same cache-population path. Reusing keeps cache write + credential resolution + `CredentialsMissing` handling in ONE place. Affects FR-1, §9 invariants.
- **2026-05-24 (D-6) — Banner E2E failure is a separate bug, NOT in scope.** Per the idea's "Decoupling from the banner E2E failure" section, `dashboard.spec.ts` failure is unrelated to this `/healthz` aggregate bug. The banner reads `GET /api/v1/clusters` (which returns ALL clusters regardless of health); it doesn't depend on `/healthz`. Likely root cause: globalTeardown cluster-cleanup mid-suite at [`ui/tests/e2e/global-teardown.ts:124-150`](../../../../ui/tests/e2e/global-teardown.ts#L124-L150). Tracked as a separate future bug folder. Affects §3 out-of-scope; smoke gate red is expected post-merge.
- **2026-05-24 (D-7) — Plug the CredentialsMissing cache-write gap in scope.** Cycle-1 GPT-5.5 A1 caught that [`cluster.py:202-209`](../../../../backend/app/services/cluster.py#L202-L209) returns a synthetic `HealthStatus` for `CredentialsMissing` WITHOUT writing it to cache. Left as-is, the warmup would re-probe (and re-fail) every credentials-missing cluster on every call, AND `/healthz` would forever see them as cache-miss-`unreachable`. FR-7 brings the cache-write into the branch so every `get_or_probe_health` return populates the cache. Affects §2 current-state-audit, §3 in-scope, FR-7, AC-11, §14 unit tests.
- **2026-05-24 (D-8) — Drop `cache_hits` / `probed` counters from FR-5.** Cycle-1 GPT-5.5 A2 caught that `get_or_probe_health: HealthStatus` exposes no way to distinguish cache-hit from live-probe. Adding such a distinction would change the on-demand path's return shape for marginal observability value (`count` + `failures` + `duration_ms` are sufficient — operators correlate the completion timestamp with their first `/healthz` reading). Affects FR-5, AC-3.
- **2026-05-24 (D-9) — Add a Redis-ping-then-WARN at warmup start (Q1 locked).** The warmup function MUST `await redis_client.ping()` once before any probing. On failure, emit WARN `cluster_health_warmup_redis_unavailable` with `error=str(exc)` and continue to per-cluster probes (so per-cluster `health_check` WARN logs still inform the operator). This closes the Redis-down observability gap: the existing cache helpers swallow Redis errors silently per [`health_cache.py:38-58`](../../../../backend/app/adapters/health_cache.py#L38-L58), so without this ping the operator gets zero signal that the cache is unwritable. Affects FR-6, §14 unit tests, §11 edge-flow.
- **2026-05-24 (D-10) — Split shutdown tests across two test files.** Per cycle-2 B4: `test_main_lifespan.py` verifies lifespan-level create/cancel/await/swallow ordering (warmup function can be a no-op fixture). `test_cluster_health_warmup.py` verifies that the warmup function itself releases its DB session on `CancelledError` propagation (uses a fake `async_sessionmaker[AsyncSession]` whose `__aexit__` records invocation; the test mocks `get_or_probe_health` as a blocking coroutine, cancels the task, and asserts the `__aexit__` ran). Splitting prevents the lifespan test from monkeypatching the warmup function into a no-op (which would never enter the DB session context). Affects §14 test plan.
