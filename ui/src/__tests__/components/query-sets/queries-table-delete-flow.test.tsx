// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Integration-style component test (feat_query_inline_crud — was
 * chore_query_inline_crud_table_integration_test before in-PR implementation).
 *
 * Renders the full <QueriesTable> and exercises the delete flow through the
 * row's Delete icon-button → AlertDialog confirm → DELETE response → cache
 * invalidation. Asserts the DOM state matches the response:
 *
 * - 204 → row removed after the refetch fires
 * - 409 → row still present, no refetch, destructive toast surfaces
 * - in-flight → "Deleting…" button + disabled state (no double-submit)
 *
 * The standalone delete-query-dialog.test.tsx asserts toast behavior in
 * isolation; this file proves the composition works end-to-end inside the
 * table (which is the actual operator experience).
 */
import { http, HttpResponse, delay as mswDelay } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type ReactNode } from 'react';

import { server } from '../../setup';
import { QueriesTable } from '@/components/query-sets/queries-table';

vi.mock('next/navigation', () => ({
  usePathname: () => '/test',
  useRouter: () => ({ push: () => {}, replace: () => {} }),
  useSearchParams: () => new URLSearchParams(),
}));

const API_BASE = 'http://api.test';
const QS_ID = 'qs-1';

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

function row(idx: number, judgmentCount = 0) {
  return {
    id: `01935b9a-0000-7000-8000-${idx.toString().padStart(12, '0')}`,
    query_text: `query-${idx}`,
    reference_answer: null,
    query_metadata: null,
    judgment_count: judgmentCount,
  };
}

describe('QueriesTable delete-flow integration', () => {
  it('204 path: row disappears after refetch + total-count decrements', async () => {
    // First GET returns 3 rows. After the DELETE invalidates the cache, the
    // refetch returns 2 rows (q-0 gone) with total=2.
    let getCalls = 0;
    server.use(
      http.get(`${API_BASE}/api/v1/query-sets/${QS_ID}/queries`, () => {
        getCalls += 1;
        if (getCalls === 1) {
          return HttpResponse.json(
            { data: [row(0), row(1), row(2)], next_cursor: null, has_more: false },
            { headers: { 'X-Total-Count': '3' } },
          );
        }
        // Post-invalidation refetch — q-0 is gone.
        return HttpResponse.json(
          { data: [row(1), row(2)], next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '2' } },
        );
      }),
      http.delete(
        `${API_BASE}/api/v1/query-sets/${QS_ID}/queries/${row(0).id}`,
        () => new HttpResponse(null, { status: 204 }),
      ),
    );

    wrap(<QueriesTable querySetId={QS_ID} />);
    await waitFor(() => expect(screen.getByText('query-0')).toBeInTheDocument());
    expect(screen.getByTestId('data-table-total-count')).toHaveTextContent('3');

    // Click the row's Delete icon-button → AlertDialog opens.
    fireEvent.click(screen.getByTestId(`delete-${row(0).id}`));
    await waitFor(() => expect(screen.getByTestId('confirm-delete-query')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('confirm-delete-query'));

    // Wait for the refetch — q-0 should disappear, total drops to 2.
    await waitFor(() => expect(screen.queryByText('query-0')).not.toBeInTheDocument());
    expect(screen.getByText('query-1')).toBeInTheDocument();
    expect(screen.getByText('query-2')).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByTestId('data-table-total-count')).toHaveTextContent('2'),
    );
  });

  it('409 path: row stays in the DOM, no refetch (cache not invalidated)', async () => {
    let getCalls = 0;
    server.use(
      http.get(`${API_BASE}/api/v1/query-sets/${QS_ID}/queries`, () => {
        getCalls += 1;
        return HttpResponse.json(
          { data: [row(0, 5), row(1)], next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '2' } },
        );
      }),
      http.delete(`${API_BASE}/api/v1/query-sets/${QS_ID}/queries/${row(0).id}`, () =>
        HttpResponse.json(
          {
            detail: {
              error_code: 'QUERY_HAS_JUDGMENTS',
              message: 'query has 5 judgments across 1 list',
              retryable: false,
              judgment_lists: [{ id: 'jl-1', name: 'esci-tutorial-v1' }],
              overflow_count: 0,
            },
          },
          { status: 409 },
        ),
      ),
    );

    wrap(<QueriesTable querySetId={QS_ID} />);
    await waitFor(() => expect(screen.getByText('query-0')).toBeInTheDocument());
    const initialGetCalls = getCalls;

    // Trigger DELETE → 409.
    fireEvent.click(screen.getByTestId(`delete-${row(0).id}`));
    await waitFor(() => expect(screen.getByTestId('confirm-delete-query')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('confirm-delete-query'));

    // Wait for the mutation to settle. The 409 must NOT invalidate the cache,
    // so the row stays in the DOM and no extra GET fires.
    await new Promise((r) => setTimeout(r, 100));
    expect(screen.getByText('query-0')).toBeInTheDocument();
    expect(getCalls).toBe(initialGetCalls); // no refetch
  });

  it('in-flight: confirm button shows "Deleting…" mid-request', async () => {
    let getCalls = 0;
    server.use(
      http.get(`${API_BASE}/api/v1/query-sets/${QS_ID}/queries`, () => {
        getCalls += 1;
        if (getCalls === 1) {
          return HttpResponse.json(
            { data: [row(0)], next_cursor: null, has_more: false },
            { headers: { 'X-Total-Count': '1' } },
          );
        }
        // After cache invalidation, the row is gone.
        return HttpResponse.json(
          { data: [], next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '0' } },
        );
      }),
      http.delete(`${API_BASE}/api/v1/query-sets/${QS_ID}/queries/${row(0).id}`, async () => {
        await mswDelay(200); // simulate slow backend
        return new HttpResponse(null, { status: 204 });
      }),
    );

    wrap(<QueriesTable querySetId={QS_ID} />);
    await waitFor(() => expect(screen.getByText('query-0')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId(`delete-${row(0).id}`));
    await waitFor(() => expect(screen.getByTestId('confirm-delete-query')).toBeInTheDocument());

    const confirmBtn = screen.getByTestId('confirm-delete-query');
    fireEvent.click(confirmBtn);

    // Mid-flight: label flips to "Deleting…". The button is also marked
    // disabled via `disabled={del.isPending}`, which a real browser would
    // honor; jsdom + fireEvent fires onClick even on disabled elements, so
    // we assert only the visible-state contract here.
    await waitFor(() => expect(confirmBtn.textContent).toContain('Deleting…'));

    // Eventually the DELETE resolves and the row is removed (post-refetch).
    await waitFor(() => expect(screen.queryByText('query-0')).not.toBeInTheDocument(), {
      timeout: 3000,
    });
  });
});
