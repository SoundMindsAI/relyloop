# Implementation Plan — OpenAI capability check: surface `models_endpoint` status in `/healthz`

**Date:** 2026-05-24
**Status:** Complete (PR #234, merged 2026-05-24 as squash commit `d69189db`)
**Primary spec:** [feature_spec.md](feature_spec.md)
**Policy source(s):** [CLAUDE.md](../../../../CLAUDE.md) Absolute Rules #6 (`/healthz` unauthenticated), #10 (never log/expose secrets), #11 (`/healthz` per-probe 200ms budget); [llm-orchestration.md §"Capability check at startup"](../../../01_architecture/llm-orchestration.md).

---

## 0) Planning principles

- Spec traceability first: every story/task maps to FR IDs (FR-1 through FR-5) and to the §19 decision log (D-1 through D-9).
- Phase gates: single phase — no inter-phase gates beyond the standard pre-merge gates.
- Fail-loud tests: assert explicit response-shape, JSON-key presence, OpenAPI schema, and secret-redaction conditions. The AC-10 security regression test is the highest-risk invariant in the fix.
- Backwards compatibility: the cached `CapabilityResult` schema gains one optional field (`models_endpoint_status_code: int | None = None`); existing Redis rows (24h TTL) must deserialize cleanly. The `OpenAICapabilities` response model gains two fields; existing consumers reading only the three existing fields continue to work.
- Keep increments narrow enough to verify independently — three stories sequenced by data flow: model → probe → response.

## 1) Scope traceability (FR → epics/phases)

| FR ID | Story | Notes |
|---|---|---|
| FR-1: `/healthz` surfaces `models_endpoint` status | Story 1.3 | `Literal["ok", "fail", "untested"]` in `OpenAICapabilities` response model only (cached schema unchanged per D-2). |
| FR-2: `/healthz` exposes HTTP status code on `models_endpoint` HTTP failures | Story 1.3 | Required-but-nullable per D-3 + D-8 — `int \| None = Field(...)`, no default. |
| FR-3: `CapabilityResult` carries `models_endpoint_status_code`; cache schema unchanged | Story 1.1 | New optional field with `default=None` (backwards-compatible). `Literal["ok", "fail"]` for `models_endpoint` **not** widened (D-2). |
| FR-4: Architecture doc updated | Story 1.4 | `docs/01_architecture/llm-orchestration.md` §"Capability check at startup". |
| FR-5: Tests updated | All stories (tests inline in DoD) | Unit + contract layers. AC-10 redaction test in Story 1.2. |

No deferred phases — single-phase delivery. All 10 ACs (AC-1 through AC-10) are covered by Story 1.3 + Story 1.2 + Story 1.4.

## 2) Delivery structure

**Epic → Story → Tasks → DoD** (single epic, four stories sequenced strictly by data flow).

### Story-level detail requirements

Every story below includes:
- Outcome
- New files / Modified files
- Key interfaces (where applicable — Stories 1.1 and 1.2 add/modify Python signatures)
- Endpoints (only Story 1.3 — `/healthz` response shape change)
- Tasks
- Definition of Done (DoD) with explicit test layer references

### Conventions

- Pydantic v2 (`from pydantic import BaseModel, Field`); use `int | None = Field(...)` for required-but-nullable; `int | None = None` for optional with default `None`.
- `httpx.AsyncClient` per-probe with `PROBE_HTTP_TIMEOUT_SECONDS = 5.0` (unchanged).
- All structlog calls use kwargs (`logger.warning("msg", step=..., status_code=...)`); never `logger.warning(f"msg {key}")`.
- Tests use `from backend.tests._log_helpers import assert_log_level` for capturing structlog output.
- Type hints required on all new function signatures (mypy `--strict` is in CI).
- New `tuple[bool, int | None]` return type uses Python 3.10+ `|` syntax (the project's settled Python version per `pyproject.toml`).

### AI Agent Execution Protocol (applies to every story)

0. Read `architecture.md`, `state.md`, and this plan before starting Story 1.1.
1. Read the story's scope (outcome + interfaces + DoD).
2. Implement in order: capability_models → capability_check → health → llm-orchestration doc.
3. Run `make test-unit` after each story's tests are written; `make test-contract` after Story 1.3.
4. Run `make lint` + `make typecheck` after each story.
5. Story 1.4 (docs) closes the epic.

Story completion is invalid if any step above is skipped.

---

## Epic 1 — Surface `models_endpoint` status + HTTP status code in `/healthz`

### Story 1.1 — Extend `CapabilityResult` with `models_endpoint_status_code`

**Outcome:** The cached `CapabilityResult` Pydantic model carries an optional `models_endpoint_status_code: int | None = None` field. Existing cached Redis rows (serialized before this PR) continue to deserialize cleanly with the new field defaulting to `None`. The `models_endpoint` field's `Literal["ok", "fail"]` is **not** widened (per §19 D-2).

**New files:** None.

**Modified files**

| File | Change |
|---|---|
| [`backend/app/llm/capability_models.py`](../../../../backend/app/llm/capability_models.py) | Add `models_endpoint_status_code: int \| None = Field(default=None, description="HTTP status code captured when the step-1 /models probe HTTP-failed (>= 400). None for success / network-class failure / pre-fix cached rows.")`. Do NOT change `models_endpoint`'s `Literal["ok", "fail"]` type. |

**Key interfaces**

```python
# backend/app/llm/capability_models.py
class CapabilityResult(BaseModel):
    base_url: str
    model: str
    models_endpoint: Literal["ok", "fail"]                         # UNCHANGED
    chat_completion: Literal["ok", "fail", "untested"]
    function_calling: Literal["ok", "fail", "untested"]
    structured_output: Literal["ok", "fail", "untested"]
    models_endpoint_status_code: int | None = Field(               # NEW
        default=None,
        description="HTTP status code captured when models_endpoint='fail' AND the failure was an HTTP response (>= 400). None for success / network-class failure / pre-fix cached rows.",
    )
    tested_at: datetime
```

**Tasks**

1. Add the `models_endpoint_status_code` field to `CapabilityResult` per the Key interfaces block above.
2. Verify backwards compatibility: write a test (under Story 1.2's DoD) that takes the JSON serialization of a pre-fix `CapabilityResult` (no `models_endpoint_status_code` key) and confirms `CapabilityResult.model_validate_json(raw)` round-trips with `models_endpoint_status_code is None`.
3. Run `make lint` + `make typecheck` — both clean.

**Definition of Done (DoD)**

- [ ] `CapabilityResult.models_endpoint_status_code` exists with `int | None = Field(default=None)`.
- [ ] `CapabilityResult.models_endpoint` type **unchanged** at `Literal["ok", "fail"]`.
- [ ] `make typecheck` passes (Pydantic field declaration validates).
- [ ] `make lint` passes.
- [ ] Coverage gate (80%) is not affected by this story (no new branches; field declaration only).

---

### Story 1.2 — Update `_probe_models_endpoint` to capture HTTP status code

**Outcome:** `_probe_models_endpoint` returns `tuple[bool, int | None]` per the §19 D-4 contract: `(True, None)` on status < 400; `(False, resp.status_code)` only when status >= 400; `(False, None)` on `httpx.HTTPError`. `check_capabilities()` threads the captured status code through to the `CapabilityResult(...)` construction. The existing WARN log at [`capability_check.py:75-80`](../../../../backend/app/llm/capability_check.py#L75-L80) keeps its current `status_code` field (already present — no log change). Security invariant AC-10: neither the cached `CapabilityResult.model_dump_json()` nor captured structlog output contains any portion of the OpenAI response body.

**New files:** None.

**Modified files**

| File | Change |
|---|---|
| [`backend/app/llm/capability_check.py`](../../../../backend/app/llm/capability_check.py) | (a) Change `_probe_models_endpoint`'s return type from `bool` to `tuple[bool, int \| None]`. Return `(True, None)` for 2xx/3xx; `(False, resp.status_code)` for `>= 400`; `(False, None)` for `httpx.HTTPError`. (b) Update `check_capabilities()` at line 306 to unpack the tuple: `models_ok, models_status_code = await _probe_models_endpoint(client, base_url, api_key)`. (c) Thread `models_endpoint_status_code=models_status_code` through to `CapabilityResult(...)` at lines 323-331. |
| [`backend/tests/unit/test_capability_check.py`](../../../../backend/tests/unit/test_capability_check.py) | Add tests for the status-code capture matrix + the AC-10 security redaction case (see DoD below). |

**Key interfaces**

```python
# backend/app/llm/capability_check.py
async def _probe_models_endpoint(
    client: httpx.AsyncClient, base_url: str, api_key: str
) -> tuple[bool, int | None]:
    """Step 1 — GET {base_url}/models.

    Returns:
        (True, None)              — HTTP < 400 (success).
        (False, resp.status_code) — HTTP >= 400 (status code captured for /healthz diagnostic).
        (False, None)             — httpx.HTTPError raised before any HTTP response.
    """
    ...

# backend/app/llm/capability_check.py — check_capabilities() update (excerpt)
async def check_capabilities(...) -> CapabilityResult:
    ...
    models_ok, models_status_code = await _probe_models_endpoint(client, base_url, api_key)
    ...
    result = CapabilityResult(
        base_url=base_url,
        model=model,
        models_endpoint="ok" if models_ok else "fail",
        models_endpoint_status_code=models_status_code,   # NEW
        chat_completion=chat_status,
        function_calling=fc_status,
        structured_output=struct_status,
        tested_at=datetime.now(UTC),
    )
```

**Tasks**

1. Refactor `_probe_models_endpoint` per the Key interfaces block. The existing WARN logs at lines 67-73 (network error path) and 75-81 (HTTP-error path) stay unchanged — they already include `status_code=resp.status_code` in the HTTP-error case and `error=str(exc)` in the network-error case. Do NOT log `response.text` or `response.json()`.
2. Update `check_capabilities()` to unpack the tuple at line 306; thread `models_endpoint_status_code` into the `CapabilityResult(...)` construction at lines 323-331.
3. Add unit tests in `backend/tests/unit/test_capability_check.py`:
   - **AC-3 (HTTP 401):** httpx mock returns `Response(401, json={...})`. Assert `result.models_endpoint == "fail"`, `result.models_endpoint_status_code == 401`, `result.chat_completion == "untested"` (skip path unchanged). ALSO assert the WARN-level structlog event for `step="models_endpoint"` includes `status_code=401` (per B3 / GPT-5.5 cycle-1 finding — pin the structured log field, not just the message). Use the existing `assert_log_level` helper + structlog test capture pattern from [`backend/tests/unit/test_capability_check.py:36`](../../../../backend/tests/unit/test_capability_check.py#L36).
   - **HTTP 429:** assert `models_endpoint_status_code == 429`.
   - **HTTP 500:** assert `models_endpoint_status_code == 500`.
   - **AC-4 (network error):** httpx mock raises `httpx.ConnectError`. Assert `result.models_endpoint == "fail"`, `result.models_endpoint_status_code is None`.
   - **AC-5 (success path):** httpx mock returns `Response(200, ...)`. Assert `result.models_endpoint == "ok"`, `result.models_endpoint_status_code is None` (never `200`).
   - **AC-8 (backwards compat):** Take a JSON string serialized from a pre-fix `CapabilityResult` (no `models_endpoint_status_code` key — e.g., `'{"base_url":"...","model":"...","models_endpoint":"ok","chat_completion":"ok","function_calling":"ok","structured_output":"ok","tested_at":"2026-05-24T00:00:00Z"}'`). Assert `CapabilityResult.model_validate_json(raw).models_endpoint_status_code is None`.
   - **AC-10 (security redaction — cache-layer half):** Story 1.2 owns the cache-layer redaction proof. Story 1.3 owns the endpoint-layer redaction proof (because Story 1.2 cannot test `/healthz` projection — the response schema doesn't yet have the new fields until Story 1.3 lands). Story 1.2 test design:
     1. httpx mock returns `Response(401, json={"error": {"message": "Invalid Bearer token: sk-redacted-token-abc"}})` for `GET /models`.
     2. Run `await check_capabilities(...)` to produce a real `CapabilityResult` and a real Redis cache write (mock the Redis client).
     3. Capture the `model_dump_json()` value that gets sent to `redis.set()` (via the Redis mock's `.set.call_args`).
     4. Capture the structlog output via the existing `assert_log_level` helper at [`backend/tests/_log_helpers.py`](../../../../backend/tests/_log_helpers.py) (and structlog's testing capture).
     5. Assert ALL of the following on the captured surfaces (cached JSON + structlog text):
        - `"Invalid Bearer token"` does NOT appear in either surface.
        - `"sk-redacted-token-abc"` does NOT appear in either surface.
        - `result.models_endpoint_status_code == 401`.
        - Captured structlog at WARN level has `step="models_endpoint"` AND `status_code=401`.
     6. Story 1.3 picks up the endpoint-layer test (see Story 1.3 task 5).

**Definition of Done (DoD)**

- [ ] `_probe_models_endpoint` return type is `tuple[bool, int | None]`.
- [ ] `check_capabilities()` correctly threads the status code into `CapabilityResult(models_endpoint_status_code=...)`.
- [ ] All 7 unit-test cases above (401 with WARN log assertion, 429, 500, network error, success, backwards compat, AC-10 redaction end-to-end) pass.
- [ ] AC-10 cache-layer redaction test asserts on TWO surfaces: `CapabilityResult.model_dump_json()` (the value sent to Redis) and captured structlog text. The third surface (`/healthz` response body) is owned by Story 1.3's end-to-end AC-10 test. **This is the hardest gate in the PR; do not weaken it.**
- [ ] `make lint` + `make typecheck` + `make test-unit` pass.
- [ ] Coverage gate (80%) maintained (the new branches in `_probe_models_endpoint` are fully covered by the test matrix).
- [ ] No `response.text` / `response.json()` body content leaks into `CapabilityResult` (mechanically — the implementation never reads the body except for the status code property), into logs (verified by AC-10 cache-layer test in this story), or into the `/healthz` response (verified by AC-10 endpoint-layer test in Story 1.3). The two AC-10 tests together cover all three required surfaces.

---

### Story 1.3 — Surface `models_endpoint` + `models_endpoint_status_code` in `/healthz`

**Outcome:** The `/healthz` response's `openai_capabilities` block carries two new fields: `models_endpoint: Literal["ok", "fail", "untested"]` (required string) and `models_endpoint_status_code: int | None` (required-but-nullable). The cache-miss branch reports `models_endpoint: "untested"` + `models_endpoint_status_code: null`. The cache-hit branch projects from `CapabilityResult`. Existing consumers reading only the three existing fields (`chat / function_calling / structured_output`) continue to work.

**New files:** None.

**Modified files**

| File | Change |
|---|---|
| [`backend/app/api/health.py`](../../../../backend/app/api/health.py) | (a) Add `models_endpoint: Literal["ok", "fail", "untested"]` and `models_endpoint_status_code: int \| None = Field(...)` (REQUIRED, no default — explicit-pass at every construction site) to `OpenAICapabilities` (lines 72-82). (b) Update the cache-hit construction at lines 277-282 to pass `models_endpoint=cap.models_endpoint, models_endpoint_status_code=cap.models_endpoint_status_code`. (c) Update the cache-miss construction at lines 283-286 to pass `models_endpoint="untested", models_endpoint_status_code=None`. (d) Keep `JSONResponse(content=body.model_dump())` at line 298 unchanged — do NOT pass `exclude_none=True`. |
| [`backend/tests/unit/test_health.py`](../../../../backend/tests/unit/test_health.py) | Add response-shape assertions for the new fields across cache-hit and cache-miss paths. |
| [`backend/tests/contract/test_health_contract.py`](../../../../backend/tests/contract/test_health_contract.py) | Assert OpenAPI schema includes both new fields (required-but-nullable for `models_endpoint_status_code`). |

**Endpoints**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `GET` | `/healthz` | — | `200` `HealthResponse` body with `openai_capabilities.{models_endpoint, models_endpoint_status_code, chat, function_calling, structured_output}` | `503` (degraded — same body shape; openai `incapable` is non-blocking per [`health.py:127-138`](../../../../backend/app/api/health.py#L127-L138) and does NOT trigger 503) |

**Pydantic schemas**

```python
# backend/app/api/health.py
class OpenAICapabilities(BaseModel):
    """Cached results of the OpenAI capability check (Story 3.3 populates Redis)."""

    models_endpoint: Literal["ok", "fail", "untested"] = Field(                # NEW
        description=(
            "GET /models probe outcome. 'ok' / 'fail' are projected from "
            "CapabilityResult.models_endpoint; 'untested' is the cache-miss "
            "default (matches chat/function_calling/structured_output)."
        )
    )
    models_endpoint_status_code: int | None = Field(                            # NEW
        description=(
            "HTTP status code from the GET /models probe when it HTTP-failed "
            "(>= 400). null for success / network-class failure / cache miss. "
            "Required-but-nullable: always present in the response JSON with "
            "explicit null when no value."
        )
    )
    chat: Literal["ok", "fail", "untested"] = Field(...)                        # UNCHANGED
    function_calling: Literal["ok", "fail", "untested"] = Field(...)            # UNCHANGED
    structured_output: Literal["ok", "fail", "untested"] = Field(...)           # UNCHANGED
```

**Tasks**

1. Add the two new fields to `OpenAICapabilities` per the Pydantic schemas block. The order in the class matches the order in the response body — put `models_endpoint` BEFORE `chat / function_calling / structured_output` (it's step 1 in the probe sequence).
2. Update the cache-hit construction at `health.py:277-282`:
   ```python
   capabilities = OpenAICapabilities(
       models_endpoint=cap.models_endpoint,
       models_endpoint_status_code=cap.models_endpoint_status_code,
       chat=cap.chat_completion,
       function_calling=cap.function_calling,
       structured_output=cap.structured_output,
   )
   ```
3. Update the cache-miss construction at `health.py:283-286`:
   ```python
   capabilities = OpenAICapabilities(
       models_endpoint="untested",
       models_endpoint_status_code=None,
       chat="untested",
       function_calling="untested",
       structured_output="untested",
   )
   ```
4. Verify `JSONResponse(content=body.model_dump())` at line 298 stays unchanged — Pydantic's default `model_dump()` includes `None` values. **Do not pass `exclude_none=True`** (would omit the field on null and break AC-2).
5. Add unit tests in `backend/tests/unit/test_health.py`:
   - **AC-1 (cache hit, HTTP 401 in cache — exercises the REAL `probe_openai_state` mapping):** Override `_read_capability_cache` to return a `CapabilityResult(models_endpoint="fail", models_endpoint_status_code=401, ...)`. Critically: do NOT monkeypatch `probe_openai_state` to a fixed value in this test (other tests in the file do this for convenience — see [`test_health.py:103-113`](../../../../backend/tests/unit/test_health.py#L103-L113) for the pattern). Configure a non-empty OpenAI API key in Settings. Assert response body has `openai_capabilities.models_endpoint == "fail"`, `openai_capabilities.models_endpoint_status_code == 401`, AND `body["subsystems"]["openai"] == "incapable"` (proves the real mapping at [`probes.py:158`](../../../../backend/app/api/probes.py#L158) still maps `models_endpoint == "fail"` → `"incapable"` post-fix).
   - **AC-2 (cache hit, network failure in cache):** `CapabilityResult(models_endpoint="fail", models_endpoint_status_code=None, ...)`. Assert response includes both keys with `models_endpoint == "fail"` and `models_endpoint_status_code is None` (explicit `null`, not missing).
   - **AC-5 health-layer (cache hit, success path):** Override cache to return `CapabilityResult(models_endpoint="ok", models_endpoint_status_code=None, chat_completion="ok", function_calling="ok", structured_output="ok", ...)`. Assert response has `openai_capabilities.models_endpoint == "ok"`, `models_endpoint_status_code is None` (explicit `null`, key present), AND `subsystems.openai == "configured"`. This is the success-path null-presence assertion required by spec FR-2.
   - **AC-6 (cache miss):** Override `_read_capability_cache` to return `None`. Assert response has `openai_capabilities.models_endpoint == "untested"`, `models_endpoint_status_code is None`, AND `subsystems.openai == "configured"` (cache-miss branch unchanged).
   - **AC-7 (backwards compat):** Assert the existing three fields (`chat / function_calling / structured_output`) still serialize with the same Literal value space in every response above.
   - **AC-10 endpoint-layer (security redaction — full end-to-end through cache and `/healthz`):** This is Story 1.3's half of the AC-10 split, and it MUST chain from a real mocked 401 response — not from a hand-constructed clean `CapabilityResult` (per GPT-5.5 cycle-3 finding B1: a clean fixture can't catch regressions where `check_capabilities()` accidentally stores body text in a new field that downstream code then surfaces). Test design:
     1. httpx mock returns `Response(401, json={"error": {"message": "Invalid Bearer token: sk-redacted-token-abc"}})` for `GET /models`.
     2. Run `await check_capabilities(...)` against the mock; capture the exact JSON string passed to `redis.set()` (via the Redis mock's `.set.call_args[0][1]`).
     3. Deserialize that captured JSON via `CapabilityResult.model_validate_json(captured_json)` — this is the round-trip the real `_read_capability_cache` path performs.
     4. Override the `/healthz` `_read_capability_cache` to return the deserialized result.
     5. Capture structlog output via the existing `assert_log_level` pattern.
     6. Call `GET /healthz` via the ASGI test client.
     7. Assert ALL three surfaces are body-free:
        - The captured `redis.set()` JSON string excludes `"Invalid Bearer token"` and `"sk-redacted-token-abc"`.
        - The captured structlog text excludes those substrings (only `status_code=401` integer is present at WARN with `step="models_endpoint"`).
        - The raw `/healthz` response text (`resp.text`, NOT just the parsed JSON) excludes those substrings.
     8. Also assert `body["openai_capabilities"]["models_endpoint_status_code"] == 401` (positive case — the integer IS surfaced).
     **Why this end-to-end design:** It exercises the actual data flow (mock 401 → `check_capabilities` → Redis write → deserialize → `/healthz` → JSONResponse). A regression where `check_capabilities()` adds a new field that captures body content would be caught here, even if the field had a Pydantic default of `None` (because the 401 path would populate it from `response.text`). The Story 1.2 cache-layer AC-10 test still runs as defence-in-depth — it catches cache-layer regressions before the response schema is wired.
   - **JSON key always present:** For every test above, assert `"models_endpoint_status_code" in body["openai_capabilities"]` (key present even when value is `null`).
6. In [`backend/tests/unit/test_probes.py`](../../../../backend/tests/unit/test_probes.py): extend the `_make_cap()` helper at lines 128-143 to accept `models_endpoint_status_code: int | None = None` (kwarg-only). Add ONE new test asserting `probe_openai_state(...)` returns `"incapable"` for `_make_cap(models="fail", models_endpoint_status_code=401)` — proves the function ignores the new field and the existing `incapable` mapping is unaffected.

7. Update [`backend/tests/contract/test_health_contract.py`](../../../../backend/tests/contract/test_health_contract.py):
   - Extend `TestHealthOpenAPISchema.test_response_schema_matches_documented_keys` to assert `body["openai_capabilities"]` keys are now exactly `{"models_endpoint", "models_endpoint_status_code", "chat", "function_calling", "structured_output"}`.
   - Add a new test that exercises a cache-hit path with `models_endpoint_status_code=401` and asserts the OpenAPI schema:
     - `OpenAICapabilities.properties.models_endpoint.enum` equals `["ok", "fail", "untested"]` (order-insensitive — use `set(...)` comparison). This is the FR-5 contract assertion on the literal value space.
     - `OpenAICapabilities.required` includes both `"models_endpoint"` and `"models_endpoint_status_code"`.
     - `OpenAICapabilities.properties.models_endpoint_status_code` is nullable — Pydantic v2 emits `{"anyOf": [{"type": "integer"}, {"type": "null"}]}` for `int | None = Field(...)`. Assert this shape.
8. Run `make test-unit` + `make test-contract` + `make lint` + `make typecheck` — all clean.

**Definition of Done (DoD)**

- [ ] `OpenAICapabilities` declares `models_endpoint` (required `Literal["ok", "fail", "untested"]`) and `models_endpoint_status_code` (required-but-nullable `int | None`) per §19 D-1, D-2, D-3, D-8.
- [ ] Cache-hit response carries the cached values for both fields (AC-1, AC-2).
- [ ] Cache-miss response carries `"untested"` + `null` (AC-6).
- [ ] The JSON response body always includes both keys; `models_endpoint_status_code` is `null` (not omitted) for the success / network-error / cache-miss cases (AC-7, AC-10 response-layer).
- [ ] Contract test asserts OpenAPI schema lists both fields as required, with `models_endpoint_status_code` nullable.
- [ ] Coverage gate (80%) maintained.
- [ ] `make test-unit` + `make test-contract` + `make lint` + `make typecheck` pass.
- [ ] Existing `/healthz` consumers that read only the three pre-existing capability fields continue to receive correct values (AC-7).

---

### Story 1.4 — Update `llm-orchestration.md` documentation

**Outcome:** The architecture doc reflects the new `/healthz` response shape and explains the `models_endpoint=fail → chat/fc/struct=untested` cascade. The doc also surfaces the repo-secret-vs-`.env` divergence risk so operators reading the doc know what to do when CI reports `models_endpoint: "fail"` + `models_endpoint_status_code: 401`.

**New files:** None.

**Modified files**

| File | Change |
|---|---|
| [`docs/01_architecture/llm-orchestration.md`](../../../01_architecture/llm-orchestration.md) | (a) Update the JSON example in §"Capability check at startup" (currently at lines 68-78) to include `models_endpoint_status_code: null` in the success-path example. (b) Append a new paragraph after the example explaining the `models_endpoint=fail → 3× untested` cascade and the `/healthz` projection. (c) Append a one-line repo-secret-vs-`.env` divergence note. |

**Tasks**

1. Update the `CapabilityResult` JSON example to include the new field AND fix a pre-existing inaccuracy (the live doc uses `"structured_output": "degraded"`, but the `Literal["ok", "fail", "untested"]` schema at [`capability_models.py:33`](../../../../backend/app/llm/capability_models.py#L33) doesn't permit `"degraded"` — this is a stale value left from an earlier draft):
   ```json
   {
     "base_url": "http://ollama:11434/v1",
     "model": "llama3.1:70b-instruct",
     "models_endpoint": "ok",
     "models_endpoint_status_code": null,
     "chat_completion": "ok",
     "function_calling": "ok",
     "structured_output": "ok",
     "tested_at": "2026-05-09T12:00:00Z"
   }
   ```
   Show a parallel "step-1-failure" example beneath the success one to illustrate the cascade:
   ```json
   {
     "base_url": "https://api.openai.com/v1",
     "model": "gpt-4o-2024-08-06",
     "models_endpoint": "fail",
     "models_endpoint_status_code": 401,
     "chat_completion": "untested",
     "function_calling": "untested",
     "structured_output": "untested",
     "tested_at": "2026-05-24T10:00:00Z"
   }
   ```
2. Append a paragraph after the example:
   > **Cascade on step-1 failure.** When `models_endpoint == "fail"`, steps 2–4 are skipped and reported as `"untested"` (probing chat/function-calling/structured-output is meaningless against an unreachable endpoint). `/healthz` surfaces this combination as `subsystems.openai: "incapable"` + `openai_capabilities.models_endpoint: "fail"` + 3× `"untested"`. The `models_endpoint_status_code` field tells the operator *why* step 1 failed: `401 → bad key`, `403 → quota/billing`, `429 → rate-limited`, `5xx → OpenAI outage`, `null → network unreachable (DNS / timeout / connection-refused)`. Detailed failure context (URL, error text) stays in the api container's WARN log per [`backend/app/llm/capability_check.py:67-80`](../../../../backend/app/llm/capability_check.py#L67-L80).
3. Add or update a `/healthz` response snippet adjacent to the existing capability-check section showing the post-fix `openai_capabilities` block with all five keys (success-path example):
   ```json
   "openai_capabilities": {
     "models_endpoint": "ok",
     "models_endpoint_status_code": null,
     "chat": "ok",
     "function_calling": "ok",
     "structured_output": "ok"
   }
   ```
   And a failure-path example with `models_endpoint: "fail"` + `models_endpoint_status_code: 401` so operators reading the doc can pattern-match what they see in CI.

4. Append a note on operator `.env` vs. repo-secret divergence:
   > **Repo-secret vs operator `.env` divergence.** The `OPENAI_API_KEY_TEST` value populated in GitHub Actions' repo secret may not match any individual operator's `./secrets/openai_key` file. If CI's smoke gate reports `models_endpoint: "fail"` + `models_endpoint_status_code: 401`, the next step is to rotate the repo secret with a known-good key. Per CLAUDE.md operator-environment handoff, repo secrets are operator-only — Claude cannot modify them. The smoke job's diagnostic surface for this case is the `smoke-logs.txt` artifact built at [`.github/workflows/pr.yml:444-445`](../../../../.github/workflows/pr.yml#L444-L445).

**Definition of Done (DoD)**

- [ ] `docs/01_architecture/llm-orchestration.md` §"Capability check at startup" JSON example includes `models_endpoint_status_code`.
- [ ] Cascade paragraph + repo-secret divergence note are present.
- [ ] `make lint` passes (markdown link checker, if enabled, finds no broken refs).
- [ ] No code/test changes in this story.

---

## 3) Testing workstream

Tests are co-located in the relevant story's DoD (RelyLoop convention — see CLAUDE.md "Testing Conventions"). Below is the cross-story inventory.

### 3.1 Unit tests

- Location: [`backend/tests/unit/test_capability_check.py`](../../../../backend/tests/unit/test_capability_check.py), [`backend/tests/unit/test_health.py`](../../../../backend/tests/unit/test_health.py)
- Scope: probe return contract, status-code threading, `OpenAICapabilities` response-model construction, AC-10 secret-redaction invariant
- Tasks:
  - [ ] **Story 1.2:** Probe tests — 7 cases:
    - HTTP 401 (with WARN log `status_code=401` assertion)
    - HTTP 429
    - HTTP 500
    - Network error (`httpx.ConnectError`)
    - HTTP 200 (success)
    - Backwards compat (pre-fix JSON deserialization)
    - AC-10 cache-layer redaction (CapabilityResult + structlog)
  - [ ] **Story 1.3:** Health-endpoint tests in `test_health.py` — 5 cases:
    - AC-1 cache-hit HTTP failure WITH real `probe_openai_state` mapping (asserts `subsystems.openai == "incapable"`)
    - AC-2 cache-hit network failure
    - AC-5 cache-hit success path (proves `models_endpoint_status_code: null` always present in the JSON)
    - AC-6 cache miss
    - AC-10 endpoint-layer redaction (full GET /healthz call; assert raw response text excludes body substrings)
  - [ ] **Story 1.3:** `test_probes.py` defensive assertion that `probe_openai_state` still maps `models_endpoint="fail" + status_code=401` → `"incapable"`.
  - [ ] **Story 1.3:** `test_health_contract.py` extensions — response-key-set assertion + OpenAPI nullable-field schema assertion.
- DoD:
  - [ ] All new test cases pass:
    - 7 cases in `test_capability_check.py` (Story 1.2: 401 with WARN-log assertion, 429, 500, network error, success, backwards compat, AC-10 cache-layer redaction)
    - 5 cases in `test_health.py` (Story 1.3: AC-1 cache-hit-fail with real `probe_openai_state` mapping, AC-2 cache-hit-network-fail, AC-5 cache-hit-success-null-presence, AC-6 cache miss, AC-10 endpoint-layer redaction)
    - 1 case in `test_probes.py` (Story 1.3: defensive `probe_openai_state` ignoring the new field)
    - 2 cases in `test_health_contract.py` (Story 1.3: response-key-set assertion + OpenAPI nullable-field assertion)
    - **Total: 15 new/updated cases across 4 test files**
  - [ ] AC-10 redaction is covered across BOTH stories:
    - Story 1.2 cache-layer test asserts `CapabilityResult.model_dump_json()` + structlog are body-free.
    - Story 1.3 endpoint-layer test (full end-to-end: mock 401 → check_capabilities → Redis JSON round-trip → /healthz response) asserts the raw `/healthz` response text is body-free.
    - Both tests assert the WARN log carries `status_code=401`.

### 3.2 Integration tests

N/A — no DB schema changes, no service-layer orchestration changes, no Arq worker changes. The capability check is unit-testable via httpx mocks; the `/healthz` endpoint is unit-testable via `_read_capability_cache` override.

### 3.3 Contract tests

- Location: [`backend/tests/contract/test_health_contract.py`](../../../../backend/tests/contract/test_health_contract.py)
- Scope: OpenAPI schema + response-body shape parity for the new fields
- Tasks:
  - [ ] **Story 1.3:** Extend `TestHealthOpenAPISchema.test_response_schema_matches_documented_keys` to assert `body["openai_capabilities"]` keys include `"models_endpoint"` and `"models_endpoint_status_code"`.
  - [ ] **Story 1.3:** Add a contract test that fetches `app.openapi()`, navigates to the `OpenAICapabilities` schema component, and asserts both new fields are in `required` and `models_endpoint_status_code` has nullable type encoding.
- DoD:
  - [ ] No accepted endpoint without contract coverage.
  - [ ] OpenAPI schema reflects the new required-but-nullable `models_endpoint_status_code` field.

### 3.4 E2E tests

N/A — no UI surface change. The `/healthz` response is consumed by operator curl and the smoke-job artifact capture only.

### 3.5 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| [`backend/tests/unit/test_capability_check.py`](../../../../backend/tests/unit/test_capability_check.py) | Uses `_probe_models_endpoint(...) -> bool` return type | The probe is only called via `check_capabilities` in test fixtures; the existing assertions on `CapabilityResult.models_endpoint` continue to work without change. New tests are additive (see Story 1.2). | Add new tests; do not break existing ones. |
| [`backend/tests/unit/test_health.py`](../../../../backend/tests/unit/test_health.py) | Asserts on `/healthz` response shape (no direct `OpenAICapabilities(...)` construction — verified by `grep` post-spec-gen: 0 sites in this file) | The only `OpenAICapabilities(...)` constructor sites are in [`backend/app/api/health.py:277`](../../../../backend/app/api/health.py#L277) and [`backend/app/api/health.py:283`](../../../../backend/app/api/health.py#L283); both branches updated in Story 1.3 task 2 + task 3. test_health.py needs response-body-key-presence assertions (the new keys, the always-present-with-null serialization for `models_endpoint_status_code`), NOT constructor fixture edits. | Update response-shape assertions per Story 1.3 task 5; no fixture-constructor edits required. |
| [`backend/tests/unit/test_probes.py`](../../../../backend/tests/unit/test_probes.py) | `_make_cap()` helper builds `CapabilityResult` (lines 128-143) | `CapabilityResult.models_endpoint_status_code` has a default of `None` per Story 1.1 — the helper continues to work unchanged. **Add ONE defensive assertion** that `probe_openai_state` ignores the new field: pass `_make_cap(models="fail")` with a non-None `models_endpoint_status_code` and verify the function still returns `"incapable"` (i.e., the mapping logic at [`probes.py:151-159`](../../../../backend/app/api/probes.py#L151-L159) does not regress when reading caches with the new field). Extend `_make_cap()` with an optional `models_endpoint_status_code: int \| None = None` kwarg. | Add one small test + extend helper signature. Owner: Story 1.3 (since it lands after Story 1.1's field exists). |
| [`backend/tests/unit/agent/conftest.py`](../../../../backend/tests/unit/agent/conftest.py) | Lines 169, 184: `CapabilityResult(models_endpoint="ok", ...)` fixtures | `CapabilityResult.models_endpoint_status_code` defaults to `None` per Story 1.1 — fixtures keep working. | No change required. |
| [`backend/tests/unit/services/test_agent_judgments_dispatch.py`](../../../../backend/tests/unit/services/test_agent_judgments_dispatch.py) | Imports `CapabilityResult` | Additive change; no shape break. | No change required. |
| [`backend/tests/contract/test_health_contract.py`](../../../../backend/tests/contract/test_health_contract.py) | `set(body["subsystems"].keys())` assertions (lines 157-164); no `openai_capabilities` assertions yet | Must add `openai_capabilities` key-set assertion AND OpenAPI schema assertions for the new fields. | Extend per Story 1.3. |
| [`backend/tests/contract/test_openapi_surface.py`](../../../../backend/tests/contract/test_openapi_surface.py) | Surface-level OpenAPI counts | If the surface count asserts on the schema component count, it MAY need a bump (the `OpenAICapabilities` schema gains 2 fields but stays one schema component). | Verify by running `make test-contract` after Story 1.3; only patch if the test fails. |

### 3.5 Migration verification

N/A — no Alembic migration. The change is purely Pydantic / response-shape.

### 3.6 CI gates

- [ ] `make test-unit` (all green, including the 13 new unit-level cases: 7 probe + 5 health + 1 probes-defensive)
- [ ] `make test-contract` (all green, including the 2 new contract assertions)
- [ ] `make lint` (ruff)
- [ ] `make typecheck` (mypy `--strict`)
- [ ] Coverage gate (80%) maintained

---

## 4) Documentation update workstream

### 4.0 Core context files

- [ ] **`state.md`** — update the "Recent changes" section after merge with a one-line entry (handled by `impl-execute` finalization).
- [ ] **`architecture.md`** — likely no update needed (the response shape change is documented in `llm-orchestration.md` per Story 1.4). Verify post-implementation.
- [ ] **`CLAUDE.md`** — no update needed. The CLAUDE.md mention of `/healthz` shape (Absolute Rule #6) is high-level; field-level shape is governed by the spec.

### 4.1 Architecture docs (`docs/01_architecture`)

- [x] **Story 1.4:** Update `docs/01_architecture/llm-orchestration.md` per FR-4 / AC-9.

### 4.2 Product docs (`docs/02_product`)

- [ ] Move the `bug_openai_capability_check_incapable_on_valid_key/` folder to `docs/00_overview/implemented_features/<YYYY_MM_DD>_<short_name>/` after merge (handled by `impl-execute` finalization).

### 4.3 Runbooks (`docs/03_runbooks`)

- [ ] No new runbook needed — the WARN log path is unchanged; existing operator workflow ("tail api logs") still works. The new `/healthz` fields are self-documenting.

### 4.4 Security docs (`docs/04_security`)

- [ ] No new security doc needed — the secret-redaction invariant is enforced by AC-10's test; the doc already covers secret-handling in general per existing files.

### 4.5 Quality docs (`docs/05_quality`)

- [ ] No quality-doc updates — `docs/05_quality/testing.md` 80% coverage gate is maintained, and the test layer convention is unchanged.

**Documentation DoD**

- [ ] `state.md` and `architecture.md` are consistent with shipped behavior post-merge.
- [ ] `docs/01_architecture/llm-orchestration.md` reflects the new `/healthz` response shape.
- [ ] No new runbooks required; existing operator workflow continues to work.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

None — this is a bounded bug fix, not a refactor. No code is being relocated or restructured beyond the additive Pydantic fields and the `_probe_models_endpoint` return-type widening (a strict subset of "return more information than before").

### 5.2 Planned refactor tasks

None.

### 5.3 Refactor guardrails

- [x] No expansion of product scope.
- [x] Behavioral parity proven by tests (AC-7 + AC-8 explicitly assert backwards compatibility).
- [x] Lint/typecheck remain green.
- [x] Track discovered debt with owner + disposition (none expected; surface any in the post-impl tangential-discoveries sweep).

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `infra_foundation` (PR #4, merged) | All stories | Implemented | N/A |
| Redis (cache subsystem) | Story 1.3 cache-hit path | Implemented | Already wired; same risk model as pre-fix. |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Pre-fix cached `CapabilityResult` rows fail to deserialize after deploy | Low | Medium (24h cache miss → `/healthz` reports `models_endpoint: "untested"` for ~5s post-restart per container) | AC-8 backwards-compat test in Story 1.2 explicitly validates pre-fix JSON deserialization. Pydantic v2 + `default=None` handles missing-field-on-read cleanly. |
| Backend cache-hit/cache-miss branches fail to construct `OpenAICapabilities` after the field becomes required | Medium | Low (caught immediately by `make test-unit`) | The only constructor sites are the cache-hit and cache-miss branches in [`backend/app/api/health.py:277` + `:283`](../../../../backend/app/api/health.py#L277); `test_health.py` does NOT directly construct `OpenAICapabilities` (verified by `grep "OpenAICapabilities" backend/tests/unit/test_health.py` → 0 matches). Story 1.3 task 2 + task 3 update the two constructor sites; task 5 adds response-shape assertions to `test_health.py`. |
| AC-10 redaction test gives false confidence (e.g., asserts only on `model_dump_json()` and misses log capture) | Low | High (silent security regression if a future change adds body content to logs) | AC-10's DoD requires assertions on three surfaces; explicit DoD checkbox per Story 1.2. Reviewer should flag any weakening. |
| `exclude_none=True` accidentally introduced (omitting `models_endpoint_status_code: null` from the response) | Low | Low (breaks AC-2; caught by Story 1.3 cache-miss test) | Story 1.3 task 4 explicitly verifies `JSONResponse(content=body.model_dump())` is unchanged; contract test asserts key presence on null. |
| Pydantic v2 `int | None = Field(...)` produces a different OpenAPI schema shape than expected | Low | Low (caught by contract test) | Story 1.3 task 6 asserts schema includes the field in `required` AND with the nullable type encoding (`anyOf: [integer, null]`). If Pydantic emits a different shape, the test fails and the fix is local. |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| OpenAI `/models` returns 401 | Bad API key | Cache stores `models_endpoint="fail", models_endpoint_status_code=401`; `/healthz` exposes both; WARN log fires once at startup. | Operator rotates key; restart api container; next capability check repopulates cache. |
| OpenAI `/models` returns 429 | Rate-limited / quota | Same shape with `status_code=429`. | Operator waits / increases quota; restart. |
| Network unreachable (DNS / timeout) | Local LLM daemon down | Cache stores `models_endpoint="fail", models_endpoint_status_code=None`; WARN log captures `error=str(exc)`. | Operator starts the daemon; restart api container. |
| Redis cache write fails | Redis transient hiccup | Capability check completes; cache-write failure logged at WARN; next `/healthz` call sees cache miss → `models_endpoint="untested"`. | Self-recovers on next probe (cache repopulates). |
| Redis cache read fails at `/healthz` time | Redis transient hiccup | `_read_capability_cache` returns `None`; treated as cache miss → `"untested"` + `null`. | Self-recovers on next /healthz call. |
| Pre-fix cached row in Redis | Operator deploys this PR without flushing Redis | `CapabilityResult.model_validate_json(raw)` succeeds with `models_endpoint_status_code = None` (Pydantic default). `/healthz` shows `models_endpoint_status_code: null` until the next capability check overwrites the row. | Self-recovers within ~5s of container restart (next fire-and-forget probe rewrites the cache with the new field). |

## 7) Sequencing and parallelization

### Suggested sequence

1. **Story 1.1** — add field to `CapabilityResult`. Independent; pure model declaration.
2. **Story 1.2** — refactor probe + add status-code threading. Depends on Story 1.1's field existing.
3. **Story 1.3** — surface fields in `OpenAICapabilities` response + tests + contract. Depends on Story 1.2's `CapabilityResult` shape being correct (the cache-hit path projects from it).
4. **Story 1.4** — documentation. Independent of 1.1-1.3 implementation, but should be written after 1.3 lands so the example response JSON reflects the implemented shape.

### Parallelization opportunities

For a single agent / single PR, sequential execution is preferred (Story 1.4 docs can be drafted in parallel but should be finalized after 1.3 to avoid drift). The bug is small enough that there's no value in parallel branches.

## 8) Rollout and cutover plan

- **Rollout stages:** Single deploy via the standard PR → merge → CI → main. No staged rollout, no feature flag.
- **Feature flag strategy:** None. The change is backwards-compatible additive — existing consumers are unaffected.
- **Migration/cutover steps:** None. No Alembic migration; Redis cache rows expire naturally within 24h and deserialize cleanly via Pydantic's optional-field defaulting (see AC-8).
- **Reconciliation/repair strategy:** None needed.

## 9) Execution tracker (copy/paste section)

### Current sprint
- [ ] Story 1.1 — Extend `CapabilityResult` with `models_endpoint_status_code`
- [ ] Story 1.2 — Update `_probe_models_endpoint` + threading + unit tests (including AC-10 redaction)
- [ ] Story 1.3 — Surface new fields in `OpenAICapabilities` + unit + contract tests
- [ ] Story 1.4 — Update `llm-orchestration.md`

### Blocked items

None.

### Done this sprint

(populated by `impl-execute` as stories complete)

## 10) Story-by-Story Verification Gate (Agent Checklist)

Before marking any story complete:

- [ ] Files created/modified match story scope.
- [ ] Pydantic schema changes match the Key interfaces / Pydantic schemas block.
- [ ] All cited line numbers in the story (e.g., "line 306", "lines 277-282") match the actual file (verify by reading; line numbers may shift after Story 1.2's refactor).
- [ ] Required tests added/updated for the layers touched.
- [ ] Commands executed and passed:
  - [ ] `make lint`
  - [ ] `make typecheck`
  - [ ] `make test-unit`
  - [ ] `make test-contract` (after Story 1.3)
- [ ] No `make test-integration` required (story scope does not touch DB / services / workers).
- [ ] No `make e2e` required (no UI changes).
- [ ] AC-10 redaction test passes — the security invariant is the highest gate; it MUST be green.
- [ ] Related docs updated in same PR when behavior changed (Story 1.4).

## 11) Plan consistency review

1. **Spec → plan endpoint count**: Spec §8.1 lists 1 endpoint (`GET /healthz`). Plan covers it in Story 1.3. ✓
2. **Spec → plan FR coverage**: 5 FRs (FR-1..FR-5). All mapped in §1 traceability table. ✓
3. **Spec → plan AC coverage**:
   - AC-1 → Story 1.3 (cache-hit test)
   - AC-2 → Story 1.3 (network-failure-cache test)
   - AC-3, AC-4, AC-5 → Story 1.2 (probe matrix)
   - AC-6 → Story 1.3 (cache-miss test)
   - AC-7 → Story 1.3 (backwards-compat assertion)
   - AC-8 → Story 1.2 (pre-fix cache deserialization)
   - AC-9 → Story 1.4 (doc update)
   - AC-10 → Story 1.2 (redaction test on 3 surfaces) + Story 1.3 (response-layer redaction)
   ✓ all 10 ACs covered.
4. **Spec §19 decision coverage**: D-1 (`untested` cache-miss) → Story 1.3 task 3. D-2 (cached schema unchanged) → Story 1.1. D-3/D-8 (required-but-nullable) → Story 1.3 Pydantic schemas block + task 4. D-4 (probe return contract) → Story 1.2 Key interfaces. D-5 (security regression test) → Story 1.2 task 3 AC-10. D-6/D-9 (CI workflow out of scope; smoke-logs.txt is the diagnostic surface) → no implementation tasks (deliberately). D-7 (rejected B4) → N/A. ✓
5. **Story internal consistency**: Each story's Key interfaces match the Modified files claims; the Pydantic schemas block in Story 1.3 matches the cache-hit construction in task 2. ✓
6. **Test file count**: 4 test files modified — `backend/tests/unit/test_capability_check.py` (Story 1.2), `backend/tests/unit/test_health.py` (Story 1.3), `backend/tests/unit/test_probes.py` (Story 1.3 — `_make_cap()` helper extension + defensive `probe_openai_state` assertion per cycle-1 B2), `backend/tests/contract/test_health_contract.py` (Story 1.3). Each assigned to a specific story. ✓
7. **Gate arithmetic**: No epic/phase gates beyond standard CI; single epic. ✓
8. **Open questions resolved**: §19 has zero open questions (all closed in cycle 1/2/3 of spec-gen). ✓
9. **Plan ↔ codebase verification**:
   - `backend/app/llm/capability_models.py:19` — class `CapabilityResult(BaseModel)` ✓
   - `backend/app/llm/capability_check.py:61` — `async def _probe_models_endpoint(client, base_url, api_key) -> bool` ✓
   - `backend/app/llm/capability_check.py:306` — `models_ok = await _probe_models_endpoint(...)` ✓
   - `backend/app/llm/capability_check.py:323-331` — `CapabilityResult(...)` construction ✓
   - `backend/app/api/health.py:72-82` — `class OpenAICapabilities(BaseModel)` ✓
   - `backend/app/api/health.py:277-286` — cache-hit and cache-miss branches ✓
   - `backend/app/api/health.py:298` — `JSONResponse(content=body.model_dump())` ✓
   - `backend/tests/unit/test_capability_check.py` — exists ✓
   - `backend/tests/unit/test_health.py` — exists ✓
   - `backend/tests/unit/test_probes.py:128-143` — `_make_cap()` helper ✓
   - `backend/tests/contract/test_health_contract.py` — exists ✓
   - All cited line numbers verified by reading the source files during spec-gen Pass 1.
10. **Infrastructure path verification**: No migrations; no new routers; no new services. N/A.
11. **Frontend data plumbing verification**: N/A — no frontend scope.
12. **Persistence scope consistency**: N/A — no `localStorage` / `sessionStorage`.
13. **Enumerated value contract audit**: Spec §8.4 enum table is present and cites concrete backend source files for every literal. Story 1.3 task 1 adds the `Literal["ok", "fail", "untested"]` declaration; the Pydantic schemas block enumerates all three values explicitly. Story 1.4 doc shows the same three values in the cascade paragraph. ✓
14. **Admin control and ceiling enforcement audit**: N/A (MVP4+ rule; MVP1 has no admin model).
15. **Audit-event coverage audit**: N/A (MVP2+ rule; MVP1 has no `audit_log` table).

---

## 12) Definition of plan done

- [x] Every FR (FR-1..FR-5) mapped to stories/tasks/tests.
- [x] Every story includes New files, Modified files, Tasks, DoD (Endpoints + Key interfaces + Pydantic schemas where applicable).
- [x] Test layers explicitly scoped (unit + contract; no integration / E2E / migration needed).
- [x] Documentation updates planned and owned (Story 1.4 + post-merge state.md/architecture.md).
- [x] Lean refactor scope: explicitly none.
- [x] No epic/phase gates beyond standard CI.
- [x] Story-by-Story Verification Gate included (§10).
- [x] Plan consistency review (§11) performed with no unresolved findings.
- [ ] Cross-model review (Step 6) — pending GPT-5.5 cycle 1.
