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

    // bug_judgment_header_omits_click_bucket (AC-4): the header surfaces the
    // `click` bucket so the three displayed terms sum to the total. On a
    // pure-CTR list that is `0 / 0 / {clickCount}` with clickCount > 0.
    const detailResp = await request.get(
      new URL(`/api/v1/judgment-lists/${listId}`, API_BASE).toString(),
    );
    expect(detailResp.ok()).toBeTruthy();
    const detail = (await detailResp.json()) as {
      source_breakdown: { llm: number; human: number; click: number };
    };
    expect(detail.source_breakdown.click).toBeGreaterThan(0);
    const { llm, human, click } = detail.source_breakdown;
    await expect(page.getByTestId('header-breakdown')).toBeVisible();
    // Locale-robust: parse the three integers out of the rendered text rather
    // than compare against Node's toLocaleString() (which can differ from the
    // browser's locale separators). Per Gemini Code Assist review on PR #470.
    const breakdownText = (await page.getByTestId('header-breakdown').textContent()) ?? '';
    const parsedBreakdown = breakdownText
      .split('/')
      .map((part) => parseInt(part.replace(/[^\d]/g, ''), 10));
    expect(parsedBreakdown).toEqual([llm, human, click]);
    await expect(page.getByText('LLM / Human / Clicks')).toBeVisible();

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
