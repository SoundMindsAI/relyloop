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
 * Usage:
 *   cd ui
 *   pnpm playwright test -c playwright.demo.config.ts \
 *     tests/e2e/guides/06_create_and_monitor_study.spec.ts
 *
 * Prerequisite: `make up` stack running (UI at :3000, API at :8000).
 */
import path from 'node:path';

import { expect, test } from '@playwright/test';

import { seedAcmeProductsChain } from '../helpers/seed';

const SCREENSHOTS = path.resolve(__dirname, '../../../public/guides/06_create_and_monitor_study');

test.describe('Walkthrough: Create and monitor a study', () => {
  test('captures the studies list + create modal + monitoring view', async ({ page }) => {
    const chain = await seedAcmeProductsChain();

    // 01: Studies list.
    await page.goto('/studies');
    await expect(page.getByTestId('studies-table')).toBeVisible({ timeout: 10_000 });
    await page.waitForTimeout(500);
    await page.screenshot({
      path: path.join(SCREENSHOTS, '01-studies-list.png'),
      fullPage: false,
    });

    // 02: Status filter chips driving the URL.
    await page.getByTestId('filter-chip-status-queued').click();
    await page.waitForTimeout(400);
    await page.screenshot({
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
    await page.getByTestId('open-create-study').click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await page.waitForTimeout(500);
    await page.screenshot({
      path: path.join(SCREENSHOTS, '03-create-study-modal.png'),
      fullPage: false,
    });
    // Close — the existing seeded study has the data we need for the
    // monitoring screenshots.
    await page.keyboard.press('Escape');
    await page.waitForTimeout(300);

    // 04: Monitor the seeded study.
    //
    // Wait for the orchestrator to complete the 2 real trials so the
    // `<ConfidencePanel>` renders into the screenshot. Best-effort with a
    // 45s ceiling — if the panel doesn't appear (older study with
    // per_query_metrics NULL, or orchestrator slow / failed), we still
    // capture whatever state the page is in. The `.catch(() => null)`
    // keeps the test alive in that case.
    await page.goto(`/studies/${chain.studyId}`);
    await expect(page.getByTestId('study-name')).toContainText(chain.studyName, {
      timeout: 10_000,
    });
    await page
      .waitForSelector('[data-testid="confidence-panel"]', { timeout: 45_000 })
      .catch(() => null);
    // Brief settle for any in-flight animations / fonts.
    await page.waitForTimeout(700);
    await page.screenshot({
      path: path.join(SCREENSHOTS, '04-study-detail.png'),
      fullPage: true,
    });

    // 05: Cancel-study confirmation (operator's mid-flight kill switch).
    const cancelBtn = page.getByTestId('cancel-study');
    if (await cancelBtn.isEnabled().catch(() => false)) {
      await cancelBtn.click();
      await page.waitForTimeout(400);
      await page.screenshot({
        path: path.join(SCREENSHOTS, '05-cancel-confirmation.png'),
        fullPage: false,
      });
    } else {
      // The orchestrator may already have terminated the 2-trial study.
      // Capture the terminal-state screenshot in that case.
      await page.waitForTimeout(400);
      await page.screenshot({
        path: path.join(SCREENSHOTS, '05-study-terminal-state.png'),
        fullPage: false,
      });
    }
  });
});
