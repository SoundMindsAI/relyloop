// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Walkthrough: Create a query set + add queries (guide 04).
 *
 * Captures the operator's query-set-creation journey:
 * seed a cluster → open Create modal on /query-sets → fill the form →
 * submit → see the new set → open detail → add queries via the dialog.
 */
import path from 'node:path';
import { randomUUID } from 'node:crypto';

import { expect, test } from '@playwright/test';

import { seedCluster } from '../helpers/seed';

const SCREENSHOTS = path.resolve(__dirname, '../../../public/guides/04_create_query_set');

test.describe('Walkthrough: Create a query set', () => {
  test('captures the query-set-creation + add-queries journey', async ({ page }) => {
    const cluster = await seedCluster();
    const name = `qs-${randomUUID().slice(0, 6)}`;

    await page.goto('/query-sets');
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(SCREENSHOTS, '01-query-sets-list.png') });

    // Open the create modal.
    await page.getByTestId('open-create-query-set').click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await page.waitForTimeout(400);
    await page.screenshot({ path: path.join(SCREENSHOTS, '02-create-modal-empty.png') });

    // Fill the form.
    await page.getByLabel('Name', { exact: true }).fill(name);
    // Cluster picker is an EntitySelect (shadcn Select) post-chore_form_dropdown_primitive.
    // Open the dropdown and click the seeded cluster's name; the status dot
    // is aria-hidden so the accessible name is just `cluster.name`.
    // Use `dispatchEvent('click')` (rather than `.click()`) because with a
    // polluted dev DB the Radix popover renders 200+ options and the target
    // can end up outside the popup's viewport — Playwright's actionability
    // check loops on scroll even with `force: true`, since the viewport
    // check is enforced separately. Synthetic click bypasses both checks;
    // Radix's option handler still fires correctly via the bubbling event.
    await page.getByTestId('qs-cluster').click();
    await page.getByRole('option', { name: cluster.name, exact: true }).dispatchEvent('click');
    await page.waitForTimeout(400);
    await page.screenshot({ path: path.join(SCREENSHOTS, '03-create-modal-filled.png') });

    // Submit.
    const postPromise = page.waitForResponse(
      (resp) =>
        resp.url().includes('/api/v1/query-sets') &&
        resp.request().method() === 'POST' &&
        resp.status() < 500,
      { timeout: 15_000 },
    );
    await page.getByTestId('create-query-set-submit').click();
    const resp = await postPromise;
    expect(resp.status()).toBe(201);

    // Modal closes; new query set appears in the list.
    await expect(page.getByRole('dialog')).not.toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(name).first()).toBeVisible({ timeout: 10_000 });
    await page.waitForTimeout(500);

    // Drill into the detail page.
    await page.getByText(name).first().click();
    await page.waitForURL(/\/query-sets\/[a-f0-9-]+$/, { timeout: 10_000 });
    await page.waitForTimeout(500);
    await page.screenshot({
      path: path.join(SCREENSHOTS, '04-query-set-detail-empty.png'),
      fullPage: false,
    });

    // Open the Add Queries dialog (accepts JSON or CSV).
    await page.getByTestId('open-add-queries').click();
    await expect(page.getByRole('dialog')).toBeVisible({ timeout: 5_000 });
    await page.waitForTimeout(500);
    await page.screenshot({
      path: path.join(SCREENSHOTS, '05-add-queries-dialog.png'),
      fullPage: false,
    });
  });
});
