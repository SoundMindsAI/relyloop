# Implementation Plan — Workspace Health Alerts

**Date:** 2026-03-05
**Status:** Ready for Execution
**Primary spec:** `example_feature-spec_workspace_health_alerts.md`

---

## 0) Planning principles

- Every story maps to FR IDs.
- Tests are fail-loud and deterministic.
- Keep repository-layer/service-layer/API-layer patterns consistent.

## 1) Scope traceability (FR → epics)

| FR ID | Epic | Notes |
|---|---|---|
| FR-1 | Epic 1 | alert generation + lifecycle |
| FR-2 | Epic 2 | tenant API + authorization |
| FR-3 | Epic 3 | UI discoverability |

## 2) Delivery structure

Conventions carried from existing codebase:
- All repo functions take `db: Session` as first arg; use `db.flush()` (caller commits)
- Services are async; create `job_run` at start where applicable
- Domain layer is pure — no DB access, no side effects
- Models use `Mapped[]` typed columns, `String(36)` UUIDs, `Base` from `backend/app/db/models/base.py`
- Routers return typed Pydantic response models; errors use `HTTPException` with structured detail
- All `__init__.py` exports updated via `__all__`

### AI Agent Execution Protocol (applies to every story)

1. **Read scope**: verify story outcome + endpoints + interfaces + DoD.
2. **Implement backend first**: models → migration → repo → domain → service → router → schemas.
3. **Run backend tests** (minimum: unit + integration + contract subset for touched endpoints).
4. **Implement frontend** (if story includes UI scope).
5. **Run E2E scope** for touched UX paths.
6. **Update docs/checklists** impacted by behavior changes in same PR.
7. **Verify migration round-trip** if schema changed.
8. **Attach evidence** in PR description: commands run, pass/fail, and files changed.

---

## Epic 1 — Alert generation and lifecycle

### Story 1.1 — Trigger rule engine
**Outcome:** deterministic creation of health alerts from auth/billing signals.

**New files**

| File | Purpose |
|---|---|
| `backend/app/db/models/tenant_health_alert.py` | `TenantHealthAlert` model: `id` (UUID PK), `tenant_id` (FK indexed), `type` (enum: `AUTH_LOCKOUT_SPIKE`, `INACTIVITY`, `BILLING_RISK`), `severity` (enum: `low`, `medium`, `high`), `status` (enum: `open`, `acknowledged`, `resolved`), `details_json` (JSON nullable), `idempotency_key` (unique — `tenant_id:type:window`), `created_at`, `acknowledged_at` (nullable), `resolved_at` (nullable) |
| `backend/app/db/models/tenant_health_alert_event.py` | `TenantHealthAlertEvent` model: `id` (UUID PK), `alert_id` (FK), `event_type` (enum: `created`, `acknowledged`, `resolved`), `actor_user_id` (nullable), `reason` (nullable), `created_at` |
| `backend/app/db/repo/health_alert_repo.py` | `create_alert()`, `get_alert()`, `get_alert_or_404()`, `list_alerts_for_tenant()`, `alert_exists_for_window()` |
| `backend/app/db/repo/health_alert_event_repo.py` | `create_event()`, `list_events_for_alert()` |
| `backend/app/domain/health_alerts/__init__.py` | Package init |
| `backend/app/domain/health_alerts/triggers.py` | `evaluate_lockout_spike()`, `evaluate_inactivity()`, `evaluate_billing_risk()` — pure functions returning trigger decision |
| `backend/app/domain/health_alerts/idempotency.py` | `build_idempotency_key()` — `(tenant_id, type, window_start) -> str` |
| `backend/app/services/health_alert_service.py` | `run_trigger_evaluation()` — orchestrates trigger checks per tenant and creates alerts |
| `backend/app/workers/jobs/health_alert_trigger.py` | Scheduled job: runs `run_trigger_evaluation()` for all active tenants |
| `backend/alembic/versions/XXXX_add_health_alerts.py` | Migration: create `tenant_health_alerts` and `tenant_health_alert_events` tables with `downgrade()` |

**Modified files**

| File | Change |
|---|---|
| `backend/app/db/models/__init__.py` | Export `TenantHealthAlert`, `TenantHealthAlertEvent` |
| `backend/app/db/repo/__init__.py` | Export health_alert_repo and health_alert_event_repo functions via `__all__` |
| `backend/app/workers/scheduling/cron.py` | Register health alert trigger job |

**Key interfaces**

```python
# domain/health_alerts/triggers.py
def evaluate_lockout_spike(failed_login_count_24h: int, threshold: int = 10) -> bool: ...
def evaluate_inactivity(last_login_days_ago: int, threshold: int = 30) -> bool: ...
def evaluate_billing_risk(payment_status: str, grace_end: datetime | None,
                          now: datetime) -> bool: ...

# domain/health_alerts/idempotency.py
def build_idempotency_key(tenant_id: str, alert_type: str, window_start: date) -> str: ...

# db/repo/health_alert_repo.py
def create_alert(db: Session, tenant_id: str, alert_type: str, severity: str,
                 details: dict | None, idempotency_key: str) -> TenantHealthAlert: ...
def alert_exists_for_window(db: Session, idempotency_key: str) -> bool: ...
def list_alerts_for_tenant(db: Session, tenant_id: str,
                           status: str | None = None) -> list[TenantHealthAlert]: ...

# services/health_alert_service.py
async def run_trigger_evaluation(db: Session, tenant_id: str) -> list[TenantHealthAlert]: ...
    # 1. Query auth events and billing state for tenant
    # 2. Evaluate each trigger rule
    # 3. Build idempotency key per trigger + window
    # 4. Skip if alert already exists for window
    # 5. Create alert + audit event
```

**Tasks**
1. Create `TenantHealthAlert` and `TenantHealthAlertEvent` models; create Alembic migration with `downgrade()`.
2. Create `backend/app/db/repo/health_alert_repo.py` and `health_alert_event_repo.py`.
3. Create `backend/app/domain/health_alerts/triggers.py` with threshold evaluation functions.
4. Create `backend/app/domain/health_alerts/idempotency.py` with key builder.
5. Create `backend/app/services/health_alert_service.py` with trigger orchestration.
6. Create `backend/app/workers/jobs/health_alert_trigger.py` and register in cron.
7. Add unit tests for all trigger threshold calculations and idempotency key builder.

**DoD**
- Unit tests validate trigger threshold logic and dedupe key generation.
- Integration tests prove one alert per trigger window (idempotency enforcement).
- Migration round-trip verified: `alembic downgrade -1 && alembic upgrade head`.

---

### Story 1.2 — Alert lifecycle transitions
**Outcome:** robust state transitions and audit trail.

**New files**

| File | Purpose |
|---|---|
| `backend/app/domain/health_alerts/transitions.py` | `acknowledge_alert()`, `resolve_alert()` — pure state transition guards; reject invalid transitions |

**Modified files**

| File | Change |
|---|---|
| `backend/app/db/repo/health_alert_repo.py` | Add `acknowledge_alert()`, `resolve_alert()` — persist state change |
| `backend/app/db/repo/health_alert_event_repo.py` | (already has `create_event()` from Story 1.1) |
| `backend/app/services/health_alert_service.py` | Add `acknowledge()`, `resolve()` — orchestrate transition + audit event |

**Key interfaces**

```python
# domain/health_alerts/transitions.py
VALID_TRANSITIONS = {
    "open": {"acknowledged", "resolved"},
    "acknowledged": {"resolved"},
    "resolved": set(),
}

def validate_transition(current_status: str, target_status: str) -> bool: ...
    # Returns True if transition is allowed; False otherwise

# db/repo/health_alert_repo.py (additions)
def acknowledge_alert(db: Session, alert_id: str) -> TenantHealthAlert: ...
def resolve_alert(db: Session, alert_id: str) -> TenantHealthAlert: ...

# services/health_alert_service.py (additions)
async def acknowledge(db: Session, tenant_id: str, alert_id: str,
                      actor_user_id: str, reason: str | None = None) -> dict: ...
async def resolve(db: Session, tenant_id: str, alert_id: str,
                  actor_user_id: str, reason: str | None = None) -> dict: ...
```

**Tasks**
1. Create `backend/app/domain/health_alerts/transitions.py` with state machine and validation.
2. Add `acknowledge_alert()`, `resolve_alert()` to health_alert_repo.
3. Add `acknowledge()`, `resolve()` to health_alert_service with audit event creation.
4. Add unit tests for valid/invalid state transition paths.
5. Add integration tests for transition persistence and audit event recording.

**DoD**
- Invalid transitions rejected with stable error code (`HEALTH_ALERT_INVALID_TRANSITION`).
- Audit events persist with actor, reason, and timestamp.
- Unit tests cover all transition paths (valid and invalid).

---

## Epic 2 — Tenant API and authorization

### Story 2.1 — Alert API contracts
**Outcome:** stable tenant-facing endpoint contracts.

**New files**

| File | Purpose |
|---|---|
| `backend/app/api/tenant/health_alerts.py` | Health alerts router — list, detail, acknowledge, resolve endpoints |

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/tenant/__init__.py` | Register `health_alerts` router |
| `backend/app/api/schemas.py` | Add `HealthAlertResponse`, `HealthAlertListResponse`, `HealthAlertActionRequest`, `HealthAlertActionResponse` |
| `backend/app/core/errors.py` | Add `HealthAlertNotFoundError`, `HealthAlertForbiddenError`, `HealthAlertInvalidTransitionError` |

**Endpoints**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `GET` | `/v1/health-alerts` | query: `status` (optional) | `200` `{ items: [{ id, tenant_id, type, severity, status, title, created_at }] }` | `401` |
| `GET` | `/v1/health-alerts/{alert_id}` | — | `200` `{ id, tenant_id, type, severity, status, details, created_at, acknowledged_at, resolved_at, events[] }` | `401`, `404` |
| `POST` | `/v1/health-alerts/{alert_id}/acknowledge` | `{ reason }` (optional) | `200` `{ id, status: "acknowledged", acknowledged_at }` | `HEALTH_ALERT_FORBIDDEN` (403), `HEALTH_ALERT_INVALID_TRANSITION` (409), `404` |
| `POST` | `/v1/health-alerts/{alert_id}/resolve` | `{ reason }` (optional) | `200` `{ id, status: "resolved", resolved_at }` | `HEALTH_ALERT_FORBIDDEN` (403), `HEALTH_ALERT_INVALID_TRANSITION` (409), `404` |

**Key interfaces**

```python
# Pydantic schemas (added to backend/app/api/schemas.py)
class HealthAlertResponse(BaseModel):
    id: str
    tenant_id: str
    type: str
    severity: str
    status: str
    title: str
    created_at: datetime

class HealthAlertDetailResponse(HealthAlertResponse):
    details: dict | None
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    events: list[HealthAlertEventResponse]

class HealthAlertActionRequest(BaseModel):
    reason: str | None = None

class HealthAlertActionResponse(BaseModel):
    id: str
    status: str
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None

class HealthAlertListResponse(BaseModel):
    items: list[HealthAlertResponse]
```

**Tasks**
1. Create `backend/app/api/tenant/health_alerts.py` with list, detail, acknowledge, resolve endpoints.
2. Add tenant-scoping: all queries filter by authenticated user's `tenant_id`.
3. Add role gate: acknowledge/resolve restricted to `owner`/`admin` roles.
4. Add Pydantic schemas to `backend/app/api/schemas.py`.
5. Add error codes to `backend/app/core/errors.py`.
6. Register router in `backend/app/api/tenant/__init__.py`.
7. Add contract tests for all endpoint success/failure shapes.
8. Add integration tests confirming no cross-tenant leakage.

**DoD**
- Contract suite covers all 4 endpoints with success + error shapes.
- Integration tests confirm cross-tenant access returns `404` (anti-enumeration).
- Role-gated denial returns `403` with `HEALTH_ALERT_FORBIDDEN`.

---

## Epic 3 — Dashboard and UX flows

### Story 3.1 — Health alert UI exposure
**Outcome:** owner/admin users can discover and act on alerts quickly.

**New files**

| File | Purpose |
|---|---|
| `web/src/app/settings/health-alerts/page.tsx` | Health alert list page with status filtering and acknowledge/resolve actions |
| `web/src/components/health-alert-card.tsx` | Dashboard summary card showing top 3 open alerts |
| `web/src/components/health-alert-detail.tsx` | Alert detail panel with event timeline and action buttons |

**Modified files**

| File | Change |
|---|---|
| `web/src/app/settings/page.tsx` | Add health alert summary card to settings dashboard |
| `web/src/styles/globals.css` | Add `.alert-card`, `.alert-badge-severity`, `.alert-actions` classes |

**Tasks**
1. Create health alert list page at `web/src/app/settings/health-alerts/page.tsx`.
2. Create `health-alert-card.tsx` component showing top open alerts on settings dashboard.
3. Create `health-alert-detail.tsx` with event timeline and acknowledge/resolve buttons.
4. Add role-gated UI: hide action buttons for `member` role; show permission message.
5. Wire acknowledge/resolve actions to API endpoints.
6. Add E2E tests for discoverability and action execution.

**DoD**
- E2E verifies owner/admin can view, acknowledge, and resolve alerts.
- E2E verifies member sees alerts but action buttons are hidden/disabled.
- Alert summary card visible on settings dashboard with link to full list.

---

## 3) Testing workstream (required)

### 3.1 Unit tests
- Location: `backend/tests/unit/`
- [ ] `test_alert_triggers.py` — trigger threshold calculations for all 3 trigger types
- [ ] `test_alert_transitions.py` — lifecycle transition guards (valid + invalid paths)
- [ ] `test_alert_idempotency.py` — idempotency key generation

### 3.2 Integration tests
- Location: `backend/tests/integration/`
- [ ] `test_alert_creation.py` — alert creation, dedupe enforcement, trigger job behavior
- [ ] `test_alert_lifecycle.py` — acknowledge/resolve persistence, audit event recording
- [ ] `test_alert_tenant_scoping.py` — tenant isolation and role enforcement

### 3.3 Contract tests
- Location: `backend/tests/contract/`
- [ ] `test_health_alerts.py` — endpoint shape/status/code verification for all 4 endpoints

### 3.4 E2E tests
- Location: `web/tests/e2e/`
- [ ] `health-alerts.spec.ts` — dashboard summary + list/detail + acknowledge/resolve flows

### 3.5 Migration verification
- [ ] Alembic migration creates `tenant_health_alerts` and `tenant_health_alert_events` tables
  with `downgrade()`
- [ ] `alembic upgrade head` succeeds
- [ ] Round-trip verified: `alembic downgrade -1 && alembic upgrade head`

### 3.6 CI gates
- [ ] `make test-unit`
- [ ] `make test-integration`
- [ ] `make test-contract`
- [ ] `cd web && npm run test:e2e:stable`

---

## 4) Documentation update workstream (required)

### 4.1 Architecture (`docs/01_architecture`)
- [ ] Add alert generation sequence and state model.

### 4.2 Product (`docs/02_product`)
- [ ] Add owner/admin health alert UX and response expectations.

### 4.3 Runbooks (`docs/03_runbooks`)
- [ ] Add lockout spike remediation procedure.

### 4.4 Security (`docs/04_security`)
- [ ] Add alert abuse/false-positive handling and audit controls.

### 4.5 Quality (`docs/05_quality`)
- [ ] Add alert test matrix and CI gating notes.

**Documentation DoD**
- [ ] All docs updated and cross-linked from feature index.

---

## 5) Lean refactor workstream (required)

### 5.1 Planned refactor tasks
- [ ] Consolidate duplicated role-gating logic into shared helper.
- [ ] Consolidate alert error-code mapping into shared utility.
- [ ] Remove temporary legacy dashboard branch after rollout.

### 5.2 Refactor guardrails
- [ ] No new user-visible scope added by refactor.
- [ ] Behavior parity verified by existing + new tests.
- [ ] Lint/type checks remain green.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| Auth event log (`audit_events` table) | Story 1.1 (lockout spike trigger) | Implemented | Lockout alerts unavailable without event data |
| Billing state fields (`payment_status`, `grace_end`) | Story 1.1 (billing risk trigger) | Implemented | Billing risk alerts unavailable |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Alert fatigue from false positives | Medium | Medium | Conservative thresholds + tuning review after rollout |
| Auth event stream gaps | Low | Medium | Fallback recompute job sweeps missed windows |

## 7) Sequencing and parallelization

### Suggested sequence
1. Epic 1 (generation/lifecycle)
2. Epic 2 (API/contracts)
3. Epic 3 (UI/e2e)

### Parallelization opportunities
- Story 1.2 and 2.1 can overlap once lifecycle contract is frozen.
- E2E scaffolding can start with stubbed API responses.

## 8) Rollout and cutover plan

- Stage 1: internal tenant only.
- Stage 2: 10% tenant rollout with monitoring.
- Stage 3: full rollout after one stable weekly cycle.

## 9) Execution tracker (copy/paste section)

### Current sprint
- [ ] Story 1.1 implementation and tests
- [ ] Story 2.1 endpoint contracts

### Blocked items
- None

### Done this sprint
- [x] Spec and implementation plan approved

## 10) Story-by-Story Verification Gate (Agent Checklist)

Before marking any story complete, attach evidence for:

- [ ] Files created/modified match story scope (`New files` / `Modified files` tables)
- [ ] Endpoint contract implemented exactly as documented (method/path/body/status/error code)
- [ ] Key interfaces implemented with compatible signatures
- [ ] Required tests added/updated for all four layers where applicable
- [ ] Commands executed and passed:
    - [ ] `make test-unit`
    - [ ] `make test-integration`
    - [ ] `make test-contract`
    - [ ] `cd web && npm run test:e2e:stable` (if UI touched)
- [ ] Migration round-trip evidence included if schema changed
- [ ] Related docs/checklists updated in same PR when behavior/contract changed

## 11) Definition of plan done

- [ ] Every FR mapped to stories/tasks/tests/docs updates.
- [ ] Every story includes New files, Modified files, Endpoints, Key interfaces, Tasks, and DoD.
- [ ] All test layers green for release candidate.
- [ ] Documentation updates across docs/01-05 completed.
- [ ] Refactor stream completed within guardrails.
