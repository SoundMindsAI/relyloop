// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';

import { partitionTemplateParams } from '@/lib/proposal-param-space';

describe('partitionTemplateParams', () => {
  it('Test 1 (AC-1): partitions into three non-empty groups, alphabetical within each', () => {
    const result = partitionTemplateParams({
      configDiff: {
        title_boost: { from: 1.0, to: 2.5 },
        description_boost: { from: 1.0, to: 0.5 },
      },
      searchSpaceParams: { title_boost: {}, description_boost: {}, fuzziness: {} },
      declaredParams: {
        title_boost: 'float',
        description_boost: 'float',
        fuzziness: 'int',
        function_score_decay: 'categorical',
      },
    });
    // tunedChanged: alphabetical — description_boost before title_boost.
    expect(result.tunedChanged.map((r) => r.name)).toEqual(['description_boost', 'title_boost']);
    expect(result.tunedChanged[0]).toEqual({
      name: 'description_boost',
      type: 'float',
      from: 1.0,
      to: 0.5,
    });
    expect(result.tunedChanged[1]).toEqual({
      name: 'title_boost',
      type: 'float',
      from: 1.0,
      to: 2.5,
    });
    // tunedUnchanged: fuzziness (in search_space, not in config_diff).
    expect(result.tunedUnchanged).toEqual([{ name: 'fuzziness', type: 'int' }]);
    // untuned: function_score_decay (declared, not in search_space, not in config_diff).
    expect(result.untuned).toEqual([{ name: 'function_score_decay', type: 'categorical' }]);
  });

  it('Test 2 (AC-5): empty config_diff puts every search-space key in tunedUnchanged (alphabetical)', () => {
    const result = partitionTemplateParams({
      configDiff: {},
      searchSpaceParams: { foo: {}, bar: {} },
      declaredParams: { foo: 'float', bar: 'int', baz: 'categorical' },
    });
    expect(result.tunedChanged).toEqual([]);
    // Alphabetical: bar before foo (cycle-3 F3 correction).
    expect(result.tunedUnchanged).toEqual([
      { name: 'bar', type: 'int' },
      { name: 'foo', type: 'float' },
    ]);
    expect(result.untuned).toEqual([{ name: 'baz', type: 'categorical' }]);
  });

  it('Test 3 (AC-3 / manual proposal): undefined searchSpaceParams → tunedUnchanged empty', () => {
    const result = partitionTemplateParams({
      configDiff: { boost: { from: 1, to: 2 } },
      searchSpaceParams: undefined,
      declaredParams: { boost: 'float', title_weight: 'float' },
    });
    expect(result.tunedChanged).toEqual([{ name: 'boost', type: 'float', from: 1, to: 2 }]);
    expect(result.tunedUnchanged).toEqual([]);
    // Every declared param not in config_diff falls into untuned.
    expect(result.untuned).toEqual([{ name: 'title_weight', type: 'float' }]);
  });

  it('Test 4 (AC-6 / config_diff drift): key not in declaredParams renders type "(unknown)"', () => {
    const result = partitionTemplateParams({
      configDiff: { removed_param: { from: 1, to: 2 } },
      searchSpaceParams: undefined,
      declaredParams: {},
    });
    expect(result.tunedChanged).toEqual([
      { name: 'removed_param', type: '(unknown)', from: 1, to: 2 },
    ]);
    expect(result.tunedUnchanged).toEqual([]);
    expect(result.untuned).toEqual([]);
  });

  it('Test 5 (D-9 / search-space drift): key only in searchSpaceParams is silently dropped', () => {
    const result = partitionTemplateParams({
      configDiff: {},
      // `phantom` is in searchSpaceParams but NOT declared (template-evolution
      // drift); `foo` is declared but NOT in searchSpaceParams.
      searchSpaceParams: { phantom: {} },
      declaredParams: { foo: 'int' },
    });
    // phantom is in searchSpaceParams but NOT in declaredParams → dropped entirely.
    const allNames = [
      ...result.tunedChanged.map((r) => r.name),
      ...result.tunedUnchanged.map((r) => r.name),
      ...result.untuned.map((r) => r.name),
    ];
    expect(allNames).not.toContain('phantom');
    // foo is declared but NOT in search_space → untuned (it was never tuned).
    expect(result.tunedUnchanged).toEqual([]);
    expect(result.untuned).toEqual([{ name: 'foo', type: 'int' }]);
  });

  it('Test 5b (Gemini G1 / null search space): null searchSpaceParams does not throw; declared params → untuned', () => {
    // JSONB study.search_space.params may be null at runtime; `key in null`
    // would throw a TypeError without the truthiness guard.
    const result = partitionTemplateParams({
      configDiff: { boost: { from: 1, to: 2 } },
      searchSpaceParams: null,
      declaredParams: { boost: 'float', title_weight: 'float' },
    });
    expect(result.tunedChanged).toEqual([{ name: 'boost', type: 'float', from: 1, to: 2 }]);
    expect(result.tunedUnchanged).toEqual([]);
    expect(result.untuned).toEqual([{ name: 'title_weight', type: 'float' }]);
  });

  it('Test 6 (AC-2 / legacy 2-tuple): config_diff 2-tuple is normalized via extractFromTo', () => {
    const result = partitionTemplateParams({
      configDiff: { boost: [1.0, 1.5] },
      searchSpaceParams: undefined,
      declaredParams: { boost: 'float' },
    });
    expect(result.tunedChanged).toEqual([{ name: 'boost', type: 'float', from: 1.0, to: 1.5 }]);
  });

  it('Test 7 (D-10 / from===to anomaly): a config_diff entry with equal values still classifies as tunedChanged', () => {
    const result = partitionTemplateParams({
      configDiff: { boost: { from: 1, to: 1 } },
      searchSpaceParams: { boost: {} },
      declaredParams: { boost: 'float' },
    });
    // Membership-based: boost is in config_diff → tunedChanged, NOT tunedUnchanged.
    expect(result.tunedChanged).toEqual([{ name: 'boost', type: 'float', from: 1, to: 1 }]);
    expect(result.tunedUnchanged).toEqual([]);
  });

  it('Test 8 (sort stability): scrambled input yields alphabetical output within each group', () => {
    const result = partitionTemplateParams({
      configDiff: {
        zeta: { from: 1, to: 2 },
        alpha: { from: 1, to: 2 },
        mu: { from: 1, to: 2 },
      },
      searchSpaceParams: { yankee: {}, bravo: {}, november: {} },
      declaredParams: {
        zeta: 'float',
        alpha: 'float',
        mu: 'float',
        yankee: 'int',
        bravo: 'int',
        november: 'int',
        zulu: 'categorical',
        delta: 'categorical',
      },
    });
    expect(result.tunedChanged.map((r) => r.name)).toEqual(['alpha', 'mu', 'zeta']);
    expect(result.tunedUnchanged.map((r) => r.name)).toEqual(['bravo', 'november', 'yankee']);
    expect(result.untuned.map((r) => r.name)).toEqual(['delta', 'zulu']);
  });
});
