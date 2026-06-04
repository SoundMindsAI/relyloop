// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * E2E spec: feat_study_wizard_inline_judgment_generation.
 *
 * Real-backend; no `page.route()` mocking. Verifies the Create-Study wizard's
 * inline judgment-generation affordance so a query set with no judgment list no
 * longer dead-ends study creation:
 *   - AC-1: when the judgment-list dropdown is empty, a "Generate judgments for
 *     this query set" button is shown and opens <GenerateJudgmentsDialog>.
 *   - AC-2: the dialog's target field is pre-filled from the wizard's target
 *     and is read-only (locked).
 *   - AC-3 + continuation: once a matching judgment list exists, closing the
 *     dialog refetches the dropdown; the new list is selectable and Step-1
 *     "Next" advances.
 *
 * The real generation worker (LLM/UBI) is NOT driven here — that path is
 * exercised by the demo reseed + the component/hook tests. Instead we seed a
 * matching judgment list via the API to simulate generation completing, which
 * keeps the spec deterministic (no LLM dependency) while still exercising the
 * wizard's refetch-and-continue browser behavior.
 *
 * EntitySelect stability: mirrors studies-create-validation.spec.ts — gate
 * each trigger on `.toBeEnabled()` then `dispatchEvent('click')` to bypass
 * Playwright's over-eager actionability heuristic on the modal's chained
 * TanStack queries.
 */
import { type Locator, type Page, expect, test } from '@playwright/test';

import { seedQuerySet, seedJudgmentList } from './helpers/seed';

const API_BASE = process.env.PLAYWRIGHT_API_BASE_URL ?? 'http://127.0.0.1:8000';
const ENTITY_SELECT_TIMEOUT = 10_000;

async function getName(path: string): Promise<string> {
  const resp = await fetch(new URL(path, API_BASE).toString());
  if (!resp.ok) throw new Error(`GET ${path} failed: ${resp.status}`);
  const body = (await resp.json()) as { name: string };
  return body.name;
}

async function pickEntity(
  page: Page,
  triggerTestId: string,
  optionName: string | RegExp,
): Promise<void> {
  const trigger: Locator = page.getByTestId(triggerTestId);
  await expect(trigger).toBeEnabled({ timeout: ENTITY_SELECT_TIMEOUT });
  await trigger.dispatchEvent('click');
  await page.getByRole('option', { name: optionName }).first().click();
}

test.describe('/studies — inline judgment generation in the wizard', () => {
  test('empty judgment list → generate inline → list appears → select → Next', async ({ page }) => {
    // Seed a cluster + query set with NO judgment list (default opts).
    const { clusterId, querySetId, queryIds } = await seedQuerySet(2);
    const clusterName = await getName(`/api/v1/clusters/${clusterId}`);
    const querySetName = await getName(`/api/v1/query-sets/${querySetId}`);

    await page.goto('/studies');
    await page.getByTestId('open-create-study').click();
    await expect(page.getByTestId('create-study-form')).toBeVisible({ timeout: 5_000 });

    // Step 1 — cluster + manual target 'products'.
    await pickEntity(page, 'cs-cluster', clusterName);
    await page.getByRole('button', { name: 'Enter manually' }).click();
    await page.getByLabel('Target index / collection').fill('products');
    await page.getByTestId('step-next').click();

    // Step 2 — pick the query set; its judgment-list dropdown is empty.
    await expect(page.getByTestId('step-2')).toBeVisible({ timeout: 5_000 });
    await pickEntity(page, 'cs-qs', querySetName);

    // AC-1: the inline generate button is present.
    const genBtn = page.getByTestId('cs-generate-judgments');
    await expect(genBtn).toBeVisible({ timeout: ENTITY_SELECT_TIMEOUT });

    // AC-2: opening the dialog pre-fills + locks the target.
    await genBtn.dispatchEvent('click');
    await expect(page.getByTestId('generate-form')).toBeVisible({ timeout: 5_000 });
    const genTarget = page.getByTestId('gen-target');
    await expect(genTarget).toHaveValue('products');
    await expect(genTarget).toHaveAttribute('readonly', '');
    // Close the dialog (simulating "I dispatched / I'll wait").
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('generate-form')).not.toBeVisible({ timeout: 5_000 });

    // Simulate generation completing: import a matching (cluster, query-set,
    // target) judgment list via the API. Import lands a `complete` list.
    const jl = await seedJudgmentList({ clusterId, querySetId, queryIds, target: 'products' });
    const judgmentListName = await getName(`/api/v1/judgment-lists/${jl.id}`);

    // AC-3: re-open + close the dialog to trigger the on-close invalidation,
    // so the dropdown refetches and surfaces the now-existing list.
    await genBtn.dispatchEvent('click');
    await expect(page.getByTestId('generate-form')).toBeVisible({ timeout: 5_000 });
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('generate-form')).not.toBeVisible({ timeout: 5_000 });

    // The new list is now selectable; pick it and advance.
    await pickEntity(page, 'cs-jl', judgmentListName);
    await page.getByTestId('step-next').click();
    // Next advanced to Step 3 (template) — the wizard is no longer dead-ended.
    await expect(page.getByTestId('step-3')).toBeVisible({ timeout: 5_000 });
  });
});
