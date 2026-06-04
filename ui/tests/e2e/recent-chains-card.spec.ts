// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * E2E spec: "Ran while you were away" card on /studies
 * (feat_overnight_studies_summary_card Story 3.1).
 *
 * Real-backend Playwright coverage of the card's mount + review-link
 * behavior:
 *
 *  - Seeds a 2+ link chain whose leaf is terminal (`inFlightLeaf=false`)
 *    via the `seedAutoFollowupChain` helper, then sets the localStorage
 *    visited cutoff to "before" the chain via `page.addInitScript()` so
 *    the card has rows to show.
 *  - Asserts the card renders with the anchor name and a clickable
 *    review-chain link pointing at `/studies/{root_id}`.
 *  - Asserts "Got it" dismisses the card so it's gone after a reload
 *    (FR-5 — the +1ms exclusive nudge prevents re-show).
 *
 * Per CLAUDE.md E2E rules: no `page.route()` mocking of backend; assertions
 * verify browser-visible behavior via `page`; `request` is used only via
 * the seed helpers for test setup.
 *
 * Limitation: the seed-chain endpoint creates chain links without
 * `selected_followup_kind` (legacy narrow per Phase 1 D-12), and the
 * leaf may or may not carry a usable `best_metric` — the test asserts
 * card visibility + anchor link target, not the per-row metric content.
 * Metric / null-metric / stop-reason rendering is covered exhaustively
 * by the vitest component suite in `__tests__/components/studies/
 * recent-chains-card.test.tsx`.
 */

import { expect, test } from '@playwright/test';

import { seedAutoFollowupChain, seedFullChain } from './helpers/seed';

test.describe('/studies — Recent chains card', () => {
  test('renders the card with a working Review chain link after a terminated chain', async ({
    page,
  }) => {
    // Seed a 3-link chain (depth=2 = parent + middle + leaf), all completed
    // (leaf not in-flight). The chain endpoint sees the leaf as terminal,
    // so the discovery query returns one row for the chain.
    const fixture = await seedFullChain(2);
    const { rootId } = await seedAutoFollowupChain({
      clusterId: fixture.clusterId,
      querySetId: fixture.querySetId,
      templateId: fixture.templateId,
      judgmentListId: fixture.judgmentListId,
      depth: 2,
      inFlightLeaf: false,
      inFlightMiddle: false,
    });

    // Force the visited-state cutoff into the past so the card shows the
    // chain that was just seeded — the default 7-day window already
    // covers it, but this is belt-and-suspenders and decouples the test
    // from clock skew between the seeder + the browser tab.
    await page.addInitScript(() => {
      window.localStorage.setItem(
        'relyloop.last_visited_studies_at',
        '2000-01-01T00:00:00.000Z',
      );
    });

    await page.goto('/studies');

    // Card visible.
    const card = page.getByTestId('recent-chains-card');
    await expect(card).toBeVisible();
    await expect(card.getByText('Ran while you were away')).toBeVisible();

    // The anchor link points at /studies/{rootId} (the chain's anchor is
    // the root, NOT the leaf — the discovery query dedupes by anchor).
    const anchorLink = card.getByTestId(`recent-chains-card-anchor-link-${rootId}`);
    await expect(anchorLink).toBeVisible();
    await expect(anchorLink).toHaveAttribute('href', `/studies/${rootId}`);

    // Click through and confirm navigation. The study page summary is
    // the canonical "we landed on the right page" assertion (matches
    // the existing overnight-result-card spec).
    await anchorLink.click();
    await expect(page).toHaveURL(new RegExp(`/studies/${rootId}$`));
    await expect(page.getByTestId('study-page-summary')).toBeVisible();
  });

  test('"Got it" dismisses the card; it stays hidden after reload (FR-5)', async ({ page }) => {
    const fixture = await seedFullChain(2);
    await seedAutoFollowupChain({
      clusterId: fixture.clusterId,
      querySetId: fixture.querySetId,
      templateId: fixture.templateId,
      judgmentListId: fixture.judgmentListId,
      depth: 2,
      inFlightLeaf: false,
      inFlightMiddle: false,
    });

    await page.addInitScript(() => {
      window.localStorage.setItem(
        'relyloop.last_visited_studies_at',
        '2000-01-01T00:00:00.000Z',
      );
    });

    await page.goto('/studies');

    // Card visible first.
    const card = page.getByTestId('recent-chains-card');
    await expect(card).toBeVisible();

    // Dismiss + verify the card unmounts on the next refetch (the query
    // key includes `since`, so the new cutoff produces an empty list).
    await card.getByTestId('recent-chains-card-dismiss').click();
    await expect(page.getByTestId('recent-chains-card')).toHaveCount(0);

    // Reload — visited cutoff persists in localStorage; the card stays
    // gone because the chain's tail completed_at is now < since.
    await page.reload();
    await expect(page.getByTestId('recent-chains-card')).toHaveCount(0);
  });
});
