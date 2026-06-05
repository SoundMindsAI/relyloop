// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';

import { diffNarratives } from '@/lib/diff/narrative-diff';

describe('diffNarratives (FR-4)', () => {
  it('reports per-side change counts for differing narratives', () => {
    const a = 'The loop converged. BM25 k1 was the key knob.';
    const b = 'The loop converged. Title boost was the key knob.';
    const d = diffNarratives(a, b);
    expect(d.addedCount).toBeGreaterThan(0);
    expect(d.removedCount).toBeGreaterThan(0);
    // The shared opening sentence is an unchanged segment.
    expect(d.segments.some((s) => !s.added && !s.removed)).toBe(true);
  });

  it('identical narratives have zero added/removed', () => {
    const d = diffNarratives('Same text.', 'Same text.');
    expect(d.addedCount).toBe(0);
    expect(d.removedCount).toBe(0);
  });

  it('handles empty strings without throwing', () => {
    expect(() => diffNarratives('', '')).not.toThrow();
  });
});
