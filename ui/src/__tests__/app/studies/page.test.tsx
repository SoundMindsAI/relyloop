import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type ReactNode } from 'react';

import { server } from '../../setup';

const API_BASE = 'http://api.test';

let lastReplace = '';
let mockedSearch = '';

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    replace: (url: string) => {
      lastReplace = url;
    },
  }),
  useSearchParams: () => new URLSearchParams(mockedSearch),
}));

vi.mock('next/link', () => ({
  default: ({ children, href }: { children: ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

async function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { default: StudiesPage } = await import('@/app/studies/page');
  return render(
    <QueryClientProvider client={qc}>
      <StudiesPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  lastReplace = '';
  mockedSearch = '';
});

afterEach(() => {
  vi.restoreAllMocks();
});

function studyRows(count = 2) {
  return Array.from({ length: count }, (_, i) => ({
    id: `s${i}`,
    name: `study ${i}`,
    cluster_id: `c${i}`,
    status: 'running' as const,
    best_metric: 0.5 + i * 0.1,
    created_at: '2026-05-12T00:00:00Z',
    completed_at: null,
  }));
}

describe('StudiesPage', () => {
  it('renders rows from the API', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/studies`, () =>
        HttpResponse.json(
          { data: studyRows(2), next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '2' } },
        ),
      ),
    );
    await renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('study-row-s0')).toBeInTheDocument();
      expect(screen.getByTestId('study-row-s1')).toBeInTheDocument();
    });
    expect(screen.getByTestId('total-count')).toHaveTextContent('2');
  });

  it('clicking a status chip updates the URL', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/studies`, () =>
        HttpResponse.json(
          { data: [], next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '0' } },
        ),
      ),
    );
    await renderPage();
    await waitFor(() => expect(screen.getByTestId('studies-empty')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('status-chip-running'));
    expect(lastReplace).toBe('/studies?status=running');
  });
});
