// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * E2E spec: typed normalizer-pipeline create-study flow
 * (feat_query_normalizer_typed_pipeline Story 3.2 / AC-11).
 *
 * Real-backend; no `page.route()` mocking. Setup via API helpers (allowed per
 * the E2E rules); all assertions verify browser-visible behavior + the
 * persisted study.
 *
 * Scope (mirrors the sibling `query-normalization.spec.ts` decision): the
 * UI-observable surface is the create-study wizard's `query_normalizer` row
 * switched to the typed-pipeline type. Engine-boundary application (I-5), the
 * PR-body bilingual snippet (FR-4/FR-5), and the digest advisory (AC-13) are
 * covered at their own layers (integration / backend unit / vitest) — this
 * spec proves the wizard renders the pipeline row, lets the operator pick
 * steps with a live `2^N` cardinality preview, and persists the
 * `{type:"normalizer_pipeline", steps:[...]}` param through POST /studies.
 */
import { type Locator, type Page, expect, test } from '@playwright/test';

import { seedFullChain } from './helpers/seed';

const API_BASE = process.env.PLAYWRIGHT_API_BASE_URL ?? 'http://127.0.0.1:8000';
const ENTITY_SELECT_TIMEOUT = 10_000;
const TARGET = 'e2e-normalizer-pipeline-target';

async function getName(path: string): Promise<string> {
  const resp = await fetch(new URL(path, API_BASE).toString());
  if (!resp.ok) throw new Error(`GET ${path} failed: ${resp.status}`);
  const body = (await resp.json()) as { name: string };
  return body.name;
}

async function seedNormalizerTemplate(): Promise<string> {
  const name = `e2e-pipeline-tpl-${Date.now()}`;
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

  await pickEntity(page, 'cs-tpl', templateName);
  await page.getByTestId('step-next').click();

  await expect(page.getByTestId('step-4')).toBeVisible({ timeout: 5_000 });
  await expect(page.getByTestId('cs-search-space-builder')).toBeVisible();
  await expect(page.getByTestId('cs-param-row-query_normalizer')).toBeVisible({ timeout: 5_000 });
}

async function readSearchSpace(page: Page): Promise<{ params: Record<string, unknown> }> {
  const raw = await page.getByTestId('cs-search-space').inputValue();
  return JSON.parse(raw);
}

test.describe('/studies — typed normalizer-pipeline row (Story 3.2 / AC-11)', () => {
  test('switch to pipeline, pick steps, persist the powerset param', async ({ page }) => {
    const templateName = await seedNormalizerTemplate();
    await walkToStep4(page, templateName);

    // Switch the reserved row's type to the typed pipeline via RowTypeSelector
    // (Radix Select rendered as a combobox button).
    const typeTrigger = page.getByTestId('cs-row-query_normalizer-type');
    await expect(typeTrigger).toBeEnabled({ timeout: ENTITY_SELECT_TIMEOUT });
    await typeTrigger.dispatchEvent('click');
    await page.getByRole('option', { name: 'normalizer_pipeline', exact: true }).click();

    // The empty pipeline row is flagged incomplete until a step is picked.
    await expect(page.getByTestId('cs-row-error-query_normalizer-steps')).toBeVisible();

    // Pick lowercase + trim (browser-visible checkbox interactions).
    await page.getByTestId('cs-row-query_normalizer-step-lowercase-checkbox').check();
    await page.getByTestId('cs-row-query_normalizer-step-trim-checkbox').check();

    // The incomplete helper clears, and the live cardinality preview reads 4 (=2²).
    await expect(page.getByTestId('cs-row-error-query_normalizer-steps')).toHaveCount(0);
    await expect(page.getByTestId('cs-row-query_normalizer-cardinality')).toContainText('4 states');

    // The textarea reflects the typed-pipeline spec, steps in STEP_ORDER.
    await expect(async () => {
      const parsed = await readSearchSpace(page);
      expect(parsed.params.query_normalizer).toEqual({
        type: 'normalizer_pipeline',
        steps: ['lowercase', 'trim'],
      });
    }).toPass({ timeout: 2_000 });

    // Submit and assert the persisted study carries the pipeline param.
    const studyName = `e2e-pipeline-${Date.now()}`;
    await page.getByLabel('Study name').fill(studyName);
    await page.getByTestId('step-next').click();
    await expect(page.getByTestId('step-5')).toBeVisible({ timeout: 5_000 });
    await page.getByRole('spinbutton', { name: 'Max trials' }).fill('10');
    await page.getByTestId('create-study-submit').click();
    await expect(page.getByTestId('create-study-form')).not.toBeVisible({ timeout: 5_000 });

    const list = await (
      await fetch(new URL('/api/v1/studies?limit=20', API_BASE).toString())
    ).json();
    const created = (list.data as Array<{ id: string; name: string }>).find(
      (s) => s.name === studyName,
    );
    expect(created, `study ${studyName} not in /api/v1/studies?limit=20`).toBeDefined();
    const detail = await (
      await fetch(new URL(`/api/v1/studies/${created!.id}`, API_BASE).toString())
    ).json();
    expect(detail.search_space.params.query_normalizer).toEqual({
      type: 'normalizer_pipeline',
      steps: ['lowercase', 'trim'],
    });
  });
});
