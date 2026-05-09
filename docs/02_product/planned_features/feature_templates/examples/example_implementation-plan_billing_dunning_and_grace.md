# Implementation Plan — Billing Dunning and Grace Recovery

**Date:** 2026-03-05
**Status:** Ready for Execution
**Primary spec:** `example_feature-spec_billing_dunning_and_grace.md`

---

## 0) Planning principles

- Preserve Stripe-as-canonical-state behavior.
- Every story maps to FRs and test layers.
- Keep migrations reversible and rollout gated.

## 1) Scope traceability (FR → epics)

| FR ID | Epic | Notes |
|---|---|---|
| FR-1 | Epic 1 | payment-failed and grace transitions |
| FR-2 | Epic 2 | reminders and policy timing |
| FR-3 | Epic 3 | recovery UX and support path |

## 2) Delivery structure

Conventions carried from existing codebase:
- All repo functions take `db: Session` as first arg; use `db.flush()` (caller commits)
- Services are async; create `job_run` at start where applicable
- Domain layer is pure — no DB access, no side effects
- Stripe webhook handlers must call `is_event_processed()` before processing and `record_event()` after
- Models use `Mapped[]` typed columns, `String(36)` UUIDs
- Routers return typed Pydantic response models; errors use `HTTPException` with structured detail

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

## Epic 1 — Billing lifecycle transitions

### Story 1.1 — Webhook transition hardening
**Outcome:** canonical, replay-safe transitions for payment failure/success.

**New files**

| File | Purpose |
|---|---|
| `backend/app/domain/billing/__init__.py` | Package init |
| `backend/app/domain/billing/transitions.py` | `apply_payment_failed()`, `apply_payment_succeeded()`, `reconcile_billing_state()` — pure transition rules; determine target state from current state + event |
| `backend/app/domain/billing/guards.py` | `is_out_of_order()` — checks event timestamp vs current state; returns True if event should be skipped |
| `backend/app/db/repo/billing_audit_repo.py` | `create_billing_audit_event()`, `list_events_for_tenant()` |

**Modified files**

| File | Change |
|---|---|
| `backend/app/db/models/tenant_entitlement.py` | Add columns: `payment_status` (enum: `active`, `payment_failed`, `grace`, `restricted`, default `active`), `grace_end` (timestamptz nullable), `last_payment_failure_at` (timestamptz nullable), `dunning_reminder_count` (int default 0) |
| `backend/app/db/models/__init__.py` | Export `TenantBillingAuditEvent` |
| `backend/app/db/repo/__init__.py` | Export billing_audit_repo functions via `__all__` |
| `backend/app/integrations/stripe/webhook_handlers.py` | Refactor `invoice.payment_failed` and `invoice.payment_succeeded` handlers to use domain transition functions instead of inline state mutation |
| `backend/alembic/versions/XXXX_add_dunning_fields.py` | Migration: add `payment_status`, `grace_end`, `last_payment_failure_at`, `dunning_reminder_count` to `tenant_entitlements`; create `tenant_billing_audit_events` table. Includes `downgrade()`. |

**Key interfaces**

```python
# domain/billing/transitions.py
def apply_payment_failed(current_status: str, grace_period_days: int = 14,
                         now: datetime = None) -> dict: ...
    # Returns: { payment_status, grace_end, last_payment_failure_at }
    # Rules: active -> payment_failed; sets grace_end = now + grace_period_days

def apply_payment_succeeded(current_status: str) -> dict: ...
    # Returns: { payment_status: "active", grace_end: None, dunning_reminder_count: 0 }
    # Clears all dunning state regardless of current status

def reconcile_billing_state(current: dict, stripe_subscription_status: str,
                            latest_invoice_status: str) -> dict: ...
    # Canonical reconciliation: Stripe state wins over local state

# domain/billing/guards.py
def is_out_of_order(event_created: datetime, last_processed_at: datetime | None) -> bool: ...

# db/repo/billing_audit_repo.py
def create_billing_audit_event(db: Session, tenant_id: str, event_type: str,
                               actor: str | None = None,
                               metadata: dict | None = None) -> TenantBillingAuditEvent: ...
def list_events_for_tenant(db: Session, tenant_id: str,
                           limit: int = 50) -> list[TenantBillingAuditEvent]: ...
```

**Tasks**
1. Create `backend/app/domain/billing/transitions.py` and `guards.py` with pure transition logic.
2. Add `payment_status`, `grace_end`, `last_payment_failure_at`, `dunning_reminder_count` to `TenantEntitlement` model.
3. Create `TenantBillingAuditEvent` model and `billing_audit_repo.py`.
4. Create Alembic migration with `downgrade()`.
5. Refactor `invoice.payment_failed` handler to use `apply_payment_failed()`.
6. Refactor `invoice.payment_succeeded` handler to use `apply_payment_succeeded()`.
7. Add out-of-order guard using `is_out_of_order()` in both handlers.
8. Add integration tests for duplicate and out-of-order webhook event replay.

**DoD**
- Duplicate event replay causes no state corruption (idempotency verified in integration tests).
- Latest canonical Stripe state wins after reconciliation.
- Migration round-trip verified: `alembic downgrade -1 && alembic upgrade head`.
- Unit tests pass for all transition rule branches.

---

### Story 1.2 — Restriction and grace enforcement
**Outcome:** consistent access behavior during grace and restricted states.

**New files**

| File | Purpose |
|---|---|
| `backend/app/domain/billing/access.py` | `get_access_level()` — pure function: given `payment_status` and `grace_end`, returns access level (`full`, `limited`, `billing_only`) |

**Modified files**

| File | Change |
|---|---|
| `backend/app/services/quota_service.py` | Add billing-state check before quota evaluation: if `payment_status == "restricted"`, block cost-incurring actions with `BILLING_PAYMENT_REQUIRED` |
| `backend/app/api/tenant/middleware.py` (or equivalent) | Add billing-state middleware: inject `access_level` into request context for tenant-scoped routes |

**Key interfaces**

```python
# domain/billing/access.py
def get_access_level(payment_status: str, grace_end: datetime | None,
                     now: datetime) -> str: ...
    # Returns: "full" | "limited" | "billing_only"
    # "limited" = grace active (warnings shown, features available)
    # "billing_only" = grace expired, restricted state
```

**Tasks**
1. Create `backend/app/domain/billing/access.py` with access level determination logic.
2. Integrate billing-state check into quota service — return `BILLING_PAYMENT_REQUIRED` for restricted tenants.
3. Add automatic state clearing: when `apply_payment_succeeded()` runs, restore full access.
4. Add integration tests for grace → restricted transition timing and post-payment recovery.

**DoD**
- Restricted tenants retain billing/settings access but cannot perform cost-incurring actions.
- Successful payment deterministically restores full access.
- Integration tests verify state-driven access gating across grace/restricted/active.

---

## Epic 2 — Reminder policy execution

### Story 2.1 — Reminder scheduler and dedupe
**Outcome:** deterministic reminder cadence without duplicate sends.

**New files**

| File | Purpose |
|---|---|
| `backend/app/domain/billing/reminders.py` | `calculate_checkpoints()` — returns list of reminder dates from `grace_start`; `should_send_reminder()` — checks `dunning_reminder_count` against checkpoint index |
| `backend/app/workers/jobs/dunning_reminder.py` | Scheduled job: iterates tenants in grace, evaluates checkpoint, sends reminder if due |

**Modified files**

| File | Change |
|---|---|
| `backend/app/db/repo/billing_audit_repo.py` | Add `count_reminders_for_tenant()` for dedupe check |
| `backend/app/services/billing_service.py` | Add `send_dunning_reminder()` — orchestrates checkpoint check, email send, audit event, counter increment |
| `backend/app/workers/scheduling/cron.py` | Register dunning reminder job |

**Key interfaces**

```python
# domain/billing/reminders.py
REMINDER_CHECKPOINTS_DAYS = [1, 3, 7, 12]  # days after grace_start

def calculate_checkpoints(grace_start: datetime) -> list[datetime]: ...
def should_send_reminder(grace_start: datetime, reminder_count: int,
                         now: datetime) -> tuple[bool, int]: ...
    # Returns: (should_send, checkpoint_index)

# services/billing_service.py (addition)
async def send_dunning_reminder(db: Session, tenant_id: str,
                                checkpoint_index: int) -> None: ...
    # 1. Check dedupe: if reminder_count >= checkpoint_index, skip
    # 2. Send email via Resend integration
    # 3. Create audit event: reminder_sent
    # 4. Increment dunning_reminder_count
```

**Tasks**
1. Create `backend/app/domain/billing/reminders.py` with checkpoint calculation and send-decision logic.
2. Create `backend/app/workers/jobs/dunning_reminder.py` scheduled job.
3. Add `send_dunning_reminder()` to billing service.
4. Add `count_reminders_for_tenant()` to billing_audit_repo.
5. Register job in cron scheduler.
6. Add unit tests for checkpoint schedule calculations and dedupe decision logic.
7. Add integration tests for reminder send and counter increment.

**DoD**
- Checkpoint reminders match policy constants (`[1, 3, 7, 12]` days).
- No duplicate reminders for same checkpoint (dedupe verified in integration tests).
- Unit tests cover all schedule calculation edge cases.

---

## Epic 3 — Tenant recovery UX and contracts

### Story 3.1 — Billing status API and UI recovery flow
**Outcome:** owners can recover from payment failure with clear action path.

**New files**

| File | Purpose |
|---|---|
| `web/src/components/billing-recovery-banner.tsx` | In-app banner for payment-failed/grace states with portal CTA and support contact |

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/tenant/billing.py` | Add/extend `GET /v1/billing/status` to return `payment_status`, `grace_end`, `is_restricted`, `next_action`, `support_contact` |
| `backend/app/api/schemas.py` | Add `BillingStatusResponse` with dunning-specific fields |
| `web/src/app/settings/billing/page.tsx` | Add billing recovery banner and portal CTA in payment-friction states |
| `web/src/styles/globals.css` | Add `.billing-banner`, `.billing-banner-warning`, `.billing-banner-critical` classes |

**Endpoints**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `GET` | `/v1/billing/status` | — (tenant-scoped) | `200` `{ tenant_id, plan, payment_status, grace_end, is_restricted, next_action, support_contact, dunning_reminder_count }` | `401`, `BILLING_NOT_FOUND` (404) |

**Key interfaces**

```python
# Pydantic schemas (added to backend/app/api/schemas.py)
class BillingStatusResponse(BaseModel):
    tenant_id: str
    plan: str
    payment_status: str        # active | payment_failed | grace | restricted
    grace_end: datetime | None
    is_restricted: bool
    next_action: str | None    # "update_payment_method" | "contact_support" | None
    support_contact: str
    dunning_reminder_count: int
```

**Tasks**
1. Extend `GET /v1/billing/status` response with recovery fields.
2. Add `BillingStatusResponse` Pydantic schema.
3. Create `web/src/components/billing-recovery-banner.tsx` with portal CTA and support contact.
4. Integrate banner into settings billing page for `payment_failed`/`grace`/`restricted` states.
5. Add contract tests for billing status response shape in all payment states.
6. Add E2E tests for payment-failed banner visibility and portal CTA click.

**DoD**
- Status API returns stable schema for `payment_failed`/`grace`/`restricted` states.
- E2E validates owner recovery flow: banner visible → CTA present → portal link works.
- Contract tests verify response shape for all `payment_status` enum values.

---

## 3) Testing workstream (required)

### 3.1 Unit tests
- Location: `backend/tests/unit/`
- [ ] `test_billing_transitions.py` — transition rule guards for all state paths
- [ ] `test_billing_guards.py` — out-of-order event detection
- [ ] `test_billing_reminders.py` — reminder schedule calculations and dedupe decisions
- [ ] `test_billing_access.py` — access level determination for all payment states

### 3.2 Integration tests
- Location: `backend/tests/integration/`
- [ ] `test_billing_webhooks.py` — webhook replay/out-of-order behavior, idempotency
- [ ] `test_billing_grace.py` — grace-to-restricted enforcement and payment recovery
- [ ] `test_billing_reminders.py` — reminder send, counter increment, dedupe

### 3.3 Contract tests
- Location: `backend/tests/contract/`
- [ ] `test_billing_status.py` — `GET /v1/billing/status` shape/status/code for all states

### 3.4 E2E tests
- Location: `web/tests/e2e/`
- [ ] `billing-recovery.spec.ts` — payment-failed banner, portal CTA, post-recovery state

### 3.5 Migration verification
- [ ] Alembic migration adds `payment_status`, `grace_end`, `last_payment_failure_at`,
  `dunning_reminder_count` to `tenant_entitlements` with `downgrade()`
- [ ] Migration creates `tenant_billing_audit_events` table with `downgrade()`
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
- [ ] Add dunning/grace lifecycle diagram and state precedence notes.

### 4.2 Product (`docs/02_product`)
- [ ] Add payment-failure UX states and owner/admin behavior matrix.

### 4.3 Runbooks (`docs/03_runbooks`)
- [ ] Add webhook replay and payment-failed remediation procedure.

### 4.4 Security (`docs/04_security`)
- [ ] Update trust boundary docs for Stripe webhooks and billing portal flows.

### 4.5 Quality (`docs/05_quality`)
- [ ] Add dunning and recovery test matrix with release gates.

**Documentation DoD**
- [ ] All docs updated and cross-linked from billing feature artifacts.

---

## 5) Lean refactor workstream (required)

### 5.1 Planned refactor tasks
- [ ] Consolidate billing state precedence logic into single service utility.
- [ ] Remove duplicated webhook event mapping branches.
- [ ] Normalize billing error-code mapping across API handlers.

### 5.2 Refactor guardrails
- [ ] Behavior parity validated by integration + contract tests.
- [ ] No scope expansion beyond dunning/grace/recovery.
- [ ] Lint/type checks remain green.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| Stripe webhook pipeline (`invoice.payment_failed`, `invoice.payment_succeeded`) | Story 1.1 | Implemented | Grace state transitions cannot be triggered |
| Transactional email channel (Resend) | Story 2.1 | Implemented | Dunning reminders cannot be sent |
| Stripe customer portal session (`POST /v1/billing/portal-session`) | Story 3.1 | Planned | Recovery CTA links to dead endpoint |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Reminder fatigue from too-frequent emails | Medium | Medium | Strict checkpoint policy (`[1, 3, 7, 12]` days) and dedupe enforcement |
| Webhook delivery gaps miss payment events | Low | High | Reconciliation worker daily sweep against Stripe API |
| Grace period too short for some payment methods | Low | Medium | Configurable `grace_period_days` default (14 days); adjustable per admin override |

## 7) Sequencing and parallelization

### Suggested sequence
1. Epic 1 (transitions)
2. Epic 2 (reminders)
3. Epic 3 (UX/contracts)

### Parallelization opportunities
- Story 2.1 can start once grace state fields are finalized.
- E2E scaffolding can run in parallel with API contract freeze.

## 8) Rollout and cutover plan

- Stage 1: internal tenant validation.
- Stage 2: small production cohort with enhanced monitoring.
- Stage 3: full rollout after one complete billing cycle observation.

## 9) Execution tracker (copy/paste section)

### Current sprint
- [ ] Story 1.1 transition hardening
- [ ] Story 3.1 status contract updates

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

- [ ] FR coverage complete with mapped stories, tests, and docs updates.
- [ ] Every story includes New files, Modified files, Endpoints, Key interfaces, Tasks, and DoD.
- [ ] Unit/integration/contract/e2e layers are green.
- [ ] Docs/01-05 updates complete.
- [ ] Refactor stream complete within guardrails.
