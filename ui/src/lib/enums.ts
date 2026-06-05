// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Canonical wire-value allowlists mirroring backend Literals.
 *
 * SOURCE-OF-TRUTH POLICY: every exported `as const` array in THIS FILE carries a
 * `// Values must match <backend/path.py> <Symbol>` comment immediately above it.
 * The Story 4.2 CI grep gate scans ONLY this file. Zod schemas and component
 * option lists consume the typed arrays via `z.enum(STUDY_STATUS_VALUES)` and
 * `STUDY_STATUS_VALUES.map(...)` — they don't repeat the comment.
 */

// Values must match backend/app/api/v1/schemas.py StudyStatusWire.
export const STUDY_STATUS_VALUES = [
  'queued',
  'running',
  'completed',
  'cancelled',
  'failed',
] as const;
export type StudyStatus = (typeof STUDY_STATUS_VALUES)[number];

// Values must match backend/app/api/v1/schemas.py TrialStatusWire.
export const TRIAL_STATUS_VALUES = ['complete', 'failed', 'pruned'] as const;
export type TrialStatus = (typeof TRIAL_STATUS_VALUES)[number];

// Values must match backend/app/api/v1/schemas.py TrialSortKey.
export const TRIAL_SORT_VALUES = [
  'primary_metric_desc',
  'primary_metric_asc',
  'ended_at_desc',
  'ended_at_asc',
  'optuna_trial_number_asc',
] as const;
export type TrialSort = (typeof TRIAL_SORT_VALUES)[number];

// Values must match backend/app/api/v1/schemas.py EngineTypeWire.
// `solr` added by infra_adapter_solr Story A11.
export const ENGINE_TYPE_VALUES = ['elasticsearch', 'opensearch', 'solr'] as const;
export type EngineType = (typeof ENGINE_TYPE_VALUES)[number];

// Values must match backend/app/api/v1/schemas.py AuthKind.
// `solr_basic` / `solr_apikey` added by infra_adapter_solr Story A11.
export const AUTH_KIND_VALUES = [
  'es_apikey',
  'es_basic',
  'opensearch_basic',
  'opensearch_sigv4',
  'solr_basic',
  'solr_apikey',
] as const;
export type AuthKind = (typeof AUTH_KIND_VALUES)[number];

// Values must match backend/app/api/v1/schemas.py Environment.
export const ENVIRONMENT_VALUES = ['prod', 'staging', 'dev'] as const;
export type Environment = (typeof ENVIRONMENT_VALUES)[number];

// Values must match backend/app/api/v1/schemas.py HealthStatusValue.
export const HEALTH_STATUS_VALUES = ['green', 'yellow', 'red', 'unreachable'] as const;
export type HealthStatus = (typeof HEALTH_STATUS_VALUES)[number];

// Values must match backend/app/eval/types.py SamplerKind.
// (Re-exported by backend/app/api/v1/schemas.py — eval/types.py is the canonical definition per spec §8.1.)
export const SAMPLER_VALUES = ['tpe', 'random'] as const;
export type SamplerKind = (typeof SAMPLER_VALUES)[number];

// Values must match backend/app/eval/types.py PrunerKind.
export const PRUNER_VALUES = ['median', 'none'] as const;
export type PrunerKind = (typeof PRUNER_VALUES)[number];

// Values must match backend/app/domain/study/convergence.py ConvergenceVerdict.
// Ordering matters — the value-lock vitest in
// ui/src/__tests__/lib/enums-convergence-discipline.test.ts asserts the exact
// array contents AND order to catch any silent drift on either side.
export const CONVERGENCE_VERDICT_VALUES = [
  'converged',
  'still_improving',
  'too_few_trials',
] as const;
export type ConvergenceVerdict = (typeof CONVERGENCE_VERDICT_VALUES)[number];

// Values must match backend/app/api/v1/schemas.py AUTO_FOLLOWUP_STRATEGY_VALUES.
// feat_overnight_final_solution Story 1.1 / D-13 — the backend Pydantic field is
// `str | None` (NOT a Literal) so the canonical AUTO_FOLLOWUP_STRATEGY_INVALID
// error envelope works; the enum tuple is the source of truth that both the
// backend validator and this frontend mirror cite. Value-lock vitest at
// ui/src/__tests__/lib/enums-overnight-strategy-discipline.test.ts asserts the
// exact array contents AND order.
export const OVERNIGHT_STRATEGY_VALUES = ['narrow', 'follow_suggestions'] as const;
export type OvernightStrategy = (typeof OVERNIGHT_STRATEGY_VALUES)[number];

// Values must match backend/app/domain/study/auto_followup_strategy.py SELECTED_FOLLOWUP_KIND_VALUES.
// feat_overnight_final_solution Story 3.2 / FR-6 — mirrors the additive
// `selected_followup_kind` field on StudyChainLink. `narrow_default` marks
// the follow_suggestions fallback path (operator picked suggestions but
// the autopilot fell back); the legacy/default narrow path persists no
// key at all per D-12 (the API field is null, no badge rendered).
// Value-lock vitest at
// ui/src/__tests__/lib/enums-selected-followup-kind-discipline.test.ts.
export const SELECTED_FOLLOWUP_KIND_VALUES = [
  'narrow_default',
  'narrow',
  'widen',
  'swap_template',
] as const;
export type SelectedFollowupKind = (typeof SELECTED_FOLLOWUP_KIND_VALUES)[number];

// Values must match backend/app/api/v1/schemas.py ObjectiveMetric.
// ERR@k is deferred to MVP2 per infra_optuna_eval feature_spec.md §3 / §FR-3 / §13;
// add it back here when scoring.py SUPPORTED_METRICS grows the entry.
export const OBJECTIVE_METRIC_VALUES = ['ndcg', 'map', 'precision', 'recall', 'mrr'] as const;
export type ObjectiveMetric = (typeof OBJECTIVE_METRIC_VALUES)[number];

// Values must match backend/app/domain/study/confidence.py ConvergenceRegime.
// Three regimes for the optimization convergence call-out on the
// ConfidencePanel + PR body's ## Confidence section.
export const CONVERGENCE_REGIME_VALUES = ['early_held', 'late_rising', 'noisy'] as const;
export type ConvergenceRegime = (typeof CONVERGENCE_REGIME_VALUES)[number];

// Values must match backend/app/domain/study/confidence.py RunnerUpClassification.
// Indicates whether the winner trial sits on a robust plateau (many
// near-equivalent configs in the top-10) or a sharp peak (winner isolated).
export const RUNNER_UP_CLASSIFICATION_VALUES = ['robust_plateau', 'sharp_peak'] as const;
export type RunnerUpClassification = (typeof RUNNER_UP_CLASSIFICATION_VALUES)[number];

// Values must match backend/app/domain/study/confidence.py ComparisonAgainst.
// Phase 1 always emits `runner_up`; `baseline` is reserved for Phase 2
// when the orchestrator runs a no-tuning baseline trial.
export const COMPARISON_AGAINST_VALUES = ['runner_up', 'baseline'] as const;
export type ComparisonAgainst = (typeof COMPARISON_AGAINST_VALUES)[number];

// Values must match backend/app/api/v1/schemas.py ObjectiveK.
export const OBJECTIVE_K_VALUES = [1, 3, 5, 10, 20, 50, 100] as const;
export type ObjectiveK = (typeof OBJECTIVE_K_VALUES)[number];

// feat_auto_followup_studies Story 3.2 wizard-facing depth options.
//
// Wizard-only values: the wizard NEVER sends wire-`0` (per FR-1 + D-12,
// wire-`0` is the worker-internal terminal-state value). The `0` here is
// the wizard's "Off" sentinel that maps to undefined at submit time.
//
// Source-of-truth (backend): backend/app/api/v1/schemas.py
// StudyConfigSpec.auto_followup_depth — validator enforces 0..5 with
// None|undefined meaning "off". The wizard restricts to the user-facing
// 0..5 subset where 0 = off and 1..5 = enabled depths.
export const AUTO_FOLLOWUP_DEPTH_WIZARD_VALUES = [0, 1, 2, 3, 4, 5] as const;
export type AutoFollowupDepthWizard = (typeof AUTO_FOLLOWUP_DEPTH_WIZARD_VALUES)[number];

// Values must match backend/app/api/v1/schemas.py ObjectiveDirection.
export const OBJECTIVE_DIRECTION_VALUES = ['maximize', 'minimize'] as const;
export type ObjectiveDirection = (typeof OBJECTIVE_DIRECTION_VALUES)[number];

// Values must match backend/app/api/v1/schemas.py JudgmentListStatusWire.
export const JUDGMENT_LIST_STATUS_VALUES = ['generating', 'complete', 'failed'] as const;
export type JudgmentListStatus = (typeof JUDGMENT_LIST_STATUS_VALUES)[number];

// Widened by feat_ubi_judgments FR-10 to include `click` so the UI's
// Source filter on judgment-list detail can surface UBI rows.
// Values must match backend/app/api/v1/schemas.py JudgmentSourceFilterWire.
export const JUDGMENT_SOURCE_FILTER_VALUES = ['llm', 'human', 'click'] as const;
export type JudgmentSourceFilter = (typeof JUDGMENT_SOURCE_FILTER_VALUES)[number];

// feat_ubi_judgments FR-9. Three UBI-specific converters consumed by
// POST /api/v1/judgments/generate-from-ubi.
// Values must match backend/app/api/v1/schemas.py UbiConverterKind.
export const UBI_CONVERTER_VALUES = ['ctr_threshold', 'dwell_time', 'hybrid_ubi_llm'] as const;
export type UbiConverter = (typeof UBI_CONVERTER_VALUES)[number];

// feat_ubi_judgments FR-9. Superset surfaced by the generate-judgments
// dialog's method picker — `llm` routes to POST /judgments/generate; the
// three UBI converters route to POST /judgments/generate-from-ubi.
// Values must match backend/app/api/v1/schemas.py JudgmentGenerationMethodWire.
export const JUDGMENT_GENERATION_METHOD_VALUES = [
  'llm',
  'ctr_threshold',
  'dwell_time',
  'hybrid_ubi_llm',
] as const;
export type JudgmentGenerationMethod = (typeof JUDGMENT_GENERATION_METHOD_VALUES)[number];

// feat_ubi_judgments FR-9. Returned by GET /api/v1/clusters/{id}/ubi-readiness.
// Values must match backend/app/api/v1/schemas.py UbiReadinessRungWire.
export const UBI_READINESS_RUNG_VALUES = ['rung_0', 'rung_1', 'rung_2', 'rung_3'] as const;
export type UbiReadinessRung = (typeof UBI_READINESS_RUNG_VALUES)[number];

// feat_ubi_judgments FR-9. `reject` is the default; per-query ambiguous
// mappings under `reject` are skipped + counted (NOT terminal).
// Values must match backend/app/api/v1/schemas.py UbiMappingStrategyWire.
export const UBI_MAPPING_STRATEGY_VALUES = ['reject', 'first_match', 'most_recent'] as const;
export type UbiMappingStrategy = (typeof UBI_MAPPING_STRATEGY_VALUES)[number];

// Values must match backend/app/api/v1/schemas.py JudgmentSourceWire.
export const JUDGMENT_SOURCE_VALUES = ['llm', 'human', 'click'] as const;
export type JudgmentSource = (typeof JUDGMENT_SOURCE_VALUES)[number];

// Values must match backend/app/api/v1/schemas.py RatingWire.
export const RATING_VALUES = [0, 1, 2, 3] as const;
export type Rating = (typeof RATING_VALUES)[number];

// Values must match backend/app/api/v1/schemas.py ProposalStatusWire.
export const PROPOSAL_STATUS_VALUES = [
  'pending',
  'pr_opened',
  'pr_merged',
  'rejected',
  'superseded',
] as const;
export type ProposalStatus = (typeof PROPOSAL_STATUS_VALUES)[number];

// Values must match backend/app/api/v1/schemas.py ProposalPrStateWire.
export const PROPOSAL_PR_STATE_VALUES = ['open', 'closed', 'merged'] as const;
export type ProposalPrState = (typeof PROPOSAL_PR_STATE_VALUES)[number];

// Values must match backend/app/api/v1/schemas.py ConfigRepoProviderWire.
export const CONFIG_REPO_PROVIDER_VALUES = ['github'] as const;
export type ConfigRepoProvider = (typeof CONFIG_REPO_PROVIDER_VALUES)[number];

// Values must match backend/app/api/v1/schemas.py MessageRoleWire.
export const MESSAGE_ROLE_VALUES = ['user', 'assistant', 'tool'] as const;
export type MessageRole = (typeof MESSAGE_ROLE_VALUES)[number];

// Values must match backend/app/api/v1/schemas.py SSEEventTypeWire.
export const SSE_EVENT_TYPE_VALUES = ['token', 'tool_call', 'tool_result', 'done'] as const;
export type SseEventType = (typeof SSE_EVENT_TYPE_VALUES)[number];

// =============================================================================
// DataTable sort-key arrays (feat_data_table_primitive Story 1.3)
//
// Each <Resource>_SORT_VALUES is the cross-product of sortable columns ×
// {asc, desc} accepted by GET /api/v1/<resource>?sort=<value>. Backend mirrors
// these in `backend/app/api/v1/schemas.py` as `<Resource>SortKey` Literals;
// the CI grep gate at `scripts/ci/verify_enum_source_of_truth.sh` enforces
// parity in both directions.
// =============================================================================

// Values must match backend/app/api/v1/schemas.py ClusterSortKey.
export const CLUSTER_SORT_VALUES = [
  'name:asc',
  'name:desc',
  'created_at:asc',
  'created_at:desc',
  'environment:asc',
  'environment:desc',
] as const;
export type ClusterSortKey = (typeof CLUSTER_SORT_VALUES)[number];

// Values must match backend/app/api/v1/schemas.py StudySortKey.
export const STUDY_SORT_VALUES = [
  'name:asc',
  'name:desc',
  'created_at:asc',
  'created_at:desc',
  'completed_at:asc',
  'completed_at:desc',
  'best_metric:asc',
  'best_metric:desc',
  'status:asc',
  'status:desc',
] as const;
export type StudySortKey = (typeof STUDY_SORT_VALUES)[number];

// Values must match backend/app/api/v1/schemas.py QuerySetSortKey.
export const QUERY_SET_SORT_VALUES = [
  'name:asc',
  'name:desc',
  'created_at:asc',
  'created_at:desc',
] as const;
export type QuerySetSortKey = (typeof QUERY_SET_SORT_VALUES)[number];

// Values must match backend/app/api/v1/schemas.py QueryTemplateSortKey.
export const QUERY_TEMPLATE_SORT_VALUES = [
  'name:asc',
  'name:desc',
  'created_at:asc',
  'created_at:desc',
  'engine_type:asc',
  'engine_type:desc',
  'version:asc',
  'version:desc',
] as const;
export type QueryTemplateSortKey = (typeof QUERY_TEMPLATE_SORT_VALUES)[number];

// Values must match backend/app/api/v1/schemas.py JudgmentListSortKey.
export const JUDGMENT_LIST_SORT_VALUES = [
  'name:asc',
  'name:desc',
  'created_at:asc',
  'created_at:desc',
  'status:asc',
  'status:desc',
] as const;
export type JudgmentListSortKey = (typeof JUDGMENT_LIST_SORT_VALUES)[number];

// Values must match backend/app/api/v1/schemas.py JudgmentRowSortKey.
export const JUDGMENT_ROW_SORT_VALUES = [
  'created_at:asc',
  'created_at:desc',
  'rating:asc',
  'rating:desc',
  'source:asc',
  'source:desc',
] as const;
export type JudgmentRowSortKey = (typeof JUDGMENT_ROW_SORT_VALUES)[number];

// Values must match backend/app/api/v1/schemas.py ProposalSortKey.
export const PROPOSAL_SORT_VALUES = [
  'created_at:asc',
  'created_at:desc',
  'status:asc',
  'status:desc',
  'pr_state:asc',
  'pr_state:desc',
] as const;
export type ProposalSortKey = (typeof PROPOSAL_SORT_VALUES)[number];

// New in feat_data_table_primitive Story 3.2 — frontend mirror of
// backend ProposalSourceWire Literal (which has existed since PR #83).
// Values must match backend/app/api/v1/schemas.py ProposalSourceWire.
export const PROPOSAL_SOURCE_VALUES = ['study', 'manual'] as const;
export type ProposalSource = (typeof PROPOSAL_SOURCE_VALUES)[number];

// feat_digest_executable_followups Story 5.1 — frontend mirror of the
// backend FollowupItem discriminator. The values flow back to the backend
// only indirectly (via persisted JSONB), but the frontend uses them to
// branch UI per card kind.
// Values must match backend/app/domain/study/followups.py FOLLOWUP_KIND_VALUES
export const FOLLOWUP_KIND_VALUES = ['narrow', 'widen', 'text', 'swap_template'] as const;
export type FollowupKind = (typeof FOLLOWUP_KIND_VALUES)[number];
