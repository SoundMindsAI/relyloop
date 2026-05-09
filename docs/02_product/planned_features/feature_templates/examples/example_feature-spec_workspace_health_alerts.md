# Feature Specification — Workspace Health Alerts

**Date:** 2026-03-05
**Status:** Planned
**Owners:** Product (Growth), Engineering (Backend Platform)
**Related docs:**
- `docs/02_product/planned_features/feature_templates/feature-spec-template.md`
- `docs/02_product/planned_features/feature_templates/examples/example_implementation-plan_workspace_health_alerts.md`

---

## 1) Purpose

Workspace owners currently have limited visibility into account health drift (no active users, repeated lockouts, and billing risk). This feature introduces a workspace health alert center that surfaces actionable alerts and recovery actions for owners/admins. Success means owners can identify and resolve health risks in under 5 minutes without admin intervention in common scenarios.

## 2) Scope

### In scope
- Workspace health read model for owner/admin users.
- Alert generation for inactivity, lockout spikes, and billing-risk status.
- Tenant-facing API and dashboard card/list UI.
- Alert acknowledgment and resolution tracking.

### Out of scope
- Predictive churn scoring model.
- Cross-tenant global admin alert dashboard.

## 3) Product principles and constraints

- Tenant isolation is mandatory for all reads/writes.
- Alerts must be explainable with deterministic trigger rules.
- Alert actions must be auditable.

## 4) Assumptions and dependencies

- Dependency: auth/account event stream
  - Why required: lockout/inactivity triggers
  - Status: implemented
  - Risk if missing: incomplete alert coverage
- Dependency: tenant billing state
  - Why required: billing-risk alerts
  - Status: implemented
  - Risk if missing: billing alerts unavailable

## 5) Actors and roles

- Primary actors: `owner`, `admin`, `member`.
- Permissions:
  - `owner`, `admin`: view + acknowledge + resolve alerts.
  - `member`: denied.

### RBAC authorization matrix

| Endpoint | `owner` | `admin` | `member` |
|----------|---------|---------|----------|
| `GET /v1/health-alerts` | allow | allow | deny |
| `GET /v1/health-alerts/{id}` | allow | allow | deny |
| `POST /v1/health-alerts/{id}/acknowledge` | allow | allow | deny |
| `POST /v1/health-alerts/{id}/resolve` | allow | allow | deny |

## 6) Functional requirements

### FR-1: Alert generation and lifecycle
- The system **MUST** generate alerts for configured trigger conditions.
- The system **MUST** track alert lifecycle: `open`, `acknowledged`, `resolved`.

### FR-2: Tenant-scoped API
- The system **MUST** expose tenant-scoped alert list and detail endpoints.
- The system **MUST** enforce role gates on acknowledgment and resolution actions.

### FR-3: UI discoverability
- The system **MUST** expose health alerts in settings dashboard and dedicated list view.
- The system **SHOULD** surface top 3 open alerts in dashboard summary.

## 7) API and data contract baseline

### 7.1 Endpoint surface

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `GET` | `/v1/health-alerts` | List alerts for tenant (filterable by status) | `401` |
| `GET` | `/v1/health-alerts/{alert_id}` | Alert detail with event timeline | `401`, `404` |
| `POST` | `/v1/health-alerts/{alert_id}/acknowledge` | Acknowledge open alert | `HEALTH_ALERT_FORBIDDEN` (403), `HEALTH_ALERT_INVALID_TRANSITION` (409), `404` |
| `POST` | `/v1/health-alerts/{alert_id}/resolve` | Resolve alert | `HEALTH_ALERT_FORBIDDEN` (403), `HEALTH_ALERT_INVALID_TRANSITION` (409), `404` |

### 7.2 Contract rules
- Error body includes `code`.
- Cross-tenant scope denial uses anti-enumeration semantics (`404` for cross-tenant access).

### 7.3 Response examples

`GET /v1/health-alerts` success:

```json
{
  "items": [
    {
      "id": "uuid",
      "tenant_id": "uuid",
      "type": "AUTH_LOCKOUT_SPIKE",
      "severity": "high",
      "status": "open",
      "title": "Unusual lockout spike detected",
      "created_at": "2026-03-05T00:00:00Z"
    }
  ]
}
```

`POST /v1/health-alerts/{alert_id}/acknowledge` — member denied:

```json
{
  "error": {
    "code": "HEALTH_ALERT_FORBIDDEN",
    "message": "You do not have permission to acknowledge alerts."
  }
}
```

HTTP `403` — role-gated: only `owner` and `admin` can acknowledge or resolve alerts.

### 7.4 Error code catalog

| Code | HTTP Status | Meaning |
|------|-------------|---------|
| `HEALTH_ALERT_FORBIDDEN` | `403` | Caller lacks permission to acknowledge/resolve (member role) |
| `HEALTH_ALERT_INVALID_TRANSITION` | `409` | Alert is not in a state that allows the requested transition |

## 8) Data model and state transitions

### New table: `tenant_health_alerts`

- `id` (UUID PK)
- `tenant_id` (FK to `tenants.id`, indexed)
- `type` (enum: `AUTH_LOCKOUT_SPIKE`, `INACTIVITY`, `BILLING_RISK`)
- `severity` (enum: `low`, `medium`, `high`)
- `status` (enum: `open`, `acknowledged`, `resolved`, default `open`)
- `details_json` (JSON, nullable — trigger-specific metadata)
- `idempotency_key` (varchar, unique — `tenant_id:type:window_start` for dedupe)
- `created_at` (timestamptz, default now)
- `acknowledged_at` (timestamptz, nullable)
- `resolved_at` (timestamptz, nullable)

### New table: `tenant_health_alert_events`

- `id` (UUID PK)
- `alert_id` (FK to `tenant_health_alerts.id`)
- `event_type` (enum: `created`, `acknowledged`, `resolved`)
- `actor_user_id` (UUID, nullable — null for system-generated events)
- `reason` (text, nullable)
- `created_at` (timestamptz, default now)

### Required invariants
- One alert per `(tenant_id, type, window_start)` — enforced by unique `idempotency_key`.
- Tenant isolation: all queries filter by `tenant_id`.

### State transitions
- `open -> acknowledged -> resolved`
- `open -> resolved` (direct resolution allowed)
- No reverse transitions (resolved is terminal)

## 9) Security, privacy, and compliance

- No PII beyond existing tenant member identifiers in audit metadata.
- Alert actions audit fields: actor, reason (optional), target alert, timestamp.

## 10) UX flows and edge cases

### Primary flows
1. Owner opens settings and sees top open alerts.
2. Owner opens alert detail and acknowledges alert.
3. Owner resolves alert after remediation.

### Edge/error flows
- Unauthorized member action denied.
- Alert already resolved returns deterministic conflict response.

## 11) Given/When/Then acceptance criteria

### AC-1: Lockout spike alert creation
- Given a tenant exceeds lockout threshold in 24h
- When daily alert job runs
- Then an `AUTH_LOCKOUT_SPIKE` alert is created with `status=open`

### AC-2: Acknowledge alert
- Given an open alert exists for tenant
- When tenant owner acknowledges the alert
- Then alert status becomes `acknowledged`
- And audit event is recorded

### AC-3: Unauthorized member action
- Given a tenant member (not owner/admin)
- When member calls acknowledge endpoint
- Then API returns authorization failure contract

## 12) Non-functional requirements

- Alert list endpoint p95 < 250ms at 100 open alerts.
- Alert generation job is idempotent per trigger window.

## 13) Test strategy requirements (spec-level)

- Unit tests (`backend/tests/unit/`): trigger calculation, status transition guards.
- Integration tests (`backend/tests/integration/`): persistence, tenant scoping, lifecycle transitions.
- Contract tests (`backend/tests/contract/`): endpoint shape/status/error codes.
- E2E tests (`web/tests/e2e/`): owner visibility, member denial, acknowledge/resolve journey.

## 14) Documentation update requirements

- `docs/01_architecture`: add health-alert subsystem and sequence.
- `docs/02_product`: add owner health alert UX and policies.
- `docs/03_runbooks`: add remediation playbook for lockout spike alert.
- `docs/04_security`: add abuse/false-positive mitigation notes.
- `docs/05_quality`: add alert coverage matrix and release gates.

## 15) Rollout and migration readiness

- Staged rollout: internal tenant -> 10% tenants -> full.
- Migration adds new alert tables with downgrade path.

## 16) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 | AC-1, AC-2 | S1.1, S1.2 | `tests/unit/domain/test_alert_triggers.py`, `tests/integration/test_alert_lifecycle.py` | `docs/01_architecture/health_alerts.md`, `docs/05_quality/alert_test_matrix.md` |
| FR-2 | AC-2, AC-3 | S2.1 | `tests/contract/test_health_alerts.py`, `tests/integration/test_alert_tenant_scoping.py` | `docs/01_architecture/health_alerts.md`, `docs/03_runbooks/lockout_spike.md` |
| FR-3 | AC-2 | S3.1 | `web/tests/e2e/health-alerts.spec.ts` | `docs/02_product/health_alert_ux.md` |

## 17) Definition of feature done

This feature is complete when:

- [ ] All acceptance criteria (AC-1, AC-2, AC-3) pass in CI.
- [ ] All test layers (unit/integration/contract/e2e) are green.
- [ ] Documentation updates across docs/01-05 are merged.
- [ ] Rollout gates from §15 are satisfied.
- [ ] No open questions remain in §18.

## 18) Open questions and decision log

### Open questions
- Should acknowledge require mandatory reason for `high` severity alerts?

### Decision log
- 2026-03-05 — Start with optional reason for acknowledge; mandatory reason for resolve in phase 2.
