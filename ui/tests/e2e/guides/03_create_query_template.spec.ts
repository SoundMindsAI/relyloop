// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Walkthrough: Create a query template (guide 03).
 *
 * Captures the operator's first-time query-template-creation journey:
 * land on /templates → open Create modal → fill the Jinja2 body and
 * declared params → submit → see the new template in the list.
 *
 * Cursor + smoother pacing + WebVTT step captions via the shared demo-cursor
 * helper (feat_walkthrough_video_cursor_captions). Run video-only so the
 * committed screenshots don't churn:
 *   cd ui
 *   DEMO_VIDEO_ONLY=1 pnpm playwright test -c playwright.demo.config.ts \
 *     tests/e2e/guides/03_create_query_template.spec.ts
 */
import path from 'node:path';
import { randomUUID } from 'node:crypto';

import { expect, test } from '@playwright/test';

import metadata from '../../../public/guides/03_create_query_template/metadata.json';
import { glide, installCursor, loadStepCaptions, shot, StepTimer, writeCaptionsVtt } from '../helpers/demo-cursor';

const SLUG = '03_create_query_template';
const GUIDES_ROOT = path.resolve(__dirname, '../../../public/guides');
const SCREENSHOTS = path.join(GUIDES_ROOT, SLUG);

test.describe('Walkthrough: Create a query template', () => {
  test('captures the template-creation journey', async ({ page }) => {
    await installCursor(page);
    const captions = loadStepCaptions(metadata);
    const timer = new StepTimer();

    const name = `tpl-${randomUUID().slice(0, 6)}`;

    await page.goto('/templates');
    await page.waitForTimeout(500);
    timer.mark(captions[0]!);
    await shot(page, { path: path.join(SCREENSHOTS, '01-templates-list.png') });

    // Open the create modal.
    await glide(page, page.getByRole('button', { name: /Create template/i }));
    await page.getByRole('button', { name: /Create template/i }).click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await page.waitForTimeout(400);
    timer.mark(captions[1]!);
    await shot(page, { path: path.join(SCREENSHOTS, '02-create-modal-empty.png') });

    // Fill the form. The Body field is a custom <TemplateBodyEditor> with a
    // hidden <textarea> — the visible highlight layer isn't focusable, so
    // we target the underlying textarea by its testid.
    await glide(page, page.getByLabel('Name', { exact: true }), 400);
    await page.getByLabel('Name', { exact: true }).click();
    await page.getByLabel('Name', { exact: true }).pressSequentially(name, { delay: 55 });

    await glide(page, page.getByTestId('template-body-textarea'), 400);
    await page.getByTestId('template-body-textarea').click();
    await page
      .getByTestId('template-body-textarea')
      .pressSequentially(
        '{ "query": { "match": { "title": { "query": "{{ query_text }}", "boost": {{ boost }} } } } }',
        { delay: 55 },
      );

    await glide(page, page.getByLabel(/Declared params/), 400);
    await page.getByLabel(/Declared params/).click();
    await page
      .getByLabel(/Declared params/)
      .pressSequentially('boost:float\nquery_text:string', { delay: 55 });
    await page.waitForTimeout(400);
    timer.mark(captions[2]!);
    await shot(page, { path: path.join(SCREENSHOTS, '03-create-modal-filled.png') });

    // Submit.
    const postPromise = page.waitForResponse(
      (resp) =>
        resp.url().includes('/api/v1/query-templates') &&
        resp.request().method() === 'POST' &&
        resp.status() < 500,
      { timeout: 15_000 },
    );
    await glide(page, page.getByRole('button', { name: /^Create$/i }));
    await page.getByRole('button', { name: /^Create$/i }).click();
    const resp = await postPromise;
    expect(resp.status()).toBe(201);

    // Modal closes; new template appears in the list.
    await expect(page.getByRole('dialog')).not.toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(name).first()).toBeVisible({ timeout: 10_000 });
    await page.waitForTimeout(500);
    timer.mark(captions[3]!);
    await shot(page, { path: path.join(SCREENSHOTS, '04-template-created.png') });

    // Drill into the detail page — shows fork-to-v2 affordance.
    await glide(page, page.getByText(name).first());
    await page.getByText(name).first().click();
    await expect(page.getByTestId('open-fork-modal')).toBeVisible({ timeout: 10_000 });
    await page.waitForTimeout(500);
    timer.mark(captions[4]!);
    await shot(page, {
      path: path.join(SCREENSHOTS, '05-template-detail-fork-button.png'),
      fullPage: true,
    });

    if (captions.length === 0) {
      // Zero-caption deck: delete any stale captions.vtt, emit no <track>.
      writeCaptionsVtt([], SLUG, GUIDES_ROOT);
    } else {
      if (timer.timings.length !== captions.length) {
        throw new Error(
          `caption/step mismatch for ${SLUG}: ${timer.timings.length} marks vs ${captions.length} captions`,
        );
      }
      writeCaptionsVtt(timer.timings, SLUG, GUIDES_ROOT);
    }
  });
});
