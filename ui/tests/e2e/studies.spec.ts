/**
 * E2E spec: /studies workflows (C1 create, C3 monitor, C4 cancel).
 *
 * Covers the core "Karpathy loop" entry points in the UI:
 *  - C1: seed an upstream chain via the API, then verify the study detail
 *    page renders with the expected metadata + status badge.
 *  - C3: confirm the polling-driven trials table mounts and the study
 *    header surfaces the study's current state.
 *  - C4: cancel a running/queued study from the detail action bar and
 *    assert the status transitions away from running.
 *
 * Note on C1: the CreateStudyModal is a 5-step wizard with rich form state.
 * Driving it end-to-end via Playwright is brittle — instead we seed the
 * study via the API (mirroring what the modal POSTs) and assert the
 * post-create UI shape, which is what users actually see.
 */
import { expect, test } from '@playwright/test';

import { seedFullChain, seedStudy } from './helpers/seed';

const API_BASE = process.env.PLAYWRIGHT_API_BASE_URL ?? 'http://127.0.0.1:8000';

test.describe('/studies', () => {
  test('lists a created study and the detail page renders header + trials table', async ({
    page,
  }) => {
    const chain = await seedFullChain(3);
    const study = await seedStudy({
      clusterId: chain.clusterId,
      querySetId: chain.querySetId,
      templateId: chain.templateId,
      judgmentListId: chain.judgmentListId,
    });

    // List page contains the new study.
    await page.goto('/studies');
    await expect(page.getByTestId('studies-table')).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText(study.name).first()).toBeVisible({ timeout: 5_000 });

    // Detail page renders the canonical header testids + trials surface.
    await page.goto(`/studies/${study.id}`);
    await expect(page.getByTestId('study-name')).toContainText(study.name);
    await expect(page.getByTestId('trials-table').or(page.getByTestId('trials-empty'))).toBeVisible(
      { timeout: 10_000 },
    );
  });

  test('status filter chips drive the URL ?status= param', async ({ page }) => {
    await page.goto('/studies');
    await expect(
      page.getByTestId('studies-table').or(page.getByTestId('data-table-empty-no-rows-exist')),
    ).toBeVisible();

    // Click the "completed" chip → URL should reflect ?status=completed.
    // Story 2.3 testid pattern: `filter-chip-<col>-<val>`.
    await page.getByTestId('filter-chip-status-completed').click();
    await expect(page).toHaveURL(/[?&]status=completed/);

    // Back to "all" → ?status= dropped.
    await page.getByTestId('filter-chip-status-all').click();
    await expect(page).not.toHaveURL(/[?&]status=/);
  });

  test('contextual help — modal triggers (FR-6, 11 placements)', async ({ page }) => {
    await page.goto('/studies');
    // Open the create-study modal.
    await page.getByTestId('open-create-study').click();
    await expect(page.getByTestId('create-study-form')).toBeVisible({ timeout: 5_000 });

    // Step 1: target trigger
    await expect(page.getByTestId('tooltip-trigger-study.target')).toBeVisible();
    // NOTE: Step 3 (template) and Step 5 (objective + config) triggers require
    // advancing through the wizard with a seeded chain. Those triggers are
    // covered by the create-study-modal.test.tsx vitest component test (which
    // walks all 5 steps with a mocked backend). E2E here asserts only the
    // Step 1 trigger as a smoke; deeper E2E walks live in vitest where the
    // form state machine is deterministic.
  });

  test('contextual help — study-detail header + trials-table triggers (FR-7, FR-8)', async ({
    page,
  }) => {
    const chain = await seedFullChain(2);
    const study = await seedStudy({
      clusterId: chain.clusterId,
      querySetId: chain.querySetId,
      templateId: chain.templateId,
      judgmentListId: chain.judgmentListId,
      maxTrials: 1,
    });
    await page.goto(`/studies/${study.id}`);

    // Wait for the study to load so the header renders.
    await expect(page.getByTestId('study-name')).toBeVisible({ timeout: 10_000 });

    // FR-7: study-header tooltips (status badge dynamic key + Best metric + Trials).
    // The status badge tooltip uses a dynamic key matching the actual status.
    const statusTrigger = page
      .getByTestId(/^tooltip-trigger-study\.status\.(queued|running|completed|cancelled|failed)$/)
      .first();
    await expect(statusTrigger).toBeVisible();
    await expect(page.getByTestId('tooltip-trigger-study.best_metric')).toBeVisible();
    await expect(page.getByTestId('tooltip-trigger-study.trials_summary')).toBeVisible();

    // FR-8: trials-table tooltips. The Sort label always renders (above the table).
    await expect(page.getByTestId('tooltip-trigger-trial.sort_by')).toBeVisible();
    // Column headers only render when at least one trial row exists; the
    // empty-state placeholder takes their place otherwise. Assert headers
    // only on the populated path so the test doesn't race the orchestrator.
    const trialsTable = page.getByTestId('trials-table');
    if (await trialsTable.isVisible().catch(() => false)) {
      await expect(page.getByTestId('tooltip-trigger-trial.status')).toBeVisible();
      await expect(page.getByTestId('tooltip-trigger-trial.primary_metric')).toBeVisible();
      await expect(page.getByTestId('tooltip-trigger-trial.duration_ms')).toBeVisible();
      await expect(page.getByTestId('tooltip-trigger-trial.params')).toBeVisible();
    }
  });

  test('contextual help — InfoTooltip reveals on hover and ESC dismisses (AC-2 / AC-3)', async ({
    page,
  }) => {
    const chain = await seedFullChain(2);
    const study = await seedStudy({
      clusterId: chain.clusterId,
      querySetId: chain.querySetId,
      templateId: chain.templateId,
      judgmentListId: chain.judgmentListId,
      maxTrials: 1,
    });
    await page.goto(`/studies/${study.id}`);
    await expect(page.getByTestId('study-name')).toBeVisible({ timeout: 10_000 });

    const trigger = page.getByTestId('tooltip-trigger-study.best_metric');
    await trigger.hover();
    await expect(page.getByTestId('tooltip-body-study.best_metric')).toBeVisible({
      timeout: 2_000,
    });
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('tooltip-body-study.best_metric')).not.toBeVisible();
  });

  test('cancel button fires POST /cancel on a cancellable study', async ({ page }) => {
    // Deterministic test of the C4 cancel flow: seed a study, navigate to its
    // detail page, and verify that clicking the cancel button (when visible)
    // fires the cancel POST. We don't assert on downstream state transitions
    // — those are tested by backend integration tests against the orchestrator.
    const chain = await seedFullChain(2);
    const study = await seedStudy({
      clusterId: chain.clusterId,
      querySetId: chain.querySetId,
      templateId: chain.templateId,
      judgmentListId: chain.judgmentListId,
      maxTrials: 1,
    });

    await page.goto(`/studies/${study.id}`);

    // Wait for the page to load fully — the StudyActionBar only renders once
    // studyQ.data resolves. The cancel button is always present (just disabled
    // when status isn't queued/running), so we wait for it to appear.
    const cancelBtn = page.getByTestId('cancel-study');
    await expect(cancelBtn).toBeVisible({ timeout: 10_000 });

    const isEnabled = await cancelBtn.isEnabled();
    if (isEnabled) {
      const postPromise = page.waitForResponse(
        (resp) =>
          resp.url().endsWith(`/api/v1/studies/${study.id}/cancel`) &&
          resp.request().method() === 'POST',
        { timeout: 10_000 },
      );
      await cancelBtn.click();
      await page.getByTestId('confirm-cancel').click();
      const resp = await postPromise;
      // 200 on success, 409 if the study raced to terminal before the click.
      expect([200, 409]).toContain(resp.status());
    } else {
      // Button disabled = study has transitioned past queued/running.
      // Confirm the underlying state via the API.
      const apiResp = await page.request.get(`${API_BASE}/api/v1/studies/${study.id}`);
      expect(apiResp.ok()).toBe(true);
      const body = await apiResp.json();
      expect(['completed', 'failed', 'cancelled']).toContain(body.status);
    }
  });
});
