// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { http, HttpResponse } from 'msw';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type ReactNode } from 'react';

import { server } from '../setup';

const API_BASE = 'http://api.test';

vi.mock('next/link', () => ({
  default: ({ children, href, ...rest }: { children: ReactNode; href: string }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

afterEach(() => vi.restoreAllMocks());

async function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { default: Page } = await import('@/app/page');
  return render(
    <QueryClientProvider client={qc}>
      <Page />
    </QueryClientProvider>,
  );
}

describe('Dashboard page', () => {
  it('renders recent studies + count cards (X-Total-Count drives the counts)', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/studies`, ({ request }) => {
        const url = new URL(request.url);
        const status = url.searchParams.get('status');
        const totalCount = status === 'completed' ? '3' : '5';
        return HttpResponse.json(
          {
            data:
              status === 'completed'
                ? []
                : [
                    {
                      id: 's1',
                      name: 'demo-1',
                      cluster_id: 'c1',
                      status: 'running',
                      best_metric: 0.55,
                      created_at: '2026-05-12T00:00:00Z',
                      completed_at: null,
                    },
                  ],
            next_cursor: null,
            has_more: false,
          },
          { headers: { 'X-Total-Count': totalCount } },
        );
      }),
      http.get(`${API_BASE}/api/v1/proposals`, () =>
        HttpResponse.json(
          { data: [], next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '2' } },
        ),
      ),
    );

    await renderPage();
    await waitFor(() => expect(screen.getByTestId('recent-study-s1')).toBeInTheDocument());
    expect(screen.getByTestId('card-open-proposals')).toHaveTextContent('2');
    expect(screen.getByTestId('card-completed-recent')).toHaveTextContent('3');
  });

  it('shows the backend-unreachable empty state when all three queries fail', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/studies`, () =>
        HttpResponse.json(
          { detail: { error_code: 'INTERNAL_ERROR', message: 'down', retryable: false } },
          { status: 500 },
        ),
      ),
      http.get(`${API_BASE}/api/v1/proposals`, () =>
        HttpResponse.json(
          { detail: { error_code: 'INTERNAL_ERROR', message: 'down', retryable: false } },
          { status: 500 },
        ),
      ),
    );
    await renderPage();
    await waitFor(() => expect(screen.getByText(/Backend unreachable/i)).toBeInTheDocument());
  });
});
