// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { CHAIN_STOP_REASON_PHRASE } from '@/lib/chain-stop-reason';

describe('feat_overnight_final_solution_phase2 Story 1 / FR-8 — CHAIN_STOP_REASON_PHRASE', () => {
  it('exports all six chain-stop-reason wire values with non-empty phrases', () => {
    const expectedKeys = [
      'depth_exhausted',
      'no_lift',
      'budget',
      'parent_failed',
      'cancelled',
      'in_flight',
    ] as const;
    for (const key of expectedKeys) {
      expect(CHAIN_STOP_REASON_PHRASE[key], `phrase for ${key} missing`).toBeTruthy();
      expect(CHAIN_STOP_REASON_PHRASE[key].length).toBeGreaterThan(0);
    }
  });

  it('has exactly six keys (no spurious entries)', () => {
    expect(Object.keys(CHAIN_STOP_REASON_PHRASE)).toHaveLength(6);
  });

  it('carries the source-of-truth comment pointing at the backend module', () => {
    // The lock guards against future drift — if someone moves the map without
    // the comment, this test fails loudly.
    const source = readFileSync('src/lib/chain-stop-reason.ts', 'utf8');
    expect(source).toContain(
      'Source-of-truth: backend/app/domain/study/chain_summary.py CHAIN_STOP_REASONS',
    );
  });
});
