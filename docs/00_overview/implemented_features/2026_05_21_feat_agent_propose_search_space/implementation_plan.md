# Implementation Plan — `propose_search_space` agent tool

**Date:** 2026-05-21
**Status:** Complete (PR [#175](https://github.com/SoundMindsAI/relyloop/pull/175), merged 2026-05-21)
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy source(s):**
- [`CLAUDE.md`](../../../../CLAUDE.md)
- [`docs/01_architecture/agent-tools.md`](../../../01_architecture/agent-tools.md)
- [`docs/01_architecture/llm-orchestration.md`](../../../01_architecture/llm-orchestration.md)

---

## 0) Planning principles

- Spec traceability first: every story maps to FR IDs.
- Phase gates are hard stops; pre-push gate is unwaivable.
- Fail-loud tests: assert explicit status, error codes, log event names.
- Match codebase conventions for tools (`backend/app/agent/tools/studies/create_study.py` is the canonical template).
- Keep increments narrow enough to verify independently — every story ends with at least one test green.
- Single-phase delivery. Cluster-stats grounding (spec §3 Out-of-scope) is not in this plan.

## 1) Scope traceability (FR → epics/phases)

| FR ID | Epic | Notes |
|---|---|---|
| FR-1 (heuristic-based starter + overflow guard) | Epic 1, Stories 1.1 + 1.2 | Python `build_starter_search_space` returns `StarterSearchSpace` dataclass; TS sibling updated to parallel shape + throw on overflow / empty. |
| FR-2 (`propose_search_space` agent tool) | Epic 3, Story 3.2 | Tool impl + registry wiring + canonical name set update (`EXPECTED_TOOL_COUNT_MVP1` 19→20). |
| FR-3 (prior-study narrowing + graceful degrade) | Epic 1, Story 1.1 (math); Epic 2, Story 2.1 (repo); Epic 3, Story 3.2 (tool plumbing + WARN paths) | ±50% linear / √2 log-uniform bracket; template-mismatch and missing-trial degrade to heuristic-only with WARN logs. |
| FR-4 (narrowing cardinality non-increasing) | Epic 1, Story 1.1 (docstring + invariant assertion in unit test) | Documentation FR; no separate code path. |
| FR-5 (system-prompt update) | Epic 4, Story 4.1 | `prompts/orchestrator.system.md` tool count + Studies (4) + chain guidance + snapshot test. |
| FR-6 (paired INFO-event telemetry) | Epic 3, Story 3.1 (`ToolContext.conversation_id` plumb) + Story 3.3 (event emission in both impls) | Adherence ratio computed offline by correlating events on `conversation_id`. |
| FR-7 (TS↔Python heuristic parity) | Epic 1, Story 1.3 | Shared JSON fixture + symmetric assertions for `expected_search_space` and `expected_error` rows. |

No deferred FRs. The spec is single-phase; cluster-stats grounding is documented in spec §3 Out-of-scope and does not require a separate `phase2_idea.md` per the spec's phase boundaries note.

## 2) Delivery structure

This plan uses **Epic → Story → Tasks → DoD**. 10 stories across 5 epics. The 5 epics are roughly sequenced by dependency: domain helpers (Epic 1) → repo (Epic 2) → agent surface (Epic 3) → prompts + integration (Epic 4) → docs (Epic 5). Within each epic stories may parallelize once the upstream epic completes.

### Story-level detail requirements

Every story below includes: Outcome, New files, Modified files, Endpoints (or "N/A — agent tool only" when not REST), Key interfaces, Pydantic schemas (if any), Tasks, and Definition of Done.

### Conventions (project-specific)

- All repo functions take `db: AsyncSession` as first arg; use `await db.flush()` (caller commits).
- Tool impls take `(args, ctx: ToolContext)` and return `dict[str, Any]`; errors via `HTTPException(status_code, detail={error_code, message, retryable})`.
- Read-only tools never call `ctx.db.commit()`. `propose_search_space` is read-only.
- Domain layer is pure — no DB access, no async, no I/O.
- Pydantic v2; models use `ConfigDict(extra="forbid")` where strict.
- All `__init__.py` exports updated via `__all__` and the three-struct module-load assertion at `backend/app/agent/tools/__init__.py:221-228`.
- Conventional Commits enforced by pre-commit `commit-msg` hook.
- Never bypass hooks with `--no-verify`.
- Structlog event names are stable identifiers; renaming requires a spec patch.

### AI Agent Execution Protocol (applies to every story)

0. **Load context first**: Read `architecture.md`, `state.md`, and the feature spec before starting the first story.
1. **Read scope**: verify story Outcome + Endpoints + Key interfaces + DoD.
2. **Implement backend first**: domain helper → repo → tool impl → registry wiring → system prompt → integration.
3. **Run tests in the order**: targeted unit → integration → contract (none in this feature) → full suite.
4. **No frontend production code** in this feature beyond (a) the TS edit to `ui/src/lib/search-space-defaults.ts` and (b) the corresponding caller migration in `ui/src/components/studies/create-study-modal.tsx` to consume the new return shape (both in Story 1.2). No new UI elements, no navigation changes, no new tooltips. The caller migration is wrapped in try/catch so new throw paths surface via the existing modal-level error toast.
5. **No DB migration** — this feature is purely additive at the application layer.
6. **Update docs in same PR** when behavior/contract changes (Epic 5).
7. **Attach evidence** in PR description per the post-impl protocol of `/impl-execute`.

---

## Epic 1 — Domain helper + parity

### Story 1.1 — Port `search_space_defaults.py` from TS with overflow guard + narrowing helper

**Outcome:** A pure-Python module at `backend/app/domain/study/search_space_defaults.py` mirrors `ui/src/lib/search-space-defaults.ts` exactly, exposes `HEURISTIC_RULES`, `simple_form_spec`, `estimate_param_cardinality`, `build_starter_search_space → StarterSearchSpace`, and `narrow_bounds_around_winner`. Empty input and cap-aware-overflow raise `InvalidSearchSpaceError`; cap-aware fallback fires a `logger.warning`. Unit tests at `backend/tests/unit/domain/test_search_space_defaults.py` exercise every heuristic rule, every `simple_form_spec` branch, the cap-aware fallback (firing + exhausting), the overflow guard, narrowing math for each param type, the skip-on-out-of-bounds rule, the type-guard for non-numeric winner values, and the cardinality-non-increasing invariant.

**New files**

| File | Purpose |
|---|---|
| `backend/app/domain/study/search_space_defaults.py` | Python port of `ui/src/lib/search-space-defaults.ts`. Exports `HEURISTIC_RULES`, `simple_form_spec`, `estimate_param_cardinality`, `build_starter_search_space`, `narrow_bounds_around_winner`, and the `StarterSearchSpace` dataclass. |
| `backend/tests/unit/domain/test_search_space_defaults.py` | Unit tests covering all branches above. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/domain/study/search_space.py` | None of the existing classes change. (`InvalidSearchSpaceError` already exists at lines 121-129 and is re-used by the new module.) |
| `backend/app/domain/study/template_defaults.py` | Add a one-line cross-reference comment at the top of the module noting that `search_space_defaults.py` picks `ParamSpec` ranges while `template_defaults.py` picks concrete per-trial values. No behavior change. |

**Endpoints:** N/A — pure domain helper, no API surface.

**Key interfaces**

```python
# backend/app/domain/study/search_space_defaults.py
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class StarterSearchSpace:
    """Return type of `build_starter_search_space` — pairs the SearchSpace with
    fallback metadata so the tool can populate grounding.cap_aware_fallback_param_names
    without duplicating fallback logic."""

    space: SearchSpace
    cap_aware_fallback_param_names: list[str]


HEURISTIC_RULES: list[tuple[re.Pattern[str], dict[str, Any]]] = [...]  # mirrors TS

def simple_form_spec(type_name: str) -> ParamSpec | None: ...

def estimate_param_cardinality(spec: ParamSpec) -> int: ...

def build_starter_search_space(declared_params: dict[str, str]) -> StarterSearchSpace:
    """Build a starter search_space from a template's declared_params.

    Raises:
        InvalidSearchSpaceError: empty declared_params (mirrors Pydantic's
            min_length=1 rejection inside SearchSpace), OR cap-aware fallback
            cannot drop cardinality <= 10^6 even after converting every float
            to int[0, 5].
    """

def narrow_bounds_around_winner(
    space: SearchSpace,
    winning_params: dict[str, Any],
    bracket: float = 0.5,
) -> tuple[SearchSpace, list[str]]:  # tuple-return per spec FR-3 (helper signature)
    """Apply ±bracket narrowing to each numeric param whose name is in winning_params.

    Returns the (possibly-rewritten) SearchSpace and the list of param names
    actually narrowed (per FR-3's skip-on-out-of-bounds rule and the non-numeric
    type guard).

    Cardinality non-increasing (FR-4 invariant).
    """
```

**Pydantic schemas:** N/A — uses the existing `SearchSpace`/`FloatParam`/`IntParam`/`CategoricalParam` from `backend/app/domain/study/search_space.py`.

**Tasks**
1. Create `backend/app/domain/study/search_space_defaults.py`. Mirror the TS source line-by-line (HEURISTIC_RULES order, simple_form_spec switch, cap-aware fallback algorithm).
2. Implement the `StarterSearchSpace` frozen dataclass with `slots=True`.
3. Wrap `SearchSpace.model_validate` for empty input — catch `pydantic.ValidationError` and re-raise as `InvalidSearchSpaceError("empty declared_params")` so the tool surfaces a single exception type.
4. Add the cap-aware overflow guard: after exhausting fall-through-then-regex-matched float conversions, if `estimate_cardinality > 1_000_000`, raise `InvalidSearchSpaceError("cap-aware fallback exhausted: cardinality={n} > 10^6 for declared_params={names}")`.
5. Implement `narrow_bounds_around_winner` with three branches (FloatParam linear, FloatParam log, IntParam) + categorical pass-through + skip-on-out-of-bounds + non-numeric-winner type guard. Use `math.sqrt(2)` for log-uniform brackets.
6. Add a module-level `logger = structlog.get_logger(__name__)` and emit `logger.warning("search_space_defaults.cap_aware_fallback", converted_param_names=[...], reason="cardinality_above_cap")` when cap-aware fallback fires.
7. Cross-reference docstring in `template_defaults.py`.
8. Write unit tests at `backend/tests/unit/domain/test_search_space_defaults.py`:
   - Every regex rule produces the expected ParamSpec (parametrize over names).
   - `simple_form_spec` returns the right spec for `int`, `float`, `bool`, `string`, `None` for anything else.
   - `estimate_param_cardinality` returns 100 for floats, `high-low+1` for ints, `len(choices)` for categoricals.
   - `build_starter_search_space({})` raises `InvalidSearchSpaceError`.
   - Cap-aware fallback fires + populates `cap_aware_fallback_param_names`. Reference math: 4 fall-through floats has starting cardinality `100⁴ = 10⁸ > 10⁶`; after converting 2 to `int[0, 5]` in lex order the cardinality is `6² × 100² = 360_000 ≤ 10⁶`. Test asserts exactly 2 are converted and they're the lex-first 2 names.
   - Cap-aware overflow raises (8 fall-through floats — `6^8 = 1_679_616 > 10^6`).
   - `narrow_bounds_around_winner` math for each param type with concrete numbers (matching AC-2, AC-3).
   - Winner out of bounds → skip + not in narrowed list (AC-4).
   - Non-numeric winner → skip + not in narrowed list.
   - Cardinality before narrowing ≥ cardinality after narrowing (parametrized over several starter spaces).

**Definition of Done**
- [ ] `backend/app/domain/study/search_space_defaults.py` exists with the listed exports.
- [ ] `make test-unit` includes the new test file; all cases pass.
- [ ] `mypy --strict` clean on the new file.
- [ ] `ruff check` + `ruff format` clean.
- [ ] `logger.warning` event fires when the cap-aware fallback runs, verified via the `backend/tests/_log_helpers.py` pattern (`capture_logs()`).

### Story 1.2 — TS-side parity changes to `ui/src/lib/search-space-defaults.ts`

**Outcome:** TS `buildStarterSearchSpace` returns `{ space: SearchSpaceJson, capAwareFallbackParamNames: string[] }` instead of a bare `SearchSpaceJson`, and throws on empty input or cap-aware-overflow conditions. The create-study wizard's existing call site (`ui/src/components/studies/create-study-modal.tsx` — Step-3→4 transition effect) is updated to consume `.space`. TS unit tests at `ui/src/__tests__/lib/search-space-defaults.test.ts` (and the cardinality test) are adjusted; new throw-case tests added.

**New files**

| File | Purpose |
|---|---|
| (none — see Story 1.3 for the new parity test) | |

**Modified files**

| File | Change |
|---|---|
| `ui/src/lib/search-space-defaults.ts` | Add `StarterSearchSpace` type alias; change `buildStarterSearchSpace` return type to `StarterSearchSpace`; throw `Error("empty declared_params")` on empty input; throw `Error("cap-aware fallback exhausted: cardinality=N > 10^6 ...")` when fallback can't bring cardinality under cap; emit `console.warn` when fallback fires (existing behavior preserved). |
| `ui/src/components/studies/create-study-modal.tsx` | Update the Step-3→4 transition effect that calls `buildStarterSearchSpace(declaredParams)` to consume `.space` from the return value. Wrap the call in try/catch so the new `Error` throws (empty input, cap-aware overflow) surface as the existing modal-level error toast pattern (same as 422 backend errors). **No new UI** — `capAwareFallbackParamNames` is ignored in the wizard (the cap-aware metadata is for the agent's grounding object, not for new user-facing chrome — spec §1 keeps v1 backend-only). |
| `ui/src/__tests__/lib/search-space-defaults.test.ts` | Adjust existing assertions that destructure the return value (currently `const space = buildStarterSearchSpace(...)`, becomes `const { space } = buildStarterSearchSpace(...)`). Add new cases for the two throw conditions. |
| `ui/src/__tests__/lib/search-space-defaults.cardinality.test.ts` | Same destructure update. |
| `ui/src/__tests__/components/create-study-modal.*.test.tsx` | If any test reads the return value of `buildStarterSearchSpace`, update destructure. Otherwise no change. |

**Endpoints:** N/A — frontend lib.

**Key interfaces**

```ts
// ui/src/lib/search-space-defaults.ts
export type StarterSearchSpace = {
  space: SearchSpaceJson;
  capAwareFallbackParamNames: string[];
};

export function buildStarterSearchSpace(
  declaredParams: Record<string, string>,
): StarterSearchSpace;  // throws on empty input or cap-aware overflow
```

**Pydantic schemas:** N/A.

**Tasks**
1. Update `ui/src/lib/search-space-defaults.ts`:
   - Add `StarterSearchSpace` type alias above `buildStarterSearchSpace`.
   - Throw `new Error("empty declared_params: at least one declared param is required")` when `declaredParams` has zero keys (before any work).
   - Track `capAwareFallbackParamNames: string[]` inside the function (rename the existing `converted` accumulator).
   - At end of fallback loop, if `estimateCardinality(candidate) > 1_000_000`, throw `new Error(\`cap-aware fallback exhausted: cardinality=${size} > 10^6 for declared_params=${...}\`)`.
   - Return `{ space: candidate, capAwareFallbackParamNames: converted }`.
2. Update `ui/src/components/studies/create-study-modal.tsx` Step-3→4 transition effect:
   - Destructure: `const { space } = buildStarterSearchSpace(declaredParams);` — `capAwareFallbackParamNames` is intentionally ignored (no new wizard UI).
   - Pass `space.params` into the existing state writer.
   - Wrap the destructure in try/catch so the new `Error` throws (empty input, cap-aware overflow) surface as the existing modal-level error toast (same path as backend 422 errors). Confirm no behavior regression for valid templates — existing tests must continue to pass.
3. Sweep `ui/src/` for other `buildStarterSearchSpace` callers via `rg buildStarterSearchSpace ui/src` and update each.
4. Update existing TS tests' destructures.
5. Add new TS tests in `ui/src/__tests__/lib/search-space-defaults.test.ts`:
   - `expect(() => buildStarterSearchSpace({})).toThrow(/empty declared_params/)`
   - Cap-aware overflow case (8 fall-through floats) → `toThrow(/cap-aware fallback exhausted/)`
   - Cap-aware fallback fires but doesn't overflow (e.g., 5 fall-through floats) → returned `capAwareFallbackParamNames` non-empty + final cardinality ≤ 10⁶.

**Definition of Done**
- [ ] `cd ui && pnpm test src/__tests__/lib/search-space-defaults.test.ts` passes (existing + new cases).
- [ ] `cd ui && pnpm test src/__tests__/lib/search-space-defaults.cardinality.test.ts` passes.
- [ ] `cd ui && pnpm test src/__tests__/components/create-study-modal` passes (any tests that touched the call site continue to pass).
- [ ] `cd ui && pnpm typecheck` clean (the return-type change must propagate cleanly through `create-study-modal.tsx`).
- [ ] `cd ui && pnpm lint` clean.
- [ ] No call site of `buildStarterSearchSpace` reads the return value as `SearchSpaceJson` directly anymore.

### Story 1.3 — Shared TS↔Python parity fixture + parity tests

**Outcome:** A shared JSON fixture at `backend/tests/_fixtures/search_space_defaults_parity.json` drives two symmetric tests: `backend/tests/unit/domain/test_search_space_defaults_parity.py` and `ui/src/__tests__/lib/search-space-defaults.parity.test.ts`. Each fixture row has shape `{name, declared_params, expected_search_space | expected_error}`. Both tests iterate the fixture and assert the corresponding implementation produces the expected output (or throws when `expected_error` is set).

**New files**

| File | Purpose |
|---|---|
| `backend/tests/_fixtures/search_space_defaults_parity.json` | Shared parity fixture. ~10–15 rows covering every heuristic rule, every `simple_form_spec` branch, a cap-aware-fallback-fires case (small enough to succeed), a cap-aware-overflow case (8 fall-through floats), and the empty case. |
| `backend/tests/unit/domain/test_search_space_defaults_parity.py` | Python half. Iterates the fixture; asserts byte-identical `space.model_dump()` for happy rows and `pytest.raises(InvalidSearchSpaceError)` for `expected_error` rows. |
| `ui/src/__tests__/lib/search-space-defaults.parity.test.ts` | TS half. Reads the same JSON file (via Node `fs.readFile` since the fixture lives outside the `ui/` package). Asserts byte-identical `space` for happy rows and `expect(...).toThrow(...)` for `expected_error` rows. |

**Modified files** — none.

**Endpoints:** N/A.

**Key interfaces**

Fixture row schema (TypeScript form for clarity; same shape in JSON):

```ts
type ParityFixtureRow =
  | {
      name: string;
      declared_params: Record<string, string>;
      expected_search_space: { params: Record<string, ParamSpec> };
      expected_cap_aware_fallback_param_names: string[]; // [] when fallback doesn't fire
    }
  | {
      name: string;
      declared_params: Record<string, string>;
      expected_error: { kind: "invalid_search_space"; message_substring: string };
    };
```

**Pydantic schemas:** N/A.

**Tasks**
1. Write the fixture file with rows in this order:
   - `heuristic_field_boost_prefix` — `{"field_boost_title": "float"}` → log-uniform float [0.5, 10].
   - `heuristic_boost_underscore_prefix` — `{"boost_title": "float"}` → same.
   - `heuristic_boost_standalone` — `{"boost": "float"}` → same.
   - `heuristic_field_boost_suffix` — `{"title_boost": "float"}` → same.
   - `heuristic_tie_breaker` — `{"tie_breaker": "float"}` → uniform float [0, 1].
   - `heuristic_min_should_match` — `{"min_should_match": "int"}` → int [0, 5].
   - `heuristic_fuzziness` — `{"fuzziness": "string"}` → categorical ["AUTO", "0", "1", "2"].
   - `simple_form_int_fallback` — `{"unknown_int": "int"}` → int [0, 5].
   - `simple_form_float_fallback` — `{"unknown_float": "float"}` → uniform float [0, 1].
   - `simple_form_bool` — `{"flag": "bool"}` → categorical [true, false].
   - `simple_form_string` — `{"text_field": "string"}` → categorical ["__placeholder__"].
   - `cap_aware_fires_safe` — 4 fall-through floats (cardinality before fallback = 100⁴ = 10⁸ > 10⁶). After cap-aware fallback converts 2 floats to `int[0, 5]` in lex order, cardinality is `6² × 100² = 360_000 ≤ 10⁶`. Expected `cap_aware_fallback_param_names` = the lex-first 2 of the 4 names. Both Python and TS must agree on which 2.
   - `cap_aware_overflow_throws` — 8 fall-through floats (`{"a","b",...,"h"}` all `float`) → `expected_error: {"kind": "invalid_search_space", "message_substring": "cap-aware fallback exhausted"}`.
   - `empty_declared_params_throws` — `{}` → `expected_error: {"kind": "invalid_search_space", "message_substring": "empty declared_params"}`.
2. Write `backend/tests/unit/domain/test_search_space_defaults_parity.py`. Pattern: parametrize over loaded fixtures; happy rows assert `space.model_dump() == expected` and `result.cap_aware_fallback_param_names == expected`; error rows use `pytest.raises(InvalidSearchSpaceError, match=expected_error["message_substring"])`.
3. Write `ui/src/__tests__/lib/search-space-defaults.parity.test.ts`. Use `node:fs/promises` `readFile(path.resolve(__dirname, "../../../../backend/tests/_fixtures/search_space_defaults_parity.json"), "utf-8")` to load (since Vitest runs from `ui/`). `describe.each(rows)` pattern; happy rows assert equality (object-deep-equal), error rows use `expect(() => buildStarterSearchSpace(...)).toThrow(new RegExp(message_substring))`.
4. Verify both tests run green simultaneously: change one heuristic in either source momentarily to confirm both tests fail; revert.

**Definition of Done**
- [ ] Fixture JSON validates (`python -m json.tool < backend/tests/_fixtures/search_space_defaults_parity.json` clean).
- [ ] `pytest backend/tests/unit/domain/test_search_space_defaults_parity.py` passes.
- [ ] `cd ui && pnpm test src/__tests__/lib/search-space-defaults.parity.test.ts` passes.
- [ ] Drift sanity check: temporarily mutate `HEURISTIC_RULES[0].spec.low` in either source and confirm both parity tests fail (then revert).

**Epic 1 gate (hard stop):** Stories 1.1, 1.2, 1.3 all DoD-green. After this gate, the heuristic source-of-truth is single (TS + Python parity-locked) and ready for the tool to consume.

---

## Epic 2 — Repo helper for prior-trial fetch

### Story 2.1 — Add `repo.get_trial(db, trial_id)` to `backend/app/db/repo/trial.py`

**Outcome:** `backend/app/db/repo/trial.py` exports an async `get_trial(db, trial_id) → Trial | None` analogous to `repo.get_study`. The `__init__.py` exports update accordingly. A unit test under `backend/tests/unit/db/test_trial_repo.py` (or extends the existing file if present) covers found / not-found / soft-delete-aware cases. (Note: `trials` has no `deleted_at` per the schema — append-only — so only found / not-found cases apply.)

**New files**

| File | Purpose |
|---|---|
| (none) | Test additions extend the existing trial-repo tests if any; new file only if none exist. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/db/repo/trial.py` | Add `async def get_trial(db: AsyncSession, trial_id: str) -> Trial | None`. Standard SQLAlchemy `select(Trial).where(Trial.id == trial_id)` + `result.scalar_one_or_none()`. |
| `backend/app/db/repo/__init__.py` | Add `get_trial` to `__all__` and the import block. |
| `backend/tests/integration/test_trial_repo.py` (or new file under `backend/tests/integration/` if none exists) | 2 cases: found returns Trial, not-found returns None. |

**Endpoints:** N/A.

**Key interfaces**

```python
# backend/app/db/repo/trial.py
async def get_trial(db: AsyncSession, trial_id: str) -> Trial | None:
    """Fetch a single trial by primary key. Returns None if not found."""
```

**Pydantic schemas:** N/A.

**Tasks**
1. Add the function to `backend/app/db/repo/trial.py`. Pattern: identical shape to `get_study` in `backend/app/db/repo/study.py:61-64`.
2. Update `backend/app/db/repo/__init__.py` — add `get_trial` to `__all__` and the from-import block.
3. Write integration tests (because trial fetches are DB-backed, this is integration not unit per `docs/05_quality/testing.md`):
   - Found case: insert a Trial via the existing trial test fixture, call `repo.get_trial`, assert the returned object.
   - Not-found case: call with a UUIDv7 string that doesn't exist, assert `None`.

**Definition of Done**
- [ ] `backend/app/db/repo/trial.py:get_trial` exists.
- [ ] `repo.get_trial` is importable as `from backend.app.db.repo import get_trial`.
- [ ] `make test-integration` includes the new cases; all pass.
- [ ] `mypy --strict` clean.

---

## Epic 3 — Agent surface (ToolContext, tool impl, telemetry)

### Story 3.1 — Add `conversation_id: str` to `ToolContext` and plumb it from the orchestrator

**Outcome:** `backend/app/agent/context.py:ToolContext` gains a `conversation_id: str` field. The single in-app construction site at `backend/app/services/agent_chat.py:244` is updated to pass the value (already resolved at that point in `run_turn`). The test fixture at `backend/tests/unit/agent/conftest.py:139` is updated to accept a `conversation_id` (default to a fixture-stable value). A new unit test asserts the field exists and is propagated.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/unit/agent/test_tool_context_conversation_id.py` | Asserts `ToolContext` exposes `conversation_id: str`; asserts the orchestrator's construction site passes the `run_turn` parameter through. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/agent/context.py` | Add `conversation_id: str` field to the `ToolContext` frozen dataclass. Place it after `db` (the most-referenced field) to keep call sites readable. |
| `backend/app/services/agent_chat.py` | Update the `ToolContext(...)` construction call at line 244 to pass `conversation_id=<the var in scope>`. (Audit during the story — the `run_turn` parameter is in scope at this call site; confirm during implementation.) |
| `backend/tests/unit/agent/conftest.py` | Update the `ToolContext` fixture at line 139 to set `conversation_id="test-conversation-id"` (or accept an override via fixture param). |

**Endpoints:** N/A.

**Key interfaces**

```python
# backend/app/agent/context.py
@dataclass(frozen=True, slots=True)
class ToolContext:
    db: AsyncSession
    conversation_id: str  # NEW — required field
    redis: Redis
    arq_pool: ArqRedis | None
    settings: Settings
```

**Pydantic schemas:** N/A.

**Tasks**
1. Edit `backend/app/agent/context.py` — add `conversation_id: str` between `db` and `redis`. Update the module docstring to mention the new field's purpose ("Stable per-conversation identifier used for adherence telemetry — paired structlog events tag every emission with this value so offline correlation can compute propose → create chain adherence.").
2. Read `backend/app/services/agent_chat.py:200-260` to confirm `conversation_id` is in scope at line 244. Update the call.
3. Update `backend/tests/unit/agent/conftest.py` — add `conversation_id="test-conv-fixture"` to the `ToolContext(...)` construction inside the fixture.
4. Grep the codebase for other `ToolContext(` instantiations: `rg 'ToolContext\(' --type py`. There are currently only 2; if more arrive during this story, update them too.
5. Write the new test file `backend/tests/unit/agent/test_tool_context_conversation_id.py`:
   - Assert `dataclasses.fields(ToolContext)` includes a field named `conversation_id` with type `str`.
   - Use a stubbed `agent_chat.run_turn` call (or partial of `ToolContext` construction) to assert the runtime value is propagated from the `run_turn` parameter into the `ToolContext` instance.

**Definition of Done**
- [ ] `ToolContext` has `conversation_id: str` field, no defaulting, no Optional.
- [ ] All existing `ToolContext(...)` construction sites (currently 2) compile + pass tests.
- [ ] `make test-unit` includes the new test file; all cases pass.
- [ ] `mypy --strict` clean.
- [ ] No existing test fails because of this change (audit by running the full unit test suite).

### Story 3.2 — New tool: `backend/app/agent/tools/studies/propose_search_space.py` + registry wiring

**Outcome:** A new read-only tool file `propose_search_space.py` exposes `ProposeSearchSpaceArgs`, `propose_search_space_impl`, `_DESCRIPTION`, and `PROPOSE_SEARCH_SPACE_TOOL`, mirroring the shape of `get_study.py`. The tool is registered in all three structures in `backend/app/agent/tools/__init__.py` (TOOLS, TOOL_REGISTRY, TOOL_ARG_MODELS). `backend/tests/unit/agent/test_tool_registry.py` updates `EXPECTED_TOOL_COUNT_MVP1` to 20 and adds `"propose_search_space"` to the canonical name set. The tool is NOT added to `MUTATING_TOOL_NAMES`. Unit tests under `backend/tests/unit/agent/test_propose_search_space.py` cover all error codes + happy paths + graceful-degrade paths.

**New files**

| File | Purpose |
|---|---|
| `backend/app/agent/tools/studies/propose_search_space.py` | Tool impl, args model, `_DESCRIPTION`, `PROPOSE_SEARCH_SPACE_TOOL`. |
| `backend/tests/unit/agent/test_propose_search_space.py` | Unit tests covering all error codes + happy paths + graceful-degrade. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/agent/tools/__init__.py` | Add 3 entries: import from `propose_search_space.py`; add `PROPOSE_SEARCH_SPACE_TOOL` to `TOOLS`; add `"propose_search_space": propose_search_space_impl` to `TOOL_REGISTRY`; add `"propose_search_space": ProposeSearchSpaceArgs` to `TOOL_ARG_MODELS`. The module-load assertion at lines 221-228 catches drift if any of the three is missed. |
| `backend/tests/unit/agent/test_tool_registry.py` | `EXPECTED_TOOL_COUNT_MVP1 = 20`; add `"propose_search_space"` to `CANONICAL_MVP1_TOOL_NAMES`. |

**Endpoints:** N/A — agent tool only. Wire shape documented in spec §8.

**Key interfaces**

```python
# backend/app/agent/tools/studies/propose_search_space.py
from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from fastapi import HTTPException
from openai.types.chat import ChatCompletionToolParam
from pydantic import BaseModel, Field

from backend.app.agent.context import ToolContext
from backend.app.db import repo
from backend.app.domain.study.search_space import InvalidSearchSpaceError, SearchSpace, estimate_cardinality
from backend.app.domain.study.search_space_defaults import (
    build_starter_search_space,
    narrow_bounds_around_winner,
)

logger = structlog.get_logger(__name__)


class ProposeSearchSpaceArgs(BaseModel):
    """Arguments for the `propose_search_space` tool."""

    template_id: UUID = Field(description="The template's UUIDv7 — the param universe.")
    cluster_id: UUID = Field(description="The cluster's UUIDv7 — validated to exist.")
    judgment_list_id: UUID | None = Field(
        default=None,
        description="Optional judgment list — v1 validates existence only (signature-only).",
    )
    prior_study_id: UUID | None = Field(
        default=None,
        description="Optional prior study — narrows bounds around its winning trial when template matches.",
    )


async def propose_search_space_impl(
    args: ProposeSearchSpaceArgs, ctx: ToolContext
) -> dict[str, Any]: ...

_DESCRIPTION = (propose_search_space_impl.__doc__ or "").split("\n\n", 1)[0].strip()

PROPOSE_SEARCH_SPACE_TOOL: ChatCompletionToolParam = {
    "type": "function",
    "function": {
        "name": "propose_search_space",
        "description": _DESCRIPTION,
        "parameters": ProposeSearchSpaceArgs.model_json_schema(),
    },
}
```

The impl follows this structure:

```python
async def propose_search_space_impl(args, ctx) -> dict[str, Any]:
    """Build a deterministic, code-generated search_space for create_study.

    Returns a JSON-ready dict with `search_space` (consumable by `create_study`)
    and `grounding` (origin metadata: template + cluster + prior-study state).
    Read-only — no DB writes.
    """
    # 1. FK resolution (TEMPLATE_NOT_FOUND, CLUSTER_NOT_FOUND, optional 404s).
    template = await repo.get_query_template(ctx.db, str(args.template_id))
    if template is None: raise HTTPException(404, {"error_code": "TEMPLATE_NOT_FOUND", ...})
    cluster = await repo.get_cluster(ctx.db, str(args.cluster_id))
    if cluster is None: raise HTTPException(404, {"error_code": "CLUSTER_NOT_FOUND", ...})
    if args.judgment_list_id:
        jlist = await repo.get_judgment_list(ctx.db, str(args.judgment_list_id))
        if jlist is None: raise HTTPException(404, {"error_code": "JUDGMENT_LIST_NOT_FOUND", ...})

    # 2. Build heuristic-only starter via build_starter_search_space().
    try:
        starter = build_starter_search_space(template.declared_params)
    except InvalidSearchSpaceError as exc:
        raise HTTPException(400, {"error_code": "INVALID_SEARCH_SPACE", ...}) from exc

    space = starter.space
    cap_fallback_names = list(starter.cap_aware_fallback_param_names)
    narrowed_names: list[str] = []
    prior_study_template_mismatch = False
    used_prior_study_id: str | None = None

    # 3. Optional prior-study narrowing (FR-3 graceful degrade).
    if args.prior_study_id:
        prior = await repo.get_study(ctx.db, str(args.prior_study_id))
        if prior is None: raise HTTPException(404, {"error_code": "STUDY_NOT_FOUND", ...})
        used_prior_study_id = str(prior.id)
        if str(prior.template_id) != str(args.template_id):  # both sides normalized — model field is String(36) but Pydantic UUID args round-trip through `str()` to be safe
            prior_study_template_mismatch = True
            logger.warning("agent.propose_search_space.prior_template_mismatch", ...)
        elif prior.best_trial_id:
            trial = await repo.get_trial(ctx.db, prior.best_trial_id)
            if trial is None:
                logger.warning("agent.propose_search_space.missing_winner_trial", ...)
            else:
                space, narrowed_names = narrow_bounds_around_winner(space, trial.params, bracket=0.5)  # explicit per spec FR-3

    # 4. Telemetry (FR-6) — INFO event, swallowed on logger failure.
    try:
        logger.info(
            "agent.search_space_proposed",
            conversation_id=ctx.conversation_id,
            template_id=str(args.template_id),
            cluster_id=str(args.cluster_id),
            judgment_list_id=str(args.judgment_list_id) if args.judgment_list_id else None,
            prior_study_id=str(args.prior_study_id) if args.prior_study_id else None,
            param_names=sorted(space.params.keys()),
            cardinality=estimate_cardinality(space),
            narrowed_param_names=narrowed_names,
        )
    except Exception:  # noqa: BLE001 — telemetry must not block dispatch (spec FR-6)
        pass

    # 5. Return result. Read-only — no ctx.db.commit().
    return {
        "search_space": space.model_dump(),
        "grounding": {
            "template_id": str(template.id),
            "template_name": template.name,
            "cluster_id": str(cluster.id),
            "used_prior_study_id": used_prior_study_id,
            "narrowed_param_names": narrowed_names,
            "cap_aware_fallback_param_names": cap_fallback_names,
            "prior_study_template_mismatch": prior_study_template_mismatch,
        },
    }
```

**Pydantic schemas:** `ProposeSearchSpaceArgs` (above).

**Tasks**
1. Create `backend/app/agent/tools/studies/propose_search_space.py` per the structure above.
2. Update `backend/app/agent/tools/__init__.py`:
   - Add import block (mirror existing imports at lines 101-115).
   - Append `PROPOSE_SEARCH_SPACE_TOOL` to the `TOOLS` list under "# Studies (Story 2.3)" — add a comment marking the addition.
   - Append `"propose_search_space": propose_search_space_impl` to `TOOL_REGISTRY` under the same section.
   - Append `"propose_search_space": ProposeSearchSpaceArgs` to `TOOL_ARG_MODELS` under the same section.
   - Run `python -c "import backend.app.agent.tools"` locally — the module-load assertion at lines 221-228 catches misalignment.
3. Update `backend/tests/unit/agent/test_tool_registry.py`:
   - `EXPECTED_TOOL_COUNT_MVP1 = 20`.
   - `CANONICAL_MVP1_TOOL_NAMES = frozenset({..., "propose_search_space"})`.
4. Confirm `backend/app/agent/confirmation.py:MUTATING_TOOL_NAMES` (lines 14-24) is NOT modified — `propose_search_space` is read-only.
5. Write unit tests at `backend/tests/unit/agent/test_propose_search_space.py`. Use the existing `ToolContext` fixture from `conftest.py`. Cover:
   - **Happy path heuristic-only** (no prior study, no judgment list). Verify `grounding.used_prior_study_id is None`, `grounding.narrowed_param_names == []`, `grounding.cap_aware_fallback_param_names == []`, `grounding.prior_study_template_mismatch is False`, and `result.search_space` validates against `SearchSpace.model_validate`. (AC-1, AC-7)
   - **Happy path with prior_study_id narrowing** (template matches, trial exists). Verify expected bound math matches FR-3 (AC-2 + AC-3).
   - **Prior study has `best_trial_id is None`** — degrade to heuristic-only, `narrowed_param_names == []`, no error. (AC-5)
   - **Prior study `best_trial_id` set but `repo.get_trial` returns None** — heuristic-only, structlog WARN `agent.propose_search_space.missing_winner_trial` fires. (AC-15)
   - **Prior study template mismatch** — heuristic-only, `prior_study_template_mismatch is True`, WARN `agent.propose_search_space.prior_template_mismatch` fires. (AC-14)
   - **Winner out of bounds** — skip narrowing for that param, not in `narrowed_param_names`. (AC-4)
   - **Unknown cluster** → `HTTPException(404, error_code="CLUSTER_NOT_FOUND")`. (AC-6)
   - **Unknown template** → 404 `TEMPLATE_NOT_FOUND`.
   - **Unknown judgment list** → 404 `JUDGMENT_LIST_NOT_FOUND`.
   - **Unknown prior study** → 404 `STUDY_NOT_FOUND`.
   - **Empty declared_params** in the template (edge case) → 400 `INVALID_SEARCH_SPACE` (AC-12).
   - **Cap-aware overflow** (template has 8 fall-through float declared params) → 400 `INVALID_SEARCH_SPACE` (AC-13).
   - **`ctx.db.commit()` is never called** — use a `Mock`/`AsyncMock` on `ctx.db.commit` and assert `commit.call_count == 0`.
   - **Tool registration sanity** — assertions that `PROPOSE_SEARCH_SPACE_TOOL["function"]["name"] == "propose_search_space"` and that `ProposeSearchSpaceArgs.model_json_schema()` is well-formed (4 properties with the right types). (AC-11)

**Definition of Done**
- [ ] Tool file exists with all four exports.
- [ ] Registry has 20 entries; module-load assertion passes.
- [ ] `propose_search_space` is NOT in `MUTATING_TOOL_NAMES`.
- [ ] `EXPECTED_TOOL_COUNT_MVP1 == 20` and canonical name set updated.
- [ ] `make test-unit` includes the new test file; all listed cases pass.
- [ ] `mypy --strict` clean.
- [ ] `ruff check` + `ruff format` clean.
- [ ] All 12 AC cases above traceable to specific tests in the new file via test docstrings.

### Story 3.3 — Telemetry: emit `agent.search_space_proposed` + `agent.create_study.invoked`

**Outcome:** `propose_search_space_impl` (Story 3.2) emits its INFO event before returning. `create_study_impl` is modified to emit `agent.create_study.invoked` after search-space validation (between current lines 35-46 and the FK resolution at 49+). Both events carry `conversation_id`. Unit tests via `backend/tests/_log_helpers.py` assert event names and field shapes.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/unit/agent/test_propose_search_space_telemetry.py` | Asserts `agent.search_space_proposed` fires with expected fields on every successful impl call. |
| `backend/tests/unit/agent/test_create_study_telemetry.py` | Asserts `agent.create_study.invoked` fires after search-space validation, even when subsequent FK resolution raises 404. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/agent/tools/studies/create_study.py` | Add `import structlog`; `logger = structlog.get_logger(__name__)`; insert telemetry emit between step 1 (search_space validation, lines 35-46) and step 2 (FK resolution, line 48+). Wrap the emit in `try/except Exception: pass` (telemetry must not block dispatch, spec FR-6). Fields per spec FR-6. Also generate `study_id` UUIDv7 earlier (currently line 105) so the telemetry emit can include `study_id_pending` — relocate the UUID generation to step 1.5. |
| `backend/app/agent/tools/studies/propose_search_space.py` | Story 3.2's `logger.info(...)` block (already designed in Story 3.2 — this story validates it under test). |

**Endpoints:** N/A.

**Key interfaces** — log event schemas:

```
INFO agent.search_space_proposed
  conversation_id: str
  template_id: str
  cluster_id: str
  judgment_list_id: str | None
  prior_study_id: str | None
  param_names: list[str]  # sorted
  cardinality: int
  narrowed_param_names: list[str]

INFO agent.create_study.invoked
  conversation_id: str
  study_id_pending: str  # UUIDv7, before DB insert
  template_id: str
  cluster_id: str
  search_space_param_names: list[str]  # sorted
  search_space_cardinality: int
```

**Pydantic schemas:** N/A.

**Tasks**
1. Modify `backend/app/agent/tools/studies/create_study.py`:
   - Add `import structlog` + `logger = structlog.get_logger(__name__)`.
   - Move `study_id = str(uuid_utils.uuid7())` from current line 105 to before step 2 (FK resolution at line 48) so it's available for the telemetry emit.
   - After step 1 (search_space validation) and BEFORE step 2 (FK resolution), insert the `logger.info("agent.create_study.invoked", ...)` call.
   - Pass `study_id_pending=study_id` (already generated) and the search_space metadata fields.
   - Keep the existing DB INSERT at step 5 — pass `id=study_id` (already in scope).
2. Write `backend/tests/unit/agent/test_create_study_telemetry.py`:
   - Use `backend/tests/_log_helpers.py` `capture_logs()` pattern.
   - Test 1: happy-path create_study → asserts `agent.create_study.invoked` is in captured events with all required fields.
   - Test 2: create_study with invalid search_space → `INVALID_SEARCH_SPACE` raised BEFORE the telemetry fires → assert event count for `agent.create_study.invoked == 0`.
   - Test 3: create_study with valid search_space but unknown cluster_id → telemetry SHOULD fire (search_space validation passed) AND `CLUSTER_NOT_FOUND` raised.
3. Write `backend/tests/unit/agent/test_propose_search_space_telemetry.py`:
   - Happy-path → `agent.search_space_proposed` emitted once with all required fields.
   - With prior_study_id narrowing → event fires with non-empty `narrowed_param_names`.
   - Template mismatch → event fires with empty `narrowed_param_names` + the separate WARN `agent.propose_search_space.prior_template_mismatch` also fires.
   - **Logger-failure swallow:** monkeypatch `logger.info` to raise `RuntimeError("structlog blew up")` and assert the impl still returns its result dict unchanged (no exception propagates). Same test pattern for `create_study_impl` in the sibling telemetry test file — telemetry must never block dispatch (spec FR-6).
4. Confirm the events are at the `info` level by inspecting the `capture_logs` output (the helpers expose log level on each event).

**Definition of Done**
- [ ] `agent.create_study.invoked` fires on every `create_study_impl` call where search_space validates, regardless of subsequent failures.
- [ ] `agent.search_space_proposed` fires on every successful `propose_search_space_impl` return.
- [ ] Both events tagged with the `conversation_id` from `ctx.conversation_id`.
- [ ] All three telemetry tests pass.
- [ ] `make test-unit` is green.
- [ ] Manual smoke: run a tool dispatch locally, `grep agent.search_space_proposed` in `make logs` output, confirm the event appears.

**Epic 3 gate:** Stories 3.1, 3.2, 3.3 all DoD-green. After this gate, the tool is fully registered, the telemetry seam exists, and tests cover all 16 ACs except the prompt snapshot (AC-16) and the integration assertion (cross-epic).

---

## Epic 4 — System prompt + integration

### Story 4.1 — System-prompt update + snapshot test

**Outcome:** `prompts/orchestrator.system.md` is updated per FR-5 (tool count 19→20; `Studies (4)` row with `propose_search_space`; chain-guidance bullet). A new snapshot test `backend/tests/unit/agent/test_orchestrator_system_prompt_inventory.py` reads the prompt file and asserts the four invariants in AC-16.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/unit/agent/test_orchestrator_system_prompt_inventory.py` | Snapshot test for the four AC-16 invariants. |

**Modified files**

| File | Change |
|---|---|
| `prompts/orchestrator.system.md` | Tool count `19` → `20` (line 9); studies inventory line at line 17 → `Studies (4): propose_search_space, create_study (mutating), get_study, cancel_study (mutating)`; insert new rule (or extend rule #1) directing the LLM to chain `propose_search_space` before `create_study`. Mutation set bullet (rule #2) unchanged — `propose_search_space` is read-only. |

**Endpoints:** N/A.

**Key interfaces:** N/A (markdown content).

**Pydantic schemas:** N/A.

**Tasks**
1. Edit `prompts/orchestrator.system.md`:
   - Change "You have 19 tools" → "You have 20 tools" (line 9).
   - Change the Studies bullet (line 17) to `Studies (4): \`propose_search_space\`, \`create_study\` (mutating), \`get_study\`, \`cancel_study\` (mutating)`.
   - Add a new sentence at the end of behavior rule #1 (line 26) or as a sub-bullet: "**Chain propose_search_space before create_study.** When the user asks to start an optimization study, call `propose_search_space(template_id, cluster_id, prior_study_id?)` first; pass `result.search_space` verbatim into `create_study.search_space` and cite the `grounding` fields in your chat reply."
2. Write `backend/tests/unit/agent/test_orchestrator_system_prompt_inventory.py`:
   - Open `prompts/orchestrator.system.md`, read content.
   - Assert `"You have 20 tools"` substring present (exact case).
   - Assert the studies line names `propose_search_space` and lists it FIRST in the Studies (4) row.
   - Assert that within the mutation-set bullet (rule #2, the 7-tool list), `propose_search_space` does NOT appear.
   - Assert a regex match for `before\s+calling\s+\W?create_study\W?` (or equivalent phrase) to catch the chain-guidance sentence.

**Definition of Done**
- [ ] `prompts/orchestrator.system.md` updated per spec FR-5.
- [ ] `backend/tests/unit/agent/test_orchestrator_system_prompt_inventory.py` passes.
- [ ] `cd ui && pnpm test` does NOT touch this file (no UI dependency on prompt content); confirm CI parity.

### Story 4.2 — Integration test: full propose → create_study chain through orchestrator

**Outcome:** A new integration test at `backend/tests/integration/test_agent_propose_search_space_dispatch.py` exercises the orchestrator's dispatch loop with a stubbed LLM, simulating the LLM calling `propose_search_space` followed by `create_study` with the proposed search_space. Verifies a study row lands in DB with the proposed JSON intact + both telemetry events fire with the same `conversation_id`.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/integration/test_agent_propose_search_space_dispatch.py` | Integration test described above. |

**Modified files** — none.

**Endpoints:** N/A.

**Key interfaces** — none new; uses existing orchestrator + tool registry.

**Pydantic schemas:** N/A.

**Tasks**
1. Read an existing orchestrator integration test under `backend/tests/integration/` (search for `orchestrator` or `run_turn`) to identify the LLM-stubbing pattern.
2. Create `backend/tests/integration/test_agent_propose_search_space_dispatch.py`:
   - Seed a cluster + query template + query set + judgment list via existing test fixtures.
   - Stub the OpenAI client to emit two tool_calls in sequence: first `propose_search_space(template_id=..., cluster_id=...)`, then (after consuming the tool_result) `create_study(...)` with the proposed `search_space` from the first result.
   - Capture structlog events via `backend/tests/_log_helpers.py`.
   - Assert: study row exists in DB with `search_space` matching the propose result; both `agent.search_space_proposed` and `agent.create_study.invoked` events captured with the same `conversation_id`.
3. Mark the test with `@pytest.mark.integration` (per `CLAUDE.md` test-layer convention).

**Definition of Done**
- [ ] `make test-integration` includes the new test; it passes against a service-container Postgres.
- [ ] Both telemetry events captured in the test's log assertions.
- [ ] No `ctx.db.commit()` call from `propose_search_space_impl` (assert via mock or by checking commit count).

**Epic 4 gate:** Stories 4.1, 4.2 DoD-green. All 16 ACs covered by tests.

---

## Epic 5 — Documentation

### Story 5.1 — Doc deltas + state/architecture refresh

**Outcome:** Architecture, agent-tools, llm-orchestration, mvp1-user-stories, agent-debugging runbook, and `state.md` are updated per spec §15. `architecture.md` does NOT need updates (the architecture is unchanged — no new layer, no new external integration), but a one-line note about the propose_search_space tool may be added under "Topical architecture docs" if relevant. Verify and skip if no narrative change is warranted.

**New files** — none.

**Modified files**

| File | Change |
|---|---|
| `docs/01_architecture/agent-tools.md` | Update tool inventory section: count 19→20; add `propose_search_space` row with purpose + read-only marker. |
| `docs/01_architecture/llm-orchestration.md` | Add a one-paragraph note under "Function-calling pattern" describing the propose-then-create chain expectation + the paired-INFO-event telemetry. |
| `docs/02_product/mvp1-user-stories.md` | Extend the `feat_chat_agent` story group (or add a new story) covering the chain: "As a relevance engineer, when I ask the agent to start a study, it grounds the bounds via `propose_search_space` before calling `create_study`." |
| `docs/03_runbooks/agent-debugging.md` | Add a paragraph on how to grep both adherence events (`agent.search_space_proposed`, `agent.create_study.invoked`) and correlate them by `conversation_id` to compute adherence ratio. Sample `make logs` grep command. |
| `state.md` | Append to "Most recent meaningful changes" with the feature's PR + Alembic-head-unchanged note + telemetry-event-name reference. Update "Active feature" to none-in-flight after merge. |

**Endpoints:** N/A.

**Key interfaces:** N/A.

**Pydantic schemas:** N/A.

**Tasks**
1. Update `docs/01_architecture/agent-tools.md` — add row for `propose_search_space` in the tool inventory table (or list), mark read-only, link to spec.
2. Update `docs/01_architecture/llm-orchestration.md` — one paragraph under "Function-calling pattern" (or equivalent section — read first) about the chain.
3. Update `docs/02_product/mvp1-user-stories.md` — add the story bullet.
4. Update `docs/03_runbooks/agent-debugging.md` — add the grep section.
5. Update `state.md`:
   - "Current branch / execution context": branch name + PR # filled in by `/impl-execute` finalization.
   - "Most recent meaningful changes": one entry with the feature name, PR #, telemetry event names, no-migration note.
6. Confirm `architecture.md` does NOT need changes (no new top-level layer; no new critical flow). State explicitly in the PR description if skipped.
7. Confirm `CLAUDE.md` does NOT need new conventions (no new env var, no new build command, no new absolute rule).

**Definition of Done**
- [ ] All 5 modified docs reflect the shipped behavior.
- [ ] `state.md` "recent changes" includes this feature with the merged PR #.
- [ ] No drift between spec §15 and the actual doc deltas.

**Epic 5 gate:** Story 5.1 DoD-green. Feature is documentation-complete.

---

## UI Guidance

**No UI Guidance required** — no user-facing UI component is added, deleted, or migrated by this plan. The only frontend code change (Story 1.2) is to a pure-function library (`ui/src/lib/search-space-defaults.ts`) and its call site (`create-study-modal.tsx`'s Step-3→4 transition effect), which already uses the existing modal-error toast pattern for the new throw paths. There is no new card, no new form, no new modal, no navigation change, no tooltip, no `<select>` change.

**No legacy behavior parity table** — no user-facing component >100 LOC is being deleted or migrated in this plan. The wizard modal continues to work as before; only its internal call to `buildStarterSearchSpace` is updated for the new return shape, and the throw cases surface as the existing modal-level error toast.

---

## 3) Testing workstream (required)

### 3.1 Unit tests
- **Location:** `backend/tests/unit/`
- **Scope:** Domain helpers (Stories 1.1, 1.3), ToolContext field (3.1), tool impl + registry (3.2), telemetry (3.3), prompt snapshot (4.1).
- **Tasks:**
  - [ ] `backend/tests/unit/domain/test_search_space_defaults.py` — Story 1.1 (FR-1, FR-3, FR-4, AC-1, AC-2, AC-3, AC-4, AC-12, AC-13, AC-15)
  - [ ] `backend/tests/unit/domain/test_search_space_defaults_parity.py` — Story 1.3 (FR-7, AC-10, AC-13)
  - [ ] `backend/tests/unit/agent/test_tool_context_conversation_id.py` — Story 3.1
  - [ ] `backend/tests/unit/agent/test_propose_search_space.py` — Story 3.2 (FR-2, FR-3, FR-4, AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7, AC-11, AC-12, AC-13, AC-14, AC-15)
  - [ ] `backend/tests/unit/agent/test_propose_search_space_telemetry.py` — Story 3.3 (FR-6, AC-8)
  - [ ] `backend/tests/unit/agent/test_create_study_telemetry.py` — Story 3.3 (FR-6, AC-9)
  - [ ] `backend/tests/unit/agent/test_orchestrator_system_prompt_inventory.py` — Story 4.1 (FR-5, AC-16)
  - [ ] `backend/tests/unit/agent/test_tool_registry.py` — Story 3.2 update (AC-11)
- **DoD:** All cases pass; coverage gate (80%) green; mypy strict clean.

### 3.2 Integration tests
- **Location:** `backend/tests/integration/`
- **Scope:** Repo helper round-trip (Story 2.1); orchestrator dispatch chain (Story 4.2).
- **Tasks:**
  - [ ] `backend/tests/integration/test_trial_repo.py` — `get_trial` found / not-found (Story 2.1)
  - [ ] `backend/tests/integration/test_agent_propose_search_space_dispatch.py` — full propose→create chain (Story 4.2; FR-2, FR-6)
- **DoD:** Both pass against the service-container Postgres in CI; happy path + critical failure paths covered.

### 3.3 Contract tests
- **Location:** `backend/tests/contract/`
- **Scope:** **N/A — no REST endpoint added.** The tool's wire shape is the Pydantic-generated JSON schema; drift detection is handled by `test_tool_registry.py` (counts + canonical-names assertion) which the unit-tests workstream covers.
- **Tasks:** None.
- **DoD:** Confirm no new endpoint exists by reading `backend/app/api/`.

### 3.4 E2E tests
- **Location:** `ui/tests/e2e/`
- **Scope:** **N/A** — this feature does not change user-visible UI (Story 1.2 only swaps the return-value destructure pattern; modal behavior is preserved). Existing chat E2E coverage already exercises the agent surface.
- **Tasks:** None.
- **DoD:** No regressions in `ui/tests/e2e/studies.spec.ts` (the wizard's destructure change is backwards-compatible from the user's perspective).

### 3.5 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `ui/src/__tests__/lib/search-space-defaults.test.ts` | `const space = buildStarterSearchSpace(...)` | ~5 | Update destructure to `const { space } = buildStarterSearchSpace(...)` — Story 1.2. |
| `ui/src/__tests__/lib/search-space-defaults.cardinality.test.ts` | same | ~3 | same |
| `ui/src/__tests__/components/create-study-modal.*.test.tsx` | direct call to `buildStarterSearchSpace` | TBD | grep during Story 1.2; update only if any test reads the return value. |
| `backend/tests/unit/agent/test_tool_registry.py` | `EXPECTED_TOOL_COUNT_MVP1 = 19` + canonical name set | 1 | Update count to 20 + add `propose_search_space` to set — Story 3.2. |
| `backend/tests/unit/agent/conftest.py` | `ToolContext(db=..., redis=..., arq_pool=..., settings=...)` | 1 | Add `conversation_id=...` — Story 3.1. |
| `backend/tests/integration/test_agent_*` | any orchestrator dispatch fixture asserting tool count | TBD | audit during Story 3.2; adjust expected counts if snapshot-based. |

### 3.6 Migration verification
**N/A — no schema changes.**

### 3.7 CI gates
- [ ] `make test-unit`
- [ ] `make test-integration`
- [ ] `make test-contract` (existing; should pass with no changes)
- [ ] `cd ui && pnpm test` (existing + new parity test)
- [ ] `cd ui && pnpm typecheck` (the return-type change in Story 1.2 must propagate clean)
- [ ] `cd ui && pnpm lint`

---

## 4) Documentation update workstream

### 4.0 Core context files

**`state.md`** — update at finalization:
- [x] Active feature: `feat_agent_propose_search_space` in flight → none after merge.
- [x] Alembic head: unchanged (no migration).
- [x] "Most recent meaningful changes" entry covering PR #, the new telemetry events, the propose→create chain.

**`architecture.md`** — likely no changes. Read at finalization; add only if the propose tool warrants a new pointer (probably not — `docs/01_architecture/agent-tools.md` already covers the agent-tool layer).

**`CLAUDE.md`** — no changes (no new env var, no new build command, no new absolute rule).

### 4.1 Architecture docs
- [x] `docs/01_architecture/agent-tools.md` — Story 5.1.
- [x] `docs/01_architecture/llm-orchestration.md` — Story 5.1.

### 4.2 Product docs
- [x] `docs/02_product/mvp1-user-stories.md` — Story 5.1.

### 4.3 Runbooks
- [x] `docs/03_runbooks/agent-debugging.md` — Story 5.1.

### 4.4 Security docs
- No changes. The tool makes no LLM call, no engine call, no third-party network call.

### 4.5 Quality docs
- No changes. Existing test-layer convention covers this feature.

**Documentation DoD**
- [ ] `state.md`, `architecture.md`, `CLAUDE.md` consistent with shipped behavior (or explicitly unchanged with rationale).
- [ ] Docs across docs/01-05 consistent with shipped behavior.
- [ ] No drift between spec §15 and the actual doc deltas.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals
- None — this is a pure-add feature. No refactor work is bundled.

### 5.2 Planned refactor tasks
- None.

### 5.3 Refactor guardrails
- Behavioral parity is structural: existing TS unit tests must continue to pass under Story 1.2's return-shape change. The destructure migration is the only "refactor" in this plan, and it's bounded to lib + one caller + tests.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `feat_chat_agent` (PR #60) | All Epic 3 stories | Implemented (on `main`) | None — already shipped. |
| `chore_create_study_wizard_polish` (PR #157) — `ui/src/lib/search-space-defaults.ts` | Stories 1.1, 1.2, 1.3 | Implemented (on `main`) | None — already shipped. |
| `feat_create_study_search_space_builder` (PR #163) | Story 1.2 (the wizard caller surface) | Implemented (on `main`) | None — confirms the destructure migration only touches one caller. |
| `feat_study_lifecycle` Phase 2 (`Study.best_trial_id`, `Trial.params`) | Story 2.1, Story 3.2's narrowing path | Implemented (on `main`) | None — already shipped. |
| `infra_structlog_test_helpers` (PR #114) | Stories 3.1, 3.3 telemetry tests | Implemented (on `main`) | None — `backend/tests/_log_helpers.py` already factored. |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `ToolContext` plumbing has more construction sites than the 2 currently grep'd | L | M | Story 3.1 task 4 explicitly greps before changing the dataclass; any new site discovered is updated in the same story. |
| TS↔Python parity drift bug surfaces in CI but only on one half | L | M | Story 1.3 includes a manual "drift sanity check" (temporarily mutate one source, confirm both tests fail). |
| Stale prior_study with a different template silently degrades user expectations | M | L | Spec FR-3 + AC-14 require WARN log + `prior_study_template_mismatch` grounding flag so operators can see the degrade; AC-14 has a dedicated test. |
| Telemetry event name typo silently disables adherence measurement | L | M | Story 3.3 unit tests assert the exact event names against the spec; spec §FR-6 declares the names as stable identifiers. |
| `study_id_pending` UUIDv7 generation relocation (Story 3.3) interacts with an existing DB INSERT failure path | L | L | The UUID is generated client-side and assigned to a local var; the INSERT path is unchanged. Existing `create_study` integration tests catch any regression. |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| Template's `declared_params` is empty | Operator/admin somehow stores an empty dict in `query_templates.declared_params` (should never happen in production due to existing template validation) | Tool raises `INVALID_SEARCH_SPACE` 400; LLM sees the error in `<tool_result>` and surfaces a chat reply ("That template has no declared params — pick a different one"). | Operator-side data fix. |
| Cap-aware fallback exhausted | Template with many fall-through floats (≥8) and no name matching any HEURISTIC_RULES rule | Tool raises `INVALID_SEARCH_SPACE` 400; LLM apologizes and asks the operator to manually specify a narrower starter space. | The chain re-attempts via direct `create_study` with operator-supplied search_space. |
| Prior study fetched but trial row missing (cascade-delete race) | Operator deleted a prior study mid-conversation | Tool degrades to heuristic-only + emits `agent.propose_search_space.missing_winner_trial` WARN. | Automatic — no operator action needed. |
| Prior study template mismatch | LLM passed the wrong `prior_study_id` | Tool degrades to heuristic-only + sets `prior_study_template_mismatch: true` in grounding + emits WARN. | LLM reads grounding flag and adjusts chat reply. |
| `ctx.db` connection lost between FK lookups | Postgres restart mid-call | `sqlalchemy.exc.OperationalError` propagates → orchestrator catches → wraps in `<tool_result>` error envelope. | Operator-side retry. |

---

## 7) Sequencing and parallelization

### Suggested sequence
1. **Epic 1** (Stories 1.1, 1.2, 1.3) — domain helper + TS parity. Story 1.1 first (Python source-of-truth), then 1.2 (TS in parallel-eligible after 1.1's contract is clear), then 1.3 (fixture + both parity tests).
2. **Epic 2** (Story 2.1) — repo helper. Parallel-eligible with Epic 1 (no overlap).
3. **Epic 3** (Stories 3.1, 3.2, 3.3) — agent surface. 3.1 first (ToolContext), then 3.2 (tool impl needs 3.1 + Epic 1 + Epic 2 done), then 3.3 (telemetry).
4. **Epic 4** (Stories 4.1, 4.2) — system prompt + integration. 4.1 in parallel with Epic 3. 4.2 after Epic 3.
5. **Epic 5** (Story 5.1) — docs. Last; consumes the merged code.

### Parallelization opportunities
- Epic 1 ↔ Epic 2 fully parallel (no shared files).
- Story 4.1 can start as soon as Story 3.2 is in progress (just needs the tool name `propose_search_space` locked).
- Story 5.1 deferred until everything else lands so doc claims match shipped code.

In `/impl-execute --all` (sequential by default), the natural order is 1.1 → 1.2 → 1.3 → 2.1 → 3.1 → 3.2 → 3.3 → 4.1 → 4.2 → 5.1.

---

## 8) Rollout and cutover plan

- **Rollout stages:** Local dev only (MVP1 has no remote staging). Feature is additive — the new tool exists in the registry but is only invoked when the LLM chooses to call it. Until the system prompt updates roll out (atomic with the registry change in this PR), the LLM doesn't know the tool exists.
- **Feature-flag strategy:** None. The feature is additive and read-only; no runtime gate is justified.
- **Migration/cutover steps:** None. No schema changes.
- **Reconciliation/repair strategy:** N/A — no external system involved.

---

## 9) Execution tracker (copy/paste section)

### Current sprint
- [ ] Story 1.1 — Port `search_space_defaults.py` from TS with overflow guard + narrowing helper
- [ ] Story 1.2 — TS-side parity changes to `ui/src/lib/search-space-defaults.ts`
- [ ] Story 1.3 — Shared TS↔Python parity fixture + parity tests
- [ ] Story 2.1 — Add `repo.get_trial(db, trial_id)` to `backend/app/db/repo/trial.py`
- [ ] Story 3.1 — Add `conversation_id: str` to `ToolContext` and plumb from orchestrator
- [ ] Story 3.2 — New tool `propose_search_space.py` + registry wiring
- [ ] Story 3.3 — Telemetry: emit `agent.search_space_proposed` + `agent.create_study.invoked`
- [ ] Story 4.1 — System-prompt update + snapshot test
- [ ] Story 4.2 — Integration test for full propose → create_study chain
- [ ] Story 5.1 — Doc deltas + state refresh

### Blocked items
- None at plan time.

### Done this sprint
- (none yet)

---

## 10) Story-by-Story Verification Gate (Agent Checklist)

Before marking any story complete:

- [ ] Files created/modified match story scope (New/Modified tables verified).
- [ ] Endpoint contract (where applicable) implemented exactly as the spec documents (this feature: agent-tool wire shape only).
- [ ] Key interfaces implemented with compatible signatures.
- [ ] Required tests added at all relevant layers per the layer table above.
- [ ] Commands executed and passed:
  - [ ] `make test-unit`
  - [ ] `make test-integration` (or targeted subset with explanation)
  - [ ] `make test-contract` (no changes expected — confirm pass)
  - [ ] `cd ui && pnpm test` (Stories 1.2, 1.3)
  - [ ] `cd ui && pnpm typecheck` (Story 1.2)
- [ ] Migration round-trip: N/A.
- [ ] Related docs updated in same PR when behavior/contract changes (Epic 5 covers this; per-story docs at most).

---

## 11) Plan consistency review

| # | Check | Result |
|---|---|---|
| 1 | Spec endpoint count ↔ plan endpoint count | N/A — agent tool only, no REST endpoints. Plan §3.3 explicitly N/A. ✅ |
| 2 | Spec error codes (§7.5) ↔ plan contract test coverage | All 5 spec error codes (`INVALID_SEARCH_SPACE`, `TEMPLATE_NOT_FOUND`, `CLUSTER_NOT_FOUND`, `JUDGMENT_LIST_NOT_FOUND`, `STUDY_NOT_FOUND`) covered by Story 3.2's unit-test list (test cases 7-13 in `test_propose_search_space.py`). ✅ |
| 3 | Spec FR coverage ↔ plan §1 traceability | 7 FRs in spec; 7 rows in §1 above. ✅ |
| 4 | Story internal consistency | Each story's New/Modified files audited against the codebase (see Verification ledger below). ✅ |
| 5 | Test file count ↔ workstream inventory | 8 unit test files + 2 integration test files = 10 test files. Each is assigned to a specific story (§3.1, §3.2). No orphans. ✅ |
| 6 | Gate arithmetic | Epic 1 gate (3 stories), Epic 2 gate (1 story), Epic 3 gate (3 stories), Epic 4 gate (2 stories), Epic 5 gate (1 story) = 10 stories. Matches §9 execution tracker. ✅ |
| 7 | Open questions resolved | Spec §19 lists "None at spec time" — confirmed. ✅ |
| 8 | Frontend UI Guidance | Skipped with rationale (no >100 LOC component delete/migrate; only library-call destructure change). ✅ |
| 9 | Legacy behavior parity table | Skipped with rationale (same as above). ✅ |
| 10 | Enumerated value contract audit | Spec §7.4 lists only the existing `ParamSpec.type` discriminator + tool-error `error_code` allowlist. No new UI dropdowns added. ✅ |
| 11 | Audit-event coverage | N/A — MVP1 has no `audit_log` table; spec §6 states audit_log lands at MVP2. The structlog INFO events (FR-6) are the v1 surrogate. ✅ |

### Verification ledger

| Claim | Verified by | Status |
|---|---|---|
| `backend/app/agent/tools/__init__.py:141-228` has the 3-struct registry + module-load assertion | Read file lines 141-228 | Verified |
| `backend/app/agent/tools/studies/create_study.py:35-46` is the search_space validation step | Read file | Verified |
| `backend/app/agent/confirmation.py:14-24` defines `MUTATING_TOOL_NAMES` and does NOT include `propose_search_space` | Read file | Verified — `propose_search_space` stays out |
| `backend/app/agent/context.py:20` `ToolContext` currently has 4 fields (`db`, `redis`, `arq_pool`, `settings`) | Read file | Verified — adding `conversation_id` makes 5 |
| Only 2 `ToolContext(...)` construction sites exist | `rg 'ToolContext\(' --type py` → 2 hits (agent_chat.py:244, conftest.py:139) | Verified |
| `backend/app/db/repo/trial.py` has no `get_trial` function | `grep -n "^async def \|^def " backend/app/db/repo/trial.py` | Verified — only `create_trial`, `list_trials_for_study`, `list_trials_paginated`, `count_trials`, `aggregate_trials_summary` |
| `backend/app/db/repo/study.py:61-64` has `async def get_study(db, study_id) -> Study \| None` | Read file | Verified — template for `get_trial` |
| `backend/tests/unit/domain/test_search_space_cardinality_parity.py` exists at the expected path | Read file (40 lines) | Verified — fixture under `backend/tests/_fixtures/search_space_cardinality_fixtures.json` |
| `backend/tests/_log_helpers.py` exists | `ls backend/tests/_log_helpers.py` | Verified |
| `ui/src/lib/search-space-defaults.ts` is the TS source-of-truth | Read file (211 lines) | Verified |
| `prompts/orchestrator.system.md:9` says "You have 19 tools" | Read file | Verified — target for `19` → `20` change |
| `prompts/orchestrator.system.md:17` is the Studies bullet (3 tools) | Read file | Verified — target for `(3)` → `(4)` + reorder |
| `backend/tests/unit/agent/test_tool_registry.py:23` has `EXPECTED_TOOL_COUNT_MVP1 = 19` | grep | Verified |
| `backend/tests/unit/agent/test_tool_registry.py:28` has `CANONICAL_MVP1_TOOL_NAMES = frozenset(...)` | grep | Verified |
| Alembic head is `0014_clusters_target_filter` per `state.md` | `state.md` reads "Alembic head: `0014_clusters_target_filter`" | Verified — NO migration in this plan, head unchanged |
| `Study.best_trial_id` column exists (line 80 of model file) | Read `backend/app/db/models/study.py` | Verified |
| `Trial.params` column exists (line 55 of model file) | Read `backend/app/db/models/trial.py` | Verified |

---

## 12) Definition of plan done

- [x] Every FR is mapped to stories/tasks/tests/docs updates (§1).
- [x] Every story includes New files, Modified files, Endpoints (or N/A with reason), Key interfaces, Tasks, DoD.
- [x] Test layers explicitly scoped (§3).
- [x] Documentation updates planned and owned (§4, Story 5.1).
- [x] Lean refactor scope explicit (§5 — none, with rationale).
- [x] Epic gates measurable.
- [x] Story-by-Story Verification Gate included (§10).
- [x] Plan consistency review performed with all checks passing (§11).
- [x] Cross-model GPT-5.5 review scheduled (next step after this draft).
