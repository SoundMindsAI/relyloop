# Implementation Plan — infra_optuna_eval

**Date:** 2026-05-10
**Status:** Complete (PR #23, merged 2026-05-10 as squash commit `c4f1aab`). GPT-5.5 plan review converged at cycle 3 (28 findings, all accepted); final-review cycle on the merged diff produced 4 findings (3 accepted + applied in commit `3b112f9`; 1 rejected with cited counter-evidence — AC-7 covered at adapter+worker layer composition).
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy source(s):** [`docs/01_architecture/optimization.md`](../../../01_architecture/optimization.md), [`docs/01_architecture/adapters.md`](../../../01_architecture/adapters.md), [`docs/01_architecture/data-model.md`](../../../01_architecture/data-model.md), [`CLAUDE.md`](../../../../CLAUDE.md)
**Tangential discovery filed:** [`chore_infra_optuna_eval_spec_text_drift/idea.md`](../../../00_overview/planned_features/chore_infra_optuna_eval_spec_text_drift/idea.md) (spec §14 vs §11 wording drift around the partial-failure retry contract — controlling §11 is honored by the plan; §14 needs a one-paragraph rewrite).

---

## 0) Planning principles

- Spec traceability first: every story/task maps to FR IDs.
- Phase gates are hard stops.
- Fail-loud tests: assert explicit status/shape/errors.
- Keep repository patterns consistent with the shipped layers (`backend/app/adapters/`, `backend/app/db/repo/`, `backend/workers/`).
- Keep increments narrow enough to verify independently.
- No new tables — schema is `0003_study_lifecycle_schema` (per spec §9).
- Worker-internal feature — no HTTP endpoints; no UI; no E2E layer (per spec §3 / §11).

## 1) Scope traceability (FR → epics/stories)

| FR ID | Epic / Story | Notes |
|---|---|---|
| FR-1 (Optuna RDBStorage isolation + lazy table creation) | Epic 2 / Story 2.1 | Builder constructs `RDBStorage` with `options=-csearch_path=optuna`. Lazy create on first `create_study()` use. |
| FR-2 (TPE + MedianPruner defaults; pruner auto-disable; explicit-override) | Epic 2 / Story 2.1 | `build_sampler()` + `build_pruner()` honor key-presence-vs-absence semantics. |
| FR-3 (pytrec_eval evaluator + wire-name translation) | Epic 1 / Story 1.2 | `score()` + frozensets + `objective_metric_key()` + translation table. |
| FR-4 (`run_trial` Arq job) | Epic 2 / Story 2.3 | Job at `backend/workers/trials.py`; registered in `WorkerSettings.functions`. Idempotency + reconciliation per spec §11. |
| FR-5 (trial metrics persisted; primary denormalized; duration_ms) | Epic 2 / Story 2.3 | Persisted via `repo.create_trial(...)`. `objective_metric_key()` reused for the denormalization key. |

**Deferred-phase tracking:** Per spec §3 "Phase boundaries" — single-phase feature, no deferred FRs. No `phase<N>_idea.md` artifact required.

## 2) Delivery structure

Three epics, executed sequentially. Stories within an epic may be parallelized by independent file ownership; the gates between epics are hard stops.

### Story-level detail requirements

Each story includes Outcome, New files, Modified files, Key interfaces, Tasks, and DoD. Endpoints/Pydantic schemas/UI inventory sections are omitted — this feature has no API or UI surface.

### Conventions (this feature)

- Async by default. Optuna's `RDBStorage` is synchronous (per spec §5) — wrap **every** RDB-backed Optuna call in `asyncio.to_thread()` from async contexts (worker, tests). That includes `create_study` / `load_study` / `study.tell` AND `study.trials[N]` (the lazy collection access that hits RDBStorage). Once a `FrozenTrial` is loaded, attribute reads on it (`.params` / `.value` / `.state` / `.number`) are local dict/scalar reads that do NOT re-touch storage — but to avoid coupling to Optuna's internal lazy-loading details across versions, **always snapshot the trial via a single `asyncio.to_thread`-wrapped helper** that returns a plain dataclass (`number`, `state`, `params`, `value`) and use the snapshot in async code from then on. See Story 2.3 task 2.5 for the snapshot helper definition.
- **`study.tell()` accepts a trial number, not a `FrozenTrial`.** Optuna's public API signature is `Study.tell(trial: int | Trial, values=None, state=...)`. The worker MUST pass the integer `optuna_trial_number` to `tell()` — passing a `FrozenTrial` raises at runtime on current Optuna versions. (Cycle-2 review A1 caught this; the plan now uses the integer form everywhere.)
- Repo functions take `db: AsyncSession` first; caller commits (per CLAUDE.md "Repository Layer").
- Domain-style modules live under `backend/app/eval/` (analogous to `backend/app/adapters/` — pure logic + thin runtime wrappers, no HTTP). Worker job code lives under `backend/workers/` (analogous to `backend/workers/all.py`).
- Settings are read via `get_settings()` — never `Settings()` direct.
- Structlog context: every `run_trial` log record binds `trial_id`, `study_id`, `optuna_trial_number` via `structlog.contextvars.bind_contextvars()`.
- Never hardcode pytrec_eval wire-name strings outside `scoring.py` — the translation table is its single source of truth.
- **Orchestrator vs. worker contract for Optuna trials (spec §11 lock-in):** Phase 2's orchestrator (when it ships) is responsible for **(a)** calling `study.ask()` to allocate a trial number AND **(b)** calling `trial.suggest_int/float/categorical(...)` against that trial to populate `FrozenTrial.params` (per `studies.search_space`) — both *before* enqueueing `run_trial(study_id, trial.number)`. The worker reads `study.trials[N].params` and never calls `ask()` or any `suggest_*` (calling either would create a duplicate trial). Integration tests in Epic 3 simulate the orchestrator's responsibility explicitly: they invoke `ask()` + `suggest_*` directly in test setup before running the worker.
- **Fault-injection seam for partial-failure tests:** The worker reads an env var `INFRA_OPTUNA_EVAL_FAULT` at carefully chosen seams and calls `os._exit(1)` when matched. This is the ONLY production-safe way to simulate worker death across a subprocess boundary (pytest monkeypatch state does not survive a fresh Python interpreter — finding documented in plan §6 Risks). Valid values are enumerated in Story 2.3.

### AI Agent Execution Protocol (applies to every story)

0. **Load context first**: Re-read [`feature_spec.md`](feature_spec.md), [`state.md`](../../../../state.md), [`architecture.md`](../../../../architecture.md), and `docs/01_architecture/optimization.md` before starting Story 1.1.
1. **Read scope**: verify story outcome + key interfaces + DoD.
2. **Implement backend code first**: types → scoring → optuna_runtime → qrels_loader → trials worker → worker registration.
3. **Run backend tests** for each story (unit tests baked into each story's DoD).
4. **Run integration tests** in Epic 3 after the runtime is wired.
5. **Update docs/runbooks** in Epic 3 Story 3.3.
6. **Verify Alembic round-trip** — N/A this feature, no migration. Confirm with `ls migrations/versions/` that no new file was added.
7. **Attach evidence** in PR description: commands run, pass/fail, files changed.
8. **After the final story**, update `state.md` and `architecture.md` (Story 3.3).

Story completion is invalid if any step above is skipped.

---

## Epic 1 — pytrec_eval scoring helpers + types

**Goal:** Ship the pure-functional scoring layer with full unit-test coverage so Epic 2's `run_trial` has a vetted dependency to call.

### Story 1.1 — Add Optuna + pytrec_eval deps; create `backend/app/eval/types.py`

**Outcome:** `optuna>=3.6` and `pytrec_eval>=0.5` are installed. `SamplerKind`, `PrunerKind`, and `TrialStatus` Literals live at a single import path; the `eval` package exists and imports cleanly.

**New files**

| File | Purpose |
|---|---|
| `backend/app/eval/__init__.py` | Empty package marker — explicitly empty (no re-exports) so module imports stay unambiguous. |
| `backend/app/eval/types.py` | `SamplerKind = Literal["tpe", "random"]`, `PrunerKind = Literal["median", "none"]`, `TrialStatus = Literal["complete", "failed", "pruned"]` (per spec §8.4). |
| `backend/tests/unit/eval/__init__.py` | Empty package marker for the unit-test subpackage. |
| `backend/tests/unit/eval/test_types.py` | Smoke test: imports the three Literals and asserts their `__args__`. |

**Modified files**

| File | Change |
|---|---|
| `pyproject.toml` | Add `"optuna>=3.6"` and `"pytrec_eval>=0.5"` to `[project].dependencies`. |
| `uv.lock` | Regenerated by `uv lock` after editing `pyproject.toml`. |

**Key interfaces** — none beyond the Literal exports listed above.

**Tasks**

1. Edit `pyproject.toml`: append `"optuna>=3.6"` and `"pytrec_eval>=0.5"` to the `dependencies` list (preserve existing ordering).
2. Run `uv lock` to regenerate `uv.lock`; commit both files in this story.
3. Create `backend/app/eval/__init__.py` (empty).
4. Create `backend/app/eval/types.py` with the three Literal aliases. Include a docstring citing spec §8.4 as the source-of-truth.
5. Create `backend/tests/unit/eval/__init__.py` (empty).
6. Create `backend/tests/unit/eval/test_types.py` — asserts each Literal's `__args__` exactly matches the spec §8.4 wire values.

**Definition of Done (DoD)**

- [ ] `uv sync` resolves cleanly; `import optuna` and `import pytrec_eval` succeed in a Python REPL.
- [ ] `backend/tests/unit/eval/test_types.py` passes (`uv run pytest backend/tests/unit/eval/test_types.py -v`).
- [ ] `make lint` and `make typecheck` green for the new files.
- [ ] No new migration files in `migrations/versions/` (sanity check — this story adds none).

---

### Story 1.2 — `backend/app/eval/scoring.py` (pytrec_eval helper, frozensets, denormalization key)

**Outcome:** Pure-functional scorer that translates user-facing metric names to pytrec_eval wire names, supports the spec §FR-3 metric set, and provides `objective_metric_key()` for primary-metric denormalization. Unit tests cover both happy path (matches a hand-curated baseline within 1e-6) and edge cases (unknown metric → `ValueError`; `map` vs `map@k` distinction; `objective.k=None` for `mrr`).

**New files**

| File | Purpose |
|---|---|
| `backend/app/eval/scoring.py` | `SUPPORTED_METRICS`, `SUPPORTED_K_VALUES`, `score()`, `objective_metric_key()`, `_translate_metric_name()`. |
| `backend/tests/unit/eval/test_scoring.py` | Hand-curated qrels/run fixture asserting nDCG@10 / MAP / P@10 / recall@10 / MRR within 1e-6; translation-table edge cases; `objective_metric_key()` contract. |
| `backend/tests/unit/eval/test_metric_validation.py` | Out-of-allowlist metric → `ValueError`; out-of-allowlist k → `ValueError`; `objective.k=None` flows for `mrr` + `map` (no cut). |

**Modified files**

| File | Change |
|---|---|
| `backend/app/eval/__init__.py` | No change (keep empty — callers import from explicit submodules). |

**Key interfaces**

```python
# backend/app/eval/scoring.py
from typing import TypedDict

SUPPORTED_METRICS: frozenset[str] = frozenset({"ndcg", "map", "precision", "recall", "mrr"})
SUPPORTED_K_VALUES: frozenset[int] = frozenset({1, 3, 5, 10, 20, 50, 100})

Qrels = dict[str, dict[str, int]]   # {query_id: {doc_id: rating}}
Run = dict[str, dict[str, float]]   # {query_id: {doc_id: score}}

class ScoreResult(TypedDict):
    aggregate: dict[str, float]
    per_query: dict[str, dict[str, float]]

def score(qrels: Qrels, run: Run, metrics: set[str]) -> ScoreResult: ...
    # Validates every metric token against SUPPORTED_METRICS/SUPPORTED_K_VALUES,
    # translates to pytrec_eval wire names via _translate_metric_name,
    # invokes RelevanceEvaluator(qrels, wire_names).evaluate(run),
    # then re-keys per_query/aggregate back to user-facing names.

def objective_metric_key(objective: dict[str, object]) -> str: ...
    # Returns the user-facing metric key used to index trials.metrics
    # for denormalization into trials.primary_metric (per spec FR-5).
    # Contract:
    #   ndcg/precision/recall → f"{metric}@{k}"   (k required)
    #   map  → f"map@{k}" if k present else "map" (full recall when k absent)
    #   mrr  → "mrr"                              (k ignored)
    # Raises ValueError on unknown metric or missing-required-k.

def _translate_metric_name(user_facing: str) -> str: ...
    # Single source of truth for the §FR-3 translation table.
    # ndcg@k → ndcg_cut_<k>; map@k → map_cut_<k>; map → map;
    # precision@k → P_<k>; recall@k → recall_<k>; mrr → recip_rank.
    # Raises ValueError on unparseable tokens.
```

**Tasks**

1. Create `backend/app/eval/scoring.py` with the frozenset constants, type aliases, and three functions (`_translate_metric_name`, `objective_metric_key`, `score`).
2. Implement `_translate_metric_name` as a pure parser. Reject unknown bases (`err`) and out-of-allowlist k.
3. Implement `objective_metric_key()` per the three-branch contract in §FR-5. Test all three branches plus error paths.
4. Implement `score()`:
   - Validate every metric token (call `_translate_metric_name` to get the wire name; collect into a `set[str]` for pytrec_eval).
   - Construct `pytrec_eval.RelevanceEvaluator(qrels, wire_names)`.
   - Call `evaluator.evaluate(run)` → per-query dict keyed by wire names.
   - Re-key per-query results back to user-facing names; aggregate (arithmetic mean) across queries.
   - Return `{"aggregate": ..., "per_query": ...}`.
5. Create `backend/tests/unit/eval/test_scoring.py` with a 5-query × 4-doc hand-curated qrels + run fixture. **AC-3 covered metrics (`ndcg@10` and `map@10`) MUST use independently hand-computed baseline values** — do not pin to the implementation's first output for those two metrics, since that would assert the library against itself. Compute expected nDCG@10 from the DCG/IDCG formula and MAP@10 from the canonical precision-at-k summation; show the math in a fixture docstring. Other metrics (recall@10, MRR) MAY be pinned from a smoke run to guard against future regressions, but the AC-3 pair must be hand-derived.
6. Create `backend/tests/unit/eval/test_metric_validation.py` for the error paths.

**Definition of Done (DoD)**

- [ ] `uv run pytest backend/tests/unit/eval/test_scoring.py backend/tests/unit/eval/test_metric_validation.py -v` — all pass.
- [ ] `aggregate['ndcg@10']` matches hand-computed baseline within 1e-6 (AC-3 covered at unit level; integration repeat in Epic 3).
- [ ] Coverage of `backend/app/eval/scoring.py` ≥ 95% (the file is pure; high coverage is reachable).
- [ ] `make lint` and `make typecheck` green.

---

## Epic 1 gate — eval helpers shippable

- [ ] Stories 1.1 + 1.2 complete; all unit tests green.
- [ ] `backend/app/eval/scoring.py` and `backend/app/eval/types.py` cover every spec §8.4 enumerated value.
- [ ] No imports of `pytrec_eval` exist outside `backend/app/eval/scoring.py` (grep -rn "import pytrec_eval" backend/ should return exactly one match).

---

## Epic 2 — Optuna runtime + `run_trial` job

**Goal:** Build the production code that turns a `(study_id, optuna_trial_number)` pair into a persisted `trials` row.

### Story 2.1 — `backend/app/eval/optuna_runtime.py` (study factory, sampler/pruner builders)

**Outcome:** A reusable helper that constructs/loads an Optuna study against the app Postgres with the `optuna.*` schema isolated, builds the configured sampler + pruner, and applies the spec §FR-2 default + auto-disable + explicit-override semantics. URL composition is factored into a pure helper so unit tests don't depend on Optuna's constructor opening (or not opening) a DB connection.

**New files**

| File | Purpose |
|---|---|
| `backend/app/eval/optuna_runtime.py` | `_compose_storage_url()` (pure), `build_storage()`, `build_sampler()`, `build_pruner()`, `get_or_create_study()`. |
| `backend/tests/unit/eval/test_optuna_runtime.py` | Sampler/pruner default + override + auto-disable behavior (AC-2, AC-6a, AC-6b); URL-composition unit test against the pure `_compose_storage_url`. |

**Modified files** — none.

**Key interfaces**

```python
# backend/app/eval/optuna_runtime.py
from typing import Any
import optuna
from optuna.samplers import BaseSampler
from optuna.pruners import BasePruner
from backend.app.eval.types import SamplerKind, PrunerKind

def _compose_storage_url(database_url: str) -> str: ...
    # Pure helper. Converts postgresql+asyncpg:// to postgresql:// (mirror
    # backend/app/db/optuna_schema.py:41); appends options=-csearch_path=optuna
    # to the query string (preserving any existing query params). Returns the
    # final URL string. No I/O. Unit-testable without a DB.

def build_storage(database_url: str) -> optuna.storages.RDBStorage: ...
    # Thin wrapper: optuna.storages.RDBStorage(url=_compose_storage_url(database_url)).
    # Whether construction opens a connection or defers is an Optuna implementation
    # detail (per spec FR-1/AC-1b — neither timing is guaranteed by RelyLoop).

def build_sampler(config: dict[str, Any], *, seed: int | None) -> BaseSampler: ...
    # config["sampler"] omitted → TPESampler(seed=seed)
    # config["sampler"] == "tpe" → TPESampler(seed=seed)
    # config["sampler"] == "random" → RandomSampler(seed=seed)
    # else → ValueError.

def build_pruner(config: dict[str, Any]) -> BasePruner: ...
    # Reads config["max_trials"] (required key — passed in via the same dict
    # alongside the pruner key). FR-2 contract:
    #   "pruner" key absent + config["max_trials"] < 50  → NopPruner   (safeguard)
    #   "pruner" key absent + config["max_trials"] >= 50 → MedianPruner(n_warmup_steps=10)
    #   config["pruner"] == "median" (explicit)          → MedianPruner(n_warmup_steps=10)  (override)
    #   config["pruner"] == "none"                       → NopPruner
    #   else                                              → ValueError

def get_or_create_study(
    *,
    storage: optuna.storages.RDBStorage,
    optuna_study_name: str,
    direction: str,                 # "maximize" or "minimize"
    sampler: BaseSampler,
    pruner: BasePruner,
) -> optuna.Study: ...
    # Thin wrapper over optuna.create_study(load_if_exists=True, ...).
    # Sync; callers wrap in asyncio.to_thread() from async contexts.
```

**Tasks**

1. Create `backend/app/eval/optuna_runtime.py`.
2. Implement `_compose_storage_url(database_url)` as a pure helper:
   - Convert `postgresql+asyncpg://` to `postgresql://` (mirror `optuna_schema.py:41`).
   - Parse with `urlparse`; if `options=-csearch_path=optuna` already appears in the query string, return the URL unchanged. Otherwise append it (handling both empty and non-empty query strings with `&` separator).
   - Return the final URL string. No I/O. No Optuna calls.
3. Implement `build_storage(database_url)` as `optuna.storages.RDBStorage(url=_compose_storage_url(database_url))`.
4. Implement `build_sampler()` per the contract above. Reject unknown values with `ValueError`.
5. Implement `build_pruner()` per the FR-2 two-pronged contract — key-presence is the explicitness signal; absent key + small `max_trials` → `NopPruner`. Read `max_trials` from the SAME `config` dict (not a separate kwarg). Reject unknown pruner values with `ValueError`. If `max_trials` is missing AND `pruner` key absent, raise `ValueError("config.max_trials is required when pruner is unspecified")`.
6. Implement `get_or_create_study()` as a thin wrapper around `optuna.create_study(..., load_if_exists=True)`.
7. Create `backend/tests/unit/eval/test_optuna_runtime.py`:
   - **URL composition tests** (use `_compose_storage_url` directly — no Optuna construction):
     - `_compose_storage_url("postgresql+asyncpg://u:p@h:5432/d")` → `"postgresql://u:p@h:5432/d?options=-csearch_path=optuna"`.
     - `_compose_storage_url("postgresql://u:p@h:5432/d?sslmode=require")` → `"postgresql://u:p@h:5432/d?sslmode=require&options=-csearch_path=optuna"`.
     - Idempotent: passing an already-composed URL returns it unchanged.
   - **`build_storage` tests** — monkeypatch `optuna.storages.RDBStorage` to a recording fake; assert it's called with the composed URL string. Do NOT instantiate the real RDBStorage in unit tests.
   - **Sampler/pruner tests:**
     - `build_sampler({}, seed=42)` → `TPESampler`; seed forwarded.
     - `build_sampler({"sampler": "random"}, seed=42)` → `RandomSampler`.
     - `build_pruner({"max_trials": 30})` → `NopPruner` (AC-6a — `pruner` key absent + small).
     - `build_pruner({"max_trials": 100})` → `MedianPruner` with `n_warmup_steps=10`.
     - `build_pruner({"max_trials": 30, "pruner": "median"})` → `MedianPruner` (AC-6b — explicit override).
     - `build_pruner({"max_trials": 30, "pruner": "none"})` → `NopPruner`.
     - `build_sampler({"sampler": "cma-es"}, seed=None)` raises `ValueError`.
     - `build_pruner({"max_trials": 30, "pruner": "hyperband"})` raises `ValueError`.
     - `build_pruner({})` (missing max_trials) raises `ValueError`.

**Definition of Done (DoD)**

- [ ] `uv run pytest backend/tests/unit/eval/test_optuna_runtime.py -v` — all pass without requiring a live Postgres (the unit tests use only `_compose_storage_url` and a monkeypatched `RDBStorage`).
- [ ] No connection-timing assertion is made about `RDBStorage()` — spec FR-1/AC-1b explicitly does not constrain whether construction opens a DB connection (constructor vs. first method call). Connection-timing assertions belong in AC-1b post-condition checks at the integration layer (Story 3.1 `test_optuna_rdb.py`), not here.
- [ ] `make lint` and `make typecheck` green.

---

### Story 2.2 — `backend/app/eval/qrels_loader.py` (qrels interface; MVP1 raises `JudgmentsTableMissing`)

**Outcome:** A single import point for the `run_trial` job to fetch qrels. In MVP1 the loader raises `JudgmentsTableMissing` because the `judgments` child table is owned by `feat_llm_judgments` (per [`data-model.md` §"judgment_lists and judgments"](../../../01_architecture/data-model.md)) and is not yet shipped. Integration tests in Epic 3 monkeypatch `load_qrels` to inject hand-built qrels (per spec AC-4 "hand-built judgment list"). When `feat_llm_judgments` lands, that feature replaces the stub with a real `SELECT` against `judgments`.

**Why this is safe for MVP1 production**, even though the production path raises: the only callers of `run_trial` in production are Phase 2's orchestrator (`feat_study_lifecycle` Phase 2 — also deferred per [`phase2_idea.md`](../../../00_overview/planned_features/feat_study_lifecycle/phase2_idea.md)) and `feat_llm_judgments`. **Neither has shipped.** There is no MVP1 surface that can dispatch a real trial — the API has no endpoint to start a study, the worker has no enqueuer, and `run_trial` cannot be invoked from outside the test suite. The stub-with-typed-exception pattern therefore lets us ship the runtime substrate without compromising correctness: any premature dispatch (e.g., an operator manually invoking `arq` against the queue) fails loud with a clear message, and the real loader implementation lands atomically with `feat_llm_judgments`.

**Why this design (vs. real `SELECT`):** Spec §9 explicitly forbids new tables in this feature ("This feature does NOT define new tables"). Implementing the loader as a real `SELECT` against `judgments` would either (a) fail at SQL parse time on every dispatch (since the table doesn't exist), or (b) require creating the table as part of this feature (scope violation). The stub-with-typed-error path keeps the runtime interface stable and gives `feat_llm_judgments` an unambiguous swap point: that feature's plan should include "replace `qrels_loader.load_qrels` with a real `SELECT query_id, doc_id, rating FROM judgments WHERE judgment_list_id = :id GROUP BY query_id`".

**New files**

| File | Purpose |
|---|---|
| `backend/app/eval/qrels_loader.py` | `JudgmentsTableMissing` exception + `load_qrels()` stub. |
| `backend/tests/unit/eval/test_qrels_loader.py` | Asserts MVP1 stub raises `JudgmentsTableMissing` and the exception inherits from `RuntimeError`. |

**Modified files** — none.

**Key interfaces**

```python
# backend/app/eval/qrels_loader.py
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.eval.scoring import Qrels

class JudgmentsTableMissing(RuntimeError):
    """Raised in MVP1 because the `judgments` table is owned by feat_llm_judgments
    and has not shipped yet. Integration tests monkeypatch `load_qrels` to inject
    hand-built qrels (per spec AC-4)."""

async def load_qrels(db: AsyncSession, judgment_list_id: str) -> Qrels: ...
    # MVP1: raises JudgmentsTableMissing.
    # When feat_llm_judgments lands, this stub is replaced with:
    #   SELECT query_id, doc_id, rating FROM judgments
    #   WHERE judgment_list_id = :id
    # and the result is grouped by query_id.
```

**Tasks**

1. Create `backend/app/eval/qrels_loader.py` with the exception class and async function.
2. The async function body: `raise JudgmentsTableMissing(f"judgments table not yet shipped (feat_llm_judgments owns it); judgment_list_id={judgment_list_id}")`.
3. Create `backend/tests/unit/eval/test_qrels_loader.py`:
   - **Test:** Calling `await load_qrels(db_session_mock, "any-id")` raises `JudgmentsTableMissing`.
   - **Test:** `issubclass(JudgmentsTableMissing, RuntimeError)`.
   - **Test:** The exception message contains the judgment_list_id (so tracebacks are diagnosable).

**Definition of Done (DoD)**

- [ ] `uv run pytest backend/tests/unit/eval/test_qrels_loader.py -v` — all pass.
- [ ] A tracking note exists in `state.md` "Known debt / fragility" pointing at `feat_llm_judgments` as the owner of the swap-in.
- [ ] `make lint` and `make typecheck` green.

---

### Story 2.3 — `backend/workers/trials.py` (`run_trial` Arq job) + worker registration

**Outcome:** The hot-path Arq job exists, executes a trial end-to-end per spec FR-4, persists the result per FR-5, and honors the spec §11 idempotency + Optuna-side reconciliation contract. Registered in `backend.workers.all.WorkerSettings.functions` so the Compose `worker` container picks it up.

**New files**

| File | Purpose |
|---|---|
| `backend/workers/trials.py` | `run_trial(ctx, study_id, optuna_trial_number)` Arq job. Contains the idempotency check + Optuna-side reconciliation + the happy-path execute → score → tell → INSERT sequence. |
| `backend/tests/unit/workers/__init__.py` | Empty package marker. |
| `backend/tests/unit/workers/test_trials_unit.py` | Unit-level coverage of the idempotency branches with monkeypatched repo + Optuna helpers (full integration coverage in Epic 3). |

**Modified files**

| File | Change |
|---|---|
| `backend/workers/all.py` | Append `run_trial` to `WorkerSettings.functions = [run_trial]`. Update the module docstring slot that already pre-declares `feat_study_lifecycle → run_trial` to reference `infra_optuna_eval → run_trial` (per spec §2 — the existing slot is currently mis-attributed). |
| `backend/app/db/models/trial.py` | Fix the stale docstring on the `optuna_trial_number` column. The current text claims `study.ask()` is "idempotent on the trial number" — this is false (per spec §11 review log cycles 1–3). Replace with: "Pre-assigned by the orchestrator (`feat_study_lifecycle` Phase 2) via `study.ask().number` before enqueue; `run_trial` loads the in-flight trial via `study.trials[optuna_trial_number]`. Idempotency on `(study_id, optuna_trial_number)` is enforced by the worker per spec §11." |
| `backend/app/services/cluster.py` | Rename `_build_adapter` → `build_adapter` (drop leading underscore — promoting to public factory). Update `__all__` and internal callers (`get_or_probe_health`, `acquire_adapter`). Public consumers: this feature's worker. Cycle-1 review F13 outcome. |

**Key interfaces**

```python
# backend/workers/trials.py
from typing import Any
from arq import ArqRedis
from sqlalchemy.ext.asyncio import AsyncSession

async def run_trial(ctx: dict[str, Any], study_id: str, optuna_trial_number: int) -> None: ...
    # Spec §11 contract (executed in order):
    # 1a. Check app `trials` for existing terminal row (study_id, optuna_trial_number).
    #     If found → return (no-op).
    # 1b. Load Optuna study; check study.trials[optuna_trial_number] state.
    #     If terminal (COMPLETE/FAIL/PRUNED) → reconstruct app trials row from
    #     trial.value + trial.params + trial.state; INSERT and return (NO re-run).
    # 2.  Happy path: load adapter, judgments (via qrels_loader.load_qrels),
    #     template, queries; render N native queries; search_batch (strict_errors=False);
    #     score (eval.scoring.score); compute primary_metric via objective_metric_key;
    #     wall-clock duration; study.tell(trial, value); INSERT trials row.
    # 3.  Failure handling: any of adapter/render/search/score raises →
    #     status='failed', error=str(exc), metrics={}, primary_metric=None;
    #     STILL call study.tell(..., state=TrialState.FAIL); INSERT row;
    #     do NOT re-raise (Arq treats success).
    # 4.  Re-raise only on infra-level (DB unreachable, Redis lost) so Arq retries.
    # 5.  Structlog binds {trial_id, study_id, optuna_trial_number} for every record
    #     emitted by this job.

# Internal helpers (private — single-use within the job):
async def _existing_terminal_app_row(db: AsyncSession, study_id: str, n: int) -> Trial | None: ...
async def _reconstruct_from_optuna(db: AsyncSession, study, study_id: str, n: int) -> Trial: ...
async def _execute_trial(...) -> dict: ...
```

**Tasks**

1. Create `backend/workers/trials.py`. Module docstring cites spec FR-4 + §11 and explicitly states the orchestrator-vs-worker contract: the orchestrator pre-assigns `optuna_trial_number` via `study.ask()` AND pre-populates `FrozenTrial.params` via `trial.suggest_*` against `studies.search_space` before enqueue. The worker does NOT call `ask()` or `suggest_*`.
2. Implement helper `_existing_terminal_app_row(db, study_id, n)`:
   - `SELECT ... FROM trials WHERE study_id = :sid AND optuna_trial_number = :n AND status IN ('complete','failed','pruned') LIMIT 1`.
   - Returns the `Trial` or `None`.
2.5. **Snapshot helper** `_snapshot_optuna_trial(study, n)`:
   - Synchronous function. Reads `frozen = study.trials[n]` (this triggers the storage round-trip). Builds a plain `@dataclass class TrialSnapshot: number: int; state: TrialState; params: dict[str, Any]; value: float | None`. Returns the dataclass.
   - Always invoked from async code via `await asyncio.to_thread(_snapshot_optuna_trial, study, n)` so the storage hit happens in a worker thread.
   - Unit-test via `unittest.mock.Mock(spec=optuna.study.Study)` with a fake `.trials` list.
3. Implement helper `_reconstruct_from_optuna(db, snapshot, study_id, n, objective_key)` — **state-specific reconstruction** per spec §11 clause 1b:
   - Input: a `TrialSnapshot` dataclass already loaded from `study.trials[n]` via `asyncio.to_thread` (per task 2.5), plus the app `study_id`/`n`/`objective_key` computed from the app study row.
   - Map Optuna `state` → app `status`: `COMPLETE → "complete"`, `FAIL → "failed"`, `PRUNED → "pruned"`. Unknown state → `ValueError` (defensive — should never happen with Optuna's terminal-state enum).
   - **For `COMPLETE`:** Persist `params = snapshot.params`, `primary_metric = snapshot.value`, `metrics = {objective_key: snapshot.value}` (full per-metric values cannot be recovered since `study.tell` accepts only the primary; the metrics dict carries only the primary). `error = None`. **Emit a structured log line** at INFO level: `logger.info("trial reconstructed from optuna", event="optuna_reconciled", state="COMPLETE", trial_id=trial_id, study_id=study_id, optuna_trial_number=n, primary_metric=snapshot.value)` — the observability path that "this row was reconciled, not freshly scored" lives in the log stream, NOT in the `metrics` dict (which spec FR-5 reserves for user-facing metric names only).
   - **For `FAIL`:** Persist `params = snapshot.params or {}`, `primary_metric = None`, `metrics = {}` (matches AC-5 shape), `error = "reconstructed from Optuna FAIL state; original exception unavailable"` (the original `error` was lost when the worker died before INSERTing). Emit a WARN-level structured log line with `event="optuna_reconciled", state="FAIL"`.
   - **For `PRUNED`:** Persist `params = snapshot.params or {}`, `primary_metric = snapshot.value` (may be None for pre-warmup prune), `metrics = {}` (no scoring occurred — keep the field empty rather than embedding metadata), `error = None`. (Pruning is reserved per spec §3 — MVP1 trials are single-step so this branch should rarely fire, but the shape must be defined.) Emit an INFO log line with `event="optuna_reconciled", state="PRUNED"`.
   - INSERT via `repo.create_trial(db, ...)` with `duration_ms = None` (wall-clock unknown for reconstructed rows); commit. **The `trial_id` (pre-generated UUID from `run_trial` step A) is passed through as `id=` to keep the structlog `trial_id` consistent with the persisted row PK.**
4. Implement `run_trial(ctx, study_id, optuna_trial_number)` with this strict sequence:
   - **A.** Open a fresh `AsyncSession` via `get_session_factory()()` (one session per job). **Pre-generate `trial_id = str(uuid_utils.uuid7())`** for the app `trials` row — this is the persistent identifier that will be passed to `repo.create_trial(id=trial_id, ...)` AND bound to structlog from job entry, satisfying spec FR-4 ("propagate the trial_id as structlog context for all log records emitted during the job"). Bind `structlog.contextvars.bind_contextvars(trial_id=trial_id, study_id=study_id, optuna_trial_number=optuna_trial_number)`. Initialize `started_at: datetime | None = None` here so the failure handler can safely read it before step J assigns it.
   - **B. Load app Study row** via `repo.get_study(db, study_id)`. If `None` → log WARN "study deleted before run_trial executed" and return (Arq retries won't help; let it die).
   - **C. App-row idempotency check (spec §11 clause 1a)** — call `_existing_terminal_app_row(db, study_id, optuna_trial_number)`; if found → return no-op.
   - **D. Build/load Optuna study using app row data:** Read the boot-cached `optuna.storages.RDBStorage` from `ctx["optuna_storage"]` (populated by `WorkerSettings.on_startup` — see task 5 below). For direct test/CLI invocations that don't run through Arq's startup hook, the entrypoint builds storage itself and seeds `ctx` before calling `run_trial`. The worker treats a missing `ctx["optuna_storage"]` as a defect (raise `RuntimeError("ctx['optuna_storage'] missing — Arq on_startup hook did not run; tests must seed ctx explicitly")`) — no silent fallback that would mask a config mistake in production. Compute `optuna_study_name = study.optuna_study_name`, `direction = study.objective["direction"]`. Build sampler + pruner against the app-row config: `sampler = build_sampler(study.config, seed=study.config.get("seed"))`, `pruner = build_pruner(study.config)` (the dict already contains `max_trials` per the data model). Then `await asyncio.to_thread(get_or_create_study, storage=ctx["optuna_storage"], optuna_study_name=optuna_study_name, direction=direction, sampler=sampler, pruner=pruner)` → `optuna_study`.
   - **E.** Load the in-flight Optuna trial as a snapshot: `snapshot = await asyncio.to_thread(_snapshot_optuna_trial, optuna_study, optuna_trial_number)`. If `snapshot.state.is_finished()` (terminal) → call `_reconstruct_from_optuna(db, snapshot, study_id, optuna_trial_number, objective_metric_key(study.objective))`, passing `trial_id=trial_id` so the reconstructed row uses the same UUID; commit; return. (Spec §11 clause 1b.)
   - **F. Fault seam #1 (test-only):** `if os.environ.get("INFRA_OPTUNA_EVAL_FAULT") == "after_trial_load_before_execute": os._exit(1)` — covers AC-8b case 1 (death after trial load, before tell).
   - **Initialize** `adapter: SearchAdapter | None = None` and `tell_succeeded = False` BEFORE the try-block (used by the finally + the failure-handler logic).
   - **G.** **Happy path** (inside `try:`). Read `snapshot.params` (orchestrator-populated per Conventions). Load cluster via `repo.get_cluster(db, study.cluster_id)`; build adapter via `services.cluster.build_adapter(cluster)` (renamed from `_build_adapter` in Story 5.2 refactor — public factory). Load template via `repo.get_query_template(db, study.template_id)`; load queries via `repo.list_queries_for_set(db, study.query_set_id)`; load qrels via `qrels_loader.load_qrels(db, study.judgment_list_id)`.
   - **H.** Derive retrieval depth: `top_k = study.objective.get("k") or 100` — `objective.k` is optional for `map` and ignored for `mrr` (spec §8.4), so we fall back to a sensible default rather than passing `None` to `adapter.search_batch`. Document this in the function docstring.
   - **I.** Build metrics set from `study.objective` + any secondary metrics declared in `study.config.get("secondary_metrics", [])` (defaults to a fixed inventory: nDCG@10, MAP@10, MRR — the "every metric the study's objective enumerated" interpretation of FR-5).
   - **J.** `started_at = now()`. For each `query` row: build a `NativeQuery` via `adapter.render(template_pydantic, snapshot.params, query.query_text)`. Single `adapter.search_batch(target=study.target, queries=native_queries, top_k=top_k, strict_errors=False)` call. Convert hit lists to `run` dict (`{query_id: {doc_id: score}}`).
   - **K.** `result = score(qrels, run, metrics_set)`. Compute `primary = result["aggregate"][objective_metric_key(study.objective)]`. Compute `duration_ms = int(round((now() - started_at).total_seconds() * 1000))` — explicit `int` cast required because `trials.duration_ms` is an INT column per spec FR-5 and the ORM model.
   - **M.** `await asyncio.to_thread(study.tell, optuna_trial_number, primary)` to mark the Optuna trial COMPLETE. Then set `tell_succeeded = True`.
   - **L.5. Fault seam #2 (test-only):** Immediately after step M sets `tell_succeeded = True`, BEFORE step N: `if os.environ.get("INFRA_OPTUNA_EVAL_FAULT") == "after_tell_before_insert": os._exit(1)` — covers AC-8b case 2.
   - **N.** INSERT `trials` row via `repo.create_trial(db, id=trial_id, study_id=study_id, optuna_trial_number=optuna_trial_number, status="complete", params=snapshot.params, metrics=result["aggregate"], primary_metric=primary, duration_ms=duration_ms, started_at=started_at, ended_at=now())`. Commit.
   - **Failure handling (the try wraps steps G–N):** On any exception that is NOT `sqlalchemy.exc.OperationalError` or `redis.exceptions.ConnectionError`:
     - **If `tell_succeeded` is False** (failure during G–K or M itself): call `await asyncio.to_thread(study.tell, optuna_trial_number, state=optuna.trial.TrialState.FAIL)`. INSERT row with `status='failed'`, `error=str(exc)[:500]`, `params=snapshot.params or {}`, `metrics={}`, `primary_metric=None`, `duration_ms = int(round((now()-started_at).total_seconds()*1000)) if started_at is not None else None`. Commit. Return normally — Arq treats success.
     - **If `tell_succeeded` is True** (failure during N — INSERT/commit): **DO NOT call `study.tell` again** (the Optuna trial is already terminal-COMPLETE; a second `tell` would either raise or silently no-op depending on Optuna version, and either way it's wrong). Re-raise the exception (or treat as infra-level) so Arq retries. On the retry, spec §11 clause 1b reconciliation fires: the worker loads `study.trials[N]` (COMPLETE), reconstructs the app row via `_reconstruct_from_optuna` without re-running search/score/tell, and returns. This is the exact failure mode AC-8b case 2 verifies. Classify `sqlalchemy.exc.IntegrityError` and `sqlalchemy.exc.DataError` here as persistence failures (not trial-level adapter/score failures) so they take this re-raise path.
   - **Infra-level re-raise:** `OperationalError`/`ConnectionError` are re-raised so Arq retries with backoff per spec §13.
   - **Finally block:** if `adapter is not None`, `await adapter.aclose()`. Unbind structlog contextvars via `structlog.contextvars.unbind_contextvars("trial_id", "study_id", "optuna_trial_number")`.
   - **Logging:** Log INFO at completion (`status, primary_metric, duration_ms`), WARN on failure (`error`).
5. Edit `backend/workers/all.py` — adds `run_trial` to the function registry AND adds an `on_startup` hook that initializes Optuna's RDBStorage once at worker boot (satisfying spec FR-1 "MUST initialize Optuna's RDBStorage at worker startup"):
   - Import: `from backend.workers.trials import run_trial; from backend.app.eval.optuna_runtime import build_storage`.
   - Update `WorkerSettings.functions: list[Any] = [run_trial]`.
   - Add `async def on_startup(ctx: dict[str, Any]) -> None:` that calls `ctx["optuna_storage"] = await asyncio.to_thread(build_storage, get_settings().database_url)`. The `to_thread` wrap is required because `build_storage` may open a sync DB connection at construction time (per cycle-1 review F7's resolution — neither timing is guaranteed by spec FR-1/AC-1b). Spec FR-1 + AC-1b allow either constructor-time or first-method-call lazy creation — the boot-time construction satisfies "initialize at worker startup" regardless of which trigger Optuna uses internally.
   - Add `async def on_shutdown(ctx: dict[str, Any]) -> None:` that disposes the storage's underlying engine if Optuna exposes the API (`ctx["optuna_storage"]._engine.dispose()` is the conventional path in current Optuna; wrap in try/except AttributeError for forward-compat).
   - Register both hooks on `WorkerSettings`: `on_startup = on_startup`, `on_shutdown = on_shutdown`.
   - Update docstring slot per "Modified files" table.
   - Update `backend/tests/unit/test_workers.py::test_worker_settings_importable` to assert `len(WorkerSettings.functions) == 1`, `WorkerSettings.functions[0].__name__ == "run_trial"`, AND `hasattr(WorkerSettings, "on_startup")`.
6. Edit `backend/app/db/models/trial.py` to correct the stale `optuna_trial_number` comment per "Modified files" table.
7. Edit `backend/app/services/cluster.py`: **rename `_build_adapter` to `build_adapter`** (drop leading underscore — promoting to public factory per cycle-1 review F13). Update `__all__` ("_build_adapter" → "build_adapter"). Update existing internal callers within the same module (`get_or_probe_health` line 196, `acquire_adapter` line 240). Update tests that grep/import the symbol (see §11.9 grep evidence — currently only `services.cluster` imports it).
8. Create `backend/tests/unit/workers/__init__.py` (empty).
9. Create `backend/tests/unit/workers/test_trials_unit.py`:
   - **Test:** `_existing_terminal_app_row` returns the row when one exists (use `db_session` fixture + `repo.create_trial`).
   - **Test:** `_existing_terminal_app_row` returns `None` when no row exists.
   - **Test:** `_reconstruct_from_optuna` for `COMPLETE`: persists `metrics={objective_key: value}` (only the primary metric, no metadata keys), `primary_metric=value`, `error=None`, `duration_ms=None`. Assert a structured log line was emitted with `event="optuna_reconciled", state="COMPLETE"` (capture via `caplog`).
   - **Test:** `_reconstruct_from_optuna` for `FAIL`: persists `metrics={}`, `primary_metric=None`, `error` contains "reconstructed from Optuna FAIL", `duration_ms=None`. Log line `event="optuna_reconciled", state="FAIL"` at WARN.
   - **Test:** `_reconstruct_from_optuna` for `PRUNED`: persists `metrics={}` (empty — no metadata keys), `primary_metric=snapshot.value`, `error=None`, `duration_ms=None`. Log line `event="optuna_reconciled", state="PRUNED"` at INFO.
   - **Test:** unknown Optuna state raises `ValueError`.
   - All tests use `TrialSnapshot(...)` dataclass instances directly (no Optuna mock needed for the reconstruction helper since the snapshot is the input contract); the snapshot helper itself is tested separately with a mocked `study.trials` lookup.

**Definition of Done (DoD)**

- [ ] `uv run pytest backend/tests/unit/workers/test_trials_unit.py backend/tests/unit/test_workers.py -v` — all pass (including the existing `test_workers.py` which now sees `functions != []`).
- [ ] `backend/tests/unit/test_workers.py::test_worker_settings_importable` is updated to assert `len(WorkerSettings.functions) == 1` and `WorkerSettings.functions[0].__name__ == 'run_trial'`.
- [ ] No `import elasticsearch` / `import opensearchpy` / `httpx` outside `backend/app/adapters/` from the new file (CLAUDE.md Absolute Rule #4 — grep -rn "from elasticsearch" backend/workers/ should be empty).
- [ ] `make lint` and `make typecheck` green.

---

## Epic 2 gate — runtime shippable

- [ ] Stories 2.1–2.3 complete; all unit tests green.
- [ ] `WorkerSettings.functions` contains exactly one entry (`run_trial`); the Arq worker boots without raising (verify by `uv run python -c "from backend.workers.all import WorkerSettings; print(WorkerSettings.functions)"`).
- [ ] `backend/app/eval/` package has 5 files — `__init__.py` (package marker) + 4 modules (`types.py`, `scoring.py`, `optuna_runtime.py`, `qrels_loader.py`). The matching test subpackage `backend/tests/unit/eval/` has 6 files — `__init__.py` (package marker) + 5 test modules (`test_types.py`, `test_scoring.py`, `test_metric_validation.py`, `test_optuna_runtime.py`, `test_qrels_loader.py`).
- [ ] Stale comment on `backend/app/db/models/trial.py:48` is fixed.

---

## Epic 3 — Integration tests, contract test, benchmark, docs

**Goal:** Prove the runtime works end-to-end against a real Postgres + cassette-replayed Elasticsearch, satisfy every spec AC, and update operator-facing docs.

### Story 3.1 — Integration tests (Optuna RDB schema, run_trial happy path, adapter failure, idempotency, partial failure)

**Outcome:** Six integration test files at `backend/tests/integration/` covering AC-1a, AC-1b, AC-2, AC-4, AC-5, AC-6a, AC-6b, AC-7, AC-8a, AC-8b. Tests use the existing `db_session` fixture (autouse migrations + transaction rollback), `pytest-recording` cassettes for ES interactions (proven by `infra_adapter_elastic`'s `test_elastic_schema.py:105`), and `monkeypatch` to swap `qrels_loader.load_qrels` with hand-built qrels.

**Orchestrator simulation pattern (applies to every test that drives `run_trial`):** Since this feature's worker does NOT call `ask()` or `suggest_*` (per spec §11 + Conventions), every integration test that needs a populated Optuna trial must simulate Phase 2's orchestrator role in setup:

```python
# Test setup (simulates Phase 2 orchestrator)
storage = build_storage(database_url)
study = optuna.create_study(
    storage=storage, study_name=str(app_study.id), direction="maximize",
    sampler=build_sampler(app_study.config, seed=42),
    pruner=build_pruner(app_study.config),
    load_if_exists=True,
)
trial = study.ask()
# Populate params per the app study's search_space — for tests, hardcode small space:
trial.suggest_int("bm25_k1", 0, 4)
trial.suggest_float("bm25_b", 0.0, 1.0)
optuna_trial_number = trial.number   # passed to run_trial

# Now invoke the worker
await run_trial(ctx={"optuna_storage": build_storage(get_settings().database_url)}, study_id=app_study.id, optuna_trial_number=optuna_trial_number)
```

**New files**

| File | Purpose |
|---|---|
| `backend/tests/integration/test_optuna_rdb.py` | AC-1a (schema exists after `make migrate`) + AC-1b (lazy table creation in `optuna.*`); two-worker concurrent ask/tell without deadlock. |
| `backend/tests/integration/test_run_trial.py` | AC-2 (TPE default) + AC-4 (trial completes with populated metrics) + AC-7 (single `_msearch`, zero `_search`). |
| `backend/tests/integration/test_run_trial_adapter_failure.py` | AC-5 (stopped cluster → `status='failed'`, `error` populated, `study.tell` called with FAIL state). |
| `backend/tests/integration/test_run_trial_idempotent_retry.py` | AC-8a (app-row idempotency — re-running `run_trial(study_id, N)` after success is a no-op). |
| `backend/tests/integration/test_run_trial_partial_failure.py` | AC-8b — TWO `os._exit(1)` injection points: (a) after ask before tell; (b) after tell before INSERT. Both assert the spec §11 contract holds. |
| `backend/tests/integration/test_pruner_defaults.py` | AC-6a (default-omitted pruner + `max_trials=30` → `NopPruner`) + AC-6b (explicit `pruner='median'` + `max_trials=30` → `MedianPruner` regardless). |
| `backend/tests/integration/fixtures/trial_cassettes/run_trial_happy_path.yaml` | Recorded `_msearch` response for AC-4 (50 queries × 10 docs). Captured against a live local-es with `pytest --record-mode=once` once and committed. |
| `backend/tests/integration/fixtures/handbuilt_qrels.py` | Tiny module exporting a `HANDBUILT_QRELS: Qrels` constant (5 queries × ≤10 docs/query) used by every integration test that needs scoring. |
| `backend/tests/integration/_subprocess_helpers/__init__.py` | Empty marker for the subprocess helper package. |
| `backend/tests/integration/_subprocess_helpers/run_trial_with_test_stubs.py` | Subprocess entrypoint that installs test doubles (qrels loader, stub adapter) from env vars before invoking `run_trial`. Underscore-prefixed dir so pytest doesn't collect it. |

**Modified files**

| File | Change |
|---|---|
| `backend/tests/integration/__init__.py` | No change needed (package already exists). |

**Key interfaces** — N/A (test files only).

**Tasks**

1. Create `backend/tests/integration/fixtures/handbuilt_qrels.py` with a deterministic 5-query × ≤10-doc qrels dict + matching `EXPECTED_NDCG_AT_10`, `EXPECTED_MAP_AT_10`, etc. computed once by `score()` and pinned.
2. Create `backend/tests/integration/test_optuna_rdb.py`:
   - **AC-1a:** `_alembic("upgrade", "head")` + `python -m backend.app.db.optuna_schema`; query `information_schema.schemata` — assert both `public` and `optuna` are present.
   - **AC-1b:** Build storage via `optuna_runtime.build_storage(database_url)`; `optuna.create_study(storage=storage, study_name="ac1b-" + uuid)`. Query `information_schema.tables WHERE table_schema='optuna'` — assert at least `studies`, `trials`, `trial_values` exist. Cross-check no rows for those names in `table_schema='public'` other than RelyLoop's own `studies`/`trials`.
   - **Concurrent ask/tell:** Spawn two `asyncio.to_thread(study.ask)` calls concurrently; assert both return distinct trial numbers; tell both; assert no deadlock (test completes within 30s).
3. Create `backend/tests/integration/test_run_trial.py`:
   - Set up fixtures: register a cluster (use the `local-es` seed pattern from `infra_adapter_elastic`'s seed_clusters), create a `query_set` + 5 `queries` + a `query_template` + a `judgment_list` header + a `study` with `objective={"metric":"ndcg","k":10,"direction":"maximize"}` and a small `search_space`.
   - Apply the orchestrator simulation pattern (above): `study.ask()` + `trial.suggest_*` to get `optuna_trial_number` with populated params.
   - Monkeypatch `backend.app.eval.qrels_loader.load_qrels` to return `HANDBUILT_QRELS`.
   - Mark the test `@pytest.mark.vcr` to use the `run_trial_happy_path.yaml` cassette.
   - Call `run_trial(ctx={"optuna_storage": build_storage(get_settings().database_url)}, study_id=..., optuna_trial_number=trial_number)`.
   - **AC-2:** Inspect the (Optuna) study's sampler → `study.sampler.__class__.__name__ == "TPESampler"`.
   - **AC-4:** Assert a `trials` row exists with `status='complete'`, `params` non-empty (matches the suggested values), `metrics["ndcg@10"]` matches the expected value within 1e-6, `primary_metric` == `metrics["ndcg@10"]`, `duration_ms` is non-null and < 5000.
   - **AC-7 (robust cassette inspection):** Open the committed cassette YAML file with `yaml.safe_load`; iterate `data["interactions"]`; for each interaction parse `request.uri` via `urllib.parse.urlparse` and inspect `.path`. Assert exactly one path equals `"/_msearch"` (or ends with `"/_msearch"` when an index prefix is included); assert zero paths equal `"/_search"` (do NOT use `endswith("_search")` because `_msearch` also matches that suffix — exact path-component match is required). Document the parser logic in a comment.
4. Create `backend/tests/integration/test_run_trial_adapter_failure.py`:
   - Same fixtures as test_run_trial, but point the cluster at an unreachable URL (`http://127.0.0.1:1` — port 1 is reserved).
   - Call `run_trial`; assert no exception escapes.
   - **AC-5:** Assert the `trials` row has `status='failed'`, `error` contains `"CLUSTER_UNREACHABLE"` or `"unreachable"`, `metrics == {}`, `primary_metric is None`.
   - Assert `study.tell` was called with `TrialState.FAIL` (use `monkeypatch` to wrap and capture).
5. Create `backend/tests/integration/test_run_trial_idempotent_retry.py`:
   - Same fixtures + cassette as test_run_trial.
   - Run `run_trial(ctx, study_id, 0)` once → row count = 1.
   - Run `run_trial(ctx, study_id, 0)` again (with `monkeypatch` instrumenting `score()` to record calls).
   - **AC-8a:** Assert row count is still 1; assert `score()` was NOT called the second time; assert the Optuna study has exactly 1 trial.
6. Create `backend/tests/integration/test_run_trial_partial_failure.py` using the **env-var-guarded fault injection seam** documented in Conventions and Story 2.3 task 4 (seams F and L.5). Pytest monkeypatches do NOT survive into a fresh Python interpreter — env vars do, but the child process must install its own test doubles for `qrels_loader.load_qrels` and adapter HTTP traffic. The child process invokes a small helper script (`backend/tests/integration/_subprocess_helpers/run_trial_with_test_stubs.py`) that:
   - Reads `INFRA_OPTUNA_EVAL_TEST_QRELS_JSON` from the env (a JSON-serialized `Qrels` dict) and monkeypatches `backend.app.eval.qrels_loader.load_qrels` to return that dict.
   - Reads `INFRA_OPTUNA_EVAL_TEST_HITS_JSON` from the env (a JSON-serialized `dict[query_id, list[(doc_id, score)]]`) and monkeypatches `backend.app.services.cluster.build_adapter` to return a stub adapter whose `search_batch` returns the canned hits and whose `render` is a passthrough. The stub adapter satisfies the `SearchAdapter` Protocol.
   - Reads `INFRA_OPTUNA_EVAL_FAULT` from the env (forwarded to the worker).
   - Invokes `asyncio.run(run_trial({"optuna_storage": await asyncio.to_thread(build_storage, get_settings().database_url)}, study_id=..., optuna_trial_number=N))` — wrapped in an `async def main()` because `await` requires async context. The helper must seed `ctx["optuna_storage"]` itself because the on_startup hook only runs under real Arq.
   - The helper script lives under `backend/tests/integration/_subprocess_helpers/` (prefix underscore so pytest doesn't try to collect it as tests). New `__init__.py` package marker required.

   **Note on spec §11 vs §14 wording:** Spec §14's `test_run_trial_partial_failure.py` description says case 1's end state should be "1 RUNNING (orphan, tolerated) + 1 COMPLETE" — but that outcome can only arise if the worker calls `ask()` itself (creating a new trial). Spec §11 explicitly forbids the worker from calling `ask()`. **Spec §11 is the controlling contract** (it was the focus of three review cycles; §14's wording is stale relative to the §11 lock-in). The plan implements tests per §11: a within-worker death + retry produces 1 COMPLETE Optuna trial + 1 terminal app row, NO orphan accumulation. A follow-up patch should harmonize §14's text with §11; tracked as a tangential discovery in this feature's PR.

   Test cases:
     - **AC-8b case 1 (worker dies after loading the in-flight trial, before tell — within-worker death scenario):** In test setup, apply the orchestrator simulation pattern to allocate an Optuna trial with populated params (Optuna trial state: RUNNING). Serialize the handbuilt qrels + canned hits to env vars. Spawn the helper subprocess with `INFRA_OPTUNA_EVAL_FAULT="after_trial_load_before_execute"`. Assert subprocess exit code 1 (from `os._exit(1)`). After death: query app `trials` — 0 rows for `(study_id, N)`; query Optuna `study.trials[N].state` — RUNNING. Now invoke `run_trial` again from the parent test (with parent's monkeypatched `load_qrels` and stub adapter). End state per spec §11: the second invocation re-loads `study.trials[N]` (still RUNNING — not terminal, so reconciliation doesn't fire), proceeds through happy path, calls tell + INSERT. **End state: 1 terminal app row, 1 COMPLETE Optuna trial. No RUNNING orphans accumulate** for this scenario — the worker doesn't call `ask()`, so the second invocation completes the SAME trial number rather than allocating a fresh one. (Orphans only arise from orchestrator deaths between `ask()` and the enqueue commit — Phase 2's failure mode, tracked separately as `infra_optuna_orphan_reaper`.)
     - **AC-8b case 2 (tell without INSERT — the dangerous window that motivated spec §11 clause 1b):** Same setup. Subprocess: `INFRA_OPTUNA_EVAL_FAULT="after_tell_before_insert"`. Worker invocation 1 completes search → score → tell → then `os._exit(1)` before the INSERT. Assert subprocess exit code 1. After death: app `trials` — 0 rows for `(study_id, N)`; Optuna `study.trials[N].state` — COMPLETE. Invoke `run_trial` again from the parent. Assert: spec §11 clause 1b reconciliation fires (verified by monkeypatching the parent's `score` and the stub adapter's `search_batch` to RAISE if called — they should NOT be called); end state — exactly 1 terminal app row with `metrics={objective_key: value, "_reconciled": True}` (the reconstruction marker), exactly 1 COMPLETE Optuna trial. No duplicates.

**New files for this story:**

| File | Purpose |
|---|---|
| `backend/tests/integration/_subprocess_helpers/__init__.py` | Empty marker. |
| `backend/tests/integration/_subprocess_helpers/run_trial_with_test_stubs.py` | Subprocess entrypoint with test-double installation. Not collected by pytest (underscore prefix). |
7. Create `backend/tests/integration/test_pruner_defaults.py`:
   - **AC-6a:** Build study with `config={"max_trials": 30}` (no `pruner` key). Construct via `build_pruner(config)` → `NopPruner`.
   - **AC-6b:** Build study with `config={"max_trials": 30, "pruner": "median"}` → `MedianPruner` (regardless of `max_trials`).
   - These can technically be unit tests (Story 2.1 covers them), but the integration variant exercises the loaded `studies.config` JSONB → Python dict round-trip too. Keep both layers — unit asserts the function; integration asserts the data path.

**Definition of Done (DoD)**

- [ ] `uv run pytest -m integration backend/tests/integration/test_optuna_rdb.py backend/tests/integration/test_run_trial.py backend/tests/integration/test_run_trial_adapter_failure.py backend/tests/integration/test_run_trial_idempotent_retry.py backend/tests/integration/test_run_trial_partial_failure.py backend/tests/integration/test_pruner_defaults.py -v` — all pass.
- [ ] Cassette file committed (`run_trial_happy_path.yaml`) and produces deterministic test output across runs.
- [ ] All 11 ACs from spec §12 verified by at least one test (AC-1a, AC-1b, AC-2, AC-3 (Epic 1), AC-4, AC-5, AC-6a, AC-6b, AC-7, AC-8a, AC-8b).
- [ ] `make lint` and `make typecheck` green.

---

### Story 3.2 — Contract test (`trials` row shape) + benchmark (`test_scoring_perf.py`)

**Outcome:** A contract test asserts every `run_trial` execution produces a `Trial` ORM row matching the §FR-5 shape (no Pydantic shape — that arrives in Phase 2). A benchmark verifies the spec §FR-3 SHOULD: scoring completes in <100ms per query for a 50-query × top_k=10 fixture.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/contract/test_trial_row_shape.py` | Asserts the `Trial` row shape after a happy-path `run_trial`: `params` is JSON-serializable, `metrics` keyed by user-facing names (no `ndcg_cut_10` etc.), `primary_metric` is a `float` denormalized from `metrics[objective_metric_key(...)]`, `duration_ms` non-null, `status` ∈ DB CHECK allowlist. Uses the spec FR-5 contract directly, not a Pydantic schema. |
| `backend/tests/benchmarks/__init__.py` | New package marker (directory doesn't exist yet). |
| `backend/tests/benchmarks/test_scoring_perf.py` | 50-query × top_k=10 fixture; asserts `score()` average wall-clock per query < 100ms (warm-up call discarded; 5 timed iterations). |

**Modified files**

| File | Change |
|---|---|
| `pyproject.toml` | Add `"benchmarks"` to `[tool.pytest.ini_options].testpaths`? **No** — keep `testpaths = ["backend/tests"]` (already covers the new subdir). Add a `benchmark: ...` marker to `[tool.pytest.ini_options].markers` so the benchmark can opt-in via `-m benchmark`. |

**Key interfaces** — N/A (test files only).

**Tasks**

1. Create `backend/tests/contract/test_trial_row_shape.py`:
   - Run a happy-path `run_trial` (same monkeypatched qrels + cassette as Story 3.1).
   - Read the resulting `Trial` row.
   - Assert: every column matches the `Trial` ORM model declared in `backend/app/db/models/trial.py`; no extra/missing columns when compared to `Trial.__table__.columns`.
   - Assert: `json.dumps(trial.params)` and `json.dumps(trial.metrics)` succeed (round-trip serializable).
   - Assert: every key in `trial.metrics` is a user-facing name — none of the pytrec_eval wire prefixes (`ndcg_cut_`, `P_`, `recall_`, `recip_rank`, `map_cut_`).
   - Assert: `trial.primary_metric == trial.metrics[objective_metric_key(study.objective)]`.
   - Assert: `trial.status` is one of `{"complete", "failed", "pruned"}` (the spec §8.4 + DB CHECK allowlist).
2. Create `backend/tests/benchmarks/__init__.py` (empty).
3. Edit `pyproject.toml` `[tool.pytest.ini_options].markers` — add `"benchmark: opt-in performance benchmarks; runs in dedicated CI job not the default test layer"`.
4. Create `backend/tests/benchmarks/test_scoring_perf.py`:
   - Build a deterministic 50-query × top_k=10 qrels + run fixture (random docs/ratings seeded with `random.seed(42)`).
   - Mark `@pytest.mark.benchmark`.
   - Warm-up call: `score(qrels, run, {"ndcg@10","map","mrr"})`.
   - Timed loop: 5 iterations; record `time.perf_counter_ns()` deltas; compute mean.
   - Assert: `mean_per_query_ms < 100.0`. On failure, print the actual value for debugging.

**Definition of Done (DoD)**

- [ ] `uv run pytest backend/tests/contract/test_trial_row_shape.py -v` — passes.
- [ ] `uv run pytest -m benchmark backend/tests/benchmarks/ -v` — passes locally and in CI.
- [ ] No `error` codes referenced in contract tests beyond what the spec §8.5 declares (which is N/A — this feature has no HTTP errors).
- [ ] `make lint` and `make typecheck` green.

---

### Story 3.3 — Runbook + `state.md` + `architecture.md` updates

**Outcome:** Operator-facing runbook covers Optuna RDB inspection + trial replay + pruner diagnosis. Core context files reflect the shipped state.

**New files**

| File | Purpose |
|---|---|
| `docs/03_runbooks/optuna-debugging.md` | How to: connect to Optuna's RDB tables (`\dt optuna.*`), replay a specific trial via the worker CLI, diagnose stuck-running trials (manual Optuna `study._storage._study_state` inspection), wipe & reseed for tests. |

**Modified files**

| File | Change |
|---|---|
| `state.md` | Current branch / "Most recent meaningful changes" entry for `infra_optuna_eval`; `In flight: none`; `Queued (priority-ordered)` — promote `feat_study_lifecycle` Phase 2 to next-up; Alembic head unchanged (`0003_study_lifecycle_schema`); Known debt — add the `feat_llm_judgments` qrels-loader swap-in. |
| `architecture.md` | "Where the code lives" — add `backend/app/eval/` with the 4 modules; add `backend/workers/trials.py` to the workers slot; update the "topical architecture docs" line referencing `optimization.md` to flag the now-implemented runtime. |
| `docs/01_architecture/optimization.md` | Patch any divergence — the spec's review log already corrected the doc's stale `RDBStorage(...).initialize()` reference; verify the file matches what shipped (mostly a re-read pass). If the worker pseudocode in §"Worker job: `run_trial`" differs from what was actually built (e.g., the spec §11 ordering — tell before INSERT — vs. the doc's example), update the doc. |
| `docs/02_product/mvp1-user-stories.md` | Mark US-7 and US-8 as "implemented" (per spec §15). |
| `docs/05_quality/testing.md` | Extend the existing pytest-recording cassette guidance with the `run_trial` cassette-replay pattern (per spec §15). |
| `backend/app/db/optuna_schema.py` | Update the docstring opening line: "In MVP1 this is effectively a no-op stub since `infra_optuna_eval` hasn't shipped yet" → "In MVP1 this prepares the schema; `infra_optuna_eval`'s worker boot triggers Optuna's lazy table creation on first `RDBStorage` use." |

**Key interfaces** — N/A (docs only).

**Tasks**

1. Write `docs/03_runbooks/optuna-debugging.md` covering: (a) connecting to Postgres + `\dn optuna; \dt optuna.*`; (b) inspecting `optuna.trials` for a stuck trial; (c) replaying a trial via a small Python snippet that seeds `ctx["optuna_storage"]` itself (e.g., `from backend.app.eval.optuna_runtime import build_storage; from backend.app.core.settings import get_settings; from backend.workers.trials import run_trial; import asyncio; asyncio.run(run_trial({"optuna_storage": build_storage(get_settings().database_url)}, study_id="...", optuna_trial_number=N))`) — note the storage must be seeded because the Arq `on_startup` hook only runs when invoked via `arq backend.workers.all.WorkerSettings`; (d) detecting orphan RUNNING trials (and the open `infra_optuna_orphan_reaper` follow-up).
2. Edit `state.md` per the table above. Convert any "next up: infra_optuna_eval" entries to "feat_study_lifecycle Phase 2".
3. Edit `architecture.md` "Where the code lives" block.
4. Re-read `docs/01_architecture/optimization.md` and patch any line that disagrees with the shipped runtime (the spec's review log made `RDBStorage(...).initialize()` a dead reference — confirm the doc says "first `RDBStorage` construction/use" not "explicit `.initialize()`").
5. Patch `docs/02_product/mvp1-user-stories.md` to mark US-7 + US-8 implemented.
6. Patch `docs/05_quality/testing.md` with the cassette-replay subsection.
7. Patch the `backend/app/db/optuna_schema.py` docstring per "Modified files" table.

**Definition of Done (DoD)**

- [ ] `docs/03_runbooks/optuna-debugging.md` exists and is operator-tested (run each command block once locally to verify the syntax — at least the `psql` queries).
- [ ] `state.md` and `architecture.md` reflect the shipped state (no references to "next up: infra_optuna_eval" remain).
- [ ] `make lint` green (Markdown is unaffected by ruff, but the Python docstring change should not break anything).

---

## Epic 3 gate — feature shippable

- [ ] All 11 ACs verified by at least one test (spec §12 + §18 checklist).
- [ ] Coverage on `backend/app/eval/scoring.py` and `backend/workers/trials.py` ≥ 80% (per spec §18).
- [ ] Benchmark `backend/tests/benchmarks/test_scoring_perf.py` passes (<100ms/query average).
- [ ] All four test layers green: `make test-unit`, `make test-integration` (skips Postgres if not reachable from host), `make test-contract`. No E2E (no UI).
- [ ] Pre-commit hooks pass on the final commit (`uv run pre-commit run --all-files`).
- [ ] Cross-model GPT-5.5 final review on the merged diff: any High-severity finding resolved or rejected with cited counter-evidence before merge.
- [ ] PR opened against `main`; CI green; Gemini Code Assist comments adjudicated.

---

## 3) Testing workstream

This feature is worker-internal; the test layers map as follows.

### 3.1 Unit tests
- Location: `backend/tests/unit/eval/`, `backend/tests/unit/workers/`
- Scope: pytrec_eval translation, frozenset enforcement, sampler/pruner builders, qrels loader stub, idempotency branches with mocked DB.
- Tasks:
  - [ ] `test_types.py` — Literal contents (Story 1.1)
  - [ ] `test_scoring.py` — score() against hand-curated baseline; AC-3 (Story 1.2)
  - [ ] `test_metric_validation.py` — frozenset enforcement; objective_metric_key branches (Story 1.2)
  - [ ] `test_optuna_runtime.py` — sampler/pruner defaults + overrides; AC-2, AC-6a, AC-6b (unit layer) (Story 2.1)
  - [ ] `test_qrels_loader.py` — MVP1 stub raises (Story 2.2)
  - [ ] `test_trials_unit.py` — idempotency helpers + reconstruction state mapping (Story 2.3)
- DoD:
  - [ ] All unit tests pass. Coverage on `backend/app/eval/` ≥ 90%, on `backend/workers/trials.py` ≥ 70% (the rest covered at integration layer).

### 3.2 Integration tests
- Location: `backend/tests/integration/`
- Scope: full `run_trial` execution against a real Postgres + cassette-replayed ES; Optuna RDB schema isolation; AC-1, AC-4, AC-5, AC-7, AC-8a, AC-8b; AC-6a/AC-6b at data-path layer.
- Tasks:
  - [ ] `test_optuna_rdb.py` — AC-1a + AC-1b + concurrent ask/tell (Story 3.1)
  - [ ] `test_run_trial.py` — AC-2 + AC-4 + AC-7 (Story 3.1)
  - [ ] `test_run_trial_adapter_failure.py` — AC-5 (Story 3.1)
  - [ ] `test_run_trial_idempotent_retry.py` — AC-8a (Story 3.1)
  - [ ] `test_run_trial_partial_failure.py` — AC-8b (two `os._exit(1)` cases) (Story 3.1)
  - [ ] `test_pruner_defaults.py` — AC-6a + AC-6b at integration layer (Story 3.1)
- DoD:
  - [ ] All integration tests pass when Postgres is reachable. Cassette deterministic. Worker process exits cleanly after every test.

### 3.3 Contract tests
- Location: `backend/tests/contract/`
- Scope: `Trial` ORM row shape after a happy-path `run_trial` execution; metric key namespace (no pytrec_eval wire-name leakage); status allowlist; JSON-serializability.
- Tasks:
  - [ ] `test_trial_row_shape.py` — FR-5 contract (Story 3.2)
- DoD:
  - [ ] Contract test passes; no Pydantic shape introduced (Phase 2 owns API-layer Pydantic).
- **No HTTP error codes** — this feature emits none. Trial failures land in `trials.status='failed'` per FR-4.

### 3.4 E2E tests
- N/A — no UI. Spec §11 + §14 confirm.

### 3.5 Benchmarks
- Location: `backend/tests/benchmarks/`
- Scope: `score()` performance — <100ms/query average for 50q × top_k=10 (per spec §FR-3 SHOULD + §18 DoD).
- Tasks:
  - [ ] `test_scoring_perf.py` (Story 3.2)
- DoD:
  - [ ] Benchmark passes on CI runner.

### 3.6 Migration verification
- N/A — this feature adds no Alembic migration. Verification step: `git diff --stat migrations/` between the base branch and the final PR commit must show zero files changed in `migrations/`.

### 3.7 CI gates
- [ ] `make test-unit`
- [ ] `make test-integration` (skips Postgres tests from host shell; CI uses service container)
- [ ] `make test-contract`
- [ ] `uv run pytest -m benchmark backend/tests/benchmarks/`
- [ ] `make lint`
- [ ] `make typecheck`
- [ ] `uv run pre-commit run --all-files`

### 3.8 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `backend/tests/unit/test_workers.py` | `WorkerSettings.functions == []` | 1 (line 36) | **Update**: change to `len(WorkerSettings.functions) == 1` and `WorkerSettings.functions[0].__name__ == "run_trial"`. Story 2.3 owns this change. |
| `backend/tests/integration/test_study_lifecycle_migration.py` | Asserts 7 tables exist | — | No change — `infra_optuna_eval` adds zero tables. |
| `backend/tests/integration/test_study_repos.py` | Tests `create_trial`/`list_trials_for_study` | — | No change — repo functions remain the same; this feature reads/writes via `repo.create_trial`. |

All other test files are unaffected (no router/middleware/settings changes).

---

## 4) Documentation update workstream

### 4.0 Core context files

- [ ] **`state.md`** — Updated in Story 3.3 (priorities, Alembic head reaffirmed at `0003`, known-debt qrels-loader note).
- [ ] **`architecture.md`** — Updated in Story 3.3 (new `backend/app/eval/` slot; worker job slot).
- [ ] **`CLAUDE.md`** — **No update** — no new conventions, env vars, or build commands. The "Stack (MVP1)" line already names Optuna + pytrec_eval. Feature status table needs no change here (it's tracked in `state.md`).

### 4.1 Architecture docs
- [ ] `docs/01_architecture/optimization.md` — verify no drift from shipped runtime (Story 3.3).

### 4.2 Product docs
- [ ] `docs/02_product/mvp1-user-stories.md` — mark US-7 + US-8 implemented (Story 3.3).

### 4.3 Runbooks
- [ ] `docs/03_runbooks/optuna-debugging.md` — new (Story 3.3).

### 4.4 Security docs
- N/A — no new secrets, no new threat surfaces beyond what spec §10 documented (and that section is informational only).

### 4.5 Quality docs
- [ ] `docs/05_quality/testing.md` — extend cassette guidance (Story 3.3).

---

## 5) Lean refactor workstream

### 5.1 Refactor goals
- **Promote `services.cluster._build_adapter()` to a public `build_adapter()`** (drop the leading underscore) — used by both the API layer and this feature's worker. Avoids a worker importing a privately-named symbol across module boundaries (cycle-1 review F13). Story 2.3 owns this rename.
- Single source of truth for the pytrec_eval translation table — only `scoring.py:_translate_metric_name` knows wire names (per spec §FR-3 last paragraph: "the wire names never leak past `score()`").
- Single source of truth for the metric/k allowlists — `SUPPORTED_METRICS` / `SUPPORTED_K_VALUES` frozensets in `scoring.py`. Phase 2 of `feat_study_lifecycle` will `from backend.app.eval.scoring import SUPPORTED_METRICS, SUPPORTED_K_VALUES` when validating `studies.objective` at the API layer; this avoids duplicating the allowlist.

### 5.2 Planned refactor tasks
- [ ] Story 2.3 — rename `_build_adapter` → `build_adapter` in `backend/app/services/cluster.py`; update `__all__` and internal callers (`get_or_probe_health` line 196, `acquire_adapter` line 240, the function def at line 308, the docstring at line 10, the `__all__` entry at line 299); the worker imports the public name. Verified there are NO external imports of `services.cluster._build_adapter` — adapter test files (`backend/tests/unit/adapters/test_elastic_*.py`, `test_request_retry.py`) each define their own LOCAL `_build_adapter` helper function with the same name; those are module-local and unaffected by the service-module rename. The grep `grep -rn "from backend.app.services.cluster import" backend/` returns zero matches for `_build_adapter`.
- [ ] Story 1.2 — `_translate_metric_name` is private (leading underscore); only `score()` calls it. Enforce by docstring.
- [ ] Story 3.3 — fix the stale `optuna_trial_number` comment on `backend/app/db/models/trial.py:48` (the "idempotent on the trial number" claim is false per the spec's review log).

### 5.3 Refactor guardrails
- [ ] Behavioral parity proven by unit + integration tests.
- [ ] No expansion of product scope beyond spec §3.
- [ ] All code added under `backend/app/eval/` follows the "pure logic + thin runtime" pattern. No HTTP, no router registration, no Pydantic API models.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `optuna>=3.6` | Story 1.1 | Planned (added in 1.1) | Worker can't construct study. |
| `pytrec_eval>=0.5` | Story 1.1 | Planned (added in 1.1) | Scoring can't run. |
| `infra_foundation` (Postgres, Alembic, Arq scaffolding, `optuna_schema.py`) | All | ✅ Shipped (PR #4) | — |
| `infra_adapter_elastic` (`SearchAdapter`, `ElasticAdapter`, `_build_adapter`, `acquire_adapter`, cassettes) | Story 2.3, 3.1 | ✅ Shipped (PR #16) | — |
| `feat_study_lifecycle` Phase 1 (`studies` + `trials` + `judgment_lists` + repo functions) | Story 2.3, 3.1 | ✅ Shipped (PR #18) | — |
| `feat_llm_judgments` (real `load_qrels` impl) | Story 2.2 — interface only; impl owned downstream | Not shipped; integration tests monkeypatch | Live `run_trial` calls would fail with `JudgmentsTableMissing` until `feat_llm_judgments` lands. **This is intentional and documented in §11 of this plan + spec §3.** |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Optuna's exact lazy-creation trigger differs across point releases (constructor vs. first method call) | M | L | Spec §FR-1 explicitly does not constrain the trigger — only the two guarantees (schema exists; tables in `optuna.*`). AC-1b verifies post-condition, not mechanism. |
| `os._exit(1)` injection in `test_run_trial_partial_failure.py` proves harder than expected to drive cleanly from pytest | M | M | Use `subprocess.Popen` to invoke the worker function in a child process; pytest parent observes via the child's exit code + DB state. Documented in Story 3.1. |
| pytrec_eval pinned hand-baseline drifts when the library version moves | L | L | Test asserts within 1e-6 — wide enough to absorb library FP noise but tight enough to catch real regressions. |
| `feat_study_lifecycle` Phase 2 orchestrator integration surfaces a contract mismatch (e.g., the pre-assigned `optuna_trial_number` semantics) | M | M | Spec §11 locks the orchestrator-pre-assignment contract; this plan matches it. Spec §18 DoD already requires Phase 2 author to confirm before this feature is "done". |
| Optuna RDB schema lock contention at 4-worker parallelism slows trials below the spec §13 p99 budget | L | M | Spec §11 + §13 already document the trade-off; not gating MVP1 ship. If reproducible, file as `infra_optuna_rdb_contention` follow-up. |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| Adapter raises `ClusterUnreachableError` mid-trial | Cluster down, network partition, auth rejected | `trials.status='failed'`, `trials.error='CLUSTER_UNREACHABLE: ...'`, `study.tell(trial, state=FAIL)` called, job returns normally | Operator restarts cluster; next trial succeeds. No worker restart needed. |
| `score()` raises `ValueError` (empty qrels, malformed run) | Test misconfiguration or stale judgment list | Same as above with `error='ValueError: ...'` | Investigate the judgment list / qrels source. |
| `pytrec_eval.RelevanceEvaluator` import raises at module load | Missing C extension in the runtime image | `run_trial` import fails; Arq worker fails to start | Re-build image with `pytrec_eval` wheel installed (covered by Story 1.1 + Compose worker). |
| Optuna RDB unreachable mid-trial | Postgres restart, network blip | Job raises `OperationalError` and re-raises (infra-level); Arq retries with exponential backoff per visibility-timeout | Postgres comes back; retry succeeds. Spec §13 reliability. |
| Worker dies after loading the in-flight Optuna trial but before `study.tell()` | OOM, SIGKILL, panic mid-execute | Optuna trial stays `RUNNING`; app `trials` has 0 rows for that number. On retry, the worker re-loads `study.trials[N]` (still RUNNING — not terminal, so reconciliation does not fire), proceeds through happy path → tell → INSERT. End state: 1 COMPLETE Optuna trial, 1 terminal app row, no duplicates. **No orphan accumulates from THIS scenario** — the worker doesn't call `ask()`, so the second invocation completes the SAME trial number rather than allocating a fresh one. Orphans only arise from a different failure (orchestrator dies between its `ask()` and the enqueue commit — Phase 2's failure mode, separately tracked as `infra_optuna_orphan_reaper`). | Automatic on next Arq retry. |
| Worker dies between `study.tell()` and INSERT | OOM, SIGKILL between two operations | Optuna trial is terminal; app `trials` has 0 rows. Spec §11 clause 1b reconciliation: retry reads `study.trials[N]`, reconstructs the app row from Optuna's terminal state, INSERTs without re-running search/score. | Automatic on next retry. |
| `JudgmentsTableMissing` raised at runtime (production attempt with no `feat_llm_judgments`) | Operator runs a real study before `feat_llm_judgments` ships | Trial fails fast with `status='failed'`, `error='JudgmentsTableMissing: ...'` | Wait for `feat_llm_judgments` to ship and replace the stub. This is gated by `feat_study_lifecycle` Phase 2's orchestrator (which won't dispatch trials until judgments exist for the study). |

---

## 7) Sequencing and parallelization

### Suggested sequence

1. **Epic 1** (Stories 1.1 → 1.2) — must complete before Epic 2.
2. **Epic 2** (Stories 2.1 ∥ 2.2 → 2.3) — 2.1 and 2.2 are independent (different files); 2.3 depends on both.
3. **Epic 3** (Stories 3.1 ∥ 3.2 → 3.3) — 3.1 and 3.2 are independent (different test files); 3.3 docs go last so they reference the actual shipped state.

### Parallelization opportunities

- Story 2.1 (optuna_runtime) and Story 2.2 (qrels_loader) modify disjoint files; can be implemented in parallel.
- Story 3.1 (integration) and 3.2 (contract + benchmark) modify disjoint directories; can be implemented in parallel.

---

## 8) Rollout and cutover plan

- **Rollout stages:** Single stage. Merge to `main` triggers the (future) staging deploy when remote staging arrives in MVP3. Until then, the rollout is "operator pulls and runs `make migrate && make up`".
- **Feature flag strategy:** None.
- **Migration/cutover steps:** None. Schema unchanged; only Optuna's lazy table creation runs on first worker boot (idempotent — no operator action required).
- **Reconciliation/repair strategy:** Orphan Optuna RUNNING trials are operationally tolerated for MVP1 per spec §11. Follow-up `infra_optuna_orphan_reaper` is filed separately when needed.

---

## 9) Execution tracker

### Current sprint
- [x] Story 1.1 — deps + types (commit `be114ab`)
- [x] Story 1.2 — scoring helper + frozensets + objective_metric_key (commit `e508366`)
- [x] Story 2.1 — optuna_runtime (sampler/pruner/storage builders) (commit `e619fdc`)
- [x] Story 2.2 — qrels_loader stub (commit `884c10e`)
- [x] Story 2.3 — run_trial job + worker registration + trial.py comment fix (commit `135bac5`)
- [x] Story 3.1 — integration tests (6 files + handbuilt_qrels fixture + stub_adapter + subprocess helper)
- [x] Story 3.2 — contract test + benchmark (commit `d908a84`)
- [x] Story 3.3 — runbook + state.md + architecture.md + doc straggler patches

### Blocked items
- None at plan-write time. `feat_llm_judgments` non-blocking (interface stubbed; integration tests monkeypatch).

### Done this sprint
- (none yet — plan just written)

---

## 10) Story-by-Story Verification Gate (Agent Checklist)

Before marking any story complete, the executing agent must attach evidence for:

- [ ] Files created/modified match story scope (`New files` / `Modified files` tables)
- [ ] Key interfaces implemented with compatible signatures (type-checked by mypy)
- [ ] Required unit tests added for the story's scope (DoD references for the story name them)
- [ ] Commands executed and passed:
    - [ ] `uv run pytest <story-scoped test paths>`
    - [ ] `make lint`
    - [ ] `make typecheck`
- [ ] No migration files added in `migrations/versions/` (this feature ships zero migrations).
- [ ] Related docs/runbooks updated in the same PR when behavior changed (deferred to Story 3.3 by design — earlier stories don't touch docs).

---

## 11) Plan consistency review

### 11.1 Spec ↔ plan endpoint count
- Spec §8.1: N/A — feature has no HTTP endpoints. Plan stories define zero endpoints. ✅ Match.

### 11.2 Spec ↔ plan error code coverage
- Spec §8.5: N/A — no HTTP errors. Plan defines zero contract-test error codes. Trial failures land in `trials.status='failed'` and are asserted by integration tests, not contract error-code tests. ✅ Match.

### 11.3 Spec ↔ plan FR coverage
- FR-1 → Story 2.1 (build_storage). ✅
- FR-2 → Story 2.1 (build_sampler + build_pruner). ✅
- FR-3 → Story 1.2 (scoring + translation). ✅
- FR-4 → Story 2.3 (run_trial). ✅
- FR-5 → Story 2.3 (Trial row INSERT) + Story 1.2 (objective_metric_key). ✅
- AC-1a → Story 3.1 (test_optuna_rdb.py). ✅
- AC-1b → Story 3.1 (test_optuna_rdb.py). ✅
- AC-2 → Story 2.1 (unit) + Story 3.1 (integration). ✅
- AC-3 → Story 1.2 (unit). ✅
- AC-4 → Story 3.1 (test_run_trial.py). ✅
- AC-5 → Story 3.1 (test_run_trial_adapter_failure.py). ✅
- AC-6a → Story 2.1 (unit) + Story 3.1 (test_pruner_defaults.py). ✅
- AC-6b → Story 2.1 (unit) + Story 3.1 (test_pruner_defaults.py). ✅
- AC-7 → Story 3.1 (cassette assertion in test_run_trial.py). ✅
- AC-8a → Story 3.1 (test_run_trial_idempotent_retry.py). ✅
- AC-8b → Story 3.1 (test_run_trial_partial_failure.py — two `os._exit(1)` cases). ✅

### 11.4 Story internal consistency
- Endpoint tables: N/A.
- DoD assertions reference correct error codes: N/A.
- New files not double-claimed: verified — every file in §1 traceability + story tables belongs to exactly one story.
- Modified files exist: `backend/workers/all.py` (verified line 33), `backend/app/db/models/trial.py` (verified line 48 docstring), `pyproject.toml` (verified). `backend/tests/unit/test_workers.py` line 36 — verified.

### 11.5 Test file count
- Unit tests: 6 files (`test_types.py`, `test_scoring.py`, `test_metric_validation.py`, `test_optuna_runtime.py`, `test_qrels_loader.py`, `test_trials_unit.py`).
- Integration tests: 6 files + 2 fixtures + 1 subprocess helper module (`_subprocess_helpers/run_trial_with_test_stubs.py`) + 2 package markers.
- Contract tests: 1 file.
- Benchmarks: 1 file + package marker.
- Total: 14 test files + 2 fixture files + 1 subprocess helper. All assigned to a specific story.

### 11.6 Gate arithmetic
- Epic 1 gate: 2 stories complete → matches Stories 1.1, 1.2. ✅
- Epic 2 gate: 3 stories complete + 4 modules under `backend/app/eval/` + 1 module under `backend/workers/` → consistent.
- Epic 3 gate: 11 ACs verified by tests → all 11 enumerated above with story refs. ✅

### 11.7 Open questions resolved
- Spec §19: "None — all resolved." ✅

### 11.8 Frontend UI Guidance
- N/A — no frontend scope.

### 11.9 Codebase grounding (Pass 2 outcomes)

**Verified claims:**

| Claim | Verification | Status |
|---|---|---|
| Migration dir is `migrations/versions/` | `ls /Users/ericstarr/relyloop/migrations/versions/` → `0001_baseline.py`, `0002_clusters_config_repos.py`, `0003_study_lifecycle_schema.py` | ✅ Verified |
| Alembic head is `0003_study_lifecycle_schema` | `ls migrations/versions/ \| sort \| tail -1` | ✅ Verified |
| `backend/app/db/optuna_schema.py:init_optuna_schema` exists | Read file:25 | ✅ Verified |
| `backend/workers/all.py:WorkerSettings.functions == []` | Read file:33 | ✅ Verified |
| `backend/app/adapters/protocol.py:SearchAdapter.search_batch` accepts `strict_errors` + `timeout` | Read file:152–173 | ✅ Verified |
| `backend/app/db/models/trial.py:48` carries a false claim about `ask()` idempotency | Read file:46–48 | ✅ Verified — Story 2.3 fixes |
| `backend/app/db/repo/__init__.py` exports `create_trial`, `get_study`, `get_judgment_list`, `get_query_template`, `list_queries_for_set`, `get_cluster` | Read file | ✅ Verified |
| `backend/app/services/cluster.py:_build_adapter` exists | Read file:308–317 | ✅ Verified |
| `backend/tests/unit/test_workers.py:36` asserts `WorkerSettings.functions == []` | Read file | ✅ Verified — Story 2.3 updates |
| `pyproject.toml` already includes `pytest-recording>=0.13` | Read file:50 | ✅ Verified |
| `backend/tests/integration/test_clusters_migration.py:test_downgrade_removes_both_tables` uses explicit `downgrade 0001` | Spec §"Most recent meaningful changes" cites the fix | ✅ Verified by state.md |

**No corrections required** — the spec's review log (cycles 1–3) already corrected the major plan-relevant claims (`backend/app/eval/...` path, `backend/workers/trials.py` path, FR-5 denormalization key, retry contract). This plan inherits the corrected baselines.

### 11.10 Enumerated value contract audit
- This feature ships frozenset/Literal allowlists at `backend/app/eval/scoring.py` and `backend/app/eval/types.py`. Spec §8.4 documents them. Plan Stories 1.1 + 1.2 cite the same source-of-truth files. ✅ No frontend dropdowns — N/A for the §11 phantom-value drift mode.

### 11.11 Admin control audit
- N/A — MVP1, single-tenant, no admin model.

### 11.12 Audit-event coverage audit
- N/A — `audit_log` arrives at MVP2. Spec §6 explicitly skips audit events for this feature (per-trial volume is too high to instrument).

---

## 12) Definition of plan done

- [x] Every FR is mapped to stories/tasks/tests/docs updates (§1 traceability).
- [x] Every story includes New files, Modified files, Key interfaces, Tasks, and DoD.
- [x] Test layers (unit/integration/contract/benchmark) are explicitly scoped (§3).
- [x] Documentation updates across docs/01–05 are planned and owned (§4).
- [x] Lean refactor scope and guardrails are explicit (§5).
- [x] Phase/epic gates are measurable.
- [x] Story-by-Story Verification Gate is included (§10).
- [x] Plan consistency review (§11) performed with no unresolved findings.
- [x] Cross-model review (GPT-5.5) — converged at cycle 3. Cycle 1: 14 findings (3 High / 7 Medium / 4 Low) — all accepted, all applied. Cycle 2: 8 findings (3 High / 4 Medium / 0 Low) — all accepted, all applied (cycle-2 caught defects in cycle-1 patches: `study.tell` requires int not FrozenTrial; FR-1 worker startup hook was missing; trial_id needed pre-generation; subprocess fault tests needed their own stubs). Cycle 3: 6 findings (2 High / 4 Medium / 0 Low) — all accepted, all applied (cycle-3 caught: `ctx["optuna_storage"]` missing in test invocations; `on_startup` needed `asyncio.to_thread`; `started_at` unbound risk; `duration_ms` needed int cast; `_reconciled` key polluted metrics namespace; spec §14 vs §11 wording drift captured as a separate chore idea). Zero rejected findings across all three cycles.
