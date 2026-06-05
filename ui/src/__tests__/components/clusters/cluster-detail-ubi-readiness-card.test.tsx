// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Unit tests for ClusterDetailUbiReadinessCard (chore_cluster_detail_rung_badge
 * Story 7). Covers AC-1 through AC-9.
 *
 * Network-layer mocking ONLY (MSW intercepts the HTTP calls) — `useQuery`,
 * `useMutation`, and `keepPreviousData` run for real so AC-8 actually exercises
 * `placeholderData: keepPreviousData`. The query-sets handler differentiates
 * the picker call (`limit=50`) from the auto-seed probe (`limit=2`) by the
 * `limit` query param; the readiness handler differentiates by `target`.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { delay, http, HttpResponse } from 'msw';
import { type ReactNode } from 'react';
import { describe, expect, it } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { server } from '../../setup';
import { ClusterDetailUbiReadinessCard } from '@/components/clusters/cluster-detail-ubi-readiness-card';
import { TooltipProvider } from '@/components/ui/tooltip';
import type { ClusterDetail } from '@/lib/api/clusters';
import type { QuerySetSummary } from '@/lib/api/query-sets';

const API_BASE = 'http://api.test';
const CLUSTER_ID = 'cluster-1';

const BASE_CLUSTER: ClusterDetail = {
  id: CLUSTER_ID,
  name: 'production-real-cluster',
  engine_type: 'elasticsearch',
  environment: 'prod',
  base_url: 'http://elasticsearch:9200',
  auth_kind: 'es_basic',
  engine_config: null,
  notes: null,
  target_filter: null,
  created_at: '2026-05-21T00:00:00Z',
  health_check: {
    status: 'green',
    version: '9.4.0',
    checked_at: '2026-05-21T00:00:00Z',
    error: null,
  },
};

function makeQuerySet(id: string, name: string): QuerySetSummary {
  return {
    id,
    name,
    cluster_id: CLUSTER_ID,
    query_count: 10,
    created_at: '2026-05-21T00:00:00Z',
  };
}

/**
 * Register the query-sets endpoint with separate payloads for the picker
 * (limit=50) and the auto-seed probe (limit=2). `pickerRows` defaults to
 * `probeRows` so single-row auto-seed fixtures stay consistent.
 */
function useQuerySetsHandler(opts: {
  probeRows: QuerySetSummary[];
  probeHasMore?: boolean;
  pickerRows?: QuerySetSummary[];
  pickerHasMore?: boolean;
}) {
  const pickerRows = opts.pickerRows ?? opts.probeRows;
  server.use(
    http.get(`${API_BASE}/api/v1/query-sets`, ({ request }) => {
      const limit = new URL(request.url).searchParams.get('limit');
      const isProbe = limit === '2';
      const rows = isProbe ? opts.probeRows : pickerRows;
      const hasMore = isProbe ? (opts.probeHasMore ?? false) : (opts.pickerHasMore ?? false);
      return HttpResponse.json(
        { data: rows, has_more: hasMore, next_cursor: null },
        { headers: { 'X-Total-Count': String(rows.length) } },
      );
    }),
  );
}

function useReadinessHandler(
  responder: (target: string | null) => { status?: number; body?: unknown; delayMs?: number },
) {
  server.use(
    http.get(`${API_BASE}/api/v1/clusters/${CLUSTER_ID}/ubi-readiness`, async ({ request }) => {
      const target = new URL(request.url).searchParams.get('target');
      const { status = 200, body, delayMs } = responder(target);
      if (delayMs) await delay(delayMs);
      return HttpResponse.json(body ?? {}, { status });
    }),
  );
}

function readiness(rung: string) {
  return {
    rung,
    covered_pairs_pct: 0.5,
    head_covered: true,
    checked_at: '2026-05-21T00:00:00Z',
  };
}

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider delayDuration={0}>{node}</TooltipProvider>
    </QueryClientProvider>,
  );
}

describe('ClusterDetailUbiReadinessCard', () => {
  it('AC-1: mounts the card', async () => {
    useQuerySetsHandler({ probeRows: [], pickerRows: [] });
    wrap(<ClusterDetailUbiReadinessCard cluster={BASE_CLUSTER} />);
    expect(await screen.findByTestId('cluster-detail-ubi-readiness-card')).toBeInTheDocument();
  });

  it('AC-4: renders the empty state when the cluster has no query sets', async () => {
    useQuerySetsHandler({ probeRows: [], pickerRows: [] });
    wrap(<ClusterDetailUbiReadinessCard cluster={BASE_CLUSTER} />);
    expect(await screen.findByTestId('ubi-readiness-empty')).toBeInTheDocument();
    expect(screen.getByTestId('ubi-readiness-create-query-set')).toHaveAttribute(
      'href',
      '/query-sets',
    );
  });

  it('AC-2: auto-seeds + resolves the badge on a single-query-set cluster with a target_filter', async () => {
    const qs = makeQuerySet('qs-1', 'Primary set');
    useQuerySetsHandler({ probeRows: [qs], pickerRows: [qs] });
    useReadinessHandler(() => ({ body: readiness('rung_2') }));
    wrap(
      <ClusterDetailUbiReadinessCard
        cluster={{ ...BASE_CLUSTER, target_filter: 'products*' }}
      />,
    );
    const badge = await screen.findByTestId('ubi-rung-badge', undefined, { timeout: 3000 });
    expect(badge).toHaveAttribute('data-rung', 'rung_2');
  });

  it('AC-3: does NOT auto-seed when the cluster has more than one query set', async () => {
    const rows = [makeQuerySet('qs-1', 'One'), makeQuerySet('qs-2', 'Two')];
    useQuerySetsHandler({ probeRows: rows, probeHasMore: false, pickerRows: rows });
    useReadinessHandler(() => ({ body: readiness('rung_2') }));
    wrap(
      <ClusterDetailUbiReadinessCard cluster={{ ...BASE_CLUSTER, target_filter: 'products*' }} />,
    );
    // Picker renders, but no auto-seed → no badge.
    expect(await screen.findByTestId('cluster-detail-ubi-query-set-trigger')).toBeInTheDocument();
    expect(screen.queryByTestId('ubi-rung-badge')).not.toBeInTheDocument();
  });

  it('AC-3: does NOT auto-seed when has_more is true even with a single returned row', async () => {
    const qs = makeQuerySet('qs-1', 'Primary set');
    useQuerySetsHandler({ probeRows: [qs], probeHasMore: true, pickerRows: [qs] });
    useReadinessHandler(() => ({ body: readiness('rung_2') }));
    wrap(
      <ClusterDetailUbiReadinessCard cluster={{ ...BASE_CLUSTER, target_filter: 'products*' }} />,
    );
    expect(await screen.findByTestId('cluster-detail-ubi-query-set-trigger')).toBeInTheDocument();
    expect(screen.queryByTestId('ubi-rung-badge')).not.toBeInTheDocument();
  });

  it('AC-5: relocated synthetic-data chip renders next to the badge on a demo cluster', async () => {
    const qs = makeQuerySet('qs-1', 'Primary set');
    useQuerySetsHandler({ probeRows: [qs], pickerRows: [qs] });
    useReadinessHandler(() => ({ body: readiness('rung_2') }));
    wrap(
      <ClusterDetailUbiReadinessCard
        cluster={{ ...BASE_CLUSTER, name: 'acme-products-prod', target_filter: 'products*' }}
      />,
    );
    await screen.findByTestId('ubi-rung-badge', undefined, { timeout: 3000 });
    const row = screen.getByTestId('cluster-detail-ubi-result-row');
    expect(row).toContainElement(screen.getByTestId('demo-badge-synthetic-ubi'));
  });

  it('AC-6: no synthetic-data chip on a non-demo cluster', async () => {
    const qs = makeQuerySet('qs-1', 'Primary set');
    useQuerySetsHandler({ probeRows: [qs], pickerRows: [qs] });
    useReadinessHandler(() => ({ body: readiness('rung_2') }));
    wrap(
      <ClusterDetailUbiReadinessCard cluster={{ ...BASE_CLUSTER, target_filter: 'products*' }} />,
    );
    await screen.findByTestId('ubi-rung-badge', undefined, { timeout: 3000 });
    expect(screen.queryByTestId('demo-badge-synthetic-ubi')).not.toBeInTheDocument();
  });

  it('AC-7: unified fallback caption renders when readiness degrades (404 → rung_0 fallback)', async () => {
    const qs = makeQuerySet('qs-1', 'Primary set');
    useQuerySetsHandler({ probeRows: [qs], pickerRows: [qs] });
    // 404 (not 503+retryable) so the apiClient throws immediately and the
    // hook's graceful-degrade catch synthesizes the rung_0 fallback.
    useReadinessHandler(() => ({
      status: 404,
      body: { detail: { error_code: 'UBI_QUERIES_MISSING', message: 'no ubi', retryable: false } },
    }));
    wrap(
      <ClusterDetailUbiReadinessCard cluster={{ ...BASE_CLUSTER, target_filter: 'products*' }} />,
    );
    const caption = await screen.findByText(
      /Couldn't refresh UBI status \(cluster unreachable or query set missing\)\./,
      undefined,
      { timeout: 3000 },
    );
    expect(caption).toBeInTheDocument();
    // The hook synthesizes rung_0 on 503, so the badge still renders.
    expect(screen.getByTestId('ubi-rung-badge')).toHaveAttribute('data-rung', 'rung_0');
  });

  it('AC-7: shows a first-fetch skeleton while readiness is in-flight', async () => {
    const qs = makeQuerySet('qs-1', 'Primary set');
    useQuerySetsHandler({ probeRows: [qs], pickerRows: [qs] });
    useReadinessHandler(() => ({ body: readiness('rung_2'), delayMs: 400 }));
    wrap(
      <ClusterDetailUbiReadinessCard cluster={{ ...BASE_CLUSTER, target_filter: 'products*' }} />,
    );
    expect(
      await screen.findByTestId('ubi-readiness-skeleton', undefined, { timeout: 3000 }),
    ).toBeInTheDocument();
    // …and it resolves into the badge.
    await screen.findByTestId('ubi-rung-badge', undefined, { timeout: 3000 });
    expect(screen.queryByTestId('ubi-readiness-skeleton')).not.toBeInTheDocument();
  });

  it('AC-8: badge persists (no skeleton flash, no unmount) across a target edit (placeholderData)', async () => {
    const qs = makeQuerySet('qs-1', 'Primary set');
    useQuerySetsHandler({ probeRows: [qs], pickerRows: [qs] });
    // First target → rung_1; edited target → rung_2 (delayed so the previous
    // value is observably retained during the refetch).
    useReadinessHandler((target) =>
      target === 'orders*'
        ? { body: readiness('rung_2'), delayMs: 300 }
        : { body: readiness('rung_1') },
    );
    wrap(
      <ClusterDetailUbiReadinessCard cluster={{ ...BASE_CLUSTER, target_filter: 'products*' }} />,
    );
    const badge = await screen.findByTestId('ubi-rung-badge', undefined, { timeout: 3000 });
    expect(badge).toHaveAttribute('data-rung', 'rung_1');

    fireEvent.change(screen.getByTestId('cluster-detail-ubi-target-input'), {
      target: { value: 'orders*' },
    });

    // Across the debounce + delayed refetch window, the badge must stay mounted
    // (keepPreviousData) and no skeleton may replace it.
    for (let i = 0; i < 8; i += 1) {
      await delay(50);
      expect(screen.getByTestId('ubi-rung-badge')).toBeInTheDocument();
      expect(screen.queryByTestId('ubi-readiness-skeleton')).not.toBeInTheDocument();
    }
    await waitFor(
      () => expect(screen.getByTestId('ubi-rung-badge')).toHaveAttribute('data-rung', 'rung_2'),
      { timeout: 3000 },
    );
  });

  it('AC-8b: clearing the target input hides the badge + chip (dual leak gate)', async () => {
    const qs = makeQuerySet('qs-1', 'Primary set');
    useQuerySetsHandler({ probeRows: [qs], pickerRows: [qs] });
    useReadinessHandler(() => ({ body: readiness('rung_2') }));
    wrap(
      <ClusterDetailUbiReadinessCard
        cluster={{ ...BASE_CLUSTER, name: 'acme-products-prod', target_filter: 'products*' }}
      />,
    );
    await screen.findByTestId('ubi-rung-badge', undefined, { timeout: 3000 });
    fireEvent.change(screen.getByTestId('cluster-detail-ubi-target-input'), {
      target: { value: '' },
    });
    await waitFor(() => expect(screen.queryByTestId('ubi-rung-badge')).not.toBeInTheDocument(), {
      timeout: 3000,
    });
    expect(screen.queryByTestId('demo-badge-synthetic-ubi')).not.toBeInTheDocument();
  });

  it('AC-8b: clearing the query-set picker via the Clear button hides the badge', async () => {
    const qs = makeQuerySet('qs-1', 'Primary set');
    useQuerySetsHandler({ probeRows: [qs], pickerRows: [qs] });
    useReadinessHandler(() => ({ body: readiness('rung_2') }));
    wrap(
      <ClusterDetailUbiReadinessCard cluster={{ ...BASE_CLUSTER, target_filter: 'products*' }} />,
    );
    await screen.findByTestId('ubi-rung-badge', undefined, { timeout: 3000 });
    fireEvent.click(screen.getByTestId('cluster-detail-ubi-clear-query-set'));
    await waitFor(() => expect(screen.queryByTestId('ubi-rung-badge')).not.toBeInTheDocument(), {
      timeout: 3000,
    });
  });

  it('AC-9: the card source contains no inline rung string literals (enum discipline)', () => {
    const cardSource = readFileSync(
      join(process.cwd(), 'src', 'components', 'clusters', 'cluster-detail-ubi-readiness-card.tsx'),
      'utf8',
    );
    const matches = cardSource.match(/['"`]rung_[0-3]['"`]/g) ?? [];
    expect(matches).toHaveLength(0);
  });
});
