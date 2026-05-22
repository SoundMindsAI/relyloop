# Implementation Plan — Replace `pytrec_eval` with `ir_measures` for IR metric scoring

**Date:** 2026-05-22
**Status:** Draft
**Primary spec:** [`feature_spec.md`](./feature_spec.md) — Approved 2026-05-22 (GPT-5.5 3 cycles, 11 → 6 → 1 findings)
**Policy source(s):** [`CLAUDE.md`](../../../../CLAUDE.md) (Absolute Rules + Bug Fix Protocol + Test Conventions), [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md) (error envelope), [`docs/05_quality/testing.md`](../../../05_quality/testing.md) (test-layer convention)

---

## 0) Planning principles

- Spec traceability first: every story maps to FR IDs from §17 of the spec.
- The 8 stories ship as **one PR** (locked by spec §3 Phase boundaries) — there are no inter-story phase gates, just sequencing inside one branch.
- Fail-loud tests: the parity test, the per-query shape parity test, and the existing-row read regression are the load-bearing gates.
- Keep the migration narrow: no scope expansion beyond what FR-1 through FR-7 require. The `confidence.py` rework, the `ranx` extras, and the `pytrec-eval-terrier` fork are all explicitly OUT per spec §3 + §19 decisions.
- Permanent test infra: `pytrec-eval>=0.5` stays in `[dependency-groups.dev]` indefinitely so the parity gate keeps firing post-merge.

## 1) Scope traceability (FR → epics/phases)

| FR ID | Epic / Story | Notes |
|---|---|---|
| FR-1 (scoring.py swap + locked metric-object mapping + per-query iteration aggregate) | Epic 1 / Story 1.3 | Single core code rewrite. Aggregate-via-iter contract (C2-F4) is load-bearing. |
| FR-2 (parity test, permanent CI gate, 30 parametrized cases) | Epic 1 / Story 1.2 (fixture + skeleton) → Story 1.4 (assertions activated) | Test-infra precedes activation to keep the branch always-green. |
| FR-3 (no wire-form leakage + per-query shape parity) | Epic 1 / Story 1.4 (shape parity) + Story 1.5 (leakage + existing-row regression) | Per-query shape parity rides with parity activation; leakage assertion extension + existing-row regression are a separate story. |
| FR-4 (pyproject.toml: runtime `ir-measures` + dev `pytrec-eval` + mypy override audit) | Epic 1 / Story 1.1 | First story — every later story needs the new lib installed. |
| FR-5 (operator-visible error message at `studies.py:313` + docstring sweep) | Epic 1 / Story 1.6 | `test_studies_api_contract.py:156` docstring reworded; existing structural assertions unchanged (no message substring is pinned today — verified 2026-05-22). The `test_seeding.py` `p@10` → `precision@10` inline fix moved to Story 1.5 task 0 per plan cycle-1 F7. |
| FR-6 (Dockerfile conditional gcc/g++/python3-dev install) | Epic 1 / Story 1.7 | Empirical — depends on §19 Q3 resolution. |
| FR-7 (doc-rewrite sweep + dashboard regen + broader wire-form grep gate) | Epic 1 / Story 1.8 | Final story — runs after every code change is in so the grep gates verify a clean working tree. |

All 7 FRs covered. No deferred phases (spec is single-phase per §3). No deferred-phase tracking files needed.

### Open question resolution

| Question (from spec §19) | Resolved during | Resolution recorded in |
|---|---|---|
| Q1: Reword historical migration `0015_trials_per_query_metrics.py:17` docstring? | Story 1.8 (doc sweep) | Story 1.8 tasks list — recommendation is reword (forward-looking explanation for future engineers). |
| Q2: Does `ir_measures` ship `py.typed`? | Story 1.1 (pyproject) | Story 1.1 task — `find $(python -c 'import ir_measures, os; print(os.path.dirname(ir_measures.__file__))') -name py.typed`; result drives the mypy-override decision. |
| Q3: Does `ir_measures` keep `pytrec_eval` as a transitive backend? | Story 1.7 (Dockerfile) | Story 1.7 task — `pip install ir-measures && pip show pytrec_eval` + `uv tree \| grep pytrec_eval`. |
| Q4: Provider routing per metric / forcing API? | Story 1.4 (parity activation) | If all 30 cases pass, resolves "no action needed". If any fail, narrow to bounded outcomes (a)/(b)/(c)/(d) per spec §19 Q4. |
| Q5: Transitive deps + license + performance verification? | Story 1.1 (deps inspection) + Story 1.4 (perf benchmark) | Story 1.1 — `uv tree` license cross-check. Story 1.4 — `pytest backend/tests/benchmarks/test_scoring_perf.py -v` before/after diff. |

## 2) Delivery structure

**Epic → Story → Tasks → DoD.** Eight stories in one epic, sequenced as listed in §1 (1.1 → 1.2 → 1.3 → 1.4 → 1.5 → 1.6 → 1.7 → 1.8). Each story is verifiable independently (tests pass at the end of each); the branch is always green.

### Conventions (project-specific)

The migration touches the eval layer, the worker layer, the API layer, the test infrastructure, and docs. Conventions to respect:

- **Public API of `scoring.py` is FROZEN** per spec FR-1 (Decision log lock). `score()`, `objective_metric_key()`, `SUPPORTED_METRICS`, `SUPPORTED_K_VALUES`, `ScoreResult`, `Qrels`, `Run` keep their signatures byte-identically.
- **Persisted JSONB keys are FROZEN** per spec FR-1c / FR-3. `trials.metrics` and `trials.per_query_metrics` continue to use user-facing tokens (`ndcg@10`, `map@10`, `mrr`, plain `map`).
- **Aggregate is computed via per-query iteration + manual mean** — NOT via `ir_measures.calc_aggregate()` (C2-F4 contract).
- **No `pytrec_eval` runtime dependency.** `pytrec-eval>=0.5` lives only in `[dependency-groups.dev]` after this PR.
- **`uv sync`** regenerates `uv.lock` automatically; that's a normal side-effect.
- **Conventional Commits** per CLAUDE.md Absolute Rule #7. Branch name: `feature/infra-ir-measures-migration`. Commits use `feat(eval):` / `chore(eval):` / `docs(eval):` prefixes.
- **No `--no-verify` on commits.** Pre-commit hooks (ruff format + ruff check + mypy strict on backend, prettier on frontend) must pass.

### AI Agent Execution Protocol

0. Load context first: read `architecture.md` and `state.md` before starting Story 1.1.
1. Read scope: confirm story outcome + new/modified files + tasks + DoD.
2. Implement story-by-story in the §1 order (1.1 through 1.8 — strictly sequential).
3. Run tests after each story:
   - Story 1.1: `uv sync && uv lock --check && make typecheck`.
   - Story 1.2: `pytest backend/tests/unit/eval/test_scoring_parity.py -v` (will skip with `pytest.mark.skip`; check fixture loads).
   - Story 1.3: `make test-unit` (existing scoring tests must pass against new `ir_measures` backend).
   - Story 1.4: `pytest backend/tests/unit/eval/ -v` (parity test now active; 30 cases + per-query shape test).
   - Story 1.5: `make test-contract && make test-integration` (leakage assertions extended; existing-row regression added).
   - Story 1.6: `pytest backend/tests/contract/test_studies_api_contract.py -v` (docstring reworded; no assertion change — see Story 1.6 task 3).
   - Story 1.7: `docker build .` (Dockerfile change empirically verified).
   - Story 1.8: `grep -rn 'pytrec_eval\|pytrec-eval' . --exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=.git` AND the broader wire-form grep (per FR-7) — both must match only the allowlist.
4. Update docs in same PR (the doc sweep IS Story 1.8 — no separate workstream).
5. No migration round-trip (no schema change).
6. After Story 1.8, update `state.md` with a new dated entry (no back-edits).

---

## Epic 1 — Replace `pytrec_eval` with `ir_measures`

### Story 1.1 — Add `ir-measures` to runtime deps; move `pytrec-eval` to dev-group; audit mypy overrides

**Outcome:** `pyproject.toml` is the new dependency state — `ir-measures>=0.4.3` is a runtime dep; `pytrec-eval>=0.5` is a dev/test dep only; `[[tool.mypy.overrides]]` matches the actual import surface. `uv.lock` regenerates cleanly; `mypy --strict` passes.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| [`pyproject.toml`](../../../../pyproject.toml) | (a) Remove `"pytrec-eval>=0.5"` from `[project].dependencies` (line 47). (b) Add `"ir-measures>=0.4.3"` in its place under `[project].dependencies`. (c) Add `"pytrec-eval>=0.5"` to `[dependency-groups.dev]` (between `pre-commit>=4.6.0` and `types-PyYAML>=6.0`, alphabetical). (d) Audit the `[[tool.mypy.overrides]]` block at lines 156–158: see Q2 resolution below. |
| [`uv.lock`](../../../../uv.lock) | Auto-regenerated by `uv lock` — do NOT edit by hand. Commit alongside `pyproject.toml`. |

**Tasks**

1. Resolve §19 Q2 (Does `ir_measures` ship `py.typed`?). Recipe:
   ```bash
   uv sync --frozen=false  # let the lock regen
   find $(uv run python -c 'import ir_measures, os; print(os.path.dirname(ir_measures.__file__))') -name py.typed
   ```
   Two outcomes:
   - Empty: `ir_measures` does NOT ship type hints → ADD a new `[[tool.mypy.overrides]]` block:
     ```toml
     [[tool.mypy.overrides]]
     module = "ir_measures"
     ignore_missing_imports = true
     ```
   - One path: `ir_measures` DOES ship `py.typed` → no new override needed.
2. Audit the existing `pytrec_eval` mypy override at lines 156–158. After Story 1.3 lands, `scoring.py` no longer imports `pytrec_eval`. After Story 1.2 lands, the parity test DOES import `pytrec_eval`. The override stays as long as ANY source imports `pytrec_eval`. After this story, no source imports it yet (Stories 1.2 + 1.4 add the parity test), so the override is needed only after Story 1.2. **For ordering: keep the override in Story 1.1 — it's already there, and removing/re-adding it is churn. Delete only if Q3 resolves "no pytrec_eval in dev-group either" (which would never happen under FR-4).**
3. Resolve §19 Q5 (transitive deps + license). Recipe:
   ```bash
   uv tree
   # Then manually verify each new package's license is Apache 2.0-compatible (MIT, Apache, BSD all OK).
   ```
   Expected new packages from `ir-measures`: `cwl-eval`, possibly `pandas` (already present transitively via `optuna`'s deps), `numpy` (already present via `scikit-learn`). Record the new dependency list in the Story 1.1 PR commit message.
4. Run `uv sync` to regenerate `uv.lock`. Commit `pyproject.toml` + `uv.lock` together.
5. Run `make typecheck` — must pass. If `ir_measures` doesn't ship types and the override was missed, this will surface a `Cannot find implementation or library stub for module named 'ir_measures'` error → add the override.

**Definition of Done (DoD)**

- `pyproject.toml` `[project].dependencies` contains `"ir-measures>=0.4.3"` AND does NOT contain any `pytrec-eval` line (verified by AC-4a's TOML check).
- `pyproject.toml` `[dependency-groups.dev]` contains `"pytrec-eval>=0.5"` (verified by AC-4b).
- `[[tool.mypy.overrides]]` blocks match the import surface: `ir_measures` override iff Q2 says it doesn't ship type hints; `pytrec_eval` override stays as long as anything in the source tree imports it (verified by AC-4c).
- `uv lock --check` exit code 0 (lockfile is up-to-date).
- `make typecheck` passes.
- The Q5 dependency license audit is recorded in the commit message (the new packages' licenses are documented).

---

### Story 1.2 — Create parity test fixture and skeleton (skipped placeholders)

**Outcome:** The parity test infrastructure is in the repo, fixture loads, both libraries are importable side-by-side. The 30 parametrized cases exist but are marked `pytest.mark.skip(reason="scoring.py not yet migrated to ir_measures — activate in Story 1.4")` so the branch stays green while Story 1.3's code rewrite is in progress.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/unit/eval/fixtures/__init__.py` | Empty (Python package marker). Verify `backend/tests/unit/eval/` doesn't already have a `fixtures/` directory; if it does, skip this. |
| `backend/tests/unit/eval/fixtures/parity_qrels_run.py` | Fixed (qrels, run) fixture per spec FR-2. Must include: ≥ 10 queries, ≥ 5 docs each, mixed graded ratings 0/1/2/3, AND the 6 edge cases per spec FR-2 + plan cycles 2/3: (a) one query with no relevant docs (zero-score path), (b) one query in qrels with no matching docs in run (qrel-only / missing-from-run), (c) one query in run with no entry in qrels (run-only / unjudged), (d) one query whose run has no overlap at all with the qrels (the "study2 scenario"), (e) one query with `qrels[q] = {}` but non-empty `run[q]` (cycle-2 C2-F1 universe-filter coverage), (f) one query with `run[q] = {}` but non-empty `qrels[q]` (cycle-3 C3-F1 symmetric coverage). Export `qrels: Qrels` and `run: Run` module-level constants. |
| `backend/tests/unit/eval/test_scoring_parity.py` | The parity test. Imports both `pytrec_eval` and `ir_measures`. Defines the 30 parametrized cases per spec FR-2 (3 cut-required metrics × 7 k = 21; map × 7 + plain map = 8; plain mrr = 1). Skipped in Story 1.2; activated in Story 1.4. |

**Modified files**

None (this is a pure additive story; the fixture and test live in new files only).

**Key interfaces**

```python
# backend/tests/unit/eval/fixtures/parity_qrels_run.py
from backend.app.eval.scoring import Qrels, Run

qrels: Qrels  # {query_id: {doc_id: int rating}}
run: Run      # {query_id: {doc_id: float score}}
# Exactly 4 edge-case queries documented inline with comments naming each case.
```

```python
# backend/tests/unit/eval/test_scoring_parity.py
import pytest
import pytrec_eval
import ir_measures
from ir_measures import nDCG, AP, P, R, RR
from backend.app.eval.scoring import score
from backend.tests.unit.eval.fixtures.parity_qrels_run import qrels, run

# 30-case parametrize covering:
#   ("ndcg", k) for k in [1,3,5,10,20,50,100]              # 7
#   ("precision", k) for k in [1,3,5,10,20,50,100]         # 7
#   ("recall", k) for k in [1,3,5,10,20,50,100]            # 7
#   ("map", k) for k in [1,3,5,10,20,50,100]               # 7
#   ("map", None)                                          # 1
#   ("mrr", None)                                          # 1
PARITY_CASES: list[tuple[str, int | None]] = [...]

@pytest.mark.skip(reason="scoring.py not yet migrated — activate in Story 1.4")
@pytest.mark.parametrize("metric,k", PARITY_CASES)
def test_score_matches_pytrec_eval_within_1e_minus_6(metric: str, k: int | None) -> None:
    """Compare score()'s aggregate to pytrec_eval direct, mean-across-queries."""
    ...

@pytest.mark.skip(reason="scoring.py not yet migrated — activate in Story 1.4")
def test_per_query_shape_matches_pytrec_eval() -> None:
    """Per-query shape parity per spec FR-3 / C2-F4."""
    ...
```

**Tasks**

1. Verify `backend/tests/unit/eval/` is the correct test path: `ls backend/tests/unit/eval/test_scoring.py` exists → path verified.
2. Create the fixture file. Write the 8 queries with explicit comments calling out which is which edge case. Use realistic doc IDs (e.g., `"d{i}"` strings). Ratings stay in `{0, 1, 2, 3}` (graded). **Include BOTH symmetric empty-inner-dict cases** so the cycle-2 universe-filter tightening is verified on both sides (per plan cycle-3 C3-F1):
   - `qrels["q_empty_qrels"] = {}` with a non-empty `run["q_empty_qrels"]` (e.g., 3 doc IDs).
   - `run["q_empty_run"] = {}` with a non-empty `qrels["q_empty_run"]` (e.g., 2 rated doc IDs).
   - Together, this raises the fixture's query count to ≥ 10 and ensures the parity test PINS whatever `pytrec_eval`'s legacy behavior is on both empty-inner cases. If `pytrec_eval` emits the qid in either case (e.g., as zero-valued metrics) the parity test will fail, and Story 1.3 must relax the filter to match.
3. Create the parity test file. Build the 30-case `PARITY_CASES` list as a module-level constant. Both test functions are decorated with `@pytest.mark.skip` referencing Story 1.4.
4. The actual assertion bodies CAN be sketched in this story (they'll be unskipped in Story 1.4), but they MUST follow the C2-F4 contract:
   - For aggregate parity: call `score(qrels, run, {token})` (the function-under-test); separately compute the `pytrec_eval` value via `pytrec_eval.RelevanceEvaluator(qrels, {wire_set}).evaluate(run)` and take the same mean-across-queries the current `score()` performs at lines 187–192. Assert `abs(score_aggregate - pytrec_mean) < 1e-6`.
   - For per-query shape AND per-query value parity (per spec FR-3 + cycle-1 F3): assert (a) the outer qid set is identical between `score(qrels, run, {token})["per_query"]` and the legacy `pytrec_eval` output (after wire→user-facing re-keying), (b) the inner metric-key set for each qid is identical, AND (c) every present `(qid, metric)` value matches `pytrec_eval`'s value to 1e-6 (`abs(a - b) < 1e-6`). Without (c), the shape test could pass while every value is wrong. Use the same fixture as the aggregate parity test.
   - **DO NOT** call `ir_measures.calc_aggregate(...)` anywhere — that's the C2-F4 prohibition.
5. Run `pytest backend/tests/unit/eval/test_scoring_parity.py -v --collect-only` → confirms 31 collected items (30 parity + 1 shape test) all marked SKIPPED.

**Definition of Done (DoD)**

- New files exist at the listed paths and import cleanly under `pytest --collect-only`.
- Fixture exports `qrels` and `run` at module scope; pyright/mypy strict pass over the test file.
- 30 parametrized cases enumerable via `pytest --collect-only -q | grep test_score_matches_pytrec_eval_within_1e_minus_6` returns 30 lines.
- The 4 edge-case queries are documented inline (one comment per query naming the case it covers).
- All 31 tests SKIP — no execution failures.
- Existing tests still pass (`make test-unit` green).

---

### Story 1.3 — Rewrite `scoring.py` with `ir_measures` + locked metric-object mapping

**Outcome:** [`backend/app/eval/scoring.py`](../../../../backend/app/eval/scoring.py) imports `ir_measures` instead of `pytrec_eval`. `_translate_metric_name()` returns `ir_measures` metric objects per the locked FR-1 mapping table. `score()` computes the aggregate via per-query iteration + manual mean (NOT via `ir_measures.calc_aggregate()`). The existing `test_scoring.py` + `test_scoring_metric_tokens.py` + `test_qrels_loader.py` continue to pass without source edits.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| [`backend/app/eval/scoring.py`](../../../../backend/app/eval/scoring.py) | Replace `import pytrec_eval` (line 22) with `import ir_measures` plus explicit imports `from ir_measures import nDCG, AP, P, R, RR`. Rewrite `_translate_metric_name()` to return metric objects per the FR-1 mapping table (NOT wire strings). Rewrite `score()`'s body (lines 153–194) to: (1) translate each token via the new `_translate_metric_name`, (2) iterate via `ir_measures.iter_calc([obj_list], qrels, run)` yielding `Metric(query_id, measure, value)` tuples, (3) build `per_query` dict by mapping each tuple's `measure` back to its user-facing token, (4) compute aggregate as `sum(values) / len(values)` over the per-query dict — matching the current logic at lines 187–192 EXACTLY. Update module + function docstrings to name `ir_measures`. Update the source-of-truth line-citation that other docstrings reference (now pointing at the new internal logic). |

**Key interfaces**

The public API is FROZEN per spec FR-1. Only the INTERNALS change.

```python
# backend/app/eval/scoring.py — PUBLIC API (unchanged byte-for-byte)
SUPPORTED_METRICS: frozenset[str] = frozenset({"ndcg", "map", "precision", "recall", "mrr"})
SUPPORTED_K_VALUES: frozenset[int] = frozenset({1, 3, 5, 10, 20, 50, 100})
Qrels = dict[str, dict[str, int]]
Run = dict[str, dict[str, float]]

class ScoreResult(TypedDict):
    aggregate: dict[str, float]
    per_query: dict[str, dict[str, float]]

def objective_metric_key(objective: dict[str, object]) -> str: ...
def score(qrels: Qrels, run: Run, metrics: set[str]) -> ScoreResult: ...

# backend/app/eval/scoring.py — PRIVATE (signature changes return type)
def _translate_metric_name(user_facing: str) -> object:
    """Return an ir_measures metric object per the FR-1 locked mapping.

    Mapping (locked by feature_spec.md FR-1):
        ndcg@<k>      → nDCG @ k
        map           → AP
        map@<k>       → AP @ k
        precision@<k> → P @ k
        recall@<k>    → R @ k
        mrr           → RR

    Uncut ndcg/precision/recall still raise the existing "requires an @<k> cut"
    ValueError. The function's other ValueError paths (unknown base, bad k,
    k-not-in-allowlist, "metric does not accept an @<k> cut") are all preserved
    with the same triggering inputs.
    """
```

**Tasks**

1. Update the module docstring (lines 1–16). Replace "pytrec_eval scoring helper (infra_optuna_eval Story 1.2 / FR-3 + FR-5)" wording with the `ir_measures` equivalent; keep all the spec/FR references that remain accurate.
2. Replace `import pytrec_eval` (line 22) with `import ir_measures` + `from ir_measures import nDCG, AP, P, R, RR`.
3. Rewrite `_translate_metric_name()` (lines 51–103). The new body:
   ```python
   def _translate_metric_name(user_facing: str) -> object:
       if user_facing == "mrr":
           return RR
       if user_facing == "map":
           return AP

       if "@" not in user_facing:
           raise ValueError(
               f"metric {user_facing!r} requires an @<k> cut (allowed bases: "
               f"{sorted(SUPPORTED_METRICS - _K_NEVER)})"
           )

       base, _, k_str = user_facing.partition("@")
       if base not in SUPPORTED_METRICS:
           raise ValueError(f"unknown metric base {base!r}; allowed: {sorted(SUPPORTED_METRICS)}")
       if base in _K_NEVER:
           raise ValueError(f"metric {base!r} does not accept an @<k> cut; use plain {base!r}")
       try:
           k = int(k_str)
       except ValueError as exc:
           raise ValueError(f"k value {k_str!r} in {user_facing!r} is not an integer") from exc
       if k not in SUPPORTED_K_VALUES:
           raise ValueError(
               f"k={k} in {user_facing!r} is not in the allowlist {sorted(SUPPORTED_K_VALUES)}"
           )

       if base == "ndcg":
           return nDCG @ k
       if base == "map":
           return AP @ k
       if base == "precision":
           return P @ k
       if base == "recall":
           return R @ k
       raise ValueError(f"unexpected metric base {base!r}")  # pragma: no cover
   ```
   Every ValueError path is preserved character-for-character with the existing wording. Only the return values change.
4. Keep `objective_metric_key()` (lines 106–150) **untouched**. It returns user-facing token strings; this migration doesn't change that.
5. Rewrite `score()` (lines 153–194). The new body — **includes per-query universe filtering by default** so the per-query shape parity test (Story 1.4) doesn't depend on `ir_measures.iter_calc()` emitting exactly the pytrec_eval qid universe (per cycle-1 F2 + F3):
   ```python
   def score(qrels: Qrels, run: Run, metrics: set[str]) -> ScoreResult:
       # Map user-facing → metric-object; remember the reverse for re-keying.
       user_to_obj: dict[str, object] = {m: _translate_metric_name(m) for m in metrics}
       obj_to_user: dict[object, str] = {obj: user for user, obj in user_to_obj.items()}
       obj_list = list(user_to_obj.values())

       # Per-query: iterate ir_measures' per-(qid, measure, value) tuples; re-key.
       # FILTER to the pytrec_eval qid universe (per spec FR-3's historical contract):
       # keep only qids that have at least one rated doc in qrels AND at least one
       # scored entry in run — NOT just qid-key membership in both outer dicts.
       # An empty inner dict (qrels[qid] == {} or run[qid] == {}) excludes the qid
       # from pytrec_eval's evaluator output today; the filter preserves that
       # exclusion. (Tightened per plan cycle-2 C2-F1.)
       valid_qids: frozenset[str] = frozenset(
           qid for qid in qrels.keys() & run.keys()
           if qrels.get(qid) and run.get(qid)
       )
       per_query: dict[str, dict[str, float]] = {}
       for metric_tuple in ir_measures.iter_calc(obj_list, qrels, run):
           if metric_tuple.query_id not in valid_qids:
               continue
           user_token = obj_to_user[metric_tuple.measure]
           per_query.setdefault(metric_tuple.query_id, {})[user_token] = float(metric_tuple.value)

       # Aggregate: mean across queries, per user-facing metric — matches the
       # original logic at scoring.py:187-192 (DO NOT call calc_aggregate).
       aggregate: dict[str, float] = {}
       if per_query:
           for user in user_to_obj:
               values = [q[user] for q in per_query.values() if user in q]
               if values:
                   aggregate[user] = sum(values) / len(values)

       return {"aggregate": aggregate, "per_query": per_query}
   ```
   **CRITICAL invariants** (both are enforced inline by the snippet above):
   - The aggregate is computed over the per_query dict — NOT delegated to `ir_measures.calc_aggregate()` (C2-F4 contract).
   - The per-query universe is filtered to `qrels.keys() & run.keys()` — preserving the pytrec_eval qid set on qrel-only / run-only / empty-overlap edge cases. This makes Story 1.4's per-query shape parity test a verification step rather than a fallback-fixup moment.
6. Update docstrings for `_translate_metric_name` and `score` to name `ir_measures` and the metric-object DSL. Reword any reference to "pytrec_eval wire names" to "ir_measures metric-object DSL".
7. Update the line-number-referencing module docstring at scoring.py:14-15 (currently says "per spec §FR-5"). The reference stays valid; just update the surrounding library name.
8. Run `make test-unit` — the existing `test_scoring.py`, `test_scoring_metric_tokens.py`, and `test_qrels_loader.py` must pass WITHOUT source edits. If any expected value drifts, the migration is invalid for that metric — STOP and resolve §19 Q4 (provider routing) before continuing.
9. Run `make typecheck` — `mypy --strict` over the new `scoring.py`. Pay attention to the `_translate_metric_name() -> object` return type; if mypy complains about losing precision, use a Union of the specific ir_measures metric-object types (subject to whether `ir_measures` exports those types as named classes).

**Definition of Done (DoD)**

- `import pytrec_eval` no longer appears in `scoring.py` (AC-1).
- `import ir_measures` appears exactly once.
- `_translate_metric_name()` returns metric objects per the locked mapping table; every ValueError path's wording is preserved.
- `score()` computes the aggregate via per-query iteration + manual mean — NOT `ir_measures.calc_aggregate()` (verified by `grep -n 'calc_aggregate' backend/app/eval/scoring.py` returning zero lines).
- `objective_metric_key()` is untouched (verified by `git diff backend/app/eval/scoring.py` not showing any change in lines 106–150).
- `make test-unit` passes — no existing eval test fails.
- `make typecheck` passes.
- Q4 first-touch resolution: if every existing `test_scoring.py` test still passes against the new backend, Q4 resolves to outcome (a) "default routing produces parity, no forcing needed". Record in the commit message.

---

### Story 1.4 — Activate parity test + per-query shape parity + Q5 perf benchmark

**Outcome:** The parity test's 30 cases are LIVE and passing. The per-query shape parity test asserts identical outer-qid sets and inner-metric-key sets between the new `score()` and the legacy `pytrec_eval`-direct output. The benchmark-perf delta is within ±10% (§19 Q5 resolved).

**New files**

None (the test file landed in Story 1.2).

**Modified files**

| File | Change |
|---|---|
| `backend/tests/unit/eval/test_scoring_parity.py` | Remove the `@pytest.mark.skip` decorators from both test functions. Fill in the assertion bodies per the Story 1.2 sketch (if not already filled). |

**Tasks**

1. Remove the `@pytest.mark.skip` decorator from `test_score_matches_pytrec_eval_within_1e_minus_6` AND `test_per_query_shape_matches_pytrec_eval`.
2. Run `pytest backend/tests/unit/eval/test_scoring_parity.py -v` — expect 31 passing (30 parametrized + 1 shape).
3. If any parity case fails:
   - **DO NOT** weaken the tolerance or skip the failing case.
   - Inspect the failing metric — what provider did `ir_measures` route it through? Use only documented APIs per spec §19 Q4 (no leading-underscore private names).
   - Apply the bounded outcome from spec §19 Q4: (a) default routing OK → impossible since we got a failure; (b) documented provider-forcing API at the pinned version → use it; (c) bump/repin `ir_measures` → record the new version; (d) blocker → STOP and escalate to the user with the failure detail.
4. **Verify the per-query universe filter in Story 1.3 worked.** Story 1.3's `score()` already filters per-query results to `qrels.keys() & run.keys()` (the pytrec_eval-historical qid universe) — that's an unconditional invariant, not a contingency. If the per-query shape test fails despite that filter, something deeper is wrong:
   - Possibility (a): The filter is correct in `score()` but pytrec_eval is emitting *different* qids than the filter would predict — investigate pytrec_eval's actual behavior on the fixture's edge-case queries; if pytrec_eval omits a qid that `qrels.keys() & run.keys()` includes, the filter set may need to be tighter (e.g., also require at least one relevant doc in the qrel set).
   - Possibility (b): Per-(qid, metric) values disagree at the 1e-6 boundary — see step 3 (this is the Q4 provider-routing case).
   - Possibility (c): A bug in the test's pytrec_eval baseline computation — review the test code.
   - **Never** weaken the test to make it pass. If the filter needs refinement, tighten it in `scoring.py` and re-run the test. The persisted JSONB key set must continue to match what production currently emits.
5. Resolve §19 Q5 perf delta. Run `pytest backend/tests/benchmarks/test_scoring_perf.py -v` on the feature branch; compare against the same run on `main`. Acceptable: ±10% on the warm-call timing. Record both numbers in the commit message.

**Definition of Done (DoD)**

- `test_score_matches_pytrec_eval_within_1e_minus_6` passes for all 30 parametrized cases (AC-2).
- `test_per_query_shape_matches_pytrec_eval` passes — covers qid-set parity, inner-key-set parity, AND per-(qid, metric) value parity at 1e-6 (FR-3 + cycle-1 F3).
- `grep -n '@pytest.mark.skip\|pytest.skip' backend/tests/unit/eval/test_scoring_parity.py` returns ZERO matches (per cycle-1 F9 — guards against accidentally leaving a skipped parity gate).
- The benchmark perf delta is within ±10% of pre-migration baseline (AC-9 / Q5 resolution).
- Q4 resolution is recorded in the commit message: outcome (a)/(b)/(c) per spec §19 — with the cited verification output.
- No skips, no xfails, no weakened tolerances.

---

### Story 1.5 — Extend "no wire-form leakage" assertions; add existing-row read regression

**Outcome:** The contract + integration test assertions that forbid `pytrec_eval` wire-form prefixes are extended to ALSO forbid `ir_measures` PascalCase reprs. The new existing-row read regression test loads pre-migration JSONB shapes and exercises the consumers (`fetch_study_confidence` + trial-list endpoint + digest worker) without re-scoring.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/integration/test_existing_row_read_compat.py` | Per AC-12 / GPT-5.5 cycle-1 F9. Inserts a synthetic `Trial` with pre-migration JSONB shape (`metrics = {"ndcg@10": ..., "map@10": ..., "map": ..., "mrr": ...}`; `per_query_metrics = {"q1": {"ndcg@10": ...}, ...}`); then calls `fetch_study_confidence`, asserts the trial-list endpoint serializes the JSONB through, and asserts the digest worker's top-trials section runs without raising. Load-bearing test for the "no migration / no backfill" claim. |

**Modified files**

| File | Change |
|---|---|
| [`backend/tests/contract/test_trial_row_shape.py`](../../../../backend/tests/contract/test_trial_row_shape.py) | Lines 6, 109, 113 — update docstrings to name `ir_measures`. **The leakage assertion at line 111 iterates over the module-level tuple `_PYTREC_EVAL_WIRE_PREFIXES` defined at lines 51–57** (verified 2026-05-22 — contains `("ndcg_cut_", "P_", "recall_", "recip_rank", "map_cut_")`). Action: (a) rename the tuple to `_FORBIDDEN_WIRE_PREFIXES` and add the `ir_measures` PascalCase entries (`nDCG@`, `AP@`, `P@`, `R@`, `RR`); (b) tighten the loop to handle `RR` correctly (it's a whole-token match, not a prefix — use `key == "RR"` OR `key.startswith("RR@")` as a separate check, OR adopt the AC-3 strict regex approach below). Recommended: switch the entire assertion to the strict regex per AC-3:<br><br>```python<br>_STRICT_USER_FACING_KEY = re.compile(<br>    r"^(?:mrr\|map\|(?:ndcg\|precision\|recall\|map)@(?:1\|3\|5\|10\|20\|50\|100))$"<br>)<br>for key in t.metrics:<br>    assert _STRICT_USER_FACING_KEY.match(key), (<br>        f"metrics key {key!r} is not in the user-facing token allowlist — "<br>        f"library wire forms must never leak past scoring.score()"<br>    )<br>```<br><br>Then ADD the negative-case + positive-case parametrized helper tests per AC-3 (13 negative cases + ~10 positive cases). |
| [`backend/tests/integration/test_run_trial_per_query_persistence.py`](../../../../backend/tests/integration/test_run_trial_per_query_persistence.py) | Lines 53, 111, 119 — docstring rewording. **The existing assertion already rejects `ir_measures` PascalCase reprs** (verified 2026-05-22): the check `base = metric_key.partition("@")[0]; assert base in expected_metric_bases` where `expected_metric_bases = {"ndcg", "map", "precision", "recall", "mrr"}` rejects PascalCase because `"nDCG"` is case-sensitively NOT in the lowercase set. Action: (a) tighten the assertion to use the same strict regex from `test_trial_row_shape.py` (extract the regex to a shared `backend/tests/_eval_helpers.py` module to avoid duplication), (b) reword the docstring on line 119 to name `ir_measures` (replacing "score() should remap pytrec_eval wire names to user-facing tokens"). |
| [`backend/app/services/test_seeding.py`](../../../../backend/app/services/test_seeding.py) | Lines 127 + 142: change both `"p@10"` literals → `"precision@10"`. **Moved from Story 1.6 per cycle-1 F7** so the branch stays green when this story's AC-3 strict regex activates. 2-character fix bundled per spec §2 C2-F5 + §15 inline-fix entry. |

**Key interfaces**

```python
# backend/tests/integration/test_existing_row_read_compat.py
import pytest
from backend.app.services.study_confidence import fetch_study_confidence

@pytest.mark.integration
async def test_pre_migration_jsonb_shape_hydrates_confidence(db_session, ...):
    """Per AC-12 — pre-migration JSONB key shape continues to work post-migration.

    Insert a fixture trial with metrics/per_query_metrics keyed by the user-facing
    tokens already in production (ndcg@10, map@10, map, mrr). Confidence orchestrator
    must hydrate the shape; trial-list endpoint must serialize through; digest worker
    must include the row in its top-trials section.

    The load-bearing test for FR-1c / FR-3's "no-migration / no-backfill" invariant.
    """
    ...
```

**Tasks**

0. **FIRST:** Apply the `test_seeding.py` `p@10` → `precision@10` fix at lines 127 + 142 (moved here from Story 1.6 per cycle-1 F7; ordered first per cycle-2 C2-F2 so it precedes the strict-regex activation in tasks 1–6 below). Two literal substitutions; verify by `grep -n '"p@10"' backend/app/services/test_seeding.py` returning zero matches.
1. Read [`backend/tests/contract/test_trial_row_shape.py`](../../../../backend/tests/contract/test_trial_row_shape.py) to confirm line numbers (6 / 109 / 113) for the docstring + assertion.
2. Update docstring at line 6 to name `ir_measures` (the contract description: keys are user-facing names, NOT library wire forms).
3. Update docstring at line 109 to name `ir_measures`.
4. Extend the assertion logic. The existing check is something like:
   ```python
   assert not any(key.startswith(prefix) for prefix in ("ndcg_cut_", "P_", "recip_rank", "map_cut_", "recall_"))
   ```
   Extend to include `ir_measures` PascalCase reprs:
   ```python
   PYTREC_WIRE_PREFIXES = ("ndcg_cut_", "P_", "recip_rank", "map_cut_", "recall_")
   IR_MEASURES_REPRS = ("nDCG@", "P@", "RR", "AP@", "R@")
   forbidden = PYTREC_WIRE_PREFIXES + IR_MEASURES_REPRS

   for key in row_keys:
       assert not any(key.startswith(p) for p in forbidden), (
           f"metrics key {key!r} starts with a library wire-form prefix; "
           f"expected user-facing tokens only"
       )
   ```
   Note: `RR` is a 2-character whole token; `key.startswith("RR")` would match `RR_anything` but the test should reject the EXACT `RR` value. Use a stricter regex check matching the AC-3 strict regex:
   ```python
   import re
   _STRICT_KEY = re.compile(r"^(?:mrr|map|(?:ndcg|precision|recall|map)@(?:1|3|5|10|20|50|100))$")
   for key in row_keys:
       assert _STRICT_KEY.match(key), f"metrics key {key!r} not in user-facing token allowlist"
   ```
5. Add explicit negative cases per AC-3. Write a helper test that demonstrates the regex REJECTS each forbidden value:
   ```python
   @pytest.mark.parametrize("forbidden_key", [
       "ndcg",            # uncut — forbidden by objective_metric_key
       "precision",       # same
       "recall",          # same
       "nDCG@10",         # ir_measures repr
       "P@10",            # ir_measures repr
       "RR",              # ir_measures repr
       "AP@5",            # ir_measures repr
       "R@10",            # ir_measures repr
       "ndcg_cut_10",     # pytrec_eval wire
       "recip_rank",      # pytrec_eval wire
       "map_cut_10",      # pytrec_eval wire
       "P_10",            # pytrec_eval wire
       "recall_10",       # pytrec_eval wire
   ])
   def test_strict_key_regex_rejects_forbidden(forbidden_key: str) -> None:
       assert _STRICT_KEY.match(forbidden_key) is None, (
           f"strict key regex should REJECT {forbidden_key!r} but didn't"
       )

   @pytest.mark.parametrize("allowed_key", [
       "ndcg@10", "ndcg@5", "ndcg@1",
       "map@10", "map",
       "mrr",
       "precision@10", "precision@50",
       "recall@10", "recall@1",
   ])
   def test_strict_key_regex_accepts_allowed(allowed_key: str) -> None:
       assert _STRICT_KEY.match(allowed_key) is not None, (
           f"strict key regex should ACCEPT {allowed_key!r} but didn't"
       )
   ```
6. Repeat the steps for [`backend/tests/integration/test_run_trial_per_query_persistence.py`](../../../../backend/tests/integration/test_run_trial_per_query_persistence.py) lines 53 / 111 / 119. Extract the strict regex into a shared module — perhaps `backend/tests/_eval_helpers.py` — if the same regex is used in two test files.
7. Create the new existing-row read regression at `backend/tests/integration/test_existing_row_read_compat.py`. The test:
   - Sets up a study + judgment list + query set via the standard integration fixtures.
   - Inserts a hand-crafted `Trial` row with realistic pre-migration JSONB:
     ```python
     trial = await repo.create_trial(
         db,
         id=str(uuid7()),
         study_id=study.id,
         optuna_trial_number=5,
         params={"boost": 1.5},
         primary_metric=0.82,
         metrics={"ndcg@10": 0.82, "map@10": 0.71, "map": 0.65, "mrr": 0.91},
         per_query_metrics={
             "q1": {"ndcg@10": 0.83, "map@10": 0.7, "mrr": 1.0},
             "q2": {"ndcg@10": 0.81, "map@10": 0.72, "mrr": 0.83},
             # ...minimum 5 queries to satisfy bootstrap_ci_95's BOOTSTRAP_MIN_N_QUERIES
         },
         duration_ms=120,
         status="complete",
         error=None,
         started_at=..., ended_at=...,
     )
     await db.commit()
     ```
   - Stamps the study with `best_trial_id = trial.id` + `best_metric = trial.primary_metric`.
   - Calls `fetch_study_confidence(db, study.id)` and asserts the returned `ConfidenceShape` has `headline.value == 0.82`, `headline.n_queries > 0`, and `ci_95 is not None`.
   - Calls `GET /api/v1/studies/{study.id}` (via the integration test client) and asserts the response includes the `confidence` block with the same values.
   - **Calls the digest worker's top-trials selection logic** in isolation against this trial (REQUIRED per AC-12 — cycle-1 F4). The digest's top-trials renderer reads `Trial.primary_metric` (scalar) and `Trial.metrics` (JSONB); the test asserts the digest worker can include this row without raising. If the digest worker's relevant entrypoint isn't trivially callable in isolation, simulate the same read pattern: `select(Trial).where(Trial.study_id == study.id).order_by(Trial.primary_metric.desc())` followed by accessing the trial's JSONB fields.

**Definition of Done (DoD)**

- `backend/tests/contract/test_trial_row_shape.py` strict regex check passes for the migrated `score()` output.
- The new negative-case parametrize test passes (rejects each forbidden key explicitly).
- The new positive-case parametrize test passes (accepts each allowed key).
- `backend/tests/integration/test_run_trial_per_query_persistence.py` extended assertion passes.
- `backend/tests/integration/test_existing_row_read_compat.py` passes: pre-migration JSONB row hydrates `ConfidenceShape`, the trial-list endpoint serializes through, AND the digest worker's top-trials selection includes the row without raising (AC-12; all three consumers exercised — cycle-1 F4).
- The `test_seeding.py` `p@10` → `precision@10` inline fix is bundled in this story (moved from Story 1.6 per cycle-1 F7 to keep the branch green when AC-3's strict regex activates).
- `make test-contract && make test-integration` both green.

---

### Story 1.6 — Operator-visible error message at `studies.py:313` + docstring rewording

**Outcome:** The `INSUFFICIENT_JUDGMENT_OVERLAP` error envelope's `message` field no longer names `pytrec_eval`. The neighboring inline comment at `studies.py:270` is updated in lock-step. (Per cycle-1 F7: the `test_seeding.py` `p@10` → `precision@10` inline fix moved to Story 1.5 so the branch stays green when AC-3's strict regex activates.)

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| [`backend/app/api/v1/studies.py`](../../../../backend/app/api/v1/studies.py) | Line 270 inline comment: replace `pytrec_eval scores 0 on every trial by construction` → `ir_measures scores 0 on every trial by construction`. Line 313 error-message string: replace `pytrec_eval will likely score 0 on every trial` → `ir_measures will likely score 0 on every trial`. (Or, equivalently, name no library at all per spec FR-5 wording flexibility — `every trial will score 0 on every metric` is acceptable; the impl-plan author picks one and is consistent.) |
| [`backend/tests/contract/test_studies_api_contract.py`](../../../../backend/tests/contract/test_studies_api_contract.py) | Line 156 docstring rewording per spec §2 sweep. **No message-substring assertion update needed** — the existing `INSUFFICIENT_JUDGMENT_OVERLAP` contract tests at lines ~218–240 (verified 2026-05-22) are STRUCTURAL ONLY: they assert the error-code literal `"INSUFFICIENT_JUDGMENT_OVERLAP"` appears in the studies.py source AND that the source-presence ordering of error codes is preserved (`target_pos < probe_pos < overlap_pos < config_pos`). No substring of the human-readable `message` field is asserted. Reword the line-156 docstring's "pytrec_eval semantics" mention; no assertion changes needed. The atomic-update requirement from spec FR-5 reduces in scope: this story only updates the source string in `studies.py` (no test contract to bring along). |

**Tasks**

1. Read `backend/app/api/v1/studies.py` lines 268–320 to confirm the exact comment + error-message string and surrounding context.
2. Apply the rewording at line 270 (inline comment) and line 313 (error-message string). Use one consistent choice — recommendation: `ir_measures` (operator engineers reading the error need a library name to grep for if they need to inspect). The Spec §11 update for Story 1.6 also commits to one variant; pick the same wording here.
3. Read `backend/tests/contract/test_studies_api_contract.py` line 156 — reword the docstring's `pytrec_eval semantics` to name `ir_measures` (or "standard IR-evaluation conventions" — see spec §15 schemas.py guidance). **No assertion change needed** — the existing tests are structural-only (assert literal `"INSUFFICIENT_JUDGMENT_OVERLAP"` is in `studies.py` source and that error codes appear in a fixed order). The message substring is NOT pinned today; the spec's "atomic update" requirement is satisfied by the source-only change.
4. Run `pytest backend/tests/contract/test_studies_api_contract.py -v` — should pass without assertion changes (the docstring rewording is comment-only).

(Note: the `test_seeding.py` `p@10` → `precision@10` fix is bundled into Story 1.5 per cycle-1 F7 to keep the branch green when Story 1.5's AC-3 strict regex activates. It is NOT in this story.)

**Definition of Done (DoD)**

- `grep -n 'pytrec_eval' backend/app/api/v1/studies.py` returns zero matches (AC-7).
- `grep -n 'pytrec_eval' backend/tests/contract/test_studies_api_contract.py` returns zero matches (line 156 docstring reworded).
- `make test-contract` green.

---

### Story 1.7 — Dockerfile conditional update (gcc/g++/python3-dev install)

**Outcome:** The Dockerfile reflects the empirical transitive-dependency reality per §19 Q3. Either the gcc/g++/python3-dev install stays (with a reworded comment crediting `ir_measures`' transitive backend) or it's dropped (because `ir_measures` resolves to pure-Python providers only for all `SUPPORTED_METRICS`). `docker build .` succeeds either way.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| [`Dockerfile`](../../../../Dockerfile) | Lines 44–54: conditional change per Q3 resolution. Option (a) — `pytrec_eval` transitively present: KEEP the gcc/g++/python3-dev install; REWORD the comment at lines 44–48 to credit `ir_measures` (or the actual transitive C-extension dep). Option (b) — no transitive C extension: DROP lines 44–54 entirely (the `RUN apt-get update ...` block); `docker build .` succeeds with `python:3.13-slim` headers only. |

**Tasks**

1. Resolve §19 Q3 empirically. Recipe in a clean temp dir:
   ```bash
   cd /tmp && python -m venv .venv && source .venv/bin/activate
   pip install ir-measures
   pip show pytrec_eval
   # exit code 0 + non-empty output → transitive backend present
   # exit code 1 → no transitive backend
   ```
   Also confirm against `uv` resolution:
   ```bash
   cd /Users/ericstarr/relyloop && uv tree | grep pytrec_eval
   # output = pytrec_eval is a resolved dep (direct or transitive)
   # empty = not resolved
   ```
2. Apply the conditional Dockerfile change:
   - **Outcome (a) — TRANSITIVE backend present:** Keep the `RUN apt-get update ... gcc g++ python3-dev` block at lines 49–54. Reword the comment block at lines 44–48:
     ```dockerfile
     # ir_measures (added by infra_ir_measures_migration, replacing the abandoned
     # pytrec_eval) resolves a C-extension backend transitively (verified at impl-plan
     # time per feature_spec.md §19 Q3). The backend's sdist has no prebuilt wheels for
     # every Python version we target, so every install compiles its C extension on the
     # fly. We install gcc + python-dev headers here, then this whole stage is discarded
     # (the runtime stage copies only /app/.venv, not the build toolchain), so the final
     # image stays slim.
     ```
   - **Outcome (b) — NO transitive C extension:** Remove lines 39–54 entirely (the entire `RUN apt-get update ... && rm -rf /var/lib/apt/lists/*` block plus its comment header — the next layer `COPY pyproject.toml uv.lock README.md ./` becomes adjacent to the `FROM base AS deps` line). The `deps` stage compresses by ~40 LOC. Verify with `docker build .` succeeds.
3. Run `docker build . --target deps` to verify the deps stage builds cleanly. If outcome (a), confirm gcc/g++/python3-dev are still installed.
4. Run `docker build .` (full multi-stage) — must succeed. Verify the runtime image contains `ir_measures` via `docker run <image> python -c "import ir_measures; print(ir_measures.__file__)"`.

**Definition of Done (DoD)**

- `docker build .` succeeds (AC-10).
- The Dockerfile state matches the empirical Q3 verification — comment OR removal explicitly cites the verification output in the commit message.
- The runtime image can `import ir_measures` without error.
- No regression to the existing healthcheck or container size.

---

### Story 1.8 — Full doc-rewrite sweep + dashboard regen + broader wire-form grep gate

**Outcome:** Every current-state doc and comment that named `pytrec_eval` now names `ir_measures` (or names no library if appropriate). The MVP1_DASHBOARD.md is regenerated. Both grep gates (the basic `pytrec_eval|pytrec-eval` sweep AND the broader wire-form sweep for `RelevanceEvaluator|ndcg_cut_|map_cut_|recip_rank|recall_[0-9]|\bP_[0-9]`) return only allowlisted matches.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| [`README.md`](../../../../README.md) | Line 9 — `pytrec_eval` → `ir_measures`. |
| [`CLAUDE.md`](../../../../CLAUDE.md) | Lines 15 + 29 — both `pytrec_eval` mentions → `ir_measures`. |
| [`architecture.md`](../../../../architecture.md) | Line 131 — `eval/ pytrec_eval scoring` → `eval/ ir_measures scoring`. |
| [`release-notes-v0.1.0-draft.md`](../../../../release-notes-v0.1.0-draft.md) | Line 12 — stack table entry. |
| [`docs/00_overview/product/relevance-copilot-spec.md`](../../../00_overview/product/relevance-copilot-spec.md) | All 11 mentions (lines 12, 155, 688, 690, 692–693, 711, 2192, 2302, 2513, 2658, 2722). The "Engine: pytrec_eval everywhere" subsection (lines 688–693) is reframed as "Engine: provider-abstracted via `ir_measures`" with the reasons restated as: standard IR metric semantics across engines, per-query inspectability, cross-engine comparability (the old "de facto standard wrapper for trec_eval" framing becomes "provider abstraction means swapping backends is config, not rewrite"). |
| [`docs/01_architecture/optimization.md`](../../../01_architecture/optimization.md) | All 10 mentions. Title `# Optimization (Optuna + pytrec_eval)` → `# Optimization (Optuna + ir_measures)`. Code-example block at lines 87–90 (`pytrec_eval.RelevanceEvaluator(qrels, {"ndcg_cut_10", "map", "P_10"}).evaluate(run)`) rewritten to: `import ir_measures` + `metrics = list(ir_measures.iter_calc([nDCG@10, AP, P@10], qrels, run))` plus a note that RelyLoop's `score()` re-keys back to user-facing tokens (`ndcg@10`, `map`, `precision@10`). |
| [`docs/01_architecture/tech-stack.md`](../../../01_architecture/tech-stack.md) | Line 41 IR-evaluation row updated. |
| [`docs/01_architecture/system-overview.md`](../../../01_architecture/system-overview.md) | Line 76 component table row updated. |
| [`docs/01_architecture/README.md`](../../../01_architecture/README.md) | Line 21 cross-reference updated. |
| [`docs/01_architecture/data-model.md`](../../../01_architecture/data-model.md) | Lines 52 + 231 reworded. |
| [`docs/01_architecture/cluster-lifecycle.md`](../../../01_architecture/cluster-lifecycle.md) | Line 159 reworded. |
| [`docs/02_product/mvp1-user-stories.md`](../../../02_product/mvp1-user-stories.md) | Line 40 — US-7 narrative. |
| [`docs/02_product/planned_features/feat_study_baseline_trial/idea.md`](../feat_study_baseline_trial/idea.md) | Line 56 — sibling planned-feature coordination per spec §15. `scores via pytrec_eval` → `scores via ir_measures`. |
| [`docs/02_product/planned_features/feat_auto_followup_studies/idea.md`](../feat_auto_followup_studies/idea.md) | Line 47 — `Optuna + pytrec_eval are deterministic` → `Optuna + ir_measures are deterministic`. |
| [`docs/08_guides/workflows-overview.md`](../../../08_guides/workflows-overview.md) | Lines 123 + 277 reworded. |
| [`ui/public/docs/workflows-overview.md`](../../../../ui/public/docs/workflows-overview.md) | Lines 123 + 277 — runtime-served mirror; lock-step with `docs/08_guides/workflows-overview.md`. |
| [`ui/public/guides/05_import_judgments_and_calibrate/script.md`](../../../../ui/public/guides/05_import_judgments_and_calibrate/script.md) | Line 6 reworded. |
| [`ui/public/guides/06_create_and_monitor_study/script.md`](../../../../ui/public/guides/06_create_and_monitor_study/script.md) | Line 8 reworded. |
| [`ui/public/guides/06_create_and_monitor_study/metadata.json`](../../../../ui/public/guides/06_create_and_monitor_study/metadata.json) | Line 26 `caption` field reworded — same content shape as `script.md`. |
| [`ui/src/components/studies/create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx) | Line 60 source-of-truth comment: `// Source-of-truth: backend/app/eval/scoring.py:32 (metric → pytrec_eval token …)` → `// Source-of-truth: backend/app/eval/scoring.py (metric → ir_measures metric-object DSL …)`. The line-number citation is dropped because Story 1.3 rewrites that section; the symbol citation is enough. |
| [`ui/src/__tests__/components/studies/k-ignored.test.ts`](../../../../ui/src/__tests__/components/studies/k-ignored.test.ts) | Line 4 same source-of-truth comment update. |
| [`ui/src/lib/types.ts`](../../../../ui/src/lib/types.ts) | Line 1889 — `pytrec_eval semantics` comment reworded. |
| Test files: `backend/tests/unit/eval/test_scoring.py`, `test_scoring_metric_tokens.py`, `test_qrels_loader.py`, `backend/tests/integration/fixtures/handbuilt_qrels.py:75`, `backend/tests/benchmarks/test_scoring_perf.py:56` | Docstring + comment rewordings only. No assertion changes. |
| [`backend/app/eval/qrels_loader.py`](../../../../backend/app/eval/qrels_loader.py) | Line 45 docstring — `pytrec_eval treats as a no-op` → `ir_measures treats as a no-op` (the no-op-on-empty-input behavior is preserved across both libraries). |
| [`backend/app/db/models/trial.py`](../../../../backend/app/db/models/trial.py) | Lines 19 + 83 docstrings updated. |
| [`backend/app/api/v1/schemas.py`](../../../../backend/app/api/v1/schemas.py) | Line 534 — `ObjectiveSpec` docstring's "per pytrec_eval semantics" reframed: the cutoff requirement is an IR convention, not a `pytrec_eval` invention. Replace with: `per standard IR-evaluation conventions` (no library name needed — the convention predates both libraries). |
| [`migrations/versions/0015_trials_per_query_metrics.py`](../../../../migrations/versions/0015_trials_per_query_metrics.py) | Line 17 docstring per §19 Q1 recommendation: reword `NOT the pytrec_eval wire forms` → `NOT the library wire forms (per backend/app/eval/scoring.py)`. The migration file is part of the active source tree; future engineers read its docstring; rewording is forward-looking. |
| [`docs/00_overview/MVP1_DASHBOARD.md`](../../../00_overview/MVP1_DASHBOARD.md) | Regenerated via `scripts/build_mvp1_dashboard.py`. Picks up: (a) the `infra_optuna_eval` row's `pytrec_eval` mention at line 64 (this row stays in implemented_features but the dashboard regen reads the source feature_spec.md and propagates whatever description text is there — verify behavior), (b) the `infra_ir_measures_migration` row at line 134 (the planned-features entry text from THIS spec's first 200 chars). |

**Tasks**

1. **Doc rewordings (bulk).** Open each file in the modified files table; apply the rewording. Use `sed -i` where the replacement is a literal token swap (`pytrec_eval` → `ir_measures`) but verify each file before bulk substitution — the umbrella spec and optimization.md have prose context that may need a sentence-level rewrite, not a token swap.

2. **Umbrella spec rewrite (subsection).** The "Engine: pytrec_eval everywhere" subsection at `docs/00_overview/product/relevance-copilot-spec.md:688–693` needs more than a token swap. Rewrite to **never name `pytrec_eval` in the live umbrella spec** (per cycle-1 F5 — FR-7's allowlist does not include the umbrella spec, and the provider-abstraction framing doesn't require naming the underlying backend):
   ```markdown
   ### Engine: provider-abstracted IR evaluation via `ir_measures`

   Workers always evaluate via `ir_measures`, never engine-native `_rank_eval`. Reasons:

   - `ir_measures` (from the PyTerrier team) wraps multiple IR-evaluation backends behind a typed metric-object DSL (`nDCG@10`, `AP@5`, `RR`, …). The provider abstraction means swapping the underlying backend is a config change rather than a rewrite — protecting against future single-maintainer abandonment risk.
   - ES `_rank_eval` and `ir_measures` don't always agree to many decimal places (different normalization conventions across engines).
   - Per-query scores are inspectable, enabling deep debugging.
   - Cross-engine comparability: the same metric semantics apply whether the underlying engine is ES, OpenSearch, Fusion, or Solr.
   ```
   Note: the live umbrella spec MUST NOT name `pytrec_eval` after this rewrite. The "wraps multiple IR-evaluation backends" framing is sufficient. Historical context (what `pytrec_eval` was, why we migrated away) lives in the dated `state.md` entry and the frozen historical `feature_spec.md` under `implemented_features/` — NOT in the durable umbrella spec.

3. **Code-example rewrite in optimization.md.** Lines 87–90:
   ```python
   # OLD:
   metrics = pytrec_eval.RelevanceEvaluator(qrels, {"ndcg_cut_10", "map", "P_10"}).evaluate(run)
   ```
   →
   ```python
   # NEW:
   import ir_measures
   from ir_measures import nDCG, AP, P
   metrics_per_query = list(ir_measures.iter_calc([nDCG@10, AP, P@10], qrels, run))
   # RelyLoop's score() re-keys to user-facing tokens — see backend/app/eval/scoring.py.
   ```

4. **Migration docstring (Q1 resolution).** Apply the rewording to `migrations/versions/0015_trials_per_query_metrics.py:17` per the §19 Q1 recommendation.

5. **Regenerate MVP1_DASHBOARD.md and produce a CLEAN current-state dashboard** (per cycle-1 F6 — the implementation plan cannot amend AC-6; the regenerated dashboard MUST satisfy the FR-7 grep gate without an invented allowlist exception):
   ```bash
   python scripts/build_mvp1_dashboard.py
   ```
   Then inspect the regen output:
   - **`infra_ir_measures_migration` row at line ~134** — should regenerate cleanly from THIS feature's `feature_spec.md` (which is reworded by this very PR; the new dashboard row will name `ir_measures`).
   - **`infra_optuna_eval` row at line ~64** — the dashboard generator reads the implemented feature's `feature_spec.md` first-N-chars; that file is frozen historical and still names `pytrec_eval`. If the regen output still names `pytrec_eval` in the current-state dashboard, fix the generator (don't extend the AC-6 allowlist):
     - **Option (a) — preferred:** Audit `scripts/build_mvp1_dashboard.py` for how it builds the "description" cell for implemented features. If it pulls text verbatim from frozen historical specs, change it to pull from a current-state override (e.g., a `description_override` field in a sibling `pipeline_status.md` or `dashboard_summary.md` file) or hardcode a current-state one-liner per feature.
     - **Option (b) — fallback:** Edit the `infra_optuna_eval` row's description in the generator's input directly. The implemented feature's `feature_spec.md` itself stays frozen; only the dashboard's summary cell for that row is updated to current-state language (e.g., "Optuna RDB storage; IR-evaluation runs via `ir_measures`").
   - After applying option (a) or (b), the regenerated dashboard MUST satisfy the FR-7 grep gate without any exception for dashboard rows. If both options are impractical, STOP and escalate to the user — do not weaken AC-6 unilaterally.

6. **Run the merge-time grep gates** (per FR-7):
   ```bash
   # Basic gate
   grep -rn 'pytrec_eval\|pytrec-eval' . --exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=.git

   # Broader wire-form gate
   grep -rEn '(RelevanceEvaluator|ndcg_cut_|map_cut_|recip_rank|recall_[0-9]|\bP_[0-9])' . --exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=.git
   ```
   Both must match ONLY (matches the spec's FR-7 allowlist verbatim — no plan-level additions per cycle-1 F5 + F6):
   - `docs/00_overview/implemented_features/` (historical)
   - `docs/blog/` (dated historical)
   - `state.md` (historical entries; the new dated entry may name `pytrec_eval` once to reference "the library being replaced")
   - `backend/tests/unit/eval/test_scoring_parity.py` (parity test imports `pytrec_eval` by design)
   - `pyproject.toml` `[dependency-groups.dev]` line (per FR-4 — REQUIRED, not optional)
   - `pyproject.toml` `[[tool.mypy.overrides]]` block for `pytrec_eval` if AC-4c kept it
   - The Dockerfile comment if Story 1.7 outcome (a) reworded it to credit `ir_measures`' transitive backend
   - This `feature_spec.md` and `implementation_plan.md` (the spec/plan for this very feature — naturally names `pytrec_eval` as "the library being replaced")
   - **NOT** the MVP1_DASHBOARD.md (per cycle-1 F6 — the dashboard must regen cleanly; if the generator emits stale text, fix the generator per task 5 options (a)/(b))

7. **Update `state.md`** with a NEW dated entry describing the migration. Do NOT back-edit any existing entry. The new entry references the PR number, summarizes scope, and notes Alembic head unchanged.

**Definition of Done (DoD)**

- All modified files reworded (verified by spot-check of each).
- `python scripts/build_mvp1_dashboard.py` runs cleanly; the regenerated MVP1_DASHBOARD.md is committed.
- Basic `pytrec_eval|pytrec-eval` grep gate returns only allowlist matches (AC-6).
- Broader wire-form grep gate (`RelevanceEvaluator|ndcg_cut_|map_cut_|recip_rank|recall_[0-9]|\bP_[0-9]`) returns only allowlist matches (AC-6 extended).
- `state.md` has a new dated entry (AC-11).
- `make lint` passes (any new doc + comment changes pass ruff format).
- Final full-suite run: `make test-unit && make test-integration && make test-contract && make typecheck && make lint` — all green.

---

## UI Guidance

**No UI changes in this migration.** Two UI source-of-truth COMMENTS are reworded (`ui/src/components/studies/create-study-modal.tsx:60`, `ui/src/__tests__/components/studies/k-ignored.test.ts:4`) but these are comment-only changes — no element inventory, no markup change, no behavior change. No new tooltips. No new glossary keys. No new dropdowns or filters.

**No legacy behavior parity table** — no user-facing component >100 LOC is being deleted or migrated in this plan.

**Enumerated value contracts (§7.4 of spec):** unchanged. The `objective.metric` and `objective.k` allowlists (`SUPPORTED_METRICS`, `SUPPORTED_K_VALUES`) are byte-identically preserved by FR-1. The frontend's hardcoded option arrays at `create-study-modal.tsx` continue to match the backend source. No grep audit required because no allowlist values are added, removed, or changed.

---

## 3) Testing workstream

The migration adds 2 new test files and extends 3 existing assertions; existing tests must pass without source edits.

### 3.1 Unit tests
- Location: `backend/tests/unit/`
- Scope: scoring layer (pure functions), no DB
- Tasks:
  - [ ] **NEW** `backend/tests/unit/eval/fixtures/parity_qrels_run.py` — fixed (qrels, run) fixture per FR-2 with 4 edge cases (Story 1.2).
  - [ ] **NEW** `backend/tests/unit/eval/test_scoring_parity.py` — 30 parametrized parity cases + per-query shape parity (Stories 1.2 + 1.4).
  - [ ] **EXISTING** `backend/tests/unit/eval/test_scoring.py` — passes unchanged (Story 1.3 verification).
  - [ ] **EXISTING** `backend/tests/unit/eval/test_scoring_metric_tokens.py` — passes unchanged (Story 1.3).
  - [ ] **EXISTING** `backend/tests/unit/eval/test_qrels_loader.py` — passes unchanged (Story 1.3).
- DoD:
  - [ ] All 30 parametrized parity cases pass with `abs(a - b) < 1e-6` (AC-2).
  - [ ] Per-query shape parity passes (FR-3 / C2-F4 contract).
  - [ ] Negative-case + positive-case strict-regex tests pass (AC-3).

### 3.2 Integration tests
- Location: `backend/tests/integration/`
- Scope: DB-backed read regression + extended leakage assertion
- Tasks:
  - [ ] **EXTEND** `backend/tests/integration/test_run_trial_per_query_persistence.py:111` — leakage assertion extended to forbid `ir_measures` PascalCase reprs (Story 1.5).
  - [ ] **NEW** `backend/tests/integration/test_existing_row_read_compat.py` — pre-migration JSONB shape regression (AC-12 / Story 1.5).
  - [ ] **EXISTING** `backend/tests/integration/fixtures/handbuilt_qrels.py:75` — docstring rewording only (Story 1.8).
- DoD:
  - [ ] Existing-row read regression passes — `fetch_study_confidence` hydrates the pre-migration JSONB shape (AC-12).
  - [ ] No leakage assertion regressed.

### 3.3 Contract tests
- Location: `backend/tests/contract/`
- Scope: response-shape envelope assertions + leakage assertion
- Tasks:
  - [ ] **EXTEND** `backend/tests/contract/test_trial_row_shape.py:113` — strict regex check + negative/positive parametrized cases per AC-3 (Story 1.5).
  - [ ] **REWORD** `backend/tests/contract/test_studies_api_contract.py` line 156 docstring (Story 1.6) — `pytrec_eval semantics` → `ir_measures`-equivalent or library-neutral. **No assertion change** — the existing INSUFFICIENT_JUDGMENT_OVERLAP tests at lines ~218–240 are structural-only (assert the error-code literal appears in `studies.py` source + assert source-presence ordering of error codes). No message substring is pinned today (verified 2026-05-22).
- DoD:
  - [ ] The strict-regex assertion is substantive (negative cases fail, positive cases pass — AC-3 enumeration).
  - [ ] `studies.py:313` operator-visible error message renamed and the `test_studies_api_contract.py:156` docstring reworded; existing structural assertions (`INSUFFICIENT_JUDGMENT_OVERLAP` literal + ordering) still pass without modification (AC-7).

### 3.4 E2E tests
- **N/A.** No UI flow changes. The error-toast text change in the create-study modal is a string update that's verified at the contract layer (the modal displays whatever the API returns; the API string change is contract-tested).

### 3.5 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `backend/tests/unit/eval/test_scoring.py` | Pinned metric values (hand-computed) | many | No change needed — Story 1.3 must keep values identical via parity. If any value drifts, that's a Q4 resolution moment (Story 1.4 task 3). |
| `backend/tests/unit/eval/test_scoring_metric_tokens.py` | `_translate_metric_name` ValueError paths | several | No change needed — Story 1.3 preserves all ValueError paths. |
| `backend/tests/unit/eval/test_qrels_loader.py` | Empty-dict on unknown id | 1 | No change needed — loader unchanged. |
| `backend/tests/contract/test_trial_row_shape.py:113` | Leakage assertion | 1 | EXTENDED (Story 1.5). |
| `backend/tests/contract/test_studies_api_contract.py:156` | Docstring `pytrec_eval semantics` | 1 | Docstring REWORDED (Story 1.6). Existing assertions are structural-only — no substring of the message field is pinned, so the source string change at `studies.py:313` does NOT require an assertion update. |
| `backend/tests/integration/test_run_trial_per_query_persistence.py:111` | Leakage assertion | 1 | EXTENDED (Story 1.5). |
| `backend/tests/benchmarks/test_scoring_perf.py` | Warm-call timing | 1 | Compared before/after for Q5 resolution (Story 1.4 task 5). Not a default-gate test. |
| `backend/tests/integration/test_pagination.py:264` | `Trial(...)` constructor in test helper | 1 | No change — uses user-facing token shape already. |
| `backend/tests/integration/test_sort_pagination.py:419` | `Trial(...)` constructor | 1 | No change. |
| `backend/app/services/test_seeding.py:127,142` | `"p@10"` literal | 2 | FIXED inline (**Story 1.5 task 0** — moved from Story 1.6 per cycle-1 F7) → `"precision@10"`. |

### 3.5 Migration verification

**N/A** — no schema change, no Alembic migration in this plan. The Alembic head remains at `0015_trials_per_query_metrics` (unchanged).

### 3.6 CI gates

- [ ] `make test-unit` (includes new parity + shape tests)
- [ ] `make test-integration` (includes new existing-row regression)
- [ ] `make test-contract` (includes extended leakage assertion; the `test_studies_api_contract.py` docstring is reworded but no assertion changes — see Story 1.6)
- [ ] `make typecheck` (mypy strict)
- [ ] `make lint` (ruff)
- [ ] `cd ui && pnpm typecheck && pnpm lint` (the 3 UI source-of-truth comment changes don't change types but the strict TS config must still pass)
- [ ] **NEW gate** — `grep -rn 'pytrec_eval\|pytrec-eval'` returns only allowlist matches (FR-7 / AC-6).
- [ ] **NEW gate** — broader wire-form grep returns only allowlist matches (FR-7).
- [ ] `docker build .` succeeds (AC-10).

---

## 4) Documentation update workstream

### 4.0 Core context files

**`state.md`** — REQUIRED update (per AC-11):
- [x] New dated entry added describing the migration (Story 1.8 task 7). Existing entries NOT back-edited.

**`architecture.md`** — REQUIRED update (Story 1.8):
- [x] Line 131 — `eval/ pytrec_eval scoring` → `eval/ ir_measures scoring`.

**`CLAUDE.md`** — REQUIRED update (Story 1.8):
- [x] Lines 15 + 29 — both `pytrec_eval` mentions → `ir_measures`. The umbrella-spec link convention stays; only the library name changes.

### 4.1 Architecture docs

- [x] `docs/01_architecture/optimization.md` — title + 10 mentions + code-example block (Story 1.8).
- [x] `docs/01_architecture/tech-stack.md` — line 41.
- [x] `docs/01_architecture/system-overview.md` — line 76.
- [x] `docs/01_architecture/README.md` — line 21.
- [x] `docs/01_architecture/data-model.md` — lines 52 + 231.
- [x] `docs/01_architecture/cluster-lifecycle.md` — line 159.

### 4.2 Product docs

- [x] `docs/02_product/mvp1-user-stories.md` — line 40.
- [x] `docs/02_product/planned_features/feat_study_baseline_trial/idea.md` — sibling coordination, line 56.
- [x] `docs/02_product/planned_features/feat_auto_followup_studies/idea.md` — sibling coordination, line 47.
- [x] `docs/00_overview/product/relevance-copilot-spec.md` — umbrella spec, 11 mentions including subsection rewrite.

### 4.3 Runbooks

**No runbook changes.** This migration adds no new operational procedure; no new debugging recipe; no new failure mode. The error-message rewording is a one-line string change that surfaces in the existing create-study modal error toast.

### 4.4 Security docs

**No security-docs changes.** No new data leaves the cluster on each scoring call (the scoring layer is local-only). No new secret, no new key handling, no new auth path.

### 4.5 Quality docs

**No quality-docs changes.** Coverage gate unchanged at 80%. The test-layer convention is unchanged — just adding more tests at the unit + integration + contract layers.

### 4.6 Guides (tenant-facing)

- [x] `docs/08_guides/workflows-overview.md` — lines 123 + 277.
- [x] `ui/public/docs/workflows-overview.md` — same content, lock-step.
- [x] `ui/public/guides/05_import_judgments_and_calibrate/script.md` — line 6.
- [x] `ui/public/guides/06_create_and_monitor_study/script.md` — line 8.
- [x] `ui/public/guides/06_create_and_monitor_study/metadata.json` — line 26.

### 4.7 Auto-regenerated

- [x] `docs/00_overview/MVP1_DASHBOARD.md` — Story 1.8 task 5 runs `python scripts/build_mvp1_dashboard.py`.

**Documentation DoD**

- [ ] All grep gates clean (Story 1.8 DoD).
- [ ] `state.md` has new dated entry (Story 1.8 DoD).
- [ ] `architecture.md` line 131 updated.
- [ ] `CLAUDE.md` lines 15 + 29 updated.
- [ ] MVP1_DASHBOARD.md regenerated and committed.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

- **None planned.** This is a substrate migration. No code consolidation, no abstraction extraction, no policy centralization.

### 5.2 Planned refactor tasks

- None.

### 5.3 Refactor guardrails

- Behavioral parity proven by the 30-case parity test + per-query shape test + existing-row read regression (Stories 1.4 + 1.5).
- Lint and typecheck stay green at each commit (Story-by-Story Verification Gate §10).
- No expansion of product scope per spec §3 "Out of scope" — `confidence.py`, `ranx`, paired-bootstrap, Fisher randomization all stay out.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `ir-measures>=0.4.3` on PyPI | Story 1.1 | Implemented (PyTerrier team, MIT, actively maintained) | If PyPI unavailable at install time, `uv sync` fails with a normal dep-resolution error. |
| `pytrec-eval>=0.5` on PyPI | Story 1.1 (dev-group), Stories 1.2 + 1.4 (parity test) | Implemented (abandoned but still installable on Python 3.13) | If the C extension fails to compile on a new Python version (3.14+), the parity gate eventually goes dark. Acceptable future-drag per spec §19 + decision log. |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `ir_measures` routes some metric through a non-`pytrec_eval` provider with subtly different values | M | H — parity gate fails, PR blocked | Story 1.4 task 3 — bounded outcomes (a)/(b)/(c)/(d) per spec §19 Q4. Default response: use documented provider-forcing API; if none, bump `ir_measures` version. |
| `ir_measures.iter_calc()` emits a different per-query universe than `pytrec_eval.RelevanceEvaluator.evaluate()` for qrel-only / run-only edge cases | M | H — per-query shape parity fails, persisted JSONB key set on edge cases would change | Story 1.4 task 4 — default to filtering `iter_calc` output to match `pytrec_eval`'s universe (option (a) under task 4). Escalate to user only if option (a) is impractical. |
| `ir_measures` doesn't ship `py.typed`, mypy strict fails | L | M — Story 1.1 needs a mypy override | Story 1.1 task 1 verifies empirically; adds the override if needed. |
| Performance regression > 10% | L | M — Q5 resolution flags it as a blocker | Story 1.4 task 5 measures empirically; if regression > 10%, escalate to user with the benchmark numbers. |
| Dashboard regen surfaces historical `pytrec_eval` mention from `infra_optuna_eval` row, fails AC-6 grep gate | M | M — requires generator fix, NOT an allowlist exception | Story 1.8 task 5 inspects the regenerator; if historical text leaks, **fix the generator** (per Story 1.8 task 5 options (a)/(b)) so the regenerated dashboard is current-state clean. **Do not** add a dashboard allowlist exception — the spec's FR-7 allowlist is fixed and the plan cannot weaken AC-6 (per plan cycle-2 C2-F4 + Story 1.8 task 5 lock). If neither option (a) nor (b) is practical, STOP and escalate. |
| Pre-commit hook (Conventional Commits + ruff + mypy) rejects a doc-only commit | L | L | All commits follow Conventional Commits format; doc-sweep commit prefix is `docs(eval):`. |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| `ir_measures` import fails at worker boot | Bad install / missing C extension | Worker process exits at import time; Compose healthcheck fails | Rebuild image; verify install logs |
| Parity test fails on one metric | Provider routing divergence | CI blocks the PR; impl-plan author follows §19 Q4 bounded outcomes | Use documented forcing API OR bump `ir_measures` version |
| Per-query shape parity fails | `iter_calc` emits different qid universe | CI blocks the PR | Apply Story 1.4 task 4 option (a) — filter to match legacy universe |
| Existing-row read regression fails | Pre-migration JSONB row hydration breaks | CI blocks the PR | Inspect: did `objective_metric_key` change? Did `confidence.py` change unexpectedly? The migration claim "no-migration / no-backfill" is invalidated; STOP and escalate. |
| Dockerfile change breaks build | gcc/g++/python3-dev wrongly dropped when transitive C ext still resolves | `docker build .` fails | Revert Story 1.7 change; verify Q3 outcome was correct |
| `pytrec-eval` dev dep fails to install in CI | C extension can't compile against the CI Python version (e.g., Python 3.14+ with no wheels) | Parity gate cannot run → CI blocks the PR | Mitigation: file `chore_pytrec_eval_dev_dep_removal` idea per spec §19 Decision log; either swap the parity gate to a different comparison library OR retire it. Until then, the PR cannot merge unless the parity gate runs. |
| `ir_measures` transitive dependency has license-incompatible package | `uv tree` shows a non-Apache-2.0-compatible package (e.g., GPL) | PR blocked at Q5 resolution | Mitigation: repin `ir_measures` to a version without that transitive OR escalate to user. Do not merge under a license-incompatible dependency. |

---

## 7) Sequencing and parallelization

### Suggested sequence

Strict sequential — every story builds on the prior one:

1. Story 1.1 — pyproject.toml (deps in place)
2. Story 1.2 — parity test skeleton (test infra in place, skipped)
3. Story 1.3 — scoring.py rewrite (core change; existing tests still pass)
4. Story 1.4 — parity test activated (the gate fires for the first time)
5. Story 1.5 — leakage assertions extended + existing-row regression
6. Story 1.6 — operator-visible error message at `studies.py:313` + docstring rewording (the `p@10` inline fix moved to Story 1.5 task 0 per cycle-1 F7)
7. Story 1.7 — Dockerfile conditional update
8. Story 1.8 — full doc/comment sweep + dashboard regen + final grep gates

### Parallelization opportunities

None. The migration is one PR (per spec) and each story depends on its predecessor:
- Story 1.2 needs Story 1.1's `ir_measures` install to be importable.
- Story 1.3 needs Story 1.2's fixture to exist (for `make test-unit` not to error on Story 1.3's reuses of fixture imports).
- Story 1.4 needs Story 1.3's scoring.py to be migrated.
- Stories 1.5 + 1.6 + 1.7 + 1.8 each modify different files but inspect the post-1.4 state.

Sub-tasks WITHIN Story 1.8 (the doc sweep) can be parallelized — different files, no cross-dependencies. The impl-execute agent can edit 3-5 doc files per batched tool call.

---

## 8) Rollout and cutover plan

- **Rollout stages:** N/A — single-PR migration. No staging deploy in MVP1 (per CLAUDE.md / state.md). Merge to main → local dev stacks get the new behavior on next `make up`.
- **Feature flag strategy:** None. The migration is atomic at the library-import level — no flag would gain anything.
- **Migration/cutover steps:** None. No schema change, no data backfill.
- **Reconciliation/repair strategy:** N/A.

---

## 9) Execution tracker

### Current sprint
- [ ] Story 1.1 — pyproject.toml (add ir-measures, move pytrec-eval to dev, audit mypy overrides)
- [ ] Story 1.2 — parity test fixture + skeleton
- [ ] Story 1.3 — scoring.py rewrite with locked metric-object mapping
- [ ] Story 1.4 — parity test activation + per-query shape + Q5 perf benchmark
- [ ] Story 1.5 — leakage assertions extended + existing-row read regression
- [ ] Story 1.6 — studies.py:313 message + `test_studies_api_contract.py:156` docstring rewording (no assertion change; no `p@10` fix here — moved to Story 1.5 task 0)
- [ ] Story 1.7 — Dockerfile conditional update (per Q3 resolution)
- [ ] Story 1.8 — full doc sweep + MVP1_DASHBOARD regen + grep gates clean

### Blocked items

None at planning time.

### Done this sprint

—

---

## 10) Story-by-Story Verification Gate (Agent Checklist)

Before marking any story complete, the executing engineer or agent must attach evidence for:

- [ ] Files created/modified match story scope (`New files` / `Modified files` tables)
- [ ] Public API of `scoring.py` is byte-identical (verified by `git diff backend/app/eval/scoring.py` showing only internal-logic + docstring changes, no signature changes)
- [ ] Persisted JSONB key shape preserved (verified by AC-3's strict regex + the existing-row regression in Story 1.5)
- [ ] Tests pass at the layers touched:
  - [ ] `make test-unit` (always required)
  - [ ] `make test-integration` (required from Story 1.5 onward)
  - [ ] `make test-contract` (required from Story 1.5 onward)
- [ ] Typecheck + lint green (`make typecheck`, `make lint`)
- [ ] After Story 1.4: 30 parity cases + per-query shape test PASS, Q4 resolution recorded in commit
- [ ] After Story 1.7: `docker build .` succeeds, Q3 resolution recorded in commit
- [ ] After Story 1.8: both grep gates clean, MVP1_DASHBOARD.md regenerated and committed, `state.md` has new dated entry

---

## 11) Plan consistency review

### 11.1 Spec ↔ plan endpoint count

Spec §8.1 endpoint surface: **N/A** — no new endpoints. Plan endpoint count: **0**. Match.

### 11.2 Spec ↔ plan error code coverage

Spec §8.5 error code catalog: "No new error codes. The existing `INSUFFICIENT_JUDGMENT_OVERLAP` code (owned by `feat_study_preflight_overlap_probe`) is unchanged in code value, status, and retryability — only its message text is reworded."

Plan: Story 1.6 rewords the source message at `studies.py:270` + `:313`; the existing contract test at `test_studies_api_contract.py` is structural-only (asserts the error-code literal + ordering — no message substring pinned), so only a docstring rewording is needed there. No new error code introduced. Match.

### 11.3 Spec ↔ plan FR coverage

| Spec FR | Plan story | Verified |
|---|---|---|
| FR-1 scoring.py swap + mapping + aggregate-via-iter | Story 1.3 | ✓ |
| FR-2 parity test (permanent CI gate, 30 cases) | Stories 1.2 + 1.4 | ✓ |
| FR-3 no wire-form leakage + per-query shape parity | Story 1.4 (shape) + Story 1.5 (leakage) | ✓ |
| FR-4 pyproject.toml (runtime + dev split + mypy overrides) | Story 1.1 | ✓ |
| FR-5 studies.py:313 operator-visible message + contract docstring rewording | Story 1.6 | ✓ (no message substring is pinned today; existing structural contract assertions are unchanged) |
| FR-6 Dockerfile conditional gcc/g++/python3-dev | Story 1.7 | ✓ |
| FR-7 doc sweep + dashboard regen + broader grep gate | Story 1.8 | ✓ |

All 7 FRs covered by at least one story. No FR orphaned. No story without an FR backing.

### 11.4 Story internal consistency

- No endpoint tables in any story (no new endpoints), so no schema field mismatch possible.
- DoD assertions reference the spec's AC-1 through AC-12 by ID.
- New files don't overlap across stories: Story 1.2 creates `parity_qrels_run.py` + `test_scoring_parity.py`; Story 1.5 creates `test_existing_row_read_compat.py`. No conflict.
- Modified files: scoring.py is touched only by Story 1.3. studies.py is touched only by Story 1.6. Contract test files are touched by Stories 1.5 + 1.6 (but at different assertions). pyproject.toml is touched only by Story 1.1. Dockerfile only by Story 1.7. No file ownership conflict.

### 11.5 Test file count and assignment

Test files in the testing workstream:
- `backend/tests/unit/eval/fixtures/parity_qrels_run.py` → Story 1.2
- `backend/tests/unit/eval/test_scoring_parity.py` → Story 1.2 (creation) + Story 1.4 (activation)
- `backend/tests/integration/test_existing_row_read_compat.py` → Story 1.5
- Extended `backend/tests/contract/test_trial_row_shape.py` → Story 1.5
- Extended `backend/tests/contract/test_studies_api_contract.py` → Story 1.6
- Extended `backend/tests/integration/test_run_trial_per_query_persistence.py` → Story 1.5

Every test file is assigned to exactly one story (or two stories for the parity test, which is correct — Story 1.2 creates skipped, Story 1.4 unskips).

### 11.6 Gate arithmetic

No epic/phase gates — single-epic, single-PR. The Story-by-Story Verification Gate (§10) is the sole gate; it lists the per-story conditions.

### 11.7 Open questions resolved

| Q | Resolved in | How |
|---|---|---|
| Q1 | Story 1.8 | Reword the migration docstring; recommendation locked. |
| Q2 | Story 1.1 task 1 | Empirical `find py.typed` recipe; conditional mypy override. |
| Q3 | Story 1.7 task 1 | Empirical `pip show pytrec_eval` recipe; Dockerfile change driven by output. |
| Q4 | Story 1.4 task 3 | Run parity; if pass → no action; if fail → bounded outcomes per spec §19 Q4. |
| Q5 | Story 1.1 task 3 + Story 1.4 task 5 | `uv tree` license audit + perf benchmark before/after. |

### 11.8 Frontend UI Guidance completeness

**Not required for this plan** — no frontend stories with element inventories. The 3 UI source-of-truth comment changes (`create-study-modal.tsx:60`, `k-ignored.test.ts:4`, `types.ts:1889`) are pure comment edits with no JSX or behavior change; they live in Story 1.8.

### 11.9 Enumerated value contract audit

**No new enumerated values added.** `SUPPORTED_METRICS` and `SUPPORTED_K_VALUES` are preserved byte-identically by FR-1. The frontend option arrays at `create-study-modal.tsx` continue to match the backend source. No grep audit required.

### 11.10 Audit-event coverage

**N/A** — pre-MVP2. RelyLoop's `audit_log` table arrives at MVP2 per `docs/01_architecture/data-model.md`. No audit events to instrument.

### 11.11 Persistence scope consistency

**N/A** — no `localStorage` / `sessionStorage` usage in this migration.

### 11.12 Plan ↔ codebase verification

| Claim | Verified by | Status |
|---|---|---|
| `backend/app/eval/scoring.py` exists and is the only `import pytrec_eval` site | grep — only one source-tree match at line 22 | Verified |
| `pyproject.toml` line 47 has `pytrec-eval>=0.5` | Read pyproject.toml | Verified |
| `pyproject.toml` lines 156–158 have the `pytrec_eval` mypy override | Read pyproject.toml | Verified |
| Dockerfile lines 44–54 have the gcc/g++/python3-dev install | Read Dockerfile | Verified |
| `backend/app/api/v1/studies.py` line 270 inline comment AND line 313 error-message string both mention `pytrec_eval` | Read studies.py:260–320 | Verified — TWO mentions (idea said one) |
| `backend/app/services/test_seeding.py` lines 127 + 142 contain `"p@10"` literals | grep test_seeding.py | Verified — two occurrences |
| MVP1_DASHBOARD.md lines 64 + 134 contain actual `pytrec_eval` mentions (not false positives) | Re-read snippet during cycle-2 patch | Verified |
| `backend/tests/contract/test_trial_row_shape.py:113` has the leakage assertion | Read test_trial_row_shape.py around line 113 | Verified (spot-check during impl-plan) |
| `backend/tests/integration/test_run_trial_per_query_persistence.py:111` has the leakage assertion | Read test_run_trial_per_query_persistence.py around line 111 | Verified |
| `backend/workers/trials.py` has TWO write paths to `trials.metrics` (lines 446–447 happy path + line 178 idempotency-replay) | Read trials.py 150–230 + 440–450 | Verified |

### 11.13 Infrastructure path verification

| Path | Verified by | Status |
|---|---|---|
| `backend/tests/unit/eval/` is the unit-test directory | `ls backend/tests/unit/eval/` (verified during draft) | Verified |
| `backend/tests/integration/` for the new existing-row test | Sibling tests like `test_run_trial_per_query_persistence.py` live there | Verified |
| `migrations/alembic.ini` (NOT `backend/alembic`) — but no migration in this plan | — | N/A |

---

## 12) Definition of plan done

- [x] Every FR is mapped to stories/tasks/tests/docs updates (§1 + §11.3).
- [x] Every story includes New files, Modified files, Tasks, and DoD. (No endpoints/schemas to include — no new API surface.)
- [x] Test layers (unit/integration/contract) are explicitly scoped (§3). E2E is documented as N/A.
- [x] Documentation updates across docs/01-08 + ui/public are planned and owned (§4).
- [x] Lean refactor scope and guardrails are explicit — §5 documents "none planned".
- [x] No epic/phase gates beyond the Story-by-Story Verification Gate (§10) — single-PR migration.
- [x] Story-by-Story Verification Gate is included (§10).
- [x] Plan consistency review (§11) has been performed with no unresolved findings.

---

## Cross-model review log

GPT-5.5 reviewed this plan in 3 cycles per the impl-plan-gen workflow Step 6/7:

- **Cycle 1: 10 findings (9 accepted, 1 rejected).** Accepted + applied: F2 score()-universe-filter restructure, F3 per-query value parity in tests, F4 mandatory digest assertion in AC-12, F5 umbrella-spec rewrite without naming pytrec_eval, F6 dashboard clean-regen (no allowlist exception), F7 test_seeding.py p@10 fix moved to Story 1.5, F8 §3.3 docstring-only consistency, F9 grep gate against `pytest.mark.skip` in test_scoring_parity.py, F10 two new failure-mode rows. Rejected with cited counter-evidence: F1 (`_translate_metric_name("unknown")` → `requires an @<k> cut` is the EXISTING behavior; both old and new code preserve identical triggering inputs — verified at scoring.py:74-78).
- **Cycle 2: 4 findings (all accepted).** C2-F1 universe-filter tightening (`if qrels.get(qid) and run.get(qid)` for empty-inner-dict edge cases), C2-F2 test_seeding.py reassignment + ordering consistency across summary sections, C2-F3 stale "contract substring" references purged, C2-F4 dashboard regen mitigation aligned with Story 1.8's no-allowlist-exception stance.
- **Cycle 3: 1 finding (accepted).** C3-F1 added symmetric `run[q] = {}` parity fixture case to mirror the `qrels[q] = {}` case from C2-F1.
- **Convergence:** 10 → 4 → 1 (monotonically decreasing). Plan approved for impl-execute.
