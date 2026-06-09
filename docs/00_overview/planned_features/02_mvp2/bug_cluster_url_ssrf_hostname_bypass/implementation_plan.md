# Implementation Plan — Cluster base_url SSRF guard (hostname-aware)

**Date:** 2026-06-09
**Status:** Ready for Execution
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy source(s):** CLAUDE.md Absolute Rules #4 (engine-adapter boundary), #10 (never log secrets); `docs/01_architecture/cluster-lifecycle.md`

---

## 0) Planning principles

- Spec traceability first: every story maps to FR IDs.
- Backend-only; no migration, no UI, no new third-party dependency.
- Fail-loud tests: assert explicit status/shape/error codes; assert the probe is **not** called on a blocked URL.
- Default posture is a strict no-op: with `relyloop_allow_private_clusters=True` (shipped default), behavior is unchanged.
- Keep the policy on one code path (one classifier, one orchestrator) so the two endpoints cannot drift.

## 1) Scope traceability (FR → epics/phases)

| FR ID | Epic/Story | Notes |
|---|---|---|
| FR-1 (classifier + orchestrator) | Story 1.1 (pure classifier) + 1.2 (async orchestrator) | Split across domain/service per spec D-6 |
| FR-2 (enforcement at register + test-connection) | Story 1.2 | Call before `_build_adapter_from_args` |
| FR-3 (error contract `CLUSTER_URL_BLOCKED` 400) | Story 1.2 | Router mapping on both endpoints |
| FR-4 (validator de-dup, structural only) | Story 1.2 | One shared scheme+host validator in `schemas.py` |
| FR-5 (metadata-hostname denylist) | Story 1.1 | Constant + `is_metadata_hostname` in the domain module |
| FR-6 (security doc) | Story 1.3 | `docs/04_security/` note + `cluster-lifecycle.md` |

All Phase-1 FRs covered. Phase 2 (connect-time IP pinning) is deferred and tracked in [`phase2_idea.md`](phase2_idea.md) (verified present).

## 2) Delivery structure

Structure: **Epic → Story → Tasks → DoD**. No frontend scope.

### Conventions (project-specific)

```
- Domain layer is pure: no I/O, no async, no DB (CLAUDE.md). The IP/hostname classifier lives here.
- Service layer is async; DNS resolution (I/O) lives here, never in the Pydantic validator.
- Routers map service exceptions to the _err(status, code, message, retryable) envelope.
- Settings read via get_settings() (lru_cached); never instantiate Settings() directly.
- All __init__.py exports updated via __all__ where the package uses one.
- Never log secrets — the policy touches base_url (host/scheme) only.
```

### AI Agent Execution Protocol

0. Load `architecture.md` + `state.md` first.
1. Story 1.1 (pure domain classifier + unit tests) → run `make test-unit`.
2. Story 1.2 (service orchestrator + exception + wiring + validator de-dup + router + integration/contract tests) → run unit + integration + contract.
3. Story 1.3 (docs).
4. No migration round-trip (no schema change). No E2E (no UI change).
5. `make lint` + `make typecheck` green before push.

---

## Epic 1 — Hostname-aware SSRF guard for cluster base_url

### Story 1.1 — Pure IP/hostname classifier (domain)

**Outcome:** A pure, synchronous, I/O-free module that decides whether an IP is in a blocked range and whether a hostname is a known cloud-metadata name.

**New files**

| File | Purpose |
|---|---|
| `backend/app/domain/cluster/__init__.py` | New `domain/cluster` package marker (verify it doesn't already exist — it does not). |
| `backend/app/domain/cluster/url_policy.py` | `is_blocked_address(ip)`, `is_metadata_hostname(host)`, `METADATA_HOSTNAMES` constant, `BLOCKED_EXTRA_NETWORKS` (`100.64.0.0/10`). Pure, no I/O. |

**Modified files**

| File | Change |
|---|---|
| (none) | — |

**Key interfaces**

```python
# backend/app/domain/cluster/url_policy.py
from ipaddress import IPv4Address, IPv6Address, IPv4Network

METADATA_HOSTNAMES: frozenset[str]  # {"metadata.google.internal", "metadata"}
_CGNAT: IPv4Network                 # ip_network("100.64.0.0/10")

def is_blocked_address(ip: IPv4Address | IPv6Address) -> bool: ...
    # True if is_private | is_loopback | is_link_local | is_reserved |
    # is_multicast | is_unspecified, OR (after unwrapping IPv4-mapped IPv6)
    # the v4 address is in 100.64.0.0/10. Pure.

def is_metadata_hostname(host: str) -> bool: ...
    # case-insensitive exact match against METADATA_HOSTNAMES. Pure.
```

**Tasks**
1. Create `backend/app/domain/cluster/__init__.py` (empty package marker).
2. Implement `is_blocked_address` with IPv4-mapped-IPv6 unwrap (`ip.ipv4_mapped` → classify the v4) before the boolean OR over the `ipaddress` flags + CGNAT membership.
3. Implement `METADATA_HOSTNAMES` + `is_metadata_hostname` (lowercase exact match).
4. Unit tests in `backend/tests/unit/domain/test_cluster_url_policy.py`.

**Definition of Done**
- `is_blocked_address` returns True for `127.0.0.1`, `10.0.0.1`, `192.168.1.1`, `169.254.169.254`, `100.64.0.1`, `0.0.0.0`, `224.0.0.1`, `fe80::1`, `::1`, `::ffff:10.0.0.1`; returns False for `93.184.216.34`, `8.8.8.8`, `2606:4700:4700::1111`. (unit) — AC-6.
- `is_metadata_hostname("metadata.google.internal")` / `"METADATA"` → True; `"search.example.com"` → False. (unit) — AC-1.
- Module imports cleanly under `make typecheck` (mypy strict); no I/O imports (`socket`, `asyncio`) in this file.

### Story 1.2 — Async policy orchestrator + enforcement + error contract + validator de-dup

**Outcome:** Registering or test-connecting a cluster with a `base_url` that (literally is / resolves to / is named as) an internal-or-metadata target is rejected with `400 CLUSTER_URL_BLOCKED` before any network probe — but only when `relyloop_allow_private_clusters=False`.

**New files**

| File | Purpose |
|---|---|
| `backend/app/services/cluster_url_policy.py` | `assert_base_url_allowed(base_url: str) -> None` (async): flag gate → metadata-host check → literal-IP classify OR async `getaddrinfo` + classify every resolved address; raises `ClusterUrlBlocked`. `gaierror` → return (no SSRF hit). |

**Modified files**

| File | Change |
|---|---|
| `backend/app/services/cluster.py` | Add `class ClusterUrlBlocked(Exception)` alongside `ClusterUnreachable`/`EngineTypeNotSupported`/`AuthKindNotSupported` (lines 71-83). Call `await assert_base_url_allowed(base_url)` in `register_cluster` (before `_build_adapter_from_args`, line ~147) and in `test_cluster_connection` (before `_build_adapter_from_args`, line ~293). |
| `backend/app/api/v1/clusters.py` | Import `ClusterUrlBlocked`; in `create_cluster` (line 250-271) and `test_connection` (line 187-202) add `except ClusterUrlBlocked as exc: raise _err(400, "CLUSTER_URL_BLOCKED", str(exc), False) from exc`. |
| `backend/app/api/v1/schemas.py` | Replace the two duplicated `validate_base_url` validators (lines 117-143, 162-180) with calls to one shared structural helper checking scheme∈{http,https} + host-present only (raises `ValueError` → 422). Remove the literal-IP `is_private/is_loopback` block from the validators (moved to the service policy). Drop the now-unused `ip_address`/`get_settings` imports if no longer referenced. |

**Endpoints**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `POST` | `/api/v1/clusters` | `CreateClusterRequest` (unchanged) | `201 ClusterDetail` (unchanged) | **`CLUSTER_URL_BLOCKED` (400, new)**, `ENGINE_NOT_SUPPORTED` (400), `AUTH_KIND_NOT_SUPPORTED` (400), `CLUSTER_NAME_TAKEN` (409), `CLUSTER_UNREACHABLE` (503), `VALIDATION_ERROR` (422) |
| `POST` | `/api/v1/clusters/test-connection` | `ConnectionTestRequest` (unchanged) | `200 ConnectionTestResult` (unchanged) | **`CLUSTER_URL_BLOCKED` (400, new)**, `ENGINE_NOT_SUPPORTED` (400), `AUTH_KIND_NOT_SUPPORTED` (400), `CREDENTIALS_INVALID` (400), `VALIDATION_ERROR` (422) |

**Key interfaces**

```python
# backend/app/services/cluster_url_policy.py
async def assert_base_url_allowed(base_url: str) -> None: ...
    # No-op when get_settings().relyloop_allow_private_clusters is True.
    # Else: raise ClusterUrlBlocked if is_metadata_hostname(host); if host is a
    # literal IP, classify directly; else getaddrinfo(host, port) via
    # asyncio.get_running_loop() and raise if any resolved addr is_blocked_address.
    # socket.gaierror -> return (unresolvable is not an SSRF hit).

# backend/app/services/cluster.py
class ClusterUrlBlocked(Exception): ...  # -> 400 CLUSTER_URL_BLOCKED at router
```

**Pydantic schemas**: no field changes. The shared structural validator is internal to `schemas.py`:

```python
def _validate_base_url_structure(v: str) -> str:
    parsed = urlparse(v)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("base_url must use http or https scheme")
    if not parsed.hostname:
        raise ValueError("base_url must include a host")
    return v
```

**Tasks**
1. Add `ClusterUrlBlocked` exception to `services/cluster.py`.
2. Implement `services/cluster_url_policy.py::assert_base_url_allowed` (flag gate, metadata check, literal-vs-resolve branch, `gaierror` fall-through, `asyncio.get_running_loop().getaddrinfo`).
3. Call it in `register_cluster` (before adapter build) and `test_cluster_connection` (before adapter build), in the "validation that DOES raise" position.
4. Map `ClusterUrlBlocked` → `_err(400, "CLUSTER_URL_BLOCKED", ...)` in both routers; add the import.
5. Collapse the two `validate_base_url` validators into the shared structural helper; delete the literal-IP policy from the validator; prune unused imports.
6. Register `CLUSTER_URL_BLOCKED` in `backend/tests/contract/test_error_codes.py` (the code catalog comment + any assertion list).
7. Integration tests (`backend/tests/integration/test_cluster_url_ssrf.py`) + contract tests (extend `test_clusters_api_contract.py`) + service unit tests (`backend/tests/unit/services/test_cluster_url_policy.py`).

**Definition of Done**
- `relyloop_allow_private_clusters=False` + `base_url="http://metadata.google.internal/"` → `POST /clusters` returns `400 CLUSTER_URL_BLOCKED`, `retryable=false`, and the adapter probe is **never** called (assert via a spy/monkeypatch that `health_check` is not invoked). (integration + contract) — AC-1.
- Stubbed `getaddrinfo("internal.test")→10.1.2.3` + flag False → `POST /clusters/test-connection` returns `400 CLUSTER_URL_BLOCKED` before the probe. (integration) — AC-2.
- Stubbed `getaddrinfo("search.example.com")→93.184.216.34` + flag False → `assert_base_url_allowed` returns normally. (unit) — AC-3.
- Flag True (default) + `base_url="http://elasticsearch:9200"` → no policy applied; control reaches the probe exactly as before. (integration) — AC-4.
- Flag False + literal `http://127.0.0.1:9200` → `400 CLUSTER_URL_BLOCKED` with no DNS resolution attempted. (integration) — AC-5.
- Flag False + stub `getaddrinfo` raising `socket.gaierror` → `assert_base_url_allowed` returns normally; downstream yields `503 CLUSTER_UNREACHABLE`. (unit + integration) — AC-7.
- `CreateClusterRequest(base_url="ftp://x:9200")` still raises Pydantic `ValidationError` matching `"http or https"`. (contract — existing test unchanged) — AC-8.
- `CLUSTER_URL_BLOCKED` present in `test_error_codes.py`; `make lint` + `make typecheck` green.

### Story 1.3 — Security + architecture documentation

**Outcome:** The SSRF control, its flag gate, blocked ranges, metadata denylist, and the residual DNS-rebinding risk are documented.

**New files**

| File | Purpose |
|---|---|
| `docs/04_security/cluster-url-ssrf.md` | The control: flag gate, blocked-range set, metadata denylist, the `CLUSTER_URL_BLOCKED` 400, and the residual DNS-rebinding risk → pointer to `phase2_idea.md`. |

**Modified files**

| File | Change |
|---|---|
| `docs/04_security/README.md` | Add a row for the new note in the contents table. |
| `docs/01_architecture/cluster-lifecycle.md` | Note the pre-probe URL-policy gate + `CLUSTER_URL_BLOCKED` in the registration flow. |

**Tasks**
1. Write `docs/04_security/cluster-url-ssrf.md`.
2. Add the README contents-table row.
3. Add the cluster-lifecycle.md note.

**Definition of Done**
- The note states the `RELYLOOP_ALLOW_PRIVATE_CLUSTERS` gate, the blocked ranges, the metadata denylist, and the residual rebinding risk with a `phase2_idea.md` pointer.
- `docs/04_security/README.md` contents table includes the new note.

---

## 3) Testing workstream

### 3.1 Unit tests
- Location: `backend/tests/unit/`
- Tasks:
  - [ ] `backend/tests/unit/domain/test_cluster_url_policy.py` — `is_blocked_address` over every AC-6 range + public-pass + IPv4-mapped unwrap; `is_metadata_hostname` true/false. (Story 1.1)
  - [ ] `backend/tests/unit/services/test_cluster_url_policy.py` — flag-True no-op; metadata-host raise; literal-IP raise (no resolution); resolved-private raise; resolved-public pass; mixed-resolution raise; `gaierror` pass-through. Monkeypatch `asyncio` loop `getaddrinfo`. (Story 1.2)
- DoD: every classifier branch + every orchestrator branch deterministic; the load-bearing assertions verified (mutate a flag check → a test fails).

### 3.2 Integration tests
- Location: `backend/tests/integration/`
- Tasks:
  - [ ] `backend/tests/integration/test_cluster_url_ssrf.py` — drive `register_cluster` + `test_cluster_connection` with `relyloop_allow_private_clusters=False` and a monkeypatched resolver + a spy on `_build_adapter_from_args`/`health_check`; assert `ClusterUrlBlocked` raised before any adapter build (probe spy never called) for metadata-host, resolved-private, literal-loopback; assert flag-True path reaches the probe. (Story 1.2)
- DoD: blocked-before-probe proven (spy assert); flag-True no-op proven.

### 3.3 Contract tests
- Location: `backend/tests/contract/`
- Tasks:
  - [ ] Extend `backend/tests/contract/test_clusters_api_contract.py` — `POST /clusters` + `POST /clusters/test-connection` with flag False + a blocked URL → `400` envelope `{error_code: "CLUSTER_URL_BLOCKED", message, retryable: false}`. Keep `test_create_cluster_request_validates_scheme` unchanged. (Story 1.2)
  - [ ] Register `CLUSTER_URL_BLOCKED` in `backend/tests/contract/test_error_codes.py`. (Story 1.2)
- DoD: the new code has contract coverage on both endpoints; envelope shape asserted.

### 3.4 E2E tests
- **None.** No UI behavior change — the new error code rides the existing `_err` envelope renderer. Stated explicitly per template.

### 3.5 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `backend/tests/contract/test_clusters_api_contract.py` | `test_create_cluster_request_validates_scheme` (`ftp://` → ValidationError) | 1 | **No change** — scheme stays in the structural validator. |
| `backend/tests/contract/test_clusters_api_contract.py` | `_make_cluster_request` (`base_url="http://elasticsearch:9200"`) | 1 | **No change** — only blocked when flag False; default fixture posture (True) leaves it valid. |
| `backend/tests/**` | literal-IP private-range 422 assertion | 0 | None exist (verified by grep) — moving the IP policy to the service breaks no test. |

### 3.5 Migration verification
- N/A — no schema change.

### 3.6 CI gates
- [ ] `make test-unit`
- [ ] `make test-integration`
- [ ] `make test-contract`
- [ ] `make lint` && `make typecheck`

---

## 4) Documentation update workstream

### 4.0 Core context files
- **`state.md`** — [x] update at finalization: note the SSRF guard shipped (new merge one-liner), no Alembic head move.
- **`architecture.md`** — [ ] no new layer/flow worth a pointer (a new `domain/cluster/` + `services/cluster_url_policy.py` is minor; mention only if the invariants list warrants it). Likely no change.
- **`CLAUDE.md`** — [ ] no new convention/env var (reuses `RELYLOOP_ALLOW_PRIVATE_CLUSTERS`). No change.

### 4.4 Security docs (`docs/04_security`)
- [ ] New `cluster-url-ssrf.md` note (Story 1.3) + README contents row.

### 4.1 Architecture docs
- [ ] `cluster-lifecycle.md` pre-probe URL-policy note (Story 1.3).

**Documentation DoD**
- `docs/04_security/` + `cluster-lifecycle.md` consistent with shipped behavior.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals
- Eliminate the duplicated `validate_base_url` across `CreateClusterRequest` + `ConnectionTestRequest` (the drift source).
- Centralize the SSRF policy on one classifier + one orchestrator.

### 5.2 Planned refactor tasks
- [ ] Collapse the two validators into `_validate_base_url_structure` (Story 1.2).
- [ ] Remove the literal-IP policy from the Pydantic layer (moved to the service).

### 5.3 Refactor guardrails
- [ ] Scheme-validation contract test stays green (behavioral parity for the structural part).
- [ ] Lint/typecheck green.
- [ ] No product-scope expansion.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `ipaddress` + `asyncio` stdlib | Story 1.1/1.2 | implemented | none |
| `relyloop_allow_private_clusters` setting | Story 1.2 | implemented (`settings.py:302`) | none |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| DNS resolution adds latency to register/test | L | L | Only on flag-False + non-literal host; bounded by system resolver; not on the health-probe hot loop. |
| Over-blocking a legitimate cluster in hardened mode (host resolves to a private IP intentionally) | L | M | Operator sets `relyloop_allow_private_clusters=True` deliberately (the documented opt-in); error message names the host + policy. |
| Test flakiness from real DNS | M | M | Monkeypatch `getaddrinfo` in unit/integration tests — never hit real DNS. |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| Unresolvable host (flag False) | `getaddrinfo` → `gaierror` | Policy returns (no SSRF hit); probe runs → `503 CLUSTER_UNREACHABLE` | operator fixes DNS/URL |
| Mixed public+private resolution (flag False) | host resolves to ≥1 blocked addr | `400 CLUSTER_URL_BLOCKED` (fail-safe; any blocked addr fails the URL) | operator changes URL |
| Resolver hang | slow/blackholed DNS | bounded by the event-loop resolver default; not unbounded | n/a (Phase-1 acceptable; pinning is Phase 2) |

## 7) Sequencing and parallelization

### Suggested sequence
1. Story 1.1 (pure classifier — no dependencies).
2. Story 1.2 (orchestrator + wiring + validator + router + tests — depends on 1.1).
3. Story 1.3 (docs — depends on 1.2's final shape).

### Parallelization
- Story 1.1 and the Story 1.3 doc skeleton can draft in parallel; 1.2 needs 1.1.

## 8) Rollout and cutover plan

- Rollout: ships dormant — default `relyloop_allow_private_clusters=True` ⇒ zero behavior change on merge. Activates only where an operator already set the flag False (hardened posture).
- Feature flag: the existing setting; no new flag.
- Migration/cutover: none.

## 9) Execution tracker

### Current sprint
- [ ] Story 1.1 — pure classifier + unit tests
- [ ] Story 1.2 — orchestrator + exception + wiring + validator de-dup + router + integration/contract tests + error-code registration
- [ ] Story 1.3 — security + architecture docs

### Blocked items
- (none)

### Done this sprint
- (none yet)

## 10) Story-by-Story Verification Gate

- [ ] Files created/modified match story scope.
- [ ] `CLUSTER_URL_BLOCKED` implemented exactly (400, non-retryable, both endpoints).
- [ ] `assert_base_url_allowed` + `is_blocked_address` signatures as specified.
- [ ] Tests at unit + integration + contract layers (no E2E needed).
- [ ] Commands passed: `make test-unit`, `make test-integration`, `make test-contract`, `make lint`, `make typecheck`.
- [ ] No migration (no schema change).
- [ ] `docs/04_security/` + `cluster-lifecycle.md` updated in the same PR.

## 11) Plan consistency review

1. **Spec ↔ plan endpoint count:** spec §7.1 lists 2 endpoints (both pre-existing); plan covers both in Story 1.2. ✓
2. **Spec ↔ plan error code coverage:** spec §7.5 introduces 1 code (`CLUSTER_URL_BLOCKED`); plan covers it in Story 1.2 contract tasks + `test_error_codes.py`. ✓
3. **Spec ↔ plan FR coverage:** FR-1…FR-6 all mapped in §1. ✓
4. **Story internal consistency:** new files unique per story (`url_policy.py`→1.1, `cluster_url_policy.py`→1.2, doc→1.3); modified files (`cluster.py`, `clusters.py`, `schemas.py`) verified to exist. ✓
5. **Test file count:** 2 unit + 1 integration + extended contract + `test_error_codes.py` — all assigned to a story. ✓
6. **Gate arithmetic:** no multi-endpoint gate claim. ✓
7. **Open questions resolved:** spec §19 — none open (D-1…D-6 locked). ✓
8. **Frontend UI Guidance:** N/A — no frontend scope (stated). 
9. **Legacy behavior parity:** N/A — no user-facing component >100 LOC deleted/migrated. 
10. **Plan ↔ codebase verification:** `register_cluster` adapter-build at `cluster.py:147-160`; `test_cluster_connection` at `cluster.py:293-306`; router exception-map blocks at `clusters.py:195-202` + `264-271`; cluster exceptions at `cluster.py:71-83`; validators at `schemas.py:117-143`/`162-180`; `_err` at `_errors.py:19`; `relyloop_allow_private_clusters` at `settings.py:302`. All verified this session. ✓
11. **Enumerated value contract audit:** no new filter/dropdown/badge; the new code is a thrown error, not a selectable wire value. §7.4 covers it. ✓
13. **Audit-event coverage:** `audit_log` not present (lands MVP3); no new persisted mutation (a rejection path on existing endpoints). Justified N/A. ✓

---

## 12) Definition of plan done

- [x] Every FR (1-6) mapped to stories/tasks/tests/docs.
- [x] Every story includes New/Modified files, (Endpoints where applicable), Key interfaces, Tasks, DoD.
- [x] Test layers scoped (unit/integration/contract; E2E N/A with reason).
- [x] Documentation updates planned (docs/04_security + docs/01_architecture).
- [x] Lean refactor (validator de-dup) scoped with guardrails.
- [x] Gates measurable.
- [x] Story-by-Story Verification Gate included.
- [x] Plan consistency review performed — no unresolved findings.

**Cross-model review:** Opus self-review (GPT-5.5 unreachable in the Claude Code remote sandbox). Gemini Code Assist remains the live cross-family gate at the code/PR stage.
