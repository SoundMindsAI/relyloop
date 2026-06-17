# Feature Specification — Selective Engine Provisioning (Startup + Reset-to-Demo)

**Date:** 2026-06-17
**Status:** Draft
**Owners:** Product: relevance engineer (operator persona). Engineering: maintainer.
**Cross-model review:** Opus self-review (GPT-5.5 unreachable in Claude Code remote sandbox per CLAUDE.md "Environment-aware fallback"; Gemini Code Assist remains the cross-family gate at the code/PR stage).
**Related docs:**
- [idea.md](idea.md) — origin brief (preflighted 2026-06-17)
- [docs/01_architecture/deployment.md](../../../../01_architecture/deployment.md) — Compose engine services + secrets posture
- [docs/03_runbooks/local-dev.md](../../../../03_runbooks/local-dev.md) — `make up` quickstart
- [docs/03_runbooks/demo-reseed-engine-tolerance.md](../../../../03_runbooks/demo-reseed-engine-tolerance.md) — partial-completion contract (engine reachability)
- [docs/01_architecture/api-conventions.md](../../../../01_architecture/api-conventions.md) — error envelope, routing
- Sibling (coordinate-only): [`infra_pr_yml_split_integration_by_service`](../infra_pr_yml_split_integration_by_service/idea.md)

---

## 1) Purpose

**Problem.** Today `make up` pulls and boots **all three** engines — `elasticsearch:9.4.1`, `opensearchproject/opensearch:3.6.0`, `solr:10.0` ([docker-compose.yml:331](../../../../../docker-compose.yml#L331), [:356](../../../../../docker-compose.yml#L356), [:392](../../../../../docker-compose.yml#L392)). For an operator evaluating RelyLoop against a single engine, two of three image pulls and two JVM boots are dead weight. Likewise the "Reset to demo state" button ([ui/src/components/dashboard/reset-demo-state-button.tsx](../../../../../ui/src/components/dashboard/reset-demo-state-button.tsx)) reseeds across **all** reachable engines with no way for the operator to pick a subset.

**Outcome.** The operator can opt-in at install time to a subset of engines (`RELYLOOP_ENGINES=es` → only Elasticsearch pulled and started → measurably faster `make up`) and can pick a subset of running engines on the reset-to-demo modal. The default for both is "all three" so the current operator experience is preserved unless the operator opts in.

**Non-goal.** Switching engine versions from the browser. Engine versions are a startup/Compose concern (the API container has no Docker socket and no authority to pull images or restart engine services); changing versions still requires re-running `make up`. Version *selection* at install time is deferred to Phase 2.

## 2) Current state audit

### Existing implementations

| File / artifact | What it does today | API / interface | Notes |
|---|---|---|---|
| [docker-compose.yml:331-405](../../../../../docker-compose.yml#L331-L405) | Defines `elasticsearch`, `opensearch`, `solr` services pinned to `9.4.1` / `3.6.0` / `10.0`. | Compose | **No `profiles:` field** — every service is in the default `up` set. Image tags are hardcoded (only `BASE_REGISTRY`, `ES_HEAP_SIZE`, `SOLR_HEAP_SIZE` are env-parameterized). |
| [scripts/install.sh:96-105](../../../../../scripts/install.sh#L96-L105) | Runs `docker compose up -d --wait` after building images. | Bash | No engine selection step. Honors `RELYLOOP_SKIP_BUILD` and `RELYLOOP_SKIP_AUTO_SEED`. |
| [scripts/install.sh:107-126](../../../../../scripts/install.sh#L107-L126) | Auto-seeds demo data when stack is empty (`seed_meaningful_demos.py --if-empty`). | Python via `docker compose exec` | Idempotent; non-fatal on failure. Already engine-tolerant (skips unreachable engines via `is_engine_reachable`). |
| [backend/app/api/v1/_test.py:602-699](../../../../../backend/app/api/v1/_test.py#L602-L699) | `POST /api/v1/_test/demo/reseed` enqueues an Arq job and returns `202 + ReseedStatusResponse`. | FastAPI route, `_require_development_env` gate | Currently takes **no request body** (idempotency keyed on `"demo_reseed:singleton"`). Returns 409 `SEED_IN_PROGRESS` on overlap. |
| [backend/app/api/v1/_test.py:702-736](../../../../../backend/app/api/v1/_test.py#L702-L736) | `GET /api/v1/_test/demo/reseed/status` returns the current Redis-backed status. | FastAPI route | Returns `idle` not 404 when no run exists, so polling is trivially safe. |
| [backend/app/services/demo_seeding.py:446-485](../../../../../backend/app/services/demo_seeding.py#L446-L485) | `is_engine_reachable(url, engine_type)` — 2s-timeout GET probe of `/` (ES/OS) or `/solr/admin/info/system`. | async function | Already returns False on any error; never raises. |
| [backend/app/services/demo_seeding.py:488-523](../../../../../backend/app/services/demo_seeding.py#L488-L523) | `snapshot_engine_reachability()` — one-shot per-URL cache for the run. | async function | Probes each unique engine URL once. |
| [backend/app/services/demo_seeding.py:1562-1742](../../../../../backend/app/services/demo_seeding.py#L1562-L1742) | `reseed_demo_state()` scenario loop — per-scenario reachability gate at line 1578 → adds slug to `progress.scenarios_skipped` on unreachable. | async function | Implements partial-completion contract. `status=complete` with non-empty `scenarios_skipped` is NOT a failure (per CLAUDE.md). |
| [backend/app/services/demo_seeding.py:210](../../../../../backend/app/services/demo_seeding.py#L210) | `AllEnginesUnreachableError` — raised when every scenario was skipped → `failed_reason="all_engines_unreachable"`. | Exception | Worker maps this to terminal `failed` state. |
| [ui/src/components/dashboard/reset-demo-state-button.tsx](../../../../../ui/src/components/dashboard/reset-demo-state-button.tsx) | The "Reset to demo state" button + confirmation dialog + live progress UI. | React component | Rendered inside [`start-here-checklist.tsx:56`](../../../../../ui/src/components/dashboard/start-here-checklist.tsx#L56) on the home dashboard `/`. POSTs to `/api/v1/_test/demo/reseed` with **no body**. |
| [ui/src/lib/api/demo-reseed.ts](../../../../../ui/src/lib/api/demo-reseed.ts) | TanStack Query hook `useDemoReseedStatus` polling every 2s while `status === 'running'`; stops on any terminal state. | Hook | Inlined `ReseedStatusResponse` type; matches backend `ReseedStatusResponse` in `backend/app/services/demo_seeding.py`. |
| [ui/src/lib/enums.ts:42-44](../../../../../ui/src/lib/enums.ts#L42-L44) | `ENGINE_TYPE_VALUES = ['elasticsearch', 'opensearch', 'solr']` cites `backend/app/api/v1/schemas.py EngineTypeWire`. | TS `as const` array | Already the canonical frontend mirror of the backend `EngineTypeWire = Literal[...]`. |
| [backend/app/api/v1/schemas.py:315](../../../../../backend/app/api/v1/schemas.py#L315) | `EngineTypeWire = Literal["elasticsearch", "opensearch", "solr"]`. | Pydantic Literal | Canonical backend allowlist for engine type wire values. |
| [backend/app/services/demo_seeding.py:443](../../../../../backend/app/services/demo_seeding.py#L443) | Module-local `_EngineType = Literal["elasticsearch", "opensearch", "solr"]`. | Literal alias | **Duplicates** the canonical `EngineTypeWire`. Either consolidates onto the canonical one or stays local — call out as a discoverable cleanup, not a blocker. |
| [.github/workflows/pr.yml:439](../../../../../.github/workflows/pr.yml#L439), [:455](../../../../../.github/workflows/pr.yml#L455) | Backend test lane declares `elasticsearch:9.4.1` and `opensearchproject/opensearch:3.6.0` as **GitHub Actions service containers**, NOT via the Compose engine services. | GHA service container | **Decoupled from `docker-compose.yml`** — Compose `profiles:` changes will not affect backend CI. |
| [.github/workflows/pr.yml:848](../../../../../.github/workflows/pr.yml#L848), [:887](../../../../../.github/workflows/pr.yml#L887) | Smoke job uses `make up` and references all three engines. | GHA job | Currently gated OFF by `SMOKE_TEST` repo variable (default unset). When enabled, it DOES exercise the Compose path. |

### Navigation and link impact

| Source file | Current link target | New link target |
|---|---|---|
| None — Phase 1 adds a modal to an existing button (no route changes, no new pages). | — | — |

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `backend/tests/integration/services/test_demo_seeding_*.py` | Scenario-loop tests asserting `scenarios_skipped` is a `list[str]` of slugs | several | Update assertions to accept the new structured form (Phase 1 adds a `reason` field per skip). Backward-compatible if we keep `scenarios_skipped: list[str]` and add a sibling `scenarios_skipped_reasons: dict[str, "user_excluded" | "unreachable"]` — verify in plan. |
| `backend/tests/contract/api/v1/test__test_demo_reseed.py` (or equivalent) | Contract test for the POST body (currently empty) | 1+ | Add cases: `{engines: ["elasticsearch"]}` accepted (200/202); `{engines: ["nope"]}` rejected with 422 `VALIDATION_ERROR`; empty body still accepted (defaults to "all running"). |
| `backend/tests/contract/api/v1/test_openapi_surface.py` | Asserts the demo-reseed wire shape matches the inlined frontend type | 1 | Refresh after schema change; if OpenAPI drift triggers `ui/openapi.json` regen, the generated-artifacts-fresh gate fires. |
| `ui/src/components/dashboard/__tests__/reset-demo-state-button.test.tsx` (if exists) | Component-level test of the dialog | — | Add cases: engine checkboxes render, default to "all running checked", omit/include `engines` in the request body, render skipped-reasons differently for user-excluded vs unreachable. |
| `ui/tests/e2e/demo-ubi.spec.ts` | E2E covering the demo reseed flow | 1 | Currently CI-excluded via `testIgnore` per [`infra_smoke_reseed_runtime_budget`](../../../implemented_features/2026_06_02_infra_smoke_reseed_runtime_budget/). Update locally to exercise the new modal; CI exclusion holds. |

### Existing behaviors affected by scope change

- **`scenarios_skipped` semantics today** — append-only list of slugs skipped because their engine was unreachable. **New** — same list still populated, but each entry's reason is now discriminated. Operator-visible change: the partial-completion footer renders "X skipped (you excluded), Y skipped (engine down)" instead of the conflated "X skipped." Decision needed: **no** (the spec proposes the structured form; backward compatibility preserved via additive sibling field).
- **`make up` default behavior today** — pulls + starts all three engines. **New** — unchanged when no engine selection is provided (preserves first-run UX). Decision needed: **no** (default is explicit non-regression).
- **CI smoke-job behavior** — if/when SMOKE_TEST is enabled, it does `make up` and expects all three engines. **New** — smoke job MUST set `COMPOSE_PROFILES=es,os,solr` (or equivalent) explicitly so the operator default behind a subset doesn't reduce smoke coverage. Decision needed: **no** (the spec mandates explicit opt-in for the smoke job).

---

## 3) Scope

### In scope (Phase 1)

- A1. Compose `profiles:` per engine service (`es`, `os`, `solr`); default behavior preserved by including all three when no profile selection is provided.
- A2. `scripts/install.sh` recognizes `RELYLOOP_ENGINES` env var; translates to `COMPOSE_PROFILES` on the Compose invocation. Default unset = all three.
- A3. `make up` documents `RELYLOOP_ENGINES` in `make help` / `.env.example`.
- A4. CI smoke job (`.github/workflows/pr.yml`) sets `COMPOSE_PROFILES=es,os,solr` explicitly when invoking `make up` so coverage doesn't drop with an operator-default change.
- B1. `POST /api/v1/_test/demo/reseed` accepts an optional request body `{engines: ["elasticsearch", "opensearch", "solr"] | null}`. Null/missing = all running engines (current behavior). The backend filters `SCENARIOS` to those whose `engine_type` is in the selected set, then applies the existing reachability gate.
- B2. The reseed `ReseedStatusResponse.scenarios_skipped` shape is extended with a structured form. Two acceptable designs (locked in §19 D-1):
   - **D-1 chosen:** `scenarios_skipped: list[str]` stays as-is for backward compat; a new sibling field `scenarios_skipped_reasons: dict[str, "user_excluded" | "unreachable"]` carries the reason per slug.
- B3. New backend capability endpoint `GET /api/v1/_test/demo/engines` returns the set of engines currently running (reachability-probed) so the frontend modal can populate checkboxes without inventing an option list. Response shape: `{engines: [{engine_type: "elasticsearch", reachable: true}, ...]}`.
- B4. Frontend reset-to-demo modal: when the operator clicks "Reset to demo state," fetch `/api/v1/_test/demo/engines` to render an engine checkbox group. All running engines checked by default. The confirmation POST passes the selected list. The progress card displays user-excluded skips distinctly from unreachable skips.
- B5. The streaming UX stays on the existing 2s Redis poll — see §19 D-2 for the decision. The existing `useDemoReseedStatus` already renders incremental `current_step` updates and a deduped step log; Phase 1 makes no SSE change.

### Out of scope (Phase 1)

- Version selection at install time (`ES_IMAGE_TAG`/`OS_IMAGE_TAG`/`SOLR_IMAGE_TAG` env vars, curated version matrix, install.sh version flags). **Tracked:** [phase2_idea.md](../../planned_features/02_mvp2/feat_engine_version_selection/idea.md).
- Version display in the reset-to-demo modal. ES/OS have no version-report path today; adding one for the reset modal alone is not justified. **Tracked:** [phase2_idea.md](../../planned_features/02_mvp2/feat_engine_version_selection/idea.md).
- SSE migration of the reseed status endpoint. The existing 2s poll already streams step-by-step progress; defer SSE until measured insufficiency. **Tracked:** [phase3_idea.md](../../planned_features/02_mvp2/feat_reseed_status_sse_streaming/idea.md).
- Auto-discovering engine versions from Docker Hub at runtime (would break the corp-network/air-gapped install posture).
- Giving the API container Docker control (out of architectural bounds).
- Interactive TTY prompts in `install.sh` for engine selection (env-driven only — keeps CI and scripted installs unaffected).
- Removing any of the three engines from `docker-compose.yml`. All three remain defined; `profiles:` just makes them opt-in.

### API convention check

- **Endpoint prefix:** `/api/v1/<resource>` for business endpoints; this feature touches the existing `/api/v1/_test/demo/...` namespace (already established by the demo-reseed feature in `_test.py`).
- **Router namespace:** [`backend/app/api/v1/_test.py`](../../../../../backend/app/api/v1/_test.py) — the new `GET /api/v1/_test/demo/engines` endpoint MUST live in this file alongside the existing reseed endpoints (gated by `_require_development_env`).
- **HTTP methods for CRUD:** N/A — this is a query-only capability + an existing async-trigger.
- **Non-auth error envelope shape (verified [backend/app/api/errors.py](../../../../../backend/app/api/errors.py)):**
  ```json
  {"detail": {"error_code": "<CODE>", "message": "<human>", "retryable": <bool>}}
  ```
- **Auth error shape:** N/A (RelyLoop is single-tenant + no auth through MVP3 + the `_test` namespace is gated by `_require_development_env`).

### Phase boundaries

- **Phase 1 (this spec):** A1–A4 (Compose `profiles:` + install.sh) and B1–B5 (reseed `engines` filter + new capability endpoint + reset modal UI). Rationale: ships the user's headline value (startup-time reduction by skipping engine pulls) AND the coordinated reset modal in one slice. The two halves share the engine enum (`EngineTypeWire`) and the enum-discipline source-of-truth comment in `ui/src/lib/enums.ts`; splitting them across phases would create synchronization debt.
- **Phase 2 (deferred — see [phase2_idea.md](../../planned_features/02_mvp2/feat_engine_version_selection/idea.md)):** Engine version selection at install time. Adds `ES_IMAGE_TAG` / `OS_IMAGE_TAG` / `SOLR_IMAGE_TAG` env vars with the current pins as defaults; new `ENGINE_VERSION_MATRIX` backend constant listing the offered tags (manual maintainer-curated); install.sh non-interactive version flags; ES/OS version-report path (extend the reachability probe to surface the `version` field). Optional version display in the reset modal once a unified capability endpoint exists. Rationale to defer: ES/OS have no version-report logic today (only Solr does via `probe_capabilities`), so adding it for the reset modal alone is unjustified — defer until the install-time version picker creates the justification. Engine selection (Phase 1) is the bigger user-value win; version is polish.
- **Phase 3 (deferred — see [phase3_idea.md](../../planned_features/02_mvp2/feat_reseed_status_sse_streaming/idea.md)):** SSE migration of `GET /api/v1/_test/demo/reseed/status`. Replaces the 2s Redis poll with `text/event-stream` using the existing `to_sse_frame()` infrastructure ([backend/app/agent/events.py](../../../../../backend/app/agent/events.py)). Rationale to defer: the poll already delivers step-by-step progress; only pick this up if operators report the 2s granularity is insufficient.

---

## 4) Product principles and constraints

- **Non-regression of `make up` first-run UX.** Operators who don't opt-in see exactly today's behavior — all three engines, all five demo scenarios, no new prompts, no new flags.
- **Single source of truth for the engine wire-value allowlist.** The Pydantic `EngineTypeWire = Literal["elasticsearch", "opensearch", "solr"]` is canonical; the frontend mirror at `ui/src/lib/enums.ts:42-44` already cites it. The new reseed POST body's `engines` field MUST consume this enum, not duplicate it.
- **Partial-completion contract preserved.** `status="complete"` with non-empty `scenarios_skipped` is NOT a failure (CLAUDE.md "Common Pitfalls"). Adding user-excluded skips MUST NOT reclassify those runs as failed.
- **`_test` namespace remains dev-only.** Every new endpoint MUST carry `dependencies=[Depends(_require_development_env)]` so it returns 404 in production.
- **No Docker socket access from the API container.** The version picker cannot live in the browser. The reset modal can READ which engines are running but cannot pull / restart / change versions.
- **Corp-network / air-gapped install posture preserved.** No runtime Docker Hub queries; the offered engine list and (in Phase 2) version matrix are baked into shipped code.

### Anti-patterns

- **Do not** introduce a separate `EngineType` literal anywhere new — consume `EngineTypeWire` from `backend/app/api/v1/schemas.py`. The duplicate `_EngineType` in `demo_seeding.py:443` is a discoverable cleanup, not a license to keep duplicating.
- **Do not** reclassify `status="complete" + scenarios_skipped non-empty` as failed. The toast may say "partial completion" but the terminal state stays `complete`. The CLAUDE.md "Common Pitfalls" entry is canonical.
- **Do not** add a TTY prompt in `install.sh` for engine selection. CI and scripted installs lose determinism. Env-driven only.
- **Do not** auto-discover engine versions from Docker Hub at runtime. The corp-network install (`chore_corp_install_dx_improvements`) explicitly hardens against unbounded outbound calls; the engine matrix is a maintainer-curated constant.
- **Do not** delete or rearrange any engine service in `docker-compose.yml` — `profiles:` is additive. Existing deployments that rely on all-three should see no diff in default behavior.
- **Do not** make the reset-modal selection persist across sessions. The selection is per-click; no localStorage, no cookie, no DB.
- **Do not** invent option list values for the reset modal. The engines list MUST come from `GET /api/v1/_test/demo/engines` (server-side reachability probe), not from a hardcoded array in the React component.

---

## 5) Assumptions and dependencies

- **Compose `profiles:` semantics.** Docker Compose v2 honors `COMPOSE_PROFILES` to gate services. Verified: the project's Compose version is Compose v2 (services use `pull_policy`, depends_on conditions, named profiles supported). Risk: an extremely old Compose v1 environment wouldn't honor profiles — but project README pins Compose v2 (per the corp-install runbook).
- **No engine in the `depends_on` graph of application services.** Verified at [`docker-compose.yml:100-102`](../../../../../docker-compose.yml#L100-L102), [`:149-155`](../../../../../docker-compose.yml#L149-L155), [`:237-245`](../../../../../docker-compose.yml#L237-L245), [`:309-311`](../../../../../docker-compose.yml#L309-L311): `migrate`, `api`, `worker`, `ui` depend only on `postgres`, `redis`, and each other — none of the three engines. Therefore profile-gating engines via `profiles:` does NOT cascade-skip the application services. This is the load-bearing assumption that makes opt-in engines viable; if a future PR adds `depends_on: elasticsearch` to `api`, the spec must be revisited.
- **The reseed Arq worker startup ordering.** `arq_pool` must be ready before the new capability endpoint is hit. The capability endpoint doesn't need the Arq pool — it just probes engines via the existing `is_engine_reachable`. No new dependency.
- **`is_engine_reachable` 2-second timeout.** The new capability endpoint probes 3 engines in parallel via `asyncio.gather` — max ~2s when all are down. Risk: under-2s probe budget per-engine if we add a deadline. Mitigation: keep the existing 2s timeout; document that a "Reset to demo state" click costs at most ~2s of probing before the modal renders.
- **No Alembic migration required.** Selection is request-param + config; no persisted state. State.md confirms the head stays at `0023_proposals_superseded_status`.

---

## 6) Actors and roles

- **Primary actor:** Relevance engineer / operator running RelyLoop on a laptop or evaluation host.
- **Role model:** N/A — single-tenant install, no auth surface (per umbrella spec §6).
- **Permission boundaries:** Every new endpoint is `_test/`-namespaced and dev-only (`_require_development_env`). In production builds the endpoints 404.

### Authorization

N/A — single-tenant install, no auth surface. The dev-only gate is sufficient.

### Audit events

N/A — MVP2's `audit_log` table has not yet shipped (Alembic head `0023`, no `audit_log` table per `state.md` "Reserved for later releases" reference in [data-model.md](../../../../01_architecture/data-model.md)). Even when `audit_log` lands, the `_test/` namespace is explicitly excluded from audit emission (dev-only, not a production business mutation surface). The reset-to-demo flow is a sanctioned wipe — operators triggering it know what they're doing.

---

## 7) Functional requirements

### FR-1: Compose engine services become opt-in via profiles
- Requirement:
  - The system **MUST** add a `profiles:` field on each of the three engine services in `docker-compose.yml` (`elasticsearch` → profile `es`; `opensearch` → profile `os`; `solr` → profile `solr`).
  - The system **MUST** preserve current behavior when no profile is provided: a bare `docker compose up -d` (without `COMPOSE_PROFILES` set) starts all three engines, identical to today.
  - The system **MUST NOT** change the default heap sizes, pinned image tags, ports, or healthchecks for any engine service in Phase 1.
- Notes: Compose's `profiles:` semantics treat unprofiled services as always-on; profiled services participate only when their profile is in `COMPOSE_PROFILES`. The "include all by default when nothing is set" behavior MUST be implemented in `install.sh` by defaulting `COMPOSE_PROFILES=es,os,solr` when `RELYLOOP_ENGINES` is unset (Compose itself defaults to "none of the profiled services" otherwise).

### FR-2: install.sh accepts `RELYLOOP_ENGINES` env var
- Requirement:
  - The system **MUST** parse `RELYLOOP_ENGINES` (comma-separated list of `es`, `os`, `solr`) in `scripts/install.sh` and export it as `COMPOSE_PROFILES` for the `docker compose build` and `docker compose up` invocations.
  - The system **MUST** default `RELYLOOP_ENGINES=es,os,solr` when the env var is unset (preserving current behavior).
  - The system **MUST** reject unrecognized values with an explicit error message — e.g., `RELYLOOP_ENGINES=es,fusion` exits 1 with `unknown engine: fusion (allowed: es, os, solr)`.
  - The system **SHOULD** echo the selected engine set during the install run (e.g., `RelyLoop: starting engines: es, os, solr`).
- Notes: `COMPOSE_PROFILES` env var is the canonical Compose mechanism — alternatives like `--profile` flag would require editing the `docker compose` command lines and lose the env-driven pattern that CI's `RELYLOOP_SKIP_*` already establishes.

### FR-3: CI smoke job opts into all profiles explicitly
- Requirement:
  - The system **MUST** set `COMPOSE_PROFILES=es,os,solr` in the smoke job's environment (in `.github/workflows/pr.yml`) before any `make up` invocation, so the smoke job's three-engine coverage is preserved regardless of the operator default.
- Notes: The smoke job is currently OFF by default (`SMOKE_TEST` repo variable unset). When it's flipped on, three-engine coverage is the assumed baseline; the explicit profile opt-in protects against silent coverage regression.

### FR-4: Backend reseed POST accepts an `engines` filter
- Requirement:
  - `POST /api/v1/_test/demo/reseed` **MUST** accept an optional JSON request body of the shape `{"engines": ["elasticsearch", "opensearch", "solr"]} | {"engines": null} | {}`.
  - The system **MUST** validate `engines[*]` against the canonical `EngineTypeWire = Literal["elasticsearch", "opensearch", "solr"]` from `backend/app/api/v1/schemas.py`. Invalid values return `422 VALIDATION_ERROR` using the existing error envelope.
  - When `engines` is null or omitted, the system **MUST** behave identically to today (reseed all reachable engines).
  - The system **MUST** thread the selected list into `reseed_demo_state()` as an explicit parameter (no module-level globals).
  - The system **MUST NOT** change the existing 409 `SEED_IN_PROGRESS` or 503 `ARQ_POOL_UNAVAILABLE` semantics.
- Notes: The current endpoint takes no body. Adding an optional body is backward-compatible — existing clients posting empty bodies continue to work.

### FR-5: Reseed orchestrator filters scenarios by engine selection
- Requirement:
  - `reseed_demo_state()` **MUST** accept an optional `engines: list[Literal["elasticsearch", "opensearch", "solr"]] | None` parameter; when present, filter `SCENARIOS` to entries whose `engine_type` is in the set BEFORE the existing per-scenario reachability gate.
  - The system **MUST** apply the same `engines` filter to the rich ESCI scenario (`_RICH_SCENARIO_SLUG`, engine_type = `elasticsearch`, dispatched outside the `SCENARIOS` loop at [`demo_seeding.py:1962`](../../../../../backend/app/services/demo_seeding.py#L1962)). When ES is not in the selected set, the rich slug is appended to `scenarios_skipped` with reason `user_excluded` before its dispatch path is entered.
  - For scenarios filtered out by user selection, the system **MUST** append the slug to `progress.scenarios_skipped` AND record the reason as `"user_excluded"` in the new `scenarios_skipped_reasons` map.
  - For scenarios that pass the user-selection filter but fail the reachability gate, the system **MUST** record the reason as `"unreachable"` (consistent with today's behavior).
  - The system **MUST** preserve the `AllEnginesUnreachableError` semantics: if every scenario was either user-excluded OR unreachable, the run terminates `failed` with `failed_reason="all_engines_unreachable"`. (User-excluded-only is treated as unreachable for the purpose of this single failure check, because both produce the same "nothing got reseeded" outcome.) The existing `_is_all_engines_unreachable()` helper at [`demo_seeding.py:232`](../../../../../backend/app/services/demo_seeding.py#L232) checks `len(scenarios_skipped) >= len(SCENARIOS) + 1`; this logic is unchanged — both reasons count toward the threshold.
- Notes: The user-excluded vs unreachable distinction is informational for the operator; both reduce `scenarios_completed`. `scenarios_total` stays at `len(SCENARIOS) + 1` (today's value, 5) regardless of `engines` filter — consistent with the existing partial-completion convention where the operator sees the progress bar cap below 100% when some scenarios are skipped.

### FR-6: `ReseedStatusResponse` carries skip reasons
- Requirement:
  - The system **MUST** add `scenarios_skipped_reasons: dict[str, Literal["user_excluded", "unreachable"]]` to the `ReseedStatusResponse` Pydantic model.
  - The system **MUST** keep the existing `scenarios_skipped: list[str]` field unchanged (backward compat with cached statuses, the existing TS hook, and downstream tests).
  - When deserializing an older cached payload that lacks `scenarios_skipped_reasons` (Redis TTL'd vs fresh), the system **MUST** default the field to `{}` and treat unknown skips as "unreachable" for display purposes.
- Notes: Keeping the list-of-slugs field unchanged means existing tests/UI continue to render the slug list; the new field is additive.

### FR-7: New `GET /api/v1/_test/demo/engines` capability endpoint
- Requirement:
  - The system **MUST** add `GET /api/v1/_test/demo/engines` to [`backend/app/api/v1/_test.py`](../../../../../backend/app/api/v1/_test.py), gated by `_require_development_env`, returning the current reachability of each engine.
  - Response shape:
    ```json
    {
      "engines": [
        {"engine_type": "elasticsearch", "reachable": true},
        {"engine_type": "opensearch", "reachable": true},
        {"engine_type": "solr", "reachable": false}
      ]
    }
    ```
  - The system **MUST** probe all three engines concurrently via `asyncio.gather`, each probe bounded by `is_engine_reachable`'s existing 2-second timeout.
  - The system **MUST** return `200 OK` even if some/all engines are unreachable (the response carries the per-engine boolean).
- Notes: This is a small endpoint with no Redis or Arq dependencies — pure network probe. It powers the reset modal's checkbox population.

### FR-8: Reset-to-demo modal renders engine checkboxes
- Requirement:
  - The system **MUST** modify [`reset-demo-state-button.tsx`](../../../../../ui/src/components/dashboard/reset-demo-state-button.tsx) to fetch `GET /api/v1/_test/demo/engines` when the operator clicks the "Reset to demo state" trigger button (before the user clicks Confirm).
  - The modal **MUST** render a checkbox for each engine returned by the capability endpoint, labeled with a user-friendly name (`Elasticsearch`, `OpenSearch`, `Apache Solr`) — labels diverging from wire values per §7.4.
  - Each checkbox MUST be checked by default if `reachable=true`, disabled (and unchecked) if `reachable=false`.
  - The system **MUST** display a small helper line above the checkboxes: `Choose which engines to reseed (defaults to all running engines).`
  - On confirmation, the system **MUST** POST `{engines: [selected wire values]}` to the reseed endpoint.
  - If the operator unchecks every checkbox, the Confirm button MUST be disabled (no point reseeding nothing).
- Notes: The wire values come from `ENGINE_TYPE_VALUES` in `ui/src/lib/enums.ts:43` (already canonical); labels are display-only.

### FR-9: Progress card distinguishes user-excluded from unreachable skips
- Requirement:
  - The system **MUST** modify the partial-completion footer in `reset-demo-state-button.tsx` to render user-excluded and unreachable skips as separate sublines, e.g.:
    ```
    Partial completion — 2 scenarios skipped:
    • You excluded: opensearch (news-search-staging)
    • Engine unreachable: solr (acme-kb-docs-solr)
    See: <Why?>
    ```
  - When `scenarios_skipped_reasons` is empty (older cached status), the system **MUST** fall back to today's flat rendering.
  - The "Why?" link continues to point at [`docs/03_runbooks/demo-reseed-engine-tolerance.md`](../../../../03_runbooks/demo-reseed-engine-tolerance.md); the runbook MUST be updated (see §15) to cover the new user_excluded reason.
- Notes: The rendering polish matters because today's flat list is the operator's only window into what got skipped and why.

### FR-10: `.env.example` and runbook updates
- Requirement:
  - `.env.example` **MUST** document `RELYLOOP_ENGINES` near the existing `BASE_REGISTRY` block with an inline example.
  - [`docs/03_runbooks/local-dev.md`](../../../../03_runbooks/local-dev.md) **MUST** describe the new opt-in mechanism (single-engine evaluation) under a new "Selecting a subset of engines" section.
  - [`docs/03_runbooks/corporate-network-install.md`](../../../../03_runbooks/corporate-network-install.md) **MAY** mention `RELYLOOP_ENGINES` as a way to reduce registry-pull surface (each unselected engine = one fewer image to pull through the corp proxy).
  - [`docs/03_runbooks/demo-reseed-engine-tolerance.md`](../../../../03_runbooks/demo-reseed-engine-tolerance.md) **MUST** be updated to cover the new `user_excluded` reason.
- Notes: Docs land in the same PR; the generated-artifacts-fresh CI gate covers `ui/openapi.json` regen.

---

## 8) API and data contract baseline

### 8.1 Endpoint surface

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `POST` | `/api/v1/_test/demo/reseed` | (Existing) Enqueue a reseed; now accepts optional `{engines: [...]}` body. | `409 SEED_IN_PROGRESS`, `422 VALIDATION_ERROR`, `503 ARQ_POOL_UNAVAILABLE` |
| `GET` | `/api/v1/_test/demo/reseed/status` | (Existing) Poll status — response shape extended with `scenarios_skipped_reasons`. | None (returns `idle` not 404) |
| `GET` | `/api/v1/_test/demo/engines` | (New) Probe the three engines and report per-engine reachability. | None (always 200) |

All three endpoints carry `dependencies=[Depends(_require_development_env)]` — 404 in production builds.

### 8.2 Contract rules

- Error envelope: `{"detail": {"error_code": "<CODE>", "message": "<human>", "retryable": <bool>}}` per [api-conventions.md](../../../../01_architecture/api-conventions.md), verified at [`backend/app/api/errors.py:101-104`](../../../../../backend/app/api/errors.py#L101).
- Status codes deterministic per scenario (table above).
- `engines` list values strictly validated against `EngineTypeWire`.
- The capability endpoint MUST return `200` even when all engines are unreachable (reachability data IS the response, not the error).

### 8.3 Response examples

**`POST /api/v1/_test/demo/reseed` — success (202 Accepted, with body):**
```json
{
  "status": "running",
  "started_at": "2026-06-17T12:34:56Z",
  "finished_at": null,
  "scenarios_total": 5,
  "scenarios_completed": 0,
  "current_step": "enqueued — waiting for worker",
  "failed_reason": null,
  "summary": null,
  "steps": [],
  "scenarios_skipped": [],
  "scenarios_skipped_reasons": {}
}
```

**`POST /api/v1/_test/demo/reseed` — validation error (422):**
```json
{
  "detail": {
    "error_code": "VALIDATION_ERROR",
    "message": "engines[1]: input must be one of 'elasticsearch', 'opensearch', 'solr'",
    "retryable": false
  }
}
```

**`POST /api/v1/_test/demo/reseed` — already running (409):**
```json
{
  "detail": {
    "error_code": "SEED_IN_PROGRESS",
    "message": "A demo reseed is already running. Poll GET /api/v1/_test/demo/reseed/status for progress.",
    "retryable": true
  }
}
```

**`GET /api/v1/_test/demo/reseed/status` — partial completion with mixed skips (200):**
```json
{
  "status": "complete",
  "started_at": "2026-06-17T12:34:56Z",
  "finished_at": "2026-06-17T12:42:01Z",
  "scenarios_total": 5,
  "scenarios_completed": 3,
  "current_step": "done",
  "failed_reason": null,
  "summary": {
    "clusters_created": 3,
    "query_sets_created": 3,
    "studies_completed": 3,
    "proposals_created": 0,
    "duration_ms": 425034
  },
  "steps": ["…dedup-log entries…"],
  "scenarios_skipped": ["news-search-staging", "acme-kb-docs-solr"],
  "scenarios_skipped_reasons": {
    "news-search-staging": "user_excluded",
    "acme-kb-docs-solr": "unreachable"
  }
}
```

**`GET /api/v1/_test/demo/engines` — mixed reachability (200):**
```json
{
  "engines": [
    {"engine_type": "elasticsearch", "reachable": true},
    {"engine_type": "opensearch", "reachable": true},
    {"engine_type": "solr", "reachable": false}
  ]
}
```

### 8.4 Enumerated value contracts

| Field | Accepted values (exact) | Backend source of truth | Frontend call site(s) |
|---|---|---|---|
| `engines[*]` (POST body) | `elasticsearch`, `opensearch`, `solr` | [`backend/app/api/v1/schemas.py:315`](../../../../../backend/app/api/v1/schemas.py#L315) `EngineTypeWire` | [`ui/src/components/dashboard/reset-demo-state-button.tsx`](../../../../../ui/src/components/dashboard/reset-demo-state-button.tsx) (modal checkboxes) — consume `ENGINE_TYPE_VALUES` from [`ui/src/lib/enums.ts:43`](../../../../../ui/src/lib/enums.ts#L43) |
| `engines[*].engine_type` (capability response) | `elasticsearch`, `opensearch`, `solr` | Same `EngineTypeWire` | Same modal |
| `scenarios_skipped_reasons.values()` | `user_excluded`, `unreachable` | NEW Literal in [`backend/app/api/v1/schemas.py`](../../../../../backend/app/api/v1/schemas.py) (or co-located with `ReseedStatusResponse` in `demo_seeding.py` — pick one in the plan) | [`ui/src/lib/enums.ts`](../../../../../ui/src/lib/enums.ts) — add `RESEED_SKIP_REASON_VALUES` as a new `as const` array with a backend-source-of-truth comment; consumed by the reset modal's partial-completion footer rendering |
| `RELYLOOP_ENGINES` env var (install.sh) | `es`, `os`, `solr` (comma-separated, any subset) | `scripts/install.sh` parser (validates against `{es, os, solr}` set) | N/A — env var, not a frontend dropdown |

**Note on label divergence (per §7.4 Rules):** The modal's user-facing labels are `Elasticsearch`, `OpenSearch`, `Apache Solr` — these are display-only and diverge intentionally from the wire values (`elasticsearch`, etc.). The labels are co-located with the wire values in a single TS const so they can't drift.

### 8.5 Error code catalog

This feature introduces no NEW error codes. It reuses:

| Code | HTTP Status | Meaning | Source |
|---|---|---|---|
| `VALIDATION_ERROR` | 422 | Request body validation failed (e.g., bad value in `engines[*]`) | Existing FastAPI validator path → translated by [`backend/app/api/errors.py`](../../../../../backend/app/api/errors.py) |
| `SEED_IN_PROGRESS` | 409 | A reseed is already running | Existing in `_test.py:655-663` |
| `ARQ_POOL_UNAVAILABLE` | 503 | Arq worker pool not initialized | Existing in `_test.py:644-649` |

---

## 9) Data model and state transitions

### New/changed entities

**No new tables. No Alembic migration.**

**Modified Pydantic models:**

- `ReseedStatusResponse` (in `backend/app/services/demo_seeding.py` — co-located with the service, not the API schema module):
  - Add `scenarios_skipped_reasons: dict[str, Literal["user_excluded", "unreachable"]]` — defaults to `{}`. Additive; existing `scenarios_skipped: list[str]` unchanged.

**New Pydantic models:**

- `ReseedRequest` (NEW, in `backend/app/api/v1/schemas.py` or co-located with the route in `_test.py` — plan picks):
  - `engines: list[EngineTypeWire] | None = None` — optional filter on which engines to reseed.

- `DemoEnginesResponse` (NEW, co-located with new capability endpoint in `_test.py`):
  - `engines: list[DemoEngineStatus]` — per-engine reachability snapshot.
- `DemoEngineStatus` (NEW):
  - `engine_type: EngineTypeWire`
  - `reachable: bool`

### Required invariants

- `engines` filter (when non-null) is a non-empty subset of `{elasticsearch, opensearch, solr}` — empty list is treated as "validation error" (the UI guarantees this server-side too).
- `scenarios_skipped` and `scenarios_skipped_reasons` are kept consistent: every slug in the list MUST have an entry in the dict; every key in the dict MUST be in the list. The orchestrator enforces this in a single helper.
- `AllEnginesUnreachableError` continues to fire when every scenario was skipped (regardless of reason mix).

### State transitions

- Reseed run lifecycle unchanged: `idle → running → complete | failed`. The new `engines` filter affects only which scenarios are attempted; the state machine is untouched.

### Idempotency / replay behavior

- The Arq job id `"demo_reseed:singleton"` is unchanged; double-clicking with a different `engines` selection still returns `409 SEED_IN_PROGRESS` until the in-flight run terminates. Documented in the runbook update.

---

## 10) Security, privacy, and compliance

- **Threats:**
  1. **Operator unintentionally seeds production data by hitting the test endpoint.** Already mitigated by `_require_development_env` (the endpoint 404s in production builds). Phase 1 changes nothing here.
  2. **A misconfigured `RELYLOOP_ENGINES` value crashes `install.sh` mid-run, leaving the operator in a half-built state.** Mitigated by validating the env var BEFORE any `docker compose` invocation; an unknown engine name exits 1 with a clear message before any side effects.
  3. **The capability endpoint leaks internal engine URLs.** Mitigated by returning only `(engine_type, reachable)` — no URLs, no auth metadata, no version data.
- **Controls:** dev-only gate on all `_test/` endpoints; pre-validation of env vars in `install.sh`; response-shape minimalism on the new capability endpoint.
- **Secrets / key handling:** no new secrets. `RELYLOOP_ENGINES` is a non-secret operational config.
- **Auditability:** N/A (pre-MVP3 audit_log; `_test/` namespace excluded from audit emission).
- **Data retention / deletion / export impact:** N/A — no persisted state changes.

---

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement:** The reset-to-demo selection modal lives **inside the existing dialog** opened by the "Reset to demo state" button at [`ui/src/components/dashboard/start-here-checklist.tsx:56`](../../../../../ui/src/components/dashboard/start-here-checklist.tsx#L56). The button stays where it is (home page `/` → Start Here checklist). No new routes, no new sidebar entries.
- **Labeling taxonomy:**
  - Button label: `Reset to demo state` (unchanged).
  - Modal title (before run): `Wipe and reseed demo data?` (unchanged).
  - New section heading inside the dialog: `Engines to reseed` (sentence case, small label above the checkbox group).
  - Checkbox labels: `Elasticsearch`, `OpenSearch`, `Apache Solr` (matching engine vendor names, not wire values).
  - Helper text under the heading: `Defaults to all running engines. Unreachable engines are shown disabled.`
- **Content hierarchy** (top to bottom inside the dialog, pre-run):
  1. Title.
  2. Existing description (wipe warning, ~5–9 min duration, ESCI cost note).
  3. NEW: `Engines to reseed` section with checkbox group.
  4. Cancel / Confirm footer.
- **Progressive disclosure:** No new disclosure layer — the checkbox group is visible from the moment the dialog opens. Engines that are unreachable show their checkbox disabled with `(unreachable)` appended to the label (helps the operator understand why their selection is constrained).
- **Relationship to existing pages:** Extends an existing dialog — no new pages, no replacement.

### Tooltips and contextual help

| Element | Tooltip / help text | Trigger | Placement |
|---|---|---|---|
| `Engines to reseed` heading | `Each engine has its own demo scenarios. Selecting only Elasticsearch (for example) will reseed only the ES scenarios — the others appear as "you excluded" in the run summary.` | info icon click | inline helper text below the heading (no info icon needed; the helper line is the tooltip) |
| Disabled engine checkbox (`(unreachable)` suffix) | `This engine isn't running — start it via 'make up' with COMPOSE_PROFILES=<profile>, then reload.` | hover on label | top |
| Partial completion footer (existing) | `Scenarios for unselected engines are recorded as 'you excluded' so you can tell them apart from genuinely unreachable engines.` | hover on "you excluded" badge | top |

Tooltip discipline: each tooltip is ≤120 chars (per template guidelines). No new glossary keys are introduced for Phase 1 — the terminology (`reseed`, `engine`, `unreachable`) already exists in [`ui/src/lib/glossary.ts`](../../../../../ui/src/lib/glossary.ts) per the contextual-help discipline. Phase 1 reuses existing keys.

### Primary flows

1. **Single-engine evaluator first-run (the headline flow):**
   - Operator copies `.env.example` to `.env`, sets `RELYLOOP_ENGINES=es`, runs `make up`.
   - `install.sh` validates the env var, exports `COMPOSE_PROFILES=es`, runs `docker compose up -d --wait`.
   - Only the `elasticsearch` engine is pulled and started. Postgres, Redis, api, worker, ui boot as usual.
   - Auto-seed (`seed_meaningful_demos.py --if-empty`) runs against the live api; it probes each scenario's engine, finds only ES reachable, seeds the ES scenarios, marks OS/Solr scenarios as `scenarios_skipped` with reason `unreachable` (existing behavior).
   - Operator hits `http://localhost:3000` → home → sees ES demo data only.
2. **Operator picks an engine subset on the reset modal:**
   - With all three engines running, operator clicks "Reset to demo state."
   - Modal opens; capability fetch resolves; all three checkboxes are checked + enabled.
   - Operator unchecks OpenSearch and Solr, clicks Confirm.
   - POST `{engines: ["elasticsearch"]}` → 202.
   - Worker reseeds only ES scenarios; reports OS/Solr scenarios as `scenarios_skipped` with reason `user_excluded`.
   - Modal shows partial completion footer: `2 scenarios skipped: You excluded — news-search-staging; You excluded — acme-kb-docs-solr.`
3. **All three engines running, operator accepts the default:**
   - Modal opens with all checked. Operator clicks Confirm without changes.
   - POST `{engines: ["elasticsearch", "opensearch", "solr"]}` OR `{engines: null}` (UI may send either — the orchestrator treats both identically).
   - Full reseed runs, identical to today's behavior, including the ESCI scenario.

### Edge / error flows

- **Operator unchecks all engines.** Confirm button disabled; helper text reads `Select at least one engine to reseed.` POST never fires.
- **`/api/v1/_test/demo/engines` returns 404 (operator's backend not rebuilt).** Modal falls back to rendering all three checkboxes as enabled (reachability unknown); helper line shows `Couldn't probe engines — your container build is out of date. Continuing as if all are reachable.` The orchestrator will still handle unreachable engines correctly via the existing per-scenario gate.
- **`/api/v1/_test/demo/engines` returns 500 / network error.** Same fallback as 404. Toast: `Could not check which engines are running.`
- **Operator picks engines that aren't actually running** (e.g., started with `RELYLOOP_ENGINES=es` then somehow checked all three on the modal — possible if capability probe was stale). The reseed orchestrator probes engines per-scenario; unreachable ones get reason `unreachable`. The operator sees a mixed-reason partial completion.
- **Unrecognized `RELYLOOP_ENGINES=foo` in install.sh.** `install.sh` exits 1 BEFORE any `docker compose` call with `Unknown engine 'foo' in RELYLOOP_ENGINES. Allowed: es, os, solr.`
- **Empty `RELYLOOP_ENGINES=` (set but empty).** Treated as "unset" — defaults to `es,os,solr`. Documented in `.env.example`.
- **Operator double-clicks Confirm.** The 409 `SEED_IN_PROGRESS` path is unchanged; the second click sees the toast and resumes polling the in-flight run.
- **Developer runs `docker compose up -d` directly (bypassing `make up`).** With `profiles:` on the engine services and no `COMPOSE_PROFILES` set, Compose's default behavior is to skip profile-gated services entirely — so no engines come up. `make up` mitigates this by defaulting `COMPOSE_PROFILES=es,os,solr` when `RELYLOOP_ENGINES` is unset (FR-2 + FR-1 Notes); developers who bypass `make up` see only postgres/redis/api/worker/ui boot until they re-run with `COMPOSE_PROFILES` or `make up`. [`docs/03_runbooks/local-dev.md`](../../../../03_runbooks/local-dev.md) must document this so the workaround (`COMPOSE_PROFILES=es,os,solr docker compose up -d`, or just use `make up`) is one click away. The runbook update is mandatory per §15.

---

## 12) Given/When/Then acceptance criteria

### AC-1: Default `make up` behavior preserved
- Given: a fresh checkout with no `.env` (or `.env` without `RELYLOOP_ENGINES`).
- When: the operator runs `make up`.
- Then: all three engine containers (`elasticsearch`, `opensearch`, `solr`) come up healthy, identical to current behavior; auto-seed runs all five demo scenarios.
- Example: `docker compose ps` shows `elasticsearch`, `opensearch`, `solr` all `running (healthy)`.

### AC-2: `RELYLOOP_ENGINES=es` skips non-ES image pulls
- Given: a fresh checkout with `RELYLOOP_ENGINES=es` set in `.env`.
- When: the operator runs `make up` against a clean Docker (no cached images).
- Then: `docker compose up -d --wait` does NOT issue `docker pull` requests for `opensearch` or `solr`; only `elasticsearch` boots; `docker compose ps` shows `elasticsearch` running and `opensearch` / `solr` either absent or in `created (not started)` state.
- Example: `docker compose ps -a` shows only one engine container; `docker compose logs opensearch` returns "service not running."

### AC-3: Unknown engine in `RELYLOOP_ENGINES` rejected early
- Given: `RELYLOOP_ENGINES=es,fusion` in env.
- When: the operator runs `make up`.
- Then: `install.sh` exits 1 with `Unknown engine 'fusion' in RELYLOOP_ENGINES. Allowed: es, os, solr.` BEFORE any `docker compose build` or `docker compose up` invocation.

### AC-4: Reset POST accepts `engines` filter
- Given: stack running with all three engines.
- When: `POST /api/v1/_test/demo/reseed` with body `{"engines": ["elasticsearch"]}`.
- Then: response 202 + initial `ReseedStatusResponse` with `scenarios_total=5` (unchanged — total counts all scenarios, including those that will be skipped).

### AC-5: Reset POST rejects invalid engine values
- Given: stack running.
- When: `POST /api/v1/_test/demo/reseed` with body `{"engines": ["elasticsearch", "fusion"]}`.
- Then: response 422 with envelope `{"detail": {"error_code": "VALIDATION_ERROR", "message": "engines[1]: input must be one of 'elasticsearch', 'opensearch', 'solr'", "retryable": false}}`.

### AC-6: Reset POST treats `engines: null` and `{}` as "all engines"
- Given: stack running with all three engines.
- When: `POST /api/v1/_test/demo/reseed` with body `{}` OR `{"engines": null}` OR no body at all (Content-Length 0).
- Then: response 202; the run reseeds every scenario whose engine is reachable; `scenarios_skipped_reasons` contains only `unreachable` entries (no `user_excluded`).

### AC-7: User-excluded scenarios reported with correct reason
- Given: stack running with all three engines.
- When: a reseed run completes with body `{"engines": ["elasticsearch"]}`.
- Then: `GET /api/v1/_test/demo/reseed/status` returns:
  - `status: "complete"`, `scenarios_completed >= 1`
  - `scenarios_skipped` includes the OS and Solr scenario slugs
  - `scenarios_skipped_reasons` maps each of those slugs to `"user_excluded"`
  - `failed_reason: null`

### AC-8: All-engines-skipped still terminates `failed`
- Given: stack running with all three engines.
- When: a reseed run is dispatched with body `{"engines": []}`.
- Then: the request is rejected at validation (empty list invalid per FR-4 validators), 422 with `VALIDATION_ERROR`. (The endpoint never enqueues a no-op job; the failure is at the request boundary.)

### AC-9: Capability endpoint reports per-engine reachability
- Given: stack with ES + OS running, Solr stopped (`docker compose stop solr`).
- When: `GET /api/v1/_test/demo/engines`.
- Then: response 200 with body `{"engines": [{"engine_type":"elasticsearch","reachable":true},{"engine_type":"opensearch","reachable":true},{"engine_type":"solr","reachable":false}]}`.

### AC-10: Reset modal renders checkbox group from capability endpoint
- Given: backend reporting ES reachable, Solr unreachable.
- When: operator clicks "Reset to demo state."
- Then: modal opens, fetches `GET /api/v1/_test/demo/engines`, renders three checkboxes:
  - Elasticsearch — checked + enabled
  - OpenSearch — checked + enabled (assuming reachable)
  - Apache Solr — unchecked + disabled, label suffix `(unreachable)`

### AC-11: Reset modal Confirm button disabled when no engines selected
- Given: modal open with all three reachable.
- When: operator unchecks all three checkboxes.
- Then: Confirm button is disabled; helper text reads `Select at least one engine to reseed.`

### AC-12: Reset modal sends selected `engines` on Confirm
- Given: modal open, operator checks only Elasticsearch.
- When: operator clicks Confirm.
- Then: a single POST to `/api/v1/_test/demo/reseed` fires with body `{"engines":["elasticsearch"]}` (exact wire value).

### AC-13: Partial completion footer distinguishes the two skip reasons
- Given: a completed run with `scenarios_skipped_reasons = {"news-search-staging": "user_excluded", "acme-kb-docs-solr": "unreachable"}`.
- When: the operator views the modal at terminal state.
- Then: the footer renders two distinct sublines:
  - `You excluded: news-search-staging`
  - `Engine unreachable: acme-kb-docs-solr`

### AC-14: CI smoke job preserves three-engine coverage
- Given: `SMOKE_TEST=true` and `RELYLOOP_ENGINES` unset at the repo level.
- When: the smoke workflow job runs.
- Then: the job's `make up` step exports `COMPOSE_PROFILES=es,os,solr` (visible in the job env or in the workflow YAML) so all three engines come up regardless of any operator default change.

### AC-15: Backend CI lane unaffected by Compose profile changes
- Given: PRs that modify `docker-compose.yml` `profiles:` fields.
- When: the backend test lane runs.
- Then: ES + OS service containers (declared directly in `pr.yml`) still start and respond; the backend lane's pass/fail is unaffected by the Compose change.

---

## 13) Non-functional requirements

- **Performance:**
  - `GET /api/v1/_test/demo/engines` p99 ≤ 2.5s (probes 3 engines in parallel, each capped at 2s `is_engine_reachable` timeout + ~500ms slack).
  - `make up` with `RELYLOOP_ENGINES=es` on a cold Docker cache: at least 30% faster wall-clock than the all-three baseline (rough target — image pulls dominate, two skipped pulls save substantial time). Documented in the runbook update.
- **Reliability:** The capability endpoint MUST NOT raise even if all three engines time out — it returns `200` with all-false reachability.
- **Operability:**
  - `install.sh` echoes the selected engine set during startup (`RelyLoop: starting engines: es`) so the operator can confirm the selection took effect.
  - Engine selection appears in `docker compose config` output (the `profiles:` lines), so post-mortem debugging is straightforward.
- **Accessibility / usability:**
  - The new checkbox group MUST have proper `<label htmlFor>` associations; the disabled `(unreachable)` state MUST set `aria-disabled="true"` and `aria-describedby` pointing at the tooltip ID.
  - The helper text is rendered as visible text (not just a tooltip) so keyboard / screen-reader users see it.

---

## 14) Test strategy requirements (spec-level)

**Unit tests (`backend/tests/unit/`):**
- `_validate_relyloop_engines(env_value)` helper — pure function exercised in isolation. Cases: unset → default `"es,os,solr"`; valid subset → subset; invalid value → raises a typed error; empty string → default.
- Filtering logic inside `reseed_demo_state()` for the engine subset path — given a mock `SCENARIOS` and `engines=["elasticsearch"]`, only ES scenarios pass through; the skipped slugs land in `scenarios_skipped` with reason `user_excluded`.
- `ReseedStatusResponse` Pydantic model: default `scenarios_skipped_reasons={}`; round-trip JSON deserialization preserves the dict.

**Integration tests (`backend/tests/integration/`):**
- Real reseed run against the test database with `engines=["elasticsearch"]` — verify only ES scenarios got seeded (real `clusters` / `studies` rows present for ES slugs only); OS/Solr slugs appear in `scenarios_skipped` with reason `user_excluded`.
- Real reseed run with all-three (default) — backward-compat check; same row counts and behavior as today.
- Capability endpoint integration test — bring up ES service container, stop the others, verify `reachable` reflects reality.

**Contract tests (`backend/tests/contract/`):**
- New: `POST /api/v1/_test/demo/reseed` with `{engines:["elasticsearch"]}` → 202 + shape.
- New: same with `{engines:["fusion"]}` → 422 + exact envelope.
- New: same with `{engines:[]}` → 422 + envelope (empty list rejected).
- New: same with `{}` and no-body → both 202.
- New: `GET /api/v1/_test/demo/engines` → 200 + shape (all three engine types present).
- Updated: `test_openapi_surface.py` checks the new fields on `ReseedStatusResponse` and the new endpoint registration.

**E2E tests (`ui/tests/e2e/`):**
- The existing `demo-ubi.spec.ts` is CI-excluded (per [`infra_smoke_reseed_runtime_budget`](../../../implemented_features/2026_06_02_infra_smoke_reseed_runtime_budget/)); update it locally to (a) verify the modal renders the checkbox group, (b) verify selecting a subset sends the correct POST body, (c) verify the partial-completion footer's two-reason rendering. The CI-excluded gate holds — these run locally only.
- New: A short modal-only spec that doesn't run an actual reseed: opens the dialog, asserts checkboxes render from the capability endpoint, asserts the Confirm button disables when nothing is selected. This one can run in CI because it doesn't trigger the long reseed.

**Component / vitest:**
- `reset-demo-state-button.test.tsx` — covers the new checkbox rendering + the partial-completion footer's two-reason rendering with a mocked `useDemoReseedStatus`.
- `enums-discipline.test.ts` (existing lint guard) — add `RESEED_SKIP_REASON_VALUES` to the watched list and verify the source-of-truth comment is present.

---

## 15) Documentation update requirements

- `docs/01_architecture/deployment.md` — add a "Selecting a subset of engines" subsection under the Compose / engines block; document `RELYLOOP_ENGINES` + the resulting `COMPOSE_PROFILES` value.
- `docs/03_runbooks/local-dev.md` — add a "Selecting a subset of engines" section after the existing quickstart; include the headline win (faster startup) and the trade-off (reset modal only seeds the running subset).
- `docs/03_runbooks/corporate-network-install.md` — mention `RELYLOOP_ENGINES` as a way to reduce registry-pull surface (one paragraph).
- `docs/03_runbooks/demo-reseed-engine-tolerance.md` — update to cover the new `user_excluded` reason; explain the difference from `unreachable`.
- `.env.example` — document `RELYLOOP_ENGINES` near `BASE_REGISTRY`.
- `make help` — the new `RELYLOOP_ENGINES` env var should be discoverable from `make help` output (Makefile target docstring updates).
- `ui/public/docs/*.md` — N/A for Phase 1 (no tenant-facing guide changes).
- `state.md` — append a one-liner to "Last 5 merges" at merge time; full narrative goes into `state_history.md`.
- `architecture.md` — N/A for Phase 1 (no new services or data flows).
- `CLAUDE.md` — N/A for Phase 1 (no new conventions; the env-driven non-interactive install pattern is already established).

---

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** None. The feature is additive (default behavior preserved) and shipped behind the operator's explicit `RELYLOOP_ENGINES` opt-in. No flag needed.
- **Migration / backfill expectations:** No DB migration. Alembic head stays at `0023_proposals_superseded_status`.
- **Operational readiness gates:**
  - The smoke job's `COMPOSE_PROFILES=es,os,solr` opt-in must land in the same PR as the `profiles:` change so smoke coverage doesn't drop.
  - The runbook update describing `RELYLOOP_ENGINES` must land in the same PR so operators discover the new flag through normal docs paths.
- **Release gate:**
  - All ACs green.
  - `pr.yml` backend + UI + freshness gates green.
  - Smoke job (if `SMOKE_TEST=true` for the PR) green with three-engine coverage preserved.
  - Gemini Code Assist findings adjudicated per CLAUDE.md.

---

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned story area | Test files / suites | Docs to update |
|---|---|---|---|---|
| FR-1 (Compose `profiles:`) | AC-1, AC-2, AC-15 | infra: docker-compose.yml edit | `tests/unit/test_compose_profiles.py` (snapshot of the profile block); integration covered by AC-1 / AC-2 manual smoke | `docs/01_architecture/deployment.md`, `.env.example` |
| FR-2 (`install.sh` env parsing) | AC-1, AC-2, AC-3 | infra: install.sh edit | shell test in `scripts/ci/verify_install_*.sh`-style harness | `.env.example`, local-dev runbook |
| FR-3 (CI smoke profile opt-in) | AC-14 | infra: `pr.yml` edit | smoke job itself is the test | none |
| FR-4 (reseed POST `engines` filter) | AC-4, AC-5, AC-6 | backend: `_test.py` endpoint + Pydantic body model | contract tests above | `_test` namespace docs (none externally) |
| FR-5 (orchestrator engine filter) | AC-7, AC-8 | backend: `demo_seeding.reseed_demo_state` signature + filter | unit + integration tests above | none |
| FR-6 (`scenarios_skipped_reasons` field) | AC-7, AC-13 | backend: `ReseedStatusResponse` model | unit + integration + contract | demo-reseed-engine-tolerance runbook |
| FR-7 (capability endpoint) | AC-9, AC-10 | backend: new GET route | contract + integration | none (internal endpoint) |
| FR-8 (reset modal checkbox group) | AC-10, AC-11, AC-12 | frontend: `reset-demo-state-button.tsx` + capability fetch hook | vitest + Playwright spec | none |
| FR-9 (partial footer two-reason rendering) | AC-13 | frontend: same component | vitest | demo-reseed-engine-tolerance runbook |
| FR-10 (docs + `.env.example`) | covered indirectly via gates | docs only | n/a | every doc listed in §15 |

---

## 18) Definition of feature done

- [ ] All ACs (AC-1 through AC-15) pass in CI (or are validated manually for the infra ACs that don't have an automated harness — AC-1, AC-2, AC-3, AC-14 — with the validation captured in the PR body).
- [ ] All test layers (unit / integration / contract / vitest / Playwright modal-only) are green.
- [ ] Docs updates per §15 are merged in the same PR.
- [ ] Smoke job (when enabled) preserves three-engine coverage via `COMPOSE_PROFILES=es,os,solr`.
- [ ] No open questions remain in §19.
- [ ] `phase2_idea.md` and `phase3_idea.md` are tracked alongside this spec (per Spec template §3 Phase boundaries).

---

## 19) Open questions and decision log

### Open questions

None remaining — the five forks in [idea.md](idea.md) "Open forks to resolve at spec time" are resolved in the Decision log below.

### Decision log

- **2026-06-17 — D-1: `scenarios_skipped_reasons` is an additive sibling dict, not a list-of-objects replacement.**
  - Rationale: keeps the existing `scenarios_skipped: list[str]` shape unchanged → existing TS hook, contract test, and Redis-cached payloads continue to work without coordination. The alternative (`list[{slug, reason}]`) would require simultaneous frontend + backend deploy and would invalidate any in-flight cached status. Additive sibling is the safer rollout.

- **2026-06-17 — D-2: Streaming stays on the existing 2s Redis poll (Phase 1).**
  - Rationale: the poll already streams step-by-step `current_step` updates and a deduped step log via the existing `useDemoReseedStatus` hook. SSE migration would require StreamingResponse + EventSource refactor on a flow that doesn't have a felt latency problem. Phase 3 picks this up if/when operators report 2s granularity is insufficient.

- **2026-06-17 — D-3: Reset modal omits version display (Phase 1).**
  - Rationale: ES/OS have no version-report path today (only Solr does via `probe_capabilities`). Adding version-report for ES/OS solely to populate a read-only display in the reset modal is unjustified. Version display lands with Phase 2 when the install-time version picker creates the justification for a unified ES/OS version-report path.

- **2026-06-17 — D-4: `install.sh` engine selection is env-driven only — no interactive TTY prompt.**
  - Rationale: CI invocations (`RELYLOOP_SKIP_BUILD=1`, `RELYLOOP_SKIP_AUTO_SEED=1`) already establish the env-driven non-interactive pattern. Adding an interactive prompt would either fork behavior between TTY and non-TTY (drift risk) or require a `--non-interactive` flag (more surface). Env-only keeps the install path single-shape.

- **2026-06-17 — D-5: Engine version matrix is a maintainer-curated backend constant (Phase 2), not an auto-discovered Docker Hub query.**
  - Rationale: runtime Docker Hub queries break corp-network / air-gapped installs (per `chore_corp_install_dx_improvements`). The trade-off — operators need to wait for a release to get a newer version offered — is acceptable; engine versions don't change weekly. Recorded here even though version selection is Phase 2, because the decision is locked across phases.

- **2026-06-17 — D-6: Backend CI `pr.yml` service containers are not affected by Compose `profiles:`.**
  - Rationale: verified at [`pr.yml:439`](../../../../../.github/workflows/pr.yml#L439) and [`pr.yml:455`](../../../../../.github/workflows/pr.yml#L455) — the backend test lane declares ES + OS as GHA service containers directly, not via the Compose engine services. Compose changes don't affect that lane. Only the smoke job (which uses `make up`) needs the explicit `COMPOSE_PROFILES=es,os,solr` opt-in (FR-3).

- **2026-06-17 — D-7: Empty `engines: []` is rejected at validation, not treated as "all engines."**
  - Rationale: an empty list expresses "I want nothing reseeded" which has no legitimate workflow (it's a no-op masquerading as a request). `engines: null` and `engines: <missing>` and `{}` all mean "all engines" (the well-known absent-means-default pattern); `[]` is a request shape mistake and should be a 422 so the operator notices.

- **2026-06-17 — D-8: The duplicate `_EngineType = Literal[...]` in `demo_seeding.py:443` is left in place for Phase 1.**
  - Rationale: consolidating onto `EngineTypeWire` from `backend/app/api/v1/schemas.py` would touch the service layer for cosmetic reasons. Plan it as a follow-up chore (`chore_engine_type_literal_dedup`) only if the duplication actively bites; today it's discoverable but not harmful. Captured to prevent future audits from re-flagging it.
