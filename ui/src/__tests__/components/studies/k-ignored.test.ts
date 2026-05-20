/**
 * K_IGNORED parity test (chore_create_study_wizard_polish AC-14 frontend half).
 *
 * Source-of-truth: backend/app/eval/scoring.py:32 (metric → pytrec_eval token
 * mapper). The backend unit test at
 * backend/tests/unit/eval/test_scoring_metric_tokens.py asserts the mapping
 * directly — including that `mrr` and `err` produce identical tokens
 * regardless of k. The frontend's K_IGNORED set is the predicate that drives
 * the Step-5 "no cutoff" caption + k-state clearing on metric change. They
 * must agree.
 */

import { describe, expect, it } from 'vitest';

import { K_IGNORED } from '@/components/studies/create-study-modal';

describe('K_IGNORED frontend ↔ backend parity', () => {
  it('equals { mrr, err }', () => {
    expect(K_IGNORED).toEqual(new Set(['mrr', 'err']));
  });
});
