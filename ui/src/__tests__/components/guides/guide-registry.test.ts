// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import { GUIDE_MAP, GUIDE_REGISTRY, guidesForPath } from '@/components/guides/guide-types';

// Resolve repo root from this test file: ui/src/__tests__/components/guides → up 4 → ui → up 1 → repo root.
const REPO_ROOT = join(__dirname, '..', '..', '..', '..', '..');

function readGuideMetadata(guideId: string): {
  title: string;
  description: string;
  screenshots: Array<{ file: string; caption: string }>;
} {
  const p = join(REPO_ROOT, 'ui', 'public', 'guides', guideId, 'metadata.json');
  return JSON.parse(readFileSync(p, 'utf-8'));
}

describe('GUIDE_REGISTRY', () => {
  it('matches the metadata.json title/description for every registered guide', () => {
    for (const entry of GUIDE_REGISTRY) {
      const meta = readGuideMetadata(entry.id);
      expect(meta.title, `title mismatch for ${entry.id}`).toBe(entry.title);
      expect(meta.description, `description mismatch for ${entry.id}`).toBe(entry.description);
      expect(meta.screenshots.length, `${entry.id} has no screenshots`).toBeGreaterThan(0);
    }
  });

  it('GUIDE_MAP entries point at ids that exist in GUIDE_REGISTRY', () => {
    const registryIds = new Set(GUIDE_REGISTRY.map((g) => g.id));
    for (const entry of GUIDE_MAP) {
      expect(registryIds.has(entry.guideId), `unknown guideId ${entry.guideId} in GUIDE_MAP`).toBe(
        true,
      );
    }
  });

  it('guidesForPath returns the right matches', () => {
    expect(guidesForPath('/clusters')).toHaveLength(1);
    expect(guidesForPath('/clusters/abc-123')).toHaveLength(1); // prefix match
    // /proposals has two registered guides (browse + review).
    expect(guidesForPath('/proposals')).toHaveLength(2);
    expect(guidesForPath('/templates')).toHaveLength(1);
    expect(guidesForPath('/some-other-route')).toHaveLength(0);
  });
});
