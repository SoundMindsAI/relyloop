// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * E2E spec: overnight-chain summary panel (feat_overnight_autopilot, Story 4.2,
 * FR-4).
 *
 * Real-backend coverage of the rolled-up chain-summary surface that
 * `AutoFollowupChainPanel` renders from `GET /api/v1/studies/{id}/chain`:
 *  - `data-testid="chain-summary"` visible on the anchor's detail page.
 *  - The seeded link names (root + middle + leaf) appear in the ordered list.
 *  - Cumulative-lift line renders with the signed `±0.0NNN` format.
 *  - Stop-reason phrase renders for the seeded terminal state.
 *  - Best-config branch renders (the `(Awaiting proposal)` plain-text branch
 *    for the seeded state — no proposal is attached to any chain link).
 *
 * Per CLAUDE.md E2E rules: real backend at localhost:8000, real UI at
 * localhost:3000, browser interactions via the `page` object. NO `page.route()`
 * mocking — `seedAutoFollowupChain` / `seedFullChain` are setup-only API
 * helpers; every assertion verifies browser-visible DOM.
 *
 * DETERMINISM CHOICE (Story 4.2 task 4):
 *   The spec seeds with the helper defaults — `inFlightLeaf:true,
 *   inFlightMiddle:true`. That produces a depth-2 chain whose middle + leaf
 *   links stay `queued`, so the chain's `stop_reason` derives deterministically
 *   to `in_flight` → the panel renders "Stop reason: chain still running". This
 *   avoids waiting on the auto-followup worker to complete the chain (which is
 *   neither deterministic nor <30s), exactly the path Story 4.2 task 4
 *   explicitly permits. The same seeded state yields:
 *     - cumulative_lift = 0 → rendered as `+0.0000` (matches `±0.0NNN`).
 *     - best_link = the completed root, with no proposal attached
 *       (`proposal_id_for_best_link = null`), so the best-config row renders the
 *       `(Awaiting proposal)` plain-text branch. The public `POST
 *       /api/v1/proposals` creates manual proposals only (`study_id = null`), so
 *       there is no deterministic way to attach a proposal to a chain link
 *       without a full orchestrator run; the `(Awaiting proposal)` branch is the
 *       branch the DoD permits asserting here.
 */
import { expect, test } from '@playwright/test';

import { seedAutoFollowupChain, seedFullChain } from './helpers/seed';

test.describe('/studies — overnight chain summary', () => {
  test('chain-summary panel renders on the anchor detail page', async ({ page }) => {
    // Seed a 3-link chain (root → middle → leaf) with the helper defaults:
    // root completed, middle + leaf queued → stop_reason derives to in_flight.
    const fc = await seedFullChain(3);
    const seed = await seedAutoFollowupChain({
      clusterId: fc.clusterId,
      querySetId: fc.querySetId,
      templateId: fc.templateId,
      judgmentListId: fc.judgmentListId,
      depth: 2,
    });
    // depth=2 → 3 nodes total → exactly one middle node.
    expect(seed.middleIds).toHaveLength(1);
    const middleId = seed.middleIds[0]!;

    // Resolve the seeded link names from the backend so the DOM assertions
    // are grounded in real wire values (setup-only API reads).
    const names = await Promise.all(
      [seed.rootId, middleId, seed.leafId].map(async (id) => {
        const resp = await page.request.get(
          new URL(`/api/v1/studies/${id}`, 'http://127.0.0.1:8000').toString(),
        );
        expect(resp.ok()).toBe(true);
        return ((await resp.json()) as { name: string }).name;
      }),
    );
    const [rootName, middleName, leafName] = names;

    // Navigate to the ANCHOR (root) detail page; the chain summary rolls up
    // from the anchor downward.
    await page.goto(`/studies/${seed.rootId}`);
    await expect(page.getByTestId('study-name')).toBeVisible({ timeout: 10_000 });

    // (1) The chain-summary surface is visible.
    const summary = page.getByTestId('chain-summary');
    await expect(summary).toBeVisible({ timeout: 10_000 });

    // (2) All three seeded link names appear in the ordered link list.
    const links = page.getByTestId('chain-summary-link');
    await expect(links).toHaveCount(3);
    await expect(summary).toContainText(rootName!);
    await expect(summary).toContainText(middleName!);
    await expect(summary).toContainText(leafName!);

    // (3) Cumulative-lift line renders with the signed ±0.0NNN format.
    const cumulativeLift = page.getByTestId('chain-summary-cumulative-lift');
    await expect(cumulativeLift).toBeVisible();
    await expect(cumulativeLift).toContainText('Cumulative lift:');
    // The signed 4-decimal format: optional leading '+'/'-', then 0.NNNN.
    await expect(cumulativeLift).toContainText(/[+-]?\d+\.\d{4}/);

    // (4) Stop-reason phrase for the seeded in-flight chain.
    const stopReason = page.getByTestId('chain-summary-stop-reason');
    await expect(stopReason).toBeVisible();
    await expect(stopReason).toContainText('Stop reason: chain still running');

    // (5) Best-config branch: best link is the completed root, with no proposal
    // attached → the `(Awaiting proposal)` plain-text branch.
    const bestConfig = page.getByTestId('chain-summary-best-config');
    await expect(bestConfig).toBeVisible();
    await expect(bestConfig).toContainText('Best config:');
    await expect(bestConfig).toContainText('(Awaiting proposal)');
    await expect(bestConfig).toContainText(rootName!);
    // No proposal link is rendered in this branch.
    await expect(bestConfig.locator('a[href^="/proposals/"]')).toHaveCount(0);
  });
});
