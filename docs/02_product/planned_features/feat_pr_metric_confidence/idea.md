# PR Metric Confidence — per-query variance, runner-up gap, and named regressors in the digest + PR body

**Date:** 2026-05-20
**Status:** Idea — surfaced during a 2026-05-20 conversation reviewing two outside articles for relevance to RelyLoop ([Doug Turnbull, "Autoresearching a better MSMarco BM25", 2026-05-17](https://softwaredoug.com/blog/2026/05/17/autoresearching-a-better-msmarco-bm25) and [Li/Wang/Wang, "Choosing the Better Bandit Algorithm under Data Sharing", arXiv:2507.11891v2](https://arxiv.org/pdf/2507.11891)). The articles themselves are not directly material to RelyLoop's roadmap; what surfaced as material — after several rounds of honest filtering — is the underlying question they prompted: **how confident should the approver be in the metric reported on the PR?**
**Origin:** Conversation chain: (a) "are these articles relevant?" → "Doug's piece suggests holdout discipline" → "holdout is not actually right for RelyLoop's persona" → "the real concern is approver confidence in the PR metric" → "RelyLoop already computes per-query dispersion data and throws it away." See standalone plan note at `~/.claude/plans/review-this-codebase-and-abundant-kite.md` for full reasoning trail.
**Depends on:** None. The schema change is additive (one JSONB column on `trials`, nullable, no backfill). No in-flight feature blocks this.

## Problem

When the operator's approver opens a study-backed PR in the central search-config repo, the only confidence signal in the PR body is two scalar point estimates. From [`_render_pr_body_study_backed`](../../../../backend/workers/git_pr.py) at `backend/workers/git_pr.py:488`:

```
## Metric delta
- ndcg@10: 0.71 → 0.84 (+18.3%)

## Config diff
| Param | From | To | ...

## Suggested follow-ups
...

## Parameter importance
[chart]
```

The PR body does NOT show: runner-up gap, convergence trajectory, trial-to-trial noise floor, per-query win/loss breakdown, named regressor queries, or any bootstrap CI on the headline metric. The approver cannot tell from the PR alone:

1. **Whether the winner is fragile or robust.** If the 2nd-best trial is 0.835 vs winner 0.84, the optimizer found a plateau and the winner is one of many near-equivalent configs (robust). If 2nd-best is 0.62, the winner is a sharp peak — possibly an artifact of TPE's exploration noise — and small param shifts would break it.
2. **Whether the lift is bigger than the noise floor.** A +0.13 lift means different things if late-trial 1σ is 0.02 vs 0.05. The current PR body provides no way to gauge.
3. **Whether the config silently breaks specific queries the operator cares about.** A config that lifts average NDCG by 0.13 by improving 18 queries +0.18 while regressing 2 queries from 0.92 → 0.40 may be the wrong choice — those 2 queries may be the operator's most commercially important ones. Approvers want regressor names, not just averages. This is *the* relevance-engineer concern in any config swap and is precisely what the PR body should surface.
4. **Whether the optimizer actually converged.** "Best found at trial 50 of 1000 then held" → confident. "Best found at trial 980 of 1000" → suggests the budget bound the answer, not the metric landscape.

Compounding this gap: [`backend/app/eval/scoring.py:194`](../../../../backend/app/eval/scoring.py) already computes per-query metrics for every trial (`{"aggregate": {...}, "per_query": {qid: {metric: value}}}`) via pytrec_eval. But [`backend/workers/trials.py:440`](../../../../backend/workers/trials.py) writes only `scored["aggregate"]` to `trials.metrics`. The `scored["per_query"]` dict is computed by pytrec_eval, used to compute the mean, and then dropped on the floor. The per-query signal RelyLoop most needs is being thrown away at the persistence boundary, every trial, on every study.

Zero references to `variance|std|stderr|confidence|bootstrap` exist anywhere in `backend/app/eval/`, `backend/app/services/`, `backend/workers/`, or `backend/app/domain/`. The single hit on "variance" in `calibration.py` is about LLM-judge inter-rater kappa — a different concept with no relation to trial metric dispersion.

The honest framing: RelyLoop's PR-to-config-repo handoff is the product's main value-delivery surface. The PR description is the artifact the approver bases their merge decision on. Today that artifact carries less confidence information than a relevance engineer needs to merge safely.

## Proposed capabilities

Tiered. Tier A ships from existing data; Tier B unlocks the highest-leverage signal (named regressors) with one schema change; Tier C is academic-correct but probably undersells real wins on small N — deferred for v2.

### Tier A — post-hoc analytics on existing `trials` data (no schema change)

These ship from the `trials` table as it stands today. Worker change zero; analytics live in a new domain helper consumed by the digest worker and PR template.

- **Runner-up gap.** `SELECT primary_metric FROM trials WHERE study_id = :s AND status = 'complete' ORDER BY primary_metric DESC NULLS LAST LIMIT 10`. Surface as: "Top 10 trials within 0.005 of winner — wide plateau, robust." vs "Winner separated from #2 by 0.04 — sharp peak." Phrasing chosen by a threshold rule the feature spec locks (likely `gap < 0.5 * (winner − baseline)` = robust).
- **Convergence trajectory.** Cummax of `primary_metric` over Optuna trial number. Surface as a textual call-out in the PR body ("Best metric found at trial 387 of 1000; held thereafter.") and a sparkline on the study-detail UI. Distinguish three regimes: (a) early-and-held (high confidence), (b) late and rising at budget exhaustion (low confidence — more trials warranted), (c) noisy across all trials (no clear winner — search-space probably ill-conditioned).
- **Late-trial noise floor.** Std of `primary_metric` over the last 20% of completed trials → empirical estimate of how much the metric varies between near-equivalent configs. Surface as: "headline lift +0.13 vs late-trial noise floor σ=0.018 (~7σ)." If lift is < 2σ above the noise floor, flag prominently as "marginal — may not reproduce."

### Tier B — persist `trials.per_query_metrics` (one JSONB column)

- **Schema:** add `trials.per_query_metrics JSONB NULL` via a new Alembic migration. Nullable because old trials don't have it and we don't backfill (trials cascade-delete with studies; old studies degrade gracefully — analytics just skip the per-query surfaces when the column is null). Migration is strictly additive; `downgrade()` drops the column. Schema shape: `{qid: {metric_name: float}}` matching `ScoreResult.per_query`'s shape from scoring.py.
- **Worker change:** at `backend/workers/trials.py:440`, write `per_query_metrics=scored["per_query"]` alongside `metrics=scored["aggregate"]`. One-line addition. No new computation — the data is already in `scored`.
- **New domain helpers** under `backend/app/domain/study/confidence.py`:
  - `compute_per_query_deltas(winner_per_q, baseline_per_q) -> dict[qid, float]` — per-query lift.
  - `classify_query_outcomes(deltas, threshold=0.01) -> {improved: int, unchanged: int, regressed: int}` — counts.
  - `top_regressors(deltas, query_lookup, n=5) -> list[{qid, query_text, delta}]` — biggest absolute-value negative deltas, joined to query text via the `queries` table.
  - `bootstrap_ci(per_query_values: list[float], n_resamples=1000, ci=0.95) -> tuple[float, float]` — resample with replacement, return percentile CI on the mean. Pure-Python numpy if `np.random.choice` is available; otherwise inline a small implementation. Likely scipy is already a transitive dep through pytrec_eval — feature spec verifies.
- **PR body section "## Confidence"** (new, between Metric delta and Config diff):
  - `ndcg@10 = 0.84 (95% CI 0.78–0.89, N=20 queries)` if Tier B data exists; falls back to "(N=20 queries)" without CI when running on old un-backfilled studies.
  - "Queries: 14 improved · 4 unchanged · 2 regressed" (only when baseline trial exists).
  - **Named regressors block**, when any: "Queries that regressed: `shipping policy` (0.92 → 0.71) · `wireless headphones` (0.85 → 0.78)." Cap at 5; link to study detail for full breakdown.
  - **Convergence + noise-floor lines** from Tier A.
- **Digest narrative prompt update:** [`prompts/digest_narrative.user.jinja`](../../../../prompts/digest_narrative.user.jinja) gets new XML blocks `<confidence>` (CI + late-trial σ + runner-up gap) and `<per_query_outcomes>` (counts + top regressors). [`prompts/digest_narrative.system.md`](../../../../prompts/digest_narrative.system.md) gains a paragraph: "Open with the headline delta, then a one-sentence confidence framing that mentions the CI, the per-query regressor count, and (if any) the worst-regressed query by name." The existing "Open with the headline metric delta" line in the system prompt becomes "Open with the headline metric delta + a confidence framing."
- **Study detail UI:** new `<ConfidencePanel>` component on `ui/src/app/studies/[id]/page.tsx`, positioned above the Trials table. Renders: CI band on the metric, per-query histogram bar (green/grey/red counts), regressor table with query text + delta. Probably 250 LOC frontend + tests.
- **Trials table column:** optional expandable per-query row for the winner trial (click chevron, see all `qid → metric` pairs). Cheap addition once `per_query_metrics` is persisted.

### Out of scope for v1 — capture as follow-ups if/when v1 ships

- **Wilcoxon signed-rank paired test** (winner vs baseline per-query). Theoretically correct but for typical 10–20 query studies the test rarely returns significant even when the lift is real, which produces a confusing UX. Defer until operators ask for it.
- **Multiple-comparison correction** across the 1000-trial budget. Theoretically the most-correct concern (running 1000 random samples and reporting the max is a classic multiple-testing problem) but the hardest to surface for non-statisticians. Defer; revisit if approver feedback flags inflated metrics.
- **Holdout-set discipline** (split the judgment list 80/20). This was the original direction floated during the surfacing conversation. Skipped in favor of in-sample variance because: (a) MVP1 judgment sets are too small for an 80/20 split to be statistically meaningful — a 4-query holdout has wild variance that misleads more than it informs; (b) enterprise relevance engineers often *want* to optimize on a curated set (no generalization claim is being made); (c) per-query regressor naming addresses the same approver-trust concern more directly without the small-N statistical fragility. Revisit at MVP4 if multi-tenant judgments routinely exceed 100 queries.

## Scope signals

- **Backend:** Tier A ~150 LOC (one domain helper + digest worker enrichment + PR template additions + unit tests). Tier B ~400 LOC (migration + worker change + ~200 LOC domain helpers + digest prompt updates + tests at unit / integration / contract layers).
- **Frontend:** ~300 LOC for the `<ConfidencePanel>` on study detail; the per-query expandable row on the trials table adds ~50 LOC. Smaller PR-body changes are server-rendered, so no frontend work for the PR description itself.
- **Migration:** one additive Alembic migration `00NN_trials_per_query_metrics` — adds `per_query_metrics JSONB` column to `trials`, nullable, no backfill, no index. Downgrade drops the column. Round-trip-clean per Absolute Rule #5.
- **Config:** none.
- **Audit events:** N/A (MVP1 has no audit_log; the digest worker's existing observability still applies).
- **New dependencies:** likely none — scipy is probably a transitive dep via pytrec_eval; if not, bootstrap CI can be implemented in ~10 lines of `random.choices`-based resampling. Feature spec verifies before adding to `pyproject.toml`.

## Why not implemented inline today

Three reasons:

1. **Cross-subsystem.** Touches backend domain + backend worker + Alembic migration + digest LLM prompt + PR template + frontend Confidence panel + tests at every layer. Far outside the inline-fix budget per [`CLAUDE.md`](../../../../CLAUDE.md) "Inline-fix vs idea-file rubric." Tier A alone could be inline if scoped carefully, but Tier A without Tier B's per-query regressors leaves the highest-leverage signal on the table — the bundle is the right unit.
2. **Real product-design surface.** Exact phrasing of the confidence framing in the digest narrative + the choice of which dispersion metrics to lead with (CI vs late-trial σ vs runner-up gap) + the regressor-threshold rule (how negative is "regressed"?) is a UX decision that needs spec-shaped scrutiny, not first-pass invention. Get this wrong and approvers either reject good configs (over-cautious framing) or merge bad ones (under-cautious framing).
3. **Statistical design surface.** Bootstrap CI parameters (N=1000? 10000?), regressor threshold (absolute delta? relative? per-metric?), late-trial-window definition (last 20%? last 50%? minimum-trial-count guard?) all benefit from a feature-spec review cycle and possibly a GPT-5.5 statistical review before implementation. These are not "obvious defaults" — different choices change what operators see.

## Relationship to other work

- **Supersedes a hypothetical `feat_study_holdout_split`** that was floated during the surfacing conversation and then deprioritized. Per-query in-sample variance and named regressors address the same approver-trust concern more directly without the small-N statistical fragility a holdout split would introduce at MVP1 judgment-set sizes.
- **Adjacent to [`feat_agent_propose_search_space`](../feat_agent_propose_search_space/idea.md)** (planned tool for the chat agent to propose a search space deterministically). Once this feature ships, that tool could optionally include "expected confidence band given historical study variance on similar templates" as part of its proposal.
- **Adjacent to [`feat_llm_judgments`](../../../00_overview/implemented_features/2026_05_11_feat_llm_judgments/)** (shipped). When judgments are LLM-generated, the per-query histogram lets the approver distinguish "config got worse on these queries" from "judge is inherently uncertain on these queries" (the latter being a calibration concern that already has its own surface). This composes cleanly.
- **Composes with [`feat_digest_proposal`](../../../00_overview/implemented_features/2026_05_11_feat_digest_proposal/)** (shipped). The digest narrative is the natural place for the confidence framing to live; the PR body inherits both the narrative and the structured "## Confidence" section.
- **Composes with [`feat_github_pr_worker`](../../../00_overview/implemented_features/2026_05_12_feat_github_pr_worker/)** (shipped). PR-body changes are localized to `_render_pr_body_study_backed` in `backend/workers/git_pr.py`; no changes to the PR-open lifecycle or auth surface.
