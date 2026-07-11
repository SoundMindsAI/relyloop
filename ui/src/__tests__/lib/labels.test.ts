// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';

import {
  JUDGMENT_SOURCE_VALUES,
  OBJECTIVE_METRIC_VALUES,
  PRUNER_VALUES,
  SAMPLER_VALUES,
} from '@/lib/enums';
import {
  formatMetricLabel,
  humanizeWireValue,
  JUDGMENT_SOURCE_LABELS,
  METRIC_LABELS,
  PRUNER_LABELS,
  SAMPLER_LABELS,
} from '@/lib/labels';

describe('humanizeWireValue', () => {
  it('turns snake_case into Title case', () => {
    expect(humanizeWireValue('still_improving')).toBe('Still improving');
    expect(humanizeWireValue('running')).toBe('Running');
    expect(humanizeWireValue('too_few_trials')).toBe('Too few trials');
  });
});

describe('formatMetricLabel', () => {
  it('renders NDCG@10 with the acronym uppercased and cutoff appended', () => {
    expect(formatMetricLabel('ndcg', 10)).toBe('NDCG@10');
    expect(formatMetricLabel('map', 5)).toBe('MAP@5');
  });
  it('omits @k for cutoff-less metrics (k null)', () => {
    expect(formatMetricLabel('mrr', null)).toBe('MRR');
  });
  it('falls back to uppercase for an unknown metric', () => {
    expect(formatMetricLabel('foo', 3)).toBe('FOO@3');
  });
});

describe('label maps cover every enum value (no raw value can leak)', () => {
  it('METRIC_LABELS covers OBJECTIVE_METRIC_VALUES', () => {
    for (const m of OBJECTIVE_METRIC_VALUES) expect(METRIC_LABELS[m]).toBeTruthy();
  });
  it('SAMPLER_LABELS covers SAMPLER_VALUES', () => {
    for (const s of SAMPLER_VALUES) expect(SAMPLER_LABELS[s]).toBeTruthy();
  });
  it('PRUNER_LABELS covers PRUNER_VALUES', () => {
    for (const p of PRUNER_VALUES) expect(PRUNER_LABELS[p]).toBeTruthy();
  });
  it('JUDGMENT_SOURCE_LABELS covers JUDGMENT_SOURCE_VALUES', () => {
    for (const s of JUDGMENT_SOURCE_VALUES) expect(JUDGMENT_SOURCE_LABELS[s]).toBeTruthy();
  });
});
