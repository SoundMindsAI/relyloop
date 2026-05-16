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
