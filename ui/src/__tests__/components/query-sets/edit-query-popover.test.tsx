// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Component tests for EditQueryPopover (feat_query_inline_crud Story 4.2).
 *
 * Covers AC-19 (happy-path submit + success toast). PATCH body sent must
 * contain ONLY changed keys (omitted-key semantics).
 */
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type ReactNode } from 'react';
import { toast } from 'sonner';

import { server } from '../../setup';
import { EditQueryPopover } from '@/components/query-sets/edit-query-popover';
import { Button } from '@/components/ui/button';
import type { QueryRow } from '@/lib/api/query-sets';

const API_BASE = 'http://api.test';
const QS_ID = 'qs-1';

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

const baseQuery: QueryRow = {
  id: '01935b9a-0000-7000-8000-000000000001',
  query_text: 'original text',
  reference_answer: 'original ref',
  query_metadata: { intent: 'commercial' },
  judgment_count: 0,
};

describe('EditQueryPopover', () => {
  it('PATCHes only changed fields and shows success toast', async () => {
    const toastSpy = vi.spyOn(toast, 'success');
    let captured: Record<string, unknown> | null = null;
    server.use(
      http.patch(
        `${API_BASE}/api/v1/query-sets/${QS_ID}/queries/${baseQuery.id}`,
        async ({ request }) => {
          captured = (await request.json()) as Record<string, unknown>;
          return HttpResponse.json({ ...baseQuery, query_text: 'new text' });
        },
      ),
    );

    wrap(
      <EditQueryPopover
        querySetId={QS_ID}
        query={baseQuery}
        trigger={<Button data-testid="open-edit">Edit</Button>}
      />,
    );

    fireEvent.click(screen.getByTestId('open-edit'));
    await waitFor(() => expect(screen.getByTestId('edit-query-text')).toBeInTheDocument());

    fireEvent.change(screen.getByTestId('edit-query-text'), {
      target: { value: 'new text' },
    });
    // reference_answer left UNCHANGED — should NOT appear in PATCH body.
    fireEvent.click(screen.getByTestId('edit-query-save'));

    await waitFor(() => expect(captured).not.toBeNull());
    expect(captured).toEqual({ query_text: 'new text' });
    await waitFor(() => expect(toastSpy).toHaveBeenCalledWith('Query updated'));
    toastSpy.mockRestore();
  });

  it('does not send PATCH when no field changed (no-op close)', async () => {
    let patchCalls = 0;
    server.use(
      http.patch(`${API_BASE}/api/v1/query-sets/${QS_ID}/queries/${baseQuery.id}`, () => {
        patchCalls += 1;
        return HttpResponse.json(baseQuery);
      }),
    );

    wrap(
      <EditQueryPopover
        querySetId={QS_ID}
        query={baseQuery}
        trigger={<Button data-testid="open-edit">Edit</Button>}
      />,
    );

    fireEvent.click(screen.getByTestId('open-edit'));
    await waitFor(() => expect(screen.getByTestId('edit-query-save')).toBeInTheDocument());

    // Submit immediately with no edits.
    fireEvent.click(screen.getByTestId('edit-query-save'));
    // Give the form a tick to attempt the PATCH (it won't, but we want to be sure).
    await new Promise((r) => setTimeout(r, 20));
    expect(patchCalls).toBe(0);
  });

  it('clears reference_answer when blanked', async () => {
    let captured: Record<string, unknown> | null = null;
    server.use(
      http.patch(
        `${API_BASE}/api/v1/query-sets/${QS_ID}/queries/${baseQuery.id}`,
        async ({ request }) => {
          captured = (await request.json()) as Record<string, unknown>;
          return HttpResponse.json({ ...baseQuery, reference_answer: null });
        },
      ),
    );

    wrap(
      <EditQueryPopover
        querySetId={QS_ID}
        query={baseQuery}
        trigger={<Button data-testid="open-edit">Edit</Button>}
      />,
    );

    fireEvent.click(screen.getByTestId('open-edit'));
    await waitFor(() => expect(screen.getByTestId('edit-reference-answer')).toBeInTheDocument());

    fireEvent.change(screen.getByTestId('edit-reference-answer'), { target: { value: '' } });
    fireEvent.click(screen.getByTestId('edit-query-save'));

    await waitFor(() => expect(captured).not.toBeNull());
    expect(captured).toEqual({ reference_answer: null });
  });
});
