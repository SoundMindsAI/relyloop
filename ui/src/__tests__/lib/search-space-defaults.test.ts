import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  buildStarterSearchSpace,
  estimateCardinality,
  HEURISTIC_RULES,
} from '@/lib/search-space-defaults';

describe('HEURISTIC_RULES — naming-convention table (chore_create_study_wizard_polish FR-1)', () => {
  it('matches boost_<field> as log-uniform float in [0.5, 10.0]', () => {
    const out = buildStarterSearchSpace({ boost_title: 'float' });
    expect(out.params['boost_title']).toEqual({
      type: 'float',
      low: 0.5,
      high: 10.0,
      log: true,
    });
  });

  it('matches field_boost_<field> as log-uniform float', () => {
    const out = buildStarterSearchSpace({ field_boost_title: 'float' });
    expect(out.params['field_boost_title']).toEqual({
      type: 'float',
      low: 0.5,
      high: 10.0,
      log: true,
    });
  });

  it('matches standalone `boost` and <field>_boost suffix as log-uniform float', () => {
    // bug_tutorial_template_param_boost_naming: the tutorial template's
    // declared_params use `title_boost` / `description_boost` /
    // `bullet_points_boost` (suffix), and the E2E `seedTemplate()` fixture
    // uses standalone `boost`. Before the rule extension all four fell
    // through to the simple-form 'float' default → uniform [0, 1] instead of
    // the [0.5, 10] log-uniform range the template comments document and
    // the chat-agent path produces.
    //
    // Tested one name at a time so the cap-aware fallback doesn't fire
    // (4 log-uniform floats would product 10^8 cardinality and force
    // conversions). The per-rule assertion is what we're locking here.
    for (const name of ['boost', 'title_boost', 'description_boost', 'bullet_points_boost']) {
      const out = buildStarterSearchSpace({ [name]: 'float' });
      expect(out.params[name]).toEqual({
        type: 'float',
        low: 0.5,
        high: 10.0,
        log: true,
      });
    }
  });

  it('matches tie_breaker as uniform float in [0.0, 1.0]', () => {
    const out = buildStarterSearchSpace({ tie_breaker: 'float' });
    expect(out.params['tie_breaker']).toEqual({ type: 'float', low: 0.0, high: 1.0 });
  });

  it('matches *_weight names as uniform float in [0.0, 1.0]', () => {
    const out = buildStarterSearchSpace({ phrase_weight: 'float' });
    expect(out.params['phrase_weight']).toEqual({ type: 'float', low: 0.0, high: 1.0 });
  });

  it('matches slop as int in [0, 5]', () => {
    const out = buildStarterSearchSpace({ slop: 'int' });
    expect(out.params['slop']).toEqual({ type: 'int', low: 0, high: 5 });
  });

  it('matches min_should_match as int in [0, 5]', () => {
    const out = buildStarterSearchSpace({ min_should_match: 'int' });
    expect(out.params['min_should_match']).toEqual({ type: 'int', low: 0, high: 5 });
  });

  it('matches *_size names as int in [0, 5]', () => {
    const out = buildStarterSearchSpace({ window_size: 'int' });
    expect(out.params['window_size']).toEqual({ type: 'int', low: 0, high: 5 });
  });

  it('matches fuzziness as categorical AUTO/0/1/2', () => {
    const out = buildStarterSearchSpace({ fuzziness: 'string' });
    expect(out.params['fuzziness']).toEqual({
      type: 'categorical',
      choices: ['AUTO', '0', '1', '2'],
    });
  });

  it('exports the rule table for inspection', () => {
    expect(HEURISTIC_RULES.length).toBeGreaterThanOrEqual(4);
  });
});

describe('buildStarterSearchSpace — simple-form fallbacks', () => {
  it('int → small int range', () => {
    const out = buildStarterSearchSpace({ exotic_int_param: 'int' });
    expect(out.params['exotic_int_param']).toEqual({ type: 'int', low: 0, high: 5 });
  });

  it('float → uniform float 0..1', () => {
    const out = buildStarterSearchSpace({ exotic_float_param: 'float' });
    expect(out.params['exotic_float_param']).toEqual({
      type: 'float',
      low: 0.0,
      high: 1.0,
    });
  });

  it('bool → categorical [true, false]', () => {
    const out = buildStarterSearchSpace({ use_stemmer: 'bool' });
    expect(out.params['use_stemmer']).toEqual({
      type: 'categorical',
      choices: [true, false],
    });
  });

  it("string → degenerate '__placeholder__' categorical sentinel", () => {
    const out = buildStarterSearchSpace({ some_string_param: 'string' });
    expect(out.params['some_string_param']).toEqual({
      type: 'categorical',
      choices: ['__placeholder__'],
    });
  });

  it('unknown simple-form value falls through to DEFAULT_FALLBACK (uniform float 0..1)', () => {
    const out = buildStarterSearchSpace({ exotic: 'unknown_type' });
    expect(out.params['exotic']).toEqual({ type: 'float', low: 0.0, high: 1.0 });
  });
});

describe('buildStarterSearchSpace — happy path multi-param', () => {
  it('reproduces the spec AC-1 example exactly', () => {
    const out = buildStarterSearchSpace({
      boost_title: 'float',
      boost_body: 'float',
      min_should_match: 'int',
      fuzziness: 'string',
    });
    expect(out).toEqual({
      params: {
        boost_title: { type: 'float', low: 0.5, high: 10.0, log: true },
        boost_body: { type: 'float', low: 0.5, high: 10.0, log: true },
        min_should_match: { type: 'int', low: 0, high: 5 },
        fuzziness: { type: 'categorical', choices: ['AUTO', '0', '1', '2'] },
      },
    });
  });
});

describe('buildStarterSearchSpace — cap-aware fallback (spec FR-1)', () => {
  let warnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
  });

  afterEach(() => {
    warnSpy.mockRestore();
  });

  it('keeps regex-matched floats and converts fall-through floats first when over cap', () => {
    // Three boost-like floats (3 × 100 = 10⁶ exactly) plus two fall-through floats
    // (×100 each) → candidate cardinality = 10⁸. Fall-through floats must be
    // converted to int [0,5] first.
    const out = buildStarterSearchSpace({
      boost_title: 'float',
      boost_body: 'float',
      boost_subject: 'float',
      arbitrary_a: 'float',
      arbitrary_b: 'float',
    });

    expect(out.params['boost_title']).toEqual({
      type: 'float',
      low: 0.5,
      high: 10.0,
      log: true,
    });
    expect(out.params['arbitrary_a']).toEqual({ type: 'int', low: 0, high: 5 });
    expect(out.params['arbitrary_b']).toEqual({ type: 'int', low: 0, high: 5 });
    expect(estimateCardinality(out)).toBeLessThanOrEqual(1_000_000);
    expect(warnSpy).toHaveBeenCalledTimes(1);
  });

  it('converts regex-matched floats only if still over cap after fall-through conversions', () => {
    // Five boost-like floats (5 × 100 = 10¹⁰) and no fall-through floats — the
    // function must convert regex-matched floats lexicographically until under cap.
    const out = buildStarterSearchSpace({
      boost_a: 'float',
      boost_b: 'float',
      boost_c: 'float',
      boost_d: 'float',
      boost_e: 'float',
    });
    expect(estimateCardinality(out)).toBeLessThanOrEqual(1_000_000);
    // boost_a was the first converted (lexicographic order)
    expect(out.params['boost_a']).toEqual({ type: 'int', low: 0, high: 5 });
    expect(warnSpy).toHaveBeenCalledTimes(1);
  });

  it('never converts categoricals or ints — they do not contribute float weight', () => {
    // 4 floats (10⁸) + fuzziness (×4) + slop (×6) → cardinality = 4 × 6 × 10⁸ = 2.4×10⁹.
    // The function must keep fuzziness categorical and slop int, only converting floats.
    const out = buildStarterSearchSpace({
      boost_title: 'float',
      boost_body: 'float',
      a_extra: 'float',
      b_extra: 'float',
      slop: 'int',
      fuzziness: 'string',
    });
    expect(out.params['fuzziness']).toEqual({
      type: 'categorical',
      choices: ['AUTO', '0', '1', '2'],
    });
    expect(out.params['slop']).toEqual({ type: 'int', low: 0, high: 5 });
    expect(estimateCardinality(out)).toBeLessThanOrEqual(1_000_000);
  });

  it('does not fire when candidate cardinality is already within cap', () => {
    buildStarterSearchSpace({ boost_title: 'float' });
    expect(warnSpy).not.toHaveBeenCalled();
  });
});

describe('estimateCardinality', () => {
  it('returns 100 for a single float param', () => {
    expect(
      estimateCardinality({
        params: { a: { type: 'float', low: 0, high: 1 } },
      }),
    ).toBe(100);
  });

  it('returns high - low + 1 for a single int param', () => {
    expect(
      estimateCardinality({
        params: { a: { type: 'int', low: 0, high: 5 } },
      }),
    ).toBe(6);
  });

  it('returns len(choices) for a categorical', () => {
    expect(
      estimateCardinality({
        params: { a: { type: 'categorical', choices: ['x', 'y', 'z'] } },
      }),
    ).toBe(3);
  });

  it('multiplies across params', () => {
    expect(
      estimateCardinality({
        params: {
          a: { type: 'float', low: 0, high: 1 },
          b: { type: 'int', low: 0, high: 5 },
          c: { type: 'categorical', choices: ['x', 'y'] },
        },
      }),
    ).toBe(100 * 6 * 2);
  });
});
