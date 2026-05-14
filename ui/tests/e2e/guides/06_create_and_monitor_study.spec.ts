/**
 * Walkthrough: Create and monitor a study (guide 06).
 *
 * Captures the core Karpathy-loop entry point: seed the upstream chain
 * via API → land on /studies → walk through the seeded study's detail
 * page (header + trials table + status badge). The 5-step study-creation
 * modal is intentionally captured at one screen — it's a wizard with too
 * many micro-steps to walk through slide-by-slide. The detail page is
 * where the operator spends actual time.
 */
import path from 'node:path';

import { expect, test } from '@playwright/test';

import { seedFullChain, seedStudy } from '../helpers/seed';

const SCREENSHOTS = path.resolve(__dirname, '../../../public/guides/06_create_and_monitor_study');

test.describe('Walkthrough: Create and monitor a study', () => {
  test('captures the studies list + create modal + monitoring view', async ({ page }) => {
    const chain = await seedFullChain(3);
    const study = await seedStudy({
      clusterId: chain.clusterId,
      querySetId: chain.querySetId,
      templateId: chain.templateId,
      judgmentListId: chain.judgmentListId,
      maxTrials: 2,
    });

    // 01: Studies list.
    await page.goto('/studies');
    await expect(page.getByTestId('studies-table')).toBeVisible({ timeout: 10_000 });
    await page.waitForTimeout(500);
    await page.screenshot({
      path: path.join(SCREENSHOTS, '01-studies-list.png'),
      fullPage: false,
    });

    // 02: Status filter chips driving the URL.
    await page.getByTestId('status-chip-queued').click();
    await page.waitForTimeout(400);
    await page.screenshot({
      path: path.join(SCREENSHOTS, '02-studies-status-filter.png'),
      fullPage: false,
    });

    // 03: Open the Create study modal (its first step).
    await page.getByTestId('status-chip-all').click();
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
    await page.goto(`/studies/${study.id}`);
    await expect(page.getByTestId('study-name')).toContainText(study.name, { timeout: 10_000 });
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
