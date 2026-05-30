// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Walkthrough: Create a query template (guide 03).
 *
 * Captures the operator's first-time query-template-creation journey:
 * land on /templates → open Create modal → fill the Jinja2 body and
 * declared params → submit → see the new template in the list.
 */
import path from 'node:path';
import { randomUUID } from 'node:crypto';

import { expect, test } from '@playwright/test';

const SCREENSHOTS = path.resolve(__dirname, '../../../public/guides/03_create_query_template');

test.describe('Walkthrough: Create a query template', () => {
  test('captures the template-creation journey', async ({ page }) => {
    const name = `tpl-${randomUUID().slice(0, 6)}`;

    await page.goto('/templates');
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(SCREENSHOTS, '01-templates-list.png') });

    // Open the create modal.
    await page.getByRole('button', { name: /Create template/i }).click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await page.waitForTimeout(400);
    await page.screenshot({ path: path.join(SCREENSHOTS, '02-create-modal-empty.png') });

    // Fill the form. The Body field is a custom <TemplateBodyEditor> with a
    // hidden <textarea> — the visible highlight layer isn't focusable, so
    // we target the underlying textarea by its testid.
    await page.getByLabel('Name', { exact: true }).fill(name);
    await page
      .getByTestId('template-body-textarea')
      .fill(
        '{ "query": { "match": { "title": { "query": "{{ query_text }}", "boost": {{ boost }} } } } }',
      );
    await page.getByLabel(/Declared params/).fill('boost:float\nquery_text:string');
    await page.waitForTimeout(400);
    await page.screenshot({ path: path.join(SCREENSHOTS, '03-create-modal-filled.png') });

    // Submit.
    const postPromise = page.waitForResponse(
      (resp) =>
        resp.url().includes('/api/v1/query-templates') &&
        resp.request().method() === 'POST' &&
        resp.status() < 500,
      { timeout: 15_000 },
    );
    await page.getByRole('button', { name: /^Create$/i }).click();
    const resp = await postPromise;
    expect(resp.status()).toBe(201);

    // Modal closes; new template appears in the list.
    await expect(page.getByRole('dialog')).not.toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(name).first()).toBeVisible({ timeout: 10_000 });
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(SCREENSHOTS, '04-template-created.png') });

    // Drill into the detail page — shows fork-to-v2 affordance.
    await page.getByText(name).first().click();
    await expect(page.getByTestId('open-fork-modal')).toBeVisible({ timeout: 10_000 });
    await page.waitForTimeout(500);
    await page.screenshot({
      path: path.join(SCREENSHOTS, '05-template-detail-fork-button.png'),
      fullPage: true,
    });
  });
});
