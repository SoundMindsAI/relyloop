/**
 * E2E spec: / (dashboard) landing page.
 *
 * The dashboard is read-only — it surfaces two count cards (open proposals,
 * studies completed in the last 7 days) plus a recent-studies card. We
 * verify the cards render and their links navigate to the correct list
 * pages with the expected query parameters.
 */
import { expect, test } from '@playwright/test';

test.describe('/ dashboard', () => {
  test('renders the two count cards wrapped in navigation links', async ({ page }) => {
    await page.goto('/');

    // CountCard wraps `<Card data-testid={...}>` inside a `<Link href={...}>`.
    // We assert visibility on the card AND href on the ancestor anchor.
    const openProposals = page.getByTestId('card-open-proposals');
    await expect(openProposals).toBeVisible({ timeout: 5_000 });
    const proposalsHref = await openProposals.locator('xpath=ancestor::a').getAttribute('href');
    expect(proposalsHref).toContain('/proposals');

    const completed = page.getByTestId('card-completed-recent');
    await expect(completed).toBeVisible();
    const studiesHref = await completed.locator('xpath=ancestor::a').getAttribute('href');
    expect(studiesHref).toContain('/studies');
    expect(studiesHref).toContain('status=completed');
  });

  test('open-proposals card click navigates to /proposals', async ({ page }) => {
    await page.goto('/');
    await page.getByTestId('card-open-proposals').click();
    await expect(page).toHaveURL(/\/proposals/);
  });
});

// feat_home_first_run_demo_nudge — Story 4.1.
//
// Verifies the demo-data banner against the real backend (no page.route
// mocking). The CI environment seeds 4 demo clusters via `make up`, so
// the banner SHOULD be visible on a fresh `/` load. Coverage:
//   1. Banner is visible despite the seed already creating studies
//      (proves the FR-1 trigger is not gated on `studies==0`).
//   2. Dismiss persists across reload (localStorage round-trip).
//   3. Pre-set localStorage via addInitScript hides the banner from
//      initial render.
test.describe('/ dashboard demo-data banner', () => {
  test('banner renders on a seeded stack regardless of seeded studies (FR-1, AC-1)', async ({
    page,
    context,
  }) => {
    // Ensure no stale dismissal from a prior test in this worker.
    await context.addInitScript(() => {
      window.localStorage.removeItem('relyloop.home-first-run-demo-nudge.dismissed');
    });
    await page.goto('/');
    const banner = page.getByTestId('demo-data-banner');
    await expect(banner).toBeVisible({ timeout: 10_000 });
    await expect(banner.getByRole('heading')).toHaveText("You're set up with demo data.");
    // Demo cluster slugs appear in the body.
    await expect(banner.getByText('acme-products-prod')).toBeVisible();
  });

  test('Dismiss persists across reload (FR-7, AC-3)', async ({ page, context }) => {
    await context.addInitScript(() => {
      window.localStorage.removeItem('relyloop.home-first-run-demo-nudge.dismissed');
    });
    await page.goto('/');
    await expect(page.getByTestId('demo-data-banner')).toBeVisible({ timeout: 10_000 });
    await page.getByTestId('demo-data-banner-dismiss').click();
    await expect(page.getByTestId('demo-data-banner')).toBeHidden();
    await page.reload();
    // Banner stays hidden after reload because localStorage persisted.
    // The dashboard count cards still render to confirm the page loaded.
    await expect(page.getByTestId('card-open-proposals')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId('demo-data-banner')).toBeHidden();
  });

  test('pre-set localStorage hides the banner from initial render (AC-6)', async ({
    page,
    context,
  }) => {
    await context.addInitScript(() => {
      window.localStorage.setItem('relyloop.home-first-run-demo-nudge.dismissed', '1');
    });
    await page.goto('/');
    // Wait for the dashboard to load so we know the banner had a chance to render.
    await expect(page.getByTestId('card-open-proposals')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId('demo-data-banner')).toBeHidden();
  });
});
