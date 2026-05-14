/**
 * E2E spec: /judgments/[id] workflows (B6 override, B7 calibrate).
 *
 * Seeds a judgment list via the import path (skips LLM generation entirely),
 * then exercises the review UI: page renders header counts, calibration
 * modal opens. Per-judgment override is API-only in MVP1 (no inline-edit UI
 * shipped yet) — we assert the API contract via direct PATCH instead.
 */
import { expect, test } from '@playwright/test';

import { seedJudgmentList, seedQuerySet } from './helpers/seed';

const API_BASE = process.env.PLAYWRIGHT_API_BASE_URL ?? 'http://127.0.0.1:8000';

test.describe('/judgments/[id]', () => {
  test('renders the judgment list header + count after import', async ({ page }) => {
    const qs = await seedQuerySet(3);
    const jl = await seedJudgmentList({
      clusterId: qs.clusterId,
      querySetId: qs.querySetId,
      queryIds: qs.queryIds,
    });

    await page.goto(`/judgments/${jl.id}`);
    // The header surfaces the total count we just imported.
    await expect(page.getByTestId('header-count')).toBeVisible({ timeout: 5_000 });
    await expect(page.getByTestId('header-count')).toContainText(String(jl.judgmentCount));
  });

  test('calibrate button opens the calibration modal', async ({ page }) => {
    const qs = await seedQuerySet(3);
    const jl = await seedJudgmentList({
      clusterId: qs.clusterId,
      querySetId: qs.querySetId,
      queryIds: qs.queryIds,
    });

    await page.goto(`/judgments/${jl.id}`);
    await page.getByTestId('open-calibration').click();
    // Calibration modal renders as a dialog.
    await expect(page.getByRole('dialog')).toBeVisible({ timeout: 5_000 });
  });

  test('PATCH judgment via API succeeds (UI override surface deferred to v2)', async ({
    request,
  }) => {
    // B6 (override): the API contract is shipped and exercised here.
    // PATCH /api/v1/judgment-lists/{id}/judgments/{judgment_id} is the
    // canonical override path; the in-table UI override surface is deferred.
    const qs = await seedQuerySet(2);
    const jl = await seedJudgmentList({
      clusterId: qs.clusterId,
      querySetId: qs.querySetId,
      queryIds: qs.queryIds,
    });

    // Fetch the list's judgments to learn the first judgment id.
    const listResp = await request.get(
      `${API_BASE}/api/v1/judgment-lists/${jl.id}/judgments?limit=1`,
    );
    expect(listResp.ok()).toBe(true);
    const listBody = (await listResp.json()) as { data: Array<{ id: string }> };
    expect(listBody.data.length).toBeGreaterThan(0);
    const firstJudgmentId = listBody.data[0]!.id;

    const patchResp = await request.patch(
      `${API_BASE}/api/v1/judgment-lists/${jl.id}/judgments/${firstJudgmentId}`,
      { data: { rating: 3, notes: 'e2e human override' } },
    );
    expect(patchResp.ok()).toBe(true);
  });
});
