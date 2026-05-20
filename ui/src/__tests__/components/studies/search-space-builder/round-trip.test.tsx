/**
 * Round-trip parity test for `<SearchSpaceBuilder>` (Story 1.1).
 *
 * Verifies spec FR-9 + AC-7 + §4 product principles: builder ↔ textarea
 * round-trip is **semantically loss-less**. Each fixture either:
 *
 *   (a) is already-canonical → builder's canonicalize-on-mount effect
 *       MUST NOT emit; `onChange` is not called.
 *   (b) requires normalization (`10.0 → 10`, `1e-3 → 0.001`,
 *       `{params:{}}` shape) → builder emits exactly one canonical
 *       write; the emitted JSON is `JSON.stringify(parse(value), null, 2)`.
 *
 * Pure-helper supplemental assertions exercise `parseSearchSpace` and
 * `stringifySearchSpace` directly.
 */

import { describe, expect, it, vi } from 'vitest';
import { render } from '@testing-library/react';

import { TooltipProvider } from '@/components/ui/tooltip';
import type { QueryTemplateDetail } from '@/lib/api/query-templates';
import {
  SearchSpaceBuilder,
  parseSearchSpace,
  stringifySearchSpace,
} from '@/components/studies/search-space-builder';

type Fixture = {
  name: string;
  value: string;
  /** When omitted → fixture is already canonical; expect zero onChange calls. */
  expectedAfter?: string;
};

// 8 spec-listed fixtures (already canonical):
const SPEC_FIXTURES: Fixture[] = [
  {
    name: 'boost-only float',
    value:
      '{\n  "params": {\n    "boost": {\n      "type": "float",\n      "low": 0.5,\n      "high": 10,\n      "log": true\n    }\n  }\n}',
  },
  {
    name: 'mixed float+int',
    value:
      '{\n  "params": {\n    "boost": {\n      "type": "float",\n      "low": 0.5,\n      "high": 10\n    },\n    "min_should_match": {\n      "type": "int",\n      "low": 0,\n      "high": 5\n    }\n  }\n}',
  },
  {
    name: 'fuzziness categorical',
    value:
      '{\n  "params": {\n    "fuzziness": {\n      "type": "categorical",\n      "choices": [\n        "AUTO",\n        "0",\n        "1",\n        "2"\n      ]\n    }\n  }\n}',
  },
  {
    name: 'log float',
    value:
      '{\n  "params": {\n    "boost": {\n      "type": "float",\n      "low": 0.5,\n      "high": 10,\n      "log": true\n    }\n  }\n}',
  },
  {
    name: 'log-with-low<=0',
    value:
      '{\n  "params": {\n    "boost": {\n      "type": "float",\n      "low": -1,\n      "high": 10,\n      "log": true\n    }\n  }\n}',
  },
  {
    name: 'multi-param hitting cap',
    value:
      '{\n  "params": {\n    "a": {\n      "type": "float",\n      "low": 0,\n      "high": 1\n    },\n    "b": {\n      "type": "float",\n      "low": 0,\n      "high": 1\n    },\n    "c": {\n      "type": "int",\n      "low": 0,\n      "high": 100000\n    }\n  }\n}',
  },
  {
    name: 'placeholder categorical',
    value:
      '{\n  "params": {\n    "operator": {\n      "type": "categorical",\n      "choices": [\n        "__placeholder__"\n      ]\n    }\n  }\n}',
  },
  {
    name: 'empty params object',
    value: '{\n  "params": {}\n}',
  },
  // Spec fixture #9: duplicate categorical choices survive (no auto-dedup per FR-5):
  {
    name: 'duplicate categorical choices',
    value:
      '{\n  "params": {\n    "operator": {\n      "type": "categorical",\n      "choices": [\n        "AUTO",\n        "AUTO",\n        "BM25"\n      ]\n    }\n  }\n}',
  },
];

// Spec fixtures #10 + #11: numeric normalization on first canonical pass.
const NORMALIZATION_FIXTURES: Fixture[] = [
  {
    name: 'numeric normalization 10.0 → 10',
    value:
      '{\n  "params": {\n    "boost": {\n      "type": "float",\n      "low": 0.5,\n      "high": 10.0\n    }\n  }\n}',
    expectedAfter:
      '{\n  "params": {\n    "boost": {\n      "type": "float",\n      "low": 0.5,\n      "high": 10\n    }\n  }\n}',
  },
  {
    name: 'exponent normalization 1e-3 → 0.001',
    value:
      '{\n  "params": {\n    "boost": {\n      "type": "float",\n      "low": 1e-3,\n      "high": 1\n    }\n  }\n}',
    expectedAfter:
      '{\n  "params": {\n    "boost": {\n      "type": "float",\n      "low": 0.001,\n      "high": 1\n    }\n  }\n}',
  },
];

const TEMPLATE: QueryTemplateDetail = {
  id: 't1',
  name: 'test-template',
  engine_type: 'elasticsearch',
  body: '{}',
  declared_params: { boost: 'float', operator: 'string' },
  version: 1,
  parent_id: null,
  created_at: '2026-05-20T00:00:00Z',
};

function mount(value: string): { spy: ReturnType<typeof vi.fn>; unmount: () => void } {
  const spy = vi.fn();
  const { unmount } = render(
    <TooltipProvider delayDuration={0}>
      <SearchSpaceBuilder
        value={value}
        onChange={spy}
        templateBody={TEMPLATE}
        templateId="t1"
        templateFetchStatus="ok"
      />
    </TooltipProvider>,
  );
  return { spy, unmount };
}

describe('SearchSpaceBuilder round-trip parity', () => {
  describe('already-canonical fixtures (deepEqual symmetry; zero onChange)', () => {
    for (const fixture of SPEC_FIXTURES) {
      it(fixture.name, () => {
        const { spy, unmount } = mount(fixture.value);
        // No write fires when input is already canonical.
        expect(spy).not.toHaveBeenCalled();
        // Semantic equality via the pure helpers (sanity check).
        const parsed = parseSearchSpace(fixture.value);
        expect(parsed.ok).toBe(true);
        if (parsed.ok) {
          const restringified = stringifySearchSpace(
            parsed.data as Parameters<typeof stringifySearchSpace>[0],
          );
          expect(JSON.parse(restringified)).toEqual(JSON.parse(fixture.value));
        }
        unmount();
      });
    }
  });

  describe('normalization fixtures (exactly one canonical write on first mount)', () => {
    for (const fixture of NORMALIZATION_FIXTURES) {
      it(fixture.name, () => {
        const { spy, unmount } = mount(fixture.value);
        expect(spy).toHaveBeenCalledTimes(1);
        expect(spy).toHaveBeenCalledWith(fixture.expectedAfter);
        unmount();
      });
    }

    it('idempotence: re-mounting with the canonical value emits nothing', () => {
      const fixture = NORMALIZATION_FIXTURES[0]!;
      const { spy, unmount } = mount(fixture.expectedAfter!);
      expect(spy).not.toHaveBeenCalled();
      unmount();
    });
  });

  describe('supplemental: pure-helper assertions', () => {
    it('parseSearchSpace returns ok for empty string', () => {
      expect(parseSearchSpace('')).toEqual({ ok: true, data: {} });
    });

    it('parseSearchSpace returns error for unparseable JSON', () => {
      const result = parseSearchSpace('{not valid');
      expect(result.ok).toBe(false);
      if (!result.ok) expect(result.error.length).toBeGreaterThan(0);
    });

    it('stringifySearchSpace round-trips a valid SearchSpaceJson symmetrically', () => {
      const data = { params: { boost: { type: 'float', low: 0.5, high: 10 } } } as const;
      const text = stringifySearchSpace(data);
      const parsed = parseSearchSpace(text);
      expect(parsed.ok).toBe(true);
      if (parsed.ok) expect(parsed.data).toEqual(data);
    });
  });
});
