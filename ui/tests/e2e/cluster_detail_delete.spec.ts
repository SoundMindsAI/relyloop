/**
 * E2E spec: /clusters/[id] delete flow regression.
 *
 * Guards against the bug where useDeleteCluster.onSuccess ran a blanket
 * `invalidateQueries(['clusters'])` and prefix-matched the still-mounted
 * `useCluster(id)` subscription on /clusters/[id], firing a stale
 * GET /clusters/{id} → 404 before the call-site could router.push away.
 *
 * Asserts the user-visible properties end-to-end:
 *  1. Confirmation gate (name must match) → confirm button enables.
 *  2. Delete succeeds → navigation back to /clusters list.
 *  3. No GET to the deleted cluster's detail URL returns a 4xx after the
 *     DELETE fires (the regression signature).
 */
import { expect, test } from '@playwright/test';

import { seedCluster } from './helpers/seed';

test.describe('/clusters/[id] delete flow', () => {
  test('deletes the cluster and does not fire a 404-bound detail refetch', async ({ page }) => {
    const cluster = await seedCluster();
    const detailPath = `/api/v1/clusters/${cluster.id}`;

    // Track any GET to the deleted cluster's detail URL that returns >=400 —
    // the exact signature of the regression. The DELETE itself returns 204
    // and is method=DELETE, so it never matches this filter.
    const detailGetErrors: { status: number; method: string }[] = [];
    page.on('response', (resp) => {
      const url = resp.url();
      if (resp.status() >= 400 && url.endsWith(detailPath)) {
        detailGetErrors.push({ status: resp.status(), method: resp.request().method() });
      }
    });

    await page.goto(`/clusters/${cluster.id}`);

    // Confirm gate: button disabled until typed name matches.
    await page.getByTestId('delete-cluster').click();
    const confirm = page.getByTestId('confirm-delete');
    await expect(confirm).toBeDisabled();
    await page.getByTestId('confirm-name-input').fill(cluster.name);
    await expect(confirm).toBeEnabled();

    // Trigger delete + wait for navigation.
    await confirm.click();
    await page.waitForURL(/\/clusters$/, { timeout: 10_000 });

    // Give any pending TanStack refetch enough time to fire before sampling.
    await page.waitForTimeout(500);

    expect(detailGetErrors).toEqual([]);
  });
});
