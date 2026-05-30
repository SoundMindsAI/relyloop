// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

import { TooltipProvider } from '@/components/ui/tooltip';

import { server } from '../../setup';

vi.mock('@/components/ui/select', async () => {
  const { mockShadcnSelect } = await import('../../helpers/shadcn-select-mock');
  return mockShadcnSelect();
});

let lastUndoAction: (() => void) | null = null;
const toastSpy = vi.fn(
  (
    _message: string,
    options?: { duration?: number; action?: { label?: string; onClick?: () => void } },
  ) => {
    if (options?.action?.label === 'Undo' && typeof options.action.onClick === 'function') {
      lastUndoAction = options.action.onClick;
    }
  },
);
type ToastFn = ((message: string, options?: Record<string, unknown>) => void) & {
  error: (m: string) => void;
  success: (m: string) => void;
};
const toastStub: ToastFn = Object.assign(toastSpy as unknown as ToastFn, {
  error: (m: string) => toastSpy(m, undefined),
  success: (m: string) => toastSpy(m, undefined),
});
vi.mock('sonner', () => ({ toast: toastStub, Toaster: () => null }));

const { CreateStudyModal } = await import('@/components/studies/create-study-modal');

const API_BASE = 'http://api.test';

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider delayDuration={0}>{node}</TooltipProvider>
    </QueryClientProvider>,
  );
}

function mockTwoTemplates() {
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
    http.get(`${API_BASE}/api/v1/clusters/c1/schema`, () => HttpResponse.json({ fields: [] })),
    http.get(`${API_BASE}/api/v1/clusters/c1/targets`, () =>
      HttpResponse.json({ data: [{ name: 'products', doc_count: 42 }] }),
    ),
    http.get(`${API_BASE}/api/v1/query-sets`, () =>
      HttpResponse.json(
        {
          data: [{ id: 'qs1', name: 'demo', cluster_id: 'c1', created_at: '2026-05-12T00:00:00Z' }],
          next_cursor: null,
          has_more: false,
        },
        { headers: { 'X-Total-Count': '1' } },
      ),
    ),
    http.get(`${API_BASE}/api/v1/judgment-lists`, () =>
      HttpResponse.json(
        {
          data: [
            {
              id: 'jl1',
              name: 'demo',
              description: null,
              query_set_id: 'qs1',
              cluster_id: 'c1',
              status: 'complete',
              created_at: '2026-05-12T00:00:00Z',
            },
          ],
          next_cursor: null,
          has_more: false,
        },
        { headers: { 'X-Total-Count': '1' } },
      ),
    ),
    http.get(`${API_BASE}/api/v1/query-templates`, () =>
      HttpResponse.json(
        {
          data: [
            {
              id: 'tpl1',
              name: 'T1',
              engine_type: 'elasticsearch',
              version: 1,
              created_at: '2026-05-12T00:00:00Z',
            },
            {
              id: 'tpl2',
              name: 'T2',
              engine_type: 'elasticsearch',
              version: 1,
              created_at: '2026-05-12T00:00:00Z',
            },
          ],
          next_cursor: null,
          has_more: false,
        },
        { headers: { 'X-Total-Count': '2' } },
      ),
    ),
    http.get(`${API_BASE}/api/v1/query-templates/tpl1`, () =>
      HttpResponse.json({
        id: 'tpl1',
        name: 'T1',
        engine_type: 'elasticsearch',
        body: '{}',
        declared_params: { boost_title: 'float' },
        version: 1,
        parent_id: null,
        created_at: '2026-05-12T00:00:00Z',
      }),
    ),
    http.get(`${API_BASE}/api/v1/query-templates/tpl2`, () =>
      HttpResponse.json({
        id: 'tpl2',
        name: 'T2',
        engine_type: 'elasticsearch',
        body: '{}',
        declared_params: { boost_body: 'float' },
        version: 1,
        parent_id: null,
        created_at: '2026-05-12T00:00:00Z',
      }),
    ),
  );
}

async function walkToStep4(): Promise<void> {
  await waitFor(() => expect(screen.getByRole('option', { name: /local-es/ })).toBeInTheDocument());
  fireEvent.change(screen.getByLabelText('Cluster'), { target: { value: 'c1' } });
  await waitFor(() =>
    expect(screen.queryAllByRole('option', { name: /products/ }).length).toBeGreaterThan(0),
  );
  fireEvent.change(screen.getByLabelText('Target index / collection'), {
    target: { value: 'products' },
  });
  fireEvent.click(screen.getByTestId('step-next'));
  await waitFor(() => expect(screen.getByTestId('step-2')).toBeInTheDocument());
  await waitFor(() =>
    expect(screen.queryAllByRole('option', { name: 'demo' }).length).toBeGreaterThan(0),
  );
  fireEvent.change(screen.getByLabelText('Query set'), { target: { value: 'qs1' } });
  await waitFor(() => {
    expect(screen.queryAllByRole('option', { name: 'demo' }).length).toBeGreaterThanOrEqual(2);
  });
  fireEvent.change(screen.getByLabelText('Judgment list'), { target: { value: 'jl1' } });
  fireEvent.click(screen.getByTestId('step-next'));
  await waitFor(() => expect(screen.getByTestId('step-3')).toBeInTheDocument());
  await waitFor(() => expect(screen.getByRole('option', { name: 'T1 (v1)' })).toBeInTheDocument());
  fireEvent.change(screen.getByLabelText('Query template (filtered by engine)'), {
    target: { value: 'tpl1' },
  });
  fireEvent.click(screen.getByTestId('step-next'));
  await waitFor(() => expect(screen.getByTestId('step-4')).toBeInTheDocument());
}

describe('CreateStudyModal — Step-4 template-change Undo flow (FR-1 / AC-3)', () => {
  beforeEach(() => {
    toastSpy.mockClear();
    lastUndoAction = null;
  });
  afterEach(() => server.resetHandlers());

  it('clicking Undo restores prior user content', async () => {
    mockTwoTemplates();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToStep4();

    const textarea = (await screen.findByTestId('cs-search-space')) as HTMLTextAreaElement;
    await waitFor(() => expect(textarea.value).toContain('boost_title'));

    // User edits Step 4 with content NOT in autoFillSignatures.
    const userText = '{"params": {"user_only_param": {"type": "int", "low": 0, "high": 9}}}';
    fireEvent.change(textarea, { target: { value: userText } });

    // Go back, switch template.
    fireEvent.click(screen.getByText('Back'));
    await waitFor(() => expect(screen.getByTestId('step-3')).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText('Query template (filtered by engine)'), {
      target: { value: 'tpl2' },
    });
    fireEvent.click(screen.getByTestId('step-next'));
    await waitFor(() => expect(screen.getByTestId('step-4')).toBeInTheDocument());

    // Auto-fill replaced the user content with T2's defaults.
    await waitFor(() =>
      expect((screen.getByTestId('cs-search-space') as HTMLTextAreaElement).value).toContain(
        'boost_body',
      ),
    );

    // Toast was raised with an Undo action handler.
    await waitFor(() => expect(lastUndoAction).toBeTruthy());

    // Fire Undo — the textarea must restore the prior user content.
    expect(lastUndoAction).not.toBeNull();
    lastUndoAction?.();
    await waitFor(() =>
      expect((screen.getByTestId('cs-search-space') as HTMLTextAreaElement).value).toContain(
        'user_only_param',
      ),
    );
  });
});
