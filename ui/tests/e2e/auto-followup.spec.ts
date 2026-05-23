/**
 * E2E spec: auto-followup chain (feat_auto_followup_studies, Story 3.3, FR-8/10/11).
 *
 * Real-backend coverage of the auto-followup chain UX surfaces:
 *  - Wizard depth selector (FR-11): create-study modal accepts depth=2,
 *    submits `config.auto_followup_depth=2` to POST /studies.
 *  - Chain panel remaining-depth indicator (FR-10 partial): the panel
 *    renders the "Remaining auto-follow-ups: N" line for any study with
 *    `config.auto_followup_depth > 0`.
 *
 * Limitations (deliberate, documented in
 * `chore_auto_followup_e2e_chain_seed_helper/idea.md`):
 *  - Cannot seed a 3-node chain (parent → child → grandchild) via the
 *    public POST /studies API — `parent_study_id` is set by the worker,
 *    not accepted from clients. Test coverage of the chain panel's
 *    parent-link + children-table + cascade-radio paths requires a
 *    new `/api/v1/_test/auto-followup/seed-chain` endpoint, captured as
 *    a follow-up. Until then, those paths are exercised at the vitest
 *    component layer in
 *    `ui/src/__tests__/components/studies/auto-followup-chain-panel.test.tsx`
 *    + `study-action-bar-cascade.test.tsx` (real component, mocked data).
 */
import { expect, test } from '@playwright/test';

import { seedFullChain, seedStudy } from './helpers/seed';

const API_BASE = process.env.PLAYWRIGHT_API_BASE_URL ?? 'http://127.0.0.1:8000';

test.describe('/studies — auto-followup chain', () => {
  test('chain panel renders the remaining-depth indicator when depth > 0', async ({ page }) => {
    // Seed a single study with auto_followup_depth=3. No chain children
    // exist yet (the worker only enqueues them after the study completes,
    // which doesn't happen within this test's lifetime), so the panel
    // renders only the remaining-depth line — exactly what the unit-test
    // 'hasDepth without hasChildren without hasParent' branch covers.
    const chain = await seedFullChain(2);
    const study = await seedStudy({
      clusterId: chain.clusterId,
      querySetId: chain.querySetId,
      templateId: chain.templateId,
      judgmentListId: chain.judgmentListId,
      maxTrials: 1,
      autoFollowupDepth: 3,
    });

    await page.goto(`/studies/${study.id}`);
    await expect(page.getByTestId('study-name')).toContainText(study.name);

    // Panel + the depth line are both present.
    await expect(page.getByTestId('auto-followup-chain-panel')).toBeVisible({ timeout: 10_000 });
    const depthLine = page.getByTestId('auto-followup-remaining-depth');
    await expect(depthLine).toBeVisible();
    await expect(depthLine).toContainText('Remaining auto-follow-ups');
    await expect(depthLine).toContainText('3');

    // Parent-link branch is absent — this is a root.
    await expect(page.getByTestId('auto-followup-parent-link')).toHaveCount(0);
  });

  test('chain panel is hidden on a study with no chain context', async ({ page }) => {
    // A vanilla study (no auto_followup_depth, no parent, no children)
    // should NOT render the chain panel — verifies the early-return guard
    // in AutoFollowupChainPanel.
    const chain = await seedFullChain(2);
    const study = await seedStudy({
      clusterId: chain.clusterId,
      querySetId: chain.querySetId,
      templateId: chain.templateId,
      judgmentListId: chain.judgmentListId,
      maxTrials: 1,
      // autoFollowupDepth intentionally omitted
    });

    await page.goto(`/studies/${study.id}`);
    await expect(page.getByTestId('study-name')).toContainText(study.name);

    await expect(page.getByTestId('auto-followup-chain-panel')).toHaveCount(0);
  });

  test('wizard depth selector submits config.auto_followup_depth (FR-11)', async ({ page }) => {
    // Drive the create-study modal end-to-end with depth=2 selected and
    // verify the resulting study row has config.auto_followup_depth=2.
    // The modal is a 5-step wizard; we navigate step-by-step via testids,
    // selecting the new depth in step 5 before submitting.
    const chain = await seedFullChain(2);

    await page.goto('/studies');
    await expect(page.getByTestId('studies-table')).toBeVisible({ timeout: 5_000 });

    // Open the create-study modal. The button text is "New study" per the
    // landing page header; if that name drifts, swap to a testid.
    await page.getByRole('button', { name: /New study/i }).click();
    await expect(page.getByTestId('step-1')).toBeVisible({ timeout: 5_000 });

    // Step 1: cluster + target.
    await page.locator('select[id*="cluster"], select#cs-cluster').first().selectOption(chain.clusterId);
    await page.locator('select[id*="target"], select#cs-target').first().selectOption('products');
    await page.getByTestId('step-next').click();
    await expect(page.getByTestId('step-2')).toBeVisible();

    // Step 2: query set + judgment list.
    await page.locator('select[id*="query"], select#cs-query-set').first().selectOption(chain.querySetId);
    await page
      .locator('select[id*="judgment"], select#cs-judgment-list')
      .first()
      .selectOption(chain.judgmentListId);
    await page.getByTestId('step-next').click();
    await expect(page.getByTestId('step-3')).toBeVisible();

    // Step 3: query template.
    await page
      .locator('select[id*="template"], select#cs-template')
      .first()
      .selectOption(chain.templateId);
    await page.getByTestId('step-next').click();
    await expect(page.getByTestId('step-4')).toBeVisible();

    // Step 4: name.
    const studyName = `e2e-auto-followup-${Date.now()}`;
    await page.getByLabel('Study name').fill(studyName);
    await page.getByTestId('step-next').click();
    await expect(page.getByTestId('step-5')).toBeVisible();

    // Step 5: pick depth=2 in the auto-followup selector.
    await page.getByTestId('cs-auto-followup').click();
    // Radix Select renders options as buttons in a portal; click by text.
    await page.getByRole('option', { name: /^2 follow-ups$/ }).click();

    // Submit.
    await page.getByRole('button', { name: /Create study/i }).click();

    // Modal should close + the new study should appear in the list. The
    // backend POST returns the created study; assert its config via API.
    await expect(page.getByText(studyName).first()).toBeVisible({ timeout: 10_000 });

    const listResp = await page.request.get(`${API_BASE}/api/v1/studies?limit=200`);
    expect(listResp.ok()).toBe(true);
    const listBody = (await listResp.json()) as { data: Array<{ id: string; name: string }> };
    const created = listBody.data.find((s) => s.name === studyName);
    expect(created).toBeDefined();

    const detailResp = await page.request.get(`${API_BASE}/api/v1/studies/${created!.id}`);
    expect(detailResp.ok()).toBe(true);
    const detail = (await detailResp.json()) as { config: { auto_followup_depth?: number } };
    expect(detail.config.auto_followup_depth).toBe(2);
  });
});
