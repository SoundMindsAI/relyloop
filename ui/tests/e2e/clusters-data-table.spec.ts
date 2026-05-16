/**
 * E2E spec: /clusters DataTable surface
 * (feat_data_table_primitive Story 3.3, spec §14 matrix row "clusters").
 *
 * Covers FTS search, sort, engine_type filter, environment filter, and
 * URL-state-survives-refresh. Runs against the real `make up` stack.
 */
import { expect, test } from '@playwright/test';

import { seedCluster } from './helpers/seed';

test.describe('/clusters DataTable', () => {
  test('search input drives ?q= URL state', async ({ page }) => {
    const cluster = await seedCluster();
    await page.goto('/clusters');
    await expect(page.getByTestId('clusters-table')).toBeVisible({ timeout: 5_000 });

    const fragment = cluster.name.slice(0, 8);
    await page.getByTestId('data-table-search').fill(fragment);
    await expect(page).toHaveURL(new RegExp(`[?&]q=${fragment}`), { timeout: 2_000 });
    await expect(page.getByText(cluster.name).first()).toBeVisible();
  });

  test('engine_type filter chip drives ?engine_type= URL state', async ({ page }) => {
    await page.goto('/clusters');
    await expect(
      page.getByTestId('clusters-table').or(page.getByTestId('data-table-empty-no-rows-exist')),
    ).toBeVisible({ timeout: 5_000 });

    await page.getByTestId('filter-chip-engine_type-elasticsearch').click();
    await expect(page).toHaveURL(/[?&]engine_type=elasticsearch/);

    await page.getByTestId('filter-chip-engine_type-all').click();
    await expect(page).not.toHaveURL(/[?&]engine_type=/);
  });

  test('environment filter chip drives ?environment= URL state', async ({ page }) => {
    await page.goto('/clusters');
    await expect(
      page.getByTestId('clusters-table').or(page.getByTestId('data-table-empty-no-rows-exist')),
    ).toBeVisible({ timeout: 5_000 });

    await page.getByTestId('filter-chip-environment-prod').click();
    await expect(page).toHaveURL(/[?&]environment=prod/);
  });

  test('sortable Name column header serializes to ?sort=name:<dir>', async ({ page }) => {
    await page.goto('/clusters');
    await expect(
      page.getByTestId('clusters-table').or(page.getByTestId('data-table-empty-no-rows-exist')),
    ).toBeVisible({ timeout: 5_000 });

    await page.getByTestId('data-table-sort-name').click();
    await expect(page).toHaveURL(/[?&]sort=name%3Aasc/);

    await page.getByTestId('data-table-sort-name').click();
    await expect(page).toHaveURL(/[?&]sort=name%3Adesc/);

    await page.getByTestId('data-table-sort-name').click();
    await expect(page).not.toHaveURL(/[?&]sort=/);
  });

  test('URL state survives a hard refresh', async ({ page }) => {
    await page.goto('/clusters?engine_type=elasticsearch&sort=name%3Aasc');
    await expect(page.getByTestId('filter-chip-engine_type-elasticsearch')).toHaveAttribute(
      'data-active',
      'true',
    );
    await expect(page.getByTestId('data-table-sort-name')).toHaveAttribute('data-active-dir', 'asc');

    await page.reload();
    await expect(page.getByTestId('filter-chip-engine_type-elasticsearch')).toHaveAttribute(
      'data-active',
      'true',
    );
    await expect(page.getByTestId('data-table-sort-name')).toHaveAttribute('data-active-dir', 'asc');
  });
});
