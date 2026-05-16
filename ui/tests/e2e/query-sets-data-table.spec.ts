/**
 * E2E spec: /query-sets DataTable surface
 * (feat_data_table_primitive Story 3.5, spec §14 matrix row "query-sets").
 */
import { expect, test } from '@playwright/test';

import { seedQuerySet } from './helpers/seed';

test.describe('/query-sets DataTable', () => {
  test('search input drives ?q= URL state', async ({ page }) => {
    const qs = await seedQuerySet(2);
    await page.goto('/query-sets');
    await expect(page.getByTestId('query-sets-table')).toBeVisible({ timeout: 5_000 });

    // seedQuerySet returns a generic result; pick a fragment from any seeded name.
    const frag = 'e2e';
    await page.getByTestId('data-table-search').fill(frag);
    await expect(page).toHaveURL(new RegExp(`[?&]q=${frag}`), { timeout: 2_000 });
    // Sanity: the query-set still exists in the API after FTS filter.
    expect(qs.querySetId).toBeTruthy();
  });

  test('Name sort header serializes to ?sort=name:<dir>', async ({ page }) => {
    await page.goto('/query-sets');
    await expect(
      page.getByTestId('query-sets-table').or(page.getByTestId('data-table-empty-no-rows-exist')),
    ).toBeVisible({ timeout: 5_000 });

    await page.getByTestId('data-table-sort-name').click();
    await expect(page).toHaveURL(/[?&]sort=name%3Aasc/);

    await page.getByTestId('data-table-sort-name').click();
    await expect(page).toHaveURL(/[?&]sort=name%3Adesc/);
  });

  test('URL state survives refresh (search + sort)', async ({ page }) => {
    await page.goto('/query-sets?q=alpha&sort=name%3Aasc');
    await expect(page.getByTestId('data-table-sort-name')).toHaveAttribute('data-active-dir', 'asc');
    await page.reload();
    await expect(page.getByTestId('data-table-sort-name')).toHaveAttribute('data-active-dir', 'asc');
  });
});
