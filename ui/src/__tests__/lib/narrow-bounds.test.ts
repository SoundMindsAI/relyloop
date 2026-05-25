/**
 * feat_study_clone_narrow_bounds Story 1.1 — unit tests for the pure
 * ``narrowBoundsAroundWinner`` helper at [`ui/src/lib/narrow-bounds.ts`](../../lib/narrow-bounds.ts).
 *
 * Coverage targets every branch of FR-10's clamp algorithm:
 *   - Float positive / negative / zero / out-of-bounds winners
 *   - Log-uniform floor preservation + zero-floor skip
 *   - Int rounding + degenerate skip + single-value valid range + negative winner
 *   - Categorical / missing-winner / non-numeric-winner skips
 *   - Multi-param mix; all-skipped result; custom percent; malformed JSON
 */

import { describe, expect, it } from 'vitest';

import { narrowBoundsAroundWinner } from '@/lib/narrow-bounds';

function parseSpace(json: string) {
  return JSON.parse(json) as {
    params: Record<
      string,
      | { type: 'float'; low: number; high: number; log?: boolean }
      | { type: 'int'; low: number; high: number }
      | { type: 'categorical'; choices: unknown[] }
    >;
  };
}

function spaceJson(
  params: Record<
    string,
    | { type: 'float'; low: number; high: number; log?: boolean }
    | { type: 'int'; low: number; high: number }
    | { type: 'categorical'; choices: unknown[] }
  >,
): string {
  return JSON.stringify({ params }, null, 2);
}

describe('narrowBoundsAroundWinner — Float clamp', () => {
  it('positive winner inside old bounds → narrowed to ±20%', () => {
    const input = spaceJson({
      title_boost: { type: 'float', low: 0.5, high: 5.0, log: false },
    });
    const result = narrowBoundsAroundWinner(input, { title_boost: 2.34 }, 20);
    expect(result.narrowed).toEqual(['title_boost']);
    expect(result.skipped).toEqual([]);
    const parsed = parseSpace(result.json);
    const spec = parsed.params['title_boost'];
    if (spec?.type !== 'float') throw new Error('expected float spec');
    expect(spec.low).toBeCloseTo(1.872, 6);
    expect(spec.high).toBeCloseTo(2.808, 6);
  });

  it('negative winner inside old bounds → narrowed (unordered min/max applied)', () => {
    const input = spaceJson({
      x: { type: 'float', low: -20, high: 0, log: false },
    });
    const result = narrowBoundsAroundWinner(input, { x: -10 }, 20);
    expect(result.narrowed).toEqual(['x']);
    expect(result.skipped).toEqual([]);
    const parsed = parseSpace(result.json);
    const spec = parsed.params['x'];
    if (spec?.type !== 'float') throw new Error('expected float spec');
    expect(spec.low).toBeCloseTo(-12, 6);
    expect(spec.high).toBeCloseTo(-8, 6);
  });

  it('winner = 0 → degenerate_intersection skip (zero-width target)', () => {
    const input = spaceJson({
      x: { type: 'float', low: -1, high: 1, log: false },
    });
    const result = narrowBoundsAroundWinner(input, { x: 0 }, 20);
    expect(result.narrowed).toEqual([]);
    expect(result.skipped).toEqual([{ name: 'x', reason: 'degenerate_intersection' }]);
    // Spec must be byte-equivalent to input.
    const parsed = parseSpace(result.json);
    expect(parsed.params['x']).toEqual({ type: 'float', low: -1, high: 1, log: false });
  });

  it('winner below oldLow → degenerate_intersection skip', () => {
    const input = spaceJson({
      x: { type: 'float', low: 5, high: 10, log: false },
    });
    const result = narrowBoundsAroundWinner(input, { x: 1 }, 20);
    expect(result.narrowed).toEqual([]);
    expect(result.skipped[0]?.reason).toBe('degenerate_intersection');
    // Original bounds untouched.
    const parsed = parseSpace(result.json);
    expect(parsed.params['x']).toEqual({ type: 'float', low: 5, high: 10, log: false });
  });

  it('winner above oldHigh → degenerate_intersection skip', () => {
    const input = spaceJson({
      x: { type: 'float', low: 0, high: 1, log: false },
    });
    const result = narrowBoundsAroundWinner(input, { x: 10 }, 20);
    expect(result.skipped[0]?.reason).toBe('degenerate_intersection');
  });
});

describe('narrowBoundsAroundWinner — Float log-uniform', () => {
  it('clamped low > 0 → preserved', () => {
    const input = spaceJson({
      boost: { type: 'float', low: 1e-6, high: 100, log: true },
    });
    const result = narrowBoundsAroundWinner(input, { boost: 0.001 }, 20);
    expect(result.narrowed).toEqual(['boost']);
    const parsed = parseSpace(result.json);
    const spec = parsed.params['boost'];
    if (spec?.type !== 'float') throw new Error('expected float spec');
    expect(spec.low).toBeGreaterThan(0);
    expect(spec.low).toBeCloseTo(0.0008, 6);
    expect(spec.high).toBeCloseTo(0.0012, 6);
    expect(spec.log).toBe(true);
  });

  it('clamped low would land below the 1e-12 floor → log_uniform_zero_floor skip', () => {
    // Construct a case where targetLow > 0 but after clamping it gets pinned
    // to floor and the resulting newLow >= newHigh. Choose winner ~1e-13 so
    // targetLow = 0.8e-13 < 1e-12, targetHigh = 1.2e-13 < 1e-12 — floor
    // pushes newLow up to 1e-12 which exceeds newHigh.
    const input = spaceJson({
      boost: { type: 'float', low: 1e-15, high: 100, log: true },
    });
    const result = narrowBoundsAroundWinner(input, { boost: 1e-13 }, 20);
    expect(result.narrowed).toEqual([]);
    expect(result.skipped[0]?.reason).toBe('log_uniform_zero_floor');
  });
});

describe('narrowBoundsAroundWinner — Int clamp', () => {
  it('simple clamp + rounding (ceil low, floor high)', () => {
    const input = spaceJson({
      n: { type: 'int', low: 1, high: 10 },
    });
    const result = narrowBoundsAroundWinner(input, { n: 5 }, 20);
    expect(result.narrowed).toEqual(['n']);
    const parsed = parseSpace(result.json);
    const spec = parsed.params['n'];
    if (spec?.type !== 'int') throw new Error('expected int spec');
    expect(spec.low).toBe(4);
    expect(spec.high).toBe(6);
  });

  it('single-value result is valid (low === high)', () => {
    // Winner=3, p=20% → target [2.4, 3.6] → ceil(2.4)=3, floor(3.6)=3 → [3, 3]
    // IntParam validator allows low <= high (equality OK).
    const input = spaceJson({
      n: { type: 'int', low: 1, high: 5 },
    });
    const result = narrowBoundsAroundWinner(input, { n: 3 }, 20);
    expect(result.narrowed).toEqual(['n']);
    const parsed = parseSpace(result.json);
    const spec = parsed.params['n'];
    if (spec?.type !== 'int') throw new Error('expected int spec');
    expect(spec.low).toBe(3);
    expect(spec.high).toBe(3);
  });

  it('degenerate after ceil/floor → degenerate_intersection skip', () => {
    // Winner=2.5, p=4% → target [2.4, 2.6] → ceil(2.4)=3, floor(2.6)=2 → low>high.
    const input = spaceJson({
      n: { type: 'int', low: 1, high: 10 },
    });
    const result = narrowBoundsAroundWinner(input, { n: 2.5 }, 4);
    expect(result.skipped[0]?.reason).toBe('degenerate_intersection');
  });

  it('negative winner → narrowed correctly', () => {
    const input = spaceJson({
      n: { type: 'int', low: -10, high: 10 },
    });
    const result = narrowBoundsAroundWinner(input, { n: -3 }, 20);
    expect(result.narrowed).toEqual(['n']);
    const parsed = parseSpace(result.json);
    const spec = parsed.params['n'];
    if (spec?.type !== 'int') throw new Error('expected int spec');
    // target = [-3.6, -2.4]; ceil(-3.6) = -3; floor(-2.4) = -3 → [-3, -3]
    expect(spec.low).toBe(-3);
    expect(spec.high).toBe(-3);
  });
});

describe('narrowBoundsAroundWinner — Skip reasons', () => {
  it('categorical param → skip with reason: categorical', () => {
    const input = spaceJson({
      fuzziness: { type: 'categorical', choices: ['AUTO', '0', '1', '2'] },
    });
    const result = narrowBoundsAroundWinner(input, { fuzziness: 'AUTO' }, 20);
    expect(result.narrowed).toEqual([]);
    expect(result.skipped).toEqual([{ name: 'fuzziness', reason: 'categorical' }]);
    // Choices untouched.
    const parsed = parseSpace(result.json);
    expect(parsed.params['fuzziness']).toEqual({
      type: 'categorical',
      choices: ['AUTO', '0', '1', '2'],
    });
  });

  it('param in space but absent from winner → skip with reason: missing_winner', () => {
    const input = spaceJson({
      x: { type: 'float', low: 0, high: 10, log: false },
    });
    const result = narrowBoundsAroundWinner(input, {}, 20);
    expect(result.skipped).toEqual([{ name: 'x', reason: 'missing_winner' }]);
  });

  it('non-numeric winner on numeric spec → skip with reason: non_numeric_winner', () => {
    const input = spaceJson({
      x: { type: 'float', low: 0, high: 10, log: false },
      y: { type: 'int', low: 0, high: 10 },
      z: { type: 'float', low: 0, high: 10, log: false },
    });
    const result = narrowBoundsAroundWinner(input, { x: 'AUTO', y: true, z: null }, 20);
    expect(result.narrowed).toEqual([]);
    expect(result.skipped.map((s) => s.reason)).toEqual([
      'non_numeric_winner',
      'non_numeric_winner',
      'non_numeric_winner',
    ]);
  });
});

describe('narrowBoundsAroundWinner — multi-param + edge cases', () => {
  it('mix of narrowed and skipped — preserves insertion order in narrowed list', () => {
    const input = spaceJson({
      title_boost: { type: 'float', low: 0.5, high: 5.0, log: false },
      fuzziness: { type: 'categorical', choices: ['AUTO', '0', '1'] },
      unrelated_param: { type: 'int', low: 1, high: 10 },
    });
    const result = narrowBoundsAroundWinner(input, { title_boost: 2.34, fuzziness: 'AUTO' }, 20);
    expect(result.narrowed).toEqual(['title_boost']);
    expect(result.skipped).toEqual([
      { name: 'fuzziness', reason: 'categorical' },
      { name: 'unrelated_param', reason: 'missing_winner' },
    ]);
  });

  it('all-skipped input → empty narrowed list, populated skipped list', () => {
    const input = spaceJson({
      a: { type: 'categorical', choices: ['x', 'y'] },
      b: { type: 'categorical', choices: ['p', 'q'] },
    });
    const result = narrowBoundsAroundWinner(input, { a: 'x', b: 'p' }, 20);
    expect(result.narrowed).toEqual([]);
    expect(result.skipped).toHaveLength(2);
  });

  it('custom percent — 10% produces narrower bounds than 50%', () => {
    const input = spaceJson({
      x: { type: 'float', low: 0, high: 100, log: false },
    });
    const tight = narrowBoundsAroundWinner(input, { x: 50 }, 10);
    const wide = narrowBoundsAroundWinner(input, { x: 50 }, 50);
    const tightSpec = parseSpace(tight.json).params['x'];
    const wideSpec = parseSpace(wide.json).params['x'];
    if (tightSpec?.type !== 'float' || wideSpec?.type !== 'float') {
      throw new Error('expected float specs');
    }
    expect(tightSpec.low).toBeCloseTo(45, 6);
    expect(tightSpec.high).toBeCloseTo(55, 6);
    expect(wideSpec.low).toBeCloseTo(25, 6);
    expect(wideSpec.high).toBeCloseTo(75, 6);
  });

  it('malformed JSON throws SyntaxError', () => {
    expect(() => narrowBoundsAroundWinner('not json', {})).toThrow(SyntaxError);
  });
});
