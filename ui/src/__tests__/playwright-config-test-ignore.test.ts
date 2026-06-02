// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Source-of-truth lint guard test
 * (`infra_smoke_reseed_runtime_budget` FR-2 / AC-3).
 *
 * Reads `ui/playwright.config.ts` as text and asserts the structural shape
 * of the `testIgnore` CI-gated branch:
 *
 *   1. `'**\/demo-ubi.spec.ts'` is present inside the `process.env.CI ?
 *      [...]` ternary's true branch (so the CI smoke job excludes it).
 *   2. All 7 expected CI-gated spec entries are present in that branch
 *      (the 6 pre-existing demo-data-dependent specs +
 *      `demo-ubi.spec.ts`). Catches regression where any sibling entry
 *      gets silently removed during a config refactor.
 *   3. `'**\/demo-ubi.spec.ts'` does NOT appear outside the CI ternary
 *      (i.e., is not in the always-ignored slot next to
 *      `'**\/guides/**'`). Local coverage stays intact.
 *
 * Text-grep is intentional (see spec D-7): lowest-coupling, no
 * module-reload tricks, and the test serves as a comment-anchor that
 * future editors can't miss when they touch the config.
 *
 * AC-1 (CI excludes demo-ubi) and AC-2 (local includes demo-ubi) are
 * Playwright discovery behaviors and are verified once manually via
 * `playwright test --list` at PR review (spec §16). This test holds the
 * config-file-shape invariant on every subsequent commit.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

const CONFIG_PATH = join(process.cwd(), 'playwright.config.ts');

// Source of truth: the 7 spec files the CI-gated testIgnore branch must
// list after `infra_smoke_reseed_runtime_budget` ships. Order in this
// array doesn't matter (we check membership, not sequence), but matches
// the order they appear in the config file for readability.
const EXPECTED_CI_GATED_ENTRIES: readonly string[] = [
  "'**/dashboard.spec.ts'",
  "'**/dashboard-reseed.spec.ts'",
  "'**/auto-followup.spec.ts'",
  "'**/index-document-browser.spec.ts'",
  "'**/studies-create-builder.spec.ts'",
  "'**/studies-create-target-dropdown.spec.ts'",
  "'**/demo-ubi.spec.ts'",
];

const DEMO_UBI_ENTRY = "'**/demo-ubi.spec.ts'";

/**
 * Slice the `playwright.config.ts` source into three regions:
 *
 *   - `beforeCi`: everything before `process.env.CI`
 *   - `ciBranch`: the contents of the `?  [ ... ]` true branch of the
 *     `process.env.CI ? [...] : []` ternary (between the `[` and the
 *     matching `]`)
 *   - `afterCi`: everything after the closing `]` of that branch
 *
 * The split is anchored on a literal `process.env.CI` substring + the
 * next `? [` and the corresponding `]` (we look for the matching `: []`
 * closing-tag pair, which is the canonical shape of this ternary).
 *
 * If the config file ever stops using this exact ternary shape, this
 * test will fail loud with a clear "could not locate CI ternary"
 * message — which is the right failure mode (don't silently pass against
 * a config shape that doesn't match what we're guarding).
 */
function sliceConfig(source: string): {
  beforeCi: string;
  ciBranch: string;
  afterCi: string;
} {
  const ciIdx = source.indexOf('process.env.CI');
  if (ciIdx === -1) {
    throw new Error(
      'Could not locate `process.env.CI` in playwright.config.ts — testIgnore CI-ternary shape changed?',
    );
  }
  // Find the `? [` after process.env.CI.
  const openBracketIdx = source.indexOf('? [', ciIdx);
  if (openBracketIdx === -1) {
    throw new Error(
      'Could not locate `? [` after `process.env.CI` — testIgnore CI-ternary shape changed?',
    );
  }
  // Find the matching `] : []` close that ends the ternary.
  const closeIdx = source.indexOf(']\n      : []', openBracketIdx);
  if (closeIdx === -1) {
    throw new Error(
      'Could not locate `] : []` closing the CI ternary — testIgnore CI-ternary shape changed?',
    );
  }
  return {
    beforeCi: source.slice(0, ciIdx),
    ciBranch: source.slice(openBracketIdx, closeIdx),
    afterCi: source.slice(closeIdx),
  };
}

describe('playwright.config.ts testIgnore CI-gated branch', () => {
  const source = readFileSync(CONFIG_PATH, 'utf8');
  const slices = sliceConfig(source);

  it("includes '**/demo-ubi.spec.ts' inside the process.env.CI ternary's true branch", () => {
    expect(slices.ciBranch).toContain(DEMO_UBI_ENTRY);
  });

  it('lists all 7 expected CI-gated spec entries (6 pre-existing + demo-ubi)', () => {
    const missing = EXPECTED_CI_GATED_ENTRIES.filter((entry) => !slices.ciBranch.includes(entry));
    expect(missing).toEqual([]);
  });

  it("does NOT list '**/demo-ubi.spec.ts' outside the CI ternary (local coverage stays intact)", () => {
    expect(slices.beforeCi).not.toContain(DEMO_UBI_ENTRY);
    expect(slices.afterCi).not.toContain(DEMO_UBI_ENTRY);
  });
});
