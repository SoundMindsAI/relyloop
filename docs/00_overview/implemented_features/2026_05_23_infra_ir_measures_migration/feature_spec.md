# Feature Specification — Replace `pytrec_eval` with `ir_measures` for IR metric scoring

**Date:** 2026-05-22
**Status:** Draft
**Owners:** soundminds.ai (initial maintainer)
**Related docs:**
- [`idea.md`](./idea.md)
- [`docs/01_architecture/optimization.md`](../../../01_architecture/optimization.md)
- [`docs/01_architecture/tech-stack.md`](../../../01_architecture/tech-stack.md)
- Upstream library: [terrierteam/ir_measures](https://github.com/terrierteam/ir_measures)

---

## 1) Purpose

Replace the unmaintained `pytrec_eval` library with `ir_measures` as the IR-evaluation engine sitting behind [`backend/app/eval/scoring.py`](../../../../backend/app/eval/scoring.py). `pytrec_eval`'s canonical repo at `cvangysel/pytrec_eval` last shipped a commit on 2020-09-07 with zero GitHub releases since; the package still installs and computes correct numbers, but every Python release going forward is a roll-the-dice for C-extension wheel availability, every `trec_eval` upstream bug report has no maintainer to file against, and every Apple-Silicon / arm64 first-build pays the gcc-compile tax. `ir_measures` (PyTerrier team, active) wraps `pytrec_eval` + `gdeval` + `judged_as_relevant` behind a provider interface, exposes a typed metric-object DSL (`nDCG@10`, `AP@5`, `RR`, etc.), and supports the per-query iteration shape (`iter_calc()`) that the next confidence wave (paired-comparison + Fisher randomization) needs.

- **Problem:** Direct dependency on an abandoned-upstream C-extension library with single-maintainer bus-factor risk and no path forward for Python 3.14+.
- **Outcome:** `scoring.py` imports `ir_measures` rather than `pytrec_eval`; the user-facing `score(qrels, run, metrics) -> ScoreResult` signature is unchanged; the wire forms (`ndcg@10`, `map@5`, `mrr`, `map`) the rest of the codebase consumes are unchanged; every parity-tested metric value matches `pytrec_eval` to 6 decimal places. `pyproject.toml` no longer pins `pytrec_eval` directly.
- **Non-goal:** Replacing the pure-Python `bootstrap_ci_95()` / runner-up-gap / late-trial-stddev / convergence helpers in [`backend/app/domain/study/confidence.py`](../../../../backend/app/domain/study/confidence.py). Those helpers consume user-facing per-query metric dicts (already keyed by `ndcg@10` etc., not pytrec_eval wire forms) and do not import the library directly — they are unaffected by this migration.

## 2) Current state audit

### Existing implementations

| File | What it does | Notes |
|---|---|---|
| [`backend/app/eval/scoring.py`](../../../../backend/app/eval/scoring.py) (~195 LOC) | The **only direct call site** of `import pytrec_eval`. Owns `_translate_metric_name()` (user-facing → wire form), `objective_metric_key()` (used by `confidence.py` + studies endpoint + worker), `SUPPORTED_METRICS` + `SUPPORTED_K_VALUES` frozensets (the source-of-truth allowlist for `studies.objective.metric` / `studies.objective.k`), and `score(qrels, run, metrics) -> ScoreResult`. | The `evaluator = pytrec_eval.RelevanceEvaluator(qrels, wire_set); evaluator.evaluate(run)` call lives on line 176; re-keying back to user-facing names lives at lines 180–192. The translation table maps `ndcg@k` → `ndcg_cut_k`, `map@k` → `map_cut_k`, `precision@k` → `P_k`, `recall@k` → `recall_k`, `map` → `map`, `mrr` → `recip_rank`. |
| [`backend/app/eval/qrels_loader.py`](../../../../backend/app/eval/qrels_loader.py) | Loads judgments from the `judgments` table into the dict-of-dicts shape `pytrec_eval` (and `ir_measures`) consume. Docstring at line 45 says "an empty dict… which `pytrec_eval` treats as a no-op". | The shape `{query_id: {doc_id: rating}}` is identical between `pytrec_eval` and `ir_measures` per the [ir_measures README](https://github.com/terrierteam/ir_measures) — no loader change needed. |
| [`backend/app/db/models/trial.py:19,83`](../../../../backend/app/db/models/trial.py) | `per_query_metrics` JSONB column docstring references `pytrec_eval` scores from `scoring.py::score()`. Two mentions: module-level docstring (line 19) **and** the column-level docstring on line 83. | Both docstrings describe a contract that survives this migration — the persisted shape is keyed by user-facing tokens (`ndcg@10`, `map@10`, `mrr`, plain `map`), NOT the wire forms. |
| [`backend/app/api/v1/schemas.py:534`](../../../../backend/app/api/v1/schemas.py) | `ObjectiveSpec` docstring says `k` is required "per pytrec_eval semantics: those metrics are computed at a cutoff rank". | The cutoff semantics are an IR convention, not a `pytrec_eval` invention — rewording without losing the constraint. |
| [`backend/app/api/v1/studies.py:270,313`](../../../../backend/app/api/v1/studies.py) | Two error-message strings reference `pytrec_eval`: (a) inline comment at 270 ("pytrec_eval scores 0 on every trial by construction"), (b) user-facing error message at 313 ("pytrec_eval will likely score 0 on every trial"). Both are part of `JUDGMENT_TARGET_MISMATCH` / `INSUFFICIENT_JUDGMENT_OVERLAP` handlers. | **The user-facing error message at 313 is wire-visible to operators** AND it is **currently pinned by a contract-test substring assertion** in `backend/tests/contract/test_studies_api_contract.py` (verified by grep). Architecturally, the contract is the `error_code` + `retryable` fields per `api-conventions.md`; in practice the test-enforced substring makes the message text part of what the PR must atomically update. Both must move in lock-step. |
| [`migrations/versions/0015_trials_per_query_metrics.py:17`](../../../../migrations/versions/0015_trials_per_query_metrics.py) | Docstring says the persisted column is keyed by user-facing names "NOT the pytrec_eval wire forms". | Historical migration — see §15. Rewording vs. leaving alone is a decision (see §19 Q1). |
| [`backend/app/domain/study/confidence.py`](../../../../backend/app/domain/study/confidence.py) | Imports `objective_metric_key` from `scoring.py` but **does NOT import `pytrec_eval` directly.** `bootstrap_ci_95()` at line 247 consumes a list of floats; the per-query dict is keyed by user-facing tokens. | **No code change required**, including no rewording — confidence.py doesn't name the library. |
| `pyproject.toml:47` | Direct pin `pytrec-eval>=0.5`. | Drop and replace with `ir-measures>=0.4.3`. |
| `pyproject.toml:156-158` | `[[tool.mypy.overrides]]` block setting `ignore_missing_imports = true` for module `pytrec_eval`. | `ir_measures` likely ships type hints (see §19 Q2); drop the override if confirmed, otherwise repoint to `ir_measures`. |
| [`Dockerfile`](../../../../Dockerfile) stage-2, lines 44–54 | Installs `gcc`, `g++`, `python3-dev` headers so `pytrec_eval`'s C extension can compile on first install (no prebuilt wheels). The deps stage is discarded; runtime is slim. | Conditional change — depends on whether `ir_measures` resolves a transitive C-extension backend (see §19 Q3). |

### Doc-rewrite inventory (current-state docs that name `pytrec_eval`)

Verified via `grep -rn 'pytrec_eval\|pytrec-eval'` on `main` HEAD (2026-05-22). This list is **canonical** for the migration — the idea file's list is a subset; the additional files below were missed and are required.

| Doc | Lines | Treatment |
|---|---|---|
| [`README.md`](../../../../README.md) | 9 | Update — current-state project README. |
| [`CLAUDE.md`](../../../../CLAUDE.md) | 15, 29 | Update both mentions. |
| [`architecture.md`](../../../../architecture.md) | 131 | Update — "eval/ pytrec_eval scoring + Optuna runtime helpers". |
| [`release-notes-v0.1.0-draft.md`](../../../../release-notes-v0.1.0-draft.md) | 12 | Update — release notes for the not-yet-tagged v0.1.0 / v0.2.0 cycle. |
| [`docs/00_overview/relyloop-spec.md`](../../../00_overview/relyloop-spec.md) | 12, 155, 688, 690, 692–693, 711, 2192, 2302, 2513, 2658, 2722 (~11 mentions) | Update — durable umbrella spec, NOT a historical artifact. Includes the "Engine: pytrec_eval everywhere" subsection (lines 688–693) that needs reframing as the provider-abstracted engine choice. |
| [`docs/01_architecture/optimization.md`](../../../01_architecture/optimization.md) | 1 (title), 3, 15, 48, 50, 52–53, 69, 76, 87, 90, 176 (~10 mentions) | Update — **the canonical IR-evaluation architecture page**, including the code example block at lines 87–90. Title `# Optimization (Optuna + pytrec_eval)` becomes `# Optimization (Optuna + ir_measures)`. |
| [`docs/01_architecture/tech-stack.md`](../../../01_architecture/tech-stack.md) | 41 | Update — IR evaluation row in the stack table. |
| [`docs/01_architecture/system-overview.md`](../../../01_architecture/system-overview.md) | 76 | Update — component table row. |
| [`docs/01_architecture/README.md`](../../../01_architecture/README.md) | 21 | Update — directory readme cross-references `optimization.md`. |
| [`docs/01_architecture/data-model.md`](../../../01_architecture/data-model.md) | 52, 231 | Update — `judgments` consumer pointer + `per_query_metrics` description. |
| [`docs/01_architecture/cluster-lifecycle.md`](../../../01_architecture/cluster-lifecycle.md) | 159 | Update — "Wire up Optuna's RDBStorage + pytrec_eval" cluster-lifecycle step. |
| [`docs/02_product/mvp1-user-stories.md`](../../../02_product/mvp1-user-stories.md) | 40 | Update — US-7 narrative ("nDCG@10, MAP, and P@10"). |
| [`docs/08_guides/workflows-overview.md`](../../../08_guides/workflows-overview.md) | 123, 277 | Update — tenant-facing operator guide. |
| [`ui/public/docs/workflows-overview.md`](../../../../ui/public/docs/workflows-overview.md) | 123, 277 | Update — runtime-served mirror of the same doc; both must move in lock-step. |
| [`ui/public/guides/05_import_judgments_and_calibrate/script.md`](../../../../ui/public/guides/05_import_judgments_and_calibrate/script.md) | 6 | Update. |
| [`ui/public/guides/06_create_and_monitor_study/script.md`](../../../../ui/public/guides/06_create_and_monitor_study/script.md) | 8 | Update. |
| [`ui/public/guides/06_create_and_monitor_study/metadata.json`](../../../../ui/public/guides/06_create_and_monitor_study/metadata.json) | 26 | Update — `caption` field; same content shape as `script.md`. |
| [`ui/src/components/studies/create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx) | 60 | Update — `// Source-of-truth: backend/app/eval/scoring.py:32 (metric → pytrec_eval token …)` source-of-truth comment. |
| [`ui/src/__tests__/components/studies/k-ignored.test.ts`](../../../../ui/src/__tests__/components/studies/k-ignored.test.ts) | 4 | Update — matching source-of-truth comment. |
| [`ui/src/lib/types.ts`](../../../../ui/src/lib/types.ts) | 1889 | Update — `pytrec_eval semantics` comment. |
| [`docs/00_overview/MVP1_DASHBOARD.md`](../../../00_overview/MVP1_DASHBOARD.md) | 64, 134 | **Auto-generated** — no manual edit. Regen ([`scripts/build_mvp1_dashboard.py`](../../../../scripts/build_mvp1_dashboard.py)) will pick up the planned-feature folder + spec changes. |

**Historical artifacts — explicitly leave alone:**
- [`state.md`](../../../../state.md) — add a new dated entry describing this migration when it lands; do NOT back-edit existing entries.
- Anything under `docs/00_overview/implemented_features/` — every implemented-features folder is frozen at shipping date. Includes the `infra_optuna_eval` implementation plan, the `feat_pr_metric_confidence` spec/plan, etc.
- Dated blog posts under `docs/blog/` — datestamped at writing time; same convention as implemented_features. (Mentions of `pytrec_eval` in `2026-05-22-elevator-pitch-search-platform.md` and others are point-in-time references.)

### Code-comment / docstring sweep (current-state, beyond the doc-rewrite list above)

Verified via the same grep. Update each in lock-step with the scoring.py rewrite; treat as part of the same PR so the codebase doesn't ship with rotted references.

| File | Lines | Treatment |
|---|---|---|
| [`backend/app/eval/scoring.py`](../../../../backend/app/eval/scoring.py) | 1, 4, 22, 52, 156, 176 | Module docstring + `_translate_metric_name` notes + `score()` docstring + the `import pytrec_eval` itself + the `RelevanceEvaluator` call. Most are the structural code change, not a comment-only sweep. |
| [`backend/app/eval/qrels_loader.py`](../../../../backend/app/eval/qrels_loader.py) | 45 | Reword "treats as a no-op" docstring. |
| [`backend/app/db/models/trial.py`](../../../../backend/app/db/models/trial.py) | 19, 83 | Two docstrings — module-level (line 19) and column-level on `per_query_metrics` (line 83). |
| [`backend/app/api/v1/schemas.py`](../../../../backend/app/api/v1/schemas.py) | 534 | `ObjectiveSpec` k-cutoff comment. |
| [`backend/app/api/v1/studies.py`](../../../../backend/app/api/v1/studies.py) | 270, 313 | TWO mentions, NOT one (idea understates). Line 270 is an inline comment; line 313 is part of a user-facing error message string. |
| [`migrations/versions/0015_trials_per_query_metrics.py`](../../../../migrations/versions/0015_trials_per_query_metrics.py) | 17 | See §19 Q1 — historical migration; decision is whether to reword the docstring or leave the historical reference. |
| `backend/tests/unit/eval/test_scoring.py` | 4, 143, 156 | Reword. |
| `backend/tests/unit/eval/test_scoring_metric_tokens.py` | 1, 82 | Reword. |
| `backend/tests/unit/eval/test_qrels_loader.py` | 53 | Reword. |
| `backend/tests/contract/test_trial_row_shape.py` | 6, 109, 113 | **Behavioral assertion**: line 113 asserts `metrics` keys do NOT start with `pytrec_eval` wire prefixes. The assertion itself must move to checking for the *new* wire-form leakage surface (the `ir_measures` metric-object `repr` strings) — see FR-2 / AC-3. Reword the docstrings on lines 6 + 109 accordingly. |
| `backend/tests/contract/test_studies_api_contract.py` | 156 | Reword. |
| `backend/tests/integration/test_run_trial_per_query_persistence.py` | 53, 111, 119 | Reword; the assertion on line 111 also lives under the "no pytrec_eval wire-form leakage" contract — update to assert no `ir_measures`-shaped leakage. |
| `backend/tests/integration/fixtures/handbuilt_qrels.py` | 75 | Reword `build_zero_scoring_hits_response` helper docstring. |
| `backend/tests/benchmarks/test_scoring_perf.py` | 56 | Reword the warm-up comment. |
| [`backend/app/services/test_seeding.py`](../../../../backend/app/services/test_seeding.py) | 127, 142 | **Inline bug fix (bundled per C2-F5).** Both occurrences of `"p@10"` in seed `metrics` dicts → `"precision@10"` to match the canonical user-facing token emitted by `score()` + `objective_metric_key()`. Pre-existing inconsistency surfaced by AC-3's strict regex; the 2-character fix is well under the inline-fix budget. |

### Reader inventory — every code path that reads the user-facing token keys

Verified via `grep -rn '\.metrics\b\|\.per_query_metrics\b\|\.primary_metric\b\|objective_metric_key' backend/app backend/workers` (2026-05-22). Every reader below consumes either `primary_metric` (scalar float, unaffected) or `metrics` / `per_query_metrics` JSONB keyed by user-facing tokens. FR-1's signature-preservation + FR-3's key invariant guarantee these readers continue to work without source edits.

| Reader | File:line | What it reads | Why preserved |
|---|---|---|---|
| Trial list endpoint serialization | [`backend/app/api/v1/studies.py:551,566-567`](../../../../backend/app/api/v1/studies.py) | `t.primary_metric`, `t.metrics` (JSONB) | API response shape; user-facing tokens flow straight to wire. Preserved by FR-3. |
| Trial pagination + sort | [`backend/app/db/repo/trial.py:127-154`](../../../../backend/app/db/repo/trial.py) | `Trial.primary_metric` (scalar) | Scalar comparison; unaffected. |
| "Best trial" lookup | [`backend/app/db/repo/trial.py:224,234`](../../../../backend/app/db/repo/trial.py) | `func.max(Trial.primary_metric)` | Scalar aggregate; unaffected. |
| Confidence orchestrator | [`backend/app/domain/study/confidence.py:568,570,609,612`](../../../../backend/app/domain/study/confidence.py) | `winner_trial.primary_metric`, `winner_trial.per_query_metrics`, `runner_up_trial.per_query_metrics` | Calls `objective_metric_key()` to derive lookup key (preserved by FR-1). |
| Confidence service | [`backend/app/services/study_confidence.py:59,66,83-91`](../../../../backend/app/services/study_confidence.py) | Same as above | Same. |
| Digest worker — top trials | [`backend/workers/digest.py:318,632`](../../../../backend/workers/digest.py) | `t.primary_metric` | Scalar. |
| Orchestrator — cancel-streak | [`backend/workers/orchestrator.py:360`](../../../../backend/workers/orchestrator.py) | `Trial.status, Trial.primary_metric` | Scalar. |
| `objective_metric_key()` callers | [`backend/app/eval/scoring.py:106`](../../../../backend/app/eval/scoring.py) (definition); [`backend/app/domain/study/confidence.py:40,556`](../../../../backend/app/domain/study/confidence.py); [`backend/app/services/study_confidence.py:30,85`](../../../../backend/app/services/study_confidence.py); plus 2 test files | Function returns user-facing token string. | Preserved verbatim by FR-1. |

### Write-surface audit — every code path that WRITES user-facing token keys

Verified via `grep -rn 'metrics\s*=\|per_query_metrics\s*=\|Trial(' backend/app backend/workers migrations` (2026-05-22). There are **two production write paths**, both flowing through helpers that this migration preserves:

| Write site | File:line | What it writes | Invariant boundary |
|---|---|---|---|
| **Happy-path scoring write** | [`backend/workers/trials.py:446-447`](../../../../backend/workers/trials.py) | `metrics=scored["aggregate"]`, `per_query_metrics=scored["per_query"]` — full dicts straight from `score()`. | `score()`'s re-keying step (preserved by FR-1) — re-keys `ir_measures` metric-object outputs back to user-facing tokens before returning. |
| **Idempotency-replay write** | [`backend/workers/trials.py:178`](../../../../backend/workers/trials.py) (COMPLETE path); lines 191, 203, 507 emit `metrics={}` for FAIL/PRUNED paths (no token contract to enforce on an empty dict) | `metrics = {objective_key: snapshot.value}` — synthesized single-key dict when Optuna already has the result cached (no re-run of search/score). | `objective_key = objective_metric_key(study.objective)` — function returns user-facing token (preserved by FR-1). |

Both paths therefore funnel through user-facing tokens via FR-1's preserved API. No additional write surfaces exist in production code. **Test-only Trial constructors** ([`backend/tests/integration/test_pagination.py:264`](../../../../backend/tests/integration/test_pagination.py), [`backend/tests/integration/test_sort_pagination.py:419`](../../../../backend/tests/integration/test_sort_pagination.py)) write hand-rolled dicts that match the user-facing token shape — no AC-3 conflict.

**Inline fix bundled with this PR (per GPT-5.5 cycle-2 C2-F5):** [`backend/app/services/test_seeding.py:127,142`](../../../../backend/app/services/test_seeding.py) currently writes `metrics={"ndcg@10": ..., "map": ..., "p@10": ...}` — the `"p@10"` literal is a pre-existing inconsistency with the canonical user-facing token (`precision@10`) that `score()` emits. Left alone, it would fail AC-3's strict regex. The fix is two character-substitutions (`p@10` → `precision@10`); bundled inline per CLAUDE.md "Inline-fix vs idea-file rubric" (≤50 LOC, no new tests beyond what AC-3 already runs, same subsystem). The fix is captured in §15 doc/code update list.

### Navigation and link impact

None. No URL paths change. No frontend route changes.

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `backend/tests/unit/eval/test_scoring.py` | Asserts metric values + re-keying | unchanged | Pass unchanged (public API preserved). Comments reworded. |
| `backend/tests/unit/eval/test_scoring_metric_tokens.py` | Asserts `_translate_metric_name` raises on bad input | unchanged | Pass unchanged — the translation table simplifies but `ValueError` paths are preserved. |
| `backend/tests/unit/eval/test_qrels_loader.py` | Loader returns empty dict on unknown id | unchanged | Pass unchanged. |
| `backend/tests/contract/test_trial_row_shape.py` | Asserts no `pytrec_eval` wire prefixes leak into `trials.metrics` | **updated assertion** | The "no wire-form leakage" contract moves from "no `ndcg_cut_`/`P_`/`recip_rank`/`map_cut_`/`recall_` keys" to "no `ir_measures` metric-object `repr` strings (e.g. `nDCG@10`-style PascalCase tokens) AND the existing pytrec_eval prefix check is preserved (since `ir_measures` may use pytrec_eval as a transitive backend whose wire names could still surface if re-keying is wrong)". Line 113's assertion expression itself widens; the test stays. |
| `backend/tests/integration/test_run_trial_per_query_persistence.py` | Same "no wire-form leakage" assertion at integration layer | **updated assertion** | Same as above. |
| `backend/tests/benchmarks/test_scoring_perf.py` | Per-call timing for `score()` | unchanged (modulo possible delta) | Should pass unchanged; the benchmark numbers may shift slightly under `ir_measures`. The benchmark is not part of the default test layer (marked `@pytest.mark.benchmark`) so no CI gate impact. |

### Existing behaviors affected by scope change

- **Behavior:** `pyproject.toml` direct pin on `pytrec-eval>=0.5`.
  - Current: pinned; `uv sync` installs the C extension via gcc.
  - New: dropped; `ir-measures>=0.4.3` pinned instead. `pytrec_eval` may remain transitively (resolves at impl-plan time — Q3).
  - Decision needed: No — locked.
- **Behavior:** `[[tool.mypy.overrides]]` for `pytrec_eval`.
  - Current: `ignore_missing_imports = true` for module `pytrec_eval`.
  - New: if `ir_measures` ships type hints, drop the override entirely. If it doesn't, repoint the override to `ir_measures` (or both, if `pytrec_eval` remains a transitive backend that's still nominally importable).
  - Decision needed: Yes (Q2) — empirical, resolved at impl-plan time.
- **Behavior:** Dockerfile stage-2 toolchain install.
  - Current: installs `gcc`/`g++`/`python3-dev`.
  - New: stays as-is if `ir_measures` resolves a transitive `pytrec_eval` C extension; can be dropped if no transitive C extension is needed.
  - Decision needed: Yes (Q3) — empirical, resolved at impl-plan time. **Do NOT drop speculatively.**
- **Behavior:** `_translate_metric_name()` returning wire strings.
  - Current: returns strings like `"ndcg_cut_10"` to pass into `pytrec_eval.RelevanceEvaluator`.
  - New: returns `ir_measures` metric *objects* per the locked FR-1 mapping table — `nDCG@10`, `AP@10`, `AP` (plain), `P@10`, `R@10`, `RR`. Uncut `nDCG` / `P` / `R` are NEVER returned because the user-facing uncut forms remain invalid (the existing "requires an @<k> cut" `ValueError` paths are preserved). These objects are suitable to pass into `ir_measures.iter_calc()`.
  - Decision needed: No — locked.

---

## 3) Scope

### In scope

1. Replace `pytrec_eval` with `ir_measures` in [`backend/app/eval/scoring.py`](../../../../backend/app/eval/scoring.py) — preserve the public `score(qrels, run, metrics) -> ScoreResult` signature exactly; preserve `SUPPORTED_METRICS` / `SUPPORTED_K_VALUES` / `objective_metric_key()`; rewrite `_translate_metric_name()` to return `ir_measures` metric objects instead of wire strings.
2. Update [`pyproject.toml`](../../../../pyproject.toml) — drop `pytrec-eval>=0.5`, add `ir-measures>=0.4.3`, conditionally drop the `pytrec_eval` mypy override (per §19 Q2 resolution).
3. Add **parity test** at `backend/tests/unit/eval/test_scoring_parity.py` that runs both libraries against a fixed (qrels, run) fixture and asserts identical values to 6 decimal places for every valid `(metric, k)` pair in `SUPPORTED_METRICS × (SUPPORTED_K_VALUES ∪ {None})` per FR-2's per-metric k-rules — exactly 30 parametrized cases. Verifies per-query SHAPE parity (same outer qids, same inner metric keys per query, same handling of empty-overlap / qrel-only / run-only queries) per FR-3. The test is **a permanent CI gate**, kept active by adding `pytrec-eval>=0.5` to `[dependency-groups.dev]` (FR-4) so both libs remain reachable in the test environment indefinitely.
4. Update the "no wire-form leakage" assertions in `test_trial_row_shape.py:109-113` and `test_run_trial_per_query_persistence.py:111` to cover both the legacy `pytrec_eval` wire prefixes AND the new `ir_measures` metric-object `repr` shapes.
5. Doc-rewrite sweep across all current-state docs and code comments listed in §2 — both backend and frontend (UI source-of-truth comments).
6. Update the **user-visible error message** in `studies.py:313` (`INSUFFICIENT_JUDGMENT_OVERLAP` handler) — this is wire-visible to operators.
7. Conditionally update [`Dockerfile`](../../../../Dockerfile) stage-2 (per §19 Q3 resolution).

### Out of scope

- Replacing the pure-Python `bootstrap_ci_95()` / runner-up-gap / late-trial-stddev / convergence helpers in [`backend/app/domain/study/confidence.py`](../../../../backend/app/domain/study/confidence.py). They consume user-facing per-query metric dicts (already keyed by `ndcg@10`, etc.) and do not import the library directly.
- Adding ERR@k or any other metric not currently in `SUPPORTED_METRICS`. The metric allowlist is unchanged.
- Adding paired-bootstrap / Fisher randomization / paired-comparison helpers. Those are queued for the next confidence wave (referenced in idea §"Relationship to other work") and will sit on `ir_measures.iter_calc()` once that primitive is the per-query iteration surface; this migration unblocks but does not deliver them.
- Updating any doc under `docs/00_overview/implemented_features/` or dated blog posts in `docs/blog/`. Those are point-in-time historical artifacts (per CLAUDE.md `state.md` convention: "Don't back-edit them").
- Replacing the qrels-loader implementation. The dict-of-dicts shape is identical between `pytrec_eval` and `ir_measures`.
- Changing the persisted `trials.metrics` / `trials.per_query_metrics` JSONB keys. The user-facing tokens (`ndcg@10`, `map@10`, `mrr`, plain `map`) are the durable contract — this migration must preserve them byte-identically (FR-1c).
- Adding `ir-measures[ranx]` as an extra. `ranx` remains available as a fast-follow if the hand-rolled paired-bootstrap grows uncomfortable; not added speculatively.
- Multi-PR phasing. The whole migration ships in one PR (see §3 Phase boundaries).

### API convention check

- **Endpoint prefix convention:** `/api/v1/<resource>` for business endpoints; unprefixed for `/healthz`. Verified in [`backend/app/api/v1/`](../../../../backend/app/api/v1/). **This migration adds zero endpoints.**
- **Router namespace for this feature's endpoints:** N/A — no new routes.
- **HTTP methods for CRUD:** N/A.
- **Non-auth error envelope shape:** existing operator-visible error message at `studies.py:313` lives inside the `_err()` helper which emits the standard envelope `{ "detail": { "error_code": "INSUFFICIENT_JUDGMENT_OVERLAP", "message": "<human>", "retryable": false } }` per [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md). The migration only changes the `message` text inside that envelope; envelope shape unchanged.
- **Auth error shape:** N/A in MVP1–3.

### Phase boundaries (if multi-phase)

**Single-phase.** The migration is one PR — scoring rewrite + parity test + pyproject change + doc sweep + UI comment sweep all together. Rationale:
- The doc sweep would create grep-divergence (some docs say `ir_measures`, some say `pytrec_eval`) if landed separately — operators reading docs would see inconsistency.
- The parity test depends on both libraries being installable; running it once at PR-merge time is sufficient and there's no reason to defer.
- The UI source-of-truth comments at `create-study-modal.tsx:60` and `k-ignored.test.ts:4` reference `scoring.py:32` directly — leaving the comments stale while scoring.py moves means the next reader doesn't know which file is the source of truth.

No `phase2_idea.md` is required — there is only one phase.

## 4) Product principles and constraints

- **Public API of `scoring.py` is frozen.** Callers (the `run_trial` worker + tests + `confidence.py`) must require zero source edits. `score()`, `objective_metric_key()`, `SUPPORTED_METRICS`, `SUPPORTED_K_VALUES`, `ScoreResult`, `Qrels`, `Run` all preserve their existing signatures and shapes.
- **Persisted JSONB shape is frozen.** `trials.metrics` and `trials.per_query_metrics` JSONB columns must continue to be keyed by the user-facing tokens currently in production — `ndcg@10`, `map@10`, `precision@10`, `recall@10`, `mrr`, plain `map`. Any drift here breaks `confidence.py`'s `objective_metric_key()` consumer + the digest worker + the PR-body renderer + the trials API + any read-back from historical rows (every trial in production was persisted with these keys).
- **Six-decimal parity is a hard gate.** The migration is invalid if `ir_measures` and `pytrec_eval` disagree on any metric for the fixed fixture by ≥ 1e-6.
- **No `pytrec_eval` wire-form leakage outside `scoring.py`.** Same invariant as today — extended to also forbid `ir_measures` metric-object `repr` shapes leaking past the function. The contract is that everything outside `scoring.py` sees only user-facing tokens.
- **Forward-only.** No DEPRECATED markers, no compatibility shims, no "fall back to pytrec_eval if ir_measures fails". Single migration; complete cutover.

### Anti-patterns

- **Do not** preserve `import pytrec_eval` as a fallback path inside `scoring.py`. The migration is a cutover. A "try ir_measures; except: fall back to pytrec_eval" branch turns the parity test into a no-op and locks in the abandoned-upstream risk we're trying to escape.
- **Do not** invent a new persisted metric-key shape (e.g., `nDCG@10` PascalCase). The `trials.metrics` keys are a durable contract; rows that were persisted yesterday must still be readable tomorrow. `ir_measures.iter_calc()` yields `Metric` namedtuples whose `measure` field is the metric *object* — `str(measure)` produces PascalCase like `nDCG@10`. The migration must re-key back to the user-facing lowercase token (`ndcg@10`) before returning from `score()`.
- **Do not** rely on `ir_measures` calling `pytrec_eval` transitively as "good enough" without verifying parity. The PyTerrier team may route some metrics through `gdeval` or another backend that produces subtly different values for tie-handling or normalization. The fixed-fixture parity test is the only way to know.
- **Do not** drop the Dockerfile gcc/g++/python3-dev install speculatively. If `ir_measures` resolves `pytrec_eval` transitively, those headers are still required at install time. The verification recipe (`pip install ir-measures && pip show pytrec_eval`) settles this empirically at impl-plan time.
- **Do not** edit anything under `docs/00_overview/implemented_features/` or dated blog posts. Those are frozen historical artifacts; any back-edit muddies the project's "what shipped when" narrative.
- **Do not** ship the rewrite without also updating `studies.py:313`. That string is operator-facing in the `INSUFFICIENT_JUDGMENT_OVERLAP` error response — leaving it stale means production-grade incident messages still reference the abandoned library.

## 5) Assumptions and dependencies

- **Dependency:** [terrierteam/ir_measures](https://github.com/terrierteam/ir_measures) (`ir-measures>=0.4.3` on PyPI).
  - Why required: Becomes the IR-evaluation engine behind `scoring.py`.
  - Status: Implemented + actively maintained (PyTerrier team).
  - Risk if missing: N/A — the library is the substrate this feature swaps onto. If PyPI is unreachable at install time, `uv sync` fails with a normal dependency-resolution error.
- **Dependency:** `pytrec_eval` module via the transitively-resolved `pytrec-eval-terrier` (no explicit dev pin).
  - Why required: The parity test (FR-2) is a **permanent CI gate**, not a one-shot pre-merge check. It does `import pytrec_eval` and asserts value-equivalence against `ir_measures.iter_calc()` on every CI run.
  - Status: Provided transitively by `ir-measures>=0.4.3`'s dependency on `pytrec-eval-terrier v0.5.10` (the actively-maintained PyTerrier fork that publishes to the `pytrec_eval` module name). No explicit dev-group pin is needed; the original FR-4 plan was to add one, but it was REMOVED after CI revealed the abandoned `pytrec-eval` distribution conflicts with `pytrec-eval-terrier` at install time (both ship the same `pytrec_eval` module name; install order determines which one wins, and CI happened to pick the abandoned one, leaving `ir_measures` without its cut-aware-metric backend). See the post-push fix commit and the §19 Decision log entry below.
  - Risk if missing: Parity gate goes dark. Acceptable future-drag: when `pytrec-eval-terrier` eventually fails to install (e.g., Python 3.14+ with no wheels available), the parity test gracefully `xfail`s or skips; at that point a `chore_pytrec_eval_dev_dep_removal` idea file is filed and the gate retires. We accept this future drag today in exchange for the permanent live parity gate.
- **Dependency:** No external service / no LLM / no operator-environment change. Purely an in-process library swap.

## 6) Actors and roles

- **Primary actor:** the `run_trial` worker (an in-process consumer of `scoring.py::score()`). No human actor.
- **Role model:** N/A — RelyLoop is single-tenant + no auth through MVP3 per [`docs/01_architecture/tech-stack.md` §"Canonical release matrix"](../../../01_architecture/tech-stack.md).
- **Permission boundaries:** N/A.

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — audit_log lands at MVP2.

## 7) Functional requirements

### FR-1: `scoring.py` swaps to `ir_measures`

- Requirement:
  - The system **MUST** replace the `import pytrec_eval` statement in [`backend/app/eval/scoring.py`](../../../../backend/app/eval/scoring.py) with `import ir_measures` (and explicit metric-object imports as needed: `from ir_measures import nDCG, AP, RR, P, R`).
  - The system **MUST** preserve the public function signatures `score(qrels: Qrels, run: Run, metrics: set[str]) -> ScoreResult`, `objective_metric_key(objective: dict[str, object]) -> str`, and the type aliases `Qrels = dict[str, dict[str, int]]`, `Run = dict[str, dict[str, float]]`, `ScoreResult = TypedDict("ScoreResult", {"aggregate": dict[str, float], "per_query": dict[str, dict[str, float]]})` byte-identically.
  - The system **MUST** preserve the values of `SUPPORTED_METRICS = frozenset({"ndcg", "map", "precision", "recall", "mrr"})` and `SUPPORTED_K_VALUES = frozenset({1, 3, 5, 10, 20, 50, 100})`.
  - The system **MUST** rewrite `_translate_metric_name(user_facing: str)` to return an `ir_measures` *metric object* per the mapping table below, rather than a `pytrec_eval` wire string. The function's `ValueError` paths for malformed tokens (`"unknown metric base"`, `"k value is not an integer"`, `"k not in allowlist"`, `"metric does not accept an @<k> cut"`, `"requires an @<k> cut"`) **MUST** all be preserved with the same triggering inputs. In particular, uncut `ndcg`, `precision`, and `recall` **MUST** continue to raise the existing "requires an @<k> cut" error — no new "plain metric" path is opened up.

    **Locked metric-object mapping** (per `ir_measures` README; uses MIT-licensed naming: `AP` for average precision, `RR` for reciprocal rank, `P`/`R` for precision/recall):

    | User-facing token | `ir_measures` metric object | Notes |
    |---|---|---|
    | `ndcg@<k>` | `nDCG@<k>` | k ∈ `SUPPORTED_K_VALUES`; uncut `ndcg` still rejected. |
    | `map@<k>` | `AP@<k>` | k ∈ `SUPPORTED_K_VALUES`. |
    | `map` (plain) | `AP` | Full-recall MAP; matches `pytrec_eval`'s plain `map`. |
    | `precision@<k>` | `P@<k>` | k ∈ `SUPPORTED_K_VALUES`; uncut `precision` still rejected. |
    | `recall@<k>` | `R@<k>` | k ∈ `SUPPORTED_K_VALUES`; uncut `recall` still rejected. |
    | `mrr` | `RR` | k ignored; only the plain form is valid. |
  - The system **MUST** re-key the per-query and aggregate results back to user-facing tokens (`ndcg@10`, `map@10`, `precision@10`, `recall@10`, `mrr`, plain `map`) before returning from `score()` — the persisted JSONB keys do not change.
  - The system **MUST NOT** retain a `pytrec_eval` import-time fallback or runtime branch inside `scoring.py`.
  - **Aggregate-computation contract (per GPT-5.5 cycle-2 C2-F4).** The implementation **MUST** compute the `ScoreResult.aggregate` dict by iterating per-query results and taking the arithmetic mean over **exactly the qid set the per-query dict reports for each metric** — mirroring `score()`'s current logic at [`backend/app/eval/scoring.py:187-192`](../../../../backend/app/eval/scoring.py). The implementation **MUST NOT** delegate the aggregate to `ir_measures.calc_aggregate(...)` because that helper aggregates over `ir_measures`' provider-defined query universe, which may include qrel-only or run-only topics that `pytrec_eval`'s `RelevanceEvaluator(...).evaluate(run)` excludes today. The required pattern: build the per-query dict via `ir_measures.iter_calc([metric_obj, ...], qrels, run)` (yielding `Metric(query_id, measure, value)` tuples), filter/re-key to user-facing tokens, THEN compute the aggregate as `sum(values) / len(values)` over the per-query dict's metric-present entries.
- Notes: The translation table simplifies from "metric → wire string" to "metric → ir_measures object" — one entry per metric family, with `@k` applied via the `metric @ k` operator. The wire-form re-keying step that converts the engine's output back to the user-facing token shape is preserved as today. The deliberate avoidance of `calc_aggregate()` is the load-bearing design choice for FR-3's per-query shape parity — see FR-2 fixture's qrel-only / run-only / empty-overlap edge cases.

### FR-2: Parity test pins value-equivalence to 6 decimal places

- Requirement:
  - The system **MUST** ship `backend/tests/unit/eval/test_scoring_parity.py` (new file) that loads a fixed (qrels, run) fixture and asserts, for every valid `(metric, k)` pair in the parametrized cross of `SUPPORTED_METRICS × (SUPPORTED_K_VALUES ∪ {None})` (where the pairing respects the per-metric k-rules: `ndcg`/`precision`/`recall` require k; `map` accepts both; `mrr` ignores k → only `(mrr, None)` is parametrized), value-equivalence to 6 decimal places between:
    - The aggregate value emitted by **the migrated `score(qrels, run, {token})["aggregate"][token]`** (i.e., the function under test, which computes the aggregate via per-query iteration per FR-1's aggregate-computation contract — NOT via `ir_measures.calc_aggregate()`), AND
    - The aggregate value emitted by **`pytrec_eval.RelevanceEvaluator(qrels, {wire_set}).evaluate(run)` followed by the same mean-across-queries computation** the current `score()` performs (lines 187–192 of `scoring.py`).
    - Tolerance: `abs(a - b) < 1e-6`.
  - The parity test **MUST NOT** call `ir_measures.calc_aggregate()` directly — comparing `calc_aggregate()` to `pytrec_eval` would test whether `ir_measures`' native aggregate matches `pytrec_eval`, not whether the migrated `score()` is correct. The contract is that `score()`'s output is unchanged, so the test compares the new `score()` against the old `pytrec_eval`-based evaluation.
  - The system **MUST** parametrize over every valid `(metric, k)` pair so each individual case is independently observable in pytest output. The cross-product yields exactly **30 cases**: `ndcg × 7 k-values = 7`, `precision × 7 = 7`, `recall × 7 = 7`, `map × 7 + plain map = 8`, `mrr (plain) = 1` (mrr ignores k so any other k-value would be a duplicate).
  - The system **MUST** use the same fixture as the existing `test_scoring.py` (or a sibling fixture in `backend/tests/unit/eval/fixtures/`) so the inputs are diff-reviewable. Required fixture coverage: ≥ 8 queries, ≥ 5 docs each, mixed ratings (0/1/2/3), AND the following edge cases each represented by at least one query: (a) a query with no relevant docs (zero-score path), (b) a query in qrels with no matching docs in the run (qrel-only / missing-from-run), (c) a query in the run with no entry in qrels (run-only / unjudged), (d) a query whose run has no overlap at all with the qrels (the literal study2 scenario).
- Notes: The parity test runs **as a permanent CI gate**, not as a one-shot pre-merge check. To keep both libraries reachable in CI, this migration adds `pytrec-eval>=0.5` to `[dependency-groups.dev]` (FR-4) so the test environment can import both libs side-by-side even after `pytrec_eval` is no longer a runtime/`[project].dependencies` pin. Runtime images (the API + worker Compose services) no longer ship `pytrec_eval` directly — only `ir_measures` (which may resolve `pytrec_eval` transitively per §19 Q3). The parity test never runs against a runtime image.

### FR-3: No wire-form leakage (extended) + per-query shape parity

- Requirement:
  - The system **MUST** preserve the existing "no `pytrec_eval` wire-form leakage" assertions in `backend/tests/contract/test_trial_row_shape.py:113` and `backend/tests/integration/test_run_trial_per_query_persistence.py:111`.
  - The system **MUST** extend those assertions to also forbid `ir_measures`-shaped metric-object `repr` strings (PascalCase tokens like `nDCG@10`, `P@10`, `RR`, `AP@5`, `R@10`) from leaking into `trials.metrics` or `trials.per_query_metrics` JSONB.
  - The system **MUST** keep the persisted JSONB key set restricted to the existing user-facing tokens: `ndcg@<k>`, `map@<k>`, `map` (plain), `precision@<k>`, `recall@<k>`, `mrr` — for `k ∈ SUPPORTED_K_VALUES`.
  - **Per-query shape parity (added per GPT-5.5 cycle-1 F5).** The system **MUST** preserve the per-query result shape `score()` emits today:
    - Outer dict keys (`query_id`) **MUST** be exactly the set of queries `pytrec_eval`'s evaluator currently returns — every query that has at least one rated doc in `qrels` AND at least one entry in `run`, no more and no less.
    - For each outer key, inner dict keys **MUST** include exactly the same set of metric tokens as today's output — i.e., every requested metric token where the underlying backend produced a value. Today's logic at [`backend/app/eval/scoring.py:180-184`](../../../../backend/app/eval/scoring.py) conditionally omits a metric for a query when the wire-form key is absent from `raw_per_query[qid]`. The new implementation **MUST** maintain the same conditional-inclusion semantics — `ir_measures.iter_calc()` yielding fewer per-(qid, metric) tuples than `pytrec_eval`'s evaluator on the same input is a parity failure.
    - For each outer key, every present inner value **MUST** equal the `pytrec_eval`-emitted value to 1e-6.
  - Per-query shape parity is verified by the same parity test (FR-2 fixture extended with the four edge cases listed there) AND by a new integration test that loads a synthetic-but-realistic trial and asserts per-(qid, metric) tuple equality between the old and new implementations.
- Notes: This invariant is what makes `confidence.py::compute_outcome_summary` and `digest.py`'s prompt rendering work without per-metric translation. Any drift here cascades to incorrect per-query analytics on every existing study. `ir_measures.iter_calc()` returns `Metric(query_id, measure, value)` tuples that *may* omit pairs the caller didn't request, but its handling of edge cases (qrel-only-query, run-only-query, empty-overlap) needs explicit fixture-level pinning to confirm equivalence — see FR-2 fixture requirements.

### FR-4: `pyproject.toml` updates

- Requirement:
  - The system **MUST** remove `pytrec-eval>=0.5` from `[project].dependencies` and add `ir-measures>=0.4.3` in its place.
  - The system **MUST** add `pytrec-eval>=0.5` to `[dependency-groups.dev]` so the parity test (FR-2) can import both libraries side-by-side as a permanent CI gate. This pin is the parity-test infrastructure; it never ships into the runtime image because the Dockerfile installs only the `[project]` runtime deps via `uv sync --frozen --no-dev`.
  - The system **MUST** either remove the `[[tool.mypy.overrides]] module = "pytrec_eval"` block (if `ir_measures` ships type hints AND `pytrec_eval` is no longer directly imported) OR keep one repointed at `module = "ir_measures"` (if it doesn't ship type hints) OR keep both blocks (the existing `pytrec_eval` override AND a new `ir_measures` override) if both modules are imported anywhere (the parity test imports `pytrec_eval` even when scoring.py doesn't). Resolution at impl-plan time per Q2; spec-level constraint: the override set **MUST** match the actual import surface after the migration.
- Notes: `uv.lock` regenerates on `uv lock` — that's a normal side-effect, not a manual edit. Keeping `pytrec-eval>=0.5` as a permanent dev-group dependency means future Python/uv upgrades may eventually break it (the C extension has no Python-3.14+ wheels guaranteed); when that happens, the parity test gracefully becomes `xfail`-or-skip and a `chore_pytrec_eval_dev_dep_removal` idea file is filed. We accept this future drag in exchange for the live parity gate today.

### FR-5: Operator-visible string at `studies.py:313` is reworded

- Requirement:
  - The system **MUST** change the string `"pytrec_eval will likely score 0 on every trial"` in the `INSUFFICIENT_JUDGMENT_OVERLAP` error message (`backend/app/api/v1/studies.py:313`) to a wording that names `ir_measures` (or, equivalently, names the behavior without naming any library — e.g. `"every trial will score 0 on every metric"`).
  - The system **MUST** update the contract-test substring assertion in `backend/tests/contract/test_studies_api_contract.py` that currently pins the pre-migration text. The impl-plan author confirms the exact assertion location and updates it atomically with the source change.
- Notes: Architecturally, per [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md), the envelope contract is the `error_code` + HTTP status + `retryable` fields — the `message` field is free-text intended for human display. **In practice**, this repo's contract suite asserts on substrings of the message field for several error codes (a pre-existing pattern across `test_studies_api_contract.py`), so the message change is effectively a test-enforced contract for this PR. The atomic update of source + contract test is captured as a checklist item under §18. The `INSUFFICIENT_JUDGMENT_OVERLAP` error code itself, HTTP 422 status, and `retryable=false` field are all preserved unchanged.

### FR-6: Conditional Dockerfile change

- Requirement:
  - The system **MUST** verify at impl-plan time whether `ir_measures` keeps `pytrec_eval` as a transitive backend for the metrics in `SUPPORTED_METRICS × SUPPORTED_K_VALUES`. Verification recipe: `pip install ir-measures && pip show pytrec_eval` (or `uv tree | grep pytrec_eval` after a fresh `uv sync`).
  - If a C-extension backend is still resolved transitively, the [`Dockerfile`](../../../../Dockerfile) stage-2 install of `gcc` / `g++` / `python3-dev` (lines 44–54) **MUST** stay as-is, and the comment block at lines 44–48 explaining "pytrec_eval (added by infra_optuna_eval) ships as a sdist with NO prebuilt wheels…" **MUST** be reworded to credit `ir_measures` (or the actual transitive C-extension dependency) as the reason.
  - If no C-extension is resolved transitively, the system **MAY** drop the gcc/g++/python3-dev install block. The decision must cite the empirical verification.
- Notes: Saves the speculative "drop the install" mistake that would surface as a slow next-feature debug session.

### FR-7: Doc-rewrite sweep is complete

- Requirement:
  - The system **MUST** update every file in the doc-rewrite inventory in §2 ("Doc-rewrite inventory" table) AND every file in the code-comment / docstring sweep table.
  - The system **MUST** include an explicit story / task in the implementation plan for regenerating [`docs/00_overview/MVP1_DASHBOARD.md`](../../../00_overview/MVP1_DASHBOARD.md) via `scripts/build_mvp1_dashboard.py` so the dashboard's two existing `pytrec_eval` mentions (lines 64 + 134, verified by grep) are picked up by the rewrite. Without an explicit task, the dashboard regen is silently optional and the merge-time grep gate (below) will fail.
  - Verification gate at merge time: `grep -rn 'pytrec_eval\|pytrec-eval' .` on the working tree (excluding `node_modules`, `.venv`, `.git`) **MUST** return only:
    - Lines inside `docs/00_overview/implemented_features/` (historical),
    - Lines inside `docs/blog/` (dated historical),
    - Lines inside `state.md` (historical entries; the new state.md entry describing the migration may name `pytrec_eval` once to reference "the library being replaced"),
    - The parity-test file (`backend/tests/unit/eval/test_scoring_parity.py` — imports `pytrec_eval` for side-by-side comparison),
    - The `pyproject.toml` `[dependency-groups.dev]` line (per FR-4),
    - The Dockerfile comment IF it's reworded to explain `ir_measures`' transitive C-extension dependency (per FR-6).
  - **Expanded wire-form sweep (per GPT-5.5 cycle-1 F11).** The merge-time check **MUST** also verify that the legacy `pytrec_eval` wire-form terms are gone from live-state docs and comments. Run `grep -rEn '(RelevanceEvaluator|ndcg_cut_|map_cut_|recip_rank|recall_[0-9]|\\bP_[0-9])' . --exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=.git` and confirm every remaining match is inside the same allowlist as above (historical, dated, parity test, dependency-groups, Dockerfile). Specifically, code examples in [`docs/01_architecture/optimization.md`](../../../01_architecture/optimization.md) that show `pytrec_eval.RelevanceEvaluator(qrels, {"ndcg_cut_10", "map", "P_10"}).evaluate(run)` MUST be rewritten to the `ir_measures.calc_aggregate([nDCG@10, AP, P@10], qrels, run)` shape.
  - The system **MUST NOT** leave a single live-state doc, code comment, or UI source-of-truth annotation that names `pytrec_eval` OR cites a pytrec_eval wire-form metric token after the PR lands.
- Notes: The verification grep is itself part of the PR-time CI check. Spec §16 captures it as a release gate.

## 8) API and data contract baseline

### 8.1 Endpoint surface

**N/A.** This migration adds zero endpoints, changes zero request/response shapes (except the wire-string in the `INSUFFICIENT_JUDGMENT_OVERLAP` envelope's `message` field, which is a free-text field not part of the contract).

### 8.2 Contract rules

- The user-visible error message string in the `INSUFFICIENT_JUDGMENT_OVERLAP` envelope is a non-contractual `message` field per [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md) — the contract is the `error_code` + `retryable` fields, both unchanged.
- All other API contracts (`POST /api/v1/studies`, `GET /api/v1/studies/{id}`, `GET /api/v1/trials/...`, the digest endpoint, the proposal endpoints) are unchanged.

### 8.3 Response examples

**N/A** for new responses (none added). The `INSUFFICIENT_JUDGMENT_OVERLAP` envelope existing shape (which this migration rewords inside the `message` field) is documented in [`feat_study_preflight_overlap_probe/feature_spec.md`](../../../00_overview/implemented_features/2026_05_22_feat_study_preflight_overlap_probe/feature_spec.md). No change to status code (422), no change to `error_code` value, no change to `retryable` (false).

### 8.4 Enumerated value contracts

The wire-value enumerations consumed by the create-study flow (`objective.metric`, `objective.k`) are owned by `scoring.py`'s `SUPPORTED_METRICS` and `SUPPORTED_K_VALUES` frozensets:

| Field | Accepted values (exact) | Backend source of truth | Frontend call site(s) |
|---|---|---|---|
| `objective.metric` | `ndcg`, `map`, `precision`, `recall`, `mrr` | [`backend/app/eval/scoring.py`](../../../../backend/app/eval/scoring.py) — `SUPPORTED_METRICS` frozenset | Create-study modal Step 5 metric `<select>` ([`ui/src/components/studies/create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx)) |
| `objective.k` | `1`, `3`, `5`, `10`, `20`, `50`, `100` (required for ndcg/precision/recall; optional for map; ignored for mrr) | `SUPPORTED_K_VALUES` frozenset | Same modal Step 5 k `<select>` |

**This migration MUST preserve both frozensets' values byte-identically.** The frontend's hardcoded option arrays already match these via the source-of-truth comments at `create-study-modal.tsx:60` and `k-ignored.test.ts:4` (which this spec updates per §2's UI source-of-truth comment sweep).

### 8.5 Error code catalog

**No new error codes.** The existing `INSUFFICIENT_JUDGMENT_OVERLAP` code (owned by `feat_study_preflight_overlap_probe`) is unchanged in code value, status, and retryability — only its message text is reworded.

## 9) Data model and state transitions

**No data-model changes.** No new tables, no new columns, no migration, no `alembic_version` head bump.

The persisted shapes that this migration explicitly preserves:

- `trials.metrics` JSONB — keys are user-facing tokens (`ndcg@10`, `map@10`, `precision@10`, `recall@10`, `mrr`, plain `map`).
- `trials.per_query_metrics` JSONB — outer key is `query_id` (UUIDv7 string); inner dict keyed by the same user-facing tokens; value is `float` per-query score.

### Required invariants

- **JSONB key invariant:** Every key in `trials.metrics` and the inner dicts of `trials.per_query_metrics` MUST be in the set `{f"{metric}@{k}" for metric in {"ndcg","precision","recall"} for k in SUPPORTED_K_VALUES} | {f"map@{k}" for k in SUPPORTED_K_VALUES} | {"map", "mrr"}`. No `pytrec_eval` wire prefixes (`ndcg_cut_`, `P_`, `recip_rank`, `map_cut_`, `recall_`). No `ir_measures` PascalCase reprs (`nDCG@10`, `P@10`, `RR`, `AP@5`).
- **Value-equivalence invariant:** For any fixed (qrels, run, metric), the value emitted by the new `score()` MUST equal the value the old `score()` would have emitted to within 1e-6. Verified at PR-merge time by the parity test (FR-2).
- **Existing-row read invariant:** Every existing `trials` row in production was persisted with the user-facing token keys. After this migration, every existing row must still be readable by `confidence.py::compute_study_confidence` (which calls `objective_metric_key()` to derive the per-query lookup key). The contract preservation in FR-1 + FR-3 guarantees this — no row-rewrite, no backfill, no migration.

### State transitions

N/A — no state machines added or modified.

### Idempotency/replay behavior

N/A — no event-driven surfaces.

## 10) Security, privacy, and compliance

- **Threats:** None new. The migration is an in-process library swap.
- **Controls:** Same as today — `ir_measures` is an MIT-licensed open-source library on PyPI; no secrets, no network calls, no PII handling.
- **Secrets/key handling:** N/A.
- **Auditability:** `state.md` gains a new dated entry (per CLAUDE.md "After completing a task" convention) describing the migration: date, Alembic head (unchanged), test counts, parity result.
- **Data retention/deletion/export impact:** None.
- **Supply-chain note:** `ir_measures` adds one new pip dependency (`ir-measures`) plus its transitive set. Verify at impl-plan time that the transitive set (e.g., `cwl-eval`, `pandas` if it's a hard dep, etc.) is acceptable. No license-incompatible dependencies are expected — `ir_measures` itself is MIT.

## 11) UX flows and edge cases

### Information architecture

**N/A** — no UI route changes, no new pages, no new components. Two distinct categories of operator-visible change exist (per GPT-5.5 cycle-1 F8 — keep them disjoint mentally):

1. **Runtime API/UI behavior change (one surface):** The reworded error message inside the `INSUFFICIENT_JUDGMENT_OVERLAP` envelope (delivered as JSON to the create-study modal's error toast; verified at `studies.py:313`). This is what shows up live in the running app post-merge.
2. **Operator-visible documentation copy change (many surfaces):** The guide scripts at `/guide/05` + `/guide/06`, the workflows-overview docs at `/guide/workflows-overview` + the duplicate at `ui/public/docs/workflows-overview.md`, and the guide-06 caption in `metadata.json`. These are static markdown / JSON served by the UI from `ui/public/`. They do not change runtime behavior but they ARE what a tenant reads when learning the product. Listed under §15 documentation update requirements; release-notes copy should call them out.

### Tooltips and contextual help

**N/A** — no new UI elements. No glossary keys are added or modified. Existing glossary entries (`ui/src/lib/glossary.ts`) that reference IR metric semantics (`ndcg@10`, etc.) describe the semantics via the standard IR convention — they do not name `pytrec_eval`. Verified by grep on `ui/src/lib/glossary.ts` returning zero `pytrec` matches.

### Primary flows

1. **Operator creates a study.** Backend renders the search-space → enqueues `run_trial` jobs. The worker imports `scoring.py::score()`; under the hood, `score()` now uses `ir_measures` rather than `pytrec_eval`. Same `trials` rows persist, same `trials.metrics` keys, same `primary_metric` value, same digest, same PR body. Operator sees zero behavioral difference.
2. **Operator creates a study with insufficient judgment overlap.** Same flow up to the preflight probe at `studies.py:286`. The 422 envelope returns with the same `error_code` and `retryable` fields; the `message` text now says "ir_measures" instead of "pytrec_eval". The error toast in the create-study modal shows the updated text — visually the only operator-noticeable change in this whole migration.
3. **Operator reads a guide (`/guide/06/...`).** The guide-06 caption + script (currently mentioning "scores via pytrec_eval") now mentions "scores via ir_measures". Both `ui/public/guides/06_*/script.md` and `metadata.json` ship the rewording.

### Edge/error flows

- **`ir_measures` import fails at app boot.** Same failure mode as today's `pytrec_eval` import failure — the worker's process exits at import time, surfaced via the Compose healthcheck for the worker container. No new error path; same operator-recovery flow (rebuild image, retry).
- **Parity test fails on one metric.** Block the PR. The migration is invalid until the discrepancy is investigated. Most-likely cause: `ir_measures` routes the metric through a non-`pytrec_eval` backend (e.g., `gdeval`) with subtly different tie-handling. Mitigation: pin `ir_measures` to use the `pytrec_eval` provider for that metric specifically, or accept the discrepancy and document it.
- **`pytrec_eval` not resolvable in CI dev environment.** Permanent mitigation: `pytrec-eval>=0.5` lives in `[dependency-groups.dev]` (FR-4); the test environment always has it. The transitive question (whether `ir_measures` ALSO pulls it) is only relevant to Dockerfile decisions (FR-6 / Q3), not to parity-test viability.

## 12) Given/When/Then acceptance criteria

### AC-1: scoring.py imports ir_measures, not pytrec_eval

- Given the merged PR for this migration is on `main`.
- When `grep -n 'import pytrec_eval\|import ir_measures' backend/app/eval/scoring.py` runs.
- Then exactly one match returns and it is `import ir_measures` (or `import ir_measures` + explicit metric imports). Zero `import pytrec_eval` lines remain in `scoring.py`.
- Example values:
  - Input: `grep -n 'import pytrec_eval' backend/app/eval/scoring.py`
  - Expected: exit code 1 (no matches).

### AC-2: Parity test asserts ≤ 1e-6 value drift on every supported (metric, k)

- Given a fixed graded-qrels-and-run fixture in `backend/tests/unit/eval/fixtures/` (≥ 8 queries, mixed ratings).
- When `pytest backend/tests/unit/eval/test_scoring_parity.py -v` runs.
- Then every parametrized case passes; for each `(metric, k)` pair in `SUPPORTED_METRICS × (SUPPORTED_K_VALUES ∪ {None})`, `abs(ir_measures_aggregate - pytrec_eval_aggregate) < 1e-6`.
- Example values:
  - Input: pytest parametrize over `[("ndcg", 10), ("ndcg", 5), ("map", None), ("map", 10), ("precision", 10), ("recall", 10), ("mrr", None), …]`
  - Expected: zero failures, ≥ 30 parametrized cases (5 metrics × ~7 k values minus the invalid combinations).

### AC-3: trials.metrics keys are exactly the user-facing token set

- Given the test database after running `make test-integration`.
- When `backend/tests/contract/test_trial_row_shape.py` and `backend/tests/integration/test_run_trial_per_query_persistence.py` execute.
- Then every key in `trials.metrics` and every inner key in `trials.per_query_metrics` matches the **strict** regex `^(?:mrr|map|(?:ndcg|precision|recall|map)@(?:1|3|5|10|20|50|100))$` (i.e., user-facing tokens only, with uncut `ndcg` / `precision` / `recall` excluded per the k-rules in `objective_metric_key()`); no `pytrec_eval` wire prefixes (`ndcg_cut_`, `P_`, `recip_rank`, `map_cut_`, `recall_`); no `ir_measures` PascalCase reprs (`nDCG@`, `P@`, `RR`, `AP@`, `R@`).
- Negative cases (must be REJECTED by the assertion to prove the regex is strict — implementer adds explicit `pytest.raises(AssertionError)` cases for these):
  - `ndcg` (uncut — forbidden by `objective_metric_key()`),
  - `precision` (uncut — same),
  - `recall` (uncut — same),
  - `nDCG@10` (PascalCase `ir_measures` repr),
  - `P@10` (`ir_measures` repr),
  - `RR` (`ir_measures` repr),
  - `AP@5` (`ir_measures` repr),
  - `R@10` (`ir_measures` repr),
  - `ndcg_cut_10` (`pytrec_eval` wire),
  - `recip_rank` (`pytrec_eval` wire),
  - `map_cut_10` (`pytrec_eval` wire),
  - `P_10` (`pytrec_eval` wire),
  - `recall_10` (`pytrec_eval` wire).
- Positive cases (must be ACCEPTED): `ndcg@10`, `map@10`, `map`, `mrr`, `precision@10`, `recall@10`, `ndcg@5`, `precision@50`, `map@1`, etc. — every value in the cross-product `{ndcg|precision|recall} × {1,3,5,10,20,50,100}` plus `{map@1,...,map@100, map, mrr}`.
- Example values:
  - Input: any successful trial's `trials.metrics` JSONB.
  - Expected: every key matches the strict regex; the assertion is a substantive guard, not a tautology that passes on every string.

### AC-4a: pyproject.toml `[project].dependencies` has NO `pytrec-eval` pin

- Given the merged PR.
- When a section-aware TOML check runs (e.g., `python -c "import tomllib, sys; data = tomllib.load(open('pyproject.toml','rb')); deps = data['project']['dependencies']; assert not any(d.startswith('pytrec-eval') for d in deps), deps"`).
- Then exit code 0 — `pytrec-eval` is absent from the runtime dependency list.
- Example values:
  - Input: the python check above.
  - Expected: zero matches in `[project].dependencies`.

### AC-4b: pyproject.toml `[dependency-groups.dev]` does NOT contain `pytrec-eval`

**Superseded 2026-05-23** — see §19 Decision log. The original spec required an explicit `pytrec-eval>=0.5` dev-group pin, but CI revealed it conflicts with the transitively-resolved `pytrec-eval-terrier` (both publish to the same `pytrec_eval` module name). The pin was removed; the parity gate stays alive via the transitive backend.

- Given the merged PR.
- When the same section-aware check runs against the dev group (`data['dependency-groups']['dev']`).
- Then exit code 0 — `pytrec-eval` is ABSENT from `[dependency-groups.dev]`. The `pytrec_eval` module the parity test imports is provided by `pytrec-eval-terrier`, which `ir-measures>=0.4.3` pulls transitively as a runtime dependency (so the runtime image, the parity test, and the development environment all have `pytrec_eval` reachable without any explicit dev-group pin).
- Example values:
  - Input: `python -c "import tomllib; d=tomllib.load(open('pyproject.toml','rb')); assert not any(x.startswith('pytrec-eval') for x in d['dependency-groups']['dev'])"`
  - Expected: zero exit code.
  - Sanity check (positive parity-gate alive signal): `python -c "import pytrec_eval; assert hasattr(pytrec_eval, 'RelevanceEvaluator')"` exits 0.

### AC-4c: mypy overrides match the import surface

- Given the merged PR.
- When the impl-plan author inspects `[[tool.mypy.overrides]]` blocks in `pyproject.toml`.
- Then every `module = "<name>"` block matches an actual `import <name>` somewhere in the source tree (`scoring.py` imports `ir_measures`; the parity-test imports both `pytrec_eval` and `ir_measures`). Stale overrides for modules no longer imported anywhere in the codebase are removed.
- Example values:
  - Acceptable: an `ir_measures` override iff `ir_measures` doesn't ship type hints (resolved by Q2); a `pytrec_eval` override iff the parity test or any other source still imports it.
  - Unacceptable: a `pytrec_eval` override when nothing in the source tree imports `pytrec_eval`.

### AC-5: ir-measures direct pin exists

- Given the merged PR.
- When `grep -nE '^\s*"ir-measures' pyproject.toml` runs.
- Then exactly one match returns, in `[project].dependencies`, with version constraint `>=0.4.3` (or a tighter pin if the impl-plan author chose).
- Example values:
  - Input: `grep '"ir-measures' pyproject.toml`
  - Expected: `"ir-measures>=0.4.3",`

### AC-6: Doc-rewrite verification grep is clean

- Given the merged PR.
- When `grep -rn 'pytrec_eval\|pytrec-eval' . --exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=.git` runs.
- Then every remaining match is inside one of:
  - `docs/00_overview/implemented_features/` (historical),
  - `docs/blog/` (dated historical),
  - `state.md` (historical entries; the new entry describing the migration may name `pytrec_eval` once as "the library being replaced"),
  - The parity test file (`backend/tests/unit/eval/test_scoring_parity.py`),
  - The Dockerfile comment IF reworded to credit `ir_measures`' transitive C-extension dependency (per FR-6),
  - The `pyproject.toml` `[dependency-groups.dev]` line (per FR-4 — REQUIRED, not optional),
  - The `pyproject.toml` `[[tool.mypy.overrides]]` block for `pytrec_eval` if AC-4c keeps it.
- Example values:
  - Input: the grep above.
  - Expected: no matches in `backend/app/`, `backend/tests/` (other than the parity test), `docs/01_architecture/`, `docs/02_product/` (other than this spec's own §15 docstring inventory and §19 decision log naming the library being replaced), `docs/08_guides/`, `ui/src/`, `ui/public/`, `README.md`, `CLAUDE.md`, `architecture.md`, `release-notes-v0.1.0-draft.md`.

### AC-7: studies.py:313 error message names ir_measures (or no library)

- Given the merged PR.
- When `grep -n "ir_measures\|pytrec_eval" backend/app/api/v1/studies.py` runs.
- Then the inline comment (currently line 270) and the error-message string (currently line 313) both name `ir_measures` instead of `pytrec_eval`, OR are reworded to name no library at all (e.g., "every trial will score 0 on every metric"). Either is acceptable.
- Example values:
  - Input: `grep -n "score 0 on every trial" backend/app/api/v1/studies.py`
  - Expected: one match, with `ir_measures` (or no library) named in the surrounding string.

### AC-8: Existing tests still pass unchanged

- Given the merged PR.
- When `make test-unit test-integration test-contract` runs (with running Postgres + ES + OpenSearch).
- Then every pre-existing test passes — no test assertion is weakened, skipped, or deleted to accommodate the migration. The only test changes are: (a) new `test_scoring_parity.py` file added (the **permanent** CI gate per FR-2), (b) the "no wire-form leakage" assertions in `test_trial_row_shape.py:113` and `test_run_trial_per_query_persistence.py:111` are *extended* (not weakened) to also forbid `ir_measures` PascalCase reprs (`nDCG@`, `P@`, `RR`, `AP@`, `R@`), (c) the `test_studies_api_contract.py` case that pins the `INSUFFICIENT_JUDGMENT_OVERLAP` envelope message substring is updated to match the new wording, (d) a new integration test (per AC-12) loads a pre-migration-shaped trial fixture and exercises the consumers without re-scoring.
- Example values:
  - Input: `pytest backend/tests/unit backend/tests/integration backend/tests/contract -v`
  - Expected: zero new failures; total count = previous count + ~30 (parity test parametrized cases) + 1 (existing-row regression).

### AC-12: Existing-row read regression — pre-migration JSONB shapes still hydrate consumers

- Given a synthetic-but-realistic `Trial` row inserted via a test fixture with `metrics = {"ndcg@10": 0.82, "map@10": 0.71, "map": 0.65, "mrr": 0.91}` AND `per_query_metrics = {"q1": {"ndcg@10": 0.83, "map@10": 0.7, "mrr": 1.0}, "q2": {"ndcg@10": 0.81, "map@10": 0.72, "mrr": 0.83}, ...}` (exactly the shape rows persisted before this migration carry today).
- When the test invokes `compute_study_confidence` against that trial via the existing `fetch_study_confidence` service, AND the trial-list endpoint serializes the row, AND the digest worker's top-trials section runs on it.
- Then every consumer returns its expected output without raising: `compute_study_confidence` returns a `ConfidenceShape` whose `headline.metric` matches the trial's objective, whose `ci_95` populates from the per-query values, and whose `per_query_outcomes.top_regressors` enumerates the named regressors correctly; the trial-list response includes the JSONB unchanged; the digest sees the row in its top-trials list.
- This AC is the load-bearing test for the "no-migration / no-backfill" claim — it proves the new code path on the OLD persisted shape works without re-scoring.
- Example values:
  - Input: insert a fixture trial with the JSONB above; call `GET /api/v1/studies/{study_id}` and assert the `confidence` block populates.
  - Expected: `confidence.headline.value == 0.82`, `confidence.headline.n_queries > 0`, no exceptions, no NULL ConfidenceShape return.

### AC-9: Coverage gate stays green

- Given the merged PR.
- When `make test-unit && coverage report` runs.
- Then the 80% coverage gate from `pyproject.toml [tool.coverage.report].fail_under` is satisfied. The migration touches only `scoring.py` (already well-covered) and shouldn't move the needle.
- Example values:
  - Expected: coverage report shows ≥ 80% for `backend.app.eval.scoring`.

### AC-10: Dockerfile change matches the empirical verification

- Given the merged PR.
- When the impl-plan author runs `pip install ir-measures && pip show pytrec_eval` in a clean environment (per FR-6 verification recipe).
- Then either:
  - (a) `pytrec_eval` IS resolved as a transitive backend → Dockerfile lines 44–54 stay; comment is reworded to credit `ir_measures` as the reason for needing gcc/g++/python3-dev headers.
  - (b) `pytrec_eval` is NOT resolved transitively → Dockerfile lines 44–54 are dropped; alpine/arm64 first-builds get the wheel install path.
- The implementation plan's Story for this conditional change documents which branch was taken AND cites the verification output.
- Example values:
  - Branch (a) command: `docker build .` succeeds on a fresh checkout; the `deps` stage still installs gcc.
  - Branch (b) command: `docker build .` succeeds with gcc removed.

### AC-11: state.md gains a new dated entry

- Given the merged PR.
- When the user reads `state.md` after merge.
- Then the "Most recent meaningful changes" section's newest entry describes the migration: PR number, date, scope summary ("scoring.py swapped from pytrec_eval to ir_measures"), parity test result, Alembic head ("unchanged at `0015_trials_per_query_metrics` — application-layer-only feature"). The entry is *new*; no previous entry is back-edited.

## 13) Non-functional requirements

- **Performance:** `score()` p99 latency unchanged ± 10%. `ir_measures` adds a thin layer over the same backend; the parametrized-fixture benchmark at `backend/tests/benchmarks/test_scoring_perf.py` should report numbers within 10% of pre-migration baseline. The benchmark is not part of the default test gate (marked `@pytest.mark.benchmark`); spot-check after merge.
- **Reliability:** No change in error semantics. The library swap doesn't introduce new failure modes — same C-extension load path (if transitive), same input shape, same return shape.
- **Operability:** No new env vars, no new secrets, no new logs, no new metrics. The structlog events emitted by `run_trial` (`trial.scored`, etc.) carry the same payload shape — they reference `metric` keys by user-facing token, which is unchanged.
- **Accessibility/usability:** N/A — no UI change.

## 14) Test strategy requirements (spec-level)

| Layer | Path | Required coverage |
|---|---|---|
| Unit | `backend/tests/unit/eval/test_scoring.py` | Existing tests pass unchanged. Comments reworded (no new test cases needed). |
| Unit | `backend/tests/unit/eval/test_scoring_metric_tokens.py` | Existing tests pass unchanged. `_translate_metric_name`'s ValueError paths still trigger on the same inputs (the function now returns metric objects instead of strings, but the exception surface is preserved). |
| Unit | `backend/tests/unit/eval/test_qrels_loader.py` | Existing tests pass unchanged. |
| Unit | **NEW** `backend/tests/unit/eval/test_scoring_parity.py` | Parametrized parity test per FR-2 / AC-2. Imports both `pytrec_eval` and `ir_measures`; asserts 6-decimal equivalence per `(metric, k)` pair across the 30-case cross. Permanent CI gate (FR-4 keeps `pytrec-eval` as a dev/test dep so this test stays runnable). The fixture covers the four edge cases listed in FR-2 (no-relevant-docs query, qrel-only query, run-only query, empty-overlap query). |
| Unit | **NEW (or extended)** `backend/tests/unit/eval/test_scoring_per_query_shape.py` | Per-query shape parity per FR-3 / AC-2 (extended). Asserts the outer-key set and per-query inner-key set match `pytrec_eval`'s output 1:1 on the same edge-case fixture. |
| Contract | `backend/tests/contract/test_trial_row_shape.py` | The "no wire-form leakage" assertion at line 113 is **extended** (not replaced) to also forbid `ir_measures` PascalCase reprs (`nDCG@`, `P@`, `RR`, `AP@`, `R@`). AC-3's negative-case enumeration verifies the assertion is substantive (rejects each forbidden token explicitly). Tests still pass against the user-facing token contract. |
| Contract | `backend/tests/contract/test_studies_api_contract.py` | The `INSUFFICIENT_JUDGMENT_OVERLAP` envelope test that pins the message substring (per FR-5) is updated to match the new wording. |
| Integration | `backend/tests/integration/test_run_trial_per_query_persistence.py` | The "no wire-form leakage" assertion at line 111 extended same as contract test. Existing happy-path tests pass unchanged — the worker invokes `score()` which now returns the same shape via `ir_measures`. |
| Integration | **NEW** `backend/tests/integration/test_existing_row_read_compat.py` | Per AC-12: insert a synthetic-but-realistic trial with pre-migration JSONB shape, then exercise `fetch_study_confidence` + the trial-list endpoint + the digest's top-trials section without re-scoring. The load-bearing test for the "no migration / no backfill" claim. |
| E2E | N/A | No E2E coverage required. No UI flow changes (error-toast text change is a string update, not a flow change). |

## 15) Documentation update requirements

- `docs/01_architecture/optimization.md` — title + 10 mentions reworded to `ir_measures`. Code example block at lines 87–90 (`pytrec_eval.RelevanceEvaluator(qrels, ...).evaluate(run)`) rewritten to the `ir_measures.calc_aggregate([nDCG@10, AP, P@10, ...], qrels, run)` shape. The "Engine: pytrec_eval everywhere" subsection (if mirrored from the umbrella spec) reframed as "Engine: provider-abstracted via `ir_measures`".
- `docs/01_architecture/tech-stack.md` — line 41 IR-evaluation row updated.
- `docs/01_architecture/system-overview.md` — line 76 component table row updated.
- `docs/01_architecture/README.md` — line 21 cross-reference updated.
- `docs/01_architecture/data-model.md` — lines 52, 231 reworded.
- `docs/01_architecture/cluster-lifecycle.md` — line 159 reworded.
- `docs/00_overview/relyloop-spec.md` — umbrella spec; ~11 mentions reworded. The "Engine: pytrec_eval everywhere" subsection (lines 688–693) reframed as a provider-abstraction discussion. Stack table at line 155 + line 2513 + decision log at 2658 + appendix at 2722 all updated.
- `docs/02_product/mvp1-user-stories.md` — US-7 narrative reworded.
- `docs/02_product/planned_features/feat_study_baseline_trial/idea.md` — sibling-coordination: line 56 ("scores via `pytrec_eval`") reworded to `ir_measures`. Same-PR update.
- `docs/02_product/planned_features/feat_auto_followup_studies/idea.md` — sibling-coordination: line 47 ("Optuna + pytrec_eval are deterministic") reworded to `Optuna + ir_measures`. Same-PR update.
- `docs/08_guides/workflows-overview.md` — lines 123, 277 reworded.
- `ui/public/docs/workflows-overview.md` — same content as above; lock-step.
- `ui/public/guides/05_import_judgments_and_calibrate/script.md` — line 6 reworded.
- `ui/public/guides/06_create_and_monitor_study/script.md` — line 8 reworded.
- `ui/public/guides/06_create_and_monitor_study/metadata.json` — line 26 `caption` reworded.
- `README.md` — line 9 reworded.
- `CLAUDE.md` — lines 15, 29 reworded.
- `architecture.md` — line 131 reworded.
- `release-notes-v0.1.0-draft.md` — line 12 reworded.
- `state.md` — new dated entry per AC-11. **Do not back-edit existing entries.**

**Auto-regenerated (still a required PR task):**
- `docs/00_overview/MVP1_DASHBOARD.md` — regenerates via `scripts/build_mvp1_dashboard.py`. The implementation plan **MUST** include an explicit story for running the regen so the dashboard's two pre-existing `pytrec_eval` mentions (line 64 in the `infra_optuna_eval` row, line 134 in the `infra_ir_measures_migration` row that this very feature is closing) are picked up at merge time. Without an explicit regen task, the merge-time AC-6 grep gate fails (per GPT-5.5 cycle-1 F11).

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** None. The migration is a library swap with a parity test as the gate. There's no operator-facing surface to flag.
- **Migration/backfill expectations:** None. No DB migration, no data backfill — every existing `trials` row continues to be readable because the persisted JSONB key shape is preserved (FR-1c / FR-3).
- **Operational readiness gates:**
  - Parity test passes for every (metric, k) in the 30-case cross (AC-2).
  - Per-query shape parity passes for the four edge-case queries in the fixture (AC-2 extended via FR-3).
  - Doc-sweep grep is clean AND the broader wire-form sweep (`RelevanceEvaluator|ndcg_cut_|map_cut_|recip_rank|recall_[0-9]|\bP_[0-9]`) is also clean per FR-7 (AC-6).
  - Existing test suites all green at unit + integration + contract layers (AC-8).
  - Existing-row read regression passes — pre-migration JSONB shapes hydrate every consumer without raising (AC-12).
  - 80% coverage gate met (AC-9).
  - Dockerfile change matches empirical verification (AC-10).
  - MVP1_DASHBOARD.md regenerated (per §15 explicit regen task).
- **Release gate:** PR-time CI runs the full test matrix (including the new parity test); the GPT-5.5 cross-model review and Gemini Code Assist review pass; the canonical grep verification (AC-6) runs as part of the impl-plan's pre-push gate (or as a dedicated CI step). No staged rollout needed — the migration is atomic at merge time.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 (scoring.py swap) | AC-1, AC-3 | Story 1: rewrite scoring.py with locked metric-object mapping | `test_scoring.py`, `test_scoring_metric_tokens.py`, `test_qrels_loader.py` (all pass unchanged); contract tests verify JSONB keys | `scoring.py` docstrings + `qrels_loader.py:45` |
| FR-2 (parity test, permanent CI gate) | AC-2 | Story 2: write parity test + fixture (30 parametrized cases, 4 edge-case queries) | NEW `test_scoring_parity.py` | N/A |
| FR-3 (no wire-form leakage + per-query shape parity) | AC-3, AC-8, AC-12 | Story 3: extend leakage assertions, add per-query shape parity test, add existing-row regression | `test_trial_row_shape.py`, `test_run_trial_per_query_persistence.py`, NEW `test_scoring_per_query_shape.py`, NEW `test_existing_row_read_compat.py` | N/A |
| FR-4 (pyproject.toml — runtime + dev) | AC-4, AC-5 | Story 4: drop pytrec-eval from `[project]`, add `ir-measures` to `[project]`, add `pytrec-eval` to `[dependency-groups.dev]`, update mypy overrides | N/A (verified by AC-4/AC-5 grep) | N/A |
| FR-5 (studies.py:313 wording) | AC-7 | Story 5: reword inline comment (270) + error message (313) + contract-test substring | `test_studies_api_contract.py` (envelope substring) | studies.py inline + error message |
| FR-6 (Dockerfile conditional) | AC-10 | Story 6: verify transitive backend; update Dockerfile | N/A (verified by docker build) | Dockerfile lines 44–54 + comment |
| FR-7 (doc sweep + dashboard regen + broader grep) | AC-6, AC-11 | Story 7: full doc + code-comment + UI source-of-truth sweep + MVP1_DASHBOARD regen | N/A (verified by AC-6 grep AND broader wire-form grep) | Everything in §15 doc list + dashboard regen |

## 18) Definition of feature done

This feature is complete when:

- [ ] All acceptance criteria (AC-1 through AC-12) pass in CI.
- [ ] `make test-unit`, `make test-integration`, `make test-contract`, `make typecheck`, `make lint` all green.
- [ ] The grep gate per AC-6 passes (no live-state `pytrec_eval` mentions outside the allowlist).
- [ ] The broader wire-form sweep passes per FR-7 (`RelevanceEvaluator`, `ndcg_cut_`, `map_cut_`, `recip_rank`, `recall_[0-9]`, `\bP_[0-9]` are all clean outside the allowlist).
- [ ] The parity test (AC-2) passes for all 30 parametrized `(metric, k)` cases.
- [ ] Per-query shape parity passes for the 4 edge-case queries (no-relevant, qrel-only, run-only, empty-overlap).
- [ ] The existing-row read regression (AC-12) passes — pre-migration JSONB shapes hydrate confidence + trial-list + digest without raising.
- [ ] `docs/01_architecture/optimization.md` + `tech-stack.md` + `system-overview.md` + all docs in §15 are updated and merged in the same PR. The umbrella spec (`docs/00_overview/relyloop-spec.md`)'s "Engine: pytrec_eval everywhere" subsection is reframed as a provider-abstraction discussion.
- [ ] `state.md` has a new dated entry describing the migration (per AC-11).
- [ ] `docs/00_overview/MVP1_DASHBOARD.md` regenerated via `scripts/build_mvp1_dashboard.py`.
- [ ] Q1/Q2/Q3/Q4/Q5 resolutions are recorded in the decision log with cited verification output (per §19).
- [ ] Dockerfile change decision (drop vs. keep gcc/g++/python3-dev) is documented with the empirical verification output that drove it.
- [ ] Sibling planned-feature idea files (`feat_study_baseline_trial/idea.md:56`, `feat_auto_followup_studies/idea.md:47`) updated to name `ir_measures` instead of `pytrec_eval`.
- [ ] `studies.py:313` operator-visible error message AND its contract-test substring assertion updated atomically.
- [ ] `pytrec-eval>=0.5` lives only in `[dependency-groups.dev]` after the PR; no occurrence in `[project].dependencies`.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

All five resolve at implementation-plan time. They are empirical and bounded — none require a product decision.

**Q1: Does the historical migration `0015_trials_per_query_metrics.py:17` docstring get reworded?**

- Context: The migration file is part of `docs/00_overview/implemented_features/2026_05_21_feat_pr_metric_confidence/`'s shipped scope, but the *file itself* lives at `migrations/versions/0015_trials_per_query_metrics.py` — under `migrations/`, not under `implemented_features/`. The CLAUDE.md / spec convention says implemented-features folders are frozen, but `migrations/` lives outside that convention.
- Options:
  - (a) Treat as historical (leave alone): the migration was authored when `pytrec_eval` was the engine; rewording rewrites history.
  - (b) Treat as current-state (reword): the migration file is in the active source tree and will be read by future engineers (or `alembic upgrade --sql` output); leaving stale references is misleading.
- Recommended: **(b) reword.** The migration file is read by future engineers; the docstring is a forward-looking explanation of the persisted shape, not a record of authoring history.
- Owner: spec author / impl-plan author — Due: before plan-creation. (Recommended decision is the default; deferred to impl-plan time only if the recommendation is rejected.)

**Q2: Does `ir_measures` ship PEP 561 type hints (a `py.typed` marker)?**

- Context: `pyproject.toml` line 156–158 currently has `[[tool.mypy.overrides]] module = "pytrec_eval" ignore_missing_imports = true` because `pytrec_eval` ships no type info. If `ir_measures` does ship type info, the override can be dropped entirely; if not, it must be repointed.
- Verification recipe: `pip install ir-measures && find $(python -c 'import ir_measures, os; print(os.path.dirname(ir_measures.__file__))') -name py.typed` — empty output means no `py.typed` marker; one path means it does.
- Owner: impl-plan author — Due: before writing pyproject.toml updates.

**Q3: Does `ir-measures>=0.4.3` keep `pytrec_eval` as a default transitive backend for the metrics in `SUPPORTED_METRICS × SUPPORTED_K_VALUES`?**

- Context: Drives the Dockerfile change decision (FR-6), the `[dependency-groups.dev]` decision (FR-4), and the parity-test fixture infrastructure (FR-2).
- Verification recipe: `pip install ir-measures && pip show pytrec_eval` — exit code 0 + non-empty output means `pytrec_eval` is reachable transitively; exit code 1 means it isn't. Also confirmable via `uv tree | grep pytrec_eval` after a fresh `uv sync`.
- Two outcomes for the **Dockerfile / runtime image** (the parity-test viability is already guaranteed independently by FR-4's `[dependency-groups.dev]` pin, regardless of transitive routing):
  - (a) `pytrec_eval` is transitively present for at least one `SUPPORTED_METRICS` value. Dockerfile gcc/g++/python3-dev install stays (the runtime image needs the C-extension toolchain at install time); the comment block is reworded to credit `ir_measures`' transitive backend.
  - (b) `pytrec_eval` is NOT transitively present (or every `SUPPORTED_METRICS` value routes to a pure-Python provider in the resolved `ir_measures` version). Dockerfile gcc/g++/python3-dev install may be droppable; verify a clean `docker build .` still succeeds.
- Owner: impl-plan author — Due: before writing the Dockerfile + pyproject.toml stories.

**Q4: Does any metric need provider forcing to achieve parity, and if so, what is the documented API at the pinned `ir_measures` version?**

- Context: `ir_measures` is a provider-abstracted facade that routes each metric to one of `pytrec_eval`, `gdeval`, `judged_as_relevant`, or `cwl_eval` based on internal heuristics that can shift across versions. For parity to pass (FR-2), every metric's chosen provider must produce values within 1e-6 of `pytrec_eval`'s direct output.
- Verification recipe (observable-first):
  1. Pin `ir_measures` to a specific version in `pyproject.toml`.
  2. Run the parity test (FR-2) — if all 30 cases pass, no provider forcing is needed and Q4 resolves "no action required, no internals introspected".
  3. If any case fails, inspect the failing metric's provider routing using only **documented** `ir_measures` APIs at the pinned version (the impl-plan author reads `ir_measures`' published documentation / README / release notes — NOT private modules with leading-underscore names like `_get_measure_args`). If a documented provider-forcing API exists at the pinned version, use it; the spec's hard 1e-6 parity gate (§4 + AC-2) MUST still pass after the forcing.
- **Bounded outcomes** for Q4 (the impl-plan resolves to exactly one of these — there is no "accept the drift" branch because AC-2 is a hard gate; relaxing AC-2 would be a separate user-approved spec change, not a Q4 resolution):
  - (a) Parity passes for all 30 cases against the default `ir_measures` provider routing → no forcing required, no spec change.
  - (b) Parity passes for all 30 cases after invoking the **documented** provider-forcing API at the pinned `ir_measures` version → cite the API in the impl-plan + decision log.
  - (c) Parity passes for all 30 cases after bumping or repinning `ir_measures` to a version where the default routing produces parity → cite the version pin + decision log.
  - (d) **Blocker.** Parity cannot be made to pass via (a)/(b)/(c). The PR is blocked pending a separate user-approved spec change that either relaxes AC-2's tolerance OR shrinks `SUPPORTED_METRICS` (the latter changes the public allowlist contract and is a product decision).
- Owner: impl-plan author — Due: before the parity test is run for the first time.
- Note: the spec deliberately avoids citing `ir_measures.measures._get_measure_args(...)` / `set_provider(...)` (private names that may not exist at the pinned version). The implementation plan, not this spec, anchors any internal-API references against the actual installed version (per GPT-5.5 cycle-2 C2-F6 + cycle-3 C3-F1).

**Q5: What is the transitive dependency set / license footprint / performance delta of `ir_measures` vs. the current `pytrec_eval`-only path?**

- Context: `ir_measures` may pull `pandas`, `numpy` (already a dep), `cwl-eval`, plus provider backends transitively. The supply-chain note in §10 says "no license-incompatible dependencies expected" but doesn't verify it. The performance non-functional requirement in §13 says "p99 latency unchanged ± 10%" but doesn't have a measurement.
- Verification recipe: in a clean checkout, run (a) `uv sync && uv tree | grep -v pytrec_eval` to see the new transitive set, (b) cross-reference each new package's license against the project's [LICENSE](../../../../LICENSE) (Apache 2.0) compatibility list, (c) run `pytest backend/tests/benchmarks/test_scoring_perf.py -v` against both `main` and the feature branch and compare the warm-call timings.
- Owner: impl-plan author — Due: before merging the PR.
- Acceptable outcomes: all transitive deps Apache-2.0-compatible; benchmark within 10% of pre-migration baseline. Failing either of these is a blocker.

### Decision log

- **2026-05-22 — Single-PR scope, no phasing.** The migration ships as one PR (scoring + parity test + pyproject + doc sweep + UI comment sweep + Dockerfile conditional + sibling-idea coordination). Rationale: doc-sweep grep-divergence and UI source-of-truth comments rotting against scoring.py would create operator-visible inconsistency if landed separately.
- **2026-05-22 — `ir_measures` over `ranx`.** The idea author considered `ranx` directly; rejected on (a) single-maintainer bus factor (same failure mode), (b) Numba install + JIT cold-start cost, (c) no provider abstraction. `ir_measures` keeps provider-swap as a config change.
- **2026-05-22 — `ir_measures` over `pytrec-eval-terrier` (the actively-maintained fork).** Rejected because (a) still a C extension with the same build-pain footprint, (b) doesn't introduce the provider abstraction.
- **2026-05-22 — Public API of `scoring.py` is frozen.** `score()`, `objective_metric_key()`, `SUPPORTED_METRICS`, `SUPPORTED_K_VALUES`, `ScoreResult`, `Qrels`, `Run` all preserve their existing signatures and shapes. Rationale: every caller (the `run_trial` worker, `confidence.py`, the studies endpoint, every test) reads these symbols today; a signature change would cascade.
- **2026-05-22 — Persisted JSONB key shape is frozen.** `trials.metrics` + `trials.per_query_metrics` keep their user-facing token keys (`ndcg@10`, etc.). Rationale: every existing row in production was persisted with these keys; changing them silently breaks every read consumer.
- **2026-05-22 — Parity gate is 6 decimal places (1e-6 tolerance).** Rationale: standard IR-eval precision; tighter than the FP32 noise floor of typical retrieval scoring; loose enough to tolerate the cumulative rounding of bootstrap means.
- **2026-05-22 — Sibling planned-feature idea files updated in same PR.** `feat_study_baseline_trial/idea.md:56` and `feat_auto_followup_studies/idea.md:47` mention `pytrec_eval` by name; updating in the same PR avoids the drift-vs-source-of-truth failure mode where the planning doc still names the abandoned library after the codebase moves.
- **2026-05-22 — `confidence.py` is out of scope.** It consumes user-facing per-query keys (not pytrec_eval wire forms) and does not import the library directly. The "land before further confidence surface grows" pressure that motivated this migration originally was rendered moot when `feat_pr_metric_confidence` Phase 1 shipped 2026-05-21 against user-facing keys.
- **2026-05-22 — Cross-model review trajectory.** Cycle 1: 11 findings (all accepted, all applied — metric-object mapping table in FR-1, stricter AC-3 regex with negative cases, parity-test lifecycle, per-query shape parity in FR-3, reader inventory + write-surface audit in §2, new AC-12 existing-row regression, Q4 + Q5, expanded wire-form sweep in FR-7, §11 two-categories clarification, dashboard-regen task). Cycle 2: 6 findings (all accepted, all applied — dependency lifecycle deduped to "permanent dev-group" model only, AC-4 split into AC-4a/b/c with section-aware verification, §2 mapping example aligned with FR-1, FR-1/FR-2 aggregate-computation contract pinned to per-query iteration + manual mean rather than `calc_aggregate()`, inline `test_seeding.py p@10 → precision@10` fix bundled, Q4 reframed around observable behavior + documented APIs). Cycle 3: 1 finding (accepted + applied — Q4 bounded outcomes locked, no "accept drift" branch). Convergence: 11 → 6 → 1 — spec approved for impl-plan generation.
- **2026-05-23 — Dev-group `pytrec-eval>=0.5` pin removed post-CI-failure.** The original FR-4 / AC-4b spec required a dev-group pin on `pytrec-eval>=0.5` to keep the parity test runnable. CI failure on PR #198 first push revealed that the abandoned `pytrec-eval` distribution and the transitively-pulled `pytrec-eval-terrier` distribution BOTH publish to the same `pytrec_eval` module name in site-packages — install order determines which one wins, and CI happened to install the abandoned `pytrec-eval` last, leaving `ir_measures` without its cut-aware-metric provider (every `(metric, k)` test failed with "Unsupported measures {nDCG@10}"). Fix: remove the dev-group pin entirely. The transitively-resolved `pytrec-eval-terrier` (from `ir-measures>=0.4.3`) provides the `pytrec_eval` module the parity test needs. **AC-4b is hereby superseded** — the gate now reads "pyproject.toml `[dependency-groups.dev]` does NOT contain `pytrec-eval` (the abandoned distribution would conflict with the transitively-resolved `pytrec-eval-terrier`)." The parity gate stays alive because `pytrec-eval-terrier` is byte-identical to `pytrec-eval` on the metrics we support — that's why the parity test passes against it.
