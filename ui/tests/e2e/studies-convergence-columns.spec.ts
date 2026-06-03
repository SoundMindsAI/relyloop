// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * E2E spec: /studies Trials + Convergence columns
 * (feat_studies_convergence_visibility Story 1.2 / FR-4, AC-6).
 *
 * Runs against the real `make up` stack via the helpers in `./helpers/seed.ts`.
 * No `page.route()` mocking per CLAUDE.md E2E rule — the columns are driven
 * by the real backend's trial_count + convergence_verdict fields.
 *
 * A freshly seeded study runs only a handful of trials (well below the
 * 50-trial warmup floor), so its convergence verdict is either
 * "Too few trials" or null (em-dash) — both are valid renderings. The
 * stable, deterministic assertions are therefore:
 *  - the "Trials" + "Convergence" column headers render;
 *  - the seeded study's row shows a numeric Trials cell;
 *  - the Convergence cell renders either a verdict badge or the em-dash
 *    null-state (never crashes / never blank).
 */
import { expect, test } from '@playwright/test';

import { seedFullChain, seedStudy } from './helpers/seed';

test.describe('/studies convergence columns', () => {
  test('Trials + Convergence columns render against the real backend', async ({ page }) => {
    const chain = await seedFullChain(2);
    const study = await seedStudy({
      clusterId: chain.clusterId,
      querySetId: chain.querySetId,
      templateId: chain.templateId,
      judgmentListId: chain.judgmentListId,
      maxTrials: 3,
    });

    await page.goto('/studies');
    await expect(page.getByTestId('studies-table')).toBeVisible({ timeout: 5_000 });

    // Both new column headers are present.
    await expect(
      page.getByTestId('studies-table').getByRole('columnheader', { name: /Trials/ }),
    ).toBeVisible();
    await expect(
      page.getByTestId('studies-table').getByRole('columnheader', { name: /Convergence/ }),
    ).toBeVisible();

    // Locate the seeded study's row and assert its Trials cell is numeric.
    // Filter the list to the seeded study so its row is reliably on the first
    // page regardless of how many other studies exist.
    const suffix = study.name.replace(/^e2e-study-/, '');
    await page.getByTestId('data-table-search').fill(suffix);
    await expect(
      page.getByTestId('studies-table').getByText(study.name).first(),
    ).toBeVisible({ timeout: 15_000 });

    const row = page.locator(`[data-testid="study-row-${study.id}"]`);
    await expect(row).toBeVisible();
    // The Trials cell shows a non-negative integer (tabular-nums span).
    await expect(row.getByText(/^\d+$/).first()).toBeVisible();

    // The Convergence cell renders either a verdict badge OR the em-dash
    // null-state — both are correct for a low-trial study. Assert the cell
    // is non-empty (not blank/undefined).
    const convergenceBadge = row.locator('[data-verdict]');
    const emDash = row.getByText('—');
    await expect(convergenceBadge.or(emDash).first()).toBeVisible();
  });
});
