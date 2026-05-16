/**
 * E2E spec: /studies/[id] trials DataTable surface
 * (feat_data_table_primitive Story 3.7, spec §14 matrix row "trials").
 *
 * Per-study trials view: searchable=false, no filters. Sort uses the
 * fused-wire codec from trials-table.column-config. Trial number column
 * is asc-only (no `optuna_trial_number_desc` in TrialSortKey).
 */
import { expect, test } from '@playwright/test';

import { seedFullChain, seedStudy } from './helpers/seed';

test.describe('/studies/[id] trials DataTable', () => {
  test('Primary metric sort header serializes to ?sort=primary_metric_<dir>', async ({ page }) => {
    const chain = await seedFullChain(2);
    const study = await seedStudy({
      clusterId: chain.clusterId,
      querySetId: chain.querySetId,
      templateId: chain.templateId,
      judgmentListId: chain.judgmentListId,
      maxTrials: 1,
    });
    await page.goto(`/studies/${study.id}`);
    await expect(
      page.getByTestId('trials-table').or(page.getByTestId('data-table-empty-no-rows-exist')),
    ).toBeVisible({ timeout: 10_000 });

    // First click on Primary metric → firstClickDirection 'desc' → wire `primary_metric_desc`.
    await page.getByTestId('data-table-sort-primary_metric').click();
    await expect(page).toHaveURL(/[?&]sort=primary_metric_desc/);
    // Second click → primary_metric_asc.
    await page.getByTestId('data-table-sort-primary_metric').click();
    await expect(page).toHaveURL(/[?&]sort=primary_metric_asc/);
    // Third click → unsorted (param drops).
    await page.getByTestId('data-table-sort-primary_metric').click();
    await expect(page).not.toHaveURL(/[?&]sort=/);
  });

  test('Trial number column is asc-only — cycles unsorted → asc → unsorted', async ({ page }) => {
    const chain = await seedFullChain(2);
    const study = await seedStudy({
      clusterId: chain.clusterId,
      querySetId: chain.querySetId,
      templateId: chain.templateId,
      judgmentListId: chain.judgmentListId,
      maxTrials: 1,
    });
    await page.goto(`/studies/${study.id}`);
    await expect(
      page.getByTestId('trials-table').or(page.getByTestId('data-table-empty-no-rows-exist')),
    ).toBeVisible({ timeout: 10_000 });

    await page.getByTestId('data-table-sort-optuna_trial_number').click();
    await expect(page).toHaveURL(/[?&]sort=optuna_trial_number_asc/);
    // Second click — no `optuna_trial_number_desc` exists; cycle clears.
    await page.getByTestId('data-table-sort-optuna_trial_number').click();
    await expect(page).not.toHaveURL(/[?&]sort=/);
  });

  test('Direct URL load with ?sort=ended_at_asc shows the column active in asc', async ({
    page,
  }) => {
    const chain = await seedFullChain(2);
    const study = await seedStudy({
      clusterId: chain.clusterId,
      querySetId: chain.querySetId,
      templateId: chain.templateId,
      judgmentListId: chain.judgmentListId,
      maxTrials: 1,
    });
    await page.goto(`/studies/${study.id}?sort=ended_at_asc`);
    await expect(
      page.getByTestId('trials-table').or(page.getByTestId('data-table-empty-no-rows-exist')),
    ).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId('data-table-sort-ended_at')).toHaveAttribute(
      'data-active-dir',
      'asc',
    );
  });
});
