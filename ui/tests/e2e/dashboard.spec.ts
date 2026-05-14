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
