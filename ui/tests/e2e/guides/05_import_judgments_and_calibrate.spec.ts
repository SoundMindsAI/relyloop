// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Walkthrough: Import judgments + calibrate (guide 05).
 *
 * Captures the tutorial path that bypasses LLM judgment generation:
 * seed a chain → import judgments via API → /judgments/[id] page →
 * calibration modal (the human-vs-LLM agreement surface).
 *
 * Uses the import path (POST /api/v1/judgment-lists/import) rather than
 * the LLM generation path, so the guide is deterministic + doesn't
 * require an OpenAI key to run.
 *
 * Cursor + smoother pacing + WebVTT step captions via the shared demo-cursor
 * helper (feat_walkthrough_video_cursor_captions). Run video-only so the
 * committed screenshots don't churn:
 *   cd ui
 *   DEMO_VIDEO_ONLY=1 pnpm playwright test -c playwright.demo.config.ts \
 *     tests/e2e/guides/05_import_judgments_and_calibrate.spec.ts
 */
import path from 'node:path';

import { expect, test } from '@playwright/test';

import metadata from '../../../public/guides/05_import_judgments_and_calibrate/metadata.json';
import { glide, installCursor, loadStepCaptions, shot, StepTimer, finalizeCaptions } from '../helpers/demo-cursor';
import { seedJudgmentList, seedQuerySet } from '../helpers/seed';

const SLUG = '05_import_judgments_and_calibrate';
const GUIDES_ROOT = path.resolve(__dirname, '../../../public/guides');
const SCREENSHOTS = path.join(GUIDES_ROOT, SLUG);

test.describe('Walkthrough: Import judgments + calibrate', () => {
  test('captures the import + review + calibrate flow', async ({ page }) => {
    await installCursor(page);
    const captions = loadStepCaptions(metadata);
    const timer = new StepTimer();

    const qs = await seedQuerySet(12);
    const jl = await seedJudgmentList({
      clusterId: qs.clusterId,
      querySetId: qs.querySetId,
      queryIds: qs.queryIds,
    });

    await page.goto(`/judgments/${jl.id}`);
    await expect(page.getByTestId('header-count')).toBeVisible({ timeout: 10_000 });
    await page.waitForTimeout(500);
    timer.mark(captions[0]!);
    await shot(page, {
      path: path.join(SCREENSHOTS, '01-judgments-list.png'),
      fullPage: true,
    });

    // Open the calibration modal.
    await glide(page, page.getByTestId('open-calibration'));
    await page.getByTestId('open-calibration').click();
    await expect(page.getByRole('dialog')).toBeVisible({ timeout: 5_000 });
    await page.waitForTimeout(400);
    timer.mark(captions[1]!);
    await shot(page, {
      path: path.join(SCREENSHOTS, '02-calibration-modal-empty.png'),
      fullPage: false,
    });

    // Show a populated CSV sample (real query_ids — won't match the seeded
    // judgments' (query_id, doc_id) pairs exactly so the kappa is unlikely
    // to compute, but the form-filled screenshot is the goal).
    const samplesCsv = qs.queryIds
      .slice(0, 12)
      .map((qid, i) => `${qid},e2e-doc-${i},${(i % 4)}`)
      .join('\n');
    await glide(page, page.getByTestId('cal-samples'), 400);
    await page.getByTestId('cal-samples').click();
    await page
      .getByTestId('cal-samples')
      .pressSequentially(`query_id,doc_id,rating\n${samplesCsv}`, { delay: 55 });
    await page.waitForTimeout(400);
    timer.mark(captions[2]!);
    await shot(page, {
      path: path.join(SCREENSHOTS, '03-calibration-modal-filled.png'),
      fullPage: false,
    });

    // Submit calibration — backend computes Cohen's + linear-weighted kappa
    // and persists the result on the judgment_lists row.
    const calPromise = page.waitForResponse(
      (resp) =>
        resp.url().includes(`/api/v1/judgment-lists/${jl.id}/calibration`) &&
        resp.request().method() === 'POST',
      { timeout: 15_000 },
    );
    await glide(page, page.getByTestId('cal-submit'));
    await page.getByTestId('cal-submit').click();
    const calResp = await calPromise;
    // Any HTTP status is OK for the walkthrough — the goal is to capture the
    // result panel (success kappa value, or the validation-error message
    // when the sample CSV doesn't meet the ≥10 distinct-pairs requirement).
    expect(calResp.status()).toBeGreaterThan(0);
    await page.waitForTimeout(500);
    timer.mark(captions[3]!);
    await shot(page, {
      path: path.join(SCREENSHOTS, '04-calibration-result.png'),
      fullPage: false,
    });

    finalizeCaptions(timer, captions, SLUG, GUIDES_ROOT);
  });
});
