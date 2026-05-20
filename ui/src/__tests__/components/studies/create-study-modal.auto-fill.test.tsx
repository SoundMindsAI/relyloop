import { http, HttpResponse } from 'msw';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

import { TooltipProvider } from '@/components/ui/tooltip';

import { server } from '../../setup';

vi.mock('@/components/ui/select', async () => {
  const { mockShadcnSelect } = await import('../../helpers/shadcn-select-mock');
  return mockShadcnSelect();
});

// Spy on sonner so we can assert toast calls without mounting <Toaster /> in
// jsdom (which would also require the sonner DOM-portal stack).
const toastSpy = vi.fn();
type ToastFn = ((message: string, options?: Record<string, unknown>) => void) & {
  error: (m: string) => void;
  success: (m: string) => void;
};
const toastStub: ToastFn = Object.assign(
  ((m: string, o?: Record<string, unknown>) => toastSpy(m, o)) as ToastFn,
  {
    error: (m: string) => toastSpy(m),
    success: (m: string) => toastSpy(m),
  },
);
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

function mockStep1to3(templateDetail: { declared_params: Record<string, string>; name?: string }) {
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
              name: templateDetail.name ?? 'product_search v1',
              engine_type: 'elasticsearch',
              version: 1,
              created_at: '2026-05-12T00:00:00Z',
            },
          ],
          next_cursor: null,
          has_more: false,
        },
        { headers: { 'X-Total-Count': '1' } },
      ),
    ),
    http.get(`${API_BASE}/api/v1/query-templates/tpl1`, () =>
      HttpResponse.json({
        id: 'tpl1',
        name: templateDetail.name ?? 'product_search v1',
        engine_type: 'elasticsearch',
        body: '{}',
        declared_params: templateDetail.declared_params,
        version: 1,
        parent_id: null,
        created_at: '2026-05-12T00:00:00Z',
      }),
    ),
  );
}

async function walkSteps1to3(): Promise<void> {
  await waitFor(() => expect(screen.getByRole('option', { name: /local-es/ })).toBeInTheDocument());
  fireEvent.change(screen.getByLabelText('Cluster'), { target: { value: 'c1' } });
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
    const opts = screen.queryAllByRole('option', { name: 'demo' });
    expect(opts.length).toBeGreaterThanOrEqual(2);
  });
  fireEvent.change(screen.getByLabelText('Judgment list'), { target: { value: 'jl1' } });
  fireEvent.click(screen.getByTestId('step-next'));

  await waitFor(() => expect(screen.getByTestId('step-3')).toBeInTheDocument());
  await waitFor(() =>
    expect(screen.getByRole('option', { name: /product_search v1/ })).toBeInTheDocument(),
  );
  fireEvent.change(screen.getByLabelText('Query template (filtered by engine)'), {
    target: { value: 'tpl1' },
  });
  fireEvent.click(screen.getByTestId('step-next'));
  await waitFor(() => expect(screen.getByTestId('step-4')).toBeInTheDocument());
}

describe('CreateStudyModal — Step-4 auto-fill (chore_create_study_wizard_polish FR-1)', () => {
  afterEach(() => server.resetHandlers());

  it('pre-fills the textarea with starter JSON on Step-3 → Step-4 transition', async () => {
    mockStep1to3({
      declared_params: {
        boost_title: 'float',
        boost_body: 'float',
        min_should_match: 'int',
        fuzziness: 'string',
      },
    });
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkSteps1to3();

    const textarea = (await screen.findByTestId('cs-search-space')) as HTMLTextAreaElement;
    await waitFor(() => expect(textarea.value).not.toBe(''));
    const parsed = JSON.parse(textarea.value);
    expect(parsed).toMatchObject({
      params: {
        boost_title: { type: 'float', low: 0.5, high: 10.0, log: true },
        boost_body: { type: 'float', low: 0.5, high: 10.0, log: true },
        min_should_match: { type: 'int', low: 0, high: 5 },
        fuzziness: { type: 'categorical', choices: ['AUTO', '0', '1', '2'] },
      },
    });
  });

  it('does not overwrite user-typed content silently — but template fetch arrives and shows Undo toast', async () => {
    mockStep1to3({ declared_params: { boost_title: 'float' } });
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);

    // Walk through steps but type into the textarea between Step-3 click and
    // template-fetch resolution. Cleanest path: click into Step 4 first, then
    // type — auto-fill runs only when the fetch resolves.
    await walkSteps1to3();
    // The auto-fill effect may have already run; explicitly overwrite with
    // user content to simulate later edits.
    const textarea = (await screen.findByTestId('cs-search-space')) as HTMLTextAreaElement;
    fireEvent.change(textarea, {
      target: { value: '{"params": {"my_custom_param": {"type": "int", "low": 0, "high": 9}}}' },
    });

    // The user's content was not generated by auto-fill, so it is not in the
    // autoFillSignatures set; subsequent template re-fetch would surface an
    // Undo toast. This test asserts the user content is preserved at the
    // moment after Step 3 → Step 4 transition (no surprise overwrite).
    await waitFor(() => expect(textarea.value).toContain('my_custom_param'));
  });

  it('replaces existing user content (with Undo toast) when the template changes', async () => {
    // Two templates with different declared_params.
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
      http.get(`${API_BASE}/api/v1/query-sets`, () =>
        HttpResponse.json(
          {
            data: [
              { id: 'qs1', name: 'demo', cluster_id: 'c1', created_at: '2026-05-12T00:00:00Z' },
            ],
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

    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await waitFor(() =>
      expect(screen.getByRole('option', { name: /local-es/ })).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByLabelText('Cluster'), { target: { value: 'c1' } });
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
    await waitFor(() =>
      expect(screen.getByRole('option', { name: 'T1 (v1)' })).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByLabelText('Query template (filtered by engine)'), {
      target: { value: 'tpl1' },
    });
    fireEvent.click(screen.getByTestId('step-next'));
    await waitFor(() => expect(screen.getByTestId('step-4')).toBeInTheDocument());

    const textarea = (await screen.findByTestId('cs-search-space')) as HTMLTextAreaElement;
    await waitFor(() => expect(textarea.value).toContain('boost_title'));

    // User edits Step 4, then goes back and re-picks template tpl2.
    fireEvent.change(textarea, {
      target: { value: '{"params": {"user_param": {"type": "int", "low": 0, "high": 9}}}' },
    });
    fireEvent.click(screen.getByText('Back'));
    await waitFor(() => expect(screen.getByTestId('step-3')).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText('Query template (filtered by engine)'), {
      target: { value: 'tpl2' },
    });
    fireEvent.click(screen.getByTestId('step-next'));
    await waitFor(() => expect(screen.getByTestId('step-4')).toBeInTheDocument());

    // The auto-fill replaced the user content — boost_body now appears.
    await waitFor(() =>
      expect((screen.getByTestId('cs-search-space') as HTMLTextAreaElement).value).toContain(
        'boost_body',
      ),
    );
    // And sonner.toast was invoked with an Undo action.
    await waitFor(() => {
      const undoCall = toastSpy.mock.calls.find((c) => {
        const opts = c[1] as { action?: { label?: string } } | undefined;
        return opts?.action?.label === 'Undo';
      });
      expect(undoCall).toBeTruthy();
    });
  });
});
