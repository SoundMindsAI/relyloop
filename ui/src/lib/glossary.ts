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
      '- `err` — Expected Reciprocal Rank. Models a user who stops at the first useful doc; penalizes redundancy.',
    ].join('\n'),
    ariaLabel: 'More information about metrics',
  },
  'study.metric.ndcg': {
    short:
      'NDCG rewards placing the most relevant docs at the top. Best default for ranked retrieval.',
  },
  'study.metric.map': {
    short:
      'Mean Average Precision. Averages precision at each relevant-doc position. Good for recall + ordering.',
  },
  'study.metric.precision': {
    short:
      'Fraction of top-k docs that are relevant. Use when "any relevant doc in top-k" matters more than order.',
  },
  'study.metric.recall': {
    short:
      'Fraction of relevant docs that make it into top-k. Use when missing a relevant doc is costly.',
  },
  'study.metric.mrr': {
    short:
      'Mean Reciprocal Rank. Rewards finding the first relevant doc quickly. Best for known-item search.',
  },
  'study.metric.err': {
    short:
      'Expected Reciprocal Rank. Models a user who stops at the first useful doc; penalizes redundancy.',
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
      'Maximum number of trials to run. 100–500 is typical for 3 search-space parameters; raise it for larger spaces.',
    ariaLabel: 'More information about max trials',
  },
  'study.time_budget_min': {
    short:
      'Stop the study after this many minutes, even if max trials would allow more. Either gate alone is fine; both apply when both are set.',
    ariaLabel: 'More information about time budget',
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
  'study.trials_summary': {
    short:
      'Counts of trials by terminal status. Complete = finished and scored; Failed = errored; Pruned = cut short by the pruner.',
    ariaLabel: 'More information about trial counts',
  },

  // -------------------------------------------------------------------------
  // Trials table (FR-8)
  // -------------------------------------------------------------------------

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
