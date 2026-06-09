// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Three-way parity — JS side (feat_query_normalizer_typed_pipeline FR-5 / Q-2).
 *
 * Reads the committed shared corpus fixture
 * (`fixtures/normalizer_snippet_parity.json`), evaluates each operator-facing
 * `jsSnippet` via `new Function`, and asserts its `normalizeQuery` output
 * equals `expected` for every corpus input. `expected` is the Python runtime
 * (`normalize_pipeline`) output — the backend test
 * `test_normalizers_pr_snippets_js.py` keeps the fixture in sync with both the
 * runtime and `build_js_snippet`, so passing here proves
 * JS == runtime == Python over the corpus.
 */

import { describe, expect, it } from 'vitest';

import fixture from './fixtures/normalizer_snippet_parity.json';

type Case = { label: string; jsSnippet: string; expected: string[] };

const corpus: string[] = fixture.corpus;
const cases: Case[] = fixture.cases;

function loadNormalizeQuery(jsSnippet: string): (q: string) => string {
  // The snippet declares `function normalizeQuery(...)`; return a reference.
  return new Function(`${jsSnippet}\nreturn normalizeQuery;`)() as (q: string) => string;
}

describe('normalizer snippet JS parity', () => {
  it('has a non-empty corpus and cases', () => {
    expect(corpus.length).toBeGreaterThan(0);
    expect(cases.length).toBeGreaterThan(0);
  });

  it.each(cases)('JS snippet for "$label" matches runtime over the corpus', (c) => {
    const fn = loadNormalizeQuery(c.jsSnippet);
    expect(c.expected).toHaveLength(corpus.length);
    corpus.forEach((input, i) => {
      expect(fn(input)).toBe(c.expected[i]);
    });
  });
});
