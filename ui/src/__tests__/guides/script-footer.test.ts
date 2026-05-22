import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { GUIDE_REGISTRY } from '@/components/guides/guide-types';

/**
 * Locks the glossary cross-link footer added by chore_guides_glossary_route
 * to every shipped walkthrough's `script.md`. Vitest runs with `cwd=ui/`,
 * so we resolve from this test file's URL up to the repo root then into
 * `ui/public/guides/`.
 */

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, '../../../..');
const GUIDES_DIR = path.join(REPO_ROOT, 'ui', 'public', 'guides');

const FOOTER =
  '> See the [glossary](/guide/glossary) for definitions of every term used in this walkthrough.';

describe('Walkthrough script.md footers point at /guide/glossary (FR-7)', () => {
  it('every guide directory under ui/public/guides/ has a script.md', () => {
    const dirs = readdirSync(GUIDES_DIR, { withFileTypes: true })
      .filter((d) => d.isDirectory())
      .map((d) => d.name);
    expect(dirs.length).toBeGreaterThanOrEqual(GUIDE_REGISTRY.length);
    for (const guide of GUIDE_REGISTRY) {
      expect(dirs).toContain(guide.id);
    }
  });

  it.each(GUIDE_REGISTRY.map((g) => [g.id]))('%s/script.md ends with the glossary footer', (id) => {
    const p = path.join(GUIDES_DIR, id, 'script.md');
    const text = readFileSync(p, 'utf-8');
    // Footer must be present
    expect(text).toContain(FOOTER);
    // And appear at the tail of the file (last non-empty line ignoring
    // trailing whitespace)
    const lines = text.replace(/\s+$/, '').split('\n');
    expect(lines[lines.length - 1]).toBe(FOOTER);
  });

  it('the footer text matches the canonical pattern exactly (single source-of-truth)', () => {
    // Lock the wording — if a refactor changes one of the 10 files but not
    // the others, this test catches the divergence.
    for (const guide of GUIDE_REGISTRY) {
      const p = path.join(GUIDES_DIR, guide.id, 'script.md');
      const text = readFileSync(p, 'utf-8');
      const occurrences = text.split(FOOTER).length - 1;
      expect(occurrences).toBe(1);
    }
  });
});
