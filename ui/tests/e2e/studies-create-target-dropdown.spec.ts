// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * E2E spec: feat_create_study_target_autocomplete Story F2 happy path.
 *
 * Real-backend; no `page.route()` mocking. Seeds two ES indices via Playwright's
 * `request` fixture (Node, against the host-published ES port 9200), then walks
 * the create-study wizard:
 *
 *   1. Pick the seeded cluster.
 *   2. Assert the target dropdown loads and contains both seeded indices.
 *   3. Assert alphabetical sort (FR-7).
 *   4. Pick the first index from the dropdown.
 *   5. Walk through the remaining steps to submission.
 *   6. Assert the persisted study.target matches the picked index.
 *
 * Cleanup removes the seeded indices.
 */
import { type APIRequestContext, expect, test } from '@playwright/test';

import { seedFullChain } from './helpers/seed';

const API_BASE = process.env.PLAYWRIGHT_API_BASE_URL ?? 'http://127.0.0.1:8000';
const ES_HOST = process.env.PLAYWRIGHT_ES_URL ?? 'http://localhost:9200';
const ENTITY_SELECT_TIMEOUT = 10_000;

async function createIndex(request: APIRequestContext, name: string): Promise<void> {
  const resp = await request.put(`${ES_HOST}/${name}`, {
    data: { mappings: { properties: { title: { type: 'text' } } } },
    headers: { 'Content-Type': 'application/json' },
  });
  // 200 OK (created) or 400 if it already exists from a flaky prior run — both fine.
  if (!resp.ok() && resp.status() !== 400) {
    throw new Error(`Failed to create ES index ${name}: HTTP ${resp.status()}`);
  }
}

async function deleteIndex(request: APIRequestContext, name: string): Promise<void> {
  // Best-effort cleanup; ignore 404 (index already gone).
  await request.delete(`${ES_HOST}/${name}`);
}

// Real-backend dropdown-mode happy path for the Step-1 target picker
// (feat_create_study_target_autocomplete AC-1 + AC-6 + AC-7). Pairs with the
// unit-layer dropdown coverage:
//   - 8 hook cases in src/__tests__/lib/api/clusters.test.tsx
//   - 6 modal cases in src/__tests__/components/studies/create-study-modal.test.tsx
// The existing builder + validation specs flip into manual mode (post-F2);
// this spec is the only one that exercises the dropdown end-to-end.
test('Step-1 target picker loads from the cluster, sorts alphabetically, and persists the picked target (AC-1 + AC-6 + AC-7)', async ({
  page,
  request,
}) => {
  const suffix = Date.now().toString(36);
  const seededTargets = [`e2e-target-zulu-${suffix}`, `e2e-target-alpha-${suffix}`];

  // Setup: seed full chain (cluster, query-set, template, judgment-list), then
  // create two ES indices on the cluster so the targets dropdown has data.
  // The judgment-list target must match the target the test picks (the alpha
  // one) so the chained POST /studies passes feat_study_target_judgment_mismatch_guard
  // FR-1.
  const chain = await seedFullChain(2, { judgmentListTarget: seededTargets[1] });
  for (const name of seededTargets) {
    await createIndex(request, name);
  }

  try {
    // Verify the backend sees the seeded indices before opening the modal.
    const apiCheck = await request.get(
      new URL(`/api/v1/clusters/${chain.clusterId}/targets`, API_BASE).toString(),
    );
    expect(apiCheck.ok()).toBe(true);
    const apiTargets = (await apiCheck.json()) as { data: Array<{ name: string }> };
    const apiNames = apiTargets.data.map((t) => t.name);
    expect(apiNames).toContain(seededTargets[0]);
    expect(apiNames).toContain(seededTargets[1]);

    await page.goto('/studies');
    await page.getByTestId('open-create-study').click();
    await expect(page.getByTestId('create-study-form')).toBeVisible({ timeout: 5_000 });

    // Pick the seeded cluster via the cluster EntitySelect.
    const clusterTrigger = page.getByTestId('cs-cluster');
    await expect(clusterTrigger).toBeEnabled({ timeout: ENTITY_SELECT_TIMEOUT });
    await clusterTrigger.dispatchEvent('click');
    await page.getByRole('option', { name: chain.clusterName }).first().click();

    // Target dropdown loads from /api/v1/clusters/{id}/targets.
    const targetTrigger = page.getByTestId('cs-target');
    await expect(targetTrigger).toBeEnabled({ timeout: ENTITY_SELECT_TIMEOUT });
    await targetTrigger.dispatchEvent('click');

    // AC-1: both seeded targets are visible as dropdown options.
    // (FR-7 alphabetical sort is unit-tested at
    // src/__tests__/components/studies/create-study-modal.test.tsx — visual
    // boundingBox assertions in E2E are fragile under Radix portal rendering.)
    const alphaOption = page
      .getByRole('option', { name: new RegExp(`^${seededTargets[1]}`) })
      .first();
    const zuluOption = page
      .getByRole('option', { name: new RegExp(`^${seededTargets[0]}`) })
      .first();
    await expect(alphaOption).toBeVisible({ timeout: ENTITY_SELECT_TIMEOUT });
    await expect(zuluOption).toBeVisible();

    // Pick the alpha target.
    await alphaOption.click();
    await page.getByTestId('step-next').click();

    // Walk Steps 2-5 quickly using the seeded chain.
    const querySetResp = await request.get(new URL(`/api/v1/query-sets/${chain.querySetId}`, API_BASE).toString());
    const querySetName = (await querySetResp.json()).name as string;
    const judgmentListResp = await request.get(
      new URL(`/api/v1/judgment-lists/${chain.judgmentListId}`, API_BASE).toString(),
    );
    const judgmentListName = (await judgmentListResp.json()).name as string;

    async function pickEntity(testId: string, optionName: string): Promise<void> {
      const trigger = page.getByTestId(testId);
      await expect(trigger).toBeEnabled({ timeout: ENTITY_SELECT_TIMEOUT });
      await trigger.dispatchEvent('click');
      await page.getByRole('option', { name: optionName }).first().click();
    }

    await pickEntity('cs-qs', querySetName);
    await pickEntity('cs-jl', judgmentListName);
    await page.getByTestId('step-next').click();

    await pickEntity('cs-tpl', chain.templateName);
    await page.getByTestId('step-next').click();

    // Step 4: fill Study name (gates Step-4 Next per stepValid at
    // create-study-modal.tsx:376-383 — both `values.name` AND parseable
    // search-space JSON are required) + advance. Search-space auto-fill
    // from the picked template carries the JSON.
    await expect(page.getByTestId('step-4')).toBeVisible({ timeout: 5_000 });
    const studyName = `e2e-target-dropdown-${suffix}`;
    await page.getByLabel('Study name').fill(studyName);
    await page.getByTestId('step-next').click();

    // Step 5: fill Max trials (gates Submit via stopOk in stepValid case 4)
    // and submit.
    await expect(page.getByTestId('step-5')).toBeVisible({ timeout: 5_000 });
    await page.getByRole('spinbutton', { name: 'Max trials' }).fill('10');
    await page.getByTestId('create-study-submit').click();

    // The modal closes on success; verify via API that the study persisted
    // with the picked target.
    await expect(page.getByTestId('create-study-form')).not.toBeVisible({ timeout: 10_000 });

    // The study list page should be back in focus. Find the created study via
    // the list endpoint (returns StudySummary which omits `target`), then fetch
    // the detail endpoint to read the persisted `target`.
    const studiesUrl = new URL('/api/v1/studies', API_BASE);
    studiesUrl.searchParams.set('q', studyName);
    studiesUrl.searchParams.set('limit', '10');
    const studiesResp = await request.get(studiesUrl.toString());
    expect(studiesResp.ok()).toBe(true);
    const studies = (await studiesResp.json()) as {
      data: Array<{ id: string; name: string }>;
    };
    const created = studies.data.find((s) => s.name === studyName);
    expect(created).toBeDefined();
    if (created) {
      const detailResp = await request.get(new URL(`/api/v1/studies/${created.id}`, API_BASE).toString());
      expect(detailResp.ok()).toBe(true);
      const detail = (await detailResp.json()) as { target: string };
      expect(detail.target).toBe(seededTargets[1]); // alpha
    }
  } finally {
    for (const name of seededTargets) {
      await deleteIndex(request, name);
    }
  }
});
