// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Walkthrough: Review a proposal (guide 02).
 *
 * Captures the operator's proposal-review journey:
 * land on /proposals → click the pending proposal → read the config diff +
 * metric delta → see the Open PR / Reject options.
 *
 * Seeds a manual proposal via the API so the walkthrough doesn't require a
 * full study + digest pipeline to have run first.
 *
 * Cursor + smoother pacing + WebVTT step captions via the shared demo-cursor
 * helper (feat_walkthrough_video_cursor_captions). Run video-only so the
 * committed screenshots don't churn:
 *   cd ui
 *   DEMO_VIDEO_ONLY=1 pnpm playwright test -c playwright.demo.config.ts \
 *     tests/e2e/guides/02_review_a_proposal.spec.ts
 *
 * Prerequisite: `make up` stack running (UI at :3000, API at :8000).
 */
import path from 'node:path';

import { expect, test } from '@playwright/test';

import metadata from '../../../public/guides/02_review_a_proposal/metadata.json';
import { glide, installCursor, loadStepCaptions, shot, StepTimer, writeCaptionsVtt } from '../helpers/demo-cursor';
import { seedCluster, seedProposal, seedTemplate } from '../helpers/seed';

const SLUG = '02_review_a_proposal';
const GUIDES_ROOT = path.resolve(__dirname, '../../../public/guides');
const SCREENSHOTS = path.join(GUIDES_ROOT, SLUG);

test.describe('Walkthrough: Review a proposal', () => {
  test('captures the full proposal-review journey', async ({ page }) => {
    await installCursor(page);
    const captions = loadStepCaptions(metadata);
    const timer = new StepTimer(Date.now());

    const cluster = await seedCluster();
    const template = await seedTemplate();
    const proposal = await seedProposal({ clusterId: cluster.id, templateId: template.id });

    // ── 01: Land on /proposals list ───────────────────────────────────
    await page.goto('/proposals');
    await expect(page.getByTestId('filter-chip-status-all')).toBeVisible();
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(500);
    timer.mark(captions[0]!, Date.now());
    await shot(page, { path: path.join(SCREENSHOTS, '01-proposals-list.png'), fullPage: false });

    // ── 02: Filter to pending ──────────────────────────────────────────
    await glide(page, page.getByTestId('filter-chip-status-pending'));
    await page.getByTestId('filter-chip-status-pending').click();
    await page.waitForTimeout(500);
    timer.mark(captions[1]!, Date.now());
    await shot(page, {
      path: path.join(SCREENSHOTS, '02-proposals-pending-filter.png'),
      fullPage: false,
    });

    // ── 03: Navigate to the proposal detail directly ──────────────────
    await page.goto(`/proposals/${proposal.id}`);
    await expect(page.getByTestId('config-diff-table')).toBeVisible({ timeout: 10_000 });
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(500);
    timer.mark(captions[2]!, Date.now());
    await shot(page, { path: path.join(SCREENSHOTS, '03-proposal-detail.png'), fullPage: true });

    // ── 04: Highlight the config diff ─────────────────────────────────
    await glide(page, page.getByTestId('config-diff-table'), 1200);
    timer.mark(captions[3]!, Date.now());
    await shot(page, { path: path.join(SCREENSHOTS, '04-config-diff.png'), fullPage: false });

    // ── 05: Open the reject dialog (shows the alternative path) ──────
    await glide(page, page.getByTestId('open-reject-dialog'));
    await page.getByTestId('open-reject-dialog').click();
    await expect(page.getByTestId('reject-reason-input')).toBeVisible({ timeout: 5_000 });
    await glide(page, page.getByTestId('reject-reason-input'), 400);
    await page.getByTestId('reject-reason-input').click();
    await page
      .getByTestId('reject-reason-input')
      .pressSequentially('Not the right time — saving as walkthrough demo', { delay: 55 });
    await page.waitForTimeout(400);
    timer.mark(captions[4]!, Date.now());
    await shot(page, { path: path.join(SCREENSHOTS, '05-reject-dialog.png'), fullPage: false });

    if (captions.length > 0 && timer.timings.length !== captions.length) {
      throw new Error(
        `caption/step mismatch for ${SLUG}: ${timer.timings.length} marks vs ${captions.length} captions`,
      );
    }
    writeCaptionsVtt(timer.timings, SLUG, GUIDES_ROOT);
  });
});
