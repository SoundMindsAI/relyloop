/**
 * Walkthrough: Browse proposals + filters (guide 07).
 *
 * Captures the proposals queue review surface — list, filter chips
 * (status / source / cluster), URL-backed state. Proposal detail and
 * reject flows are covered separately in guide 02.
 */
import path from 'node:path';

import { expect, test } from '@playwright/test';

import { seedCluster, seedProposal, seedTemplate } from '../helpers/seed';

const SCREENSHOTS = path.resolve(__dirname, '../../../public/guides/07_browse_proposals');

test.describe('Walkthrough: Browse proposals', () => {
  test('captures the proposals list filter UX', async ({ page }) => {
    // Seed three manual proposals so the list has real rows.
    const cluster = await seedCluster();
    const template = await seedTemplate();
    await seedProposal({ clusterId: cluster.id, templateId: template.id });
    await seedProposal({ clusterId: cluster.id, templateId: template.id });
    await seedProposal({ clusterId: cluster.id, templateId: template.id });

    await page.goto('/proposals');
    await expect(page.getByTestId('filter-chip-status-all')).toBeVisible();
    await page.waitForTimeout(600);
    await page.screenshot({
      path: path.join(SCREENSHOTS, '01-proposals-list.png'),
      fullPage: true,
    });

    // 02: Status chip → pending (URL ?status=pending).
    await page.getByTestId('filter-chip-status-pending').click();
    await page.waitForTimeout(400);
    await page.screenshot({
      path: path.join(SCREENSHOTS, '02-status-filter-pending.png'),
      fullPage: false,
    });

    // 03: Source chip → manual.
    await page.getByTestId('filter-chip-source-manual').click();
    await page.waitForTimeout(400);
    await page.screenshot({
      path: path.join(SCREENSHOTS, '03-source-filter-manual.png'),
      fullPage: false,
    });

    // 04: Cluster filter dropdown.
    await page.getByTestId('fk-select-cluster_id').click();
    await page.waitForTimeout(400);
    await page.screenshot({
      path: path.join(SCREENSHOTS, '04-cluster-filter-open.png'),
      fullPage: false,
    });
    // Close the dropdown.
    await page.keyboard.press('Escape');
    await page.waitForTimeout(300);

    // 05: Reset to all + show the row count.
    await page.getByTestId('filter-chip-status-all').click();
    await page.getByTestId('filter-chip-source-all').click();
    await page.waitForTimeout(400);
    await page.screenshot({
      path: path.join(SCREENSHOTS, '05-all-filters-reset.png'),
      fullPage: false,
    });
  });
});
