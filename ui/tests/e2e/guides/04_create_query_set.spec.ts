// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Walkthrough: Create a query set + add queries (guide 04).
 *
 * Captures the operator's query-set-creation journey:
 * seed a cluster → open Create modal on /query-sets → fill the form →
 * submit → see the new set → open detail → add queries via the dialog.
 *
 * Cursor + smoother pacing + WebVTT step captions via the shared demo-cursor
 * helper (feat_walkthrough_video_cursor_captions). Run video-only so the
 * committed screenshots don't churn:
 *   cd ui
 *   DEMO_VIDEO_ONLY=1 pnpm playwright test -c playwright.demo.config.ts \
 *     tests/e2e/guides/04_create_query_set.spec.ts
 */
import path from 'node:path';
import { randomUUID } from 'node:crypto';

import { expect, test } from '@playwright/test';

import metadata from '../../../public/guides/04_create_query_set/metadata.json';
import { glide, installCursor, loadStepCaptions, shot, StepTimer, writeCaptionsVtt } from '../helpers/demo-cursor';
import { seedCluster } from '../helpers/seed';

const SLUG = '04_create_query_set';
const GUIDES_ROOT = path.resolve(__dirname, '../../../public/guides');
const SCREENSHOTS = path.join(GUIDES_ROOT, SLUG);

test.describe('Walkthrough: Create a query set', () => {
  test('captures the query-set-creation + add-queries journey', async ({ page }) => {
    await installCursor(page);
    const captions = loadStepCaptions(metadata);
    const timer = new StepTimer(Date.now());

    const cluster = await seedCluster();
    const name = `qs-${randomUUID().slice(0, 6)}`;

    await page.goto('/query-sets');
    await page.waitForTimeout(500);
    timer.mark(captions[0]!, Date.now());
    await shot(page, { path: path.join(SCREENSHOTS, '01-query-sets-list.png') });

    // Open the create modal.
    await glide(page, page.getByTestId('open-create-query-set'));
    await page.getByTestId('open-create-query-set').click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await page.waitForTimeout(400);
    timer.mark(captions[1]!, Date.now());
    await shot(page, { path: path.join(SCREENSHOTS, '02-create-modal-empty.png') });

    // Fill the form.
    await glide(page, page.getByLabel('Name', { exact: true }), 400);
    await page.getByLabel('Name', { exact: true }).click();
    await page.getByLabel('Name', { exact: true }).pressSequentially(name, { delay: 55 });
    // Cluster picker is an EntitySelect (shadcn Select) post-chore_form_dropdown_primitive.
    // Open the dropdown and click the seeded cluster's name; the status dot
    // is aria-hidden so the accessible name is just `cluster.name`.
    // Use `dispatchEvent('click')` (rather than `.click()`) because with a
    // polluted dev DB the Radix popover renders 200+ options and the target
    // can end up outside the popup's viewport — Playwright's actionability
    // check loops on scroll even with `force: true`, since the viewport
    // check is enforced separately. Synthetic click bypasses both checks;
    // Radix's option handler still fires correctly via the bubbling event.
    await glide(page, page.getByTestId('qs-cluster'));
    await page.getByTestId('qs-cluster').click();
    await page.getByRole('option', { name: cluster.name, exact: true }).dispatchEvent('click');
    await page.waitForTimeout(400);
    timer.mark(captions[2]!, Date.now());
    await shot(page, { path: path.join(SCREENSHOTS, '03-create-modal-filled.png') });

    // Submit.
    const postPromise = page.waitForResponse(
      (resp) =>
        resp.url().includes('/api/v1/query-sets') &&
        resp.request().method() === 'POST' &&
        resp.status() < 500,
      { timeout: 15_000 },
    );
    await glide(page, page.getByTestId('create-query-set-submit'));
    await page.getByTestId('create-query-set-submit').click();
    const resp = await postPromise;
    expect(resp.status()).toBe(201);

    // Modal closes; new query set appears in the list.
    await expect(page.getByRole('dialog')).not.toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(name).first()).toBeVisible({ timeout: 10_000 });
    await page.waitForTimeout(500);

    // Drill into the detail page.
    await glide(page, page.getByText(name).first());
    await page.getByText(name).first().click();
    await page.waitForURL(/\/query-sets\/[a-f0-9-]+$/, { timeout: 10_000 });
    await page.waitForTimeout(500);
    timer.mark(captions[3]!, Date.now());
    await shot(page, {
      path: path.join(SCREENSHOTS, '04-query-set-detail-empty.png'),
      fullPage: false,
    });

    // Open the Add Queries dialog (accepts JSON or CSV).
    await glide(page, page.getByTestId('open-add-queries'));
    await page.getByTestId('open-add-queries').click();
    await expect(page.getByRole('dialog')).toBeVisible({ timeout: 5_000 });
    await page.waitForTimeout(500);
    timer.mark(captions[4]!, Date.now());
    await shot(page, {
      path: path.join(SCREENSHOTS, '05-add-queries-dialog.png'),
      fullPage: false,
    });

    if (captions.length > 0 && timer.timings.length !== captions.length) {
      throw new Error(
        `caption/step mismatch for ${SLUG}: ${timer.timings.length} marks vs ${captions.length} captions`,
      );
    }
    writeCaptionsVtt(timer.timings, SLUG, GUIDES_ROOT);
  });
});
