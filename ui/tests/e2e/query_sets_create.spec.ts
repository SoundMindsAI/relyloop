// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * E2E spec: /query-sets create flow (workflow B2).
 *
 * Covers the create-query-set modal end-to-end against the live backend.
 * The per-query CRUD on the detail page is exercised by query_set_detail.spec.ts.
 */
import { randomUUID } from 'node:crypto';

import { expect, test } from '@playwright/test';

import { seedCluster } from './helpers/seed';

test.describe('/query-sets create flow', () => {
  test('creates a query set bound to an existing cluster', async ({ page }) => {
    const cluster = await seedCluster();
    const name = `e2e-qs-${randomUUID().slice(0, 8)}`;

    await page.goto('/query-sets');
    await page.getByTestId('open-create-query-set').click();
    await expect(page.getByRole('dialog')).toBeVisible();

    await page.getByLabel('Name', { exact: true }).fill(name);
    // Cluster picker is an EntitySelect (shadcn Select). Open the dropdown,
    // then click the option matching the seeded cluster's name. The status
    // dot inside the option is aria-hidden so the accessible name is just
    // the cluster name.
    await page.getByTestId('qs-cluster').click();
    await page.getByRole('option', { name: cluster.name }).click();

    await page.getByTestId('create-query-set-submit').click();

    // Modal closes; the new row appears in the list.
    await expect(page.getByRole('dialog')).not.toBeVisible({ timeout: 5_000 });
    await expect(page.getByText(name).first()).toBeVisible({ timeout: 5_000 });
  });
});
