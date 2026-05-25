/**
 * feat_study_clone_from_previous Story 2.1 — unit tests for the pure
 * ``buildPrefillFromStudy`` helper.
 *
 * Cases (per implementation plan §Story 2.1 task 3):
 *   (i)   fully-populated source → every PrefillValues field maps correctly
 *   (ii)  cloneSource.name un-truncated; cloneSource.id === source.id
 *   (iii) source.name = 250 chars → name = source.name.slice(0,200) + ' (clone)'
 *         (exactly 208 chars, NO ellipsis)
 *   (iv)  source.name = 50 chars → name = source.name + ' (clone)' (no truncation)
 *   (v)   optional config keys missing → undefined (form defaults stand)
 *   (vi)  parent_study_id === source.id
 *   (vii) parent is undefined (clone path carries no proposal-followup lineage)
 */

import { describe, expect, it } from 'vitest';

import type { StudyDetail } from '@/lib/api/studies';
import { buildPrefillFromStudy } from '@/components/studies/prefill-from-study';

const FULLY_POPULATED_SOURCE: StudyDetail = {
  id: '01970000-0000-7000-8000-000000000001',
  name: 'baseline-study',
  cluster_id: 'c-elasticsearch-local',
  target: 'products',
  template_id: 'tpl-baseline-v1',
  query_set_id: 'qs-demo',
  judgment_list_id: 'jl-demo',
  search_space: {
    params: {
      boost_title: { type: 'float', low: 1.0, high: 5.0, log: false },
      minimum_should_match: { type: 'int', low: 1, high: 4 },
    },
  },
  objective: {
    metric: 'ndcg',
    k: 10,
    direction: 'maximize',
  },
  config: {
    max_trials: 200,
    time_budget_min: 60,
    parallelism: 4,
    trial_timeout_s: 30,
    sampler: 'tpe',
    pruner: 'median',
    seed: 42,
  },
  status: 'completed',
  failed_reason: null,
  optuna_study_name: 'baseline-study-optuna',
  parent_study_id: null,
  baseline_metric: 0.42,
  best_metric: 0.51,
  best_trial_id: '01970000-0000-7000-8000-0000000000ab',
  created_at: '2026-05-20T00:00:00Z',
  started_at: '2026-05-20T00:01:00Z',
  completed_at: '2026-05-20T00:30:00Z',
  trials_summary: {
    total: 200,
    complete: 195,
    failed: 2,
    pruned: 3,
    best_primary_metric: 0.51,
  },
};

describe('buildPrefillFromStudy', () => {
  it('(i) maps every field from a fully-populated StudyDetail', () => {
    const prefill = buildPrefillFromStudy(FULLY_POPULATED_SOURCE);

    expect(prefill.cluster_id).toBe('c-elasticsearch-local');
    expect(prefill.target).toBe('products');
    expect(prefill.template_id).toBe('tpl-baseline-v1');
    expect(prefill.query_set_id).toBe('qs-demo');
    expect(prefill.judgment_list_id).toBe('jl-demo');
    expect(prefill.name).toBe('baseline-study (clone)');
    expect(prefill.search_space_text).toBe(
      JSON.stringify(FULLY_POPULATED_SOURCE.search_space, null, 2),
    );
    expect(prefill.metric).toBe('ndcg');
    expect(prefill.k).toBe(10);
    expect(prefill.direction).toBe('maximize');
    expect(prefill.max_trials).toBe(200);
    expect(prefill.time_budget_min).toBe(60);
    expect(prefill.parallelism).toBe(4);
    expect(prefill.trial_timeout_s).toBe(30);
    expect(prefill.sampler).toBe('tpe');
    expect(prefill.pruner).toBe('median');
    expect(prefill.seed).toBe(42);
  });

  it('(ii) cloneSource carries the un-truncated source name and source id', () => {
    const longName = 'X'.repeat(250);
    const source: StudyDetail = { ...FULLY_POPULATED_SOURCE, name: longName };
    const prefill = buildPrefillFromStudy(source);

    expect(prefill.cloneSource).toEqual({
      id: FULLY_POPULATED_SOURCE.id,
      name: longName,
    });
    expect(prefill.cloneSource?.name).toHaveLength(250);
  });

  it('(iii) source.name = 250 chars → name truncated to 200 + " (clone)" (208 chars, no ellipsis)', () => {
    const longName = 'A'.repeat(250);
    const source: StudyDetail = { ...FULLY_POPULATED_SOURCE, name: longName };
    const prefill = buildPrefillFromStudy(source);

    expect(prefill.name).toBe('A'.repeat(200) + ' (clone)');
    expect(prefill.name).toHaveLength(208);
    expect(prefill.name).not.toContain('...');
  });

  it('(iv) source.name = 50 chars → name appended without truncation', () => {
    const shortName = 'short-study-name';
    const source: StudyDetail = { ...FULLY_POPULATED_SOURCE, name: shortName };
    const prefill = buildPrefillFromStudy(source);

    expect(prefill.name).toBe(`${shortName} (clone)`);
  });

  it('(v) optional config keys missing → undefined (form defaults stand)', () => {
    const source: StudyDetail = {
      ...FULLY_POPULATED_SOURCE,
      config: {
        // Only metric/k/direction live on objective; config can be entirely empty.
      },
      objective: { metric: 'ndcg', direction: 'maximize' },
    };
    const prefill = buildPrefillFromStudy(source);

    expect(prefill.max_trials).toBeUndefined();
    expect(prefill.time_budget_min).toBeUndefined();
    expect(prefill.parallelism).toBeUndefined();
    expect(prefill.trial_timeout_s).toBeUndefined();
    expect(prefill.sampler).toBeUndefined();
    expect(prefill.pruner).toBeUndefined();
    expect(prefill.seed).toBeUndefined();
    expect(prefill.k).toBeUndefined();
  });

  it('(vi) parent_study_id === source.id', () => {
    const prefill = buildPrefillFromStudy(FULLY_POPULATED_SOURCE);
    expect(prefill.parent_study_id).toBe(FULLY_POPULATED_SOURCE.id);
  });

  it('(vii) parent is undefined (clone path carries no proposal-followup lineage)', () => {
    const prefill = buildPrefillFromStudy(FULLY_POPULATED_SOURCE);
    expect(prefill.parent).toBeUndefined();
  });
});
