# Feature Specification — <Feature Name>

**Date:** <YYYY-MM-DD>
**Status:** <Draft | Planned | Approved | Implemented>
**Owners:** <Product Owner>, <Engineering Owner>
**Related docs:**
- <planning-index.md>
- <implementation-plan.md>
- <policy-decisions.md> (if applicable)

---

## 1) Purpose

Describe the problem and intended business outcome in 3-6 sentences.

- Problem: <what is broken/missing>
- Outcome: <what success looks like>
- Non-goal: <what this feature is explicitly not trying to solve>

## 2) Current state audit

Before specifying changes, audit the existing implementation to prevent stale assumptions:

### Existing implementations
List every existing UI, API endpoint, data model, or service that this feature touches or replaces.
For each, note the file path, the API it uses, and any differences from what you expect.

- <file/component>: <what it does> — API: <endpoint> — Notes: <any surprises>

**Why this matters:** Features that move, replace, or extend existing functionality often have
duplicate implementations, legacy patterns, or unexpected dependencies. Discovering these during
implementation rather than spec review leads to rework and missed functionality.

### Navigation and link impact
Search the codebase for all links, redirects, and URL references that point to pages or tabs
being moved, renamed, or removed. Include source file, line, current target, and required new target.

| Source file | Current link target | New link target |
|---|---|---|
| `<file:line>` | `<current URL>` | `<new URL or "remove">` |

### Existing test impact
Search test files (E2E, integration, contract) for references to pages, URLs, or behaviors that
will change. List files, occurrence counts, and required updates.

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `<file>` | `<URL or assertion>` | <N> | `<what to change>` |

### Existing behaviors affected by scope change
List behaviors that exist today and will change meaning, scope, or trigger conditions under this
feature. For each, state the current behavior, the new behavior, and whether this needs an explicit
decision.

- <behavior>: Current: <how it works now>. New: <how it should work>. Decision needed: <yes/no>

---

## 3) Scope

### In scope
- <capability A>
- <capability B>

### Out of scope
- <non-goal A>
- <non-goal B>

### API convention check
Verify the project's conventions before writing endpoint tables or response examples. Check the
actual codebase for each of the following — do not assume defaults or copy from the template.

- **Endpoint prefix convention:** <e.g., "unprefixed tenant routes: /drafts, /keywords, /pipeline/*">
- **Router namespace for this feature's endpoints:** <e.g., "/admin/configuration/" — verify by reading the actual router file>
- **HTTP methods for CRUD:** <e.g., "POST for create, GET for read, PUT for full replace, PATCH for partial update — verify existing similar endpoints">
- **Non-auth error envelope shape:** <paste the actual shape from the project's error helper, e.g., `{ "detail": { "code": ..., "message": ..., "details": {} } }`>
- **Auth error shape:** <paste the actual shape, e.g., `{ "detail": "Admin authentication required" }` — often a plain string, not structured>

**Why this matters:** Response examples in the spec become the source of truth for contract tests.
If the spec uses a different envelope shape than the codebase actually produces, every contract
test written from the spec will be wrong.

### Phase boundaries (if multi-phase)

If the in-scope work spans multiple delivery phases, list what ships in each phase and why the
boundary exists. This prevents scope ambiguity during implementation.

- **Phase 1 (MVP):** <capabilities shipping first> — rationale: <why this subset>
- **Phase 2:** <deferred capabilities> — rationale: <dependency or complexity reason>

**Deferred phase tracking:** Each phase beyond Phase 1 MUST have a corresponding `phase<N>_idea.md` file in the feature directory (see `feature_templates/idea-template.md`). This ensures deferred work is discoverable by future planning sessions and not lost as invisible prose inside this spec.

## 4) Product principles and constraints

List the durable rules this feature must respect.

- <principle 1>
- <principle 2>
- <security/compliance constraint>

### Anti-patterns

List implementation approaches that are explicitly wrong for this feature. These guard against
plausible-but-incorrect shortcuts that an implementer (human or AI) might take. Each entry should
name the anti-pattern and explain why it's wrong in this context.

- **Do not** <wrong approach> — because <why it's wrong>.
- **Do not** <wrong approach> — because <why it's wrong>.

## 5) Assumptions and dependencies

Call out every external or cross-team dependency explicitly.

- Dependency: <service/team/system>
  - Why required: <reason>
  - Status: <planned | implemented | blocked>
  - Risk if missing: <impact>

## 6) Actors and roles

- Primary actor(s): <user/admin/system>
- Role model: <RelyLoop MVP1–MVP3: single-tenant, no auth (write `N/A`). MVP4+: `viewer` / `runner` / `tenant_admin` (per-tenant) + `platform_admin` (cross-tenant) per umbrella §18.>
- Permission boundaries: <who can do what>

### Authorization

For MVP1–MVP3 (single-tenant, no auth per [`docs/01_architecture/tech-stack.md` §"Canonical release matrix"](../../../01_architecture/tech-stack.md)): write `N/A — single-tenant install, no auth surface`.

For MVP4+ (auth lands): author an RBAC matrix mapping each endpoint to allow/deny across roles `viewer / runner / tenant_admin / platform_admin` (per umbrella §18) with the enforcement mechanism (guard function / dependency) named per row.

### Audit events

For MVP1 (no `audit_log` table yet per [`docs/01_architecture/data-model.md` §"Reserved for later releases"](../../../01_architecture/data-model.md)): write `N/A — audit_log lands at MVP2`.

For MVP2+: list every state-mutating endpoint or service function this spec adds, with the event_type it emits, the metadata fields, and the visibility (tenant-visible / admin-only / system). Emission must be atomic — `audit_log` INSERT inside the same transaction as the primary mutation, before `db.commit()`. Metadata must contain no credentials, tokens, or PII beyond display-name strings.


## 7) Functional requirements

Use stable requirement IDs and explicit requirement strength.

### FR-1: <name>
- Requirement:
  - The system **MUST** <required behavior>.
  - The system **SHOULD** <recommended behavior>.
  - The system **MAY** <optional behavior>.
- Notes: <domain/business rule context>

### FR-2: <name>
- Requirement:
  - The system **MUST** <required behavior>.
- Notes: <context>

(Repeat as needed)

## 8) API and data contract baseline

### 7.1 Endpoint surface (if applicable)

Use an endpoint table with enough detail that the implementation plan can reference it directly.
At minimum, include the method, path, purpose, and key error codes. For complex features, include
request/response shape summaries.

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `POST` | `/<resource>` | <purpose> | `ERROR_CODE` (4xx) |
| `GET` | `/<resource>/{id}` | <purpose> | `401`, `404` |

Note: Use the project's established endpoint prefix convention (see §3 API convention check above).
Do not assume `/v1/` — verify against existing routers.

### 7.2 Contract rules
- Error body **MUST** include machine-readable `code`.
- Status codes **MUST** be deterministic per scenario.
- Cross-tenant unauthorized access **MUST** follow anti-enumeration policy.

### 7.3 Response examples

Provide at least one success and one failure example for each critical endpoint. Include the HTTP
status code and full response body shape.

**IMPORTANT:** Do not invent an error envelope shape. Copy the exact shape from the project's
error helper (identified in §3 API convention check). Auth errors and non-auth errors often have
different shapes — provide separate examples for each if both apply.

Success example:
```json
{
  "id": "uuid",
  "field": "value",
  "status": "active"
}
```

Non-auth failure example (use actual project envelope from §3 convention check):
```json
<paste the actual error envelope shape here — do not guess>
```

Auth failure example (use actual project envelope from §3 convention check):
```json
<paste the actual auth error shape here — often different from non-auth>
```

Include the HTTP status and any anti-enumeration or security notes (e.g., cross-tenant access
returns 404 with same shape as genuinely missing resource).

### 7.4 Enumerated value contracts (required for any feature with filters, status badges, sort keys, or dropdowns)

For every field the backend validates against a fixed allowlist — filter query params, sort keys, status enums, tier/bucket/category labels, role strings, platform identifiers — list the **exact values** the router accepts and cite the backend source-of-truth file. The frontend's `<select>` options, filter chips, badge variants, and URL-encoded query values MUST match these values character-for-character.

**Why this matters:** Frontend option lists drift the most when writers (human or AI) invent plausible labels ("mid" tier, "drafting" bucket) without grepping the backend allowlist. These mismatches aren't caught by TypeScript, lint, or unit tests — they surface as 422 VALIDATION_ERROR responses or silent zero-result filters in production. Every option list in the spec should be traceable back to a concrete backend definition.

Format:

| Field | Accepted values (exact) | Backend source of truth | Frontend call site(s) |
|---|---|---|---|
| `?engine_type` | `elasticsearch`, `opensearch` | `backend/adapters/protocol.py` (`EngineType` `Literal[...]`) | cluster filter dropdown in `<path>` |
| `?status` (studies) | `queued`, `running`, `completed`, `cancelled`, `failed` | `backend/db/models/study.py` (`StudyStatus` `Literal[...]` or DB CHECK) | studies filter chip in `<path>` |
| `?status` (proposals) | `pending`, `pr_opened`, `pr_merged`, `rejected` | `backend/db/models/proposal.py` (`ProposalStatus`) | proposals filter chip in `<path>` |

**Rules:**
- Labels shown to the user (e.g., "Nano (<10k)") may differ from the wire value (`nano`) — the wire value is the contract, the label is UX. Spell out both when they diverge.
- If the backend allowlist is a Python `frozenset`, `StrEnum`, or `Literal[...]` type, cite the exact symbol name so implementers can grep it.
- If a threshold (e.g., "100k followers") appears in a label, it must match the backend classifier's actual cutoff. Read the classifier, don't guess.
- When the backend adds a new value, the spec (and any frontend option list) must be updated in the same PR — treat missing values the same as wrong values.

### 7.5 Error code catalog (if API-heavy)

List all machine-readable error codes this feature introduces. Each code should be stable (never
renamed), documented with its HTTP status, and mapped to a user-facing message strategy.

| Code | HTTP Status | Meaning |
|------|-------------|---------|
| `<FEATURE_ERROR_NAME>` | `<4xx>` | `<description>` |

## 9) Data model and state transitions

### New/changed entities

For each new or modified table, list columns with types and constraints. This level of detail
prevents ambiguity in the implementation plan and ensures the migration is correct on first pass.

**IMPORTANT:** When referencing existing columns or fields (e.g., "store data in `job_runs.metadata`"),
verify the column actually exists by reading the current ORM model. Do not assume column names from
memory or convention — check the model file. If the column does not exist, either use an existing
column that fits or explicitly call for a migration to add it.

**New table: `<table_name>`**
- `id` (UUID PK, UUIDv7)
- `<column>` (`<type>`, <constraints: nullable, default, unique, indexed>)
- `<column>` (`<type>`, <constraints>)
- `created_at` (timestamptz, default now)
- `deleted_at` (timestamptz, nullable) — for soft-delete on user-facing tables; omit for append-only tables

> **RELYLOOP MVP1–MVP3:** do NOT include `tenant_id` or `created_by` columns. RelyLoop is single-tenant + no auth through MVP3 per [`docs/01_architecture/data-model.md` §"Reserved for later releases"](../../../01_architecture/data-model.md). MVP4 adds `tenants`, `users`, and the per-table `tenant_id` migration with a `default`-tenant backfill.

**Modified table: `<existing_table>`**
- Add `<column>` (`<type>`, <constraints>) — <purpose>
- Add `<column>` (`<type>`, <constraints>) — <purpose>

### Required invariants
- <uniqueness constraints, ownership rules, minimum-count guards, etc.>

### State transitions
- <allowed transitions: `state_a -> state_b -> state_c`>
- <guardrails: what prevents invalid transitions>

### Idempotency/replay behavior (if event-driven)
- <how duplicate/out-of-order events are handled>

## 10) Security, privacy, and compliance

- Threats: <top 3-5 threat scenarios>
- Controls: <mitigation mapping>
- Secrets/key handling: <storage + rotation>
- Auditability: actor, reason, target, timestamp requirements
- Data retention/deletion/export impact: <if applicable>

## 11) UX flows and edge cases

### Information architecture

Before describing flows, document where the new UI lives in the product's navigation hierarchy and
how it relates to existing pages. This prevents features that are functionally correct but
undiscoverable, mislabeled, or confusing in context.

- **Navigation placement:** Where does the user access this feature? (sidebar link, tab within an
  existing page, modal triggered from a button, settings subsection, etc.)
- **Labeling taxonomy:** What are the user-facing labels for pages, tabs, sections, buttons, and
  form fields? Labels should match the user's mental model — use the same terminology the user
  already sees elsewhere in the product. List each label with its purpose.
- **Content hierarchy:** Within the page/section, what is the visual priority order? (e.g.,
  "status summary card at top, then configuration form, then history table"). State which elements
  are primary (always visible) vs. secondary (collapsed, behind a tab, or progressive disclosure).
- **Progressive disclosure:** If this feature has complexity that should be revealed gradually,
  describe what the user sees initially vs. what they see after interaction. (e.g., "Show summary
  by default; expand to show full history on click.")
- **Relationship to existing pages:** Does this feature replace, extend, or sit alongside existing
  UI? If extending, describe which existing page/tab it lives within and why.

### Tooltips and contextual help

For every non-obvious UI element (settings, status indicators, limits, technical terms, or actions
with consequences), specify the contextual help the user needs to understand and use the feature
confidently.

| Element | Tooltip / help text | Trigger | Placement |
|---------|-------------------|---------|-----------|
| `<field label or button>` | `<text the user sees on hover/focus>` | `hover` / `focus` / `info icon click` | `top` / `right` / `inline helper text` |

**Guidelines for tooltip content:**
- Answer "what does this do?" or "why would I change this?" — not just the field name restated.
- Use concrete examples where possible (e.g., "e.g., 'vegan food brands'" not "enter a keyword").
- For limits/thresholds, state the consequence of the setting (e.g., "Creators below this score
  won't appear in your drafts queue").
- For destructive or irreversible actions, the tooltip should state the consequence clearly.
- Keep tooltip text under ~120 characters. For longer explanations, use an inline helper text
  pattern (text below the field) or a "Learn more" link.

### Primary flows
1. <flow name>
2. <flow name>

### Edge/error flows
- <error flow A>
- <error flow B>
- <support/recovery flow>

## 12) Given/When/Then acceptance criteria

Each criterion should be independently testable and observable. For complex scenarios, include
concrete example values so that implementers can use them directly in test assertions without
interpreting intent.

### AC-1: <scenario title>
- Given <precondition>
- When <action/event>
- Then <observable result>
- Example values (if non-trivial):
  - Input: `<concrete input value or payload>`
  - Expected: `<concrete expected output, status code, or state>`

### AC-2: <scenario title>
- Given <precondition>
- When <action/event>
- Then <observable result>

(Include success, failure, authorization, and recovery scenarios. Add example values to any
criterion where the inputs, thresholds, or expected outputs could be ambiguous.)

## 13) Non-functional requirements

- Performance: <latency/throughput targets>
- Reliability: <error budget/SLO impact>
- Operability: <logging/metrics/alerts>
- Accessibility/usability: <if UI-facing>

## 14) Test strategy requirements (spec-level)

Minimum required coverage by layer:

- Unit tests (`backend/tests/unit/`): <logic to isolate>
- Integration tests (`backend/tests/integration/`): <DB/workflow transitions>
- Contract tests (`backend/tests/contract/`): <status/code/shape>
- E2E tests (`web/tests/e2e/`): <critical journeys and role gating>

## 15) Documentation update requirements

Define canonical doc updates required for feature completion.

- `docs/01_architecture`: <what must be updated>
- `docs/02_product`: <what must be updated>
- `docs/03_runbooks`: <what must be updated>
- `docs/04_security`: <what must be updated>
- `docs/05_quality`: <what must be updated>

## 16) Rollout and migration readiness

- Feature flags / staged rollout: <strategy>
- Migration/backfill expectations: <if schema changes>
- Operational readiness gates: <runbooks, alerts, on-call>
- Release gate: <what must be green before ship>

## 17) Traceability matrix

Map each FR to implementation and validation artifacts.

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 | AC-1, AC-3 | <story IDs> | <test paths> | <doc paths> |
| FR-2 | AC-2 | <story IDs> | <test paths> | <doc paths> |

## 18) Definition of feature done

This feature is complete when:

- [ ] All acceptance criteria (AC-*) pass in CI.
- [ ] All test layers (unit/integration/contract/e2e) are green.
- [ ] Documentation updates across docs/01-05 are merged.
- [ ] Rollout gates from §16 are satisfied.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

All open questions must be resolved before creating the implementation plan. Questions that remain
open at plan-creation time block story-level design — the plan cannot assign concrete interfaces,
error codes, or test assertions against unresolved decisions.

- <question> — Owner: <name> — Due: before implementation plan

### Decision log
- <YYYY-MM-DD> — <decision> — <rationale>
