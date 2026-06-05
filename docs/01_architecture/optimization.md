# Optimization (Optuna + ir_measures)

**Status:** Adopted for MVP1. Single-objective TPE + median pruner; provider-abstracted IR evaluation via `ir_measures` (wraps multiple cut-aware-metric backends behind a typed metric-object DSL). Multi-objective optimization (CMA-ES + multi-metric) reserved for v2 per umbrella spec.
**Source of truth for product context:** [docs/00_overview/relyloop-spec.md §13–§14](../00_overview/relyloop-spec.md). Per-release timing per [`tech-stack.md` §"Canonical release matrix"](tech-stack.md).

---

## The optimization loop

A study runs N trials in parallel. Each trial:

1. **Ask** Optuna for a parameter combination (the sampler decides; TPE in MVP1).
2. **Render** the parameter combination into a native engine query via the configured `QueryTemplate` and `SearchAdapter` (per [`adapters.md` §"The Protocol"](adapters.md)).
3. **Execute** the query batch via `SearchAdapter.search_batch(target, queries, top_k)` against the registered cluster.
4. **Score** the result set with ir_measures against the configured `judgment_list`, computing the study's primary metric + secondary metrics.
5. **Tell** Optuna the metric value.
6. **Persist** the trial row (params + all metrics + duration_ms + status) per [`data-model.md` §"`trials`"](data-model.md).

Workers loop until the study's stop condition fires (max_trials hit, time_budget_min elapsed, or `studies.status` flips to `cancelled`).

## Optuna configuration

Per umbrella spec §13, defaults below ship in MVP1:

| Setting | MVP1 default | Activates / changes at |
|---|---|---|
| Storage | `RDBStorage` against the same Postgres instance, schema `optuna.*` | — |
| Sampler | `TPESampler` (Tree-structured Parzen Estimator) | CMA-ES selectable per study (≥7 continuous params, no categoricals) at MVP2; random sampler available as a baseline-comparison option from MVP1 |
| Pruner | `MedianPruner(n_warmup_steps=10)` | Studies with `max_trials < STUDIES_TPE_WARMUP_FLOOR` (= 50) disable pruning automatically (pruning needs warmup; small studies don't get enough signal). The constant lives in [`backend/app/eval/optuna_runtime.py`](../../backend/app/eval/optuna_runtime.py) and is mirrored in the create-study wizard as `SUB_WARMUP_FLOOR` (the Custom-mode sub-warmup warning trigger — `feat_study_sub_warmup_guard`); a `// Values must match` comment + a backend value-lock test (`test_studies_tpe_warmup_floor_constant_value`) catch cross-side drift. |
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

## ir_measures configuration

Per umbrella spec §14, RelyLoop **always** evaluates via `ir_measures` — never engine-native `_rank_eval`. Reasons:

- `ir_measures` (from the PyTerrier team) wraps multiple IR-evaluation backends behind a typed metric-object DSL (`nDCG@10`, `AP@5`, `RR`, `P@k`, `R@k`). The provider abstraction means swapping the underlying backend is a config change rather than a rewrite — protecting against future single-maintainer abandonment risk.
- ES `_rank_eval` and `ir_measures` don't always agree to many decimal places (different normalization conventions across engines).
- Per-query scores are inspectable, enabling deep debugging.
- Cross-engine comparability: the same metric semantics apply whether the underlying engine is Elasticsearch, OpenSearch, or Apache Solr.

### Supported metrics (MVP1)

Computed at trial time and stored in `trials.metrics` (JSONB):

| Metric | Notes |
|---|---|
| `ndcg@k` | Default `k=10`; `k` configurable per study via `studies.objective.k` |
| `map` | Mean Average Precision (full-recall when `studies.objective.k` omitted; `map@k` when set) |
| `precision@k` | `precision@10` is the convention; `k` follows `studies.objective.k` |
| `recall@k` | Same `k` |
| `mrr` | Mean Reciprocal Rank (k ignored — always full-recall) |

ERR@k is deferred to MVP2 (the cut-aware-metric backend wrapped by ir_measures doesn't ship it; reserved for the
metric-expansion alongside CMA-ES per [`infra_optuna_eval` spec §3](../00_overview/implemented_features/2026_05_10_infra_optuna_eval/feature_spec.md)).

Studies declare a single primary `objective.metric` (the value Optuna optimizes against) and the others are recorded for analysis. The primary metric is denormalized into `trials.primary_metric` (REAL) for fast sort.

### Judgment input format

Judgments are stored as `(judgment_list_id, query_id, doc_id, rating, source)` tuples per [`data-model.md` §"`judgments`"](data-model.md). `ir_measures` expects:

```python
qrels = {
    "<query_id>": {"<doc_id>": <int rating>, ...},
    ...
}
run = {
    "<query_id>": {"<doc_id>": <float score>, ...},
    ...
}
import ir_measures
from ir_measures import nDCG, AP, P
metrics_per_query = list(ir_measures.iter_calc([nDCG@10, AP, P@10], qrels, run))
# RelyLoop's backend/app/eval/scoring.py::score() re-keys the per-query
# results back to user-facing tokens (ndcg@10, map, precision@10) before
# returning — library wire-form metric-object reprs never leak past score().
```

Ratings in `0..3` (graded) or `0..1` (binary). `ir_measures` is configured per metric to handle each.

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

- `complete` — successful trial; metrics in `trials.metrics`, per-query in `trials.per_query_metrics`
- `failed` — adapter raised, scoring raised, or render raised; `error` field captures the exception; `per_query_metrics` stays NULL
- `pruned` — Optuna's pruner short-circuited the trial mid-evaluation (only on multi-step trials, which MVP1 doesn't have — reserved for MVP2 when intermediate pruning checkpoints arrive)

## Per-study confidence analytics (owned by `feat_pr_metric_confidence`)

On successful trials, the `run_trial` worker persists `scored["per_query"]`
(from `backend/app/eval/scoring.py::score()`) verbatim into
`trials.per_query_metrics`. The values are keyed by user-facing metric
tokens — `ndcg@10`, `map@10`, `mrr`, etc. — matching what
`objective_metric_key(study.objective)` resolves to.

Read-side enrichment lives at
[`backend/app/services/study_confidence.py::fetch_study_confidence`](../../backend/app/services/study_confidence.py) —
an async wrapper that runs the FR-2 4-query read pattern (winner trial,
runner-up trial, complete-trials projection by `optuna_trial_number`,
conditional `query_text` lookup for named regressors) and hands the
pre-fetched data to the pure-Python orchestrator
[`backend/app/domain/study/confidence.py::compute_study_confidence`](../../backend/app/domain/study/confidence.py).
The orchestrator returns a `ConfidenceShape` (bootstrap 95% CI on the
winner's per-query values, runner-up gap classification, late-trial 1σ,
convergence regime, per-query outcome counts) or `None` on every degraded
path per FR-7 — no raises. Three consumers compose this:

- `GET /api/v1/studies/{id}` — `_detail()` attaches the shape to
  `StudyDetail.confidence`.
- The `open_pr` Arq worker — emits a `## Confidence` PR-body section
  between `## Metric delta` and `## Config diff`.
- The digest narrative worker — serializes via `model_dump()` and feeds
  the two new `<confidence>` + `<per_query_outcomes>` Jinja blocks.

Locked thresholds (bootstrap N=1000, seed=42, plateau band 0.005,
late-trial window 20% / min 5, etc.) and regressor-classification deltas
live as module constants in
`backend/app/domain/study/confidence.py`. The full ConfidenceShape
contract is reviewed in [`feat_pr_metric_confidence/feature_spec.md`](../00_overview/implemented_features/2026_05_21_feat_pr_metric_confidence/feature_spec.md)
§7 (FR-4 / FR-4a) and §12 (AC-3 through AC-17).

## Where RelyLoop fits in your relevance pipeline (and what comes *before* it)

A search-relevance pipeline runs in stages, and RelyLoop deliberately operates at **one** of them. Knowing which stage matters, because the stage *before* RelyLoop is often where the biggest wins hide — and it is not something RelyLoop tunes.

| Stage | What it does | Owned by | RelyLoop? |
|---|---|---|---|
| 1. **Query understanding / normalization** | Transform the *incoming query string* before it hits the engine: lowercasing, whitespace trimming, contraction expansion (`what's` → `what is`), spelling correction, synonym/abbreviation expansion, intent/entity detection. Fixes *vocabulary mismatch*. | The operator's query-rewriting layer (e.g. Querqy, a preprocessing service) **or** the engine's analyzers | **No** (see below) |
| 2. **Retrieval** | Match the query against the index; pull candidate documents. | The engine, driven by the query template | RelyLoop *renders* the query here |
| 3. **Ranking / boosting** | Field boosts, function scores, tie-breakers, fuzziness, slop, `min_should_match`, rerankers. | Query-time parameters | **Yes — this is RelyLoop's tuning surface** |
| 4. **Re-ranking / business rules / personalization** | LTR rerank, pinned results, merchandising rules. | Operator (LTR consume-only in MVP2; rules are out of scope) | Partial (LTR consume-only) |

**RelyLoop tunes stage 3** — and, as of MVP2, a thin, opt-in slice of stage 1 (see "Normalizer tuning" below). By default it passes `query_text` through to the engine **verbatim** — no lowercasing, no trimming, no rewriting ([`ElasticAdapter.render`](../../backend/app/adapters/elastic.py); the template interpolates `{{ query_text }}` raw). A template that declares the reserved `query_normalizer` Categorical param opts into having the loop tune a bundled query-string transform.

Normalization splits into two mechanisms, both currently outside RelyLoop's tuning boundary, for *different* reasons:

- **Analyzer-level normalization** (lowercase, stemming, stopwords, synonyms as token filters) is governed by the index's **analyzers**, with index-time/query-time *symmetry* — the same analysis runs on documents at index time and on the query at search time. Changing it usually requires **reindexing**, which is why it sits behind the umbrella spec §4 non-goal: *"Make schema/mapping/analyzer changes. Tuning is restricted to query-time parameters."* RelyLoop *reads* analyzer names (the schema browser shows them) but never writes them. **This boundary is permanent.**
- **Pre-query rewriting** (contraction expansion, spell-correction, query expansion) is an *application-layer* transform of the query string before it reaches the engine. It does **not** require touching the cluster, so it is technically query-time — RelyLoop's domain. **MVP2 ships a bounded, opt-in slice of this** via the reserved `query_normalizer` param (see below); broader rewriting (spell-correction, synonyms, query expansion) remains the operator's query layer.

**Operator guidance:** do your query-understanding work (stage 1) *before* leaning on RelyLoop for stage 3. Ranking tuning cannot recover a query whose terms never matched the index in the first place — the canonical failure is an analyzer that strips `not` as a stopword, turning "not waterproof" into "waterproof". RelyLoop sharpens *how matched candidates are scored*; it does not fix *whether the query matched*.

### Normalizer tuning (MVP2)

Shipped by [`feat_query_normalization_tuning`](../00_overview/planned_features/02_mvp2/feat_query_normalization_tuning/feature_spec.md). A template opts in by declaring a reserved Categorical search-space param named **`query_normalizer`** whose `choices` are a subset of the four built-in normalizers: `none`, `lowercase`, `lowercase+trim`, `lowercase+trim+expand_contractions` (English, 30-entry contraction dictionary). The Optuna loop then searches over those choices like any other categorical, deciding empirically — on the operator's judgment set — which transform lifts the metric.

Mechanics:

- **Consumption is adapter-confined.** Only `ElasticAdapter.render` and `SolrAdapter.render` read `params["query_normalizer"]`; a pre-render hook normalizes `query_text` before it enters the Jinja context. The orchestrator, trial runner, baseline runner, and judgment generator pass the value through opaquely (invariant I-2). The pure-domain library lives in [`backend/app/domain/study/normalizers.py`](../../backend/app/domain/study/normalizers.py).
- **Production parity is documented, not engineered.** RelyLoop applies the normalizer only inside its own evaluation loop. The winning choice travels in the proposal's `config_diff` and surfaces in the PR body as a copy-pasteable Python snippet under an **"Operator-side requirement"** section — the operator replicates it in their query-serving layer to reproduce the gain. RelyLoop never touches the cluster.
- **Reserved, non-render key.** `query_normalizer` is consumed by the adapter, so a template body must **not** reference `{{ query_normalizer }}` (rejected at create time with `RESERVED_PARAM_REFERENCED`); it may declare it without referencing it.

## Cross-references

- Stack choices (Optuna + ir_measures pinned in `pyproject.toml`): [`tech-stack.md`](tech-stack.md)
- `studies` and `trials` schemas: [`data-model.md`](data-model.md)
- Search engine execution path: [`adapters.md`](adapters.md)
- Service topology (worker pool consuming the `trials` queue): [`system-overview.md`](system-overview.md)
- MVP1 navigation summary: [`mvp1-overview.md`](mvp1-overview.md)
- Owning feature: [`infra_optuna_eval/feature_spec.md`](../00_overview/implemented_features/2026_05_10_infra_optuna_eval/feature_spec.md)

## Reserved for later releases

| Capability | Activates at | Why deferred |
|---|---|---|
| CMA-ES sampler (selectable per study) | MVP2 | TPE is sufficient for MVP1's low-dim search spaces; CMA-ES becomes valuable when adopters tune ≥7 continuous parameters. |
| Intermediate-step pruning (truly active `MedianPruner`) | MVP2 | Requires multi-step trials (e.g., evaluate after each query batch); MVP1 trials evaluate once per (params, full query set). |
| Multi-objective optimization (Pareto fronts via NSGA-II) | v2 | Single scalar objective is sufficient through GA v1; multi-objective adds product complexity (which Pareto trade-off do you ship?). |
| UBI-derived judgments + hybrid UBI+LLM converter | MVP2 | Bundled with the Solr adapter in MVP2 (see [`feat_ubi_judgments/idea.md`](../00_overview/planned_features/02_mvp2/feat_ubi_judgments/idea.md)). The judgment `source = 'click'` enum value is reserved from MVP1 forward; the `UbiReader` + `SignalsConverter` land at MVP2. |
| Counterfactual click models (CCM, DBN) as additional `SignalsConverter` impls | Backlog | Require enough impressions per (query, doc) to be statistically valid; promoted out when post-MVP2 adopter traffic supports it. |
| Engine-native click readers (Elastic Behavioral Analytics) | Backlog | UBI covers the engine-neutral path for ES + OpenSearch + Solr. Elastic BA is a residual ES-shop bridge despite Elastic's 9.0 deprecation; landed when an adopter requires it. |
