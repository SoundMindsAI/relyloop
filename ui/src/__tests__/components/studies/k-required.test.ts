// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * K_REQUIRED parity test (chore_create_study_wizard_polish AC-13 frontend half).
 *
 * Source-of-truth: backend/app/api/v1/schemas.py:474 `_K_REQUIRED_METRICS`
 * frozenset. The backend contract test at
 * backend/tests/contract/test_k_required_membership.py asserts the matrix
 * of (metric × k-presence) cells the server returns. This test asserts the
 * frontend's K_REQUIRED set is the same membership so the wizard's
 * required/optional/ignored tiers match server behavior.
 */

import { describe, expect, it } from 'vitest';

import { K_REQUIRED } from '@/components/studies/create-study-modal';

describe('K_REQUIRED frontend ↔ backend parity', () => {
  it('equals { ndcg, precision, recall }', () => {
    expect(K_REQUIRED).toEqual(new Set(['ndcg', 'precision', 'recall']));
  });
});
