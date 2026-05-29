import { describe, expect, it } from 'vitest';

import {
  AUTH_KIND_VALUES,
  CONFIG_REPO_PROVIDER_VALUES,
  ENGINE_TYPE_VALUES,
  ENVIRONMENT_VALUES,
  HEALTH_STATUS_VALUES,
  JUDGMENT_LIST_STATUS_VALUES,
  JUDGMENT_SOURCE_FILTER_VALUES,
  JUDGMENT_SOURCE_VALUES,
  OBJECTIVE_DIRECTION_VALUES,
  OBJECTIVE_K_VALUES,
  OBJECTIVE_METRIC_VALUES,
  PROPOSAL_PR_STATE_VALUES,
  PROPOSAL_STATUS_VALUES,
  PRUNER_VALUES,
  RATING_VALUES,
  SAMPLER_VALUES,
  STUDY_STATUS_VALUES,
  TRIAL_SORT_VALUES,
  TRIAL_STATUS_VALUES,
} from '@/lib/enums';

/**
 * Belt-and-braces contract assertions for the wire-value arrays. Catches local
 * drift before the Story 4.2 CI grep gate runs in CI. If any of these fail,
 * the backend Literal in `backend/app/api/v1/schemas.py` (or the named source-
 * of-truth file) was updated and `ui/src/lib/enums.ts` is now stale.
 */
describe('wire-value arrays match documented spec table', () => {
  it.each([
    [
      'STUDY_STATUS_VALUES',
      STUDY_STATUS_VALUES,
      ['queued', 'running', 'completed', 'cancelled', 'failed'],
    ],
    ['TRIAL_STATUS_VALUES', TRIAL_STATUS_VALUES, ['complete', 'failed', 'pruned']],
    [
      'TRIAL_SORT_VALUES',
      TRIAL_SORT_VALUES,
      [
        'primary_metric_desc',
        'primary_metric_asc',
        'ended_at_desc',
        'ended_at_asc',
        'optuna_trial_number_asc',
      ],
    ],
    ['ENGINE_TYPE_VALUES', ENGINE_TYPE_VALUES, ['elasticsearch', 'opensearch']],
    [
      'AUTH_KIND_VALUES',
      AUTH_KIND_VALUES,
      ['es_apikey', 'es_basic', 'opensearch_basic', 'opensearch_sigv4'],
    ],
    ['ENVIRONMENT_VALUES', ENVIRONMENT_VALUES, ['prod', 'staging', 'dev']],
    ['HEALTH_STATUS_VALUES', HEALTH_STATUS_VALUES, ['green', 'yellow', 'red', 'unreachable']],
    ['SAMPLER_VALUES', SAMPLER_VALUES, ['tpe', 'random']],
    ['PRUNER_VALUES', PRUNER_VALUES, ['median', 'none']],
    [
      'OBJECTIVE_METRIC_VALUES',
      OBJECTIVE_METRIC_VALUES,
      ['ndcg', 'map', 'precision', 'recall', 'mrr'],
    ],
    ['OBJECTIVE_K_VALUES', OBJECTIVE_K_VALUES, [1, 3, 5, 10, 20, 50, 100]],
    ['OBJECTIVE_DIRECTION_VALUES', OBJECTIVE_DIRECTION_VALUES, ['maximize', 'minimize']],
    [
      'JUDGMENT_LIST_STATUS_VALUES',
      JUDGMENT_LIST_STATUS_VALUES,
      ['generating', 'complete', 'failed'],
    ],
    // Widened by feat_ubi_judgments FR-10 — `click` is now a valid filter value.
    ['JUDGMENT_SOURCE_FILTER_VALUES', JUDGMENT_SOURCE_FILTER_VALUES, ['llm', 'human', 'click']],
    ['JUDGMENT_SOURCE_VALUES', JUDGMENT_SOURCE_VALUES, ['llm', 'human', 'click']],
    ['RATING_VALUES', RATING_VALUES, [0, 1, 2, 3]],
    [
      'PROPOSAL_STATUS_VALUES',
      PROPOSAL_STATUS_VALUES,
      ['pending', 'pr_opened', 'pr_merged', 'rejected'],
    ],
    ['PROPOSAL_PR_STATE_VALUES', PROPOSAL_PR_STATE_VALUES, ['open', 'closed', 'merged']],
    ['CONFIG_REPO_PROVIDER_VALUES', CONFIG_REPO_PROVIDER_VALUES, ['github']],
  ])('%s', (_name, actual, expected) => {
    expect([...actual]).toEqual(expected);
  });
});
