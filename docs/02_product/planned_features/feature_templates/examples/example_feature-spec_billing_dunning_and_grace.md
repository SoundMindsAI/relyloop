# Feature Specification — Billing Dunning and Grace Recovery

**Date:** 2026-03-05
**Status:** Planned
**Owners:** Product (Monetization), Engineering (Billing)
**Related docs:**
- `docs/02_product/planned_features/feature_templates/feature-spec-template.md`
- `docs/02_product/planned_features/feature_templates/examples/example_implementation-plan_billing_dunning_and_grace.md`

---

## 1) Purpose

Tenants that fail payment currently encounter inconsistent recovery messaging and unclear next steps. This feature standardizes dunning behavior, grace-state transitions, and recovery UX so tenants can restore service quickly while preserving billing integrity. Success means payment-failed tenants consistently receive clear reminders and recover without support intervention in common cases.

## 2) Scope

### In scope
- Payment-failed state handling and grace progression rules.
- Reminder cadence and channel policy for dunning period.
- Billing status API fields for `payment_status`, `grace_end`, and next action.
- Tenant-facing recovery UX and support fallback visibility.

### Out of scope
- New payment providers beyond Stripe.
- Price model redesign.

## 3) Product principles and constraints

- Stripe lifecycle state is canonical source for subscription/payment transitions.
- Dunning communication must be deterministic and auditable.
- Recovery path must remain available in restricted mode.

## 4) Assumptions and dependencies

- Dependency: Stripe webhook pipeline (`invoice.payment_failed`, `invoice.payment_succeeded`, `customer.subscription.updated`)
  - Status: implemented
  - Risk if missing: grace state drift
- Dependency: transactional email channel
  - Status: implemented
  - Risk if missing: dunning reminders not sent

## 5) Actors and roles

- Tenant `owner`: can update payment method and recover account.
- Tenant `admin`: can view billing state; cannot cancel account if policy forbids.
- System: processes Stripe events and reminder jobs.

### RBAC authorization matrix

| Endpoint | `owner` | `admin` | `member` |
|----------|---------|---------|----------|
| `GET /v1/billing/status` | allow | allow | deny |
| `POST /v1/billing/portal-session` | allow | deny | deny |

## 6) Functional requirements

### FR-1: Dunning lifecycle
- The system **MUST** transition tenant to dunning/grace on payment failure per policy defaults.
- The system **MUST** clear dunning/grace immediately on successful payment confirmation.

### FR-2: Reminder policy
- The system **MUST** send reminder emails on configured checkpoints during grace.
- The system **SHOULD** show in-app banners for active users during dunning period.

### FR-3: Recovery UX and support path
- The system **MUST** expose next-step recovery actions from billing status and settings page.
- The system **MUST** display billing support contact in payment-friction states.

## 7) API and data contract baseline

### 7.1 Endpoint surface

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `GET` | `/v1/billing/status` | Billing status with dunning/recovery fields | `401`, `BILLING_NOT_FOUND` (404) |
| `POST` | `/v1/billing/portal-session` | Create Stripe customer portal session for payment update | `401`, `BILLING_PAYMENT_REQUIRED` (402) |

### 7.2 Contract rules
- Status response includes `payment_status`, `grace_end`, `is_restricted`, `next_action`.
- Error body includes machine-readable `code`.
- Cross-tenant billing access returns `404` with anti-enumeration shape.

### 7.3 Response examples

`GET /v1/billing/status` during grace:

```json
{
  "tenant_id": "uuid",
  "plan": "starter",
  "payment_status": "payment_failed",
  "grace_end": "2026-03-15T00:00:00Z",
  "is_restricted": true,
  "next_action": "update_payment_method",
  "support_contact": "billing@soundminds.ai"
}
```

`GET /v1/billing/status` — unauthorized (cross-tenant):

```json
{
  "error": {
    "code": "BILLING_NOT_FOUND",
    "message": "Billing status not found."
  }
}
```

HTTP `404` — anti-enumeration: cross-tenant access returns the same shape as a genuinely missing
resource.

### 7.4 Error code catalog

| Code | HTTP Status | Meaning |
|------|-------------|---------|
| `BILLING_NOT_FOUND` | `404` | Billing status not found (anti-enumeration for cross-tenant) |
| `BILLING_PAYMENT_REQUIRED` | `402` | Tenant in restricted state; payment update required |

## 8) Data model and state transitions

### Modified table: `tenant_entitlements`

- Add `payment_status` (enum: `active`, `payment_failed`, `grace`, `restricted`, default `active`) — current dunning state
- Add `grace_end` (timestamptz, nullable) — set on payment failure per policy defaults; cleared on payment success
- Add `last_payment_failure_at` (timestamptz, nullable) — timestamp of most recent payment failure event
- Add `dunning_reminder_count` (int, default 0) — tracks reminders sent in current grace window; reset on recovery

### New table: `tenant_billing_audit_events`

- `id` (UUID PK)
- `tenant_id` (FK to `tenants.id`, indexed)
- `event_type` (enum: `payment_failed`, `grace_entered`, `reminder_sent`, `restricted`, `payment_recovered`, `admin_override`)
- `actor` (varchar, nullable — `"system"` or admin email)
- `metadata_json` (jsonb, nullable — checkpoint index, Stripe event ID, etc.)
- `created_at` (timestamptz, default now)

### Required invariants
- `payment_status` must always reflect the canonical Stripe subscription/invoice state after reconciliation.
- `grace_end` is non-null only when `payment_status` is `payment_failed` or `grace`.
- `dunning_reminder_count` resets to 0 when `payment_status` returns to `active`.

### State transitions
- `active -> payment_failed -> grace -> restricted`
- `payment_failed|grace|restricted -> active` on payment success
- Guardrails: transitions only via domain function; webhook handlers cannot mutate state directly.

### Idempotency/replay behavior
- Webhook handlers check `is_event_processed()` before processing.
- Out-of-order events reconciled via `reconcile_billing_state()` — Stripe state wins.

## 9) Security, privacy, and compliance

- Billing actions and admin overrides are audit-logged with actor/reason.
- No card data stored in local system; Stripe-hosted payment handling only.

## 10) UX flows and edge cases

### Primary flows
1. Payment fails and tenant enters grace with clear banner + CTA.
2. Owner updates payment method via portal and returns to active state.

### Edge/error flows
- Webhook out-of-order delivery reconciles to canonical Stripe state.
- Grace ends without payment and tenant remains restricted with billing-only access.

## 11) Given/When/Then acceptance criteria

### AC-1: Payment failure enters grace
- Given an active Starter tenant
- When Stripe sends `invoice.payment_failed`
- Then tenant billing status transitions to payment-failed/grace state
- And `grace_end` is populated using policy defaults

### AC-2: Payment success exits grace
- Given a tenant in grace state
- When Stripe sends `invoice.payment_succeeded`
- Then billing status returns to active
- And restriction flags are cleared

### AC-3: Recovery visibility
- Given a tenant in payment-failed or grace state
- When owner loads settings billing page
- Then owner sees recovery CTA and support contact

## 12) Non-functional requirements

- Billing status endpoint p95 < 300ms.
- Webhook handlers are idempotent and replay-safe.

## 13) Test strategy requirements (spec-level)

- Unit tests (`backend/tests/unit/`): state transition rules, reminder checkpoint calculations.
- Integration tests (`backend/tests/integration/`): webhook-driven transitions, reconciliation, grace expiry behavior.
- Contract tests (`backend/tests/contract/`): billing status response schema and error codes.
- E2E tests (`web/tests/e2e/`): payment-failed banner, portal CTA flow, post-recovery state.

## 14) Documentation update requirements

- `docs/01_architecture`: billing lifecycle and reconciliation sequence.
- `docs/02_product`: dunning/grace UX copy and role expectations.
- `docs/03_runbooks`: payment-failure incident and replay/remediation steps.
- `docs/04_security`: payment data boundary and webhook trust model updates.
- `docs/05_quality`: dunning/grace test matrix and CI gates.

## 15) Rollout and migration readiness

- Stage rollout by tenant cohort: internal -> low-risk -> full.
- Backfill existing `payment_failed` tenants to consistent grace metadata before full rollout.

## 16) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 | AC-1, AC-2 | S1.1, S1.2 | `tests/unit/domain/test_billing_transitions.py`, `tests/integration/test_billing_grace.py` | `docs/01_architecture/billing_lifecycle.md`, `docs/03_runbooks/payment_failure.md` |
| FR-2 | AC-1 | S2.1 | `tests/unit/services/test_dunning_scheduler.py`, `tests/integration/test_reminder_dedupe.py` | `docs/02_product/dunning_ux.md`, `docs/05_quality/billing_test_matrix.md` |
| FR-3 | AC-3 | S3.1 | `tests/contract/test_billing_status.py`, `web/tests/e2e/billing-recovery.spec.ts` | `docs/02_product/billing_recovery_ux.md` |

## 17) Definition of feature done

This feature is complete when:

- [ ] All acceptance criteria (AC-1, AC-2, AC-3) pass in CI.
- [ ] All test layers (unit/integration/contract/e2e) are green.
- [ ] Documentation updates across docs/01-05 are merged.
- [ ] Rollout gates from §15 are satisfied.
- [ ] No open questions remain in §18.

## 18) Open questions and decision log

### Open questions
- Should first grace reminder send immediately on failure or at D-3 only?

### Decision log
- 2026-03-05 — Keep support contact mandatory in all payment-friction views.
