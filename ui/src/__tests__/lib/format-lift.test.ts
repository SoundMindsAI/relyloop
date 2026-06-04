// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import { formatSignedLift } from '@/lib/format-lift';

describe('feat_overnight_final_solution_phase2 Story 1 / FR-8 / D-12 — formatSignedLift', () => {
  it('returns "—" for null/undefined (empty-cell convention)', () => {
    expect(formatSignedLift(null)).toBe('—');
    expect(formatSignedLift(undefined)).toBe('—');
  });

  it('formats positive values with a leading "+" and 4 decimals', () => {
    expect(formatSignedLift(0.1245)).toBe('+0.1245');
    expect(formatSignedLift(1)).toBe('+1.0000');
  });

  it('formats negative values with a leading "-" and 4 decimals (Number.toFixed semantics)', () => {
    expect(formatSignedLift(-0.05)).toBe('-0.0500');
    expect(formatSignedLift(-1)).toBe('-1.0000');
  });

  it('formats zero with a leading "+" (zero is non-negative)', () => {
    expect(formatSignedLift(0)).toBe('+0.0000');
  });

  it('truncates to 4 decimal places (Number.toFixed semantics)', () => {
    // toFixed rounds half-to-even-ish; the contract is "4 decimals", any
    // consistent rounding is acceptable, but we lock the actual behaviour
    // so a future Number.toFixed change would surface here.
    expect(formatSignedLift(0.123456789)).toBe('+0.1235');
  });
});
