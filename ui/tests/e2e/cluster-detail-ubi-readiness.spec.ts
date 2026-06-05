// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * E2E: cluster-detail UBI readiness card (chore_cluster_detail_rung_badge
 * Story 7 / FR-8).
 *
 * Real-backend, no `page.route()` mocking. Assumes the demo stack is already
 * seeded (the heavy-lane `demo-ubi.spec.ts` performs the reseed; this spec only
 * reads). The acme-products-prod scenario seeds exactly one query set + a
 * `target_filter`, so the card auto-seeds and the badge resolves without
 * operator interaction. Asserts:
 *
 *   - The readiness card is mounted on `/clusters/{acme_id}`.
 *   - The `<UbiRungBadge>` resolves with a `data-rung` ≠ `rung_0` (acme has
 *     dense synthetic UBI).
 *   - Exactly one synthetic-UBI chip is present AND it lives inside the
 *     readiness card (not the summary card — Story 5 relocation).
 *
 * Gated behind SKIP_HEAVY_CI per the heavy-lane convention.
 */
import { expect, test, type APIRequestContext } from '@playwright/test';

test.skip(
  process.env.SKIP_HEAVY_CI === 'true',
  'SKIP_HEAVY_CI=true — heavy lane suppressed (state.md)',
);

const API_BASE = process.env.PLAYWRIGHT_API_BASE_URL ?? 'http://127.0.0.1:8000';

interface ClusterRow {
  id: string;
  name: string;
}

async function discoverClusterByName(
  request: APIRequestContext,
  name: string,
): Promise<ClusterRow> {
  const resp = await request.get(new URL('/api/v1/clusters?limit=50', API_BASE).toString());
  expect(resp.ok()).toBeTruthy();
  const body = (await resp.json()) as { data: ClusterRow[] };
  const cluster = body.data.find((c) => c.name === name);
  test.skip(cluster == null, `demo cluster ${name} not seeded — run make seed-demo`);
  return cluster as ClusterRow;
}

test.describe('Cluster-detail UBI readiness card (Story 7)', () => {
  test('auto-seeds + resolves the badge with the relocated synthetic chip on acme', async ({
    page,
    request,
  }) => {
    const acme = await discoverClusterByName(request, 'acme-products-prod');
    await page.goto(`/clusters/${acme.id}`);

    const card = page.getByTestId('cluster-detail-ubi-readiness-card');
    await expect(card).toBeVisible({ timeout: 15_000 });

    const badge = card.getByTestId('ubi-rung-badge');
    await expect(badge).toBeVisible({ timeout: 15_000 });
    // acme has dense synthetic UBI — the rung must resolve past rung_0.
    await expect(badge).not.toHaveAttribute('data-rung', 'rung_0');

    // Exactly one chip, and it lives inside the readiness card (Story 5).
    await expect(page.getByTestId('demo-badge-synthetic-ubi')).toHaveCount(1);
    await expect(card.getByTestId('demo-badge-synthetic-ubi')).toBeVisible();
  });

  test('no synthetic chip on news-search-staging cluster detail (negative case)', async ({
    page,
    request,
  }) => {
    const news = await discoverClusterByName(request, 'news-search-staging');
    await page.goto(`/clusters/${news.id}`);
    await expect(page.getByTestId('cluster-detail-ubi-readiness-card')).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByTestId('demo-badge-synthetic-ubi')).toHaveCount(0);
  });
});
