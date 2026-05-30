// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Component tests for QueriesTable (Story 3.8 DataTable migration).
 *
 * Asserts rendering, the trio of action icon-buttons, empty state, and
 * Next/Prev pagination behaviour against the new useDataTableUrlState
 * contract.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { type ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { QueriesTable } from '@/components/query-sets/queries-table';

import { resetDataTableUrlMock } from '../../helpers/data-table-url-mock';
import { server } from '../../setup';

const API_BASE = 'http://api.test';
const QS_ID = 'qs-1';

vi.mock('next/navigation', async () => {
  const mod = await import('../../helpers/data-table-url-mock');
  return mod.makeNextNavigationMock();
});

beforeEach(() => {
  resetDataTableUrlMock();
});

afterEach(() => vi.restoreAllMocks());

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

describe('QueriesTable (DataTable migration)', () => {
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
    const dashCells = screen.getAllByText('—');
    expect(dashCells.length).toBeGreaterThan(0);
    // Total-count display now lives in the DataTable toolbar (Story 2.5).
    expect(screen.getByTestId('data-table-total-count')).toHaveTextContent('3');
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

  it('shows the no-rows-exist empty state when no queries', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/query-sets/${QS_ID}/queries`, () =>
        HttpResponse.json(
          { data: [], next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '0' } },
        ),
      ),
    );
    wrap(<QueriesTable querySetId={QS_ID} />);
    await waitFor(() =>
      expect(screen.getByTestId('data-table-empty-no-rows-exist')).toBeInTheDocument(),
    );
    expect(screen.getByText(/No queries yet/i)).toBeInTheDocument();
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
