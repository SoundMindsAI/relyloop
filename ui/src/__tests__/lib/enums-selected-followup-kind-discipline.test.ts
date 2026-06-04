// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * feat_overnight_final_solution Story 3.2 — enum value-lock.
 *
 * The backend source-of-truth is the
 * `SELECTED_FOLLOWUP_KIND_VALUES` tuple at
 * backend/app/domain/study/auto_followup_strategy.py — drift on either
 * side trips this lock or the backend pair at
 * backend/tests/contract/test_studies_chain_contract.py.
 */

import { describe, expect, it } from 'vitest';

import { SELECTED_FOLLOWUP_KIND_VALUES, type SelectedFollowupKind } from '@/lib/enums';

describe('SELECTED_FOLLOWUP_KIND_VALUES', () => {
  it('contains exactly the four kinds in canonical order', () => {
    expect(SELECTED_FOLLOWUP_KIND_VALUES.length).toBe(4);
    expect(SELECTED_FOLLOWUP_KIND_VALUES).toEqual([
      'narrow_default',
      'narrow',
      'widen',
      'swap_template',
    ]);
  });

  it('type alias narrows to the union of canonical values', () => {
    const k: SelectedFollowupKind = 'narrow_default';
    expect(k).toBe('narrow_default');
    const k2: SelectedFollowupKind = 'swap_template';
    expect(k2).toBe('swap_template');
  });
});
