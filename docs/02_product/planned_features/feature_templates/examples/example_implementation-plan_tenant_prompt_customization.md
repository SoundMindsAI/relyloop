# Implementation Plan — Tenant-Customizable Drafting System Prompt

**Date:** 2026-03-16
**Status:** Ready for Execution
**Primary spec:** `docs/02_product/planned_features/feature_tenant_can_update_server_prompt/feature_tenant_can_update_server_prompt.md`

---

## 0) Planning principles

- Spec traceability first: every story maps to FR IDs from the spec.
- Phase gates are hard stops: Epic 1 → Epic 2 → Epics 3/4/5 (parallel) → Refactor.
- Fail-loud tests: assert exact status codes, error codes, and field presence.
- Follow existing repo patterns exactly — no new conventions without a note.
- `drafting.jinja` is retired in Epic 3 (not earlier — file is touched once, with a test suite green).

---

## 1) Scope traceability (FR → epics)

| FR ID | Epic | Notes |
|---|---|---|
| FR-1 (read active prompt) | Epic 2, S2.2 | GET endpoint + fallback to system default constant |
| FR-2 (update prompt — gate, store, notify) | Epic 2, S2.1 + S2.2 | Service layer: validate → classify → version → notify |
| FR-3 (version history) | Epic 1 + Epic 2, S2.2 | `tenant_prompt_versions` table; tenant endpoint |
| FR-4 (tenant revert) | Epic 2, S2.2 | POST `/v1/settings/drafting-prompt/revert` |
| FR-5 (superadmin visibility + revert) | Epic 2, S2.3 | Admin-router endpoints under `/admin/tenants/{id}/...` |
| FR-6 (superadmin notification) | Epic 2, S2.1 | Tenant saves → audit log + email; admin reverts → audit log only (no email) |
| FR-7 (apply prompt in drafting) | Epic 3, S3.2 | `drafting_service.py` reads `custom_drafting_prompt` at job start |
| FR-8 (LLM abstraction extension) | Epic 3, S3.1 | `system_prompt: str \| None = None` on both `generate_text()` and `generate_structured()` |
| FR-9 (Phase 2 generation — deferred) | Not in this plan | Described in spec §2; separate future plan |
| FR-10 (scoring system prompt) | Epic 3, S3.3 | `scoring_system_prompt` column on `GlobalAdminConfiguration`; scoring service reads at job start; admin UI textarea in Global Controls panel |
| FR-11 (rejection audit log) | Epic 1, S1.1 + Epic 2, S2.1 | `tenant_prompt_rejection_log` table; log every PROMPT_TOO_LONG and PROMPT_SAFETY_VIOLATION rejection; security alert on every rejection; repeated-attempts escalation at ≥3/24h |
| FR-12 (superadmin rejection log visibility) | Epic 2, S2.3 | `GET /admin/tenants/{id}/drafting-prompt/rejection-log` + `GET /admin/drafting-prompt/rejection-log` |

---

## 2) Delivery structure

### Conventions (project-specific)

- All repo functions accept `db: Session` as first arg; call `db.flush()` (caller commits).
- Services are `async`; create `job_run` only where scheduled work is tracked. Prompt saves do not create `job_run` records.
- Domain layer is pure: no DB, no side effects, no async.
- ORM models use `Mapped[T]` typed columns; UUIDs are `String(36)` with `default=lambda: str(uuid.uuid4())`.
- Routers return typed Pydantic response models; errors use `raise_app_http_error(exc)` from `backend/app/core/errors.py`.
- Admin routers live in `backend/app/api/admin/`; registered in `main.py` with `prefix="/admin"`.
- All new exports added to the relevant `__init__.py` `__all__` list.

### AI Agent Execution Protocol (applies to every story)

1. Read story outcome + endpoints + interfaces + DoD before writing any code.
2. Backend first: migration → model → repo → domain → service → router → schemas.
3. Run `make test-unit && make test-integration && make test-contract` after each story.
4. Frontend after backend tests are green (if story has UI scope).
5. Run `cd web && npm run test:e2e:stable` after frontend changes.
6. Update `docs/05_quality/testing_strategy.md` inventory in the same PR when new test files are added.
7. Verify migration round-trip if schema changed: `alembic downgrade -1 && alembic upgrade head`.
8. Mark story `[x]` in §9 tracker only after all DoD gates are green.

---

## Epic 1 — Data and Domain Foundation

> **Gate:** migration round-trip clean, repo functions exported, domain validation unit-tested.

### Story 1.1 — Schema, ORM, repo, and domain validation

**Status:** `[ ]`

**Outcome:** `tenant_settings.custom_drafting_prompt` column exists; `tenant_prompt_versions` table exists; `tenant_prompt_rejection_log` table exists; repo functions cover the full CRUD surface for both tables; domain layer enforces length and idempotency rules.

**New files**

| File | Purpose |
|---|---|
| `backend/app/db/repo/prompt_repo.py` | Version functions: `get_active_prompt`, `create_prompt_version`, `get_prompt_history`, `get_prompt_version`; rejection log functions: `create_rejection_log_entry`, `get_rejection_log_for_tenant`, `get_fleet_rejection_log`, `count_recent_rejections` |
| `backend/app/domain/prompt/validation.py` | `validate_prompt_length`, `is_identical_to_active` — pure, no DB |
| `backend/migrations/versions/<id>_add_tenant_prompt_versioning.py` | Alembic migration |
| `backend/tests/unit/domain/test_prompt_validation.py` | Unit tests for domain validation |
| `backend/tests/unit/db/test_prompt_repo.py` | Repo function unit tests (SQLite in-memory) |

**Modified files**

| File | Change |
|---|---|
| `backend/app/db/models/tenant.py` | Add `custom_drafting_prompt: Mapped[str \| None]` (Text, nullable) to `TenantSettings` |
| `backend/app/db/models/tenant.py` | Add `custom_drafting_prompt_enabled: Mapped[bool]` (Boolean, default False) to `GlobalAdminConfiguration` |
| `backend/app/db/models/__init__.py` | Export `TenantPromptVersion` and `TenantPromptRejectionLog` |
| `backend/app/db/repo/__init__.py` | Export all 8 new repo functions via `__all__` |

**New ORM models** (add to `backend/app/db/models/tenant.py`):

```python
class TenantPromptVersion(Base):
    __tablename__ = "tenant_prompt_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)          # "" = explicit clear to default
    actor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)    # "tenant" | "tenant_revert" | "admin_revert"
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), nullable=False)

    __table_args__ = (
        sa.Index("ix_tenant_prompt_versions_tenant_id", "tenant_id"),
    )


class TenantPromptRejectionLog(Base):
    __tablename__ = "tenant_prompt_rejection_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    rejection_type: Mapped[str] = mapped_column(String(50), nullable=False)  # "PROMPT_SAFETY_VIOLATION" | "PROMPT_TOO_LONG"
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)   # classifier reason; None for PROMPT_TOO_LONG
    prompt_preview: Mapped[str] = mapped_column(String(500), nullable=False)    # first 500 chars of rejected prompt
    alert_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), nullable=False)

    __table_args__ = (
        sa.Index("ix_tenant_prompt_rejection_log_tenant_id", "tenant_id"),
        sa.Index("ix_tenant_prompt_rejection_log_created_at", "created_at"),
    )
```

**Key interfaces**

```python
# backend/app/db/repo/prompt_repo.py — version functions

def get_active_prompt(db: Session, tenant_id: str) -> TenantPromptVersion | None:
    """Return the row with is_active=True for this tenant, or None."""

def create_prompt_version(
    db: Session,
    *,
    tenant_id: str,
    prompt: str,
    actor: str | None,
    source: str,           # "tenant" | "tenant_revert" | "admin_revert"
) -> TenantPromptVersion:
    """Atomically: deactivate all prior active rows, insert new active row, flush (no commit)."""

def get_prompt_history(
    db: Session,
    tenant_id: str,
    limit: int = 20,
) -> list[TenantPromptVersion]:
    """Return versions ordered by created_at DESC, limited to `limit`."""

def get_prompt_version(
    db: Session,
    tenant_id: str,
    version_id: str,
) -> TenantPromptVersion | None:
    """Return a specific version belonging to this tenant, or None."""


# backend/app/db/repo/prompt_repo.py — rejection log functions

def create_rejection_log_entry(
    db: Session,
    *,
    tenant_id: str,
    actor: str,
    rejection_type: str,       # "PROMPT_SAFETY_VIOLATION" | "PROMPT_TOO_LONG"
    rejection_reason: str | None,
    prompt_preview: str,       # caller must slice to 500 chars before passing
) -> TenantPromptRejectionLog:
    """Insert a rejection log row and flush (no commit)."""

def get_rejection_log_for_tenant(
    db: Session,
    tenant_id: str,
    limit: int = 50,
) -> list[TenantPromptRejectionLog]:
    """Return rejection log entries for one tenant, most recent first."""

def get_fleet_rejection_log(
    db: Session,
    limit: int = 100,
    offset: int = 0,
) -> list[TenantPromptRejectionLog]:
    """Return rejection log entries across all tenants, most recent first, paginated."""

def count_recent_rejections(
    db: Session,
    tenant_id: str,
    window_hours: int = 24,
) -> int:
    """Count rejection log rows for this tenant within the rolling window. Used for escalation threshold."""


# backend/app/domain/prompt/validation.py

PROMPT_MAX_CHARS = 1_500
PROMPT_WARN_CHARS = 1_400

def validate_prompt_length(prompt: str) -> None:
    """Raise ValueError if prompt exceeds PROMPT_MAX_CHARS after strip."""

def is_identical_to_active(prompt: str, active_version: TenantPromptVersion | None) -> bool:
    """True if stripped prompt equals the active version's stored prompt."""
```

**Tasks**
1. Add `custom_drafting_prompt: Mapped[str | None]` column to `TenantSettings` in `tenant.py`.
2. Add `TenantPromptVersion` and `TenantPromptRejectionLog` ORM models to `tenant.py`; export both from `models/__init__.py`.
3. Write Alembic migration: add `custom_drafting_prompt` column to `tenant_settings` + add `custom_drafting_prompt_enabled` Boolean column (default False) to `global_admin_configuration` + create both new tables + `downgrade()` that reverses all four changes.
4. Implement all 8 repo functions in `prompt_repo.py`; export via `repo/__init__.py`.
5. Implement `validate_prompt_length` and `is_identical_to_active` in `domain/prompt/validation.py`.
6. Write unit tests: `test_prompt_validation.py` (length boundary, idempotency edge cases). `test_prompt_repo.py` covers `create_prompt_version` atomicity, `get_prompt_history` ordering, `create_rejection_log_entry`, and `count_recent_rejections` rolling window.
7. Verify migration round-trip.

**Definition of Done (DoD)**
- [ ] `alembic upgrade head` + `downgrade -1` + `upgrade head` succeeds with no errors.
- [ ] `TenantSettings` has `custom_drafting_prompt` (nullable Text).
- [ ] `GlobalAdminConfiguration` has `custom_drafting_prompt_enabled` (Boolean, default False).
- [ ] `TenantPromptVersion` table created with index on `tenant_id`.
- [ ] `TenantPromptRejectionLog` table created with indexes on `tenant_id` and `created_at`.
- [ ] All 8 repo functions exported from `repo/__init__.py`.
- [ ] `make test-unit` green with `test_prompt_validation.py` and `test_prompt_repo.py` passing.

---

## Epic 2 — Backend Service and API

> **Gate:** all 8 Phase 1 endpoints live (4 tenant + 2 admin history/revert + 2 admin rejection-log), contract tests green, integration tests cover happy path + safety rejection + idempotency + revert + rejection-log visibility.

### Story 2.1 — Prompt service (classification gate + version management + notification)

**Status:** `[ ]`

**Outcome:** `PromptService` handles save and revert logic — classification, idempotency, atomically versioning, updating `tenant_settings.custom_drafting_prompt`, emitting a superadmin notification on success, and logging rejected attempts to `tenant_prompt_rejection_log` with a superadmin security alert (including repeated-attempts escalation at ≥3/24h).

**New files**

| File | Purpose |
|---|---|
| `backend/app/services/prompt_service.py` | `save_prompt`, `revert_prompt`, `classify_prompt` |
| `backend/tests/unit/services/test_prompt_service.py` | Unit tests: classification rejection, idempotency, notification emit on save, notification skipped on no-change |

**Modified files**

| File | Change |
|---|---|
| `backend/app/services/billing_notifications_service.py` | Add `notify_prompt_saved(tenant_id, tenant_name, actor, source, prompt_preview)` and `notify_prompt_rejection(tenant_id, tenant_name, actor, rejection_type, prompt_preview, repeated_attempts_count)` functions |

**Key interfaces**

```python
# backend/app/services/prompt_service.py

SYSTEM_DEFAULT_PROMPT = (
    "You are a creator discovery & outreach specialist writing on behalf of a music technology company."
)

async def classify_prompt(prompt: str, llm_provider: LLMProvider) -> bool:
    """Call llm_provider.generate_structured() with a safety-classification schema.
    Returns True if safe. Raises PromptClassificationError on LLM call failure
    (fail-closed — caller must reject the save on exception).
    Schema: {"safe": {"type": "boolean"}, "reason": {"type": "string"}}"""

async def save_prompt(
    db: Session,
    *,
    tenant_id: str,
    tenant_name: str,
    prompt: str,
    actor: str,
    llm_provider: LLMProvider,
) -> dict:
    """
    Validate length → check idempotency → classify → version → update tenant_settings
    → notify (email + audit log). On rejection (PROMPT_TOO_LONG or PROMPT_SAFETY_VIOLATION),
    creates a tenant_prompt_rejection_log row and emits a superadmin security alert
    (with "Repeated attempts detected" escalation at ≥3 rejections in 24h).
    Raises ValueError (PROMPT_TOO_LONG), ValueError (PROMPT_SAFETY_VIOLATION),
    or PromptClassificationError on LLM failure.
    Returns {"version_id", "changed", "prompt", "updated_at"}.
    """

async def revert_prompt(
    db: Session,
    *,
    tenant_id: str,
    tenant_name: str,
    version_id: str,
    actor: str,
    source: str,             # "tenant_revert" | "admin_revert"
    send_email: bool,        # True for tenant reverts; False for admin reverts (audit log only)
) -> dict:
    """Look up target version (404 if missing/wrong tenant), create new active version
    with that content, update tenant_settings, notify per send_email flag.
    No re-classification — reverts skip the safety gate (spec §18 decision).
    Returns same shape as save_prompt."""
```

**Classification approach (resolves spec open question 1):** Use `llm_provider.generate_structured()` with a minimal JSON schema `{"safe": bool, "reason": str}`. This is compatible with `MockLLMProvider` in tests and with any future provider swap. A dedicated moderation endpoint can be substituted later without changing the service interface.

**Notification split (resolves spec open question 3):**
- Tenant saves and tenant reverts → `notify_prompt_saved(...)` with `send_email=True` → audit log entry + Resend email.
- Admin reverts → `notify_prompt_saved(...)` with `send_email=False` → audit log entry only, no email.
- Notification failures are caught, logged at `WARNING`, and do not roll back the save.
- Use the existing `ResendClient` from `backend/app/integrations/resend/`.

**Rejection logging and security alert (FR-11):**
- On `PROMPT_TOO_LONG` or `PROMPT_SAFETY_VIOLATION` rejection, `save_prompt` calls `create_rejection_log_entry(...)` to persist to `tenant_prompt_rejection_log`.
- After creating the rejection log row, call `count_recent_rejections(db, tenant_id, window_hours=24)` and pass the count to `notify_prompt_rejection(...)`.
- `notify_prompt_rejection(...)` emits a superadmin security alert (audit log entry + email) with a "blocked attempt" subject. When `count >= 3`, the alert includes a "Repeated attempts detected (N in 24h)" escalation warning.
- `PROMPT_CLASSIFICATION_UNAVAILABLE` (503) does NOT create a rejection log row — it's an infra failure, not evidence of hostile intent. Logged at WARNING level only.

**Empty-string "clear to default" handling:**
- If the trimmed prompt is an empty string, `save_prompt` creates a version row with `prompt = ""` and sets `tenant_settings.custom_drafting_prompt = NULL`. Classification is skipped for empty strings. Next drafting job uses the system default.

**Tasks**
1. Define `PromptClassificationError` in `backend/app/core/errors.py`.
2. Implement `classify_prompt` in `prompt_service.py` using `LLMProvider.generate_structured`.
3. Implement `save_prompt` — call `validate_prompt_length` → `is_identical_to_active` → `classify_prompt` → `create_prompt_version` → update `tenant_settings.custom_drafting_prompt` → commit → `notify_prompt_saved`. Handle empty-string input as a "clear to default" action (skip classification, set `custom_drafting_prompt = NULL`, version row with `prompt = ""`).
4. On `PROMPT_TOO_LONG` or `PROMPT_SAFETY_VIOLATION` rejection within `save_prompt`: call `create_rejection_log_entry(...)` → `count_recent_rejections(...)` → `notify_prompt_rejection(...)` with escalation flag.
5. Implement `revert_prompt` — `get_prompt_version` → 404 if not found → `create_prompt_version` with `source=source` → update `tenant_settings.custom_drafting_prompt` → commit → `notify_prompt_saved`.
6. Add `notify_prompt_saved` and `notify_prompt_rejection` to `billing_notifications_service.py`. `notify_prompt_rejection` takes `repeated_attempts_count` and includes escalation warning in the email body when `count >= 3`.
7. Write `test_prompt_service.py` with `MockLLMProvider`; cover: length rejection (no classify call, rejection log row created, security alert emitted), safety rejection (prompt unchanged in DB, rejection log row created, security alert emitted), idempotency (no version row, no notification), successful save (version row created, `custom_drafting_prompt` updated, notification emitted), classification LLM failure → save rejected (no rejection log row), empty-string save → `custom_drafting_prompt` becomes NULL with version row `prompt = ""`, repeated-attempts escalation (≥3 rejections in 24h → alert includes escalation warning).

**Definition of Done (DoD)**
- [ ] `save_prompt` correctly rejects too-long prompts before any LLM call.
- [ ] `save_prompt` correctly rejects flagged prompts; prior `custom_drafting_prompt` unchanged.
- [ ] On `PROMPT_TOO_LONG` and `PROMPT_SAFETY_VIOLATION` rejections: a `tenant_prompt_rejection_log` row is created and a superadmin security alert is emitted.
- [ ] Repeated-attempts escalation: ≥3 rejections in 24h → alert includes "Repeated attempts detected" warning.
- [ ] `PROMPT_CLASSIFICATION_UNAVAILABLE` (LLM failure) does NOT create a rejection log row.
- [ ] Identical content returns `changed: False`; no version row; no notification.
- [ ] Successful save: new version row `is_active=True`; prior version `is_active=False`; `tenant_settings.custom_drafting_prompt` updated; notification emitted.
- [ ] Empty-string save: `custom_drafting_prompt` set to `NULL`; version row with `prompt = ""`; classification skipped.
- [ ] `revert_prompt` with a cross-tenant version_id raises 404-equivalent error.
- [ ] `make test-unit` green on `test_prompt_service.py`.

---

### Story 2.2 — Tenant-facing API endpoints

**Status:** `[ ]`

**Outcome:** 4 tenant endpoints live and tested.

**New files**

| File | Purpose |
|---|---|
| `backend/app/api/v1/drafting_prompt.py` | 4 tenant endpoints |
| `backend/app/api/schemas/drafting_prompt.py` | Pydantic request/response models |
| `backend/tests/contract/test_drafting_prompt_contracts.py` | Contract tests for all 8 Phase 1 endpoints |
| `backend/tests/integration/test_prompt_save.py` | Integration: full save → history → revert cycle |

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/__init__.py` | Register `drafting_prompt.router` |
| `backend/app/main.py` | Include tenant drafting_prompt router under `/v1` prefix |

**Endpoints**

| Method | Path | Auth | Request body | Success response | Error codes |
|---|---|---|---|---|---|
| `GET` | `/v1/settings/drafting-prompt` | `x-tenant-id` | — | `200` `ActivePromptResponse` | `401` |
| `PUT` | `/v1/settings/drafting-prompt` | `x-tenant-id` (owner/admin only) | `UpdatePromptRequest` | `200` `SavePromptResponse` | `401`, `403`, `PROMPT_TOO_LONG` (422), `PROMPT_SAFETY_VIOLATION` (422), `PROMPT_CLASSIFICATION_UNAVAILABLE` (503) |
| `GET` | `/v1/settings/drafting-prompt/history` | `x-tenant-id` (owner/admin only) | — | `200` `PromptHistoryResponse` | `401`, `403` |
| `POST` | `/v1/settings/drafting-prompt/revert` | `x-tenant-id` (owner/admin only) | `RevertPromptRequest` | `200` `SavePromptResponse` | `401`, `403`, `PROMPT_VERSION_NOT_FOUND` (404) |

**Pydantic schemas**

```python
# backend/app/api/schemas/drafting_prompt.py

class UpdatePromptRequest(BaseModel):
    prompt: str                          # raw; service trims and validates

class RevertPromptRequest(BaseModel):
    version_id: str

class PromptVersionItem(BaseModel):
    version_id: str
    prompt: str
    actor: str | None
    source: str                          # "tenant" | "tenant_revert" | "admin_revert"
    is_active: bool
    created_at: datetime

class ActivePromptResponse(BaseModel):
    feature_enabled: bool               # value of GlobalAdminConfiguration.custom_drafting_prompt_enabled
    is_custom: bool
    prompt: str
    version_id: str | None
    updated_at: datetime | None
    updated_by: str | None              # actor from the active version row

class SavePromptResponse(BaseModel):
    version_id: str | None              # None when changed=False
    prompt: str | None                  # None when changed=False
    changed: bool
    updated_at: datetime | None

class PromptHistoryResponse(BaseModel):
    versions: list[PromptVersionItem]
```

**RBAC enforcement:** Extract the requesting user's role from the `x-tenant-id` header context. `member` role → `403` on `PUT`, history `GET`, and revert `POST`. Use existing role-resolution pattern from other v1 routers.

**Tasks**
1. Create `backend/app/api/schemas/drafting_prompt.py` with all 6 schema classes.
2. Create `backend/app/api/v1/drafting_prompt.py` with 4 route handlers; wire through `prompt_service`. In the `PUT` handler, catch `PromptClassificationError` and return `503` with code `PROMPT_CLASSIFICATION_UNAVAILABLE`.
3. At the top of `PUT` and `POST /revert` route handlers, call `get_or_create_global_admin_configuration(db)` (from `backend/app/db/repo/admin_config_repo.py`) and check `config.custom_drafting_prompt_enabled`. If `False`, return `501 Not Implemented`. Include `config.custom_drafting_prompt_enabled` in the `GET` response via `ActivePromptResponse.feature_enabled`.
4. Register router in `main.py`.
5. Write `test_drafting_prompt_contracts.py`: status codes, response shapes, error code presence, `is_custom` flag, `changed: false` shape, `403` for member role, `503` `PROMPT_CLASSIFICATION_UNAVAILABLE` on LLM failure, `501` when feature flag off.
6. Write `test_prompt_save.py` (integration): save → history shows 1 version → revert → history shows 2 versions; `custom_drafting_prompt` updated in DB after each; identical content → `changed: false`, 0 new rows; empty-string save → `custom_drafting_prompt` becomes NULL with version row `prompt = ""`; rejection creates `tenant_prompt_rejection_log` row.

**Definition of Done (DoD)**
- [ ] All 4 endpoints return documented status codes and response shapes.
- [ ] `member` role denied `PUT` and `POST /revert` with `403`.
- [ ] `make test-contract` green on `test_drafting_prompt_contracts.py`.
- [ ] `make test-integration` green on `test_prompt_save.py`.
- [ ] Feature flag `custom_drafting_prompt_enabled=False` → `PUT` returns `501`.

---

### Story 2.3 — Admin API endpoints

**Status:** `[ ]`

**Outcome:** 4 admin endpoints live; superadmins can view and revert any tenant's prompt and view rejection logs (per-tenant and fleet-wide).

**New files**

| File | Purpose |
|---|---|
| `backend/app/api/admin/drafting_prompt.py` | Admin router with GET history + POST revert + GET rejection-log (per-tenant and fleet-wide) |
| `backend/tests/integration/test_prompt_admin.py` | Integration: superadmin reads/reverts, non-superadmin denied |

**Modified files**

| File | Change |
|---|---|
| `backend/app/main.py` | Register admin drafting_prompt router with `prefix="/admin"` |

**Endpoints**

| Method | Path | Auth | Request body | Success response | Error codes |
|---|---|---|---|---|---|
| `GET` | `/admin/tenants/{id}/drafting-prompt/history` | Bearer `require_admin_auth` + `super_admin` role | — | `200` `PromptHistoryResponse` | `401`, `403`, `404` (unknown tenant) |
| `POST` | `/admin/tenants/{id}/drafting-prompt/revert` | Bearer `require_admin_auth` + `super_admin` role | `RevertPromptRequest` | `200` `SavePromptResponse` | `401`, `403`, `404`, `PROMPT_VERSION_NOT_FOUND` (404) |
| `GET` | `/admin/tenants/{id}/drafting-prompt/rejection-log` | Bearer `require_admin_auth` + `super_admin` role | — | `200` `RejectionLogResponse` | `401`, `403`, `404` (unknown tenant) |
| `GET` | `/admin/drafting-prompt/rejection-log` | Bearer `require_admin_auth` + `super_admin` role | — | `200` `RejectionLogResponse` | `401`, `403` |

Reuse `PromptHistoryResponse`, `RevertPromptRequest`, `SavePromptResponse` from Story 2.2 schemas.

**Additional Pydantic schemas** (add to `backend/app/api/schemas/drafting_prompt.py`):

```python
class RejectionLogItem(BaseModel):
    id: str
    tenant_id: str                       # included in fleet-wide response; redundant but consistent in per-tenant
    actor: str
    rejection_type: str                  # "PROMPT_SAFETY_VIOLATION" | "PROMPT_TOO_LONG"
    rejection_reason: str | None
    prompt_preview: str                  # first 500 chars
    created_at: datetime

class RejectionLogResponse(BaseModel):
    rejections: list[RejectionLogItem]
```

Admin actor sourced from `x-admin-actor` header; stored as `f"admin:{actor}"` in the `actor` column of the new version row.

Admin revert calls `revert_prompt(..., source="admin_revert", send_email=False)` — audit log entry only, no Resend email.

**Tasks**
1. Create `backend/app/api/admin/drafting_prompt.py`; follow existing admin router pattern (Bearer auth via `Depends(require_admin_auth)`; role-gate to `super_admin` via `require_admin_role({"super_admin"})`). Include all 4 endpoints: history GET, revert POST, per-tenant rejection-log GET, fleet-wide rejection-log GET.
2. Add `RejectionLogItem` and `RejectionLogResponse` Pydantic schemas to `backend/app/api/schemas/drafting_prompt.py`.
3. For the fleet-wide endpoint (`GET /admin/drafting-prompt/rejection-log`): this path is not scoped under `/admin/tenants/{id}/`, so register it on a separate prefix or use a distinct route path within the same router. Accept `limit` and `offset` query params for pagination; wire through `get_fleet_rejection_log(db, limit, offset)`.
4. Register in `main.py`.
5. Write `test_prompt_admin.py`: superadmin GET returns history; superadmin POST revert creates new `admin_revert` version; non-superadmin (support role) → 403; unknown tenant → 404; superadmin GET rejection-log returns rejection entries for one tenant; superadmin GET fleet-wide rejection-log returns entries across tenants.
6. Add contract assertions for all 4 admin endpoints to `test_drafting_prompt_contracts.py`, including rejection-log response shapes and `tenant_id` field presence in fleet-wide response.

**Definition of Done (DoD)**
- [ ] Superadmin can view full version history for any tenant.
- [ ] Superadmin revert creates a version row with `source = "admin_revert"` and `actor = "admin:<email>"`.
- [ ] Superadmin can view per-tenant rejection log via `GET /admin/tenants/{id}/drafting-prompt/rejection-log`.
- [ ] Superadmin can view fleet-wide rejection log via `GET /admin/drafting-prompt/rejection-log` with pagination.
- [ ] Support-role admin denied with `403` on all 4 endpoints.
- [ ] `make test-integration` green on `test_prompt_admin.py`.

---

## Epic 3 — LLM Abstraction + Drafting Service Wiring

> **Gate:** `make test-unit` green including new LLM provider tests; drafting integration test reads custom prompt from DB.

### Story 3.1 — Extend LLM abstraction with `system_prompt` parameter

**Status:** `[ ]`

**Outcome:** Both `LLMProvider.generate_text()` and `LLMProvider.generate_structured()` accept an optional `system_prompt: str | None = None`. `OpenAIProvider` injects it as a `system` role message in both methods. `MockLLMProvider` accepts and ignores it. All existing callers unaffected (default `None` preserves backward compat). `generate_structured()` currently has a hardcoded system message `"You are a helpful assistant. Respond with valid JSON matching the requested schema."` — that string becomes the default applied when `system_prompt` is `None`.

**Modified files**

| File | Change |
|---|---|
| `backend/app/integrations/llm/base.py` | Add `system_prompt: str \| None = None` to both `generate_text()` and `generate_structured()` abstract signatures |
| `backend/app/integrations/llm/openai_provider.py` | `generate_text()`: when `system_prompt` non-null, prepend system message; `generate_structured()`: replace hardcoded system string with `system_prompt or SCORING_DEFAULT_SYSTEM_PROMPT` constant |
| `backend/app/integrations/llm/mock_provider.py` | Accept `system_prompt` kwarg on both methods; no behavioral change |
| `backend/tests/unit/integrations/test_openai_provider.py` | **New file.** Covers: `generate_text` with `system_prompt` → 2 messages (system + user); without → 1 message; `generate_structured` with custom `system_prompt` → system message is the custom string; without → system message is the default constant |

**Key interfaces**

```python
# backend/app/integrations/llm/base.py (updated signatures)
@abstractmethod
async def generate_text(
    self,
    prompt: str,
    *,
    system_prompt: str | None = None,
    **kwargs: object,
) -> str: ...

@abstractmethod
async def generate_structured(
    self,
    schema: dict,
    prompt: str,
    *,
    system_prompt: str | None = None,
    **kwargs: object,
) -> dict: ...

# backend/app/integrations/llm/openai_provider.py — generate_text
messages = []
if system_prompt:
    messages.append({"role": "system", "content": system_prompt})
messages.append({"role": "user", "content": prompt})

# backend/app/integrations/llm/openai_provider.py — generate_structured
SCORING_DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant. Respond with valid JSON matching the requested schema."
messages = [
    {"role": "system", "content": system_prompt or SCORING_DEFAULT_SYSTEM_PROMPT},
    {"role": "user", "content": prompt},
]
```

**Tasks**
1. Update `LLMProvider.generate_text()` abstract signature with `system_prompt` param.
2. Update `LLMProvider.generate_structured()` abstract signature with `system_prompt` param.
3. Update `OpenAIProvider.generate_text()` to conditionally prepend system message.
4. Update `OpenAIProvider.generate_structured()` to use `system_prompt or SCORING_DEFAULT_SYSTEM_PROMPT`.
5. Update `MockLLMProvider` for both methods.
6. Add unit tests to `test_openai_provider.py` using `unittest.mock.patch` on the `openai.AsyncOpenAI` client.
7. Verify no existing caller is broken by running `make test-unit`.

**Definition of Done (DoD)**
- [ ] `generate_text`: `system_prompt` present → OpenAI call has 2 messages (`system` then `user`); absent → 1 message (`user` only).
- [ ] `generate_structured`: `system_prompt` present → system message uses the provided string; absent → system message is `SCORING_DEFAULT_SYSTEM_PROMPT`.
- [ ] `make test-unit` green with new assertions in `test_openai_provider.py`.
- [ ] `make typecheck` clean.

---

### Story 3.2 — Wire custom prompt into drafting service; retire `drafting.jinja`

**Status:** `[ ]`

**Outcome:** `drafting_service.py` reads `tenant_settings.custom_drafting_prompt` at job start and passes it as `system_prompt` to `generate_text()`. `drafting.jinja` is deleted. `SYSTEM_DEFAULT_PROMPT` constant (defined in `prompt_service.py`) is the fallback.

**Modified files**

| File | Change |
|---|---|
| `backend/app/services/drafting_service.py` | Read `custom_drafting_prompt` from `tenant.settings`; pass as `system_prompt` to `generate_text()` |
| `backend/tests/unit/services/test_drafting_service.py` | Add assertions: `generate_text` called with correct `system_prompt` for custom and default cases |
| `backend/tests/integration/test_drafting_integration.py` | New integration test: tenant with custom prompt → generated draft uses that prompt as system message |

**Deleted files**

| File | Reason |
|---|---|
| `backend/app/integrations/llm/prompts/drafting.jinja` | Unused — prompt is assembled in service layer; template is retired here |

**Change in `drafting_service.py`:**
```python
# At top of draft_scored_items(), after loading tenant settings:
from backend.app.services.prompt_service import SYSTEM_DEFAULT_PROMPT

custom_prompt = tenant.settings.custom_drafting_prompt if tenant.settings else None
system_prompt = custom_prompt or SYSTEM_DEFAULT_PROMPT

# Then in the per-item loop:
message = await llm_provider.generate_text(prompt, system_prompt=system_prompt)
```

**Tasks**
1. Import `SYSTEM_DEFAULT_PROMPT` from `prompt_service.py` in `drafting_service.py`.
2. Read `tenant.settings.custom_drafting_prompt` after loading tenant; fall back to constant.
3. Pass `system_prompt=` to both `generate_text()` calls (message body + subject line).
4. Delete `backend/app/integrations/llm/prompts/drafting.jinja`.
5. Update existing `test_drafting_service.py` unit tests to assert `system_prompt` is passed correctly.
6. Write `test_drafting_integration.py`: seed a tenant with `custom_drafting_prompt = "Custom voice"`, run drafting via `MockLLMProvider`, assert `generate_text` was called with `system_prompt = "Custom voice"`. Also assert that a tenant without a custom prompt uses `SYSTEM_DEFAULT_PROMPT`.

**Definition of Done (DoD)**
- [ ] `drafting.jinja` deleted; no imports of the template remain anywhere.
- [ ] Drafting service passes tenant custom prompt (or default constant) as `system_prompt`.
- [ ] Subject-line `generate_text` call also receives `system_prompt` (consistent brand voice).
- [ ] `make test-unit` green; `make test-integration` green on `test_drafting_integration.py`.

---

### Story 3.3 — Scoring system prompt: admin config + scoring service wiring + admin UI

**Status:** `[ ]`

**Outcome:** Superadmins can view and edit the scoring system prompt via the existing "Global Controls" tab in the admin dashboard. The value is stored in `GlobalAdminConfiguration.scoring_system_prompt`. `scoring_service.py` reads the value at job start and passes it as `system_prompt` to `generate_structured()`. When the column is `NULL`, the scoring default constant is used (same behavior as before this feature).

**New files**

| File | Purpose |
|---|---|
| `backend/tests/unit/services/test_scoring_service_prompt.py` | Unit tests: scoring service reads `scoring_system_prompt` from global config and passes it to `generate_structured()` |

**Modified files**

| File | Change |
|---|---|
| `backend/alembic/versions/<next_id>_add_scoring_system_prompt.py` | Add `scoring_system_prompt: Mapped[str \| None]` column to `global_admin_configuration` |
| `backend/app/db/models/tenant.py` | Add `scoring_system_prompt: Mapped[str \| None] = mapped_column(Text, nullable=True)` to `GlobalAdminConfiguration` |
| `backend/app/api/admin/configuration.py` | Add `scoring_system_prompt: str \| None` to `AdminConfigRequest` and `AdminConfigResponse` Pydantic schemas |
| `backend/app/services/scoring_service.py` | At job start, call `get_or_create_global_admin_configuration(db)` and read `scoring_system_prompt`; pass as `system_prompt` to `generate_structured()` |
| `web/src/components/admin/dashboard/admin-global-controls-panel.tsx` | Add "AI Settings" section with a textarea for `scoring_system_prompt` (see UI spec below) |
| `backend/tests/integration/test_scoring_prompt_config.py` | New integration test: global config `scoring_system_prompt` set → `generate_structured` receives that value; unset → receives `None` (falls back to constant inside `OpenAIProvider`) |

**Migration note:** Revision ID must be ≤32 chars (e.g., `add_scoring_system_prompt`). `downgrade()` must drop the column.

**Key interfaces**

```python
# backend/app/api/admin/configuration.py — updated schemas
class AdminConfigRequest(BaseModel):
    # ... existing fields ...
    scoring_system_prompt: str | None = None  # added

class AdminConfigResponse(BaseModel):
    # ... existing fields ...
    scoring_system_prompt: str | None  # added

# backend/app/services/scoring_service.py — at job start
global_config = get_or_create_global_admin_configuration(db)
scoring_system_prompt = global_config.scoring_system_prompt  # may be None

# in score loop:
result = await llm_provider.generate_structured(
    SCORING_SCHEMA,
    prompt,
    system_prompt=scoring_system_prompt,  # None → OpenAIProvider uses SCORING_DEFAULT_SYSTEM_PROMPT
)
```

**Frontend: admin Global Controls UI (AI Settings section)**

Location: `AdminGlobalControlsPanel` in `web/src/components/admin/dashboard/admin-global-controls-panel.tsx`.

Add a new "AI Settings" subsection after the existing controls. Pattern: `AdminSectionCard` wrapper with title "AI Settings". Inside: a labeled `<textarea>` for Scoring System Prompt with helper text "Used as the system-role message for all AI scoring calls. Defaults to the built-in JSON-structured response prompt when left blank." The textarea should:
- Use `AdminNumberField`-style labeling: `<label>` above, helper text below.
- Be resizable (`resize: "vertical"`), monospace font, ~4 rows tall.
- Bind to the same `config` state object already managed by the panel's `handleSave()` flow.
- Use `style={{ width: "100%", fontFamily: "monospace", fontSize: "0.875rem", padding: "0.75rem", borderRadius: "4px", border: "1px solid var(--color-border)", resize: "vertical" }}`.
- No separate Save button — the existing Global Controls "Save" button persists all fields together.

```
┌─────────────────────────────────────────────────────┐
│ AI Settings                                          │
│ ─────────────────────────────────────────────────── │
│ Scoring System Prompt                                │
│ [textarea — 4 rows — full width — monospace]         │
│ Used as the system-role message for all AI scoring   │
│ calls. Leave blank to use the built-in default.      │
└─────────────────────────────────────────────────────┘
```

**Tasks**
1. Write migration: add `scoring_system_prompt TEXT NULL` to `global_admin_configuration`; include `downgrade()`.
2. Add `scoring_system_prompt` column to `GlobalAdminConfiguration` ORM model.
3. Update `AdminConfigRequest` and `AdminConfigResponse` schemas with `scoring_system_prompt: str | None`.
4. Update `PUT /admin/configuration` handler to persist the new field (it likely iterates `AdminConfigRequest` fields already — verify and update if needed).
5. Wire `scoring_service.py` to read and forward `scoring_system_prompt` from global config.
6. Add "AI Settings" subsection with textarea to `AdminGlobalControlsPanel`.
7. Write unit tests in `test_scoring_service_prompt.py`.
8. Write integration tests in `test_scoring_prompt_config.py`.
9. Run `alembic upgrade head` then round-trip `alembic downgrade -1 && alembic upgrade head`.
10. Run `make test-unit && make test-integration && make lint && make typecheck`.

**Definition of Done (DoD)**
- [ ] Migration applies and reverses cleanly.
- [ ] `GET /admin/configuration` returns `scoring_system_prompt` field.
- [ ] `PUT /admin/configuration` with `scoring_system_prompt` updates the DB value.
- [ ] Scoring service passes the stored value (or `None`) to `generate_structured()`.
- [ ] Admin Global Controls panel renders "AI Settings" textarea; saves via existing Save button.
- [ ] Unit tests in `test_scoring_service_prompt.py` green.
- [ ] Integration test in `test_scoring_prompt_config.py` green.
- [ ] `make test-unit && make test-integration && make lint && make typecheck` all pass.

---

## Epic 4 — Tenant Settings UI

> **Gate:** E2E test `settings_drafting_prompt.spec.ts` stable.

### Story 4.1 — "System Prompt" tab on settings page

**Status:** `[ ]`

**Outcome:** The tenant settings page has a "System Prompt" tab. `owner` and `admin` users see a textarea with live character count, a Save button, and a version history list with Restore buttons. `member` users see the active prompt read-only with no edit controls. When `feature_enabled: false` is returned in the `GET /v1/settings/drafting-prompt` response, the tab renders a "Feature coming soon" notice instead of the edit controls.

**New files**

| File | Purpose |
|---|---|
| `web/src/hooks/use-drafting-prompt.ts` | Data fetching hook: `activePrompt`, `history`, `save`, `revert`, `loading`, `error` |
| `web/tests/e2e/settings_drafting_prompt.spec.ts` | E2E spec — see flows below |

**Modified files**

| File | Change |
|---|---|
| `web/src/app/settings/page.tsx` | Add `"drafting-prompt"` to `SettingsTab` type; add tab button; render `DraftingPromptTab` component |
| `web/src/app/settings/page.tsx` | (or extract to `web/src/components/settings/drafting-prompt-tab.tsx` if component grows large) |

---

#### Frontend: Data-fetching hook

```typescript
// web/src/hooks/use-drafting-prompt.ts

interface ActivePrompt {
  is_custom: boolean;
  prompt: string;
  version_id: string | null;
  updated_at: string | null;
  updated_by: string | null;
}

interface PromptVersion {
  version_id: string;
  prompt: string;
  actor: string | null;
  source: string;
  is_active: boolean;
  created_at: string;
}

interface UseDraftingPromptResult {
  featureEnabled: boolean;             // from activePrompt.feature_enabled
  activePrompt: ActivePrompt | null;
  history: PromptVersion[];
  loading: boolean;
  error: string | null;
  saving: boolean;
  saveError: string | null;
  save: (prompt: string) => Promise<void>;
  revert: (version_id: string) => Promise<void>;
}

// Pattern: useCallback for fetchActive and fetchHistory; call both in useEffect.
// Auth: authFetch from @/lib/auth (carries x-tenant-id header automatically).
// featureEnabled: derived from activePrompt?.feature_enabled ?? false
//   → when false, render "Feature coming soon" notice in the tab instead of edit form.
// On 403: member role — render read-only view (no Save, no Restore buttons).
```

---

#### Frontend: Tab UI layout

**Tab label:** "System Prompt" — added to the existing tab bar next to "Company & Plan" and "Usage".

**Active prompt display (read state, all roles):**
```
┌─────────────────────────────────────────────────────┐
│ Outreach System Prompt                               │
│ ─────────────────────────────────────────────────── │
│ This text is sent to the AI as brand context when   │
│ generating all outreach drafts.                      │
│                                                      │
│ [textarea — 6 rows — full width]                     │
│                                                      │
│ 142 / 1,500 characters          [warning at 1,400]  │
│                                                      │
│ [Save]  (disabled when member or saving)             │
│                                                      │
│ Last updated: Mar 16, 2026 by owner@example.com      │
└─────────────────────────────────────────────────────┘
```

**Character counter logic:**
```typescript
const charCount = promptText.length;
const isOverLimit = charCount > 1500;
const isNearLimit = charCount >= 1400;

// Counter element classes:
// default: inline, no special style
// isNearLimit: add inline color warning ("color: var(--color-warning)")
// isOverLimit: add inline color danger ("color: var(--color-danger)") + disable Save button
```

**Save flow:**
1. User edits textarea → `setPromptText(val)` → char counter updates live.
2. User clicks Save → `setSaving(true)` → call `save(promptText)`.
3. On success: refetch `activePrompt` and `history`; show inline "Saved" confirmation for 3s.
4. On error (`PROMPT_TOO_LONG`, `PROMPT_SAFETY_VIOLATION`): show `saveError` message below textarea; do not clear the textarea.
5. On `changed: false`: show "No changes detected" message.

**Member read-only view:**
```typescript
// When role === "member": render the prompt text in a <pre> or disabled <textarea>
// Hide Save button and character counter
// Hide history Restore buttons
```

**Version history section** (below the prompt form, collapsible):

```
▼ Version History (3 versions)
─────────────────────────────────────────────────────
  ● Active — Mar 16, 2026 — owner@example.com — tenant
    "You are a fitness brand partnership specialist..."   [120-char preview]

  ○ Mar 10, 2026 — owner@example.com — tenant
    "You are a creator outreach specialist..."
    [Restore this version]

  ○ Mar 1, 2026 — owner@example.com — tenant
    "You are a creator discovery specialist..."
    [Restore this version]
```

Implementation:
- `● / ○` bullet: `is_active ? "●" : "○"` in the row
- Preview: `version.prompt.slice(0, 120) + (version.prompt.length > 120 ? "…" : "")`
- "Restore this version" button: calls `revert(version.version_id)` → `setSaving(true)` → on success refetch both active + history
- History section starts collapsed (`useState(false)` for `historyOpen`); toggle with a `<button>` labeled `▼ / ▶ Version History (N versions)`

**CSS classes / patterns to use:**
- Outer card: wrap in a div with `className="admin-surface-box"` style (or equivalent settings surface box if one exists — check `globals.css`) with `padding: 1.5rem`, `border: 1px solid var(--color-border)`, `border-radius: 6px`
- Section title: match existing settings page `<h3>` style
- Textarea: `style={{ width: "100%", fontFamily: "monospace", fontSize: "0.875rem", padding: "0.75rem", borderRadius: "4px", border: "1px solid var(--color-border)", resize: "vertical" }}`
- Save button: match existing settings save button pattern (likely a `<button className="btn-primary">` or inline `backgroundColor: "var(--color-primary)"` style)
- Char counter: `<span style={{ fontSize: "0.75rem", color: isNearLimit ? "var(--color-warning)" : "var(--color-muted)" }}>{charCount} / 1,500</span>`
- No external UI libraries — no shadcn/ui, no Radix, no charting libs

---

#### E2E test coverage

**File:** `web/tests/e2e/settings_drafting_prompt.spec.ts`

Flows to cover:
1. Owner navigates to Settings → "System Prompt" tab — tab renders, textarea contains active prompt or placeholder.
2. Owner types a new prompt → char count updates live.
3. Owner types 1,400+ chars → counter turns orange/warning color.
4. Owner saves → "Saved" confirmation appears → textarea shows new value.
5. Version history section toggle (collapsed/expanded) — 1 row visible after first save.
6. Owner clicks "Restore this version" → active prompt reverts → history shows 1 new row.
7. Member user navigates to System Prompt tab → textarea is read-only, Save button absent, Restore buttons absent.

**Tasks**
1. Create `web/src/hooks/use-drafting-prompt.ts` following the `useCallback`/`useEffect` pattern of existing hooks.
2. Add `"drafting-prompt"` to `SettingsTab` type in `settings/page.tsx`.
3. Add tab button for "System Prompt" to the tab bar.
4. Implement `DraftingPromptTab` inline or extract to `web/src/components/settings/drafting-prompt-tab.tsx`.
5. Implement textarea + char counter + save + member read-only within the tab component.
6. Implement version history section with collapse toggle, preview rows, and Restore buttons.
7. Write `settings_drafting_prompt.spec.ts` covering the 7 flows above.
8. Run `cd web && npm run lint` and `cd web && npx tsc --noEmit` — both must be clean.

**Definition of Done (DoD)**
- [ ] "System Prompt" tab renders for owner/admin; prompts visible and editable.
- [ ] Char counter updates on every keystroke; warning threshold visible at 1,400 chars.
- [ ] Save succeeds → history list shows 1 new version.
- [ ] Restore reverts content and adds a `tenant_revert` history row.
- [ ] Member sees read-only prompt; Save and Restore controls absent.
- [ ] `cd web && npm run test:e2e:stable` green on `settings_drafting_prompt.spec.ts`.
- [ ] `cd web && npm run lint` and `tsc --noEmit` clean.

---

## Epic 5 — Admin Tenant UI

> **Gate:** E2E test `admin_prompt_history.spec.ts` stable; admin_discoverability.spec.ts unbroken.

### Story 5.1 — "Prompt History" tab on admin tenant detail page

**Status:** `[ ]`

**Outcome:** Superadmins see a "Prompt History" tab on the tenant detail page. The tab shows the full version history with actor, source, and preview. A "Revert" button triggers the admin revert endpoint.

**New files**

| File | Purpose |
|---|---|
| `web/src/components/admin/tenant-detail/tenant-prompt-history-tab.tsx` | Prompt history tab component |
| `web/src/hooks/admin/use-admin-prompt-history.ts` | Data fetching hook for admin prompt history and revert |
| `web/tests/e2e/admin_prompt_history.spec.ts` | E2E spec |

**Modified files**

| File | Change |
|---|---|
| `web/src/components/admin/tenant-detail/types.ts` | Add `"prompt-history"` to `TenantDetailTab` union |
| `web/src/app/admin/tenants/[id]/page.tsx` | Add tab button; render `TenantPromptHistoryTab` for active tab |

---

#### Frontend: Tab layout

The admin detail page uses a tab pattern with dark nav and consistent tab body padding. Follow the exact same structure as `TenantBillingTab`, `TenantMembersTab`, etc.

```
┌─── Prompt History ────────────────────────────────────────────────────────┐
│                                                                            │
│  Drafting system prompt version history for this tenant.                  │
│  Superadmin reverts take effect immediately.                              │
│                                                                            │
│  ┌───────────────────────────────────────────────────────────────────┐    │
│  │ # │ Date             │ Actor             │ Source         │ Active │    │
│  │ 1 │ Mar 16, 2026     │ owner@example.com │ tenant         │ ●      │    │
│  │   │ "You are a fitness brand..."                 [View] [Revert]  │    │
│  │ 2 │ Mar 10, 2026     │ owner@example.com │ tenant         │        │    │
│  │   │ "You are a creator outreach..."              [View] [Revert]  │    │
│  └───────────────────────────────────────────────────────────────────┘    │
│                                                                            │
│  [View] expands the full prompt inline (not a modal). [Revert] prompts    │
│  a confirmation: "Revert this tenant's prompt to the selected version?"   │
│  On confirm → POST admin revert endpoint → toast "Reverted" → refetch.   │
└────────────────────────────────────────────────────────────────────────────┘
```

**Source badge display:**
- `"tenant"` → `<AdminStatusBadge variant="muted">tenant</AdminStatusBadge>`
- `"tenant_revert"` → `<AdminStatusBadge variant="info">tenant revert</AdminStatusBadge>`
- `"admin_revert"` → `<AdminStatusBadge variant="warning">admin revert</AdminStatusBadge>`

**Active indicator:** `is_active` → `"●"` in the Active column; `""` otherwise.

**[View] button:** toggles inline expansion of the full `version.prompt` in a `<pre>` block below the row. Only one row expanded at a time (`expandedId` state). No modal.

**[Revert] button:**
- Disabled for the currently active version.
- On click: show an inline confirmation row (not a modal): "Revert to this version? [Confirm] [Cancel]"
- On Confirm: call `revert(version_id)` → on success: `showToast("Prompt reverted", "success")` → refetch.

**Hook pattern:**
```typescript
// web/src/hooks/admin/use-admin-prompt-history.ts
// Same pattern as existing admin hooks (useCallback for fetch, useEffect to trigger on tenantId change)
// Auth: { Authorization: `Bearer ${token}` } from sessionStorage["cdo.admin.access-token"]
// On 401: call onUnauthorized()
```

**E2E flows** (`web/tests/e2e/admin_prompt_history.spec.ts`):
1. Superadmin opens tenant detail → "Prompt History" tab visible.
2. Tab renders version history table with at least 1 row.
3. [View] expands full prompt inline; second [View] click on same row collapses it.
4. [Revert] on active version is disabled.
5. [Revert] on older version → confirmation row appears → Confirm → toast "Prompt reverted" → version 1 is now active.
6. Non-superadmin (support role) → "Prompt History" tab not rendered (or 403 on data fetch).

**Tasks**
1. Add `"prompt-history"` to `TenantDetailTab` in `types.ts`.
2. Create `use-admin-prompt-history.ts` hook.
3. Create `tenant-prompt-history-tab.tsx` component; use `AdminDataTable`, `AdminStatusBadge` per CLAUDE.md reusable component conventions.
4. Add tab button and conditional render in `tenants/[id]/page.tsx`.
5. Write `admin_prompt_history.spec.ts` covering the 6 flows.
6. Run `npm run lint` and `tsc --noEmit` clean.

**Definition of Done (DoD)**
- [ ] "Prompt History" tab visible to superadmin; hidden or 403 for support role.
- [ ] Table renders all version rows with correct source badge and active indicator.
- [ ] [View] toggle works inline without modal.
- [ ] [Revert] fires admin revert endpoint; toast confirms; history refetches with new active row.
- [ ] `cd web && npm run test:e2e:stable` green on `admin_prompt_history.spec.ts`.
- [ ] Existing `admin_discoverability.spec.ts` remains green (tab structure unchanged for other tabs).

---

## 3) Testing workstream

Aligned with `docs/05_quality/testing_strategy.md` naming conventions.

### 3.1 Unit tests

**Location:** `backend/tests/unit/`

| New file | Coverage |
|---|---|
| `unit/domain/test_prompt_validation.py` | `validate_prompt_length` boundary (1499/1500/1501 chars), strip behavior; `is_identical_to_active` exact match, whitespace differences, None active version |
| `unit/services/test_prompt_service.py` | `save_prompt`: length rejection (no LLM call, rejection log row created, security alert emitted), safety rejection (DB unchanged, rejection log row created, security alert emitted), idempotency (no version row), successful save (version + settings updated + notification), LLM failure → no rejection log row, empty-string save → NULL + version row with `prompt = ""`, repeated-attempts escalation (≥3 in 24h → alert includes warning); `revert_prompt`: wrong tenant version_id → error; correct version → new row with source="tenant_revert" |
| `unit/integrations/test_openai_provider.py` | **New file.** `generate_text` with `system_prompt` → 2 messages (system + user); without → 1 message; `generate_structured` with custom `system_prompt` → uses that string; without → uses `SCORING_DEFAULT_SYSTEM_PROMPT` |
| `unit/services/test_drafting_service.py` (additions) | `generate_text` called with `system_prompt=custom` when custom set; `system_prompt=SYSTEM_DEFAULT` when null |
| `unit/services/test_scoring_service_prompt.py` | **New file.** Global config with `scoring_system_prompt` set → `generate_structured` receives that value; global config with `scoring_system_prompt=None` → `generate_structured` receives `None` |

**DoD:** `make test-unit` green; all new test files added to the inventory in `docs/05_quality/testing_strategy.md`.

### 3.2 Integration tests

**Location:** `backend/tests/integration/`

| New file | Coverage |
|---|---|
| `integration/test_prompt_save.py` | Save → version created; identical content → no version row; safety rejection → DB unchanged + rejection log row created; revert → new version row with `tenant_revert` source; `tenant_settings.custom_drafting_prompt` updated atomically; empty-string save → NULL + version row with `prompt = ""`; repeated-attempts escalation at ≥3 rejections in 24h |
| `integration/test_prompt_admin.py` | Superadmin reads history across 3 versions; admin revert → `admin_revert` source row; support role → 403; unknown tenant → 404; superadmin reads per-tenant rejection log; superadmin reads fleet-wide rejection log with pagination |
| `integration/test_drafting_integration.py` | Tenant with custom prompt → `generate_text` receives correct `system_prompt`; tenant without custom prompt → receives `SYSTEM_DEFAULT_PROMPT` |
| `integration/test_scoring_prompt_config.py` | Global config `scoring_system_prompt` set → `generate_structured` receives that value; unset → receives `None` |

**DoD:** `make test-integration` green on all 4 new files.

### 3.3 Contract tests

**Location:** `backend/tests/contract/`

| File | Coverage |
|---|---|
| `contract/test_drafting_prompt_contracts.py` | GET → `is_custom` bool present; PUT → `changed` bool present; PUT with 1501 chars → 422 `PROMPT_TOO_LONG`; PUT with LLM failure → 503 `PROMPT_CLASSIFICATION_UNAVAILABLE`; history → `versions` array; revert with bad ID → 404 `PROMPT_VERSION_NOT_FOUND`; member PUT → 403; feature flag off → 501; admin rejection-log per-tenant → `rejections` array with `tenant_id` field; admin rejection-log fleet-wide → `rejections` array with pagination; rejection-log response shape includes `id`, `actor`, `rejection_type`, `rejection_reason`, `prompt_preview`, `created_at` |

**DoD:** `make test-contract` green; every error code in the catalog has a contract assertion.

### 3.4 E2E tests

**Location:** `web/tests/e2e/`

| New file | Coverage |
|---|---|
| `e2e/settings_drafting_prompt.spec.ts` | Owner save, char counter warning, history expand/collapse, restore revert, member read-only |
| `e2e/admin_prompt_history.spec.ts` | Superadmin view, [View] expand, [Revert] with confirmation, toast, support-role access denied |

**DoD:** `cd web && npm run test:e2e:stable` green on both new spec files; existing specs unbroken.

### 3.5 Migration verification

- [ ] `alembic upgrade head` succeeds.
- [ ] `alembic downgrade -1 && alembic upgrade head` succeeds with no data loss.
- [ ] DB revision guard passes at API startup.

### 3.6 CI gates

- [ ] `make test-unit`
- [ ] `make test-integration`
- [ ] `make test-contract`
- [ ] `make lint`
- [ ] `make typecheck`
- [ ] `cd web && npm run lint`
- [ ] `cd web && npx tsc --noEmit`
- [ ] `cd web && npm run test:e2e:stable`

---

## 4) Documentation update workstream

### 4.1 Architecture docs (`docs/01_architecture/`)
- [ ] Create `llm_prompt_customization.md` — one page covering: how the custom prompt is stored, how it is injected as the system-role message, how the safety gate works, and that `drafting.jinja` was retired. Keep it to ~1 page.

### 4.2 Runbooks (`docs/03_runbooks/`)
- [ ] Create `prompt_revert.md` — short runbook: how a superadmin reverts a tenant prompt via the admin UI and via the API directly. Include the curl commands.

### 4.3 Security docs (`docs/04_security/`)
- [ ] Update LLM trust model section with: prompt injection threat, classification gate approach, fail-closed policy, positional separation of system vs user role.

### 4.4 Quality docs (`docs/05_quality/testing_strategy.md`)
- [ ] Add new unit test files (5) to the unit inventory tables.
- [ ] Add new integration test files (4) to the integration inventory table.
- [ ] Add new contract test file (1) to the contract inventory table.
- [ ] Add new E2E spec files (2) to the E2E inventory table.
- [ ] Update file counts in the Test Pyramid Overview table.

**Documentation DoD**
- [ ] All 4 doc updates are in the same PR as the final implementation story.
- [ ] No documentation section contradicts the shipped behavior.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

After all epic gates are green and the implementation is complete, scope one focused refactor pass:

1. **Inline prompt string in `drafting_service.py`** — The per-creator user-role prompt is currently assembled via string concatenation. Extract into a named function `_build_draft_user_prompt(creator, item, evidence) -> str` for readability and testability.
2. **Notification coupling** — `billing_notifications_service.py` may not be the natural home for `notify_prompt_saved`. If it feels out of place after implementation, extract to a `notification_service.py` module that handles all superadmin notifications.
3. **Dead code audit** — Confirm no references to `drafting.jinja` remain anywhere (grep `drafting.jinja`). Remove any dead imports.

### 5.2 Guardrails

- [ ] `make test-unit && make test-integration && make test-contract` green before and after refactor.
- [ ] `make lint && make typecheck` clean.
- [ ] No product behavior changes — only internal structure.
- [ ] No expansion of scope during this pass.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `LLMProvider.generate_text()` signature extension | S3.1, S3.2 | Planned | Blocks prompt injection into drafting |
| `LLMProvider.generate_structured()` signature extension | S3.1, S3.3 | Planned | Blocks configurable system prompt for scoring |
| Resend client (existing) | S2.1 | Implemented | Notification degrades to audit log only |
| `custom_drafting_prompt_enabled` global config flag | S2.2 | Planned — new boolean on `GlobalAdminConfiguration` | Feature cannot be staged without it; add in S1.1 migration |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| LLM classification call adds 1-2s to every prompt save | M | M | Acceptable per NFR (p95 < 3s); cache classification result for identical prompt text |
| `generate_text()` signature change breaks existing callers | L | H | `system_prompt=None` default; `make test-unit` catches regressions immediately |
| `drafting.jinja` deletion reveals a caller we missed | L | H | Grep `drafting.jinja` across entire repo before deletion; CI typecheck will catch missing imports |
| Admin notification email floods superadmin on tenant revert storms | L | L | Identical-content gate prevents most noise; no email on `admin_revert` source (audit log only per §18 decision) |

---

## 7) Sequencing and parallelization

### Suggested sequence

1. **S1.1** — data foundation; migration green ✓
2. **S2.1** — prompt service (no API yet)
3. **S2.2 + S2.3** — API endpoints (can run in parallel once S2.1 done)
4. **S3.1** — LLM abstraction (no dependency on S2.x)
5. **S3.2** — drafting wiring (depends on S3.1 and S1.1)
6. **S3.3** — scoring system prompt (depends on S3.1; no dependency on S2.x or S3.2)
7. **S4.1 + S5.1** — frontend (depends on S2.2/S2.3 being live; can run in parallel with each other)
8. **Refactor** — after all gates green

### Parallelization opportunities

- S2.2 and S2.3 can be written simultaneously by different contributors; both depend only on S2.1.
- S3.1 (LLM abstraction) can start in parallel with S2.1 — no shared dependencies.
- S4.1 (tenant UI) and S5.1 (admin UI) can be built simultaneously after S2.2/S2.3 are live.

---

## 8) Rollout and cutover plan

- **Stage 1 (internal):** Enable `custom_drafting_prompt_enabled = True` on a single internal tenant. Verify draft quality and superadmin notification end-to-end.
- **Stage 2 (limited):** Enable for 5–10 willing pilot tenants. Monitor prompt save volume, classification rejection rate, and draft quality feedback.
- **Stage 3 (full):** Enable globally via the `GlobalAdminConfiguration` flag.
- **Feature flag management:** `custom_drafting_prompt_enabled` is a boolean column on `GlobalAdminConfiguration`. Set via `PUT /admin/configuration` (existing endpoint). No code deploy required to toggle.
- **Backfill:** None. All existing tenants start with `custom_drafting_prompt = NULL` → system default behavior preserved.

---

## 9) Execution tracker

### Epic 1 — Data and Domain Foundation
- [x] S1.1 — Schema, ORM, repo, domain validation

### Epic 2 — Backend Service and API
- [x] S2.1 — Prompt service (classification + versioning + notification)
- [x] S2.2 — Tenant API endpoints (GET/PUT/history/revert)
- [x] S2.3 — Admin API endpoints (GET history, POST revert, GET rejection-log per-tenant, GET rejection-log fleet-wide)

### Epic 3 — LLM Abstraction + Drafting Wiring
- [x] S3.1 — Extend LLM abstraction with `system_prompt` param (both `generate_text` and `generate_structured`)
- [x] S3.2 — Wire prompt into drafting service; retire `drafting.jinja`
- [x] S3.3 — Scoring system prompt: migration + scoring service wiring + admin UI textarea

### Epic 4 — Tenant Settings UI
- [x] S4.1 — "System Prompt" tab on settings page

### Epic 5 — Admin Tenant UI
- [x] S5.1 — "Prompt History" tab on admin tenant detail page

### Refactor
- [x] R1 — Post-implementation lean refactor

### Documentation
- [x] D1 — `docs/01_architecture/llm_prompt_customization.md` created
- [x] D2 — `docs/03_runbooks/prompt_revert.md` created
- [x] D3 — `docs/04_security/` LLM trust model updated
- [x] D4 — `docs/05_quality/testing_strategy.md` inventory updated

### Blocked items
_None._

---

## 10) Story-by-Story Verification Gate (Agent Checklist)

Before marking any story `[x]`:

- [ ] Files created/modified match the story's `New files` / `Modified files` tables exactly.
- [ ] Endpoint contract implemented exactly as documented (method / path / body / status / error code).
- [ ] Key interfaces implemented with compatible signatures (type hints match).
- [ ] Required tests added for all applicable layers (unit / integration / contract / E2E).
- [ ] Commands executed and passed:
    - [ ] `make test-unit`
    - [ ] `make test-integration` (or targeted subset with explanation)
    - [ ] `make test-contract`
    - [ ] `make lint && make typecheck`
    - [ ] `cd web && npm run lint && npx tsc --noEmit` (if frontend touched)
    - [ ] `cd web && npm run test:e2e:stable` (if UI touched)
- [ ] Migration round-trip evidence provided if schema changed.
- [ ] `docs/05_quality/testing_strategy.md` updated in the same PR when new test files are added.

---

## 11) Definition of plan done

This implementation plan is execution-ready when:

- [x] Every FR from the spec is mapped to a story with test and doc coverage.
- [x] Every story includes New/Modified files, Endpoints, Key interfaces, Pydantic schemas, Tasks, and DoD.
- [x] Test layers (unit/integration/contract/E2E) explicitly scoped with file names aligned to `docs/05_quality/testing_strategy.md` conventions.
- [x] Documentation updates across docs/01, docs/03, docs/04, docs/05 are planned.
- [x] Lean refactor scope and guardrails are explicit (§5).
- [x] Phase/epic gates are measurable.
- [x] Story-by-Story Verification Gate (§10) is included.
