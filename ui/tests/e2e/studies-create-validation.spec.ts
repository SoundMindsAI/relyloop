/**
 * E2E spec: create-study modal Step-4 auto-fill + client-side validation.
 *
 * Real-backend; no `page.route()` mocking. Walks Steps 1–3 of the wizard,
 * asserts that:
 *   1. Step-4 textarea is pre-filled with `buildStarterSearchSpace` output
 *      derived from the seeded template's `declared_params` (FR-1 / AC-1).
 *   2. Corrupting the auto-fill with a typo surfaces an inline alert with
 *      the spec's exact unknown-param error format (FR-2 / AC-4) and
 *      blocks the Step-4 → Step-5 transition.
 *
 * The server-side rejection envelope is exercised by the backend contract
 * test at `backend/tests/contract/test_studies_error_codes.py` (Story 1.1).
 * The client-side mirror's message format matches what the server returns,
 * so the inline-error assertion below doubles as a parity check on the
 * cross-layer message text.
 */
import { expect, test } from '@playwright/test';

import { seedFullChain } from './helpers/seed';

const API_BASE = process.env.PLAYWRIGHT_API_BASE_URL ?? 'http://127.0.0.1:8000';

async function getName(path: string): Promise<string> {
  const resp = await fetch(`${API_BASE}${path}`);
  if (!resp.ok) throw new Error(`GET ${path} failed: ${resp.status}`);
  const body = (await resp.json()) as { name: string };
  return body.name;
}

test.describe('/studies — create-study Step-4 client-side validation', () => {
  test('Step 4 auto-fills + inline unknown-param error blocks Step 5', async ({ page }) => {
    // Seed cluster + query-set + template (declared_params: { boost: 'float' })
    // + judgment list. `query_text` is referenced in the Jinja template body
    // but is not a search-space param — render() injects it from the query
    // set at trial time.
    const chain = await seedFullChain(2);
    // FullChainSeed exposes IDs only for query-set / judgment-list — fetch
    // their names so we can click the right option in the Radix popups.
    const querySetName = await getName(`/api/v1/query-sets/${chain.querySetId}`);
    const judgmentListName = await getName(`/api/v1/judgment-lists/${chain.judgmentListId}`);

    await page.goto('/studies');
    await page.getByTestId('open-create-study').click();
    await expect(page.getByTestId('create-study-form')).toBeVisible({ timeout: 5_000 });

    // Step 1 — pick the seeded cluster + a target index name.
    await page.getByTestId('cs-cluster').click();
    await page
      .getByRole('option', { name: new RegExp(chain.clusterName) })
      .first()
      .click();
    await page.getByLabel('Target index / collection').fill('e2e-target');
    await page.getByTestId('step-next').click();

    // Step 2 — pick the seeded query set + judgment list.
    await page.getByTestId('cs-qs').click();
    await page
      .getByRole('option', { name: new RegExp(querySetName) })
      .first()
      .click();
    await page.getByTestId('cs-jl').click();
    await page
      .getByRole('option', { name: new RegExp(judgmentListName) })
      .first()
      .click();
    await page.getByTestId('step-next').click();

    // Step 3 — pick the seeded template.
    await page.getByTestId('cs-tpl').click();
    await page
      .getByRole('option', { name: new RegExp(chain.templateName) })
      .first()
      .click();
    await page.getByTestId('step-next').click();

    // Step 4 — auto-fill has landed.
    await expect(page.getByTestId('step-4')).toBeVisible({ timeout: 5_000 });
    const textarea = page.getByTestId('cs-search-space');
    // Wait for the template fetch + auto-fill effect to populate the textarea.
    await expect(async () => {
      const v = await textarea.inputValue();
      expect(v.length).toBeGreaterThan(2);
      // The seedTemplate fixture's declared_params is { boost: 'float' } —
      // 'boost' (no underscore) falls through the heuristic to the simple-form
      // 'float' default → uniform [0.0, 1.0].
      expect(v).toContain('boost');
    }).toPass({ timeout: 5_000 });

    // Fill the required Study name.
    await page.getByLabel('Study name').fill(`e2e-validation-${Date.now()}`);

    // Corrupt the textarea with a typo: rename 'boost' → 'boos' (unknown param).
    const current = await textarea.inputValue();
    const corrupted = current.replace('"boost"', '"boos"');
    await textarea.fill(corrupted);

    // Click Next — the client-side validator must surface an inline error and
    // block the transition.
    await page.getByTestId('step-next').click();
    const err = page.getByTestId('cs-search-space-error');
    await expect(err).toBeVisible({ timeout: 2_000 });
    await expect(err).toContainText("Param 'boos' is not declared");
    // Verify Step-4 → Step-5 did NOT advance.
    await expect(page.getByTestId('step-5')).not.toBeVisible();
  });
});
