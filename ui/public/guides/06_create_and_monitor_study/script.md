# Create and monitor a study

> 5-minute walkthrough — the core Karpathy loop end-to-end.

A "study" is one Optuna optimization run against a query set + judgment
list. RelyLoop's Optuna orchestrator uses the TPE sampler by default,
proposes parameter sets, the worker runs each trial (renders the template
→ searches the cluster → scores via `ir_measures`), and the study
terminates when budget (max_trials or time_budget_min) is exhausted.

## The 5-step create-study form

1. **Cluster + target** — which cluster's index are you tuning against?
2. **Query set + judgment list** — which queries + ratings to score against?
3. **Template** — the parameterized query DSL
4. **Search space + study name** — JSON dict of `{param_name: {type, low, high, log?}}`
5. **Objective + budget** — metric (ndcg, map, precision, recall, mrr, err),
   k for top-K metrics, direction (maximize/minimize), max_trials and/or
   time_budget_min, sampler (tpe / random), pruner (median / none)

The form validates the FK chain (judgment_list.query_set_id MUST match the
selected query_set; template engine_type MUST match the cluster's
engine_type) before it lets you submit.

## Monitoring

The detail page polls `GET /api/v1/studies/{id}` every 3 seconds while the
study is running and pauses polling on terminal states. The trials table
sorts by `primary_metric_desc` by default — so the best trial is always
on top.

Once the study reaches a terminal state, the **Confidence** panel
appears between the study header and the trials table. It surfaces:

- **Headline metric** — the winner's score, with a 95% bootstrap CI band
  when at least 5 completed queries carry per-query metrics. With fewer
  queries (or older studies whose trials predate
  `feat_pr_metric_confidence`), the CI band is omitted and you'll see
  the bare headline — a legitimate partial shape, not an error.
- **Per-query outcomes** — counts of Improved / Unchanged / Regressed
  queries versus the runner-up trial, with the named regressors
  revealed on click. The thresholds are 0.01 for NDCG / Precision /
  Recall and 0.02 for MAP / MRR; deltas within that band count as
  Unchanged.
- **Runner-up gap** — labels the result as `Robust plateau` (top trials
  cluster within 0.005 of the winner — winner is reproducible) or
  `Sharp peak` (winner is isolated and sensitive to small parameter
  changes). Add a `Convergence regime` callout (`Early-and-held` /
  `Late-rising` / `Noisy`) once the budget is large enough for one to
  resolve.

See [glossary: confidence](/guide/glossary#confidence.ci_95) and
[FAQ: My confidence interval is missing — why?](/guide/faq#confidence-ci-missing)
for the operator-judgment context behind these signals.

## Cancellation

Click **Cancel study** in the action bar to fire
`POST /api/v1/studies/{id}/cancel`. In-flight trials complete cleanly;
no new trials enqueue. The orchestrator transitions to `cancelled` within
~30 seconds.

## Reference

- API create: `POST /api/v1/studies` with `{name, cluster_id, target, template_id, query_set_id, judgment_list_id, search_space, objective, config}`
- API cancel: `POST /api/v1/studies/{id}/cancel`
- API trials: `GET /api/v1/studies/{id}/trials?sort=primary_metric_desc`
- Worker entry: [`backend/workers/orchestrator.py`](../../backend/workers/orchestrator.py)
- Sampler config: [`docs/01_architecture/optimization.md`](../01_architecture/optimization.md)

> See the [glossary](/guide/glossary) for definitions of every term used in this walkthrough.
