// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Unit tests for `estimateParamCardinality()` helper (Story 2.3, FR-6).
 *
 * Pure-function tests; no React, no DOM. Pairs with the existing
 * `search-space-defaults.cardinality.test.ts` Python/TS parity test
 * (which exercises the wrapping `estimateCardinality()` function — the
 * refactor must NOT change its totals).
 */

import { describe, expect, it } from 'vitest';

import { estimateParamCardinality } from '@/lib/search-space-defaults';

describe('estimateParamCardinality', () => {
  it('float counts as 100 regardless of low/high', () => {
    expect(estimateParamCardinality({ type: 'float', low: 0.5, high: 10 })).toBe(100);
  });

  it('float counts as 100 even with log + log=true', () => {
    expect(estimateParamCardinality({ type: 'float', low: 0.5, high: 10, log: true })).toBe(100);
  });

  it('float counts as 100 even with negative low (invalid for log, but counted)', () => {
    expect(estimateParamCardinality({ type: 'float', low: -1, high: 10 })).toBe(100);
  });

  it('int counts as high - low + 1 (inclusive)', () => {
    expect(estimateParamCardinality({ type: 'int', low: 0, high: 5 })).toBe(6);
  });

  it('int low=high counts as 1', () => {
    expect(estimateParamCardinality({ type: 'int', low: 3, high: 3 })).toBe(1);
  });

  it('categorical counts as choices.length', () => {
    expect(estimateParamCardinality({ type: 'categorical', choices: ['AUTO', 'BM25'] })).toBe(2);
    expect(estimateParamCardinality({ type: 'categorical', choices: ['only'] })).toBe(1);
  });
});
