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

## Study-page orientation surfaces

Above the panels, three surfaces help operators navigate without grepping UUIDs:

- **Linked entities row** — named, clickable links to the **cluster**,
  **query set**, **judgment list**, and **template** the study ran
  against. Click any to drill into the source of truth.
- **View-proposal link** — once a proposal has been promoted from this
  study, a `Proposal: view proposal (<status>)` link appears below the
  header for the round-trip from study → proposal.
- **Glossary `(i)` tooltips** — hover for short definitions on Target,
  Trials, Best metric, and every Confidence sub-heading. The Guide
  button (bottom-right) opens the full glossary.

## Reading the Confidence panel

Once the study reaches a terminal state, the **Confidence** panel
appears between the study header and the trials table. It answers
*"is this winner statistically reliable, or did Optuna get lucky on
one trial?"* The panel has four parts:

- **Headline metric + 95% CI band** — bootstrap CI, displayed when at
  least 5 completed queries carry per-query metrics. With fewer queries
  the bare headline shows and the CI band is omitted (a legitimate
  partial shape, not an error).
- **Per-query outcome chips** — counts of **Improved · Unchanged ·
  Regressed** queries vs. the runner-up trial (or baseline when one
  exists). Thresholds: 0.01 for NDCG / Precision / Recall, 0.02 for
  MAP / MRR; deltas within the band count as Unchanged.
- **Queries that improved** and **Queries that regressed** tables —
  named query text + winner score + comparison score + signed delta,
  each capped at 5 rows. Improvers are green (+delta); regressors are
  red (-delta). These tables are where an operator sees *which*
  workloads gained and lost, not just the aggregate.
- **Secondary callouts** — *runner-up gap* (`Robust plateau` when top
  trials cluster within 0.005 of the winner; `Sharp peak` when the
  winner is isolated), *late-trial 1σ*, and *convergence regime*
  (`Early-and-held` / `Late-rising` / `Noisy`).

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
