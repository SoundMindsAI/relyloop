# Feature Specification — Cluster base_url SSRF guard (hostname-aware)

**Date:** 2026-06-09
**Status:** Draft
**Owners:** soundminds.ai (Product), RelyLoop Eng (Engineering)
**Related docs:**
- [`idea.md`](idea.md)
- [`docs/04_security/README.md`](../../../04_security/README.md)
- [`docs/01_architecture/cluster-lifecycle.md`](../../../01_architecture/cluster-lifecycle.md)

---

## 1) Purpose

- **Problem:** The cluster `base_url` validator at `backend/app/api/v1/schemas.py` is intended to stop SSRF into internal / cloud-metadata endpoints (it cites "spec §10 Threat 3"), but it only inspects the host when it parses as a **literal IP address**. Any DNS **hostname** is returned unchecked (`schemas.py:135-137`), so in the hardened posture (`RELYLOOP_ALLOW_PRIVATE_CLUSTERS=False`) the guard is trivially bypassed by `http://metadata.google.internal/...`, `http://vault.internal:8200`, or any name that resolves to an internal/loopback/link-local address. RelyLoop then issues HTTP requests to that host during the registration probe / `test-connection` and on every health probe, caches the response, and surfaces it via cluster detail — a read-SSRF exfiltration path.
- **Outcome:** When private clusters are disallowed (`RELYLOOP_ALLOW_PRIVATE_CLUSTERS=False`), a `base_url` whose host **resolves** to a private / loopback / link-local / reserved / multicast / unspecified / carrier-grade-NAT address — or whose host is a known cloud-metadata name — is rejected with a deterministic `400 CLUSTER_URL_BLOCKED` before any network probe, on both `POST /api/v1/clusters` and `POST /api/v1/clusters/test-connection`. The literal-IP and hostname paths are unified behind one shared policy helper so they cannot drift.
- **Non-goal:** This does **not** close the DNS-rebinding window (host resolves to a benign IP at validation, an internal IP at connect time). Connect-time IP pinning is deferred to Phase 2 (`phase2_idea.md`). This does **not** change the default local-dev posture: with `RELYLOOP_ALLOW_PRIVATE_CLUSTERS=True` (the MVP1/MVP2 default, laptop convenience) no SSRF policy is applied and `http://elasticsearch:9200`-style Docker hostnames keep working exactly as today.

## 2) Current state audit

### Existing implementations

- **`backend/app/api/v1/schemas.py:117-143`** — `CreateClusterRequest.validate_base_url` (Pydantic `field_validator`). Checks scheme ∈ {http, https} (raises `ValueError` → 422), requires a host, and — **only for literal-IP hosts** — rejects `ip.is_private or ip.is_loopback` when `not get_settings().relyloop_allow_private_clusters`. Hostnames hit the `except ValueError: return v` branch at line 135-137 and skip the check entirely.
- **`backend/app/api/v1/schemas.py:162-180`** — `ConnectionTestRequest.validate_base_url`. **Byte-for-byte duplicate** of the above logic. Drift risk.
- **`backend/app/core/settings.py:302-308`** — `relyloop_allow_private_clusters: bool = Field(default=True, ...)`. **Defaults `True`** ("laptop convenience … flips to False at MVP3 hardening"). So the existing literal-IP guard is a **no-op by default** and only fires in the hardened posture — which is exactly the posture where the hostname bypass matters.
- **`backend/app/services/cluster.py:96-202`** — `register_cluster(...)`. Validates engine/auth, builds an adapter via `_build_adapter_from_args(base_url=...)` (line 148-155), then probes `adapter.health_check()` (line 160). This is the network call the SSRF check must precede.
- **`backend/app/services/cluster.py:253-331`** — `test_cluster_connection(...)`. Same shape: engine/auth validation, then `_build_adapter_from_args` (line 294-301), then `health_check()` (line 306). Documents a "Validation that DOES raise (translated to 400 at the router)" contract — `EngineTypeNotSupported`, `AuthKindNotSupported`, `ClusterUnreachable`. The new SSRF block joins this set.
- **`backend/app/api/v1/clusters.py:244-272`** — `create_cluster` router. Maps service exceptions to `_err(...)` envelopes: `ENGINE_NOT_SUPPORTED`/`AUTH_KIND_NOT_SUPPORTED` → 400, `CLUSTER_NAME_TAKEN` → 409, `ClusterUnreachable` → 503.
- **`backend/app/api/v1/clusters.py:175-209`** — `test_connection` router. Maps `EngineTypeNotSupported`/`AuthKindNotSupported` → 400, `CredentialsInvalid` → 400.
- **`backend/app/api/v1/_errors.py:19-29`** — `_err(status_code, code, message, retryable)` builds `{"error_code", "message", "retryable"}`. Single source of truth.

### Navigation and link impact

N/A — no UI routes change. The create-cluster modal and test-connection button already surface the `_err` envelope's `message`; a new `CLUSTER_URL_BLOCKED` code flows through the existing error-display path with no frontend change required.

| Source file | Current link target | New link target |
|---|---|---|
| N/A | — | — |

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `backend/tests/contract/test_clusters_api_contract.py` | `test_create_cluster_request_validates_scheme` (asserts `ftp://` → `ValidationError match="http or https"`) | 1 | **No change** — scheme validation stays in the Pydantic validator. New tests added alongside. |
| `backend/tests/contract/test_clusters_api_contract.py` | `_make_cluster_request` helper uses `base_url="http://elasticsearch:9200"` | 1 | **No change** — that host is only blocked when `relyloop_allow_private_clusters=False`; the default fixture posture (True) leaves it valid. |

No existing test asserts the literal-IP private-range rejection (verified by grep — only the scheme test exists), so moving the IP-policy decision out of the Pydantic validator and into the service layer breaks no contract test.

### Existing behaviors affected by scope change

- **Literal private-IP `base_url` rejection.** Current: `CreateClusterRequest(base_url="http://10.0.0.1:9200")` raises a Pydantic `ValueError` → **422 VALIDATION_ERROR** *when the flag is False*. New: the literal-IP policy decision moves to the shared service-layer helper and surfaces as **400 CLUSTER_URL_BLOCKED**, consolidating literal-IP and resolved-hostname rejections under one code. **Decision needed: yes** — resolved in §19 Decision log (D-1). This is an internal contract change with no test impact (no test asserts the 422 literal-IP path) and is a no-op in the default `True` posture.

---

## 3) Scope

### In scope

- A shared, async SSRF-policy helper (service layer) that, **only when `not relyloop_allow_private_clusters`**, rejects a `base_url` whose host (a) is a literal IP in a blocked range, (b) resolves (DNS) to any address in a blocked range, or (c) matches the cloud-metadata hostname denylist.
- Wiring the helper into `register_cluster` and `test_cluster_connection`, raising a new `ClusterUrlBlocked` domain exception before `_build_adapter_from_args` / `health_check()`.
- Router mapping of `ClusterUrlBlocked` → `400 CLUSTER_URL_BLOCKED` on both `POST /clusters` and `POST /clusters/test-connection`.
- Expanding the blocked-IP-range classification to `is_private | is_loopback | is_link_local | is_reserved | is_multicast | is_unspecified` plus carrier-grade NAT `100.64.0.0/10`.
- A metadata-hostname denylist constant (`metadata.google.internal`, `metadata`, and the bare metadata IPs which already fail via `is_link_local`).
- Reducing the two duplicated Pydantic validators to one shared structural validator (scheme + host-present only) so they cannot drift.
- A `docs/04_security/` note documenting the control and the residual DNS-rebinding risk.

### Out of scope

- Connect-time IP pinning to defeat DNS rebinding (→ Phase 2, `phase2_idea.md`).
- Any change to the default `relyloop_allow_private_clusters=True` posture or the flag's default value.
- Per-IP allowlisting, egress proxies, or network-policy enforcement (operator/infra responsibility).
- Frontend changes (the new error code rides the existing envelope display).

### API convention check

Per [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md), verified against the codebase:

- **Endpoint prefix:** `/api/v1/clusters` (business resource). Verified `backend/app/api/v1/clusters.py` mounted at `/api/v1` in `backend/app/main.py:211`.
- **Router namespace:** `backend/app/api/v1/clusters.py`.
- **HTTP methods:** both affected endpoints are `POST` (register; diagnostic test-connection). No new endpoints.
- **Non-auth error envelope:** `{ "detail": { "error_code": "<CODE>", "message": "<human>", "retryable": <bool> } }` — verified `backend/app/api/v1/_errors.py:26-29`.
- **Auth error shape:** N/A — single-tenant, no auth surface (MVP1–MVP3).

### Phase boundaries

- **Phase 1 (this spec):** Resolve-and-check at registration / test-connection time + literal-IP set expansion + metadata denylist + validator de-duplication + security doc. Closes the standing hostname-bypass hole. Rationale: this is the high-value, self-contained fix with no new dependencies.
- **Phase 2 (deferred → `phase2_idea.md`):** Connect-time IP pinning — pass the validated, resolved IP through to the adapter's HTTP client (or a pinning resolver) so a name that re-resolves to an internal IP at connect time is still blocked. Rationale: requires threading a resolved IP through `_build_adapter_from_args` → `ElasticAdapter`/`SolrAdapter` httpx client construction (Host-header preservation + TLS SNI handling), a materially larger and riskier change than the registration-time gate, and the rebinding window is a narrower threat than the standing unconditional bypass Phase 1 closes.

## 4) Product principles and constraints

- **Engine-adapter boundary (Absolute Rule #4):** the SSRF policy helper is engine-neutral and lives in the service/domain layer; it must not import or branch on a specific engine adapter. It runs before `_build_adapter_from_args`.
- **Never log secrets (Absolute Rule #10):** the helper operates on `base_url` (host/scheme) only — never on `credentials_ref` or resolved credentials. The rejection `message` includes the offending host but never credentials.
- **Deterministic error contract:** policy rejection is a non-retryable `400`, distinct from the transient `503 CLUSTER_UNREACHABLE`. An operator must be able to tell "you may not point here" from "it didn't answer."
- **No event-loop blocking (CLAUDE.md / sandbox perf):** DNS resolution must use the async resolver (`asyncio.get_running_loop().getaddrinfo(...)`), never blocking `socket.gethostbyname` inside the request path.
- **Backwards-compatible default:** with the flag at its `True` default, behavior is unchanged — no new rejections, local Docker hostnames keep working.

### Anti-patterns

- **Do not** perform DNS resolution inside the Pydantic `field_validator` — validators are synchronous, so blocking DNS I/O there stalls the FastAPI event loop. Resolution belongs in the async service helper.
- **Do not** rely on a hostname string denylist alone — `metadata.google.internal` is one name among many; the load-bearing control is resolving the host and classifying every returned IP. The denylist is defense-in-depth, not the primary control.
- **Do not** fail-closed on DNS resolution failure (NXDOMAIN / timeout) — a name that does not resolve cannot be an SSRF target, and blocking it would reject legitimate-but-temporarily-unresolvable clusters that the existing `503 CLUSTER_UNREACHABLE` path already handles. Treat "unresolvable" as "not an SSRF hit" and let the normal probe path proceed.
- **Do not** keep two copies of the validator — the duplication across `CreateClusterRequest`/`ConnectionTestRequest` is exactly what let drift accumulate.
- **Do not** classify IPv4-mapped IPv6 (`::ffff:10.0.0.1`) or scoped addresses naively — normalize via the `ipaddress` module's mapped-address handling before classification.

## 5) Assumptions and dependencies

- Dependency: **Python `ipaddress` + `asyncio` stdlib** — Why required: range classification + async DNS. Status: implemented (stdlib). Risk if missing: none.
- Dependency: **`RELYLOOP_ALLOW_PRIVATE_CLUSTERS` setting** — Why required: the policy is gated on it. Status: implemented (`settings.py:302`). Risk if missing: n/a.
- No DB, no migration, no new third-party package, no cross-feature dependency.

## 6) Actors and roles

- Primary actor(s): the Relevance Engineer registering a cluster (or testing a connection); the system health-probe path consuming the same `base_url` downstream.
- Role model: **N/A — single-tenant install, no auth surface** (MVP1–MVP3 per [`docs/01_architecture/tech-stack.md`](../../../01_architecture/tech-stack.md)).
- Permission boundaries: N/A.

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — `audit_log` lands at MVP3 (Observable) per [`CLAUDE.md`](../../../../CLAUDE.md) "Activates at MVP3". This change adds a rejection path to existing endpoints; it introduces no new persisted mutation. When `audit_log` lands, a rejected SSRF attempt is a candidate `system`-visibility event, but that is out of scope here.

## 7) Functional requirements

### FR-1: SSRF policy helper (pure classifier in domain + async orchestrator in service)

The work splits across two layers to respect the domain-purity rule (CLAUDE.md: "Domain layer — pure business logic, no I/O, no async"). DNS resolution is I/O, so it lives in the service layer; only the IP-range decision is pure domain logic.

- Requirement (domain, pure):
  - The system **MUST** provide a pure classifier `backend/app/domain/cluster/url_policy.py::is_blocked_address(ip: IPv4Address | IPv6Address) -> bool` returning `True` for `is_private | is_loopback | is_link_local | is_reserved | is_multicast | is_unspecified` or membership in `100.64.0.0/10` (CGNAT). It **MUST** unwrap IPv4-mapped IPv6 (`::ffff:a.b.c.d`) before classifying. No I/O, synchronous, unit-testable without fixtures.
  - The system **MUST** provide the metadata-hostname denylist constant and a pure `is_metadata_hostname(host: str) -> bool` (case-insensitive exact match) in the same module.
- Requirement (service, async orchestrator):
  - The system **MUST** provide `backend/app/services/cluster_url_policy.py::assert_base_url_allowed(base_url: str) -> None` (async) that, **only when `not get_settings().relyloop_allow_private_clusters`**:
    - parses the host from `base_url`;
    - raises `ClusterUrlBlocked` if `is_metadata_hostname(host)`;
    - if the host is a literal IP, classifies it directly via `is_blocked_address`;
    - else resolves the host via `asyncio.get_running_loop().getaddrinfo(host, port, type=SOCK_STREAM)` and runs `is_blocked_address` over **every** returned address;
    - raises `ClusterUrlBlocked` if any classified address is blocked.
  - The system **MUST** treat a DNS resolution failure (`socket.gaierror`) as "no SSRF hit" — return normally and let the downstream probe surface unreachability.
  - The system **MUST NOT** apply any policy (return immediately) when `relyloop_allow_private_clusters` is `True`.
- Notes: `ClusterUrlBlocked` is a new exception defined alongside the existing cluster service exceptions in `backend/app/services/cluster.py` (where `ClusterUnreachable`/`EngineTypeNotSupported`/`AuthKindNotSupported` live, lines 71-83).

### FR-2: Enforcement at registration and test-connection

- Requirement:
  - `register_cluster` **MUST** call the FR-1 helper before `_build_adapter_from_args` and propagate `ClusterUrlBlocked`.
  - `test_cluster_connection` **MUST** call the FR-1 helper before `_build_adapter_from_args`, in the same "validation that DOES raise" position as the engine/auth checks, and propagate `ClusterUrlBlocked`.
- Notes: enforcement precedes the network probe so a blocked URL is never contacted.

### FR-3: Error contract

- Requirement:
  - The `create_cluster` and `test_connection` routers **MUST** map `ClusterUrlBlocked` → `_err(400, "CLUSTER_URL_BLOCKED", <message>, False)`.
  - The message **MUST** name the offending host and state the policy, and **MUST NOT** contain credentials.
- Notes: `400` (client must change the URL), non-retryable, distinct from `503 CLUSTER_UNREACHABLE`.

### FR-4: Structural validator de-duplication

- Requirement:
  - The system **MUST** reduce the two `validate_base_url` field validators to one shared structural validator covering scheme ∈ {http, https} and host-present, both raising `ValueError` → `422 VALIDATION_ERROR`.
  - The literal-IP range decision **MUST** move out of the Pydantic validator into the FR-1 service helper (single policy site).
- Notes: preserves the existing `test_create_cluster_request_validates_scheme` contract exactly.

### FR-5: Metadata-hostname denylist

- Requirement:
  - The system **MUST** maintain a denylist constant (`metadata.google.internal`, `metadata`, case-insensitive exact host match) in `backend/app/domain/cluster/url_policy.py`, consumed by the FR-1 async orchestrator under the same flag gate.
- Notes: the AWS/Azure metadata IP `169.254.169.254` is already caught by `is_link_local`; the denylist covers the name-based GCP path that never resolves to a classifiable public IP from outside the VM.

### FR-6: Security documentation

- Requirement:
  - The system **MUST** add a `docs/04_security/` note describing the control, the flag gate, and the residual DNS-rebinding risk (with a pointer to `phase2_idea.md`).

## 8) API and data contract baseline

### 7.1 Endpoint surface

No new endpoints. Two existing endpoints gain one error path:

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `POST` | `/api/v1/clusters` | Register a cluster (probe → insert) | `CLUSTER_URL_BLOCKED` (400, **new**), `ENGINE_NOT_SUPPORTED` (400), `AUTH_KIND_NOT_SUPPORTED` (400), `CLUSTER_NAME_TAKEN` (409), `CLUSTER_UNREACHABLE` (503), `VALIDATION_ERROR` (422) |
| `POST` | `/api/v1/clusters/test-connection` | Diagnostic probe of unsaved form fields | `CLUSTER_URL_BLOCKED` (400, **new**), `ENGINE_NOT_SUPPORTED` (400), `AUTH_KIND_NOT_SUPPORTED` (400), `CREDENTIALS_INVALID` (400), `VALIDATION_ERROR` (422) |

### 7.2 Contract rules

- Error body MUST include machine-readable `error_code`.
- Status codes MUST be deterministic per scenario: policy block = `400` (non-retryable), unreachable = `503` (retryable), malformed scheme/host = `422`.
- N/A — no cross-tenant access (single-tenant).

### 7.3 Response examples

`CLUSTER_URL_BLOCKED` failure (HTTP 400) — applies to both endpoints:
```json
{
  "detail": {
    "error_code": "CLUSTER_URL_BLOCKED",
    "message": "base_url host 'metadata.google.internal' resolves to a blocked address range and RELYLOOP_ALLOW_PRIVATE_CLUSTERS is false",
    "retryable": false
  }
}
```

Scheme failure (HTTP 422, unchanged — Pydantic `RequestValidationError` envelope):
```json
{
  "detail": {
    "error_code": "VALIDATION_ERROR",
    "message": "base_url must use http or https scheme",
    "retryable": false
  }
}
```

Success (HTTP 201, `POST /clusters`) — unchanged `ClusterDetail` shape:
```json
{
  "id": "0192f8a0-...-uuidv7",
  "name": "prod-search",
  "engine_type": "elasticsearch",
  "environment": "prod",
  "base_url": "https://search.example.com:9200",
  "health": { "status": "green", "version": "8.13.0", "checked_at": "2026-06-09T19:30:00Z", "error": null }
}
```

Auth failure example: N/A — no auth surface.

### 7.4 Enumerated value contracts

| Field | Accepted values (exact) | Backend source of truth | Frontend call site(s) |
|---|---|---|---|
| error `error_code` (new) | `CLUSTER_URL_BLOCKED` | `backend/app/api/v1/clusters.py` (`_err(400, "CLUSTER_URL_BLOCKED", ...)`) + asserted in `backend/tests/contract/test_error_codes.py` | none — surfaced as a toast/inline message via the existing envelope renderer; no option list, no filter |

No new filters, sort keys, status badges, or dropdowns. The new code is a thrown error, not a selectable wire value.

### 7.5 Error code catalog

| Code | HTTP Status | Meaning |
|------|-------------|---------|
| `CLUSTER_URL_BLOCKED` | `400` | The `base_url` host is a blocked-range IP, resolves to one, or is a known cloud-metadata hostname, while `RELYLOOP_ALLOW_PRIVATE_CLUSTERS=False`. Non-retryable; the operator must change the URL (or, deliberately, flip the flag). |

## 9) Data model and state transitions

### New/changed entities

**None.** No new table, no column change, no migration. (`relyloop_allow_private_clusters` already exists at `settings.py:302`.)

### Required invariants

- A blocked `base_url` is never contacted: the FR-1 helper runs strictly before `_build_adapter_from_args` / `health_check()` in both service functions.
- The policy is a strict no-op when `relyloop_allow_private_clusters=True` (default).

### State transitions

N/A — no entity state machine touched. Registration flow gains a pre-probe rejection branch.

### Idempotency/replay behavior

N/A — synchronous request path, no events.

## 10) Security, privacy, and compliance

- **Threats:**
  1. **Cloud-metadata exfiltration** — `base_url=http://metadata.google.internal/...` or any name resolving to `169.254.169.254` → reads IAM/role credentials into RelyLoop's cached health/detail surfaces. *Control: FR-1 resolve-and-classify + FR-5 denylist (flag-gated).* 
  2. **Internal service port-scan / read-SSRF** — `base_url` pointing at `http://vault.internal`, `http://127.0.0.1:<port>`, etc. *Control: FR-1 classifies loopback/private/CGNAT resolved IPs.*
  3. **DNS rebinding** — host resolves benign at validation, internal at connect. *Residual (Phase 2); documented in `docs/04_security/`.*
- **Controls:** flag-gated (`RELYLOOP_ALLOW_PRIVATE_CLUSTERS=False`) async resolve-and-classify before any probe; expanded range set; metadata-hostname denylist; one shared helper (no drift).
- **Secrets/key handling:** the helper touches `base_url` only; rejection messages exclude credentials (Absolute Rule #10).
- **Auditability:** `audit_log` not yet present (MVP3); rejection is logged via the standard request log at WARN with the offending host (no secret).
- **Data retention/deletion/export impact:** none.

## 11) UX flows and edge cases

### Information architecture

No UI change. The create-cluster modal and the test-connection button already render the `_err` envelope's `message`. `CLUSTER_URL_BLOCKED` surfaces through that same path as an inline error / toast. N/A for navigation, labeling taxonomy, content hierarchy, progressive disclosure.

### Tooltips and contextual help

N/A — no new settings, indicators, or controls in the UI. (The `RELYLOOP_ALLOW_PRIVATE_CLUSTERS` flag is operator-environment config, not a UI element.)

### Primary flows

1. **Hardened register, blocked host:** operator (with `RELYLOOP_ALLOW_PRIVATE_CLUSTERS=False`) submits `base_url=http://metadata.google.internal/` → `400 CLUSTER_URL_BLOCKED`, no probe issued.
2. **Hardened register, legit host:** `base_url=https://search.example.com:9200` resolves to a public IP → policy passes → normal probe → `201`.
3. **Default register (flag True):** `base_url=http://elasticsearch:9200` → policy is a no-op → normal probe (unchanged local-dev behavior).

### Edge/error flows

- **Unresolvable host (flag False):** `getaddrinfo` raises `gaierror` → helper returns normally → probe runs → `503 CLUSTER_UNREACHABLE` (unchanged path).
- **Literal blocked IP (flag False):** `base_url=http://10.0.0.1:9200` → `400 CLUSTER_URL_BLOCKED` (now via the service helper, not the validator).
- **Mixed resolution (flag False):** host resolves to one public + one private IP → **blocked** (any blocked address in the set fails the URL — fail-safe).
- **IPv4-mapped IPv6 (flag False):** `::ffff:127.0.0.1` → unwrapped and classified as loopback → blocked.
- **Malformed scheme/host:** `422 VALIDATION_ERROR` from the structural validator (unchanged).

## 12) Given/When/Then acceptance criteria

### AC-1: Metadata hostname blocked in hardened mode
- Given `RELYLOOP_ALLOW_PRIVATE_CLUSTERS=False`
- When `POST /api/v1/clusters` with `base_url="http://metadata.google.internal/"`
- Then response is `400` with `error_code="CLUSTER_URL_BLOCKED"`, `retryable=false`, and **no** outbound probe is made.

### AC-2: Hostname resolving to a private IP blocked in hardened mode
- Given `RELYLOOP_ALLOW_PRIVATE_CLUSTERS=False` and a test stub where `getaddrinfo("internal.test", ...)` returns `10.1.2.3`
- When `POST /api/v1/clusters/test-connection` with `base_url="http://internal.test:9200"`
- Then response is `400 CLUSTER_URL_BLOCKED` (raised before the probe).
- Example values: resolver stub → `[(AF_INET, ..., ('10.1.2.3', 9200))]`; expected status `400`.

### AC-3: Public hostname allowed in hardened mode
- Given `RELYLOOP_ALLOW_PRIVATE_CLUSTERS=False` and a stub where `getaddrinfo("search.example.com", ...)` returns `93.184.216.34`
- When the URL policy helper runs for `base_url="https://search.example.com:9200"`
- Then it returns normally (no exception) and control proceeds to the probe.

### AC-4: Policy is a no-op when private clusters are allowed
- Given `RELYLOOP_ALLOW_PRIVATE_CLUSTERS=True` (default)
- When `POST /api/v1/clusters` with `base_url="http://elasticsearch:9200"` (resolves to a Docker-internal private IP)
- Then the helper applies no policy; the request proceeds to the normal probe exactly as today (no `CLUSTER_URL_BLOCKED`).

### AC-5: Literal blocked IP rejected via the service helper
- Given `RELYLOOP_ALLOW_PRIVATE_CLUSTERS=False`
- When `base_url="http://127.0.0.1:9200"` is submitted to either endpoint
- Then `400 CLUSTER_URL_BLOCKED` (no DNS resolution needed; literal classification).

### AC-6: Expanded range coverage
- Given `RELYLOOP_ALLOW_PRIVATE_CLUSTERS=False`
- When the helper classifies each of `169.254.169.254` (link-local), `100.64.0.1` (CGNAT), `0.0.0.0` (unspecified), `224.0.0.1` (multicast), `::ffff:10.0.0.1` (mapped private)
- Then every one is classified blocked.

### AC-7: Unresolvable host falls through to the probe
- Given `RELYLOOP_ALLOW_PRIVATE_CLUSTERS=False` and a stub where `getaddrinfo` raises `socket.gaierror`
- When the helper runs for `base_url="http://does-not-resolve.invalid:9200"`
- Then it returns normally (no `CLUSTER_URL_BLOCKED`); the downstream probe yields `503 CLUSTER_UNREACHABLE`.

### AC-8: Scheme validation unchanged
- Given any flag value
- When `CreateClusterRequest(base_url="ftp://x:9200", ...)` is constructed
- Then a Pydantic `ValidationError` matching `"http or https"` is raised (existing contract preserved).

## 13) Non-functional requirements

- **Performance:** one `getaddrinfo` per registration / test-connection call when the flag is False and the host is non-literal; bounded by a resolver timeout (reuse the system resolver; no per-request DNS amplification). Zero added latency when the flag is True (default) or the host is a literal IP. Not on the hot health-probe loop — the gate runs only at register/test time.
- **Reliability:** resolution failure is non-fatal (falls through). No new external dependency.
- **Operability:** a blocked attempt logs one WARN line with the offending host (no secret) for operator visibility.
- **Accessibility/usability:** N/A (no UI).

## 14) Test strategy requirements (spec-level)

- **Unit (`backend/tests/unit/`):** the pure classifier (`backend/tests/unit/domain/test_cluster_url_policy.py`) — each blocked range in AC-6, public IP pass, IPv4-mapped unwrap, metadata-hostname denylist. The async orchestrator (`backend/tests/unit/services/test_cluster_url_policy.py`) — resolved-private (stub `getaddrinfo`), resolved-public, mixed resolution → block, literal-IP no-resolution path, `gaierror` → pass-through, flag-True → no-op. Structural validator: scheme + host-present.
- **Integration (`backend/tests/integration/`):** `register_cluster` and `test_cluster_connection` with `relyloop_allow_private_clusters=False` and a monkeypatched resolver — assert `ClusterUrlBlocked` raised before any adapter build / probe (assert the probe stub is never called); assert flag-True path proceeds to probe.
- **Contract (`backend/tests/contract/`):** `POST /clusters` and `POST /clusters/test-connection` return `400 CLUSTER_URL_BLOCKED` envelope shape (extend `test_clusters_api_contract.py` + register the code in `test_error_codes.py`); scheme test unchanged.
- **E2E (`ui/tests/e2e/`):** none — no UI behavior change; the error rides the existing envelope renderer.

## 15) Documentation update requirements

- `docs/01_architecture`: `cluster-lifecycle.md` — note the pre-probe URL policy gate and the `CLUSTER_URL_BLOCKED` code in the registration flow.
- `docs/02_product`: none.
- `docs/03_runbooks`: optional one-liner in the cluster-registration runbook (if present) on the new 400.
- `docs/04_security`: **new note** (FR-6) — the SSRF control, the `RELYLOOP_ALLOW_PRIVATE_CLUSTERS` gate, blocked ranges, metadata denylist, and the residual DNS-rebinding risk (→ Phase 2).
- `docs/05_quality`: none.

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** governed by the existing `RELYLOOP_ALLOW_PRIVATE_CLUSTERS` setting (default `True` → no behavior change on merge). The new policy activates only where an operator has already opted into the hardened posture.
- **Migration/backfill:** none (no schema change).
- **Operational readiness gates:** the `docs/04_security/` note merged; CI green.
- **Release gate:** unit + integration + contract layers green; `make lint` + `make typecheck` clean; the new code registered in `test_error_codes.py`.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 | AC-1, AC-2, AC-3, AC-6, AC-7 | pure classifier (domain) + async orchestrator (service) | `backend/tests/unit/domain/test_cluster_url_policy.py`, `backend/tests/unit/services/test_cluster_url_policy.py` | `docs/04_security/*` |
| FR-2 | AC-1, AC-2, AC-4, AC-5 | wire into `register_cluster` + `test_cluster_connection` + `ClusterUrlBlocked` exception | `backend/tests/integration/test_cluster_url_ssrf.py` | `docs/01_architecture/cluster-lifecycle.md` |
| FR-3 | AC-1, AC-2, AC-5 | router exception mapping | `backend/tests/contract/test_clusters_api_contract.py`, `test_error_codes.py` | — |
| FR-4 | AC-8 | de-dupe validators (structural only) | `backend/tests/contract/test_clusters_api_contract.py` | — |
| FR-5 | AC-1 | denylist constant (domain module) | `backend/tests/unit/domain/test_cluster_url_policy.py` | `docs/04_security/*` |
| FR-6 | — | security doc | — | `docs/04_security/*` |

## 18) Definition of feature done

- [ ] All acceptance criteria (AC-1…AC-8) pass in CI.
- [ ] Unit / integration / contract layers green (no E2E required).
- [ ] `docs/04_security/` note + `cluster-lifecycle.md` update merged.
- [ ] `CLUSTER_URL_BLOCKED` registered in `test_error_codes.py`.
- [ ] `phase2_idea.md` (connect-time IP pinning) filed.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

None — all forks resolved below (locked at recommended defaults per `--auto`).

### Decision log

- **2026-06-09 — D-1: Consolidate the literal-IP rejection into the service-layer policy helper (one `400 CLUSTER_URL_BLOCKED`), rather than keeping literal-IPs at `422` in the Pydantic validator and only adding hostnames at the service layer.** Rationale: one error code for "this URL is not allowed" is a cleaner operator contract than a 422/400 split keyed on whether the host happened to be a literal IP; no contract test asserts the literal-IP 422 path (only scheme), and the flag defaults `True` so the change is a no-op in the shipped default. Considered alternative (keep validator literal-IP at 422, add service hostname-check at 400) rejected for the dual-status-code inconsistency.
- **2026-06-09 — D-2: Gate the entire policy (including the metadata-hostname denylist) on `not relyloop_allow_private_clusters`.** Rationale: matches the existing flag's single, well-understood meaning ("allow internal hosts"); avoids surprising the default laptop operator who points at Docker-internal hostnames. Considered alternative (unconditional metadata denylist even when private clusters are allowed) rejected to keep one coherent gate — a hardened deployment is exactly where metadata protection is wanted, and that posture sets the flag False.
- **2026-06-09 — D-3: DNS resolution failure is non-fatal (fall through to the normal probe), not fail-closed.** Rationale: an unresolvable name is not an SSRF target; the existing `503 CLUSTER_UNREACHABLE` path already covers it; fail-closed would add friction for transient DNS blips.
- **2026-06-09 — D-4: Connect-time IP pinning (DNS-rebinding defense) is deferred to Phase 2.** Rationale: it requires threading a resolved IP through the engine adapters' httpx construction (Host/SNI handling) — materially larger and engine-touching — whereas the registration-time gate closes the standing unconditional bypass on its own.
- **2026-06-09 — D-5: Async resolution via `asyncio.get_running_loop().getaddrinfo`.** Rationale: non-blocking on the event loop; avoids the synchronous-`socket`-in-async-handler anti-pattern Gemini flagged on the idea.
- **2026-06-09 — D-6 (Opus self-review Pass 2 finding): split the helper across layers to respect domain purity.** The first draft placed the async DNS helper in `domain/cluster/`, violating CLAUDE.md's "domain layer = no I/O, no async" rule. Corrected: pure IP/hostname classification → `backend/app/domain/cluster/url_policy.py` (domain); async resolve-and-orchestrate → `backend/app/services/cluster_url_policy.py` (service); `ClusterUrlBlocked` exception → `backend/app/services/cluster.py` alongside the existing cluster exceptions.
- **2026-06-09 — Cross-model review: Opus self-review (GPT-5.5 unreachable in the Claude Code remote sandbox).** Gemini Code Assist remains the live cross-family gate at the code/PR stage.
