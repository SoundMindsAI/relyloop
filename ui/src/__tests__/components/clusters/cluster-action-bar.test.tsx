import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type ReactNode } from 'react';

import { server } from '../../setup';
import { ClusterActionBar } from '@/components/clusters/cluster-action-bar';
import { useCluster, useClusters, useClusterSchema, type ClusterDetail } from '@/lib/api/clusters';

const API_BASE = 'http://api.test';

let lastPush = '';
vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: (url: string) => {
      lastPush = url;
    },
  }),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const CLUSTER: ClusterDetail = {
  id: 'c-1',
  name: 'local-es',
  engine_type: 'elasticsearch',
  environment: 'dev',
  base_url: 'http://localhost:9200',
  auth_kind: 'es_apikey',
  engine_config: null,
  notes: null,
  created_at: '2026-05-13T00:00:00Z',
  health_check: {
    status: 'green',
    version: '9.4.0',
    checked_at: '2026-05-13T00:00:00Z',
    error: null,
  },
};

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

beforeEach(() => {
  lastPush = '';
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('ClusterActionBar', () => {
  it('keeps the confirm button disabled until the typed name matches', async () => {
    wrap(<ClusterActionBar cluster={CLUSTER} />);
    fireEvent.click(screen.getByTestId('delete-cluster'));
    const confirm = await screen.findByTestId('confirm-delete');
    expect(confirm).toBeDisabled();
    const input = screen.getByTestId('confirm-name-input') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'wrong' } });
    expect(confirm).toBeDisabled();
    fireEvent.change(input, { target: { value: 'local-es' } });
    expect(confirm).not.toBeDisabled();
  });

  it('DELETEs the cluster + navigates back to /clusters on success', async () => {
    let deleteCalled = false;
    server.use(
      http.delete(`${API_BASE}/api/v1/clusters/c-1`, () => {
        deleteCalled = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    wrap(<ClusterActionBar cluster={CLUSTER} />);
    fireEvent.click(screen.getByTestId('delete-cluster'));
    const input = await screen.findByTestId('confirm-name-input');
    fireEvent.change(input, { target: { value: 'local-es' } });
    fireEvent.click(screen.getByTestId('confirm-delete'));
    await waitFor(() => expect(deleteCalled).toBe(true));
    await waitFor(() => expect(lastPush).toBe('/clusters'));
  });

  // Helper: drive the dialog through to a successful delete + navigation.
  async function deleteAndNavigate() {
    fireEvent.click(screen.getByTestId('delete-cluster'));
    const input = await screen.findByTestId('confirm-name-input');
    fireEvent.change(input, { target: { value: 'local-es' } });
    fireEvent.click(screen.getByTestId('confirm-delete'));
    await waitFor(() => expect(lastPush).toBe('/clusters'));
    // Give any pending TanStack refetch enough time to fire before we sample.
    // 50ms is generous vs. TanStack's internal microtask scheduling but fast
    // enough to keep the test suite snappy.
    await new Promise((resolve) => setTimeout(resolve, 50));
  }

  it('does not refetch the deleted cluster detail after a successful delete', async () => {
    // Regression: prior to the targeted invalidate, useDeleteCluster ran
    // `qc.invalidateQueries({ queryKey: ['clusters'] })` which prefix-matched
    // the still-mounted `useCluster(id)` subscription on /clusters/[id] and
    // fired a GET /clusters/{id} → 404 before the call-site could router.push
    // away. We assert here that exactly one GET fires (the initial mount) and
    // no second GET is triggered after the DELETE succeeds.
    let getCount = 0;
    server.use(
      http.get(`${API_BASE}/api/v1/clusters/c-1`, () => {
        getCount += 1;
        return HttpResponse.json(CLUSTER);
      }),
      http.delete(`${API_BASE}/api/v1/clusters/c-1`, () => new HttpResponse(null, { status: 204 })),
    );

    function Harness() {
      useCluster('c-1');
      return <ClusterActionBar cluster={CLUSTER} />;
    }
    wrap(<Harness />);
    await waitFor(() => expect(getCount).toBe(1));

    await deleteAndNavigate();
    expect(getCount).toBe(1);
  });

  it('refetches the clusters list after a successful delete', async () => {
    // Positive case for the predicate: list-shaped query keys
    // (['clusters', { cursor, limit, since }]) must still be invalidated, or
    // the /clusters page would stay stale and show the just-deleted row.
    let listGetCount = 0;
    server.use(
      http.get(`${API_BASE}/api/v1/clusters`, () => {
        listGetCount += 1;
        return HttpResponse.json(
          { items: [], next_cursor: null },
          { headers: { 'X-Total-Count': '0' } },
        );
      }),
      http.delete(`${API_BASE}/api/v1/clusters/c-1`, () => new HttpResponse(null, { status: 204 })),
    );

    function Harness() {
      useClusters();
      return <ClusterActionBar cluster={CLUSTER} />;
    }
    wrap(<Harness />);
    await waitFor(() => expect(listGetCount).toBe(1));

    await deleteAndNavigate();
    // Predicate-scoped invalidate must mark the list query stale; since it's
    // still actively subscribed, TanStack refetches it.
    await waitFor(() => expect(listGetCount).toBe(2));
  });

  it('does not refetch a different cluster detail when one cluster is deleted', async () => {
    // Negative case for the predicate: deleting cluster c-1 must not touch
    // the cache entry for an unrelated cluster c-2. A naive
    // invalidateQueries(['clusters']) would refetch c-2 too.
    let cluster1Count = 0;
    let cluster2Count = 0;
    const OTHER = { ...CLUSTER, id: 'c-2', name: 'other-es' };
    server.use(
      http.get(`${API_BASE}/api/v1/clusters/c-1`, () => {
        cluster1Count += 1;
        return HttpResponse.json(CLUSTER);
      }),
      http.get(`${API_BASE}/api/v1/clusters/c-2`, () => {
        cluster2Count += 1;
        return HttpResponse.json(OTHER);
      }),
      http.delete(`${API_BASE}/api/v1/clusters/c-1`, () => new HttpResponse(null, { status: 204 })),
    );

    function Harness() {
      useCluster('c-1');
      useCluster('c-2');
      return <ClusterActionBar cluster={CLUSTER} />;
    }
    wrap(<Harness />);
    await waitFor(() => expect(cluster1Count).toBe(1));
    await waitFor(() => expect(cluster2Count).toBe(1));

    await deleteAndNavigate();
    expect(cluster1Count).toBe(1); // removed from cache, no refetch
    expect(cluster2Count).toBe(1); // skipped by the predicate
  });

  it('drops the deleted cluster schema query so it does not refetch', async () => {
    // removeQueries(['clusters', deletedId]) prefix-matches the schema
    // sub-key (['clusters', deletedId, 'schema', target]) — so a still-mounted
    // useClusterSchema subscription doesn't fire a GET /schema → 404 either.
    let schemaCount = 0;
    server.use(
      http.get(`${API_BASE}/api/v1/clusters/c-1/schema`, () => {
        schemaCount += 1;
        return HttpResponse.json({ fields: {} });
      }),
      http.delete(`${API_BASE}/api/v1/clusters/c-1`, () => new HttpResponse(null, { status: 204 })),
    );

    function Harness() {
      useClusterSchema('c-1', 'products');
      return <ClusterActionBar cluster={CLUSTER} />;
    }
    wrap(<Harness />);
    await waitFor(() => expect(schemaCount).toBe(1));

    await deleteAndNavigate();
    expect(schemaCount).toBe(1);
  });

  it('keeps the dialog open and shows no navigation on a failed delete', async () => {
    server.use(
      http.delete(`${API_BASE}/api/v1/clusters/c-1`, () =>
        HttpResponse.json(
          {
            detail: {
              error_code: 'CLUSTER_HAS_DEPENDENTS',
              message: 'cluster has open studies',
              retryable: false,
            },
          },
          { status: 409 },
        ),
      ),
    );
    wrap(<ClusterActionBar cluster={CLUSTER} />);
    fireEvent.click(screen.getByTestId('delete-cluster'));
    const input = await screen.findByTestId('confirm-name-input');
    fireEvent.change(input, { target: { value: 'local-es' } });
    fireEvent.click(screen.getByTestId('confirm-delete'));
    // Wait for mutation to settle.
    await waitFor(() =>
      expect(screen.getByTestId('confirm-delete')).toHaveTextContent('Delete cluster'),
    );
    expect(lastPush).toBe('');
  });
});
