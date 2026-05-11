# Implementation Plan — feat_study_lifecycle (Phase 2 — Orchestrator + API)

**Date:** 2026-05-10
**Status:** Implementation Complete — PR #25 open (pending human merge). All 14 stories shipped. **4 GPT-5.5 implementation-review cycles to convergence** (cycle 1: 10 findings, 5 applied + 5 deferred to idea files; cycle 2: 3 findings, all applied; cycle 3: 2 findings, all applied; cycle 4: `{"findings": []}` clean pass). See PR #25 adjudication summary comment for the full verdict table.
**Primary spec:** [feature_spec.md](feature_spec.md) (Phase 2 scope per §3 "Phase boundaries")
**Source idea:** [phase2_idea.md](phase2_idea.md) — defers FR-1..FR-7 from the 2026-05-10 Phase 1 split
**Companion plan:** [implementation_plan.md](implementation_plan.md) (Phase 1 — Schema, Complete via PR #18, merged 2026-05-10 as `d74e1be`)
**Policy source(s):**
- [CLAUDE.md](../../../../CLAUDE.md) — Absolute Rules #1 (no commit to main), #4 (engine adapter Protocol), #6 (`/healthz` unauthenticated), #7 (Conventional Commits), #9 (always invoke `/impl-execute`), #10 (never log secrets), #11 (no synchronous slow probes inside `/healthz`)
- [docs/01_architecture/api-conventions.md](../../../01_architecture/api-conventions.md) — error envelope shape, cursor pagination, `X-Total-Count`, `?since=<iso8601>`
- [docs/01_architecture/data-model.md](../../../01_architecture/data-model.md) — column-level shapes consumed by FR-1..FR-7
- [docs/01_architecture/optimization.md](../../../01_architecture/optimization.md) — Optuna ask/tell distributed pattern
- [`infra_optuna_eval` spec §11](../../../00_overview/implemented_features/2026_05_10_infra_optuna_eval/feature_spec.md) — orchestrator/worker contract; Phase 2 owns the orchestrator half

---

## 0) Planning principles

- **Spec covers both phases.** Phase 1 shipped the 7-table schema + 15 minimal repos. Phase 2 ships every FR (FR-1..FR-7) on top of that substrate. No new tables, no schema migrations.
- **State transitions go through `services/study_state.py`** (FR-7). The API enqueues; the orchestrator (Arq job) calls service-layer mutators; direct ORM `UPDATE studies.status` raises `StudyStateProtectionError`.
- **Adapter Protocol respected** (CLAUDE.md Rule #4). The orchestrator never calls `ElasticAdapter` directly — `run_trial` (already shipped by `infra_optuna_eval`) handles all engine I/O.
- **Worker contract preserved** (`infra_optuna_eval` spec §11). The orchestrator calls `study.ask()` + `trial.suggest_*` BEFORE enqueueing `run_trial(study_id, optuna_trial_number)`. The worker NEVER calls `ask()` itself.
- **Idempotency carries.** API uses optimistic transitions wrapped in row-level `SELECT … FOR UPDATE`. The orchestrator is restart-safe: `start_study` and `resume_study` collapse into a single re-entrant job (FR-5).
- **Settings env-vars, not magic constants.** New defaults — `STUDIES_DEFAULT_PARALLELISM` and `STUDIES_DEFAULT_TIMEOUT_S` — are added to `backend/app/core/settings.py` as plain env-vars (matching the `REDIS_URL` / `OPENAI_BASE_URL` / `ES_HEAP_SIZE` precedent, NOT a `*_FILE` secret). The API layer **does NOT** materialize these defaults into `studies.config` at create time — the keys stay omitted in the persisted row so `infra_optuna_eval`'s pruner key-presence contract (spec FR-2 explicit-override semantics) remains intact. The worker reads Settings at job time when a key is absent.
- **Forward-only.** No backwards-compatibility shims; no MVP1→MVP2 placeholder code. Per the project's "delete obsolete content outright" rule.

## 1) Scope traceability (FR → stories)

Every FR in the spec belongs to Phase 2:

| FR ID | Owning story | Spec §          | ACs covered |
|---|---|---|---|
| FR-1 (Study CRUD endpoints) | 3.3 (POST/GET/GET/Cancel) | §7 FR-1 | AC-1, AC-3, AC-9 |
| FR-2 (Query-template CRUD)  | 3.1 + 1.2 (validator)     | §7 FR-2 | AC-7 |
| FR-3 (Query-set CRUD + CSV) | 3.2                       | §7 FR-3 | AC-8 |
| FR-4 (Orchestrator process) | 2.1 (start_study loop)    | §7 FR-4 | AC-1, AC-2, AC-5 |
| FR-5 (Resume-after-restart) | 2.3                       | §7 FR-5 | AC-4 |
| FR-6 (Trials list endpoint) | 3.4                       | §7 FR-6 | AC-10 |
| FR-7 (State-transition guard) | 1.3 (state machine + listener) | §7 FR-7 | AC-6 |

10 ACs (AC-1 through AC-10) trace through these 7 FRs; every AC has a named owning story plus a test file in §3.

## 2) Delivery structure

**4 epics, 12 stories, 3 phase gates between epics.** Single PR — Phase 2 is one cohesive unit (orchestrator + API + tests).

### Conventions (project-specific — anchor pattern is `infra_adapter_elastic`)

- **API:** routers in `backend/app/api/v1/<resource>.py`; registered in `backend/app/main.py` with `app.include_router(<router>, prefix="/api/v1")`. Error envelope via `HTTPException(detail={"error_code", "message", "retryable"})` (mirror `backend/app/api/v1/clusters.py:_err`).
- **Cursor pagination:** opaque base64-encoded `(created_at_iso, id)` — mirror `_encode_cursor` / `_decode_cursor` in `clusters.py`. `?cursor=<opaque>&limit=<n>` (default 50, max 200). Always emit `X-Total-Count` header via `response.headers["X-Total-Count"] = str(total)`.
- **Services:** async functions in `backend/app/services/<module>.py`. Service exceptions are local types (`ClusterNameTaken`, etc.); the router maps them to envelope codes. Mirror `services/cluster.py`.
- **Domain layer:** pure Python in `backend/app/domain/study/<file>.py` (no I/O, no async). Mirror `domain/query/render.py`.
- **Repo layer:** `backend/app/db/repo/<aggregate>.py`. Functions take `db: AsyncSession` first; use `db.flush()`; caller commits. Export via `backend/app/db/repo/__init__.py` `__all__`.
- **Workers:** Arq jobs in `backend/workers/<file>.py`. Register in `backend/workers/all.py:WorkerSettings.functions`. Settings boot logic goes in `on_startup`. The existing `WorkerSettings` already exposes `ctx["optuna_storage"]` — Phase 2's orchestrator reads from `ctx` to avoid re-constructing storage.
- **Schemas:** Pydantic v2 in `backend/app/api/v1/schemas.py` (or a new sibling module if `schemas.py` gets too large — split by aggregate). Use `Literal[...]` for every enumerated value that hits the wire (CLAUDE.md "Enumerated Value Contract Discipline").
- **Tests:** `backend/tests/unit/`, `backend/tests/integration/`, `backend/tests/contract/`. Integration tests use the `db_session` fixture and the session-scoped Alembic-applied schema; external services (OpenAI, GitHub) are monkeypatched; ES/OpenSearch run as CI service containers.
- **Logging:** structlog with `event_type=` tags on every transition. Phase 2 introduces `event_type=study_state_transition`, `event_type=trial_replenished`, `event_type=stop_condition_fired` per spec §13 Operability.

### AI Agent Execution Protocol (applies to every story)

0. Read [`architecture.md`](../../../../architecture.md), [`state.md`](../../../../state.md), and the relevant section of [`feature_spec.md`](feature_spec.md) before starting the first story.
1. Read scope: verify story outcome + endpoints + interfaces + DoD against this plan.
2. Implement in dependency order: domain → service → repo extensions → router → schemas → tests.
3. Run touched test layers: `make test-unit` + `make test-integration` + `make test-contract` (whichever this story touches).
4. After each story, run `make lint typecheck` and resolve any failures.
5. Frontend stories: N/A — Phase 2 has no UI (UI is `feat_studies_ui`).
6. Update docs only at the end (Epic 4) — don't drip-edit `state.md` mid-implementation.
7. Migration round-trip: N/A — Phase 2 adds zero migrations (Phase 1 owns the schema).
8. Attach evidence in the PR description: commands run, pass/fail counts, files changed.

---

## Epic 1 — Domain, service, repo, settings primitives (Stories 1.1–1.5)

### Story 1.1 — `search_space` Pydantic validator + Optuna sampler mapping

**Outcome:** `studies.search_space` JSON payloads validate at create time (rejecting unknown sampler types, malformed ranges, and explosion-prone cardinalities per spec §10 Threat 1); a pure domain helper maps a validated `SearchSpace` onto an Optuna trial's `suggest_*` calls. Used at `POST /studies` (create-time validation) and inside the orchestrator (per-trial suggest dispatch).

**New files**

| File | Purpose |
|---|---|
| `backend/app/domain/study/__init__.py` | Package marker for the study domain subpackage |
| `backend/app/domain/study/search_space.py` | `SearchSpace` Pydantic model + `apply_search_space(trial, space) -> dict[str, Any]` + `estimate_cardinality(space) -> int` + `InvalidSearchSpaceError` |
| `backend/tests/unit/domain/test_search_space_validator.py` | Pydantic validation cases: legal floats/ints/categoricals, illegal types, missing required keys, cardinality > 10⁶ rejected, log-uniform float bounds |

**Modified files**

| File | Change |
|---|---|
| (none — purely additive within domain/) | — |

**Key interface**

```python
# backend/app/domain/study/search_space.py
from typing import Annotated, Any, Literal, Union
from pydantic import BaseModel, Field, model_validator
import optuna

class FloatParam(BaseModel):
    type: Literal["float"]
    low: float
    high: float
    log: bool = False

    @model_validator(mode="after")
    def _check_bounds(self) -> "FloatParam":
        if self.low >= self.high:
            raise ValueError(f"float param: low ({self.low}) must be < high ({self.high})")
        if self.log and self.low <= 0:
            raise ValueError(f"log-uniform float param: low must be > 0 (got {self.low})")
        return self

class IntParam(BaseModel):
    type: Literal["int"]
    low: int
    high: int

    @model_validator(mode="after")
    def _check_bounds(self) -> "IntParam":
        if self.low > self.high:
            raise ValueError(f"int param: low ({self.low}) must be <= high ({self.high})")
        return self

class CategoricalParam(BaseModel):
    type: Literal["categorical"]
    choices: Annotated[list[Union[str, int, float, bool]], Field(min_length=1)]

ParamSpec = Annotated[
    Union[FloatParam, IntParam, CategoricalParam],
    Field(discriminator="type"),
]

class SearchSpace(BaseModel):
    """Pydantic model for `studies.search_space`.

    Schema:
        {
          "params": {
            "boost_title":   {"type": "float", "low": 0.1, "high": 10.0, "log": true},
            "min_should_match": {"type": "int", "low": 1, "high": 5},
            "operator":      {"type": "categorical", "choices": ["and", "or"]}
          }
        }
    """
    params: dict[str, ParamSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_cardinality(self) -> "SearchSpace":
        if estimate_cardinality(self) > 1_000_000:
            raise ValueError(
                f"search-space cardinality estimate exceeds 10^6 (got "
                f"{estimate_cardinality(self)}); pick narrower ranges or "
                f"smaller categorical sets"
            )
        return self

class InvalidSearchSpaceError(ValueError):
    """Raised when SearchSpace.model_validate(...) fails; router translates to 400 INVALID_SEARCH_SPACE."""

def estimate_cardinality(space: SearchSpace) -> int:
    """Estimate the combinatorial size of the search space.

    Floats counted as 100 (per-param sampling resolution); ints as
    (high - low + 1); categoricals as len(choices). Product across params.
    """
    total = 1
    for spec in space.params.values():
        if isinstance(spec, FloatParam):
            total *= 100
        elif isinstance(spec, IntParam):
            total *= (spec.high - spec.low + 1)
        elif isinstance(spec, CategoricalParam):
            total *= len(spec.choices)
    return total

def apply_search_space(trial: optuna.Trial, space: SearchSpace) -> dict[str, Any]:
    """Call `trial.suggest_*` for every param in `space`; return the suggested values.

    Called by the orchestrator BEFORE enqueueing `run_trial` so the worker
    can read `FrozenTrial.params` (worker contract per `infra_optuna_eval`
    spec §11). The orchestrator wraps this in `asyncio.to_thread` because
    Optuna's `suggest_*` is synchronous.
    """
    suggested: dict[str, Any] = {}
    for name, spec in space.params.items():
        if isinstance(spec, FloatParam):
            suggested[name] = trial.suggest_float(name, spec.low, spec.high, log=spec.log)
        elif isinstance(spec, IntParam):
            suggested[name] = trial.suggest_int(name, spec.low, spec.high)
        elif isinstance(spec, CategoricalParam):
            suggested[name] = trial.suggest_categorical(name, spec.choices)
    return suggested
```

**Tasks**

1. Create the domain package + module per the interface above.
2. Author 14 unit tests in `test_search_space_validator.py` covering: minimal valid space (1 float / 1 int / 1 categorical); discriminator-based parsing; rejected `type="unknown"`; rejected `low >= high` for float and int; rejected `log=true` with `low=0`; rejected empty `params` dict; rejected empty `choices` list; rejected cardinality > 10⁶ (boundary: 99×99×100 = 980_100 OK, 100×100×101 = 1_010_000 fails); `apply_search_space` with a mocked `optuna.Trial`.
3. Verify mypy strict passes by running `make typecheck`.

**DoD**
- `from backend.app.domain.study.search_space import SearchSpace, apply_search_space, InvalidSearchSpaceError` succeeds.
- `make test-unit` green on the new file.
- `make lint typecheck` green.

---

### Story 1.2 — Query-template validator (Jinja2 SandboxedEnvironment + declared-params cross-check)

**Outcome:** Two pure-domain validators run at `POST /api/v1/query-templates` create time: (a) Jinja2 `SandboxedEnvironment.parse()` rejects sandbox-illegal expressions (e.g. `{{ os.system(...) }}`) per spec AC-7 + §10 Threat 3; (b) declared-params↔body cross-check ensures every variable referenced in the template is declared in `declared_params` and vice versa per spec FR-2. The existing runtime renderer (`backend/app/domain/query/render.py`) is refactored to use the same sandboxed environment for defense-in-depth.

**New files**

| File | Purpose |
|---|---|
| `backend/app/domain/study/template_validator.py` | `validate_template_body(body, declared_params) -> None` raises `InvalidTemplateSyntax`, `UndeclaredParamUsed`, `DeclaredParamUnused` |
| `backend/tests/unit/domain/test_template_validator.py` | AC-7 sandbox cases + cross-check matrix |

**Modified files**

| File | Change |
|---|---|
| `backend/app/domain/query/render.py` | Swap `Template(body, undefined=StrictUndefined).render(**ctx)` for `SandboxedEnvironment(undefined=StrictUndefined).from_string(body).render(**ctx)` — same render contract, sandboxed at runtime. Mirror the sandbox config used in the new validator so create-time + runtime use one allowed-construct surface. |

**Key interface**

```python
# backend/app/domain/study/template_validator.py
from jinja2 import meta, nodes
from jinja2.exceptions import TemplateSyntaxError
from jinja2.sandbox import SandboxedEnvironment

class InvalidTemplateSyntax(ValueError):
    """Jinja2 parse failed OR AST walk rejected a dangerous construct. Router → 400 INVALID_TEMPLATE_SYNTAX."""

class UndeclaredParamUsed(ValueError):
    """Template body references a param not in declared_params. Router → 400 UNDECLARED_PARAM_USED."""

class DeclaredParamUnused(ValueError):
    """declared_params lists a param not referenced in body. Router → 400 DECLARED_PARAM_UNUSED."""

# Built once at module import; reused across calls (Jinja sandboxes are
# thread-safe per the SandboxedEnvironment docs).
_SANDBOX_ENV = SandboxedEnvironment()

# query_text is the implicit param every template receives at render
# time — it carries the user's natural-language query. It does NOT need
# to be declared by the template author.
_IMPLICIT_PARAMS: frozenset[str] = frozenset({"query_text"})

def validate_template_body(body: str, declared_params: dict[str, str]) -> None:
    """Validate a Jinja2 template body against the declared param set.

    Three-step validation (order matters — sandbox check fires BEFORE the
    declared/undeclared cross-check, so `{{ os.system('rm -rf /') }}`
    surfaces as `InvalidTemplateSyntax` per AC-7 rather than the
    less-specific `UndeclaredParamUsed`):

      1. Parse via Jinja2 — raises `TemplateSyntaxError` on syntactic
         errors → mapped to `InvalidTemplateSyntax`.
      2. **AST walk** for sandbox-illegal constructs: any `Call` node, any
         `Getattr` (attribute access), or any name beginning with `_`
         (dunder/private) → `InvalidTemplateSyntax`. Note: `SandboxedEnvironment`
         enforces these at RENDER time, not parse time — `parse()` alone is
         insufficient for create-time validation, so we walk the AST here.
      3. `meta.find_undeclared_variables(parsed)` cross-check vs.
         `set(declared_params) | _IMPLICIT_PARAMS`:
           - referenced \\ declared_or_implicit → `UndeclaredParamUsed`
           - declared \\ referenced → `DeclaredParamUnused`
    """
    try:
        ast = _SANDBOX_ENV.parse(body)
    except TemplateSyntaxError as exc:
        raise InvalidTemplateSyntax(f"jinja2 parse error: {exc.message}") from exc

    # Step 2 — AST walk for dangerous constructs.
    for node in ast.find_all((nodes.Call, nodes.Getattr, nodes.Getitem)):
        if isinstance(node, nodes.Call):
            raise InvalidTemplateSyntax(
                "template body contains a call expression; "
                "Jinja2 sandbox forbids function/method invocation in query templates"
            )
        if isinstance(node, nodes.Getattr):
            raise InvalidTemplateSyntax(
                f"template body contains attribute access (.{node.attr}); "
                "Jinja2 sandbox forbids attribute access in query templates"
            )
        if isinstance(node, nodes.Getitem):
            # Subscript on a dunder/private name is suspect (e.g. `_secret[0]`).
            target = node.node
            if isinstance(target, nodes.Name) and target.name.startswith("_"):
                raise InvalidTemplateSyntax(
                    f"template body subscripts a dunder/private name ({target.name})"
                )

    # Step 2b — reject any reference to a dunder/private name (C2-F6 cycle-2
    # fix). `{{ _secret }}` would otherwise pass step 2 (no Call/Getattr/
    # Getitem) and reach the meta-vars check; if `_secret` happens to be
    # in `declared_params`, it would pass entirely. We reject all
    # `_`-prefixed name references at the AST level.
    for name_node in ast.find_all(nodes.Name):
        if name_node.name.startswith("_"):
            raise InvalidTemplateSyntax(
                f"template body references dunder/private name "
                f"({name_node.name!r}); Jinja2 sandbox forbids underscore-"
                f"prefixed identifiers in query templates"
            )

    # Step 3 — declared/undeclared cross-check.
    referenced: set[str] = meta.find_undeclared_variables(ast)
    declared: set[str] = set(declared_params) | _IMPLICIT_PARAMS

    undeclared_uses = referenced - declared
    if undeclared_uses:
        raise UndeclaredParamUsed(
            f"template references undeclared param(s): {sorted(undeclared_uses)}"
        )

    unused_declarations = set(declared_params) - referenced
    if unused_declarations:
        raise DeclaredParamUnused(
            f"declared param(s) unused in template: {sorted(unused_declarations)}"
        )
```

**Tasks**

1. Create `template_validator.py` per the interface above.
2. Refactor `backend/app/domain/query/render.py:render_template` to use the same sandboxed environment (one-line change to `Template(...)` → `SandboxedEnvironment(...).from_string(...)`). Preserve `StrictUndefined` behavior. Existing `infra_adapter_elastic` unit tests for `render_template` must continue to pass.
3. Author 12 unit tests in `test_template_validator.py`:
   - AC-7: body `{{ os.system('rm -rf /') }}` → `InvalidTemplateSyntax` (AST walk catches the `Call` node before reaching the meta-vars cross-check; otherwise this would surface as `UndeclaredParamUsed("os")` which AC-7 explicitly forbids).
   - body `{{ "".__class__ }}` → `InvalidTemplateSyntax` (AST walk: `Getattr(attr="__class__")`).
   - body `{{ obj.method() }}` → `InvalidTemplateSyntax` (Call rejected even if `obj` IS declared — sandbox forbids method invocation in templates).
   - body `{{ _secret }}` with `declared_params = {"_secret": "string"}` → `InvalidTemplateSyntax` (C2-F6 cycle-2: dunder/private name rejected at AST level regardless of declaration).
   - syntactically broken body `{% for x %}` → `InvalidTemplateSyntax`.
   - body uses `{{ foo }}` not in `declared_params` → `UndeclaredParamUsed`.
   - declared_params has `bar` not in body → `DeclaredParamUnused`.
   - body uses `{{ query_text }}` with empty `declared_params` → passes (implicit).
   - happy path: body `{"query": {"match": {"title": "{{ query_text }}^{{ boost }}"}}}` with `declared_params = {"boost": "float"}` → passes.
4. Verify the existing `infra_adapter_elastic` tests for `render_template` still pass after the sandbox refactor: `make test-unit -k render`.

**DoD**
- All 11 new unit tests pass.
- Existing `domain/query/render.py` callers (adapter `render()`) still work — verified by `make test-unit` (no regression in adapter unit tests).
- `make lint typecheck` green.

---

### Story 1.3 — Service-layer state machine + `StudyStateProtectionError` event listener (FR-7)

**Outcome:** All `studies.status` mutations route through four public service-layer functions; an SQLAlchemy `before_flush` event listener attached to the session detects out-of-band status changes and raises `StudyStateProtectionError`, satisfying AC-6.

**New files**

| File | Purpose |
|---|---|
| `backend/app/services/study_state.py` | State machine: `start_study`, `cancel_study`, `complete_study`, `fail_study` + `StudyStateProtectionError` + `InvalidStateTransition` + `_authorize_status_mutation` context manager + `_install_state_guard_listener` (SQLAlchemy event listener) |
| `backend/tests/unit/services/test_study_state.py` | Legal/illegal transition matrix + protection guard (AC-6) |

**Modified files**

| File | Change |
|---|---|
| `backend/app/db/session.py` | Call `study_state._install_state_guard_listener(...)` once at engine init, wiring the `before_flush` event listener onto the session-factory's session class. (One-line addition immediately after `async_sessionmaker(...)`.) |

**Key interface**

```python
# backend/app/services/study_state.py
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from sqlalchemy import event, inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from backend.app.db import repo
from backend.app.db.models import Study

# Public exceptions — router translates to spec §7.5 error codes.

class StudyNotFound(Exception):
    """Router → 404 STUDY_NOT_FOUND."""

class InvalidStateTransition(Exception):
    """Router → 409 INVALID_STATE_TRANSITION."""

class StudyStateProtectionError(RuntimeError):
    """Raised by the `before_flush` listener when a Study.status change is
    not authorized by the service layer. Service callers MUST wrap
    mutations in `_authorize_status_mutation` to clear this guard.
    """

# Internal authorization sentinel — set on `db.info` for the duration of a
# legitimate service-layer mutation. The before_flush listener checks for
# this sentinel and only allows status changes when it's True.

_GUARD_KEY = "_relyloop_study_state_authorized"

@asynccontextmanager
async def _authorize_status_mutation(db: AsyncSession) -> AsyncIterator[None]:
    sync_session = db.sync_session
    sync_session.info[_GUARD_KEY] = True
    try:
        yield
    finally:
        sync_session.info.pop(_GUARD_KEY, None)

# Legal transitions per spec §9 state transition diagram:
_LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued":    frozenset({"running", "cancelled"}),
    "running":   frozenset({"completed", "cancelled", "failed"}),
    "completed": frozenset(),
    "cancelled": frozenset(),
    "failed":    frozenset(),
}

async def start_study(db: AsyncSession, study_id: str) -> Study:
    """Atomic `queued → running`; stamps `started_at = now()`. Idempotent on
    `running` (resume path returns the row unchanged)."""
    study = await _load_for_update(db, study_id)
    if study.status == "running":
        return study  # resume — already running, no-op
    _ensure_legal(study.status, "running")
    async with _authorize_status_mutation(db):
        study.status = "running"
        study.started_at = datetime.now(UTC)
        await db.flush()
    return study

async def cancel_study(db: AsyncSession, study_id: str) -> Study:
    """User-initiated cancel from API; emits `state_transition` log."""
    study = await _load_for_update(db, study_id)
    _ensure_legal(study.status, "cancelled")
    async with _authorize_status_mutation(db):
        study.status = "cancelled"
        study.completed_at = datetime.now(UTC)
        await db.flush()
    return study

async def complete_study(
    db: AsyncSession,
    study_id: str,
    *,
    best_metric: float | None,
    best_trial_id: str | None,
    stop_reason: str,
) -> Study:
    """Orchestrator-initiated success transition + denormalization."""
    study = await _load_for_update(db, study_id)
    _ensure_legal(study.status, "completed")
    async with _authorize_status_mutation(db):
        study.status = "completed"
        study.completed_at = datetime.now(UTC)
        study.best_metric = best_metric
        study.best_trial_id = best_trial_id
        await db.flush()
    return study

async def fail_study(
    db: AsyncSession,
    study_id: str,
    *,
    failed_reason: str,
) -> Study:
    """Orchestrator-initiated failure transition (e.g. 5 consecutive trial failures)."""
    study = await _load_for_update(db, study_id)
    _ensure_legal(study.status, "failed")
    async with _authorize_status_mutation(db):
        study.status = "failed"
        study.completed_at = datetime.now(UTC)
        study.failed_reason = failed_reason
        await db.flush()
    return study

# Helpers

async def _load_for_update(db: AsyncSession, study_id: str) -> Study:
    """SELECT … FOR UPDATE to serialize concurrent transitions (e.g. user
    cancel vs. orchestrator max_trials-stop race per spec §11 "Cancel
    race")."""
    from sqlalchemy import select
    stmt = select(Study).where(Study.id == study_id).with_for_update()
    study = (await db.execute(stmt)).scalar_one_or_none()
    if study is None:
        raise StudyNotFound(study_id)
    return study

def _ensure_legal(current: str, target: str) -> None:
    if target not in _LEGAL_TRANSITIONS.get(current, frozenset()):
        raise InvalidStateTransition(
            f"illegal transition: {current!r} → {target!r}"
        )

# Event listener — installed once per process.
#
# `_guard` is defined at MODULE SCOPE (not inside the installer) so its
# callable identity is stable across `_install_state_guard_listener()`
# invocations. SQLAlchemy's `event.contains(...)` short-circuits the
# registration if the same callable is already attached — but only when
# the callable identity matches. A locally-defined inner function would
# create a new identity per installer call, sneaking duplicate listeners
# onto `Session` across test sessions (C2-F2 cycle-2 fix).

from sqlalchemy.orm import Session  # module-level import — Session is the
                                    # sync class all AsyncSession instances
                                    # inherit from; the listener fires for
                                    # every flush including async ones.


def _study_state_guard(
    session: Session, flush_context: object, instances: object
) -> None:
    """Module-level `before_flush` listener — stable callable identity."""
    if session.info.get(_GUARD_KEY):
        return
    for obj in session.dirty:
        if not isinstance(obj, Study):
            continue
        history = inspect(obj).attrs["status"].history
        if history.has_changes():
            raise StudyStateProtectionError(
                "direct UPDATE of studies.status outside the service "
                "layer is forbidden; route through "
                "backend.app.services.study_state"
            )


def _install_state_guard_listener(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Idempotently attach `_study_state_guard` to `Session.before_flush`.

    Safe to call multiple times — `event.contains(...)` check short-circuits
    duplicate registration (C2-F2 cycle-2 fix). Tests that rebuild a fresh
    session factory get the same single listener.

    The `session_factory` parameter is preserved for signature compatibility
    with the original Story 1.3 wiring; it isn't used by the listener
    (Session is module-imported above).
    """
    del session_factory  # not used — listener target is `Session` directly
    if not event.contains(Session, "before_flush", _study_state_guard):
        event.listen(Session, "before_flush", _study_state_guard)
```

`inspect(obj).attrs["status"].history.has_changes()` is the canonical SQLAlchemy 2.0 idiom for "did this mapped attribute change since load?". Reference: `sqlalchemy.orm.AttributeState.history`.

**Tasks**

1. Create `services/study_state.py` per the interface above. Use `sqlalchemy.inspect(obj).attrs["status"].history.has_changes()` for the "did status change?" check.
2. Modify `backend/app/db/session.py` to call `_install_state_guard_listener(session_factory)` after the `async_sessionmaker` is built. Single one-line addition.
3. Author 12 unit tests in `test_study_state.py`:
   - Happy: every legal transition (`queued→running`, `queued→cancelled`, `running→completed`, `running→cancelled`, `running→failed`) succeeds with correct timestamp + denormalization side effects.
   - Sad: every illegal transition (`completed→*`, `cancelled→*`, `failed→*`, `queued→completed`, `queued→failed`, `running→queued`) raises `InvalidStateTransition`.
   - AC-6: direct `study.status = "completed"` outside the service layer (mock session in unit; integration test does the real thing) raises `StudyStateProtectionError`.
   - Resume idempotence: `start_study` on a `running` study returns unchanged.
   - StudyNotFound when ID is absent.
4. Also assert the protection guard catches the AC-6 scenario at the integration layer — this lives in `test_study_lifecycle.py` (Story 2.1's test file), since AC-6 needs a real DB session to trigger the event listener.

**DoD**
- All 12 unit tests pass.
- Integration smoke for AC-6 lives in Story 2.1's `test_study_lifecycle.py`.
- `make lint typecheck` green.

---

### Story 1.4 — Repo extensions: cursor pagination + filters + counts + trials summary + sort

**Outcome:** Repository functions Phase 2 needs (cursor pagination, status filter, `?since=` filter, `X-Total-Count` counts, `trials_summary` aggregation, sortable trials list, bulk `queries` insert) land alongside the Phase 1 minimal set. Mirror the existing `cluster.py` pagination pattern.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/integration/test_phase2_repos.py` | Round-trip tests for each new repo function (pagination, filters, counts, trials_summary, sort variants, bulk insert) |

**Modified files**

| File | Change |
|---|---|
| `backend/app/db/repo/study.py` | Add `list_studies(db, *, cursor, limit, since, status)` + `count_studies(db, *, since, status)` |
| `backend/app/db/repo/trial.py` | Add `list_trials_paginated(db, study_id, *, cursor, limit, sort_key)` + `count_trials(db, study_id)` + `aggregate_trials_summary(db, study_id) -> TrialsSummary` |
| `backend/app/db/repo/query_template.py` | Add `list_query_templates(db, *, cursor, limit, since)` + `count_query_templates(db, *, since)` |
| `backend/app/db/repo/query_set.py` | Add `list_query_sets(db, *, cursor, limit, since)` + `count_query_sets(db, *, since)` + `count_queries_in_set(db, query_set_id)` |
| `backend/app/db/repo/query.py` | Add `bulk_create_queries(db, query_set_id, rows) -> int` (returns inserted count) |
| `backend/app/db/repo/__init__.py` | Re-export every new function via `__all__` |

**Key interfaces**

```python
# backend/app/db/repo/trial.py — new functions
from dataclasses import dataclass
from typing import Literal

TrialSortKey = Literal[
    "primary_metric_desc",
    "primary_metric_asc",
    "created_at_desc",
    "created_at_asc",
    "optuna_trial_number_asc",
]
"""Wire values surfaced by `GET /studies/{id}/trials?sort=...` per spec §7.4.
Must match the corresponding `Literal[...]` in `backend/app/api/v1/schemas.py`."""

@dataclass(frozen=True)
class TrialsSummary:
    total: int
    complete: int
    failed: int
    pruned: int
    best_primary_metric: float | None
    best_trial_id: str | None

async def aggregate_trials_summary(db: AsyncSession, study_id: str) -> TrialsSummary:
    """Single-query aggregation for `GET /studies/{id}.trials_summary` per FR-1.

    Implementation: one SELECT with COUNT(*) FILTER (WHERE status='complete')…
    + MAX(primary_metric) FILTER (WHERE status='complete') + a window
    function for `best_trial_id`. Wall-clock target <100ms p99 per spec §13.
    """
    ...

async def list_trials_paginated(
    db: AsyncSession,
    study_id: str,
    *,
    cursor: tuple[float | None, str] | None = None,
    limit: int = 50,
    sort_key: TrialSortKey = "primary_metric_desc",
    since: datetime | None = None,
) -> Sequence[Trial]:
    """Cursor-paginated trials list, sortable by 5 wire values.

    Cursor shape depends on sort_key: `(primary_metric, id)` for primary_metric_*,
    `(created_at, id)` for created_at_*, `(optuna_trial_number, id)` for the
    last. The router encodes/decodes per sort_key.

    `since` filters by `created_at >= since` (per api-conventions.md
    "Filtering by recency" cross-cutting contract — every list endpoint
    accepts `?since=<iso8601>`; F8 cycle-1 fix).
    """
    ...

async def count_trials(
    db: AsyncSession,
    study_id: str,
    *,
    since: datetime | None = None,
) -> int:
    """Single COUNT(*) for the `X-Total-Count` header on
    `GET /studies/{id}/trials`. Filters by `study_id` and optionally
    `created_at >= since`."""
    ...
```

```python
# backend/app/db/repo/study.py — new functions
from typing import Literal

StudyStatusFilter = Literal["queued", "running", "completed", "cancelled", "failed"]
"""Wire values surfaced by `GET /studies?status=...` per spec §7.4.
Must match `backend/app/db/models/study.py` CHECK constraint + the
corresponding `Literal[...]` in `backend/app/api/v1/schemas.py`."""

async def list_studies(
    db: AsyncSession,
    *,
    cursor: tuple[datetime, str] | None = None,
    limit: int = 50,
    since: datetime | None = None,
    status: StudyStatusFilter | None = None,
) -> Sequence[Study]:
    """Cursor-paginated study list, optionally filtered by status + since.

    Order: `created_at DESC, id DESC`. Mirror the row-value comparison
    used in `cluster.py:list_clusters` so the predicate is portable.
    """
    ...

async def count_studies(
    db: AsyncSession,
    *,
    since: datetime | None = None,
    status: StudyStatusFilter | None = None,
) -> int:
    """Single COUNT(*) for the `X-Total-Count` header."""
    ...
```

```python
# backend/app/db/repo/query.py — new function
async def bulk_create_queries(
    db: AsyncSession,
    query_set_id: str,
    rows: Sequence[dict[str, Any]],
) -> int:
    """Bulk-INSERT `len(rows)` Query rows under `query_set_id`. Returns
    the count of rows actually inserted. Caller commits.

    Each row must contain `query_text`; `reference_answer` and
    `query_metadata` are optional. UUIDv7 IDs are generated client-side
    here so the response can echo IDs without a SELECT round-trip.
    """
    ...
```

**Tasks**

1. Add the new repo functions per the signatures above. Mirror `cluster.py:list_clusters` for cursor pagination and `cluster.py:count_clusters` for counts.
2. For `aggregate_trials_summary`: implement as a single SQL statement using `COUNT(*) FILTER (WHERE status=...)` + `MAX(primary_metric) FILTER (WHERE status='complete')`. Use a subquery / `DISTINCT ON` (or `argmax` via window function) to identify the `best_trial_id` matching the best metric.
3. For `list_trials_paginated`: sort-key dispatch lives in this function; the router only encodes/decodes the cursor shape. The `trials_study_metric` index from Phase 1 covers `primary_metric_*` variants; `created_at_*` falls back to a sequential scan on small studies (acceptable for MVP1).
4. Update `backend/app/db/repo/__init__.py` `__all__` to re-export every new function.
5. Author 11 integration tests in `test_phase2_repos.py`:
   - `list_studies` cursor pagination round-trip (insert 75, paginate 50+25).
   - `list_studies` with `status="running"` filter.
   - `list_studies` with `since=<iso8601>` filter (use `created_at` manipulation).
   - `count_studies` matches `len(list_studies)` ignoring pagination.
   - `aggregate_trials_summary` shape: 5 complete + 2 failed + 1 pruned → `(8, 5, 2, 1, max_metric, best_id)`.
   - `aggregate_trials_summary` on empty study → `(0, 0, 0, 0, None, None)`.
   - `list_trials_paginated` with `sort_key="primary_metric_desc"` returns trials in metric order.
   - `list_trials_paginated` with `sort_key="primary_metric_asc"` reverses.
   - `list_trials_paginated` with `sort_key="optuna_trial_number_asc"` matches Phase 1's default order.
   - `bulk_create_queries` inserts N rows and returns count N.
   - `count_queries_in_set` returns the post-bulk count.

**DoD**
- All 11 new integration tests pass against the CI service-container Postgres.
- Existing `test_study_repos.py` (Phase 1) still green.
- `make lint typecheck` green.

---

### Story 1.5 — Settings additions: `STUDIES_DEFAULT_PARALLELISM` + `STUDIES_DEFAULT_TIMEOUT_S`

**Outcome:** Two new plain-env-var settings land in `backend/app/core/settings.py` as fallbacks the orchestrator reads when `studies.config.parallelism` / `studies.config.trial_timeout_s` are absent. The API layer **does NOT** materialize these into `studies.config` at create time — keys stay omitted, preserving `infra_optuna_eval`'s pruner key-presence contract.

**New files**

| File | Purpose |
|---|---|
| (none — appends to existing modules) | — |

**Modified files**

| File | Change |
|---|---|
| `backend/app/core/settings.py` | Add two `Field(default=...)` declarations: `studies_default_parallelism: int = Field(default=4, ge=1, le=64)` + `studies_default_timeout_s: int = Field(default=60, ge=5, le=3600)`. Mirror the existing `redis_url` / `openai_base_url` / `es_heap_size` plain-env pattern. Update the module docstring's "Plain values" list. |
| `backend/tests/unit/test_settings.py` | Add 2 cases: defaults present when env unset; env override picked up. |
| `.env.example` | Add 2 lines documenting the new env-vars + defaults (so operators see them in `cp .env.example .env`). |

**Tasks**

1. Add the two fields to `Settings` per the spec.
2. Extend `test_settings.py` with the two test cases.
3. Add 2 lines to `.env.example` (under the existing non-secret section).

**DoD**
- `get_settings().studies_default_parallelism == 4` when env is unset.
- `STUDIES_DEFAULT_PARALLELISM=8` env override picks up.
- `make test-unit` green.
- `.env.example` documents both fields.

---

### Epic 1 phase gate (hard stop — do not proceed to Epic 2)

- [ ] Stories 1.1, 1.2, 1.3, 1.4, 1.5 all complete with their per-story DoD ticked.
- [ ] `make test-unit test-integration` green.
- [ ] `make lint typecheck` green.
- [ ] `domain/query/render.py` sandbox refactor verified non-regressive against existing adapter tests (`make test-unit -k render` + `make test-integration -k cluster`).
- [ ] **GPT-5.5 phase-gate diff review** per `impl-execute` Step 4 — review the cumulative Epic 1 diff against the spec + this plan; adjudicate findings per the four-quadrant rubric; commit any review-fix changes.

---

## Epic 2 — Orchestrator + worker integration (Stories 2.1–2.3)

### Story 2.1 — `start_study` Arq job: ask/tell loop, replenishment, stop conditions, AC-5 failure detection (FR-4)

**Outcome:** `backend/workers/orchestrator.py` ships a single Arq job (`start_study(ctx, study_id)`) that picks up a `queued` study, transitions it to `running` via the service layer (Story 1.3), initializes the Optuna study (reuses `ctx["optuna_storage"]` from `infra_optuna_eval`'s `on_startup`), enqueues `parallelism` initial `run_trial` jobs (each preceded by `study.ask()` + `apply_search_space`), then polls every 1s for completion / cancel / stop-condition / consecutive-failure. On stop-condition fire calls `services.study_state.complete_study(...)` and enqueues the digest job. AC-1, AC-2, AC-5, AC-10 verified.

**New files**

| File | Purpose |
|---|---|
| `backend/workers/orchestrator.py` | `start_study` Arq job + `_count_in_flight` + `_last_n_all_failed` + `_stop` + `_drain_in_flight` helpers |
| `backend/workers/digest_stub.py` | **Idempotent digest handoff acknowledger** (F10 cycle-1 + C2-F3 cycle-2 + C3-F1 cycle-3 atomicity fix). The durable forward marker (a `proposals` row with `status='pending'`) is now created **inside `_stop()`'s `complete_study` transaction** (see `orchestrator.py:_stop`) — so the proposal exists the moment the study is `completed`, regardless of whether the Arq job runs. `generate_digest(ctx, study_id)` is therefore just an **idempotent acknowledger**: it SELECTs the pending proposal for `study_id`; if present, logs `event_type=digest_deferred` and returns; if absent (race: this job ran BEFORE the proposal row committed — extremely unlikely given commit-then-enqueue ordering), INSERTs the row defensively. Safe to retry. **`feat_digest_proposal` REPLACES this file** — its impl-plan removes `digest_stub.py` and registers a real `generate_digest` worker that consumes both newly-enqueued AND pre-existing `status='pending'` proposal rows at boot. |
| `backend/tests/integration/test_study_lifecycle.py` | AC-1, AC-2, AC-5, AC-10, AC-6 — full create→run→complete cycle against seeded local-es; cluster-failure path; sort verification |
| `backend/tests/integration/test_cancel_race.py` | Two-session race test (F5 cycle-1 fix): orchestrator's `_stop` calls `complete_study` while a parallel session calls `cancel_study`; assert the loser raises `InvalidStateTransition` and the orchestrator silently exits per spec §11 |
| `backend/tests/integration/fixtures/study_factories.py` | Test helpers to seed a complete study (cluster, query_set, queries, judgment_list with monkeypatched qrels, template, study row) |

**Modified files**

| File | Change |
|---|---|
| `backend/workers/all.py` | Append `start_study`, `resume_study` (Story 2.3), and **`generate_digest`** (the digest_stub function — F10) to `WorkerSettings.functions`. Add per-job `job_timeout`: `start_study` / `resume_study` get `job_timeout=86400` (24h) so a long `time_budget_min` doesn't trigger Arq's default 5-min timeout. `run_trial`'s timeout stays at default (per-trial scope). `generate_digest` keeps default for now (stub returns instantly). |
| `backend/app/db/session.py` | If `_install_state_guard_listener` not already wired in Story 1.3 — sanity-check it's installed. (No-op if Story 1.3 already landed.) |

**Key interface**

```python
# backend/workers/orchestrator.py
import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import optuna
import structlog
from arq.connections import ArqRedis, create_pool, RedisSettings
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.settings import get_settings
from backend.app.db import repo
from backend.app.db.repo.trial import TrialsSummary, aggregate_trials_summary
from backend.app.db.session import get_session_factory
from backend.app.domain.study.search_space import SearchSpace, apply_search_space
from backend.app.eval.optuna_runtime import build_pruner, build_sampler, get_or_create_study
from backend.app.services import study_state

logger = structlog.get_logger(__name__)

_REPLENISH_TICK_S = 1.0
"""Spec §19 decision log: 1s replenishment cadence."""

_DRAIN_TIMEOUT_S = 30.0
"""Spec FR-4 cancel path: wait up to 30s for in-flight trials to terminate."""

_CONSECUTIVE_FAILURE_THRESHOLD = 5
"""Spec AC-5: study transitions to `failed` after 5 consecutive trial failures.
Counted as: the most recent 5 terminal trials (ordered by `optuna_trial_number`
DESC) are all `status='failed'`. Any non-failed trial in that window resets
the count."""


async def start_study(ctx: dict[str, Any], study_id: str) -> None:
    """Orchestrator job — see module docstring.

    Idempotent + restart-safe (FR-5): if called on an already-running study
    (resume path), skips the queued→running transition and replenishes from
    the current in-flight count.

    Failure surface:
      * Trial-level failures (per `infra_optuna_eval`'s `run_trial`) are
        absorbed — failed `trials` rows accumulate; the study continues.
      * After 5 consecutive failed trials, the orchestrator calls
        `fail_study` with `failed_reason="5 consecutive trial failures"`.
      * Orchestrator-internal `OperationalError` re-raises for Arq retry;
        a fresh `start_study` invocation resumes via the running-study path.
    """
    session_factory = get_session_factory()
    arq_pool: ArqRedis = ctx.get("arq_pool") or await create_pool(
        RedisSettings.from_dsn(get_settings().redis_url)
    )

    # **Short-lived sessions per tick** (C3-F2 cycle-3 fix). The original
    # draft wrapped the entire 24h-job in a single `async with session_factory()`
    # block, holding a checked-out connection across every `asyncio.sleep(1)`.
    # That exhausts the connection pool when N studies run concurrently.
    # We now open a fresh session per orchestrator step (entry transition,
    # each polling tick, each terminal transition) and close it before the
    # `asyncio.sleep`. The Postgres advisory lock used in the replenish-
    # section is `pg_try_advisory_xact_lock` — transaction-scoped, so the
    # commit/rollback at session close releases it automatically (no
    # explicit `pg_advisory_unlock` needed).

    # A. Entry transition — short session.
    # Three observable entry states:
    #   - queued       → transition to running (standard fresh start)
    #   - running      → idempotent (resume-after-restart path, FR-5)
    #   - cancelled    → user cancelled between POST /studies and the
    #                    job dispatch; orchestrator silently exits
    #                    (C2-F4 cycle-2 fix).
    #   - completed/failed → also possible after Arq retry; same exit.
    async with session_factory() as db:
        try:
            study = await study_state.start_study(db, study_id)
            await db.commit()
        except study_state.InvalidStateTransition:
            await db.rollback()
            current = await repo.get_study(db, study_id)
            logger.info(
                "orchestrator entry transition lost — study no longer queued",
                event_type="orchestrator_exit",
                final_status=current.status if current else "deleted",
            )
            return
        except study_state.StudyNotFound:
            logger.warning(
                "study deleted before start_study job ran",
                event_type="orchestrator_exit",
                final_status="deleted",
            )
            return

    # B. Initialize Optuna study using cached storage from worker on_startup.
    # No DB session needed — Optuna's RDBStorage uses its own sync engine.
    storage = ctx["optuna_storage"]
    sampler = build_sampler(study.config, seed=study.config.get("seed"))
    pruner = build_pruner(study.config)
    optuna_study = await asyncio.to_thread(
        get_or_create_study,
        storage=storage,
        optuna_study_name=study.optuna_study_name,
        direction=study.objective["direction"],
        sampler=sampler,
        pruner=pruner,
    )

    # C. Parse search_space once.
    space = SearchSpace.model_validate(study.search_space)

    # D. Polling loop — open a fresh session per tick (C3-F2 cycle-3).
    settings = get_settings()
    parallelism: int = study.config.get("parallelism", settings.studies_default_parallelism)

    while True:
        async with session_factory() as db:
            # 1. Fresh status read (cancel detection).
            current = await repo.get_study(db, study_id)
            if current is None or current.status != "running":
                if current is not None and current.status == "cancelled":
                    await _drain_in_flight(db, study_id, optuna_study)
                logger.info("orchestrator exit", event_type="orchestrator_exit", final_status=current.status if current else "deleted")
                return

            # 2. Trials summary (one query).
            summary = await aggregate_trials_summary(db, study_id)

            # 3. Stop conditions — each is evaluated only when its key
            # is present in `studies.config` (per F1 — the spec allows
            # either max_trials OR time_budget_min; at least one is
            # required by the StudyConfigSpec model_validator).
            terminal = summary.complete + summary.failed + summary.pruned
            max_trials = study.config.get("max_trials")
            if max_trials is not None and terminal >= max_trials:
                await _stop(db, arq_pool, study_id, summary, reason="max_trials_reached")
                return
            time_budget_min = study.config.get("time_budget_min")
            if time_budget_min is not None:
                elapsed = datetime.now(UTC) - (current.started_at or datetime.now(UTC))
                if elapsed >= timedelta(minutes=time_budget_min):
                    await _stop(db, arq_pool, study_id, summary, reason="time_budget_exceeded")
                    return

            # 4. Consecutive-failure detection (AC-5). `fail_study` already
            # wraps its mutation in `_authorize_status_mutation` (Story 1.3) —
            # no extra wrapper needed here (F4).
            if await _last_n_all_failed(db, study_id, n=_CONSECUTIVE_FAILURE_THRESHOLD):
                try:
                    await study_state.fail_study(
                        db, study_id, failed_reason="5 consecutive trial failures"
                    )
                    await db.commit()
                    logger.warning(
                        "study failed",
                        event_type="stop_condition_fired",
                        reason="consecutive_failures",
                    )
                except study_state.InvalidStateTransition:
                    # Spec §11 cancel-race tolerance: user may have cancelled
                    # the study between our status read and our transition.
                    # The cancel commit wins; orchestrator silently exits (F5).
                    await db.rollback()
                    logger.info(
                        "consecutive-failure transition lost race to a "
                        "concurrent state change; exiting orchestrator loop",
                        event_type="orchestrator_race_lost",
                    )
                return
            # (end of `async with session_factory()` context — session
            # closes BEFORE the sleep and replenishment block. The
            # replenishment block opens its OWN short session so the
            # advisory-xact-lock + ask + enqueue all run in one
            # transaction that commits when the session closes.)

        # 5. Replenish open slots — protected by a Postgres advisory
        # **xact-scoped** lock keyed by study_id (C2-F1 + C3-F2 cycle-3:
        # transaction-scoped so commit/rollback releases automatically).
        # Two concurrent orchestrator processes on the same study MUST NOT
        # both observe the same in-flight count and both `ask()`. The
        # advisory xact-lock serializes the count + ask block per study;
        # losers skip the tick and retry in 1s.
        async with session_factory() as db:
            async with _try_replenish_xact_lock(db, study_id) as got_lock:
                if got_lock:
                    in_flight_count = await _count_in_flight(db, study_id, optuna_study)
                    total_allocated = await asyncio.to_thread(lambda: len(optuna_study.trials))
                    slots_open = parallelism - in_flight_count
                    if max_trials is not None:
                        slots_open = min(slots_open, max_trials - total_allocated)
                    for _ in range(max(0, slots_open)):
                        trial = await asyncio.to_thread(optuna_study.ask)
                        await asyncio.to_thread(apply_search_space, trial, space)
                        await arq_pool.enqueue_job("run_trial", study_id, trial.number)
                        logger.info(
                            "trial replenished",
                            event_type="trial_replenished",
                            optuna_trial_number=trial.number,
                        )
                    # Explicit commit so the xact-lock releases promptly.
                    await db.commit()
                else:
                    logger.debug(
                        "replenish lock held by another orchestrator process; "
                        "skipping tick (will retry in 1s)",
                        event_type="replenish_lock_contention",
                    )

        await asyncio.sleep(_REPLENISH_TICK_S)


async def _last_n_all_failed(db: AsyncSession, study_id: str, *, n: int) -> bool:
    """Per AC-5: returns True iff the N most recent terminal trials (by
    `optuna_trial_number DESC`) are ALL `status='failed'`. If fewer than N
    terminal trials exist, returns False (insufficient signal).

    SQL: ``SELECT status FROM trials WHERE study_id = :id ORDER BY
    optuna_trial_number DESC LIMIT :n``; return True iff len == n AND all
    rows have status == 'failed'. Non-failed trials in that window reset
    the streak by definition."""
    ...

async def _count_in_flight(
    db: AsyncSession, study_id: str, optuna_study: optuna.Study
) -> int:
    """In-flight = Optuna trials currently in RUNNING or WAITING state.

    **Why Optuna, not app rows** (F6 cycle-1 fix): app ``trials`` rows are
    written by ``run_trial`` only AT terminal state. Between ``orchestrator
    enqueues run_trial(study_id, n)`` and ``run_trial commits the trials
    INSERT``, no app row exists. Counting "0 in-flight" from app rows would
    cause the polling loop (and especially the resume-after-restart path)
    to re-enqueue another full ``parallelism`` batch on top of the already-
    in-flight ones, exceeding the operator's parallelism budget.

    Optuna's ``study.trials`` (synced from RDB) is the authoritative list
    of allocated trials with state. ``TrialState.RUNNING`` covers
    ``ask()``-then-not-yet-tell()'d; ``WAITING`` covers ``ask()``-allocated
    but no worker has loaded it yet.
    """
    # Sync call — wrap in to_thread by the caller. This helper is invoked
    # via `await asyncio.to_thread(_count_in_flight_sync, ...)` from the
    # async polling loop, OR the impl can keep it async and use to_thread
    # internally. The actual implementation does the latter for clarity.
    def _sync_count() -> int:
        running = sum(1 for t in optuna_study.trials if t.state == optuna.trial.TrialState.RUNNING)
        waiting = sum(1 for t in optuna_study.trials if t.state == optuna.trial.TrialState.WAITING)
        return running + waiting
    return await asyncio.to_thread(_sync_count)

async def _stop(
    db: AsyncSession,
    arq_pool: ArqRedis,
    study_id: str,
    summary: TrialsSummary,
    *,
    reason: str,
) -> None:
    """Fires when a stop-condition is detected. Atomically completes the
    study AND creates the durable pending-proposal row in the same
    transaction; enqueues the digest job as a best-effort accelerator.

    **Atomic durable handoff** (C3-F1 cycle-3 fix): the pending proposal
    row MUST be inserted in the SAME transaction as `complete_study`'s
    status mutation. Otherwise a crash between commit and enqueue would
    leave a `completed` study with no pending-proposal marker — the
    digest would be silently lost. The Arq enqueue is now a fast-path
    accelerator only; `feat_digest_proposal` is required to also scan
    `proposals WHERE status='pending'` at boot to pick up any markers
    whose enqueue failed.

    **Cancel-race tolerance** (F5): wraps the transition in
    ``try/except InvalidStateTransition``. If the user cancelled the
    study between our last status read and now, the cancel commit wins
    and our complete_study raises — we swallow and log per spec §11
    "Cancel race".

    **Digest stub semantics** (F10 + C2-F3): `digest_stub.generate_digest`
    is **idempotent** — it SELECTs the pending proposal for the study
    and no-ops if present, INSERTs only if absent. So enqueueing twice
    (e.g. via Arq retry on transient failure) is harmless.
    """
    try:
        await study_state.complete_study(
            db,
            study_id,
            best_metric=summary.best_primary_metric,
            best_trial_id=summary.best_trial_id,
            stop_reason=reason,
        )
        # Atomic pending-proposal insert in the same transaction as the
        # completion (C3-F1). The proposal row IS the durable handoff —
        # the Arq enqueue below is just a latency optimization.
        study = await repo.get_study(db, study_id)  # re-read for cluster_id + template_id
        if study is not None:
            await repo.create_proposal(
                db,
                id=str(uuid_utils.uuid7()),
                study_id=study_id,
                cluster_id=study.cluster_id,
                template_id=study.template_id,
                config_diff={},
                metric_delta={},
                status="pending",
            )
        await db.commit()
    except study_state.InvalidStateTransition:
        await db.rollback()
        logger.info(
            "stop-condition transition lost race to a concurrent state "
            "change (likely a user cancel); exiting orchestrator loop",
            event_type="orchestrator_race_lost",
            attempted_reason=reason,
        )
        return
    # Best-effort accelerator — failure here is non-fatal (the proposal
    # row above is the durable marker).
    try:
        await arq_pool.enqueue_job("generate_digest", study_id)
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning(
            "digest job enqueue failed; pending proposal row will be "
            "picked up by feat_digest_proposal's boot-time scan",
            event_type="digest_enqueue_failed",
            error=str(exc),
        )
    logger.info(
        "stop condition fired",
        event_type="stop_condition_fired",
        reason=reason,
        best_metric=summary.best_primary_metric,
    )

@asynccontextmanager
async def _try_replenish_xact_lock(
    db: AsyncSession, study_id: str
) -> AsyncIterator[bool]:
    """Try to acquire a Postgres **transaction-scoped** advisory lock
    keyed by ``study_id`` (C3-F2 cycle-3 fix — xact-scoped releases on
    commit/rollback automatically; no need for an explicit
    ``pg_advisory_unlock`` that could leak if the session closes early).

    Yields ``True`` if the lock was acquired (caller has exclusive access to
    the replenish-section for this study), ``False`` otherwise. The caller
    is expected to ``await db.commit()`` shortly after — the lock is
    held only for the duration of the current transaction.

    **Why a try-lock, not a blocking lock**: two concurrent orchestrators
    on the same study is a recoverable condition (spec §11). The loser just
    skips this 1s tick — no harm done. A blocking lock would risk both
    processes piling up on the same study and deadlocking against each
    other on different studies if both held multiple locks.

    The lock key is the first 8 bytes of ``hashlib.blake2b(study_id.encode(),
    digest_size=8).digest()`` interpreted as a signed 64-bit int — Postgres
    advisory locks take a single bigint key. Collisions are astronomically
    rare (UUIDv7 input).
    """
    import hashlib
    from sqlalchemy import text

    lock_key = int.from_bytes(
        hashlib.blake2b(study_id.encode(), digest_size=8).digest(),
        byteorder="big",
        signed=True,
    )
    acquired = (
        await db.execute(
            text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": lock_key}
        )
    ).scalar_one()
    yield bool(acquired)
    # No explicit unlock — pg_try_advisory_xact_lock is scoped to the
    # current transaction; commit/rollback (called by the orchestrator
    # immediately after this block, or by `async with session_factory()`
    # exit on raise) releases it.


async def _drain_in_flight(
    db: AsyncSession, study_id: str, optuna_study: optuna.Study
) -> None:
    """Wait up to _DRAIN_TIMEOUT_S for every in-flight Optuna trial to
    terminate (F7 — concrete algorithm).

    **Algorithm:**
    1. Snapshot the currently-RUNNING/WAITING Optuna trial numbers.
    2. Poll every 1s: re-read `optuna_study.trials` (sync, via to_thread);
       count how many of the snapshotted numbers are now in a terminal
       Optuna state (COMPLETE, FAIL, PRUNED).
    3. Return when all snapshotted numbers are terminal, OR when 30s
       elapses (`asyncio.wait_for` outer guard).

    The orchestrator does NOT actively cancel in-flight workers — `run_trial`
    is brief (~200ms-2s per trial) and completes naturally. The drain just
    waits for natural termination so the cancel state isn't observed
    mid-trial-write.
    """
    snapshot_numbers = {
        t.number for t in optuna_study.trials
        if t.state in (optuna.trial.TrialState.RUNNING, optuna.trial.TrialState.WAITING)
    }
    deadline = asyncio.get_event_loop().time() + _DRAIN_TIMEOUT_S

    while True:
        terminal_now = await asyncio.to_thread(
            lambda: {
                t.number for t in optuna_study.trials
                if t.number in snapshot_numbers and t.state.is_finished()
            }
        )
        if terminal_now >= snapshot_numbers:
            return
        if asyncio.get_event_loop().time() >= deadline:
            logger.warning(
                "drain timed out — some in-flight trials still RUNNING",
                event_type="drain_timeout",
                still_pending=sorted(snapshot_numbers - terminal_now),
            )
            return
        await asyncio.sleep(1.0)
```

**Tasks**

1. Implement `start_study` and helpers per the interface above.
2. Wire `start_study` (and `resume_study` from Story 2.3) into `WorkerSettings.functions` with `job_timeout=86400`.
3. Author `test_study_lifecycle.py` integration tests covering:
   - **AC-1** — POST a complete-study setup; poll `/studies/{id}` until `status='completed'`; assert `trials_summary.complete == max_trials`, `best_metric` non-null, `best_trial_id` non-null. Use a monkeypatched `qrels_loader` to provide synthetic judgments.
   - **AC-2** — same setup but `max_trials=10000, time_budget_min=0.05` (3s budget); assert `status='completed'` within 30s and `trials_summary.complete > 0` and `< 10000`.
   - **AC-5** — start a study against an unreachable cluster (or one whose adapter raises `ClusterUnreachableError` via monkeypatch); assert 5 consecutive failed trials accumulate, then `status='failed'` with `failed_reason="5 consecutive trial failures"`.
   - **AC-6** — open a session via `get_db`, load a Study row, set `study.status = "completed"` directly; assert `db.flush()` raises `StudyStateProtectionError`.
   - **AC-10** — after AC-1 completes, hit `GET /studies/{id}/trials?sort=primary_metric_desc&limit=10` and assert the top-10 are sorted descending by `primary_metric`.
4. Author `fixtures/study_factories.py` with helpers: `seed_study(db, *, cluster_id, max_trials, parallelism, time_budget_min, search_space)` + `monkeypatch_qrels(monkeypatch, judgment_list_id, qrels_dict)`.

**DoD**
- All 5 ACs covered by passing integration tests.
- `make test-integration` green for `test_study_lifecycle.py`.
- Orchestrator logs include `event_type=trial_replenished` and `event_type=stop_condition_fired` entries (verified via `caplog`).
- `make lint typecheck` green.

---

### Story 2.2 — Cancel-during-running path (service-layer + drain) (AC-3 partial)

**Outcome:** The service-layer half of AC-3: `services.study_state.cancel_study` flips `studies.status` to `cancelled`; the orchestrator's polling loop detects the change on its next 1s tick, calls `_drain_in_flight` (waits up to 30s for in-flight `run_trial` jobs to complete naturally), then exits. **The HTTP 409 second-cancel surface is verified in Story 3.5's error-code tests** (Epic 3) — Story 2.2 owns the orchestrator-drain half because the cancel endpoint doesn't exist yet at Epic 2 time (F9 cycle-1 fix: split per the original sequencing-contradiction note).

**New files**

| File | Purpose |
|---|---|
| `backend/tests/integration/test_study_cancel.py` | AC-3 (service-layer half) — orchestrator detects cancel + drains |

**Modified files**

| File | Change |
|---|---|
| (none — cancel uses `cancel_study` from Story 1.3 + the orchestrator's status-poll loop from Story 2.1) | — |

**Tasks**

1. Author `test_study_cancel.py`:
   - Seed a study with `max_trials=1000, parallelism=4`.
   - Enqueue `start_study` (in-process via Arq's `start_jobs` test pattern, or by calling `start_study` directly via `asyncio.create_task`).
   - Wait until `status='running'` and ≥1 trial has accumulated.
   - Call `services.study_state.cancel_study(db, study_id)` directly (the HTTP cancel surface ships in Story 3.3 — this test verifies the service-layer + orchestrator contract without HTTP overhead).
   - Within 30s, assert `status='cancelled'` and the orchestrator task has exited.
   - Assert no `failed` rows appeared from the cancel itself.
   - Assert `_drain_in_flight` was reached (verify via `caplog` → `event_type=orchestrator_exit` log entry).
2. **The HTTP 409 "second cancel" assertion** lives in Story 3.5's `test_studies_error_codes.py::test_invalid_state_transition` (one of the 12 error-code tests). That test seeds a cancelled study + POSTs `/cancel` → asserts 409 + `error_code=INVALID_STATE_TRANSITION`.

**DoD**
- AC-3 service-layer half covered by `test_study_cancel.py` (passes).
- `make test-integration -k cancel` green.
- HTTP 409 surface deferred to Story 3.5 (Epic 3) per F9 sequencing fix.

---

### Story 2.3 — Resume-after-restart (`resume_study` + `WorkerSettings.on_startup` sweep) (FR-5, AC-4)

**Outcome:** When the Arq worker process restarts, `WorkerSettings.on_startup` (extended from `infra_optuna_eval`) sweeps `SELECT id FROM studies WHERE status = 'running'` and enqueues `resume_study(study_id)` for each. `resume_study` is a thin wrapper that calls `start_study(ctx, study_id)` — `start_study` is idempotent on the running state (Story 1.3 + 2.1 design). New `run_trial` jobs pick up from where they left off (Optuna's RDB has the full trial history).

**New files**

| File | Purpose |
|---|---|
| `backend/tests/integration/test_study_resume.py` | AC-4 — orchestrator restart mid-study |
| `backend/tests/integration/_subprocess_helpers/orchestrator_restart.py` | Subprocess fixture: spawn an Arq worker via `arq backend.workers.all.WorkerSettings`, run for N seconds, SIGTERM, restart |

**Modified files**

| File | Change |
|---|---|
| `backend/workers/orchestrator.py` | Add `resume_study(ctx, study_id)` (a 2-line wrapper that calls `start_study`) |
| `backend/workers/all.py` | Extend `on_startup` to call `_enqueue_resume_jobs(ctx)` after the existing Optuna storage init; the helper enqueues `resume_study` for every currently-running study. Adds `resume_study` to `functions` list. |

**Key interface**

```python
# backend/workers/orchestrator.py — addition
async def resume_study(ctx: dict[str, Any], study_id: str) -> None:
    """Resume an orchestrator loop after worker restart. Thin wrapper —
    `start_study` already handles the resume path (Story 1.3 makes the
    queued→running transition idempotent on running)."""
    await start_study(ctx, study_id)


# backend/workers/all.py — extend on_startup
async def on_startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    ctx["optuna_storage"] = await asyncio.to_thread(build_storage, settings.database_url)
    # NEW: resume any studies that were running when the worker died.
    arq_pool: ArqRedis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    ctx["arq_pool"] = arq_pool
    async with get_session_factory()() as db:
        running_ids = await repo.list_running_study_ids(db)
    for sid in running_ids:
        await arq_pool.enqueue_job("resume_study", sid)
        logger.info("study queued for resume", event_type="resume_enqueued", study_id=sid)
```

`repo.list_running_study_ids(db)` is a small repo addition: `SELECT id FROM studies WHERE status = 'running'`. Add to `backend/app/db/repo/study.py` alongside the Story 1.4 additions (one-line addition).

**Tasks**

1. Add `resume_study` wrapper in `orchestrator.py`.
2. Extend `on_startup` in `workers/all.py` with the resume sweep. Add `arq_pool` to `ctx` so `start_study` reuses the same pool.
3. Add `repo.list_running_study_ids` (one-liner — assign to Story 1.4 if convenient, but acceptable here).
4. Author the subprocess helper that runs an Arq worker for N seconds then SIGTERMs it.
5. Author `test_study_resume.py` covering AC-4:
   - Seed a running study with `max_trials=100, parallelism=4`.
   - Start the orchestrator subprocess; wait until 20 trials complete.
   - SIGTERM the subprocess.
   - Restart the subprocess.
   - Within 30s of restart, assert `status='running'` (the on_startup sweep re-enqueued) and new trials accumulate from optuna_trial_number 21+.
   - Eventually study completes at trial 100.

**DoD**
- AC-4 covered by passing integration test.
- `make test-integration -k resume` green.
- `arq backend.workers.all.WorkerSettings` continues to boot cleanly with both `run_trial` and `start_study`/`resume_study` registered.

---

### Epic 2 phase gate (hard stop — do not proceed to Epic 3)

- [ ] Stories 2.1, 2.2, 2.3 complete with their per-story DoD ticked.
- [ ] AC-1, AC-2, AC-3 (service-layer half — orchestrator detects cancel + drains), AC-4, AC-5, AC-6, AC-10 covered by integration tests; all green. (AC-3 HTTP half — 409 on second cancel — lands in Epic 3 Story 3.5 per F9 cycle-1 sequencing fix.)
- [ ] `make test-unit test-integration` green.
- [ ] `arq backend.workers.all.WorkerSettings` boots without warnings (4 registered jobs: `run_trial` + `start_study` + `resume_study` + `generate_digest` stub).
- [ ] **GPT-5.5 phase-gate diff review** per `impl-execute` Step 4 on the cumulative Epic 1+2 diff.

---

## Epic 3 — API endpoints (Stories 3.1–3.5)

### Story 3.1 — Query-template endpoints (POST + GET-list + GET-detail) (FR-2)

**Outcome:** 3 endpoints under `/api/v1/query-templates` ship, using the Story 1.2 validator for create-time `body` + `declared_params` checks. Errors mapped to spec §7.5: `INVALID_TEMPLATE_SYNTAX`, `UNDECLARED_PARAM_USED`, `DECLARED_PARAM_UNUSED`, `TEMPLATE_NAME_TAKEN`, `TEMPLATE_NOT_FOUND`.

**New files**

| File | Purpose |
|---|---|
| `backend/app/api/v1/query_templates.py` | Router with 3 endpoints + reusable `_err` from `clusters.py` pattern |

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/schemas.py` | Add `CreateQueryTemplateRequest`, `QueryTemplateDetail`, `QueryTemplateListResponse`, `QueryTemplateSummary` Pydantic models |
| `backend/app/main.py` | `app.include_router(query_templates_router.router, prefix="/api/v1")` |

**Endpoints**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `POST` | `/api/v1/query-templates` | `{name, engine_type, body, declared_params, parent_id?}` | `201` `QueryTemplateDetail` | `VALIDATION_ERROR` (422), `INVALID_TEMPLATE_SYNTAX` (400), `UNDECLARED_PARAM_USED` (400), `DECLARED_PARAM_UNUSED` (400), `TEMPLATE_NAME_TAKEN` (409) |
| `GET` | `/api/v1/query-templates?cursor=&limit=&since=` | — | `200` `QueryTemplateListResponse` + `X-Total-Count` header | (none) |
| `GET` | `/api/v1/query-templates/{id}` | — | `200` `QueryTemplateDetail` | `TEMPLATE_NOT_FOUND` (404) |

All endpoints follow `clusters.py`'s envelope-via-`HTTPException` pattern.

**Pydantic schemas**

```python
# backend/app/api/v1/schemas.py — additions
from typing import Literal

# Values must match backend/app/adapters/elastic.py SUPPORTED_ENGINE_TYPES.
EngineTypeWire = Literal["elasticsearch", "opensearch"]

class CreateQueryTemplateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    engine_type: EngineTypeWire
    body: str = Field(min_length=1)
    declared_params: dict[str, str] = Field(default_factory=dict)
    parent_id: str | None = None

class QueryTemplateDetail(BaseModel):
    id: str
    name: str
    engine_type: EngineTypeWire
    body: str
    declared_params: dict[str, str]
    version: int
    parent_id: str | None
    created_at: datetime

class QueryTemplateSummary(BaseModel):
    id: str
    name: str
    engine_type: EngineTypeWire
    version: int
    created_at: datetime

class QueryTemplateListResponse(BaseModel):
    data: list[QueryTemplateSummary]
    next_cursor: str | None
    has_more: bool
```

**Tasks**

1. Create the router module + register in `main.py`.
2. Add the 4 schema classes to `schemas.py`.
3. In the POST handler: parse the body; call `validate_template_body(body, declared_params)`; catch the 3 domain exceptions and translate via `_err` to the documented error codes; UUIDv7 the ID; call `repo.create_query_template`; commit. On `IntegrityError` from the `(name, version)` UNIQUE constraint, translate to `TEMPLATE_NAME_TAKEN` (409).
4. In the GET-list handler: decode cursor; call `repo.list_query_templates` + `repo.count_query_templates`; set `X-Total-Count`; return.
5. In the GET-detail handler: call `repo.get_query_template`; 404 if None.

**DoD**
- All 3 endpoints respond with the documented shape (contract tests in Story 3.5 enforce).
- AC-7 (`POST` with `{{ os.system('rm -rf /') }}` → 400 `INVALID_TEMPLATE_SYNTAX`) covered by integration smoke included in this story's local test.
- `make test-integration` green for the query-templates path.

---

### Story 3.2 — Query-set endpoints + bulk queries upload (POST + GET + GET-detail + POST-queries with CSV/JSON) (FR-3)

**Outcome:** 4 endpoints under `/api/v1/query-sets` ship. `POST /api/v1/query-sets/{id}/queries` accepts both JSON (`application/json`) and CSV (`text/csv`) per AC-8. AC-8 verified.

**New files**

| File | Purpose |
|---|---|
| `backend/app/api/v1/query_sets.py` | Router with 4 endpoints |
| `backend/app/domain/study/csv_parser.py` | Pure CSV → row-dicts parser with strict validation (header schema, row count cap at 10K for MVP1) |
| `backend/tests/integration/test_csv_upload.py` | AC-8 |
| `backend/tests/unit/domain/test_csv_parser.py` | CSV header validation + bad-row rejection |

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/schemas.py` | Add `CreateQuerySetRequest`, `QuerySetDetail` (incl. `query_count`), `QuerySetSummary`, `QuerySetListResponse`, `BulkQueriesJsonRequest`, `BulkQueriesResponse` |
| `backend/app/main.py` | Register the router |

**Endpoints**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `POST` | `/api/v1/query-sets` | `{name, description?, cluster_id}` — `cluster_id` is **required** because Phase 1's shipped schema has `query_sets.cluster_id NOT NULL` (`migrations/versions/0003_study_lifecycle_schema.py:79` + `backend/app/db/models/query_set.py:26`); Phase 2 doesn't add migrations. Spec FR-3 wording `cluster_id?` is a documentation drift — see [`chore_spec_query_set_cluster_id_drift`](../chore_spec_query_set_cluster_id_drift/idea.md) for the spec patch follow-up. | `201` `QuerySetDetail` | `VALIDATION_ERROR`, `CLUSTER_NOT_FOUND`, `QUERY_SET_NAME_TAKEN` |
| `GET` | `/api/v1/query-sets?cursor=&limit=&since=` | — | `200` `QuerySetListResponse` + `X-Total-Count` | (none) |
| `GET` | `/api/v1/query-sets/{id}` | — | `200` `QuerySetDetail` (incl. `query_count`) | `QUERY_SET_NOT_FOUND` |
| `POST` | `/api/v1/query-sets/{id}/queries` | JSON `{queries: [...]}` OR `Content-Type: text/csv` body | `201` `BulkQueriesResponse {added: N}` | `QUERY_SET_NOT_FOUND`, `INVALID_CSV` (400), `VALIDATION_ERROR` |

**Key interface**

```python
# backend/app/domain/study/csv_parser.py
import csv
from io import StringIO
from typing import Any

class InvalidCsvError(ValueError):
    """Router → 400 INVALID_CSV. Used for header mismatch, row count exceeded,
    or per-row validation failure."""

_REQUIRED_COLUMNS: frozenset[str] = frozenset({"query_text"})
_OPTIONAL_COLUMNS: frozenset[str] = frozenset({"reference_answer"})
_MAX_ROWS: int = 10_000

def parse_queries_csv(body: bytes) -> list[dict[str, Any]]:
    """Parse a UTF-8 CSV body into row dicts.

    Required header columns: `query_text`. Optional: `reference_answer`.
    Any additional columns are captured into a per-row `metadata` dict
    (preserves spec §7 FR-3 "metadata as additional columns").

    Row count cap: 10,000 rows per upload — over the cap raises `InvalidCsvError`.
    """
    try:
        reader = csv.DictReader(StringIO(body.decode("utf-8")))
    except UnicodeDecodeError as exc:
        raise InvalidCsvError(f"csv body is not valid UTF-8: {exc}") from exc

    if reader.fieldnames is None:
        raise InvalidCsvError("csv body has no header row")

    headers = set(reader.fieldnames)
    missing = _REQUIRED_COLUMNS - headers
    if missing:
        raise InvalidCsvError(f"csv missing required column(s): {sorted(missing)}")

    rows: list[dict[str, Any]] = []
    for i, row in enumerate(reader, start=2):  # row 1 was the header
        if i > _MAX_ROWS + 1:
            raise InvalidCsvError(f"csv exceeds max row count ({_MAX_ROWS})")
        if not row.get("query_text"):
            raise InvalidCsvError(f"row {i}: empty `query_text`")
        metadata = {
            k: v for k, v in row.items()
            if k not in _REQUIRED_COLUMNS and k not in _OPTIONAL_COLUMNS and v
        }
        rows.append({
            "query_text": row["query_text"],
            "reference_answer": row.get("reference_answer") or None,
            "query_metadata": metadata or None,
        })
    return rows
```

**Tasks**

1. Create router + `csv_parser.py` + schemas.
2. In the POST-queries handler: dispatch on `Content-Type` header. `application/json` → parse via Pydantic; `text/csv` → call `parse_queries_csv(await request.body())`. Either path calls `repo.bulk_create_queries`.
3. In `parse_queries_csv`: per the interface above. Tests in `test_csv_parser.py` cover all error paths.
4. Author `test_csv_upload.py` (AC-8): POST a 50-row CSV; assert `201` + `{added: 50}`; GET `/query-sets/{id}` and assert `query_count: 50`.

**DoD**
- AC-8 covered by passing integration test.
- 7 unit tests for `csv_parser.py` (happy path, missing header, bad UTF-8, exceeded row cap, missing query_text, extra columns → metadata, no header row).
- `make test-unit test-integration` green for query-sets path.

---

### Story 3.3 — Study endpoints (POST + GET-list + GET-detail + POST-cancel) (FR-1)

**Outcome:** 4 endpoints under `/api/v1/studies` ship. `POST` validates `search_space` via Story 1.1's `SearchSpace.model_validate(...)`, generates UUIDv7 for both `id` and `optuna_study_name`, inserts the study row with `status='queued'`, and enqueues `start_study(study_id)` to the Arq queue. `POST /cancel` uses `services.study_state.cancel_study`. AC-1 (create + run + complete) covered end-to-end through Story 2.1's test.

**New files**

| File | Purpose |
|---|---|
| `backend/app/api/v1/studies.py` | Router with 4 study endpoints + 1 trials endpoint (Story 3.4 owns the trials handler but co-locates the router file) |
| `backend/tests/integration/test_pagination.py` | AC-9 — 75 studies, paginate in 50+25 |

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/schemas.py` | Add `CreateStudyRequest`, `StudyDetail` (incl. `trials_summary`), `StudySummary`, `StudyListResponse`, `TrialsSummaryShape`, `StudyStatusWire = Literal[...]`, `ObjectiveSpec`, `StudyConfigSpec` |
| `backend/app/main.py` | Register the studies router |

**Endpoints**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `POST` | `/api/v1/studies` | `CreateStudyRequest` | `201` `StudyDetail` (status=`queued`) | `VALIDATION_ERROR`, `CLUSTER_NOT_FOUND`, `TEMPLATE_NOT_FOUND`, `QUERY_SET_NOT_FOUND`, `JUDGMENT_LIST_NOT_FOUND`, `INVALID_SEARCH_SPACE` (400) |
| `GET` | `/api/v1/studies?status=&cursor=&limit=&since=` | — | `200` `StudyListResponse` + `X-Total-Count` | (none) |
| `GET` | `/api/v1/studies/{id}` | — | `200` `StudyDetail` (incl. `trials_summary`) | `STUDY_NOT_FOUND` |
| `POST` | `/api/v1/studies/{id}/cancel` | — | `200` `StudyDetail` | `STUDY_NOT_FOUND`, `INVALID_STATE_TRANSITION` (409) |

**Pydantic schemas**

```python
# backend/app/api/v1/schemas.py — additions
from typing import Literal

# Values must match backend/app/db/models/study.py CHECK constraint
# AND backend/app/db/repo/study.py StudyStatusFilter Literal.
StudyStatusWire = Literal["queued", "running", "completed", "cancelled", "failed"]

# Values must match backend/app/eval/scoring.py SUPPORTED_METRICS frozenset.
ObjectiveMetric = Literal["ndcg", "map", "precision", "recall", "mrr", "err"]

# Values must match backend/app/eval/scoring.py SUPPORTED_K_VALUES frozenset.
ObjectiveK = Literal[1, 3, 5, 10, 20, 50, 100]

# Values must match backend/app/services/study_state.py + spec §7.4.
ObjectiveDirection = Literal["maximize", "minimize"]

# Values must match backend/app/eval/types.py SamplerKind Literal.
SamplerKind = Literal["tpe", "random"]

# Values must match backend/app/eval/types.py PrunerKind Literal.
PrunerKind = Literal["median", "none"]


class ObjectiveSpec(BaseModel):
    metric: ObjectiveMetric
    k: ObjectiveK | None = None  # required for ndcg/precision/recall, optional for map, ignored for mrr/err
    direction: ObjectiveDirection = "maximize"


class StudyConfigSpec(BaseModel):
    """`studies.config` JSONB — fields surfaced to the operator at study create.

    Both stop-condition keys (`max_trials`, `time_budget_min`) are individually
    optional but the model_validator requires **at least one** — a study with
    neither stop condition would run forever. This matches the spec's "stop
    conditions: `trial_count >= max_trials` OR `time_budget_min` elapsed" wording
    (FR-4) and the AC payloads:
      * AC-1 sets `{max_trials: 20, parallelism: 4}` (no time budget).
      * AC-2 sets `{max_trials: 10000, time_budget_min: 1, parallelism: 4}`.

    `parallelism` and `trial_timeout_s` are optional in the API payload; when
    absent the worker reads `Settings.studies_default_parallelism` and
    `Settings.studies_default_timeout_s` at job time. The API layer does NOT
    materialize these into the stored row — preserves `infra_optuna_eval`'s
    pruner key-presence contract.
    """
    max_trials: int | None = Field(default=None, ge=1, le=100_000)
    time_budget_min: float | None = Field(default=None, gt=0)
    parallelism: int | None = Field(default=None, ge=1, le=64)
    trial_timeout_s: int | None = Field(default=None, ge=5, le=3600)
    sampler: SamplerKind | None = None
    pruner: PrunerKind | None = None
    seed: int | None = None
    secondary_metrics: list[str] | None = None

    @model_validator(mode="after")
    def _require_one_stop_condition(self) -> "StudyConfigSpec":
        if self.max_trials is None and self.time_budget_min is None:
            raise ValueError(
                "studies.config must specify at least one of "
                "`max_trials` or `time_budget_min` — otherwise the study "
                "has no terminating stop condition"
            )
        return self


class CreateStudyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    cluster_id: str
    target: str = Field(min_length=1, max_length=256)
    template_id: str
    query_set_id: str
    judgment_list_id: str
    search_space: dict[str, Any]  # validated post-parse via SearchSpace.model_validate
    objective: ObjectiveSpec
    config: StudyConfigSpec


class TrialsSummaryShape(BaseModel):
    total: int
    complete: int
    failed: int
    pruned: int
    best_primary_metric: float | None


class StudyDetail(BaseModel):
    id: str
    name: str
    cluster_id: str
    target: str
    template_id: str
    query_set_id: str
    judgment_list_id: str
    search_space: dict[str, Any]
    objective: dict[str, Any]
    config: dict[str, Any]
    status: StudyStatusWire
    failed_reason: str | None
    optuna_study_name: str
    parent_study_id: str | None
    baseline_metric: float | None
    best_metric: float | None
    best_trial_id: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    trials_summary: TrialsSummaryShape


class StudySummary(BaseModel):
    id: str
    name: str
    cluster_id: str
    status: StudyStatusWire
    best_metric: float | None
    created_at: datetime
    completed_at: datetime | None


class StudyListResponse(BaseModel):
    data: list[StudySummary]
    next_cursor: str | None
    has_more: bool
```

**Tasks**

1. Create `backend/app/api/v1/studies.py` with the 4 endpoints (Story 3.4 adds a 5th).
2. POST handler:
   - Parse body → validate search_space via `SearchSpace.model_validate(body.search_space)` (catch `ValidationError` → `INVALID_SEARCH_SPACE`).
   - Look up cluster/template/query_set/judgment_list — each absent target → its `*_NOT_FOUND` code.
   - **Judgment/query-set consistency check** (F12 cycle-1 + spec §11 "Edge/error flows"): verify `judgment_list.query_set_id == request.query_set_id`. On mismatch raise 422 `VALIDATION_ERROR` with message `judgment_list query_set_id does not match study query_set_id`. Tested in Story 3.5's `test_studies_error_codes.py::test_validation_error_judgment_query_set_mismatch`.
   - **Serialize `config` with `exclude_none=True, exclude_unset=True`** (C3-F1 cycle-3 fix). Without this, `StudyConfigSpec`'s `Optional[...] = None` fields would persist as JSON null keys, violating the key-omission contract documented in §0 Planning principles + Story 1.5 (the worker reads `Settings.studies_default_parallelism` only when the key is ABSENT — a null-valued key would short-circuit the fallback). Concretely: `config_payload = body.config.model_dump(exclude_none=True, exclude_unset=True)` before INSERT.
   - UUIDv7 study ID; INSERT with `status='queued'` and `optuna_study_name=str(study_id)`; enqueue `start_study(study_id)` via an `ArqRedis` pool dependency; return `StudyDetail`.
3. GET-list handler: cursor + status filter + since; emit `X-Total-Count`. Mirror `clusters.py:list_clusters`.
4. GET-detail handler: load study + `aggregate_trials_summary`; return `StudyDetail` with summary.
5. POST-cancel handler: call `services.study_state.cancel_study`; translate `InvalidStateTransition` → 409; return updated `StudyDetail`.
6. Add an `arq_pool` FastAPI dependency that creates a pool once per app lifespan (mirror `Redis.from_url` in `main.py:lifespan`).
7. Author `test_pagination.py` (AC-9 — expanded per F8 cycle-1 + the phase2_idea.md "12 combinations" mandate, then split per C2-F5 cycle-2 between Stories 3.3 and 3.4 because trials endpoint doesn't exist until 3.4):

   **Story 3.3 adds 9 methods** (studies + query-sets + query-templates × 3 behaviors):
   - **Studies** (`GET /studies`): (a) cursor pagination — 75 rows, paginate 50+25 with `has_more` correct; (b) `?since=<iso8601>` filter — half the rows created before T, GET with `since=T` returns only after-T; (c) `X-Total-Count` header — matches filter count, ignoring pagination.
   - **Query-sets** (`GET /query-sets`): same 3 behaviors.
   - **Query-templates** (`GET /query-templates`): same 3 behaviors.

   **Story 3.4 adds 3 methods** (trials × 3 behaviors — owns the trials endpoint):
   - **Trials** (`GET /studies/{id}/trials`): same 3 behaviors via `list_trials_paginated` + `count_trials` with the F8 `since` arg.

**DoD**
- AC-1 (verified end-to-end through Story 2.1's lifecycle test) — POST returns `queued`, orchestrator picks up, study completes.
- AC-3 (verified through Story 2.2's cancel test) — POST cancel + 409 on second call.
- AC-9 covered by `test_pagination.py`.
- **Key-omission test** (C3-F1): POST `/studies` with `config: {max_trials: 20}` → assert the persisted `studies.config` dict has NO `parallelism`, `trial_timeout_s`, `sampler`, `pruner`, `seed`, or `secondary_metrics` keys (not just null values). Explicit `pruner: "none"` is preserved.
- `make test-integration` green for studies path.

---

### Story 3.4 — Trials list endpoint (`GET /api/v1/studies/{id}/trials`) (FR-6)

**Outcome:** `GET /api/v1/studies/{id}/trials` cursor-paginates trials with 5 sort variants. Uses Story 1.4's `list_trials_paginated`. AC-10 verified via Story 2.1's lifecycle test.

**New files**

| File | Purpose |
|---|---|
| (none — handler co-located in `studies.py` from Story 3.3) | — |

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/studies.py` | Add the trials handler |
| `backend/app/api/v1/schemas.py` | Add `TrialDetail`, `TrialListResponse`, `TrialSortKey = Literal[...]` |

**Endpoints**

| Method | Path | Query params | Success response | Error codes |
|---|---|---|---|---|
| `GET` | `/api/v1/studies/{id}/trials` | `cursor=&limit=&since=&sort=` | `200` `TrialListResponse` + `X-Total-Count` | `STUDY_NOT_FOUND`, `VALIDATION_ERROR` (bad sort value) |

**Pydantic schemas**

```python
# backend/app/api/v1/schemas.py — additions
from typing import Literal

# Values must match backend/app/db/repo/trial.py TrialSortKey Literal.
TrialSortKey = Literal[
    "primary_metric_desc",
    "primary_metric_asc",
    "created_at_desc",
    "created_at_asc",
    "optuna_trial_number_asc",
]

# Values must match backend/app/db/models/trial.py CHECK constraint
# (status enum from data-model.md).
TrialStatusWire = Literal["complete", "failed", "pruned"]


class TrialDetail(BaseModel):
    id: str
    study_id: str
    optuna_trial_number: int
    params: dict[str, Any]
    primary_metric: float | None
    metrics: dict[str, Any]
    duration_ms: int | None
    status: TrialStatusWire
    error: str | None
    started_at: datetime | None
    ended_at: datetime | None


class TrialListResponse(BaseModel):
    data: list[TrialDetail]
    next_cursor: str | None
    has_more: bool
```

**Tasks**

1. Add the trials handler in `studies.py`.
2. Handler: validate study exists (404 if not); decode cursor per `sort_key` shape; call `list_trials_paginated`; emit `X-Total-Count` via `count_trials`; return.
3. **Add 3 pagination tests to `test_pagination.py`** (C2-F5 cycle-2 split — Story 3.3 covers the other 9): cursor pagination on `/studies/{id}/trials`; `?since=` filter; `X-Total-Count` header. Use the trials seeded by AC-1's lifecycle test as the data source, or seed directly via `repo.create_trial`.

**DoD**
- AC-10 verified via Story 2.1's `test_study_lifecycle.py` (asserts `?sort=primary_metric_desc` ordering).
- AC-9 trials-coverage 3 methods added to `test_pagination.py` (cursor + since + X-Total-Count).
- `make test-integration -k trial_list` green.

---

### Story 3.5 — Contract tests + full error-code matrix

**Outcome:** Every endpoint shape verified against the OpenAPI schema; every error code in spec §7.5 (12 codes) verified to produce the documented HTTP status + envelope.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/contract/test_studies_api_contract.py` | OpenAPI shape assertions for all 12 endpoints + envelope shape for happy + error paths |
| `backend/tests/contract/test_studies_error_codes.py` | One test method per spec §7.5 error code (12 total) |

**Modified files**

| File | Change |
|---|---|
| (none — existing `test_error_codes.py` for the cluster surface stays untouched) | — |

**Tasks**

1. Author `test_studies_api_contract.py`:
   - For each of the 12 endpoints, send a valid request and assert `response.json()` validates against the OpenAPI schema for the route (use `app.openapi()`).
   - For each error case, assert response body has the `{detail: {error_code, message, retryable}}` shape.
2. Author `test_studies_error_codes.py`:
   - One `async def test_<code>(...)` per code in spec §7.5: `STUDY_NOT_FOUND` (404), `INVALID_STATE_TRANSITION` (409 — covers both "cancel a completed study" AND F9 "cancel an already-cancelled study" — AC-3 HTTP-half assertion), `INVALID_SEARCH_SPACE` (400), `TEMPLATE_NOT_FOUND` (404), `QUERY_SET_NOT_FOUND` (404), `JUDGMENT_LIST_NOT_FOUND` (404), `INVALID_TEMPLATE_SYNTAX` (400), `UNDECLARED_PARAM_USED` (400), `DECLARED_PARAM_UNUSED` (400), `TEMPLATE_NAME_TAKEN` (409), `QUERY_SET_NAME_TAKEN` (409), `INVALID_CSV` (400).
   - **Plus** F12 case: `test_validation_error_judgment_query_set_mismatch` — POST `/studies` with `judgment_list_id` whose `query_set_id` differs from request's `query_set_id` → 422 `VALIDATION_ERROR` with message naming the mismatch.
   - Each test triggers the documented condition + asserts the HTTP status + the envelope's `error_code` + `retryable` values.

**DoD**
- 12 contract tests + 12 error-code tests pass.
- `make test-contract` green.

---

### Epic 3 phase gate (hard stop — do not proceed to Epic 4)

- [ ] Stories 3.1, 3.2, 3.3, 3.4, 3.5 complete.
- [ ] All 12 endpoints respond per their documented shape.
- [ ] All 12 error codes from spec §7.5 produce the documented status + envelope.
- [ ] `make test-unit test-integration test-contract` green.
- [ ] `make lint typecheck` green.
- [ ] **GPT-5.5 phase-gate diff review** per `impl-execute` Step 4 on the cumulative Epic 1+2+3 diff.

---

## Epic 4 — Documentation + finalization (Story 4.1)

### Story 4.1 — Runbook + state.md/architecture.md/CLAUDE.md updates

**Outcome:** Operator-facing runbook lands; the three context files reflect Phase 2's shipped behavior; MVP1 user-story doc updates US-9/10/11/12 to "implemented".

**New files**

| File | Purpose |
|---|---|
| `docs/03_runbooks/study-lifecycle-debugging.md` | How to inspect a stuck study, manually transition state, purge a study, debug orchestrator deadlocks |

**Modified files**

| File | Change |
|---|---|
| `state.md` | Add Phase 2 entry under "Most recent meaningful changes"; update "In flight" + "Queued" sections; bump active priority pointer |
| `architecture.md` | Extend `services/` line: `cluster.py` → `cluster.py + study_state.py`; extend `workers/` line: add `orchestrator.py` alongside `trials.py`; extend `domain/` line: `query/render.py` → `query/render.py + study/search_space.py + study/template_validator.py + study/csv_parser.py` |
| `CLAUDE.md` | Update Feature Status table: `feat_study_lifecycle` → "**Complete (Phase 2 PR #<N>, merged YYYY-MM-DD)**"; remove the phase2_idea.md pointer |
| `docs/02_product/mvp1-user-stories.md` | Mark US-9, US-10, US-11, US-12 as "implemented" |

**Tasks**

1. Author `study-lifecycle-debugging.md` mirroring `optuna-debugging.md`'s structure:
   - Background — what a study is, the state machine, the orchestrator loop.
   - Connect to Postgres + inspect `studies` / `trials`.
   - Find a stuck study (orchestrator died mid-loop).
   - Force-cancel via direct DB UPDATE (escape hatch — calls `study_state.cancel_study` directly through a `python -c` snippet that the runbook quotes).
   - Purge a study (cascade delete via `DELETE FROM studies WHERE id = ...`).
   - Common errors: `5 consecutive trial failures`, `INVALID_STATE_TRANSITION`, `StudyStateProtectionError`.
2. Update the three core context files per the table above.
3. Move the feature folder per `impl-execute` Step 8.6: `docs/02_product/planned_features/feat_study_lifecycle/` → `docs/00_overview/implemented_features/<YYYY_MM_DD>_feat_study_lifecycle/` AFTER Phase 2's PR merges. Per Step 8.6, the move requires that no `phase*_idea.md` files remain — Phase 2 IS the last phase, so removing `phase2_idea.md` (or moving it into the implemented folder as historical context) unblocks the move.

**DoD**
- Runbook merged + dry-run validated against a real running study locally.
- `state.md`, `architecture.md`, `CLAUDE.md`, `mvp1-user-stories.md` reflect shipped behavior.
- Folder move executed only AFTER PR merge (per Step 8.6).

---

### Epic 4 phase gate (release-ready)

- [ ] Story 4.1 complete.
- [ ] `make test-unit test-integration test-contract` green.
- [ ] `make lint typecheck` green.
- [ ] All 10 ACs verified (AC-1..AC-10).
- [ ] **Final GPT-5.5 review** per `impl-execute` Step 6 on the complete merged-diff scope (Epic 1 + Epic 2 + Epic 3 + Epic 4).
- [ ] Gemini Code Assist comments adjudicated (if Gemini fires on the PR).
- [ ] Feature folder moved to `implemented_features/` after PR merge.

---

## 3) Testing workstream

### 3.1 Unit tests

- Location: `backend/tests/unit/`
- Files (4 new):
  - [ ] `unit/domain/test_search_space_validator.py` — Story 1.1 (14 cases)
  - [ ] `unit/domain/test_template_validator.py` — Story 1.2 (11 cases, including AC-7)
  - [ ] `unit/services/test_study_state.py` — Story 1.3 (12 cases, including AC-6 mock-session variant)
  - [ ] `unit/domain/test_csv_parser.py` — Story 3.2 (7 cases)

### 3.2 Integration tests

- Location: `backend/tests/integration/`
- Files (5 new):
  - [ ] `integration/test_phase2_repos.py` — Story 1.4 (11 cases)
  - [ ] `integration/test_study_lifecycle.py` — Story 2.1 (AC-1, AC-2, AC-5, AC-6, AC-10)
  - [ ] `integration/test_study_cancel.py` — Story 2.2 (AC-3)
  - [ ] `integration/test_study_resume.py` — Story 2.3 (AC-4)
  - [ ] `integration/test_csv_upload.py` — Story 3.2 (AC-8)
  - [ ] `integration/test_pagination.py` — Story 3.3 (AC-9)
- Helper file: `integration/fixtures/study_factories.py` (Story 2.1) + `integration/_subprocess_helpers/orchestrator_restart.py` (Story 2.3)

### 3.3 Contract tests

- Location: `backend/tests/contract/`
- Files (2 new):
  - [ ] `contract/test_studies_api_contract.py` — Story 3.5
  - [ ] `contract/test_studies_error_codes.py` — Story 3.5 (12 error codes)

### 3.4 E2E tests

N/A — Phase 2 has no UI surface. UI is `feat_studies_ui`.

### 3.5 Existing test impact audit

| Test file | Pattern | Action |
|---|---|---|
| `backend/tests/integration/test_run_trial.py` | uses `_build_adapter` from `infra_optuna_eval` | No change — Phase 2 doesn't touch `run_trial` |
| `backend/tests/integration/test_cluster_repo.py` | tests `Cluster` repo only | No change |
| `backend/tests/unit/test_settings.py` | tests Settings defaults | Story 1.5 extends — adds 2 cases |
| Existing `domain/query/render.py` callers (adapter tests) | render uses `Template(...)` | Story 1.2 sandbox-swaps render — verify no regression via `make test-unit -k render && make test-integration -k cluster` |

### 3.6 Migration verification

N/A — Phase 2 adds zero migrations. Alembic head stays at `0003_study_lifecycle_schema` (from Phase 1).

### 3.7 CI gates

- [ ] `make test-unit`
- [ ] `make test-integration` (CI service-container Postgres + ES + OpenSearch)
- [ ] `make test-contract`
- [ ] `make lint typecheck`
- [ ] Coverage ≥80% gate (existing — Phase 2 adds substantial code; verify coverage stays above 80% on the new files specifically: `services/study_state.py`, `workers/orchestrator.py`, `domain/study/*`, `api/v1/{studies,query_sets,query_templates}.py`)

---

## 4) Documentation update workstream

### 4.0 Core context files

**`state.md`** — Story 4.1 updates:
- [ ] Active branch / execution context — flip to "feature/feat-study-lifecycle-phase2 (in flight)" while building, then "merged" after PR closes.
- [ ] Most recent meaningful changes — add Phase 2 entry with PR number, story count, AC coverage, file moves.
- [ ] In flight / Queued — Phase 2 → done; `feat_llm_judgments` becomes next-up.

**`architecture.md`** — Story 4.1 updates:
- [ ] "Where the code lives" tree — add `services/study_state.py`, `workers/orchestrator.py`, `domain/study/*`, `api/v1/studies.py`, `api/v1/query_sets.py`, `api/v1/query_templates.py`.

**`CLAUDE.md`** — Story 4.1 updates:
- [ ] Feature Status table row for `feat_study_lifecycle`: Phase 1 + Phase 2 → "**Complete (Phase 2 PR #<N>, merged YYYY-MM-DD)**".

### 4.1 Architecture docs

- [ ] `docs/01_architecture/data-model.md` — no change expected (Phase 1 already documents the 7 tables' final shape).
- [ ] `docs/01_architecture/optimization.md` — review the "Optuna study lifecycle" section to confirm it accurately describes the orchestrator's ask/tell loop (it may need a small clarification about the pre-allocate-then-enqueue contract).
- [ ] `docs/01_architecture/api-conventions.md` — no change (the spec's API convention check already conforms).

### 4.2 Product docs

- [ ] `docs/02_product/mvp1-user-stories.md` — mark US-9, US-10, US-11, US-12 as implemented.

### 4.3 Runbooks

- [ ] `docs/03_runbooks/study-lifecycle-debugging.md` — Story 4.1 creates it.
- [ ] `docs/03_runbooks/optuna-debugging.md` — cross-link the new runbook from the "Find a stuck or orphan trial" section.

### 4.4 Security docs

N/A — no new secrets, no new auth surface. The Jinja2 sandbox is a defense-in-depth mitigation; spec §10 documents the threat model.

### 4.5 Quality docs

N/A — existing test-layer convention applies.

### 4.6 Idea-file finalization

- [ ] `phase2_idea.md` — when the feature folder moves to `implemented_features/`, retain the idea file inside the moved folder as historical context (per impl-execute Step 8.6 — phase idea files are kept after the deferred phase ships).

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

- **One real refactor:** swap `domain/query/render.py` from raw `Template(...)` to `SandboxedEnvironment.from_string(...)` (Story 1.2). Defense-in-depth — same render contract, sandbox applied at runtime so a stored-but-pre-Phase-2-validation template can't escape attribute restrictions.
- **No speculative redesign.** The cluster pagination pattern (`_encode_cursor` / `_decode_cursor`) is duplicated across the new routers — extract to a shared helper IF it appears in 3+ routers cleanly (judgment call during Story 3.3); otherwise leave the inline pattern (per the `no premature abstraction` guideline in CLAUDE.md "Doing tasks").

### 5.2 Planned refactor tasks

- [ ] Story 1.2: sandbox render swap — verified non-regressive.
- [ ] Story 3.3 (conditional): cursor helper extraction IF the pattern is identical across `clusters.py`, `studies.py`, and 1+ other routers AND the inline duplication exceeds ~30 LOC total. Otherwise no extraction.

### 5.3 Refactor guardrails

- [ ] Behavioral parity proven by existing render tests + new `test_template_validator.py`.
- [ ] `make lint typecheck` green.
- [ ] No expansion of product scope.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `infra_foundation` shipped | All stories | **Done — PR #4 merged 2026-05-09** | No Settings, no Alembic, no Arq worker — cannot start |
| `infra_adapter_elastic` shipped | Story 2.1 (orchestrator) | **Done — PR #16 merged 2026-05-10** | `clusters` table required for FK targets + adapter for `run_trial` |
| `feat_study_lifecycle` Phase 1 shipped | All Epic 1+2+3 stories | **Done — PR #18 merged 2026-05-10** | The 7 tables + 15 minimal repos are the substrate |
| `infra_optuna_eval` shipped | Story 2.1 (orchestrator dispatches `run_trial`) | **Done — PR #23 merged 2026-05-10** | `run_trial` job + Optuna RDB bootstrap required |
| `feat_digest_proposal` runner registered | Story 2.1 (orchestrator enqueues `generate_digest`) | **Not shipped — Phase 2 provides the durable handoff via `digest_stub.py`** | Phase 2's `digest_stub.generate_digest` inserts a `proposals` row with `status='pending'` for every completed study. `feat_digest_proposal` later replaces the stub; its plan must scan pre-existing `pending` proposal rows AND consume newly-enqueued jobs so studies completed in the gap aren't dropped. **Documented in C2-F3 cycle-2 fix** + `Story 2.1 New files` table. |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Orchestrator deadlocks holding `SELECT … FOR UPDATE` on a `studies` row while replenishment loop also reads | L | H | Service-layer `_load_for_update` only fires inside transition functions; the polling loop uses plain `repo.get_study` (no lock). Transitions commit immediately. |
| `study.ask()` + `apply_search_space` from orchestrator races with `run_trial`'s `study.trials[n]` read in worker | L | M | Optuna RDB locking serializes `ask`/`tell`; the worker reads via `study.trials[n]` which fetches from RDB on demand. `infra_optuna_eval` final-review F3 added a regression test (`test_concurrent_ask_tell_does_not_deadlock`); this contract continues to hold. |
| Replenishment over-enqueues (e.g. count drift between Optuna RDB and app `trials`) | M | L | Worker idempotency (spec §11 clause 1a + 1b) handles over-enqueue cleanly — duplicate `run_trial(study_id, optuna_trial_number)` invocations return no-op. |
| `time_budget_min` of 0.05 (3s) in AC-2 race condition: orchestrator polling-tick (1s) means budget can elapse before any trial completes | M | L | AC-2 acceptance window is 90s (60s budget + 30s drain); even with one trial in flight, the orchestrator transitions to `completed` at next tick. Spec AC-2 explicitly allows `trials_summary.complete > 0` — does NOT require all trials complete. |
| `arq_pool` not initialized in `ctx` for non-Arq invocations (tests calling `start_study` directly) | M | L | Story 2.1's `start_study` falls back to `create_pool(...)` if `ctx["arq_pool"]` is absent. Test fixtures can mock the pool. |
| AC-5 "5 consecutive failures" window definition drift between spec and implementation | L | M | Spec leaves the window definition open (idea-file open question 2); this plan locks in "the N most recent terminal trials by `optuna_trial_number DESC` are all `failed`". Story 1.3 + 2.1 docstrings cite this contract explicitly. |
| Cancel-race between user + orchestrator stop-condition (spec §11) | L | L | `_load_for_update` SERIALIZE the transitions; the loser raises `InvalidStateTransition` and the orchestrator catches+swallows per spec §11 ("loser is silently swallowed by the orchestrator"). |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| Orchestrator process dies mid-tick | SIGKILL / OOM | Study stays at `status='running'`; on worker restart, `on_startup` sweep re-enqueues `resume_study` | Automatic (FR-5 / AC-4) |
| Postgres unreachable mid-orchestrator-tick | DB down | Service-layer mutation raises `OperationalError`; orchestrator job re-raises; Arq retries with backoff | Automatic (Arq retry) |
| `run_trial` fails 5 times in a row (e.g. cluster unreachable) | Cluster down | Orchestrator detects via `_last_n_all_failed`; transitions study to `failed` with `failed_reason="5 consecutive trial failures"` | Operator restores cluster + manually `UPDATE studies SET status='queued' …` via the service-layer `python -c` snippet documented in `study-lifecycle-debugging.md` |
| Operator deletes the cluster row while study is running | `DELETE FROM clusters WHERE id = …` | `run_trial` finds no cluster row → raises `RuntimeError`; trial fails; after 5 consecutive failures the study fails per AC-5 | Operator re-creates the cluster (revives the soft-deleted row per `infra_adapter_elastic`); re-queue the study manually |
| `judgment_lists` row deleted mid-study | DB DELETE | `qrels_loader` raises (currently `JudgmentsTableMissing`; with `feat_llm_judgments` shipped, a real `SELECT` returns empty); trial fails; after 5 consecutive failures the study fails | Same as above |
| Operator submits study with `judgment_list_id` whose `query_set_id` doesn't match study's `query_set_id` | API create | POST validation rejects with `VALIDATION_ERROR` (spec §11 "Edge/error flows" first bullet) | Operator corrects payload |
| Orchestrator dies between `study.ask()` and the enqueue commit | Worker crash | Optuna has a RUNNING trial with no corresponding app row; orphan reaper (deferred per `state.md` "infra_optuna_orphan_reaper" debt) is the eventual cleanup; Phase 2 tolerates orphans operationally | Deferred to `infra_optuna_orphan_reaper` (operational tolerance per `infra_optuna_eval` spec §11) |

---

## 7) Sequencing and parallelization

### Suggested sequence

1. **Epic 1** (foundations) — Stories 1.1 → 1.2 → 1.3 → 1.4 → 1.5. 1.1 + 1.2 are independent and can run in parallel; 1.3 depends on neither (the event listener uses `Study` from Phase 1). 1.4 + 1.5 also independent. Suggested order respects the natural read order of the plan but parallelization is fine.
2. **Epic 2** (orchestrator) — Stories 2.1 → 2.2 → 2.3. 2.1 is the heavy lift; 2.2 and 2.3 build on 2.1's `start_study`.
3. **Epic 3** (API) — Stories 3.1 → 3.2 → 3.3 → 3.4 → 3.5. Suggested order is "smallest scope first" (templates → query-sets → studies → trials → contract sweep). **3.3 and 2.2's test depend on each other**: 2.2's test cancels via the API endpoint, which 3.3 implements. Either run 3.3 first, or 2.2's test calls the service-layer cancel directly (acceptable shortcut documented in 2.2's note).
4. **Epic 4** (docs) — Story 4.1 last. Single story.

### Parallelization opportunities

- Stories 1.1, 1.2, 1.5 are fully independent — author in parallel if multiple contributors.
- Stories 3.1 and 3.2 are independent (templates vs query-sets) — author in parallel.
- Story 4.1's runbook can begin draft once Epic 2 lands.

---

## 8) Rollout and cutover plan

- **Rollout stages:** Single-shot. Phase 2 is one PR.
- **Feature flag strategy:** None. The orchestrator's queue consumer is keyed off the `studies` Arq function — a study that's never POSTed never triggers anything.
- **Migration/cutover:** Zero migrations. `make migrate` is a no-op for Phase 2. Existing dev installs need no migration step.
- **Operational handoff (CLAUDE.md §7.5):** Operators must restart the Arq worker after deploy so `WorkerSettings.on_startup` picks up the new `start_study` / `resume_study` registrations. Document in the PR description.

---

## 9) Execution tracker (copy/paste section — agents update as they land)

### Current sprint (Phase 2)

- [x] Story 1.1 — Search-space validator + apply mapping
- [x] Story 1.2 — Template validator + sandbox refactor
- [x] Story 1.3 — Study state machine + protection listener (FR-7 / AC-6)
- [x] Story 1.4 — Repo extensions (pagination, filters, counts, trials_summary, sort, bulk insert)
- [x] Story 1.5 — Settings additions (parallelism, timeout defaults)
- [x] Epic 1 phase gate
- [x] Story 2.1 — `start_study` Arq job (FR-4 / AC-1, AC-2, AC-5, AC-10)
- [x] Story 2.2 — Cancel path (AC-3)
- [x] Story 2.3 — Resume-after-restart (FR-5 / AC-4)
- [x] Epic 2 phase gate
- [x] Story 3.1 — Query-template endpoints (FR-2 / AC-7)
- [x] Story 3.2 — Query-set + bulk queries endpoints (FR-3 / AC-8)
- [x] Story 3.3 — Study endpoints (FR-1 / AC-9)
- [x] Story 3.4 — Trials list endpoint (FR-6)
- [x] Story 3.5 — Contract + error-code tests
- [x] Epic 3 phase gate
- [x] Story 4.1 — Runbook + state.md/architecture.md/CLAUDE.md updates
- [x] Epic 4 phase gate

### Blocked items

- None at draft time.

### Done this sprint

- (track here as stories land)

---

## 10) Story-by-Story Verification Gate (Agent Checklist)

Before marking any story complete, the executing engineer / agent must attach evidence for:

- [ ] Files created/modified match story scope (`New files` / `Modified files` tables).
- [ ] Endpoint contract implemented exactly as documented (method/path/body/status/error code).
- [ ] Key interfaces implemented with compatible signatures (mypy strict passes).
- [ ] Required tests added/updated for every layer the story touches.
- [ ] Commands executed and passed:
  - [ ] `make test-unit`
  - [ ] `make test-integration` (or targeted subset, with explanation)
  - [ ] `make test-contract` (whenever the story modifies API surface)
  - [ ] `make lint typecheck`
- [ ] Migration round-trip evidence — N/A for every Phase 2 story (zero migrations).
- [ ] Related docs/checklists updated in same PR when behavior/contract changed (deferred to Story 4.1 for the bulk updates).

---

## 11) Plan consistency review (required before execution)

### Spec ↔ plan endpoint count

Spec §7.1 lists **12 endpoints**. This plan covers all 12:

| # | Spec endpoint | Owning story |
|---|---|---|
| 1 | `POST /api/v1/studies` | 3.3 |
| 2 | `GET /api/v1/studies` | 3.3 |
| 3 | `GET /api/v1/studies/{id}` | 3.3 |
| 4 | `POST /api/v1/studies/{id}/cancel` | 3.3 |
| 5 | `GET /api/v1/studies/{id}/trials` | 3.4 |
| 6 | `POST /api/v1/query-templates` | 3.1 |
| 7 | `GET /api/v1/query-templates` | 3.1 |
| 8 | `GET /api/v1/query-templates/{id}` | 3.1 |
| 9 | `POST /api/v1/query-sets` | 3.2 |
| 10 | `POST /api/v1/query-sets/{id}/queries` | 3.2 |
| 11 | `GET /api/v1/query-sets` | 3.2 |
| 12 | `GET /api/v1/query-sets/{id}` | 3.2 |

### Spec ↔ plan error code coverage

Spec §7.5 lists **12 codes**. Each is covered by a contract test in Story 3.5 + assigned to the story that emits it:

| Code | HTTP | Owning story (emits) | Test (Story 3.5) |
|---|---|---|---|
| `STUDY_NOT_FOUND` | 404 | 3.3 (GET-detail, cancel), 3.4 (trials list) | `test_studies_error_codes.py::test_study_not_found` |
| `INVALID_STATE_TRANSITION` | 409 | 3.3 (cancel) | `test_studies_error_codes.py::test_invalid_state_transition` |
| `INVALID_SEARCH_SPACE` | 400 | 3.3 (POST) | `test_studies_error_codes.py::test_invalid_search_space` |
| `TEMPLATE_NOT_FOUND` | 404 | 3.1 (GET-detail), 3.3 (POST validates) | `test_studies_error_codes.py::test_template_not_found` |
| `QUERY_SET_NOT_FOUND` | 404 | 3.2 (GET-detail, POST queries), 3.3 (POST validates) | `test_studies_error_codes.py::test_query_set_not_found` |
| `JUDGMENT_LIST_NOT_FOUND` | 404 | 3.3 (POST validates) | `test_studies_error_codes.py::test_judgment_list_not_found` |
| `INVALID_TEMPLATE_SYNTAX` | 400 | 3.1 (POST) | `test_studies_error_codes.py::test_invalid_template_syntax` |
| `UNDECLARED_PARAM_USED` | 400 | 3.1 (POST) | `test_studies_error_codes.py::test_undeclared_param_used` |
| `DECLARED_PARAM_UNUSED` | 400 | 3.1 (POST) | `test_studies_error_codes.py::test_declared_param_unused` |
| `TEMPLATE_NAME_TAKEN` | 409 | 3.1 (POST IntegrityError translation) | `test_studies_error_codes.py::test_template_name_taken` |
| `QUERY_SET_NAME_TAKEN` | 409 | 3.2 (POST IntegrityError translation) | `test_studies_error_codes.py::test_query_set_name_taken` |
| `INVALID_CSV` | 400 | 3.2 (POST queries) | `test_studies_error_codes.py::test_invalid_csv` |

### Spec ↔ plan FR coverage

All 7 FRs covered (see §1 above).

### Story internal consistency

- **Story 3.3 endpoint table matches `CreateStudyRequest` schema fields**: ✓ `name`, `cluster_id`, `target`, `template_id`, `query_set_id`, `judgment_list_id`, `search_space`, `objective`, `config`.
- **Story 3.4 endpoint table matches `TrialDetail` schema fields**: ✓ all `trials` columns surfaced.
- **No file ownership conflict**: Each new file appears in exactly one story's New files table. The `studies.py` router is owned by Story 3.3; Story 3.4 modifies it (handler addition).
- **Modified files exist**: verified via filesystem walk during plan drafting (Step 2 codebase exploration).

### Test file count and assignment

- Unit: 4 new files. Each assigned to exactly one story: 1.1, 1.2, 1.3, 3.2.
- Integration: 5 new test files + 2 helper modules. Each test file assigned to exactly one story.
- Contract: 2 new files, both assigned to Story 3.5.
- **No orphaned test files.**

### Gate arithmetic

- Epic 1 gate: 5 stories. ✓
- Epic 2 gate: 3 stories. ✓
- Epic 3 gate: 5 stories. ✓
- Epic 4 gate: 1 story. ✓
- Total: 14 stories. Cross-check: §1 traceability lists 7 FRs across stories 1.1, 1.2, 1.3, 2.1, 2.3, 3.1–3.5 — 13 trace-bearing stories + Story 1.4 (foundations) + Story 1.5 (settings) + Story 2.2 (cancel test) + Story 4.1 (docs) = 17? Re-check: actually 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4, 3.5, 4.1 = **14 stories**. ✓

### Open questions resolved

Spec §19 has **zero open questions**. ✓

Phase 2 idea-file open questions (3) — all locked by this plan:

1. **Settings vs JSON-only defaults for `parallelism` / `trial_timeout_s`** → Locked: Settings env-vars (`STUDIES_DEFAULT_PARALLELISM`, `STUDIES_DEFAULT_TIMEOUT_S`) per `redis_url` / `es_heap_size` precedent. API does NOT materialize into stored `studies.config` (preserves `infra_optuna_eval` pruner key-presence contract). Story 1.5 + Story 3.3.
2. **AC-5 "5 consecutive failures" semantics** → Locked: the N most recent terminal trials (by `optuna_trial_number DESC`) are all `status='failed'`. Story 2.1 + `_CONSECUTIVE_FAILURE_THRESHOLD` constant.
3. **Orchestrator backoff on `run_trial` infra re-raise** → Locked: no separate orchestrator timeout. Rely on Arq's visibility timeout + `studies.config.time_budget_min`. Documented in Story 2.1's "Failure surface" note.

### Frontend UI Guidance section

**N/A** — Phase 2 has no UI. UI is `feat_studies_ui`. No frontend files in any New/Modified files table.

### Enumerated value contract verification

Per the CLAUDE.md "Enumerated Value Contract Discipline" rule, every wire enum surfaces from one source of truth and the Pydantic schemas mirror it character-for-character.

| Wire enum | Backend source | Schema location | Comment requirement |
|---|---|---|---|
| `StudyStatusWire` (5 values) | `backend/app/db/models/study.py` CHECK + `backend/app/db/repo/study.py:StudyStatusFilter` | `backend/app/api/v1/schemas.py:StudyStatusWire` | `# Values must match backend/app/db/models/study.py CHECK constraint AND backend/app/db/repo/study.py StudyStatusFilter Literal` |
| `TrialStatusWire` (3 values) | `backend/app/db/models/trial.py` CHECK | `backend/app/api/v1/schemas.py:TrialStatusWire` | `# Values must match backend/app/db/models/trial.py CHECK constraint` |
| `EngineTypeWire` (2 values) | `backend/app/adapters/elastic.py:SUPPORTED_ENGINE_TYPES` | `backend/app/api/v1/schemas.py:EngineTypeWire` | `# Values must match backend/app/adapters/elastic.py SUPPORTED_ENGINE_TYPES` |
| `ObjectiveMetric` (6 values) | `backend/app/eval/scoring.py:SUPPORTED_METRICS` frozenset | `backend/app/api/v1/schemas.py:ObjectiveMetric` | `# Values must match backend/app/eval/scoring.py SUPPORTED_METRICS frozenset` |
| `ObjectiveK` (7 values) | `backend/app/eval/scoring.py:SUPPORTED_K_VALUES` frozenset | `backend/app/api/v1/schemas.py:ObjectiveK` | `# Values must match backend/app/eval/scoring.py SUPPORTED_K_VALUES frozenset` |
| `ObjectiveDirection` (2 values) | spec §7.4 + service layer | `backend/app/api/v1/schemas.py:ObjectiveDirection` | `# Values must match spec §7.4 + services/study_state.py transition logic` |
| `SamplerKind` (2 values) | `backend/app/eval/types.py:SamplerKind` Literal | `backend/app/api/v1/schemas.py:SamplerKind` | `# Values must match backend/app/eval/types.py SamplerKind Literal` |
| `PrunerKind` (2 values) | `backend/app/eval/types.py:PrunerKind` Literal | `backend/app/api/v1/schemas.py:PrunerKind` | `# Values must match backend/app/eval/types.py PrunerKind Literal` |
| `TrialSortKey` (5 values) | `backend/app/db/repo/trial.py:TrialSortKey` | `backend/app/api/v1/schemas.py:TrialSortKey` | `# Values must match backend/app/db/repo/trial.py TrialSortKey Literal` |

Each Pydantic `Literal[...]` declaration in `schemas.py` MUST be preceded by the comment above. Reviewers will grep for the commented anchors during phase-gate review.

### Audit-event coverage

**N/A in MVP1** per spec §6 ("`audit_log` lands at MVP2"). When MVP2 ships, this feature's `start_study` and `cancel_study` mutations will need to emit `study.start` and `study.cancel` audit events; `complete_study` will emit `study.complete`; `fail_study` will emit `study.fail`. These are noted in spec §6 and become a Phase 2.1 task when MVP2 boundary lands. No story in this plan adds audit emission — it's deferred to MVP2 by design.

### Admin / ceiling enforcement audit

**N/A in MVP1** per `docs/01_architecture/tech-stack.md` canonical release matrix. RelyLoop has no admin / tenant model in MVP1–MVP3. Activates at MVP4.

---

## 12) Definition of plan done

- [x] Every FR (7) mapped to stories/tasks/tests/docs updates.
- [x] Every story includes New files, Modified files, Endpoints (where applicable), Key interfaces, Tasks, and DoD.
- [x] Test layers (unit/integration/contract — no E2E) explicitly scoped.
- [x] Documentation updates across docs/01-05 planned and owned (Story 4.1).
- [x] Lean refactor scope bounded (sandbox swap; conditional cursor helper).
- [x] Phase/epic gates measurable (3 gates between epics + 1 release-ready gate).
- [x] Story-by-Story Verification Gate included.
- [x] Plan consistency review (§11) performed with no unresolved findings.
- [x] Cross-model review (GPT-5.5) — cycle 1 complete; 12 findings raised, **11 accepted + applied, 1 rejected with cited counter-evidence** (see Review log below). Cycle 2 pending.
- [x] Phase 2 deferred-work tracker — N/A; Phase 2 IS the deferred work, and after it ships there are no further phases.

---

## Review log — GPT-5.5 cycle 1 (2026-05-10)

Cross-model reviewer: GPT-5.5 (`gpt-5.5` via OpenAI API). Prompt token count: 50,503; completion: 7,508. Findings as structured JSON saved at `/tmp/gpt55_findings_phase2.json` for audit.

| # | Sev | Pass | Verdict | Issue → Fix |
|---|---|---|---|---|
| F1 | H | A | Accept + applied | `StudyConfigSpec.time_budget_min` was required; spec AC-1 payload omits it. → made both `max_trials` and `time_budget_min` optional with `model_validator` requiring at least one; orchestrator gates each stop-condition check on key presence. |
| F2 | M | A | **Reject + cited counter-evidence** | Cited spec §7 FR-3 `cluster_id?` to claim plan over-required the field. **Phase 1's shipped schema is authoritative** — `migrations/versions/0003_study_lifecycle_schema.py:79` declares `query_sets.cluster_id NOT NULL`; `backend/app/db/models/query_set.py:26` mirrors it. Phase 2 doesn't add migrations. Plan correctly requires the field. **Filed `chore_spec_query_set_cluster_id_drift/idea.md`** to patch the spec wording follow-up. |
| F3 | H | B | Accept + applied | `SandboxedEnvironment.parse()` does NOT catch `{{ os.system(...) }}` at parse time — the sandbox checks fire at render time. `meta.find_undeclared_variables` would classify `os` as undeclared and emit `UNDECLARED_PARAM_USED` instead of AC-7's required `INVALID_TEMPLATE_SYNTAX`. → Added explicit AST walk in `validate_template_body` rejecting `Call`/`Getattr`/dunder-name subscript as `InvalidTemplateSyntax` BEFORE the meta-vars check; tests updated. |
| F4 | H | B | Accept + applied | Story 2.1 referenced `_authorize_status_mutation_proxy()` which doesn't exist. `fail_study` already wraps its mutation internally. → Removed the dead wrapper; consecutive-failure path calls `fail_study` directly. |
| F5 | H | A | Accept + applied | `_stop()` claimed cancel-race tolerance via §11 but didn't `try/except InvalidStateTransition`. → Wrapped `complete_study` and `fail_study` calls in `try/except study_state.InvalidStateTransition`; loser logs + exits silently. Added `test_cancel_race.py` integration test. |
| F6 | H | B | Accept + applied | `_count_in_flight` counted from app `trials` rows, which exist only AT terminal state — would let the resume path over-allocate. → Redesigned to count Optuna RUNNING + WAITING trials via `optuna_study.trials`; capped total allocations at `max_trials`. |
| F7 | M | B | Accept + applied | `_drain_in_flight` had `...` body — algorithm not specified. → Specified: snapshot RUNNING/WAITING trial numbers, poll Optuna `study.trials` every 1s until all snapshotted are terminal OR 30s elapses; log `event_type=drain_timeout` on timeout. |
| F8 | M | A | Accept + applied | Trials list endpoint missing `?since=`; cross-cutting tests covered only studies. → Added `since` to `list_trials_paginated` + `count_trials`; expanded `test_pagination.py` to 12 test methods (4 endpoints × 3 behaviors: cursor + since + X-Total-Count). |
| F9 | M | B | Accept + applied | Story 2.2 required POST `/cancel` (Story 3.3) before Epic 2 gate. → Split: Story 2.2 tests the service-layer cancel + orchestrator drain; HTTP 409 second-cancel test moves to Story 3.5 `test_studies_error_codes.py::test_invalid_state_transition`. Epic 2 gate text updated. |
| F10 | M | B | Accept + applied | Enqueueing `generate_digest` against a worker that doesn't register it would log errors / discard jobs. → Added `backend/workers/digest_stub.py` (no-op `generate_digest` that logs `event_type=digest_deferred`); registered in `WorkerSettings.functions`; `feat_digest_proposal` later replaces the stub. |
| F11 | M | B | Accept + applied | `@event.listens_for(session_factory.sync_session_class, ...)` was version-fragile. → Switched to `event.listen(Session, "before_flush", _guard)` (Session from `sqlalchemy.orm`) with `isinstance(obj, Study)` filter inside. `inspect(obj).attrs["status"].history.has_changes()` for change detection. |
| F12 | M | A | Accept + applied | Spec §11 requires `judgment_list.query_set_id == study.query_set_id` consistency check; Story 3.3 missed it. → Added the check to Story 3.3 POST handler tasks; added `test_validation_error_judgment_query_set_mismatch` case to Story 3.5. |

**Tally:** 11 accepted + applied, 1 rejected with cited counter-evidence. Net plan deltas: 1 new test file (`test_cancel_race.py`), 1 new worker stub (`digest_stub.py`), 1 new chore idea file, +6 test methods on `test_pagination.py`, +1 test method on `test_studies_error_codes.py`, +3 test methods on `test_template_validator.py`. Total new/modified test methods: +12.

## Review log — GPT-5.5 cycle 2 (2026-05-10)

Convergence assessment: **issues_remain**. 6 new findings, all addressing residual gaps in cycle-1 fixes (specifically F6, F10, F11 had unresolved tails) and one new architectural concern (queued-cancel race).

| # | Sev | Pass | Verdict | Issue → Fix |
|---|---|---|---|---|
| C2-F1 | H | B | Accept + applied | Cycle 1's F6 fix capped allocations at `max_trials` but didn't atomicize the check-then-act block. Two concurrent orchestrators on the same study (spec §11 "recoverable" case) could both observe the same in-flight count and both `ask()`. → Added `_try_replenish_lock` context manager using `pg_try_advisory_lock(blake2b-keyed)` around the count + `ask()` block. Non-blocking — losers skip the tick and retry in 1s. |
| C2-F2 | M | B | Accept + applied | Cycle 1's F11 listener fix defined `_guard` inside `_install_state_guard_listener()`, so repeated installer calls registered distinct callables (SQLAlchemy's dup-listener check only matches identity). → Hoisted `_study_state_guard` to module scope; added `event.contains(...)` short-circuit before `event.listen(...)`. |
| C2-F3 | M | B | Accept + applied | Cycle 1's F10 no-op `digest_stub` consumed jobs from Redis and discarded them — studies completed between Phase 2 and `feat_digest_proposal` shipping would lose their digest with no durable handoff. → Redesigned `digest_stub.generate_digest` to INSERT a `proposals` row with `status='pending'` (the durable forward marker). `feat_digest_proposal` later SELECTs pending proposals + processes them. Updated the Dependencies/Risks row to match. |
| C2-F4 | M | A | Accept + applied | `study_state.start_study` raises `InvalidStateTransition` on `cancelled → running`. If user POST-cancels a queued study before the Arq job runs, the orchestrator's entry transition raises and Arq retries forever. → Wrapped the orchestrator's initial `study_state.start_study()` call in `try/except InvalidStateTransition`; log + return silently. Also handle `StudyNotFound` for delete-before-dispatch. |
| C2-F5 | L | B | Accept + applied | Story 3.3 owned `test_pagination.py` with 12 methods, but 3 of them hit `/studies/{id}/trials` which doesn't exist until Story 3.4. → Split: Story 3.3 owns 9 methods (studies + query-sets + query-templates × 3 behaviors); Story 3.4 owns 3 methods (trials × 3 behaviors). |
| C2-F6 | L | B | Accept + applied | Cycle 1's F3 AST walk only inspected `Call`/`Getattr`/`Getitem` nodes — a plain `{{ _secret }}` reference (especially if `_secret` is in `declared_params`) would slip through. → Added a `nodes.Name` walk that rejects any `_`-prefixed identifier as `InvalidTemplateSyntax`. Added test 12. |

**Cycle 1 fix verifications (GPT-5.5):**
- ✓ F1: stop-condition optionality + model_validator + key-presence gating verified.
- ✓ F3: AST `Call` rejection before meta-vars check verified.
- ✓ F4: no remaining `_authorize_status_mutation_proxy` references.
- ✓ F5: `_stop()` catches `InvalidStateTransition`, rolls back, logs, exits.
- ⚠ F6 → C2-F1 (residual non-atomicity — fixed).
- ✓ F7: `_drain_in_flight` algorithm specified.
- ✓ F8: trials `since` added; pagination matrix complete (sequencing fix lands as C2-F5).
- ✓ F9: Story 2.2 service-only; HTTP cancel-409 in Story 3.5.
- ⚠ F10 → C2-F3 (no-op discarded handoff — fixed via durable proposals insert).
- ⚠ F11 → C2-F2 (closure identity bug — fixed via module-scope callable).
- ✓ F12: judgment/query-set consistency check + test added.

**Cycle 2 tally:** 6 accepted + applied, 0 rejected. Net plan deltas: `_try_replenish_lock` helper, module-level `_study_state_guard`, durable digest handoff via proposals insert, queued-cancel race tolerance, test re-assignment between Stories 3.3 / 3.4, 1 additional template validator test.

## Review log — GPT-5.5 cycle 3 (2026-05-10)

Convergence assessment: **issues_remain** at first pass (2 findings); **clean** at second pass (1 residual finding) after applying first-pass patches in-cycle. Final cycle per the impl-plan-gen Step 7 "max 3 cycles" rule.

| # | Sev | Pass | Verdict | Issue → Fix |
|---|---|---|---|---|
| C3-F1 | M | A | Accept + applied | Cycle 2 fix changed pruner/parallelism defaults to env-var fallbacks read at job time IF the key is absent in `studies.config`. But Story 3.3's POST handler didn't specify `model_dump(exclude_none=True, exclude_unset=True)` — a straightforward `.model_dump()` would persist `{"parallelism": null, "pruner": null, ...}` and break the key-presence semantics. → Added explicit `model_dump(exclude_none=True, exclude_unset=True)` task + key-omission DoD test. |
| C3-F2 | M | B | Accept + applied | Orchestrator held `async with session_factory() as db:` across the entire 24h `while True` loop including 1s sleeps — would exhaust the connection pool when N studies run concurrently. → Restructured to open/close session per tick. The advisory lock changed from session-scoped (`pg_try_advisory_lock` + explicit unlock) to **transaction-scoped** (`pg_try_advisory_xact_lock`, auto-released on commit). Helper renamed `_try_replenish_lock` → `_try_replenish_xact_lock`. |
| C3-F3 | M | B | Accept + applied (cycle-3 second pass) | The C2-F3 cycle-2 fix put the pending-proposal INSERT inside `digest_stub.generate_digest` (the Arq job body). But `_stop()` commits `complete_study` THEN enqueues — a crash between commit and enqueue leaves a `completed` study with no proposal marker, losing the digest. → Moved the proposal INSERT into `_stop()`'s `complete_study` transaction (atomic durable handoff). `digest_stub.generate_digest` became an **idempotent acknowledger** (SELECT-then-no-op-or-INSERT). Enqueue is now best-effort with try/except. |

**Cycle 2 fix verifications (GPT-5.5):**
- ✓ C2-F1: advisory lock keyed by study_id with non-blocking `pg_try_advisory_xact_lock`.
- ✓ C2-F2: `_study_state_guard` module-scoped + `event.contains(...)` short-circuit.
- ⚠ C2-F3 → C3-F3 (completion-to-enqueue atomicity gap — fixed in cycle 3 second pass).
- ✓ C2-F4: orchestrator entry catches `InvalidStateTransition` + `StudyNotFound`.
- ✓ C2-F5: pagination tests split across Story 3.3 (9 methods) + Story 3.4 (3 methods).
- ✓ C2-F6: `nodes.Name` walk rejects `_`-prefixed identifiers.

**Cycle 3 tally:** 3 accepted + applied (C3-F1, C3-F2 from first pass; C3-F3 from second pass), 0 rejected. Final cycle complete.

## Convergence statement

After 3 GPT-5.5 cycles:
- **21 distinct findings raised** (12 in cycle 1, 6 in cycle 2, 3 in cycle 3).
- **19 accepted + applied** to the plan with concrete code/structure changes.
- **1 rejected with cited counter-evidence** (cycle-1 F2 — captured separately as `chore_spec_query_set_cluster_id_drift/idea.md` for spec patch follow-up; reviewer respected the rejection in cycles 2 and 3 and did not re-raise).
- **1 second-pass discovery** (C3-F3) inside cycle 3 — fixed in the same cycle.
- **0 unresolved disagreements**, **0 open user-escalation questions**.

The plan is execution-ready. No further pre-implementation review cycles. The per-phase gate reviews (Epic 1, Epic 2, Epic 3, Epic 4) within `/impl-execute` will catch any residual implementation drift against this plan.
