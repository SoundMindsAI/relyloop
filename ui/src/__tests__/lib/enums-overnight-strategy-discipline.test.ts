// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * feat_overnight_final_solution Story 1.2 — enum value-lock.
 *
 * The backend Pydantic field `StudyConfigSpec.auto_followup_strategy` is
 * `str | None` (NOT `Literal[...]`) per spec D-13 — the enum tuple at
 * backend/app/api/v1/schemas.py `AUTO_FOLLOWUP_STRATEGY_VALUES` is the
 * source of truth that both the backend validator AND this frontend mirror
 * cite. Drift on either side trips this lock or the backend pair at
 * backend/tests/contract/test_studies_api_contract.py.
 */

import { describe, expect, it } from 'vitest';

import { OVERNIGHT_STRATEGY_VALUES, type OvernightStrategy } from '@/lib/enums';

describe('OVERNIGHT_STRATEGY_VALUES', () => {
  it('contains exactly the two strategies in canonical order', () => {
    expect(OVERNIGHT_STRATEGY_VALUES.length).toBe(2);
    expect(OVERNIGHT_STRATEGY_VALUES).toEqual(['narrow', 'follow_suggestions']);
  });

  it('type alias narrows to the union of canonical values', () => {
    const strategy: OvernightStrategy = 'narrow';
    expect(strategy).toBe('narrow');
    const broader: OvernightStrategy = 'follow_suggestions';
    expect(broader).toBe('follow_suggestions');
  });
});
