// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Fallback best-so-far curve derivation (feat_ubi_llm_study_comparison FR-7).
 *
 * When `StudyDetail.convergence.best_so_far_curve` is absent, derive the same
 * shape client-side from the study's trials. Output MUST match the borrowed
 * `CurvePoint` shape exactly: `{trial_number, best_so_far}`.
 */

export interface CurvePoint {
  trial_number: number;
  best_so_far: number;
}

export interface TrialLike {
  optuna_trial_number: number;
  primary_metric: number | null;
  status: 'complete' | 'failed' | 'pruned';
  is_baseline: boolean;
}

/**
 * Running extremum of `primary_metric` over the study's completed,
 * non-baseline trials, sorted by `optuna_trial_number` ascending. Running-max
 * for `maximize`, running-min for `minimize`. Trials with a null
 * `primary_metric`, non-`complete` status, or `is_baseline` are excluded.
 */
export function deriveBestSoFarCurve(
  trials: readonly TrialLike[],
  direction: 'maximize' | 'minimize',
): CurvePoint[] {
  const usable = trials
    .filter((t) => t.status === 'complete' && !t.is_baseline && t.primary_metric !== null)
    .slice()
    .sort((x, y) => x.optuna_trial_number - y.optuna_trial_number);

  const out: CurvePoint[] = [];
  let best: number | null = null;
  for (const t of usable) {
    const v = t.primary_metric as number;
    if (best === null) {
      best = v;
    } else if (direction === 'minimize') {
      best = Math.min(best, v);
    } else {
      best = Math.max(best, v);
    }
    out.push({ trial_number: t.optuna_trial_number, best_so_far: best });
  }
  return out;
}
