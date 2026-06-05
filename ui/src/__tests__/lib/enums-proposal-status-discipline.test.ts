// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Phase 3 Story 4.1 — PROPOSAL_STATUS_VALUES enum value-lock (AC-18).
 *
 * Mirrors the discipline established by `enums-convergence-discipline.test.ts`:
 * the canonical source-of-truth is
 * `backend/app/api/v1/schemas.py ProposalStatusWire`. Drift on either side
 * trips this test or the backend's contract test on the same Literal.
 *
 * `superseded` was added in Phase 3 alongside the migration that extends
 * the `proposals_status_check` CHECK constraint.
 */

import { describe, expect, it } from 'vitest';

import { PROPOSAL_STATUS_VALUES, type ProposalStatus } from '@/lib/enums';

describe('PROPOSAL_STATUS_VALUES', () => {
  it('contains exactly the five statuses in canonical order', () => {
    expect(PROPOSAL_STATUS_VALUES.length).toBe(5);
    expect(PROPOSAL_STATUS_VALUES).toEqual([
      'pending',
      'pr_opened',
      'pr_merged',
      'rejected',
      'superseded',
    ]);
  });

  it('type alias narrows to the union of canonical values', () => {
    const status: ProposalStatus = 'superseded';
    // Compile-time check; the assertion keeps the test runtime green.
    expect(status).toBe('superseded');
  });
});
