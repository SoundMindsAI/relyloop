// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Walkthrough: Create and monitor a study (guide 06).
 *
 * Captures the core Karpathy-loop entry point: seed the upstream chain
 * via API → land on /studies → walk through the seeded study's detail
 * page (header + trials table + status badge). The 5-step study-creation
 * modal is intentionally captured at one screen — it's a wizard with too
 * many micro-steps to walk through slide-by-slide. The detail page is
 * where the operator spends actual time.
 *
 * Uses the **acme-products-prod** scenario from
 * `scripts/seed_meaningful_demos.py` so the screenshots look like a real
 * production e-commerce tuning workflow rather than `e2e-*` dev-test
 * artifacts. Mirrors the guide-01 precedent (PR #177). The spec is
 * self-contained — it does NOT depend on `make seed-demo` having run.
 *
 * Cursor + smoother pacing + WebVTT step captions via the shared demo-cursor
 * helper (feat_walkthrough_video_cursor_captions). Run video-only so the
 * committed screenshots don't churn:
 *   cd ui
 *   DEMO_VIDEO_ONLY=1 pnpm playwright test -c playwright.demo.config.ts \
 *     tests/e2e/guides/06_create_and_monitor_study.spec.ts
 *
 * Prerequisite: `make up` stack running (UI at :3000, API at :8000).
 */
import path from 'node:path';

import { expect, test } from '@playwright/test';

import metadata from '../../../public/guides/06_create_and_monitor_study/metadata.json';
import { glide, installCursor, loadStepCaptions, shot, StepTimer, writeCaptionsVtt } from '../helpers/demo-cursor';
import { seedAcmeProductsChain } from '../helpers/seed';

const SLUG = '06_create_and_monitor_study';
const GUIDES_ROOT = path.resolve(__dirname, '../../../public/guides');
const SCREENSHOTS = path.join(GUIDES_ROOT, SLUG);

test.describe('Walkthrough: Create and monitor a study', () => {
  test('captures the studies list + create modal + monitoring view', async ({ page }) => {
    await installCursor(page);
    const captions = loadStepCaptions(metadata);
    const timer = new StepTimer(Date.now());

    const chain = await seedAcmeProductsChain();

    // 01: Studies list.
    await page.goto('/studies');
    await expect(page.getByTestId('studies-table')).toBeVisible({ timeout: 10_000 });
    await page.waitForTimeout(500);
    timer.mark(captions[0]!, Date.now());
    await shot(page, {
      path: path.join(SCREENSHOTS, '01-studies-list.png'),
      fullPage: false,
    });

    // 02: Status filter chips driving the URL.
    await glide(page, page.getByTestId('filter-chip-status-queued'));
    await page.getByTestId('filter-chip-status-queued').click();
    await page.waitForTimeout(400);
    timer.mark(captions[1]!, Date.now());
    await shot(page, {
      path: path.join(SCREENSHOTS, '02-studies-status-filter.png'),
      fullPage: false,
    });

    // 03: Open the Create study modal (its first step). The target field
    // is now a disabled <Select> with "Pick a cluster first" placeholder
    // until a cluster is chosen, plus an "Enter manually" toggle below
    // (feat_create_study_target_autocomplete, PR #179). Capture the empty
    // Step-1 state so the new picker UI is visible.
    await page.getByTestId('filter-chip-status-all').click();
    await page.waitForTimeout(200);
    await glide(page, page.getByTestId('open-create-study'));
    await page.getByTestId('open-create-study').click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await page.waitForTimeout(500);
    timer.mark(captions[2]!, Date.now());
    await shot(page, {
      path: path.join(SCREENSHOTS, '03-create-study-modal.png'),
      fullPage: false,
    });
    // Close — the existing seeded study has the data we need for the
    // monitoring screenshots.
    await page.keyboard.press('Escape');
    await page.waitForTimeout(300);

    // 04: The completed study's detail page — the core monitoring surface.
    //
    // The study is seeded COMPLETED (via the test endpoint) with 50 trials and
    // per-query metrics, so both headline panels render deterministically with
    // no orchestrator wait: <ConfidencePanel> (per-query CI) and
    // <ConvergencePanel> (a real `converged` verdict + best-so-far curve — the
    // 50-trial count clears STUDIES_TPE_WARMUP_FLOOR). See seedAcmeProductsChain.
    await page.goto(`/studies/${chain.studyId}`);
    await expect(page.getByTestId('study-name')).toContainText(chain.studyName, {
      timeout: 10_000,
    });
    await page.waitForSelector('[data-testid="confidence-panel"]', { timeout: 15_000 });
    await page.waitForSelector('[data-testid="convergence-panel"]', { timeout: 15_000 });
    // The convergence-curve <details> auto-collapses when the verdict is
    // `converged`; expand it so the best-so-far curve is visible in the shot.
    const curveDetails = page.getByTestId('convergence-curve-details');
    if (!(await curveDetails.evaluate((el) => (el as HTMLDetailsElement).open).catch(() => true))) {
      await curveDetails.getByText(/show convergence curve/i).click();
    }
    await expect(page.getByTestId('convergence-curve')).toBeVisible({ timeout: 5_000 });
    // Brief settle for the Recharts render + any in-flight animations / fonts.
    await page.waitForTimeout(900);
    timer.mark(captions[3]!, Date.now());
    await shot(page, {
      path: path.join(SCREENSHOTS, '04-study-detail.png'),
      fullPage: true,
    });

    // 05: Cancel-study confirmation (operator's mid-flight kill switch).
    const cancelBtn = page.getByTestId('cancel-study');
    if (await cancelBtn.isEnabled().catch(() => false)) {
      await glide(page, cancelBtn);
      await cancelBtn.click();
      await page.waitForTimeout(400);
      timer.mark(captions[4]!, Date.now());
      await shot(page, {
        path: path.join(SCREENSHOTS, '05-cancel-confirmation.png'),
        fullPage: false,
      });
    } else {
      // The orchestrator may already have terminated the 2-trial study.
      // Capture the terminal-state screenshot in that case.
      await page.waitForTimeout(400);
      timer.mark(captions[4]!, Date.now());
      await shot(page, {
        path: path.join(SCREENSHOTS, '05-study-terminal-state.png'),
        fullPage: false,
      });
    }

    if (captions.length > 0 && timer.timings.length !== captions.length) {
      throw new Error(
        `caption/step mismatch for ${SLUG}: ${timer.timings.length} marks vs ${captions.length} captions`,
      );
    }
    writeCaptionsVtt(timer.timings, SLUG, GUIDES_ROOT);
  });
});
