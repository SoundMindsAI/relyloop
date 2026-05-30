// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * E2E: source filter widened to `click` (feat_ubi_judgments FR-10).
 *
 * After a UBI generation produces `source='click'` judgments, the
 * judgment-list DataTable's Source filter offers a `click` chip that drives
 * `?source=click` and shows the UBI rows; the `llm` chip (no LLM rows on a
 * pure-CTR list) shows the empty state. Exercises the FR-10 filter widening
 * browser-visibly.
 *
 * Real-backend, no mocking. Runs the real worker (pure CTR → no OpenAI).
 */
import { expect, test } from '@playwright/test';

import { seedQuerySet } from './helpers/seed';
import { seedUbiForQuerySet, teardownUbi, type UbiQueryRow } from './helpers/seed_ubi';

const API_BASE = process.env.PLAYWRIGHT_API_BASE_URL ?? 'http://127.0.0.1:8000';
const TARGET = 'products';

test.describe('UBI source filter — click widening', () => {
  // Polls the worker round-trip up to 60s; raise above Playwright's 30s default.
  test.setTimeout(90_000);

  test.afterEach(async () => {
    await teardownUbi();
  });

  test('click chip filters to UBI rows; llm chip is empty on a pure-CTR list', async ({
    page,
    request,
  }) => {
    const qs = await seedQuerySet(2);
    const ubiQueries: UbiQueryRow[] = qs.queryIds.map((_id, i) => ({
      queryId: `ubi-q-${i}`,
      userQuery: `e2e query ${i}`,
    }));
    await seedUbiForQuerySet({
      target: TARGET,
      queries: ubiQueries,
      docIds: ['doc-a', 'doc-b', 'doc-c'],
      impressionsPerPair: 90, // 2 × 3 × 90 = 540 → rung_3
      clicksPerQuery: 40,
    });

    // Generate via the dialog (browser interaction).
    await page.goto(`/query-sets/${qs.querySetId}`);
    await page.getByTestId('open-generate-judgments').click();
    await page.getByTestId('gen-name').fill(`e2e-ubi-srcfilter-${Date.now()}`);
    await page.getByTestId('gen-target').fill(TARGET);
    await expect(page.getByTestId('gen-method')).toContainText('UBI (click-through)', {
      timeout: 10_000,
    });
    await page.getByTestId('generate-submit').click();

    // Poll the new list to completion (setup-style API read).
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
          const list = body.data[0];
          if (!list) return 'pending';
          listId = list.id;
          return list.status;
        },
        { timeout: 60_000, intervals: [1_000, 2_000, 3_000] },
      )
      .toBe('complete');

    await page.goto(`/judgments/${listId}`);
    await expect(
      page.getByTestId('judgments-table').or(page.getByTestId('data-table-empty-no-rows-exist')),
    ).toBeVisible({ timeout: 10_000 });

    // The `click` source chip exists (FR-10 widening) + drives ?source=click.
    await page.getByTestId('filter-chip-source-click').click();
    await expect(page).toHaveURL(/[?&]source=click/);
    await expect(page.getByTestId('judgments-table')).toBeVisible({ timeout: 10_000 });

    // The `llm` chip → empty state (pure-CTR list has no LLM rows).
    await page.getByTestId('filter-chip-source-llm').click();
    await expect(page).toHaveURL(/[?&]source=llm/);
    await expect(page.getByTestId('data-table-empty-no-rows-match')).toBeVisible({
      timeout: 10_000,
    });
  });
});
