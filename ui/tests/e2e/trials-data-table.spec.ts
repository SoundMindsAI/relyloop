/**
 * E2E spec: /studies/[id] trials DataTable surface
 * (feat_data_table_primitive Story 3.7, spec §14 matrix row "trials").
 *
 * Per-study trials view: searchable=false, no filters. Sort uses the
 * fused-wire codec from trials-table.column-config. Trial number column
 * is asc-only (no `optuna_trial_number_desc` in TrialSortKey).
 *
 * Why these tests are URL/API-driven rather than click-driven: the
 * trials orchestrator runs asynchronously after seedStudy(). In CI the
 * polling cron + adapter latency mean trials can take 60+ seconds to
 * materialize — too slow for a CI smoke job to wait on. The click
 * cycle itself (codec → URL) is covered exhaustively at the component
 * layer in `ui/src/__tests__/components/common/data-table-sort-header.test.tsx`
 * + `data-table.test.tsx`. What only E2E can verify is the live wire
 * contract: that the backend accepts the fused-wire tokens AND that
 * the URL state survives a real round-trip. That's what each test below
 * pins.
 */
import { expect, test } from '@playwright/test';

import { seedFullChain, seedStudy } from './helpers/seed';

const API_BASE = process.env.PLAYWRIGHT_API_BASE_URL ?? 'http://127.0.0.1:8000';

test.describe('/studies/[id] trials DataTable', () => {
  test('backend accepts fused-wire sort tokens via the trials list endpoint', async ({ page }) => {
    const chain = await seedFullChain(2);
    const study = await seedStudy({
      clusterId: chain.clusterId,
      querySetId: chain.querySetId,
      templateId: chain.templateId,
      judgmentListId: chain.judgmentListId,
      maxTrials: 1,
    });
    // The 5 valid TrialSortKey tokens — each must return 200.
    for (const sort of [
      'primary_metric_desc',
      'primary_metric_asc',
      'ended_at_desc',
      'ended_at_asc',
      'optuna_trial_number_asc',
    ]) {
      const resp = await page.request.get(
        `${API_BASE}/api/v1/studies/${study.id}/trials?sort=${sort}&limit=1`,
      );
      expect(resp.status(), `sort=${sort}`).toBe(200);
    }
  });

  test('backend rejects invalid sort tokens with 422', async ({ page }) => {
    const chain = await seedFullChain(2);
    const study = await seedStudy({
      clusterId: chain.clusterId,
      querySetId: chain.querySetId,
      templateId: chain.templateId,
      judgmentListId: chain.judgmentListId,
      maxTrials: 1,
    });
    // `optuna_trial_number_desc` is NOT in TrialSortKey (Story 3.7 fused-wire
    // codec configures the column as asc-only). Garbage tokens also reject.
    for (const sort of ['optuna_trial_number_desc', 'name:asc', 'garbage']) {
      const resp = await page.request.get(
        `${API_BASE}/api/v1/studies/${study.id}/trials?sort=${sort}&limit=1`,
      );
      expect(resp.status(), `sort=${sort}`).toBe(422);
    }
  });

  test('direct URL load surfaces the trials page without error', async ({ page }) => {
    const chain = await seedFullChain(2);
    const study = await seedStudy({
      clusterId: chain.clusterId,
      querySetId: chain.querySetId,
      templateId: chain.templateId,
      judgmentListId: chain.judgmentListId,
      maxTrials: 1,
    });
    // Direct URL load with a fused-wire sort token. The page must render
    // (study header visible) AND the URL must survive the navigation. The
    // trials table itself may or may not be populated yet (orchestrator
    // timing), so we don't assert on row contents — just that the page
    // loads cleanly and the URL state is preserved.
    await page.goto(`/studies/${study.id}?sort=ended_at_asc`);
    await expect(page.getByTestId('study-name')).toBeVisible({ timeout: 10_000 });
    await expect(page).toHaveURL(/[?&]sort=ended_at_asc/);

    // Hard reload — URL state must survive.
    await page.reload();
    await expect(page).toHaveURL(/[?&]sort=ended_at_asc/);
  });
});
