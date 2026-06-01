// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * feat_study_convergence_indicator Story 4.2 — enum value-lock.
 *
 * AC-18: CONVERGENCE_VERDICT_VALUES must match
 * backend/app/domain/study/convergence.py ConvergenceVerdict character-for-
 * character, including ordering. The backend pair lives in
 * backend/tests/unit/domain/study/test_convergence.py::TestConvergenceVerdictLiteral
 * — drift on either side trips one of the two locks immediately.
 */

import { describe, expect, it } from 'vitest';

import { CONVERGENCE_VERDICT_VALUES, type ConvergenceVerdict } from '@/lib/enums';

describe('CONVERGENCE_VERDICT_VALUES', () => {
  it('contains exactly the three verdicts in canonical order', () => {
    expect(CONVERGENCE_VERDICT_VALUES.length).toBe(3);
    expect(CONVERGENCE_VERDICT_VALUES).toEqual(['converged', 'still_improving', 'too_few_trials']);
  });

  it('type alias narrows to the union of canonical values', () => {
    const verdict: ConvergenceVerdict = 'converged';
    // Compile-time check; the assertion just keeps the test runtime green.
    expect(verdict).toBe('converged');
  });
});
