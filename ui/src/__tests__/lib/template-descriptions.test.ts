// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * FR-7 vitest assertions for the runnable template library
 * (`chore_template_library_expansion` Story 3.1).
 *
 * The plan's DoD requires: "the summary text appears after picking a
 * known template AND degrades gracefully on a miss". This is the
 * lightweight component-level verification of that contract — the
 * heavier `create-study-modal.*` integration tests don't need to grow
 * a per-template assertion since the data flow is `name` → `descriptionFor`.
 */

import { describe, expect, it } from 'vitest';

import { ENGINE_TYPE_VALUES } from '@/lib/enums';
import {
  TEMPLATE_DESCRIPTIONS,
  cheatsheetUrlFor,
  descriptionFor,
} from '@/lib/template-descriptions';

describe('descriptionFor', () => {
  it('returns a one-line summary for each known recommended registration name', () => {
    // Every entry in TEMPLATE_DESCRIPTIONS resolves through the lookup,
    // and the summary is non-empty + reasonably short (single sentence
    // shape that the Step-3 picker can render inline without line wrap).
    for (const [name, expected] of Object.entries(TEMPLATE_DESCRIPTIONS)) {
      const summary = descriptionFor(name);
      expect(summary, `descriptionFor(${name}) should return a string`).toBe(expected);
      expect(summary?.length ?? 0).toBeGreaterThan(20);
      expect(summary?.length ?? 0).toBeLessThan(250);
    }
  });

  it('returns null for an unknown template name (graceful miss — FR-7 contract)', () => {
    // An operator who registered a template under a custom name MUST
    // see no summary rather than a wrong one. The Step-3 picker uses
    // this null to skip rendering entirely.
    expect(descriptionFor('completely-made-up-template')).toBeNull();
    expect(descriptionFor('')).toBeNull();
    expect(descriptionFor(null)).toBeNull();
    expect(descriptionFor(undefined)).toBeNull();
  });

  it('covers all 6 runnable library templates by recommended name', () => {
    // Catches drift if a future PR adds a template body + READMEs but
    // forgets to wire FR-7. The keys here match what the READMEs say
    // under "Recommended registration name".
    const expectedNames = [
      'multi-match-basic-v1',
      'function-score-decay-v1',
      'bool-boosted-v1',
      'rescore-phrase-v1',
      'edismax-basic-v1',
      'boost-decay-v1',
    ];
    for (const name of expectedNames) {
      expect(TEMPLATE_DESCRIPTIONS[name], `missing TEMPLATE_DESCRIPTIONS["${name}"]`).toBeTruthy();
    }
  });
});

describe('cheatsheetUrlFor', () => {
  it('resolves one URL per supported engine_type', () => {
    for (const engine of ENGINE_TYPE_VALUES) {
      const url = cheatsheetUrlFor(engine);
      expect(url, `cheatsheetUrlFor(${engine}) should be non-null`).toBeTruthy();
      // The URL must mention the engine's own cheatsheet filename — a
      // copy-paste typo (e.g. mapping `opensearch` → the ES cheatsheet)
      // gets caught here.
      expect(url).toContain(`${engine}-tunable-params.md`);
    }
  });

  it('returns null for unknown engine_type values (defense in depth)', () => {
    expect(cheatsheetUrlFor('vespa')).toBeNull();
    expect(cheatsheetUrlFor('typesense')).toBeNull();
    expect(cheatsheetUrlFor('')).toBeNull();
    expect(cheatsheetUrlFor(null)).toBeNull();
    expect(cheatsheetUrlFor(undefined)).toBeNull();
  });
});
