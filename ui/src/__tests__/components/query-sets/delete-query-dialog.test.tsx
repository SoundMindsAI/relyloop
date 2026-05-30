// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Component tests for DeleteQueryDialog (feat_query_inline_crud Story 4.3).
 *
 * Covers AC-20 (409 toast with action link) + happy-path 204 + non-409 fall
 * through to toToastMessage + XSS-safety on the affected-list name.
 */
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type ReactNode } from 'react';
import { toast } from 'sonner';

import { server } from '../../setup';
import { DeleteQueryDialog } from '@/components/query-sets/delete-query-dialog';
import { Button } from '@/components/ui/button';
import type { QueryRow } from '@/lib/api/query-sets';

const API_BASE = 'http://api.test';
const QS_ID = 'qs-1';

const pushMock = vi.fn();
vi.mock('next/navigation', () => ({
  usePathname: () => '/test',
  useRouter: () => ({ push: pushMock }),
}));

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

const baseQuery: QueryRow = {
  id: '01935b9a-0000-7000-8000-000000000001',
  query_text: 'q',
  reference_answer: null,
  query_metadata: null,
  judgment_count: 0,
};

describe('DeleteQueryDialog', () => {
  it('happy path 204 → success toast and dialog closes', async () => {
    const toastSpy = vi.spyOn(toast, 'success');
    let deleteCalls = 0;
    server.use(
      http.delete(`${API_BASE}/api/v1/query-sets/${QS_ID}/queries/${baseQuery.id}`, () => {
        deleteCalls += 1;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    wrap(
      <DeleteQueryDialog
        querySetId={QS_ID}
        query={baseQuery}
        trigger={<Button data-testid="open-delete">Delete</Button>}
      />,
    );
    fireEvent.click(screen.getByTestId('open-delete'));
    await waitFor(() => expect(screen.getByTestId('confirm-delete-query')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('confirm-delete-query'));
    await waitFor(() => expect(deleteCalls).toBe(1));
    await waitFor(() => expect(toastSpy).toHaveBeenCalledWith('Query deleted'));
    toastSpy.mockRestore();
  });

  it('409 QUERY_HAS_JUDGMENTS → toast with action link, dialog stays open', async () => {
    const errorSpy = vi.spyOn(toast, 'error');
    pushMock.mockReset();
    server.use(
      http.delete(`${API_BASE}/api/v1/query-sets/${QS_ID}/queries/${baseQuery.id}`, () =>
        HttpResponse.json(
          {
            detail: {
              error_code: 'QUERY_HAS_JUDGMENTS',
              message: 'query x has 5 judgments across 2 lists',
              retryable: false,
              judgment_lists: [
                { id: 'jl-1', name: 'esci-tutorial-v1' },
                { id: 'jl-2', name: 'esci-tutorial-v2' },
              ],
              overflow_count: 0,
            },
          },
          { status: 409 },
        ),
      ),
    );

    wrap(
      <DeleteQueryDialog
        querySetId={QS_ID}
        query={baseQuery}
        trigger={<Button data-testid="open-delete">Delete</Button>}
      />,
    );

    fireEvent.click(screen.getByTestId('open-delete'));
    await waitFor(() => expect(screen.getByTestId('confirm-delete-query')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('confirm-delete-query'));

    await waitFor(() => expect(errorSpy).toHaveBeenCalled());
    const [message, options] = errorSpy.mock.calls[0]!;
    const action = options?.action as { label: string; onClick: (e: unknown) => void } | undefined;
    expect(String(message)).toContain('2 judgment lists');
    expect(action?.label).toBe('Open esci-tutorial-v1 →');

    // Click the action label → navigates to /judgments/{first_id}
    action?.onClick?.(new MouseEvent('click'));
    expect(pushMock).toHaveBeenCalledWith('/judgments/jl-1');

    errorSpy.mockRestore();
  });

  it('409 with overflow_count > 0 includes the overflow phrase', async () => {
    const errorSpy = vi.spyOn(toast, 'error');
    server.use(
      http.delete(`${API_BASE}/api/v1/query-sets/${QS_ID}/queries/${baseQuery.id}`, () =>
        HttpResponse.json(
          {
            detail: {
              error_code: 'QUERY_HAS_JUDGMENTS',
              message: 'x',
              retryable: false,
              judgment_lists: Array.from({ length: 10 }, (_, i) => ({
                id: `jl-${i}`,
                name: `list-${i}`,
              })),
              overflow_count: 5,
            },
          },
          { status: 409 },
        ),
      ),
    );
    wrap(
      <DeleteQueryDialog
        querySetId={QS_ID}
        query={baseQuery}
        trigger={<Button data-testid="open-delete">Delete</Button>}
      />,
    );
    fireEvent.click(screen.getByTestId('open-delete'));
    await waitFor(() => expect(screen.getByTestId('confirm-delete-query')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('confirm-delete-query'));

    await waitFor(() => expect(errorSpy).toHaveBeenCalled());
    const [message] = errorSpy.mock.calls[0]!;
    expect(String(message)).toContain('15 judgment lists');
    expect(String(message)).toContain('5 more not shown');
    errorSpy.mockRestore();
  });

  it('XSS-safety — judgment-list name with HTML renders as text only', async () => {
    const errorSpy = vi.spyOn(toast, 'error');
    const evilName = "<script>alert('xss')</script>";
    server.use(
      http.delete(`${API_BASE}/api/v1/query-sets/${QS_ID}/queries/${baseQuery.id}`, () =>
        HttpResponse.json(
          {
            detail: {
              error_code: 'QUERY_HAS_JUDGMENTS',
              message: 'x',
              retryable: false,
              judgment_lists: [{ id: 'jl-1', name: evilName }],
              overflow_count: 0,
            },
          },
          { status: 409 },
        ),
      ),
    );
    wrap(
      <DeleteQueryDialog
        querySetId={QS_ID}
        query={baseQuery}
        trigger={<Button data-testid="open-delete">Delete</Button>}
      />,
    );
    fireEvent.click(screen.getByTestId('open-delete'));
    await waitFor(() => expect(screen.getByTestId('confirm-delete-query')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('confirm-delete-query'));

    await waitFor(() => expect(errorSpy).toHaveBeenCalled());
    const [, options] = errorSpy.mock.calls[0]!;
    const action = options?.action as { label: string; onClick: (e: unknown) => void } | undefined;
    // Sonner gets the action label as a plain string — React/Sonner will text-render it
    // (not as HTML). The string itself contains the literal characters; what matters is
    // that no injected <script> node appears in the document.
    expect(action?.label).toBe(`Open ${evilName} →`);
    expect(document.querySelector('script[data-test-injected]')).toBeNull();
    errorSpy.mockRestore();
  });

  it('non-409 error falls through to toToastMessage formatting', async () => {
    const errorSpy = vi.spyOn(toast, 'error');
    server.use(
      http.delete(`${API_BASE}/api/v1/query-sets/${QS_ID}/queries/${baseQuery.id}`, () =>
        HttpResponse.json(
          {
            detail: {
              error_code: 'QUERY_SET_NOT_FOUND',
              message: 'query set qs-1 not found',
              retryable: false,
            },
          },
          { status: 404 },
        ),
      ),
    );
    wrap(
      <DeleteQueryDialog
        querySetId={QS_ID}
        query={baseQuery}
        trigger={<Button data-testid="open-delete">Delete</Button>}
      />,
    );
    fireEvent.click(screen.getByTestId('open-delete'));
    await waitFor(() => expect(screen.getByTestId('confirm-delete-query')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('confirm-delete-query'));

    await waitFor(() => expect(errorSpy).toHaveBeenCalled());
    const [message] = errorSpy.mock.calls[0]!;
    expect(String(message)).toContain('QUERY_SET_NOT_FOUND');
    errorSpy.mockRestore();
  });
});
