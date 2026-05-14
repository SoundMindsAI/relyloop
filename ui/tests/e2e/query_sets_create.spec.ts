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
    // Cluster picker in MVP1 is a plain text input — type the UUIDv7 directly.
    await page.getByLabel(/^Cluster ID/).fill(cluster.id);

    await page.getByTestId('create-query-set-submit').click();

    // Modal closes; the new row appears in the list.
    await expect(page.getByRole('dialog')).not.toBeVisible({ timeout: 5_000 });
    await expect(page.getByText(name).first()).toBeVisible({ timeout: 5_000 });
  });
});
