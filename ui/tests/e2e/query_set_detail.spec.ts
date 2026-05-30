// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * E2E spec: /query-sets/[id] per-query CRUD (feat_query_inline_crud).
 *
 * First Playwright spec in the repo — exercises the full operator path
 * against the real backend at 127.0.0.1:8000 + ui at 127.0.0.1:3000.
 *
 * Five paths covered, mirroring chore_query_inline_crud_e2e/idea.md:
 *  1. List loads with seeded rows + total-count indicator.
 *  2. Inline-edit query_text via the Edit popover; row updates in place.
 *  3. Metadata clear via the Metadata dialog; indicator flips to "—".
 *  4. Delete a no-judgments query → 204 → row removed + total-count decrements.
 *  5. Delete a query with judgments → 409 toast with action link to
 *     /judgments/{first_id}; row stays in the table.
 */
import { expect, test } from '@playwright/test';

import { seedQuerySet } from './helpers/seed';

test.describe('/query-sets/[id] per-query CRUD', () => {
  test('lists rows + total-count indicator', async ({ page }) => {
    const { querySetId } = await seedQuerySet(3);

    await page.goto(`/query-sets/${querySetId}`);
    await expect(page.getByTestId('queries-table')).toBeVisible();
    await expect(page.getByTestId('data-table-total-count')).toContainText('3');
    await expect(page.getByText('e2e query 0')).toBeVisible();
    await expect(page.getByText('e2e query 1')).toBeVisible();
    await expect(page.getByText('e2e query 2')).toBeVisible();
  });

  test('inline edit: popover updates query_text in place', async ({ page }) => {
    const { querySetId, queryIds } = await seedQuerySet(2);
    const q1 = queryIds[1];

    await page.goto(`/query-sets/${querySetId}`);
    await page.getByTestId(`edit-${q1}`).click();
    await expect(page.getByTestId('edit-query-text')).toBeVisible();

    await page.getByTestId('edit-query-text').fill('edited via e2e');
    await page.getByTestId('edit-query-save').click();

    await expect(page.getByText('edited via e2e')).toBeVisible();
    await expect(page.getByText('e2e query 1')).toHaveCount(0);
  });

  test('metadata clear: dialog Clear button → indicator becomes "—"', async ({ page }) => {
    const { querySetId, queryIds } = await seedQuerySet(2);
    const q0 = queryIds[0]; // seeded with query_metadata={"intent":"test"}

    await page.goto(`/query-sets/${querySetId}`);
    await expect(page.getByTestId(`meta-badge-${q0}`)).toContainText('Set');

    // Open via the badge (also reachable via the row's Metadata icon-button).
    await page.getByTestId(`meta-badge-${q0}`).click();
    await expect(page.getByTestId('edit-metadata-textarea')).toBeVisible();

    await page.getByTestId('clear-metadata-button').click();
    await expect(page.getByTestId(`meta-badge-${q0}`)).toContainText('—');
  });

  test('delete (no judgments): 204 → row removed + total drops', async ({ page }) => {
    const { querySetId, queryIds } = await seedQuerySet(3);
    const q1 = queryIds[1];

    await page.goto(`/query-sets/${querySetId}`);
    await expect(page.getByTestId('data-table-total-count')).toContainText('3');

    await page.getByTestId(`delete-${q1}`).click();
    await expect(page.getByTestId('confirm-delete-query')).toBeVisible();
    await page.getByTestId('confirm-delete-query').click();

    await expect(page.getByText('e2e query 1')).toHaveCount(0);
    await expect(page.getByTestId('data-table-total-count')).toContainText('2');
  });

  test('delete (with judgments): 409 toast with action link, row stays', async ({ page }) => {
    const { querySetId, queryIds, judgmentListId } = await seedQuerySet(2, {
      withJudgmentList: true,
    });
    const q0 = queryIds[0]; // has 1 judgment from the seeded list

    await page.goto(`/query-sets/${querySetId}`);
    await page.getByTestId(`delete-${q0}`).click();
    await expect(page.getByTestId('confirm-delete-query')).toBeVisible();
    await page.getByTestId('confirm-delete-query').click();

    // The destructive toast appears with the action link.
    const toastText = page.getByText(/1 judgment list reference this query/i);
    await expect(toastText).toBeVisible({ timeout: 5000 });

    // Sanity-check the action link target (visible label).
    const actionLink = page.getByText(/Open e2e-jl-\w+ →/);
    await expect(actionLink).toBeVisible();

    // Close the AlertDialog first — it stays open on 409 by design (the
    // operator can re-read the toast). Press Escape so the action link is
    // clickable (otherwise the dialog overlay intercepts pointer events).
    await page.keyboard.press('Escape');

    // Row should still be visible — DELETE was rejected by FK guard.
    await expect(page.getByText('e2e query 0')).toBeVisible();

    // Click-through — verify the action navigates correctly.
    await actionLink.click();
    await expect(page).toHaveURL(new RegExp(`/judgments/${judgmentListId}$`));
  });
});
