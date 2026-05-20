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
 * test at `backend/tests/contract/test_studies_error_codes.py`. The client-
 * side mirror's message format matches what the server returns, so the
 * inline-error assertion below doubles as a parity check on cross-layer
 * message text consistency.
 *
 * Stability note (chore_create_study_modal_e2e_stability): the create-study
 * modal opens with five chained TanStack queries firing in parallel
 * (`useClusters`, `useClusterSchema`, `useQuerySets`, `useJudgmentLists`,
 * `useTemplates`). The first run of this spec saw the cs-cluster trigger
 * toggle disabled→enabled→disabled fast enough that Playwright's `click`
 * auto-wait never got a clickable + stable window. Fix: gate every
 * `EntitySelect` interaction with an explicit `.toBeEnabled({ timeout })`
 * precondition. That gives the underlying query enough time to settle into
 * a stable enabled state before Playwright commits to the click, without
 * touching the shared `EntitySelect` primitive's `isLoading`-vs-`isFetching`
 * gating.
 */
import { type Locator, type Page, expect, test } from '@playwright/test';

import { seedFullChain } from './helpers/seed';

const API_BASE = process.env.PLAYWRIGHT_API_BASE_URL ?? 'http://127.0.0.1:8000';
const ENTITY_SELECT_TIMEOUT = 10_000;

async function getName(path: string): Promise<string> {
  const resp = await fetch(`${API_BASE}${path}`);
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
  // The first version of this helper used `.click()` which gates on
  // visible+enabled+stable. The cluster trigger fails the stability check
  // (Radix Dialog focus-trap + chained TanStack queries on modal open
  // cause micro-layout shifts on every animation frame; Playwright's
  // `_isStable` heuristic never sees two consecutive frames with an
  // unchanged bounding box, even after 30s). Mirrors the resolution in
  // PR #154 for the `query-set` walkthrough guide: use
  // `dispatchEvent('click')` to fire a synthetic event that bypasses the
  // actionability check entirely. The element IS reachable; only the
  // heuristic is over-eager. The option click is fine — by the time the
  // popover renders, layout has settled.
  await expect(trigger).toBeEnabled({ timeout: ENTITY_SELECT_TIMEOUT });
  await trigger.dispatchEvent('click');
  await page.getByRole('option', { name: optionName }).first().click();
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
    await pickEntity(page, 'cs-cluster', chain.clusterName);
    // feat_create_study_target_autocomplete F2: target field is an EntitySelect
    // by default. Flip into manual mode so the existing fill() path works
    // without this test needing to seed an ES index.
    await page.getByRole('button', { name: 'Enter manually' }).click();
    await page.getByLabel('Target index / collection').fill('e2e-target');
    await page.getByTestId('step-next').click();

    // Step 2 — pick the seeded query set + judgment list.
    await pickEntity(page, 'cs-qs', querySetName);
    await pickEntity(page, 'cs-jl', judgmentListName);
    await page.getByTestId('step-next').click();

    // Step 3 — pick the seeded template.
    await pickEntity(page, 'cs-tpl', chain.templateName);
    await page.getByTestId('step-next').click();

    // Step 4 — auto-fill has landed.
    await expect(page.getByTestId('step-4')).toBeVisible({ timeout: 5_000 });
    const textarea = page.getByTestId('cs-search-space');
    // Wait for the template fetch + auto-fill effect to populate the textarea.
    await expect(async () => {
      const v = await textarea.inputValue();
      expect(v.length).toBeGreaterThan(2);
      // The seedTemplate fixture's declared_params is { boost: 'float' };
      // after PR #159's heuristic extension `boost` matches the
      // `^(boost|.+_boost)$` rule → log-uniform [0.5, 10].
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
