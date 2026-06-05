// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * E2E spec: query-normalizer create-study flow (feat_query_normalization_tuning
 * Story 6.1 / AC-13).
 *
 * Real-backend; no `page.route()` mocking. Setup via API helpers (per the
 * E2E rules — setup is allowed via `fetch`); all assertions verify
 * browser-visible behavior + the persisted study.
 *
 * Scope (per AC-13's own note): the UI-observable surface is the create-study
 * wizard's constrained `query_normalizer` row. Engine-boundary normalization
 * correctness (AC-3 / AC-4), the I-2 invariant (the trial-runner integration
 * test), the digest advisory (AC-8/9/10 vitest), and the PR-body section
 * (AC-5/6/7 backend unit) are covered at their own layers — this spec proves
 * the wizard auto-fills the reserved row, renders the constrained Select, and
 * persists the chosen value through `POST /api/v1/studies`.
 *
 * Stability note: mirrors the EntitySelect-click + walk pattern from
 * `studies-create-builder.spec.ts`.
 */
import { type Locator, type Page, expect, test } from '@playwright/test';

import { seedFullChain } from './helpers/seed';

const API_BASE = process.env.PLAYWRIGHT_API_BASE_URL ?? 'http://127.0.0.1:8000';
const ENTITY_SELECT_TIMEOUT = 10_000;
const TARGET = 'e2e-normalizer-target';

async function getName(path: string): Promise<string> {
  const resp = await fetch(new URL(path, API_BASE).toString());
  if (!resp.ok) throw new Error(`GET ${path} failed: ${resp.status}`);
  const body = (await resp.json()) as { name: string };
  return body.name;
}

/** Create a normalizer-aware template that declares ONLY query_normalizer and
 * references {{ query_text }} (NOT {{ query_normalizer }} — that would be
 * RESERVED_PARAM_REFERENCED). Returns its name for the wizard picker. */
async function seedNormalizerTemplate(): Promise<string> {
  const name = `e2e-normalizer-tpl-${Date.now()}`;
  const resp = await fetch(new URL('/api/v1/query-templates', API_BASE).toString(), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name,
      engine_type: 'elasticsearch',
      body: '{ "query": { "match": { "title": "{{ query_text }}" } } }',
      declared_params: { query_normalizer: 'string' },
    }),
  });
  if (!resp.ok)
    throw new Error(`seed normalizer template failed: ${resp.status} ${await resp.text()}`);
  return name;
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

/** Walk the create-study wizard to Step 4 with the normalizer template
 * selected, against a freshly seeded chain. */
async function walkToStep4(page: Page, templateName: string): Promise<void> {
  const chain = await seedFullChain(2, { judgmentListTarget: TARGET });
  const querySetName = await getName(`/api/v1/query-sets/${chain.querySetId}`);
  const judgmentListName = await getName(`/api/v1/judgment-lists/${chain.judgmentListId}`);

  await page.goto('/studies');
  await page.getByTestId('open-create-study').click();
  await expect(page.getByTestId('create-study-form')).toBeVisible({ timeout: 5_000 });

  await pickEntity(page, 'cs-cluster', chain.clusterName);
  await page.getByRole('button', { name: 'Enter manually' }).click();
  await page.getByLabel('Target index / collection').fill(TARGET);
  await page.getByTestId('step-next').click();

  await pickEntity(page, 'cs-qs', querySetName);
  await pickEntity(page, 'cs-jl', judgmentListName);
  await page.getByTestId('step-next').click();

  // Pick the normalizer-aware template (not the seedFullChain default).
  await pickEntity(page, 'cs-tpl', templateName);
  await page.getByTestId('step-next').click();

  await expect(page.getByTestId('step-4')).toBeVisible({ timeout: 5_000 });
  await expect(page.getByTestId('cs-search-space-builder')).toBeVisible();
  // The reserved row auto-fills to a Categorical over the four normalizers.
  await expect(page.getByTestId('cs-param-row-query_normalizer')).toBeVisible({ timeout: 5_000 });
}

async function readSearchSpace(page: Page): Promise<{ params: Record<string, unknown> }> {
  const raw = await page.getByTestId('cs-search-space').inputValue();
  return JSON.parse(raw);
}

async function submitStep5(page: Page, studyName: string): Promise<void> {
  await page.getByLabel('Study name').fill(studyName);
  await page.getByTestId('step-next').click();
  await expect(page.getByTestId('step-5')).toBeVisible({ timeout: 5_000 });
  await page.getByRole('spinbutton', { name: 'Max trials' }).fill('10');
  await page.getByTestId('create-study-submit').click();
  await expect(page.getByTestId('create-study-form')).not.toBeVisible({ timeout: 5_000 });
}

async function fetchStudyByName(
  studyName: string,
): Promise<{ id: string; search_space: { params: Record<string, { choices?: unknown[] }> } }> {
  const list = await (await fetch(new URL('/api/v1/studies?limit=20', API_BASE).toString())).json();
  const created = (list.data as Array<{ id: string; name: string }>).find(
    (s) => s.name === studyName,
  );
  expect(created, `study ${studyName} not in /api/v1/studies?limit=20`).toBeDefined();
  return (await fetch(new URL(`/api/v1/studies/${created!.id}`, API_BASE).toString())).json();
}

test.describe('/studies — create-study query_normalizer row (Story 6.1 / AC-13)', () => {
  test('auto-fills the four normalizer choices and persists the default subset', async ({
    page,
  }) => {
    const templateName = await seedNormalizerTemplate();
    await walkToStep4(page, templateName);

    // The constrained Select renders (the new reserved-key row), not the chip input.
    await expect(page.getByTestId('cs-row-query_normalizer-select')).toBeVisible();
    await expect(page.getByTestId('cs-row-query_normalizer-choices-input')).toHaveCount(0);

    // Untouched, the search space carries all four normalizer choices so the
    // loop searches over them.
    const parsed = await readSearchSpace(page);
    const qn = parsed.params.query_normalizer as { type: string; choices: string[] };
    expect(qn.type).toBe('categorical');
    expect(qn.choices).toEqual([
      'none',
      'lowercase',
      'lowercase+trim',
      'lowercase+trim+expand_contractions',
    ]);

    const studyName = `e2e-normalizer-default-${Date.now()}`;
    await submitStep5(page, studyName);

    const detail = await fetchStudyByName(studyName);
    expect(detail.search_space.params.query_normalizer?.choices).toEqual([
      'none',
      'lowercase',
      'lowercase+trim',
      'lowercase+trim+expand_contractions',
    ]);
  });

  test('picking a normalizer pins the search space to that single choice', async ({ page }) => {
    const templateName = await seedNormalizerTemplate();
    await walkToStep4(page, templateName);

    // Open the Radix Select and pick the lowercase+trim option by its
    // glossary-sourced label.
    const trigger = page.getByTestId('cs-row-query_normalizer-select');
    await trigger.click();
    await page.getByRole('option', { name: 'Lowercase + trim whitespace', exact: true }).click();

    await expect(async () => {
      const parsed = await readSearchSpace(page);
      const qn = parsed.params.query_normalizer as { choices: string[] };
      expect(qn.choices).toEqual(['lowercase+trim']);
    }).toPass({ timeout: 2_000 });

    const studyName = `e2e-normalizer-pinned-${Date.now()}`;
    await submitStep5(page, studyName);

    const detail = await fetchStudyByName(studyName);
    expect(detail.search_space.params.query_normalizer?.choices).toEqual(['lowercase+trim']);
  });
});
