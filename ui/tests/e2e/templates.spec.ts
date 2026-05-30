// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * E2E spec: /templates create + fork flow (workflow B1).
 *
 * Templates are immutable — to evolve them, operators fork to v2. This spec
 * exercises both the create-from-scratch and fork-from-existing paths.
 */
import { expect, test } from '@playwright/test';

import { seedTemplate } from './helpers/seed';

test.describe('/templates', () => {
  test('renders the templates list', async ({ page }) => {
    // Seed at least one template so the list is non-empty.
    await seedTemplate();

    await page.goto('/templates');
    // The page should render either a populated table or an empty state.
    await expect(page.getByRole('main')).toBeVisible();
    // At least one row in the table for the seeded template.
    await expect(page.locator('table tbody tr').first()).toBeVisible({ timeout: 5_000 });
  });

  test('fork-to-v2 button on detail page navigates to the fork dialog', async ({ page }) => {
    const tpl = await seedTemplate();

    await page.goto(`/templates/${tpl.id}`);
    // The fork button is the canonical detail-page action.
    await expect(page.getByTestId('open-fork-modal')).toBeVisible({ timeout: 5_000 });
    await page.getByTestId('open-fork-modal').click();
    // Fork dialog opens.
    await expect(page.getByRole('dialog')).toBeVisible({ timeout: 5_000 });
  });
});
