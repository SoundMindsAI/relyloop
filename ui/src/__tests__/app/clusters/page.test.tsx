import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type ReactNode } from 'react';

import { server } from '../../setup';

const API_BASE = 'http://api.test';

vi.mock('next/link', () => ({
  default: ({ children, href }: { children: ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

async function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { default: Page } = await import('@/app/clusters/page');
  return render(
    <QueryClientProvider client={qc}>
      <Page />
    </QueryClientProvider>,
  );
}

describe('ClustersPage', () => {
  it('renders cluster rows + health badges', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/clusters`, () =>
        HttpResponse.json(
          {
            data: [
              {
                id: 'c1',
                name: 'local-es',
                engine_type: 'elasticsearch',
                environment: 'dev',
                base_url: 'http://localhost:9200',
                auth_kind: 'es_apikey',
                created_at: '2026-05-12T00:00:00Z',
                health_check: {
                  status: 'green',
                  version: '9.4.0',
                  checked_at: '2026-05-12T00:00:00Z',
                  error: null,
                },
              },
            ],
            next_cursor: null,
            has_more: false,
          },
          { headers: { 'X-Total-Count': '1' } },
        ),
      ),
    );
    await renderPage();
    await waitFor(() => expect(screen.getByTestId('cluster-row-c1')).toBeInTheDocument());
    expect(screen.getByText('local-es')).toBeInTheDocument();
  });
});
