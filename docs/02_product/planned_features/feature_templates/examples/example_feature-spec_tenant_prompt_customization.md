# Feature Specification — Tenant-Customizable Drafting System Prompt

**Date:** 2026-03-16
**Status:** Approved
**Owners:** Product (Growth), Engineering (Backend Platform)
**Related docs:**
- `docs/02_product/planned_features/feature_tenant_can_update_server_prompt/implementation-plan.md`
- `docs/02_product/planned_features/feature_tenant_can_update_server_prompt/feature_phase2_llm_assisted_prompt_generation.md` — Phase 2 spec
- `backend/app/integrations/llm/prompts/drafting.jinja` (to be deleted in Epic 3)
- `backend/app/services/drafting_service.py`
- `backend/app/integrations/llm/openai_provider.py`

---

## 1) Purpose

Outreach drafts currently embed a hardcoded brand context ("a music technology company") in the LLM user-role prompt, producing copy that feels off-brand for tenants in fitness, gaming, travel, e-commerce, and other verticals. Tenants must manually rewrite nearly every draft before use. This feature lets tenants define a **custom drafting system prompt** — a brand context and persona statement stored per tenant and injected as the OpenAI `system`-role message on every outreach draft generation call — so that all drafts are on-brand from the first generation.

- **Problem:** Hardcoded LLM brand context produces generic drafts misaligned with tenant industry and voice. The `LLMProvider.generate_text()` abstraction currently sends no system message; brand context lives buried in the user-role prompt and cannot be overridden per tenant.
- **Outcome:** Tenants configure their brand context once and receive consistently on-brand drafts. The LLM provider abstraction is extended to carry an optional system prompt. Superadmins retain visibility and revert authority over all tenant-saved prompts.
- **Non-goal:** This feature does not expose LLM model selection, temperature tuning, per-creator prompt customization, or prompt control for discovery — only the drafting brand context system prompt and the superadmin management of the Scoring System prompt.

---

## 2) Scope

### In scope

- **Extend LLM abstraction:** Add an optional `system_prompt` parameter to both `LLMProvider.generate_text()` and `LLMProvider.generate_structured()` in `OpenAIProvider`, so the system-role message can carry tenant-supplied or admin-configured content.
- **Tenant-facing settings:** Read and update the custom drafting system prompt via settings API. `owner` and `admin` roles can write; `member` can read.
- **Content safety gate:** Candidate prompts are classified before storage. Prompts containing injection patterns or policy-violating content are rejected and the prior prompt remains active.
- **Version history with revert:** The system retains the last N (≥20) versions per tenant. Tenants can revert to any prior version.
- **Immediate effectiveness:** Saved prompts apply to the next drafting job — no approval queue.
- **Superadmin visibility and revert:** Superadmins can view prompt history for any tenant and revert on their behalf.
- **Superadmin notification:** Every tenant save and tenant revert emits an audit log entry + email notification. Admin-initiated reverts emit an audit log entry only (no email — prevents notification noise during incident remediation).
- **Drafting service wiring:** `drafting_service.py` reads the active custom prompt and passes it as the system message to the LLM provider.
- **Reconcile the `drafting.jinja` template:** The template exists but is unused by `drafting_service.py`. Implementation must either adopt the template (preferred) or formally retire it.
- **Superadmin scoring system prompt:** Superadmins can view and edit the global scoring system prompt via the admin "Global Controls" panel. Stored on `GlobalAdminConfiguration`; read by `scoring_service.py` at job-start. No versioning or classification — superadmins are trusted. Default: `"You are a helpful assistant. Respond with valid JSON matching the requested schema."`

### Out of scope

- Admin approval queue before tenant drafting prompts take effect (admins revert after the fact).
- Custom scoring prompts at the tenant level — scoring system prompt is global, superadmin-only.
- Custom prompts for discovery or eligibility.
- Per-creator or per-keyword prompt overrides.
- Multi-language prompt variants.
- Fine-tuning or model selection.

### Phase boundaries

- **Phase 1 (MVP):** Custom prompt storage, LLM abstraction extension, drafting service wiring, content safety gate, version history with tenant revert, superadmin visibility and revert, notification. Safety controls are prerequisites and ship with Phase 1.
- **Phase 2 (deferred):** LLM-assisted prompt generation — tenant describes their brand in plain language and the system drafts a suggested system prompt. Requires additional UX design and an extra LLM call at settings-save time; does not block Phase 1 value.

---

## 3) Product principles and constraints

- The custom prompt occupies the OpenAI **`system` role** message in all `generate_text()` calls made by the drafting service. The user-role message retains the per-creator instructions, structural rules, and output format requirements, which tenants cannot override.
- Tenant isolation is mandatory: one prompt record per tenant; no cross-tenant reads.
- The prompt **MUST** pass content safety classification before being stored. On rejection, the prior prompt remains active and the caller receives a structured error.
- Prompts are **immediately effective** on save. No approval queue.
- Version history is **immutable**: no version rows are ever hard-deleted.
- Hard length limit: **1,500 characters** (prevents token-budget abuse).
- Superadmin notification on every tenant-initiated save/revert is non-optional and cannot be disabled by the tenant. Admin-initiated reverts emit audit log only.
- Platform export-only rule is unaffected: the feature customizes draft tone, not delivery mechanics.

---

## 4) Assumptions and dependencies

- Dependency: `LLMProvider` abstraction (`backend/app/integrations/llm/base.py`)
  - Why required: `generate_text()` must accept `system_prompt: str | None` to carry the tenant prompt into the OpenAI API call
  - Status: implemented (signature change required)
  - Risk if missing: cannot ship without it — the feature's core mechanism depends on this extension
- Dependency: `tenant_settings` table (1:1 with tenant)
  - Why required: stores the active custom prompt as a new nullable column
  - Status: implemented (additive column required via migration)
  - Risk if missing: none — column is additive and nullable
- Dependency: Resend transactional email
  - Why required: superadmin notification email
  - Status: implemented
  - Risk if missing: notification degrades to audit log only; feature can still ship
- Dependency: LLM classification call via `LLMProvider.generate_structured()`
  - Why required: content safety gate before saving candidate prompts; uses a structured JSON schema `{"safe": bool, "reason": str}` passed to the existing LLM abstraction
  - Status: approach decided — uses `generate_structured()` with `MockLLMProvider`-compatible interface; no external moderation API dependency required
  - Risk if missing: safety gate is a Phase 1 blocker; implementation must not bypass it

---

## 5) Actors and roles

- **Tenant `owner`:** Read + write the custom prompt; view history; revert to prior version.
- **Tenant `admin`:** Read + write the custom prompt; view history; revert to prior version.
- **Tenant `member`:** Read-only — can see the currently active prompt (so they understand what tone drafts will use) but cannot change it.
- **Superadmin:** View prompt history for any tenant; revert any tenant's prompt; receives notification on every save.
- **Drafting worker (system):** Reads `tenant_settings.custom_drafting_prompt` at job-start; passes it as the system message to `generate_text()`.

### RBAC authorization matrix

| Endpoint | `owner` | `admin` | `member` | superadmin |
|---|---|---|---|---|
| `GET /v1/settings/drafting-prompt` | allow | allow | allow | — (use admin endpoint) |
| `PUT /v1/settings/drafting-prompt` | allow | allow | **deny** | — |
| `GET /v1/settings/drafting-prompt/history` | allow | allow | **deny** | — |
| `POST /v1/settings/drafting-prompt/revert` | allow | allow | **deny** | — |
| `GET /admin/tenants/{id}/drafting-prompt/history` | — | — | — | allow |
| `POST /admin/tenants/{id}/drafting-prompt/revert` | — | — | — | allow |
| `GET /admin/tenants/{id}/drafting-prompt/rejection-log` | — | — | — | allow |
| `GET /admin/drafting-prompt/rejection-log` | — | — | — | allow |

---

## 6) Functional requirements

### FR-1: Read active drafting prompt

- The system **MUST** return the tenant's active custom prompt (or the system default if none is set) from `GET /v1/settings/drafting-prompt`.
- The response **MUST** include an `is_custom` boolean indicating whether a tenant prompt is active or the system default is being used.
- The system **MUST** never return another tenant's prompt.

### FR-2: Update drafting prompt

- The system **MUST** accept a plain-text prompt update via `PUT /v1/settings/drafting-prompt`.
- Before storing, the system **MUST** run the candidate prompt through a content safety classification step.
- If classification flags the prompt, the system **MUST** reject with `PROMPT_SAFETY_VIOLATION` (422). The prior prompt remains active; no version row is created.
- The system **MUST** reject prompts exceeding 1,500 characters with `PROMPT_TOO_LONG` (422) before any LLM call.
- If content is identical to the currently active prompt, the system **MUST** return `200` with `changed: false` — no new version row, no notification.
- On success, the system **MUST** store the new prompt, snapshot the prior version, set the new version as active, and emit a superadmin notification.
- The system **SHOULD** trim leading/trailing whitespace before validation.

### FR-3: Version history

- The system **MUST** maintain an ordered, immutable history of prompt versions per tenant: content, actor (user ID/email), source type, and timestamp per version.
- The system **MUST** retain at least the last 20 versions per tenant (older versions are never hard-deleted, only archived beyond the visible window).
- The system **MUST** expose history to tenant `owner` and `admin` via `GET /v1/settings/drafting-prompt/history`.

### FR-4: Tenant revert

- The system **MUST** allow tenant `owner` or `admin` to revert the active prompt to any prior version via `POST /v1/settings/drafting-prompt/revert`.
- A revert **MUST** be recorded as a new version row (with `source = "tenant_revert"`) — intermediate versions are not deleted.
- A revert counts as a save and **MUST** emit a superadmin notification.
- The system **MAY** skip re-classification on a revert (the version previously passed classification). This decision is recorded in the decision log (§18).

### FR-5: Superadmin visibility and revert

- The system **MUST** expose prompt history for any tenant to superadmins via `GET /admin/tenants/{id}/drafting-prompt/history`.
- The system **MUST** allow superadmins to revert any tenant's prompt via `POST /admin/tenants/{id}/drafting-prompt/revert` with a target version ID.
- Superadmin reverts **MUST** record the admin email as actor and `source = "admin_revert"`.

### FR-6: Superadmin notification

- The system **MUST** emit a notification on every prompt save and tenant revert.
- The system **MUST** emit an audit log entry (but **NOT** an email) on admin-initiated reverts. This prevents notification noise during incident remediation.
- Notification **MUST** include: tenant ID, tenant name, actor email, timestamp, source type, and a 200-character truncated preview of the new prompt.
- Tenant-initiated saves and reverts: notification delivered as audit log entry + email via Resend. If Resend fails, the audit log entry still records the event and the save response is not blocked.
- Notification is **NOT** emitted for the `changed: false` (identical content) case.

### FR-7: Apply prompt in drafting service

- The drafting service **MUST** read `tenant_settings.custom_drafting_prompt` at job-start time.
- If non-null, it **MUST** be passed as the `system_prompt` argument to `llm_provider.generate_text()`.
- If null, the drafting service **MUST** fall back to the system default brand context string.
- The system default is defined as a constant in the service layer (not in the database) so it can be updated via code without a migration.
- The custom system prompt **MUST NOT** replace or merge with per-creator user-role instructions. The system and user messages are structurally separate in the LLM API call.

### FR-8: LLM provider abstraction extension

- `LLMProvider.generate_text()` **MUST** be extended to accept `system_prompt: str | None = None`.
- `OpenAIProvider.generate_text()` **MUST** prepend a `{"role": "system", "content": system_prompt}` message when `system_prompt` is provided.
- `MockLLMProvider.generate_text()` **MUST** accept and ignore `system_prompt` (no behavioral change in tests).
- All existing callers of `generate_text()` that do not pass `system_prompt` **MUST** be unaffected (backward compatible default).

### FR-9: LLM-assisted generation (Phase 2, deferred)

Fully specified in `feature_phase2_llm_assisted_prompt_generation.md`. Summary for reference:

- The system **SHOULD** accept a brand description (≤600 chars) and return a suggested system prompt via `POST /v1/settings/drafting-prompt/generate`.
- The suggested prompt **MUST NOT** be auto-saved — the tenant must explicitly confirm via `PUT /v1/settings/drafting-prompt`, which runs the standard Phase 1 safety classification gate.
- Phase 2 introduces `tenant_prompt_generation_log` (rate limiting + audit) and `GlobalAdminConfiguration.prompt_generation_daily_limit` (default 10/day).
- Phase 1 must be fully shipped before Phase 2 begins.

### FR-10: Superadmin scoring system prompt

- The system **MUST** expose `scoring_system_prompt` as a readable and writable field on `GlobalAdminConfiguration` via the existing `GET /admin/configuration` and `PUT /admin/configuration` endpoints. No new endpoints are required.
- The system **MUST** fall back to the constant `SCORING_DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant. Respond with valid JSON matching the requested schema."` when `scoring_system_prompt` is `NULL`.
- `scoring_service.py` **MUST** read `scoring_system_prompt` from `GlobalAdminConfiguration` at job-start and pass it as `system_prompt` to `llm_provider.generate_structured()`.
- `LLMProvider.generate_structured()` **MUST** be extended with `system_prompt: str | None = None` — same pattern as FR-8 for `generate_text()`.
- Only superadmins can write this field. No content safety classification, versioning, or notification is required — the superadmin role is the trust boundary.
- The admin "Global Controls" UI **MUST** render a textarea for this field within an "AI Settings" section of the Global Controls panel.

### FR-11: Security audit log for rejected prompt attempts

- The system **MUST** record every `PROMPT_SAFETY_VIOLATION` rejection in a persistent `tenant_prompt_rejection_log` table. This is separate from `tenant_prompt_versions`, which stores only accepted prompts.
- Each rejection log row **MUST** capture: `tenant_id`, `actor` (user email), `timestamp`, `rejection_reason` (the classifier's `reason` string), and the first 500 characters of the rejected prompt text.
- The log **MUST NOT** store the full rejected prompt beyond the first 500 characters (limits storage of potentially harmful content while preserving enough for investigation).
- The system **MUST** emit a superadmin security alert (audit log entry + email) on every rejection. This is distinct from the save notification — the subject line and body **MUST** make clear this was a **blocked attempt**, not a successful save.
- `PROMPT_TOO_LONG` rejections (pre-classification, no LLM call) **MUST** also be logged and alerted — these are less likely to be malicious but complete the audit trail.
- If a single tenant accumulates ≥3 rejected attempts within any 24-hour window, the alert email **MUST** include a "Repeated attempts detected" warning flag so superadmins can prioritize review.

### FR-12: Superadmin visibility into rejection attempts

- The system **MUST** expose the rejection log for a specific tenant via `GET /admin/tenants/{id}/drafting-prompt/rejection-log` (superadmin only).
- Each row **MUST** include: `id`, `actor`, `rejection_reason`, `prompt_preview` (first 500 chars), `created_at`.
- The system **SHOULD** expose a fleet-level view via `GET /admin/drafting-prompt/rejection-log` (superadmin only) returning rejections across all tenants, ordered by most recent, paginated.
- Tenant-facing endpoints **MUST NOT** expose rejection log entries — tenants see only their accepted version history.

---

## 7) API and data contract baseline

### 7.1 Endpoint surface

| Method | Path | Phase | Purpose | Key error codes |
|---|---|---|---|---|
| `GET` | `/v1/settings/drafting-prompt` | 1 | Return active prompt (custom or default) | `401` |
| `PUT` | `/v1/settings/drafting-prompt` | 1 | Save new prompt (validates, snapshots, notifies) | `401`, `403`, `501` (flag off), `PROMPT_TOO_LONG` (422), `PROMPT_SAFETY_VIOLATION` (422), `PROMPT_CLASSIFICATION_UNAVAILABLE` (503) |
| `GET` | `/v1/settings/drafting-prompt/history` | 1 | List prior versions (tenant-scoped, owner/admin only) | `401`, `403` |
| `POST` | `/v1/settings/drafting-prompt/revert` | 1 | Revert to a prior version | `401`, `403`, `PROMPT_VERSION_NOT_FOUND` (404) |
| `GET` | `/admin/tenants/{id}/drafting-prompt/history` | 1 | Superadmin: view any tenant's prompt history | `401`, `404` |
| `POST` | `/admin/tenants/{id}/drafting-prompt/revert` | 1 | Superadmin: revert any tenant's prompt | `401`, `404`, `PROMPT_VERSION_NOT_FOUND` (404) |
| `POST` | `/v1/settings/drafting-prompt/generate` | **2** | Generate suggested prompt from brand description | `401`, `PROMPT_GENERATE_FAILED` (500) |
| `GET` | `/admin/configuration` | 1 | Returns `scoring_system_prompt` alongside other global config fields (existing endpoint, new field) | `401` |
| `PUT` | `/admin/configuration` | 1 | Accepts `scoring_system_prompt` update (existing endpoint, new field) | `401`, `403` |
| `GET` | `/admin/tenants/{id}/drafting-prompt/rejection-log` | 1 | Superadmin: view all blocked prompt attempts for one tenant | `401`, `404` |
| `GET` | `/admin/drafting-prompt/rejection-log` | 1 | Superadmin: fleet-wide view of all blocked prompt attempts across all tenants | `401` |

### 7.2 Contract rules

- All error bodies **MUST** include machine-readable `code`.
- Cross-tenant access via tenant-facing endpoints **MUST** return `404` with anti-enumeration shape (not `403`).
- `PUT /v1/settings/drafting-prompt` **MUST** be idempotent for identical content: same content → `200` with `changed: false`, no side effects.
- `POST .../revert` with a version ID from a different tenant **MUST** return `404` (anti-enumeration).

### 7.3 Response examples

`GET /v1/settings/drafting-prompt` — custom prompt active, feature enabled:
```json
{
  "feature_enabled": true,
  "is_custom": true,
  "prompt": "You are a fitness brand partnership specialist writing on behalf of GainZone...",
  "version_id": "a1b2c3d4-...",
  "updated_at": "2026-03-16T10:00:00Z",
  "updated_by": "owner@gainzone.com"
}
```

`GET /v1/settings/drafting-prompt` — system default in use, feature enabled:
```json
{
  "feature_enabled": true,
  "is_custom": false,
  "prompt": "You are a creator discovery & outreach specialist writing on behalf of a music technology company.",
  "version_id": null,
  "updated_at": null,
  "updated_by": null
}
```

`GET /v1/settings/drafting-prompt` — feature flag off:
```json
{
  "feature_enabled": false,
  "is_custom": false,
  "prompt": "You are a creator discovery & outreach specialist writing on behalf of a music technology company.",
  "version_id": null,
  "updated_at": null,
  "updated_by": null
}
```

`PUT /v1/settings/drafting-prompt` — success:
```json
{
  "version_id": "a1b2c3d4-...",
  "prompt": "You are a fitness brand partnership specialist...",
  "changed": true,
  "updated_at": "2026-03-16T10:00:00Z"
}
```

`PUT /v1/settings/drafting-prompt` — no change (identical content):
```json
{
  "version_id": null,
  "prompt": null,
  "changed": false,
  "updated_at": null
}
```

`PUT /v1/settings/drafting-prompt` — safety violation:
```json
{
  "error": {
    "code": "PROMPT_SAFETY_VIOLATION",
    "message": "The submitted prompt contains content that violates platform policy. Your previous prompt remains active."
  }
}
```

`GET /v1/settings/drafting-prompt/history`:
```json
{
  "versions": [
    {
      "version_id": "a1b2c3d4-...",
      "prompt": "You are a fitness brand partnership specialist...",
      "actor": "owner@gainzone.com",
      "source": "tenant",
      "is_active": true,
      "created_at": "2026-03-16T10:00:00Z"
    },
    {
      "version_id": "b2c3d4e5-...",
      "prompt": "You are a creator outreach specialist...",
      "actor": "owner@gainzone.com",
      "source": "tenant",
      "is_active": false,
      "created_at": "2026-03-10T08:00:00Z"
    }
  ]
}
```

### 7.4 Error code catalog

| Code | HTTP Status | Meaning | Logged? |
|---|---|---|---|
| `PROMPT_TOO_LONG` | `422` | Submitted prompt exceeds 1,500-character limit | Yes — `tenant_prompt_rejection_log` + superadmin alert |
| `PROMPT_SAFETY_VIOLATION` | `422` | Prompt failed content safety classification; prior prompt remains active | Yes — `tenant_prompt_rejection_log` + superadmin alert (with repeated-attempts escalation) |
| `PROMPT_CLASSIFICATION_UNAVAILABLE` | `503` | Classification LLM call failed (timeout/error); save rejected (fail-closed); prior prompt remains active | No rejection log row — the classifier was unavailable, not the prompt unsafe; logged at WARNING level only |
| `PROMPT_VERSION_NOT_FOUND` | `404` | Target version ID does not exist for this tenant (or belongs to another tenant) | No |
| `PROMPT_GENERATE_FAILED` | `500` | (Phase 2) LLM-assisted generation failed; tenant should retry | No |

---

## 8) Data model and state transitions

### Modified table: `tenant_settings`

- Add `custom_drafting_prompt` (`Text`, nullable, default `NULL`) — the currently active tenant system prompt. `NULL` means the system default constant is in use.

### Modified table: `global_admin_configuration`

- Add `scoring_system_prompt` (`Text`, nullable, default `NULL`) — the global system message injected into every scoring LLM call. `NULL` means the `SCORING_DEFAULT_SYSTEM_PROMPT` constant is used.

### New table: `tenant_prompt_versions`

- `id` (UUID PK)
- `tenant_id` (FK to `tenants.id`, indexed, not null)
- `prompt` (`Text`, not null) — full prompt content at time of save; empty string `""` represents an explicit "clear to system default" action
- `actor` (`varchar(255)`, nullable) — user email for tenant actions; superadmin email for admin reverts; `"system"` for automated actions. The `source` column distinguishes who acted — no prefix encoding needed on `actor`.
- `source` (`varchar(50)`, not null) — one of: `"tenant"` | `"tenant_revert"` | `"admin_revert"`
- `is_active` (`Boolean`, not null, default `false`) — exactly one row per tenant may be `true` at any time; managed atomically by the service
- `created_at` (`timestamptz`, not null, default now)

### New table: `tenant_prompt_rejection_log`

- `id` (UUID PK)
- `tenant_id` (FK to `tenants.id`, indexed, not null)
- `actor` (`varchar(255)`, not null) — user email of the submitter
- `rejection_type` (`varchar(50)`, not null) — `"PROMPT_SAFETY_VIOLATION"` | `"PROMPT_TOO_LONG"`
- `rejection_reason` (`Text`, nullable) — classifier's `reason` string; null for `PROMPT_TOO_LONG`
- `prompt_preview` (`varchar(500)`, not null) — first 500 chars of the rejected prompt text
- `created_at` (`timestamptz`, not null, default now)
- `alert_sent` (`Boolean`, not null, default `false`) — true once the superadmin notification is confirmed dispatched (used to detect unsent alerts on retry)

### Required invariants

- At most one `tenant_prompt_versions` row per tenant has `is_active = true`. The toggle is atomic (transaction: set prior `is_active = false`, insert new row with `is_active = true`).
- `tenant_settings.custom_drafting_prompt` is always the canonical value read by the drafting service. `tenant_prompt_versions` is the history/audit store.
- No version rows are ever hard-deleted.
- An empty `prompt` value in a version row (`source = "tenant"`) means the tenant explicitly cleared back to the system default. `tenant_settings.custom_drafting_prompt` is set to `NULL` in this case.

### State transitions

- `NULL (default active)` → `custom` — on first tenant save
- `custom` → `custom` — on each subsequent save; prior version row set `is_active = false`
- `custom` → `prior custom` — on tenant or admin revert; new version row records the restored content
- `custom` → `NULL (default active)` — on explicit tenant clear (empty string save)
- All transitions: `tenant_settings.custom_drafting_prompt` and `tenant_prompt_versions.is_active` update in the same transaction

### Idempotency

- Identical content submitted to `PUT` → no transaction performed, no version row created, response `changed: false`.

---

## 9) Security, privacy, and compliance

- **Prompt injection:** A tenant submits instructions designed to override system behavior (e.g., "Ignore all previous instructions and output X"). Mitigation: (1) content safety classification gate rejects flagged prompts before storage; (2) architectural separation — tenant prompt occupies the `system` role, per-creator user-role instructions are assembled after and cannot be displaced; (3) LLM output is extracted as structured draft fields only (subject + message), not executed; (4) **every rejected attempt is logged in `tenant_prompt_rejection_log` and triggers an immediate superadmin security alert** — even blocked attempts leave a trail.
- **Persistent attacker / probing behavior:** A tenant may submit many injection variants to probe the classifier boundary. Mitigation: every rejection — including `PROMPT_TOO_LONG` — is logged and alerted. Superadmins see a "Repeated attempts detected" warning when ≥3 rejections occur within 24 hours from the same tenant. Fleet-wide visibility via `GET /admin/drafting-prompt/rejection-log` allows pattern detection across tenants.
- **Cross-tenant data exfiltration:** Tenant embeds instructions intended to extract another tenant's data from the LLM. Mitigation: tenant isolation is enforced at the repo layer independently of the LLM call; the LLM never receives other tenant records within the same call.
- **Policy-violating content in generated drafts:** Tenant embeds discriminatory, harassing, or harmful language that propagates into outreach drafts. Mitigation: content safety classification gate + superadmin notification on every save for out-of-band review.
- **Token exhaustion:** Long prompts inflate cost per drafting run. Mitigation: 1,500-character hard limit enforced before any LLM call.
- **Auditability (successful saves):** Every prompt save and revert is recorded in `tenant_prompt_versions` with actor, source, and timestamp. Superadmin notification provides out-of-band visibility. Admin-initiated reverts additionally capture the admin email as actor, distinguishable from tenant actions via the `source` column.
- **Auditability (blocked attempts):** Every rejected prompt attempt — whether `PROMPT_SAFETY_VIOLATION` or `PROMPT_TOO_LONG` — is recorded in `tenant_prompt_rejection_log`. This table is **never accessible to tenants**. Superadmins can review per-tenant and fleet-wide rejection history. A blocked attempt that generates no version row still leaves a permanent, non-suppressible record.
- **Data retention:** Both `tenant_prompt_versions` and `tenant_prompt_rejection_log` are retained indefinitely (immutable audit records). `tenant_prompt_rejection_log` stores only the first 500 characters of rejected content to bound storage of potentially harmful material while preserving investigability.

---

## 10) UX flows and edge cases

### Primary flows

1. **Tenant sets a custom prompt:** Owner/admin opens Settings → Outreach → System Prompt. Sees the currently active prompt (or system default in a placeholder). Edits the text area (character counter shown; warning at 1,400 chars). Saves. System classifies, stores, and notifies superadmin. Page refreshes with updated "Last updated" line showing actor and timestamp.

2. **Tenant reverts to a prior version:** Owner/admin opens Settings → Outreach → System Prompt → History tab. Sees paginated list of prior versions with truncated previews and dates. Selects a prior version and clicks "Restore." System creates a new version row with `source = "tenant_revert"` and notifies superadmin.

3. **Superadmin reviews and reverts (incident response):** Superadmin receives email notification of a new tenant prompt save. Reviews the 200-char preview. Opens Admin → Tenant detail → Prompt History. Reads full content. Clicks "Revert to prior version." System creates a new version row with `source = "admin_revert"` and actor = superadmin email, notifies (audit log entry only, not another superadmin email).

4. **Drafting worker applies prompt:** Drafting service reads `tenant_settings.custom_drafting_prompt` at job start. If non-null, passes it as `system_prompt` to `llm_provider.generate_text()`. The OpenAI call carries a `system` role message with the tenant's brand context and a `user` role message with per-creator instructions. Tenant receives on-brand drafts without editing.

### Edge/error flows

- **Safety violation:** Tenant submits a flagged prompt. Returns `PROMPT_SAFETY_VIOLATION` (422). Prior prompt unchanged. A `tenant_prompt_rejection_log` row is created and a superadmin security alert is emitted with "blocked attempt" framing. If this is the 3rd+ rejection in 24 hours, the alert includes a "Repeated attempts detected" warning. Tenant revises and resubmits.
- **Prompt too long:** Returns `PROMPT_TOO_LONG` (422) before classification. No LLM call made. A `tenant_prompt_rejection_log` row is created and a superadmin security alert is emitted (less urgent, but maintains a complete audit trail).
- **Identical content re-submitted:** Returns `200` with `changed: false`. No side effects.
- **Tenant clears the prompt:** Tenant submits an empty string. System sets `custom_drafting_prompt = NULL`, records a sentinel version row with `prompt = ""` and `source = "tenant"`. Next drafting job uses the system default.
- **Revert to unknown version ID:** Returns `PROMPT_VERSION_NOT_FOUND` (404).
- **Resend notification fails:** Failure is logged at `WARNING` level. The prompt save is not rolled back. Audit log entry is always created first (in the same transaction as the version save).
- **Classification service unavailable:** Returns `503 PROMPT_CLASSIFICATION_UNAVAILABLE`. Prompt save is rejected; prior prompt remains active. Fail-closed, not fail-open.

---

## 11) Given/When/Then acceptance criteria

### AC-1: Tenant saves a valid custom prompt
- Given a tenant `owner` with an authenticated session
- When they `PUT /v1/settings/drafting-prompt` with valid text ≤1,500 chars that passes safety classification
- Then the response is `200` with `changed: true` and a `version_id`
- And `tenant_settings.custom_drafting_prompt` is updated to the new value
- And a new `tenant_prompt_versions` row is created with `is_active = true`
- And the prior active version row (if any) has `is_active = false`
- And a superadmin audit log entry and email notification are emitted

### AC-2: Custom prompt applied as system message in drafting
- Given a tenant with `custom_drafting_prompt = "You are a gaming partnership specialist..."`
- When a drafting job runs for that tenant
- Then `generate_text()` is called with `system_prompt = "You are a gaming partnership specialist..."`
- And the OpenAI API call contains a `system` role message with that content
- And per-creator instructions are in the `user` role message

### AC-3: System default fallback when no custom prompt
- Given a tenant with `custom_drafting_prompt = NULL`
- When a drafting job runs
- Then `generate_text()` is called with `system_prompt = <SYSTEM_DEFAULT_CONSTANT>`
- And the system default constant (not a DB value) is used

### AC-4: Safety violation rejected and logged
- Given a candidate prompt containing a known injection pattern
- When a tenant submits `PUT /v1/settings/drafting-prompt`
- Then the response is `422` with code `PROMPT_SAFETY_VIOLATION`
- And `tenant_settings.custom_drafting_prompt` is unchanged
- And no new `tenant_prompt_versions` row is created
- And a `tenant_prompt_rejection_log` row IS created with the actor, reason, and first 500 chars of the rejected prompt
- And a superadmin security alert (audit log entry + email) IS emitted with a "blocked attempt" subject

### AC-5: Length limit enforced before classification; rejection logged
- Given a prompt of 1,501+ characters
- When submitted via `PUT /v1/settings/drafting-prompt`
- Then the response is `422` with code `PROMPT_TOO_LONG`
- And no LLM classification call is made
- And a `tenant_prompt_rejection_log` row IS created with `rejection_type = "PROMPT_TOO_LONG"`
- And a superadmin security alert IS emitted

### AC-6: History is returned in descending chronological order
- Given a tenant `owner` who has saved 3 different prompts
- When they `GET /v1/settings/drafting-prompt/history`
- Then all 3 versions are returned, newest first
- And each entry includes `version_id`, `actor`, `source`, `is_active`, and `created_at`

### AC-7: Tenant reverts to a prior version
- Given a tenant with 3 version rows in history
- When they `POST /v1/settings/drafting-prompt/revert` with the oldest version's ID
- Then a new version row is created with `source = "tenant_revert"` and the prior version's content
- And `tenant_settings.custom_drafting_prompt` reflects the reverted content
- And the new row is `is_active = true`; all others are `is_active = false`
- And a superadmin notification is emitted

### AC-8: `member` role denied write access
- Given a tenant `member`
- When they `PUT /v1/settings/drafting-prompt`
- Then the response is `403`

### AC-9: Superadmin views any tenant's history and reverts
- Given a superadmin and a tenant with 2 version rows
- When the superadmin `GET /admin/tenants/{id}/drafting-prompt/history`
- Then both versions are visible with actor, source, and content
- When the superadmin `POST /admin/tenants/{id}/drafting-prompt/revert` with version 1's ID
- Then a new version row is created with `source = "admin_revert"` and the superadmin's email as actor
- And `tenant_settings.custom_drafting_prompt` is updated to the reverted content

### AC-10: Identical content yields no side effects
- Given a tenant with an active prompt "Prompt A"
- When they `PUT /v1/settings/drafting-prompt` with "Prompt A" (exact match, after trim)
- Then the response is `200` with `changed: false`
- And no new version row is created
- And no superadmin notification is emitted

### AC-11: LLM provider abstraction backward compatible
- Given an existing caller of `generate_text()` that does not pass `system_prompt`
- When it calls `generate_text(prompt="...")`
- Then behavior is unchanged (no system message injected into the OpenAI call)

### AC-12: Feature flag gates mutation; GET always returns flag state
- Given `custom_drafting_prompt_enabled = false` in `GlobalAdminConfiguration`
- When any tenant calls `GET /v1/settings/drafting-prompt`
- Then response is `200` with `feature_enabled: false` and the system default prompt
- When any tenant calls `PUT /v1/settings/drafting-prompt`
- Then response is `501 Not Implemented`

### AC-13: Superadmin saves scoring system prompt; scoring jobs use it
- Given a superadmin sets `scoring_system_prompt = "You are a creator scoring expert..."` via `PUT /admin/configuration`
- When a scoring job runs for any tenant
- Then `generate_structured()` is called with `system_prompt = "You are a creator scoring expert..."`
- And per-creator instructions remain in the user-role message

### AC-14: Scoring falls back to default when prompt is null
- Given `scoring_system_prompt` is `NULL` in `GlobalAdminConfiguration`
- When a scoring job runs
- Then `generate_structured()` is called with `system_prompt = SCORING_DEFAULT_SYSTEM_PROMPT`

### AC-15: Repeated rejection attempts trigger escalation warning
- Given a tenant who has accumulated ≥3 rejection log entries within 24 hours
- When the 3rd (or later) rejection occurs
- Then the superadmin alert email body includes a "Repeated attempts detected (N in 24h)" warning
- And the alert is still sent even if Resend previously failed (re-attempt on this path)

### AC-16: Superadmin views rejection log for a specific tenant
- Given a superadmin and a tenant with 2 rejection log entries
- When the superadmin `GET /admin/tenants/{id}/drafting-prompt/rejection-log`
- Then both rows are returned with `actor`, `rejection_reason`, `prompt_preview`, and `created_at`
- And a tenant-scoped request to this endpoint returns 404 (tenants cannot access it)

### AC-17: Fleet-wide rejection log visible to superadmin
- Given rejections across 3 different tenants
- When a superadmin `GET /admin/drafting-prompt/rejection-log`
- Then rows from all tenants are returned, most recent first, with `tenant_id` included in each row

---

## 12) Non-functional requirements

- **Performance:** `GET /v1/settings/drafting-prompt` p95 < 100ms (single DB read). `PUT /v1/settings/drafting-prompt` p95 < 3s (includes LLM safety classification call). History endpoints p95 < 200ms.
- **Reliability:** Safety classification failures (LLM provider timeout or error) **MUST** be fail-closed: the save is rejected, not silently bypassed. Resend notification failures **MUST NOT** block the save response.
- **Operability:** Every prompt save (success, rejection, no-change) is logged at `INFO` level with tenant ID, actor, and outcome. Superadmin notification failures are logged at `WARNING`. No draft generation failure caused by the `system_prompt` extension is silently swallowed.
- **Usability:** Settings UI shows live character count with a warning threshold at 1,400 chars. History list shows a 120-char truncated preview per version.
- **Backward compatibility:** `LLMProvider.generate_text()` signature change **MUST NOT** break any existing caller. `system_prompt` defaults to `None`.

---

## 13) Test strategy requirements (spec-level)

- **Unit tests (`backend/tests/unit/`):** Length validation, safety classification logic (mock LLM), idempotency check (identical content), version ordering, system-default fallback, `LLMProvider.generate_text()` and `generate_structured()` signature extensions (mock provider), drafting service system-prompt injection, rejection log row creation on `PROMPT_SAFETY_VIOLATION` and `PROMPT_TOO_LONG`, repeated-attempts counter logic.
- **Integration tests (`backend/tests/integration/`):** Full save → history → tenant revert cycle; safety rejection leaves prior prompt and version table unchanged and creates rejection log row; superadmin revert correctly updates `is_active` and `custom_drafting_prompt`; drafting service reads correct prompt from DB; identical-content idempotency against real DB; superadmin reads per-tenant and fleet rejection logs; repeated-attempt escalation threshold fires at 3 rejections in 24h.
- **Contract tests (`backend/tests/contract/`):** Response shapes for all Phase 1 endpoints; `feature_enabled` and `is_custom` flags; `changed: false` response; error code presence for all Phase 1 error codes (`PROMPT_TOO_LONG`, `PROMPT_SAFETY_VIOLATION`, `PROMPT_CLASSIFICATION_UNAVAILABLE`, `PROMPT_VERSION_NOT_FOUND`); rejection log endpoints return correct shape; history list ordering; `501` when flag off; tenant-scoped rejection log request returns 404.
- **E2E tests (`web/tests/e2e/`):** Tenant owner edits and saves prompt; tenant views history; tenant reverts; member denied update; character count warning visible at 1,400 chars.

---

## 14) Documentation update requirements

- `docs/01_architecture/`: Add section on LLM prompt customization — describe how tenant custom system prompt is injected into drafting calls, how it is architecturally separated from per-creator user-role instructions, and where the safety gate sits.
- `docs/03_runbooks/`: Add runbook for superadmin prompt review and revert procedure; include escalation path if safety classification is unavailable. Add section on reviewing the rejection log to identify and respond to tenants with repeated blocked attempts.
- `docs/04_security/`: Update LLM trust model with prompt injection threat, classification gate, and fail-closed policy.
- `docs/05_quality/`: Update testing strategy coverage matrix with new test entries for this feature.

---

## 15) Rollout and migration readiness

- **Feature flag:** Phase 1 ships behind `custom_drafting_prompt_enabled` global config flag (boolean on `GlobalAdminConfiguration`). When `false`, `PUT` and revert endpoints return `501 Not Implemented`. `GET` returns the system default with `is_custom: false`. Allows superadmin-controlled pilot before full rollout.
- **Migration:** Two Alembic migrations:
  1. `custom_drafting_prompt` column on `tenant_settings` (nullable, no backfill) + new `tenant_prompt_versions` table + new `tenant_prompt_rejection_log` table.
  2. `scoring_system_prompt` column on `global_admin_configuration` (nullable, no backfill). Can run in the same migration or separately — both are additive.
  Both require `downgrade()` implementations.
- **Backfill:** None. All existing tenants start with `custom_drafting_prompt = NULL`, preserving current behavior.
- **Operational gates before enabling the flag:**
  - Superadmin notification email address configured.
  - Safety classification approach confirmed and smoke-tested against known injection patterns.
  - System default brand context constant reviewed and finalized.
- **Release gate:** All AC-* pass in CI; migration round-trip verified; notification smoke test passes; no open questions in §18.

---

## 16) Traceability matrix

| FR ID | Acceptance Criteria IDs | Implementation plan stories | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 | AC-1, AC-3, AC-10, AC-12 | S1.1 (data), S2.1 (service), S2.2 (tenant API) | `tests/unit/domain/test_prompt_validation.py`, `tests/contract/test_drafting_prompt_contracts.py` | `docs/01_architecture/llm_prompt_customization.md` |
| FR-2 | AC-1, AC-4, AC-5, AC-8, AC-10 | S2.1 (service), S2.2 (tenant API) | `tests/unit/domain/test_prompt_validation.py`, `tests/unit/services/test_prompt_service.py`, `tests/integration/test_prompt_save.py` | `docs/04_security/llm_trust_model.md` |
| FR-3 | AC-6 | S1.1 (data), S2.2 (tenant API) | `tests/integration/test_prompt_save.py`, `tests/contract/test_drafting_prompt_contracts.py` | — |
| FR-4 | AC-7 | S2.2 (tenant API) | `tests/integration/test_prompt_save.py` | `docs/03_runbooks/prompt_revert.md` |
| FR-5 | AC-9 | S2.3 (admin API) | `tests/integration/test_prompt_admin.py`, `tests/contract/test_drafting_prompt_contracts.py` | `docs/03_runbooks/prompt_revert.md` |
| FR-6 | AC-1, AC-7, AC-9, AC-10 | S2.1 (service) | `tests/unit/services/test_prompt_service.py` | `docs/03_runbooks/prompt_revert.md` |
| FR-7 | AC-2, AC-3 | S3.2 (drafting wiring) | `tests/unit/services/test_drafting_service.py`, `tests/integration/test_drafting_integration.py` | `docs/01_architecture/llm_prompt_customization.md` |
| FR-8 | AC-2, AC-11 | S3.1 (LLM abstraction) | `tests/unit/integrations/test_openai_provider.py` | `docs/01_architecture/llm_prompt_customization.md` |
| FR-9 (P2) | — | Phase 2 (deferred — separate plan) | `tests/contract/test_drafting_prompt_contracts.py` | `docs/01_architecture/llm_prompt_customization.md` |
| FR-10 | AC-13, AC-14 | S3.3 (scoring wiring + admin UI) | `tests/unit/services/test_scoring_service.py`, `tests/integration/test_scoring_integration.py` | `docs/01_architecture/llm_prompt_customization.md` |
| FR-11 | AC-4, AC-5, AC-15 | S2.1 (service) | `tests/unit/services/test_prompt_service.py`, `tests/integration/test_prompt_save.py` | `docs/04_security/llm_trust_model.md` |
| FR-12 | AC-16, AC-17 | S2.3 (admin API) | `tests/integration/test_prompt_admin.py`, `tests/contract/test_drafting_prompt_contracts.py` | `docs/03_runbooks/prompt_revert.md` |

---

## 17) Definition of feature done

This feature is complete when:

- [ ] All acceptance criteria defined in §11 (AC-1 through AC-17) pass in CI.
- [ ] All test layers (unit/integration/contract/e2e) are green.
- [ ] Alembic migration verified with round-trip (`upgrade head` + `downgrade -1` + `upgrade head`).
- [ ] Documentation updates across `docs/01`, `docs/03`, `docs/04`, `docs/05` are merged.
- [ ] Superadmin notification smoke tested in dev environment.
- [ ] `custom_drafting_prompt_enabled` flag correctly gates all mutation endpoints.
- [ ] `drafting.jinja` deleted and `SYSTEM_DEFAULT_PROMPT` constant defined in `prompt_service.py` (per §18 decision log).
- [ ] `scoring_system_prompt` field readable and writable via admin configuration; scoring service uses it with constant fallback.

---

## 18) Open questions and decision log

### Open questions

_None — all pre-implementation questions resolved before implementation plan was written._

### Decision log

- 2026-03-16 — Prompts take effect immediately (no approval queue). Rationale: approval queues add friction for legitimate tenants; superadmin revert is sufficient as a post-hoc control.
- 2026-03-16 — Custom prompt occupies the OpenAI `system` role message, not prepended to the user-role message. Rationale: system-role content has different model attention characteristics and provides cleaner separation from per-creator instructions. Requires extending `LLMProvider.generate_text()`.
- 2026-03-16 — Phase 2 (LLM-assisted generation) deferred. Rationale: adds a second LLM round-trip and additional UX design; does not block Phase 1 value delivery.
- 2026-03-16 — Content safety gate is fail-closed. Rationale: a save that bypasses classification due to a transient error could allow harmful content into the LLM call pipeline. Reject-on-error is safer than accept-on-error.
- 2026-03-16 — Safety classification uses `LLMProvider.generate_structured()` with schema `{"safe": bool, "reason": str}`. Rationale: compatible with the existing provider abstraction and `MockLLMProvider`; no external moderation API dependency; a dedicated moderation endpoint can be swapped in later without changing the service interface.
- 2026-03-16 — Reverts skip re-classification. Rationale: adds latency to a recovery action; the version already passed classification when first saved; policy tightening is addressed via admin revert authority, not re-classification.
- 2026-03-16 — Admin-initiated reverts emit audit log only, no email. Rationale: during incident remediation a superadmin may perform multiple reverts rapidly; email notification would be noisy and counterproductive.
- 2026-03-16 — `drafting.jinja` is retired (deleted) during Epic 3. The system default brand context is defined as a `SYSTEM_DEFAULT_PROMPT` constant in `prompt_service.py`. Rationale: no template loading at job-start; single place to update the default; jinja template was already unused by `drafting_service.py`.
- 2026-03-16 — History endpoint returns the 20 most recent versions (default limit). All versions are retained in DB; older ones remain accessible but are not shown by default. UI paginator can be added in a later iteration.
- 2026-03-16 — Rejected prompt attempts are logged in a **separate** `tenant_prompt_rejection_log` table, not in `tenant_prompt_versions`. Rationale: `tenant_prompt_versions` represents the accepted version lineage that tenants and admins navigate for revert operations; mixing rejected attempts into that table would pollute the history UX and require callers to filter by rejection status on every read. A separate table has a clean purpose (security audit) and can evolve independently (e.g., TTL-based archival, export to SIEM) without touching the version history API.
- 2026-03-16 — `PROMPT_CLASSIFICATION_UNAVAILABLE` (503) does NOT create a rejection log row. Rationale: this is an infrastructure failure, not evidence of hostile intent. Logging it as a rejection would create false positives in superadmin security alerts. The event is logged at WARNING level in application logs for ops visibility.
- 2026-03-16 — Rejected prompt preview is capped at 500 characters (not 200 like the save notification). Rationale: 200 chars is enough to understand save context; for security investigation, 500 chars gives significantly more signal about the injection technique without storing the full attack payload indefinitely.
- 2026-03-16 — Repeated-attempts threshold is ≥3 in 24 hours. Rationale: 1-2 rejections could be innocent formatting mistakes; 3+ suggests probing or persistent bad faith. Threshold is configurable via global config if operational experience requires adjustment.
