/**
 * E2E spec: SearchSpaceBuilder (`feat_create_study_search_space_builder` Story 4.1).
 *
 * Real-backend; no `page.route()` mocking. Walks Steps 1–4 of the
 * create-study wizard, uses the visual builder to edit `boost.high` from
 * the auto-filled default to 15, submits, and asserts the created
 * study's `search_space.params.boost.high === 15` via `GET /api/v1/studies/{id}`.
 *
 * Asserts both:
 *   (a) the builder's numeric input + onBlur flush propagates the edit to
 *       the textarea (cs-search-space) synchronously
 *   (b) the submitted study persists the edited value end-to-end.
 *
 * Stability note: mirrors the EntitySelect-click pattern from
 * `studies-create-validation.spec.ts` (toBeEnabled + dispatchEvent click).
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
  await expect(trigger).toBeEnabled({ timeout: ENTITY_SELECT_TIMEOUT });
  await trigger.dispatchEvent('click');
  await page.getByRole('option', { name: optionName }).first().click();
}

test.describe('/studies — create-study Step-4 builder (Story 4.1)', () => {
  test('builder edits propagate to textarea + submitted study persists the value', async ({
    page,
  }) => {
    const chain = await seedFullChain(2);
    const querySetName = await getName(`/api/v1/query-sets/${chain.querySetId}`);
    const judgmentListName = await getName(`/api/v1/judgment-lists/${chain.judgmentListId}`);

    await page.goto('/studies');
    await page.getByTestId('open-create-study').click();
    await expect(page.getByTestId('create-study-form')).toBeVisible({ timeout: 5_000 });

    // Steps 1–3.
    await pickEntity(page, 'cs-cluster', chain.clusterName);
    await page.getByLabel('Target index / collection').fill('e2e-builder-target');
    await page.getByTestId('step-next').click();

    await pickEntity(page, 'cs-qs', querySetName);
    await pickEntity(page, 'cs-jl', judgmentListName);
    await page.getByTestId('step-next').click();

    await pickEntity(page, 'cs-tpl', chain.templateName);
    await page.getByTestId('step-next').click();

    // Step 4 — builder + auto-filled textarea visible.
    await expect(page.getByTestId('step-4')).toBeVisible({ timeout: 5_000 });
    await expect(page.getByTestId('cs-search-space-builder')).toBeVisible();

    // Wait for the auto-fill effect + canonicalize-on-mount to land.
    const boostRow = page.getByTestId('cs-param-row-boost');
    await expect(boostRow).toBeVisible({ timeout: 5_000 });

    const studyName = `e2e-builder-${Date.now()}`;
    await page.getByLabel('Study name').fill(studyName);

    // Edit `high` from the auto-filled default (10) to 15 via the builder's
    // numeric input. Blur to flush synchronously.
    const highInput = page.getByTestId('cs-row-boost-high');
    await highInput.fill('15');
    await highInput.blur();

    // Assert the textarea reflects the builder edit.
    const textarea = page.getByTestId('cs-search-space');
    await expect(async () => {
      const v = await textarea.inputValue();
      expect(JSON.parse(v).params.boost.high).toBe(15);
    }).toPass({ timeout: 2_000 });

    // Step 4 → Step 5.
    await page.getByTestId('step-next').click();
    await expect(page.getByTestId('step-5')).toBeVisible({ timeout: 5_000 });

    // Step 5: stepValid(4, ...) requires max_trials > 0 OR time_budget_min > 0
    // (see create-study-modal.tsx stepValid case 4). The form's defaultValues
    // don't seed either, so the submit button stays disabled until we fill one.
    await page.getByLabel('Max trials').fill('10');

    // Submit.
    await page.getByTestId('create-study-submit').click();

    // The submitted study should show up; wait for the modal to close.
    await expect(page.getByTestId('create-study-form')).not.toBeVisible({ timeout: 5_000 });

    // Fetch the created study by name (the StudiesPage list shows it).
    const studies = await (await fetch(`${API_BASE}/api/v1/studies?limit=10`)).json();
    const created = (studies.data as Array<{ id: string; name: string }>).find(
      (s) => s.name === studyName,
    );
    expect(created, `study ${studyName} not in /api/v1/studies?limit=10`).toBeDefined();
    const detail = await (await fetch(`${API_BASE}/api/v1/studies/${created!.id}`)).json();
    expect(detail.search_space.params.boost.high).toBe(15);
  });
});
