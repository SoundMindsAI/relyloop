/**
 * E2E spec: /guide/glossary route (chore_guides_glossary_route).
 *
 * Real-backend test — there is no backend surface for this route (it renders
 * a TypeScript constant), so we exercise the page against `localhost:3000`
 * and assert browser-visible behavior:
 *
 *   1. The page renders with search input + category chips + entry list.
 *   2. Typing in the search box filters the entries.
 *   3. Clicking a category chip filters to that prefix.
 *   4. Deep-link fragment scrolls the anchored entry into view.
 *   5. The catalog page at /guide exposes the new glossary card.
 *
 * No `page.route()` mocking — the page makes zero network calls.
 */
import { expect, test } from '@playwright/test';

test.describe('/guide/glossary route', () => {
  test('renders search input, category chips, and the grouped entry list by default', async ({
    page,
  }) => {
    await page.goto('/guide/glossary');
    await expect(page.getByRole('heading', { name: 'Glossary', level: 1 })).toBeVisible();
    await expect(page.getByTestId('glossary-search')).toBeVisible();
    await expect(page.getByTestId('glossary-category-chips')).toBeVisible();
    await expect(page.getByTestId('glossary-grouped-list')).toBeVisible();
  });

  test('search filters entries to substring matches and switches to flat list', async ({
    page,
  }) => {
    await page.goto('/guide/glossary');
    await page.getByTestId('glossary-search').fill('ndcg');
    await expect(page.getByTestId('glossary-flat-list')).toBeVisible();
    await expect(page.getByTestId('glossary-entry-study.metric.ndcg')).toBeVisible();
    // Unrelated entry no longer in DOM
    await expect(page.getByTestId('glossary-entry-cluster.engine')).toHaveCount(0);
  });

  test('category chip filters to that prefix only', async ({ page }) => {
    await page.goto('/guide/glossary');
    await page.getByTestId('glossary-chip-confidence').click();
    await expect(page.getByTestId('glossary-chip-confidence')).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    await expect(page.getByTestId('glossary-entry-confidence.ci_95')).toBeVisible();
    await expect(page.getByTestId('glossary-entry-study.metric')).toHaveCount(0);
  });

  test('deep-link fragment scrolls the anchored entry into view', async ({ page }) => {
    await page.goto('/guide/glossary#study.metric.ndcg');
    // CSS-selector escaping for the dotted ID
    const target = page.locator('#study\\.metric\\.ndcg');
    await expect(target).toBeVisible();
    await expect(target).toBeInViewport();
  });

  test('empty search yields the empty state', async ({ page }) => {
    await page.goto('/guide/glossary');
    await page.getByTestId('glossary-search').fill('zzz-no-match-xyz');
    await expect(page.getByTestId('glossary-empty')).toBeVisible();
    await expect(page.getByTestId('glossary-empty')).toContainText('No terms match.');
  });
});

test.describe('/guide catalog (reference section — glossary + FAQ)', () => {
  test('exposes the glossary catalog card linking to /guide/glossary', async ({ page }) => {
    await page.goto('/guide');
    const section = page.getByTestId('reference-section');
    await expect(section).toBeVisible();
    const card = page.getByTestId('glossary-card');
    await expect(card).toBeVisible();
    await expect(card).toHaveAttribute('href', '/guide/glossary');
    // Dynamic count rendering
    await expect(card).toContainText(/\d+ terms/);
  });

  test('clicking the glossary card navigates to /guide/glossary', async ({ page }) => {
    await page.goto('/guide');
    await page.getByTestId('glossary-card').click();
    await expect(page).toHaveURL(/\/guide\/glossary$/);
    await expect(page.getByRole('heading', { name: 'Glossary', level: 1 })).toBeVisible();
  });
});
