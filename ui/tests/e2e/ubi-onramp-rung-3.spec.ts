// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * E2E: UBI generation at rung_3 (feat_ubi_judgments FR-5 + FR-7 + FR-8).
 *
 * Dense UBI traffic → the method picker defaults to a pure UBI converter
 * (`ctr_threshold`); submitting runs the real `generate_judgments_from_ubi`
 * Arq worker against the live ES `ubi_queries`/`ubi_events` indices and
 * produces `source='click'` judgments. We assert the browser-visible
 * outcome: the judgment-list detail page renders click rows.
 *
 * Real-backend, no mocking. Requires the worker service running (it is, in
 * the Compose stack) and ES reachable. No OpenAI needed — pure CTR converter.
 */
import { expect, test } from '@playwright/test';

import { seedQuerySet } from './helpers/seed';
import { seedUbiForQuerySet, teardownUbi, type UbiQueryRow } from './helpers/seed_ubi';

const API_BASE = process.env.PLAYWRIGHT_API_BASE_URL ?? 'http://127.0.0.1:8000';
const TARGET = 'products';

test.describe('UBI generation — rung_3 (dense)', () => {
  // The worker round-trip is polled up to 60s; raise the test timeout above
  // Playwright's 30s default so the poll can actually observe completion.
  test.setTimeout(90_000);

  test.afterEach(async () => {
    await teardownUbi();
  });

  test('picker defaults to CTR; submit produces click judgments', async ({ page, request }) => {
    const qs = await seedQuerySet(3);

    // Map each seeded query's text ("e2e query N") to a UBI query_id so the
    // worker's mapping_strategy join resolves 1:1. ~600 events → rung_3.
    const ubiQueries: UbiQueryRow[] = qs.queryIds.map((_id, i) => ({
      queryId: `ubi-q-${i}`,
      userQuery: `e2e query ${i}`,
    }));
    await seedUbiForQuerySet({
      target: TARGET,
      queries: ubiQueries,
      docIds: ['doc-a', 'doc-b', 'doc-c'],
      impressionsPerPair: 70, // 3 queries × 3 docs × 70 = 630 impressions → rung_3
      clicksPerQuery: 30, // strong CTR on doc-a → rating ≥ 1
      dwellSeconds: 45,
    });

    await page.goto(`/query-sets/${qs.querySetId}`);
    await page.getByTestId('open-generate-judgments').click();
    await expect(page.getByTestId('generate-form')).toBeVisible({ timeout: 5_000 });
    await page.getByTestId('gen-name').fill(`e2e-ubi-rung3-${Date.now()}`);
    await page.getByTestId('gen-target').fill(TARGET);

    // rung_3 → picker auto-defaults to "UBI (click-through)".
    await expect(page.getByTestId('gen-method')).toContainText('UBI (click-through)', {
      timeout: 10_000,
    });
    // No on-ramp nudge at rung_3.
    await expect(page.getByTestId('ubi-onramp-nudge')).toHaveCount(0);

    await page.getByTestId('generate-submit').click();

    // Discover the new judgment list (setup-style API read) + poll to complete.
    let listId = '';
    await expect
      .poll(
        async () => {
          const resp = await request.get(
            new URL(
              `/api/v1/judgment-lists?query_set_id=${qs.querySetId}&limit=10`,
              API_BASE,
            ).toString(),
          );
          if (!resp.ok()) return 'pending';
          const body = (await resp.json()) as { data: Array<{ id: string; status: string }> };
          const ubiList = body.data[0];
          if (!ubiList) return 'pending';
          listId = ubiList.id;
          return ubiList.status;
        },
        { timeout: 60_000, intervals: [1_000, 2_000, 3_000] },
      )
      .toBe('complete');

    // Browser-visible assertion: the UBI detail page renders the value-delta
    // card (only shown for UBI/hybrid lists) — proves the worker wrote a
    // UBI-shaped calibration + generation_params.
    await page.goto(`/judgments/${listId}`);
    await expect(page.getByTestId('value-delta-card')).toBeVisible({ timeout: 10_000 });
  });
});
