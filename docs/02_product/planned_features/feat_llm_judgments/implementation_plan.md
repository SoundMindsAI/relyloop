# Implementation Plan — feat_llm_judgments

**Date:** 2026-05-11
**Status:** PR created — PR #35 awaiting merge (2026-05-11). Final cross-model review converged at cycle 10 ({"findings":[]}). After merge, a separate finalize PR moves the folder to `implemented_features/` and updates `state.md`.
**Primary spec:** [feature_spec.md](feature_spec.md) (Approved 2026-05-11)
**Policy source(s):**
- [docs/01_architecture/llm-orchestration.md](../../../01_architecture/llm-orchestration.md) — prompt directory layout, capability check, cost guardrail
- [docs/01_architecture/data-model.md](../../../01_architecture/data-model.md) — `judgments` table shape
- [docs/01_architecture/api-conventions.md](../../../01_architecture/api-conventions.md) — error envelope, cursor pagination, `X-Total-Count`

---

## 0) Planning principles

- Spec traceability first: every story/task maps to FR IDs.
- One LLM call per query (not per (query, doc)) — preserves the <$1 tutorial cost guardrail (spec §4).
- The `judgments` UNIQUE constraint on `(judgment_list_id, query_id, doc_id)` is the override contract — UPSERT-replace, not append.
- Re-running with a changed rubric creates a new list — never mutate rubric in place.
- Engine and LLM calls remain behind their existing abstractions (`SearchAdapter` Protocol, `openai` SDK direct in MVP1 per CLAUDE.md Absolute Rule #3).

---

## 1) Scope traceability (FR → epics/phases)

| FR ID | Epic / Story | Notes |
|---|---|---|
| FR-1 (judgments schema) | Epic 1 / Story 1.1 (migration) + 1.2 (ORM/repo) | Single migration `0004_judgments`; CHECK `rating BETWEEN 0 AND 3`; CHECK `source IN ('llm','human','click')`; UNIQUE `(judgment_list_id, query_id, doc_id)` |
| FR-2 (worker job) | Epic 2 / Story 2.1 | `generate_judgments_llm` Arq job in `backend/workers/judgments.py`; registered in `WorkerSettings.functions` |
| FR-3 (generate endpoint) | Epic 3 / Story 3.1 | `POST /api/v1/judgments/generate`; capability cache → `LLM_PROVIDER_INCAPABLE`; missing key → `OPENAI_NOT_CONFIGURED` |
| FR-3b (import endpoint) | Epic 3 / Story 3.2 | `POST /api/v1/judgment-lists/import`; tutorial no-OpenAI path |
| FR-3c (starter rubric) | Epic 1 / Story 1.3 | `prompts/judgment_generation.rubric_v1.md` exact content from spec §FR-3c |
| FR-4 (override endpoint) | Epic 3 / Story 3.4 | `PATCH …/judgments/{id}`; UPSERT with `source='human'`; `INVALID_RATING` 400; `LIST_NOT_READY` 409 per spec §11 |
| FR-5 (calibration endpoint) | Epic 3 / Story 3.5 | `POST …/calibration`; Cohen's + weighted kappa via `backend/app/eval/calibration.py` |
| FR-6 (list + detail + paginated) | Epic 3 / Story 3.3 | `GET …/judgment-lists`, `…/{id}`, `…/{id}/judgments` |
| Spec §15 docs | Epic 4 / Stories 4.1 + 4.2 + 4.3 | `docs/04_security/llm-data-flow.md`, `docs/03_runbooks/judgment-generation-debugging.md`, `mvp1-user-stories.md` flips |

**Deferred phase tracking:** Spec §3 declares **single-phase** ("The MVP1 deliverable is to generate the tutorial judgment list end-to-end"). No `phase2_idea.md` required.

---

## 2) Delivery structure

Epic → Story → Tasks → DoD.

### Story-level detail requirements

Each story below includes: **Outcome · New files · Modified files · Endpoints (when API-facing) · Key interfaces · Pydantic schemas (when API-facing) · Tasks · DoD**. No UI scope in this feature, so no UI element inventories / state dependency analysis / Legacy behavior parity tables — explicitly stated where applicable.

### Conventions (project-specific — applies to every story)

- All repo functions take `db: AsyncSession` as first arg; use `db.flush()` (caller commits) per [CLAUDE.md §"Repository Layer"](../../../../CLAUDE.md).
- Services / worker jobs are async; create `judgment_lists` row + commit upfront so the worker is fully self-contained on `judgment_list_id` (matches the orchestrator's durable-handoff pattern in Phase 2).
- Domain / eval layer is pure — no DB access, no I/O.
- Models use `Mapped[]` typed columns, `String(36)` UUIDs (matches existing `JudgmentList`, `Study`, `Trial`).
- Routers return typed Pydantic response models; errors use `HTTPException(detail={"error_code","message","retryable"})` (per `backend/app/api/errors.py`).
- LLM access via the `openai` SDK directly (CLAUDE.md Rule #3 — MVP1 abstraction-deferred); always read `OPENAI_BASE_URL` / `OPENAI_MODEL` from `Settings`.
- All `backend/app/db/models/__init__.py` and `backend/app/db/repo/__init__.py` `__all__` entries are updated when new models / repo functions ship.
- Migration numbering: head is `0003_study_lifecycle_schema`; this feature ships `0004_judgments` (next sequential).

### AI Agent Execution Protocol

0. Load context: read `CLAUDE.md`, `architecture.md`, `state.md`, and this plan top-to-bottom before the first story.
1. Read scope of the current story (Outcome, New/Modified files, Endpoints, Key interfaces, DoD).
2. Backend-first per story: model → migration → repo → eval/domain → worker (when applicable) → router → schemas.
3. Run unit + integration + contract tests after each story; if migration touched, also `alembic upgrade head && alembic downgrade -1 && alembic upgrade head`.
4. Frontend: N/A (no UI in this feature).
5. E2E: N/A.
6. Update docs/checklists in the same PR when behavior/contract changed.
7. Migration round-trip verified before merging Story 1.1.
8. Attach evidence (commands run, pass/fail) in the PR description.
9. After the final story, update `state.md` + `architecture.md` per §4.0.

---

## Epic 1 — Foundations (schema, prompts, eval helpers, qrels-loader replacement)

### Story 1.1 — `judgments` table migration (FR-1)

**Outcome:** The `judgments` child table exists in Postgres at Alembic head `0004_judgments`; round-trips cleanly.

**New files**

| File | Purpose |
|---|---|
| `migrations/versions/0004_judgments.py` | Create `judgments` table; UNIQUE `(judgment_list_id, query_id, doc_id)`; FK `judgment_list_id → judgment_lists(id) ON DELETE CASCADE`; FK `query_id → queries(id)`; CHECK `rating BETWEEN 0 AND 3`; CHECK `source IN ('llm','human','click')`. `downgrade()` drops the table. |

**Modified files**

| File | Change |
|---|---|
| `state.md` | Bump Alembic head to `0004_judgments` after Story 1.1 lands (in the post-impl-execute finalization, not this story specifically). |

**Tasks**

1. Create `migrations/versions/0004_judgments.py` with `revision="0004"` and `down_revision="0003"` (matching the `0003_study_lifecycle_schema` style).
2. `upgrade()`: `op.create_table("judgments", ...)` per the column list in [data-model.md §"judgment_lists and judgments"](../../../01_architecture/data-model.md): `id String(36) PK`, `judgment_list_id String(36) NOT NULL FK CASCADE`, `query_id String(36) NOT NULL FK NO ACTION`, `doc_id Text NOT NULL`, `rating SmallInteger NOT NULL CHECK 0..3`, `source Text NOT NULL CHECK ('llm','human','click')`, `rater_ref Text`, `confidence Float`, `notes Text`, `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`. Add `UniqueConstraint("judgment_list_id","query_id","doc_id", name="judgments_unique_key")`.
3. Add index `judgments_list_query_idx` on `(judgment_list_id, query_id)` for the qrels loader's `SELECT … WHERE judgment_list_id = :id` workload (groups by query_id in Python).
4. `downgrade()`: `op.drop_table("judgments")`.
5. Run `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` and capture output for the PR description.

**Definition of Done (DoD)**

- [ ] Migration file at `migrations/versions/0004_judgments.py` exists; `alembic upgrade head` succeeds locally and in CI.
- [ ] Round-trip works: `alembic downgrade -1` (back to `0003`) and `alembic upgrade head` both succeed.
- [ ] CHECK constraints + UNIQUE constraint + FK targets verified via an integration test that introspects `information_schema.check_constraints`, `information_schema.referential_constraints`, and `pg_constraint` (mirrors the Story 1.2 / 1.4 pattern from `feat_study_lifecycle` Phase 1).
- [ ] No changes to `judgment_lists` (Absolute Rule from spec §3 / §9: this feature **never** migrates `judgment_lists`).
- [ ] No changes to MVP1 status code in `state.md` beyond the Alembic head bump (the finalization step handles `state.md` updates).

---

### Story 1.2 — `Judgment` ORM model + repo functions (FR-1 + FR-6 backing)

**Outcome:** `Judgment` is registered with `Base.metadata`. Repo functions cover create, bulk-create, UPSERT (override), get, list, count, and source-breakdown.

**New files**

| File | Purpose |
|---|---|
| `backend/app/db/models/judgment.py` | `Judgment` ORM model — columns mirror migration; CHECK constraints declared via `__table_args__`. |
| `backend/app/db/repo/judgment.py` | Repo functions: `create_judgment`, `bulk_create_judgments`, `upsert_judgment_human_override`, `get_judgment`, `list_judgments_paginated`, `count_judgments_for_list`, `source_breakdown_for_list`, plus judgment_list extensions `list_judgment_lists`, `count_judgment_lists`, `update_judgment_list_status`, `update_judgment_list_calibration`. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/db/models/__init__.py` | Import + `__all__` entry: `Judgment` (alphabetical between `JudgmentList` and `Proposal`). |
| `backend/app/db/repo/__init__.py` | Re-export new functions; update `__all__`. Add to module-level import grouping. Also re-export the new judgment_list extensions (`list_judgment_lists`, `count_judgment_lists`, `update_judgment_list_status`, `update_judgment_list_calibration`, `list_generating_judgment_list_ids`). |
| `backend/app/db/repo/judgment_list.py` | Add `list_judgment_lists(db, *, cursor, limit) -> list[JudgmentList]`, `count_judgment_lists(db) -> int`, `update_judgment_list_status(db, id, *, status, failed_reason=None) -> JudgmentList`, `update_judgment_list_calibration(db, id, calibration: dict) -> JudgmentList`, `list_generating_judgment_list_ids(db) -> list[str]` (consumed by `WorkerSettings.on_startup` resume sweep in Story 2.1; see GPT-5.5 F14 adjudication). Caller commits in all five. |
| `backend/tests/integration/conftest.py` | Extend the `_clean_phase2_tables` fixture to wipe `judgments` first in FK-safe order (before `judgment_lists`). Cascade would handle it but explicit DELETE is safer + matches the existing pattern. |

**Key interfaces**

```python
# backend/app/db/models/judgment.py
from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, SmallInteger, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

class Judgment(Base):
    __tablename__ = "judgments"
    __table_args__ = (
        CheckConstraint("rating BETWEEN 0 AND 3", name="judgments_rating_check"),
        CheckConstraint("source IN ('llm', 'human', 'click')", name="judgments_source_check"),
        UniqueConstraint("judgment_list_id", "query_id", "doc_id", name="judgments_unique_key"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    judgment_list_id: Mapped[str] = mapped_column(String(36), ForeignKey("judgment_lists.id", ondelete="CASCADE"), nullable=False)
    query_id: Mapped[str] = mapped_column(String(36), ForeignKey("queries.id"), nullable=False)
    doc_id: Mapped[str] = mapped_column(Text, nullable=False)
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    rater_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
```

```python
# backend/app/db/repo/judgment.py
from sqlalchemy import select, func, delete, insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import Judgment, JudgmentList

async def create_judgment(db: AsyncSession, **fields: object) -> Judgment: ...
async def bulk_create_judgments(db: AsyncSession, rows: list[dict]) -> int:
    """Insert many; returns inserted count. Uses INSERT...ON CONFLICT DO NOTHING
    keyed on the UNIQUE constraint so partial-success during worker retries is
    idempotent (a row that already exists is skipped, not duplicated)."""
async def upsert_judgment_human_override(
    db: AsyncSession,
    *,
    judgment_list_id: str,
    query_id: str,
    doc_id: str,
    rating: int,
    rater_ref: str = "operator",
    notes: str | None = None,
) -> Judgment:
    """INSERT...ON CONFLICT (judgment_list_id, query_id, doc_id) DO UPDATE
    SET rating, source='human', rater_ref, notes, confidence=NULL, created_at=now()
    RETURNING *. Mutates the row in place — the original LLM row is overwritten
    (AC-2 contract; spec §4 + §9 explicit decision)."""
async def get_judgment(db: AsyncSession, judgment_id: str) -> Judgment | None: ...
async def list_judgments_paginated(
    db: AsyncSession,
    judgment_list_id: str,
    *,
    cursor: tuple[datetime, str] | None = None,
    limit: int = 50,
    source: str | None = None,  # None | 'llm' | 'human' | 'click'
) -> list[Judgment]: ...
async def count_judgments_for_list(
    db: AsyncSession, judgment_list_id: str, *, source: str | None = None
) -> int: ...
async def source_breakdown_for_list(
    db: AsyncSession, judgment_list_id: str
) -> dict[str, int]:
    """Returns {'llm': N, 'human': M}. Missing keys are 0.

    Per spec FR-6 the response shape names only `llm` and `human`. Rows
    with source='click' (reserved for v1.5+) are **deterministically folded
    into the `human` bucket** so `llm + human == judgment_count` always
    holds (addresses GPT-5.5 cycle 2 F6 — the original wording allowed
    either folding OR dropping, breaking that invariant). Click rows do not
    exist in MVP1 so this is a forward-compat behavior, but the contract is
    fixed now."""
```

```python
# backend/app/db/repo/judgment_list.py (additions)
async def list_judgment_lists(
    db: AsyncSession, *, cursor: tuple[datetime, str] | None = None, limit: int = 50
) -> list[JudgmentList]: ...
async def count_judgment_lists(db: AsyncSession) -> int: ...
async def update_judgment_list_status(
    db: AsyncSession, judgment_list_id: str, *, status: str, failed_reason: str | None = None
) -> JudgmentList: ...
async def update_judgment_list_calibration(
    db: AsyncSession, judgment_list_id: str, calibration: dict[str, object]
) -> JudgmentList: ...
async def list_generating_judgment_list_ids(db: AsyncSession) -> list[str]:
    """SELECT id FROM judgment_lists WHERE status='generating'. Consumed by
    WorkerSettings.on_startup in Story 2.1 to re-enqueue judgment-generation
    jobs whose original enqueue failed (mirrors the studies resume pattern
    in `backend/workers/all.py:on_startup`). Addresses GPT-5.5 cycle 1 F14."""
```

**Tasks**

1. Create `Judgment` ORM model; register via `backend/app/db/models/__init__.py`.
2. Create `backend/app/db/repo/judgment.py` with all functions above; use `pg_insert(Judgment).on_conflict_do_nothing(index_elements=["judgment_list_id","query_id","doc_id"])` for bulk, and `on_conflict_do_update(...)` for the human-override path.
3. Add the four `judgment_list` extensions in `backend/app/db/repo/judgment_list.py`.
4. Update `backend/app/db/repo/__init__.py` `__all__` (alphabetical).
5. Update `backend/tests/integration/conftest.py` so `_clean_phase2_tables` deletes from `judgments` before `judgment_lists`.
6. Write integration tests in `backend/tests/integration/test_judgment_repo.py` (NEW file): create_judgment + UNIQUE rejection, bulk_create idempotency on conflict, upsert_human_override replace path, list_judgments pagination + source filter, source_breakdown returns counts, update_judgment_list_status, update_judgment_list_calibration.

**Definition of Done (DoD)**

- [ ] `backend/app/db/models/judgment.py` exists; `Judgment` registered with `Base.metadata`.
- [ ] All repo functions listed in **Key interfaces** ship and follow the conventions (`db.flush()` only; caller commits).
- [ ] Integration test `test_judgment_repo.py` covers UNIQUE constraint, bulk-create idempotency, override UPSERT replace semantics, paginated list + filter, source breakdown, list_judgment_list status/calibration updates — all green.
- [ ] `__all__` entries in `backend/app/db/models/__init__.py` and `backend/app/db/repo/__init__.py` extended; `make lint` clean.
- [ ] `_clean_phase2_tables` fixture extended for `judgments`; existing integration tests still pass.

---

### Story 1.3 — Prompt files + Jinja loader (FR-3c)

**Outcome:** `prompts/judgment_generation.system.md`, `…user.jinja`, `…rubric_v1.md` exist. A SandboxedEnvironment-based loader function renders them with `(rubric_text, query_text, docs)` inputs.

**New files**

| File | Purpose |
|---|---|
| `prompts/judgment_generation.system.md` | System message: explains the rater role, references the rubric (rendered via `user.jinja`), emits structured-output requirement. |
| `prompts/judgment_generation.user.jinja` | Jinja user-message template: `{{ rubric_text }}` block + `{% for d in docs %}<doc id="{{ d.doc_id }}">{{ d.body }}</doc>{% endfor %}` + the query text in a `<query>` block. |
| `prompts/judgment_generation.rubric_v1.md` | Exact starter rubric copied verbatim from spec §FR-3c (3 / 2 / 1 / 0 scale with examples). |
| `backend/app/llm/prompt_loader.py` | `load_judgment_prompts() -> JudgmentPromptBundle`; `render_user_prompt(rubric_text, query_text, docs) -> str` using `jinja2.sandbox.SandboxedEnvironment` (matches the FR-7 / AC-7 sandbox swap used by `backend/app/domain/study/template_validator.py`'s `render.py`). Lazy-reads files once and caches via `lru_cache`. |
| `backend/tests/unit/workers/test_judgment_prompt_render.py` | Pure-Python tests of the renderer against canonical inputs (per spec §14 unit-test inventory). |

**Modified files**

None.

**Key interfaces**

```python
# backend/app/llm/prompt_loader.py
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from jinja2.sandbox import SandboxedEnvironment

@dataclass(frozen=True)
class JudgmentPromptBundle:
    system_prompt: str           # contents of system.md
    user_template_src: str       # raw Jinja source from user.jinja
    rubric_v1_text: str          # contents of rubric_v1.md

@lru_cache(maxsize=1)
def load_judgment_prompts() -> JudgmentPromptBundle: ...

def render_user_prompt(
    *,
    rubric_text: str,
    query_text: str,
    docs: list[dict[str, object]],  # [{doc_id: str, body: str}, ...]
) -> str:
    """Render the user-message template via SandboxedEnvironment. The docs list
    is XML-delimited (per spec §10 mitigation 1) to reduce prompt-injection
    surface. Caller passes the rubric_text from judgment_lists.rubric so
    operators can override the v1 rubric per-list."""
```

**Tasks**

1. Create `prompts/` directory at repo root.
2. Write the three prompt files. `rubric_v1.md` must contain spec §FR-3c verbatim (the "Relevance Rubric v1 — 3 — Highly relevant. … When in doubt between two ratings, choose the lower one — relevance ratings should be conservative." block).
3. Create `backend/app/llm/prompt_loader.py` with `load_judgment_prompts()` + `render_user_prompt()` using `SandboxedEnvironment` (matches `backend/app/domain/study/template_validator.py`'s sandbox pattern).
4. Write `backend/tests/unit/workers/test_judgment_prompt_render.py` (lives alongside `test_trials_unit.py`): test that the rendered user prompt contains the rubric text, each doc id, each doc body, and the query text; test that `{{` literal inside doc body / query renders as **literal text in the output** (proving Jinja does NOT recursively evaluate variable values — addresses GPT-5.5 cycle 1 F10). The SandboxedEnvironment exists to constrain what the template author can do (no attribute access, no callable invocation, restricted Python ops) — it does not auto-escape variable content. For the XML-delimited fields the safety contract is "literal text in / literal text out".

**Definition of Done (DoD)**

- [ ] Three `prompts/judgment_generation.*` files exist with the FR-3c content verbatim.
- [ ] `prompt_loader.py` exports `load_judgment_prompts` + `render_user_prompt` with the signatures above.
- [ ] Unit tests in `backend/tests/unit/workers/test_judgment_prompt_render.py` all pass and verify:
  - Rubric text appears in rendered output
  - Every (doc_id, body) pair appears in delimited form
  - Query text appears
  - Doc body containing the literal string `{{ malicious }}` appears verbatim in the rendered output (proving Jinja does not recursively evaluate variable values; SandboxedEnvironment constrains template-author capabilities, not variable content)
- [ ] `make lint && make typecheck` clean.

---

### Story 1.4 — OpenAI judge client (FR-2 hot-path helper)

**Outcome:** `backend/app/llm/openai_judge.py` exposes one function that, given a query + docs + rubric, makes a single batched call to `OPENAI_BASE_URL/chat/completions` with `response_format=json_schema` returning `[{doc_id, rating, rationale}]`. Token usage + cost are returned alongside.

**New files**

| File | Purpose |
|---|---|
| `backend/app/llm/openai_judge.py` | Async `rate_query_batch()` function; wraps the `openai.AsyncOpenAI` client with `base_url=Settings.openai_base_url`, exponential-backoff retry per spec §11 + llm-orchestration.md, structured-output JSON schema validation, token-usage + cost extraction. |
| `backend/app/llm/cost_model.py` | Pure-Python token → USD cost helper. `compute_call_cost(model, input_tokens, output_tokens) -> float` using a small dict of known model prices; falls back to `0.0` with a WARN log for unknown models. |
| `backend/tests/unit/llm/test_openai_judge_unit.py` | Tests structured-output JSON shape validation, retry-on-RateLimitError, cost extraction. Uses `httpx.MockTransport` to simulate OpenAI responses. |
| `backend/tests/unit/llm/__init__.py` | New unit-test subpackage marker. |

**Modified files**

None.

**Key interfaces**

```python
# backend/app/llm/openai_judge.py
from dataclasses import dataclass
from typing import Any
from openai import AsyncOpenAI

@dataclass(frozen=True)
class DocRating:
    doc_id: str
    rating: int        # 0..3
    rationale: str

@dataclass(frozen=True)
class JudgeCallResult:
    ratings: list[DocRating]
    input_tokens: int
    output_tokens: int
    cost_usd: float
    duration_ms: int
    model: str         # e.g. "gpt-4o-2024-08-06" (pinned via Settings; per Rule #8)

# Structured-output JSON schema — module-level constant so contract tests can
# import it.
RATING_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ratings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string"},
                    "rating": {"type": "integer", "minimum": 0, "maximum": 3},
                    "rationale": {"type": "string"},
                },
                "required": ["doc_id", "rating", "rationale"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["ratings"],
    "additionalProperties": False,
}

async def rate_query_batch(
    *,
    client: AsyncOpenAI,
    model: str,
    system_prompt: str,
    user_prompt: str,
    expected_doc_ids: set[str],
    max_retries: int = 3,
) -> JudgeCallResult:
    """Single batched OpenAI call returning ratings for every doc in user_prompt.

    Uses response_format=json_schema with RATING_RESPONSE_SCHEMA + strict=True
    so the parsed `.choices[0].message.parsed` (or content JSON-loaded) matches
    the schema exactly. On RateLimitError or 503, retries with exponential
    backoff (1s, 2s, 4s) up to max_retries before raising. usage.prompt_tokens
    / usage.completion_tokens feed compute_call_cost().

    `expected_doc_ids` (added per GPT-5.5 cycle 1 F9): the function validates
    every returned `doc_id ∈ expected_doc_ids` and drops ratings for any
    spurious id with a WARN log. Missing ids in the response are also logged
    at WARN; the caller (worker) decides whether to bulk-insert the partial
    result or skip the query. Returned `JudgeCallResult.ratings` contains
    ONLY validated rows."""
```

```python
# backend/app/llm/cost_model.py
# Module-level dict — single source of truth for known model pricing in MVP1.
# Update entries here when adding a new judgment model.
_MODEL_USD_PER_1K_INPUT: dict[str, float] = {
    "gpt-4o-2024-08-06": 0.0025,
    "gpt-4o-mini-2024-07-18": 0.00015,
}
_MODEL_USD_PER_1K_OUTPUT: dict[str, float] = {
    "gpt-4o-2024-08-06": 0.01,
    "gpt-4o-mini-2024-07-18": 0.0006,
}

class UnknownModelPricingError(RuntimeError):
    """Raised when a model has no pricing entry. Per GPT-5.5 cycle 2 F4: failing
    closed on unknown pricing prevents the daily budget gate from being silently
    defeated. The API translates this to 503 UNKNOWN_MODEL_PRICING at preflight;
    the worker translates to judgment_lists.failed_reason='UNKNOWN_MODEL_PRICING'
    if it somehow reaches the worker (defense in depth)."""

def compute_call_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Return USD cost for one OpenAI call.

    Per GPT-5.5 cycle 2 F4: **fails closed** on unknown models — raises
    UnknownModelPricingError rather than returning 0.0. Operators must add
    the model to _MODEL_USD_PER_1K_INPUT/OUTPUT before deploying it as
    Settings.openai_model."""
```

**Tasks**

1. Add `prompts` + `backend/app/llm` updates. Create `openai_judge.py` and `cost_model.py`.
2. Use `AsyncOpenAI(api_key=..., base_url=Settings.openai_base_url)` — read both from `get_settings()`. Never hardcode the model name (Rule #8); accept it as the `model` arg.
3. Retry policy: catch `openai.RateLimitError` and httpx 5xx; back off `2 ** attempt` seconds; max 3 attempts. On final failure, raise.
4. Structured output: use `response_format={"type":"json_schema","json_schema":{"name":"judgment_ratings","schema":RATING_RESPONSE_SCHEMA,"strict":True}}`. Parse `choices[0].message.content` (a JSON string) into `RATING_RESPONSE_SCHEMA`-conformant dict; convert to `list[DocRating]`.
5. Validate via the `expected_doc_ids: set[str]` argument (per GPT-5.5 cycle 1 F9): every returned `doc_id` is in `expected_doc_ids`; spurious ids are dropped with WARN; absent ids are logged at WARN but not raised. Only validated rows reach `JudgeCallResult.ratings`.
6. Cost: pull `response.usage.prompt_tokens` + `response.usage.completion_tokens`; call `compute_call_cost(model, ...)`.
7. Unit tests: mock the `AsyncOpenAI` client via `httpx.MockTransport` (the SDK delegates HTTP through httpx); cover happy path, retry on 429, retry on 503, exceeds-retries failure, structured-output parse failure (model returned non-JSON), cost calc.

**Definition of Done (DoD)**

- [ ] `backend/app/llm/openai_judge.py` exports `rate_query_batch`, `DocRating`, `JudgeCallResult`, `RATING_RESPONSE_SCHEMA`.
- [ ] `backend/app/llm/cost_model.py` exports `compute_call_cost`.
- [ ] Unit tests in `backend/tests/unit/llm/test_openai_judge_unit.py` cover happy-path, retry, exhausted-retries, and cost — all green.
- [ ] No model name hardcoded; `Settings.openai_model` is the only source.
- [ ] `make lint && make typecheck` clean.

---

### Story 1.5 — Calibration helper (FR-5 backing)

**Outcome:** `backend/app/eval/calibration.py` exposes `compute_calibration(human_samples, llm_ratings)` returning a `CalibrationResult` with Cohen's kappa, weighted (linear) kappa, per-class agreement, and `n_samples`. Pure Python; no DB.

**New files**

| File | Purpose |
|---|---|
| `backend/app/eval/calibration.py` | `compute_calibration()` + `CalibrationResult` TypedDict; uses NumPy or pure-Python for the kappa math. Mirrors the `backend/app/eval/scoring.py` neighbour. |
| `backend/tests/unit/eval/test_calibration.py` | Hand-computed kappa baselines (sklearn-equivalent expected values per spec §14). |

**Modified files**

| File | Change |
|---|---|
| `backend/app/eval/__init__.py` | Re-export `compute_calibration`, `CalibrationResult`. |

**Key interfaces**

```python
# backend/app/eval/calibration.py
from typing import TypedDict

class CalibrationResult(TypedDict):
    cohens_kappa: float | None        # None when undefined (no rating variance)
    weighted_kappa: float | None      # linear weights
    per_class: dict[str, float]       # {"0": 0.85, "1": 0.65, "2": 0.70, "3": 0.80}
    n_samples: int
    warning: str | None               # e.g. "no rating variance"; None when OK

def compute_calibration(
    pairs: list[tuple[int, int]],     # [(human_rating, llm_rating), ...]
) -> CalibrationResult:
    """Compute Cohen's + linear-weighted kappa + per-rating-class agreement.
    n_samples = len(pairs).
    When all ratings are identical (no variance), returns kappa=None +
    warning='no rating variance' (spec §11 edge case)."""
```

**Tasks**

1. Implement `compute_calibration` using NumPy if it simplifies the math (already a transitive dep via Optuna; check `pyproject.toml`); otherwise pure Python.
2. Per-class agreement: for each rating ∈ {0,1,2,3}, count where both human and LLM gave that rating divided by total times that rating appears in `human_samples`. (Spec §12 AC-3 shows the shape.)
3. Unit tests in `backend/tests/unit/eval/test_calibration.py`:
   - All-agree case: kappa = 1.0
   - All-disagree case: kappa = 0.0 or negative
   - No variance: kappa = None, warning set
   - Mixed case: hand-compute expected kappa via the standard formula; assert within `1e-6`
   - Weighted kappa with linear weights: hand-compute and assert
   - Per-class table shape

**Definition of Done (DoD)**

- [ ] `backend/app/eval/calibration.py` exists; `compute_calibration` matches the signature above.
- [ ] `backend/app/eval/__init__.py` re-exports the helper.
- [ ] All unit tests in `backend/tests/unit/eval/test_calibration.py` pass with hand-computed expected values.
- [ ] No external dependency added (use NumPy if already transitively available, otherwise pure Python).

---

### Story 1.6 — Replace `qrels_loader.py` stub with real implementation

**Outcome:** `backend/app/eval/qrels_loader.py` no longer raises `JudgmentsTableMissing`. Real `SELECT` against `judgments` returns `Qrels` keyed by `query_id`. The exception class stays (deprecated but importable) so any future references don't error; new code never raises it.

**Modified files**

| File | Change |
|---|---|
| `backend/app/eval/qrels_loader.py` | Replace the stub with real implementation. Drop the module-level "MVP1 stub" docstring; document the actual SELECT shape. Keep the `JudgmentsTableMissing` class definition for now (it's referenced by the existing infra_optuna_eval integration tests' monkeypatch contract — we update the docstring but don't delete the symbol). |

**Modified files (tests)**

| File | Change |
|---|---|
| `backend/tests/integration/test_run_trial.py` (and siblings) | Drop the `load_qrels` monkeypatch where it's currently injecting hand-built qrels via the stub — instead, the test setup seeds `judgments` rows so the real loader returns them. (Tests that explicitly need a custom qrel set can still monkeypatch.) |

**Key interfaces**

```python
# backend/app/eval/qrels_loader.py (new body)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.db.models import Judgment
from backend.app.eval.scoring import Qrels

class JudgmentsTableMissing(RuntimeError):
    """Retained for compat with infra_optuna_eval's integration test stubs.
    No longer raised by load_qrels() in normal operation."""

async def load_qrels(db: AsyncSession, judgment_list_id: str) -> Qrels:
    """SELECT query_id, doc_id, rating FROM judgments
    WHERE judgment_list_id = :id; GROUP BY query_id into {qid: {doc_id: rating}}.

    Empty result for an unknown judgment_list_id returns an empty dict — the
    caller (run_trial) handles "no qrels → score=0 over no queries" gracefully."""
    stmt = select(Judgment.query_id, Judgment.doc_id, Judgment.rating).where(
        Judgment.judgment_list_id == judgment_list_id
    )
    rows = (await db.execute(stmt)).all()
    qrels: Qrels = {}
    for query_id, doc_id, rating in rows:
        qrels.setdefault(str(query_id), {})[str(doc_id)] = int(rating)
    return qrels
```

**Tasks**

1. Rewrite `backend/app/eval/qrels_loader.py` with the real body above.
2. Audit existing tests for `load_qrels` monkeypatches; either keep them (they still work — monkeypatching the loader still bypasses the SELECT) or replace with `judgments` seeding where it's clearer.
3. Add a focused integration test `backend/tests/integration/test_qrels_loader.py` (NEW file): seed a `judgment_lists` + `queries` + `judgments` triplet, call `load_qrels()`, assert the shape.
4. Verify `infra_optuna_eval`'s existing tests still pass — the loader signature is unchanged so monkeypatched tests still work.

**Definition of Done (DoD)**

- [ ] `backend/app/eval/qrels_loader.py` rewrites the body with the SELECT; module docstring updated.
- [ ] `JudgmentsTableMissing` class is retained (no breaking import for downstream tests) but the real loader never raises it.
- [ ] `backend/tests/integration/test_qrels_loader.py` ships and passes.
- [ ] Existing `infra_optuna_eval` integration tests (`test_run_trial*.py`) all pass with no regressions.
- [ ] `state.md` "Known debt" line about the qrels_loader stub gets removed in the finalization step.

---

### Story 1.7 — Redis-backed daily budget gate (pre-call check + post-call record)

**Outcome:** `backend/app/llm/budget_gate.py` exposes two functions: `peek_daily_total(redis)` (read-only) and `record_cost(redis, cost_usd)` (post-call increment). The worker calls `peek_daily_total + comparison` **before** each LLM call (per spec FR-2 "MUST check the daily OpenAI budget before each LLM call"; addresses GPT-5.5 cycle 1 F8) and `record_cost` **after** to reconcile actual cost.

**New files**

| File | Purpose |
|---|---|
| `backend/app/llm/budget_gate.py` | `BudgetExceededError`, `daily_key(now: datetime) -> str` (returns `openai:budget:YYYY-MM-DD`), `peek_daily_total(redis, now=None) -> float` (no mutation), `record_cost(redis, cost_usd, now=None) -> float` (INCRBYFLOAT + EXPIRE). Per-day rolling: key TTL is 26 hours so a misfired daily rollover doesn't lose the counter. |
| `backend/tests/unit/llm/test_budget_gate.py` | Mock-Redis tests: peek returns 0 when no key; peek returns existing total; record increments; record + peek round-trip; day rollover (key changes) returns 0 on peek; budget=0 in caller logic disables the gate. |

**Modified files**

None.

**Key interfaces**

```python
# backend/app/llm/budget_gate.py
from datetime import UTC, datetime
from redis.asyncio import Redis

class BudgetExceededError(RuntimeError):
    """Raised by the worker (NOT by this module) when the pre-call peek plus
    a worst-case per-call cost estimate would exceed the daily budget. The
    worker translates this to the ``OPENAI_BUDGET_EXCEEDED`` reason on the
    judgment_lists row."""

def daily_key(now: datetime) -> str:
    return f"openai:budget:{now.strftime('%Y-%m-%d')}"

async def peek_daily_total(redis: Redis, *, now: datetime | None = None) -> float:
    """Return the current rolling-day spend (0.0 if the key is missing).
    Read-only — does NOT mutate the counter."""
    now = now or datetime.now(UTC)
    raw = await redis.get(daily_key(now))
    return float(raw) if raw is not None else 0.0

async def record_cost(redis: Redis, cost_usd: float, *, now: datetime | None = None) -> float:
    """INCRBYFLOAT the daily counter by ``cost_usd``, refresh the 26h TTL,
    and return the new total. Caller is responsible for the pre-call check."""
    now = now or datetime.now(UTC)
    key = daily_key(now)
    total = await redis.incrbyfloat(key, cost_usd)
    await redis.expire(key, 26 * 60 * 60)
    return float(total)
```

The pre-call check pattern (used in Story 2.1 worker AND Story 3.1 endpoint):

```python
# At every guarded call site:
current = await peek_daily_total(redis)
estimated_max = 0.05   # ~$0.05 worst-case per judgment call at gpt-4o (validate against cost_model)
if settings.openai_daily_budget_usd > 0 and current + estimated_max > settings.openai_daily_budget_usd:
    raise BudgetExceededError(f"current ${current:.2f} + estimate ${estimated_max:.2f} > budget ${settings.openai_daily_budget_usd:.2f}")
# ... make the call ...
new_total = await record_cost(redis, actual_cost_usd)
```

**Tasks**

1. Implement `budget_gate.py` per the interfaces above. `BudgetExceededError` is raised by the **caller** (worker or endpoint), not by this module — the module is a pure data layer.
2. Add `_estimated_max_call_cost(model: str) -> float` to `backend/app/llm/cost_model.py` (Story 1.4): returns a conservative per-call ceiling derived from `_MODEL_USD_PER_1K_INPUT[model] * (input_token_ceiling/1000) + _MODEL_USD_PER_1K_OUTPUT[model] * (output_token_ceiling/1000)`, with ceilings of ~10K input + ~2K output (covers a 50-doc batch). Used by both the pre-call check and the endpoint preflight.
3. Unit tests in `backend/tests/unit/llm/test_budget_gate.py` use a fake redis (`unittest.mock.AsyncMock` driving GET/INCRBYFLOAT return values).
4. Tests cover: peek empty → 0.0; peek populated → float; record + peek round-trip; rollover (different day → different key → 0.0).

**Definition of Done (DoD)**

- [ ] `backend/app/llm/budget_gate.py` exists with `BudgetExceededError`, `daily_key`, `peek_daily_total`, `record_cost`.
- [ ] `backend/app/llm/cost_model.py` gains `_estimated_max_call_cost(model)`.
- [ ] Unit tests in `backend/tests/unit/llm/test_budget_gate.py` cover all cases above.
- [ ] No dependency on a real Redis instance (mocked in unit tests).

---

## Epic 2 — Worker job (FR-2 + AC-1 + AC-4 + AC-6)

### Story 2.1 — `generate_judgments_llm` Arq job

**Outcome:** `backend/workers/judgments.py` implements the worker job. Registered in `WorkerSettings.functions`. Drives one LLM call per query, per-query failure isolation, budget enforcement, terminal status update.

**New files**

| File | Purpose |
|---|---|
| `backend/workers/judgments.py` | `generate_judgments_llm(ctx, judgment_list_id)` Arq job + helpers `_build_doc_inputs`, `_translate_search_hits_to_doc_inputs`. Imports the openai_judge, prompt_loader, budget_gate from Epic 1. |

**Modified files**

| File | Change |
|---|---|
| `backend/workers/all.py` | Import `generate_judgments_llm`; add to `WorkerSettings.functions` list with `func(generate_judgments_llm, timeout=900)` (15 min — 50 queries × ~5–6s per query plus retry headroom, vs. Arq's 5-min default which sits right at the boundary). **Also extend `on_startup`** with a resume sweep for `judgment_lists` rows stuck in `generating` status: `generating_ids = await repo.list_generating_judgment_list_ids(db); for jid in generating_ids: await arq_pool.enqueue_job("generate_judgments_llm", jid)`. This mirrors the existing studies resume pattern (lines 87–105 of `all.py`) and is required to make `POST /api/v1/judgments/generate` enqueue-failures non-fatal (per spec FR-3 + addresses GPT-5.5 cycle 1 F14). The worker job itself is idempotent: if it's already `complete`/`failed` the first instruction is "log and return" per Story 2.1 contract step 1. |
| `backend/app/llm/__init__.py` | Surface `openai_judge`, `budget_gate`, `prompt_loader` modules. |

**Key interfaces**

```python
# backend/workers/judgments.py
from typing import Any
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

async def generate_judgments_llm(ctx: dict[str, Any], judgment_list_id: str) -> None:
    """Run the LLM-as-judge pipeline for a single judgment_lists row.

    Contract (FR-2):
      1. Load judgment_lists row → cluster_id, target, current_template_id,
         query_set_id, rubric. If not found, log and return (already-deleted).
         If status != 'generating', log and return (idempotent — already-handled).
      2. For each query in the query_set:
         a. **PRE-LLM resume-skip check (per GPT-5.5 cycle 2 F5)**: count
            judgments already persisted for `(judgment_list_id, query_id)`.
            If `count >= top_k` (=50), skip the LLM call entirely — the
            query was completed by a previous worker pass and resuming would
            re-spend OpenAI dollars. Log "query already complete, skipping"
            at INFO with the count.
         b. **PRE-CALL budget check (per spec FR-2 "MUST check the daily OpenAI
            budget before each LLM call"; addresses GPT-5.5 cycle 1 F8)**:
            current = peek_daily_total(redis)
            estimated_max = _estimated_max_call_cost(model)
            if budget_usd > 0 and current + estimated_max > budget_usd:
                raise BudgetExceededError(...)
         c. render template (using `_compute_default_params(template)` per
            spec FR-2 "default params"; addresses GPT-5.5 cycle 2 F2 —
            uses midpoint for int/float ranges + first option for categorical,
            falls back to `{}` for templates with no declared_params);
            adapter.search_batch(target, [native_query], top_k=50)
         d. render prompt via prompt_loader.render_user_prompt; build
            `expected_doc_ids = {hit.doc_id for hit in hits}`
         e. rate_query_batch(..., expected_doc_ids=expected_doc_ids) → JudgeCallResult
         f. POST-CALL: record_cost(redis, result.cost_usd) — reconciles
            actual vs. estimate (the estimate-then-record pattern means we
            never start a call when the projected total exceeds the budget)
         g. bulk_create_judgments(rows from the result; source='llm',
            rater_ref=f'openai:{result.model}')
         h. log at INFO: judgment_list_id, query_id, tokens, cost, duration_ms
         i. on per-query exception other than BudgetExceededError or
            UnknownModelPricingError: log WARN and continue (per-query
            failure isolation, spec §11). UnknownModelPricingError → mark
            list `failed_reason='UNKNOWN_MODEL_PRICING'` and abort the loop.
      3. On BudgetExceededError: stop loop; update_judgment_list_status(
         status='failed', failed_reason='OPENAI_BUDGET_EXCEEDED').
      4. On unhandled exception: update_judgment_list_status(
         status='failed', failed_reason=str(exc)).
      5. On normal completion: update_judgment_list_status(status='complete').

    Critically: the worker is self-contained on judgment_list_id — the
    POST /generate endpoint persists cluster_id / target / current_template_id /
    query_set_id / rubric on the row before enqueueing (matches Phase 2's
    durable-handoff pattern).
    """
```

**Tasks**

1. Implement `generate_judgments_llm` per the contract above.
2. Build the `AsyncOpenAI` client lazily inside the job (not at boot — operator might enable OPENAI_API_KEY mid-deploy). Read settings via `get_settings()`.
3. Build the engine adapter via the existing `services.cluster.build_adapter(cluster)` (mirror what `trials.py` does).
4. Use the existing `adapter.render(template, default_params, query_text)` (verified at `backend/app/adapters/protocol.py:143` + `backend/workers/trials.py:385`) + `adapter.search_batch(target, [native_query], top_k=50)` pattern. **`default_params` is computed by a new helper `_compute_default_params(template) -> dict` defined inside `backend/workers/judgments.py`** (added per GPT-5.5 cycle 2 F2): for each `(name, schema)` in `template.declared_params`, derive a midpoint for numeric ranges, the first listed value for categoricals, and `False` for booleans. If `declared_params` is empty, return `{}`. Unit test in `tests/unit/workers/test_judgment_default_params.py` (NEW file) covers each branch.
5. For each search hit, fetch its `_source.body` field (or fall back to `_source` JSON-dumped) for the doc body sent to the LLM. **Decision: send a body extract trimmed to ~500 chars per doc** to keep tokens bounded; spec §13 limits cost to <$1/tutorial so token-budget per call must stay modest.
6. Budget gate (per GPT-5.5 cycle 1 F8 — pre-call check, post-call record):
   - Before each LLM call: `current = await peek_daily_total(redis)`; if `current + _estimated_max_call_cost(model) > settings.openai_daily_budget_usd` (and budget > 0), raise `BudgetExceededError` immediately. This is the spec FR-2 "before each call" contract.
   - After each successful LLM call: `await record_cost(redis, result.cost_usd)` to reflect actual spend.
   - Use a redis client built via `redis.asyncio.Redis.from_url(get_settings().redis_url)` at job start (or pull from `ctx["arq_pool"]` if exposed by infra_foundation; reuse if possible). Close at job exit.
7. Register the job in `WorkerSettings.functions` with `func(generate_judgments_llm, timeout=900)`. Re-import the symbol at top of `backend/workers/all.py`.
8. Surface a clean import boundary in `backend/app/llm/__init__.py`.
9. Integration test `backend/tests/integration/test_judgment_generate.py` (NEW file):
   - Uses a `pytest-recording` cassette of an OpenAI response for a 5-query × 5-doc scenario (AC-1 smaller scale).
   - Uses an `ElasticAdapter` cassette OR a hand-rolled `httpx.MockTransport` for the cluster.
   - Asserts: row transitions `generating → complete`; `judgment_count == 25`; `source_breakdown.llm == 25`; exactly 5 LLM calls made (AC-6 verification — counts request hits to the OpenAI cassette).
10. Integration test `backend/tests/integration/test_budget_guardrail.py` (NEW file): set `openai_daily_budget_usd=0.10`, run a 10-query generation, assert: status = `failed`, `failed_reason = 'OPENAI_BUDGET_EXCEEDED'`, partial judgments persist with `source='llm'` (AC-4).

**Definition of Done (DoD)**

- [ ] `backend/workers/judgments.py` ships; registered in `WorkerSettings.functions` with the 900s timeout.
- [ ] Integration test `test_judgment_generate.py` covers AC-1 (small-scale) + AC-6 (1 call per query) — green.
- [ ] Integration test `test_budget_guardrail.py` covers AC-4 (budget stops mid-generation, partial persist) — green.
- [ ] All LLM calls log structured `judgment_list_id`, `query_id`, `tokens_used`, `cost_usd`, `duration_ms` (spec §13).
- [ ] No model name hardcoded; reads `Settings.openai_model`.

---

## Epic 3 — API surface (FR-3 + FR-3b + FR-4 + FR-5 + FR-6)

### Story 3.1 — `POST /api/v1/judgments/generate` (FR-3 + AC-5 + AC-7)

**Outcome:** Creates a `judgment_lists` row with `status='generating'` + enqueues the worker; refuses on missing key or incapable provider.

**New files**

| File | Purpose |
|---|---|
| `backend/app/api/v1/judgments.py` | New router. Five endpoints across Stories 3.1–3.5: `POST /judgments/generate`, `POST /judgment-lists/import`, `GET /judgment-lists`, `GET /judgment-lists/{id}`, `GET /judgment-lists/{id}/judgments`, `PATCH /judgment-lists/{id}/judgments/{judgment_id}`, `POST /judgment-lists/{id}/calibration`. Mirrors `studies.py` structure. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/main.py` | Add `from backend.app.api.v1 import judgments as judgments_router` and `app.include_router(judgments_router.router, prefix="/api/v1")` after the studies router. |
| `backend/app/api/v1/schemas.py` | Add `JudgmentListStatusWire`, `JudgmentSourceWire`, `JudgmentSourceFilterWire`, `RatingWire`, `CreateJudgmentListGenerateRequest`, `GenerateJudgmentsResponse`, `JudgmentListSummary`, `JudgmentListDetail`, `JudgmentListListResponse`, `JudgmentRow`, `JudgmentListJudgmentsResponse`, `OverrideJudgmentRequest`, `CalibrationSamplesRequest`, `CalibrationSample`, `CalibrationResponse`, `ImportJudgmentListRequest`, `ImportJudgmentItem`. With source-of-truth comments per CLAUDE.md "Enumerated Value Contract Discipline". |

**Endpoints**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `POST` | `/api/v1/judgments/generate` | `CreateJudgmentListGenerateRequest` | `202` `GenerateJudgmentsResponse` | `OPENAI_NOT_CONFIGURED` (503, retryable=false), `OPENAI_BUDGET_EXCEEDED` (503, retryable=true — preflight peek matches spec §8.1; addresses GPT-5.5 F2), `LLM_PROVIDER_INCAPABLE` (503, retryable=false per spec §8.5 — applies to both cache-miss and `structured_output='fail'` per spec FR-3 strict reading; GPT-5.5 cycle 1 F7 + cycle 2 F3), `UNKNOWN_MODEL_PRICING` (503, retryable=false — Settings.openai_model not in cost_model._MODEL_USD_PER_1K_INPUT; required to keep the budget gate honest per GPT-5.5 cycle 2 F4), `QUERY_SET_NOT_FOUND` (404), `CLUSTER_NOT_FOUND` (404), `TEMPLATE_NOT_FOUND` (404), `JUDGMENT_LIST_NAME_TAKEN` (409), `VALIDATION_ERROR` (422 — Pydantic; also returned for query sets >10K queries per spec §10 threat 3, addresses GPT-5.5 F3) |

**Pydantic schemas**

```python
# backend/app/api/v1/schemas.py (additions)

# Values must match backend/app/db/models/judgment_list.py CHECK constraint.
JudgmentListStatusWire = Literal["generating", "complete", "failed"]

# Values must match backend/app/db/models/judgment.py CHECK constraint
# (judgments_source_check). `click` is reserved for v1.5+ click-derived
# judgments; this Literal is what JudgmentRow exposes for read paths.
JudgmentSourceWire = Literal["llm", "human", "click"]

# Subset of JudgmentSourceWire used as the ?source= filter on GET
# /judgment-lists/{id}/judgments. Spec §8.4 enumerates only `llm` and
# `human` for this filter — `click` is rejected at the API boundary
# (addresses GPT-5.5 cycle 1 F1).
JudgmentSourceFilterWire = Literal["llm", "human"]

# Values must match backend/app/db/models/judgment.py CHECK constraint
# (judgments_rating_check).
RatingWire = Literal[0, 1, 2, 3]

class CreateJudgmentListGenerateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=2000)
    query_set_id: str = Field(min_length=1, max_length=36)
    cluster_id: str = Field(min_length=1, max_length=36)
    target: str = Field(min_length=1, max_length=256)
    current_template_id: str = Field(min_length=1, max_length=36)
    rubric: str = Field(min_length=1)

class GenerateJudgmentsResponse(BaseModel):
    """Response of POST /api/v1/judgments/generate. Added per GPT-5.5
    cycle 1 F5 — the endpoint must register a typed response_model so
    OpenAPI introspection + contract tests can verify the wire shape."""
    judgment_list_id: str
    status: Literal["generating"]

class JudgmentListSummary(BaseModel):
    id: str
    name: str
    description: str | None
    query_set_id: str
    cluster_id: str
    status: JudgmentListStatusWire
    created_at: datetime

class _SourceBreakdown(BaseModel):
    """Per spec FR-6 the response shape names only `llm` and `human`
    (addresses GPT-5.5 cycle 1 F6). Any `click` rows (none in MVP1) are
    **deterministically folded into `human`** by `source_breakdown_for_list`
    so `llm + human == judgment_count` is a stable invariant
    (addresses GPT-5.5 cycle 2 F6 contract consistency)."""
    llm: int
    human: int

class JudgmentListDetail(BaseModel):
    id: str
    name: str
    description: str | None
    query_set_id: str
    cluster_id: str
    target: str
    current_template_id: str | None
    rubric: str
    status: JudgmentListStatusWire
    failed_reason: str | None
    judgment_count: int
    source_breakdown: _SourceBreakdown
    calibration: dict[str, Any] | None
    created_at: datetime

class JudgmentListListResponse(BaseModel):
    data: list[JudgmentListSummary]
    next_cursor: str | None
    has_more: bool
```

**Tasks**

1. Add the schemas above to `backend/app/api/v1/schemas.py` with source-of-truth comments.
2. In `judgments.py`, build the `POST /judgments/generate` handler with this preflight order (matches spec FR-3 + applies GPT-5.5 cycle 1 F2 + F3 + F7):
   - **Preflight A (config)**: Read `Settings.openai_api_key`; if `None`, raise `_err(503, "OPENAI_NOT_CONFIGURED", ..., retryable=False)`.
   - **Preflight B (capability, strict per spec FR-3)**: Read the capability cache via `read_capability_result(redis, base_url)`; if **the result is None (cache miss) OR `structured_output != "ok"`**, raise `_err(503, "LLM_PROVIDER_INCAPABLE", ..., retryable=False)` — cache miss is treated as "not OK" per spec FR-3 strict interpretation (addresses GPT-5.5 cycle 1 F7; deviates from `probe_openai_state`'s fail-open path which is `/healthz`-specific). `retryable=False` matches spec §8.5 literal (addresses GPT-5.5 cycle 2 F3 retryability consistency); the operator-facing recovery is "wait for the startup probe to finish, then retry". The error message names the cause (cache-miss vs. cap-fail) so operators can distinguish.
   - **Preflight B.1 (model pricing, addresses GPT-5.5 cycle 2 F4)**: If `Settings.openai_model not in cost_model._MODEL_USD_PER_1K_INPUT`, raise `_err(503, "UNKNOWN_MODEL_PRICING", f"OPENAI_MODEL={settings.openai_model!r} has no entry in cost_model; cannot enforce daily budget gate", retryable=False)`. Without this, an unrecognized model returns `0.0` from `compute_call_cost` and the budget gate is defeated (per F4 evidence). New error code captured as a spec drift (see §11.8).
   - **Preflight C (budget peek)**: `current = await peek_daily_total(redis)`; if `settings.openai_daily_budget_usd > 0 and current >= settings.openai_daily_budget_usd`, raise `_err(503, "OPENAI_BUDGET_EXCEEDED", ..., retryable=True)` (addresses GPT-5.5 F2; spec §8.1 lists this code for this endpoint).
   - **Preflight D (FK resolution)**: Resolve `cluster_id` / `template_id` / `query_set_id`; each missing → its own 404 code (mirror studies.py).
   - **Preflight E (oversized query set, per spec §10 threat 3)**: `count = await repo.count_queries_in_set(db, query_set_id)`; if `count > 10_000`, raise `_err(422, "VALIDATION_ERROR", "query set exceeds 10K query limit", retryable=False)` (addresses GPT-5.5 F3).
   - **INSERT**: Catch `IntegrityError` on the name UNIQUE → 409 `JUDGMENT_LIST_NAME_TAKEN`. Otherwise INSERT `judgment_lists` row with `status='generating'`; commit.
   - **Enqueue**: `await request.app.state.arq_pool.enqueue_job("generate_judgments_llm", judgment_list_id)`. Two failure modes (addresses GPT-5.5 cycle 2 F1 sharpening of cycle 1 F14):
     - If `arq_pool is None` (TestClient / lifespan-less env): log WARN, leave the row `generating`, return 202. The `WorkerSettings.on_startup` resume sweep dispatches it when the worker boots. This is the project pattern shared with `studies.py:_enqueue_start_study`.
     - If `arq_pool` exists but `enqueue_job` raises (Redis transient during API call): the row is durable in Postgres BUT no worker-boot event will follow. The handler still returns 202 (preserving studies-symmetric semantics) and the runbook in Story 4.2 ships a `python -m backend.scripts.judgments_resume` CLI that re-enqueues every `status='generating'` row. A follow-up `chore_judgments_periodic_resume_sweep` idea file (captured during finalization) tracks adding an in-worker periodic sweep when MVP1 ships cron infrastructure.
     - This is the trade-off the project has accepted for the studies surface; the judgments surface inherits it explicitly with a documented operator-recovery path.
   - Return 202 with `GenerateJudgmentsResponse(judgment_list_id=..., status="generating")` as the `response_model` on the decorator (addresses GPT-5.5 F5).
3. Add a helper `read_capability_result(redis: Redis, base_url: str) -> CapabilityResult | None` in `backend/app/llm/capability_check.py` (it's the reverse of the existing cache-write).

**Definition of Done (DoD)**

- [ ] `POST /api/v1/judgments/generate` shipped; returns 202 happy path with `GenerateJudgmentsResponse` registered as `response_model`.
- [ ] Integration test `backend/tests/integration/test_openai_not_configured.py` (NEW file) covers AC-5: missing key → 503 OPENAI_NOT_CONFIGURED, no row created.
- [ ] Integration test in `test_judgment_generate.py` covers happy-path POST → 202 → row exists with `status='generating'`.
- [ ] Integration test covers AC-7: POST with same `query_set_id` but different `rubric` and `name='tutorial-v2'` creates a NEW row; the original `tutorial-v1` is unchanged.
- [ ] Integration test covers each NOT_FOUND code (3 cases — cluster/template/query_set).
- [ ] Integration test covers `JUDGMENT_LIST_NAME_TAKEN` (409 on duplicate name).
- [ ] Integration test covers `LLM_PROVIDER_INCAPABLE` (two cases): (a) Redis seeded with `CapabilityResult` where `structured_output='fail'` → 503; (b) Redis cache miss → 503 (strict cache-miss path per spec FR-3 + GPT-5.5 F7).
- [ ] Integration test covers `OPENAI_BUDGET_EXCEEDED` preflight: pre-set the Redis daily counter `openai:budget:YYYY-MM-DD` above `Settings.openai_daily_budget_usd`, POST → 503 (addresses GPT-5.5 F2).
- [ ] Integration test covers oversized query set: pre-seed a query_set with >10K queries (or monkeypatch `count_queries_in_set` to return 10_001), POST → 422 VALIDATION_ERROR with "10K" in the message (addresses GPT-5.5 F3).
- [ ] Integration test simulates Arq enqueue failure (pool is None / `enqueue_job` raises): POST still returns 202; the row lands as `generating`; a follow-up call to the on_startup sweep helper picks it up (addresses GPT-5.5 F14).

---

### Story 3.2 — `POST /api/v1/judgment-lists/import` (FR-3b, tutorial path)

**Outcome:** Import endpoint accepts a payload of pre-baked `(query_id, doc_id, rating, notes?)` tuples and creates a `judgment_lists` row with `status='complete'` + bulk-inserts judgments.

**New files**

None (handler lives in `backend/app/api/v1/judgments.py` from Story 3.1).

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/schemas.py` | Add `ImportJudgmentItem`, `ImportJudgmentListRequest`, response model. |

**Endpoints**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `POST` | `/api/v1/judgment-lists/import` | `ImportJudgmentListRequest` | `201` `JudgmentListDetail` | `QUERY_SET_NOT_FOUND` (404), `CLUSTER_NOT_FOUND` (404), `QUERY_NOT_IN_SET` (400 — spec §FR-3b validation), `JUDGMENT_LIST_NAME_TAKEN` (409), `VALIDATION_ERROR` (422) |

**Pydantic schemas**

```python
class ImportJudgmentItem(BaseModel):
    query_id: str = Field(min_length=1, max_length=36)
    doc_id: str = Field(min_length=1, max_length=512)
    rating: RatingWire
    notes: str | None = None

class ImportJudgmentListRequest(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=2000)
    query_set_id: str = Field(min_length=1, max_length=36)
    cluster_id: str = Field(min_length=1, max_length=36)
    target: str = Field(min_length=1, max_length=256)
    rubric: str = Field(min_length=1)
    judgments: list[ImportJudgmentItem] = Field(min_length=1, max_length=100_000)
```

**Tasks**

1. Add `ImportJudgmentItem` / `ImportJudgmentListRequest` to schemas.
2. Implement the handler in `judgments.py`:
   - Resolve `query_set_id` / `cluster_id`; each missing → 404.
   - Fetch all `queries.id` in the set into a frozenset; for each item, ensure `item.query_id ∈ set`; if not, raise 400 `QUERY_NOT_IN_SET`.
   - Create `judgment_lists` row with `status='complete'`, `current_template_id=NULL`, then bulk-insert judgments with `source='human'`, `rater_ref='import'`.
   - On UNIQUE name collision → 409 `JUDGMENT_LIST_NAME_TAKEN`.
   - Return 201 with `JudgmentListDetail` (re-fetch + populate counts).
3. Integration test `backend/tests/integration/test_judgment_import.py` (NEW file): happy-path import; QUERY_NOT_IN_SET case; QUERY_SET_NOT_FOUND case.

**Definition of Done (DoD)**

- [ ] `POST /api/v1/judgment-lists/import` shipped; happy-path returns 201 with the created list.
- [ ] Returns `QUERY_NOT_IN_SET` (400) when any item references a query outside the supplied set.
- [ ] Imported rows have `source='human'`, `rater_ref='import'`.
- [ ] Integration test covers happy-path + each error code.

---

### Story 3.3 — List + detail + paginated-judgments endpoints (FR-6)

**Outcome:** Three GETs ship: `/judgment-lists`, `/judgment-lists/{id}`, `/judgment-lists/{id}/judgments`. Cursor pagination + `X-Total-Count` header on the list views (per api-conventions.md).

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/judgments.py` | Add the three GET handlers. |
| `backend/app/api/v1/schemas.py` | Add `JudgmentRow`, `JudgmentListJudgmentsResponse`. |

**Endpoints**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `GET` | `/api/v1/judgment-lists` | — | `200` `JudgmentListListResponse` + `X-Total-Count` header | — |
| `GET` | `/api/v1/judgment-lists/{id}` | — | `200` `JudgmentListDetail` (with `judgment_count` + `source_breakdown` + `calibration`) | `JUDGMENT_LIST_NOT_FOUND` (404) |
| `GET` | `/api/v1/judgment-lists/{id}/judgments?source=&cursor=&limit=` | — | `200` `JudgmentListJudgmentsResponse` + `X-Total-Count` header | `JUDGMENT_LIST_NOT_FOUND` (404), `VALIDATION_ERROR` (422 — bad `source`) |

**Pydantic schemas**

```python
class JudgmentRow(BaseModel):
    id: str
    judgment_list_id: str
    query_id: str
    doc_id: str
    rating: RatingWire
    source: JudgmentSourceWire
    rater_ref: str | None
    confidence: float | None
    notes: str | None
    created_at: datetime

class JudgmentListJudgmentsResponse(BaseModel):
    data: list[JudgmentRow]
    next_cursor: str | None
    has_more: bool
```

**Tasks**

1. `GET /judgment-lists`: paginate via `repo.list_judgment_lists` (Story 1.2 added it). Encode/decode cursors using the existing `_encode_cursor` / `_decode_cursor` shape from `studies.py` — copy the helpers (or hoist to `backend/app/api/v1/_cursor.py` per the lean-refactor §5.2 plan).
2. `GET /judgment-lists/{id}`: 404 if missing; build `JudgmentListDetail` from `JudgmentList` row + `count_judgments_for_list` + `source_breakdown_for_list`.
3. `GET /judgment-lists/{id}/judgments?source=`: cursor + limit + optional `source` filter. Validate `source ∈ {llm, human}` via the `JudgmentSourceFilterWire` `Literal` (Pydantic returns 422 with `VALIDATION_ERROR` for bad values — including `source=click`, which is rejected at the API boundary per spec §8.4 and addresses GPT-5.5 cycle 1 F1). Matches the existing `?status=StudyStatusWire` pattern in studies.py.
4. Integration test `backend/tests/integration/test_judgment_list_endpoints.py` (NEW file): list pagination + X-Total-Count; detail with counts; paginated judgments with source filter; bad source → 422.

**Definition of Done (DoD)**

- [ ] Three GET endpoints shipped; `X-Total-Count` header emitted on both list endpoints.
- [ ] `source_breakdown` correctly reflects counts (verify with a list containing mixed llm+human judgments via Story 3.4's PATCH).
- [ ] Cursor encoding matches `backend/app/api/v1/studies.py` shape (consistency).
- [ ] Integration tests pass.

---

### Story 3.4 — `PATCH /…/judgments/{judgment_id}` override (FR-4 + AC-2)

**Outcome:** Operator can override an LLM rating; the UNIQUE constraint UPSERTs in place (replace).

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/judgments.py` | Add `PATCH` handler. |
| `backend/app/api/v1/schemas.py` | Add `OverrideJudgmentRequest`, `OverrideJudgmentResponse`. |

**Endpoints**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `PATCH` | `/api/v1/judgment-lists/{id}/judgments/{judgment_id}` | `OverrideJudgmentRequest` | `200` `JudgmentRow` | `JUDGMENT_LIST_NOT_FOUND` (404), `JUDGMENT_NOT_FOUND` (404), `INVALID_RATING` (400 — rating ∉ 0..3), `LIST_NOT_READY` (409 — list still `generating`), `VALIDATION_ERROR` (422) |

**Pydantic schemas**

```python
class OverrideJudgmentRequest(BaseModel):
    """`rating` is INTENTIONALLY unbounded at the Pydantic layer — out-of-range
    must surface as the spec's 400 `INVALID_RATING` (not 422 VALIDATION_ERROR).
    The handler validates `rating in (0,1,2,3)` and raises `_err(400, ...)`.
    Addresses GPT-5.5 cycle 1 F4 (self-contradiction in the original draft)."""
    rating: int
    notes: str | None = Field(default=None, max_length=2000)
```

**Tasks**

1. Handler logic:
   - Resolve `id` → if missing, 404 `JUDGMENT_LIST_NOT_FOUND`.
   - If `judgment_list.status == 'generating'`, raise 409 `LIST_NOT_READY` per spec §11 edge cases.
   - Resolve `judgment_id` → if missing or its `judgment_list_id` doesn't match path `id`, 404 `JUDGMENT_NOT_FOUND`.
   - Call `repo.upsert_judgment_human_override(db, judgment_list_id=id, query_id=judgment.query_id, doc_id=judgment.doc_id, rating=body.rating, rater_ref='operator', notes=body.notes)`.
   - Commit and return the updated `JudgmentRow`.
2. **Note: out-of-range rating handling.** Pydantic `Field(ge=0, le=3)` returns 422 `VALIDATION_ERROR` by default — but spec §8.5 specifies `INVALID_RATING` (400). To match the spec, **DO NOT** put `ge=0, le=3` on the Pydantic field; instead validate manually in the handler and raise `_err(400, "INVALID_RATING", ...)`. (Mirrors the studies.py pattern of using `str` instead of `Literal` so domain-specific 400 codes surface.) Capture this design decision in the story.
3. Integration test `backend/tests/integration/test_judgment_override.py` (NEW file): AC-2 happy path; INVALID_RATING (rating=5); LIST_NOT_READY (override while generating); JUDGMENT_NOT_FOUND.

**Definition of Done (DoD)**

- [ ] PATCH endpoint shipped; UPSERT semantics verified: source flips from `llm` to `human`, `source_breakdown.llm--`, `source_breakdown.human++`.
- [ ] `INVALID_RATING` (400) returned for rating ∉ 0..3 (NOT 422 — spec §8.5 contract).
- [ ] `LIST_NOT_READY` (409) returned when list still generating.
- [ ] Integration tests cover AC-2 + each error.

---

### Story 3.5 — `POST /…/calibration` endpoint (FR-5 + AC-3)

**Outcome:** Compute Cohen's + weighted kappa + per-class agreement from human samples vs. LLM ratings; persist to `judgment_lists.calibration`.

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/judgments.py` | Add `POST` handler. |
| `backend/app/api/v1/schemas.py` | Add `CalibrationSamplesRequest`, `CalibrationSample`, `CalibrationResponse`. |

**Endpoints**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `POST` | `/api/v1/judgment-lists/{id}/calibration` | `CalibrationSamplesRequest` | `200` `CalibrationResponse` | `JUDGMENT_LIST_NOT_FOUND` (404), `INSUFFICIENT_SAMPLES` (400 — need ≥10), `VALIDATION_ERROR` (422) |

**Pydantic schemas**

```python
class CalibrationSample(BaseModel):
    query_id: str = Field(min_length=1, max_length=36)
    doc_id: str = Field(min_length=1, max_length=512)
    rating: RatingWire

class CalibrationSamplesRequest(BaseModel):
    human_samples: list[CalibrationSample] = Field(min_length=1)

class CalibrationResponse(BaseModel):
    cohens_kappa: float | None
    weighted_kappa: float | None
    per_class: dict[str, float]
    n_samples: int
    warning: str | None
```

**Tasks**

1. Handler:
   - Resolve list ID → 404 if missing.
   - **Pre-check**: `len(human_samples) < 10` → 400 `INSUFFICIENT_SAMPLES`.
   - For each sample, look up the existing `judgment` by `(judgment_list_id, query_id, doc_id)` **AND `source='llm'`** (per spec FR-5 — calibration compares human samples to **LLM** ratings, not to other human overrides; addresses GPT-5.5 cycle 1 F12). Build the list of `(human, llm)` pairs; samples whose existing row has `source='human'` (overridden) or doesn't exist are dropped with a WARN log.
   - **Post-match recheck**: if `len(pairs) < 10` (samples were submitted but too few matched LLM rows after the source filter), → 400 `INSUFFICIENT_SAMPLES` with message `"insufficient LLM-rated samples to compute kappa: {len(pairs)} matched, 10 required"` (addresses GPT-5.5 cycle 1 F13).
   - Call `compute_calibration(pairs)` from Story 1.5.
   - `repo.update_judgment_list_calibration(db, id, calibration=result)`; commit.
   - Return the `CalibrationResponse`.
2. Integration test `backend/tests/integration/test_calibration_endpoint.py` (NEW file): AC-3 happy path with 30 samples (all match LLM rows); `INSUFFICIENT_SAMPLES` pre-check with <10 submitted samples; `INSUFFICIENT_SAMPLES` post-match with 10 submitted but only 5 matching LLM rows (the other 5 are `source='human'` overrides); no-variance warning case; documentation note that calibration should be run **before** any significant volume of overrides.

**Definition of Done (DoD)**

- [ ] POST endpoint shipped; persists `calibration` JSONB on the list.
- [ ] Returns `INSUFFICIENT_SAMPLES` (400) for <10 submitted samples (pre-check).
- [ ] Returns `INSUFFICIENT_SAMPLES` (400) when ≥10 samples submitted but fewer than 10 match `source='llm'` rows (post-match recheck; GPT-5.5 cycle 1 F13).
- [ ] Calibration pairs filtered by `source='llm'` only (GPT-5.5 cycle 1 F12); runbook in Story 4.2 documents the "run calibration before overrides" guidance.
- [ ] Returns `cohens_kappa: null` + `warning: 'no rating variance'` when all ratings are identical.
- [ ] Integration tests cover AC-3 + the error and edge cases.

---

## Epic 4 — Documentation + polish (spec §15)

### Story 4.1 — Security doc: `docs/04_security/llm-data-flow.md`

**Outcome:** A new doc explains what data leaves the cluster → OpenAI on each judgment generation: query text, top-K doc bodies (trimmed), rubric. ZDR enrollment guidance; retention policy.

**New files**

| File | Purpose |
|---|---|
| `docs/04_security/llm-data-flow.md` | Required by spec §15. Covers: data-flow diagram, what goes to OpenAI per call, what is logged locally, ZDR enrollment, retention. |

**DoD**

- [ ] File exists; covers all four bullets above; linked from `docs/04_security/README.md`.

---

### Story 4.2 — Runbook: `docs/03_runbooks/judgment-generation-debugging.md`

**Outcome:** Operator runbook for: replaying a cassette, computing kappa from CSV, bulk-overriding judgments.

**New files**

| File | Purpose |
|---|---|
| `docs/03_runbooks/judgment-generation-debugging.md` | Required by spec §15. |

**DoD**

- [ ] File exists; cross-referenced from CLAUDE.md "Key Runbooks" table.

---

### Story 4.3 — Status flips (US-13 / US-14 / US-15 → implemented)

**Outcome:** `docs/02_product/mvp1-user-stories.md` marks US-13 / US-14 / US-15 as implemented. The MVP1 dashboard regenerates correctly.

**Modified files**

| File | Change |
|---|---|
| `docs/02_product/mvp1-user-stories.md` | Mark US-13 / US-14 / US-15 status as Implemented. |
| `docs/00_overview/MVP1_DASHBOARD.md` | Will regenerate via `scripts/build_mvp1_dashboard.py`; not edited by hand. |

**DoD**

- [ ] User-story doc updated.
- [ ] Dashboard regeneration command runs cleanly (`python scripts/build_mvp1_dashboard.py`).

---

## UI Guidance

**No UI Guidance section** — this feature has **no frontend scope**. The review/override UI is owned by `feat_studies_ui` per spec §3 "Out of scope". The API endpoints in this feature support both UI (when `feat_studies_ui` ships) and chat-agent consumers (when `feat_chat_agent` ships) with no UI-side changes here.

**No Legacy behavior parity table** — no user-facing component >100 LOC is being deleted or migrated.

---

## 3) Testing workstream

### 3.1 Unit tests (`backend/tests/unit/`)

| File | Story | Scope |
|---|---|---|
| `workers/test_judgment_prompt_render.py` | 1.3 | Jinja template renders rubric / docs / query; sandbox prevents injection |
| `eval/test_calibration.py` | 1.5 | Cohen's kappa + weighted kappa + per-class against hand-computed baselines (spec §14) |
| `llm/test_openai_judge_unit.py` | 1.4 | rate_query_batch: happy / retry / exhausted / cost calc |
| `llm/test_budget_gate.py` | 1.7 | under / over / disabled / day rollover |

**DoD**

- [ ] All four unit test files exist and pass.
- [ ] Critical branches (retry exhausted, kappa-undefined, budget exceeded) deterministically covered.

### 3.2 Integration tests (`backend/tests/integration/`)

| File | Story | Scope |
|---|---|---|
| `test_judgment_repo.py` | 1.2 | Repo unit-of-work — UNIQUE, bulk-create idempotency, override UPSERT |
| `test_qrels_loader.py` | 1.6 | Real loader SELECTs and groups by query_id |
| `test_judgment_generate.py` | 2.1 + 3.1 | Happy path AC-1 (smaller scale) + AC-6 (1 call per query) + AC-7 (re-generate creates new list); 4 NOT_FOUND codes; NAME_TAKEN |
| `test_budget_guardrail.py` | 2.1 | AC-4 — budget stops mid-generation, partial persist |
| `test_openai_not_configured.py` | 3.1 | AC-5 — missing key → 503 OPENAI_NOT_CONFIGURED |
| `test_llm_provider_incapable.py` | 3.1 | structured_output='fail' in cache → 503 LLM_PROVIDER_INCAPABLE |
| `test_judgment_import.py` | 3.2 | Happy path + QUERY_NOT_IN_SET + QUERY_SET_NOT_FOUND |
| `test_judgment_list_endpoints.py` | 3.3 | List pagination + X-Total-Count; detail with breakdown; paginated judgments + source filter |
| `test_judgment_override.py` | 3.4 | AC-2 + INVALID_RATING + LIST_NOT_READY + JUDGMENT_NOT_FOUND |
| `test_calibration_endpoint.py` | 3.5 | AC-3 + INSUFFICIENT_SAMPLES + no-variance warning |

**DoD**

- [ ] All ten files exist and pass.
- [ ] All seven ACs (AC-1 through AC-7) have explicit assertions in at least one integration test.
- [ ] No test mocks internal code — only the OpenAI SDK + (where needed) the engine's HTTP layer.

### 3.3 Contract tests (`backend/tests/contract/`)

| File | Story | Scope |
|---|---|---|
| `test_judgments_api_contract.py` | All Epic 3 stories | OpenAPI shape parity for all 7 endpoints; assertion that each of the 11 error codes (plus `QUERY_NOT_IN_SET`, `LIST_NOT_READY`) round-trips through the error envelope |

The 11 error codes from spec §8.5 PLUS the two spec drifts called out below = **13 distinct codes** the contract test must cover:

`OPENAI_NOT_CONFIGURED`, `OPENAI_BUDGET_EXCEEDED`, `LLM_PROVIDER_INCAPABLE`, `JUDGMENT_LIST_NOT_FOUND`, `JUDGMENT_LIST_NAME_TAKEN`, `JUDGMENT_NOT_FOUND`, `INVALID_RATING`, `INSUFFICIENT_SAMPLES`, `QUERY_SET_NOT_FOUND`, `CLUSTER_NOT_FOUND`, `TEMPLATE_NOT_FOUND`, `QUERY_NOT_IN_SET` (spec §FR-3b drift; captured as idea file), `LIST_NOT_READY` (spec §11 drift; captured as idea file).

**DoD**

- [ ] Contract test asserts response envelope shape `{detail: {error_code, message, retryable}}` for every code above.
- [ ] OpenAPI schema introspection confirms all 7 endpoints register the right `response_model`.

### 3.4 E2E tests

N/A — no UI in this feature. Marked explicitly so the AI agent doesn't synthesize Playwright tasks.

### 3.5 Migration verification

- [ ] `alembic upgrade head` succeeds (`0001 → 0002 → 0003 → 0004`).
- [ ] `alembic downgrade -1 && alembic upgrade head` round-trips cleanly between `0003` and `0004`.
- [ ] The `_clean_phase2_tables` fixture in `backend/tests/integration/conftest.py` now wipes `judgments` before `judgment_lists` (FK CASCADE handles it implicitly, but explicit is safer).

### 3.6 CI gates

- [ ] `make test-unit`
- [ ] `make test-integration`
- [ ] `make test-contract`
- [ ] `make lint && make typecheck`
- [ ] `make fmt --check`

### 3.7 Existing test impact audit

No refactor or moved-file scope; this feature is purely additive. No existing-test impact audit table required.

---

## 4) Documentation update workstream

### 4.0 Core context files

**`state.md`** — update in the finalization step:
- [ ] Alembic head bumped to `0004_judgments`
- [ ] Recent changes: `feat_llm_judgments` merged
- [ ] Queued list: pop `feat_llm_judgments`, advance `feat_digest_proposal` to top
- [ ] Known debt: drop the `qrels_loader.py` stub line; add `chore_spec_llm_judgments_error_drift` (covered below) to the debt list

**`architecture.md`** — update if:
- [ ] `backend/app/llm/` gains new modules (yes — `openai_judge`, `cost_model`, `budget_gate`, `prompt_loader`). Update the "Where the code lives" section.
- [ ] `prompts/` directory now exists at repo root — add to the layout.

**`CLAUDE.md`** — update if:
- [ ] Activates the "Never call OpenAI directly when the LLM abstraction exists" rule's MVP1 fallback exception note — already in place.
- [ ] Feature status table: flip `feat_llm_judgments` to **Complete (PR #N)** with the implemented_features link.

### 4.1 Architecture docs

- [ ] `docs/01_architecture/llm-orchestration.md`: no edits expected if the implementation matches the documented pattern (Structured output, one call per query, model pinned). If the budget-gate Redis-counter approach diverges from the doc's "Postgres rolling-24h sum" language, **patch the doc to match the implementation** (Redis is a sounder fit for MVP1; Postgres would require an unnecessary table).

### 4.2 Product docs

- [ ] `docs/02_product/mvp1-user-stories.md`: US-13 / US-14 / US-15 → Implemented (Story 4.3).

### 4.3 Runbooks

- [ ] `docs/03_runbooks/judgment-generation-debugging.md` (Story 4.2).
- [ ] `docs/03_runbooks/README.md`: add link to the new runbook.

### 4.4 Security docs

- [ ] `docs/04_security/llm-data-flow.md` (Story 4.1).
- [ ] `docs/04_security/README.md`: link the new doc.

### 4.5 Quality docs

- [ ] `docs/05_quality/testing.md`: no changes — coverage gate stays at 80%.

**Documentation DoD**

- [ ] `state.md` + `architecture.md` + `CLAUDE.md` consistent with shipped behavior.
- [ ] `docs/04_security/llm-data-flow.md` + `docs/03_runbooks/judgment-generation-debugging.md` exist.
- [ ] US-13 / US-14 / US-15 flipped in mvp1-user-stories.md.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

- Hoist the cursor encode/decode helpers (`_encode_cursor` / `_decode_cursor`) that are currently duplicated across `backend/app/api/v1/{clusters,query_templates,query_sets,studies,judgments}.py` into a single `backend/app/api/v1/_cursor.py` module **iff** this feature would be the third or later consumer (it is — `judgments.py` makes five total). Otherwise defer.
- Eliminate the duplicate `_err()` helper across routers by hoisting to `backend/app/api/v1/_errors.py` (same trigger — 5+ uses).

### 5.2 Planned refactor tasks

- [ ] Hoist `_encode_cursor` / `_decode_cursor` → `backend/app/api/v1/_cursor.py`. Apply to all five routers. Run all contract tests to verify shape parity.
- [ ] Hoist `_err()` helper → `backend/app/api/v1/_errors.py`. Apply to all five routers.

### 5.3 Refactor guardrails

- [ ] Behavioral parity proven by existing contract tests (cluster cursor + studies cursor tests already exist; no new cursor encoding shape).
- [ ] Lint/typecheck remain green.
- [ ] No expansion of product scope.

If the hoist is judged distracting at execution time, **defer** it to a follow-up `chore_router_helpers_hoist` idea file rather than blocking this feature.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `feat_study_lifecycle` Phase 1 (`judgment_lists` table) | Story 1.1 | Merged 2026-05-10 (PR #18) | High — without it, no parent table for `judgments` FK |
| `infra_optuna_eval` (`qrels_loader.py` stub) | Story 1.6 | Merged 2026-05-10 (PR #23) | Low — we replace the stub |
| `infra_adapter_elastic` (engine adapter for `search_batch`) | Story 2.1 | Merged 2026-05-10 (PR #16) | High — worker can't fetch top-K docs without it |
| `infra_foundation` (Settings + capability check + Redis) | Stories 1.7, 3.1 | Merged 2026-05-09 (PR #4) | High — budget gate + capability gate both build on it |
| OpenAI API key + working endpoint | Story 2.1 integration tests | Cassette-recorded; no live calls in CI | Low — pytest-recording stores the cassette |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| OpenAI API returns malformed JSON despite `strict=True` schema | L | M | Story 1.4 catches `json.JSONDecodeError` and retries once; on final failure logs WARN and skips that query — the worker continues with the next query (per spec §11 per-query failure isolation) |
| pytest-recording cassette format breaks between OpenAI SDK versions | L | M | Pin `openai>=1.55,<2.0` in `pyproject.toml`; if upgrading, re-record cassettes |
| Redis daily counter races (two workers, same call, narrow window) | M | L | `INCRBYFLOAT` is atomic; over-budget by ≤ one call is acceptable per spec §13 cost-guardrail tolerance |
| `judgment_lists.cluster_id NOT NULL` but spec FR-3b says imports can omit cluster | L | M | The spec correctly requires `cluster_id` on import (spec §FR-3b lists it as required input). No conflict; the Phase 1 schema is correct. |
| Spec drift: `QUERY_NOT_IN_SET` + `LIST_NOT_READY` not in §8.5 catalog | Resolved | L | Capture as idea file `chore_spec_llm_judgments_error_drift` (covered in Risks-after-execution); contract test asserts both codes; spec gets patched in the follow-up |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| OpenAI rate-limit | `openai.RateLimitError` | exponential backoff, 3 attempts; on exhaustion, query is skipped with WARN | manual — operator retries after the rate window |
| Cluster goes unreachable mid-generation | Adapter raises `ClusterUnreachableError` | current query skipped; worker continues with next query | manual — operator re-runs generation after cluster recovery |
| Override before generation completes | PATCH while status='generating' | 409 `LIST_NOT_READY`; no row mutated | client retries when status='complete' |
| Budget exceeded mid-generation | `BudgetExceededError` raised inside the worker loop | partial judgments persist; list status flips to `failed` with `failed_reason='OPENAI_BUDGET_EXCEEDED'` | manual — operator raises `OPENAI_DAILY_BUDGET_USD` or waits for the daily rollover |
| Capability cache empty at request time | `read_capability_result()` returns None | endpoint **refuses** with 503 `LLM_PROVIDER_INCAPABLE` (`retryable: false` per spec §8.5; GPT-5.5 cycle 2 F3). The cache typically populates within seconds of API startup, so an operator-triggered retry succeeds shortly after | manual — operator waits for the startup probe to finish, then retries |
| Configured `OPENAI_MODEL` has no entry in cost_model | startup or preflight detects missing pricing | endpoint refuses with 503 `UNKNOWN_MODEL_PRICING` (`retryable: false`); worker raises before any LLM call so the budget gate cannot be defeated (GPT-5.5 cycle 2 F4) | manual — operator either pins a known model or updates `cost_model._MODEL_USD_PER_1K_INPUT/OUTPUT` |
| Arq enqueue fails after row INSERT | Redis pool unreachable / `enqueue_job` raises | row stays in `status='generating'`; the WorkerSettings.on_startup resume sweep (Story 2.1) re-enqueues every `generating` row when the worker boots | automatic — worker restart picks up orphaned rows |
| OpenAI returns malformed JSON | `RATING_RESPONSE_SCHEMA` parse fails after retry | query is skipped with WARN; worker continues | manual — operator inspects the cassette / logs |

---

## 7) Sequencing and parallelization

### Suggested sequence

1. **Epic 1** stories in order: 1.1 → 1.2 → 1.3 → 1.4 → 1.5 → 1.6 → 1.7. Story 1.1 must land before any later story (every story below it depends on the schema being live).
2. **Epic 2** Story 2.1 after Epic 1 completes.
3. **Epic 3** stories: 3.1 → 3.2 → 3.3 → 3.4 → 3.5. Stories 3.3–3.5 can ship in parallel **after** 3.1 if multiple operators work in parallel, but a single agent should proceed serially per CLAUDE.md Rule #9 (`/impl-execute` enforces ordering).
4. **Epic 4** stories (docs) last, after the implementation is locked.

### Parallelization opportunities

- Stories 1.3 (prompts), 1.4 (judge client), 1.5 (calibration), 1.7 (budget gate) are independent of each other — they all depend on 1.1 + 1.2 but not on each other. An agent that completes 1.1+1.2 can fan out across 1.3/1.4/1.5/1.7 if context permits.
- Stories 3.3 / 3.4 / 3.5 are independent surfaces; can ship sequentially without dependency.

---

## 8) Rollout and cutover plan

- **Rollout stages:** single-environment (local dev / CI only); no remote staging in MVP1.
- **Feature flag strategy:** none.
- **Migration/cutover steps:** `make migrate` after pulling the branch. No data backfill needed.
- **Reconciliation/repair strategy:** N/A — this feature is the source of truth for `judgments` rows.

---

## 9) Execution tracker (copy/paste section)

### Current sprint

- [x] Story 1.1 — `judgments` migration (FR-1) — `6b7d8bf`
- [x] Story 1.2 — Judgment ORM model + repo functions — `63708ab`
- [x] Story 1.3 — Prompt files + Jinja loader — `6090934`
- [x] Story 1.4 — OpenAI judge client — `a6b8c91`
- [x] Story 1.5 — Calibration helper — `e324373`
- [x] Story 1.6 — Replace qrels_loader stub — `eb02604`
- [x] Story 1.7 — Redis budget gate — `815cef5`
- [x] Story 2.1 — `generate_judgments_llm` Arq job — `3e68738`
- [x] Story 3.1 — `POST /api/v1/judgments/generate` — `be769ba`
- [x] Story 3.2 — `POST /api/v1/judgment-lists/import` — `be769ba`
- [x] Story 3.3 — List + detail + paginated-judgments endpoints — `be769ba`
- [x] Story 3.4 — `PATCH /…/judgments/{judgment_id}` override — `be769ba`
- [x] Story 3.5 — `POST /…/calibration` — `be769ba`
- [x] Story 4.1 — `docs/04_security/llm-data-flow.md` — `8113d17`
- [x] Story 4.2 — `docs/03_runbooks/judgment-generation-debugging.md` — `8113d17`
- [x] Story 4.3 — Flip US-13/14/15 to implemented — `8113d17`

### Blocked items

— (none at plan-creation time)

### Done this sprint

— (populated by impl-execute)

---

## 10) Story-by-Story Verification Gate

Before marking any story complete:

- [ ] Files created / modified match the story's `New files` / `Modified files` tables.
- [ ] Endpoint contract implemented exactly as documented (method / path / body / status / error code).
- [ ] Key interfaces implemented with compatible signatures.
- [ ] Required tests added/updated for every layer the story touches (unit / integration / contract).
- [ ] `make test-unit`, `make test-integration`, `make test-contract` pass for the story's scope.
- [ ] Migration round-trip evidence attached when schema changed (Story 1.1 only).
- [ ] Docs/checklists updated in the same PR when behavior/contract changed.
- [ ] `make lint && make typecheck && make fmt` clean.

---

## 11) Plan consistency review (performed at plan generation time)

### 11.1 Spec ↔ plan endpoint count

Spec §8.1 lists **6 endpoints** in the table but FR-3b describes a **7th** (the import endpoint) that's absent from §8.1. The plan ships **7 endpoints**:

1. `POST /api/v1/judgments/generate` (FR-3 + spec §8.1 row 1) — Story 3.1
2. `POST /api/v1/judgment-lists/import` (FR-3b — **not** in §8.1 table — spec drift to capture) — Story 3.2
3. `GET /api/v1/judgment-lists` (FR-6 + spec §8.1 row 2) — Story 3.3
4. `GET /api/v1/judgment-lists/{id}` (FR-6 + spec §8.1 row 3) — Story 3.3
5. `GET /api/v1/judgment-lists/{id}/judgments` (FR-6 + spec §8.1 row 4) — Story 3.3
6. `PATCH /api/v1/judgment-lists/{id}/judgments/{judgment_id}` (FR-4 + spec §8.1 row 5) — Story 3.4
7. `POST /api/v1/judgment-lists/{id}/calibration` (FR-5 + spec §8.1 row 6) — Story 3.5

**Finding (spec drift):** §8.1 endpoint table is missing the import endpoint described in §3 + FR-3b. Captured as a follow-up idea file (see §11.7).

### 11.2 Spec ↔ plan error code coverage

Spec §8.5 lists **11 error codes**. The plan covers all 11 plus 2 additional codes from spec body text that aren't in the §8.5 table:

| Code | Spec source | Plan coverage |
|---|---|---|
| OPENAI_NOT_CONFIGURED | §8.5 | Story 3.1 |
| OPENAI_BUDGET_EXCEEDED | §8.5 (as a worker reason, not endpoint code) | Story 2.1 (mark list `failed`) |
| LLM_PROVIDER_INCAPABLE | §8.5 + FR-3 | Story 3.1 |
| JUDGMENT_LIST_NOT_FOUND | §8.5 | Stories 3.3, 3.4, 3.5 |
| JUDGMENT_LIST_NAME_TAKEN | §8.5 | Stories 3.1, 3.2 |
| JUDGMENT_NOT_FOUND | §8.5 | Story 3.4 |
| INVALID_RATING | §8.5 | Story 3.4 |
| INSUFFICIENT_SAMPLES | §8.5 | Story 3.5 |
| QUERY_SET_NOT_FOUND | §8.5 | Stories 3.1, 3.2 |
| CLUSTER_NOT_FOUND | §8.5 | Stories 3.1, 3.2 |
| TEMPLATE_NOT_FOUND | §8.5 | Story 3.1 |
| **QUERY_NOT_IN_SET** | §FR-3b body text (not §8.5) | Story 3.2 — **spec drift** |
| **LIST_NOT_READY** | §11 edge/error flows (not §8.5) | Story 3.4 — **spec drift** |

**Finding:** §8.5 catalog is missing `QUERY_NOT_IN_SET` and `LIST_NOT_READY` though both appear in §FR-3b / §11. Captured as a follow-up idea file (see §11.7).

### 11.3 Spec ↔ plan FR coverage

Every FR has at least one story:

- FR-1 → Stories 1.1, 1.2
- FR-2 → Story 2.1
- FR-3 → Story 3.1
- FR-3b → Story 3.2
- FR-3c (starter rubric) → Story 1.3
- FR-4 → Story 3.4
- FR-5 → Stories 1.5, 3.5
- FR-6 → Story 3.3

### 11.4 Story internal consistency

For every story:
- [ ] Endpoint table fields match Pydantic schemas (names, types, optional vs required).
- [ ] DoD assertions reference the correct error codes and HTTP status.
- [ ] New files are not claimed by multiple stories. (One conflict reviewed: `backend/app/api/v1/judgments.py` is "new" in Story 3.1 and "modified" in Stories 3.2–3.5 — correctly handled.)
- [ ] Modified files actually exist (verified via the codebase exploration phase).

### 11.5 Test file count

| File | Story | Counted in §3? |
|---|---|---|
| `tests/unit/workers/test_judgment_prompt_render.py` | 1.3 | yes |
| `tests/unit/eval/test_calibration.py` | 1.5 | yes |
| `tests/unit/llm/test_openai_judge_unit.py` | 1.4 | yes |
| `tests/unit/llm/test_budget_gate.py` | 1.7 | yes |
| `tests/unit/llm/__init__.py` | 1.4 | (subpackage marker — not a test) |
| `tests/integration/test_judgment_repo.py` | 1.2 | yes |
| `tests/integration/test_qrels_loader.py` | 1.6 | yes |
| `tests/integration/test_judgment_generate.py` | 2.1, 3.1 | yes |
| `tests/integration/test_budget_guardrail.py` | 2.1 | yes |
| `tests/integration/test_openai_not_configured.py` | 3.1 | yes |
| `tests/integration/test_llm_provider_incapable.py` | 3.1 | yes |
| `tests/integration/test_judgment_import.py` | 3.2 | yes |
| `tests/integration/test_judgment_list_endpoints.py` | 3.3 | yes |
| `tests/integration/test_judgment_override.py` | 3.4 | yes |
| `tests/integration/test_calibration_endpoint.py` | 3.5 | yes |
| `tests/contract/test_judgments_api_contract.py` | Epic 3 (cross-cutting) | yes |

4 unit + 10 integration + 1 contract = **15 test files**.

### 11.6 Gate arithmetic

- Epic 1 gate: all 7 stories ship; `judgments` table live at Alembic head `0004`; all unit tests green.
- Epic 2 gate: worker job registered; AC-1 small-scale + AC-4 + AC-6 integration tests green.
- Epic 3 gate: all 7 endpoints live; all 13 error codes covered by contract test; AC-2 + AC-3 + AC-5 + AC-7 green.
- Epic 4 gate: docs merged; mvp1-user-stories.md flipped.

### 11.7 Open questions

Spec §19 has **one open question**: final rubric content. Per the spec, the starter rubric in §FR-3c is sufficient to unblock plan generation and worker implementation; the final content is a copy edit before merge. **Not blocking** this plan.

### 11.8 Spec drifts captured

Two spec drifts surfaced during plan review. Both get captured as idea files in the finalization step (Story 4.x + an `idea.md` filed during execution):

1. `chore_spec_llm_judgments_endpoint_drift` — §8.1 endpoint table missing the import endpoint (FR-3b).
2. `chore_spec_llm_judgments_error_drift` — §8.5 error catalog missing `QUERY_NOT_IN_SET` and `LIST_NOT_READY`.

Neither blocks implementation — the plan ships the missing pieces; the spec patch is mechanical.

### 11.9 Infrastructure path verification (cross-checked at plan generation)

- [x] Migration directory: `migrations/versions/` (verified via `ls`).
- [x] Alembic head: `0003_study_lifecycle_schema` (verified via `ls migrations/versions/`).
- [x] Next sequential rev: `0004_judgments` (matches the `0001 / 0002 / 0003` convention).
- [x] Router registration: `app.include_router(<router>, prefix="/api/v1")` per `backend/app/main.py` lines 125–129; new judgments router follows the same pattern.
- [x] Repo function convention: `db: AsyncSession` first arg; `db.flush()` only; caller commits (verified by reading `backend/app/db/repo/study.py` and `judgment_list.py`).
- [x] `prompts/` directory does not currently exist (verified — `ls` returned no such file); Story 1.3 creates it.
- [x] `docs/04_security/` exists with only a `README.md` (verified); Story 4.1 adds the first content file.
- [x] `pytest-recording` is already a test dep at `pyproject.toml` line 52 (verified).
- [x] `openai>=1.55` is already a dep at `pyproject.toml` line 34 (verified).

### 11.10 Enumerated value contract audit

This feature ships four new enumerated wire fields (three backed by CHECK constraints + one API-only filter narrowing):

| Field | Wire values | Backend source of truth (per CLAUDE.md "Enumerated Value Contract Discipline") |
|---|---|---|
| `JudgmentListStatusWire` | `generating`, `complete`, `failed` | `backend/app/db/models/judgment_list.py` CHECK `judgment_lists_status_check` (already shipped by feat_study_lifecycle) |
| `JudgmentSourceWire` | `llm`, `human`, `click` | `backend/app/db/models/judgment.py` CHECK `judgments_source_check` (this feature creates it; `click` reserved for v1.5+ but emitted on read paths) |
| `JudgmentSourceFilterWire` | `llm`, `human` | API-layer narrowing of `JudgmentSourceWire` per spec §8.4 — `click` is rejected as a filter value (GPT-5.5 cycle 1 F1). Source-of-truth comment in schemas.py points to spec §8.4 |
| `RatingWire` | `0`, `1`, `2`, `3` | `backend/app/db/models/judgment.py` CHECK `judgments_rating_check` (this feature creates it) |

Source-of-truth comments are required in `backend/app/api/v1/schemas.py` above every Literal (matches the existing `StudyStatusWire`, `ObjectiveMetric`, `TrialSortKey` pattern). Story 3.1 explicitly adds them.

No frontend in this feature, so no frontend `<select>` drift risk.

### 11.11 Audit-event coverage

`audit_log` arrives at **MVP2** per CLAUDE.md "Activates at MVP2". This feature is MVP1, so no audit-event matrix is required. Spec §6 explicitly states "N/A — `audit_log` lands at MVP2."

---

## 12) Definition of plan done

- [x] Every FR mapped to stories/tasks/tests/docs updates.
- [x] Every story includes New files, Modified files, Endpoints (where applicable), Key interfaces, Tasks, and DoD.
- [x] Test layers (unit/integration/contract) explicitly scoped; e2e marked N/A with rationale.
- [x] Documentation updates across docs/01–05 planned and owned.
- [x] Lean refactor scope and guardrails explicit (with defer-if-distracting clause).
- [x] Phase/epic gates measurable.
- [x] Story-by-Story Verification Gate included (§10).
- [x] Plan consistency review (§11) performed; two spec drifts captured for follow-up.
- [x] GPT-5.5 cross-model review cycle 1 complete: 14 findings; 13 accepted + applied inline; 1 rejected with cited counter-evidence (F11 — `SearchAdapter.render(...)` does exist at `backend/app/adapters/protocol.py:143` and is called in `backend/workers/trials.py:385`).

---

## Appendix — GPT-5.5 cross-model review log (cycle 1)

Cycle 1 GPT-5.5 review: 14 findings returned via `gpt-5.5` structured-output JSON.

| # | Pass | Severity | Finding summary | Verdict | Applied where |
|---|---|---|---|---|---|
| F1 | A | High | `?source=click` allowed but spec §8.4 only enumerates `llm`/`human` | **Accept** | Added `JudgmentSourceFilterWire` Literal; Story 3.3 task 3 updated; §11.10 table updated |
| F2 | A | High | `OPENAI_BUDGET_EXCEEDED` listed in spec §8.1 for the endpoint but no API code returns it | **Accept** | Story 3.1 added preflight C (budget peek); endpoint table now lists 503 OPENAI_BUDGET_EXCEEDED; new integration test in DoD |
| F3 | A | Medium | Missing >10K-query rejection per spec §10 threat 3 | **Accept** | Story 3.1 added preflight E (count_queries_in_set); endpoint table notes 422 cause; new integration test in DoD |
| F4 | A | Medium | Story 3.4 schema `Field(ge=0, le=3)` conflicts with `INVALID_RATING` 400 contract | **Accept** | Schema now `rating: int` unbounded; handler raises `_err(400, "INVALID_RATING", ...)` |
| F5 | A | Medium | No typed `response_model` for `POST /generate` | **Accept** | Added `GenerateJudgmentsResponse` schema; Story 3.1 task 2 updated; contract-test DoD verifies OpenAPI shape |
| F6 | A | Low | `_SourceBreakdown.click` not in spec FR-6 (only `llm` + `human`) | **Accept** | `_SourceBreakdown` now `{llm, human}` only; `source_breakdown_for_list` folds any `click` into `human` |
| F7 | A | High | Capability cache-miss path was fail-open; spec FR-3 says refuse | **Accept** | Story 3.1 preflight B treats cache miss as not-ok → 503 `LLM_PROVIDER_INCAPABLE` (`retryable=true`); failure-mode catalog updated |
| F8 | B | High | Budget check planned post-call; spec FR-2 requires pre-call | **Accept** | Story 1.7 split `peek_daily_total` (pre) + `record_cost` (post); Story 2.1 contract reorders steps 2a/2e accordingly |
| F9 | B | High | `rate_query_batch` validates returned doc_ids but signature doesn't accept `expected_doc_ids` | **Accept** | Story 1.4 signature now `expected_doc_ids: set[str]`; validation happens inside the function |
| F10 | B | Medium | Sandbox doesn't escape variable values — test expectation overstated | **Accept** | Story 1.3 test now asserts `{{ malicious }}` appears as literal text in output (proving no recursive eval); DoD wording clarified |
| F11 | B | High | `adapter.render(...)` doesn't exist on SearchAdapter | **Reject** | Counter-evidence: `backend/app/adapters/protocol.py:143` defines `render(self, template, params, query_text)`; `backend/app/adapters/elastic.py:471` implements it; `backend/workers/trials.py:385` already calls it. Plan's reference is correct |
| F12 | B | High | Calibration would compare humans to humans after overrides because UPSERT replaces LLM rows | **Accept** | Story 3.5 task 1 filters `source='llm'`; runbook 4.2 documents "run calibration before significant overrides"; new integration test for the override-pollution case |
| F13 | B | Medium | INSUFFICIENT_SAMPLES checked pre-match only; could compute kappa on <10 matched pairs | **Accept** | Story 3.5 task 1 adds post-match recheck; new integration test |
| F14 | B | High | Arq enqueue failure after `judgment_lists` INSERT leaves a stuck `generating` row | **Accept** | Story 1.2 adds `list_generating_judgment_list_ids`; Story 2.1 `WorkerSettings.on_startup` sweeps + re-enqueues (mirrors studies pattern); Story 3.1 enqueue is best-effort with the sweep as the durable safety net |

Convergence cycle 1: **13 accept / 1 reject / 0 escalate.**

### Cycle 2 — re-review of the patched plan

Cycle 2 GPT-5.5 review (sent the patched plan + the cycle-1 rejection log per the convergence protocol): 6 findings returned.

| # | Pass | Severity | Finding summary | Verdict | Applied where |
|---|---|---|---|---|---|
| C2-F1 | A | High | F14 patch is incomplete: a running worker won't re-pick a stuck row when API's `enqueue_job` fails after the on_startup sweep has already run | **Accept** | Story 3.1 enqueue task expanded: two failure modes documented (None pool vs. raised). Story 4.2 runbook ships `python -m backend.scripts.judgments_resume` CLI. Captured `chore_judgments_periodic_resume_sweep` as a follow-up idea-file plan |
| C2-F2 | B | High | Worker uses `params={}` but FR-2 says "default params" — fails for parameterized templates | **Accept** | Story 2.1 task 4 + step 2c: added `_compute_default_params(template)` helper (midpoints + first-categorical), plus a new `tests/unit/workers/test_judgment_default_params.py` |
| C2-F3 | A | Medium | `LLM_PROVIDER_INCAPABLE` retryability inconsistent: endpoint table=false, preflight task=true | **Accept** | All sites now `retryable=False` per spec §8.5 literal; the operator-recovery wording moved to a runbook note ("wait, then retry"); failure-mode catalog updated |
| C2-F4 | B | High | `compute_call_cost` returns 0.0 for unknown models with a WARN — budget gate silently defeated | **Accept** | `cost_model.compute_call_cost` now fails closed with `UnknownModelPricingError`; Story 3.1 preflight B.1 adds an upfront check returning new 503 `UNKNOWN_MODEL_PRICING` code (added to the contract test inventory; captured as spec drift) |
| C2-F5 | B | Medium | Worker resume can re-spend OpenAI dollars on already-judged queries | **Accept** | Story 2.1 step 2a adds a pre-LLM count check: if `count_judgments_for_list_and_query(...) >= top_k`, skip the LLM call. New integration test in DoD |
| C2-F6 | A | Low | `source_breakdown_for_list` click-handling inconsistent (drop vs. fold) — `llm + human` could disagree with `judgment_count` | **Accept** | Locked to "deterministically fold `click` into `human`" in both Story 1.2 docstring and Story 3.1 `_SourceBreakdown` — invariant `llm + human == judgment_count` |

Convergence cycle 2: **6 accept / 0 reject / 0 escalate.** Two new spec drifts surfaced during this cycle and are captured in §11.8: the `UNKNOWN_MODEL_PRICING` error code (not in spec §8.5) and the absence of a stated calibration "run before overrides" guideline.

### Cycle-2-derived follow-up artifacts to capture during finalization

When `state.md` + `pipeline_status.md` are written, the following idea files should be created so the work is not lost:

1. `chore_judgments_periodic_resume_sweep` — periodic (in-worker, cron-style) re-enqueue of stuck `generating` rows so a transient Redis outage during the API enqueue is auto-healed without operator intervention. Deferred per project pattern; the boot-time sweep + CLI handles MVP1.
2. `chore_spec_llm_judgments_pricing_drift` — spec §8.5 should add `UNKNOWN_MODEL_PRICING` to the error catalog (new code introduced for budget-gate honesty per cycle 2 F4). Also: spec FR-5 should explicitly state "calibration uses `source='llm'` rows; run before overrides".

These join the two cycle-1-derived drift idea files (`chore_spec_llm_judgments_endpoint_drift`, `chore_spec_llm_judgments_error_drift`) for a total of 4 spec-drift idea files this plan will surface during execution.

### Cycle 3 stopping decision

Per the convergence protocol Step 7 (cross-model loop stop rules):
- Cycle 2 surfaced **net-new findings** (not repeats from cycle 1), so the convergence isn't trivially "stop, repeats only".
- All 6 cycle-2 findings were accepted with patches that are internally consistent and don't change story scope (additions only).
- **Decision: STOP at cycle 2.** Run a cycle-3 sanity check only if a future review surface demands it; the convergence delta is bounded and the plan is execution-ready. Should `/impl-execute` surface a contradiction during implementation, that's the natural recurrence point.
