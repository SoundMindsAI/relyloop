// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';

import { extractFromTo, renderValue } from '@/lib/config-diff';

describe('extractFromTo', () => {
  it('returns {from, to} from the canonical digest-worker object form', () => {
    // Canonical shape produced by backend/workers/digest.py:1158-1174.
    const result = extractFromTo({ from: 1.0, to: 1.98 });
    expect(result).toEqual({ from: 1.0, to: 1.98 });
  });

  it('returns {from, to} from the legacy 2-tuple [before, after] form', () => {
    // Manual / agent-created proposals may write this shape.
    const result = extractFromTo([50, 100]);
    expect(result).toEqual({ from: 50, to: 100 });
  });

  it('falls back to {from: null, to: <raw>} for unknown shapes', () => {
    // Anything that is neither a {from,to} object nor a 2-tuple goes to the
    // single-value column.
    expect(extractFromTo({ foo: 'bar' })).toEqual({ from: null, to: { foo: 'bar' } });
    // Partial-object shape (only `to` present) is intentionally NOT the canonical form
    // — the 'from' in raw check requires BOTH keys.
    expect(extractFromTo({ to: 0.5 })).toEqual({ from: null, to: { to: 0.5 } });
  });
});

describe('renderValue', () => {
  it('renders null and undefined as the em-dash sentinel "—"', () => {
    expect(renderValue(null)).toBe('—');
    expect(renderValue(undefined)).toBe('—');
  });

  it('renders strings verbatim', () => {
    expect(renderValue('foo')).toBe('foo');
    expect(renderValue('')).toBe('');
  });

  it('renders numbers and booleans via String()', () => {
    expect(renderValue(42)).toBe('42');
    expect(renderValue(0)).toBe('0');
    expect(renderValue(true)).toBe('true');
    expect(renderValue(false)).toBe('false');
  });

  it('renders objects via JSON.stringify (last-resort fallback)', () => {
    expect(renderValue({ a: 1 })).toBe('{"a":1}');
    expect(renderValue([1, 2, 3])).toBe('[1,2,3]');
  });
});
