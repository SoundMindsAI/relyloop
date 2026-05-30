// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * E2E spec: /clusters register flow (workflow A3).
 *
 * Pairs with cluster_detail_delete.spec.ts (workflow F4). Together they cover
 * the cluster lifecycle in the UI: register → appears in list → delete.
 */
import { randomUUID } from 'node:crypto';

import { expect, test } from '@playwright/test';

test.describe('/clusters register flow', () => {
  test('opens the register modal, submits, and the new cluster appears in the list', async ({
    page,
  }) => {
    const name = `e2e-reg-${randomUUID().slice(0, 8)}`;
    await page.goto('/clusters');

    await expect(
      page.getByTestId('clusters-table').or(page.getByTestId('data-table-empty-no-rows-exist')),
    ).toBeVisible();

    await page.getByTestId('open-register-cluster').click();
    await expect(page.getByTestId('register-form')).toBeVisible();

    await page.getByLabel('Name', { exact: true }).fill(name);
    await page.getByLabel('Base URL', { exact: true }).fill('http://elasticsearch:9200');
    await page.getByLabel(/^Credentials ref/).fill('local-es');

    // The local-es credentials fixture uses username+password (es_basic), not
    // an api_key. Switch the auth kind dropdown to match — otherwise the
    // adapter probe fails with CLUSTER_UNREACHABLE: credentials resolution
    // failed: missing required fields for auth_kind='es_apikey': ['api_key'].
    await page.locator('#cl-auth').click();
    await page.getByRole('option', { name: 'es_basic' }).click();

    // Wait for the POST to fire before asserting on UI state — the modal's
    // onSuccess handler closes the dialog once the cluster is registered.
    const postPromise = page.waitForResponse(
      (resp) =>
        resp.url().includes('/api/v1/clusters') &&
        resp.request().method() === 'POST' &&
        resp.status() < 500,
      { timeout: 15_000 },
    );
    await page.getByTestId('register-submit').click();
    const resp = await postPromise;
    expect(resp.status()).toBe(201);

    // Modal closes and the new row appears in the table.
    await expect(page.getByTestId('register-form')).not.toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(name).first()).toBeVisible({ timeout: 10_000 });
  });
});
