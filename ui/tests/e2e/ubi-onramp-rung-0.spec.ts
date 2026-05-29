/**
 * E2E: UBI on-ramp at rung_0 (feat_ubi_judgments FR-7 + FR-8 Capability A).
 *
 * On a cluster with NO UBI plugin (no `ubi_queries` index), opening the
 * generate-judgments dialog and entering a target surfaces the on-ramp
 * nudge and the method picker stays on LLM-as-judge. The dismissal
 * persists per cluster across reload.
 *
 * Real-backend: the readiness probe hits GET /clusters/{id}/ubi-readiness
 * which builds the cluster adapter and calls get_schema('ubi_queries') on
 * the live ES — absent index → rung_0. No mocking.
 */
import { expect, test } from '@playwright/test';

import { seedQuerySet } from './helpers/seed';
import { teardownUbi } from './helpers/seed_ubi';

test.describe('UBI on-ramp — rung_0', () => {
  test.beforeEach(async () => {
    // Ensure no ubi_queries index leaks in from another spec → guarantees rung_0.
    await teardownUbi();
  });

  test('nudge surfaces + picker stays LLM + dismissal persists', async ({ page }) => {
    const qs = await seedQuerySet(3);

    await page.goto(`/query-sets/${qs.querySetId}`);
    await page.getByTestId('open-generate-judgments').click();
    await expect(page.getByTestId('generate-form')).toBeVisible({ timeout: 5_000 });

    // The readiness probe only fires once a target is entered.
    await page.getByTestId('gen-target').fill('products');

    // rung_0 → on-ramp nudge appears.
    await expect(page.getByTestId('ubi-onramp-nudge')).toBeVisible({ timeout: 10_000 });
    // Method picker stays on the LLM default (rubric textarea visible).
    await expect(page.getByLabel('Rubric')).toBeVisible();

    // Dismiss → nudge disappears.
    await page.getByTestId('ubi-nudge-dismiss').click();
    await expect(page.getByTestId('ubi-onramp-nudge')).toHaveCount(0);

    // Reload the page + re-open the dialog → dismissal persisted (localStorage,
    // keyed per cluster). The nudge must NOT reappear.
    await page.reload();
    await page.getByTestId('open-generate-judgments').click();
    await page.getByTestId('gen-target').fill('products');
    // Give the readiness probe time to resolve rung_0 again, then assert the
    // nudge stays hidden because of the persisted dismissal.
    await page.waitForTimeout(1_500);
    await expect(page.getByTestId('ubi-onramp-nudge')).toHaveCount(0);
  });
});
