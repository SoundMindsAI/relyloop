// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * E2E: LLM-study-detail → compare flow (feat_ubi_llm_study_comparison AC-9/10/15).
 *
 * Real-backend; no `page.route()` mocking. Discovers a completed study that has
 * an LLM↔UBI counterpart from the demo reseed (the same dual-pair the
 * `demo-ubi` scenario produces), navigates to the LLM study detail, clicks the
 * compare button, and asserts the comparison page renders both columns + the
 * four panels. Also asserts the button is absent on a study with no pair and
 * that the page is reachable on a narrow viewport (AC-15).
 *
 * Gated behind SKIP_HEAVY_CI per the heavy-lane convention.
 */
import { expect, test, type APIRequestContext } from '@playwright/test';

test.skip(
  process.env.SKIP_HEAVY_CI === 'true',
  'SKIP_HEAVY_CI=true — heavy lane suppressed (state.md)',
);

const API_BASE = process.env.PLAYWRIGHT_API_BASE_URL ?? 'http://127.0.0.1:8000';

interface StudyRow {
  id: string;
  name: string;
  status: string;
}

/** Find a completed study that has an LLM↔UBI counterpart (via /pair), plus a
 * completed study that has none. Skips the test if the demo data has neither. */
async function discoverPair(
  request: APIRequestContext,
): Promise<{ a: string; b: string; unpaired: string | null }> {
  const resp = await request.get(
    new URL('/api/v1/studies?status=completed&limit=50', API_BASE).toString(),
  );
  expect(resp.ok()).toBeTruthy();
  const studies = ((await resp.json()) as { data: StudyRow[] }).data;

  let pairedLlm: string | null = null;
  let pairedUbi: string | null = null;
  let unpaired: string | null = null;
  for (const s of studies) {
    const pr = await request.get(new URL(`/api/v1/studies/${s.id}/pair`, API_BASE).toString());
    const pair = (await pr.json()) as { study_id: string | null; kind: string | null };
    if (pair.study_id == null) {
      unpaired ??= s.id;
      continue;
    }
    // Canonicalize to LLM=a, UBI=b using the counterpart's kind.
    if (pair.kind === 'ubi') {
      pairedLlm = s.id;
      pairedUbi = pair.study_id;
    } else {
      pairedLlm = pair.study_id;
      pairedUbi = s.id;
    }
    break;
  }
  test.skip(pairedLlm == null || pairedUbi == null, 'demo data has no LLM↔UBI study pair');
  return { a: pairedLlm as string, b: pairedUbi as string, unpaired };
}

test.describe('Study comparison — LLM vs UBI (Stories 3.7/4.3)', () => {
  test('AC-10: compare button on the LLM study navigates to the comparison view', async ({
    page,
    request,
  }) => {
    const { a } = await discoverPair(request);
    await page.goto(`/studies/${a}`);
    const btn = page.getByTestId('study-compare-button');
    await expect(btn).toBeVisible({ timeout: 10_000 });
    await btn.click();
    await expect(page).toHaveURL(/\/studies\/compare\?a=/);
    await expect(page.getByTestId('compare-col-llm-header')).toBeVisible();
    await expect(page.getByTestId('compare-col-ubi-header')).toBeVisible();
    await expect(page.getByTestId('compare-best-metric-panel')).toBeVisible();
    await expect(page.getByTestId('compare-param-diff-panel')).toBeVisible();
    await expect(page.getByTestId('compare-digest-diff-panel')).toBeVisible();
    await expect(page.getByTestId('compare-convergence-overlay')).toBeVisible();
  });

  test('AC-9: no compare button on a study without a counterpart', async ({ page, request }) => {
    const { unpaired } = await discoverPair(request);
    test.skip(unpaired == null, 'demo data has no unpaired completed study');
    await page.goto(`/studies/${unpaired}`);
    await expect(page.getByTestId('study-page-summary')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId('study-compare-button')).toHaveCount(0);
  });

  test('AC-15: comparison page is reachable on a narrow viewport', async ({ page, request }) => {
    const { a, b } = await discoverPair(request);
    await page.setViewportSize({ width: 480, height: 900 });
    await page.goto(`/studies/compare?a=${a}&b=${b}`);
    await expect(page.getByTestId('compare-best-metric-panel')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId('compare-convergence-overlay')).toBeVisible();
  });
});
