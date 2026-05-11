import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type ReactNode } from 'react';

import { server } from '../../setup';
import { CreateQuerySetModal } from '@/components/query-sets/create-query-set-modal';

const API_BASE = 'http://api.test';

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

describe('CreateQuerySetModal', () => {
  it('POSTs to /query-sets with the form values', async () => {
    let captured: unknown = null;
    server.use(
      http.post(`${API_BASE}/api/v1/query-sets`, async ({ request }) => {
        captured = await request.json();
        return HttpResponse.json({
          id: 'qs-1',
          name: 'demo',
          description: null,
          cluster_id: 'c-1',
          query_count: 0,
          created_at: '2026-05-12T00:00:00Z',
        });
      }),
    );
    wrap(<CreateQuerySetModal open={true} onOpenChange={() => {}} />);
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'demo' } });
    fireEvent.change(screen.getByLabelText('Cluster ID'), { target: { value: 'c-1' } });
    fireEvent.click(screen.getByTestId('create-query-set-submit'));
    await waitFor(() => expect(captured).not.toBeNull());
    expect(captured).toMatchObject({ name: 'demo', cluster_id: 'c-1' });
  });
});
