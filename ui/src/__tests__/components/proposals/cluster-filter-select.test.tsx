import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type ReactNode } from 'react';

import { server } from '../../setup';
import { ClusterFilterSelect } from '@/components/proposals/cluster-filter-select';

const API_BASE = 'http://api.test';

function renderWithClient(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

function clusterRows(count: number) {
  return Array.from({ length: count }, (_, i) => ({
    id: `c${i}`,
    name: `cluster ${i}`,
    engine_type: 'elasticsearch',
    environment: 'dev',
    config_repo_id: null,
    created_at: '2026-05-12T00:00:00Z',
  }));
}

describe('ClusterFilterSelect', () => {
  it('shows loading state then lists clusters and selects null when "All clusters" is chosen', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/clusters`, () =>
        HttpResponse.json(
          { data: clusterRows(2), next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '2' } },
        ),
      ),
    );
    const onChange = vi.fn();
    renderWithClient(<ClusterFilterSelect value={null} onChange={onChange} />);

    // Loading placeholder rendered first.
    expect(screen.getByTestId('cluster-filter-select')).toBeDisabled();

    await waitFor(() => {
      expect(screen.getByText('cluster 0')).toBeInTheDocument();
      expect(screen.getByText('cluster 1')).toBeInTheDocument();
      expect(screen.getByText('All clusters')).toBeInTheDocument();
    });

    const sel = screen.getByTestId('cluster-filter-select') as HTMLSelectElement;
    expect(sel).not.toBeDisabled();
    fireEvent.change(sel, { target: { value: 'c1' } });
    expect(onChange).toHaveBeenCalledWith('c1');
    fireEvent.change(sel, { target: { value: '' } });
    expect(onChange).toHaveBeenLastCalledWith(null);
  });
});
