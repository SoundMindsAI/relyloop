// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Glossary — single source of truth for tooltip / popover copy across the UI.
 *
 * SOURCE-OF-TRUTH POLICY: every group of entries whose key mirrors a backend
 * enum carries a `// Source-of-truth: <backend/path.py> <Symbol>` comment
 * immediately above it, mirroring the established pattern in `ui/src/lib/enums.ts`.
 *
 * User-visible copy fields (`short`, `long`, `ariaLabel`) MUST NOT contain
 * backend file paths, symbol names, or implementation jargon — the audience
 * is a relevance engineer using the product. AC-12 test in
 * `ui/src/__tests__/lib/glossary.test.ts` enforces this.
 *
 * Length bounds (FR-5 of the spec):
 *   - `short`: ≤ 140 chars (used in InfoTooltip).
 *   - `long`:  ≤ 800 chars; supports a minimal Markdown subset
 *              (paragraphs, bullet lists, inline code).
 */

export interface GlossaryEntryShort {
  short: string;
  ariaLabel?: string;
}
export interface GlossaryEntryLong {
  long: string;
  ariaLabel?: string;
}
export interface GlossaryEntryDual {
  short: string;
  long: string;
  ariaLabel?: string;
}
export type GlossaryEntry = GlossaryEntryShort | GlossaryEntryLong | GlossaryEntryDual;

// =============================================================================
// Glossary entries
// =============================================================================

export const glossary = {
  // -------------------------------------------------------------------------
  // Create-study modal (FR-6)
  // -------------------------------------------------------------------------

  'study.target': {
    short:
      'The Elasticsearch index or OpenSearch collection name the study will tune against (e.g., "products").',
    ariaLabel: 'More information about target index',
  },
  'study.template': {
    short:
      'A reusable parameterized query. Pick the version that matches the query shape you want to optimize.',
    ariaLabel: 'More information about query template',
  },

  // -------------------------------------------------------------------------
  // Create-study Step-4 search space (chore_create_study_wizard_polish FR-5)
  //
  // The parent `study.search_space` entry is dual — InfoTooltip reads `short`,
  // HelpPopover reads `long`. The three subkeys (`.param_spec`, `.log`,
  // `.cardinality`) are short-only forward-compatibility hooks for
  // `feat_create_study_search_space_builder` per spec §11 decision log.
  // -------------------------------------------------------------------------
  'study.search_space': {
    short:
      'The query parameters the study will tune, with a type (float / int / categorical) and bounds for each. Pre-filled from the template.',
    long: [
      'A search space defines **which** query parameters the study will tune and **what values** to try for each.',
      '',
      'Each parameter has a type and bounds:',
      '',
      '- `float` — continuous value between `low` and `high`. Add `log: true` for log-scale sampling.',
      '- `int` — whole number between `low` and `high` (inclusive on both ends).',
      '- `categorical` — pick from a fixed `choices` list (strings, numbers, or booleans).',
      '',
      '**Log scale** helps when the range spans more than 10× (e.g. boosts from 0.5 to 10) — it samples small values as densely as large ones.',
      '',
      '**Cardinality cap:** the total number of combinations must stay under 1,000,000. Floats count as 100 each, ints as `high - low + 1`, categoricals as the number of choices. The product across all parameters must fit under the cap.',
    ].join('\n'),
    ariaLabel: 'More information about the search space',
  },
  'study.search_space.param_spec': {
    short:
      'Each parameter is float (continuous), int (whole numbers), or categorical (pick from a fixed list).',
    ariaLabel: 'More information about parameter types',
  },
  'study.search_space.log': {
    short:
      'Use log scale when the range spans more than 10× (e.g. 0.5–10). It samples small values as densely as large ones.',
    ariaLabel: 'More information about log-scale sampling',
  },
  'study.search_space.cardinality': {
    short:
      'Total combinations must stay under 1,000,000. Floats count as 100; ints as high - low + 1; categoricals as the number of choices.',
    ariaLabel: 'More information about the cardinality cap',
  },

  // Source-of-truth: backend/app/api/v1/schemas.py ObjectiveMetric
  // (mirrored in ui/src/lib/enums.ts OBJECTIVE_METRIC_VALUES). FR-4 parity
  // test enforces key parity against OBJECTIVE_METRIC_VALUES.
  'study.metric': {
    long: [
      'Pick the metric the study optimizes:',
      '',
      '- `ndcg` — Normalized Discounted Cumulative Gain. Rewards placing relevant docs at the top. Best default for ranked retrieval.',
      '- `map` — Mean Average Precision. Averages precision at each relevant-doc position. Good for recall + ordering.',
      '- `precision` — Fraction of top-k docs that are relevant. Use when "any relevant doc in top-k" matters more than order.',
      '- `recall` — Fraction of relevant docs in top-k. Use when missing a relevant doc is costly.',
      '- `mrr` — Mean Reciprocal Rank. Rewards finding the first relevant doc quickly. Best for known-item search.',
    ].join('\n'),
    ariaLabel: 'More information about metrics',
  },
  'study.metric.ndcg': {
    short:
      'NDCG rewards placing the most relevant docs at the top. Best default for ranked retrieval. Requires a top-k cutoff.',
  },
  'study.metric.map': {
    short:
      'Mean Average Precision over relevant-doc ranks. Top-k cutoff optional — set it for map@k, leave blank for full-recall MAP.',
  },
  'study.metric.precision': {
    short:
      'Fraction of top-k docs that are relevant. Use when "any relevant doc in top-k" matters most. Requires a top-k cutoff.',
  },
  'study.metric.recall': {
    short:
      'Fraction of relevant docs in top-k. Use when missing a relevant doc is costly. Requires a top-k cutoff.',
  },
  'study.metric.mrr': {
    short:
      'Mean Reciprocal Rank. Rewards finding the first relevant doc quickly. Best for known-item search. Top-k cutoff is not used.',
  },

  // Source-of-truth: backend/app/api/v1/schemas.py ObjectiveK
  'study.k': {
    short:
      'Cutoff position for ranked metrics. NDCG@10 evaluates the top 10 results. Required for NDCG / Precision / Recall.',
    ariaLabel: 'More information about k cutoff',
  },
  'study.k.1': { short: 'Top 1 result only. Rare; use when only the very top match counts.' },
  'study.k.3': { short: 'Top 3 results. Good for "above the fold" relevance.' },
  'study.k.5': { short: 'Top 5 results. Common for first-page relevance.' },
  'study.k.10': { short: 'Top 10 results. The standard default for ranked-retrieval evaluation.' },
  'study.k.20': { short: 'Top 20 results. Use when result lists scroll beyond one page.' },
  'study.k.50': { short: 'Top 50 results. Suited for recall-heavy use cases.' },
  'study.k.100': { short: 'Top 100 results. Useful for deep-recall evaluation.' },

  // Source-of-truth: backend/app/api/v1/schemas.py ObjectiveDirection
  'study.direction': {
    short:
      'Maximize for relevance metrics (higher = better). Minimize only when optimizing an error or cost metric.',
    ariaLabel: 'More information about direction',
  },
  'study.direction.maximize': {
    short:
      'Higher metric values are better. Default for relevance metrics like NDCG, MAP, Precision.',
  },
  'study.direction.minimize': {
    short: 'Lower metric values are better. Use only when optimizing an error or cost metric.',
  },

  'study.max_trials': {
    short:
      'Trials to run before stopping. Sized by search-space dimensionality: ~50 for 1–2 params, 200 for 3–5, 500–1000 for 6+.',
    long: "TPE's diminishing returns kick in past these counts. With default parallelism=4 and ~1s/trial cost on a small query set, 200 trials completes in under a minute; on a managed cluster with a large query set it's more like 25 minutes (wall-clock estimates measured against the local dev stack — production clusters may vary).",
    ariaLabel: 'More information about max trials',
  },
  'study.time_budget_min': {
    short:
      'Wall-clock safety cap, in minutes. Optional. Set this only if you want a hard ceiling on a slow cluster.',
    long: 'Trials in RelyLoop are typically cheap (subsecond against local stacks, seconds against managed clusters), so the binding stop is almost always max_trials. Use this as a circuit breaker on managed clusters where per-trial cost might unexpectedly balloon.',
    ariaLabel: 'More information about time budget',
  },
  'study.preset': {
    short: 'Sized stop-condition recommendation matching your search-space dimensionality.',
    long: 'Focused (50 trials) — 1–2 params; smallest preset where MedianPruner activates (avoids the <50 NopPruner threshold). Standard (200) — 3–5 params, the typical case. Deep (1000 + 8h cap) — 6+ params, complex tuning. Custom — preserves manual edits.',
    ariaLabel: 'More information about study presets',
  },
  'study.parallelism': {
    short:
      'Number of trials to run concurrently. 4 is a sensible default; raise it if your search cluster has spare capacity.',
    ariaLabel: 'More information about parallelism',
  },
  'study.seed': {
    short:
      'Random seed for reproducibility. Same seed + same inputs = same trial sequence. Leave blank for non-deterministic runs.',
    ariaLabel: 'More information about random seed',
  },

  // Source-of-truth: backend/app/eval/types.py SamplerKind
  'study.sampler': {
    long: [
      'The sampler decides which parameter values to try on each trial.',
      '',
      '- `tpe` — Tree-structured Parzen Estimator. Models which regions of the search space produce good metrics and proposes new trials weighted toward those regions. The right default for most studies.',
      '- `random` — Uniform random sampling. Use as a baseline to sanity-check that TPE is actually converging, or when the search space is small enough that randomness covers it cheaply.',
    ].join('\n'),
    ariaLabel: 'More information about sampler',
  },
  'study.sampler.tpe': {
    short:
      'Tree-structured Parzen Estimator. Learns from earlier trials to propose promising new ones. The right default.',
  },
  'study.sampler.random': {
    short:
      'Uniform random sampling. Useful as a convergence baseline or when the search space is small.',
  },

  // Source-of-truth: backend/app/eval/types.py PrunerKind
  'study.pruner': {
    long: [
      'The pruner can cut a trial short before it finishes if its intermediate results look unpromising.',
      '',
      '- `median` — Prune a trial if its current best metric is worse than the median of completed trials at the same step. Saves cluster time on clearly-bad parameter choices.',
      '- `none` — No pruning; every trial runs to completion. Use when each trial is fast and you want full visibility into the space.',
    ].join('\n'),
    ariaLabel: 'More information about pruner',
  },
  'study.pruner.median': {
    short:
      'Cut a trial if its running metric is worse than the median of completed trials. Saves cluster time.',
  },
  'study.pruner.none': {
    short:
      'Every trial runs to completion. Use when each trial is fast and you want full visibility.',
  },

  // -------------------------------------------------------------------------
  // Study header (FR-7)
  // -------------------------------------------------------------------------

  // Source-of-truth: backend/app/api/v1/schemas.py StudyStatusWire
  'study.status.queued': {
    short:
      'Queued and waiting for a worker. Will start within a minute when capacity is available.',
    ariaLabel: 'Study status: queued',
  },
  'study.status.running': {
    short: 'Actively running trials. The trials table refreshes every few seconds.',
    ariaLabel: 'Study status: running',
  },
  'study.status.completed': {
    short: 'All trials finished. A digest and proposal have been generated.',
    ariaLabel: 'Study status: completed',
  },
  'study.status.cancelled': {
    short:
      'Cancelled by an operator before completing. Any trials that finished still count toward the digest.',
    ariaLabel: 'Study status: cancelled',
  },
  'study.status.failed': {
    short: 'Aborted by an error. See "Failed reason" below for details.',
    ariaLabel: 'Study status: failed',
  },

  'study.best_metric': {
    short:
      'The best metric value any trial achieved so far. Direction is set by the study’s objective.',
    ariaLabel: 'More information about best metric',
  },
  'study.best_metric.saturated': {
    short:
      'Pinned at metric ceiling (≥0.99). Usually means judgments are too sparse to differentiate trials, not a real optimizer win.',
    ariaLabel: 'More information about ceiling-saturated metric',
  },
  'study.trials_summary': {
    short:
      'Counts of trials by terminal status. Complete = finished and scored; Failed = errored; Pruned = cut short by the pruner.',
    ariaLabel: 'More information about trial counts',
  },

  // -------------------------------------------------------------------------
  // Study clone (feat_study_clone_from_previous spec §11 / FR-13)
  // -------------------------------------------------------------------------

  'study.clone_button': {
    short:
      "Open the create-study form pre-filled with this study's settings. Useful for iterating with narrowed bounds or a different objective.",
    ariaLabel: 'About the Clone study button',
  },
  'study.cloned_from_banner': {
    short:
      'This study will be created as a fork of the linked source. The lineage is recorded for future reference.',
    ariaLabel: 'About the cloned-from banner',
  },

  // feat_study_clone_narrow_bounds spec FR-13. Opt-in Step-4 checkbox that
  // rewrites the cloned search_space ±20% around the source's winning values.
  'study.narrow_bounds_checkbox': {
    short:
      "Tightens each numeric range to ±20% around the source's winning values. Categoricals and missing-from-winner params are left untouched.",
    long: [
      "Each numeric `low`/`high` clamps to ±20% around the source's winning value (read from its recommended config). Narrowing never widens — clamps intersect with the original bounds.",
      '',
      '- `float` → `[winner × 0.8, winner × 1.2]`',
      '- `int` → same clamp, then rounded to integer bounds (`ceil` low, `floor` high — tightens inward to the nearest valid integer pair); single-value ranges (`low === high`) are valid',
      "- `categorical` → left untouched (choices aren't subsetted by the winning value)",
      '',
      '**Skipped:** params not in the winner, winners outside current bounds, log-uniform floats whose narrowed `low` would land at or below zero.',
      '',
      "**Uncheck to restore the source's bounds** — manual edits to the rewritten JSON are discarded.",
    ].join('\n'),
    ariaLabel: 'About the narrow-bounds checkbox',
  },

  // -------------------------------------------------------------------------
  // Trials table (FR-8)
  // -------------------------------------------------------------------------

  // Umbrella entry — defines what a trial IS. The other trial.* keys
  // describe specific fields. New operators land on the trials table
  // and need to know the concept before the field-level tooltips help.
  trial: {
    short:
      'One Optuna evaluation: a parameter combination run against the cluster and scored against the judgment list to produce one metric.',
    long: [
      "A **trial** is one concrete evaluation of a parameter combination — Optuna's unit of work.",
      '',
      'For each trial, RelyLoop:',
      '',
      "1. Picks parameter values (e.g., `title_boost=1.98`) via Optuna's TPE sampler, which learns from prior trials' scores.",
      '2. Renders them into the query template → a real ES / OpenSearch query.',
      '3. Runs that query for every query in the query set → ranked results.',
      '4. Scores each result list against the judgment list (e.g., ndcg@10), averaging across queries → one number.',
      '',
      "That number is the trial's **primary metric**. A study runs `max_trials` of these (typically 10-200); the best-scoring trial's parameters become the **proposal**.",
    ].join('\n'),
    ariaLabel: 'More information about Optuna trials',
  },

  // Source-of-truth: backend/app/api/v1/schemas.py TrialStatusWire
  'trial.status': {
    short:
      'Per-trial terminal status: complete (finished and scored), failed (errored), or pruned (cut short).',
    ariaLabel: 'More information about trial status',
  },
  'trial.status.complete': {
    short: 'Trial ran to completion and produced a primary-metric score.',
  },
  'trial.status.failed': {
    short: 'Trial errored mid-run (e.g., cluster timeout, bad parameter combination). Not scored.',
  },
  'trial.status.pruned': {
    short:
      'Trial cut short by the pruner because its intermediate metric was unpromising. Not scored.',
  },

  'trial.primary_metric': {
    short: 'Score on the metric the study is optimizing. Higher (or lower for minimize) = better.',
    ariaLabel: 'More information about primary metric',
  },
  'trial.duration_ms': {
    short: 'Wall-clock time the trial spent running, in milliseconds.',
    ariaLabel: 'More information about trial duration',
  },
  'trial.params': {
    short:
      'The search-space parameter values used for this trial. Combined with the template to render the actual search query.',
    ariaLabel: 'More information about trial params',
  },

  // Source-of-truth: backend/app/db/repo/trial.py TrialSortKey
  // (re-exported by backend/app/api/v1/schemas.py:181)
  'trial.sort_by': {
    short: 'Sort order. `primary_metric_desc` = best score first; `ended_at_desc` = newest first.',
    ariaLabel: 'More information about sort order',
  },
  'trial.sort.primary_metric_desc': {
    short: 'Sort by primary metric, best score first. The default for inspecting top trials.',
  },
  'trial.sort.primary_metric_asc': {
    short: 'Sort by primary metric, worst score first. Useful for diagnosing what went wrong.',
  },
  'trial.sort.ended_at_desc': { short: 'Sort by completion time, newest first.' },
  'trial.sort.ended_at_asc': { short: 'Sort by completion time, oldest first.' },
  'trial.sort.optuna_trial_number_asc': {
    short: 'Sort by trial number ascending — the order the sampler generated them.',
  },

  // -------------------------------------------------------------------------
  // Digest panel (FR-9)
  // -------------------------------------------------------------------------

  'digest.narrative': {
    short:
      'LLM-generated summary of what the study found — which parameters mattered, what improved the metric, and what to try next.',
    ariaLabel: 'More information about digest narrative',
  },
  'digest.parameter_importance': {
    short:
      'Importance scores (0–1) showing how much each parameter influenced the metric. Higher bars = more influence.',
    ariaLabel: 'More information about parameter importance',
  },
  'digest.metric_delta': {
    short:
      'Baseline score → best score, with the percentage change. Sign and direction depend on the study’s objective.',
    ariaLabel: 'More information about metric delta',
  },
  'digest.recommended_config': {
    short:
      'JSON of the parameter values that produced the best metric. Becomes the PR body when you open a proposal.',
    ariaLabel: 'More information about recommended config',
  },
  'digest.suggested_followups': {
    short:
      'Next-study suggestions from the LLM, based on which parameters mattered most. Treat as hypotheses, not commands.',
    ariaLabel: 'More information about suggested follow-ups',
  },
  'digest.open_pr_button': {
    short:
      'Open a GitHub PR with the recommended config in the cluster’s config repo. An operator merges the PR to deploy.',
    ariaLabel: 'More information about open PR',
  },
  'digest.open_pr_disabled': {
    short: 'The digest hasn’t produced a pending proposal yet. Check back in a minute, or refresh.',
    ariaLabel: 'More information about open PR (no pending proposal)',
  },

  // -------------------------------------------------------------------------
  // Phase 2 — Judgments review page
  // -------------------------------------------------------------------------

  'judgment.relevance': {
    short:
      'How relevant the document is to the query, on a 0–3 scale. Used as the ground truth that studies optimize against.',
    ariaLabel: 'More information about relevance rating',
  },

  // Source-of-truth: backend/app/api/v1/schemas.py RatingWire
  // (mirrored in ui/src/lib/enums.ts RATING_VALUES).
  'judgment.rating.0': { short: 'Not relevant — the document does not match the query intent.' },
  'judgment.rating.1': {
    short: 'Marginally relevant — tangentially related but not a useful answer.',
  },
  'judgment.rating.2': { short: 'Relevant — answers the query reasonably well.' },
  'judgment.rating.3': { short: 'Highly relevant — the best possible answer for this query.' },

  'judgment.source': {
    short:
      'Where the rating came from: an LLM judge (`llm`), a human reviewer (`human`), or inferred from click logs (`click`).',
    ariaLabel: 'More information about judgment source',
  },

  // Source-of-truth: backend/app/api/v1/schemas.py JudgmentSourceWire
  // (mirrored in ui/src/lib/enums.ts JUDGMENT_SOURCE_VALUES).
  'judgment.source.llm': {
    short: 'Rated by the LLM judge worker against the rubric in the judgment list.',
  },
  'judgment.source.human': {
    short: 'Rated manually — either via the Override button or imported as ground truth.',
  },
  'judgment.source.click': {
    short: 'Inferred from production click logs. Lower confidence than human or LLM ratings.',
  },

  'judgment.override_button': {
    short:
      'Replace this rating with your own. Override ratings have `source=human` and take precedence over LLM ratings in the next study.',
    ariaLabel: 'More information about overriding a rating',
  },
  'judgment.source_filter': {
    short:
      'Show only ratings from one source. "All" includes overrides + LLM ratings together; "human" shows only your overrides.',
    ariaLabel: 'More information about source filter',
  },
  'judgment.calibration': {
    long: [
      'Calibration measures how well the LLM judge agrees with a sample of human ratings.',
      '',
      'Paste a CSV (`query_id,doc_id,rating`) or JSON array of human-rated samples. The server computes two agreement scores:',
      '',
      "- **Cohen's κ** — chance-adjusted agreement on the categorical rating. Treats 0/1/2/3 as unordered labels.",
      '- **Weighted κ** — same idea, but penalizes "off by 2" more than "off by 1". The right metric for ordinal ratings like ours.',
      '',
      'Interpretation:',
      '',
      '- κ ≥ 0.7 — strong agreement; the LLM judge is reliable.',
      '- 0.4 ≤ κ < 0.7 — moderate agreement; usable but inspect the rubric.',
      '- κ < 0.4 — needs calibration; revise the rubric or switch metrics.',
    ].join('\n'),
    ariaLabel: 'More information about calibration scores',
  },

  // -------------------------------------------------------------------------
  // feat_ubi_judgments — UBI converter + readiness glossary (Story 4.1)
  // -------------------------------------------------------------------------
  // Source-of-truth: backend/app/api/v1/schemas.py UbiConverterKind +
  // JudgmentGenerationMethodWire.
  'judgment.converter': {
    short:
      'How a judgment list is generated: LLM-as-judge, UBI from real clicks/dwell, or a hybrid (UBI head + LLM tail).',
    long: [
      'Three options for generating a judgment list:',
      '',
      '- **LLM-as-judge** — an LLM rates every (query, doc) pair against the operator rubric. Works on any cluster; costs OpenAI dollars per query.',
      '- **UBI (click-through / dwell-time)** — derives ratings from real user signal captured by the OpenSearch UBI plugin (or the o19s ES UBI fork). No LLM cost.',
      '- **Hybrid UBI + LLM** — UBI rates pairs above the impression threshold; the LLM fills the long tail. Requires both a template and a rubric.',
    ].join('\n'),
    ariaLabel: 'More information about judgment-generation methods',
  },
  // Source-of-truth: backend/app/api/v1/schemas.py JudgmentGenerationMethodWire.
  'judgment.converter.llm': {
    long: [
      '**LLM-as-judge** — asks an LLM (your configured OpenAI-compatible endpoint) to rate every (query, doc) pair against the operator-supplied rubric.',
      '',
      '- Works on any cluster (no UBI install required).',
      '- Costs per query (gated by the daily budget).',
      "- The rubric is what's evaluated — a vague rubric produces vague ratings.",
    ].join('\n'),
    ariaLabel: 'More information about the LLM-as-judge converter',
  },
  // Source-of-truth: backend/app/api/v1/schemas.py UbiConverterKind.
  'judgment.converter.ubi': {
    long: [
      '**UBI (click-through / dwell-time)** — derives ratings from real user signal captured by the OpenSearch UBI plugin (or the o19s ES UBI fork).',
      '',
      '- No LLM cost.',
      '- Reflects what users actually do (click, dwell), not what an LLM thinks they should do.',
      '- Sparse pairs (few impressions) get rating 0; switch to **Hybrid** if you want the LLM to fill the long tail.',
    ].join('\n'),
    ariaLabel: 'More information about UBI converters',
  },
  // Source-of-truth: backend/app/api/v1/schemas.py UbiConverterKind.
  'judgment.converter.hybrid': {
    long: [
      '**Hybrid UBI + LLM** — UBI rates pairs above an impression threshold; the LLM fills below-threshold pairs against the rubric.',
      '',
      "- Cheapest path that covers the long tail. UBI handles the head (no LLM cost) and the LLM only spends tokens on the pairs that don't have enough behavioral signal.",
      '- Requires both a template (for retrieval) and a rubric (for the LLM-fill ratings).',
    ].join('\n'),
    ariaLabel: 'More information about the hybrid UBI + LLM converter',
  },
  // Source-of-truth: backend/app/api/v1/schemas.py UbiReadinessRungWire.
  'cluster.ubi_readiness': {
    long: [
      '**UBI readiness rungs** — how much UBI traffic this cluster has captured for the chosen target index and query set:',
      '',
      '- **rung_0** — UBI plugin is not installed on this cluster (or `ubi_queries` index does not exist).',
      '- **rung_1** — UBI traffic captured but below the minimum events threshold (default 100) — too sparse for meaningful ratings on its own.',
      '- **rung_2** — Enough UBI traffic for meaningful ratings (≥ 100 events, < 500 events).',
      '- **rung_3** — Dense UBI traffic (≥ 500 events) — the picker defaults to a pure UBI converter at this rung.',
    ].join('\n'),
    ariaLabel: 'More information about UBI readiness rungs',
  },
  // Source-of-truth: backend/app/services/demo_ubi_seed.py
  // DEMO_UBI_SCENARIO_ALLOWLIST + ui/src/lib/demo-data.ts
  // DEMO_SYNTHETIC_UBI_CLUSTER_SLUGS (feat_demo_ubi_study_comparison
  // Story 3.1 / FR-7).
  ubi_synthetic_demo_data: {
    short:
      'This UBI data was fabricated by the demo reseed to demonstrate the UBI path; it is not real user behavior.',
    ariaLabel: 'More information about synthetic demo UBI data',
  },

  // -------------------------------------------------------------------------
  // Phase 2 — Proposals
  // -------------------------------------------------------------------------

  // Source-of-truth: backend/app/api/v1/schemas.py ProposalStatusWire
  // (mirrored in ui/src/lib/enums.ts PROPOSAL_STATUS_VALUES).
  'proposal.status.pending': {
    short: 'Generated from a study but no PR opened yet. Click "Open PR" to advance.',
  },
  'proposal.status.pr_opened': {
    short: 'A GitHub PR exists in the config repo. Operator review is the next step.',
  },
  'proposal.status.pr_merged': {
    short: 'The config-repo PR merged — your CI is responsible for deploying it.',
  },
  'proposal.status.rejected': {
    short: 'Rejected by an operator. See "Rejected reason" for context; no PR will be opened.',
  },

  // Source-of-truth: backend/app/api/v1/schemas.py ProposalPrStateWire
  // (mirrored in ui/src/lib/enums.ts PROPOSAL_PR_STATE_VALUES).
  'proposal.pr_state.open': { short: 'GitHub PR is open and awaiting review.' },
  'proposal.pr_state.closed': { short: 'GitHub PR was closed without merging.' },
  'proposal.pr_state.merged': {
    short: 'GitHub PR merged — deployment now depends on your CI.',
  },

  'proposal.open_pr_button': {
    short:
      "Open a GitHub PR with this proposal's config diff in the cluster's config repo. Operator merge triggers deployment.",
    ariaLabel: 'More information about opening a PR',
  },
  'proposal.config_diff.key': {
    short: 'The parameter the study tuned — typically a template parameter or query-time setting.',
    ariaLabel: 'More information about config-diff Key',
  },
  'proposal.config_diff.from': {
    short: "The baseline value, taken from the study's baseline trial.",
    ariaLabel: 'More information about config-diff From',
  },
  'proposal.config_diff.to': {
    short: 'The recommended value — what the best-scoring trial used.',
    ariaLabel: 'More information about config-diff To',
  },
  'proposal.metric_delta': {
    short:
      'Baseline score → best score for the metric the study optimized. Sign reflects the direction (maximize vs minimize).',
    ariaLabel: 'More information about metric delta',
  },
  'proposal.suggested_followups': {
    short:
      "LLM-generated next-study hypotheses based on this study's parameter-importance pattern. Click to seed a new study.",
    ariaLabel: 'More information about suggested follow-ups',
  },
  // feat_digest_executable_followups Story 5.3 — five glossary keys for
  // the per-card kind badges, the Run button, and the search-space diff
  // toggle on the rewritten SuggestedFollowupsPanel.
  // Source-of-truth: backend/app/domain/study/followups.py NarrowFollowup
  'proposal.followup_kind_narrow': {
    short:
      "The study's winning configuration sits in a sub-region of the prior search space. This followup re-runs with a tighter range to confirm.",
    ariaLabel: 'More information about narrow follow-ups',
  },
  // Source-of-truth: backend/app/domain/study/followups.py WidenFollowup
  'proposal.followup_kind_widen': {
    short:
      'The winning configuration hit an edge of the prior search space. This followup re-runs with a broader range to find a better setting.',
    ariaLabel: 'More information about widen follow-ups',
  },
  // Source-of-truth: backend/app/domain/study/followups.py TextFollowup
  'proposal.followup_kind_text': {
    short:
      'A free-form suggestion from the LLM. Needs operator interpretation — no auto-prefill available.',
    ariaLabel: 'More information about text follow-ups',
  },
  'proposal.followup_run_button': {
    short:
      'Opens the create-study wizard pre-filled with this followup’s settings. You can review and edit before submitting.',
    ariaLabel: 'More information about the run-followup button',
  },
  'proposal.followup_search_space_diff': {
    short: "Compare this followup's proposed search space against the parent study's.",
    ariaLabel: 'More information about the search-space diff',
  },
  // Source-of-truth: backend/app/domain/study/followups.py SwapTemplateFollowup
  'proposal.followup_kind_swap_template': {
    short:
      'Try a different query template. Shared params keep LLM bounds; new params get heuristic defaults you can edit.',
    ariaLabel: 'More information about swap-template follow-ups',
  },
  'proposal.followup_declared_params_diff': {
    short:
      'Compare parent template params to swap target. Shared keep LLM bounds; new get defaults; dropped are removed.',
    ariaLabel: 'More information about the declared-params diff',
  },
  'proposal.status_filter': {
    short:
      'Filter the proposals list by lifecycle state. "All" shows every proposal regardless of where it is in the open-PR / merge flow.',
    ariaLabel: 'More information about status filter',
  },
  'proposal.source_filter': {
    short:
      'Filter by how the proposal was created. "study" = digest-generated from a completed study; "manual" = operator-authored.',
    ariaLabel: 'More information about source filter',
  },

  // feat_config_repo_baseline_tracking FR-7 + FR-9 — Currently live indicator.
  // Source-of-truth: backend/app/db/models/config_repo.py
  // ConfigRepo.last_merged_proposal_id (the pointer column).
  'proposal.currently_live': {
    short:
      'This proposal is the most recently merged PR for its config repo — assumed live in production.',
    ariaLabel: 'More information about the Currently live badge',
  },
  // Source-of-truth: backend/app/api/v1/proposals.py ?is_last_merged=true filter.
  'proposal.currently_live_filter': {
    short: 'Show only proposals tracked as the live config in their repo.',
    ariaLabel: 'More information about the Currently live only filter',
  },

  // -------------------------------------------------------------------------
  // Phase 3 — Cluster registration
  // -------------------------------------------------------------------------

  'cluster.auth_kind': {
    short:
      'How RelyLoop authenticates to the cluster. Elasticsearch uses API keys or HTTP basic; OpenSearch uses HTTP basic or AWS SigV4.',
    ariaLabel: 'More information about auth kind',
  },

  // Source-of-truth: backend/app/api/v1/schemas.py AuthKind
  // (mirrored in ui/src/lib/enums.ts AUTH_KIND_VALUES).
  'cluster.auth_kind.es_apikey': {
    short:
      'Elasticsearch API key (preferred for ES 8.x+). Faster than basic auth and supports fine-grained roles.',
  },
  'cluster.auth_kind.es_basic': {
    short: 'Elasticsearch HTTP basic (username + password). Use when API keys are not available.',
  },
  'cluster.auth_kind.opensearch_basic': {
    short:
      'OpenSearch HTTP basic (username + password). Works with the OpenSearch security plugin.',
  },
  'cluster.auth_kind.opensearch_sigv4': {
    short:
      'AWS SigV4 for OpenSearch on AWS managed service. Uses IAM roles, not username/password.',
  },
  'cluster.auth_kind.solr_basic': {
    short: 'Apache Solr HTTP basic via the BasicAuthPlugin. Configure users in security.json.',
  },
  'cluster.auth_kind.solr_apikey': {
    short:
      'Apache Solr 9+ JWT through the JWTAuthPlugin. The credential file holds the bearer token.',
  },

  'cluster.environment': {
    short:
      'Which deployment environment this cluster represents. Used for display + filtering only — does not change cluster behavior.',
    ariaLabel: 'More information about environment',
  },

  // Source-of-truth: backend/app/api/v1/schemas.py Environment
  // (mirrored in ui/src/lib/enums.ts ENVIRONMENT_VALUES).
  'cluster.environment.prod': {
    short:
      'Production. Tune carefully — RelyLoop never writes to your cluster, but the proposals it generates target it.',
  },
  'cluster.environment.staging': {
    short: 'Pre-production. The right place to dry-run new templates before they reach prod.',
  },
  'cluster.environment.dev': { short: 'Local or scratch cluster. Safe to experiment freely.' },

  'cluster.credentials_ref': {
    long: [
      'Credentials are mounted from `./secrets/<name>` on the host into the API container as Docker secrets, then read at startup.',
      '',
      '**How to set up:**',
      '',
      '1. Create a YAML file at `./secrets/cluster_credentials.yaml` on the host.',
      '2. Add an entry keyed by the name you put in this field. For example, if you enter `es-apikey` here, the file needs an `es-apikey:` block with the credential fields.',
      '3. For HTTP basic, use `username` + `password` keys; for API keys, use `api_key`.',
      '4. The API container reads the secret at startup — no restart needed for new entries, but the value cannot change while a container is running.',
      '',
      'Never check credentials into git. The `./secrets/` directory is gitignored except for `.gitkeep`.',
    ].join('\n'),
    ariaLabel: 'More information about credentials reference',
  },

  // -------------------------------------------------------------------------
  // feat_index_document_browser Stories 3.1 — 3.4
  // (cluster-detail Indices card, index summary page, documents list page).
  // -------------------------------------------------------------------------

  'cluster.indices_card': {
    short:
      'Indices (or collections) on this cluster. Click an index to view its schema, browse documents, or see studies targeting it.',
    ariaLabel: 'More information about indices on this cluster',
  },
  'cluster.target_doc_count': {
    short:
      'Approximate document count reported by the engine. Not refreshed on every page load — recently indexed documents may not appear yet.',
    ariaLabel: 'More information about the document count',
  },
  'target.schema': {
    short:
      'The fields and field types Elasticsearch / OpenSearch has mapped for this index. Drawn from the live cluster, not from configs.',
    ariaLabel: 'More information about the index schema',
  },
  'target.schema_analyzer': {
    short:
      'The text analyzer applied to this field at index time. "—" means the default analyzer or a non-text field type.',
    ariaLabel: 'More information about field analyzers',
  },
  'document.truncation_sentinel': {
    short:
      'This value was truncated for the list view because it exceeds 8 KiB. Open the document detail view to see the full value.',
    ariaLabel: 'More information about truncated previews',
  },

  // -------------------------------------------------------------------------
  // DataTable primitive (feat_data_table_primitive Story 2.8)
  // -------------------------------------------------------------------------

  'datatable.sort.toggle': {
    short: 'Click to sort ascending. Click again to reverse, click a third time to clear.',
    ariaLabel: 'More information about sorting',
  },
  'datatable.search.min_length': {
    short: 'Type at least 2 characters to search by name.',
    ariaLabel: 'More information about search',
  },
  'datatable.total_count': {
    short: 'The total across all pages matching the current filter.',
    ariaLabel: 'More information about total count',
  },
  'datatable.density.toggle': {
    short: 'Switch between comfortable and compact row heights.',
    ariaLabel: 'More information about density',
  },
  'datatable.column_visibility': {
    short: 'Show or hide columns. Choices persist on this device.',
    ariaLabel: 'More information about column visibility',
  },
  'datatable.selection.all_on_page': {
    short: 'Select all rows on this page. Selection clears when you change page.',
    ariaLabel: 'More information about row selection',
  },

  // ---------------------------------------------------------------------------
  // feat_pr_metric_confidence Story 2.2 — 6 confidence-panel entries.
  // Text lifted verbatim from feature_spec.md §11 "Tooltips and contextual
  // help" so reviewers can spot drift without leaving the glossary.
  // Source-of-truth comment per CLAUDE.md "Enumerated Value Contract
  // Discipline" — keys map to ConfidenceShape sub-fields exposed on
  // StudyDetail.
  // ---------------------------------------------------------------------------
  'confidence.ci_95': {
    short:
      'Bootstrap 95% confidence interval on the headline metric. 1000 resamples with replacement over per-query scores.',
    ariaLabel: 'More information about the 95% confidence interval',
  },
  'confidence.runner_up_gap': {
    short:
      'How close other top trials came to the winner. Robust plateau = many near-equivalents; sharp peak = winner isolated.',
    long: [
      '**Robust plateau** — the top min(10, complete trials) are all within 0.005 of the winner. Many near-equivalent configs exist; the winning lift is reproducible across small perturbations.',
      '',
      '**Sharp peak** — at least one trial in that top set is farther than 0.005 below the winner. The winner is isolated and the result is sensitive to small parameter changes.',
    ].join('\n'),
    ariaLabel: 'More information about the runner-up gap',
  },
  'confidence.late_trial_stddev': {
    short:
      'Standard deviation of the primary metric over the last 20% of completed trials — the empirical noise floor.',
    ariaLabel: 'More information about the late-trial noise floor',
  },
  'confidence.convergence_regime': {
    short: 'How the winning trial sits in the optimization budget.',
    long: [
      '**Early-and-held** — best found in the first half of the trial budget AND at least one trial in the last 25% finished within 0.005 of the winner (plateau held). Strong signal.',
      '',
      '**Late-rising** — best found in the last 10% of the budget. More trials may still help; the optimizer was still improving.',
      '',
      '**Noisy** — neither pattern holds. No clear convergence; consider re-running with a different sampler or wider search space.',
    ].join('\n'),
    ariaLabel: 'More information about the convergence regime',
  },
  'confidence.per_query_outcomes': {
    short:
      'Per-query metric vs the runner-up. Threshold: NDCG/P/R = 0.01; MAP/MRR = 0.02. Within → Unchanged.',
    ariaLabel: 'More information about per-query outcomes',
  },
  'confidence.comparison_against': {
    short:
      'Comparison reference. "Baseline" = the no-tuning baseline trial (preferred). "Runner-up" = the second-best Optuna trial (fallback).',
    ariaLabel: 'More information about the comparison reference',
  },
  'trials.is_baseline': {
    short:
      'A no-tuning trial run before Optuna started, using your production params. Used as the comparison reference for the confidence outcomes.',
    ariaLabel: 'More information about baseline trials',
  },

  // ---------------------------------------------------------------------------
  // feat_study_convergence_indicator Story 4.1 — 3 convergence-panel entries.
  // Text from feature_spec.md §11 tooltip inventory (FR-8). Distinct from the
  // `confidence.convergence_regime` entry above — that classifies the
  // *winner-trial timing*, these classify the *metric plateau*. Both surfaces
  // coexist on /studies/[id].
  // Source-of-truth: backend/app/domain/study/convergence.py
  //   - convergence_verdict → ConvergenceVerdict Literal
  //   - convergence_window  → CONVERGENCE_FLAT_WINDOW
  //   - convergence_curve   → classify_convergence algorithm
  // ---------------------------------------------------------------------------
  convergence_verdict: {
    short:
      'Did the optimizer finish learning? Converged = plateau held; Still improving = stopped mid-climb; Too few trials = below the warmup floor.',
    long: [
      '**Converged** — the best-so-far metric improved by less than 0.005 over the last 20 completed trials. The optimizer settled; more trials would not meaningfully help.',
      '',
      '**Still improving when it stopped** — the best-so-far metric was still climbing in the last 20 trials. The study is likely under-budgeted; consider re-running with the next-larger preset (Standard 200 → Deep 1000).',
      '',
      '**Too few trials to tell** — the study ran below the TPE warmup floor (50 trials). The optimizer never left random-search; treat the result as preliminary and re-run with at least Standard.',
      '',
      'See [`docs/03_runbooks/convergence-verdict.md`](/docs/03_runbooks/convergence-verdict.md) for the full interpretation guide.',
    ].join('\n'),
    ariaLabel: 'More information about the convergence verdict',
  },
  convergence_curve: {
    short:
      'Best-metric-so-far plotted against trial number. Flat tail = converged; rising tail = still improving when the study stopped.',
    ariaLabel: 'More information about the best-so-far convergence curve',
  },
  convergence_window: {
    short:
      'The last 20 completed trials the verdict compares against. Smaller for short studies (clamps to max(5, total/5)).',
    ariaLabel: 'More information about the trailing-window comparison',
  },

  // ---------------------------------------------------------------------------
  // feat_studies_convergence_visibility Story 1.2 — studies-list trial count.
  // Source-of-truth: backend/app/api/v1/schemas.py StudySummary.trial_count
  //   (mirrors trials_summary.total — non-baseline optimization trials).
  // ---------------------------------------------------------------------------
  'study.trial_count': {
    short:
      'Number of optimization trials this study ran (the baseline trial is counted separately). More trials = more of the search space explored.',
    ariaLabel: 'More information about the trial count',
  },

  // ---------------------------------------------------------------------------
  // feat_auto_followup_studies Story 3.1 — 4 chain-panel + wizard entries.
  // Text from feature_spec.md §11 tooltip inventory. Mirrors the FR-9
  // catalog (auto_followup_* events) where the chain semantics are
  // defined.
  // ---------------------------------------------------------------------------
  auto_followup_depth: {
    short:
      'Run up to N follow-up studies after this one completes. Each follow-up narrows the search space around the winner.',
    long: [
      'When set, RelyLoop automatically chains studies overnight: after a study completes, the next study uses `propose_search_space(prior_study_id=…)` to narrow numeric bounds ±50% around the prior winner, then runs deterministically.',
      '',
      'The chain halts on any of: no lift over the baseline (winner ≤ baseline + 0.5%); the daily LLM budget would exceed 80%; the parent study terminated abnormally (5 consecutive failures, no-signal cutoff, or operator cancel); or the depth counter hits 0.',
      '',
      'Every chain member still produces a manual-review proposal — no PR opens automatically.',
    ].join('\n'),
    ariaLabel: 'More information about auto-followup depth',
  },
  // feat_overnight_autopilot FR-6 — wizard control reframed as the overnight
  // autopilot path; `short` ≤ 120 chars, contains the verbatim human-merge
  // phrase "you still open every PR".
  overnight_autopilot: {
    short:
      'Run additional studies overnight, each narrowing in on the previous winner. Stops on its own; you still open every PR.',
    long: [
      'When you enable this, RelyLoop runs follow-up studies automatically after each study completes — every follow-up narrows the search space around the previous winner and runs deterministically while you sleep.',
      '',
      'The chain stops on its own: when there is no further improvement, when the daily LLM budget caps out, when a study fails, or when the depth counter hits zero.',
      '',
      'RelyLoop never opens a pull request automatically. The chain ends with a proposal you review — you still open every PR.',
    ].join('\n'),
    ariaLabel: 'More information about the overnight autopilot',
  },
  // feat_overnight_final_solution Story 1.2 / FR-9 — new key for the Strategy
  // <Select> directly beneath the overnight depth selector. Two wire values
  // ('narrow' / 'follow_suggestions') are quoted verbatim in `short` so the
  // frontend mapping never drifts silently from the backend allowlist.
  // AC-16 value-lock at ui/src/__tests__/lib/glossary.test.ts.
  overnight_strategy: {
    short:
      'How follow-ups are picked. "narrow": tighter bounds, same knobs. "follow_suggestions": digest\'s top runnable item.',
    long: [
      'Choose how the autopilot picks the next study in an overnight chain.',
      '',
      '**Refine the same knobs ("narrow"):** each follow-up tightens the search space around the previous winner on the same template. Predictable, deterministic, and the safer default.',
      '',
      '**Try suggested follow-ups ("follow_suggestions"):** each follow-up acts on the parent digest\'s top runnable recommendation, which may switch knobs (`widen`) or templates (`swap_template`). A cycle guard prevents the chain from ping-ponging between templates. When the digest has no runnable suggestion, the chain falls back to the narrow behavior so it never stalls.',
      '',
      'Either way: RelyLoop never opens a pull request on your behalf — the chain ends with a proposal you review and merge.',
    ].join('\n'),
    ariaLabel: 'More information about the overnight strategy choice',
  },
  auto_followup_chain: {
    short:
      'RelyLoop ran follow-up studies automatically based on this study’s winner. Each follow-up narrowed the search bounds.',
    long: [
      'The chain links a sequence of studies via `studies.parent_study_id`. Each child re-uses the parent’s cluster, target, template, query set, judgment list, and objective; only the search space narrows around the prior winner.',
      '',
      'The chain ends when there’s no further lift, when the daily LLM budget is exhausted, when a study fails, or when the depth counter reaches 0.',
      '',
      'To stop a running chain, navigate to the currently in-flight study (the most recent non-terminal member) and use Cancel — the cascade will halt any pending children.',
    ].join('\n'),
    ariaLabel: 'More information about the auto-followup chain',
  },
  lift_gate: {
    short:
      'A follow-up only enqueues when the parent’s winner beat the first-decile baseline by at least 0.5%. Smaller lifts are likely noise.',
    ariaLabel: 'More information about the lift gate',
  },
  auto_followup_budget_skip: {
    short:
      'Daily LLM budget is near its cap — follow-up chains are paused until the budget resets at UTC midnight.',
    ariaLabel: 'More information about auto-followup budget skip',
  },
} as const satisfies Record<string, GlossaryEntry>;

// =============================================================================
// Derived types
// =============================================================================

export type GlossaryKey = keyof typeof glossary;

/** Keys whose entry includes a `short` string — usable by `InfoTooltip`. */
export type ShortGlossaryKey = {
  [K in keyof typeof glossary]: (typeof glossary)[K] extends { short: string } ? K : never;
}[keyof typeof glossary];

/** Keys whose entry includes a `long` string — usable by `HelpPopover`. */
export type LongGlossaryKey = {
  [K in keyof typeof glossary]: (typeof glossary)[K] extends { long: string } ? K : never;
}[keyof typeof glossary];

// =============================================================================
// Test helpers (FR-4)
// =============================================================================

/**
 * Returns every glossary key that starts with `${prefix}.` (excluding the
 * aggregate `prefix` key itself). Used by the parity test to enumerate
 * per-wire-value entries for a given enum group.
 */
export function listGlossaryKeysWithPrefix(prefix: string): string[] {
  return Object.keys(glossary).filter((k) => k.startsWith(prefix + '.') && k !== prefix);
}

/**
 * Asserts the glossary contains exactly the per-wire-value keys expected for
 * a given enum group (FR-4 / AC-5). Throws on the first violation so the
 * vitest test reports a clear message.
 *
 * @param prefix dotted prefix matching the parity-key naming convention
 *               (e.g., 'study.status', 'trial.sort', 'study.metric').
 * @param wireValues the canonical readonly array from `ui/src/lib/enums.ts`
 *                   (e.g., `STUDY_STATUS_VALUES`, `OBJECTIVE_K_VALUES`).
 */
export function expectGlossaryGroundedAgainstEnums(
  prefix: string,
  wireValues: readonly (string | number)[],
): void {
  const present = new Set(listGlossaryKeysWithPrefix(prefix));
  const expected = new Set(wireValues.map((v) => `${prefix}.${String(v)}`));
  for (const key of expected) {
    if (!present.has(key)) {
      throw new Error(`glossary parity: missing key ${key}`);
    }
  }
  for (const key of present) {
    if (!expected.has(key)) {
      throw new Error(`glossary parity: unexpected key ${key} (not in ${prefix} allowlist)`);
    }
  }
}
