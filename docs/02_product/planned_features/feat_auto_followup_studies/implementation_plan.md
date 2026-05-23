# Implementation Plan — Auto-Followup Studies

**Date:** 2026-05-23
**Status:** Ready for Execution
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy source(s):** [`CLAUDE.md`](../../../../CLAUDE.md), [`docs/01_architecture/optimization.md`](../../../01_architecture/optimization.md), [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md)

---

## 0) Planning principles

- Spec traceability first — every story maps to one or more FRs (FR-1 through FR-12).
- Phase gates are hard stops — Epic 1 (foundation) must pass before Epic 2 (workers); Epic 2 before Epic 3 (frontend); E2E test (Story 3.3) is the green-light for documentation merge.
- Fail-loud tests — every contract test asserts explicit `error_code` strings; every telemetry assertion uses `event_type=` exact match.
- Use the canonical RelyLoop patterns — `_job_id` for Arq dedup, `services.study_state` for status transitions, `structlog` event_type-keyed events.
- Keep increments narrow — each story is independently mergeable as a commit on the feature branch; the PR bundles them.

## 1) Scope traceability (FR → epic/story)

| FR ID | Spec name | Epic / Story | Notes |
|---|---|---|---|
| FR-1 | Opt-in field on StudyConfigSpec | Epic 1 / Story 1.1 | Pydantic field + validator (`0 <= n <= 5`); JSONB round-trip; depth=0 internal terminal value per D-12 |
| FR-2 | Lift-gate evaluation (FR-2a active) | Epic 1 / Story 1.1 | `evaluate_chain_gate` pure domain function; first-decile baseline per D-3 |
| FR-3 | `enqueue_followup_study` worker | Epic 2 / Story 2.1 | Arq job + WorkerSettings registration + layer-2 idempotency backstop |
| FR-4 | `narrow_around_winner` domain extraction | Epic 1 / Story 1.2 | Refactor out of agent tool; byte-parity test |
| FR-5 | Strict config inheritance | Epic 2 / Story 2.1 | Implemented inside `enqueue_followup_study` |
| FR-6 | Daily budget gate at enqueue time | Epic 2 / Story 2.1 | `peek_daily_total` + `estimated_max_call_cost`; 80% threshold |
| FR-7 | Failure-aware halting | Epic 1 / Story 1.1 | `evaluate_chain_gate` returns `skip_parent_failed` (defensive only — digest doesn't run on failed studies, per AC-6 lock) |
| FR-8 | Cancellation cascade | Epic 1 / Story 1.3 (service) + Epic 2 / Story 2.3 (endpoint) | `cancel_study_with_chain_cascade` + `?cascade=` query param |
| FR-9 | Telemetry events (8-event catalog) | Epic 2 / Story 2.1 (events 1–7) + Story 2.3 (event 8 cascade) | structlog `event_type=`-keyed |
| FR-10 | UI chain panel | Epic 2 / Story 2.3 (children endpoint) + Epic 3 / Story 3.1 (panel component) | Direct-children-only per D-13 |
| FR-11 | Wizard depth selector | Epic 3 / Story 3.2 | Extends existing `create-study-modal.tsx`; `0`-sentinel maps to `undefined` |
| FR-12 | ON DELETE NO ACTION locked | (no story — negative requirement; per D-1 no migration) | Verified by absence of ALTER migration in plan |

**No deferred phases.** Spec §3 Phase boundaries: single-phase delivery (Tier A + Tier B ship together). No `phase2_idea.md` needed.

## 2) Delivery structure

**Epic → Story → Tasks → DoD.** Stories within an epic can land as adjacent commits on the feature branch; epics are the natural review-cycle boundaries.

### Story-level conventions (RelyLoop)

- All repo functions take `db: AsyncSession` as first arg; use `db.flush()` (caller commits). New repo functions exported via `backend/app/db/repo/__init__.py` `__all__`.
- Services are async; route every `study.status` mutation through `services.study_state.*` (the SQLAlchemy event-listener guards at [`backend/app/services/study_state.py:296-345`](../../../../backend/app/services/study_state.py#L296) raise `StudyStateProtectionError` on direct ORM writes).
- Domain layer is pure — no DB access, no async. Located in `backend/app/domain/`.
- Models use `Mapped[]` typed columns, `String(36)` UUIDs.
- Routers return typed Pydantic response models; errors use `HTTPException(status_code=…, detail={"error_code": "...", "message": "...", "retryable": <bool>})`.
- Arq job functions take `ctx: dict[str, Any]` as first arg; registered in `backend/workers/all.py:WorkerSettings.functions`.
- All `__init__.py` exports updated via `__all__`.
- Conventional Commits format on every commit; commit-msg pre-commit hook enforces — never bypass.
- Frontend dropdowns/selects with backend wire values MUST carry a `// Source-of-truth: <path> <Symbol>` comment per CLAUDE.md "Enumerated Value Contract Discipline."

### AI Agent Execution Protocol

0. Read [`architecture.md`](../../../../architecture.md), [`state.md`](../../../../state.md), and this plan's §0–§2 before starting Story 1.1.
1. Read story scope: Outcome + Files + Key interfaces + DoD.
2. Implement backend first (domain → repo → service → worker → router/schema).
3. Run `make lint && make test-unit` for backend stories; `cd ui && pnpm lint && pnpm typecheck && pnpm test` for frontend stories.
4. Implement frontend (if story has UI scope).
5. Run E2E scope after the cancel-modal story (3.3) — it's the only story that touches a real-backend E2E path.
6. Update docs in the final docs-only story (4.1), not inline per-story.
7. No migrations in this feature — skip "Verify migration round-trip" for every story.
8. Attach evidence in PR description: commands run, pass/fail counts, files changed.

---

## Epic 1 — Backend foundation (pure domain + repo)

**Goal:** Pydantic field, two pure domain functions, one repo function, one service wrapper. No worker code, no router code, no frontend. After Epic 1, the substrate is in place for Epic 2 to bolt on the worker and Epic 3 to bolt on the UI.

**Gate:** all of `make lint`, `make typecheck`, `make test-unit` pass; backend-only integration scaffolding for the cascade service passes.

### Story 1.1 — `auto_followup_depth` field + `evaluate_chain_gate` domain

**Outcome:** The API accepts `config.auto_followup_depth` with validator (FR-1). A pure domain function decides whether to enqueue, skip, or halt a chain (FR-2 + FR-7).

**New files:**

- `backend/app/domain/study/auto_followup.py` — pure module containing `ChainGateOutcome` (enum-like dataclass), `evaluate_chain_gate` (pure function), `compute_first_decile_max` (helper).

**Modified files:**

- `backend/app/api/v1/schemas.py` — add `auto_followup_depth: int | None = None` field to `StudyConfigSpec` (line 569 area, alongside existing `max_trials`, `time_budget_min`, etc.); add `model_validator(mode='after')` `_validate_auto_followup_depth` (alongside existing `_require_one_stop_condition` at line 578). Update class docstring to document FR-1 + D-12 semantics.

**Endpoints:** None directly — this story only changes the schema validation behavior of the existing `POST /api/v1/studies` endpoint. The 422 `AUTO_FOLLOWUP_DEPTH_OUT_OF_RANGE` path becomes live once the validator lands.

**Key interfaces:**

```python
# backend/app/domain/study/auto_followup.py

from dataclasses import dataclass
from enum import Enum

class ChainGateDecision(str, Enum):
    """What evaluate_chain_gate decided. One per FR-9 event_type (modulo the
    enqueue/skip/exhausted split). The enqueue branch returns `enqueue`;
    skip branches return their specific reason for telemetry."""
    ENQUEUE = "enqueue"
    SKIP_NO_LIFT = "skip_no_lift"
    SKIP_PARENT_FAILED = "skip_parent_failed"
    SKIP_DEPTH_EXHAUSTED = "skip_depth_exhausted"

@dataclass(frozen=True)
class ChainGateOutcome:
    decision: ChainGateDecision
    # Populated for decision == ENQUEUE OR SKIP_NO_LIFT (for telemetry):
    lift: float | None = None
    first_decile_max: float | None = None
    # Always populated:
    epsilon: float = 0.005

def compute_first_decile_max(
    complete_trials: list["Trial"],  # status='complete', sorted by created_at ASC
) -> float | None:
    """Return max(primary_metric) over the first decile of complete trials.
    Returns None if no complete trials or all have None primary_metric.
    First decile = `complete_trials[:max(1, len(complete_trials) // 10)]`
    — floor division per spec FR-2a (cycle-1 finding C1-1). Boundary cases:
       len=0    → returns None
       len=1-9  → first 1 trial
       len=10   → first 1 trial (10 // 10 = 1)
       len=11-19 → first 1 trial (11 // 10 = 1, NOT ceil(11/10) = 2)
       len=20   → first 2 trials"""

def evaluate_chain_gate(
    parent: "Study",
    complete_trials: list["Trial"],
    *,
    epsilon: float = 0.005,
) -> ChainGateOutcome:
    """Pure decision function. Inputs:
       - parent: a Study row (already loaded from DB by the caller)
       - complete_trials: parent's trials filtered to status='complete'
       - epsilon: lift threshold (default 0.005 per FR-2 / D-3)

    Returns ChainGateOutcome. No DB, no I/O, no async."""
```

**Pydantic schema additions:**

```python
# backend/app/api/v1/schemas.py — extends existing StudyConfigSpec

class StudyConfigSpec(BaseModel):
    # ... existing fields unchanged ...
    auto_followup_depth: int | None = Field(default=None)
    """Per FR-1 + D-12: 0..5 valid; 0 is worker-internal terminal state
    (operators set None to opt out). Range enforced by model_validator
    below — NOT by Field(ge, le), so the project's canonical error
    envelope can carry AUTO_FOLLOWUP_DEPTH_OUT_OF_RANGE per spec §8.5."""

    @model_validator(mode='after')
    def _validate_auto_followup_depth(self) -> StudyConfigSpec:
        if self.auto_followup_depth is not None and not (0 <= self.auto_followup_depth <= 5):
            raise ValueError(
                "AUTO_FOLLOWUP_DEPTH_OUT_OF_RANGE: config.auto_followup_depth "
                f"must be between 0 and 5 inclusive when set; got {self.auto_followup_depth}"
            )
        return self
```

**Critical implementation note (cycle-1 finding C1-2):** Do NOT use `Field(ge=0, le=5)` for the bound check. Field-level bounds raise Pydantic's generic `greater_than_equal` / `less_than_equal` errors that the project's `RequestValidationError` handler maps to a generic `VALIDATION_ERROR` envelope — not to the spec-required `AUTO_FOLLOWUP_DEPTH_OUT_OF_RANGE` code. Use only the `model_validator` and embed the error_code as the FIRST TOKEN of the raised `ValueError` message (`"AUTO_FOLLOWUP_DEPTH_OUT_OF_RANGE: ..."`). The existing `RequestValidationError` handler at [`backend/app/api/errors.py`](../../../../backend/app/api/errors.py) needs **one additional task** in Story 1.1 (below) to detect this prefix pattern and emit the correct error envelope. Pattern: parse the leading `<ERROR_CODE>:` token from each ValueError's message; if present, use it as the envelope's `error_code`, else fall back to `VALIDATION_ERROR`. This is a small, general-purpose change that benefits any future field-level error codes.

**Tasks:**

1. Create `backend/app/domain/study/auto_followup.py` with `ChainGateDecision`, `ChainGateOutcome`, `compute_first_decile_max`, `evaluate_chain_gate`.
2. Extend `StudyConfigSpec` at [`backend/app/api/v1/schemas.py:556`](../../../../backend/app/api/v1/schemas.py#L556) with the new field + `model_validator` (NOT Field-level `ge`/`le` — see critical note above).
3. Extend the `RequestValidationError` handler at [`backend/app/api/errors.py`](../../../../backend/app/api/errors.py) to parse a `<ERROR_CODE>: ...` prefix from ValueError messages and emit it as the envelope's `error_code`. **Constrained parser** (cycle-2 finding C2-1):
   - Regex: `^(?P<code>[A-Z][A-Z0-9_]{2,63}):\s*(?P<message>.+)$` — only matches all-uppercase-snake-case identifiers of length 3-64.
   - Allowlist: maintain a `frozenset` of recognized custom codes; for MVP1 this is `{"AUTO_FOLLOWUP_DEPTH_OUT_OF_RANGE"}`. The allowlist lives next to the handler as a module-level constant so future features can extend it with a one-line addition.
   - If the regex matches AND the code is in the allowlist → emit `error_code=<parsed_code>`, message=parsed message.
   - Otherwise → fall back to existing `VALIDATION_ERROR` envelope (preserves backwards compatibility).
   - **Regression coverage:** add at least one regression test asserting an EXISTING `StudyConfigSpec` validation failure (e.g., the existing `_require_one_stop_condition` at line 578 — raising `ValueError("studies.config must specify at least one of...")` with no `<CODE>:` prefix) still returns the unchanged `VALIDATION_ERROR` envelope. This locks down that the parser doesn't accidentally consume non-prefixed messages.
4. Add unit tests at `backend/tests/unit/domain/test_auto_followup.py` per spec §14:
   - Lift > epsilon → ENQUEUE (with `lift > epsilon`)
   - Lift ≤ epsilon → SKIP_NO_LIFT
   - `parent.status == 'failed'` → SKIP_PARENT_FAILED
   - `parent.status == 'cancelled'` → SKIP_PARENT_FAILED (defensive)
   - `config.auto_followup_depth == 0` → SKIP_DEPTH_EXHAUSTED
   - `config.auto_followup_depth` missing (`None`) → SKIP_DEPTH_EXHAUSTED (shouldn't fire — digest trigger gates on `is not None` — but defensive)
   - **`parent.best_metric is None`** (cycle-1 finding C1-15) → SKIP_NO_LIFT with `first_decile_max=None`, `lift=None` (cannot compute lift without best_metric)
   - `len(complete_trials) < 10` → first decile = first trial alone (boundary)
   - `len(complete_trials) == 11` → first decile is still 1 trial (per FR-2a floor division semantics — verify ceil/floor distinction with this test)
   - `len(complete_trials) == 0` → defensive: returns SKIP_NO_LIFT with `first_decile_max=None`
5. Extend `backend/tests/unit/api/test_study_config_validation.py` (or equivalent — verify exact filename via `find backend/tests/unit -name "*study_config*"`) with cases for `auto_followup_depth ∈ {None, 0, 1, 5}` (valid) and `{-1, 6, 5.5}` (invalid → ValidationError with envelope `error_code=AUTO_FOLLOWUP_DEPTH_OUT_OF_RANGE`). Per spec §14 note: `'3'` is **valid** (Pydantic v2 coerces).
6. Add a focused contract test at `backend/tests/contract/test_studies_api.py` for the 422 envelope shape — verify `error_code` field equals `AUTO_FOLLOWUP_DEPTH_OUT_OF_RANGE` exactly. This locks down the prefix-parsing behavior added in Task 3.

**Definition of Done:**

- [ ] `backend/app/domain/study/auto_followup.py` exists with the four named exports.
- [ ] `StudyConfigSpec` accepts `auto_followup_depth ∈ {None, 0, 1, 2, 3, 4, 5}` and raises `ValidationError` on `-1` or `6` (verified via unit test).
- [ ] `RequestValidationError` handler in `backend/app/api/errors.py` parses `<ERROR_CODE>:` prefix from ValueError messages and emits as `error_code` in the envelope (verified by Task 6 contract test: POST with depth=6 returns `error_code=AUTO_FOLLOWUP_DEPTH_OUT_OF_RANGE`).
- [ ] `make test-unit && make test-contract` pass the new files end-to-end.
- [ ] `make lint && make typecheck` pass — no new mypy errors.
- [ ] No DB I/O in `auto_followup.py` (grep `import.*session\|from sqlalchemy` returns nothing for the new file).
- [ ] Maps FRs: FR-1, FR-2 (FR-2a active path; FR-2b path noted in docstring), FR-7. (FR-5 is implemented in Story 2.1 — config inheritance is the worker's job, not this story's.)

### Story 1.2 — `narrow_around_winner` domain extraction (FR-4)

**Outcome:** The narrowing math currently inlined in the `propose_search_space` agent tool is extracted into a pure domain function. The agent tool is refactored to call it; output is byte-identical.

**New files:** None.

**Modified files:**

- `backend/app/domain/study/search_space_defaults.py` — add `narrow_around_winner(template_id: str, prior_winning_params: dict[str, Any], bracket: float = 0.5) -> SearchSpace` (extracted logic from the existing agent tool).
- `backend/app/agent/tools/studies/propose_search_space.py` — replace inlined narrowing math (around line 176 — `space, trial.params, bracket=0.5` invocation) with a call to the new domain function. Body shrinks ~30 LOC.

**Endpoints:** None.

**Key interfaces:**

```python
# backend/app/domain/study/search_space_defaults.py — NEW function

def narrow_around_winner(
    template_id: str,
    prior_winning_params: dict[str, Any],
    bracket: float = 0.5,
) -> SearchSpace:
    """Build a SearchSpace narrowed around prior_winning_params.

    Same math as the previous inline implementation at
    backend/app/agent/tools/studies/propose_search_space.py:176 —
    for each numeric param, bound = winner ± |winner| × bracket
    (linear; the legacy implementation handled log-uniform with
    √2-bracket; preserve that logic exactly here).

    Returns: SearchSpace (Pydantic). Cardinality-capped per existing
    SearchSpace.model_validate() at backend/app/domain/study/search_space.py:113.
    """
```

**Tasks:**

1. Read the current narrowing implementation at [`backend/app/agent/tools/studies/propose_search_space.py:130-200`](../../../../backend/app/agent/tools/studies/propose_search_space.py#L130) (the body around the `_narrow` helper or whatever the current factoring is — verify before extracting).
2. Move the math into `backend/app/domain/study/search_space_defaults.py` as `narrow_around_winner`.
3. Refactor `propose_search_space_impl` to call `narrow_around_winner(template_id, trial.params, bracket=0.5)` instead of doing the math inline.
4. Add `backend/tests/unit/domain/test_search_space_narrow.py` — parity test: existing fixtures used by `propose_search_space` tests are loaded; new domain-function output is compared byte-for-byte against the recorded fixtures.
5. Run the existing `backend/tests/unit/agent/test_propose_search_space.py` (or wherever the agent tool's tests live — verify via `find`) to confirm zero output drift.

**Definition of Done:**

- [ ] `narrow_around_winner` exists in `search_space_defaults.py` as a pure (no DB, no async) function.
- [ ] `propose_search_space_impl` body no longer contains the narrowing math; it calls the domain function.
- [ ] Parity test in `test_search_space_narrow.py` passes against the existing agent-tool fixtures.
- [ ] `make test-unit` passes ALL existing search-space tests (agent + domain) without modification.
- [ ] `make lint && make typecheck` pass.
- [ ] Maps FR-4 + D-2.

### Story 1.3 — `list_children_of_study` repo + `cancel_study_with_chain_cascade` service (FR-8)

**Outcome:** New repo function returns direct children of a parent study; new service cancels a parent + recursively cancels in-flight children. The HTTP wiring lands in Story 2.3.

**New files:** None.

**Modified files:**

- `backend/app/db/repo/study.py` — add `list_children_of_study(db, parent_id) -> list[Study]` (filters `parent_study_id == parent_id AND deleted_at IS NULL`, orders `created_at ASC`). Export via `backend/app/db/repo/__init__.py` `__all__`.
- `backend/app/services/study_state.py` — add `cancel_study_with_chain_cascade(db, study_id, *, cascade: bool = True) -> Study` wrapping the existing `cancel_study` at line 172.

**Endpoints:** None directly — Story 2.3 wires the HTTP surface.

**Key interfaces:**

```python
# backend/app/db/repo/study.py — NEW function

async def list_children_of_study(
    db: AsyncSession,
    parent_study_id: str,
) -> Sequence[Study]:
    """Return DIRECT children of parent_study_id (per FR-10 + D-13).
    Filters by parent_study_id match AND deleted_at IS NULL.
    Ordered by created_at ASC (oldest first).
    Returns empty Sequence (not None) for a study with no children."""

# backend/app/services/study_state.py — NEW function

async def cancel_study_with_chain_cascade(
    db: AsyncSession,
    study_id: str,
    *,
    cascade: bool = True,
) -> Study:
    """Cancel a chain rooted at study_id. Per cycle-2 finding C2-5, the
    cascade is TOLERANT of terminal parents — a normal auto-followup chain
    parent is `completed` by the time a child is created (because the
    digest worker fires only on the `completed` transition), so the cascade
    must work even when `cancel_study(parent)` would raise on a terminal
    state.

    Behavior:
      - If `parent.status IN ('queued', 'running')`:
            await cancel_study(db, parent.id)  # transitions parent
      - Otherwise (parent already terminal — `completed`/`cancelled`/`failed`):
            log auto_followup_cancel_terminal_parent (auxiliary event,
            outside FR-9 catalog) and DO NOT attempt the transition.
      - In BOTH cases, when `cascade=True`:
            for each direct child in list_children_of_study(parent.id):
                # Per cycle-3 finding C3-1: recurse into EVERY direct child
                # regardless of status. Intermediate `completed` children act
                # as relay nodes on the way to in-flight grandchildren.
                if child.status IN ('queued', 'running'):
                    await cancel_study(db, child.id)
                    emit auto_followup_cancelled_with_parent (FR-9 event #8)
                else:
                    emit auto_followup_cancel_terminal_parent (auxiliary)
                # Always recurse — a completed child may have a running grandchild
                await cancel_study_with_chain_cascade(db, child.id, cascade=True)

    cascade=False: only attempt the parent transition; do not iterate children.
    On a terminal parent with cascade=False, raises InvalidStateTransition
    (preserves the existing single-cancel error contract — per cycle-3
    finding C3-3 + spec AC-9).

    Idempotency: cancel_study raises InvalidStateTransition on
    cancelled → cancelled; we catch that and continue (covered by Story 1.3
    unit test).

    Returns: the parent Study row (status may be `cancelled` if it was
    in-flight, or unchanged if it was already terminal).
    """
```

**Tasks:**

1. Implement `list_children_of_study` in `backend/app/db/repo/study.py`. Mirror the shape of `list_running_study_ids` at line 141 for the SELECT query style.
2. Export it via `__all__` in `backend/app/db/repo/__init__.py`.
3. Implement `cancel_study_with_chain_cascade` in `backend/app/services/study_state.py`. Place after `cancel_study` at line 172. Use a recursive helper (depth-first traversal).
4. Add `auto_followup_cancelled_with_parent` structlog event inside the recursive child-cancel loop.
5. Add unit tests at `backend/tests/unit/services/test_study_state.py` (extend the existing file). Per cycle-2 finding C2-5, the realistic auto-chain lifecycle has `completed` parent + `running` child, so the test matrix is:
   - **`completed` parent, no children** → cascade is no-op; no `cancel_study` call on parent (terminal); auxiliary event `auto_followup_cancel_terminal_parent` emitted; returns parent row unchanged.
   - **`completed` parent, 1 in-flight child** → no parent transition; child gets cancelled via recursive call; `auto_followup_cancelled_with_parent` emitted for child.
   - **`running` parent, no children** → parent transitions to `cancelled` via `cancel_study`; no cascade activity (matches existing single-cancel behavior).
   - **`running` parent, 2 in-flight children** → parent + both children cancelled (rare edge case; possible if cancel races with chain enqueue).
   - **Depth-3 chain (root completed, mid completed, leaf running)** → only leaf gets the cancel transition; both ancestors emit `auto_followup_cancel_terminal_parent`; final state: root=completed, mid=completed, leaf=cancelled.
   - **Mock with one already-cancelled child** → cascade catches `InvalidStateTransition` from the child's `cancel_study` and continues.
   - **`cascade=False`** → only parent cancel attempted; children list never queried; if parent is terminal, raises `InvalidStateTransition` from `cancel_study` (preserves existing single-cancel error contract).

**Definition of Done:**

- [ ] `list_children_of_study` exists in repo + exported via `__all__`.
- [ ] `cancel_study_with_chain_cascade` exists; routes every child cancel through `cancel_study` (no direct ORM `UPDATE`).
- [ ] All 5 unit-test cases above pass.
- [ ] `make test-unit && make lint && make typecheck` pass.
- [ ] Maps FR-8 (service layer; HTTP surface lands in Story 2.3) + FR-9 event #8.

---

## Epic 2 — Worker layer + API endpoints

**Goal:** The Arq job that builds children, the digest-worker trigger, the cancel-with-cascade HTTP surface, and the children endpoint. After Epic 2, the backend is fully exercising the chain trigger and cascade behavior.

**Gate:** all integration tests in `backend/tests/integration/test_auto_followup.py` and the extended `test_studies_api.py` pass; layer-1 (Arq `_job_id`) dedup verified by integration test.

### Story 2.1 — `enqueue_followup_study` Arq job (FR-3, FR-5, FR-6, FR-9 events 1-7)

**Outcome:** New Arq job function that, given a parent study ID, evaluates the chain gate + budget gate, then either creates a child via `repo.create_study` + enqueues `start_study`, or logs the appropriate skip event.

**New files:**

- `backend/workers/auto_followup.py` — contains `enqueue_followup_study(ctx, parent_study_id: str)` plus a small helper for the budget-check (extracted for unit testability).

**Modified files:**

- `backend/workers/all.py` — register `enqueue_followup_study` in `WorkerSettings.functions` (around line 210 where existing job functions are registered alongside `start_study`, `generate_digest`, etc.). Import at top alongside existing worker imports.

**Endpoints:** None.

**Key interfaces:**

```python
# backend/workers/auto_followup.py

async def enqueue_followup_study(
    ctx: dict[str, Any],
    parent_study_id: str,
) -> None:
    """Build the next chain member if all gates pass.

    Flow (per FR-3 + spec §9 idempotency):
      1. Load parent via repo.get_study. If None → log auto_followup_skipped_parent_missing, return.
      2. LAYER-2 IDEMPOTENCY BACKSTOP (D-11):
         existing = await repo.list_children_of_study(db, parent_study_id)
         if existing:
             log auto_followup_enqueued_duplicate_dropped with existing_child_ids
             return
      3. Load parent_complete_trials via repo.list_trials_for_study + Python-filter
         to trial.status == 'complete'.
      4. evaluate_chain_gate(parent, complete_trials) → ChainGateOutcome.
         - SKIP_NO_LIFT → log auto_followup_skipped_no_lift, return
         - SKIP_PARENT_FAILED → log auto_followup_skipped_parent_failed, return
         - SKIP_DEPTH_EXHAUSTED → log auto_followup_depth_exhausted, return
         - ENQUEUE → proceed
      5. Budget peek:
         peek = await peek_daily_total(redis_client)
         max_cost = estimated_max_call_cost(settings.openai_model)
         if peek + max_cost > 0.8 * settings.openai_daily_budget_usd:
             log auto_followup_skipped_budget, return
      6. Get parent's best trial via repo.get_trial(parent.best_trial_id).
         If None (data anomaly), log skip and return.
      7. Build child SearchSpace via narrow_around_winner(
             template_id=parent.template_id,
             prior_winning_params=best_trial.params,
             bracket=0.5,
         )
      8. Build child_config = {**parent.config, 'auto_followup_depth': parent.config['auto_followup_depth'] - 1}
      9. Build child name: f"{parent.name} (chain depth {parent.config['auto_followup_depth'] - 1})"
     10. Create via repo.create_study(db, name=..., cluster_id=parent.cluster_id, target=...,
         template_id=..., query_set_id=..., judgment_list_id=..., search_space=child_space.model_dump(),
         objective=parent.objective, config=child_config, parent_study_id=parent.id,
         status='queued', optuna_study_name=str(uuid7()))
     11. await db.commit()
     12. Enqueue start_study: try/except around `await ctx['arq_pool'].enqueue_job('start_study', child.id)`.
         Mirror digest worker's existing best-effort pattern at backend/workers/orchestrator.py:452 —
         on failure, log a warning event (use `event_type="digest_followup_start_study_enqueue_failed"`
         to keep the FR-9 catalog stable; cycle-1 finding C1-13). The child row stays as `queued`;
         the existing `on_startup` boot-sweep at backend/workers/all.py:138-151 already enqueues
         `start_study` for queued studies on next worker boot, providing recovery.
     13. Log auto_followup_enqueued with parent + child IDs, remaining_depth, lift, epsilon.

    Resource scope: opens one DB session via get_session_factory(); uses ctx['arq_pool']
    for the start_study enqueue. Creates its OWN Redis client inline for the budget
    peek, mirroring the existing digest worker pattern at
    backend/workers/digest.py:439 (`Redis.from_url(settings.redis_url, decode_responses=False)`)
    — NOT from ctx, since `ctx['redis_client']` is not currently added in on_startup
    (verified 2026-05-23 against `backend/workers/all.py:115-138`). Close the
    Redis client in a try/finally per the digest worker's pattern at line 877.

    Imports (cycle-1 finding C1-10 — be explicit):
        from backend.app.db.repo import trial as trial_repo  # get_trial, list_trials_for_study
        from backend.app.db.repo import study as study_repo  # get_study, create_study, list_children_of_study
        from backend.app.domain.study.auto_followup import evaluate_chain_gate, ChainGateDecision
        from backend.app.domain.study.search_space_defaults import narrow_around_winner
        from backend.app.llm.budget_gate import peek_daily_total
        from backend.app.llm.cost_model import estimated_max_call_cost
    """
```

**Tasks:**

1. Create `backend/workers/auto_followup.py` with `enqueue_followup_study` per the flow above.
2. Use `structlog.get_logger(__name__)` for the logger; emit each event with `event_type=<exact_name>` and the metadata fields listed in spec FR-9.
3. Register the job in `WorkerSettings.functions` at [`backend/workers/all.py`](../../../../backend/workers/all.py) — append `enqueue_followup_study` to the existing `functions=[...]` list. Add to the imports block at line 65-72.
4. Create the Redis client inline at the top of `enqueue_followup_study` body (verified 2026-05-23: digest worker creates its own client at `backend/workers/digest.py:439`; `ctx['redis_client']` is NOT in the worker context — cycle-1 finding C1-11). Use the exact same pattern: `redis_client = Redis.from_url(settings.redis_url, decode_responses=False)` + `await redis_client.aclose()` in a try/finally.
5. **Story 2.1 owns** `backend/tests/integration/test_auto_followup.py`. Add these cases (cycle-1 finding C1-3 — file ownership belongs to one story; Story 2.2 will `extend` this file with one additional test case rather than claiming ownership):
   - Parent completes + lift-passing fixture → child row in DB with correct config + parent_study_id.
   - Budget peek > 80% → no child enqueued (mock `peek_daily_total` to return `0.85 * budget`).
   - `parent.status='failed'` → no child enqueued.
   - Depth-3 chain: parent (depth=3) → child (depth=2) → child (depth=1) → child (depth=0); depth-0 leaf's own enqueue logs `auto_followup_depth_exhausted` and creates no further child (stub `start_study` so child rows persist but don't actually run).
   - **Layer-2 idempotency:** invoke `enqueue_followup_study(ctx, parent_id)` directly twice → second invocation logs `auto_followup_enqueued_duplicate_dropped` and creates no second child.
   - **Layer-1 idempotency (Arq queue):** `arq_pool.enqueue_job("enqueue_followup_study", parent_id, _job_id=f"enqueue_followup_study:{parent_id}")` twice rapidly → second call returns `None`.

**Definition of Done:**

- [ ] `backend/workers/auto_followup.py` exists with `enqueue_followup_study`.
- [ ] Job registered in `WorkerSettings.functions`.
- [ ] 7 distinct structlog `event_type=` values emitted across the function's branches (events 1, 2, 3, 4, 5, 6, 7 per FR-9 catalog — every event except #8 cascade).
- [ ] All 6 integration test cases above pass.
- [ ] `make lint && make typecheck && make test-integration` pass.
- [ ] No direct ORM `UPDATE` on `study.status` (verified by grep: the function only writes `study` via `repo.create_study`, not by mutating loaded rows).
- [ ] Maps FR-3, FR-5, FR-6, FR-7 (worker-side check), FR-9 events 1-7, FR-12 (relies on existing FK).

### Story 2.2 — Digest worker trigger (FR-1 trigger condition)

**Outcome:** The digest worker, after persisting the digest + pending proposal, enqueues `enqueue_followup_study(study_id)` with deterministic `_job_id` when the study has `auto_followup_depth is not None`.

**New files:** None.

**Modified files:**

- `backend/workers/digest.py` — add a new block at the end of `generate_digest` (around line 580-600, after the pending-proposal block ends at the existing `Step 4 + 5 — Pending proposal` comment at line 501): if `study.config.get('auto_followup_depth') is not None`, enqueue the followup job with `_job_id=f"enqueue_followup_study:{study_id}"`.

**Endpoints:** None.

**Key interfaces:**

```python
# Insert near end of generate_digest. Per cycle-1 finding C1-6, the trigger
# block MUST land AFTER both (a) the pending-proposal block ends AND (b) the
# daily-budget peek block at line 554-578 completes. This is so the parent's
# digest LLM call (which the budget peek gates) commits the budget delta
# before the followup gate re-peeks the budget. The exact insertion point is
# the bottom of generate_digest, after the last persistence step and before
# the function returns (verify location by reading the current bottom of the
# function in the implementation step).

# Spec FR-1 + D-12: trigger fires on `is not None` so depth-0 leaf emits
# its own auto_followup_depth_exhausted event.
# Per cycle-1 finding C1-5: the warning events below use `digest_*` event_type
# prefixes (not `auto_followup_*`) so the FR-9 8-event catalog stays exact.
auto_depth = study.config.get('auto_followup_depth')
if auto_depth is not None and study.status == 'completed':
    arq_pool = ctx.get('arq_pool')
    if arq_pool is None:  # Defensive — shouldn't happen post-on_startup
        logger.warning(
            "digest worker: arq_pool missing in ctx; cannot enqueue followup",
            event_type="digest_followup_enqueue_pool_missing",
            study_id=study_id,
        )
    else:
        try:
            await arq_pool.enqueue_job(
                "enqueue_followup_study",
                study_id,
                _job_id=f"enqueue_followup_study:{study_id}",
            )
        except Exception as exc:  # noqa: BLE001 — best-effort, mirrors existing
                                 # `digest_enqueue_failed` pattern at
                                 # backend/workers/orchestrator.py:455
            logger.warning(
                "digest worker: followup enqueue failed; chain ends here",
                event_type="digest_followup_enqueue_failed",
                study_id=study_id,
                error=str(exc),
            )
```

**Tasks:**

1. Locate the insertion point in `backend/workers/digest.py`: the trigger MUST land at the **very bottom** of `generate_digest`, AFTER (a) the pending-proposal block ends, (b) the existing daily-budget peek block at line 554-578 completes, AND (c) any subsequent persistence steps. Per cycle-1 finding C1-6, ordering matters: the parent's digest LLM call commits its budget delta via `_safe_record_cost` at line 853 (verified by grep); the followup trigger re-peeks the budget *inside* `enqueue_followup_study` (FR-6), so the trigger must fire after the parent's cost is recorded, otherwise the followup's gate sees a stale budget. The simplest location is immediately before the closing `await redis_client.aclose()` at line 877 (insert before the `try/finally`'s `finally:` block, NOT after — we want the Redis client still open if we ever need to read it during the trigger, though the current design creates a fresh client inside `enqueue_followup_study`).
2. Add the trigger block per the JSX above. Use the deterministic `_job_id` per spec §9 layer-1 idempotency.
3. **Extend** `backend/tests/integration/test_auto_followup.py` (owned by Story 2.1) with one additional integration test (NO new file ownership — see cycle-1 finding C1-3): a parent study completes → `generate_digest(ctx, study_id)` is invoked → assert `arq_pool.enqueue_job` was called exactly once with the deterministic `_job_id`.
4. Document the trigger in the function's module docstring at the top of `digest.py`.

**Definition of Done:**

- [ ] Trigger block in `generate_digest` fires on `auto_followup_depth is not None` AND `status == 'completed'`.
- [ ] Uses `_job_id=f"enqueue_followup_study:{study_id}"` (verified by integration test).
- [ ] Studies with `auto_followup_depth is None` do NOT trigger the followup job (negative test).
- [ ] Failed-study digest path (which doesn't run per AC-6) does not invoke the trigger.
- [ ] `make test-integration` passes.
- [ ] Maps FR-1 (trigger side) + D-12.

### Story 2.3 — Cancel cascade endpoint + Children endpoint + Telemetry event #8

**Outcome:** `POST /api/v1/studies/{id}/cancel?cascade=<bool>` extends the existing endpoint; `GET /api/v1/studies/{id}/children` is a new sub-resource endpoint. Telemetry event #8 (`auto_followup_cancelled_with_parent`) fires inside the cascade service called by the new endpoint path.

**New files:** None.

**Modified files:**

- `backend/app/api/v1/studies.py` — extend the existing `cancel_study` endpoint at [`backend/app/api/v1/studies.py:463-475`](../../../../backend/app/api/v1/studies.py#L463) with optional `?cascade=` query param. Add new `list_study_children` endpoint.

**Endpoints:**

| Method | Path | Request | Success (200) | Error codes |
|---|---|---|---|---|
| `POST` | `/api/v1/studies/{study_id}/cancel?cascade=<bool>` | empty body, `?cascade=` query (default `true`) | `StudyDetail` shape (existing) | `404 STUDY_NOT_FOUND`, `409 INVALID_STATE_TRANSITION`, `400 INVALID_CASCADE_PARAM` |
| `GET` | `/api/v1/studies/{study_id}/children` | none | `{ "data": list[StudySummary], "next_cursor": null }` | `404 STUDY_NOT_FOUND` |

**Pydantic schemas:**

```python
# backend/app/api/v1/schemas.py — REUSE existing StudyListResponse for children endpoint
# (already shaped {data: list[StudySummary], next_cursor: str | None} at line 664-668)

# No new request/response models needed.
```

**Key interfaces:**

```python
# backend/app/api/v1/studies.py — REPLACE existing cancel_study handler

@router.post(
    "/studies/{study_id}/cancel",
    response_model=StudyDetail,
    status_code=status.HTTP_200_OK,
)
async def cancel_study(
    study_id: str,
    cascade: bool = Query(default=True, description="If True (default), also cancel in-flight chain children."),
    db: AsyncSession = Depends(get_db),
) -> StudyDetail:
    """Cancel a queued/running study + (optionally) cascade to in-flight children.

    Routes through services.study_state.cancel_study_with_chain_cascade.
    """
    try:
        row = await study_state.cancel_study_with_chain_cascade(
            db, study_id, cascade=cascade
        )
        await db.commit()
    except study_state.StudyNotFound:
        raise HTTPException(status_code=404, detail={
            "error_code": "STUDY_NOT_FOUND",
            "message": f"study {study_id} not found",
            "retryable": False,
        })
    except study_state.InvalidStateTransition as exc:
        raise HTTPException(status_code=409, detail={
            "error_code": "INVALID_STATE_TRANSITION",
            "message": str(exc),
            "retryable": False,
        })
    return _serialize_study_detail(row)

# Custom cascade parser: FastAPI's default 422 for non-bool would conflict
# with our error catalog. Override with explicit 400 INVALID_CASCADE_PARAM.
# Implementation: catch ValueError from Query coercion in the existing
# RequestValidationError handler at backend/app/api/errors.py and check if
# the failing field is 'cascade' → re-raise as 400 with our envelope.
# Alternative: a custom Depends() that parses str → bool with explicit
# error handling. Pick the dependency-based approach for clarity:

async def parse_cascade(cascade: str = Query(default="true")) -> bool:
    """Parse cascade query param case-insensitively. Default true.
    Raises 400 INVALID_CASCADE_PARAM on invalid input."""
    normalized = cascade.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise HTTPException(status_code=400, detail={
        "error_code": "INVALID_CASCADE_PARAM",
        "message": "?cascade= must be one of: true, false (case-insensitive)",
        "retryable": False,
    })

# Then in cancel_study signature: cascade: bool = Depends(parse_cascade)

# NEW endpoint:

@router.get(
    "/studies/{study_id}/children",
    response_model=StudyListResponse,  # existing
)
async def list_study_children(
    study_id: str,
    db: AsyncSession = Depends(get_db),
) -> StudyListResponse:
    """List direct child studies of a parent (per FR-10 + D-13).
    Returns empty data array (not 404) for childless study; 404 only
    if the parent study itself is missing."""
    parent = await repo.get_study(db, study_id)
    if parent is None:
        raise HTTPException(status_code=404, detail={
            "error_code": "STUDY_NOT_FOUND",
            "message": f"study {study_id} not found",
            "retryable": False,
        })
    children = await repo.list_children_of_study(db, study_id)
    return StudyListResponse(
        data=[_serialize_study_summary(c) for c in children],
        next_cursor=None,  # depth ≤ 5 → no pagination
    )
```

**Tasks:**

1. Replace the existing `cancel_study` handler at [`backend/app/api/v1/studies.py:463-475`](../../../../backend/app/api/v1/studies.py#L463) with the new version routing through `cancel_study_with_chain_cascade`.
2. Add the `parse_cascade` dependency function above the handler.
3. Add `list_study_children` handler in the same router file.
4. Register the new endpoint with `@router.get(...)` decorator (the router is already imported at the file top).
5. Add contract tests at `backend/tests/contract/test_studies_api.py` (extend). Per cycle-3 finding C3-3, scenarios must match the realistic chain lifecycle (parent typically `completed` when child is in-flight):
   - **`cancel?cascade=true` on in-flight parent** (rare race-only edge case) → 200 + parent cancelled + children cancelled.
   - **`cancel?cascade=true` on completed parent with in-flight grandchild** (realistic chain) → 200 + parent unchanged (`completed`) + intermediate completed children unchanged + leaf in-flight child cancelled. `auto_followup_cancel_terminal_parent` emitted for each terminal ancestor traversed; FR-9 event #8 emitted for the leaf cancel.
   - **`cancel?cascade=false` on in-flight parent** → 200 + only parent cancelled.
   - **`cancel?cascade=false` on completed parent** → 409 `INVALID_STATE_TRANSITION` (preserves existing single-cancel contract; per AC-9).
   - `cancel?cascade=invalid` → 400 `INVALID_CASCADE_PARAM` with canonical envelope.
   - `GET /children` returns `{ "data": [], "next_cursor": null }` for childless.
   - `GET /children` of unknown study → 404 `STUDY_NOT_FOUND`.
   - `POST /studies` with `config.auto_followup_depth=6` → 422.
   - `config.auto_followup_depth=3` round-trips through GET.
6. Add `auto_followup_cancelled_with_parent` structlog event inside `cancel_study_with_chain_cascade` (Story 1.3's function) — verified by integration test that captures structlog output via `pytest-structlog` or the existing `caplog` pattern.
7. Add integration test at `backend/tests/integration/test_studies_api.py` (extend) for the cascade behavior (per spec §14).
8. Add NEW integration test file `backend/tests/integration/test_study_children_endpoint.py` (per spec §14 + cycle-1 finding C1-4) covering:
   - `GET /studies/{id}/children` for a parent with 0 children → empty data array.
   - `GET /studies/{id}/children` for a parent with 1 direct child → single-row data array.
   - `GET /studies/{id}/children` for a depth-3 chain root → only the direct child returned (NOT transitive descendants — per D-13).
   - `GET /studies/{id}/children` for a missing parent → 404 `STUDY_NOT_FOUND`.

**Definition of Done:**

- [ ] `cancel_study` endpoint accepts `?cascade=` and routes through the cascade service.
- [ ] `list_study_children` endpoint exists and returns `StudyListResponse` shape.
- [ ] All 7 contract test cases above pass.
- [ ] Integration test for depth-3 cascade passes (parent + 2 in-flight children all cancelled).
- [ ] FR-9 event #8 `auto_followup_cancelled_with_parent` emitted per cascaded child (verified by structlog capture).
- [ ] `make test-contract && make test-integration && make lint && make typecheck` pass.
- [ ] Maps FR-8 (HTTP surface), FR-10 (children endpoint), FR-9 event #8.

---

## Epic 3 — Frontend (chain panel + wizard depth + cancel modal)

**Goal:** Operator-visible surfaces — the auto-chain panel on the study-detail page, the depth selector in the wizard, the cascade radio in the cancel modal, plus 4 new glossary entries.

**Gate:** `cd ui && pnpm lint && pnpm typecheck && pnpm test && pnpm build` pass; E2E spec `ui/tests/e2e/auto-followup.spec.ts` passes against the real backend.

### Plan-level UI Guidance (REQUIRED — applies to Stories 3.1, 3.2, 3.3)

**Insertion points:**

1. **Auto-followup chain panel** — Mounted on `/studies/[id]` page at [`ui/src/app/studies/[id]/page.tsx`](../../../../ui/src/app/studies/%5Bid%5D/page.tsx). Insert between the existing `<StudyHeader>` (top) and the trials section. Conditional render: only shows when (a) `study.parent_study_id IS NOT NULL` OR (b) `study.config.auto_followup_depth > 0` OR (c) `children.length > 0`.

2. **Wizard depth selector** — Mounted in [`ui/src/components/studies/create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx) at the existing stop-conditions section (around line 199-260 where `max_trials` / `time_budget_min` form fields are defined). Insert AFTER the existing preset block but BEFORE the closing `</fieldset>` of stop conditions.

3. **Cancel modal** — Extend the existing `study-action-bar.tsx` cancel button at [`ui/src/components/studies/study-action-bar.tsx:24`](../../../../ui/src/components/studies/study-action-bar.tsx#L24) to open a confirm modal in ALL cases (uniform UX). The cascade radio is **shown** when ANY of:
   - The study has at least one in-flight (`status IN ('queued', 'running')`) child — checked via the fetched children list.
   - The study has `config.auto_followup_depth > 0` AND `status === 'running'` (anticipated child) — per spec FR-8 + cycle-1 finding C1-8.

   The radio defaults to "Cancel parent + in-flight children" (per D-6) when shown.

   The cascade radio is **hidden** when neither condition holds; the underlying API call still goes to `POST /cancel?cascade=true` (the API default; no observable behavior change for non-chain studies because cascade is a no-op when `list_children_of_study` returns empty).

**Analogous markup patterns** — actual JSX copied from existing components:

**Panel structure (mirror `confidence-panel.tsx` pattern):**

```tsx
// ui/src/components/studies/auto-followup-chain-panel.tsx — NEW
'use client';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { GlossaryTooltip } from '@/components/common/glossary-tooltip';
import type { StudyDetail, StudySummary } from '@/lib/types';

interface AutoFollowupChainPanelProps {
  study: StudyDetail;
  children: StudySummary[];  // from GET /studies/{id}/children
}

export function AutoFollowupChainPanel({ study, children }: AutoFollowupChainPanelProps) {
  const hasContent =
    study.parent_study_id !== null ||
    (study.config?.auto_followup_depth ?? 0) > 0 ||
    children.length > 0;

  if (!hasContent) return null;

  const remaining = study.config?.auto_followup_depth ?? 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <GlossaryTooltip term="auto_followup_chain">
            Auto-followup chain
          </GlossaryTooltip>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {study.parent_study_id && (
          <p>Parent: <Link href={`/studies/${study.parent_study_id}`}>view parent</Link></p>
        )}
        {remaining > 0 && (
          <p>Remaining auto-follow-ups: {remaining}</p>
        )}
        {children.length > 0 && (
          <ChildrenTable rows={children} />
        )}
      </CardContent>
    </Card>
  );
}
```

**Children table (reuse `DataTable` primitive at `ui/src/components/common/data-table.tsx`):**

```tsx
// Inside ChildrenTable — define a column config + render <DataTable>
// Pattern follows ui/src/components/studies/studies-table.column-config.tsx
const columns: ColumnConfig<StudySummary>[] = [
  { id: 'name', header: 'Name', accessor: (r) => r.name, /* clickable link cell */ },
  { id: 'status', header: 'Status', accessor: (r) => <StatusBadge value={r.status} />,
    filter: { kind: 'enum', sourceOfTruth: 'backend/app/db/models/study.py StudyStatus' } },
  { id: 'best_metric', header: 'Best metric', accessor: (r) => r.best_metric?.toFixed(4) ?? '—' },
  { id: 'created_at', header: 'Created', accessor: (r) => formatRelative(r.created_at) },
];
```

**Wizard depth selector (mirror existing preset-selector pattern at create-study-modal.tsx:83-260):**

```tsx
// Inside create-study-modal.tsx, after the existing preset block:

// Source-of-truth: backend/app/api/v1/schemas.py StudyConfigSpec.auto_followup_depth
// Wire allowlist: None, 0..5 (per spec FR-1 + D-12). Wizard-0 is the OFF
// sentinel that submits as undefined (not wire-0). Wire-0 is reserved for
// worker decrement.
const AUTO_FOLLOWUP_DEPTH_WIZARD_VALUES = [0, 1, 2, 3, 4, 5] as const;
const AUTO_FOLLOWUP_DEPTH_LABELS: Record<number, string> = {
  0: 'Off',
  1: '1 follow-up',
  2: '2 follow-ups',
  3: '3 follow-ups',
  4: '4 follow-ups',
  5: '5 follow-ups',
};

<FormField
  control={form.control}
  name="auto_followup_depth"
  render={({ field }) => (
    <FormItem>
      <FormLabel>
        <GlossaryTooltip term="auto_followup_depth">
          Auto-followup chain
        </GlossaryTooltip>
      </FormLabel>
      <Select
        value={String(field.value ?? 0)}
        onValueChange={(v) => {
          const n = parseInt(v, 10);
          // Map wizard-0 sentinel to undefined (omit from config)
          field.onChange(n === 0 ? undefined : n);
        }}
      >
        <SelectTrigger><SelectValue /></SelectTrigger>
        <SelectContent>
          {AUTO_FOLLOWUP_DEPTH_WIZARD_VALUES.map((n) => (
            <SelectItem key={n} value={String(n)}>
              {AUTO_FOLLOWUP_DEPTH_LABELS[n]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <FormDescription>
        Run follow-up studies that narrow around the winner's params. Halts
        on no lift, exhausted budget, or failed parent.
      </FormDescription>
    </FormItem>
  )}
/>
```

**Cancel modal cascade radio (extend existing study-action-bar.tsx):**

```tsx
// ui/src/components/studies/cancel-study-confirm-modal.tsx — NEW
// Pattern mirrors ui/src/components/clusters/cluster-delete-confirm-modal.tsx
// (existing from chore_cluster_delete_ui shipped 2026-05-13)

interface CancelStudyConfirmModalProps {
  studyId: string;
  studyStatus: string;  // determines button label: 'running' → "Cancel study"; 'completed' → "Stop chain" per C2-5
  showCascadeRadio: boolean;  // per FR-8 + cycle-1 C1-8: hasInFlightChildren OR (auto_followup_depth > 0 AND status === 'running')
  isOpen: boolean;
  onClose: () => void;
}

export function CancelStudyConfirmModal({ studyId, showCascadeRadio, isOpen, onClose }: ...) {
  const [cascade, setCascade] = useState(true);  // D-6: default true when shown
  const cancel = useCancelStudy(studyId);

  // Per cycle-3 finding C3-4: label adapts based on parent's terminal state.
  // Terminal parents (completed/failed/cancelled) with in-flight DIRECT children
  // render "Stop chain" since there is no parent transition to make. For "stop
  // a chain from a completed root with a deep in-flight descendant," operator
  // navigates to the in-flight node — documented as known UX limitation in
  // docs/03_runbooks/auto-followup-debugging.md (Story 4.1).
  const isParentTerminal = ['completed', 'cancelled', 'failed'].includes(studyStatus);
  const title = isParentTerminal && showCascadeRadio ? 'Stop chain?' : 'Cancel study?';
  const buttonLabel = isParentTerminal && showCascadeRadio ? 'Stop chain' : 'Cancel study';

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        {showCascadeRadio && (
          <RadioGroup value={cascade ? 'true' : 'false'} onValueChange={(v) => setCascade(v === 'true')}>
            <div>
              <RadioGroupItem value="true" id="cascade-true" />
              <Label htmlFor="cascade-true">
                {isParentTerminal ? 'Cancel all in-flight chain members' : 'Cancel parent + in-flight children'}
              </Label>
            </div>
            <div>
              <RadioGroupItem value="false" id="cascade-false" />
              <Label htmlFor="cascade-false">
                {isParentTerminal ? 'Do nothing (chain already terminal at this node)' : 'Cancel parent only'}
              </Label>
            </div>
          </RadioGroup>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Keep running</Button>
          <Button variant="destructive" onClick={() => cancel.mutate({ cascade })}>
            {buttonLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// In study-action-bar.tsx, the showCascadeRadio prop is computed:
//   const showCascadeRadio = useMemo(() =>
//     children.some(c => c.status === 'queued' || c.status === 'running')
//     || (study.status === 'running' && (study.config?.auto_followup_depth ?? 0) > 0),
//     [children, study.status, study.config?.auto_followup_depth]
//   );
// This requires study-action-bar.tsx to receive `children` from the page —
// see Story 3.3 task list for the prop-drilling refactor.
```

**Visual consistency table:**

| New UI element | CSS class / pattern source |
|---|---|
| `<AutoFollowupChainPanel>` card | `confidence-panel.tsx` (shadcn Card primitive) |
| Children table | `data-table.tsx` (`<DataTable>` primitive from `feat_data_table_primitive`) |
| Depth selector `<Select>` | `create-study-modal.tsx` existing preset selector (line 83+) — same shadcn `<Select>` primitive |
| Cancel modal | `cluster-delete-confirm-modal.tsx` (existing pattern from `chore_cluster_delete_ui`) |
| `GlossaryTooltip` for new terms | `ui/src/components/common/glossary-tooltip.tsx` (existing from `feat_contextual_help`) |

**Component composition:** All new components are inline modules (no shared primitive needed beyond what exists). Rationale: the chain panel is the only multi-element new card and is study-detail-page-specific.

**Interaction behavior table:**

| User action | Frontend behavior | API call |
|---|---|---|
| Open study detail page with chain context | Fetch `GET /studies/{id}` (existing) + `GET /studies/{id}/children` (NEW); render panel conditionally | 2 GETs |
| Select "3 follow-ups" in wizard | Update form state to `auto_followup_depth: 3` | None (submit-time) |
| Submit wizard with depth=3 | `POST /api/v1/studies` with `config.auto_followup_depth: 3` | 1 POST (existing) |
| Click "Cancel study" button (with chain context) | Open modal | None |
| Click "Cancel study" button (no chain context) | Open modal (uniform UX) with cascade radio hidden | None |
| Confirm cancel with radio=cascade | `POST /studies/{id}/cancel?cascade=true` | 1 POST (extended) |
| Confirm cancel with radio=parent-only | `POST /studies/{id}/cancel?cascade=false` | 1 POST (extended) |

**Handler function patterns:**

```tsx
// ui/src/lib/api/studies.ts — EXTEND existing cancelStudy + useCancelStudy
// (BOTH live in this file — verified 2026-05-23: useCancelStudy is at
// ui/src/lib/api/studies.ts:113 with current signature
// `UseMutationResult<StudyDetail, ApiError, void>`. NOT in ui/src/lib/hooks/.
// Cycle-1 finding C1-9.)
//
// Before this story:
//   - cancelStudy(id) calls POST /cancel with empty body, returns StudyDetail.
//   - useCancelStudy(id) returns UseMutationResult<StudyDetail, ApiError, void>
//     (no mutation arg).
// After this story:
//   - cancelStudy(id, options?) accepts optional { cascade?: boolean }, default true.
//   - useCancelStudy(id) returns UseMutationResult<StudyDetail, ApiError, { cascade?: boolean }>.
//
// This is a TYPE SIGNATURE BREAKING CHANGE for any caller that did
// `cancel.mutate()` (with no arg). Since the new variant defaults to `{}`,
// the call `cancel.mutate({})` works; `cancel.mutate(undefined)` does NOT
// type-check. Inventory existing callers:
//   - ui/src/components/studies/study-action-bar.tsx:24 — only caller (replaced
//     by the modal in Story 3.3); no other callers per
//     `grep -rn "useCancelStudy" ui/src --include "*.tsx" --include "*.ts"`.

export async function cancelStudy(
  id: string,
  options: { cascade?: boolean } = {}
): Promise<StudyDetail> {
  const cascadeParam = options.cascade ?? true;
  const { data } = await apiClient.post<StudyDetail>(
    `/api/v1/studies/${id}/cancel?cascade=${cascadeParam}`,
    {}
  );
  return data;
}

export function useCancelStudy(
  id: string
): UseMutationResult<StudyDetail, ApiError, { cascade?: boolean }> {
  return useMutation({
    mutationFn: (vars: { cascade?: boolean } = {}) => cancelStudy(id, vars),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['study', id] });
      queryClient.invalidateQueries({ queryKey: ['studies'] });
      // NEW: also invalidate children list since cascade may have changed children's status
      queryClient.invalidateQueries({ queryKey: ['study-children', id] });
    },
  });
}

// ui/src/lib/api/studies.ts — NEW function
export async function listStudyChildren(studyId: string): Promise<StudyListResponse> {
  const { data } = await apiClient.get<StudyListResponse>(
    `/api/v1/studies/${studyId}/children`
  );
  return data;
}
```

**Information architecture placement:**

- **Chain panel:** mounted between `<StudyHeader>` and trials/digest sections on `/studies/[id]` page. Always renders at the same vertical position; visibility is content-driven. Aligns with spec §11 (panel is a new section, not a tab; not progressive disclosure beyond the conditional render).
- **Wizard depth selector:** sits inside the existing stop-conditions fieldset of the create-study modal, adjacent to `max_trials` / `time_budget_min`. Same visual weight as those numeric fields. Aligns with spec §11.
- **Cancel modal:** replaces the existing direct-cancel handler. The modal always opens (for UX consistency), but the cascade radio is hidden when no chain context exists. Aligns with spec §11 + D-6 (default radio = cancel-with-cascade).

**Tooltips and contextual help** (per spec §11 tooltip inventory):

| Element | Tooltip text | Trigger | Placement | Glossary key | Source-of-truth comment |
|---|---|---|---|---|---|
| Wizard depth selector label | "Run up to N follow-up studies after this one completes. Each follow-up narrows the search space around the winner. Halts on no lift, exhausted budget, or failed parent." | hover on info icon next to label | right | `auto_followup_depth` | `// Source-of-truth: docs/02_product/planned_features/feat_auto_followup_studies/feature_spec.md FR-1` |
| Chain panel title | "RelyLoop ran follow-up studies automatically based on this study's winner. Each follow-up narrowed the search bounds; the chain ends when there's no further lift." | hover on info icon next to title | right | `auto_followup_chain` | (same path, FR-10) |
| Lift-gate explainer (inline in `auto_followup_chain` long form) | "A follow-up only enqueues when the parent's winner beat the first-decile baseline by at least 0.5%. Smaller lifts are likely noise." | hover on info icon | inline | `lift_gate` | (same path, FR-2) |
| Wizard depth-gate (when daily budget low) | "Daily LLM budget is at {N}% — chains may be skipped." | inline below selector | inline | `auto_followup_budget_skip` | (same path, FR-6) |

Glossary keys are added to [`ui/src/lib/glossary.ts`](../../../../ui/src/lib/glossary.ts) in Story 3.1.

**Legacy behavior parity:** N/A — no UI components are being deleted or replaced. All UI is additive (new panel, new wizard field, new modal). The existing direct-cancel-button behavior in `study-action-bar.tsx` is replaced by the modal-opening behavior, but the underlying API call is preserved with the same default semantics (cascade=true is the API default that matches the previous behavior for non-chain studies, where cascade is a no-op).

### Story 3.1 — Glossary entries + Auto-followup chain panel (FR-10 frontend)

**Outcome:** 4 new glossary keys are added to `ui/src/lib/glossary.ts`. The `<AutoFollowupChainPanel>` component renders on the study-detail page when chain context is present.

**New files:**

- `ui/src/components/studies/auto-followup-chain-panel.tsx` — the panel component per the UI guidance JSX above.
- `ui/src/__tests__/components/studies/auto-followup-chain-panel.test.tsx` — vitest covering render conditions, parent link rendering, remaining-depth rendering, children table rendering.

**Modified files:**

- `ui/src/lib/glossary.ts` — add 4 new keys (`auto_followup_depth`, `auto_followup_chain`, `lift_gate`, `auto_followup_budget_skip`) per the tooltip table above. Each must follow the `GlossaryEntryDual` shape (short + long) per the existing `GlossaryEntry` types (line 19-32).
- `ui/src/app/studies/[id]/page.tsx` — fetch children via TanStack Query + mount `<AutoFollowupChainPanel>` above the trials section.
- `ui/src/lib/api/studies.ts` — add `listStudyChildren(studyId)` per the handler pattern above.

**UI element inventory** (creation story):

| Element | Type | Label | Data source | Interactions |
|---|---|---|---|---|
| Chain panel card | Card | "Auto-followup chain" | `study.parent_study_id`, `study.config.auto_followup_depth`, `children` | (none — display only) |
| Parent link | Link | "Parent: view parent" | `study.parent_study_id` | Click → navigate to parent study detail |
| Remaining depth line | Text | "Remaining auto-follow-ups: N" | `study.config.auto_followup_depth` | (none) |
| Children table | DataTable | (columns: Name / Status / Best metric / Created) | `children` from `GET /studies/{id}/children` | Row click → navigate to child study detail |

**State dependency analysis:** N/A — no shared state being moved. `children` is a new server-state slice fetched via TanStack Query with key `['study-children', studyId]`.

**Tasks:**

1. Add the 4 glossary entries to `ui/src/lib/glossary.ts` following the `GlossaryEntryDual` shape. Each `long` field contains the long-form explanation referenced from the spec §11 tooltip column.
2. Verify the existing `ui/src/__tests__/lib/glossary.test.ts` enforcement test still passes after the additions (the test enforces all keys have valid shape per the file's comment at line 11).
3. Create `auto-followup-chain-panel.tsx` per the JSX pattern in UI Guidance.
4. Create the children table using the existing `<DataTable>` primitive at `ui/src/components/common/data-table.tsx`. Column config per the pattern in `studies-table.column-config.tsx`.
5. Add `listStudyChildren` to `ui/src/lib/api/studies.ts`.
6. Mount the panel in `ui/src/app/studies/[id]/page.tsx` — use TanStack Query `useQuery({ queryKey: ['study-children', studyId], queryFn: () => listStudyChildren(studyId) })`. Conditionally render the panel (the component already handles the empty case by returning `null`).
7. Add vitest at `ui/src/__tests__/components/studies/auto-followup-chain-panel.test.tsx`:
   - Render with `study.parent_study_id=null, config.auto_followup_depth=undefined, children=[]` → returns `null` (no DOM output).
   - Render with `parent_study_id=P` → "Parent" link present.
   - Render with `auto_followup_depth=2` → "Remaining auto-follow-ups: 2" text present.
   - Render with `children=[1 row]` → DataTable renders one row.

**Definition of Done:**

- [ ] 4 glossary entries added; `pnpm test ui/src/__tests__/lib/glossary.test.ts` passes.
- [ ] `<AutoFollowupChainPanel>` component renders per the 4 vitest cases above.
- [ ] `listStudyChildren` API helper exists; `GET /api/v1/studies/{id}/children` is reachable from the frontend.
- [ ] Panel mounts on `/studies/[id]` page; visible when chain context exists; hidden otherwise.
- [ ] `cd ui && pnpm lint && pnpm typecheck && pnpm test && pnpm build` pass.
- [ ] Maps FR-10 (frontend half).

### Story 3.2 — Wizard depth selector (FR-11)

**Outcome:** The create-study modal includes a depth selector in the stop-conditions section. Wizard-0 maps to `undefined` on submit (omit `auto_followup_depth` from `config`); 1-5 set it directly.

**New files:** None.

**Modified files:**

- `ui/src/components/studies/create-study-modal.tsx` — extend the form schema, defaultValues, and render block per the UI Guidance JSX above.
- `ui/src/__tests__/components/studies/create-study-modal.auto-followup.test.tsx` — NEW vitest file covering the depth selector.

**UI element inventory:**

| Element | Type | Label | Data source | Interactions |
|---|---|---|---|---|
| Depth selector | `<Select>` (shadcn) | "Auto-followup chain" with info-icon tooltip | form state `auto_followup_depth` (default 0 = "Off") | Change → `form.setValue('auto_followup_depth', n === 0 ? undefined : n)` |

**Enumerated value contract:**

- **Backend allowlist:** `None | 0 | 1 | 2 | 3 | 4 | 5` per `StudyConfigSpec.auto_followup_depth` validator (Story 1.1).
- **Frontend wire values:** `undefined | 1 | 2 | 3 | 4 | 5` — wizard never sends wire-`0`; the `0` sentinel maps to `undefined` (omit field).
- **Source-of-truth comment** above the values array: `// Source-of-truth: backend/app/api/v1/schemas.py StudyConfigSpec.auto_followup_depth`.

**State dependency analysis:** N/A — purely additive form field; no existing state is moved or removed.

**Tasks:**

1. Extend the form schema in `create-study-modal.tsx` (the React Hook Form `useForm({ ... })` call around line 165) with `auto_followup_depth: z.number().int().min(1).max(5).optional()`.
2. Extend `defaultValues` (line 173 area) with `auto_followup_depth: undefined`.
3. Add the `<FormField>` block per the UI Guidance JSX after the existing preset block (around line 260).
4. Add the source-of-truth comment + values array per the UI Guidance.
5. Run `pnpm test ui/src/__tests__/components/common/form-select-discipline.test.tsx` — this is the lint guard from CLAUDE.md "Form dropdown primitive" section that scans for inline `<SelectItem value="..."` patterns without a source-of-truth comment. There is NO separate `pnpm lint:enum-discipline` script (verified 2026-05-23 against `ui/package.json`; cycle-1 finding C1-14). The discipline test is part of the standard vitest suite.
6. Add vitest at `auto-followup.test.tsx`:
   - Default state: dropdown shows "Off", form value is `undefined`.
   - Select "3 follow-ups" → form value becomes `3`.
   - Select "Off" after a non-zero value → form value becomes `undefined` (not `0`).
   - Submit with depth=3 → `config.auto_followup_depth=3` in submitted body.
   - Submit with depth=0 (Off) → `config` body has NO `auto_followup_depth` key.

**Definition of Done:**

- [ ] Depth selector renders in the create-study modal.
- [ ] All 5 vitest cases above pass.
- [ ] `pnpm test ui/src/__tests__/components/common/form-select-discipline.test.tsx` passes (no source-of-truth violations).
- [ ] `cd ui && pnpm lint && pnpm typecheck && pnpm test && pnpm build` pass.
- [ ] Maps FR-11.

### Story 3.3 — Cancel modal cascade radio + E2E test (FR-8 frontend, FR-11 cancel UX)

**Outcome:** The cancel-study button on `study-action-bar.tsx` opens a confirm modal. The modal includes a cascade radio (default = "Cancel parent + in-flight children" per D-6) when the study has chain context. The frontend cancel API integration accepts the cascade arg. One E2E spec exercises the full flow.

**New files:**

- `ui/src/components/studies/cancel-study-confirm-modal.tsx` — per the UI Guidance JSX above.
- `ui/src/__tests__/components/studies/cancel-study-confirm-modal.test.tsx` — vitest for modal behavior.
- `ui/tests/e2e/auto-followup.spec.ts` — NEW E2E spec per spec §14.

**Modified files:**

- `ui/src/components/studies/study-action-bar.tsx` — replace the direct `cancel.mutate()` call at the Cancel button with `setIsModalOpen(true)`; mount `<CancelStudyConfirmModal>` in the action bar's JSX.
- `ui/src/lib/api/studies.ts` — extend `cancelStudy(id, options?)` to accept `{ cascade?: boolean }` AND update `useCancelStudy` signature to `UseMutationResult<StudyDetail, ApiError, { cascade?: boolean }>` (both functions live in this same file; verified at line 113. Cycle-1 finding C1-9 — there is NO separate `ui/src/lib/hooks/useCancelStudy.ts` file). Invalidate the `study-children` query key on success.

**Endpoints:** None new — uses `POST /api/v1/studies/{id}/cancel?cascade=<bool>` from Story 2.3.

**Tasks:**

1. Create `cancel-study-confirm-modal.tsx` per the UI Guidance JSX.
2. Refactor `study-action-bar.tsx` to (a) receive `chainChildren: StudySummary[]` (NOT `children` — that collides with React's built-in `children` prop name, cycle-2 finding C2-4) as a new prop from `/studies/[id]/page.tsx`, (b) compute `showCascadeRadio = chainChildren.some(c => c.status === 'queued' || c.status === 'running') || (study.status === 'running' && (study.config?.auto_followup_depth ?? 0) > 0)` per cycle-1 finding C1-8 + spec FR-8, (c) replace the direct `cancel.mutate()` call with `setIsModalOpen(true)`, (d) mount `<CancelStudyConfirmModal>` with the computed prop. **Caller inventory** (verified 2026-05-23 via `grep -rn "<StudyActionBar\|StudyActionBar(" ui/src/`): exactly **one caller** at `ui/src/app/studies/[id]/page.tsx:71` — `<StudyActionBar study={study} />`. That call site updates to pass `chainChildren={children}` where `children` is the local query-state variable from `useQuery(['study-children', ...])`. No other callers; no test fixtures need updating since the existing component vitest files mock the bar directly.
3. Extend `cancelStudy` API helper + `useCancelStudy` mutation hook per UI Guidance (single file: `ui/src/lib/api/studies.ts` — verified at line 113).
4. Add vitest at `cancel-study-confirm-modal.test.tsx`:
   - Renders modal with cascade radio HIDDEN when `showCascadeRadio=false`.
   - Renders modal with cascade radio SHOWN + default "Cancel parent + in-flight children" selected when `showCascadeRadio=true`.
   - Clicking "Cancel study" with radio=cascade calls `mutate({ cascade: true })`.
   - Clicking "Cancel study" with radio=parent-only calls `mutate({ cascade: false })`.
5. Add E2E spec at `ui/tests/e2e/auto-followup.spec.ts` per spec §14. Mirror the seed-helper pattern from `infra_e2e_seed_completed_study` (lands in [`infra_e2e_seed_completed_study/idea.md`](../../../00_overview/implemented_features/2026_05_17_infra_e2e_seed_completed_study/idea.md)). NO `page.route()` mocking — use real backend at `localhost:8000`:
   - **Setup via API helpers:** seed a **3-node chain** (root R → middle M → leaf L). The middle node M is what AC-10 asserts against because M has both `parent_study_id=R` AND a child `L` (cycle-1 finding C1-12; a root R has no parent so it wouldn't render the parent link).
   - **Test 1 — Wizard:** open create-study modal (no `/studies/new` route — wizard is a modal mounted from somewhere in the studies UI; verify the exact entry point during implementation), select depth=2, submit, assert `config.auto_followup_depth=2` in the created study via a follow-up API helper call.
   - **Test 2 — Chain panel on middle node M:** navigate to `/studies/{M_id}`, assert "Auto-followup chain" panel + "Parent: view parent" link (resolves to R) + "Remaining auto-follow-ups: <N>" text + children-table row for L.
   - **Test 3 — Cancel modal on R (which has in-flight children M and L):** click Cancel on R's detail page, assert modal opens with cascade radio shown and pre-selected to "Cancel parent + in-flight children".

**Definition of Done:**

- [ ] Cancel button opens the modal instead of cancelling directly.
- [ ] Modal includes cascade radio (default cascade=true per D-6) when chain context present.
- [ ] All 4 vitest cases pass.
- [ ] E2E spec passes against the real backend (`cd ui && pnpm exec playwright test auto-followup.spec.ts`).
- [ ] `cd ui && pnpm lint && pnpm typecheck && pnpm test && pnpm build` pass.
- [ ] Maps FR-8 (frontend half), FR-11 (cancel UX), FR-9 event #8 (assertion fires via backend telemetry on cascade).

---

## Epic 4 — Documentation

**Goal:** Update runbook + arch docs + user-stories doc + state.md. Single story.

### Story 4.1 — Documentation updates (final story)

**Outcome:** Per spec §15, all listed doc updates land in this PR.

**New files:**

- `docs/03_runbooks/auto-followup-debugging.md` — operator guide: how to grep telemetry events for chain behavior; how to manually break a runaway chain (cancel the parent with cascade); how to verify the budget peek is reading the right Redis key.

**Modified files:**

- `docs/01_architecture/optimization.md` — add §"Auto-followup chains" subsection describing the trigger, gate, depth decrement, budget short-circuit. Cross-link to this feature's spec.
- `docs/01_architecture/ui-architecture.md` — extend §"Routes (MVP1)" entry for `/studies/[id]` to mention the chain panel render conditions. Add the 4 new glossary keys to the tooltips inventory.
- `docs/02_product/mvp1-user-stories.md` — add Story F.X "Operator chains studies overnight" under the studies-feature group.
- `state.md` — update active-priorities + recent-changes; Alembic head unchanged (no migration); branch context.

**Tasks:**

1. Write `docs/03_runbooks/auto-followup-debugging.md` (~300 lines): structured around the 8 telemetry events (one section per event); grep recipes; common operator questions. **MUST include a "Known UX limitations" section** (per cycle-3 finding C3-4 partial-accept) documenting: "To stop a chain you started overnight, navigate to the currently in-flight study (the chain's most recent non-terminal member) — NOT to the original root. The 'Stop chain' button only appears on a parent whose DIRECT child is in-flight; for chains where the in-flight node is a grandchild or deeper, navigate down the chain via 'Children' links until you find a study with `status='running'`, then click Cancel from there. This is a deliberate scope choice per D-13 (direct-children-only); a future feature could add transitive-descendant detection if operators request it. Captured as `feat_auto_followup_root_chain_stop` if the limitation surfaces in feedback."
2. Update `docs/01_architecture/optimization.md` with the new subsection.
3. Update `docs/01_architecture/ui-architecture.md` with the chain panel + 4 glossary entries.
4. Update `docs/02_product/mvp1-user-stories.md` with the new story.
5. Update `state.md` (this happens in `/impl-execute`'s finalization step too, but document it here for completeness).

**Definition of Done:**

- [ ] Runbook merged at `docs/03_runbooks/auto-followup-debugging.md`.
- [ ] All 3 modified arch/product docs updated.
- [ ] All doc links resolve (verified by markdown-link-check or manual review).
- [ ] No tests in this story (docs-only).
- [ ] Maps spec §15 documentation requirements.

---

## 3) Testing workstream inventory

Every test file is assigned to exactly one story's DoD. The 3 unit / 3 integration / 1 contract / 1 E2E files:

| Layer | Test file | Owning story | Coverage |
|---|---|---|---|
| Unit | `backend/tests/unit/domain/test_auto_followup.py` | 1.1 | FR-2, FR-5, FR-7 (gate logic) |
| Unit | `backend/tests/unit/domain/test_search_space_narrow.py` | 1.2 | FR-4 (parity) |
| Unit | `backend/tests/unit/services/test_study_state.py` (extend) | 1.3 | FR-8 service logic |
| Unit | `backend/tests/unit/api/test_study_config_validation.py` (extend) | 1.1 | FR-1 validator |
| Integration | `backend/tests/integration/test_auto_followup.py` | 2.1 (owner) + 2.2 (extends) | FR-3, FR-6, FR-9 events 1-7, FR-1 trigger, two-layer idempotency |
| Integration | `backend/tests/integration/test_studies_api.py` (extend) | 2.3 | FR-8 cascade, FR-9 event #8 |
| Integration | `backend/tests/integration/test_study_children_endpoint.py` (NEW per spec §14) | 2.3 | FR-10 children endpoint (empty / single / chained) |
| Contract | `backend/tests/contract/test_studies_api.py` (extend) | **2.3 owns** (cancel/children) · **Story 1.1 extends** (depth round-trip + envelope shape) — per cycle-2 finding C2-2; ownership is unambiguous, multiple stories may add tests to a single Pytest file | FR-1 round-trip, FR-8 endpoint shapes, FR-10 children endpoint shape |
| Frontend unit | `ui/src/__tests__/components/studies/auto-followup-chain-panel.test.tsx` | 3.1 | FR-10 panel render conditions |
| Frontend unit | `ui/src/__tests__/components/studies/create-study-modal.auto-followup.test.tsx` | 3.2 | FR-11 wizard depth selector |
| Frontend unit | `ui/src/__tests__/components/studies/cancel-study-confirm-modal.test.tsx` | 3.3 | FR-8 modal + cascade radio |
| E2E | `ui/tests/e2e/auto-followup.spec.ts` | 3.3 | FR-10 chain panel, FR-11 wizard, FR-8 modal (real-backend) |

**12 test files total** (4 backend unit + 3 backend integration + 1 backend contract = 8 backend; 3 frontend unit + 1 E2E = 4 frontend). Each file has a single **owner** story; the contract file (`test_studies_api.py`) is **owned by Story 2.3** and **extended by Story 1.1**'s depth round-trip + envelope-shape cases (per cycle-2 finding C2-2 — ownership ambiguity resolved by single-owner rule with documented extends). Per cycle-1 findings C1-3 + C1-4.

## 4) Documentation update workstream

Owned entirely by Story 4.1. Includes runbook, 3 arch/product doc updates, state.md update. No per-story doc edits during Stories 1.x-3.x — keeps PR-review cognitive load focused on code + tests per story.

## 5) Gate conditions

| Gate | Condition | Verifier |
|---|---|---|
| Epic 1 gate | All Epic 1 stories' DoD met; `make lint && make typecheck && make test-unit` pass | CI on the feature branch |
| Epic 2 gate | All Epic 1 + Epic 2 stories' DoD met; `make test-integration && make test-contract` pass; 7 of 8 FR-9 events verified emitted; **4 auxiliary events** outside the FR-9 catalog are also exercisable: `digest_followup_enqueue_pool_missing`, `digest_followup_enqueue_failed`, `digest_followup_start_study_enqueue_failed` (per C1-5 + C2-3 — warning paths from the digest worker / chain worker), AND `auto_followup_cancel_terminal_parent` (per C2-5 + C3-2 — telemetry for the cascade traversal across already-terminal ancestors). All auxiliary events are intentionally kept outside the FR-9 8-event catalog so the spec's authoritative count stays exact. | CI |
| Epic 3 gate | All Epic 1 + 2 + 3 stories' DoD met; `cd ui && pnpm lint && pnpm typecheck && pnpm test && pnpm build` pass; E2E spec passes against real backend | CI + local Playwright run |
| Pre-merge gate | All gates above + Gemini Code Assist review adjudicated + final GPT-5.5 review clean per CLAUDE.md cross-model policy | Manual at PR-merge time |

**Arithmetic check:** 10 stories × 1 DoD assertion per FR coverage = each of FR-1 through FR-12 verified by at least one story's DoD. FR-12 (NO ACTION) is verified by the absence of any migration in the PR diff — Epic 2 gate confirms no new file in `migrations/versions/`.

## 6) Sequencing and dependencies

```
1.1 (domain + Pydantic) ─┐
1.2 (narrow extraction) ─┼─► 2.1 (worker) ─► 2.2 (digest trigger) ─► 2.3 (endpoints) ─► 3.x (frontend) ─► 4.1 (docs)
1.3 (repo + service)    ─┘
```

- Stories 1.1, 1.2, 1.3 can be done in parallel (no inter-dependencies).
- Story 2.1 requires 1.1 (domain gate function), 1.2 (narrowing function), 1.3 (repo function).
- Story 2.2 requires 2.1 (the job to enqueue).
- Story 2.3 requires 1.3 (service) and 2.1 (idempotency layer assumption).
- Stories 3.1, 3.2, 3.3 can be done in parallel after Epic 2 completes (each depends only on its backend endpoint).
- Story 4.1 is last.

No story blocks any other within its epic — agents can pick them up in any order subject to the cross-epic ordering.

## 7) Risks and rollout

- **Risk: Race condition in cascade cancel + worker observe.** A worker is mid-`enqueue_followup_study` when the parent is cancelled by the cascade. The worker's gate check reads `parent.status` and may see `cancelled`. The defensive `skip_parent_failed` branch (event #4) handles this — the cascade-pre-empted worker logs and returns without creating a child. **Mitigation: handled in design.**
- **Risk (cycle-2 C2-5): Cascade UX on completed parents.** A normal chain has a `completed` parent and an in-flight child. The previous design failed because `cancel_study(completed_parent)` raises `InvalidStateTransition`. **Mitigation:** the cascade service tolerates terminal parents — it iterates descendants regardless of the parent's state. The cancel button label adapts: "Cancel study" when parent is `queued`/`running`, "Stop chain" when parent is terminal but has in-flight descendants. The auxiliary `auto_followup_cancel_terminal_parent` telemetry event tracks the terminal-parent path for observability.
- **Risk: Pydantic v2 strictness change in a future minor release coerces `None` differently.** **Mitigation:** the validator has explicit `is not None` check; not relying on truthiness.
- **Risk: Operator runs depth=5 chain, daily budget exhausted at depth=2, only 2 proposals appear; operator confused why chain ended.** **Mitigation:** the `auto_followup_skipped_budget` telemetry + the runbook (`docs/03_runbooks/auto-followup-debugging.md`) explain. Future feature could surface a banner on the chain panel; out of scope for v1.
- **Risk: Worker enqueue fails after digest commit (Redis transient down).** **Mitigation:** the digest worker's existing `try/except` around `arq_pool.enqueue_job` (mirror at line 452 of `backend/workers/orchestrator.py`) logs `digest_followup_enqueue_failed` (per cycle-1 finding C1-5 + cycle-2 finding C2-3 — naming reconciled) and continues — chain ends, parent's proposal is still created. The operator can manually re-trigger via shell if desired (out of scope).
- **Rollout:** No feature flag. Opt-in by default (`auto_followup_depth=None`). Existing studies are unaffected on deploy. Operators who want to try it set the wizard depth on their next study.

## 8) PR description checklist (filled in at PR-creation time by impl-execute)

- [ ] All 10 stories' DoD ✓
- [ ] All 4 gate conditions ✓
- [ ] All 11 test files green in CI
- [ ] No new migration (confirm `git diff main -- migrations/` is empty)
- [ ] 8 telemetry events verified emitted (grep CI logs for each `event_type=`)
- [ ] Gemini Code Assist adjudicated (per CLAUDE.md policy)
- [ ] Final GPT-5.5 review clean (per CLAUDE.md cross-model policy)
- [ ] state.md updated
- [ ] PR title: `feat(auto-followup-studies): operator-controlled chained studies with depth cap + cascade cancel`

---

## 11) Plan consistency review

| Check | Status |
|---|---|
| FR coverage (FR-1 through FR-12 all assigned) | ✓ |
| Endpoint count parity (spec §8.1 = 2 endpoints; plan covers both in Story 2.3) | ✓ |
| Error code parity (spec §8.5 = 2 codes: `AUTO_FOLLOWUP_DEPTH_OUT_OF_RANGE`, `INVALID_CASCADE_PARAM`; both covered by contract tests in Story 2.3) | ✓ |
| Telemetry event count parity (spec FR-9 = 8 events; Story 2.1 covers 7 + Story 2.3 covers 1) | ✓ |
| Test file count parity (§3 lists 12 files post-C1-3+C1-4 patch; each owned by exactly one story; some extended by additional stories) | ✓ |
| Open questions resolved (spec §19: all 6 idea-Open questions locked to defaults D-1, D-3, D-7, D-4, D-5, D-6; plus D-2, D-8, D-9, D-10, D-11, D-12, D-13 added during spec-gen) | ✓ |
| No deferred phases (spec is single-phase) | ✓ |
| Migration count (spec §16 = 0; plan creates 0 files in `migrations/versions/`) | ✓ |
| UI Guidance section complete (all 11 required subsections present) | ✓ |
| All glossary keys named in spec §11 tooltip table appear in Story 3.1 task list | ✓ (4 keys: auto_followup_depth, auto_followup_chain, lift_gate, auto_followup_budget_skip) |
| All wire-value enums cite source-of-truth (CLAUDE.md "Enumerated Value Contract Discipline") | ✓ — depth selector + cascade radio both have comments |
| No `page.route()` mocking in E2E (CLAUDE.md E2E rules) | ✓ — Story 3.3 anchors to real-backend seed-helper pattern |
| No hardcoded LLM model names (CLAUDE.md absolute rule #8) | ✓ — Story 2.1 reads `settings.openai_model` |
| Audit-event coverage (MVP2+ rule — N/A for MVP1) | N/A — spec §6 marks audit events as N/A until MVP2 |

---

## 9) Execution tracker

Resumable across `/pipeline --auto` invocations. Each `/impl-execute` turn ticks the next box.

- [x] **Story 1.1** — `auto_followup_depth` field + `evaluate_chain_gate` domain + error-handler prefix parser. Commit: TBD. Tests: 53 pass (20 domain + 8 handler + 8 schema/contract + 17 pre-existing).
- [ ] Story 1.2 — `narrow_around_winner` domain extraction (FR-4)
- [ ] Story 1.3 — `list_children_of_study` repo + `cancel_study_with_chain_cascade` service (FR-8)
- [ ] **Epic 1 phase gate** — full lint/typecheck/test-unit pass
- [ ] Story 2.1 — `enqueue_followup_study` Arq job (FR-3, FR-5, FR-6, FR-9 events 1-7)
- [ ] Story 2.2 — Digest worker trigger (FR-1 trigger)
- [ ] Story 2.3 — Cancel cascade endpoint + Children endpoint + Telemetry event #8
- [ ] **Epic 2 phase gate** — full integration + contract tests pass; 7 of 8 FR-9 events emitted
- [ ] Story 3.1 — Glossary entries + Auto-followup chain panel component (FR-10)
- [ ] Story 3.2 — Wizard depth selector (FR-11)
- [ ] Story 3.3 — Cancel modal cascade radio + E2E test (FR-8 frontend)
- [ ] **Epic 3 phase gate** — `cd ui && pnpm lint && pnpm typecheck && pnpm test && pnpm build` pass; E2E spec passes
- [ ] Story 4.1 — Documentation updates (runbook + arch docs + state.md)
- [ ] **Post-implementation** — test coverage audit, deferred-work sweep, tangential observations, guide impact, push + PR, CI watch, Gemini adjudication, final GPT-5.5 review, finalize
