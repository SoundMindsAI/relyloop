# Bug — `compute_study_confidence` uses bare metric name to look up per-query metrics whose keys are `@k`-suffixed

**Status:** Idea (filed 2026-05-21; surfaced by Story 1.5 of `feat_pr_metric_confidence`)

**Origin:** Caught while running the full integration suite during Story 1.5 (`/impl-execute` of `feat_pr_metric_confidence`). The Story 1.2 test [`backend/tests/integration/test_run_trial_per_query_persistence.py::test_successful_trial_writes_per_query_metrics`](../../../../backend/tests/integration/test_run_trial_per_query_persistence.py) fails with `unexpected metric key 'map@10' in per_query_metrics[...]; score() should remap pytrec_eval wire names to ['map', 'mrr', 'ndcg', 'precision', 'recall']`. The test asserted bare metric base names; the actual `score()` output uses `@k`-suffixed user-facing names.

## Problem

The two implementations disagree on the shape of `trials.per_query_metrics`:

| Surface | What it produces / expects |
|---|---|
| [`backend/app/eval/scoring.py:179-184`](../../../../backend/app/eval/scoring.py#L179) `score()` (Story 1.1+) | `per_query[qid] = {ndcg@10: float, map@10: float, mrr: float, ...}` — user-facing tokens preserved including `@<k>` cutoff |
| [`backend/workers/trials.py`](../../../../backend/workers/trials.py) Story 1.2 worker | Writes `scored["per_query"]` verbatim → DB has `@k`-suffixed keys |
| [`backend/app/domain/study/confidence.py:537-540`](../../../../backend/app/domain/study/confidence.py#L537) `compute_study_confidence` (Story 1.3) | Uses `metric = study_objective.get("metric")` (e.g., `"ndcg"`, bare) to look up `v[metric]` on each per_query dict — **misses** because the key is `ndcg@10`, not `ndcg` |
| [`backend/tests/integration/test_run_trial_per_query_persistence.py:100-115`](../../../../backend/tests/integration/test_run_trial_per_query_persistence.py#L100) Story 1.2 test | Asserts `metric_key in {"ndcg", "map", "precision", "recall", "mrr"}` (bare) — **fails** because the worker writes `@k`-suffixed keys |
| [`feature_spec.md`](../../../00_overview/implemented_features/2026_05_21_feat_pr_metric_confidence/feature_spec.md) AC-1 / AC-10 (when this ships there) | Examples show bare keys (`{qid: {ndcg: 0.84, map: 0.7, ...}}`) — agrees with Story 1.3's bare-key lookup but disagrees with the worker reality |

**Production impact:** For every real completed study with `per_query_metrics` populated, the orchestrator runs `metric not in v` → True → `winner_values_for_metric = []` → `bootstrap_ci_95` returns `None` (N<5) → CI suppressed. Likewise `compute_outcome_summary` produces empty intersection → `per_query_outcomes = None`. Operators see the partial / aggregate-only confidence shape on every PR — the feature's headline value (CI band, named regressors) silently never renders against real data.

**Why this slipped past Story 1.4's integration tests:** [`backend/tests/integration/test_studies_api_confidence.py`](../../../../backend/tests/integration/test_studies_api_confidence.py) seeds `per_query_metrics` directly with bare keys (`{ndcg: 0.41, ...}`) to match the spec literal. That matches the orchestrator's expectation, so the tests pass — but those keys aren't what the worker actually persists in production. Same for Story 1.5's integration test ([`test_open_pr_worker_confidence_plumbing.py`](../../../../backend/tests/integration/test_open_pr_worker_confidence_plumbing.py)).

## Why deferred

The fix forks into product-shaped questions that deserve their own design pass:

1. **Where does the canonicalization happen?**
   - **(a)** Worker remaps per_query keys to bare metric base names before persisting. Keeps Story 1.3 simple but drops `@k` info (problematic when a study computes both `ndcg@5` and `ndcg@10`).
   - **(b)** Orchestrator uses `objective_metric_key(study.objective)` to compute the lookup key. Keeps all persisted info but requires Story 1.3's `compute_outcome_summary` to accept separate `metric_lookup_key` + `metric_threshold_key` args (the former drives `v[key]` lookups; the latter drives `REGRESSOR_THRESHOLDS.get(key)`).
   - **(c)** Worker normalizes ONLY the primary metric to bare form and drops `@k` suffix; secondary metrics stay as `@k` for future analytics. Compromise that loses the cutoff for the primary metric only.

2. **Spec patch required.** Whichever route lands, the spec's AC-1 / AC-10 examples need updating to reflect the chosen canonical form. The shipped spec at [`docs/00_overview/implemented_features/2026_05_21_feat_pr_metric_confidence/feature_spec.md`](../../../00_overview/implemented_features/2026_05_21_feat_pr_metric_confidence/feature_spec.md) will get an erratum note.

3. **Test refactor cost.** Both Story 1.4 (11 cases) and Story 1.5 (1 case) integration tests seed bare-key per_query data. They'll need a small refactor (~10 LOC) to use the chosen canonical form.

The current `/impl-execute` of Story 1.5 was scoped to PR body plumbing. Bundling an interface change to Story 1.3's pure orchestrator would inflate scope past the rubric's "fix the work-type that fits this PR's intent" guidance, so capturing here is the right call.

## Surface

- **Backend:** `backend/app/domain/study/confidence.py` (Story 1.3 orchestrator), `backend/workers/trials.py` (Story 1.2 worker — only if route (a) or (c) chosen).
- **Tests:** `backend/tests/integration/test_run_trial_per_query_persistence.py` (relax / correct assertion), `backend/tests/integration/test_studies_api_confidence.py` (11 cases), `backend/tests/integration/test_open_pr_worker_confidence_plumbing.py` (1 case), `backend/tests/unit/domain/study/test_confidence.py` (25+ cases may need shape updates).
- **Docs:** `feature_spec.md` AC-1 / AC-10 erratum.
- **No new endpoints, no migration, no frontend impact.**

## Acceptance signal

- `make test-integration` runs cleanly against the live in-container Postgres with no skipped Story 1.1 / 1.2 / 1.4 / 1.5 cases left failing.
- A seeded real-worker run (winner trial inserted via `run_trial` Arq job, not direct SQL) drives `compute_study_confidence` to a fully-populated `ConfidenceShape` (CI band + per_query_outcomes both non-null when seed data warrants).
- Spec's AC-1 / AC-10 example shape matches the persisted DB shape verbatim.

## Related work

- Bundled `Story 1.5` commit `<sha>` fixes the two mechanical pre-existing test failures (`test_migrations.py` head `0014`→`0015`; `test_trials_per_query_metrics_migration.py` invalid `judgment_lists.status='ready'`→`'complete'`) — those were not part of this drift but were uncovered in the same full-suite run. See the impl-execute transcript for the rubric reasoning (mechanical assertion updates qualify as inline fixes; this product-shaped key drift does not).
