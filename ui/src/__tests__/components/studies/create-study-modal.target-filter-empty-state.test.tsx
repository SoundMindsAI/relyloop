// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * feat_cluster_target_filter Story F2 — create-study modal target picker's
 * empty-state message branches on the selected cluster's `target_filter`.
 *
 * AC-13: when target_filter is non-null AND the targets endpoint returns
 *        an empty `data` array, the dropdown's empty-state message names
 *        the filter and tells the operator how to change it.
 * AC-14: when target_filter is null AND the targets endpoint returns
 *        an empty `data` array, the existing message is preserved
 *        (regression-safe).
 */
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type ReactNode } from 'react';

import { TooltipProvider } from '@/components/ui/tooltip';

import { server } from '../../setup';

// Same Radix-Select-in-Dialog escape hatch the sibling create-study-modal
// tests use — keeps assertions on user-visible text, not Radix internals.
vi.mock('@/components/ui/select', async () => {
  const { mockShadcnSelect } = await import('../../helpers/shadcn-select-mock');
  return mockShadcnSelect();
});

const { CreateStudyModal } = await import('@/components/studies/create-study-modal');

const API_BASE = 'http://api.test';

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider delayDuration={0}>{node}</TooltipProvider>
    </QueryClientProvider>,
  );
}

function clusterRow(opts: { id: string; name: string; target_filter: string | null }) {
  return {
    id: opts.id,
    name: opts.name,
    engine_type: 'elasticsearch',
    environment: 'dev',
    base_url: 'http://localhost:9200',
    auth_kind: 'es_apikey',
    target_filter: opts.target_filter,
    created_at: '2026-05-20T00:00:00Z',
    health_check: {
      status: 'green',
      version: '9.4.0',
      checked_at: '2026-05-20T00:00:00Z',
      error: null,
    },
  };
}

function emptyTargetsBackend(opts: { clusterId: string; targetFilter: string | null }) {
  server.use(
    http.get(`${API_BASE}/api/v1/clusters`, () =>
      HttpResponse.json(
        {
          data: [
            clusterRow({
              id: opts.clusterId,
              name: 'filtered-es',
              target_filter: opts.targetFilter,
            }),
          ],
          next_cursor: null,
          has_more: false,
        },
        { headers: { 'X-Total-Count': '1' } },
      ),
    ),
    http.get(`${API_BASE}/api/v1/clusters/${opts.clusterId}/targets`, () =>
      HttpResponse.json({ data: [] }),
    ),
    http.get(`${API_BASE}/api/v1/query-sets`, () =>
      HttpResponse.json(
        { data: [], next_cursor: null, has_more: false },
        { headers: { 'X-Total-Count': '0' } },
      ),
    ),
    http.get(`${API_BASE}/api/v1/query-templates`, () =>
      HttpResponse.json(
        { data: [], next_cursor: null, has_more: false },
        { headers: { 'X-Total-Count': '0' } },
      ),
    ),
    http.get(`${API_BASE}/api/v1/judgment-lists`, () =>
      HttpResponse.json(
        { data: [], next_cursor: null, has_more: false },
        { headers: { 'X-Total-Count': '0' } },
      ),
    ),
  );
}

async function pickCluster(clusterId: string) {
  await waitFor(() =>
    expect(screen.getByRole('option', { name: /filtered-es/ })).toBeInTheDocument(),
  );
  fireEvent.change(screen.getByLabelText('Cluster'), { target: { value: clusterId } });
}

describe('CreateStudyModal target picker — filter-aware empty state', () => {
  it('shows the filter-specific message when target_filter is set and no targets match (AC-13)', async () => {
    emptyTargetsBackend({ clusterId: 'c1', targetFilter: 'non-matching-*' });
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await pickCluster('c1');
    await waitFor(() => {
      // The disabled-trigger placeholder text in EntitySelect's empty state
      // names the filter and points the operator at the workaround.
      expect(
        screen.getByText(/No targets match filter "non-matching-\*" on this cluster/i),
      ).toBeInTheDocument();
    });
    expect(
      screen.getByText(/delete and re-register the cluster — MVP1 has no in-place edit/i),
    ).toBeInTheDocument();
  });

  it('shows the original message when target_filter is null and no targets exist (AC-14)', async () => {
    emptyTargetsBackend({ clusterId: 'c1', targetFilter: null });
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await pickCluster('c1');
    await waitFor(() => {
      expect(screen.getByText('No targets found on this cluster.')).toBeInTheDocument();
    });
    // And the filter-specific copy must NOT appear.
    expect(screen.queryByText(/No targets match filter/i)).not.toBeInTheDocument();
  });
});
