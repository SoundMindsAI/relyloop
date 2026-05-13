/**
 * Component tests for QueriesTable (feat_query_inline_crud Story 4.1).
 *
 * Covers AC-18 (render + paginate). Overlay-opening (Edit / Metadata / Delete)
 * has its own dedicated test file per story; this file asserts the table renders
 * the trio of icon-buttons with correct aria-labels.
 */
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type ReactNode } from 'react';

import { server } from '../../setup';
import { QueriesTable } from '@/components/query-sets/queries-table';

// next/navigation isn't bound to a Next runtime in vitest — mock useRouter
// because <DeleteQueryDialog> (rendered inside each row) calls it at mount.
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: () => {} }),
}));

const API_BASE = 'http://api.test';
const QS_ID = 'qs-1';

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

function rowFixture(idx: number) {
  return {
    id: `01935b9a-0000-7000-8000-${idx.toString().padStart(12, '0')}`,
    query_text: `query-${idx}`,
    reference_answer: idx % 2 === 0 ? null : `ref-${idx}`,
    query_metadata: idx % 2 === 0 ? { i: idx } : null,
    judgment_count: idx,
  };
}

describe('QueriesTable', () => {
  it('renders rows with judgment_count and total count', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/query-sets/${QS_ID}/queries`, () =>
        HttpResponse.json(
          {
            data: [rowFixture(0), rowFixture(1), rowFixture(2)],
            next_cursor: null,
            has_more: false,
          },
          { headers: { 'X-Total-Count': '3' } },
        ),
      ),
    );
    wrap(<QueriesTable querySetId={QS_ID} />);

    await waitFor(() => expect(screen.getByTestId('queries-table')).toBeInTheDocument());

    expect(screen.getByText('query-0')).toBeInTheDocument();
    expect(screen.getByText('query-1')).toBeInTheDocument();
    expect(screen.getByText('ref-1')).toBeInTheDocument();
    // Reference-answer null shows the em-dash sentinel.
    const dashCells = screen.getAllByText('—');
    expect(dashCells.length).toBeGreaterThan(0);
  });

  it('renders Edit / Metadata / Delete icon buttons with correct aria-labels', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/query-sets/${QS_ID}/queries`, () =>
        HttpResponse.json(
          { data: [rowFixture(0)], next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '1' } },
        ),
      ),
    );
    wrap(<QueriesTable querySetId={QS_ID} />);

    await waitFor(() => expect(screen.getByLabelText('Edit query')).toBeInTheDocument());
    expect(screen.getByLabelText('Edit query metadata')).toBeInTheDocument();
    expect(screen.getByLabelText('Delete query')).toBeInTheDocument();
  });

  it('shows EmptyState when no queries', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/query-sets/${QS_ID}/queries`, () =>
        HttpResponse.json(
          { data: [], next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '0' } },
        ),
      ),
    );
    wrap(<QueriesTable querySetId={QS_ID} />);
    await waitFor(() => expect(screen.getByText(/No queries yet/i)).toBeInTheDocument());
  });

  it('paginates Next then Prev correctly', async () => {
    let getCalls = 0;
    server.use(
      http.get(`${API_BASE}/api/v1/query-sets/${QS_ID}/queries`, ({ request }) => {
        const url = new URL(request.url);
        const cursor = url.searchParams.get('cursor');
        getCalls += 1;
        if (cursor === 'page2-cursor') {
          return HttpResponse.json(
            { data: [rowFixture(3)], next_cursor: null, has_more: false },
            { headers: { 'X-Total-Count': '4' } },
          );
        }
        return HttpResponse.json(
          {
            data: [rowFixture(0), rowFixture(1), rowFixture(2)],
            next_cursor: 'page2-cursor',
            has_more: true,
          },
          { headers: { 'X-Total-Count': '4' } },
        );
      }),
    );
    wrap(<QueriesTable querySetId={QS_ID} />);
    await waitFor(() => expect(screen.getByText('query-0')).toBeInTheDocument());

    fireEvent.click(screen.getByTestId('paginator-next'));
    await waitFor(() => expect(screen.getByText('query-3')).toBeInTheDocument());
    expect(screen.queryByText('query-0')).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId('paginator-prev'));
    await waitFor(() => expect(screen.getByText('query-0')).toBeInTheDocument());

    expect(getCalls).toBeGreaterThanOrEqual(3);
  });
});
