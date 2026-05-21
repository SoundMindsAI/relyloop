/**
 * TypeScript half of the buildStarterSearchSpace TS↔Python parity test
 * (feat_agent_propose_search_space Story 1.3 — FR-7, AC-10, AC-13).
 *
 * Consumes the same fixture file as the Python sibling
 * (`backend/tests/unit/domain/test_search_space_defaults_parity.py`):
 *   backend/tests/_fixtures/search_space_defaults_parity.json
 *
 * Drift between this TS implementation and the Python source-of-truth
 * surfaces in one of the two tests.
 */

import { describe, expect, it } from 'vitest';

import {
  buildStarterSearchSpace,
  type ParamSpec,
  type SearchSpaceJson,
} from '@/lib/search-space-defaults';
import fixtures from '../../../../backend/tests/_fixtures/search_space_defaults_parity.json';

type HappyFixture = {
  name: string;
  declared_params: Record<string, string>;
  expected_search_space: SearchSpaceJson;
  expected_cap_aware_fallback_param_names: string[];
};

type ErrorFixture = {
  name: string;
  declared_params: Record<string, string>;
  expected_error: { kind: string; message_substring: string };
};

type Fixture = HappyFixture | ErrorFixture;

type FixtureFile = {
  fixtures: Fixture[];
};

function isHappy(f: Fixture): f is HappyFixture {
  return 'expected_search_space' in f;
}

function isError(f: Fixture): f is ErrorFixture {
  return 'expected_error' in f;
}

const allFixtures = (fixtures as unknown as FixtureFile).fixtures;
const happyFixtures = allFixtures.filter(isHappy);
const errorFixtures = allFixtures.filter(isError);

/**
 * Strip `log: false` from FloatParam dicts so the wire-format comparison
 * matches Python's normalized form. (Python's Pydantic model always emits
 * `log` on FloatParam.model_dump; the shared fixture uses TS-style implicit
 * defaults — log omitted = false. The Python sibling normalizes the same way
 * before comparison.)
 */
function stripDefaultLog(space: SearchSpaceJson): SearchSpaceJson {
  const result: SearchSpaceJson = { params: {} };
  for (const [name, param] of Object.entries(space.params)) {
    const copy: ParamSpec = { ...param } as ParamSpec;
    if (copy.type === 'float' && copy.log === false) {
      delete copy.log;
    }
    result.params[name] = copy;
  }
  return result;
}

describe('buildStarterSearchSpace TS↔Python parity', () => {
  it('loads the expected number of fixture rows from the shared JSON file', () => {
    expect(allFixtures.length).toBeGreaterThanOrEqual(15);
    expect(happyFixtures.length).toBeGreaterThanOrEqual(13);
    expect(errorFixtures.length).toBe(2);
  });

  it.each(happyFixtures)(
    'happy: $name → expected_search_space + expected_cap_aware_fallback_param_names',
    (fixture) => {
      const result = buildStarterSearchSpace(fixture.declared_params);
      expect(stripDefaultLog(result.space)).toEqual(stripDefaultLog(fixture.expected_search_space));
      expect(result.capAwareFallbackParamNames).toEqual(
        fixture.expected_cap_aware_fallback_param_names,
      );
    },
  );

  it.each(errorFixtures)('error: $name throws matching the substring', (fixture) => {
    expect(() => buildStarterSearchSpace(fixture.declared_params)).toThrow(
      new RegExp(fixture.expected_error.message_substring),
    );
  });
});
