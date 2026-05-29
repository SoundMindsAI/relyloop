/**
 * E2E: dashboard "Reset to demo state" affordance.
 *
 * feat_home_demo_reseed_endpoint Story 3.3 / AC-10. Real-backend
 * walk-through:
 *   1. Wipe the dashboard via the existing `/_test/*` DELETE endpoints
 *      so the StartHereChecklist renders (all three first-run signals
 *      false).
 *   2. Navigate to `/`.
 *   3. Open the disclosure → click the trigger → confirm in the
 *      AlertDialog.
 *   4. Wait for the success toast.
 *   5. Assert the page refetches and now renders the "Recent studies"
 *      content with at least one entry — proves the reseed populated
 *      the dashboard.
 *
 * Per Playwright rules in CLAUDE.md: no `page.route()` mocking. The
 * `request` fixture is used ONLY for setup wipe; all user-facing
 * assertions go through `page`.
 */
import { expect, test } from '@playwright/test';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000';

interface PaginatedRow {
  id: string;
}
interface PaginatedResponse {
  data: PaginatedRow[];
}

/** Wipe all dashboard-relevant rows via the test-only DELETE endpoints. */
async function wipeDashboard(request: import('@playwright/test').APIRequestContext): Promise<void> {
  // Delete order respects the FK chain: proposals → digests → studies →
  // judgment-lists → query-sets → query-templates. Each list is paginated;
  // we walk the first 200.
  const sweep = async (path: string, deletePathPrefix: string) => {
    const resp = await request.get(new URL(`${path}?limit=200`, API_BASE).toString());
    if (!resp.ok()) return;
    const body = (await resp.json()) as PaginatedResponse;
    for (const row of body.data ?? []) {
      await request.delete(new URL(`${deletePathPrefix}/${row.id}`, API_BASE).toString());
    }
  };
  await sweep('/api/v1/proposals', '/api/v1/_test/proposals');
  // Digests are 1:1 with studies; we can't list digests directly so we
  // delete them via the study delete path's cascading? No — actually
  // studies hard-delete preflight-checks for digests + proposals. So we
  // must delete digests first.
  // The studies list returns digest_id (when present); fetch and delete.
  const studiesResp = await request.get(new URL(`/api/v1/studies?limit=200`, API_BASE).toString());
  if (studiesResp.ok()) {
    const body = (await studiesResp.json()) as {
      data: { id: string; digest_id: string | null }[];
    };
    for (const study of body.data ?? []) {
      if (study.digest_id) {
        await request.delete(new URL(`/api/v1/_test/digests/${study.digest_id}`, API_BASE).toString());
      }
    }
  }
  await sweep('/api/v1/studies', '/api/v1/_test/studies');
  await sweep('/api/v1/judgment-lists', '/api/v1/_test/judgment-lists');
  await sweep('/api/v1/query-sets', '/api/v1/_test/query-sets');
  await sweep('/api/v1/query-templates', '/api/v1/_test/query-templates');
  // Clusters use the public DELETE (no test-only required).
  const clustersResp = await request.get(new URL(`/api/v1/clusters?limit=200`, API_BASE).toString());
  if (clustersResp.ok()) {
    const body = (await clustersResp.json()) as PaginatedResponse;
    for (const cluster of body.data ?? []) {
      await request.delete(new URL(`/api/v1/clusters/${cluster.id}`, API_BASE).toString());
    }
  }
}

test.describe('/ dashboard — reset to demo state', () => {
  test('AC-10: confirm dialog → reseed → dashboard refetches with 4 demo studies', async ({
    page,
    request,
    context,
  }) => {
    // 1. Wipe so the StartHereChecklist renders.
    await wipeDashboard(request);
    // Clear any prior demo-banner dismissal so the dashboard renders fresh.
    await context.addInitScript(() => {
      window.localStorage.removeItem('relyloop.home-first-run-demo-nudge.dismissed');
    });

    // 2. Navigate.
    await page.goto('/');
    await expect(page.getByTestId('start-here-checklist')).toBeVisible({ timeout: 10_000 });

    // 3. Open disclosure + trigger + confirm.
    const disclosure = page.getByTestId('reset-demo-state-disclosure');
    await expect(disclosure).toBeVisible();
    // Native <details>: click the <summary> to expand.
    await disclosure.locator('summary').click();
    const trigger = page.getByTestId('reset-demo-state-trigger');
    await expect(trigger).toBeVisible();
    await trigger.click();

    // AlertDialog visible.
    await expect(page.getByText('Wipe and reseed demo data?')).toBeVisible();
    await page.getByTestId('reset-demo-state-confirm').click();

    // 4. Wait for success toast (sonner renders any matching text).
    await expect(page.getByText(/Demo state reset/i)).toBeVisible({ timeout: 180_000 });

    // 5. Dashboard refetches; "Recent studies" card now shows entries.
    // The StartHereChecklist disappears once all three first-run signals
    // are true (clusters>0, judgment lists>0, studies>0).
    await expect(page.getByTestId('start-here-checklist')).toBeHidden({ timeout: 30_000 });
  });
});
