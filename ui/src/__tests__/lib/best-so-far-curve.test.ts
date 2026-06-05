// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';

import { deriveBestSoFarCurve, type TrialLike } from '@/lib/diff/best-so-far-curve';

function t(n: number, m: number | null, extra: Partial<TrialLike> = {}): TrialLike {
  return {
    optuna_trial_number: n,
    primary_metric: m,
    status: 'complete',
    is_baseline: false,
    ...extra,
  };
}

describe('deriveBestSoFarCurve (FR-7 fallback)', () => {
  it('running-max for maximize, sorted by trial number', () => {
    const curve = deriveBestSoFarCurve([t(2, 0.4), t(0, 0.3), t(1, 0.5)], 'maximize');
    expect(curve).toEqual([
      { trial_number: 0, best_so_far: 0.3 },
      { trial_number: 1, best_so_far: 0.5 },
      { trial_number: 2, best_so_far: 0.5 },
    ]);
  });

  it('running-min for minimize', () => {
    const curve = deriveBestSoFarCurve([t(0, 0.5), t(1, 0.3), t(2, 0.4)], 'minimize');
    expect(curve.map((p) => p.best_so_far)).toEqual([0.5, 0.3, 0.3]);
  });

  it('excludes baseline + non-complete + null-metric rows', () => {
    const curve = deriveBestSoFarCurve(
      [t(0, 0.9, { is_baseline: true }), t(1, 0.2, { status: 'failed' }), t(2, null), t(3, 0.4)],
      'maximize',
    );
    expect(curve).toEqual([{ trial_number: 3, best_so_far: 0.4 }]);
  });

  it('empty input yields empty curve', () => {
    expect(deriveBestSoFarCurve([], 'maximize')).toEqual([]);
  });
});
