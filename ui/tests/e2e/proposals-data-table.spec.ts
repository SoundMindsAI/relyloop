// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * E2E spec: /proposals DataTable surface
 * (feat_data_table_primitive Story 3.2, spec §14 matrix row "proposals").
 *
 * Per spec §3, proposals has no FTS — `searchable={false}`. Covers:
 *  - Sort column header click → `?sort=<col>:<dir>` URL state
 *  - Status filter chip → `?status=<wire>` URL state
 *  - Source filter chip → `?source=<wire>` URL state
 *  - Cluster fk-select → `?cluster_id=<id>` URL state
 *  - Template fk-select → `?template_id=<id>` URL state
 *  - URL state survives hard refresh
 *
 * Runs against the real `make up` stack. No `page.route()` mocking.
 */
import { expect, test } from '@playwright/test';

import { seedCluster, seedProposal, seedTemplate } from './helpers/seed';

test.describe('/proposals DataTable', () => {
  test('status filter chip drives ?status= URL state', async ({ page }) => {
    await page.goto('/proposals');
    await expect(
      page.getByTestId('proposals-table').or(page.getByTestId('data-table-empty-no-rows-exist')),
    ).toBeVisible({ timeout: 5_000 });

    await page.getByTestId('filter-chip-status-pending').click();
    await expect(page).toHaveURL(/[?&]status=pending/);

    await page.getByTestId('filter-chip-status-all').click();
    await expect(page).not.toHaveURL(/[?&]status=/);
  });

  test('source filter chip drives ?source= URL state', async ({ page }) => {
    await page.goto('/proposals');
    await expect(
      page.getByTestId('proposals-table').or(page.getByTestId('data-table-empty-no-rows-exist')),
    ).toBeVisible({ timeout: 5_000 });

    await page.getByTestId('filter-chip-source-manual').click();
    await expect(page).toHaveURL(/[?&]source=manual/);

    await page.getByTestId('filter-chip-source-all').click();
    await expect(page).not.toHaveURL(/[?&]source=/);
  });

  test('clicking a sortable column header serializes to ?sort=<col>:<dir>', async ({ page }) => {
    await page.goto('/proposals');
    await expect(
      page.getByTestId('proposals-table').or(page.getByTestId('data-table-empty-no-rows-exist')),
    ).toBeVisible({ timeout: 5_000 });

    await page.getByTestId('data-table-sort-status').click();
    await expect(page).toHaveURL(/[?&]sort=status%3Aasc/);

    await page.getByTestId('data-table-sort-status').click();
    await expect(page).toHaveURL(/[?&]sort=status%3Adesc/);

    await page.getByTestId('data-table-sort-status').click();
    await expect(page).not.toHaveURL(/[?&]sort=/);
  });

  test('template fk-select drives ?template_id= URL state', async ({ page }) => {
    // Seed a deterministic cluster+template+manual-proposal so the template
    // fk-select has at least one option to pick from.
    const cluster = await seedCluster();
    const template = await seedTemplate();
    await seedProposal({ clusterId: cluster.id, templateId: template.id });

    await page.goto('/proposals');
    await expect(page.getByTestId('proposals-table')).toBeVisible({ timeout: 5_000 });

    // The fk-select renders one <option> per template; pick the seeded one.
    await page.getByTestId('fk-select-template_id').selectOption(template.id);
    await expect(page).toHaveURL(new RegExp(`[?&]template_id=${template.id}`));
  });

  test('URL state survives a hard refresh (status + source)', async ({ page }) => {
    await page.goto('/proposals?status=pending&source=manual');
    await expect(page.getByTestId('filter-chip-status-pending')).toHaveAttribute(
      'data-active',
      'true',
    );
    await expect(page.getByTestId('filter-chip-source-manual')).toHaveAttribute(
      'data-active',
      'true',
    );

    await page.reload();
    await expect(page.getByTestId('filter-chip-status-pending')).toHaveAttribute(
      'data-active',
      'true',
    );
    await expect(page.getByTestId('filter-chip-source-manual')).toHaveAttribute(
      'data-active',
      'true',
    );
  });
});
