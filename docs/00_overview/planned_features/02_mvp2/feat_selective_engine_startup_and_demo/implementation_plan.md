# Implementation Plan — Selective Engine Provisioning (Startup + Reset-to-Demo)

**Date:** 2026-06-17
**Status:** Complete — Phase 1 (PR #548, squash-merged `9bf20ab2`, 2026-06-17). Phase 2 + 3 deferred (see `phase2_idea.md`, `phase3_idea.md`).
**Primary spec:** [feature_spec.md](feature_spec.md)
**Cross-model review:** Opus self-review (GPT-5.5 unreachable in Claude Code remote sandbox per CLAUDE.md "Environment-aware fallback")
**Deferred phases tracked:** [phase2_idea.md](phase2_idea.md) (engine versions), [phase3_idea.md](phase3_idea.md) (SSE migration)

---

## 0) Planning principles

- Spec traceability first: every story maps to FR IDs (§1 below).
- Phase 1 only — Phase 2/3 work lives in `phase{2,3}_idea.md`; the plan never touches them.
- No new migration. Alembic head stays `0023_proposals_superseded_status`.
- The `_test/` namespace is dev-only — every new endpoint inherits `Depends(_require_development_env)`.
- Preserve current `make up` default behavior — operators who don't set `RELYLOOP_ENGINES` see today's three-engine startup unchanged.

## 1) Scope traceability (FR → epic/story)

| FR ID | Epic / Story | Notes |
|---|---|---|
| FR-1 (Compose `profiles:`) | Epic 1 / Story 1.1 | docker-compose.yml edit on three engine services. |
| FR-2 (`install.sh` `RELYLOOP_ENGINES`) | Epic 1 / Story 1.1 | env-var parser + `COMPOSE_PROFILES` export; default to all three when unset. |
| FR-3 (CI smoke profile opt-in) | Epic 1 / Story 1.2 | `pr.yml` smoke job sets `COMPOSE_PROFILES=es,os,solr` explicitly. |
| FR-4 (reseed POST `engines` filter) | Epic 2 / Story 2.2 | `ReseedRequest` Pydantic body model + endpoint signature. |
| FR-5 (orchestrator engine filter) | Epic 2 / Story 2.2 | `reseed_demo_state()` accepts `engines: list[...]|None`; filters `SCENARIOS` AND the rich ESCI scenario. |
| FR-6 (`scenarios_skipped_reasons`) | Epic 2 / Story 2.1 | additive `dict[slug, reason]` field on `ReseedStatusResponse`. |
| FR-7 (capability `GET /demo/engines`) | Epic 2 / Story 2.1 | new endpoint + `DemoEngineStatus` + `DemoEnginesResponse` models. |
| FR-8 (reset modal checkbox group) | Epic 3 / Story 3.1 | UI capability fetch + checkbox rendering + Confirm gating. |
| FR-9 (two-reason partial-completion footer) | Epic 3 / Story 3.2 | UI rendering of `scenarios_skipped_reasons`. |
| FR-10 (`.env.example` + runbooks + Makefile help) | Epic 1 / Story 1.2 + Epic 3 / Story 3.2 | docs land alongside the code that changes the behavior. |

All 10 FRs assigned. AC-1 through AC-15 from the spec map to story DoDs (see Story DoD sections).

## 2) Delivery structure

**Epic → Story → Tasks → DoD.** Three epics, six stories total.

### Conventions

- All repo / service / domain conventions remain those documented in CLAUDE.md and reused across the codebase (services are async; routers return typed Pydantic models; the standard error envelope is `{"detail": {"error_code", "message", "retryable"}}`).
- Every new test file lives in its layer-appropriate directory: `backend/tests/unit/` (no DB), `backend/tests/integration/` (DB-backed), `backend/tests/contract/` (FastAPI surface). The contract dir is **flat** (no `/api/v1/` subdir) — confirmed by `ls backend/tests/contract/`.
- Frontend tests in `ui/src/**/__tests__/` (vitest) and `ui/tests/e2e/` (Playwright).
- New router registrations land in [`backend/app/main.py`](../../../../../backend/app/main.py) — the `_test` router is already registered at line 219 with `prefix="/api/v1"`, so the new `GET /demo/engines` endpoint just adds a route inside the existing router file.

### AI Agent Execution Protocol

Per template: read `architecture.md` + `state.md` first; implement backend before frontend; run tests at each layer; update docs in the same PR; attach evidence in the PR body. Final story updates `state.md` (append one-liner to "Last 5 merges") and pushes the dashboards regen (per the merge-time finalization step).

---

## Epic 1 — Install-time engine selection (infrastructure)

**Outcome:** Operators can set `RELYLOOP_ENGINES=es` (or `es,os`, etc.) in `.env` to boot only the selected engines, dramatically reducing first-run wall-clock. Default behavior (no env var) preserved.

### Story 1.1 — Compose profiles + install.sh `RELYLOOP_ENGINES` parsing

**Outcome:** `docker compose up` skips unselected engine services entirely; `make up` honors `RELYLOOP_ENGINES` while defaulting to all three.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| [`docker-compose.yml`](../../../../../docker-compose.yml) | Add `profiles: ["es"]` on `elasticsearch` service ([:330-353](../../../../../docker-compose.yml#L330-L353)); `profiles: ["os"]` on `opensearch` ([:355-369](../../../../../docker-compose.yml#L355-L369)); `profiles: ["solr"]` on `solr` ([:391-405](../../../../../docker-compose.yml#L391-L405)). No other field changes — heap, ports, healthcheck, image tag stay identical. |
| [`scripts/install.sh`](../../../../../scripts/install.sh) | Add new `parse_relyloop_engines()` helper between lines 50 and 60 (after the secrets generation block, before the `do_compose_build` function). The helper reads `RELYLOOP_ENGINES`, validates each comma-separated value against `{es, os, solr}`, exits 1 on unknown values, and exports `COMPOSE_PROFILES`. Call the helper before `docker compose build` so build and up both honor the selection. Default `RELYLOOP_ENGINES=es,os,solr` when unset OR empty. Echo the selected engines: `echo "RelyLoop: starting engines: $RELYLOOP_ENGINES"`. |

**Endpoints**

N/A.

**Key interfaces**

```bash
# scripts/install.sh — new helper
parse_relyloop_engines() {
  # Reads $RELYLOOP_ENGINES (default 'es,os,solr'); validates against the allowlist;
  # exports COMPOSE_PROFILES. Exits 1 on unknown engine names.
}
```

**Pydantic schemas**

N/A.

**Tasks**

1. Edit [`docker-compose.yml`](../../../../../docker-compose.yml) to add the three `profiles:` fields. Verify with `docker compose config` — when `COMPOSE_PROFILES=` (unset), the three engines are listed under `profiles:` blocks (and excluded from the active set); when `COMPOSE_PROFILES=es,os,solr` (the install.sh default), all three are part of the active set.
2. Add `parse_relyloop_engines()` to [`scripts/install.sh`](../../../../../scripts/install.sh). Implementation outline:
   ```bash
   parse_relyloop_engines() {
     local default="es,os,solr"
     local input="${RELYLOOP_ENGINES:-$default}"
     # Treat empty string as unset.
     [[ -z "$input" ]] && input="$default"
     IFS=',' read -ra requested <<< "$input"
     local valid=("es" "os" "solr")
     local cleaned=()
     for raw in "${requested[@]}"; do
       # Strip whitespace (tolerate "es, os" with spaces).
       eng="${raw// /}"
       [[ -z "$eng" ]] && continue
       local ok=0
       for v in "${valid[@]}"; do
         [[ "$eng" == "$v" ]] && ok=1 && break
       done
       if [[ "$ok" -eq 0 ]]; then
         echo "Unknown engine '$eng' in RELYLOOP_ENGINES. Allowed: es, os, solr." >&2
         exit 1
       fi
       cleaned+=("$eng")
     done
     # Deduplicate (preserves first occurrence).
     local seen=() out=()
     for e in "${cleaned[@]}"; do
       local hit=0
       for s in "${seen[@]+"${seen[@]}"}"; do
         [[ "$e" == "$s" ]] && hit=1 && break
       done
       if [[ "$hit" -eq 0 ]]; then
         seen+=("$e"); out+=("$e")
       fi
     done
     export COMPOSE_PROFILES
     COMPOSE_PROFILES="$(IFS=','; echo "${out[*]}")"
     echo "RelyLoop: starting engines: $COMPOSE_PROFILES"
   }
   ```
   The bash-3.2-safe `${seen[@]+"${seen[@]}"}` empty-array form follows the convention used in `scripts/corp-ca-extract.sh` and `scripts/run-tests-in-worktree.sh` per the project's bash-3.2 footnote in CLAUDE.md.
3. Call `parse_relyloop_engines` immediately after step 6 of install.sh (before the `do_compose_build` block) so both build and up honor the export.
4. Add a small bats-style or pure-shell test exercising the helper: unset → default; valid subset → matches; unknown → exit 1 with stderr message; trailing comma / whitespace tolerated.

**Definition of Done**

- [ ] `docker compose config` against `COMPOSE_PROFILES=es,os,solr` lists all three engines as active services (default behavior preserved). [AC-1]
- [ ] `docker compose config` against `COMPOSE_PROFILES=es` shows only `elasticsearch` among engines; `opensearch` and `solr` are present in the parsed file but excluded from the active set. [AC-2]
- [ ] `RELYLOOP_ENGINES=es,fusion bash scripts/install.sh` exits 1 with stderr `Unknown engine 'fusion' in RELYLOOP_ENGINES. Allowed: es, os, solr.` BEFORE any `docker compose build` invocation. [AC-3]
- [ ] Unit test for `parse_relyloop_engines` passes (covering default / valid subset / unknown / whitespace tolerance).
- [ ] `make up` on a fresh checkout with no `.env` boots all three engines healthy (manual smoke). [AC-1]
- [ ] `make up` with `RELYLOOP_ENGINES=es` issues no `docker pull` for opensearch/solr; `docker compose ps -a` shows only `elasticsearch` among engine services (manual smoke; documented in PR body with `docker compose ps` output). [AC-2]

### Story 1.2 — `.env.example` + Makefile help + smoke job profile opt-in + runbook updates

**Outcome:** Operators discover `RELYLOOP_ENGINES` through `.env.example` and `make help`; smoke job preserves three-engine coverage regardless of operator default.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| [`.env.example`](../../../../../.env.example) | Add a new block near the existing `BASE_REGISTRY` block (around line 109-130) documenting `RELYLOOP_ENGINES` — purpose, allowed values, default, the resulting `COMPOSE_PROFILES` translation, and the headline-win callout (faster startup). Commented-out by default. |
| [`Makefile`](../../../../../Makefile) | Extend the existing `up:` target's docstring (the `## …` comment) to mention `RELYLOOP_ENGINES`. Add a new informational block at top of `make help` (or as a new `## Engine selection` section) listing the three options. |
| [`.github/workflows/pr.yml`](../../../../../.github/workflows/pr.yml) | At [line 898](../../../../../.github/workflows/pr.yml#L898) (the smoke job's `make up` step), set `COMPOSE_PROFILES=es,os,solr` as a step-level env var so smoke retains three-engine coverage even if the operator default flips. Use the existing `env:` block on the step OR prefix the `make up` command. |
| [`docs/03_runbooks/local-dev.md`](../../../../03_runbooks/local-dev.md) | Add a "Selecting a subset of engines" subsection after the quickstart. Cover: the `RELYLOOP_ENGINES` env var, the headline win, the trade-off (reset modal only seeds running subset), and the DX hazard for developers running `docker compose up` directly (must also set `COMPOSE_PROFILES=es,os,solr`). |
| [`docs/03_runbooks/corporate-network-install.md`](../../../../03_runbooks/corporate-network-install.md) | One paragraph noting `RELYLOOP_ENGINES` as a way to reduce registry-pull surface. Cross-link to local-dev.md's new subsection. |
| [`docs/01_architecture/deployment.md`](../../../../01_architecture/deployment.md) | Document the new `profiles:` field in the engine-services block. One paragraph + code excerpt. |

**Endpoints**

N/A.

**Key interfaces**

N/A.

**Pydantic schemas**

N/A.

**Tasks**

1. Write the `.env.example` `RELYLOOP_ENGINES` block. Match the existing comment style (long-form rationale, then a commented-out example). Include the warning that running `docker compose up` directly without `COMPOSE_PROFILES` set will skip all three engines.
2. Update Makefile `up:` target's `## …` doc-comment to mention the new env var.
3. Modify the smoke job in `pr.yml` to set `COMPOSE_PROFILES=es,os,solr` on the `make up` step. Verify by re-reading the workflow file diff — the assignment MUST be set in the step's `env:` (not the workflow-level env, which is overridable per job).
4. Write the `docs/03_runbooks/local-dev.md` subsection. Include a worked example: `RELYLOOP_ENGINES=es make up` and the expected wall-clock improvement.
5. Write the deployment.md paragraph + the corp-install one-paragraph callout.

**Definition of Done**

- [ ] `.env.example` documents `RELYLOOP_ENGINES` near `BASE_REGISTRY`; passes the `.env*` filename CI guard (no changes to filename).
- [ ] `make help` shows the new env-var description.
- [ ] `pr.yml` smoke job sets `COMPOSE_PROFILES=es,os,solr` explicitly on the `make up` step. [AC-14]
- [ ] `docs/03_runbooks/local-dev.md` has a "Selecting a subset of engines" section covering the new flag + the direct-`docker-compose-up` DX hazard.
- [ ] `docs/03_runbooks/corporate-network-install.md` mentions `RELYLOOP_ENGINES`.
- [ ] `docs/01_architecture/deployment.md` documents the engine `profiles:` block.
- [ ] Generated-artifacts-fresh CI gate green (no openapi changes expected this story — sanity check).

### Epic 1 gate

- [ ] Stories 1.1 + 1.2 complete.
- [ ] AC-1, AC-2, AC-3, AC-14, AC-15 satisfied.
- [ ] `make test-unit` green (no regressions; `parse_relyloop_engines` unit test landed).
- [ ] Docs landed in the same PR series.

---

## Epic 2 — Reset-to-demo backend (engine filter + capability endpoint)

**Outcome:** The backend can accept an `engines` filter on the reseed POST, exposes a capability endpoint for the frontend to query which engines are running, and reports user-excluded vs unreachable skips distinctly.

### Story 2.1 — Capability endpoint + `scenarios_skipped_reasons` field

**Outcome:** New `GET /api/v1/_test/demo/engines` returns per-engine reachability; `ReseedStatusResponse` carries a structured `scenarios_skipped_reasons` dict.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| [`backend/app/api/v1/_test.py`](../../../../../backend/app/api/v1/_test.py) | Add new route `@router.get("/_test/demo/engines", ...)` between the existing reseed routes (after line 736). Add the response Pydantic models `DemoEngineStatus` and `DemoEnginesResponse` either co-located or imported from `_test.py`'s schema block (mirror the existing `_test.py` pattern — co-located is fine). The handler uses `asyncio.gather` with three `is_engine_reachable(...)` calls, one per engine, against the canonical URLs. |
| [`backend/app/services/demo_seeding.py`](../../../../../backend/app/services/demo_seeding.py) | Add `scenarios_skipped_reasons: dict[str, Literal["user_excluded", "unreachable"]] = Field(default_factory=dict)` to `ReseedStatusResponse` (at [line 278](../../../../../backend/app/services/demo_seeding.py#L278) class definition). Pydantic backwards-compat: when deserializing cached payloads from Redis that lack the field, Pydantic's `default_factory=dict` populates an empty dict — no code change needed. |
| [`backend/app/services/demo_seeding.py`](../../../../../backend/app/services/demo_seeding.py) | Add a typed `_SkipReason = Literal["user_excluded", "unreachable"]` alias near the existing `_EngineType` alias at [line 443](../../../../../backend/app/services/demo_seeding.py#L443). |
| [`backend/app/api/v1/schemas.py`](../../../../../backend/app/api/v1/schemas.py) | None — the new Literal lives next to the `ReseedStatusResponse` model in `demo_seeding.py`, consistent with the existing model location. Cross-reference in a comment that the canonical `EngineTypeWire` at [`schemas.py:315`](../../../../../backend/app/api/v1/schemas.py#L315) is the source of truth for engine wire values. |

**Endpoints**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `GET` | `/api/v1/_test/demo/engines` | — | `200` `DemoEnginesResponse` | None — always 200 even when all engines unreachable; reachability data IS the payload. |

**Key interfaces**

```python
# backend/app/api/v1/_test.py — new route handler
@router.get(
    f"{_TEST_PREFIX}/demo/engines",
    response_model=DemoEnginesResponse,
    status_code=status.HTTP_200_OK,
    tags=["test-only"],
    dependencies=[Depends(_require_development_env)],
    summary="Report which engines are reachable (dev-only)",
)
async def demo_engines() -> DemoEnginesResponse:
    """Probe ES, OS, Solr concurrently; return per-engine reachability."""
    es_url = _resolve_engine_base_url("http://localhost:9200")
    os_url = _resolve_engine_base_url("http://localhost:9201")
    solr_url = _resolve_engine_base_url("http://localhost:8983")
    es_ok, os_ok, solr_ok = await asyncio.gather(
        is_engine_reachable(es_url, "elasticsearch"),
        is_engine_reachable(os_url, "opensearch"),
        is_engine_reachable(solr_url, "solr"),
    )
    return DemoEnginesResponse(
        engines=[
            DemoEngineStatus(engine_type="elasticsearch", reachable=es_ok),
            DemoEngineStatus(engine_type="opensearch", reachable=os_ok),
            DemoEngineStatus(engine_type="solr", reachable=solr_ok),
        ]
    )
```

**Pydantic schemas**

```python
# Co-located in backend/app/api/v1/_test.py (matching the pattern there).
# EngineTypeWire is imported from backend.app.api.v1.schemas — canonical source of truth.
from backend.app.api.v1.schemas import EngineTypeWire

class DemoEngineStatus(BaseModel):
    engine_type: EngineTypeWire
    reachable: bool

class DemoEnginesResponse(BaseModel):
    engines: list[DemoEngineStatus]
```

```python
# Extended in backend/app/services/demo_seeding.py
_SkipReason = Literal["user_excluded", "unreachable"]

class ReseedStatusResponse(BaseModel):
    # ... existing fields unchanged ...
    scenarios_skipped: list[str] = Field(default_factory=list)
    scenarios_skipped_reasons: dict[str, _SkipReason] = Field(default_factory=dict)
```

**Tasks**

1. Add the `_SkipReason` Literal alias in `demo_seeding.py` near `_EngineType`.
2. Add the `scenarios_skipped_reasons` field to `ReseedStatusResponse`.
3. Add `DemoEngineStatus` and `DemoEnginesResponse` Pydantic models in `_test.py` (importing `EngineTypeWire` from `schemas.py` per the source-of-truth discipline).
4. Implement the `GET /api/v1/_test/demo/engines` handler. Use `asyncio.gather` for parallel probing.
5. Add unit test `backend/tests/unit/services/test_reseed_status_skip_reasons.py` — covers default `{}`, JSON round-trip, and rejection of invalid Literal values.
6. Add integration test `backend/tests/integration/test_demo_engines_capability.py` — exercise the endpoint against the test stack (ES + OS service containers should report reachable=True; Solr returns reachable=False since the backend test lane doesn't run Solr).
7. Add contract test in `backend/tests/contract/test_test_endpoints_contract.py` (extend the existing file) — assert response shape, ordering of `engines[]` (deterministic: ES, OS, Solr), and that the response is always 200.
8. Update `backend/tests/contract/test_openapi_surface.py` to include the new endpoint and the new `scenarios_skipped_reasons` field on `ReseedStatusResponse`.

**Definition of Done**

- [ ] `GET /api/v1/_test/demo/engines` returns 200 + shape `{engines: [{engine_type, reachable}, ...]}` with all three engines in deterministic order. [AC-9]
- [ ] Endpoint returns 200 even when all three are unreachable (verified by stopping a service container in the integration test).
- [ ] `ReseedStatusResponse` carries `scenarios_skipped_reasons` defaulting to `{}`; round-trip JSON deserialization works.
- [ ] Unit test for the model passes.
- [ ] Integration test against the test stack passes (ES + OS reachable, Solr reachable=false).
- [ ] Contract test asserts the shape + ordering.
- [ ] OpenAPI surface test refreshed; `ui/openapi.json` regenerated and committed; the `generated-artifacts-fresh` CI gate stays green.

### Story 2.2 — Reseed POST body + orchestrator engine filter

**Outcome:** `POST /api/v1/_test/demo/reseed` accepts an optional `{engines: [...]}` filter; the orchestrator filters scenarios accordingly and applies the user_excluded reason; the rich ESCI scenario is included in the filter.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| [`backend/app/api/v1/_test.py`](../../../../../backend/app/api/v1/_test.py) | Add `ReseedRequest` Pydantic body model (co-located near `DemoEnginesResponse`). Modify `reseed_demo()` at [line 622](../../../../../backend/app/api/v1/_test.py#L622) to accept the optional body. Thread the resolved `engines` list (or None) into the Arq job's kwargs. |
| [`backend/workers/demo_reseed.py`](../../../../../backend/workers/demo_reseed.py) | Modify `run_demo_reseed(ctx, ..., engines: list[str] \| None = None)` at [line 92](../../../../../backend/workers/demo_reseed.py#L92) to accept the new kwarg and pass it through to `reseed_demo_state(..., engines=engines)`. |
| [`backend/app/services/demo_seeding.py`](../../../../../backend/app/services/demo_seeding.py) | Modify `reseed_demo_state(...)` at [line 1442](../../../../../backend/app/services/demo_seeding.py#L1442) to accept `engines: list[Literal["elasticsearch","opensearch","solr"]] \| None = None`. Apply the filter BEFORE the per-scenario reachability gate at [line 1578](../../../../../backend/app/services/demo_seeding.py#L1578): user-excluded scenarios get their slug appended to `progress.scenarios_skipped` + `progress.scenarios_skipped_reasons[slug] = "user_excluded"` before continuing. Apply the same filter to the rich ESCI scenario at [line 1962](../../../../../backend/app/services/demo_seeding.py#L1962) — when ES is not in the selected set, append `_RICH_SCENARIO_SLUG` with reason `user_excluded` BEFORE the rich-scenario dispatch path. Existing unreachable path adds reason `unreachable`. The `_is_all_engines_unreachable()` check at [line 232](../../../../../backend/app/services/demo_seeding.py#L232) is unchanged — both skip reasons count toward the threshold. |

**Endpoints**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `POST` | `/api/v1/_test/demo/reseed` | `{engines: list[EngineTypeWire] \| null} \| {} \| <empty body>` | `202` `ReseedStatusResponse` (initial running state) | `409 SEED_IN_PROGRESS`, `422 VALIDATION_ERROR`, `503 ARQ_POOL_UNAVAILABLE` |

**Key interfaces**

```python
# backend/app/api/v1/_test.py — extended endpoint signature
class ReseedRequest(BaseModel):
    engines: list[EngineTypeWire] | None = Field(
        default=None,
        description="If non-null, reseed only scenarios whose engine_type is in this list. "
                    "Null or omitted = reseed all reachable engines (current behavior). "
                    "Empty list is rejected at validation.",
        min_length=1,  # rejects empty list; null/omitted is still valid via the optional Field
    )

@router.post(
    f"{_TEST_PREFIX}/demo/reseed",
    ...
)
async def reseed_demo(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    body: ReseedRequest = Body(default_factory=ReseedRequest),  # absent body -> all-None
) -> ReseedStatusResponse:
    ...

# backend/workers/demo_reseed.py — extended worker signature
async def run_demo_reseed(
    ctx: dict[str, Any],
    *,
    engines: list[str] | None = None,
) -> None:
    ...

# backend/app/services/demo_seeding.py — extended orchestrator signature
async def reseed_demo_state(
    *,
    db: AsyncSession,
    api_client: httpx.AsyncClient,
    engine_client: httpx.AsyncClient,
    arq_redis: Redis,
    settings: Settings,
    status_callback: StatusCallback = _noop_status,
    engines: list[Literal["elasticsearch", "opensearch", "solr"]] | None = None,
) -> ReseedSummary:
    ...
```

**Pydantic schemas**

```python
class ReseedRequest(BaseModel):
    engines: list[EngineTypeWire] | None = Field(default=None, min_length=1)
```

The `min_length=1` constraint on the inner list enforces D-7: `engines: []` rejected at validation.

**Tasks**

1. Add `ReseedRequest` model + `Body(default_factory=ReseedRequest)` to the existing `reseed_demo()` route.
2. Thread `body.engines` into `arq_pool.enqueue_job("run_demo_reseed", engines=body.engines, _job_id=...)`.
3. Update `run_demo_reseed` worker to accept the kwarg + pass to the orchestrator.
4. Update `reseed_demo_state` to accept the kwarg + apply the filter in two places:
   - In the SCENARIOS loop at [line 1562](../../../../../backend/app/services/demo_seeding.py#L1562): BEFORE the reachability check, if `engines is not None and scenario["engine_type"] not in engines`, append to skipped + record `user_excluded` reason + continue.
   - Around the rich scenario dispatch at [line 1962](../../../../../backend/app/services/demo_seeding.py#L1962): when `engines is not None and "elasticsearch" not in engines`, skip the rich path with reason `user_excluded`.
5. Verify the `_is_all_engines_unreachable` semantics — `len(scenarios_skipped) >= len(SCENARIOS) + 1` still fires correctly when every scenario was either user-excluded or unreachable.
6. Update existing unit test [`backend/tests/unit/services/test_demo_reseed_partial_completion_fast.py`](../../../../../backend/tests/unit/services/test_demo_reseed_partial_completion_fast.py) — add cases for the new engine filter + reason recording.
7. Add new integration test `backend/tests/integration/test_demo_reseed_engines_filter.py` exercising the end-to-end orchestrator with `engines=["elasticsearch"]` against the test stack. Assert: ES scenarios complete with real rows; OS+Solr slugs appear in `scenarios_skipped` with reason `user_excluded`; `scenarios_total` stays at 5; final status `complete` not `failed`.
8. Add contract tests in `backend/tests/contract/test_test_endpoints_contract.py`:
   - `POST {engines: ["elasticsearch"]}` → 202 + initial body.
   - `POST {engines: ["fusion"]}` → 422 + envelope.
   - `POST {engines: []}` → 422 + envelope.
   - `POST {}` (empty body) → 202.
   - `POST` with no body at all → 202.
   - `POST {engines: null}` → 202.

**Definition of Done**

- [ ] `POST /api/v1/_test/demo/reseed` accepts `{engines: [...]}` and threads the list to the orchestrator. [AC-4]
- [ ] Invalid engine values rejected with 422 + `VALIDATION_ERROR` envelope. [AC-5]
- [ ] Empty list rejected with 422 + `VALIDATION_ERROR` envelope. [AC-8 / D-7]
- [ ] Null / missing / `{}` body all treated as "all engines" (current behavior). [AC-6]
- [ ] Orchestrator filters small scenarios + rich ESCI scenario by engine selection.
- [ ] User-excluded scenarios appear in `scenarios_skipped` with reason `user_excluded`; unreachable scenarios with reason `unreachable`. [AC-7]
- [ ] `_is_all_engines_unreachable` still fires when every scenario is user-excluded.
- [ ] Unit + integration + contract tests green.
- [ ] No regression in existing reseed integration tests with the default (no body) path.

### Epic 2 gate

- [ ] Stories 2.1 + 2.2 complete.
- [ ] AC-4 through AC-9 satisfied at the contract + integration layer.
- [ ] `make test-unit && make test-integration && make test-contract` all green.

---

## Epic 3 — Reset-to-demo modal UI

**Outcome:** The reset-to-demo dialog renders an engine-selection checkbox group, sends the selected set to the backend, and clearly displays user-excluded vs unreachable skips.

### Story 3.1 — Modal capability fetch + checkbox group + Confirm gating

**Outcome:** When the operator clicks the "Reset to demo state" trigger button, the dialog fetches `/api/v1/_test/demo/engines`, renders one checkbox per engine, and disables Confirm when nothing is selected.

**New files**

| File | Purpose |
|---|---|
| `ui/src/lib/api/demo-engines.ts` | TanStack Query hook `useDemoEnginesCapability()` calling `GET /api/v1/_test/demo/engines`. Cached for the dialog's lifetime; refetched on dialog open. Returns the typed `DemoEnginesResponse`. Mirror the pattern in [`ui/src/lib/api/demo-reseed.ts`](../../../../../ui/src/lib/api/demo-reseed.ts) — including the no-retry / no-poll posture and the 404-tolerant fallback (when the backend hasn't been rebuilt). |

**Modified files**

| File | Change |
|---|---|
| [`ui/src/components/dashboard/reset-demo-state-button.tsx`](../../../../../ui/src/components/dashboard/reset-demo-state-button.tsx) | Add a new "Engines to reseed" section to the `<AlertDialogHeader>` block between the existing description and the running/terminal blocks (after the description at [line 162-172](../../../../../ui/src/components/dashboard/reset-demo-state-button.tsx#L162-L172) when `!isRunning && !isTerminal`). Render the checkbox group from `useDemoEnginesCapability()`. Track a `selectedEngines: Set<EngineType>` state; default to all *reachable* engines. Pass it into the POST as `engines`. Disable Confirm when `selectedEngines.size === 0`. |
| [`ui/src/lib/enums.ts`](../../../../../ui/src/lib/enums.ts) | Add a new `as const` array `RESEED_SKIP_REASON_VALUES = ['user_excluded', 'unreachable'] as const;` with the source-of-truth comment `// Values must match backend/app/services/demo_seeding.py _SkipReason.` Export `ReseedSkipReason` type. |
| [`ui/src/lib/api/demo-reseed.ts`](../../../../../ui/src/lib/api/demo-reseed.ts) | Extend the `ReseedStatusResponse` interface with `scenarios_skipped_reasons: Record<string, ReseedSkipReason>` (defaults `{}` on backend; frontend treats missing key as `unreachable` for display). Add a new exported helper `postDemoReseed(engines: EngineType[] | null)` that calls the POST with the optional body — mirror the existing inline POST in `reset-demo-state-button.tsx`. |
| [`ui/openapi.json`](../../../../../ui/openapi.json) + [`ui/src/lib/types.ts`](../../../../../ui/src/lib/types.ts) | Regenerate via `bash scripts/regen-generated-artifacts.sh`. The `generated-artifacts-fresh` CI gate enforces this. |

**Endpoints** (frontend-consumed)

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `GET` | `/api/v1/_test/demo/engines` | — | `200` `DemoEnginesResponse` | none |
| `POST` | `/api/v1/_test/demo/reseed` | `{engines: EngineType[] \| null}` | `202` `ReseedStatusResponse` | `409 SEED_IN_PROGRESS`, `422 VALIDATION_ERROR`, `503 ARQ_POOL_UNAVAILABLE` |

**Pydantic schemas**

N/A (frontend story; backend models defined in Story 2.1 / 2.2).

**Tasks**

1. Write `ui/src/lib/api/demo-engines.ts` per the pattern. Hook signature: `useDemoEnginesCapability(opts: { enabled?: boolean }): UseQueryResult<DemoEnginesResponse, ApiError>`. Inline the `DemoEngineStatus` and `DemoEnginesResponse` types pending OpenAPI regen.
2. Add `RESEED_SKIP_REASON_VALUES` to `ui/src/lib/enums.ts` with the source-of-truth comment.
3. Extend `ReseedStatusResponse` in `ui/src/lib/api/demo-reseed.ts` to include `scenarios_skipped_reasons`. Export the new `postDemoReseed` helper.
4. Modify `reset-demo-state-button.tsx`:
   - Add `const enginesQuery = useDemoEnginesCapability({ enabled: open });` so the capability fetches when the dialog opens (not pre-emptively when the dashboard renders).
   - Track `const [selectedEngines, setSelectedEngines] = useState<Set<EngineType>>(new Set());`. Default to all reachable engines via a `useEffect` reacting to `enginesQuery.data`.
   - Render the checkbox group with shadcn/ui `Checkbox` primitive (already in the project) inside an `<div className="space-y-2">`.
   - Add a helper line above: `Defaults to all running engines. Unreachable engines are shown disabled.`
   - When `enginesQuery.data == null` (404 or in-flight), fall back to all three checkboxes enabled (per spec §11 error flow). Show a tiny inline `Couldn't probe engines — continuing as if all are reachable.` muted message.
   - Disable Confirm when `selectedEngines.size === 0`; helper-line text shows `Select at least one engine to reseed.`
   - Modify `startReseed` to POST `{engines: [...selectedEngines]}`. Use the new `postDemoReseed` helper.
5. Add a new vitest spec `ui/src/components/dashboard/__tests__/reset-demo-state-button.test.tsx` covering: checkbox group renders, default selection matches reachable engines, Confirm disabled when nothing selected, POST body matches selection, fallback when capability returns 404.
6. Add a new Playwright modal-only spec `ui/tests/e2e/reset-demo-state-modal.spec.ts` that opens the dialog and asserts the checkbox group + disabled state. Do NOT trigger an actual reseed (long-running). This spec can run in CI (unlike `demo-ubi.spec.ts` which is testIgnore'd).
7. Run `bash scripts/regen-generated-artifacts.sh` after the backend schema lands; commit the regenerated `ui/openapi.json` and `ui/src/lib/types.ts`.

**UI element inventory**

| Element | Type | Label | Data source | User interactions |
|---|---|---|---|---|
| "Engines to reseed" section heading | `<div>` heading | `Engines to reseed` | static | none |
| Helper line | `<p className="text-xs text-muted-foreground">` | `Defaults to all running engines. Unreachable engines are shown disabled.` | static | none |
| ES checkbox + label | shadcn/ui `Checkbox` + `<Label>` | `Elasticsearch` | `enginesQuery.data.engines[0]` | toggle adds/removes `'elasticsearch'` from `selectedEngines` |
| OS checkbox + label | shadcn/ui `Checkbox` + `<Label>` | `OpenSearch` | `enginesQuery.data.engines[1]` | toggle adds/removes `'opensearch'` from `selectedEngines` |
| Solr checkbox + label | shadcn/ui `Checkbox` + `<Label>` | `Apache Solr` | `enginesQuery.data.engines[2]` | toggle adds/removes `'solr'` from `selectedEngines` |
| Per-engine `(unreachable)` suffix | inline `<span className="text-xs text-muted-foreground">` | `(unreachable)` shown when `reachable === false` | derived | informational only |
| Confirm-disabled helper | `<p className="text-xs text-destructive">` | `Select at least one engine to reseed.` (only when `selectedEngines.size === 0`) | derived | none |
| Capability-fallback notice | `<p className="text-xs italic text-muted-foreground">` | `Couldn't probe engines — continuing as if all are reachable.` | when `enginesQuery.error != null \|\| enginesQuery.data == null` after first fetch | none |

**State dependency analysis**

```
New state in reset-demo-state-button.tsx:
- selectedEngines: Set<EngineType>
  - Initialized: empty Set
  - Synced: useEffect on enginesQuery.data → seed with all reachable
  - Mutated: checkbox onChange handlers
  - Consumed: startReseed body construction + Confirm-disabled gate
- enginesQuery: UseQueryResult from useDemoEnginesCapability({enabled: open})
  - Mutated: on dialog open via the `enabled` flag
  - Consumed: render checkbox group + fallback notice

Existing state NOT touched: pollingEnabled, statusQuery, lastTerminalAtRef, logRef, steps.
```

**Definition of Done**

- [ ] Dialog opens → `GET /api/v1/_test/demo/engines` fires (verify in vitest with mocked fetch). [AC-10]
- [ ] Checkboxes render with correct labels (`Elasticsearch`, `OpenSearch`, `Apache Solr`); reachable engines checked + enabled; unreachable engines unchecked + disabled with `(unreachable)` suffix. [AC-10]
- [ ] Unchecking all engines disables Confirm and shows the helper text. [AC-11]
- [ ] Confirm POST body matches selection (verified in vitest by intercepting the fetch). [AC-12]
- [ ] Capability fetch failure (404 / 5xx) falls back to all-enabled checkboxes + inline notice (no console flood).
- [ ] Vitest spec passes.
- [ ] Playwright modal-only spec passes in CI.
- [ ] Regenerated `ui/openapi.json` and `ui/src/lib/types.ts` committed; `generated-artifacts-fresh` gate green.
- [ ] `RESEED_SKIP_REASON_VALUES` source-of-truth comment passes the `form-select-discipline` lint guard (the comment matches the backend file/symbol).

### Story 3.2 — Two-reason partial-completion footer + runbook update

**Outcome:** When a reseed run terminates with mixed skip reasons, the operator sees user-excluded and unreachable skips on separate lines. Runbook explains the new distinction.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| [`ui/src/components/dashboard/reset-demo-state-button.tsx`](../../../../../ui/src/components/dashboard/reset-demo-state-button.tsx) | Replace the existing partial-completion footer at [line 195-217](../../../../../ui/src/components/dashboard/reset-demo-state-button.tsx#L195-L217) with a version that splits entries by `scenarios_skipped_reasons`. When the dict is empty (older cached payload), fall back to today's flat rendering. |
| [`docs/03_runbooks/demo-reseed-engine-tolerance.md`](../../../../03_runbooks/demo-reseed-engine-tolerance.md) | Add coverage of the new `user_excluded` reason — distinction from `unreachable`, when each fires, how the partial-completion contract still treats them both as `status=complete`. |

**Endpoints**

N/A.

**Key interfaces**

```tsx
// reset-demo-state-button.tsx — new render block (replaces existing partial footer)
{isTerminal && status?.status === 'complete' && status.scenarios_skipped.length > 0 && (
  <AlertDialogDescription asChild>
    <div
      className="text-xs italic text-muted-foreground"
      data-testid="reset-demo-state-partial"
    >
      <p>
        Partial completion — {status.scenarios_skipped.length} scenario
        {status.scenarios_skipped.length === 1 ? '' : 's'} skipped:
      </p>
      {(() => {
        const reasons = status.scenarios_skipped_reasons ?? {};
        // Fall back to today's flat rendering when the backend didn't send the new field
        // (older cached payload).
        const userExcluded: string[] = [];
        const unreachable: string[] = [];
        for (const slug of status.scenarios_skipped) {
          if (reasons[slug] === 'user_excluded') userExcluded.push(slug);
          else unreachable.push(slug);
        }
        return (
          <ul className="mt-1 list-disc space-y-0.5 pl-4">
            {userExcluded.length > 0 && (
              <li>
                <strong>You excluded:</strong> {userExcluded.join(', ')}
              </li>
            )}
            {unreachable.length > 0 && (
              <li>
                <strong>Engine unreachable:</strong> {unreachable.join(', ')}
              </li>
            )}
          </ul>
        );
      })()}
      <p className="mt-1">
        <a
          href="https://github.com/SoundMindsAI/relyloop/blob/main/docs/03_runbooks/demo-reseed-engine-tolerance.md"
          target="_blank"
          rel="noopener noreferrer"
          className="underline"
        >
          Why?
        </a>
      </p>
    </div>
  </AlertDialogDescription>
)}
```

**Tasks**

1. Replace the existing partial-completion footer block in `reset-demo-state-button.tsx`. Preserve the `data-testid="reset-demo-state-partial"` for backward-compat with existing tests.
2. Update the existing vitest spec (or add a focused one) to cover: mixed-reason rendering shows both sublines; empty `scenarios_skipped_reasons` falls back to flat list; single-reason runs render only the relevant subline.
3. Update [`docs/03_runbooks/demo-reseed-engine-tolerance.md`](../../../../03_runbooks/demo-reseed-engine-tolerance.md) with the new section covering `user_excluded`.

**Definition of Done**

- [ ] Partial-completion footer renders two separate sublines for mixed skip reasons. [AC-13]
- [ ] Single-reason runs render only the relevant subline (no empty `<li>`).
- [ ] Empty `scenarios_skipped_reasons` (older payload) falls back to today's flat list (no regression).
- [ ] Vitest spec covers all three cases.
- [ ] Runbook updated.

### Epic 3 gate

- [ ] Stories 3.1 + 3.2 complete.
- [ ] AC-10 through AC-13 satisfied.
- [ ] Vitest + Playwright modal-only spec green in CI.
- [ ] `form-select-discipline` and `data-table-column-discipline` lint guards green.

---

## UI Guidance

### Reference: current component structure

- **[`ui/src/components/dashboard/reset-demo-state-button.tsx`](../../../../../ui/src/components/dashboard/reset-demo-state-button.tsx)** — 267 lines.
  - Lines 1-46: imports + JSDoc.
  - Lines 47-131: `ResetDemoStateButton()` function — state hooks (`open`, `pollingEnabled`, `statusQuery`, `lastTerminalAtRef`, `logRef`, `steps`), `startReseed()` async handler, `progressPercent()` helper, two `useEffect`s (terminal-transition toasts + log auto-scroll).
  - Lines 132-266: JSX — `<Button>` trigger + `<AlertDialog>` block containing `<AlertDialogHeader>` (title + 4 conditional description states), step log, and `<AlertDialogFooter>` (3 conditional footer states).
  - Insertion point for Story 3.1: between line 172 (closing `</AlertDialogDescription>` of the `!isRunning && !isTerminal` description) and line 173 (opening of the `isRunning && status` description). The new "Engines to reseed" block lives inside the `!isRunning && !isTerminal` branch so it only renders pre-Confirm.
  - Insertion point for Story 3.2: lines 195-217 (the existing partial-completion footer block) is replaced wholesale.

### Analogous markup patterns

For Story 3.1's checkbox group, the closest existing pattern in the codebase is the form-select discipline showcase in `ui/src/components/`. Use shadcn/ui's `Checkbox` primitive directly (already a dependency). Skeleton:

```tsx
{/* Engine selection section — pattern: checkbox group inside an AlertDialog.
    The enums import enforces source-of-truth discipline (per CLAUDE.md
    "Enumerated Value Contract Discipline"). */}
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { ENGINE_TYPE_VALUES, type EngineType } from '@/lib/enums';

const ENGINE_LABELS: Record<EngineType, string> = {
  elasticsearch: 'Elasticsearch',
  opensearch: 'OpenSearch',
  solr: 'Apache Solr',
};

{!isRunning && !isTerminal && enginesQuery.data && (
  <div className="space-y-2" data-testid="reset-demo-state-engines">
    <div className="text-sm font-medium">Engines to reseed</div>
    <p className="text-xs text-muted-foreground">
      Defaults to all running engines. Unreachable engines are shown disabled.
    </p>
    <div className="space-y-1.5">
      {enginesQuery.data.engines.map((eng) => {
        const checked = selectedEngines.has(eng.engine_type);
        const disabled = !eng.reachable;
        return (
          <div key={eng.engine_type} className="flex items-center gap-2">
            <Checkbox
              id={`engine-${eng.engine_type}`}
              checked={checked}
              disabled={disabled}
              aria-disabled={disabled ? 'true' : undefined}
              onCheckedChange={(next) => {
                setSelectedEngines((prev) => {
                  const copy = new Set(prev);
                  if (next === true) copy.add(eng.engine_type);
                  else copy.delete(eng.engine_type);
                  return copy;
                });
              }}
              data-testid={`engine-checkbox-${eng.engine_type}`}
            />
            <Label
              htmlFor={`engine-${eng.engine_type}`}
              className={disabled ? 'text-muted-foreground' : ''}
            >
              {ENGINE_LABELS[eng.engine_type]}
              {disabled && (
                <span className="ml-1 text-xs italic text-muted-foreground">
                  (unreachable)
                </span>
              )}
            </Label>
          </div>
        );
      })}
    </div>
    {selectedEngines.size === 0 && (
      <p className="text-xs text-destructive" data-testid="reset-demo-engines-empty-hint">
        Select at least one engine to reseed.
      </p>
    )}
  </div>
)}
```

The `data-testid` attributes (`reset-demo-state-engines`, `engine-checkbox-<type>`, `reset-demo-engines-empty-hint`) mirror the existing `data-testid` discipline in the component (lines 146, 175, 200, 220, 226, 241, 248, 257).

### Layout and structure

- Stacked vertical layout inside the existing `<AlertDialogHeader>` block — between the description (line 172) and the next conditional block (line 173).
- Checkbox group is a flat column of `<Checkbox> + <Label>` pairs, vertical spacing via `space-y-1.5`.
- No responsive collapse needed — the dialog has a fixed max-width and three checkboxes always fit.
- Reuse Tailwind utility classes; no new CSS.

### Confirmation/modal dialog pattern

The dialog is already in place (existing `AlertDialog` block at line 150-264). Story 3.1 only adds a new section inside it; no new modal is introduced.

### Visual consistency table

| New element | CSS pattern source |
|---|---|
| Section heading | `text-sm font-medium` — matches existing dialog title weights. |
| Helper text | `text-xs text-muted-foreground` — matches the existing "Scenario X of Y" subline at [line 177](../../../../../ui/src/components/dashboard/reset-demo-state-button.tsx#L177). |
| Checkbox | `<Checkbox>` from shadcn/ui — already used elsewhere in the project. |
| Label | `<Label>` from shadcn/ui — already used elsewhere. |
| `(unreachable)` suffix | `text-xs italic text-muted-foreground` — matches the existing partial-completion subline at [line 198](../../../../../ui/src/components/dashboard/reset-demo-state-button.tsx#L198). |
| Confirm-disabled hint | `text-xs text-destructive` — matches the existing failed-reason rendering at [line 185-187](../../../../../ui/src/components/dashboard/reset-demo-state-button.tsx#L185-L187). |
| Bullet list (Story 3.2) | `list-disc pl-4 space-y-0.5` — basic Tailwind list. |

### Component composition

- All new JSX lives **inline inside `ResetDemoStateButton`**. Extracting an `<EngineCheckboxGroup>` subcomponent is not justified — it's used in exactly one place and shares state heavily with the parent.
- One new state addition: `selectedEngines: Set<EngineType>`.
- One new hook addition: `useDemoEnginesCapability({ enabled: open })`.

### Interaction behavior table

| User action | Frontend behavior | API call |
|---|---|---|
| Click "Reset to demo state" trigger | `setOpen(true)` | None (capability hook becomes `enabled`). |
| Dialog opens | `useDemoEnginesCapability({ enabled: true })` fires; on resolve, `useEffect` seeds `selectedEngines` with all reachable | `GET /api/v1/_test/demo/engines` |
| Toggle a checkbox | Add/remove engine from `selectedEngines` | None. |
| Click Confirm | `startReseed()` → POST with `{engines: [...selectedEngines]}` | `POST /api/v1/_test/demo/reseed` body `{engines}` |
| All checkboxes unchecked | Confirm button disabled; hint text visible | None. |
| Capability returns 404/5xx | Fall back: render all-checked + show inline notice | None (errors not retried — `retry: false` in the hook). |

### Handler function patterns

```tsx
// Sync selectedEngines with capability result on first successful fetch.
useEffect(() => {
  const data = enginesQuery.data;
  if (data == null) return;
  // Only auto-select on the first resolve per dialog session; if the operator
  // has already toggled, respect their choice.
  if (selectedEngines.size === 0) {
    const reachable = data.engines
      .filter((e) => e.reachable)
      .map((e) => e.engine_type);
    setSelectedEngines(new Set(reachable));
  }
}, [enginesQuery.data, selectedEngines.size]);

// Reset selection when the dialog closes so a re-open starts from the capability default.
useEffect(() => {
  if (!open) setSelectedEngines(new Set());
}, [open]);

async function startReseed(event: React.MouseEvent): Promise<void> {
  event.preventDefault();
  if (selectedEngines.size === 0) return;  // belt-and-suspenders; button is also disabled
  setPollingEnabled(true);
  try {
    await postDemoReseed([...selectedEngines]);
  } catch (err) {
    setPollingEnabled(false);
    // ... existing error handling unchanged ...
  }
}
```

### Information architecture placement

- Reset button location is unchanged — [`start-here-checklist.tsx:56`](../../../../../ui/src/components/dashboard/start-here-checklist.tsx#L56) on the home page `/`.
- New section ("Engines to reseed") lives inside the existing dialog, between the description and the per-state blocks. No new routes, no new sidebar entries.

### Tooltips and contextual help

Per spec §11, the tooltips in scope are inline helper text rather than hover tooltips (per the spec's "the helper line is the tooltip" pattern). The `(unreachable)` suffix's hover tooltip uses native `title` attribute (sufficient — no glossary key needed; the term is plain-language).

| Element | Tooltip text | Trigger | Placement | Glossary key | Source of truth |
|---|---|---|---|---|---|
| Engines-to-reseed helper line | `Defaults to all running engines. Unreachable engines are shown disabled.` | always-visible inline | below heading | none (helper text, not tooltip) | n/a |
| `(unreachable)` suffix | `This engine isn't running — start it via 'make up' with COMPOSE_PROFILES=<profile>, then reload.` | hover via `title` attr | browser default | none (plain-language) | n/a |
| Confirm-disabled hint | `Select at least one engine to reseed.` | conditional render when `selectedEngines.size === 0` | below checkbox group | none (helper text) | n/a |

No new glossary keys are introduced — all terminology (`engine`, `reseed`, `unreachable`) already appears in [`ui/src/lib/glossary.ts`](../../../../../ui/src/lib/glossary.ts) and the existing `start-here-checklist` copy.

### Legacy behavior parity

No legacy behavior parity table — no user-facing component >100 LOC is being deleted or migrated in this plan. Story 3.2 replaces the existing 22-line partial-completion footer block with a 30-line two-reason version, well below the 100-LOC threshold; both versions render `data-testid="reset-demo-state-partial"`, fall back to today's flat list when `scenarios_skipped_reasons` is empty, and preserve the "Why?" link to the runbook.

### Client-side persistence

None. The engine selection is per-dialog-open; not persisted to `localStorage`, `sessionStorage`, or cookies. On dialog re-open, the selection re-seeds from the capability response (all reachable).

---

## 3) Testing workstream

### 3.1 Unit tests

- Location: `backend/tests/unit/`
- Tasks:
  - [ ] `backend/tests/unit/scripts/test_parse_relyloop_engines.sh` (or `.bats`) — Story 1.1: default / valid subset / unknown / whitespace tolerance / dedup. (Place under `backend/tests/unit/scripts/` or as a sidecar to `install.sh` test infra; verify the right location during implementation by checking `backend/tests/unit/` layout.)
  - [ ] `backend/tests/unit/services/test_reseed_status_skip_reasons.py` — Story 2.1: `ReseedStatusResponse.scenarios_skipped_reasons` default `{}`, JSON round-trip, invalid Literal rejection.
  - [ ] Extend `backend/tests/unit/services/test_demo_reseed_partial_completion_fast.py` — Story 2.2: engine filter applied to small SCENARIOS + rich scenario, user_excluded recording, AllEnginesUnreachableError still fires.
- DoD:
  - [ ] All unit tests green.

### 3.2 Integration tests

- Location: `backend/tests/integration/`
- Tasks:
  - [ ] `backend/tests/integration/test_demo_engines_capability.py` — Story 2.1: capability endpoint against the test stack reports ES + OS reachable, Solr reachable=false (no Solr container in backend CI lane).
  - [ ] `backend/tests/integration/test_demo_reseed_engines_filter.py` — Story 2.2: end-to-end orchestrator with `engines=["elasticsearch"]`; OS+Solr slugs in `scenarios_skipped` with reason `user_excluded`; ES rows present in `clusters` / `studies`.
- DoD:
  - [ ] Both integration tests green against the backend CI service-container stack.

### 3.3 Contract tests

- Location: `backend/tests/contract/` (flat — no `/api/v1/` subdir; confirmed by `ls`)
- Tasks:
  - [ ] Extend `backend/tests/contract/test_test_endpoints_contract.py` with all six POST body shape cases from Story 2.2 DoD + the new `GET /demo/engines` shape from Story 2.1.
  - [ ] Refresh `backend/tests/contract/test_openapi_surface.py` to cover the new endpoint and the new field on `ReseedStatusResponse`.
- DoD:
  - [ ] Every error envelope shape from the spec's §8.5 is asserted (`VALIDATION_ERROR`, `SEED_IN_PROGRESS`, `ARQ_POOL_UNAVAILABLE` — the last two unchanged from existing tests).

### 3.4 E2E tests

- Location: `ui/tests/e2e/`
- Tasks:
  - [ ] `ui/tests/e2e/reset-demo-state-modal.spec.ts` — Story 3.1: opens the dialog against a real backend, asserts checkbox group renders, asserts unreachable-checkbox disabled state, asserts Confirm-disabled when nothing selected. Does NOT trigger an actual reseed (modal-only).
  - [ ] Existing `ui/tests/e2e/demo-ubi.spec.ts` is CI-excluded per `infra_smoke_reseed_runtime_budget` — update locally to exercise the modal's new checkbox + reseed path. CI exclusion stays.
- Rule per template: assertions must verify browser-visible behavior via Playwright's `page`. No `page.route()` mocking of backend calls.
- DoD:
  - [ ] Modal-only spec passes in CI (stable).
  - [ ] Local-only `demo-ubi.spec.ts` update verified manually.

### 3.5 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `backend/tests/unit/services/test_demo_reseed_partial_completion_fast.py` | `scenarios_skipped` assertions | several | Extend with `scenarios_skipped_reasons` assertions; update fixtures to pass the new `engines` kwarg through. |
| `backend/tests/contract/test_openapi_surface.py` | `ReseedStatusResponse` field list | 1 | Refresh after schema change; expect `scenarios_skipped_reasons` to appear in the regenerated OpenAPI. |
| `backend/tests/integration/_demo_reseed_uvicorn.py` | reseed orchestration helper | 1 | Verify it still works when the new `engines` kwarg defaults to None. |
| `ui/tests/e2e/demo-ubi.spec.ts` | reseed E2E | 1 | CI-excluded — update locally only. |
| `ui/src/components/dashboard/__tests__/*.test.tsx` | any pre-existing reset-button tests | 0–1 | If exists, extend; otherwise add new spec. |

### 3.6 Migration verification

N/A — no migration in this plan. Alembic head stays `0023_proposals_superseded_status`.

### 3.7 CI gates

- [ ] `make test-unit`
- [ ] `make test-integration`
- [ ] `make test-contract`
- [ ] `cd ui && pnpm test`
- [ ] `cd ui && pnpm lint && pnpm typecheck && pnpm build`
- [ ] `generated-artifacts-fresh` workflow green (openapi.json + types.ts regenerated)
- [ ] (optional, if `SMOKE_TEST=true`) smoke job green with three-engine coverage preserved

---

## 4) Documentation update workstream

### 4.0 Core context files

- [ ] **`state.md`** — at merge time, append a one-liner to "Last 5 merges" (newest-first, drop the 6th). Full narrative goes into `state_history.md`. Note: Phase 2 + 3 ideas remain in `planned_features/02_mvp2/feat_selective_engine_startup_and_demo/` (folder NOT moved to `implemented_features/`) per the impl-execute Step 8.6 rule — the folder stays in `planned_features/` until every deferred phase ships.
- [ ] **`architecture.md`** — no change required (no new services, no new data flows).
- [ ] **`CLAUDE.md`** — no change required (no new convention beyond what's documented in §15 docs updates).

### 4.1 Architecture docs

- [ ] [`docs/01_architecture/deployment.md`](../../../../01_architecture/deployment.md) — engine `profiles:` block + env-var mapping (Story 1.2).

### 4.2 Product docs

- [ ] None.

### 4.3 Runbooks

- [ ] [`docs/03_runbooks/local-dev.md`](../../../../03_runbooks/local-dev.md) — "Selecting a subset of engines" subsection (Story 1.2).
- [ ] [`docs/03_runbooks/corporate-network-install.md`](../../../../03_runbooks/corporate-network-install.md) — `RELYLOOP_ENGINES` paragraph (Story 1.2).
- [ ] [`docs/03_runbooks/demo-reseed-engine-tolerance.md`](../../../../03_runbooks/demo-reseed-engine-tolerance.md) — `user_excluded` reason (Story 3.2).

### 4.4 Security docs

- [ ] None.

### 4.5 Quality docs

- [ ] None.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

Keep scope bounded; do not consolidate the duplicate `_EngineType` literal in [`demo_seeding.py:443`](../../../../../backend/app/services/demo_seeding.py#L443) — Spec D-8 locks this as discoverable-but-not-blocking. The new Pydantic schemas import from the canonical `EngineTypeWire` at [`schemas.py:315`](../../../../../backend/app/api/v1/schemas.py#L315); the existing service-local alias stays for now.

### 5.2 Planned refactor tasks

None in this plan.

### 5.3 Refactor guardrails

- [ ] Behavioral parity proven by tests — covered by the unit/integration/contract gates above.
- [ ] Lint/typecheck green.
- [ ] No expansion of product scope beyond Phase 1.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| Docker Compose v2 with `profiles:` support | Story 1.1 | Implemented (project pins Compose v2) | If an extremely old Compose v1 environment hits this, `profiles:` is silently ignored and engines come up regardless — degrades to today's behavior, not a hard failure. |
| `is_engine_reachable` 2s timeout already in place | Story 2.1 | Implemented | None. |
| `EngineTypeWire` canonical Literal | Stories 2.1 + 2.2 + 3.1 | Implemented at [schemas.py:315](../../../../../backend/app/api/v1/schemas.py#L315) | None. |
| No engine in `depends_on` of api/worker/migrate | Story 1.1 | Verified at [docker-compose.yml:100-311](../../../../../docker-compose.yml#L100-L311) | If a future PR adds `depends_on: elasticsearch` on `api`, profile-gating would cascade-skip api. Mitigation: spec D-6 calls this out explicitly. |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Developer running `docker compose up -d` directly (bypassing `make up`) sees no engines | M | M | Document in `docs/03_runbooks/local-dev.md` (Story 1.2 DoD). The mitigation (`COMPOSE_PROFILES=es,os,solr docker compose up -d`) is one paste. |
| `parse_relyloop_engines` parser bug breaks first-run install | L | H | Unit test in Story 1.1 covers default / valid / invalid / whitespace cases. Manual smoke required in PR body. |
| `scenarios_skipped_reasons` deserialization regressions on cached Redis payloads | L | L | Field is additive with `default_factory=dict`. Pydantic populates `{}` for older payloads automatically. Story 2.1 DoD asserts round-trip. |
| Smoke job silently loses three-engine coverage if `COMPOSE_PROFILES` opt-in is missed | L | M | Story 1.2 explicit task + DoD; AC-14 asserts. |
| Capability endpoint's 6-second worst-case wall-clock (3 engines × 2s each, sequential) | L | L | Implementation uses `asyncio.gather` for parallel probing — bounds at ~2s. NFR §13 documents the budget. |

### Failure mode catalog

| Failure mode | Trigger | Expected behavior | Recovery |
|---|---|---|---|
| All three engines unreachable | Operator picks engines that aren't running (or stack misconfigured) | Reseed terminates `failed` with `failed_reason="all_engines_unreachable"` | Operator starts the engine(s), reruns reseed |
| Capability endpoint timeout (all 3 engines unreachable + their 2s each) | Engine containers down | Returns 200 with `reachable=false` for all three | Modal renders all-disabled; Confirm disabled |
| `RELYLOOP_ENGINES=es,fusion` | Typo in env var | install.sh exits 1 with explicit error stderr | Operator fixes the typo |
| Frontend `/demo/engines` returns 404 (backend not rebuilt) | Operator hasn't pulled the latest image | Modal falls back to all-enabled checkboxes + inline notice | Operator rebuilds the api container |
| Operator unchecks all engines | UI gate | Confirm button disabled, helper text shown | Operator picks at least one engine |

---

## 7) Sequencing and parallelization

### Suggested sequence

1. **Epic 2 first (backend)** — Story 2.1 then 2.2. Lets the frontend (Story 3.1) consume the real endpoint and regenerate openapi.json against a live spec.
2. **Epic 3 (frontend)** — Story 3.1 then 3.2.
3. **Epic 1 in parallel** — Stories 1.1 and 1.2 can land in parallel commits on the same branch; the Compose edit and the install.sh edit don't conflict with the Epic 2/3 backend/frontend work.

### Parallelization opportunities

- Epic 1 ↔ Epic 2 — fully parallel (different subsystems, no shared files).
- Story 3.1 ↔ Story 3.2 — sequential (Story 3.2 modifies the same component file Story 3.1 introduces new sections in; sequential avoids merge complexity).

---

## 8) Rollout and cutover plan

- **Rollout stages:** single PR. The feature is additive; no staged rollout needed.
- **Feature flag strategy:** None (the `RELYLOOP_ENGINES` env var is itself the operator opt-in; the reset modal change is behind a new UI section that always appears once the backend deploys).
- **Migration / cutover:** None.
- **Reconciliation / repair:** None.

---

## 9) Execution tracker

### Stories
- [ ] Story 1.1 — Compose profiles + install.sh `RELYLOOP_ENGINES` parsing
- [ ] Story 1.2 — `.env.example` + Makefile + smoke job profile opt-in + runbooks
- [ ] Story 2.1 — Capability endpoint + `scenarios_skipped_reasons` field
- [ ] Story 2.2 — Reseed POST body + orchestrator engine filter
- [ ] Story 3.1 — Modal capability fetch + checkbox group + Confirm gating
- [ ] Story 3.2 — Two-reason partial-completion footer + runbook update

### Done this sprint
(populated by `/impl-execute` as stories ship)

---

## 10) Story-by-Story Verification Gate

Per template. Each story attaches evidence for:
- [ ] Files created/modified match story scope
- [ ] Endpoint contract implemented exactly as documented
- [ ] Key interfaces implemented with compatible signatures
- [ ] Required tests added at all four layers where applicable
- [ ] `make test-unit && make test-integration && make test-contract` green
- [ ] `cd ui && pnpm test && pnpm lint && pnpm typecheck && pnpm build` green when frontend touched
- [ ] Migration round-trip — N/A this plan (no migration)
- [ ] Docs updated in same PR when behavior/contract changed

---

## 11) Plan consistency review

### Spec ↔ plan endpoint count
- Spec §8.1 lists 3 endpoints (existing POST + GET reseed status + new GET engines). Plan covers all 3 — POST + GET status modified in Story 2.2 / 2.1 respectively; new GET engines added in Story 2.1.  **Match.**

### Spec ↔ plan error code coverage
- Spec §8.5 lists 3 error codes (`VALIDATION_ERROR`, `SEED_IN_PROGRESS`, `ARQ_POOL_UNAVAILABLE`). Plan Story 2.2 DoD + Story 3.3 contract test tasks cover all three.  **Match.**

### Spec ↔ plan FR coverage
- All 10 FRs mapped in §1 above. Every FR has at least one story assignment. **Match.**

### Story internal consistency
- Story 2.1 / 2.2 endpoint tables match the Pydantic schemas (engines list typing, response shape).
- Story 1.1 / 1.2 modify only `docker-compose.yml`, `install.sh`, `.env.example`, `Makefile`, `pr.yml`, and three docs files — verified to exist via the codebase audit at Story 1.1 / 1.2 modified-file tables.
- Story 3.1 / 3.2 modify `reset-demo-state-button.tsx`, `demo-reseed.ts`, `enums.ts`, and add `demo-engines.ts` — all verified to exist (the new file is explicitly listed as new).
- No file ownership conflict: each file touched by exactly the stories that touch it. Stories 3.1 and 3.2 both modify `reset-demo-state-button.tsx` but at different blocks (3.1 inserts the engine selector; 3.2 replaces the partial-completion footer); sequential execution avoids merge complexity.

### Test file count and assignment
- Unit: 3 test additions (Story 1.1 parser test, Story 2.1 model test, Story 2.2 extension). All assigned.
- Integration: 2 new files (Story 2.1 capability, Story 2.2 filter). All assigned.
- Contract: extensions to 2 existing files (test_test_endpoints_contract.py, test_openapi_surface.py). All assigned.
- E2E: 1 new modal-only spec (Story 3.1). Assigned.
- Vitest: 1 new component spec (Story 3.1) + 1 extension (Story 3.2). Assigned.

**No orphaned test files.**

### Gate arithmetic
- Epic 1 gate asserts AC-1/2/3/14/15. Stories 1.1 + 1.2 cover all five. **Match.**
- Epic 2 gate asserts AC-4 through AC-9. Stories 2.1 + 2.2 cover all six. **Match.**
- Epic 3 gate asserts AC-10 through AC-13. Stories 3.1 + 3.2 cover all four. **Match.**

### Open questions resolved
- Spec §19 has zero open questions and 8 locked decisions. All forks resolved at spec time. **Plan inherits clean state.**

### Frontend UI Guidance completeness
- Insertion points: documented in "Reference: current component structure" (line 172, lines 195-217). ✓
- Analogous markup patterns: actual JSX provided. ✓
- Layout and structure: documented. ✓
- Confirmation/modal dialog pattern: reuses existing `AlertDialog`. ✓
- Visual consistency table: provided. ✓
- Component composition: inline rationale documented. ✓
- Interaction behavior table: provided. ✓
- Handler function patterns: provided (useEffect for sync; useEffect for reset; startReseed). ✓
- Information architecture placement: documented. ✓
- Tooltips and contextual help: provided (all inline helper text, no new glossary keys). ✓
- Legacy behavior parity: explicit statement that no component >100 LOC is deleted. ✓

### Plan ↔ codebase verification
- Migration directory: N/A (no migration).
- Alembic head: not bumped; head stays `0023_proposals_superseded_status` per state.md.
- Router registration: verified `_test` router at [backend/app/main.py:219](../../../../../backend/app/main.py#L219); new endpoint inherits the existing registration.
- State variables (Story 3.1): the new `selectedEngines` doesn't collide with existing names (`open`, `pollingEnabled`, `lastTerminalAtRef`, `logRef`, `steps`). ✓
- Capability endpoint: `is_engine_reachable` (line 446), `_resolve_engine_base_url` (line 401), and `EngineTypeWire` (schemas.py:315) all verified to exist.
- The `_is_all_engines_unreachable` semantics check at demo_seeding.py:232 verified.

### Enumerated value contract audit
- `engines[*]` wire values: spec §8.4 cites `EngineTypeWire` at schemas.py:315 — grepped and matches `['elasticsearch','opensearch','solr']`.
- Frontend mirror: `ENGINE_TYPE_VALUES` at [ui/src/lib/enums.ts:43](../../../../../ui/src/lib/enums.ts#L43) — verified to cite the backend source and match character-for-character.
- New `RESEED_SKIP_REASON_VALUES` (Story 3.1): cited backend source `backend/app/services/demo_seeding.py _SkipReason` — Story 2.1 creates this Literal alias. Source-of-truth comment required per the `form-select-discipline` lint guard.
- No other dropdowns or filter values introduced.

### Audit-event coverage audit
- Activates at MVP2 (audit_log) — but this feature only touches the `_test/` namespace, which is explicitly excluded from audit emission per CLAUDE.md "Common Pitfalls" (dev-only, not a business mutation surface). Spec §6 marks audit events N/A and justifies. **No audit gap.**

---

## 12) Definition of plan done

- [x] Every FR mapped to stories/tasks/tests/docs.
- [x] Every story includes New files, Modified files, Endpoints (where applicable), Key interfaces, Tasks, DoD.
- [x] Test layers explicitly scoped.
- [x] Documentation updates planned and owned by stories.
- [x] Lean refactor scope explicit (none).
- [x] Phase/epic gates measurable.
- [x] Story-by-Story Verification Gate included.
- [x] Plan consistency review performed (no findings).

This plan is **Ready for Execution**.
