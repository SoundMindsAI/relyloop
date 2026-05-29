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
 *  - 3-node chain (parent → child → grandchild): seeded via
 *    `seedAutoFollowupChain` (backed by `POST /api/v1/_test/auto-followup/
 *    seed-chain`). The public POST /studies API does NOT accept
 *    `parent_study_id` (set only by the auto-followup worker), so the
 *    test-only endpoint is the only way to drive deterministic E2E
 *    coverage of chain-panel parent-link / children-table / cascade-radio
 *    paths. Closes `chore_auto_followup_e2e_chain_seed_helper` (added the
 *    three tests below the original 3).
 */
import { expect, test, type Locator, type Page } from '@playwright/test';

import { seedAutoFollowupChain, seedFullChain, seedStudy } from './helpers/seed';

const API_BASE = process.env.PLAYWRIGHT_API_BASE_URL ?? 'http://127.0.0.1:8000';
const ENTITY_SELECT_TIMEOUT = 10_000;

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

async function getName(path: string): Promise<string> {
  const resp = await fetch(new URL(path, API_BASE).toString());
  if (!resp.ok) throw new Error(`GET ${path} failed: ${resp.status}`);
  const body = (await resp.json()) as { name: string };
  return body.name;
}

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
    // verify the resulting study has config.auto_followup_depth=2.
    //
    // The wizard is a 5-step modal. Cluster/target/qs/jl/template are
    // EntitySelect components (Radix-portal-backed), so we open them via
    // dispatchEvent('click') + role=option, mirroring the canonical
    // pattern in studies-create-builder.spec.ts. The depth selector is
    // a shadcn <Select> (also Radix-portal-backed) in step 5.
    //
    // Pin judgmentListTarget so the target-judgmentlist mismatch guard
    // (feat_study_target_judgment_mismatch_guard FR-4) doesn't disable
    // the cs-jl trigger.
    const chain = await seedFullChain(2, { judgmentListTarget: 'e2e-auto-followup-target' });
    const querySetName = await getName(`/api/v1/query-sets/${chain.querySetId}`);
    const judgmentListName = await getName(`/api/v1/judgment-lists/${chain.judgmentListId}`);

    await page.goto('/studies');
    await page.getByTestId('open-create-study').click();
    await expect(page.getByTestId('create-study-form')).toBeVisible({ timeout: 5_000 });

    // Step 1: cluster + target (manual mode to avoid needing a real ES index).
    await pickEntity(page, 'cs-cluster', chain.clusterName);
    await page.getByRole('button', { name: 'Enter manually' }).click();
    await page.getByLabel('Target index / collection').fill('e2e-auto-followup-target');
    await page.getByTestId('step-next').click();

    // Step 2: query set + judgment list.
    await pickEntity(page, 'cs-qs', querySetName);
    await pickEntity(page, 'cs-jl', judgmentListName);
    await page.getByTestId('step-next').click();

    // Step 3: template.
    await pickEntity(page, 'cs-tpl', chain.templateName);
    await page.getByTestId('step-next').click();

    // Step 4: name. The search-space builder auto-fills from the template.
    await expect(page.getByTestId('step-4')).toBeVisible({ timeout: 5_000 });
    const studyName = `e2e-auto-followup-${Date.now()}`;
    await page.getByLabel('Study name').fill(studyName);
    await page.getByTestId('step-next').click();

    // Step 5: depth selector. Open the Radix Select trigger via dispatchEvent
    // (same pattern as switchRowType in studies-create-builder.spec.ts) and
    // click the "2 follow-ups" option.
    await expect(page.getByTestId('step-5')).toBeVisible({ timeout: 5_000 });
    const depthTrigger = page.getByTestId('cs-auto-followup');
    await expect(depthTrigger).toBeEnabled();
    await depthTrigger.dispatchEvent('click');
    await page.getByRole('option', { name: /^2 follow-ups$/ }).click();

    // Submit + verify the wire contract.
    await page.getByRole('button', { name: /Create study/i }).click();

    // Wait for the modal to dismiss; the form-create-success path closes it.
    await expect(page.getByTestId('create-study-form')).toHaveCount(0, { timeout: 10_000 });

    // Fetch the new study from the backend and assert the config.
    const listResp = await page.request.get(new URL(`/api/v1/studies?limit=200`, API_BASE).toString());
    expect(listResp.ok()).toBe(true);
    const listBody = (await listResp.json()) as { data: Array<{ id: string; name: string }> };
    const created = listBody.data.find((s) => s.name === studyName);
    expect(created, `expected to find study named ${studyName}`).toBeDefined();

    const detailResp = await page.request.get(new URL(`/api/v1/studies/${created!.id}`, API_BASE).toString());
    expect(detailResp.ok()).toBe(true);
    const detail = (await detailResp.json()) as { config: { auto_followup_depth?: number } };
    expect(detail.config.auto_followup_depth).toBe(2);
  });

  // chore_auto_followup_e2e_chain_seed_helper — Story 3.3 follow-up coverage
  // unblocked by the new `seedAutoFollowupChain` helper (POST /api/v1/_test/
  // auto-followup/seed-chain). The three tests below all run against a
  // depth=2, in_flight_leaf=true, in_flight_middle=true chain — R(completed)
  // → M(queued) → L(queued) — so M has both a parent link (R) and an
  // in-flight child (L), and M's cancel button is enabled.
  test('chain panel on middle node renders parent link + children table', async ({ page }) => {
    const chain = await seedFullChain(2);
    const seed = await seedAutoFollowupChain({
      clusterId: chain.clusterId,
      querySetId: chain.querySetId,
      templateId: chain.templateId,
      judgmentListId: chain.judgmentListId,
      depth: 2,
    });
    // depth=2 → 3 nodes total → middleIds has exactly 1 entry.
    expect(seed.middleIds).toHaveLength(1);
    const middleId = seed.middleIds[0];

    await page.goto(`/studies/${middleId}`);
    await expect(page.getByTestId('auto-followup-chain-panel')).toBeVisible({ timeout: 10_000 });

    // Parent link → root (R).
    const parentLink = page.getByTestId('auto-followup-parent-link');
    await expect(parentLink).toBeVisible();
    const parentHref = await parentLink.locator('a').getAttribute('href');
    expect(parentHref).toContain(`/studies/${seed.rootId}`);

    // Remaining depth on M = 1 (root had 2, child has 1).
    const depthLine = page.getByTestId('auto-followup-remaining-depth');
    await expect(depthLine).toBeVisible();
    await expect(depthLine).toContainText('1');

    // Children table contains the leaf (L) as a row.
    const childrenTable = page.getByTestId('auto-followup-children-table');
    await expect(childrenTable).toBeVisible();
    await expect(childrenTable).toContainText(seed.leafId.slice(0, 8));
  });

  test('cancel modal on middle node shows cascade radio defaulting to cascade=true', async ({
    page,
  }) => {
    const chain = await seedFullChain(2);
    const seed = await seedAutoFollowupChain({
      clusterId: chain.clusterId,
      querySetId: chain.querySetId,
      templateId: chain.templateId,
      judgmentListId: chain.judgmentListId,
      depth: 2,
    });
    const middleId = seed.middleIds[0]!;

    await page.goto(`/studies/${middleId}`);
    // Wait for the page to hydrate so the cancel button + chain children
    // query have resolved (showCascadeRadio depends on chainChildren).
    await expect(page.getByTestId('study-name')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId('auto-followup-chain-panel')).toBeVisible({ timeout: 10_000 });

    // Open the cancel modal — the button is enabled because M is queued.
    await page.getByTestId('cancel-study').click();
    const cascadeGroup = page.getByTestId('cancel-cascade-radio-group');
    await expect(cascadeGroup).toBeVisible({ timeout: 5_000 });
    // Defaults: cascade=true is checked.
    await expect(page.getByTestId('cascade-true')).toBeChecked();
    await expect(page.getByTestId('cascade-false')).not.toBeChecked();

    // Submit with the default (cascade=true). Assert the DELETE fires with
    // ?cascade=true by intercepting the response.
    // Frontend fires POST /api/v1/studies/{id}/cancel?cascade=…
    // (see useCancelStudy at ui/src/lib/api/studies.ts:138-158), NOT DELETE.
    const cancelRespPromise = page.waitForResponse(
      (resp) =>
        resp.url().includes(`/api/v1/studies/${middleId}/cancel`) &&
        resp.request().method() === 'POST',
    );
    await page.getByTestId('confirm-cancel').click();
    const cancelResp = await cancelRespPromise;
    expect(cancelResp.url()).toContain('cascade=true');
    expect(cancelResp.ok()).toBe(true);
  });

  test('cancel modal on middle node honors cascade=false radio selection', async ({ page }) => {
    const chain = await seedFullChain(2);
    const seed = await seedAutoFollowupChain({
      clusterId: chain.clusterId,
      querySetId: chain.querySetId,
      templateId: chain.templateId,
      judgmentListId: chain.judgmentListId,
      depth: 2,
    });
    const middleId = seed.middleIds[0]!;

    await page.goto(`/studies/${middleId}`);
    await expect(page.getByTestId('study-name')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId('auto-followup-chain-panel')).toBeVisible({ timeout: 10_000 });
    await page.getByTestId('cancel-study').click();
    await expect(page.getByTestId('cancel-cascade-radio-group')).toBeVisible({ timeout: 5_000 });

    // Flip to cascade=false then submit.
    await page.getByTestId('cascade-false').click();
    await expect(page.getByTestId('cascade-false')).toBeChecked();
    await expect(page.getByTestId('cascade-true')).not.toBeChecked();

    // Frontend fires POST /api/v1/studies/{id}/cancel?cascade=…
    // (see useCancelStudy at ui/src/lib/api/studies.ts:138-158), NOT DELETE.
    const cancelRespPromise = page.waitForResponse(
      (resp) =>
        resp.url().includes(`/api/v1/studies/${middleId}/cancel`) &&
        resp.request().method() === 'POST',
    );
    await page.getByTestId('confirm-cancel').click();
    const cancelResp = await cancelRespPromise;
    expect(cancelResp.url()).toContain('cascade=false');
    expect(cancelResp.ok()).toBe(true);
  });
});
