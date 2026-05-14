/**
 * Walkthrough: Register your first cluster (guide 01).
 *
 * Captures the operator's first-time cluster-registration journey:
 * land on /clusters → open the modal → fill the form → submit → see the
 * new row in the list with health status.
 *
 * Usage:
 *   cd ui
 *   pnpm playwright test -c playwright.demo.config.ts \
 *     tests/e2e/guides/01_register_first_cluster.spec.ts
 *
 * Prerequisite: `make up` stack running (UI at :3000, API at :8000).
 */
import path from 'node:path';
import { randomUUID } from 'node:crypto';

import { expect, test } from '@playwright/test';

const SCREENSHOTS = path.resolve(__dirname, '../../../public/guides/01_register_first_cluster');

test.describe('Walkthrough: Register your first cluster', () => {
  test('captures the full cluster-registration journey', async ({ page }) => {
    const name = `walkthrough-${randomUUID().slice(0, 6)}`;

    // ── 01: Land on /clusters list ─────────────────────────────────────
    await page.goto('/clusters');
    await expect(page.getByTestId('open-register-cluster')).toBeVisible();
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(400);
    await page.screenshot({
      path: path.join(SCREENSHOTS, '01-clusters-list.png'),
      fullPage: false,
    });

    // ── 02: Open the register modal ────────────────────────────────────
    await page.getByTestId('open-register-cluster').click();
    await expect(page.getByTestId('register-form')).toBeVisible();
    await page.waitForTimeout(400);
    await page.screenshot({
      path: path.join(SCREENSHOTS, '02-register-modal-empty.png'),
      fullPage: false,
    });

    // ── 03: Fill the form ──────────────────────────────────────────────
    await page.getByLabel('Name', { exact: true }).fill(name);
    await page.getByLabel('Base URL', { exact: true }).fill('http://elasticsearch:9200');
    await page.getByLabel(/^Credentials ref/).fill('local-es');

    // local-es credentials are username+password; switch auth_kind to match.
    await page.locator('#cl-auth').click();
    await page.getByRole('option', { name: 'es_basic' }).click();

    await page.waitForTimeout(400);
    await page.screenshot({
      path: path.join(SCREENSHOTS, '03-register-modal-filled.png'),
      fullPage: false,
    });

    // ── 04: Submit + wait for the 201 ─────────────────────────────────
    const registerPromise = page.waitForResponse(
      (resp) =>
        resp.url().includes('/api/v1/clusters') &&
        resp.request().method() === 'POST' &&
        resp.status() < 500,
      { timeout: 15_000 },
    );
    await page.getByTestId('register-submit').click();
    const resp = await registerPromise;
    expect(resp.status()).toBe(201);

    // ── 05: New cluster appears in the list with health probe result ──
    await expect(page.getByTestId('register-form')).not.toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(name).first()).toBeVisible({ timeout: 10_000 });
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(600);
    await page.screenshot({
      path: path.join(SCREENSHOTS, '04-cluster-registered.png'),
      fullPage: false,
    });

    // ── 06: Click the row → detail page ────────────────────────────────
    await page.getByText(name).first().click();
    await page.waitForURL(/\/clusters\/[a-f0-9-]+$/, { timeout: 10_000 });
    await page.waitForTimeout(600);
    await page.screenshot({
      path: path.join(SCREENSHOTS, '05-cluster-detail.png'),
      fullPage: false,
    });
  });
});
