// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * E2E spec: /clusters/[id] studies-by-cluster table inheritance
 * (feat_data_table_primitive Story 3.9 — verify the wrapper inherits the
 * new DataTable behavior via composition with `<StudiesTable>`).
 *
 * The wrapper at `ui/src/components/clusters/studies-by-cluster-table.tsx`
 * was updated in Story 3.1 to thread a per-cluster `useDataTableUrlState`
 * into the migrated `<StudiesTable>`. This spec confirms the cluster-detail
 * page renders the new DataTable toolbar (search input, filter chips,
 * total count) on a cluster that has at least one study.
 */
import { expect, test } from '@playwright/test';

import { seedFullChain, seedStudy } from './helpers/seed';

test.describe('/clusters/[id] studies-by-cluster DataTable inheritance', () => {
  test('renders the new DataTable toolbar on a cluster that has studies', async ({ page }) => {
    const chain = await seedFullChain(2);
    await seedStudy({
      clusterId: chain.clusterId,
      querySetId: chain.querySetId,
      templateId: chain.templateId,
      judgmentListId: chain.judgmentListId,
      maxTrials: 1,
    });

    await page.goto(`/clusters/${chain.clusterId}`);
    // The studies-table testid is preserved by the migrated component;
    // the toolbar is the new DataTable affordance.
    await expect(page.getByTestId('studies-table')).toBeVisible({ timeout: 5_000 });
    await expect(page.getByTestId('data-table-search')).toBeVisible();
    // The status filter chip row comes from the studies column config —
    // proves the column inheritance flows through the wrapper.
    await expect(page.getByTestId('filter-chip-status-all')).toBeVisible();
  });

  test('status filter chip drives URL state on the per-cluster route', async ({ page }) => {
    const chain = await seedFullChain(2);
    await seedStudy({
      clusterId: chain.clusterId,
      querySetId: chain.querySetId,
      templateId: chain.templateId,
      judgmentListId: chain.judgmentListId,
      maxTrials: 1,
    });
    await page.goto(`/clusters/${chain.clusterId}`);
    await expect(page.getByTestId('studies-table')).toBeVisible({ timeout: 5_000 });

    await page.getByTestId('filter-chip-status-running').click();
    await expect(page).toHaveURL(/[?&]status=running/);

    await page.getByTestId('filter-chip-status-all').click();
    await expect(page).not.toHaveURL(/[?&]status=/);
  });
});
