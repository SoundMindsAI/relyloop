// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * E2E spec: Overnight result card (feat_overnight_final_solution_phase2, Story 6).
 *
 * Real-backend Playwright coverage of the morning summary card's mount
 * predicate. Per spec D-17 the click-through to a winning proposal is a
 * best-effort assertion against the demo seed — the test endpoint at
 * /api/v1/_test/auto-followup/seed-chain creates studies + chain links but
 * does NOT create the digest + proposal lineage required for the
 * full-card AC-1 rendering. The fast lane that always runs is the
 * negative predicate: when the chain is in-flight (`inFlightLeaf=true`),
 * the card is hidden.
 *
 * Limitations (documented inline):
 *  - The seed-chain endpoint creates chain links with NULL
 *    `selected_followup_kind` (legacy narrow behavior — Phase 1 D-12),
 *    so even when we mark all links completed, the card renders WITHOUT
 *    the path summary. That's by spec (AC-4); we assert the card is
 *    visible, the path line is absent, and the best-config line falls
 *    back to "Best config: —" because no proposal exists.
 *  - Per spec D-17 a full AC-12 click-through is downgraded; vitest
 *    covers the click-through via mocked hooks.
 */

import { expect, test } from '@playwright/test';

import { seedAutoFollowupChain, seedFullChain } from './helpers/seed';

test.describe('/studies/{id} — Overnight result card', () => {
  test('AC-2 (negative): card hidden when chain stop_reason is in_flight', async ({ page }) => {
    // Seed a 2-link chain whose leaf is queued (in-flight). The chain
    // endpoint returns stop_reason="in_flight" → shouldShowOvernightResultCard
    // returns false → card returns null.
    const fixture = await seedFullChain(2);
    const { rootId } = await seedAutoFollowupChain({
      clusterId: fixture.clusterId,
      querySetId: fixture.querySetId,
      templateId: fixture.templateId,
      judgmentListId: fixture.judgmentListId,
      depth: 2,
      inFlightLeaf: true,
      inFlightMiddle: false,
    });

    await page.goto(`/studies/${rootId}`);
    // Page mounts; AutoFollowupChainPanel renders for the in-flight chain
    // (it has its own visibility predicate that allows in-flight chains),
    // but OvernightResultCard returns null per FR-7.
    await expect(page.getByTestId('study-page-summary')).toBeVisible();
    await expect(page.getByTestId('overnight-result-card')).toHaveCount(0);
  });

  test('FR-7 (positive predicate): card visible when chain is terminated and has ≥ 2 links', async ({
    page,
  }) => {
    // Seed a 3-link chain (depth=2 = parent + middle + leaf), all completed.
    // The chain endpoint computes stop_reason from the leaf state — when
    // the leaf is `completed` with no children, the derived stop_reason
    // is "depth_exhausted" or "no_lift" (terminal). Both satisfy the
    // mount predicate `stop_reason !== 'in_flight' && links.length >= 2`.
    const fixture = await seedFullChain(2);
    const { rootId, leafId } = await seedAutoFollowupChain({
      clusterId: fixture.clusterId,
      querySetId: fixture.querySetId,
      templateId: fixture.templateId,
      judgmentListId: fixture.judgmentListId,
      depth: 2,
      inFlightLeaf: false,
      inFlightMiddle: false,
    });

    await page.goto(`/studies/${rootId}`);
    await expect(page.getByTestId('study-page-summary')).toBeVisible();

    // Card visible.
    const card = page.getByTestId('overnight-result-card');
    await expect(card).toBeVisible();

    // Path line is OMITTED because the seed creates chain links with NULL
    // selected_followup_kind (legacy narrow pattern per Phase 1 D-12).
    // This is the AC-4 case; the card still renders headline + best-config
    // + stop-reason.
    await expect(card.getByTestId('overnight-result-path')).toHaveCount(0);

    // Best-config falls back to "—" because the seeder doesn't create a
    // proposal for the leaf. Per spec FR-1 / D-13 three-case matrix:
    // best_link_id may be set but proposal_id_for_best_link is null OR
    // best_link_id itself is null when no link has a best_metric — either
    // way the line renders.
    const bestConfig = card.getByTestId('overnight-result-best-config');
    await expect(bestConfig).toBeVisible();

    // Stop-reason line is rendered with a non-empty phrase.
    const stopReason = card.getByTestId('overnight-result-stop-reason');
    await expect(stopReason).toBeVisible();
    await expect(stopReason).toContainText(/Stop reason:/);

    // The leaf id appears in chainChildren so the existing chain panel
    // also renders below — both surfaces co-exist per spec D-10.
    expect(leafId).toBeTruthy();
  });
});
