# Optimization (Optuna + pytrec_eval)

**Status:** Adopted for MVP1. Single-objective TPE + median pruner; pytrec_eval scoring. Multi-objective optimization (CMA-ES + multi-metric) reserved for v2 per umbrella spec.
**Source of truth for product context:** [docs/00_overview/product/relevance-copilot-spec.md §13–§14](../00_overview/product/relevance-copilot-spec.md). Per-release timing per [`tech-stack.md` §"Canonical release matrix"](tech-stack.md).

---

## The optimization loop

A study runs N trials in parallel. Each trial:

1. **Ask** Optuna for a parameter combination (the sampler decides; TPE in MVP1).
2. **Render** the parameter combination into a native engine query via the configured `QueryTemplate` and `SearchAdapter` (per [`adapters.md` §"The Protocol"](adapters.md)).
3. **Execute** the query batch via `SearchAdapter.search_batch(target, queries, top_k)` against the registered cluster.
4. **Score** the result set with pytrec_eval against the configured `judgment_list`, computing the study's primary metric + secondary metrics.
5. **Tell** Optuna the metric value.
6. **Persist** the trial row (params + all metrics + duration_ms + status) per [`data-model.md` §"`trials`"](data-model.md).

Workers loop until the study's stop condition fires (max_trials hit, time_budget_min elapsed, or `studies.status` flips to `cancelled`).

## Optuna configuration

Per umbrella spec §13, defaults below ship in MVP1:

| Setting | MVP1 default | Activates / changes at |
|---|---|---|
| Storage | `RDBStorage` against the same Postgres instance, schema `optuna.*` | — |
| Sampler | `TPESampler` (Tree-structured Parzen Estimator) | CMA-ES selectable per study (≥7 continuous params, no categoricals) at MVP2; random sampler available as a baseline-comparison option from MVP1 |
| Pruner | `MedianPruner(n_warmup_steps=10)` | Studies with `<50` trials disable pruning automatically (pruning needs warmup; small studies don't get enough signal) |
| Parallelism | N workers share one Optuna study via the RDB; each worker calls `study.ask()` / `study.tell()` independently; RDB locking handles concurrency | — |
| Reproducibility | Seed stored on `studies.config.seed`; reruns of the same study with the same seed are deterministic up to RDB ordering effects | — |
| Stop conditions | Worker polls `study.should_stop()` which checks Postgres `studies.status` for `cancelled` or `completed` | — |
| Multi-objective | NOT supported in MVP1 — single scalar objective only | v2 |

**Why same Postgres for app + Optuna:** simplifies operator setup (one DB to back up); Postgres handles both loads comfortably at MVP1 sizing. Co-tenancy convention documented in [`data-model.md` §"Optuna RDB co-tenant"](data-model.md).

**Connection string template for the worker:**

```python
storage = optuna.storages.RDBStorage(
    url=f"{DATABASE_URL}?options=-csearch_path=optuna",
    engine_kwargs={"pool_pre_ping": True},
)
```

The `options=-csearch_path=optuna` forces Optuna's CREATE/SELECT into its own schema, isolated from the application's `public` schema.

## pytrec_eval configuration

Per umbrella spec §14, RelyLoop **always** evaluates via pytrec_eval — never engine-native `_rank_eval`. Reasons:

- pytrec_eval is the de facto standard wrapper for `trec_eval`.
- ES `_rank_eval` and pytrec_eval don't always agree to many decimal places (different normalization conventions).
- Per-query scores are inspectable, enabling deep debugging.
- Cross-engine comparability: the same metric semantics apply whether the underlying engine is ES, OpenSearch, Fusion, or Solr.

### Supported metrics (MVP1)

Computed at trial time and stored in `trials.metrics` (JSONB):

| Metric | Notes |
|---|---|
| `ndcg@k` | Default `k=10`; `k` configurable per study via `studies.objective.k` |
| `map` | Mean Average Precision (full-recall when `studies.objective.k` omitted; `map@k` when set) |
| `precision@k` | `precision@10` is the convention; `k` follows `studies.objective.k` |
| `recall@k` | Same `k` |
| `mrr` | Mean Reciprocal Rank (k ignored — always full-recall) |

ERR@k is deferred to MVP2 (pytrec_eval doesn't ship it; reserved for the
metric-expansion alongside CMA-ES per [`infra_optuna_eval` spec §3](../02_product/planned_features/infra_optuna_eval/feature_spec.md)).

Studies declare a single primary `objective.metric` (the value Optuna optimizes against) and the others are recorded for analysis. The primary metric is denormalized into `trials.primary_metric` (REAL) for fast sort.

### Judgment input format

Judgments are stored as `(judgment_list_id, query_id, doc_id, rating, source)` tuples per [`data-model.md` §"`judgments`"](data-model.md). pytrec_eval expects:

```python
qrels = {
    "<query_id>": {"<doc_id>": <int rating>, ...},
    ...
}
run = {
    "<query_id>": {"<doc_id>": <float score>, ...},
    ...
}
metrics = pytrec_eval.RelevanceEvaluator(qrels, {"ndcg_cut_10", "map", "P_10", ...}).evaluate(run)
```

Ratings in `0..3` (graded) or `0..1` (binary). pytrec_eval is configured per metric to handle each.

## Worker job: `run_trial`

The Arq job that executes one trial. Implemented in
[`backend/workers/trials.py`](../../backend/workers/trials.py) (lands with
`infra_optuna_eval`).

Per the spec §11 orchestrator-vs-worker contract, the worker does NOT call
`study.ask()` or `suggest_*` — Phase 2's orchestrator does both before
enqueue. The worker loads the in-flight trial via `study.trials[N]` and
calls `study.tell(integer_trial_number, value)` (the integer form, NOT a
`FrozenTrial`):

```python
async def run_trial(ctx, study_id: UUID, optuna_trial_number: int) -> None:
    """
    Hot-path Arq job. Loads the pre-allocated Optuna trial, renders + executes
    + scores, writes a `trials` row, calls `study.tell(number, value)`.
    """
    # 0.  Open session; pre-generate trial_id (UUIDv7) for the app row PK +
    #     structlog binding.
    # 1a. App-row idempotency — if a terminal trials row exists for
    #     (study_id, optuna_trial_number), return no-op.
    # 1b. Load study.trials[optuna_trial_number] (sync; wrapped in
    #     asyncio.to_thread); if state.is_finished(), reconstruct the app
    #     row from the cached Optuna state — NO re-run of search/score.
    # 2.  Happy path: load adapter / template / queries / qrels;
    #     render N native queries; single `_msearch` via search_batch;
    #     score; compute primary via objective_metric_key();
    #     await asyncio.to_thread(study.tell, optuna_trial_number, primary);
    #     INSERT trials row.
    # 3.  Trial-level failure (adapter/render/score raises BEFORE tell):
    #     tell(state=FAIL); write status='failed' row; return normally.
    # 4.  Infra-level failure (Postgres lost, Redis lost): re-raise so Arq
    #     retries with backoff.
```

Retrieval depth (`top_k` passed to `adapter.search_batch`) derives from
`study.objective.k` when present, falling back to a default of 100 when k
is absent (the case for `map` without a cut, or `mrr` which ignores k).

**Concurrency:** N worker processes consume the `trials` Arq queue. Each handles one trial at a time. Optuna's RDB locking serializes the `ask()`/`tell()` calls correctly across workers.

**Failure modes** persisted to `trials.status` and `trials.error`:

- `complete` — successful trial; metrics in `trials.metrics`
- `failed` — adapter raised, scoring raised, or render raised; `error` field captures the exception
- `pruned` — Optuna's pruner short-circuited the trial mid-evaluation (only on multi-step trials, which MVP1 doesn't have — reserved for MVP2 when intermediate pruning checkpoints arrive)

## Cross-references

- Stack choices (Optuna + pytrec_eval pinned in `pyproject.toml`): [`tech-stack.md`](tech-stack.md)
- `studies` and `trials` schemas: [`data-model.md`](data-model.md)
- Search engine execution path: [`adapters.md`](adapters.md)
- Service topology (worker pool consuming the `trials` queue): [`system-overview.md`](system-overview.md)
- MVP1 navigation summary: [`mvp1-overview.md`](mvp1-overview.md)
- Owning feature: [`infra_optuna_eval/feature_spec.md`](../02_product/planned_features/infra_optuna_eval/feature_spec.md)

## Reserved for later releases

| Capability | Activates at | Why deferred |
|---|---|---|
| CMA-ES sampler (selectable per study) | MVP2 | TPE is sufficient for MVP1's low-dim search spaces; CMA-ES becomes valuable when adopters tune ≥7 continuous parameters. |
| Intermediate-step pruning (truly active `MedianPruner`) | MVP2 | Requires multi-step trials (e.g., evaluate after each query batch); MVP1 trials evaluate once per (params, full query set). |
| Multi-objective optimization (Pareto fronts via NSGA-II) | v2 | Single scalar objective is sufficient through GA v1; multi-objective adds product complexity (which Pareto trade-off do you ship?). |
| Click-derived judgments from Fusion Signals | v1.5+ | Requires Fusion adapter (MVP3) + Signals enabled in the user's deployment. The judgment `source = 'click'` enum value is reserved from MVP1 forward; the converter plug-ins land at v1.5+. |
| LLM+signals hybrid judgments | v1.5+ | Same — depends on Fusion Signals integration. |
