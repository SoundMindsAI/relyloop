/**
 * E2E: UBI hybrid mode + sparse-data card (feat_ubi_judgments FR-8 Capability C).
 *
 * Sparse UBI traffic → rung_1 → the method picker defaults to
 * `Hybrid UBI + LLM`. Switching the picker to a pure UBI converter surfaces
 * the sparse-data recommendation card, whose "Switch to Hybrid" affordance
 * flips the picker back. This is a UI-state spec (no submit) — full hybrid
 * generation needs OpenAI, out of scope for a hermetic E2E run; the
 * generation path itself is covered by the rung-3 + backend tests.
 *
 * Real-backend: the readiness probe hits the live ES with a sparse
 * `ubi_events` set (< min_impressions_threshold) → rung_1. No mocking.
 */
import { expect, test } from '@playwright/test';

import { seedQuerySet } from './helpers/seed';
import { seedUbiForQuerySet, teardownUbi, type UbiQueryRow } from './helpers/seed_ubi';

const TARGET = 'products';

test.describe('UBI hybrid mode — rung_1 (sparse)', () => {
  test.afterEach(async () => {
    await teardownUbi();
  });

  test('rung_1 defaults to hybrid; pure-converter switch shows sparse card', async ({ page }) => {
    const qs = await seedQuerySet(2);
    const ubiQueries: UbiQueryRow[] = qs.queryIds.map((_id, i) => ({
      queryId: `ubi-q-${i}`,
      userQuery: `e2e query ${i}`,
    }));
    // ~30 events total — below min_impressions_threshold (100) → rung_1.
    await seedUbiForQuerySet({
      target: TARGET,
      queries: ubiQueries,
      docIds: ['doc-a', 'doc-b'],
      impressionsPerPair: 6, // 2 × 2 × 6 = 24 impressions
      clicksPerQuery: 2, // + 2×2 = 4 clicks → 28 events, < 100 → rung_1
    });

    await page.goto(`/query-sets/${qs.querySetId}`);
    await page.getByTestId('open-generate-judgments').click();
    await expect(page.getByTestId('generate-form')).toBeVisible({ timeout: 5_000 });
    await page.getByTestId('gen-target').fill(TARGET);

    // rung_1 → picker auto-defaults to Hybrid; sparse card NOT shown yet
    // (it only appears when a PURE converter is selected).
    await expect(page.getByTestId('gen-method')).toContainText('Hybrid UBI + LLM', {
      timeout: 10_000,
    });
    await expect(page.getByTestId('ubi-sparse-data-card')).toHaveCount(0);

    // Switch the picker to a pure converter (UBI click-through) → sparse card appears.
    await page.getByTestId('gen-method').click();
    await page.getByRole('option', { name: 'UBI (click-through)' }).click();
    await expect(page.getByTestId('ubi-sparse-data-card')).toBeVisible({ timeout: 5_000 });

    // "Switch to Hybrid" flips the picker back to hybrid + dismisses the card.
    await page.getByTestId('ubi-sparse-switch-to-hybrid').click();
    await expect(page.getByTestId('gen-method')).toContainText('Hybrid UBI + LLM');
    await expect(page.getByTestId('ubi-sparse-data-card')).toHaveCount(0);
  });
});
