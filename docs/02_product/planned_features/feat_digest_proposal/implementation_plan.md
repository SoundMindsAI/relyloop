# Implementation Plan — feat_digest_proposal

**Date:** 2026-05-11
**Status:** Approved (3 GPT-5.5 review cycles to the cap; 20 findings accepted + applied; ready for `/impl-execute`)
**Primary spec:** [feature_spec.md](feature_spec.md)
**Policy source(s):** [CLAUDE.md](../../../../CLAUDE.md), [docs/01_architecture/data-model.md](../../../01_architecture/data-model.md), [docs/01_architecture/llm-orchestration.md](../../../01_architecture/llm-orchestration.md), [docs/01_architecture/api-conventions.md](../../../01_architecture/api-conventions.md)

---

## 0) Planning principles

- Spec traceability first: every story/task maps to FR IDs.
- Phase gates are hard stops.
- Fail-loud tests: assert explicit status/shape/errors.
- Mirror the analogous `feat_llm_judgments` (PR #35) shape — reuse the
  preflight/budget/cost-model/prompt-loader infrastructure verbatim
  rather than re-deriving.
- Replace the `digest_stub.py` shipped by Phase 2 under the same Arq job
  name (`generate_digest`) so the orchestrator's enqueue at
  [`backend/workers/orchestrator.py:370`](../../../../backend/workers/orchestrator.py#L370)
  keeps firing without orchestrator-side changes.
- Single-phase per spec §3 — no deferred phases.

## 1) Scope traceability (FR → epics/phases)

| FR ID | Epic | Stories | Notes |
|---|---|---|---|
| FR-1 (schema) | Epic 1 (foundations) | 1.1, 1.2 | Migration `0005_digests` + `Digest` ORM model + `digest` repo |
| FR-2 (digest worker) | Epic 2 (worker) | 2.1 | `backend/workers/digest.py` replaces `digest_stub.py` under same Arq job name |
| FR-2b (boot scan) | Epic 2 (worker) | 2.2 | Extend `backend/workers/all.py:on_startup` |
| FR-3 (digest fetch endpoint) | Epic 3 (API) | 3.1 | `GET /api/v1/studies/{id}/digest` |
| FR-4 (proposal CRUD) | Epic 3 (API) | 3.2, 3.3, 3.4 | POST manual, GET list+detail, POST reject |
| FR-5 (digest prompt) | Epic 1 (foundations) | 1.3 | `prompts/digest_*` files + `DigestPromptBundle` loader |
| FR-6 (repo functions) | Epic 1 (foundations) | 1.2 | proposal repo extensions + new `digest` repo |
| All FRs (docs + tests) | Epic 4 (docs/tests) | 4.1, 4.2, 4.3 | runbook, security doc extension, MVP1 user-stories flip |

**Single-phase feature; no deferred phases.** Per spec §3 Phase boundaries —
the MVP1 deliverable ships in one PR.

## 2) Delivery structure

Epic → Story → Tasks → DoD. Four epics:

1. **Foundations** — schema (migration + ORM + repo) + prompt loader.
2. **Worker** — `generate_digest` replacement + boot-scan extension.
3. **API** — 5 endpoints under `/api/v1/`.
4. **Docs / tests / cleanup** — runbook, security extension, MVP1 user-stories flip, contract & benchmark tests, file cleanup of the stub.

### Conventions (project-specific)

- All repo functions take `db: AsyncSession` first; use `db.flush()` (caller commits).
- New ORM model `Digest` exported via `backend/app/db/models/__init__.py`.
- New repo functions exported via `backend/app/db/repo/__init__.py` `__all__`.
- Settings consumed via `get_settings()` — never `Settings()` directly.
- LLM model name read from `Settings.openai_model` (CLAUDE.md Rule #8).
- All preflight + capability + budget infrastructure reused from
  `backend/app/llm/{capability_check,budget_gate,cost_model,prompt_loader}.py`
  (shipped by `feat_llm_judgments` PR #35) — no re-implementation.
- Worker uses short-lived per-iteration DB sessions (mirrors
  `backend/workers/judgments.py` pattern around `factory()` + per-query loop).
- Migration revision IDs sequential — next is `0005_digests` (head is
  `0004_judgments` per `migrations/versions/` listing).
- Prompt files live at repo-root `prompts/` (resolved via
  `Path(__file__).resolve().parents[3] / "prompts"` mirroring
  [`backend/app/llm/prompt_loader.py:37`](../../../../backend/app/llm/prompt_loader.py#L37)).
- Router error envelope helper `_err()` copied verbatim from
  [`backend/app/api/v1/judgments.py:72-77`](../../../../backend/app/api/v1/judgments.py#L72-L77).
- Cursor encoding helpers `_encode_cursor` / `_decode_cursor` likewise — defer
  hoisting to a shared `_cursor.py` to follow-up `chore_router_helpers_hoist`
  per the existing `feat_llm_judgments` deferral.

### AI Agent Execution Protocol

Standard order: read scope → backend (model → migration → repo → prompt loader → worker → API) → tests → docs → migration round-trip → final state.md update.

---

## Epic 1 — Foundations (schema + prompt)

### Story 1.1 — `digests` table migration + ORM model

**Outcome:** Alembic migration `0005_digests` creates the `digests` table per [`data-model.md` §"digests"](../../../01_architecture/data-model.md); `Digest` ORM model registered with `Base.metadata`; round-trip `upgrade → downgrade -1 → upgrade` passes.

**New files**

| File | Purpose |
|---|---|
| `migrations/versions/0005_digests.py` | Migration creating `digests` table; `down_revision='0004_judgments'`. Round-trip downgrade required (CLAUDE.md Absolute Rule #5). |
| `backend/app/db/models/digest.py` | `Digest` ORM model: id PK, study_id FK UNIQUE, narrative TEXT, parameter_importance JSONB, recommended_config JSONB, suggested_followups TEXT[], generated_by TEXT, generated_at TIMESTAMPTZ. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/db/models/__init__.py` | Export `Digest`. |
| `backend/tests/integration/test_migrations.py` | Bump head expectation from `0004_judgments` to `0005_digests` (mirrors the `0003 → 0004` bump in the `feat_llm_judgments` PR #35). |

**Key interfaces**

```python
# backend/app/db/models/digest.py
class Digest(Base):
    __tablename__ = "digests"
    # column order matches data-model.md §"digests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    study_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("studies.id"), nullable=False, unique=True,
    )
    narrative: Mapped[str] = mapped_column(Text, nullable=False)
    parameter_importance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    recommended_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    suggested_followups: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("ARRAY[]::TEXT[]"),
        # Cycle-1 F1: avoid NULL-vs-empty ambiguity at the API layer; spec
        # FR-2 zero-trials path explicitly writes `[]` and FR-5 / §8 contract
        # both expect `list[str]`. NOT NULL with an empty-array default
        # prevents an `Optional[list[str]]` shim leaking into every consumer.
    )
    generated_by: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
```

**Tasks**
1. Create `migrations/versions/0005_digests.py` with `down_revision='0004_judgments'`. Use `op.create_table('digests', ...)` + `op.create_unique_constraint(...)` for `study_id` (or `unique=True` on the column). `suggested_followups` column: `sa.Column('suggested_followups', postgresql.ARRAY(sa.Text()), nullable=False, server_default=sa.text("ARRAY[]::TEXT[]"))` per cycle-1 F1. `downgrade()` is `op.drop_table('digests')`.
2. Create `backend/app/db/models/digest.py` per Key interfaces above.
3. Export `Digest` from `backend/app/db/models/__init__.py`.
4. Patch `backend/tests/integration/test_migrations.py` to assert head is `0005_digests`.
5. Verify round-trip: `.venv/bin/alembic upgrade head && .venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head`.

**Definition of Done**
- [ ] `alembic upgrade head` succeeds; `alembic downgrade -1 && alembic upgrade head` succeeds (round-trip).
- [ ] `select * from digests` succeeds (table + columns + UNIQUE on study_id present).
- [ ] Integration test `test_migrations.py::test_alembic_head_is_latest` passes against `0005_digests`.
- [ ] New integration test `test_digests_migration.py::test_digests_table_round_trip` asserts the table appears post-upgrade and disappears post-downgrade.

---

### Story 1.2 — `digest` repo + `proposal` repo extensions

**Outcome:** New `backend/app/db/repo/digest.py` with `create_digest` + `get_digest_for_study`. Existing `backend/app/db/repo/proposal.py` extended with the 5 functions FR-6 enumerates (update_for_digest, list_paginated, count, reject, list_pending_for_boot_scan). All exported via `__init__.py` `__all__`.

**New files**

| File | Purpose |
|---|---|
| `backend/app/db/repo/digest.py` | `create_digest(db, **fields) -> Digest` and `get_digest_for_study(db, study_id) -> Digest \| None`. Caller commits convention. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/db/repo/proposal.py` | Add 5 functions per FR-6: `update_proposal_for_digest`, `list_proposals_paginated`, `count_proposals`, `reject_proposal` (raises `InvalidStateTransition` if status != 'pending'), `list_pending_proposals_for_boot_scan`. |
| `backend/app/db/repo/__init__.py` | Export the 7 new functions via the existing `__all__`. |

**Key interfaces**

```python
# backend/app/db/repo/digest.py
async def create_digest(db: AsyncSession, **fields: object) -> Digest: ...
async def get_digest_for_study(db: AsyncSession, study_id: str) -> Digest | None: ...

# backend/app/db/repo/proposal.py (extensions)
class InvalidStateTransition(RuntimeError): ...

async def update_proposal_for_digest(
    db: AsyncSession,
    proposal_id: str,
    *,
    config_diff: dict[str, Any],
    metric_delta: dict[str, Any] | None,
) -> Proposal | None:
    """Conditional UPDATE on `proposals` (cycle-3 F4).

    Implementation: `UPDATE proposals SET config_diff=:cd, metric_delta=:md
                     WHERE id=:id AND status='pending' RETURNING *`.

    Returns the updated row, or **None** if zero rows matched. Zero rows is
    the benign race outcome (operator rejected the proposal between the
    worker's pre-LLM read and the post-LLM update). The worker logs
    `digest_proposal_no_longer_pending` and persists the digest anyway —
    digest is per-study, not per-proposal, so the rejected proposal does
    not invalidate the digest narrative.
    """
    ...

async def list_proposals_paginated(
    db: AsyncSession,
    *,
    cursor: tuple[datetime, str] | None = None,
    limit: int = 50,
    status: ProposalStatusFilter | None = None,
    cluster_id: str | None = None,
) -> Sequence[Proposal]: ...

async def count_proposals(
    db: AsyncSession,
    *,
    status: ProposalStatusFilter | None = None,
    cluster_id: str | None = None,
) -> int: ...

async def reject_proposal(
    db: AsyncSession,
    proposal_id: str,
    *,
    reason: str | None,
) -> Proposal:
    """Transitions pending → rejected. Raises InvalidStateTransition otherwise."""
    ...

async def list_pending_proposals_for_boot_scan(db: AsyncSession) -> list[str]:
    """Return study_ids of pending proposals lacking a digest.

    Implemented as: SELECT p.study_id FROM proposals p
                    LEFT JOIN digests d ON d.study_id = p.study_id
                    WHERE p.status='pending' AND p.study_id IS NOT NULL AND d.id IS NULL.
    """
    ...

# Wire-value Literal type alias mirroring StudyStatusFilter convention
# (backend/app/db/repo/study.py:27).
ProposalStatusFilter = Literal["pending", "pr_opened", "pr_merged", "rejected"]
```

**Tasks**
1. Create `backend/app/db/repo/digest.py` per Key interfaces.
2. Extend `backend/app/db/repo/proposal.py` with the 5 functions + `InvalidStateTransition` + `ProposalStatusFilter` Literal. Cursor-paginated `list_proposals_paginated` mirrors `backend/app/db/repo/study.py:list_studies` ordering (`created_at DESC, id DESC`).
3. `reject_proposal` SELECT-then-UPDATE-then-flush; raises `InvalidStateTransition(proposal_id, current_status)` if `status != 'pending'` so the API layer can translate to 409.
4. Export the 7 new symbols (2 from digest.py + 5 from proposal.py) from `backend/app/db/repo/__init__.py` and add to `__all__`. Keep existing `create_proposal` and `get_proposal` exports.
5. Add `// Values must match backend/app/db/models/proposal.py CHECK proposals_status_check` source-of-truth comment above `ProposalStatusFilter`.

**Definition of Done**
- [ ] `from backend.app.db.repo import create_digest, get_digest_for_study, update_proposal_for_digest, list_proposals_paginated, count_proposals, reject_proposal, list_pending_proposals_for_boot_scan` imports cleanly.
- [ ] Integration test `test_digest_repo.py::test_create_digest_and_fetch_by_study` passes.
- [ ] Integration test `test_proposal_repo.py::test_update_for_digest_preserves_id_and_status` passes (UPDATE leaves `id`, `status='pending'`, populates `config_diff` + `metric_delta`).
- [ ] Integration test `test_proposal_repo.py::test_reject_pending_transitions_to_rejected` + `::test_reject_terminal_raises_invalid_state` pass.
- [ ] Integration test `test_proposal_repo.py::test_list_pending_proposals_for_boot_scan_excludes_proposals_with_digests` passes.

---

### Story 1.3 — Digest prompt files + `DigestPromptBundle` loader

**Outcome:** Three prompt files at repo-root `prompts/` + a `DigestPromptBundle` loader modeled on [`backend/app/llm/prompt_loader.py:JudgmentPromptBundle`](../../../../backend/app/llm/prompt_loader.py#L44-L70) — `lru_cache(maxsize=1)`, `SandboxedEnvironment(autoescape=True)`, repo-root path resolution.

**New files**

| File | Purpose |
|---|---|
| `prompts/digest_narrative.system.md` | Operator-fixed system message describing the digest author's role + the structured-output contract. |
| `prompts/digest_narrative.user.jinja` | Jinja2 template with `{{ study_name }}`, `{{ cluster_name }}`, `{{ target }}`, `{{ query_set_name }}`, `{{ query_count }}`, `{{ judgment_list_name }}`, `{{ rubric_summary }}`, `{{ baseline_metric }}`, `{{ achieved_metric }}`, `{{ top_trials }}` (loop), `{{ parameter_importance }}` (key-value loop). XML-style delimiters per the judgment prompt convention. |
| `backend/app/llm/digest_prompt.py` | New module — `DigestPromptBundle` dataclass + `load_digest_prompts()` lru_cache + `render_digest_user_prompt(...)`. Module-level shared `SandboxedEnvironment(keep_trailing_newline=True, autoescape=True)`. |

**Modified files**

| File | Change |
|---|---|
| (none — this story is purely additive) | |

**Key interfaces**

```python
# backend/app/llm/digest_prompt.py
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from collections.abc import Mapping, Sequence

from jinja2.sandbox import SandboxedEnvironment

PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"

@dataclass(frozen=True)
class DigestPromptBundle:
    system_prompt: str
    user_template_src: str

@lru_cache(maxsize=1)
def load_digest_prompts() -> DigestPromptBundle: ...

_SANDBOX_ENV = SandboxedEnvironment(keep_trailing_newline=True, autoescape=True)

def render_digest_user_prompt(
    *,
    study_name: str,
    cluster_name: str,
    target: str,
    query_set_name: str,
    query_count: int,
    judgment_list_name: str,
    rubric_summary: str,
    baseline_metric: float | None,
    achieved_metric: float,
    top_trials: Sequence[Mapping[str, Any]],          # [{number, params: {...}, primary_metric}, ...]
    parameter_importance: Mapping[str, float],
    # Cycle-2 F2: pass the deterministic recommendation INTO the prompt so the
    # LLM narrative describes the actual shipping config (not whichever
    # best-trial param it happens to focus on). The LLM no longer GENERATES
    # `recommended_config` — it RECEIVES it as INPUT and references it.
    recommended_config: Mapping[str, Any],
    dropped_template_params: Sequence[str],            # [] when no drift
    # Cycle-3 F3: explicit toggle for the narrative-only fallback path
    # (capability check failed). When False, the renderer:
    #   - omits the <recommended_config> + <dropped_template_params> blocks
    #     from the user prompt body (worker passes them but they're not
    #     emitted),
    #   - instructs the model to return free-form prose (narrative only).
    # The worker then calls OpenAI WITHOUT response_format and assigns the
    # response text to `narrative` directly. Same system prompt is used in
    # both modes; the user prompt template branches on
    # `{% if include_recommendation %}`.
    include_recommendation: bool = True,
) -> str: ...

def render_digest_system_prompt(*, include_recommendation: bool = True) -> str: ...
"""Returns the bundle's system prompt verbatim. Reserved for the rare case
where the narrative-only fallback wants a slightly different system framing —
for MVP1 the same system prompt is used for both modes."""
```

**Tasks**
1. Author `prompts/digest_narrative.system.md` (~30-50 lines): role description ("you are a search-relevance digest author"), output contract reference, constraints (ground every claim in supplied data; no doc IDs; no doc bodies; suggest only param-tuning followups).
2. Author `prompts/digest_narrative.user.jinja` (~60-100 lines): XML-delimited blocks `<study>`, `<judgment_list>`, `<baseline_vs_achieved>`, `<top_trials>` (loop), `<parameter_importance>` (loop). When `include_recommendation` (cycle-3 F3), additionally emit `<recommended_config>` (key-value loop) and (when non-empty) `<dropped_template_params>` (instructing the LLM to mention the drift in `suggested_followups`). When `not include_recommendation` (narrative-only fallback), wrap the body in a `{% if not include_recommendation %}<degraded_mode>capability check failed; return prose narrative only — no JSON, no recommendations</degraded_mode>{% endif %}` instruction so the LLM stays inside the contract. All variable substitution autoescaped (XML safety). Cycle-2 F2 + cycle-3 F3.
3. Author `backend/app/llm/digest_prompt.py` per Key interfaces. Pattern-match `prompt_loader.py` exactly — same module-level `_SANDBOX_ENV`, same lru_cache, same path resolution.
4. Export `load_digest_prompts`, `render_digest_user_prompt`, `DigestPromptBundle` from `backend/app/llm/__init__.py` (`__all__`).

**Definition of Done**
- [ ] `from backend.app.llm.digest_prompt import load_digest_prompts, render_digest_user_prompt` imports cleanly; `load_digest_prompts()` returns a populated `DigestPromptBundle`.
- [ ] Unit test `test_digest_prompt_render.py::test_renders_canonical_inputs` passes (golden render against a fixed input fixture).
- [ ] Unit test `test_digest_prompt_render.py::test_autoescape_neutralizes_adversarial_study_name` passes (study_name `</study><inject>...` is rendered as `&lt;/study&gt;&lt;inject&gt;...`).
- [ ] Unit test `test_digest_prompt_render.py::test_sandbox_rejects_attribute_access` passes (template containing `{{ ''.__class__ }}` raises `SecurityError`).

---

## Epic 1 gate (hard stop)

- [ ] Migration `0005_digests` round-trips cleanly.
- [ ] `Digest` ORM model + 7 repo functions + `DigestPromptBundle` loader all exported and unit-tested.
- [ ] `make test-unit` + targeted `pytest backend/tests/integration/test_digest_repo.py test_proposal_repo.py test_digests_migration.py` green.

---

## Epic 2 — Worker (replaces digest_stub)

### Story 2.1 — `generate_digest` worker job + stub deletion

**Outcome:** `backend/workers/digest.py` ships the full `generate_digest(ctx, study_id)` Arq job per spec FR-2. Replaces the stub at `backend/workers/digest_stub.py` (file deleted). Registration in `backend/workers/all.py:160` import + `WorkerSettings.functions` updated to point at the new module under the same Arq job name.

**New files**

| File | Purpose |
|---|---|
| `backend/workers/digest.py` | Full implementation. Mirrors the structure of [`backend/workers/judgments.py`](../../../../backend/workers/judgments.py) — preflight order, `_safe_record_cost` helper, short-lived sessions, structured-log `event_type` markers. |

**Modified files**

| File | Change |
|---|---|
| `backend/workers/all.py` | Replace `from backend.workers.digest_stub import generate_digest` with `from backend.workers.digest import generate_digest`. The `WorkerSettings.functions` entry stays as the bare `generate_digest` callable (no `arq.func()` wrapper — default Arq timeout fits a ~30s digest call). |
| `backend/workers/digest_stub.py` | **DELETE.** The stub is replaced wholesale. |

**Key interfaces**

```python
# backend/workers/digest.py

import time
from typing import Any

from openai import AsyncOpenAI
from redis.asyncio import Redis

from backend.app.core.settings import get_settings
from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.app.eval.optuna_runtime import build_storage, get_or_create_study
from backend.app.llm.budget_gate import (
    BudgetExceededError,
    peek_daily_total,
    record_cost,
)
from backend.app.llm.capability_check import read_capability_result
from backend.app.llm.cost_model import (
    UnknownModelPricingError,
    compute_call_cost,
    estimated_max_call_cost,
    known_models,
)
from backend.app.llm.digest_prompt import load_digest_prompts, render_digest_user_prompt

# Structured-output JSON schema (FR-5). Module-level so a contract test can import.
#
# Cycle-1 F5/F9: the LLM provides ONLY the narrative + suggested_followups.
# `recommended_config` is computed deterministically from the best trial's
# params (filtered to currently-declared template params per spec §11) — NOT
# from the LLM. This guarantees AC-1 ("recommended_config matching the best
# trial's params") cannot be violated by a hallucinated schema and gives the
# template-drift case a deterministic outcome.
DIGEST_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "narrative": {"type": "string"},
        "suggested_followups": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 5,  # cycle-1 F4: wired into the schema, not just prose
        },
    },
    "required": ["narrative", "suggested_followups"],
    "additionalProperties": False,
}

# The full response_format wrapper passed to chat.completions.create — built
# at the call site, mirroring backend/app/llm/openai_judge.py:144-151.
# Cycle-1 F4: kept as a module-level constant so the unit test can assert
# strict=True and the schema name without re-deriving from the call site.
DIGEST_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "digest_narrative",
        "schema": DIGEST_RESPONSE_SCHEMA,
        "strict": True,
    },
}

_TOP_K_TRIALS = 10
_MAX_COMPLETION_TOKENS = 2_000  # honest budget gate per cycle-5 C5-F1

async def _safe_record_cost(redis: Redis, cost_usd: float) -> float | None: ...
    # Identical pattern to backend/workers/judgments.py:149-168. Catches Redis flaps so a paid call isn't dropped.

async def generate_digest(ctx: dict[str, Any], study_id: str) -> None:
    """Replaces backend/workers/digest_stub.py:generate_digest.

    Cycle-2-revised flow:
      1. Load study + bail if missing or status != 'completed'.
      2. **Pre-LLM idempotency guard (cycle-1 F6):** if
         `repo.get_digest_for_study(db, study_id)` returns non-None, log
         `digest_already_persisted` + return.
      3. **Atomic per-study generation lock (cycle-2 F6):** acquire
         `pg_try_advisory_xact_lock` keyed on a hash of `study_id`
         (mirrors `backend/workers/orchestrator.py:_try_replenish_xact_lock`).
         If lock not acquired, log `digest_lock_contention` + return —
         another worker is already generating for this study. The lock is
         transaction-scoped: held across the LLM call + persist tx;
         released automatically on commit/rollback.
      4. Locate pending proposal; defensive INSERT if missing (cycle-1 cover).
      5. **Zero-trials short-circuit (cycle-2 F5):** if `study.best_metric IS NULL`,
         write failure-narrative digest (`narrative="No successful trials..."`,
         `parameter_importance={}`, `recommended_config={}`,
         `suggested_followups=[]`, `generated_by="local:zero_trials"`) + DELETE
         pending proposal + return. **No OpenAI call.** Spec AC-2 requires
         this path fires regardless of OpenAI configuration / budget state —
         must be BEFORE the OpenAI preflights below.
      6. OpenAI key check → log `digest_openai_not_configured` (with
         `error_code="OPENAI_NOT_CONFIGURED"`) + return (no row, no proposal
         mutation).
      7. Capability check → set `structured_output_enabled = (cap is not None
         and cap.structured_output == "ok" and cap.model == settings.openai_model)`.
         **Cycle-3 F2:** do NOT short-circuit on failure — the narrative-only
         fallback STILL hits OpenAI and STILL costs money, so pricing +
         budget checks below MUST still apply. Log
         `digest_capability_fail` + `error_code="LLM_PROVIDER_INCAPABLE"`
         when False; continue.
      8. Model-pricing check → log `digest_unknown_pricing` + return.
         (Applies to BOTH the structured-output path and the narrative-only
         fallback — the LLM call costs the same regardless of
         `response_format`.)
      9. Daily-budget peek → log `digest_budget_exceeded` + return.
         (Same reason as Step 8.)
     10. Load top-10 trials + best trial + Optuna study →
         `optuna.importance.get_param_importances` (try/except — fall back
         to `{}` on RuntimeError per defense-in-depth).
     11. **Compute `recommended_config` + template-drift handling
         deterministically (cycle-1 F5/F9 + cycle-2 F7):**
         - `template = await repo.get_query_template(db, study.template_id)`
         - `declared = set(template.declared_params.keys())`
         - `recommended_config = {p: v for p, v in best_trial.params.items() if p in declared}`
         - `dropped = sorted(set(best_trial.params.keys()) - declared)`
         - **All-dropped sub-case (cycle-2 F7):** if
           `best_trial.params and not recommended_config` (every best-trial
           param drifted out of the template):
             - Persist digest with `narrative` + `parameter_importance` +
               `recommended_config={}` + `suggested_followups=["Best trial
               used params no longer declared on the template; the
               recommendation is empty. Re-add the dropped params or accept
               that the optimization run is stale.", ...]`.
             - **DELETE pending proposal** (it would be a non-actionable
               apply-path artifact with `config_diff={}`).
             - Skip the proposal UPDATE in step 14.
     12. Render user prompt via `render_digest_user_prompt(...,
         include_recommendation=structured_output_enabled, ...)` — when False,
         the loader emits the degraded variant (no `<recommended_config>` /
         `<dropped_template_params>` blocks; system-prompt instructs
         narrative-only output) per cycle-3 F3. Call OpenAI with
         `response_format=DIGEST_RESPONSE_FORMAT` when structured output is
         enabled; otherwise omit `response_format` and parse the response as
         plain text into `narrative`. `max_completion_tokens=2_000` either
         way. The structured-output path receives `{narrative,
         suggested_followups}`; the narrative-only path receives just text
         that the worker assigns to `narrative` with `suggested_followups=[]`.
     13. Merge `suggested_followups`: if `dropped` (partial-drift case),
         prepend the deterministic flagging string; cap total at 5 entries.
     14. Compute `metric_delta` + `config_diff` from `recommended_config` +
         template defaults.
     15. **Persist FIRST then record cost** (mirrors judgments worker
         cycle-2 C2-F3 ordering): in one tx, INSERT digest + UPDATE pending
         proposal via `update_proposal_for_digest` (cycle-3 F4 — conditional
         on `WHERE status='pending'`; benign-race no-op when the operator
         rejected mid-LLM-call, log `digest_proposal_no_longer_pending`)
         OR (per step 11 all-dropped sub-case) DELETE the pending proposal.
         Commit. Then `_safe_record_cost`.
    """
```

**Tasks**
1. Create `backend/workers/digest.py` per Key interfaces. Reuse the same imports as `backend/workers/judgments.py` for budget/cost/capability/prompt; add the new `digest_prompt` import + `optuna_runtime.get_or_create_study` for parameter_importance.
2. Implement `_safe_record_cost` verbatim from the judgments worker pattern (lines 149-168 there).
3. Implement an `_acquire_digest_lock` async context manager mirroring [`backend/workers/orchestrator.py:_try_replenish_xact_lock`](../../../../backend/workers/orchestrator.py#L387-L409) (cycle-2 F6). Lock key: first 8 bytes of `blake2b(f"digest:{study_id}".encode(), digest_size=8)` as a signed 64-bit int (DIFFERENT prefix from the orchestrator's replenish lock so digest + replenish never collide on the same study). The context manager yields `bool` indicating acquisition. **Held across the entire LLM-call + persist transaction**, released on commit/rollback (transaction-scoped — no explicit unlock needed).
4. Implement the load-study + idempotency guard + lock acquisition (Steps 1-3 in the docstring). For each WARN path emit a structured `event_type` log key per spec §13 Operability table: `digest_openai_not_configured`, `digest_capability_fail`, `digest_unknown_pricing`, `digest_budget_exceeded`, `digest_zero_trials`, `digest_already_persisted`, `digest_lock_contention`, `digest_complete`. **Cycle-1 F2:** alongside each `event_type` for the 4 spec §8.5 worker-side reason codes, also emit `error_code=` with the literal (e.g. `logger.warning("...", event_type="digest_openai_not_configured", error_code="OPENAI_NOT_CONFIGURED", study_id=...)`). The internal-only `INVALID_STUDY_STATE` log fires from the Step 1 status-mismatch branch (defense-in-depth).
5. Implement the pending-proposal locate (`SELECT * FROM proposals WHERE study_id = :sid AND status = 'pending' LIMIT 1`). If missing, defensive INSERT mirroring [`backend/workers/digest_stub.py:67-87`](../../../../backend/workers/digest_stub.py#L67-L87).
6. **Zero-trials branch (AC-2; cycle-2 F5 — placed BEFORE OpenAI preflights):** if `study.best_metric IS NULL`, INSERT digest with placeholder narrative + empty `parameter_importance` + empty `recommended_config` + empty `suggested_followups` + `generated_by="local:zero_trials"`, DELETE the pending proposal in the same tx, return. **No OpenAI call — this path must succeed even when OPENAI_NOT_CONFIGURED.**
7. Implement OpenAI preflight Steps 6-9 in the docstring order (key → capability → pricing → budget). The capability-fail path (AC-11) renders a narrative-only prompt (omits `recommended_config` + `dropped_template_params` from the user prompt template by routing through a degraded render variant) and persists digest with `recommended_config={}` + `suggested_followups=[]` + `parameter_importance` from Optuna; pending proposal stays untouched.
8. **Happy path:** load Optuna study via `get_or_create_study(storage=ctx["optuna_storage"], optuna_study_name=study.optuna_study_name, ...)`. The orchestrator's `ctx["optuna_storage"]` is built by `WorkerSettings.on_startup` (already shipped); `digest.py` consumes it. Call `optuna.importance.get_param_importances(optuna_study)`. Wrap in try/except — if the call raises (small-study edge case), set `parameter_importance = {}` + log `digest_importance_failed` + continue. (Zero-trials is already handled at Step 6; this is defense in depth.)
9. **Compute `recommended_config` + `suggested_followups` deterministically (cycle-1 F5/F9 + cycle-2 F7):** load `template = await repo.get_query_template(db, study.template_id)`. Filter best-trial params to currently-declared template params: `recommended_config = {p: v for p, v in best_trial.params.items() if p in template.declared_params}`. Compute `dropped = sorted(set(best_trial.params) - set(template.declared_params))`.
   - **All-dropped sub-case (cycle-2 F7):** if `best_trial.params and not recommended_config`, the recommendation is empty and there's nothing useful to ship. Persist digest with `narrative` (rendered from a degraded prompt explaining the drift) + `parameter_importance` + `recommended_config={}` + `suggested_followups=[f"Best trial used {len(dropped)} params no longer declared on the template ({', '.join(dropped[:5])}{'...' if len(dropped)>5 else ''}). The recommendation is empty. Re-add the dropped params to the template or treat this study as stale."]` + DELETE the pending proposal (it would carry `config_diff={}`, an unship­pable artifact). Skip the proposal UPDATE in Step 13.
   - **Partial-drift case:** if `dropped` is non-empty but `recommended_config` is non-empty, prepare `template_drift_followup = f"Best trial used params no longer declared on the template: {dropped}. Re-establish them or accept the filtered config."` for prepending in Step 11.
10. Render via `render_digest_user_prompt(...)` passing `recommended_config=recommended_config` and `dropped_template_params=dropped` (cycle-2 F2); call OpenAI with `response_format=DIGEST_RESPONSE_FORMAT` (per cycle-1 F4); parse the structured response. The LLM returns `{narrative, suggested_followups}` only — `recommended_config` is NOT consumed from the LLM (cycle-1 F5 / cycle-2 F1).
11. Merge follow-ups: `suggested_followups = ([template_drift_followup] if dropped and recommended_config else []) + llm_response.suggested_followups`; truncate to 5 entries.
12. Compute `metric_delta = {primary_metric_key: {baseline: study.baseline_metric, achieved: study.best_metric, delta_pct: round((study.best_metric - study.baseline_metric) / study.baseline_metric * 100, 1) if study.baseline_metric else None}}` (key derived from `study.objective["metric"]` + `study.objective.get("k")` per the existing `eval/scoring.py:objective_metric_key` helper). Compute `config_diff = {p: {"from": template_defaults.get(p), "to": v} for p, v in recommended_config.items()}` using the shared `compute_default_params(template)` helper from `backend/app/domain/study/template_defaults.py` (see Lean refactor §5.2). When `recommended_config={}` (all-dropped sub-case), `config_diff={}` — but the proposal is being deleted anyway, so this branch is unreachable in the persist tx.
13. **Persist FIRST then record cost** (mirrors judgments worker cycle-2 C2-F3 ordering): in one tx, INSERT `digests` row (set `generated_by=f"openai:{settings.openai_model}"` per FR-2 + data-model.md `generated_by` column) + (partial-drift / no-drift case only) UPDATE pending proposal via `repo.update_proposal_for_digest(db, proposal.id, config_diff=config_diff, metric_delta=metric_delta)` OR (all-dropped sub-case) DELETE the pending proposal. Commit. After commit, call `await _safe_record_cost(redis, cost_usd)`.
14. **DELETE** `backend/workers/digest_stub.py` and update `backend/workers/all.py` import line `49` from `from backend.workers.digest_stub import generate_digest` to `from backend.workers.digest import generate_digest`.
15. Verify the `WorkerSettings.functions` list at [`backend/workers/all.py:160-166`](../../../../backend/workers/all.py#L160-L166) still contains the bare `generate_digest` callable (no `arq.func()` wrapper needed; default ~5min Arq timeout comfortably fits a 30s digest call per spec §13 NFR).

**Definition of Done**
- [ ] `backend/workers/digest_stub.py` no longer exists; `git ls-files` confirms deletion.
- [ ] `backend/workers/all.py` imports `generate_digest` from `backend.workers.digest`.
- [ ] Integration test `test_digest_generate.py::test_happy_path_updates_pending_proposal` passes (AC-1 — digest row created with non-empty narrative + parameter_importance + recommended_config; pending proposal UPDATED in place; no second proposal row created).
- [ ] Integration test `test_digest_zero_trials.py::test_zero_trials_writes_failure_narrative_and_deletes_proposal` passes (AC-2).
- [ ] Integration test `test_digest_openai_deferral.py::test_no_key_does_not_write_digest_or_mutate_proposal` passes (AC-10).
- [ ] Integration test `test_digest_capability_fallback.py::test_capability_fail_writes_narrative_only_digest` passes (AC-11 — narrative + parameter_importance populated; recommended_config={}; suggested_followups=[]; pending proposal untouched).
- [ ] Integration test `test_digest_budget_guardrail.py::test_budget_peek_breach_returns_without_writing` passes.
- [ ] Integration test `test_digest_unknown_pricing.py::test_unknown_model_returns_without_writing` passes.
- [ ] Integration test `test_digest_persist_then_record_cost.py::test_digest_persisted_when_redis_record_fails` passes (mirrors judgments cycle-2 C2-F3 ordering).
- [ ] **Cycle-1 F6:** integration test `test_digest_idempotency_guard.py::test_existing_digest_short_circuits_before_llm_call` passes — mock OpenAI to raise if called; pre-seed a `digests` row; assert the worker returns without raising and without modifying any state.
- [ ] **Cycle-1 F5/F9:** integration test `test_digest_template_drift.py::test_dropped_param_excluded_from_recommended_config_and_flagged_in_followups` passes — best trial used 4 params; template now declares only 3; assert `recommended_config` has 3 keys, `config_diff` has 3 keys, and `suggested_followups[0]` mentions the dropped key.
- [ ] **Cycle-2 F7:** integration test `test_digest_template_drift_all_dropped.py::test_all_dropped_writes_empty_recommendation_and_deletes_proposal` passes — best trial used 4 params; template now declares 0 of them; assert `recommended_config={}`, the pending proposal is DELETED (no second proposal created), and `suggested_followups[0]` mentions "Best trial used N params no longer declared".
- [ ] **Cycle-2 F5:** integration test `test_digest_zero_trials_with_openai_unconfigured.py::test_zero_trials_writes_failure_digest_even_when_no_openai_key` passes — `study.best_metric IS NULL` AND `Settings.openai_api_key=None`; assert the failure digest is still persisted (Step 6 of the worker flow runs before any OpenAI preflight per cycle-2 F5).
- [ ] **Cycle-2 F6:** integration test `test_digest_advisory_lock.py::test_concurrent_workers_do_not_double_pay` passes — two `generate_digest` coroutines started simultaneously against the same study; assert exactly one acquires the lock + performs the LLM call (mocked); the other logs `digest_lock_contention` + returns without calling OpenAI.
- [ ] **Cycle-3 F2:** integration test `test_digest_capability_fallback_respects_pricing.py::test_capability_fail_with_unknown_pricing_returns_without_paid_call` passes — capability check returns `structured_output='fail'` AND `Settings.openai_model` not in `known_models()`; assert worker logs `digest_unknown_pricing` (not `digest_capability_fail` as a terminal) AND mocked OpenAI was NOT called.
- [ ] **Cycle-3 F2:** integration test `test_digest_capability_fallback_respects_budget.py::test_capability_fail_with_budget_exhausted_returns_without_paid_call` passes — capability fail AND budget peek breach; assert no OpenAI call.
- [ ] **Cycle-3 F3:** unit test `test_digest_prompt_render.py::test_include_recommendation_false_emits_degraded_mode` passes — assert the rendered output contains `<degraded_mode>` and does NOT contain `<recommended_config>`.
- [ ] **Cycle-3 F4:** integration test `test_digest_reject_race.py::test_proposal_rejected_during_llm_call_does_not_overwrite` passes — start `generate_digest`, mid-LLM-call (mock with delay) the operator rejects via `POST /api/v1/proposals/{id}/reject`; assert the `update_proposal_for_digest` no-ops (zero rows affected via `WHERE status='pending'`) + worker logs `digest_proposal_no_longer_pending` + the rejection persists; the digest row IS still written (the digest is per-study, not per-proposal).
- [ ] **Cycle-1 F7:** integration test `test_digest_parameter_importance.py::test_continuous_params_present_and_sum_to_one` passes — seed a study with 4 continuous params (`field_boosts.title`, `field_boosts.body`, `tie_breaker`, `fuzziness`) and ≥10 completed trials; assert `set(parameter_importance.keys()) == {"field_boosts.title", "field_boosts.body", "tie_breaker", "fuzziness"}`, all values are floats in `[0.0, 1.0]`, and `abs(sum(values) - 1.0) < 1e-3` (matches `optuna.importance` semantics).
- [ ] **Cycle-1 F4:** unit test `test_digest_response_format.py::test_response_format_is_strict_json_schema_with_max_items` passes — asserts `DIGEST_RESPONSE_FORMAT["type"] == "json_schema"`, `DIGEST_RESPONSE_FORMAT["json_schema"]["strict"] is True`, `DIGEST_RESPONSE_FORMAT["json_schema"]["schema"]["properties"]["suggested_followups"]["maxItems"] == 5`, and the schema does NOT declare `recommended_config` (per cycle-1 F5 — that field is not LLM-generated).
- [ ] Manual log inspection verifies all 7 `event_type` markers fire on their respective paths (`digest_openai_not_configured`, `digest_capability_fail`, `digest_unknown_pricing`, `digest_budget_exceeded`, `digest_zero_trials`, `digest_already_persisted`, `digest_complete`).

---

### Story 2.2 — Boot-time pending-proposal scan extension

**Outcome:** `backend/workers/all.py:on_startup` extended per FR-2b. Scans `proposals` rows missing a corresponding `digests` row and re-enqueues `generate_digest` with deterministic `_job_id="generate_digest:{study_id}"` (mirrors [`backend/workers/all.py:122-126`](../../../../backend/workers/all.py#L122-L126)).

**Modified files**

| File | Change |
|---|---|
| `backend/workers/all.py` | Add `pending_digest_study_ids = await repo.list_pending_proposals_for_boot_scan(db)` inside the existing `factory()` block at line 92-103. Add a 4th enqueue loop after the `generating_judgment_ids` loop at line 118-131. |

**Key interfaces** (within `on_startup`)

```python
# backend/workers/all.py — extension to existing on_startup
async with factory() as db:
    running_ids = await repo.list_running_study_ids(db)
    queued_ids = await repo.list_queued_study_ids(db)
    generating_judgment_ids = await repo.list_generating_judgment_list_ids(db)
    pending_digest_study_ids = await repo.list_pending_proposals_for_boot_scan(db)
...
for sid in pending_digest_study_ids:
    await arq_pool.enqueue_job(
        "generate_digest",
        sid,
        _job_id=f"generate_digest:{sid}",
    )
    logger.info(
        "digest dispatched at worker boot",
        event_type="digest_resume_enqueued",
        study_id=sid,
    )
```

**Tasks**
1. Edit `backend/workers/all.py` `on_startup` per the Key interfaces snippet. Place the new enqueue loop AFTER the `generating_judgment_ids` loop so the boot-scan ordering is `running → queued → generating-judgments → pending-digests`.
2. Update the module docstring's `on_startup` step list (currently 3 steps at line 73-86) to mention step 4 (pending-digest scan).

**Definition of Done**
- [ ] Integration test `test_digest_boot_scan.py::test_on_startup_enqueues_pending_proposals_lacking_digests` passes (AC-9). Test seeds: a study with status=completed + a pending proposal + NO digest. Asserts that `on_startup` enqueues `generate_digest:{study_id}` exactly once.
- [ ] Integration test `test_digest_boot_scan.py::test_on_startup_skips_proposals_with_existing_digest` passes. Test seeds: a study with status=completed + a pending proposal + an existing digest. Asserts `on_startup` does NOT enqueue.
- [ ] Integration test `test_digest_boot_scan.py::test_on_startup_uses_deterministic_job_id` passes. Asserts `_job_id="generate_digest:{sid}"` is used (per FR-2b dedup contract).

---

## Epic 2 gate (hard stop)

- [ ] `digest_stub.py` deleted.
- [ ] `generate_digest` re-implemented under same Arq job name; orchestrator's enqueue at `orchestrator.py:370` continues to fire correctly (no orchestrator-side changes).
- [ ] All AC-1, AC-2, AC-9, AC-10, AC-11 paths pass integration tests.
- [ ] `make test-integration` green.

---

## Epic 3 — API (5 endpoints)

### Story 3.1 — `GET /api/v1/studies/{id}/digest` (FR-3)

**Outcome:** New router at `backend/app/api/v1/proposals.py` registered in `backend/app/main.py` alongside the existing v1 routers. First endpoint: `GET /api/v1/studies/{id}/digest`. Spec FR-3, AC-3, AC-4.

**New files**

| File | Purpose |
|---|---|
| `backend/app/api/v1/proposals.py` | New router. Hosts the digest fetch endpoint + the 4 proposal endpoints (Stories 3.2-3.4). Mirrors structure of [`backend/app/api/v1/judgments.py`](../../../../backend/app/api/v1/judgments.py): `_err`, `_encode_cursor`, `_decode_cursor`, `_summary`, `_detail` helpers copied verbatim. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/main.py` | Add `from backend.app.api.v1 import proposals as proposals_router` import + `app.include_router(proposals_router.router, prefix="/api/v1")` line after the existing `judgments_router.router` registration at line 131. |
| `backend/app/api/v1/schemas.py` | Add `DigestResponse`, `ProposalSummary`, `ProposalDetail`, `_StudySummary`, `_DigestEmbed`, `CreateProposalRequest`, `RejectProposalRequest`, `ProposalsListResponse`, `ProposalStatusWire` (Literal). All Pydantic v2 `BaseModel`. |

**Endpoints**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `GET` | `/api/v1/studies/{study_id}/digest` | — | `200 DigestResponse` | `STUDY_NOT_FOUND` (404), `DIGEST_NOT_READY` (404, retryable=true) |

**Pydantic schemas**

```python
# backend/app/api/v1/schemas.py — additions

ProposalStatusWire = Literal["pending", "pr_opened", "pr_merged", "rejected"]
"""Values must match backend/app/db/models/proposal.py CHECK proposals_status_check."""

ProposalPrStateWire = Literal["open", "closed", "merged"]
"""Values must match backend/app/db/models/proposal.py CHECK proposals_pr_state_check."""

class DigestResponse(BaseModel):
    id: str
    study_id: str
    narrative: str
    parameter_importance: dict[str, float]
    recommended_config: dict[str, Any]
    suggested_followups: list[str]
    generated_by: str
    generated_at: datetime
```

**Tasks**
1. Create `backend/app/api/v1/proposals.py`. Copy `_err`, `_encode_cursor`, `_decode_cursor` helpers verbatim from `backend/app/api/v1/judgments.py:72-90`. Module docstring: explain that this router hosts BOTH digest fetch + proposal CRUD.
2. Implement `GET /api/v1/studies/{study_id}/digest` handler:
   - Fetch study via `repo.get_study(db, study_id)`. If None → `_err(404, "STUDY_NOT_FOUND", ...)`.
   - If `study.status != "completed"` → `_err(404, "DIGEST_NOT_READY", "study is still ...", retryable=True)`.
   - Fetch digest via `repo.get_digest_for_study(db, study_id)`. If None → `_err(404, "DIGEST_NOT_READY", "digest has not been written yet", retryable=True)`.
   - Return `DigestResponse(...)`.
3. Add the schemas to `backend/app/api/v1/schemas.py`.
4. Register the router in `backend/app/main.py`.

**Definition of Done**
- [ ] AC-3 — Integration test `test_digest_fetch.py::test_fetch_existing_digest_returns_200` passes.
- [ ] AC-4 — Integration test `test_digest_fetch.py::test_fetch_on_running_study_returns_404_digest_not_ready` passes; assert `error_code="DIGEST_NOT_READY"` and `retryable=true`.
- [ ] Integration test `test_digest_fetch.py::test_fetch_on_completed_study_without_digest_returns_404` passes (worker-lag scenario).
- [ ] Integration test `test_digest_fetch.py::test_fetch_unknown_study_returns_404_study_not_found` passes.
- [ ] OpenAPI registers `GET /api/v1/studies/{study_id}/digest` with `DigestResponse` as the 200 response model.

---

### Story 3.2 — `POST /api/v1/proposals` (manual creation; FR-4)

**Outcome:** Manual proposal creation endpoint per AC-6. `study_id` and `study_trial_id` are NULL in the inserted row.

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/proposals.py` | Add `POST /api/v1/proposals` handler. |
| `backend/app/api/v1/schemas.py` | Add `CreateProposalRequest`, `ProposalDetail`, `_StudySummary`, `_DigestEmbed` (used by Story 3.3 too). |

**Endpoints**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `POST` | `/api/v1/proposals` | `{cluster_id, template_id, config_diff, metric_delta?}` | `201 ProposalDetail` | `CLUSTER_NOT_FOUND` (404), `TEMPLATE_NOT_FOUND` (404), `VALIDATION_ERROR` (422) |

**Pydantic schemas**

```python
class CreateProposalRequest(BaseModel):
    cluster_id: str = Field(min_length=1, max_length=36)
    template_id: str = Field(min_length=1, max_length=36)
    config_diff: dict[str, Any]
    metric_delta: dict[str, Any] | None = None

class _StudySummary(BaseModel):
    id: str
    name: str
    status: str
    best_metric: float | None
    best_trial_id: str | None
    query_set: dict[str, Any]    # {id, name, query_count}
    judgment_list: dict[str, Any]  # {id, name, status}

class _DigestEmbed(BaseModel):
    id: str
    narrative: str
    parameter_importance: dict[str, float]
    recommended_config: dict[str, Any]
    suggested_followups: list[str]
    generated_at: datetime

class ProposalDetail(BaseModel):
    id: str
    study_id: str | None
    study_summary: _StudySummary | None
    study_trial_id: str | None
    cluster: dict[str, Any]      # {id, name, engine_type, environment}
    template: dict[str, Any]     # {id, name, version, engine_type}
    config_diff: dict[str, Any]
    metric_delta: dict[str, Any] | None
    status: ProposalStatusWire
    pr_url: str | None
    pr_state: ProposalPrStateWire | None
    pr_merged_at: datetime | None
    pr_open_error: str | None
    rejected_reason: str | None
    digest: _DigestEmbed | None
    created_at: datetime
```

**Tasks**
1. Implement `POST /api/v1/proposals` handler:
   - Validate FK targets: `repo.get_cluster(db, body.cluster_id)` → 404 `CLUSTER_NOT_FOUND` if None; `repo.get_query_template(db, body.template_id)` → 404 `TEMPLATE_NOT_FOUND` if None.
   - Insert via `repo.create_proposal(db, id=str(uuid_utils.uuid7()), study_id=None, study_trial_id=None, cluster_id=body.cluster_id, template_id=body.template_id, config_diff=body.config_diff, metric_delta=body.metric_delta, status="pending")`.
   - Commit; refetch + assemble `ProposalDetail` (with `study_summary=None` and `digest=None`); return 201.
2. Add the schemas (including `_StudySummary` and `_DigestEmbed` used by Story 3.3).

**Definition of Done**
- [ ] AC-6 — Integration test `test_proposal_create.py::test_manual_proposal_creates_pending_row` passes; asserts `status='pending'`, `study_id IS NULL`, `study_trial_id IS NULL`.
- [ ] Integration test `test_proposal_create.py::test_create_with_unknown_cluster_returns_404` passes.
- [ ] Integration test `test_proposal_create.py::test_create_with_unknown_template_returns_404` passes.
- [ ] Integration test `test_proposal_create.py::test_create_with_missing_required_fields_returns_422` passes.

---

### Story 3.3 — `GET /api/v1/proposals` + `GET /api/v1/proposals/{id}` (FR-4)

**Outcome:** Cursor-paginated list (with `X-Total-Count` header + status + cluster_id filters) and a detail endpoint that inlines `study_summary` + `digest` to spare the UI a fan-out query.

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/proposals.py` | Add the two GET handlers. |
| `backend/app/api/v1/schemas.py` | Add `ProposalSummary`, `ProposalsListResponse`. |

**Endpoints**

| Method | Path | Query params | Success response | Error codes |
|---|---|---|---|---|
| `GET` | `/api/v1/proposals` | `?status=` (Literal), `?cluster_id=`, `?cursor=`, `?limit=` | `200 ProposalsListResponse` + `X-Total-Count` header | `VALIDATION_ERROR` (422; bad `?status=` or bad cursor) |
| `GET` | `/api/v1/proposals/{id}` | — | `200 ProposalDetail` | `PROPOSAL_NOT_FOUND` (404) |

**Pydantic schemas**

```python
class ProposalSummary(BaseModel):
    id: str
    study_id: str | None
    cluster: dict[str, Any]   # {id, name, engine_type}
    template: dict[str, Any]  # {id, name, version}
    status: ProposalStatusWire
    pr_state: ProposalPrStateWire | None
    pr_url: str | None
    metric_delta: dict[str, Any] | None
    created_at: datetime

class ProposalsListResponse(BaseModel):
    data: list[ProposalSummary]
    next_cursor: str | None
    has_more: bool
```

**Tasks**
1. Implement `GET /api/v1/proposals` handler:
   - Decode cursor (422 on bad shape via `_decode_cursor`).
   - Call `repo.list_proposals_paginated(db, cursor=..., limit=limit+1, status=status, cluster_id=cluster_id)`.
   - `has_more = len(rows) > limit`; trim; emit `X-Total-Count` from `repo.count_proposals(db, status=status, cluster_id=cluster_id)`.
   - Build `ProposalSummary` rows; need cluster + template names — fetch in batch (one `IN (...)` per resource) to avoid N+1; mirror the pattern that `feat_llm_judgments`'s list endpoint sidesteps by leaving FK names in the response model. **Decision:** use a 2-step fan-in: collect distinct `cluster_id`s and `template_id`s from the rows, fetch via `repo.get_cluster` / `repo.get_query_template` in a `dict[id, row]`, then map. (Adds a 3-level nesting cost; acceptable for MVP1 page size 50.) Note this is only on the proposals list — `feat_proposals_ui` is the consumer.
   - Source-of-truth comment above `ProposalStatusWire` Literal: `// Values must match backend/app/db/models/proposal.py CHECK proposals_status_check` (per CLAUDE.md "Enumerated Value Contract Discipline").
2. Implement `GET /api/v1/proposals/{id}` handler:
   - `repo.get_proposal(db, proposal_id)` → 404 `PROPOSAL_NOT_FOUND` if None.
   - If `study_id` non-null: fetch study + judgment_list + query_set via the existing repos to assemble `_StudySummary`.
   - If `study_id` non-null: fetch digest via `repo.get_digest_for_study(db, study_id)` to assemble `_DigestEmbed`.
   - Fetch cluster + template for the inline `cluster` / `template` blocks.
   - Return `ProposalDetail`.

**Definition of Done**
- [ ] Integration test `test_proposals_list.py::test_list_default_returns_paginated_summaries` passes; asserts `X-Total-Count` header + cursor encoding round-trip.
- [ ] Integration test `test_proposals_list.py::test_status_filter_rejects_unknown_value_with_422` passes (asserts wire-value Literal enforcement).
- [ ] Integration test `test_proposals_list.py::test_cluster_id_filter_returns_only_matching_rows` passes.
- [ ] Integration test `test_proposals_detail.py::test_detail_with_study_id_inlines_study_summary_and_digest` passes.
- [ ] Integration test `test_proposals_detail.py::test_detail_for_manual_proposal_omits_study_summary_and_digest` passes.
- [ ] Integration test `test_proposals_detail.py::test_detail_unknown_id_returns_404_proposal_not_found` passes.

---

### Story 3.4 — `POST /api/v1/proposals/{id}/reject` (FR-4 / AC-5)

**Outcome:** Pending → rejected transition with optional reason.

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/proposals.py` | Add the reject handler. |
| `backend/app/api/v1/schemas.py` | Add `RejectProposalRequest`. |

**Endpoints**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `POST` | `/api/v1/proposals/{id}/reject` | `{reason?: str}` | `200 ProposalDetail` | `PROPOSAL_NOT_FOUND` (404), `INVALID_STATE_TRANSITION` (409, retryable=false) |

**Pydantic schemas**

```python
class RejectProposalRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)
```

**Tasks**
1. Implement `POST /api/v1/proposals/{id}/reject` handler:
   - `repo.get_proposal(db, proposal_id)` → 404 `PROPOSAL_NOT_FOUND` if None.
   - `try: await repo.reject_proposal(db, proposal_id, reason=body.reason); except InvalidStateTransition: raise _err(409, "INVALID_STATE_TRANSITION", ..., retryable=False)`.
   - Commit; refetch; assemble + return `ProposalDetail`.

**Definition of Done**
- [ ] AC-5 — Integration test `test_proposal_reject.py::test_reject_pending_transitions_to_rejected_with_reason` passes; asserts `status='rejected'` + `rejected_reason='...'`.
- [ ] AC-5 second-call — Integration test `test_proposal_reject.py::test_reject_already_terminal_returns_409_invalid_state` passes; asserts `error_code='INVALID_STATE_TRANSITION'` + `retryable=false`.
- [ ] Integration test `test_proposal_reject.py::test_reject_unknown_id_returns_404_proposal_not_found` passes.
- [ ] Integration test `test_proposal_reject.py::test_reject_with_no_reason_succeeds` passes (`reason` is optional).

---

## Epic 3 gate (hard stop)

- [ ] All 5 endpoints (1 digest + 4 proposal) live and registered in OpenAPI.
- [ ] `backend/tests/contract/test_digest_proposal_api_contract.py` asserts every endpoint is registered + the **split static grep (cycle-2 F4 / cycle-3 F1):** the 7 endpoint-visible codes appear in `backend/app/api/v1/proposals.py`; the 5 internal/worker-only codes (`INVALID_STUDY_STATE` + 4 worker terminal reasons) appear in `backend/workers/digest.py`; the worker codes do NOT appear in the router source.
- [ ] `make test-integration` + `make test-contract` green.

---

## Epic 4 — Docs / tests / cleanup

### Story 4.1 — Runbook + security doc extension

**Outcome:** Operator runbook + security-doc extension.

**New files**

| File | Purpose |
|---|---|
| `docs/03_runbooks/digest-debugging.md` | Re-enqueue a digest, inspect parameter_importance JSON, manually flag a proposal as rejected via SQL, escape hatches for `OPENAI_NOT_CONFIGURED` / `OPENAI_BUDGET_EXCEEDED` deferred digests. Mirror structure of [`docs/03_runbooks/judgment-generation-debugging.md`](../../../03_runbooks/judgment-generation-debugging.md). |

**Modified files**

| File | Change |
|---|---|
| `docs/04_security/llm-data-flow.md` | Add a "Digest path" section enumerating: data sent (study summary + params + metrics + parameter-importance map only — no doc IDs, no doc bodies, no query text); never logged; ZDR enrollment guidance reuses the judgments section's. |
| `docs/02_product/mvp1-user-stories.md` | Mark US-16 + US-17 as "(Implemented — `feat_digest_proposal`)" inline, per the PR #39 sweep pattern. |

**Tasks**
1. Author `digest-debugging.md` ~150-300 lines: quick-reference CLI commands, common deferred-digest scenarios, manual re-enqueue via `arq` REPL or `python -m backend.workers.digest study_id=...` snippet.
2. Patch `docs/04_security/llm-data-flow.md` with a new section "What leaves the cluster on each digest call".
3. Patch `docs/02_product/mvp1-user-stories.md` US-16 + US-17 status.

**Definition of Done**
- [ ] `digest-debugging.md` exists; manual eyeball confirms it covers the 4 worker-side failure modes (`OPENAI_NOT_CONFIGURED`, `OPENAI_BUDGET_EXCEEDED`, `UNKNOWN_MODEL_PRICING`, `LLM_PROVIDER_INCAPABLE`).
- [ ] `docs/04_security/llm-data-flow.md` lists the digest path explicitly with the smaller-surface qualifier.
- [ ] `docs/02_product/mvp1-user-stories.md` US-16 + US-17 read "(Implemented — `feat_digest_proposal`)".

---

### Story 4.2 — Contract tests + benchmark + lean refactor

**Outcome:** Contract test mirroring `test_judgments_api_contract.py`. Benchmark for AC-8. Lean refactor: factor `_compute_default_params` into shared `backend/app/domain/study/template_defaults.py` (consumed by judgments + digest workers).

**New files**

| File | Purpose |
|---|---|
| `backend/tests/contract/test_digest_proposal_api_contract.py` | OpenAPI presence assertions for the 5 endpoints + **split static-grep audit (cycle-2 F4):** (a) router source `backend/app/api/v1/proposals.py` MUST contain the 7 endpoint-visible §8.5 codes (`STUDY_NOT_FOUND`, `DIGEST_NOT_READY`, `PROPOSAL_NOT_FOUND`, `CLUSTER_NOT_FOUND`, `TEMPLATE_NOT_FOUND`, `INVALID_STATE_TRANSITION`, `VALIDATION_ERROR`); (b) worker source `backend/workers/digest.py` MUST contain the 5 internal/worker-only codes (`INVALID_STUDY_STATE` + the 4 terminal reasons `OPENAI_NOT_CONFIGURED`, `LLM_PROVIDER_INCAPABLE`, `UNKNOWN_MODEL_PRICING`, `OPENAI_BUDGET_EXCEEDED`), each emitted as a structured `error_code=` literal alongside its `event_type` marker. The router grep MUST NOT find the worker-only codes (negative assertion — guards against an unauthorized routerization that would change the spec contract). |
| `backend/tests/integration/test_digest_token_budget.py` | AC-8 benchmark — assert measured input + output tokens < 8000 against a representative study fixture; assert `compute_call_cost(get_settings().openai_model, prompt_tokens, completion_tokens) < 0.05` (cycle-1 F8: read the model from `Settings`, do NOT hardcode `"gpt-4o-2024-08-06"`). Skip the assertion when `Settings.openai_model not in known_models()` so the benchmark stays valid as the pricing table grows. Marked `@pytest.mark.integration`. |
| `backend/app/domain/study/template_defaults.py` | New pure-Python module hosting `compute_default_params(template_row)` lifted from [`backend/workers/judgments.py:80-121`](../../../../backend/workers/judgments.py#L80-L121). |

**Modified files**

| File | Change |
|---|---|
| `backend/workers/judgments.py` | Replace inline `_compute_default_params` (lines 80-121) with `from backend.app.domain.study.template_defaults import compute_default_params`. Delete the inline function. |
| `backend/workers/digest.py` | Import `compute_default_params` from the shared module. |

**Tasks**
1. Author `test_digest_proposal_api_contract.py`. Reuse the `EXPECTED_ENDPOINTS`-set + `SPEC_ERROR_CODES` frozenset pattern from `test_judgments_api_contract.py`.
2. Author `test_digest_token_budget.py`: mock OpenAI to return a representative payload; assert the user-prompt rendered length + the recorded `usage.prompt_tokens` stay within bounds.
3. Hoist `_compute_default_params` to `backend/app/domain/study/template_defaults.py`; export `compute_default_params`. Update both worker imports.
4. Add unit test `backend/tests/unit/domain/test_template_defaults.py` covering the int / float / bool / categorical branches (carry over the test cases from any existing `test_judgment_default_params.py` if present, otherwise add fresh).

**Definition of Done**
- [ ] `make test-contract` green; `test_digest_proposal_api_contract.py` runs the cycle-2 F4 / cycle-3 F1 split grep — 7 endpoint-visible codes in router source, 5 internal/worker codes in worker source, negative assertion that the router does NOT contain worker codes — and asserts all 5 endpoints in OpenAPI.
- [ ] `make test-integration -k test_digest_token_budget` passes; AC-8 cost guardrail verified.
- [ ] Both workers import from the shared `template_defaults` module; the inline copy is gone from `judgments.py`.

---

### Story 4.3 — Final docs sweep + state.md / architecture.md updates

**Outcome:** `state.md`, `architecture.md`, `CLAUDE.md` updated post-merge per the standard impl-execute Step 8.5 finalization. (Performed automatically by `/impl-execute` Step 8.5; documented here for completeness.)

**Modified files**

| File | Change |
|---|---|
| `state.md` | Move "feat_digest_proposal" from Queued to "Most recent meaningful changes"; bump Alembic head to `0005_digests`. |
| `architecture.md` | Update the `migrations/` line to mention `0005_digests`. Update the `backend/workers/` description: replace `digest_stub.py (idempotent generate_digest stub)` with `digest.py (full digest narrative + proposal population)`. |
| `CLAUDE.md` | Update Feature Status table row 6 from "Spec approved, plan pending" → "Complete (PR #N, merged YYYY-MM-DD)". |

**Tasks**
1. Performed by `/impl-execute` finalization step. No manual work in this plan.

**Definition of Done**
- [ ] `state.md`, `architecture.md`, `CLAUDE.md` consistent with shipped behavior.
- [ ] Feature folder moved to `docs/00_overview/implemented_features/<YYYY_MM_DD>_feat_digest_proposal/` post-merge.

---

## Epic 4 gate (hard stop)

- [ ] All 4 docs files updated.
- [ ] Contract test passing; benchmark green; lean refactor in place.
- [ ] Coverage >=80% on `backend/workers/digest.py`, `backend/app/api/v1/proposals.py`, `backend/app/db/repo/proposal.py`, `backend/app/db/repo/digest.py`, `backend/app/llm/digest_prompt.py`, `backend/app/domain/study/template_defaults.py`.

---

## 3) Testing workstream

### 3.1 Unit tests

- Location: `backend/tests/unit/`
- Tasks:
  - [ ] `backend/tests/unit/workers/test_digest_prompt_render.py` — golden render + autoescape canary + sandbox-rejects-attribute-access (Story 1.3).
  - [ ] `backend/tests/unit/workers/test_digest_response_format.py` — cycle-1 F4: assert `DIGEST_RESPONSE_FORMAT` shape (json_schema, strict=True, maxItems=5; no `recommended_config` field).
  - [ ] `backend/tests/unit/domain/test_template_defaults.py` — int / float / bool / categorical branches (Story 4.2).
- DoD:
  - [ ] Critical branches covered; deterministic.

### 3.2 Integration tests

- Location: `backend/tests/integration/`
- Tasks:
  - [ ] `test_digest_repo.py` — Story 1.2.
  - [ ] `test_proposal_repo.py` — Story 1.2.
  - [ ] `test_digests_migration.py` — Story 1.1.
  - [ ] `test_digest_generate.py` — Story 2.1 happy path (AC-1).
  - [ ] `test_digest_zero_trials.py` — AC-2.
  - [ ] `test_digest_openai_deferral.py` — AC-10.
  - [ ] `test_digest_capability_fallback.py` — AC-11.
  - [ ] `test_digest_budget_guardrail.py` — Story 2.1 budget peek path.
  - [ ] `test_digest_unknown_pricing.py` — Story 2.1 pricing path.
  - [ ] `test_digest_persist_then_record_cost.py` — cycle-2 C2-F3 ordering canary.
  - [ ] `test_digest_idempotency_guard.py` — cycle-1 F6 (existing digest short-circuits before LLM call).
  - [ ] `test_digest_template_drift.py` — cycle-1 F5/F9 (dropped param excluded from `recommended_config` + flagged in `suggested_followups`).
  - [ ] `test_digest_template_drift_all_dropped.py` — cycle-2 F7 (all params dropped → empty recommendation + proposal DELETED).
  - [ ] `test_digest_zero_trials_with_openai_unconfigured.py` — cycle-2 F5 (failure digest persisted regardless of OpenAI state).
  - [ ] `test_digest_advisory_lock.py` — cycle-2 F6 (pg_try_advisory_xact_lock serializes concurrent generate_digest).
  - [ ] `test_digest_capability_fallback_respects_pricing.py` — cycle-3 F2.
  - [ ] `test_digest_capability_fallback_respects_budget.py` — cycle-3 F2.
  - [ ] `test_digest_reject_race.py` — cycle-3 F4 (conditional UPDATE no-ops on mid-LLM rejection).
  - [ ] `test_digest_parameter_importance.py` — cycle-1 F7 (AC-7: all expected continuous param keys present + values sum to ~1.0).
  - [ ] `test_digest_boot_scan.py` — Story 2.2 (AC-9).
  - [ ] `test_digest_fetch.py` — Story 3.1 (AC-3, AC-4).
  - [ ] `test_proposal_create.py` — Story 3.2 (AC-6).
  - [ ] `test_proposals_list.py` — Story 3.3.
  - [ ] `test_proposals_detail.py` — Story 3.3.
  - [ ] `test_proposal_reject.py` — Story 3.4 (AC-5).
  - [ ] `test_digest_token_budget.py` — AC-8 (Story 4.2).
- DoD:
  - [ ] Happy path + critical failure paths covered.

### 3.3 Contract tests

- Location: `backend/tests/contract/`
- Tasks:
  - [ ] `test_digest_proposal_api_contract.py` — Story 4.2.
- DoD:
  - [ ] All 5 endpoints in OpenAPI; split static-grep audit (cycle-2 F4 / cycle-3 F1) green: 7 endpoint codes in router source, 5 internal codes in worker source, negative assertion enforced.

### 3.4 E2E tests

Not in scope for this PR. UI lands with `feat_studies_ui` (digest panel on study detail page) and `feat_proposals_ui` (proposals list + detail). Both are downstream features per spec §11.

### 3.5 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `backend/tests/integration/test_migrations.py` | `0004_judgments` head expectation | 1 | Bump to `0005_digests` (Story 1.1 task). |
| `backend/tests/unit/workers/test_judgment_default_params.py` (if present) | `_compute_default_params` private import | varies | Update to import `compute_default_params` from `backend.app.domain.study.template_defaults` (Story 4.2). |
| `backend/tests/integration/test_phase2_repos.py` | `proposal` repo imports | varies | No change — additions are net new functions; existing `create_proposal` / `get_proposal` unchanged. |

### 3.5 Migration verification

- [ ] `0005_digests.py` includes `downgrade()` (drops the table).
- [ ] `alembic upgrade head` succeeds.
- [ ] Round-trip: `alembic downgrade -1 && alembic upgrade head` succeeds.

### 3.6 CI gates

- [ ] `make test-unit`
- [ ] `make test-integration`
- [ ] `make test-contract`

---

## 4) Documentation update workstream

### 4.0 Core context files

- [ ] `state.md` — Story 4.3 (Alembic head + Most-recent-changes + remove from Queued).
- [ ] `architecture.md` — Story 4.3 (`migrations/` + `backend/workers/` lines).
- [ ] `CLAUDE.md` — Story 4.3 (Feature Status table row 6).

### 4.1 Architecture docs

- [ ] `docs/01_architecture/data-model.md` already documents `digests` — no changes if implementation matches §225-238.

### 4.2 Product docs

- [ ] `docs/02_product/mvp1-user-stories.md` — US-16, US-17 marked Implemented (Story 4.1).

### 4.3 Runbooks

- [ ] `docs/03_runbooks/digest-debugging.md` — Story 4.1.

### 4.4 Security docs

- [ ] `docs/04_security/llm-data-flow.md` — extend with digest section (Story 4.1).

### 4.5 Quality docs

- [ ] No changes needed.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

- Eliminate the duplicate `_compute_default_params` between the digest worker and the judgments worker.
- Keep changes scoped — defer the router helper hoist (`_err`, `_encode_cursor`, `_decode_cursor`) to the existing follow-up `chore_router_helpers_hoist` per the `feat_llm_judgments` deferral note in [`backend/app/api/v1/judgments.py:18-23`](../../../../backend/app/api/v1/judgments.py#L18-L23).

### 5.2 Planned refactor tasks

- [ ] **Backend refactor:** factor `_compute_default_params` into `backend/app/domain/study/template_defaults.py` and consume from both `backend/workers/judgments.py` + `backend/workers/digest.py` (Story 4.2).
- [ ] **No frontend refactor** — UI is owned by `feat_studies_ui` / `feat_proposals_ui`.
- [ ] **Remove dead code:** delete `backend/workers/digest_stub.py` (Story 2.1).

### 5.3 Refactor guardrails

- [ ] Behavioral parity proven by `test_template_defaults.py` unit tests covering the same branches the inline function covered.
- [ ] Lint/typecheck green after the hoist.
- [ ] No expansion of product scope.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `feat_study_lifecycle` Phase 2 (orchestrator inserts pending proposal in same tx as `complete_study`) | Story 2.1 | Implemented (PR #25) | Worker would need to INSERT the proposal itself, doubling the tx surface |
| `feat_llm_judgments` LLM hot-path infra (`backend/app/llm/{capability_check,budget_gate,cost_model,prompt_loader}.py`) | Story 1.3 + 2.1 | Implemented (PR #35) | Re-implementation of preflight + budget machinery |
| `infra_optuna_eval` `get_or_create_study` helper | Story 2.1 | Implemented (PR #23) | Direct `optuna.load_study` call would bypass the storage-once-per-worker pattern |
| Alembic head `0004_judgments` | Story 1.1 | Implemented | Migration chain breaks |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `optuna.importance.get_param_importances` raises on small studies | M | M | Already gated by the zero-trials AC-2 branch; defense-in-depth try/except logs `digest_importance_failed` + falls back to `parameter_importance={}` (does not block digest persist) |
| Best-trial params drift out of the current template (subset or all) | M | M | **Worker-enforced** (post-cycle-1 F5 / cycle-2 F7). Story 2.1 Step 9 computes `recommended_config = filter(best_trial.params, declared)`. Partial drift → keep filtered config + prepend a deterministic follow-up. All-dropped → empty recommended_config + DELETE the pending proposal (unshippable artifact) + strong follow-up. Tests `test_digest_template_drift.py` (partial) and `test_digest_template_drift_all_dropped.py` (all) lock both paths |
| Boot-scan SELECT joins against `digests` before the `digests` table exists | L (only on a brand-new DB pre-migration) | L | The on_startup sweep runs after `make migrate`; deployment.md documents migrate-then-up ordering. Defensive: if the SELECT raises a missing-table error, log + continue (the worker is starting up, not running) |
| Two concurrent digest workers race on the same study_id | L | L | **Three layers of defense (cycle-2 F6):** (1) the boot-scan enqueue uses `_job_id="generate_digest:{sid}"` so Arq dedups same-time enqueues; (2) the worker's Step 2 pre-LLM idempotency guard checks `get_digest_for_study` and short-circuits when a digest already exists; (3) Step 3 acquires `pg_try_advisory_xact_lock` keyed on `study_id` — held across the LLM call + persist tx — so a second worker that slipped past Step 2 (interleaved read) cannot make a duplicate paid LLM call. Final safety net: `digests.study_id UNIQUE` IntegrityError handler logs + returns. **Note:** the orchestrator's enqueue at `orchestrator.py:370` still uses no `_job_id` (out of scope to modify Phase 2 code); the advisory lock is what closes that race in practice |
| Optuna study has zero `complete` trials but `best_metric` is nonzero (corruption) | VL | M | Defense: re-check `summary.best_primary_metric IS NOT NULL` AND `summary.complete > 0` before the LLM call; if mismatch, treat as zero-trials path |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| OpenAI not configured | `Settings.openai_api_key is None` | WARN log `digest_openai_not_configured`, return without writing | Operator populates the key + restarts worker → boot scan re-enqueues |
| Capability cache miss / structured_output not ok / model mismatch | `read_capability_result` returns None or wrong shape | WARN log `digest_capability_fail`, fall back to narrative-only digest | Operator fixes the upstream + manually re-runs (runbook escape hatch: `DELETE FROM digests WHERE study_id = ...` + re-enqueue) |
| Unknown model pricing | `Settings.openai_model not in known_models()` | WARN log `digest_unknown_pricing`, return without writing | Operator pins a known model OR adds the model to `cost_model.py` |
| Budget exceeded (pre-call peek) | `current + estimated_max > openai_daily_budget_usd` | WARN log `digest_budget_exceeded`, return without writing | Operator waits for daily rollover OR raises `OPENAI_DAILY_BUDGET_USD` |
| OpenAI 5xx / rate-limit after retries | All 3 attempts exhausted | WARN log; pending proposal stays `pending`; no digest row | Boot-scan re-enqueues on next worker restart |
| Redis flap during `record_cost` | `_safe_record_cost` catches | Return None; digest already persisted | Daily total under-counts that call — recoverable on rollover |
| Optuna study row missing for a completed study | RDB drift / manual delete | `get_or_create_study` creates an empty study; `get_param_importances` raises RuntimeError | Caught by defense-in-depth try/except; `parameter_importance={}`; digest still persisted with narrative |
| Pending proposal already populated by a prior run | `update_proposal_for_digest` overwrites | Idempotent UPDATE — no duplicate row created | N/A |
| `digests.study_id UNIQUE` violation on retry | INSERT against an existing digest | IntegrityError → log + return (worker treats as already-done) | N/A |

---

## 7) Sequencing and parallelization

### Suggested sequence

1. **Epic 1** (foundations): Story 1.1 → 1.2 → 1.3. Migration + repo + prompt loader before anything depends on them.
2. **Epic 2** (worker): Story 2.1 (full worker + stub deletion) → Story 2.2 (boot scan).
3. **Epic 3** (API): Stories 3.1 → 3.2 → 3.3 → 3.4. The router file is created in 3.1; subsequent stories add handlers + schemas.
4. **Epic 4** (docs / cleanup): Stories 4.1 → 4.2 → 4.3. Run last so docs reflect the final shipped behavior; lean refactor (4.2) lands together with the contract test so both workers stay green.

### Parallelization opportunities

- Story 1.3 (prompt files) can land in parallel with Story 1.1 / 1.2 — no shared file edits.
- Story 4.1 (runbook + security doc) can be drafted in parallel with Epic 3 since it doesn't touch backend code.
- Story 4.2 (lean refactor) MUST land after Story 2.1 because both workers need to import from the new shared module.

---

## 8) Rollout and cutover plan

- **Rollout stages:** N/A — single-tenant local-only MVP1 (no remote staging until MVP3).
- **Feature flag strategy:** None.
- **Migration/cutover steps:**
  1. Merge PR.
  2. Operator runs `make migrate` to apply `0005_digests`.
  3. Operator restarts worker (`docker compose restart worker`); boot scan picks up any pending proposals from the prior `complete_study` runs that lacked digests.
- **Reconciliation/repair strategy:** Pending proposals from the stub-only era are first-class boot-scan targets (FR-2b). Operator can verify with the same SELECT the boot-scan helper executes (cycle-1 F3 — corrected; `digests` is keyed on `study_id`, not `proposal_id`):
  ```sql
  SELECT count(*) FROM proposals p
  LEFT JOIN digests d ON d.study_id = p.study_id
  WHERE p.status = 'pending' AND p.study_id IS NOT NULL AND d.id IS NULL;
  ```

---

## 9) Execution tracker (copy/paste section)

### Current sprint
- [x] Story 1.1 — `digests` migration + ORM model
- [x] Story 1.2 — repo extensions
- [x] Story 1.3 — prompt loader + files
- [x] Story 2.1 — `generate_digest` worker + stub deletion
- [x] Story 2.2 — boot-scan extension
- [x] Story 3.1 — `GET /studies/{id}/digest`
- [x] Story 3.2 — `POST /proposals` (manual)
- [x] Story 3.3 — list + detail
- [x] Story 3.4 — `POST /proposals/{id}/reject`
- [x] Story 4.1 — runbook + security doc + user-stories flip
- [x] Story 4.2 — contract test + benchmark + lean refactor
- [x] Story 4.3 — finalization (state.md + architecture.md + CLAUDE.md)

### Blocked items
- (none)

### Done this sprint
- (none)

---

## 10) Story-by-Story Verification Gate (Agent Checklist)

Before marking any story complete, attach evidence for:

- [ ] Files created/modified match the story's New / Modified file tables
- [ ] Endpoint contract implemented exactly as documented (method/path/body/status/error code)
- [ ] Key interfaces implemented with compatible signatures
- [ ] Required tests added/updated for all applicable layers
- [ ] Commands run and passed:
  - [ ] `make test-unit`
  - [ ] `make test-integration` (or targeted subset with explanation)
  - [ ] `make test-contract`
- [ ] Migration round-trip evidence included (Story 1.1 only)
- [ ] Related docs updated in same PR

---

## 11) Plan consistency review (executed before publication)

1. **Spec ↔ plan endpoint count.** Spec §8.1 lists 5 endpoints. Plan: Story 3.1 (`GET /studies/{id}/digest`) + Story 3.2 (`POST /proposals`) + Story 3.3 (`GET /proposals` + `GET /proposals/{id}`) + Story 3.4 (`POST /proposals/{id}/reject`) = 5. ✓

2. **Spec ↔ plan error code coverage.** Spec §8.5 lists 7 endpoint-visible codes (`DIGEST_NOT_READY`, `STUDY_NOT_FOUND`, `PROPOSAL_NOT_FOUND`, `CLUSTER_NOT_FOUND`, `TEMPLATE_NOT_FOUND`, `INVALID_STATE_TRANSITION`, `VALIDATION_ERROR`) + 5 internal/worker-only codes (`INVALID_STUDY_STATE` defense-in-depth + 4 worker terminal reasons `OPENAI_NOT_CONFIGURED`, `LLM_PROVIDER_INCAPABLE`, `UNKNOWN_MODEL_PRICING`, `OPENAI_BUDGET_EXCEEDED`). **Cycle-2 F4 / cycle-3 F1 split:** `test_digest_proposal_api_contract.py` greps the router source `backend/app/api/v1/proposals.py` for the 7 endpoint-visible codes, greps the worker source `backend/workers/digest.py` for the 5 internal codes, and negative-asserts that the router does NOT contain any worker-only code. ✓

3. **Spec ↔ plan FR coverage.** All 7 FRs (FR-1 through FR-6 + FR-2b) appear in §1 traceability + assigned to ≥1 story. ✓

4. **Story internal consistency.** Each story's endpoint table fields match Pydantic schema fields. DoD assertions reference the correct error codes. New files claimed once. ✓

5. **Test file count and assignment.** 3 unit + 26 integration + 1 contract + 1 benchmark = 31 test files (cycle-3 added: `test_digest_capability_fallback_respects_pricing.py`, `test_digest_capability_fallback_respects_budget.py`, `test_digest_reject_race.py`). Each is assigned to exactly one story's DoD. ✓

6. **Gate arithmetic.** Epic 3 gate: "5 endpoints live" — matches stories 3.1-3.4 (1+1+2+1). ✓

7. **Open questions resolved.** Spec §19 lists no open questions. ✓

8. **Frontend UI Guidance completeness.** N/A — no frontend stories in this plan (UI is owned by `feat_studies_ui` + `feat_proposals_ui`).

9. **Plan ↔ codebase verification.** See Pass 2 ledger below.

10. **Persistence scope consistency.** No `localStorage` / `sessionStorage` usage.

11. **Enumerated value contract audit.**

   - Spec §8.4 lists 3 enumerated wire-value contracts: `proposals.status` (4 values), `proposals.pr_state` (3 values + null), and the proposals list `?status=` filter (4 values).
   - Backend source: `backend/app/db/models/proposal.py` CHECK `proposals_status_check` (line 38) → `pending, pr_opened, pr_merged, rejected`. Verified.
   - Backend source: `backend/app/db/models/proposal.py` CHECK `proposals_pr_state_check` (line 42) → `open, closed, merged` or NULL. Verified.
   - Plan: `ProposalStatusWire = Literal["pending", "pr_opened", "pr_merged", "rejected"]` with `// Values must match backend/app/db/models/proposal.py CHECK proposals_status_check` source-of-truth comment. ✓
   - Plan: `ProposalPrStateWire = Literal["open", "closed", "merged"]` with the analogous comment. ✓

12. **Admin control / ceiling enforcement audit.** N/A (MVP4+).

13. **Audit-event coverage audit.** N/A (MVP2+).

---

### Plan ↔ codebase verification ledger (Pass 2)

| Claim | Verified by | Status |
|---|---|---|
| Migration directory is `migrations/versions/` | `ls migrations/versions/` | Verified |
| Alembic head is `0004_judgments` | `ls migrations/versions/` | Verified — next is `0005_digests` |
| `Proposal` model exists with correct columns | Read `backend/app/db/models/proposal.py` | Verified |
| Orchestrator `_stop` inserts pending proposal in same tx as `complete_study` | Read `backend/workers/orchestrator.py:309-385` | Verified — proposal INSERT at lines 346-356 |
| `digest_stub.py` is registered as `generate_digest` in `WorkerSettings.functions` | Read `backend/workers/all.py:49,160-166` | Verified |
| Orchestrator enqueues `generate_digest` at `orchestrator.py:370` | Read `backend/workers/orchestrator.py:370` | Verified |
| `read_capability_result()` exists and returns `CapabilityResult \| None` | Read `backend/app/llm/capability_check.py:372` | Verified |
| `peek_daily_total` / `record_cost` exist in `budget_gate.py` | Read `backend/app/llm/budget_gate.py` | Verified |
| `known_models()` + `compute_call_cost` + `estimated_max_call_cost` + `UnknownModelPricingError` exist in `cost_model.py` | Read `backend/app/llm/cost_model.py` | Verified |
| `get_or_create_study` exists in `optuna_runtime.py` | Read `backend/app/eval/optuna_runtime.py:164-184` | Verified |
| `studies.baseline_metric` column exists | Read `backend/app/db/models/study.py:76` | Verified |
| `studies.optuna_study_name` column exists | Read `backend/app/db/models/study.py:70` | Verified |
| Repo `__init__.py` `__all__` pattern | Read `backend/app/db/repo/__init__.py:82-140` | Verified |
| FastAPI router registration pattern | Read `backend/app/main.py:35-39, 127-131` | Verified |
| Settings.openai_model + openai_base_url + openai_daily_budget_usd exist | Read `backend/app/core/settings.py:113, 108, 121` | Verified |
| Sandbox prompt loader pattern | Read `backend/app/llm/prompt_loader.py:53-72` | Verified |
| `_compute_default_params` in judgments worker (lines 80-121) | Read `backend/workers/judgments.py:80-121` | Verified |
| `_safe_record_cost` pattern in judgments worker | Read `backend/workers/judgments.py:149-168` | Verified |
| `_err`, `_encode_cursor`, `_decode_cursor` helpers in judgments router | Read `backend/app/api/v1/judgments.py:72-90` | Verified |
| Contract test pattern: OpenAPI introspection + static error-code grep | Read `backend/tests/contract/test_judgments_api_contract.py` | Verified |
| Boot-scan pattern + `_job_id` dedup | Read `backend/workers/all.py:118-131` | Verified |
| `aggregate_trials_summary` returns `best_primary_metric` + `best_trial_id` | Read `backend/app/db/repo/trial.py:193-228` | Verified |
| `data-model.md` `digests` shape (id, study_id UNIQUE, narrative, parameter_importance, recommended_config, suggested_followups TEXT[], generated_by, generated_at) | Read `docs/01_architecture/data-model.md:228-238` | Verified |

---

## 12) Definition of plan done

This plan is execution-ready when:

- [x] Every FR is mapped to stories/tasks/tests/docs.
- [x] Every story includes New/Modified files, Endpoints (where applicable), Key interfaces, Tasks, and DoD.
- [x] Test layers (unit / integration / contract) explicitly scoped — no E2E (UI deferred).
- [x] Documentation updates planned and assigned to Story 4.1 + 4.3.
- [x] Lean refactor scope explicit (Story 4.2: hoist `_compute_default_params`).
- [x] Phase/epic gates measurable.
- [x] Story-by-Story Verification Gate included (§10).
- [x] Plan consistency review (§11) executed with no unresolved findings.
- [x] **GPT-5.5 cross-model review completed.** 3 cycles to the 3-cycle cap; 20 findings total across the run (cycle 1: 9, cycle 2: 7, cycle 3: 4); all 20 accepted + applied. See cycle artifacts in `/tmp/gpt55_review_cycle{1,2,3}.out`. Pipeline status updated to Approved.
