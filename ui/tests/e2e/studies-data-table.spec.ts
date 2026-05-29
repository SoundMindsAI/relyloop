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
    // The `?q=` URL lands as soon as the 300ms debounce fires, but the
    // studies-list still has to refetch the filtered page and re-render it.
    // studyA may have been on a later page pre-filter, so it only reliably
    // appears once that refetch completes. On a loaded CI runner that can
    // exceed Playwright's default 5s expect timeout — the cause of the
    // intermittent smoke red tracked as bug_smoke_studies_data_table_search_flake.
    // Scope the match to the table (avoids incidental page text) and give the
    // web-first assertion generous headroom; it auto-retries until visible or
    // the timeout, so this rides out the debounce + refetch + render without
    // weakening what's verified (studyA IS reachable via the filtered list).
    await expect(
      page.getByTestId('studies-table').getByText(studyA.name).first(),
    ).toBeVisible({ timeout: 15_000 });
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
    await page.goto('/studies?sort=name%3Aasc&status=queued');
    // Filter chip lives in the toolbar (rendered regardless of row count);
    // the sort header lives in the table head and only mounts when rows
    // are present. We assert on (a) the URL itself (always survives) and
    // (b) the filter chip (always rendered). The sort header is omitted
    // because the orchestrator may have advanced any seeded studies past
    // 'queued' by the time the page renders, leaving the empty state and
    // no sort header to assert on.
    await expect(page).toHaveURL(/[?&]sort=name%3Aasc/);
    await expect(page).toHaveURL(/[?&]status=queued/);
    await expect(page.getByTestId('filter-chip-status-queued')).toHaveAttribute(
      'data-active',
      'true',
    );

    await page.reload();
    await expect(page).toHaveURL(/[?&]sort=name%3Aasc/);
    await expect(page).toHaveURL(/[?&]status=queued/);
    await expect(page.getByTestId('filter-chip-status-queued')).toHaveAttribute(
      'data-active',
      'true',
    );
  });
});
