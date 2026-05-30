// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * E2E spec: /templates DataTable surface
 * (feat_data_table_primitive Story 3.4, spec §14 matrix row "templates").
 */
import { expect, test } from '@playwright/test';

import { seedTemplate } from './helpers/seed';

test.describe('/templates DataTable', () => {
  test('search input drives ?q= URL state', async ({ page }) => {
    const t = await seedTemplate();
    await page.goto('/templates');
    await expect(page.getByTestId('templates-table')).toBeVisible({ timeout: 5_000 });

    const frag = t.name.slice(0, 8);
    await page.getByTestId('data-table-search').fill(frag);
    await expect(page).toHaveURL(new RegExp(`[?&]q=${frag}`), { timeout: 2_000 });
  });

  test('engine_type filter chip drives ?engine_type= URL state', async ({ page }) => {
    await page.goto('/templates');
    await expect(
      page.getByTestId('templates-table').or(page.getByTestId('data-table-empty-no-rows-exist')),
    ).toBeVisible({ timeout: 5_000 });

    await page.getByTestId('filter-chip-engine_type-elasticsearch').click();
    await expect(page).toHaveURL(/[?&]engine_type=elasticsearch/);
  });

  test('Name sort header serializes to ?sort=name:<dir>', async ({ page }) => {
    await page.goto('/templates');
    await expect(
      page.getByTestId('templates-table').or(page.getByTestId('data-table-empty-no-rows-exist')),
    ).toBeVisible({ timeout: 5_000 });

    await page.getByTestId('data-table-sort-name').click();
    await expect(page).toHaveURL(/[?&]sort=name%3Aasc/);
  });

  test('URL state survives refresh', async ({ page }) => {
    await page.goto('/templates?engine_type=elasticsearch&sort=name%3Aasc');
    await page.reload();
    await expect(page.getByTestId('filter-chip-engine_type-elasticsearch')).toHaveAttribute(
      'data-active',
      'true',
    );
    await expect(page.getByTestId('data-table-sort-name')).toHaveAttribute('data-active-dir', 'asc');
  });
});
