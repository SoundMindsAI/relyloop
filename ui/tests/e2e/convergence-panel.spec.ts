// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * E2E spec: ConvergencePanel mount + null-state badge
 * (feat_study_convergence_indicator Story 4.2 / spec §14 FR-11).
 *
 * Real-backend smoke covering the panel's wiring on /studies/[id]:
 *  - The panel mounts between <ConfidencePanel> and the trials table.
 *  - The verdict badge renders with the canonical text.
 *  - The collapsible curve container is reachable.
 *
 * Why the "Verdict pending — not enough trials yet" path (rather than the
 * happy "Converged" path): the public seed-completed endpoint inserts only
 * two trials per study (winner + comparison). Two is well below the
 * CONVERGENCE_FLAT_MIN_COMPLETE floor of 5, so the API returns
 * `convergence: null` and the panel renders the null-state badge for
 * terminal-but-sub-minimum studies. This deliberately matches the panel's
 * AC-13b branch.
 *
 * The classifier behavior across all four verdicts is covered by the
 * domain unit tests in
 * backend/tests/unit/domain/study/test_convergence.py (39 cases) and the
 * GET /studies/{id} integration suite in
 * backend/tests/integration/test_studies_api_convergence.py (AC-8/9/10 +
 * classifier-exception). This spec proves the browser-side wiring lands.
 */
import { expect, test } from '@playwright/test';

import { seedFullChain, seedStudyCompletedWithDigest } from './helpers/seed';

test.describe('/studies/[id] convergence panel — null-state smoke', () => {
  test('mounts the panel and renders the not-enough-trials badge', async ({ page }) => {
    const chain = await seedFullChain(1);
    const seed = await seedStudyCompletedWithDigest({
      clusterId: chain.clusterId,
      querySetId: chain.querySetId,
      templateId: chain.templateId,
      judgmentListId: chain.judgmentListId,
      withPendingProposal: false,
    });

    await page.goto(`/studies/${seed.studyId}`);

    // Panel rendered (data-testid on the shadcn Card).
    const panel = page.getByTestId('convergence-panel');
    await expect(panel).toBeVisible();

    // Card title carries the canonical label + the InfoTooltip affordance.
    await expect(panel.getByText(/^Convergence$/)).toBeVisible();

    // Two trials << CONVERGENCE_FLAT_MIN_COMPLETE (5) → the panel takes
    // the AC-13b null-state branch.
    const badge = page.getByTestId('cs-convergence-verdict');
    await expect(badge).toHaveText('Verdict pending — not enough trials yet');
    await expect(badge).toHaveAttribute('data-null-reason', 'not_enough_trials');

    // Collapsible curve area exists even in the null path (the inner body
    // renders an em-dash placeholder rather than a chart).
    await expect(page.getByTestId('convergence-curve-details')).toBeVisible();
  });
});
