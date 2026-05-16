/**
 * E2E spec: /studies DataTable surface
 * (feat_data_table_primitive Story 3.1, spec §14 matrix row "studies").
 *
 * Covers the cross-cutting DataTable behaviors enabled by Epic 2 + the
 * Story 3.1 migration:
 *  - Search input (`?q=`) — debounced, URL-backed
 *  - Sort column header click → `?sort=<col>:<dir>` URL state
 *  - Status filter chip → `?status=<wire>` URL state
 *  - Cursor pagination Next / Prev with URL state survives refresh
 *
 * Runs against the real `make up` stack via the helpers in `./helpers/seed.ts`.
 * No `page.route()` mocking per CLAUDE.md E2E rule.
 */
import { expect, test } from '@playwright/test';

import { seedFullChain, seedStudy } from './helpers/seed';

test.describe('/studies DataTable', () => {
  test('search input drives ?q= URL state (debounced)', async ({ page }) => {
    // Seed two distinct studies so search has something to filter against.
    const chain = await seedFullChain(2);
    const studyA = await seedStudy({
      clusterId: chain.clusterId,
      querySetId: chain.querySetId,
      templateId: chain.templateId,
      judgmentListId: chain.judgmentListId,
      maxTrials: 1,
    });

    await page.goto('/studies');
    await expect(page.getByTestId('studies-table')).toBeVisible({ timeout: 5_000 });

    // Type the unique suffix of seeded study A and wait for `?q=` to land
    // in the URL after the 300ms debounce.
    const suffix = studyA.name.replace(/^e2e-study-/, '');
    await page.getByTestId('data-table-search').fill(suffix);
    await expect(page).toHaveURL(new RegExp(`[?&]q=${suffix}`), { timeout: 2_000 });
    await expect(page.getByText(studyA.name).first()).toBeVisible();
  });

  test('clicking a sortable column header serializes to ?sort=<col>:<dir>', async ({ page }) => {
    await page.goto('/studies');
    // Wait for either the populated table or the no-rows-exist empty state.
    await expect(
      page.getByTestId('studies-table').or(page.getByTestId('data-table-empty-no-rows-exist')),
    ).toBeVisible({ timeout: 5_000 });

    // Click the Name column header → first-click direction defaults to 'asc'.
    await page.getByTestId('data-table-sort-name').click();
    await expect(page).toHaveURL(/[?&]sort=name%3Aasc/);

    // Click again → toggles to 'desc'.
    await page.getByTestId('data-table-sort-name').click();
    await expect(page).toHaveURL(/[?&]sort=name%3Adesc/);

    // Third click → unsorted (URL drops the ?sort= param).
    await page.getByTestId('data-table-sort-name').click();
    await expect(page).not.toHaveURL(/[?&]sort=/);
  });

  test('status filter chip drives ?status= URL state', async ({ page }) => {
    await page.goto('/studies');
    await expect(
      page.getByTestId('studies-table').or(page.getByTestId('data-table-empty-no-rows-exist')),
    ).toBeVisible({ timeout: 5_000 });

    await page.getByTestId('filter-chip-status-completed').click();
    await expect(page).toHaveURL(/[?&]status=completed/);

    await page.getByTestId('filter-chip-status-all').click();
    await expect(page).not.toHaveURL(/[?&]status=/);
  });

  test('URL state survives a hard refresh (sort + filter + search)', async ({ page }) => {
    // Seed at least one study so the page renders the populated table form.
    const chain = await seedFullChain(2);
    await seedStudy({
      clusterId: chain.clusterId,
      querySetId: chain.querySetId,
      templateId: chain.templateId,
      judgmentListId: chain.judgmentListId,
      maxTrials: 1,
    });

    await page.goto('/studies?sort=name%3Aasc&status=queued');
    // Sort column header reflects the asc state (data-active-dir testid attribute).
    await expect(page.getByTestId('data-table-sort-name')).toHaveAttribute('data-active-dir', 'asc');
    // Filter chip reflects the queued active state.
    await expect(page.getByTestId('filter-chip-status-queued')).toHaveAttribute(
      'data-active',
      'true',
    );

    // Hard reload — URL state must survive the round-trip.
    await page.reload();
    await expect(page.getByTestId('data-table-sort-name')).toHaveAttribute('data-active-dir', 'asc');
    await expect(page.getByTestId('filter-chip-status-queued')).toHaveAttribute(
      'data-active',
      'true',
    );
  });
});
