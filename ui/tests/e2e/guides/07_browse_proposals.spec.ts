// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Walkthrough: Browse proposals + filters (guide 07).
 *
 * Captures the proposals queue review surface — list, filter chips
 * (status / source / cluster), URL-backed state. Proposal detail and
 * reject flows are covered separately in guide 02.
 *
 * Cursor + smoother pacing + WebVTT step captions via the shared demo-cursor
 * helper (feat_walkthrough_video_cursor_captions). Run video-only so the
 * committed screenshots don't churn:
 *   cd ui
 *   DEMO_VIDEO_ONLY=1 pnpm playwright test -c playwright.demo.config.ts \
 *     tests/e2e/guides/07_browse_proposals.spec.ts
 */
import path from 'node:path';

import { expect, test } from '@playwright/test';

import metadata from '../../../public/guides/07_browse_proposals/metadata.json';
import { glide, installCursor, loadStepCaptions, shot, StepTimer, writeCaptionsVtt } from '../helpers/demo-cursor';
import { seedCluster, seedProposal, seedTemplate } from '../helpers/seed';

const SLUG = '07_browse_proposals';
const GUIDES_ROOT = path.resolve(__dirname, '../../../public/guides');
const SCREENSHOTS = path.join(GUIDES_ROOT, SLUG);

test.describe('Walkthrough: Browse proposals', () => {
  test('captures the proposals list filter UX', async ({ page }) => {
    await installCursor(page);
    const captions = loadStepCaptions(metadata);
    const timer = new StepTimer();

    // Seed three manual proposals so the list has real rows.
    const cluster = await seedCluster();
    const template = await seedTemplate();
    await seedProposal({ clusterId: cluster.id, templateId: template.id });
    await seedProposal({ clusterId: cluster.id, templateId: template.id });
    await seedProposal({ clusterId: cluster.id, templateId: template.id });

    await page.goto('/proposals');
    await expect(page.getByTestId('filter-chip-status-all')).toBeVisible();
    await page.waitForTimeout(600);
    timer.mark(captions[0]!);
    await shot(page, {
      path: path.join(SCREENSHOTS, '01-proposals-list.png'),
      fullPage: true,
    });

    // 02: Status chip → pending (URL ?status=pending).
    await glide(page, page.getByTestId('filter-chip-status-pending'));
    await page.getByTestId('filter-chip-status-pending').click();
    await page.waitForTimeout(400);
    timer.mark(captions[1]!);
    await shot(page, {
      path: path.join(SCREENSHOTS, '02-status-filter-pending.png'),
      fullPage: false,
    });

    // 03: Source chip → manual.
    await glide(page, page.getByTestId('filter-chip-source-manual'));
    await page.getByTestId('filter-chip-source-manual').click();
    await page.waitForTimeout(400);
    timer.mark(captions[2]!);
    await shot(page, {
      path: path.join(SCREENSHOTS, '03-source-filter-manual.png'),
      fullPage: false,
    });

    // 04: Cluster filter dropdown.
    await glide(page, page.getByTestId('fk-select-cluster_id'));
    await page.getByTestId('fk-select-cluster_id').click();
    await page.waitForTimeout(400);
    timer.mark(captions[3]!);
    await shot(page, {
      path: path.join(SCREENSHOTS, '04-cluster-filter-open.png'),
      fullPage: false,
    });
    // Close the dropdown.
    await page.keyboard.press('Escape');
    await page.waitForTimeout(300);

    // 05: Reset to all + show the row count.
    await glide(page, page.getByTestId('filter-chip-status-all'));
    await page.getByTestId('filter-chip-status-all').click();
    await page.getByTestId('filter-chip-source-all').click();
    await page.waitForTimeout(400);
    timer.mark(captions[4]!);
    await shot(page, {
      path: path.join(SCREENSHOTS, '05-all-filters-reset.png'),
      fullPage: false,
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
