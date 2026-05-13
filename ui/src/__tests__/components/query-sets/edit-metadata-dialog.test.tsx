/**
 * Component tests for EditMetadataDialog (feat_query_inline_crud Story 4.2).
 *
 * Covers ACs 22 (happy path) + 23 (invalid JSON inline error + no PATCH) + 27
 * (Clear metadata sends exactly {query_metadata: null}).
 */
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type ReactNode } from 'react';
import { toast } from 'sonner';

import { server } from '../../setup';
import { EditMetadataDialog } from '@/components/query-sets/edit-metadata-dialog';
import type { QueryRow } from '@/lib/api/query-sets';

const API_BASE = 'http://api.test';
const QS_ID = 'qs-1';

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

const baseQuery: QueryRow = {
  id: '01935b9a-0000-7000-8000-000000000001',
  query_text: 'q',
  reference_answer: null,
  query_metadata: { intent: 'commercial', priority: 'high' },
  judgment_count: 0,
};

describe('EditMetadataDialog', () => {
  it('happy path — saves whole-object replace', async () => {
    const toastSpy = vi.spyOn(toast, 'success');
    let captured: Record<string, unknown> | null = null;
    server.use(
      http.patch(
        `${API_BASE}/api/v1/query-sets/${QS_ID}/queries/${baseQuery.id}`,
        async ({ request }) => {
          captured = (await request.json()) as Record<string, unknown>;
          return HttpResponse.json({ ...baseQuery, query_metadata: { intent: 'info' } });
        },
      ),
    );

    wrap(
      <EditMetadataDialog
        querySetId={QS_ID}
        query={baseQuery}
        open={true}
        onOpenChange={() => {}}
      />,
    );

    fireEvent.change(screen.getByTestId('edit-metadata-textarea'), {
      target: { value: '{"intent":"info"}' },
    });
    fireEvent.click(screen.getByTestId('save-metadata-button'));

    await waitFor(() => expect(captured).not.toBeNull());
    expect(captured).toEqual({ query_metadata: { intent: 'info' } });
    await waitFor(() => expect(toastSpy).toHaveBeenCalledWith('Metadata updated'));
    toastSpy.mockRestore();
  });

  it('invalid JSON shows inline error and does NOT send PATCH', async () => {
    let patchCalls = 0;
    server.use(
      http.patch(`${API_BASE}/api/v1/query-sets/${QS_ID}/queries/${baseQuery.id}`, () => {
        patchCalls += 1;
        return HttpResponse.json(baseQuery);
      }),
    );

    wrap(
      <EditMetadataDialog
        querySetId={QS_ID}
        query={baseQuery}
        open={true}
        onOpenChange={() => {}}
      />,
    );

    fireEvent.change(screen.getByTestId('edit-metadata-textarea'), {
      target: { value: '{not valid json}' },
    });
    fireEvent.click(screen.getByTestId('save-metadata-button'));

    await waitFor(() => expect(screen.getByTestId('metadata-json-error')).toBeInTheDocument());
    expect(screen.getByTestId('metadata-json-error').textContent).toContain('Invalid JSON');
    await new Promise((r) => setTimeout(r, 20));
    expect(patchCalls).toBe(0);
  });

  it.each([
    ['array', '[1, 2, 3]'],
    ['number', '42'],
    ['string', '"hello"'],
    ['null', 'null'],
  ])('rejects non-object JSON (%s) inline and does NOT send PATCH', async (_label, value) => {
    let patchCalls = 0;
    server.use(
      http.patch(`${API_BASE}/api/v1/query-sets/${QS_ID}/queries/${baseQuery.id}`, () => {
        patchCalls += 1;
        return HttpResponse.json(baseQuery);
      }),
    );
    wrap(
      <EditMetadataDialog
        querySetId={QS_ID}
        query={baseQuery}
        open={true}
        onOpenChange={() => {}}
      />,
    );
    fireEvent.change(screen.getByTestId('edit-metadata-textarea'), { target: { value } });
    fireEvent.click(screen.getByTestId('save-metadata-button'));
    await waitFor(() => expect(screen.getByTestId('metadata-json-error')).toBeInTheDocument());
    expect(screen.getByTestId('metadata-json-error').textContent).toContain(
      'must be a JSON object',
    );
    await new Promise((r) => setTimeout(r, 20));
    expect(patchCalls).toBe(0);
  });

  it('Clear metadata sends exactly {query_metadata: null}', async () => {
    const toastSpy = vi.spyOn(toast, 'success');
    let captured: Record<string, unknown> | null = null;
    server.use(
      http.patch(
        `${API_BASE}/api/v1/query-sets/${QS_ID}/queries/${baseQuery.id}`,
        async ({ request }) => {
          captured = (await request.json()) as Record<string, unknown>;
          return HttpResponse.json({ ...baseQuery, query_metadata: null });
        },
      ),
    );

    wrap(
      <EditMetadataDialog
        querySetId={QS_ID}
        query={baseQuery}
        open={true}
        onOpenChange={() => {}}
      />,
    );

    fireEvent.click(screen.getByTestId('clear-metadata-button'));

    await waitFor(() => expect(captured).not.toBeNull());
    // Must be exactly {query_metadata: null} — NOT {} (empty body is a no-op
    // by spec, but here we want explicit null to clear the column).
    expect(captured).toEqual({ query_metadata: null });
    await waitFor(() => expect(toastSpy).toHaveBeenCalledWith('Metadata cleared'));
    toastSpy.mockRestore();
  });
});
