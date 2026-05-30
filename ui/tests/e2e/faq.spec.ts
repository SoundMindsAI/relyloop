// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * E2E spec: /guide/faq route (chore_guides_faq).
 *
 * Real-backend test against `localhost:3000`. The page makes no network
 * calls; it renders the in-memory `ui/src/lib/faq.ts` constant.
 */
import { expect, test } from '@playwright/test';

test.describe('/guide/faq route', () => {
  test('renders the heading, search input, category chips, and grouped list', async ({ page }) => {
    await page.goto('/guide/faq');
    await expect(
      page.getByRole('heading', { name: /Frequently asked questions/i, level: 1 }),
    ).toBeVisible();
    await expect(page.getByTestId('faq-search')).toBeVisible();
    await expect(page.getByTestId('faq-category-chips')).toBeVisible();
    await expect(page.getByTestId('faq-grouped-list')).toBeVisible();
  });

  test('search filters entries and switches to flat list', async ({ page }) => {
    await page.goto('/guide/faq');
    await page.getByTestId('faq-search').fill('kappa');
    await expect(page.getByTestId('faq-flat-list')).toBeVisible();
    await expect(page.getByTestId('faq-entry-kappa-trust-threshold')).toBeVisible();
  });

  test('category chip filters to that category only', async ({ page }) => {
    await page.goto('/guide/faq');
    await page.getByTestId('faq-chip-judgments').click();
    await expect(page.getByTestId('faq-chip-judgments')).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByTestId('faq-entry-kappa-trust-threshold')).toBeVisible();
    // A studies-and-confidence entry should not be present
    await expect(page.getByTestId('faq-entry-convergence-noisy')).toHaveCount(0);
  });

  test('deep-link fragment scrolls the anchored entry into view', async ({ page }) => {
    await page.goto('/guide/faq#confidence-ci-missing');
    const target = page.locator('#confidence-ci-missing');
    await expect(target).toBeVisible();
    await expect(target).toBeInViewport();
  });
});

test.describe('/guide catalog (FAQ section)', () => {
  test('exposes the FAQ catalog card linking to /guide/faq', async ({ page }) => {
    await page.goto('/guide');
    const card = page.getByTestId('faq-card');
    await expect(card).toBeVisible();
    await expect(card).toHaveAttribute('href', '/guide/faq');
    await expect(card).toContainText(/\d+ questions/);
  });

  test('clicking the FAQ card navigates to /guide/faq', async ({ page }) => {
    await page.goto('/guide');
    await page.getByTestId('faq-card').click();
    await expect(page).toHaveURL(/\/guide\/faq$/);
    await expect(
      page.getByRole('heading', { name: /Frequently asked questions/i, level: 1 }),
    ).toBeVisible();
  });
});
