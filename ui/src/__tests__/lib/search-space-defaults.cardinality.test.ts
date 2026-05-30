// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';

import { estimateCardinality, type SearchSpaceJson } from '@/lib/search-space-defaults';
// Fixtures live next to the backend tests so the Python parity test at
// backend/tests/unit/domain/test_search_space_cardinality_parity.py consumes
// the same data. Any drift between the TS port and the Python implementation
// will surface in one of the two tests.
import fixtures from '../../../../backend/tests/_fixtures/search_space_cardinality_fixtures.json';

interface Fixture {
  name: string;
  space: SearchSpaceJson;
  expected: number;
}

interface FixtureFile {
  fixtures: Fixture[];
}

describe('estimateCardinality — parity against backend estimate_cardinality', () => {
  const cases = (fixtures as unknown as FixtureFile).fixtures;

  it('loads at least 8 fixtures from the shared JSON file', () => {
    expect(cases.length).toBeGreaterThanOrEqual(8);
  });

  it.each(cases)('$name → cardinality = $expected', ({ space, expected }) => {
    expect(estimateCardinality(space)).toBe(expected);
  });
});
