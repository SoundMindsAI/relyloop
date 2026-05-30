// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * E2E spec: /query-sets/[id] queries DataTable surface
 * (feat_data_table_primitive Story 3.8, spec §14 matrix row "queries").
 *
 * Per-query sub-resource: searchable=false, no sort, no filter, no
 * selectable. Covers cursor pagination + URL-state-survives-refresh.
 */
import { expect, test } from '@playwright/test';

import { seedQuerySet } from './helpers/seed';

test.describe('/query-sets/[id] queries DataTable', () => {
  test('cursor pagination Next + Prev round-trips with URL state', async ({ page }) => {
    // Seed enough queries to span two pages at the smallest page size (10).
    const { querySetId } = await seedQuerySet(12);
    await page.goto(`/query-sets/${querySetId}?limit=10`);
    await expect(page.getByTestId('queries-table')).toBeVisible({ timeout: 5_000 });

    // Click Next — URL gains `?cursor=` (push so Back steps).
    await page.getByTestId('paginator-next').click();
    await expect(page).toHaveURL(/[?&]cursor=/, { timeout: 2_000 });

    // Click Prev — cursor pops off the URL.
    await page.getByTestId('paginator-prev').click();
    await expect(page).not.toHaveURL(/[?&]cursor=/);
  });

  test('page-size selector drives ?limit= URL state', async ({ page }) => {
    const { querySetId } = await seedQuerySet(3);
    await page.goto(`/query-sets/${querySetId}`);
    await expect(page.getByTestId('queries-table')).toBeVisible({ timeout: 5_000 });

    await page.getByTestId('page-size-select').selectOption('25');
    await expect(page).toHaveURL(/[?&]limit=25/);
  });

  test('URL state survives refresh (cursor + limit)', async ({ page }) => {
    const { querySetId } = await seedQuerySet(12);
    await page.goto(`/query-sets/${querySetId}?limit=10`);
    await expect(page.getByTestId('queries-table')).toBeVisible({ timeout: 5_000 });

    await page.getByTestId('paginator-next').click();
    await expect(page).toHaveURL(/[?&]cursor=/);

    await page.reload();
    await expect(page).toHaveURL(/[?&]cursor=/);
    await expect(page.getByTestId('queries-table')).toBeVisible({ timeout: 5_000 });
  });
});
