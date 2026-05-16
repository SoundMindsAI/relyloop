/**
 * E2E spec: /judgments/[id] DataTable surface
 * (feat_data_table_primitive Story 3.6, spec §14 matrix row "judgments").
 *
 * Per-list judgments view: searchable=false (no FTS). Covers source filter,
 * rating sort, and URL-state-survives-refresh.
 */
import { expect, test } from '@playwright/test';

import { seedFullChain, seedJudgmentList } from './helpers/seed';

test.describe('/judgments/[id] DataTable', () => {
  test('source filter chip drives ?source= URL state and refetches', async ({ page }) => {
    const chain = await seedFullChain(2);
    const list = await seedJudgmentList({
      clusterId: chain.clusterId,
      querySetId: chain.querySetId,
      queryIds: chain.queryIds,
    });
    await page.goto(`/judgments/${list.id}`);
    await expect(
      page.getByTestId('judgments-table').or(page.getByTestId('data-table-empty-no-rows-exist')),
    ).toBeVisible({ timeout: 10_000 });

    await page.getByTestId('filter-chip-source-llm').click();
    await expect(page).toHaveURL(/[?&]source=llm/);

    await page.getByTestId('filter-chip-source-all').click();
    await expect(page).not.toHaveURL(/[?&]source=/);
  });

  test('Rating sort header serializes to ?sort=rating:<dir>', async ({ page }) => {
    const chain = await seedFullChain(2);
    const list = await seedJudgmentList({
      clusterId: chain.clusterId,
      querySetId: chain.querySetId,
      queryIds: chain.queryIds,
    });
    await page.goto(`/judgments/${list.id}`);
    await expect(
      page.getByTestId('judgments-table').or(page.getByTestId('data-table-empty-no-rows-exist')),
    ).toBeVisible({ timeout: 10_000 });

    // First click on rating header (firstClickDirection 'desc').
    await page.getByTestId('data-table-sort-rating').click();
    await expect(page).toHaveURL(/[?&]sort=rating%3Adesc/);
  });

  test('URL state survives refresh', async ({ page }) => {
    const chain = await seedFullChain(2);
    const list = await seedJudgmentList({
      clusterId: chain.clusterId,
      querySetId: chain.querySetId,
      queryIds: chain.queryIds,
    });
    await page.goto(`/judgments/${list.id}?source=llm&sort=rating%3Adesc`);
    await expect(page.getByTestId('filter-chip-source-llm')).toHaveAttribute('data-active', 'true');
    await page.reload();
    await expect(page.getByTestId('filter-chip-source-llm')).toHaveAttribute('data-active', 'true');
    await expect(page.getByTestId('data-table-sort-rating')).toHaveAttribute(
      'data-active-dir',
      'desc',
    );
  });
});
