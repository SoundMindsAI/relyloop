import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type ReactNode } from 'react';

import { server } from '../../setup';
import { ClusterActionBar } from '@/components/clusters/cluster-action-bar';
import type { ClusterDetail } from '@/lib/api/clusters';

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
