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
export const ENGINE_TYPE_VALUES = ['elasticsearch', 'opensearch'] as const;
export type EngineType = (typeof ENGINE_TYPE_VALUES)[number];

// Values must match backend/app/api/v1/schemas.py AuthKind.
export const AUTH_KIND_VALUES = [
  'es_apikey',
  'es_basic',
  'opensearch_basic',
  'opensearch_sigv4',
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

// Values must match backend/app/api/v1/schemas.py ObjectiveMetric.
export const OBJECTIVE_METRIC_VALUES = [
  'ndcg',
  'map',
  'precision',
  'recall',
  'mrr',
  'err',
] as const;
export type ObjectiveMetric = (typeof OBJECTIVE_METRIC_VALUES)[number];

// Values must match backend/app/api/v1/schemas.py ObjectiveK.
export const OBJECTIVE_K_VALUES = [1, 3, 5, 10, 20, 50, 100] as const;
export type ObjectiveK = (typeof OBJECTIVE_K_VALUES)[number];

// Values must match backend/app/api/v1/schemas.py ObjectiveDirection.
export const OBJECTIVE_DIRECTION_VALUES = ['maximize', 'minimize'] as const;
export type ObjectiveDirection = (typeof OBJECTIVE_DIRECTION_VALUES)[number];

// Values must match backend/app/api/v1/schemas.py JudgmentListStatusWire.
export const JUDGMENT_LIST_STATUS_VALUES = ['generating', 'complete', 'failed'] as const;
export type JudgmentListStatus = (typeof JUDGMENT_LIST_STATUS_VALUES)[number];

// Values must match backend/app/api/v1/schemas.py JudgmentSourceFilterWire.
export const JUDGMENT_SOURCE_FILTER_VALUES = ['llm', 'human'] as const;
export type JudgmentSourceFilter = (typeof JUDGMENT_SOURCE_FILTER_VALUES)[number];

// Values must match backend/app/api/v1/schemas.py JudgmentSourceWire.
export const JUDGMENT_SOURCE_VALUES = ['llm', 'human', 'click'] as const;
export type JudgmentSource = (typeof JUDGMENT_SOURCE_VALUES)[number];

// Values must match backend/app/api/v1/schemas.py RatingWire.
export const RATING_VALUES = [0, 1, 2, 3] as const;
export type Rating = (typeof RATING_VALUES)[number];

// Values must match backend/app/api/v1/schemas.py ProposalStatusWire.
export const PROPOSAL_STATUS_VALUES = ['pending', 'pr_opened', 'pr_merged', 'rejected'] as const;
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
