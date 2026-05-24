# Feature Specification — Home demo-data reseed endpoint + UI

**Date:** 2026-05-23
**Status:** Approved
**Owners:** Product: relevance-engineer onboarding · Engineering: backend (`backend/app/services/demo_seeding.py`, `backend/app/api/v1/_test.py`) + frontend (`ui/src/components/dashboard/start-here-checklist.tsx`)
**Related docs:**
- [`idea.md`](idea.md) — origin brief with locked decisions D1/D2/D3 and open questions Q1/Q2/Q3
- [`docs/00_overview/implemented_features/2026_05_22_feat_home_first_run_demo_nudge/feature_spec.md`](../../../00_overview/implemented_features/2026_05_22_feat_home_first_run_demo_nudge/feature_spec.md) — Phase 1 parent (merged PR #188)
- [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md) — error-envelope contract
- [`docs/01_architecture/data-model.md`](../../../01_architecture/data-model.md) — MVP2 `audit_log` location for the deferred audit hook

---

## 1) Purpose

- **Problem:** After Phase 1 of `feat_home_first_run_demo_nudge` shipped the demo-data banner + cluster indicator, dev-stack operators who wipe their state still must drop back to the host shell and run `make seed-demo FORCE=1` to recover a populated demo dashboard. There is no in-UI "Reset to demo state" affordance, and the seed script's `docker compose exec postgres psql ...` path ([`scripts/seed_meaningful_demos.py:702-721`](../../../../scripts/seed_meaningful_demos.py)) cannot run from inside the API container (no docker socket, no psql client).
- **Outcome:** A dev-only `POST /api/v1/_test/demo/reseed` endpoint plus a "Reset to demo state" button inside `StartHereChecklist` that lets an operator wipe + re-seed the 4 demo scenarios from the browser. On success the dashboard refetches and shows 4 clusters / 4 query sets / 4 completed studies / 4 pending proposals. The CLI script remains the authoritative path; the new endpoint is purely additive.
- **Non-goal:** Replace the CLI seed script. Replace `make seed-demo FORCE=1`. Expose a reseed surface outside `ENVIRONMENT=development`. Refactor `seed_meaningful_demos.py`'s scenario body. Add an audit-log emission today (deferred to MVP2 — see §6 Audit events).

## 2) Current state audit

### Existing implementations

- **`scripts/seed_meaningful_demos.py`** ([file](../../../../scripts/seed_meaningful_demos.py), 932 LOC): the canonical seeder. Truncates 10 Postgres tables via `docker compose exec` (`_psql`, line 702), deletes 3 ES indices + 1 OS index (`truncate_demo_state`, lines 724-749), then loops 4 scenario dicts via `seed_scenario` (line 579) using `urllib.request` HTTP calls. `confirm_wipe()` (line 765) is the canonical destructive-action prompt this feature's UI dialog must mirror.
- **`backend/app/api/v1/_test.py`** ([file](../../../../backend/app/api/v1/_test.py), 426 LOC): the dev-gated test surface. Hosts 1 POST (`/_test/studies/seed-completed`, line 127) + 6 DELETEs (lines 193, 213, 233, 277, 316, 366). All endpoints guarded by `_require_development_env` dependency (line 56). Canonical error helper `_err(status_code, code, message, retryable)` at line 40. **The new `/_test/demo/reseed` endpoint MUST live in this module so the env-guard pattern stays uniform.**
- **`backend/app/services/test_seeding.py`** ([file](../../../../backend/app/services/test_seeding.py), 198 LOC): the only existing test-only service module. Pattern to mirror: dataclass result, `db: AsyncSession` first arg, caller commits. **The new `demo_seeding.py` MUST follow this pattern** (no `pragma: no cover` though — the new module has explicit integration test coverage).
- **`backend/workers/digest.py:220-244` + `backend/workers/orchestrator.py:471-489`**: the only existing `pg_try_advisory_xact_lock` users. Both key the lock via `blake2b(f"<prefix>:{id}", digest_size=8).digest()` cast to a signed 64-bit int. **The new reseed endpoint MUST follow this exact pattern** (key: `blake2b(b"demo:reseed", digest_size=8)` — there's only one demo dataset, so no per-id suffix needed).
- **`ui/src/components/dashboard/start-here-checklist.tsx`** ([file](../../../../ui/src/components/dashboard/start-here-checklist.tsx), 152 LOC): the empty-state surface. Renders `null` when `hasClusters && hasQuerySetsWithJudgments && hasStudies` (line 51). Receives props from `ui/src/app/page.tsx:104-109`. **The new "Reset to demo state" button MUST live inside this component**, conditionally rendered when all three props are `false` (a truly empty stack) so partial-state operators don't see an option that wipes their in-progress work.
- **`ui/src/app/page.tsx`** ([file](../../../../ui/src/app/page.tsx)): owns the `clustersCount` + `judgmentListsCount` + `recent` queries. Already wired for the empty-state signal — no new query is needed; the button piggybacks on the existing TanStack Query keys.
- **`backend/app/llm/capability_check.py:303`**: the existing `httpx.AsyncClient(timeout=...)` self-call pattern. The reseed service follows the same shape (`async with httpx.AsyncClient(base_url=..., timeout=...) as client`).

### Navigation and link impact

| Source file | Current link target | New link target |
|---|---|---|
| N/A | N/A | N/A — feature adds a button on an existing page (`/`); no URL changes, no redirects, no renamed routes. |

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `backend/tests/contract/test_test_endpoint_guard.py` | `/_test/studies/seed-completed` env-guard parametrized assertion | 1 | Extend the parametrized list to also exercise `/_test/demo/reseed` (the env-guard behavior MUST be identical). |
| `backend/tests/contract/test_openapi_surface.py:96-97` | OpenAPI-surface registry of test-only endpoints | 1 | Add `("post", "/api/v1/_test/demo/reseed", "200")` so the contract suite enforces the endpoint stays registered. |
| `ui/src/__tests__/components/dashboard/start-here-checklist.spec.tsx` | Component-render assertions | TBD | Add coverage for the new "Reset to demo state" button (visible when all three props false; hidden otherwise; confirmation dialog open/close). |

### Existing behaviors affected by scope change

- **`StartHereChecklist` empty-state real estate.** Current: 3-step onboarding list, no secondary action. New: same 3-step list PLUS a secondary "or skip ahead — reset to demo state" disclosure (`<details>` element) shown only when all three step props are `false` (a truly empty stack). **Decision needed:** no — the recommended default from idea Q2 is adopted (see §19 Decision log).
- **`docker compose exec postgres psql` privileged path.** Current: CLI script needs the host shell. New: API container also gains a SQL-via-SQLAlchemy reseed path. **Decision needed:** no — the CLI remains unchanged (idea Decision D2 locked).

---

## 3) Scope

### In scope

- **A. New service module** `backend/app/services/demo_seeding.py` (~200 LOC):
  - `async def reseed_demo_state(db: AsyncSession, api_client: httpx.AsyncClient, engine_client: httpx.AsyncClient) -> ReseedSummary`
  - **Two `httpx.AsyncClient` instances are required** — one for RelyLoop FastAPI loopback (base URL `http://localhost:8000` per FR-1c; auth: none in MVP1 single-tenant) and one for ES/OS engine direct calls (no base URL — uses per-scenario per-request URLs from `SCENARIOS`, **transformed by the in-container host resolver described below**; per-scenario `host_auth` is passed via the `auth=` kwarg on each call). The orchestrator constructs both at the start of the call and closes them in a `try/finally` block.
  - **In-container host resolution (FR-1d).** The imported `SCENARIOS` dicts carry `host_base_url` values from the CLI's host-shell perspective: `http://localhost:9200` (ES) and `http://localhost:9201` (OS), defined at `scripts/seed_meaningful_demos.py:60-62`. These are NOT directly usable from inside the API container (where `localhost` resolves to the API container itself, not the host's port-published ES/OS). The service module MUST apply a **runtime-side resolver** `_resolve_engine_base_url(host_base_url: str) -> str` defined inside `backend/app/services/demo_seeding.py` that transforms `http://localhost:9200` → `http://elasticsearch:9200` and `http://localhost:9201` → `http://opensearch:9201` (the Compose DNS names). The resolver is a pure function (no I/O, deterministic) so it's unit-testable. The CLI itself does not touch this resolver — locked decision D2 (CLI unchanged) is preserved. The resolver MUST raise `ValueError` on any other URL pattern (defense against the CLI adding a new engine port that the resolver hasn't been updated to handle).
  - Step 1a — `db.execute(text("TRUNCATE proposals, digests, trials, studies, judgments, judgment_lists, queries, query_sets, query_templates, clusters RESTART IDENTITY CASCADE"))` (exact 10-table list mirroring [`scripts/seed_meaningful_demos.py:67-78`](../../../../scripts/seed_meaningful_demos.py)), then `db.commit()` (the TRUNCATE-before-self-call invariant per FR-1).
  - Step 1b — Via `engine_client`, DELETE the 3 ES indices in `DEMO_ES_INDICES` (basic auth `("elastic", "changeme")`) against `_resolve_engine_base_url(ES)` (= `http://elasticsearch:9200`), and DELETE the 1 OS index in `DEMO_OS_INDICES` (basic auth `("admin", "admin")`) against `_resolve_engine_base_url(OS)` (= `http://opensearch:9201`). Tolerate 404 (no-op on a brand-new stack). Each request uses the absolute URL form `{resolved_base_url}/{idx}` — do NOT rely on a client-level base URL since ES and OS hostnames differ.
  - Step 2 — Loop the 4 scenarios via the appropriate client. The scenario list MUST be imported from `scripts/seed_meaningful_demos.py` (`SCENARIOS` constant — a list of plain dicts, no executable code) to keep the data source single. The per-scenario flow makes EXACTLY the same calls the CLI's `seed_scenario` (lines 579-694) does, with the same client mapping:
    - **`engine_client` (ES/OS direct, absolute URLs constructed via `_resolve_engine_base_url(scenario.host_base_url)`, per-scenario basic auth):** `PUT {resolved}/{target}` (index mapping), `PUT {resolved}/{target}/_doc/{id}` (each doc), `POST {resolved}/{target}/_refresh`. The resolver translates the CLI's `localhost:9200/9201` URLs to the in-container `elasticsearch:9200` / `opensearch:9201` Compose DNS names per FR-1d.
    - **`api_client` (RelyLoop FastAPI self-call, base URL `http://localhost:8000`, no auth in MVP1):** `POST /api/v1/clusters`, `POST /api/v1/query-templates`, `POST /api/v1/query-sets`, `POST /api/v1/query-sets/{id}/queries`, `GET /api/v1/query-sets/{id}/queries?limit=50` (to fetch query IDs for judgment import), `POST /api/v1/judgment-lists/import`, `POST /api/v1/_test/studies/seed-completed`.
  - Step 3 — Apply study renames via the caller's `db` session in a fresh transaction (mirrors CLI's `apply_study_renames` at line 752): `UPDATE studies SET name = :name WHERE id = :id` for each scenario's `study_name`, then commit. (Renaming via SQL is faster than a `PATCH /api/v1/studies/{id}` self-call and the CLI uses the same SQL path; no new endpoint is introduced.)
  - Step 4 — Return `ReseedSummary(clusters_created=4, query_sets_created=4, studies_completed=4, proposals_created=4, duration_ms=int)`.

- **B. New endpoint** `POST /api/v1/_test/demo/reseed` (in `backend/app/api/v1/_test.py`):
  - `dependencies=[Depends(_require_development_env)]` (same gate as all other `/_test/*` endpoints).
  - Body: empty (no payload — the operation has no parameters).
  - Concurrency guard: a **session-level** Postgres advisory lock acquired via `SELECT pg_try_advisory_lock(:k)` where `k = int.from_bytes(blake2b(b"demo:reseed", digest_size=8).digest(), byteorder="big", signed=True)`. If the function returns `false` → `_err(409, "SEED_IN_PROGRESS", ..., True)` without further work. If it returns `true`, the lock is held across multiple committed transactions for the lifetime of this request and MUST be released explicitly via `SELECT pg_advisory_unlock(:k)` in a `try/finally` block. **The session-level variant is required (not `pg_try_advisory_xact_lock`) because the reseed performs multiple commits — see the transaction-shape discussion below.**
  - **No wall-clock cancellation of in-flight reseeds.** There is no outer `asyncio.wait_for`, no `SEED_TIMEOUT` error code, and no mechanism that interrupts a self-call mid-flight. The reseed runs to natural completion (or to a Python-level exception). **Rationale (GPT-5.5 cross-model cycle 3 finding):** any client-side cancellation of a mutating self-call (whether via `asyncio.wait_for` or per-call `httpx` `read_timeout`) leaves the server-side FastAPI handler running on a sibling DB session that may commit after cleanup has TRUNCATEd, leaving partial demo rows. The only way to guarantee cleanup never races a late commit is to ensure cleanup runs only after the orchestrator has returned control via natural Python-level flow (return or raise) — which means no timeout-driven cancellation. Operators whose dev stack genuinely hangs (~unbounded reseed) recover by restarting the API process: `docker compose restart api`. The session-level advisory lock releases automatically when the connection drops.
  - Failure handling: any orchestrator exception → cleanup pass runs under the held advisory lock, then raises `_err(503, "SEED_FAILED", ..., True)`. For **non-timeout exceptions** (failed self-call returned 4xx/5xx; ES/OS unreachable; Postgres error), by the time the exception reaches the route handler, no self-call is in flight (Python execution has returned to the orchestrator with a definitive response), so cleanup cannot race a late commit. For the **`httpx.ReadTimeout` edge** (per-call HTTP ceiling exceeded), the server-side handler may complete after cleanup; the residual risk + retry-the-reseed recovery are documented in §10 Threat 4 — cleanup is best-effort, not race-free, in that single edge case.
  - Cleanup pass: opens a fresh short DB transaction, `TRUNCATE`s the 10 demo tables (CASCADE handles any committed self-call inserts from the failed pass), then DELETEs the 4 demo indices (tolerating every error). The cleanup commits its own transaction and is awaited to completion BEFORE the advisory lock is released — so a concurrent caller cannot start a fresh reseed while cleanup is still wiping.
  - Response: HTTP 200 with `ReseedSummary` body.

  **Transaction shape — why session-level locking + multi-commit:** the reseed inherently requires multiple committed transactions because:
  - (a) `TRUNCATE ... CASCADE` holds Postgres `AccessExclusive` locks on every named table until commit. If the outer route handler held those locks across the subsequent `httpx` self-calls, the loopback `POST /api/v1/clusters` (and every later self-call) would BLOCK on table-lock acquisition — because each FastAPI request opens its own SQLAlchemy session and would try to take an `AccessShare` lock conflicting with the held `AccessExclusive`. The reseed must COMMIT the TRUNCATE before the self-call loop begins.
  - (b) Each `httpx` self-call hits a FastAPI route that owns its own session and commits independently. The outer orchestrator's session CANNOT roll back those committed inserts. The recovery invariant is therefore "cleanup re-wipes," not "outer rollback undoes."
  - (c) The session-level advisory lock (held in a dedicated long-running DB connection that the route handler keeps open for the request lifetime) serializes concurrent reseed requests across all of these committed sub-transactions. The lock is released only after cleanup commits (on the failure path) or after the final rename UPDATEs commit (on the success path).

- **C. New setting** `Settings.demo_reseed_per_call_http_timeout_s: int = 120` (range 30..600, validator on the field). Read by the orchestrator and passed as `httpx.AsyncClient(timeout=...)` for each per-self-call HTTP request. This is a **hard ceiling** to prevent a single self-call from hanging forever; it does NOT drive cleanup-on-timeout (see §4 and FR-4). If a self-call exceeds this, `httpx.ReadTimeout` propagates as a Python exception → orchestrator returns to the handler → 503 `SEED_FAILED` with cleanup. 120s gives a wide margin over the observed 5-10s typical scenario time. No `_FILE` suffix — not a secret.

- **D. UI button** "Reset to demo state" inside `StartHereChecklist`:
  - Conditional render: only when `!hasClusters && !hasQuerySetsWithJudgments && !hasStudies` (all three props false).
  - Disclosure pattern: `<details>` element below the 3-step list, summary text `"or skip ahead — reset to demo state"`.
  - Inside the disclosure: a `<Button variant="secondary">` labeled `"Reset to demo state"` that opens an AlertDialog.
  - AlertDialog title: `"Wipe and reseed demo data?"`. Body (mirrors `confirm_wipe` at [`scripts/seed_meaningful_demos.py:765-773`](../../../../scripts/seed_meaningful_demos.py)): `"This will WIPE the dev Postgres demo state (clusters, studies, query sets, query templates, judgment lists, judgments, trials, digests, proposals) AND the corresponding ES/OS indices. Then it will seed 4 demo scenarios."` Confirm button label: `"Reset to demo state"`. Cancel button label: `"Cancel"`.
  - On confirm: POST `/api/v1/_test/demo/reseed` via `apiClient.post` (no body). On 200: invalidate the TanStack queries (`['clusters']`, `['judgment-lists']`, `['studies']`, `['proposals']`) and show a toast `"Demo state reset — 4 clusters, 4 query sets, 4 completed studies. The dashboard will refresh in a moment."` (`useToast` hook from existing `ui/src/components/ui/use-toast.ts`). On 409/503: toast `"Reseed failed: {error_code}. If this followed a hang or timeout, run \`docker compose restart api\` before retrying; otherwise see the demo-reseed runbook or run \`make seed-demo FORCE=1\` from the host."` In all failure cases, leave the button enabled so the operator can retry. The UI sets its own `fetch` request-timeout to 180 seconds (a wide margin over the backend's 120s per-call ceiling × ~5 typical calls per scenario; the reseed-as-a-whole has no backend timeout per §3 In-scope B + FR-4). If the operator's browser request itself times out (network blip, hung backend, etc.), the UI surfaces a generic "Reseed in progress or unreachable — refresh the page in a moment" toast.

- **E. Coverage** — unit tests for the service module, integration tests for the endpoint (real DB + ES + OS), contract test for the env guard, vitest for the button + dialog, Playwright real-backend E2E covering one end-to-end click.

### Out of scope

- Refactoring `scripts/seed_meaningful_demos.py` to share code with `demo_seeding.py` beyond importing the `SCENARIOS` constant. The CLI keeps its `docker compose exec` + `urllib.request` shape (idea Decision D2).
- Per-scenario reseed (the endpoint reseeds all 4 atomically; you cannot wipe + reseed scenario 3 only).
- Reseed surface outside `ENVIRONMENT=development`. Staging / production deployments MUST 404.
- Audit-log emission today. The hook is documented (§6) but not implemented; the audit row insertion lands when MVP2's `audit_log` table arrives.
- A `?force=true` query param. The destructive prompt lives in the UI; the endpoint always wipes when called.

### API convention check

- **Endpoint prefix:** `/api/v1/_test/<verb>` — matches the existing `/_test/*` family in `backend/app/api/v1/_test.py`. Test-only endpoints DO live under `/api/v1/` (not unprefixed) per the precedent set by `infra_e2e_seed_completed_study`.
- **Router namespace:** [`backend/app/api/v1/_test.py`](../../../../backend/app/api/v1/_test.py) (no new module needed).
- **HTTP method for "reseed":** `POST` — semantically a destructive action, not idempotent (each call wipes + reseeds), so POST is correct per [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md).
- **Error envelope shape (per [`api-conventions.md` §"Error envelope"](../../../01_architecture/api-conventions.md)):**
  ```json
  {
    "detail": {
      "error_code": "<MACHINE_READABLE_CODE>",
      "message": "<human-readable>",
      "retryable": <bool>
    }
  }
  ```
  Both new error codes (`SEED_FAILED`, `SEED_IN_PROGRESS`) MUST conform.
- **Auth error shape:** N/A — single-tenant MVP1, no auth surface.

### Phase boundaries

Single-phase delivery. The feature ships in one PR; there is no Phase 2 (the MVP2 audit-log emission is an additive hook that will be applied to existing code once `audit_log` lands — not deferred work in this feature's planning footprint).

---

## 4) Product principles and constraints

- **Dev-only surface.** Every gate the existing `/_test/*` endpoints use applies here verbatim. No partial gating; no override flag; no unauthenticated tunnel into staging or production. The `_require_development_env` dependency is the sole gate.
- **CLI is authoritative for headless flows.** Operators running `make seed-demo` from CI or scripts MUST continue to get the CLI's exact behavior. The endpoint is for in-browser convenience only; it does not replace the CLI.
- **Cleanup boundary (NOT rollback-based atomicity).** The reseed performs multiple committed transactions (TRUNCATE commit, then per-scenario self-call commits). Outer-session rollback CANNOT undo those committed writes — so the recovery invariant is *cleanup re-wipes the stack*, not *the session rolls back*. On any orchestrator failure (returning 503 to the caller), the cleanup pass runs while the session-level advisory lock is still held; it `TRUNCATE`s the 10 tables (CASCADE absorbs any committed self-call writes) and `DELETE`s the 4 demo indices (tolerating every error). The advisory lock releases ONLY after cleanup commits, so a concurrent caller cannot start a second reseed during cleanup.
- **Self-call over service-function extraction (idea Decision D1).** The reseed service uses `httpx.AsyncClient` against `http://localhost:8000/api/v1` (or `127.0.0.1`) — the same HTTP path the CLI uses. Calling internal service functions directly would require auditing every existing endpoint's transaction boundary for compatibility with the bulk-loop usage; the HTTP path is already proven by the CLI.
- **Concurrency-safe by session-level Postgres advisory lock.** Two simultaneous reseed calls MUST NOT interleave. `pg_try_advisory_lock` (session-level, NOT the xact-level variant used by digest/orchestrator) is required because the reseed spans multiple committed transactions. The lock key follows the same `blake2b` → signed-int64 pattern as the workers (`backend/workers/digest.py:236-240`, `backend/workers/orchestrator.py:481-489`) but the lock primitive differs. The lock is acquired before any TRUNCATE and released ONLY after either the final rename commit (success) OR the cleanup commit (failure) — never before. Explicit `pg_advisory_unlock(:k)` in `finally`.
- **Settings discipline (CLAUDE.md Absolute Rule #8).** The per-call HTTP timeout is read from `Settings.demo_reseed_per_call_http_timeout_s`, never hardcoded.
- **Never log or expose secrets (CLAUDE.md Absolute Rule #10).** The ES/OS basic-auth credentials (`elastic:changeme`, `admin:admin`) are dev-stack defaults baked into the seed script today, NOT secrets. The endpoint MAY hardcode them in the service module mirroring the CLI; it MUST NOT echo them in toast/error messages or response bodies.

### Anti-patterns

- **Do not** call the engine adapter (`ElasticAdapter`) to manage demo indices. The demo indices are operator-data — they belong to the basic-auth ES/OS containers, not RelyLoop's cluster-registry adapter abstraction. Mirror the CLI's direct `httpx`/`urllib` calls.
- **Do not** copy/paste the `SCENARIOS` list from `seed_meaningful_demos.py`. Import it. Two copies drift; one copy stays in sync.
- **Do not** use `subprocess.run(["docker", "compose", "exec", ...])` inside the API container. There is no docker socket. Use SQLAlchemy text() for TRUNCATE and httpx for the HTTP calls (idea Origin §"Implementing C from inside the API container is non-trivial").
- **Do not** wrap each scenario in its own try/except and "skip-on-fail" semantics. The reseed is all-or-nothing: if scenario 2 fails, the endpoint returns `SEED_FAILED` and the cleanup re-wipes the stack. Partial-success has no consistent meaning here.
- **Do not** emit `demo.reseed.completed` audit-log events today. The table doesn't exist yet — wiring it now would require a no-op stub that becomes load-bearing at MVP2.
- **Do not** render the "Reset to demo state" button when any of the three onboarding props is `true`. A partial-state operator might still have work to preserve; the button is for fully-empty stacks only.
- **Do not** retry the `httpx.AsyncClient` self-call on transient HTTP errors. The CLI doesn't retry. If the API process can't respond to its own loopback, something is deeply wrong; the endpoint returns `SEED_FAILED` and the operator investigates `make logs`.

## 5) Assumptions and dependencies

- **Dependency: `httpx` Python package** — already in `pyproject.toml` (used by `backend/app/llm/capability_check.py`, `backend/app/adapters/elastic.py`, `backend/app/scripts/seed_es.py`). **Status:** implemented. **Risk if missing:** N/A — present.
- **Dependency: `pg_try_advisory_xact_lock` Postgres function** — present in Postgres 16 (the MVP1 default). **Status:** implemented. **Risk if missing:** N/A — Postgres ≥9.1.
- **Dependency: `SCENARIOS` constant in `scripts/seed_meaningful_demos.py`** — currently at line 127. **Status:** implemented. **Risk if missing:** The CLI script's scenario list is the authoritative source; if it's refactored, this feature must be re-aligned.
- **Dependency: Existing 7 API endpoints invoked by the reseed loop** — `POST /api/v1/clusters`, `POST /api/v1/query-templates`, `POST /api/v1/query-sets`, `POST /api/v1/query-sets/{id}/queries`, `GET /api/v1/query-sets/{id}/queries`, `POST /api/v1/judgment-lists/import`, `POST /api/v1/_test/studies/seed-completed`. **Status:** all implemented and exercised by the CLI today (`scripts/seed_meaningful_demos.py:579-694`). **Risk if missing:** The endpoint loopback fails; integration tests catch this immediately.
- **Dependency: ES + OS containers reachable at `http://elasticsearch:9200` / `http://opensearch:9201` from inside the API container** — Compose network DNS makes these resolvable. **Status:** confirmed via `seed_es.py`. **Risk if missing:** The reseed returns `SEED_FAILED` on the first PUT.
- **Dependency: Frontend `<AlertDialog>` primitive** — present in `ui/src/components/ui/alert-dialog.tsx` (used elsewhere in the dashboard for destructive actions). **Status:** implemented.

## 6) Actors and roles

- **Primary actor:** dev-stack operator (relevance engineer running `make up` on a laptop).
- **Role model:** N/A — single-tenant MVP1, no auth surface.
- **Permission boundary:** the `_require_development_env` dependency. Outside `ENVIRONMENT=development` the endpoint 404s; the UI button is irrelevant because the dashboard component only mounts in dev too (it loads via the same `/api/v1/clusters` query that the rest of the dashboard uses, but the button is gated on backend visibility via the response code — a 404 to the click attempt produces a clearer toast than hiding the button based on a probe).

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — `audit_log` lands at MVP2 per [`docs/01_architecture/data-model.md` §"Reserved for later releases"](../../../01_architecture/data-model.md). When MVP2 ships, the reseed endpoint MUST emit one event per successful reseed:

| Event type | Visibility | Metadata fields |
|---|---|---|
| `demo.reseed.completed` | `system` | `{clusters_created: int, query_sets_created: int, studies_completed: int, proposals_created: int, duration_ms: int}` |

The MVP2 finalization of this feature wires that insertion atomically with the final `db.commit()`. Tracking artifact: this section + the §15 Documentation requirement that an MVP2 follow-up idea file will be created when `audit_log` lands.

---

## 7) Functional requirements

### FR-1: `demo_seeding.reseed_demo_state` service function exists

- The system **MUST** expose `async def reseed_demo_state(db: AsyncSession, api_client: httpx.AsyncClient, engine_client: httpx.AsyncClient) -> ReseedSummary` in `backend/app/services/demo_seeding.py`. The function takes TWO `httpx.AsyncClient` instances by design — one for FastAPI loopback (`api_client`, base URL `http://localhost:8000`), one for direct ES/OS calls (`engine_client`, no base URL, per-call absolute URLs from `SCENARIOS[i].host_base_url`).
- The function **MUST NOT** mix the two client roles. Every FastAPI self-call MUST use `api_client`. Every direct ES/OS PUT/DELETE/_refresh call MUST use `engine_client` with `_resolve_engine_base_url(per-scenario host_base_url)` as the absolute URL prefix (per FR-1d) and the per-scenario `host_auth` tuple passed via `auth=`. The basic-auth tuples are `("elastic", "changeme")` for ES and `("admin", "admin")` for OS — dev-stack defaults baked into the CLI today.
- **FR-1c (client-construction contract):** the route handler MUST construct both clients at the start of the request (`httpx.AsyncClient(base_url="http://localhost:8000", timeout=settings.demo_reseed_per_call_http_timeout_s)` for `api_client`; `httpx.AsyncClient(timeout=settings.demo_reseed_per_call_http_timeout_s)` for `engine_client`) and close them in `finally`. The same per-call HTTP timeout applies to both.
- The function **MUST** execute the 10-table `TRUNCATE ... RESTART IDENTITY CASCADE` in the same table order as `scripts/seed_meaningful_demos.py:67-78` (`TRUNCATE_TABLES` constant) AND **commit the TRUNCATE transaction before issuing any httpx self-call**, because TRUNCATE holds `AccessExclusive` locks that would block subsequent loopback requests.
- The function **MUST** DELETE every demo index named in `DEMO_ES_INDICES` (via `engine_client`, against `http://elasticsearch:9200`) and `DEMO_OS_INDICES` (via `engine_client`, against `http://opensearch:9201`), tolerating HTTP 404 on each delete. Index deletes run AFTER the TRUNCATE commit, before the scenario loop.
- The function **MUST** loop the 4 entries in `SCENARIOS` from `scripts/seed_meaningful_demos.py`, calling the same operations `seed_scenario` calls — in the same order — using the appropriate client per the table in §3 In-scope A Step 2. Each FastAPI self-call's HTTP request opens its own FastAPI request/session and commits independently — the orchestrator does NOT and CANNOT hold a single outer transaction across them.
- The function **MUST** apply study renames after the loop using a fresh short DB transaction via the caller's `db` session — NOT a FastAPI self-call. Mirrors `apply_study_renames` at line 752 of the CLI.
- The function **MUST** return a `ReseedSummary` dataclass-like Pydantic model with `clusters_created=4`, `query_sets_created=4`, `studies_completed=4`, `proposals_created=4`, `duration_ms` (wall-clock ms from start to last rename commit).
- The caller (the route handler) **MUST** be responsible for advisory-lock acquisition + release. The service function MUST NOT touch the advisory lock — that's the handler's job.

### FR-1d: In-container engine base-URL resolver

- The system **MUST** define a pure function `_resolve_engine_base_url(host_base_url: str) -> str` inside `backend/app/services/demo_seeding.py` that maps the CLI's host-shell URLs to the in-container Compose DNS names:
  - `http://localhost:9200` → `http://elasticsearch:9200`
  - `http://localhost:9201` → `http://opensearch:9201`
  - Any other input → raise `ValueError(f"Unrecognized engine host URL: {host_base_url}")`.
- The resolver MUST be unit-tested with cases for ES, OS, and the ValueError branch.
- The resolver does NOT touch `Settings`; the mapping is hardcoded because (a) it's tied to the Compose service names which are themselves load-bearing dev-stack defaults, (b) only the CLI's two host URLs need to be translated, (c) parameterizing would invite drift between the CLI's SCENARIOS and the service-side config.
- **If the CLI ever adds a third engine target,** the resolver MUST be updated in the same PR — failure to update raises `ValueError` at runtime, which surfaces as 503 `SEED_FAILED` and makes the regression obvious.

### FR-2: `POST /api/v1/_test/demo/reseed` endpoint exists

- The system **MUST** register `POST /api/v1/_test/demo/reseed` in `backend/app/api/v1/_test.py` with `dependencies=[Depends(_require_development_env)]`.
- The endpoint **MUST** accept no request body.
- The endpoint **MUST** return HTTP 200 with body `ReseedSummary` on success.
- The endpoint **MUST** return HTTP 404 `RESOURCE_NOT_FOUND` outside `ENVIRONMENT=development` (via the existing guard dependency — no special handling).
- The endpoint **MUST** return HTTP 409 `SEED_IN_PROGRESS` (retryable=True) when `pg_try_advisory_lock(:k)` returns `false`. No DB work runs in this case — the handler returns immediately.
- The endpoint **MUST** return HTTP 503 `SEED_FAILED` (retryable=True) on any failure surfaced from the orchestrator (including `httpx.ReadTimeout` from a single self-call exceeding `demo_reseed_per_call_http_timeout_s`).
- The endpoint **MUST NOT** define or return a `SEED_TIMEOUT` error code. There is no wall-clock timeout for the reseed as a whole — see FR-4.
- On the 503 path, BEFORE returning the error, the handler **MUST** await the cleanup pass to completion under the still-held advisory lock. Cleanup uses a fresh DB transaction (NOT the caller's session, which may be in a broken/rolled-back state after a mid-flight exception). Cleanup MUST `TRUNCATE` the 10 demo tables and `DELETE` the 4 demo indices, tolerating every error.
- The endpoint **MUST** release the advisory lock via `pg_advisory_unlock(:k)` in a `finally` block, AFTER cleanup has committed (failure path) or AFTER the rename commit (success path). The handler MUST NOT release the lock before cleanup completes.
- The endpoint **MUST** use the canonical `_err(status_code, code, message, retryable)` helper.

### FR-3: Concurrency guard via session-level Postgres advisory lock on a dedicated pinned connection

- The system **MUST** acquire a session-level Postgres advisory lock before any TRUNCATE.
- The lock key **MUST** be `int.from_bytes(blake2b(b"demo:reseed", digest_size=8).digest(), byteorder="big", signed=True)` (mirroring the key-derivation pattern in `backend/workers/digest.py:236-240` + `backend/workers/orchestrator.py:481-489`, but using a different lock primitive — see below).
- The system **MUST** use `pg_try_advisory_lock` (session-level, non-blocking variant), NOT `pg_try_advisory_xact_lock`. Rationale: the reseed performs multiple committed transactions (TRUNCATE commit, per-self-call commits, rename commit, cleanup commit). A transaction-scoped lock would release after the first commit and leave the rest of the operation unprotected.
- When `pg_try_advisory_lock(:k)` returns `false`, the route handler MUST immediately raise `_err(409, "SEED_IN_PROGRESS", ..., True)` without further work.
- The lock MUST be released via an explicit `SELECT pg_advisory_unlock(:k)` call in a `finally` block in the route handler — AFTER cleanup commits on the failure path, OR after the rename commit on the success path.
- **Connection pinning is mandatory.** Session-level Postgres advisory locks are bound to a physical Postgres connection, not to a SQLAlchemy `AsyncSession` object. By default, `AsyncSession.commit()` returns the underlying connection to the pool, and the next call may check out a different physical connection — which would (a) make `pg_advisory_unlock` run on the wrong connection (returning `false` and leaking the lock on the original pooled connection), and (b) potentially let a concurrent caller's `pg_try_advisory_lock` return `true` on the same pooled connection (Postgres advisory locks are reentrant within the same connection). **Therefore: the route handler MUST acquire the advisory lock on a dedicated `AsyncConnection` checked out from the engine independently of the request's `AsyncSession`.** Concretely:
  - The handler obtains the engine via the existing `get_engine()` / `session.bind` accessor.
  - The handler opens `async with engine.connect() as lock_conn:` and calls `await lock_conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY})` on `lock_conn`.
  - `lock_conn` remains checked out for the entire request lifetime; it is NOT used for any reseed write (those use the normal `db: AsyncSession` and the FastAPI self-call sessions).
  - In `finally`, the handler calls `await lock_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})` on the SAME `lock_conn`, and asserts the returned value is `true` (logging a WARN if false — the lock was somehow already released, which indicates a connection-affinity bug).
  - `lock_conn` is committed (no-op since no writes) before context-exit so the implicit transaction doesn't sit idle.
- The handler **MUST** log the `pg_advisory_unlock` return value at INFO/WARN so a connection-affinity regression is observable in operator logs.
- The dedicated lock connection adds one Postgres connection per in-flight reseed request to the pool footprint. The default pool size (10 in MVP1) easily accommodates the worst case (~2-3 simultaneous reseed attempts before 409s fire), so no pool-size tuning is required.

### FR-4: No outer wall-clock timeout; per-call HTTP timeout is a hard ceiling only

- The system **MUST NOT** wrap the orchestrator in `asyncio.wait_for`, nor implement any other Python-level cancellation that interrupts an in-flight self-call. **Rationale (GPT-5.5 cross-model cycle 2 + cycle 3 findings):** any client-side cancellation of a mutating self-call (whether via `asyncio.wait_for` or per-call `httpx` read-timeout) leaves the server-side FastAPI handler running on a sibling DB session. That handler may commit after the orchestrator's cleanup has TRUNCATEd, leaving partial demo rows. There is no cheap way to prove server-side completion from client-side cancellation; the only safe design is to let the orchestrator run to natural completion and let cleanup run only after Python control has returned to the route handler.
- The system **MUST** set a per-self-call HTTP read-timeout via `httpx.AsyncClient(timeout=settings.demo_reseed_per_call_http_timeout_s)` (default 120s) as a hard ceiling. If a single self-call's client-side await exceeds this, `httpx.ReadTimeout` propagates as a Python exception → orchestrator unwinds → route handler runs cleanup → returns 503 `SEED_FAILED`. **Caveat:** an `httpx.ReadTimeout` does NOT prove the server-side handler stopped. In the worst case, a server-side handler completing after cleanup could leave 1 or 2 demo rows behind. **Furthermore, naively re-clicking the reseed button after a ReadTimeout is NOT safe** — the abandoned server-side handler may still be running, and its late commit could land after the retry's TRUNCATE. The documented recovery for the ReadTimeout edge is: **`docker compose restart api`** (which forces the abandoned handler's connection to drop, releasing its DB session and preventing any late commit), THEN retry the reseed. The 503 toast wording (FR-6) and the runbook (§15) both surface this guidance to the operator. The residual risk + recovery model are documented in §10 Threat 4.
- The system **MUST NOT** define a `SEED_TIMEOUT` error code. The error code catalog (§7.5) carries only `SEED_FAILED`, `SEED_IN_PROGRESS`, `RESOURCE_NOT_FOUND`.
- On any orchestrator failure, the handler **MUST** run cleanup BEFORE returning 503 — and cleanup is guaranteed to run AFTER Python control has returned to the orchestrator (no `asyncio.wait_for` to short-circuit). This is the strongest property the design can deliver without introducing server-side fencing primitives that don't exist in MVP1.

### FR-4b: New `Settings.demo_reseed_per_call_http_timeout_s` field

- The system **MUST** add `demo_reseed_per_call_http_timeout_s: int = Field(default=120, ge=30, le=600, description=...)` to `backend/app/core/settings.py`.
- Default 120s — a wide margin over the observed 5-10s typical scenario time.
- The field MUST NOT carry a `_FILE` suffix (not a secret).
- This setting is a hard ceiling per self-call, NOT a wall-clock budget for the reseed as a whole. There is no setting controlling the latter; the reseed runs to natural completion (or until a per-call timeout fires).

### FR-5: (Superseded) No global wall-clock setting; only the per-call ceiling FR-4b

- The originally-locked decision D3 proposed `Settings.demo_reseed_timeout_s` (default 60s) as a wall-clock budget enforced via `asyncio.wait_for`. **D3 is superseded** by FR-4 (drop the outer timeout entirely; per-call HTTP ceiling only).
- The system **MUST NOT** add a `demo_reseed_timeout_s` field. The locked decision D3 is updated in §19 with the cross-model rationale.
- The only timeout setting is `demo_reseed_per_call_http_timeout_s` (FR-4b).

### FR-6: "Reset to demo state" button in `StartHereChecklist`

- The system **MUST** add a `<details>` disclosure below the 3-step onboarding list inside `ui/src/components/dashboard/start-here-checklist.tsx`.
- The disclosure **MUST** render only when `!hasClusters && !hasQuerySetsWithJudgments && !hasStudies` (a truly empty stack).
- The disclosure summary text **MUST** be `"or skip ahead — reset to demo state"`.
- The inner button **MUST** be labeled `"Reset to demo state"` and use the existing `<Button variant="secondary">` primitive.
- Clicking the button **MUST** open an `<AlertDialog>` with the wording specified in §3 In-scope D.
- On confirm, the system **MUST** POST `/api/v1/_test/demo/reseed` (empty body) via the existing `apiClient`.
- On 200, the system **MUST** invalidate the relevant TanStack queries (`['clusters']`, `['judgment-lists']`, `['studies']`, `['proposals']`) and show a success toast.
- On 409/503, the system **MUST** show a failure toast naming the `error_code` and leave the button enabled.

### FR-7: Contract test extends env-guard parametrization

- The system **MUST** extend `backend/tests/contract/test_test_endpoint_guard.py` to parametrize the new `/_test/demo/reseed` endpoint across the same `_NON_DEV_ENVIRONMENTS` list (`["staging", "production", "ci", "qa", ""]`) and assert 404 + `RESOURCE_NOT_FOUND` for each.
- The system **MUST** register the new endpoint in `backend/tests/contract/test_openapi_surface.py` (mirroring the existing entries at lines 96-97).

### FR-8: Integration test covers the happy path end-to-end

- The system **MUST** add `backend/tests/integration/test_demo_seeding.py` covering: (a) clean-DB happy path → 200 + 4 rows in each demo table (AC-1), (b) populated-DB replacement → 200 + new UUIDs (AC-2), (c) two simultaneous reseed requests → second gets 409 (AC-3), (d) per-call HTTP timeout exceeded: monkeypatch `demo_reseed_per_call_http_timeout_s=1` and force a self-call to delay → assert 503 `SEED_FAILED` (AC-4 — **the test MUST NOT assert deterministic post-cleanup emptiness AND MUST NOT assert in-process retry restores demo state** per §10 Threat 4; the documented recovery requires `docker compose restart api` first, which is out of scope for the integration test runner), (e) failure-mid-flight (non-timeout): stop ES mid-loop and assert 503 + deterministic post-cleanup empty state (AC-5), (f) AC-12 cleanup-while-locked race, (g) AC-13 commit-ordering assertion, (h) AC-14 natural-failure cleanup-after-Python-control-returns assertion (deterministic emptiness — non-timeout path only).
- The integration test **MUST** use real Postgres + real ES + real OS containers (service containers in CI).

### FR-9: Vitest covers the dashboard button

- The system **MUST** add tests to `ui/src/__tests__/components/dashboard/start-here-checklist.spec.tsx` (or create the file if absent) for: (a) disclosure hidden when any prop is `true`, (b) disclosure visible when all three props are `false`, (c) confirm button opens the AlertDialog with the canonical wording, (d) Cancel closes the dialog without firing the POST.

### FR-10: Playwright E2E covers one real-backend click-through

- The system **MUST** add a Playwright test at `ui/tests/e2e/dashboard-reseed.spec.ts` that: (a) wipes the dev stack via the existing `/api/v1/_test/*` DELETE endpoints, (b) navigates to `/`, (c) clicks the disclosure → button → Confirm, (d) waits for the toast, (e) asserts the dashboard now shows 4 clusters and a non-empty Recent Studies card.
- The Playwright test **MUST** use real `page` interactions (no `page.route()` mocking — CLAUDE.md §"E2E Testing Rules").

## 8) API and data contract baseline

### 7.1 Endpoint surface

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `POST` | `/api/v1/_test/demo/reseed` | Wipe + reseed all 4 demo scenarios (dev-only). | `RESOURCE_NOT_FOUND` (404, env guard), `SEED_IN_PROGRESS` (409), `SEED_FAILED` (503) |

### 7.2 Contract rules

- Error body **MUST** include machine-readable `error_code` per `_err()` helper.
- Status codes **MUST** be deterministic per scenario (FR-2).
- Outside `ENVIRONMENT=development`, the endpoint **MUST** return 404 with the same shape a genuinely-unregistered route would produce (anti-enumeration).

### 7.3 Response examples

**Success (HTTP 200):**
```json
{
  "clusters_created": 4,
  "query_sets_created": 4,
  "studies_completed": 4,
  "proposals_created": 4,
  "duration_ms": 7423
}
```

**Failure — concurrent reseed (HTTP 409):**
```json
{
  "detail": {
    "error_code": "SEED_IN_PROGRESS",
    "message": "A demo reseed is already running; wait for it to complete.",
    "retryable": true
  }
}
```

**Failure — mid-flight error (HTTP 503):**
```json
{
  "detail": {
    "error_code": "SEED_FAILED",
    "message": "Demo reseed failed mid-flight. Cleanup applied; check `make logs` for details.",
    "retryable": true
  }
}
```

**Outside development (HTTP 404):**
```json
{
  "detail": {
    "error_code": "RESOURCE_NOT_FOUND",
    "message": "Not found",
    "retryable": false
  }
}
```

### 7.4 Enumerated value contracts

N/A — the endpoint accepts no request body and exposes no filter/dropdown/enum surface. The `error_code` values (`SEED_FAILED`, `SEED_IN_PROGRESS`, `RESOURCE_NOT_FOUND`) are documented in §7.5 and consumed by the frontend's failure toast (which just inlines the code string — no allowlist match needed).

### 7.5 Error code catalog

| Code | HTTP Status | Meaning |
|---|---|---|
| `SEED_FAILED` | 503 | The reseed orchestration errored mid-flight. Causes include: a self-call returned 4xx/5xx, ES/OS was unreachable, or a single self-call exceeded `Settings.demo_reseed_per_call_http_timeout_s` (default 120s) and raised `httpx.ReadTimeout`. The server ran cleanup (TRUNCATE + index delete). For **non-timeout** causes the demo stack is deterministically empty and an immediate operator retry is safe. For the **`httpx.ReadTimeout`** edge the abandoned server-side handler may complete after cleanup AND a naive retry can race that handler's late commit — per §10 Threat 4 the safe recovery is `docker compose restart api` THEN retry. Retryable (with the restart caveat for the timeout edge). |
| `SEED_IN_PROGRESS` | 409 | A concurrent reseed is already running on this API process. The session-level Postgres advisory lock is held; the second caller MUST wait and retry. |

## 9) Data model and state transitions

### New/changed entities

**No new tables. No schema changes. No migration.**

The reseed endpoint TRUNCATEs and re-populates existing tables; it does not introduce new columns or constraints. The `Settings.demo_reseed_per_call_http_timeout_s` field is a Python-level configuration item, not a DB column.

### Required invariants

- After a successful reseed, the following row counts MUST hold:
  - `clusters`: 4
  - `query_sets`: 4
  - `query_templates`: 4
  - `judgment_lists`: 4
  - `studies`: 4 (all `status='completed'`)
  - `digests`: 4 (one per study)
  - `proposals`: 4 (all `status='pending'`)
  - `trials`: 8 (two per study — winner + runner-up, mirrors `seed_study_completed_with_digest`)
- The ES indices `products`, `docs-articles`, `job-listings` MUST exist with the canonical mappings from `SCENARIOS`.
- The OS index `news-articles` MUST exist with the canonical mapping from `SCENARIOS`.

### State transitions

N/A — no new state machines. The studies seeded by the reseed pass through `queued → running → completed` via the existing `seed_study_completed_with_digest` service (unchanged).

### Idempotency/replay behavior

The endpoint is **not idempotent in the HTTP-method sense** — each call wipes + reseeds, producing new UUIDs for every row. Successive calls land the dashboard in the same observable state (4 clusters / 4 query sets / 4 completed studies), but the underlying IDs differ. This is acceptable for a dev-only reseed surface. The session-level advisory lock (FR-3) prevents two simultaneous wipes from interleaving AND ensures that a failed reseed's cleanup runs to completion before a retry can start.

**Retry safety by error code:**
- **409 `SEED_IN_PROGRESS`:** safe to retry immediately (after waiting for the running reseed to complete or the advisory lock to release).
- **503 `SEED_FAILED` from a non-timeout cause** (failed self-call returned 4xx/5xx; ES/OS unreachable; Postgres error): safe to retry immediately. Cleanup has run; the stack is deterministically empty.
- **503 `SEED_FAILED` from `httpx.ReadTimeout`** (per-call HTTP ceiling exceeded): NOT safe to retry immediately — see §10 Threat 4. Recovery is **`docker compose restart api` then retry**. The 503 toast directs the operator to this path.
- The endpoint MUST NOT emit HTTP 504 (the wall-clock timeout was removed per FR-4 / §19 cycle-3 decision log).

## 10) Security, privacy, and compliance

- **Threat 1 — dev-only endpoint reachable in production.** Controls: `_require_development_env` dependency returns 404 outside `ENVIRONMENT=development`. The contract test at `backend/tests/contract/test_test_endpoint_guard.py` parametrizes `staging`, `production`, `ci`, `qa`, `""` and asserts 404 + `RESOURCE_NOT_FOUND` for each.
- **Threat 2 — operator credentials in error messages.** Controls: the `_err` helper never echoes the SQL statement or HTTP payload. The ES/OS basic-auth credentials are dev-stack defaults (`elastic:changeme`, `admin:admin`) — not secrets — and are not in scope for redaction.
- **Threat 3 — concurrent reseed corrupts state.** Controls: session-level `pg_try_advisory_lock` (FR-3). Second caller gets 409 immediately. The lock is held across multiple committed transactions (TRUNCATE commit, self-call commits, rename commit, cleanup commit) and released only in the route handler's `finally` block — so a concurrent caller cannot start a fresh reseed while a previous reseed's cleanup is still wiping. Integration test AC-12 covers this race directly: request A is forced to fail mid-flight; request B fires while A's cleanup runs; B gets 409 until cleanup commits + lock releases.
- **Threat 4 — runaway reseed wedges the dev stack.** Controls (with documented residual risk): per-self-call `httpx` read timeout (`demo_reseed_per_call_http_timeout_s`, default 120s) is a hard ceiling on any single API call. There is NO outer wall-clock timeout for the reseed as a whole (per FR-4 — cycle 2 + cycle 3 findings established that client-side cancellation cannot prove server-side handler completion, so an outer timeout would race cleanup with late commits). If a single self-call's `httpx.ReadTimeout` fires, the orchestrator unwinds, cleanup runs, and 503 returns — but the server-side handler may complete after cleanup, leaving 1-2 demo rows behind. **Recovery on the ReadTimeout edge is NOT operator-clicks-the-button-again.** A naive retry can race with the still-running abandoned handler whose late commit could land after the retry's TRUNCATE. The documented recovery is: **`docker compose restart api`** — this drops the abandoned handler's DB connection, which (a) releases any DB session it held, (b) prevents any pending commit, (c) auto-releases the session-level advisory lock (lock is connection-scoped per FR-3). After the restart, the operator can safely retry the reseed. If the operator's stack genuinely hangs (e.g., FastAPI worker deadlock), the same `docker compose restart api` is the recovery. The 503 toast wording (FR-6) directs the operator to the runbook, which prescribes restart-then-retry. Documenting this residual risk + recovery is sufficient because (a) the failure mode is rare on a healthy dev stack (per-call timeout >> typical 5-10s scenario time), (b) restart-then-retry is a single-step recovery, (c) the alternative designs (server-side fencing primitives) are out of scope for MVP1.
- **Secrets/key handling:** none added. The reseed function reads no secrets; ES/OS basic-auth lives in the function body as plaintext dev defaults (same as the CLI script's pattern).
- **Auditability:** deferred to MVP2 when `audit_log` lands. The endpoint logs `demo_reseed_started`, `demo_reseed_completed`, `demo_reseed_failed` at INFO via the existing structlog pipeline; that's the operator's audit trail until the audit-log table arrives.
- **Data retention/deletion/export:** N/A. The reseed touches dev-stack data only.

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement:** the new button lives inside `StartHereChecklist`, below the 3-step onboarding list, behind a `<details>` disclosure. The component renders on `/` (the dashboard root) when the user has not yet completed all three onboarding steps. The disclosure itself is hidden unless all three steps are incomplete (i.e., a truly empty stack).
- **Labeling taxonomy:**
  - Disclosure summary: `"or skip ahead — reset to demo state"` (matches the casual tone of the existing checklist's "Get started" + step-CTA labels).
  - Button label: `"Reset to demo state"` (verb + noun, mirrors the disclosure summary's keyword).
  - AlertDialog title: `"Wipe and reseed demo data?"`.
  - AlertDialog confirm button: `"Reset to demo state"` (same as the outer button — the user has already committed to the action, the dialog confirms; reusing the verb avoids a "Confirm" / "Yes" / "Wipe" decision).
  - AlertDialog cancel button: `"Cancel"`.
  - Toast (success): `"Demo state reset — 4 clusters, 4 query sets, 4 completed studies. The dashboard will refresh in a moment."`
  - Toast (failure): `"Reseed failed: {error_code}. If this followed a hang or timeout, run \`docker compose restart api\` before retrying; otherwise see the demo-reseed runbook or run \`make seed-demo FORCE=1\` from the host."`
- **Content hierarchy:** the 3-step onboarding list remains the primary visual anchor. The disclosure summary is intentionally lowercase + casual to signal "secondary affordance"; it doesn't compete with the numbered steps.
- **Progressive disclosure:** the button is hidden by default (collapsed `<details>`). The operator clicks the disclosure to reveal it, then clicks the button to open the dialog. Two clicks before the destructive action fires — deliberate friction.
- **Relationship to existing pages:** the button extends `StartHereChecklist`. It does not appear on any other page. The Phase 1 `DemoDataBanner` (above the checklist) keeps its current behavior; the banner says "you're looking at demo data," the new disclosure says "or rebuild that demo data."

### Tooltips and contextual help

| Element | Tooltip / help text | Trigger | Placement |
|---------|-------------------|---------|-----------|
| `<details>` summary "or skip ahead — reset to demo state" | None (the summary itself is the help text) | N/A | N/A |
| `<Button>` "Reset to demo state" | None (the dialog provides the warning) | N/A | N/A |
| AlertDialog body | The full destructive-action wording (see §3 In-scope D, §11 Labeling) is itself the contextual help. No additional tooltip needed. | N/A | N/A |

No new glossary keys are required. The wording matches the CLI's `confirm_wipe` prompt; that text is the source of truth for the destructive-action language.

### Primary flows

1. **Operator wipes the stack then wants demo data back.**
   - State: dashboard renders `StartHereChecklist` with all three steps incomplete; disclosure visible.
   - Operator clicks the `<details>` summary → button revealed.
   - Operator clicks `"Reset to demo state"` → AlertDialog opens.
   - Operator clicks `"Reset to demo state"` (confirm) → POST fires.
   - On 200: toast shown, TanStack queries invalidate, dashboard refetches and shows 4 clusters + recent studies.
   - End state: operator sees a populated dashboard without leaving the browser.

2. **Operator clicks "Reset to demo state" while a previous reseed is still in flight.**
   - State: a prior POST is mid-flight (advisory lock held).
   - Operator clicks confirm → POST fires → 409 `SEED_IN_PROGRESS`.
   - Failure toast shown; button stays enabled; operator waits ~5-10s and retries.

### Edge/error flows

- **Single self-call exceeds `demo_reseed_per_call_http_timeout_s` (slow laptop / CI runner).** Endpoint returns 503 `SEED_FAILED` (per FR-4: no separate timeout code; `httpx.ReadTimeout` is just one cause of `SEED_FAILED`). Cleanup runs. Toast shown directing the operator to the runbook. **Recovery on this edge requires `docker compose restart api`** (drops the abandoned handler's DB connection and releases the advisory lock per §10 Threat 4), then retry the reseed OR run `make seed-demo FORCE=1` from the host. Operators on slow stacks should raise `DEMO_RESEED_PER_CALL_HTTP_TIMEOUT_S` in `.env` and `make restart` to prevent recurrence.
- **Reseed fails mid-flight (e.g., ES container crashed).** Endpoint returns 503 `SEED_FAILED` after cleanup. Toast shown. Operator inspects `make logs` and addresses the underlying cause.
- **Reseed appears to hang (no response).** No wall-clock cancellation by design (per FR-4 — see §10 Threat 4). The browser request can take up to `demo_reseed_per_call_http_timeout_s × scenarios × per-scenario calls` in the worst case. The UI's own 180-second fetch timeout surfaces a generic "in progress or unreachable" toast; the backend continues running the reseed. Operator can `docker compose restart api` to abort.
- **Operator clicks the disclosure on a partial-state stack (e.g., 1 cluster but no studies).** The disclosure is hidden in this case — the button never renders. The operator must use `make seed-demo FORCE=1` from the host (or delete the partial state via the existing `/_test/*` DELETE endpoints).
- **`ENVIRONMENT` is set to `staging` or `production`.** Disclosure still renders (it's a frontend component that doesn't probe), but clicking confirm → POST fires → 404 `RESOURCE_NOT_FOUND`. Failure toast shown. This is an acceptable degraded path because such a deployment is operator-misconfigured (staging/prod shouldn't be running this seed UI).

## 12) Given/When/Then acceptance criteria

### AC-1: Reseed on a clean stack returns 200 with the expected summary

- Given the dev stack is up with all 10 demo tables empty AND the 4 demo indices absent
- When a POST is made to `/api/v1/_test/demo/reseed` with no body
- Then the response is HTTP 200 with `{clusters_created: 4, query_sets_created: 4, studies_completed: 4, proposals_created: 4, duration_ms: <int>}`
- And the 10 tables now contain exactly the 4-row demo state (per §9 Required invariants)
- And the 3 ES indices + 1 OS index exist with the canonical mappings

### AC-2: Reseed on a populated stack wipes and rebuilds

- Given the dev stack has prior demo data (10 tables each with rows, 4 indices present)
- When a POST is made to `/api/v1/_test/demo/reseed`
- Then the response is HTTP 200
- And the prior rows are gone (their UUIDs no longer exist)
- And the new rows match §9 Required invariants

### AC-3: Concurrent reseed returns 409 `SEED_IN_PROGRESS`

- Given a reseed is already running (advisory lock held)
- When a second POST is made to `/api/v1/_test/demo/reseed`
- Then the second response is HTTP 409 with `error_code=SEED_IN_PROGRESS`, `retryable=true`
- And the first reseed continues uninterrupted

### AC-4: Per-call HTTP timeout exceeded returns 503 `SEED_FAILED`

- Given `Settings.demo_reseed_per_call_http_timeout_s = 1` (forced low for the test) AND a self-call is forced to take longer than 1s (e.g., the test patches `seed_completed_study` to `asyncio.sleep(5)` before its DB writes)
- When a POST is made to `/api/v1/_test/demo/reseed`
- Then the response is HTTP 503 with `error_code=SEED_FAILED`, `retryable=true` (NOT 504; there is no `SEED_TIMEOUT` code)
- And cleanup ran AFTER `httpx.ReadTimeout` propagated to the orchestrator and unwound to the route handler
- **The test MUST NOT assert deterministic post-cleanup emptiness on the timeout edge** — the server-side handler whose `httpx.ReadTimeout` triggered the failure may complete after cleanup (per §10 Threat 4).
- **The test MUST NOT assert that a naive in-process retry restores the 4-row state** — per §10 Threat 4 the safe recovery requires `docker compose restart api` first to drop the abandoned handler's connection. The integration test is responsible for asserting the 503 + the `error_code` + that cleanup was attempted (via log inspection); the restart-then-retry recovery is documented operator behavior, not a CI-asserted invariant. A Playwright E2E test verifying the restart-then-retry round-trip is out of scope (would require Compose orchestration from inside the test runner, which the test infrastructure doesn't support today).
- Example values:
  - Input: POST with no body, per-call timeout=1s, server-side delay=5s → expected status=503, `error_code=SEED_FAILED`

### AC-5: Reseed failure mid-flight returns 503 `SEED_FAILED`

- Given the ES container is unreachable (simulated by stopping it for the integration test)
- When a POST is made to `/api/v1/_test/demo/reseed`
- Then the response is HTTP 503 with `error_code=SEED_FAILED`, `retryable=true`
- And the SQLAlchemy session is rolled back
- And the Postgres tables are empty (best-effort cleanup ran)

### AC-6: Outside development the endpoint 404s

- Given `Settings.environment="production"` (or any non-`development` value)
- When a POST is made to `/api/v1/_test/demo/reseed`
- Then the response is HTTP 404 with `error_code=RESOURCE_NOT_FOUND`, `retryable=false`
- And no DB writes occur

### AC-7: Dashboard button visible only when all three onboarding props are false

- Given `clustersCount.data === 0 && judgmentListsCount.data === 0 && recent.data?.totalCount === 0`
- When the dashboard renders
- Then `StartHereChecklist` renders AND the `<details>` disclosure is in the DOM
- And the disclosure summary text is `"or skip ahead — reset to demo state"`

### AC-8: Dashboard button hidden when any onboarding prop is true

- Given `clustersCount.data === 1 && judgmentListsCount.data === 0 && recent.data?.totalCount === 0` (partial state)
- When the dashboard renders
- Then `StartHereChecklist` renders (because not all 3 are done) AND the `<details>` disclosure is NOT in the DOM

### AC-9: Confirmation dialog blocks the POST until confirm

- Given the disclosure is open and the button is clicked
- When the AlertDialog opens
- Then no POST has fired yet
- And the dialog shows the canonical wording from §3 In-scope D
- And clicking Cancel closes the dialog without firing the POST
- And clicking Confirm fires the POST

### AC-10: Success toast + dashboard refetch after reseed

- Given the operator confirms the reseed
- When the POST returns 200
- Then the success toast `"Demo state reset — 4 clusters, 4 query sets, 4 completed studies. The dashboard will refresh in a moment."` is shown
- And the dashboard's `clusters`, `judgment-lists`, `studies`, and `proposals` queries are invalidated
- And within ~2s the dashboard renders the 4 clusters / 4 query sets / 4 completed studies

### AC-11: Failure toast shows error code + restart-then-retry guidance; button remains enabled

- Given a 409/503 response (no 504 path — `SEED_TIMEOUT` does not exist per FR-4)
- When the failure toast renders
- Then the toast text is exactly the wording specified in FR-6 / §11 Labeling: `"Reseed failed: {error_code}. If this followed a hang or timeout, run \`docker compose restart api\` before retrying; otherwise see the demo-reseed runbook or run \`make seed-demo FORCE=1\` from the host."` (with `{error_code}` substituted to the actual code)
- And the toast contains BOTH the literal `error_code` token AND the literal `docker compose restart api` token
- And the button is enabled (the operator's next action depends on whether the failure followed a hang/timeout — the UI does not pre-decide)
- And the disclosure remains open so the operator can retry after the appropriate recovery step

### AC-12: Cleanup-during-failure holds the lock; second request 409s until cleanup commits

- Given request A is in flight AND fails mid-self-call (e.g., ES container forced down for the test)
- And request A enters its cleanup pass
- When request B is fired before A's cleanup commits
- Then request B receives HTTP 409 `SEED_IN_PROGRESS` (lock still held by A)
- And after A's cleanup commits + releases the lock, the next request C succeeds with HTTP 200 and the stack ends in the 4-row demo state
- Example values:
  - Setup: simulate ES failure by stopping the ES container after the 2nd scenario seeds
  - Expected: A → 503 (with cleanup), B (during cleanup) → 409, C (post-cleanup) → 200

### AC-13: TRUNCATE commits before first self-call (deadlock prevention)

- Given the reseed orchestrator starts a fresh reseed
- When the TRUNCATE step runs
- Then the TRUNCATE transaction commits BEFORE the first `httpx` self-call is issued
- And the first self-call (`POST /api/v1/clusters` for scenario 1) succeeds without blocking on any `AccessExclusive` lock
- Example values: integration test asserts the orchestrator's commit-sequence log shows `TRUNCATE COMMIT` events at index 0..1 (TRUNCATE + cleanup-of-indices commits) BEFORE any `POST /api/v1/clusters` log entry

### AC-16: Advisory lock is held on a pinned `AsyncConnection` across all commits

- Given a reseed is in progress (after TRUNCATE commit, before final rename commit)
- When an observer connection (separate from the reseed handler's `lock_conn`) queries `SELECT classid, objid FROM pg_locks WHERE locktype = 'advisory' AND objid = <expected lock objid for the demo:reseed key>`
- Then exactly one matching row is observed throughout the reseed
- And after the reseed's `finally` block calls `pg_advisory_unlock(:k)`, the row is no longer observed (`pg_advisory_unlock` returned `true`)
- And during the reseed's lifetime, the lock-holding connection's PID (`pg_locks.pid`) is the SAME across multiple observer queries — i.e., the lock did not migrate to a different pooled connection across the reseed's intermediate commits
- Example values: integration test runs the reseed and concurrently queries `pg_locks` from a sibling `AsyncEngine.connect()`; asserts (a) row present after TRUNCATE commit, (b) row present after a self-call's commit, (c) row absent after the handler returns 200, (d) `pid` matches across observations.

### AC-15: Dual httpx-client contract is enforced (no client-role mixing)

- Given the reseed orchestrator runs
- When the integration test inspects the request log on the API server side AND on the ES/OS containers
- Then every FastAPI loopback call (`POST /api/v1/clusters` etc.) is delivered to `localhost:8000`
- And every direct engine call (`PUT /{target}`, `_doc`, `_refresh`, `DELETE /{idx}`) is delivered to `elasticsearch:9200` or `opensearch:9201` (per the per-scenario `host_base_url`)
- And no FastAPI route receives an ES-shaped request (`PUT /products` would 404 against `/api/v1/...`)
- And no ES/OS request authenticates with anything other than the per-scenario basic-auth tuple
- Example values: integration test asserts the API access log shows no `PUT /products` events and the ES container's access log shows no `POST /api/v1/clusters` events.

### AC-14: Cleanup runs only after Python control returns to the orchestrator (no late-commit race for natural failures)

- Given the reseed orchestrator raises a Python-level exception (e.g., the integration test patches the 3rd `POST /api/v1/clusters` call to return HTTP 500)
- When the route handler catches the exception
- Then cleanup begins ONLY after the failed self-call has returned a definitive response (HTTP 500 in this test; the client-side await has resolved, the server-side handler has finished writing its response). Python control is fully back in the orchestrator before cleanup starts.
- And after the 503 returns, the demo tables are empty (cleanup TRUNCATEd everything the failed self-call may have committed before its 500).
- **Note on per-call timeout edge case:** if the failure is a `httpx.ReadTimeout` (per-call HTTP ceiling exceeded), the residual risk documented in §10 Threat 4 applies — the server-side handler may complete after cleanup. AC-14 specifically asserts that for **non-timeout** exception paths cleanup is race-free; the timeout edge case is covered by the operator-retries-the-reseed recovery model.

## 13) Non-functional requirements

- **Performance:** the reseed should complete in <15s on a warm dev stack (Postgres + ES + OS already running). The per-call HTTP ceiling (`demo_reseed_per_call_http_timeout_s`, default 120s — FR-4b) accommodates cold-start ES + OS heap allocation on slow laptops. There is NO outer wall-clock budget for the reseed as a whole (per FR-4).
- **Reliability:** the cleanup pass on 503 means the worst-case observed state for natural-exception failures is "empty stack" — the operator's stack never lands in a partial-seeded state that breaks the dashboard's row-count signals. The one edge case (per-call `httpx.ReadTimeout` racing a server-side late commit) is documented in §10 Threat 4 with **`docker compose restart api` + retry** as the safe recovery — naive in-process retry is NOT safe on the timeout edge.
- **Operability:** structured logs at INFO for `demo_reseed_started`, `demo_reseed_completed` (with `duration_ms`), `demo_reseed_failed` (with `error_code` + exception class). No new metrics or alerts (dev-only surface).
- **Accessibility:** the `<details>` element is keyboard-navigable by default. The `<AlertDialog>` follows the existing primitive's a11y contract (focus trap, ESC closes, ARIA `role="alertdialog"`).

## 14) Test strategy requirements

- **Unit tests** (`backend/tests/unit/services/test_demo_seeding.py`): cover the `ReseedSummary` model construction, the `_demo_reseed_lock_key()` helper (returns the deterministic blake2b → signed int64), and the table-list constant (asserts the 10-table TRUNCATE order matches `scripts/seed_meaningful_demos.py:67-78`). LLM and HTTP calls are mocked at this layer.
- **Integration tests** (`backend/tests/integration/test_demo_seeding.py`, marked `@pytest.mark.integration`): cover AC-1, AC-2, AC-3, AC-5, AC-12, AC-13, AC-14 against real Postgres + real ES + real OS service containers — these all assert deterministic post-cleanup empty state (no timeout-edge race). AC-4 (per-call HTTP ceiling exceeded) asserts HTTP 503 with `detail.error_code == "SEED_FAILED"` only; the spec intentionally does NOT assert deterministic post-cleanup emptiness OR in-process retry-restores-state on the timeout edge (per §10 Threat 4, the safe recovery requires `docker compose restart api`, which is out of scope for the integration test runner).
- **Contract tests** (`backend/tests/contract/test_test_endpoint_guard.py` extension + `backend/tests/contract/test_openapi_surface.py` extension): cover AC-6 (env guard 404) and the OpenAPI-surface registration of the new endpoint.
- **Vitest** (`ui/src/__tests__/components/dashboard/start-here-checklist.spec.tsx`): cover AC-7, AC-8, AC-9 (disclosure visibility + dialog open/close + Cancel-without-POST).
- **Playwright E2E** (`ui/tests/e2e/dashboard-reseed.spec.ts`, real-backend): covers AC-10 end-to-end — wipe via existing `/_test/*` DELETEs → navigate to `/` → click disclosure → button → Confirm → assert toast + dashboard refetch with 4 clusters. NO `page.route()` mocking (CLAUDE.md §"E2E Testing Rules").

## 15) Documentation update requirements

- **`docs/01_architecture/api-conventions.md`** — add the 2 new error codes (`SEED_FAILED`, `SEED_IN_PROGRESS`) to the error-code registry (§"Common error codes").
- **`docs/03_runbooks/demo-reseed-debugging.md`** — new runbook covering: how to call the endpoint manually with curl, how to interpret each error code, how to inspect the advisory lock state via `SELECT * FROM pg_locks WHERE locktype = 'advisory'`, and how to clear a stuck session-level advisory lock if the API process crashed mid-reseed (the lock auto-releases when the holding connection drops — which happens automatically on `docker compose restart api`; in the rare case the connection survives, `SELECT pg_advisory_unlock(<key>)` from the same connection or, as a last resort, `docker compose restart postgres`).
- **`docs/00_overview/implemented_features/<date>_feat_home_demo_reseed_endpoint/`** — finalization PR moves this folder there per the project's planned-features lifecycle.
- **`CLAUDE.md`** — no update (no new conventions, no new rules; the dev-only-endpoint pattern is already documented from `infra_e2e_seed_completed_study`).
- **`state.md`** — update on finalization PR to note the feature shipped.

## 16) Rollout and migration readiness

- **Feature flags:** none. The `_require_development_env` dependency IS the feature flag; deployments with `ENVIRONMENT != "development"` never see the surface.
- **Migration/backfill:** none. No schema change.
- **Operational readiness:** no remote staging to validate against (MVP1). Local validation via `make up && curl -X POST http://localhost:8000/api/v1/_test/demo/reseed` and the Playwright suite is the readiness signal.
- **Release gate:** all CI jobs green (lint, typecheck, unit, integration, contract, Vitest, Playwright real-backend, Next.js build, Docker build). No Gemini High-severity unresolved findings.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 (service module) | AC-1, AC-2 | Story 1: implement `backend/app/services/demo_seeding.py` | `backend/tests/unit/services/test_demo_seeding.py`, `backend/tests/integration/test_demo_seeding.py` | — |
| FR-2 (endpoint) | AC-1, AC-2, AC-3, AC-4, AC-5, AC-6 | Story 2: implement `POST /api/v1/_test/demo/reseed` in `_test.py` | Integration + contract tests above | `docs/01_architecture/api-conventions.md` |
| FR-3 (session-level advisory lock + connection pinning) | AC-3, AC-12, AC-16 | Story 2 (sub-task) | Integration tests AC-3 + AC-12 + AC-16 | — |
| FR-4 (no outer timeout) | AC-14 | Story 2 (sub-task) | Integration test AC-14 | — |
| FR-4b (per-call HTTP timeout setting) | AC-4 | Story 1 (sub-task — settings PR file) | Unit test for the field validator | — |
| FR-1 commit-ordering (TRUNCATE-before-self-call) | AC-13 | Story 1 (sub-task) | Integration test AC-13 | — |
| FR-1 dual-client contract (api_client vs engine_client) | AC-15 | Story 1 (sub-task) | Integration test AC-15 | — |
| FR-1d (engine base-URL resolver) | AC-15 | Story 1 (sub-task) | Unit test for `_resolve_engine_base_url` (ES, OS, ValueError branches) + integration test AC-15 asserting requests reach `elasticsearch:9200` / `opensearch:9201` | — |
| FR-5 (superseded) | — | — | — | — |
| FR-6 (UI button) | AC-7, AC-8, AC-9, AC-10, AC-11 | Story 3: extend `StartHereChecklist` + add toast + invalidation | `ui/src/__tests__/components/dashboard/start-here-checklist.spec.tsx`, `ui/tests/e2e/dashboard-reseed.spec.ts` | — |
| FR-7 (contract test extension) | AC-6 | Story 4: extend contract tests | `backend/tests/contract/test_test_endpoint_guard.py`, `backend/tests/contract/test_openapi_surface.py` | — |
| FR-8 (integration test) | AC-1..AC-5 | Story 4: integration suite | `backend/tests/integration/test_demo_seeding.py` | — |
| FR-9 (vitest) | AC-7..AC-9 | Story 3 (sub-task) | Vitest spec above | — |
| FR-10 (E2E) | AC-10 | Story 5: Playwright real-backend E2E | `ui/tests/e2e/dashboard-reseed.spec.ts` | — |

## 18) Definition of feature done

- [ ] All acceptance criteria in §12 (AC-1 through AC-16) pass in CI.
- [ ] All test layers (unit/integration/contract/vitest/e2e) are green.
- [ ] `docs/01_architecture/api-conventions.md` lists the 3 new error codes.
- [ ] `docs/03_runbooks/demo-reseed-debugging.md` exists.
- [ ] `state.md` reflects the feature's shipped status (via finalization PR).
- [ ] No open questions remain in §19.
- [ ] Gemini Code Assist has zero High-severity unresolved findings.

## 19) Open questions and decision log

### Open questions

(none — all 3 idea Open Questions resolved below in the Decision log)

### Decision log

- **2026-05-22 (locked at idea stage) — D1: `httpx.AsyncClient` self-call over service-function extraction.** Rationale: the CLI proves the HTTP-orchestration path is correct; calling internal service functions directly would require auditing every endpoint's transaction-boundary semantics for compatibility with the bulk-loop usage. The HTTP path is cheaper to ship and the operator-visible behavior is identical.
- **2026-05-22 (locked at idea stage) — D2: CLI script `scripts/seed_meaningful_demos.py` unchanged in this phase.** Rationale: unifying CLI + service module would couple this feature's risk surface to a working CLI tool and double the test matrix. The new `demo_seeding.py` imports the `SCENARIOS` constant from the CLI module (single source of scenario data) but reimplements the per-scenario flow in async form.
- **2026-05-22 (locked at idea stage) — D3: `Settings.demo_reseed_timeout_s` default 60s, configurable.** Initial decision (superseded — see entry below): per `asyncio.wait_for` wall-clock budget.
- **2026-05-23 (GPT-5.5 cycles 2 + 3) — D3 superseded: drop the global wall-clock budget; per-call HTTP ceiling only (`demo_reseed_per_call_http_timeout_s`, default 120s).** Rationale: client-side cancellation (whether via outer `asyncio.wait_for` or per-call `httpx.ReadTimeout`) cannot prove server-side handler completion; cleanup that runs after client-side cancellation can race late server-side commits, leaving partial demo rows. The only safe design is to let the reseed run to natural Python-level completion (return or raise) and run cleanup only after the orchestrator has returned control. The per-call ceiling is retained as a hard upper bound on individual HTTP calls (default 120s — a wide margin over the 5-10s typical scenario time). Residual risk: a single self-call's `httpx.ReadTimeout` can still leave 1-2 demo rows behind if the server-side handler completes post-cleanup; cycle 11 further tightened the recovery contract to require `docker compose restart api` before retry (naive in-process retry is itself unsafe on this edge) — documented in §10 Threat 4.
- **2026-05-23 — Q1 (idea open question): Concurrent reseed guard.** Initial decision (superseded — see next entry): `pg_try_advisory_xact_lock`. Rationale: matches `backend/workers/digest.py` + `backend/workers/orchestrator.py`.
- **2026-05-23 — Q1 follow-up (GPT-5.5 cross-model cycle 1, accepted with cited evidence): Lock primitive changed to session-level `pg_try_advisory_lock`.** Rationale: the reseed inherently spans multiple committed transactions (TRUNCATE commit → per-self-call commits → rename commit → cleanup commit). A transaction-scoped lock would release after the TRUNCATE commit, leaving the rest of the operation unprotected and allowing a second caller's reseed to race with the first caller's cleanup pass. Lock key derivation unchanged (`blake2b(b"demo:reseed", digest_size=8)` → signed int64). Explicit `pg_advisory_unlock(:k)` in `finally`.
- **2026-05-23 — Q2 (idea open question): UI button placement.** Decision: adopt the recommended default — the button lives inside `StartHereChecklist` behind a `<details>` disclosure with summary text `"or skip ahead — reset to demo state"`. Rationale: keeps the disclosure secondary (the 3-step onboarding list is the primary affordance), gives the disclosure clear contextual ownership (it's part of the empty-state surface), and avoids adding a fourth top-level dashboard card.
- **2026-05-23 — Q3 (idea open question): Partial-state recovery on `SEED_FAILED`.** Decision: adopt the recommended default — on 503, the endpoint attempts a best-effort cleanup pass (re-TRUNCATE Postgres tables + re-DELETE the 4 demo indices, tolerating every error). The cleanup outcome is logged at INFO. Rationale: an empty-stack failure mode is debuggable; a partial-state failure mode requires the operator to drop back to the CLI to clean up — which defeats the feature's purpose. The 504 path was removed entirely by the GPT-5.5 cycle-3 redesign — see decision-log entry below.
- **2026-05-23 — Scenario list source of truth: import, not copy.** Decision: `demo_seeding.py` imports `SCENARIOS` from `scripts/seed_meaningful_demos.py`. Rationale: avoids drift between CLI and endpoint; the `SCENARIOS` constant is a plain list of dicts with no executable code, so the import has no side effects. The implementation plan must verify the `scripts/` package is importable from `backend/app/services/` — confirmed: `scripts/` is in the Python path under the existing pyproject layout.
- **2026-05-23 — Cleanup-on-failure scope.** Decision: cleanup runs on every orchestrator failure that returns 503 to the caller, including the `httpx.ReadTimeout` edge case. There is no 504 path (per the GPT-5.5 cycle-3 redesign — `SEED_TIMEOUT` was removed entirely). All exception unwinds funnel into the same cleanup routine before raising `_err(503, ...)`.
- **2026-05-23 — Audit event deferred.** Decision: do NOT wire `demo.reseed.completed` audit emission today. Rationale: `audit_log` table doesn't exist until MVP2. The §6 audit-event placeholder + the runbook reminder are sufficient to ensure the wiring happens at MVP2.
- **2026-05-23 — GPT-5.5 cycle 1: transaction shape redesign.** Rationale: GPT-5.5 raised 4 High-severity findings (Pass A ×2, Pass B ×2) all converging on the same root issue — the initial spec held the TRUNCATE inside the outer route handler's session and described the reseed as "atomic / rolled back on failure." This was incorrect because (a) TRUNCATE's `AccessExclusive` locks would deadlock the subsequent `httpx` self-calls, (b) each self-call commits its own transaction (outer rollback cannot undo committed inserts), (c) `pg_try_advisory_xact_lock` would release after the TRUNCATE commit, leaving the rest unprotected, (d) `asyncio.wait_for` cancellation cannot revoke a self-call's already-committed write. The redesigned spec adopts the correct invariant: cleanup re-wipes the stack on every failure, the session-level advisory lock is held until cleanup commits, and TRUNCATE commits before any self-call. AC-12 (cleanup-while-locked race) and AC-13 (TRUNCATE-before-self-call ordering) added to lock the new design into the test suite.
- **2026-05-23 — GPT-5.5 cycle 2: timeout mechanism redesign (drop outer `asyncio.wait_for`).** Initial cycle-2 fix (superseded by cycle 3 — see next entry): introduce per-self-call timeout + between-call deadline check; remove outer `asyncio.wait_for`.
- **2026-05-23 — GPT-5.5 cycle 3: drop the wall-clock budget entirely (supersedes cycle 2's between-call deadline check).** Rationale: GPT-5.5 cycle 3 raised 2 High-severity findings — (a) residual `asyncio.wait_for` text in §3 Scope B + §10 Threat 4 contradicted FR-4 (now purged), and (b) the cycle-2 per-call `httpx.ReadTimeout` mechanism still cannot prove server-side completion: an `httpx` client-side timeout does NOT cancel the server-side FastAPI handler, which may commit after cleanup runs. **Final fix:** remove `SEED_TIMEOUT` (code, AC-4 504-path, AC-14 between-call check). The reseed runs to natural Python-level completion. The only timeout setting is `demo_reseed_per_call_http_timeout_s` (FR-4b, default 120s) — a hard ceiling that surfaces as 503 `SEED_FAILED` if it fires. AC-14 rewritten to assert "cleanup runs only after Python control returns to the orchestrator" (true by construction). The residual risk on `httpx.ReadTimeout` is documented in §10 Threat 4 and the operator-retries-the-reseed recovery model is locked in §11 Edge flows.
- **2026-05-23 — GPT-5.5 cycle 4: residual stale-text cleanup.** Rationale: GPT-5.5 cycle 4 raised 2 High-severity findings — both were residual contradictions left over from cycle 3 (§7.4 still listed `SEED_TIMEOUT`, §9 still mentioned `demo_reseed_timeout_s`, §13 still said "default timeout 60s", §14 test strategy still said "set `demo_reseed_timeout_s=1` and assert 504", §19 Q3 still said "on 503 (or 504)"). All purged. The spec now has a single coherent timeout story: per-call HTTP ceiling only, no global wall-clock cancellation, single `SEED_FAILED` error code on failure.
- **2026-05-23 — GPT-5.5 cycle 5: dual-client design.** Rationale: GPT-5.5 cycle 5 raised 1 High-severity finding — the spec's single `httpx.AsyncClient` parameter could not address both the FastAPI loopback (`http://localhost:8000/api/v1/...`, no auth) and the direct ES/OS calls (`http://elasticsearch:9200/{target}`, basic-auth `("elastic","changeme")`; `http://opensearch:9201/{target}`, basic-auth `("admin","admin")`) — they have different base URLs AND different auth schemes. **Fix:** the orchestrator takes two `httpx.AsyncClient` parameters (`api_client`, `engine_client`) and the spec now explicitly maps each CLI operation to the appropriate client (FR-1 + §3 In-scope A Step 2). AC-15 added to lock the no-client-role-mixing invariant into integration tests. Both clients share the same per-call HTTP timeout (`demo_reseed_per_call_http_timeout_s`).
- **2026-05-23 — GPT-5.5 cycle 12: align toast/UX wording with the tightened recovery contract.** Rationale: cycle 12 caught that the FR-6 / §11 / AC-11 / §13 toast text + reliability claim still said "Try again" for any 503 — but on the ReadTimeout edge that's exactly what cycle 11 just declared unsafe. The toast is updated to `"Reseed failed: {error_code}. If this followed a hang or timeout, run \`docker compose restart api\` before retrying; otherwise see the demo-reseed runbook or run \`make seed-demo FORCE=1\` from the host."` — keeping the immediate-retry option for natural-exception failures (where it IS safe) while explicitly directing the operator to the restart-then-retry path on the timeout edge. §13 Reliability now reflects the same nuance. The cycle-3 decision-log entry's stale "second reseed wipes again; safe on dev data" wording is also revised.
- **2026-05-23 — GPT-5.5 cycle 11: tighten ReadTimeout recovery contract.** Rationale: GPT-5.5 cycle 11 raised 1 High-severity finding — the cycle-3 documented recovery ("operator retries the reseed") was itself unsafe on the `httpx.ReadTimeout` edge because the abandoned server-side handler's late commit could race the retry's TRUNCATE, contaminating the second reseed's state. **Fix:** §10 Threat 4 + FR-4 + §11 Edge flows now state the safe recovery is **`docker compose restart api` then retry** — the restart drops the abandoned handler's DB connection (releasing both its session and the advisory lock, per FR-3 connection-bound semantics). AC-4 + FR-8 + §14 updated so the integration test asserts only the 503 + error_code on the timeout edge, NOT in-process retry restores state (the safe retry requires Compose orchestration outside the test runner's scope). The toast wording continues to direct the operator to the runbook, where the restart-then-retry procedure is documented.
- **2026-05-23 — GPT-5.5 cycles 9 + 10: DoD + final 504 cleanup.** Two trivial residuals patched in two cycles — §9 still mentioned "retry after 409/503/504"; §18 DoD only required AC-1..AC-11 (missed AC-12..AC-16). Both fixed.
- **2026-05-23 — GPT-5.5 cycle 8: timeout-edge wording cleanup.** Rationale: GPT-5.5 cycle 8 raised 2 High-severity findings flagging residual contradictions between FR-4 / §10 Threat 4 (which correctly document the `httpx.ReadTimeout` residual race + retry-recovery model) and §3 In-scope B + AC-4 + FR-8 + §14 (which still asserted "any orchestrator exception → cleanup cannot race a late commit" and "post-cleanup empty state" universally). All four sites now distinguish the **non-timeout** failure path (race-free cleanup, deterministic empty state asserted) from the **`httpx.ReadTimeout`** path (best-effort cleanup, retry-restores-demo-state asserted). The spec now has a single internally-consistent failure-handling story.
- **2026-05-23 — GPT-5.5 cycle 7: in-container engine base-URL resolver.** Rationale: GPT-5.5 cycle 7 raised 1 High-severity finding — the imported `SCENARIOS` constant from the CLI carries `host_base_url` values pointing at `localhost:9200/9201` (the host-shell's port-published ES/OS endpoints), but inside the API container `localhost` resolves to the API container itself, not the host. The CLI MUST stay unchanged (D2 lock); the service MUST translate. **Fix:** add `_resolve_engine_base_url()` (FR-1d) — a pure hardcoded mapping `localhost:9200 → elasticsearch:9200` and `localhost:9201 → opensearch:9201`. Unit-tested with explicit ValueError fallback for unrecognized URLs (defense against future CLI scenario additions). FR-1 + §3 In-scope A Step 2 + Step 1b updated to apply the resolver. AC-15 already asserts requests reach the Compose DNS names, which validates the resolver is wired correctly.
- **2026-05-23 — GPT-5.5 cycle 6: advisory-lock connection-pinning design.** Rationale: GPT-5.5 cycle 6 raised 2 High-severity findings — (a) FR-3 assumed `AsyncSession` retains its underlying physical connection across commits, but by default SQLAlchemy returns the connection to the pool on commit. Session-level Postgres advisory locks are connection-bound (not session-object-bound), so post-commit a different pooled connection could be checked out, making `pg_advisory_unlock` run on the wrong connection (lock leaks) AND allowing a concurrent caller to acquire `pg_try_advisory_lock` on the same pooled connection (Postgres advisory locks are reentrant within a connection); (b) the AC-3/AC-12 concurrency tests could pass by accident depending on pool checkout order, leaving the connection-affinity invariant untested. **Fix:** FR-3 now mandates a dedicated `AsyncConnection` (`async with engine.connect() as lock_conn`) checked out independently of the request's `AsyncSession`, used SOLELY for `pg_try_advisory_lock` and `pg_advisory_unlock`. The lock connection is pinned for the request lifetime and explicitly closed in `finally`. AC-16 added to assert via observer-connection `pg_locks` queries that exactly one advisory-lock row is held throughout the reseed AND that the lock-holding `pid` does not migrate across intermediate commits. §15 runbook reference updated to describe lock-state inspection via `pg_locks` and the auto-release-on-connection-drop recovery.
