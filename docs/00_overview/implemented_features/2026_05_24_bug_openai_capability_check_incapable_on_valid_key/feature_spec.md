# Feature Specification — OpenAI capability check: surface `models_endpoint` status in `/healthz`

**Date:** 2026-05-24
**Status:** Draft
**Owners:** soundminds.ai (engineering)
**Related docs:**
- [idea.md](idea.md)
- [docs/01_architecture/llm-orchestration.md §"Capability check at startup"](../../../01_architecture/llm-orchestration.md)
- [docs/00_overview/implemented_features/2026_05_09_infra_foundation/feature_spec.md FR-2 / FR-7](../../../00_overview/implemented_features/2026_05_09_infra_foundation/feature_spec.md)

**Depends on:** [`infra_foundation`](../../../00_overview/implemented_features/2026_05_09_infra_foundation/) (shipped)

---

## 1) Purpose

- **Problem:** When `/healthz` reports `subsystems.openai: "incapable"`, the `openai_capabilities` response block shows all three sub-capabilities (`chat`, `function_calling`, `structured_output`) as `"untested"` — leaving the operator with no in-response signal of *which* probe failed. This is the documented behavior when the **step-1 `GET {base_url}/models` probe** fails (see [`backend/app/llm/capability_check.py:310-314`](../../../../backend/app/llm/capability_check.py#L310-L314)): steps 2–4 are intentionally skipped because they can't succeed against an unreachable endpoint. The `models_endpoint: "fail"` value is stored in the cached `CapabilityResult` (see [`backend/app/llm/capability_models.py:24`](../../../../backend/app/llm/capability_models.py#L24)) but never surfaced in the `/healthz` response — the response model omits the field (see [`backend/app/api/health.py:72-82`](../../../../backend/app/api/health.py#L72-L82)). The failure reason (HTTP status code) is logged at WARN inside the api container but is invisible to anyone polling `/healthz`.
- **Outcome:** `/healthz` exposes which probe failed (specifically: surfaces `models_endpoint` status) and, when the failure was an HTTP error, the status code that triggered it (e.g., 401 → bad key; 429 → quota). Operators tailing `curl /healthz` and humans triaging tutorial-path regressions can distinguish "bad key" from "endpoint unreachable" without reading container logs. The new fields surface in CI via the existing `smoke-logs.txt` artifact built at [`.github/workflows/pr.yml:444-445`](../../../../.github/workflows/pr.yml#L444-L445) (`curl -s http://127.0.0.1:8000/healthz >> smoke-logs.txt`), which runs in the smoke job's always-attach step after the smoke pytest skip-or-fail. **No `.github/workflows/pr.yml` edits in this PR** (see §3 "Out of scope" + §11 flow 2 + §19 D-6).
- **Non-goal:** Not changing the underlying probe sequence or the cache schema's wire shape *outside* `models_endpoint` exposure; not surfacing OpenAI error-response bodies (which can quote the bad API key back and would leak the secret); not rotating any operator credentials; not blocking startup if the probe fails (capability check remains fire-and-forget per CLAUDE.md Absolute Rule #11).

## 2) Current state audit

### Existing implementations

- [`backend/app/llm/capability_check.py`](../../../../backend/app/llm/capability_check.py): 4-step probe orchestrator. `check_capabilities()` already writes `models_endpoint: "ok"|"fail"` into `CapabilityResult` (line 326) and skips steps 2–4 with `"untested"` when step 1 fails (lines 310–314). WARN logs at lines 67–80 capture `status_code` for HTTP failures and `error` for network failures — but the values are not durably stored.
- [`backend/app/llm/capability_models.py`](../../../../backend/app/llm/capability_models.py): `CapabilityResult` Pydantic model. Already carries `models_endpoint: Literal["ok", "fail"]`. **Does not carry** any failure-reason field (status code, error kind). Cache is serialized via `model_dump_json()` so any new optional field is additive — Redis-cached pre-fix rows deserialize cleanly as Pydantic ignores absent optional fields.
- [`backend/app/api/probes.py`](../../../../backend/app/api/probes.py): `probe_openai_state()` at lines 136–160 already correctly returns `"incapable"` when `models_endpoint == "fail"` (line 158). The mapping logic does not need to change.
- [`backend/app/api/health.py`](../../../../backend/app/api/health.py): `OpenAICapabilities` response model at lines 72–82 exposes only `chat / function_calling / structured_output`. `models_endpoint` is intentionally omitted — this is the observability gap. The handler at lines 276–286 constructs the response from `cap.chat_completion / cap.function_calling / cap.structured_output` only.
- [`backend/tests/unit/test_capability_check.py`](../../../../backend/tests/unit/test_capability_check.py): exhaustive httpx-mocked test matrix covering all probe outcomes. The "models endpoint fails → downstream `untested`" branch is covered by the existing tests (see Story 3.3 docstring).
- [`backend/tests/unit/test_probes.py:163`](../../../../backend/tests/unit/test_probes.py#L163): `test_probe_openai_state` already asserts that `models_endpoint="fail"` → `"incapable"`.
- [`backend/tests/unit/test_health.py`](../../../../backend/tests/unit/test_health.py): integration-style health-endpoint tests; will need a new assertion that the response surfaces `models_endpoint` and `models_endpoint_status_code`.
- [`.github/workflows/pr.yml`](../../../../.github/workflows/pr.yml) smoke gate: the `Wait for /healthz` step at [`pr.yml:354-365`](../../../../.github/workflows/pr.yml#L354-L365) loops on `curl /healthz | jq '.status == "ok"'`. Because openai `incapable` is non-blocking ([`health.py:127-138`](../../../../backend/app/api/health.py#L127-L138)), the wait loop SUCCEEDS on the broken-key case. The actual gate red comes from the smoke pytest at [`backend/tests/smoke/test_tutorial_path.py`](../../../../backend/tests/smoke/test_tutorial_path.py), which `pytest.skip`s when `subsystems.openai == "incapable"` per `idea.md`'s origin note. Diagnosis today requires reading container logs; this fix surfaces the failing probe directly in the `/healthz` response body that the smoke-test attach-artifacts step at [`pr.yml:444-445`](../../../../.github/workflows/pr.yml#L444-L445) already captures into `smoke-logs.txt`.

### Navigation and link impact

N/A — this bug touches API response shape and one architecture-doc paragraph; no UI routes or navigation are affected.

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `backend/tests/unit/test_health.py` | `OpenAICapabilities(chat=..., function_calling=..., structured_output=...)` construction in fixtures + body-shape assertions | ~10 sites | Add `models_endpoint` to fixtures / assertions; add a new case asserting `models_endpoint_status_code` is surfaced when probe HTTP-fails |
| `backend/tests/unit/test_probes.py` | `_make_cap()` helper builds `CapabilityResult` — already passes `models_endpoint`, no change | 1 site | No structural change; may add a case asserting the new optional `models_endpoint_status_code` round-trips through `probe_openai_state` (state mapping unchanged) |
| `backend/tests/unit/test_capability_check.py` | Asserts cached `CapabilityResult` fields after each mocked-probe scenario | ~8 cases | Add `models_endpoint_status_code` field assertion to the existing "models endpoint fails" cases (401 / 429 / network error) |
| `backend/tests/unit/agent/conftest.py` | `CapabilityResult(...)` fixtures at lines 169, 184 | 2 sites | Backwards-compatible — `models_endpoint_status_code` is optional; existing fixtures keep passing |
| `backend/tests/unit/services/test_agent_judgments_dispatch.py` | imports `CapabilityResult` | 1 site | No change — new field is optional |
| `backend/tests/contract/test_health_contract.py` | OpenAPI response-shape assertions on `/healthz` | 1 file | Update to require `models_endpoint` ∈ `OpenAICapabilities`; require `models_endpoint_status_code` as optional |
| `backend/tests/contract/test_openapi_surface.py` | Surface-level OpenAPI assertions | 1 file | Verify the surface still matches; no new endpoints, only an additive response-model change |

### Existing behaviors affected by scope change

- **`/healthz` response shape:** Currently `openai_capabilities: {chat, function_calling, structured_output}` (3 fields). New: `openai_capabilities: {models_endpoint, chat, function_calling, structured_output, models_endpoint_status_code?}` (4 fields + 1 optional). **Backwards-compatible additive** — existing consumers (smoke-gate `_wait_healthy`, dashboard, operator scripts) that read only the three existing fields continue to work. Any new consumer can opt in to the new fields.
- **`CapabilityResult` cache schema:** Adding `models_endpoint_status_code: int | None = None` is an additive change. Redis-cached pre-fix entries (24h TTL) deserialize cleanly because Pydantic treats the absent field as `None`. No schema migration needed; old cache rows naturally expire within 24h.
- **`subsystems.openai` value (top-level):** Unchanged. Still maps `{models_endpoint OR chat OR fc OR struct} == "fail"` → `"incapable"`. The user's smoke-gate decision logic does not need to change.
- **Probe ordering and skip behavior:** Unchanged. Step-1 failure still skips steps 2–4. The fix is purely about *visibility* of an already-correct internal state.

---

## 3) Scope

### In scope

- Add `models_endpoint: Literal["ok", "fail", "untested"]` field to the `OpenAICapabilities` **response model** in [`backend/app/api/health.py`](../../../../backend/app/api/health.py). Project from the cached `CapabilityResult.models_endpoint` when a cache hit exists; map the **no-cap / cache-miss** branch to `"untested"`. Critically: `"untested"` exists only in the response model, NOT in the cached `CapabilityResult` schema (per §19 D-2; see also FR-1 / FR-3 / AC-6).
- Add `models_endpoint_status_code: int | None` field to **both** `CapabilityResult` (cached schema, default `None`) **and** `OpenAICapabilities` (response model, default `None`). The field is **always present in the `/healthz` JSON** with explicit `null` for the non-failure cases (success / cache miss / network-class failures) — rely on Pydantic `model_dump()`'s default behavior of including `None` fields (consistent with `JSONResponse(content=body.model_dump())` at [`health.py:298`](../../../../backend/app/api/health.py#L298)); do NOT pass `exclude_none=True`.
- Update [`backend/app/llm/capability_check.py:_probe_models_endpoint()`](../../../../backend/app/llm/capability_check.py#L61) to return `tuple[bool, int | None]` with the **exact contract**:
  - Return `(True, None)` for any successful HTTP response (status < 400 — matches the existing `resp.status_code >= 400` check at [`capability_check.py:74`](../../../../backend/app/llm/capability_check.py#L74)).
  - Return `(False, resp.status_code)` ONLY when the HTTP response carries status >= 400 (e.g., 401, 403, 429, 5xx).
  - Return `(False, None)` when the call raised `httpx.HTTPError` before any HTTP response was received (network class: timeout / DNS / connection-refused).
  - Thread the status code through to the `CapabilityResult(...)` construction at [`capability_check.py:326`](../../../../backend/app/llm/capability_check.py#L326).
- Update the WARN log at [`capability_check.py:75-80`](../../../../backend/app/llm/capability_check.py#L75-L80) to keep emitting the same `status_code` value (no change — log already includes it; this just confirms we keep parity between log and cached field).
- Update [`docs/01_architecture/llm-orchestration.md` §"Capability check at startup"](../../../01_architecture/llm-orchestration.md) to:
  - Document the response shape including the new fields
  - Add an explanatory paragraph on the `models_endpoint=fail → chat/fc/struct=untested` cascade
  - Add the "repo secret vs. operator's `.env` divergence" risk note from `idea.md`'s suggested-fix-path step 2 — surface that the value populated in the GitHub Actions `OPENAI_API_KEY_TEST` repo secret may not match any individual operator's `.env`; recommend the smoke-gate runner-side log-tail recipe for diagnosing 401-class failures.
- Update all affected tests (see §2 "Existing test impact" table).

### Out of scope

- **Rotating the repo `OPENAI_API_KEY_TEST` secret.** This is an operator action requiring access to GitHub repo settings (per [implementation_plan.md §7.5](../../../00_overview/implemented_features/2026_05_09_infra_foundation/implementation_plan.md) canonical handoff list — Claude cannot modify repo secrets). The fix surfaces the diagnostic the operator needs to decide if rotation is required.
- **Investigating which probe the production repo-secret key fails against.** The fix exposes the diagnostic; once shipped, the operator reads it from the `smoke-logs.txt` artifact built at [`pr.yml:444-445`](../../../../.github/workflows/pr.yml#L444-L445) (the `Wait for /healthz` failure-step curl at `pr.yml:364` does NOT fire on openai-incapable — that loop succeeds). If the diagnosis is "401 on `/models`" (most likely per `idea.md` hypothesis #1), the follow-up is a separate operator action (key rotation), not code.
- **Surfacing OpenAI error response *bodies* in `/healthz`.** OpenAI's 401 response often quotes the bad API key back in the JSON error body (e.g., `{"error":{"message":"Invalid Bearer token: sk-…"}}`). Surfacing the body would leak the secret into operator terminals, CI logs (which are public on the GitHub Actions workflow page), and any third-party log aggregator that scrapes `/healthz`. **Only the integer HTTP status code is exposed**, never the response body. The WARN log path (which goes to container stdout, not `/healthz`) already keeps the response body out per [`capability_check.py:76`](../../../../backend/app/llm/capability_check.py#L76) — it logs `status_code` only.
- **Adding `models_endpoint_status_code` for the success path.** When `models_endpoint = "ok"`, no status code is reported (it would always be 200; not useful diagnostic information; keeps the response body small).
- **Changing the per-probe HTTP timeout** (`PROBE_HTTP_TIMEOUT_SECONDS = 5.0`). Existing value is correct per Story 3.3 cold-start tolerance.
- **Changing the cache TTL** (24h). Existing TTL is correct per Story 3.3.
- **Migrating cached `CapabilityResult` rows.** Adding an optional field is backwards-compatible; existing cache rows expire within 24h.
- **UI changes.** The `/healthz` response is consumed only by the smoke-gate helper and operator curl. No UI route renders this field.
- **CI workflow / smoke-gate helper changes.** No edits to `.github/workflows/pr.yml`'s `Wait for /healthz` step, the smoke-pytest skip predicate, or any `curl /healthz` capture. The existing smoke-test artifact capture at [`pr.yml:444-445`](../../../../.github/workflows/pr.yml#L444-L445) publishes the raw `/healthz` response into `smoke-logs.txt`, which post-fix will include the new fields — this is the relevant capture for the openai-incapable case (the `Wait for /healthz` step *succeeds* even when openai is incapable, so its failure curl at [`pr.yml:364`](../../../../.github/workflows/pr.yml#L364) does not fire in that scenario). Eager pre-parsing into a one-line CI diagnostic is a follow-up.

### API convention check

- **Endpoint prefix convention:** `/healthz` is **unprefixed** (operator endpoint), per CLAUDE.md Absolute Rule #6 and [`backend/app/api/health.py:30`](../../../../backend/app/api/health.py#L30). This bug does not change the endpoint path.
- **Router namespace:** [`backend/app/api/health.py`](../../../../backend/app/api/health.py) (`router = APIRouter()`, no prefix).
- **HTTP methods:** GET — unchanged.
- **Non-auth error envelope shape:** N/A — `/healthz` returns the same `HealthResponse` body on both HTTP 200 and HTTP 503 per [`health.py:204-205`](../../../../backend/app/api/health.py#L204-L205). Not affected.
- **Auth error shape:** N/A — `/healthz` is unauthenticated per Absolute Rule #6.

### Phase boundaries

Single phase — this is a bounded observability bug. All FRs ship in one PR.

## 4) Product principles and constraints

- **CLAUDE.md Absolute Rule #6:** `/healthz` is unauthenticated by design. Any new fields must remain safe to expose without auth (no PII, no secret material).
- **CLAUDE.md Absolute Rule #10:** Never log or expose secrets. The `models_endpoint_status_code` field is intentionally **an integer status code only**, never a response-body excerpt. OpenAI 401 bodies can quote bad bearer tokens — those must never enter the `/healthz` JSON.
- **CLAUDE.md Absolute Rule #11:** `/healthz` per-probe timeout = 200ms; total p99 < 500ms. This fix touches only the response-shape projection (reading from a value already in the in-memory `CapabilityResult` after the cache read at [`health.py:262`](../../../../backend/app/api/health.py#L262)). Zero new I/O. No latency impact.
- **Backwards-compatible additive change to public API response.** Existing `/healthz` consumers (smoke-gate `_wait_healthy`, operators) must not break.
- **Backwards-compatible additive change to internal `CapabilityResult` schema.** Existing Redis cache rows must deserialize cleanly until they expire naturally (24h).

### Anti-patterns

- **Do not** include `response.text` or `response.json()` content in the response or in `CapabilityResult`. OpenAI quotes invalid bearer tokens back in 401 errors; surfacing the response body in `/healthz` would publish the bad key to anyone polling — including the public CI workflow page when the smoke gate fails.
- **Do not** add `models_endpoint_status_code` for the 2xx / `ok` case. It's noise; only set the field when `models_endpoint == "fail"` AND the failure was an HTTP response (status >= 400). Use `None` for the success case and for network-class failures (timeout / DNS / connection-refused).
- **Do not** change the cache key, TTL, or value serialization beyond the additive field. Any breaking serialization change would create a 24h window where production reads cache rows that deserialize incorrectly.
- **Do not** make `models_endpoint_status_code` required in the response model. It must be optional / nullable — `None` is the documented value for network-error failures.
- **Do not** add a `models_endpoint_error_message` string field. Even seemingly-safe error strings can leak — better to document "see api container logs at `step=models_endpoint` for the WARN entry" via the architecture doc.
- **Do not** treat this as a probe-logic bug. The probe sequence is correct (skip-on-step-1-fail is documented in the file's module docstring); this is purely a response-shape observability gap. Do not refactor probe ordering.

## 5) Assumptions and dependencies

- Dependency: `infra_foundation` (shipped 2026-05-09, PR #4)
  - Why required: Provides `CapabilityResult`, `_probe_models_endpoint`, `OpenAICapabilities`, and the `/healthz` shape we're extending.
  - Status: Implemented.
  - Risk if missing: N/A — already merged to main.
- Dependency: Redis (cache subsystem)
  - Why required: Caches the `CapabilityResult` for 24h.
  - Status: Implemented (`infra_foundation` Story 3.3).
  - Risk if missing: Cache miss returns the no-cap branch in [`health.py:282-286`](../../../../backend/app/api/health.py#L282-L286). The new `models_endpoint` field follows the same pattern: it **MUST** be `"untested"` and `models_endpoint_status_code` **MUST** be `null` (per §19 D-1 + D-2 + FR-1). The broader operator signal remains `subsystems.openai == "configured"` from the cache-miss path of `probe_openai_state` at [`probes.py:151`](../../../../backend/app/api/probes.py#L151).
- Assumption: The `_probe_models_endpoint` function's existing call sites (only `check_capabilities` per grep) are the only callers — modifying the return type does not break external consumers. Verified via Pass 1 grep below.

## 6) Actors and roles

- Primary actor: Operator running the local stack (developer laptop or GitHub Actions runner) who polls `/healthz`.
- Role model: N/A — single-tenant install, no auth surface (MVP1, per [`tech-stack.md` §"Canonical release matrix"](../../../01_architecture/tech-stack.md)).
- Permission boundaries: N/A.

### Authorization

N/A — single-tenant install, no auth surface. `/healthz` is unauthenticated by design.

### Audit events

N/A — `audit_log` table lands at MVP2. This bug fix lives in MVP1 and adds no state mutations.

## 7) Functional requirements

### FR-1: `/healthz` response surfaces `models_endpoint` status

- Requirement:
  - The `/healthz` response `openai_capabilities` object **MUST** include a `models_endpoint` field of type `Literal["ok", "fail", "untested"]` (response model only — see FR-3 for the cached schema, which stays 2-valued).
  - When the capability cache is populated (hit), the field value **MUST** be projected from `CapabilityResult.models_endpoint` — i.e., `"ok"` or `"fail"`.
  - When the capability cache is empty (miss — pre-startup, post-flush, or Redis-down), the field value **MUST** be `"untested"`, matching the existing pattern for `chat / function_calling / structured_output` on the same code path at [`health.py:282-286`](../../../../backend/app/api/health.py#L282-L286).
  - The field **MUST** be a sibling of `chat / function_calling / structured_output` (same nesting level) in the `OpenAICapabilities` block, NOT promoted to `subsystems`.
- Notes: This is a backwards-compatible additive field. Existing consumers reading only the three existing fields continue to work unchanged. The `"untested"` literal exists in the **response model only**; the cached `CapabilityResult.models_endpoint` remains `Literal["ok", "fail"]` because the cache only stores results of actual probe runs (the cache-miss case is represented by `cap is None`, not by a `CapabilityResult` row with `"untested"`).

### FR-2: `/healthz` response exposes HTTP status code on `models_endpoint` HTTP failures

- Requirement:
  - The `/healthz` response `openai_capabilities` object **MUST** include a `models_endpoint_status_code` field declared as **required-but-nullable** (`int | None`) — the field is REQUIRED in the OpenAPI schema with a nullable integer value, and is always present in the JSON body with explicit `null` when no value. Pydantic declaration: `models_endpoint_status_code: int | None = Field(...)` (no default, explicitly passed at every construction site so it is OpenAPI-required not OpenAPI-optional). The response handler **MUST NOT** use `exclude_none=True` when serializing.
  - The field **MUST** be populated with the HTTP status code (integer, e.g., `401`, `403`, `429`, `503`) when the step-1 probe received an HTTP response with status >= 400.
  - The field **MUST** be `null` when (a) `models_endpoint == "ok"` (no failure), (b) the step-1 probe failed via network error (timeout / DNS failure / connection-refused — no HTTP response received), or (c) the cache is empty (cache miss).
  - The field **MUST NOT** include any portion of the OpenAI response body (`response.text` / `response.json()` content) — only the integer status code.
- Notes: This is the single critical diagnostic that lets the operator distinguish "bad key (401)" from "rate-limited (429)" from "OpenAI outage (5xx)" from "network unreachable (null)" — without having to tail the api container's WARN log. Status-code-only also keeps the field cheap and PII/secret-free.

### FR-3: `CapabilityResult` Pydantic model carries `models_endpoint_status_code`; `models_endpoint` schema unchanged

- Requirement:
  - The `CapabilityResult` model in [`backend/app/llm/capability_models.py`](../../../../backend/app/llm/capability_models.py) **MUST** be extended with `models_endpoint_status_code: int | None = None`.
  - The `CapabilityResult.models_endpoint` field's `Literal["ok", "fail"]` type **MUST NOT** be widened — the cache only ever stores actual probe outcomes (one of two states). The cache-miss representation remains "no `CapabilityResult` row at all" (i.e., `_read_capability_cache` returns `None`). Widening would create a degenerate cached state in which `probe_openai_state()` ([`probes.py:151-159`](../../../../backend/app/api/probes.py#L151-L159)) would silently treat `"untested"` as non-failure → returning `"configured"` when the operator expected `"incapable"`.
  - The `models_endpoint_status_code` default value **MUST** be `None` so existing cached rows (serialized by `model_dump_json()` before this fix) deserialize cleanly via `model_validate_json()` — Pydantic treats missing optional fields with defaults as their default. AC-8 enforces this round-trip.
  - The field **MUST** be populated by `_probe_models_endpoint()` (via the `tuple[bool, int | None]` return contract specified in §3 "In scope") and threaded through to the `CapabilityResult(...)` construction in `check_capabilities()` at [`capability_check.py:323-331`](../../../../backend/app/llm/capability_check.py#L323-L331).

### FR-4: Architecture doc updated

- Requirement:
  - [`docs/01_architecture/llm-orchestration.md` §"Capability check at startup"](../../../01_architecture/llm-orchestration.md) **MUST** be updated to:
    - Document the new `models_endpoint` and `models_endpoint_status_code` fields in the cached-`CapabilityResult` JSON example
    - Add an explanatory paragraph: "When the step-1 `GET /models` probe fails, steps 2–4 are skipped and reported as `untested`. `/healthz` surfaces this as `subsystems.openai: incapable` + `openai_capabilities.models_endpoint: fail` (+ status code if HTTP) + 3× `untested`. The status code distinguishes `401 → bad key`, `429 → quota`, `5xx → OpenAI outage`, `null → network unreachable`."
    - Add the "operator `.env` vs. repo secret divergence" note: a single line warning that the value populated in GitHub Actions' `OPENAI_API_KEY_TEST` repo secret may not match any individual operator's `.env`. When the smoke gate fails with `models_endpoint: fail` + status `401`, the operator should rotate the repo secret with a known-good key.

### FR-5: Tests updated

- Requirement:
  - [`backend/tests/unit/test_capability_check.py`](../../../../backend/tests/unit/test_capability_check.py) **MUST** add at least one case for each of: (a) `_probe_models_endpoint` HTTP 401 → `CapabilityResult.models_endpoint_status_code == 401`, (b) HTTP 429 → `... == 429`, (c) network error (httpx.ConnectError) → `... is None`, (d) HTTP 200 (success path) → `... is None`.
  - [`backend/tests/unit/test_health.py`](../../../../backend/tests/unit/test_health.py) **MUST** add at least one case asserting `/healthz`'s response includes `openai_capabilities.models_endpoint == "fail"` and `openai_capabilities.models_endpoint_status_code == <expected int>` when a cached `CapabilityResult` reports the failure.
  - [`backend/tests/unit/test_health.py`](../../../../backend/tests/unit/test_health.py) **MUST** add at least one case asserting the cache-miss path (no `CapabilityResult` in Redis) reports `openai_capabilities.models_endpoint == <FR-1 decision>` and `openai_capabilities.models_endpoint_status_code is None`.
  - [`backend/tests/contract/test_health_contract.py`](../../../../backend/tests/contract/test_health_contract.py) **MUST** assert the OpenAPI schema includes `openai_capabilities.models_endpoint` as required (literal `["ok","fail","untested"]` per §19 D-1) and `openai_capabilities.models_endpoint_status_code` as nullable (`int | None`).
  - The unit test suite **MUST** include the AC-10 security redaction test described in §14 ("HTTP 401 with body containing token-like substring → `CapabilityResult.model_dump_json()`, `/healthz` JSON, AND captured structlog all exclude the body text"). This is the regression guard for the most security-sensitive invariant in the fix.

## 8) API and data contract baseline

### 8.1 Endpoint surface

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `GET` | `/healthz` | Operator probe; reports per-subsystem state. Unauthenticated, unprefixed. | HTTP 200 (ok) or 503 (degraded) per [`health.py:297`](../../../../backend/app/api/health.py#L297). Body shape identical for both. No `detail.error_code` envelope — `/healthz` returns the `HealthResponse` body directly. |

### 8.2 Contract rules

- The response **MUST** validate against the `HealthResponse` Pydantic model.
- The `openai_capabilities` block **MUST** include exactly five required sub-fields (`models_endpoint`, `chat`, `function_calling`, `structured_output`, `models_endpoint_status_code`). The first four are non-null literal strings; `models_endpoint_status_code` is required-but-nullable (`int | None`).
- HTTP status code mapping (200 vs 503) **MUST NOT** change — the change is purely additive to the response body.

### 8.3 Response examples

All four examples use the same response model — `models_endpoint_status_code` is **always present**, with explicit `null` when there is no value.

**Success — all probes green:**
```json
{
  "status": "ok",
  "subsystems": {
    "db": "ok",
    "redis": "ok",
    "openai": "configured",
    "elasticsearch": "reachable",
    "opensearch": "reachable",
    "elasticsearch_clusters": {"registered": 0, "healthy": 0, "unreachable": 0}
  },
  "openai_endpoint": "https://api.openai.com/v1",
  "openai_capabilities": {
    "models_endpoint": "ok",
    "models_endpoint_status_code": null,
    "chat": "ok",
    "function_calling": "ok",
    "structured_output": "ok"
  },
  "version": "v0.1.0",
  "uptime_seconds": 142
}
```

**Failure — bad API key (the bug's canonical case):**
```json
{
  "status": "ok",
  "subsystems": {
    "db": "ok",
    "redis": "ok",
    "openai": "incapable",
    "elasticsearch": "reachable",
    "opensearch": "reachable",
    "elasticsearch_clusters": {"registered": 4, "healthy": 0, "unreachable": 4}
  },
  "openai_endpoint": "https://api.openai.com/v1",
  "openai_capabilities": {
    "models_endpoint": "fail",
    "models_endpoint_status_code": 401,
    "chat": "untested",
    "function_calling": "untested",
    "structured_output": "untested"
  },
  "version": "v0.1.0",
  "uptime_seconds": 30
}
```

**Failure — network unreachable (e.g., Ollama daemon down):**
```json
{
  "subsystems": {"openai": "incapable", ...},
  "openai_capabilities": {
    "models_endpoint": "fail",
    "models_endpoint_status_code": null,
    "chat": "untested",
    "function_calling": "untested",
    "structured_output": "untested"
  }
}
```

Note `models_endpoint_status_code: null` — the operator's diagnostic step is "tail api logs for `step=models_endpoint` + `error=…`".

**Cache miss (immediately after restart, before fire-and-forget probe completes):**
```json
{
  "subsystems": {"openai": "configured", ...},
  "openai_capabilities": {
    "models_endpoint": "untested",
    "models_endpoint_status_code": null,
    "chat": "untested",
    "function_calling": "untested",
    "structured_output": "untested"
  }
}
```

`subsystems.openai == "configured"` per the cache-miss branch of `probe_openai_state()` at [`probes.py:151`](../../../../backend/app/api/probes.py#L151) — the operator should wait ~5s and re-poll. `models_endpoint == "untested"` is the resolved §19 decision (D-1).

### 8.4 Enumerated value contracts

| Field | Accepted values (exact) | Backend source of truth | Frontend / consumer call site(s) |
|---|---|---|---|
| `subsystems.openai` | `configured`, `missing_key`, `incapable` | [`backend/app/api/probes.py:138`](../../../../backend/app/api/probes.py#L138) (`Literal["configured", "missing_key", "incapable"]`) | smoke-gate `_wait_healthy` in `.github/workflows/pr.yml` |
| `openai_capabilities.models_endpoint` (response model) | `ok`, `fail`, `untested` | To be added in [`backend/app/api/health.py`](../../../../backend/app/api/health.py) `OpenAICapabilities` as `Literal["ok", "fail", "untested"]`. **NOT** widened in the cached `CapabilityResult` schema — that stays `Literal["ok", "fail"]` per FR-3. | operator `curl /healthz` + future smoke-gate diagnostics |
| `CapabilityResult.models_endpoint` (cached schema) | `ok`, `fail` (unchanged) | [`backend/app/llm/capability_models.py:24`](../../../../backend/app/llm/capability_models.py#L24) — `Literal["ok", "fail"]`, **not widened** | internal cache consumers (`probe_openai_state`, `_read_capability_cache`) |
| `openai_capabilities.chat` / `.function_calling` / `.structured_output` | `ok`, `fail`, `untested` | [`backend/app/api/health.py:75-81`](../../../../backend/app/api/health.py#L75-L81) | (unchanged) operator curl |
| `openai_capabilities.models_endpoint_status_code` | Any integer (HTTP status, typically `>= 400` in practice — but the type is `int | None`, not bounded) or `null` | New field; populated from `httpx.Response.status_code` in [`_probe_models_endpoint`](../../../../backend/app/llm/capability_check.py#L61) per the §3 `tuple[bool, int | None]` return contract | operator curl + (optional follow-up) smoke gate |

### 8.5 Error code catalog

N/A — this fix introduces no new error codes. `/healthz` does not return the `detail.error_code` envelope; it returns the full `HealthResponse` body for both 200 and 503.

## 9) Data model and state transitions

### New/changed entities

**Modified Pydantic model: `CapabilityResult`** ([`backend/app/llm/capability_models.py:19`](../../../../backend/app/llm/capability_models.py#L19))
- Add `models_endpoint_status_code: int | None = None` — populated by `_probe_models_endpoint()` when the failing response carried a status code; `None` for the success path AND for network-class failures (timeout / DNS / connection-refused).
- `models_endpoint` field type **UNCHANGED** at `Literal["ok", "fail"]`. The cache stores only outcomes of actual probe runs; the cache-miss case is represented by the *absence* of a cache row (`_read_capability_cache` returns `None`), not by a `CapabilityResult` row with `"untested"`. See FR-3 / §19 D-2.

**Modified Pydantic model: `OpenAICapabilities`** ([`backend/app/api/health.py:72`](../../../../backend/app/api/health.py#L72))
- Add `models_endpoint: Literal["ok", "fail", "untested"]` — required field on the response. Projected from the cached `CapabilityResult.models_endpoint` on cache hit; mapped to `"untested"` on cache miss (matching the existing `chat / function_calling / structured_output` cache-miss handling at [`health.py:282-286`](../../../../backend/app/api/health.py#L282-L286)).
- Add `models_endpoint_status_code: int | None = Field(...)` — **required-but-nullable**, no Pydantic default; every construction site explicitly passes the value (or `None`). Always present in the response JSON; set to `None` on success / cache miss / network-class failures. Surfaces the HTTP status code on step-1 HTTP failures (e.g., 401 / 429 / 5xx).

**No table changes.** The capability cache lives in Redis under `openai:capabilities:{sha256(base_url)}` (24h TTL) — the cache-row JSON gains the optional `models_endpoint_status_code` field. Pre-fix cache rows deserialize cleanly because the new field has a default.

### Required invariants

- `models_endpoint_status_code` **MUST** be `None` whenever `models_endpoint == "ok"` (no failure → no status code to report).
- `models_endpoint_status_code` **MUST NOT** include any portion of the OpenAI response body — only the integer status code.
- When `models_endpoint == "fail"` and `models_endpoint_status_code is not None`, the value **MUST** be a 4xx or 5xx HTTP status code (the success path doesn't produce a `"fail"` result).

### State transitions

N/A — `CapabilityResult` is a snapshot, not a stateful entity. Each capability check produces a fresh result that replaces the prior cached value.

### Idempotency/replay behavior

The capability check is fire-and-forget at startup; if the api container restarts, the next startup runs a fresh check. The Redis TTL (24h) bounds staleness. No replay protection needed — checks are idempotent by design.

## 10) Security, privacy, and compliance

- **Threat 1:** Surfacing OpenAI response body in `/healthz` could leak the bad API key (OpenAI 401 error bodies quote bearer tokens). **Control:** §3 out-of-scope and §4 anti-patterns explicitly forbid response-body content; only the integer status code is exposed. Verified in FR-2 wording + the anti-pattern list.
- **Threat 2:** Surfacing detailed network errors in `/healthz` could leak internal infrastructure details. **Control:** Network errors (timeout / DNS / connection-refused) report `models_endpoint_status_code: null` only — the detailed error string stays in the WARN log inside the api container, never in the API response.
- **Threat 3:** `/healthz` is unauthenticated — any new field is publicly readable. **Control:** Status codes are non-sensitive integers; they reveal "the configured key fails" but not the key itself. The CI workflow page is public; status codes are appropriate to publish there.
- **Secrets/key handling:** No new secrets. The API key remains in the `OPENAI_API_KEY_FILE` mount per CLAUDE.md Absolute Rule #2. No log changes that could include the key (WARN log at `capability_check.py:75-80` already excludes it).
- **Auditability:** N/A — no audit events emitted (MVP1; no `audit_log` table yet).
- **Data retention:** Cache row TTL is 24h (unchanged). No new retention semantics.

## 11) UX flows and edge cases

### Information architecture

N/A — no UI changes. The `/healthz` response is consumed by:
- `.github/workflows/pr.yml` smoke gate's `_wait_healthy` helper
- Operator curl / `jq` queries
- Potentially a future dashboard (out of scope here)

### Tooltips and contextual help

N/A — no UI changes.

### Primary flows

1. **Operator polls `/healthz` after `make up` — bad key case.**
   - Operator runs `curl -s http://127.0.0.1:8000/healthz | jq`.
   - Sees `subsystems.openai: "incapable"`.
   - Sees `openai_capabilities.models_endpoint: "fail"` + `models_endpoint_status_code: 401`.
   - Diagnoses: "OpenAI rejected my key with 401. Rotate it."
   - Without this fix: operator sees `incapable` + 3× `"untested"`, doesn't know which probe failed, has to `docker compose logs api | grep capability_check`.

2. **CI smoke gate polls `/healthz` and the repo secret is invalid.**
   - The smoke job's `Wait for /healthz` loop ([`pr.yml:354-365`](../../../../.github/workflows/pr.yml#L354-L365)) succeeds because overall `status == "ok"` (OpenAI `incapable` is non-blocking per [`health.py:127-138`](../../../../backend/app/api/health.py#L127-L138)). The smoke pytest (`test_tutorial_path.py`) is what skips on `incapable`, so the gate reports red. NOTE: because the wait loop *succeeds*, its failure-step curl at [`pr.yml:364`](../../../../.github/workflows/pr.yml#L364) does NOT run — that capture only triggers on a wait-loop timeout, not on the openai-incapable case.
   - The relevant capture for the broken-key case is the smoke-test attach-artifacts step at [`pr.yml:444-445`](../../../../.github/workflows/pr.yml#L444-L445), which runs after the pytest step (regardless of pass/skip/fail) and writes `curl -s http://127.0.0.1:8000/healthz >> smoke-logs.txt`. Post-fix, that file includes `openai_capabilities.models_endpoint: "fail"` + `models_endpoint_status_code: 401`. The maintainer downloads `smoke-logs` from the workflow run artifacts; the diagnostic is "rotate the repo secret" instead of "tail container logs to find which probe failed."
   - **Out of scope this PR:** modifying the smoke-gate's helper or its skip predicate to surface the new field eagerly in the workflow's inline log. The smoke-logs artifact already publishes it; richer parsing is a follow-up.

3. **Operator running a local LLM (e.g., Ollama) before the daemon is up.**
   - `curl /healthz` shows `models_endpoint: "fail"` + `models_endpoint_status_code: null`.
   - Diagnoses: "Network unreachable. Is `ollama` running?"
   - Operator runs `ollama serve` and retries.

4. **Operator polls within ~5s of api startup.**
   - Capability check is fire-and-forget — cache may still be empty.
   - `/healthz` shows `subsystems.openai: "configured"` (cache miss → `"configured"` per `probe_openai_state` line 151) and `openai_capabilities.models_endpoint: "untested"` (§19 D-1).
   - Operator waits ~5s, re-polls; cache populates; new shape reflects the actual probe result.

**Out-of-scope flow (CI helper changes):** No edits to `.github/workflows/pr.yml`'s `Wait for /healthz` step or to the smoke-test pytest's `pytest.skip` predicate. For the broken-key case, the diagnostic surface is the **smoke-test attach-artifacts step** at [`pr.yml:444-445`](../../../../.github/workflows/pr.yml#L444-L445), which writes `curl -s http://127.0.0.1:8000/healthz >> smoke-logs.txt` and uploads the artifact. (The Wait-for-/healthz failure-step `curl` at [`pr.yml:364`](../../../../.github/workflows/pr.yml#L364) does NOT run in the broken-key scenario because the wait loop *succeeds* — overall `status == "ok"` even with `openai: incapable`.) Once this PR ships, the smoke-logs artifact captures will include `models_endpoint` + `models_endpoint_status_code` with zero workflow-file changes. A richer CI helper that pre-parses the response and prints a one-line diagnostic in the inline workflow log is a follow-up (idea-file candidate, NOT in scope here).

### Edge/error flows

- **Cache row corrupt:** `_read_capability_cache` returns `None`; treated as cache miss. New fields take the cache-miss default.
- **Redis down at probe time:** Cache write fails (WARN logged); next `/healthz` poll is a cache miss; same as the startup case.
- **Redis down at `/healthz` time:** Cache read fails (WARN logged via existing path); same as cache miss.
- **Probe returns 200 OK but unparseable body:** Currently the `_probe_chat_completion` / `_probe_function_calling` / `_probe_structured_output` probes treat this as `"fail"` (existing behavior). `_probe_models_endpoint` does not parse the body — only checks status >= 400. **No change to step-1 logic.**

## 12) Given/When/Then acceptance criteria

### AC-1: `/healthz` response includes `models_endpoint` field on cache hit

- **Given** a `CapabilityResult` is cached in Redis with `models_endpoint = "fail"` and `models_endpoint_status_code = 401`,
- **When** the operator polls `GET /healthz`,
- **Then** the response includes `openai_capabilities.models_endpoint == "fail"` and `openai_capabilities.models_endpoint_status_code == 401`, AND `subsystems.openai == "incapable"`.
- **Example values:**
  - Input: cached `CapabilityResult(models_endpoint="fail", chat_completion="untested", function_calling="untested", structured_output="untested", models_endpoint_status_code=401, base_url="https://api.openai.com/v1", model="gpt-4o-2024-08-06", tested_at=<utc>)`.
  - Expected: HTTP 200, body includes `"openai_capabilities":{"models_endpoint":"fail","models_endpoint_status_code":401,"chat":"untested","function_calling":"untested","structured_output":"untested"}`.

### AC-2: `/healthz` response shows `null` status code on network failures

- **Given** a `CapabilityResult` cached with `models_endpoint = "fail"` and `models_endpoint_status_code = None` (probe failed via `httpx.ConnectError`),
- **When** the operator polls `/healthz`,
- **Then** the response includes `openai_capabilities.models_endpoint == "fail"` and `openai_capabilities.models_endpoint_status_code is null`.

### AC-3: `_probe_models_endpoint` captures status code on HTTP failure

- **Given** the OpenAI endpoint returns HTTP 401 from `GET /models`,
- **When** `check_capabilities(...)` runs against that endpoint,
- **Then** the resulting `CapabilityResult` has `models_endpoint == "fail"` AND `models_endpoint_status_code == 401`, AND `chat_completion == "untested"` (existing skip behavior unchanged), AND a WARN log fires at `capability_check.py:75-80` with `status_code=401`.
- **Example values:**
  - Input: httpx mock returning `httpx.Response(401, json={"error": {"message": "Invalid Bearer token"}}, request=req)` to the `GET /models` call.
  - Expected: `result.models_endpoint == "fail"`; `result.models_endpoint_status_code == 401`; `result.chat_completion == result.function_calling == result.structured_output == "untested"`.

### AC-4: `_probe_models_endpoint` reports `None` status code on network failure

- **Given** the OpenAI endpoint is unreachable (raises `httpx.ConnectError` before any HTTP response),
- **When** `check_capabilities(...)` runs,
- **Then** the resulting `CapabilityResult` has `models_endpoint == "fail"` AND `models_endpoint_status_code is None`.

### AC-5: `_probe_models_endpoint` reports `None` status code on success

- **Given** the OpenAI endpoint returns HTTP 200 from `GET /models`,
- **When** `check_capabilities(...)` runs,
- **Then** the resulting `CapabilityResult` has `models_endpoint == "ok"` AND `models_endpoint_status_code is None` (never `200` — success-path status codes are not stored).

### AC-6: Cache-miss `/healthz` response reports `models_endpoint: "untested"`

- **Given** Redis has no `openai:capabilities:*` row for the configured `OPENAI_BASE_URL` (e.g., fresh startup before the fire-and-forget probe completes),
- **When** the operator polls `/healthz`,
- **Then** the response includes `openai_capabilities.models_endpoint == "untested"` and `openai_capabilities.models_endpoint_status_code is null`, AND `subsystems.openai == "configured"` per the existing cache-miss branch at [`probes.py:151`](../../../../backend/app/api/probes.py#L151).

### AC-7: Backwards compatibility — existing consumers reading 3 fields keep working

- **Given** a consumer that reads only `openai_capabilities.chat`, `openai_capabilities.function_calling`, `openai_capabilities.structured_output`,
- **When** the new response shape ships,
- **Then** the consumer continues to receive those three fields with the same `Literal["ok", "fail", "untested"]` value space.

### AC-8: Backwards compatibility — pre-fix cache rows deserialize cleanly

- **Given** a `CapabilityResult` JSON serialized by the pre-fix code (no `models_endpoint_status_code` field present),
- **When** the post-fix code reads and deserializes it via `CapabilityResult.model_validate_json(raw)`,
- **Then** the result loads successfully with `models_endpoint_status_code == None`.

### AC-9: Architecture doc updated with new shape + diagnostic table

- **Given** the spec is implemented,
- **When** a maintainer reads [`docs/01_architecture/llm-orchestration.md` §"Capability check at startup"](../../../01_architecture/llm-orchestration.md),
- **Then** the JSON example shows the new fields, and the doc contains the cascade explanation and the repo-secret-vs-`.env` divergence note.

### AC-10: No response-body content leaks into `/healthz`, `CapabilityResult`, or structured logs

- **Given** the OpenAI endpoint returns HTTP 401 with body `{"error": {"message": "Invalid Bearer token: sk-redacted-token-abc"}}` (a realistic OpenAI-shaped error that quotes the bearer token back),
- **When** `check_capabilities(...)` runs against that endpoint,
- **Then** ALL of the following MUST hold:
  - `CapabilityResult.model_dump_json()` (the value written to Redis) does NOT contain `"Invalid Bearer token"`, `"sk-redacted-token-abc"`, or any other substring of the response body.
  - The `/healthz` JSON response does NOT contain those substrings.
  - The captured structlog output (asserted via the existing `backend.tests._log_helpers.assert_log_level` pattern at [`backend/tests/unit/test_capability_check.py:36`](../../../../backend/tests/unit/test_capability_check.py#L36)) does NOT contain those substrings.
  - The only place the integer `401` appears is in `models_endpoint_status_code` (cached field + response field) and in the WARN log's `status_code` key.
- **Example values:**
  - Input: httpx mock returning `httpx.Response(401, json={"error": {"message": "Invalid Bearer token: sk-redacted-token-abc"}}, request=req)` to the `GET /models` call.
  - Expected: `result.models_endpoint_status_code == 401`; the strings `"Invalid Bearer token"` and `"sk-redacted-token-abc"` appear in neither the JSON-serialized `CapabilityResult`, the `/healthz` response body, nor the captured logs.

## 13) Non-functional requirements

- **Performance:** Zero new I/O on the `/healthz` hot path. The new fields are read from the in-memory `CapabilityResult` already loaded at [`health.py:262`](../../../../backend/app/api/health.py#L262). No latency impact; the 200ms per-probe budget and 500ms p99 endpoint target are not threatened.
- **Reliability:** Backwards-compatible additive changes only. No breakage path for existing consumers. Pre-fix cache rows in Redis deserialize cleanly: the cached `CapabilityResult` gains the new `models_endpoint_status_code: int | None = None` optional field (Pydantic-default `None`, so absent in old rows = `None` on read). The `OpenAICapabilities` response model's new `models_endpoint_status_code` is required-but-nullable — the API constructor in `/healthz` always passes an explicit value (the cached row's status code, or `None`).
- **Operability:**
  - The WARN log at [`capability_check.py:75-80`](../../../../backend/app/llm/capability_check.py#L75-L80) remains the source of truth for the detailed failure context (URL, error text). The `/healthz` field is a *diagnostic summary*, not a replacement for logs.
  - For the openai-incapable CI case: the existing smoke-test artifact capture at [`pr.yml:444-445`](../../../../.github/workflows/pr.yml#L444-L445) (`curl /healthz >> smoke-logs.txt`) will include the new fields once this PR ships — no `.github/workflows/pr.yml` edits in this PR (see §19 D-6). The `Wait for /healthz` step's failure-step curl at [`pr.yml:364`](../../../../.github/workflows/pr.yml#L364) does NOT fire for openai-incapable because the wait loop succeeds (overall `status: ok`). Inline workflow-log parsing into a one-line CI diagnostic is a follow-up.
- **Accessibility/usability:** N/A — no UI.

## 14) Test strategy requirements (spec-level)

Minimum required coverage by layer:

- **Unit tests** ([`backend/tests/unit/test_capability_check.py`](../../../../backend/tests/unit/test_capability_check.py)):
  - HTTP 401 → `models_endpoint_status_code == 401`
  - HTTP 429 → `models_endpoint_status_code == 429`
  - HTTP 500 → `models_endpoint_status_code == 500`
  - Network error (`httpx.ConnectError`) → `models_endpoint_status_code is None`
  - HTTP 200 (success) → `models_endpoint == "ok"` AND `models_endpoint_status_code is None` (success path never stores status code)
  - Backwards-compat: pre-fix-serialized cache row deserializes with `models_endpoint_status_code == None`
  - **Security redaction (required for AC-10):** HTTP 401 with body `{"error": {"message": "Invalid Bearer token: sk-redacted-token-abc"}}` — assert `result.model_dump_json()` does NOT contain the body's token-like substrings; assert the captured structlog output (via `assert_log_level` and structlog's testing capture) does NOT contain them either; assert `result.models_endpoint_status_code == 401`.
- **Unit tests** ([`backend/tests/unit/test_probes.py`](../../../../backend/tests/unit/test_probes.py)):
  - `probe_openai_state` behavior unchanged when `models_endpoint_status_code` is present (the function ignores the new field — verified by adding a case where `_make_cap()` passes a status code and the return value still maps to `"incapable"`).
- **Unit tests** ([`backend/tests/unit/test_health.py`](../../../../backend/tests/unit/test_health.py)):
  - `/healthz` response includes `openai_capabilities.models_endpoint` (per FR-1) for cache-hit and cache-miss paths
  - `/healthz` response includes `openai_capabilities.models_endpoint_status_code` when the cache hit reports an HTTP failure
  - `/healthz` response has `"models_endpoint_status_code": null` **always present** for the success path, network-error case, and cache-miss case (asserting the field is in the JSON body with explicit `null`, not omitted — verifies `exclude_none` is NOT in play)
  - Security redaction (AC-10): a `/healthz` poll built from a cached `CapabilityResult` (with status code 401) does NOT echo any body substring; only the integer `401` appears.
- **Integration tests:** N/A — no DB schema changes, no service-layer changes. The capability check itself is unit-testable via `httpx` mocks.
- **Contract tests:** Update [`backend/tests/contract/test_health_contract.py`](../../../../backend/tests/contract/test_health_contract.py) to require BOTH `models_endpoint` AND `models_endpoint_status_code` in the OpenAPI schema (`models_endpoint_status_code` is required-but-nullable per FR-2). Assert the JSON response body always includes both keys (use `assert "models_endpoint_status_code" in body["openai_capabilities"]` — the key is present even when value is `null`). [`backend/tests/contract/test_openapi_surface.py`](../../../../backend/tests/contract/test_openapi_surface.py) may not need changes — verify and patch only if a surface-level assertion grew stale.
- **E2E tests:** N/A — no UI surface change. The smoke gate's `Wait for /healthz` step is a bash helper, not Playwright. The new fields surface in CI via the existing `smoke-logs.txt` artifact (`curl /healthz >> smoke-logs.txt` at [`pr.yml:444-445`](../../../../.github/workflows/pr.yml#L444-L445)) — verify via a dry-run by reading that artifact after a deliberately-broken-key run.

## 15) Documentation update requirements

- `docs/01_architecture/llm-orchestration.md`: §"Capability check at startup" — update JSON example to include `models_endpoint` + `models_endpoint_status_code`; add the cascade explanation + repo-secret-vs-`.env` divergence note (FR-4).
- `docs/00_overview/planned_features/bug_openai_capability_check_incapable_on_valid_key/feature_spec.md`: this file.
- `docs/03_runbooks/`: no new runbook needed — the WARN log path is unchanged; existing operator workflow ("tail api logs") still works. New `/healthz` fields are self-documenting (an integer status code is a known operator concept).
- `CLAUDE.md`: no new conventions or absolute rules introduced.
- `state.md`: add to "recent changes" section after merge (the impl-execute skill handles this).

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** None. Single-PR deploy. The change is backwards-compatible additive — old consumers keep working without modification.
- **Migration/backfill expectations:** None for Postgres. Redis cache rows expire within 24h; old rows deserialize cleanly via Pydantic's optional-field defaulting. No backfill needed.
- **Operational readiness gates:**
  - `make lint` + `make typecheck` clean
  - `make test-unit` + `make test-contract` clean
  - 80% coverage gate maintained (the new field is straightforward to cover)
  - GPT-5.5 cross-model review passes
- **Release gate:** CI green on the feature branch + Gemini Code Assist findings adjudicated.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 | AC-1, AC-6, AC-7 | "Add `models_endpoint` to `OpenAICapabilities`" | `backend/tests/unit/test_health.py` | `docs/01_architecture/llm-orchestration.md` |
| FR-2 | AC-1, AC-2, AC-10 | "Add `models_endpoint_status_code` to `OpenAICapabilities`" | `backend/tests/unit/test_health.py`, `backend/tests/contract/test_health_contract.py` | (same) |
| FR-3 | AC-3, AC-4, AC-5, AC-8, AC-10 | "Extend `CapabilityResult` + `_probe_models_endpoint` to capture status code" | `backend/tests/unit/test_capability_check.py` | (same) |
| FR-4 | AC-9 | "Update llm-orchestration.md" | N/A (doc-only) | `docs/01_architecture/llm-orchestration.md` |
| FR-5 | AC-1..AC-8, AC-10 | "Test updates (including the AC-10 security redaction case in `test_capability_check.py`)" | All test files listed above + the AC-10-specific 401-body redaction test | (same) |

## 18) Definition of feature done

This bug is fixed when:

- [ ] All acceptance criteria (AC-1 through AC-10) pass in CI.
- [ ] `make test-unit` + `make test-contract` + `make lint` + `make typecheck` are green on the feature branch.
- [ ] The 80% coverage gate is maintained.
- [ ] `docs/01_architecture/llm-orchestration.md` is updated per FR-4 / AC-9.
- [ ] GPT-5.5 cross-model review of the PR diff has no unresolved High findings.
- [ ] Gemini Code Assist line-level findings (if any) are adjudicated.
- [ ] On a deliberately-broken-key dry-run of the smoke job (or equivalent local reproduction), the `smoke-logs.txt` artifact built at [`pr.yml:444-445`](../../../../.github/workflows/pr.yml#L444-L445) is confirmed to include both `openai_capabilities.models_endpoint` and `openai_capabilities.models_endpoint_status_code` in its embedded `/healthz` capture. (No `.github/workflows/pr.yml` edits required — just visual confirmation that the existing `curl >> smoke-logs.txt` capture surfaces the new fields. Note: the wait-loop failure-step curl at `pr.yml:364` is NOT the correct verification surface here — it doesn't fire on `openai: incapable` because the wait loop succeeds.)
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

None remaining — all resolved by GPT-5.5 cycle 1 review.

### Decision log

- **2026-05-24 (D-1) — Cache-miss `models_endpoint` value:** `"untested"`. The new `OpenAICapabilities.models_endpoint` field type is `Literal["ok", "fail", "untested"]`. On cache miss (no `CapabilityResult` in Redis), `/healthz` reports `models_endpoint: "untested"`. Rationale: a cache miss semantically means "the probe hasn't reported yet," not "the probe failed" — matches the existing `chat / function_calling / structured_output` cache-miss handling. Sourced from GPT-5.5 cycle 1 Pass A finding A1 (Accept). Affects FR-1, §3, §8.3 example #4, AC-6.
- **2026-05-24 (D-2) — Cached schema NOT widened:** `CapabilityResult.models_endpoint` type stays `Literal["ok", "fail"]`. The `"untested"` literal exists only in the response-model `OpenAICapabilities`, not in the cached schema. Rationale: the cache stores only outcomes of actual probe runs; cache miss = absence of cache row (not a row with `"untested"`). Widening would create a degenerate state in `probe_openai_state()` ([`probes.py:151-159`](../../../../backend/app/api/probes.py#L151-L159)) where a cached `"untested"` would silently map to `"configured"` when the operator expected `"incapable"`. Sourced from GPT-5.5 cycle 1 Pass A finding A2 + Pass B finding B1 (Accept). Affects FR-3, §9.
- **2026-05-24 (D-3) — `models_endpoint_status_code` always serialized:** The response field is declared `int | None = None` and serialized via the existing `JSONResponse(content=body.model_dump())` call at [`health.py:298`](../../../../backend/app/api/health.py#L298), which includes `None` fields by default. Do NOT pass `exclude_none=True`. Rationale: avoids ambiguity in contract-test assertions and operator scripts; explicit `null` is more discoverable than a missing key. Sourced from GPT-5.5 cycle 1 Pass A finding A3 (Accept). Affects FR-2, §8.3 examples (all four), AC-1, AC-7.
- **2026-05-24 (D-4) — `_probe_models_endpoint` return contract:** `tuple[bool, int | None]` with exact mapping: `(True, None)` on status < 400 success; `(False, resp.status_code)` only when `resp.status_code >= 400`; `(False, None)` on `httpx.HTTPError`. Rationale: matches the existing `>= 400` check at [`capability_check.py:74`](../../../../backend/app/llm/capability_check.py#L74); avoids storing success-path status codes (noise). Sourced from GPT-5.5 cycle 1 Pass A finding A4 (Accept). Affects §3 "In scope", FR-3, AC-3, AC-4, AC-5.
- **2026-05-24 (D-5) — Required security regression test:** AC-10 is strengthened with explicit assertions that `CapabilityResult.model_dump_json()`, the `/healthz` JSON, AND captured structlog output all exclude OpenAI response-body content. Test uses 401 body `Invalid Bearer token: sk-redacted-token-abc` as the canonical case. Sourced from GPT-5.5 cycle 1 Pass B finding B2 (Accept). Affects AC-10, FR-5, §14.
- **2026-05-24 (D-6) — CI workflow changes out of scope:** No edits to `.github/workflows/pr.yml`. The existing failure-step `curl -s http://127.0.0.1:8000/healthz` captures at [`pr.yml:364`](../../../../.github/workflows/pr.yml#L364) + [`pr.yml:445`](../../../../.github/workflows/pr.yml#L445) already publish the raw response into the workflow log — post-fix, those captures include the new fields with zero workflow-file edits. Eager pre-parsing into a one-line CI diagnostic is a follow-up (idea-file candidate). Sourced from GPT-5.5 cycle 1 Pass B finding B3 (Accept, partial — downgraded the claim, kept the diagnostic in scope via the existing curl-capture path). Affects §1 Outcome, §3 Out-of-scope, §11 flow 2, §11 Out-of-scope flow, §18.
- **2026-05-24 (D-7) — Rejected finding (B4):** GPT-5.5 Pass B finding B4 ("test file citations unverifiable") REJECTED with counter-evidence — all cited test files were verified in spec-gen Pass 1 (`backend/tests/unit/test_health.py`, `backend/tests/unit/test_capability_check.py`, `backend/tests/unit/test_probes.py` — including the line `163` citation at `_probes.py:159-163` `test_key_set_any_fail_returns_incapable`, `backend/tests/contract/test_health_contract.py`, `backend/tests/contract/test_openapi_surface.py`). The reviewer lacked test-file context, not the spec.
- **2026-05-24 — Out-of-scope decision:** do NOT investigate or rotate the production `OPENAI_API_KEY_TEST` repo secret in this PR. The fix surfaces the diagnostic the operator needs; the operator action (key rotation) is separate. Rationale: per CLAUDE.md operator-environment handoff, repo secrets are operator-only.
- **2026-05-24 — Security decision:** response-body content is NEVER surfaced in `models_endpoint_status_code` or in `/healthz`. Only the integer HTTP status code. Rationale: OpenAI 401 bodies can quote the bearer token. Documented as §3 out-of-scope + §4 anti-pattern + AC-10 (strengthened in D-5).
- **2026-05-24 (D-8) — `models_endpoint_status_code` is required-but-nullable in OpenAPI:** The response field is declared `int | None = Field(...)` with no Pydantic default — required in the OpenAPI schema, nullable in value. Construction sites in `/healthz` explicitly pass the value (or `None`). This contract is unambiguous: the JSON key is ALWAYS present; the value is either an integer or explicit `null`. Sourced from GPT-5.5 cycle 3 Pass A finding (Accept, Medium). Affects FR-2, §8.2, §9, §14 contract tests.
- **2026-05-24 (D-9) — CI diagnostic surface for openai-incapable is `smoke-logs.txt`, NOT the wait-loop failure-step curl:** Per [`pr.yml:444-445`](../../../../.github/workflows/pr.yml#L444-L445) — the `Wait for /healthz` step's failure-step `curl` at `pr.yml:364` does NOT fire when openai is `incapable` (overall `status: ok` still passes the wait loop). The relevant capture is the smoke-test attach-artifacts step, which uploads `smoke-logs.txt` containing the raw `/healthz` body. Sourced from GPT-5.5 cycle 3 Pass B finding (Accept, Medium). Affects §1 Outcome, §11 flow 2, §11 Out-of-scope flow, §13 Operability, §18 DoD.
