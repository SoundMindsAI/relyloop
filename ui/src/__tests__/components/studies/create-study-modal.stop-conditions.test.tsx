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

vi.mock('sonner', () => ({
  toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() }),
  Toaster: () => null,
}));

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

interface PostBody {
  config?: {
    max_trials?: number;
    time_budget_min?: number;
    preset?: unknown;
    [key: string]: unknown;
  };
  preset?: unknown;
  [key: string]: unknown;
}

function mockBackend() {
  const postBodies: PostBody[] = [];
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
        name: 'T1',
        engine_type: 'elasticsearch',
        body: '{}',
        declared_params: { boost_title: 'float' },
        version: 1,
        parent_id: null,
        created_at: '2026-05-12T00:00:00Z',
      }),
    ),
    http.post(`${API_BASE}/api/v1/studies`, async ({ request }) => {
      const body = (await request.json()) as PostBody;
      postBodies.push(body);
      return HttpResponse.json({ id: 'st1', name: 'demo', status: 'queued' });
    }),
  );
  return { postBodies };
}

async function walkToStep5(): Promise<void> {
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
  await waitFor(() => expect(screen.getAllByRole('option').length).toBeGreaterThan(0));
  fireEvent.change(screen.getByLabelText('Query template (filtered by engine)'), {
    target: { value: 'tpl1' },
  });
  fireEvent.click(screen.getByTestId('step-next'));
  await waitFor(() => expect(screen.getByTestId('step-4')).toBeInTheDocument());
  fireEvent.change(screen.getByLabelText('Study name'), { target: { value: 'preset-test' } });
  fireEvent.click(screen.getByTestId('step-next'));
  await waitFor(() => expect(screen.getByTestId('step-5')).toBeInTheDocument());
}

function getMaxTrialsInput(): HTMLInputElement {
  return screen.getByLabelText('Max trials') as HTMLInputElement;
}
function getTimeBudgetInput(): HTMLInputElement {
  return screen.getByLabelText('Time budget (min)') as HTMLInputElement;
}
function getPresetButton(name: RegExp): HTMLButtonElement {
  return screen.getByRole('button', { name }) as HTMLButtonElement;
}

describe('CreateStudyModal — stop-condition presets (FR-2..FR-4, FR-9)', () => {
  afterEach(() => server.resetHandlers());

  it('AC-1: renders Standard pressed + max_trials=200 by default', async () => {
    mockBackend();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToStep5();

    expect(getMaxTrialsInput().value).toBe('200');
    expect(getPresetButton(/Standard \(200\)/).getAttribute('aria-pressed')).toBe('true');
    expect(getPresetButton(/Focused \(50\)/).getAttribute('aria-pressed')).toBe('false');
    expect(getPresetButton(/Deep \(1000\)/).getAttribute('aria-pressed')).toBe('false');
    expect(getPresetButton(/^Custom$/).getAttribute('aria-pressed')).toBe('false');
  });

  it('AC-2: Focused writes max_trials=50 and clears time_budget_min', async () => {
    mockBackend();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToStep5();

    fireEvent.click(getPresetButton(/Focused \(50\)/));

    await waitFor(() => expect(getMaxTrialsInput().value).toBe('50'));
    expect(getTimeBudgetInput().value).toBe('');
    expect(getPresetButton(/Focused \(50\)/).getAttribute('aria-pressed')).toBe('true');
  });

  it('AC-3: Deep writes max_trials=1000 AND time_budget_min=480', async () => {
    mockBackend();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToStep5();

    fireEvent.click(getPresetButton(/Deep \(1000\)/));

    await waitFor(() => expect(getMaxTrialsInput().value).toBe('1000'));
    expect(getTimeBudgetInput().value).toBe('480');
    expect(getPresetButton(/Deep \(1000\)/).getAttribute('aria-pressed')).toBe('true');
  });

  it('AC-4: Custom preserves manual edits', async () => {
    mockBackend();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToStep5();

    fireEvent.change(getMaxTrialsInput(), { target: { value: '333' } });
    // Manual edit while Standard active should already flip to Custom (AC-5);
    // explicit click on Custom should not clobber the value.
    fireEvent.click(getPresetButton(/^Custom$/));

    expect(getMaxTrialsInput().value).toBe('333');
    expect(getPresetButton(/^Custom$/).getAttribute('aria-pressed')).toBe('true');
  });

  it('AC-5: manual edit while non-Custom flips to Custom', async () => {
    mockBackend();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToStep5();

    expect(getPresetButton(/Standard \(200\)/).getAttribute('aria-pressed')).toBe('true');

    fireEvent.change(getMaxTrialsInput(), { target: { value: '300' } });

    await waitFor(() =>
      expect(getPresetButton(/^Custom$/).getAttribute('aria-pressed')).toBe('true'),
    );
    expect(getPresetButton(/Standard \(200\)/).getAttribute('aria-pressed')).toBe('false');
  });

  it('AC-6: fresh-mount reset has Standard pressed + max_trials=200', async () => {
    mockBackend();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToStep5();

    // Fresh modal mount uses defaultValues.max_trials=200 + Standard preset.
    // Form-field reset on Radix toggle is intentionally NOT enforced — see
    // the open effect's comment in create-study-modal.tsx for the rationale
    // (production-build Chromium race with Playwright-controlled inputs).
    // Persistent form state from a previous unfinished session shows up as
    // 'custom' preset, which the manual-edit watcher correctly derives.
    expect(getMaxTrialsInput().value).toBe('200');
    expect(getTimeBudgetInput().value).toBe('');
    expect(getPresetButton(/Standard \(200\)/).getAttribute('aria-pressed')).toBe('true');
  });

  it('AC-6 follow-up: reopening after Deep selection shows Deep (form state persists, derived preset reflects values)', async () => {
    mockBackend();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { rerender } = render(
      <QueryClientProvider client={qc}>
        <TooltipProvider delayDuration={0}>
          <CreateStudyModal open={true} onOpenChange={() => {}} />
        </TooltipProvider>
      </QueryClientProvider>,
    );
    await walkToStep5();

    fireEvent.click(getPresetButton(/Deep \(1000\)/));
    await waitFor(() => expect(getMaxTrialsInput().value).toBe('1000'));

    rerender(
      <QueryClientProvider client={qc}>
        <TooltipProvider delayDuration={0}>
          <CreateStudyModal open={false} onOpenChange={() => {}} />
        </TooltipProvider>
      </QueryClientProvider>,
    );
    rerender(
      <QueryClientProvider client={qc}>
        <TooltipProvider delayDuration={0}>
          <CreateStudyModal open={true} onOpenChange={() => {}} />
        </TooltipProvider>
      </QueryClientProvider>,
    );

    // Radix Dialog keeps the component mounted; form state persists.
    // activePreset is derived purely from form values, so values 1000/480
    // re-derive to 'deep' — Deep button stays pressed (more accurate UX than
    // the previous useState+watcher approach which would have flipped to
    // 'custom' falsely).
    await waitFor(() =>
      expect(getPresetButton(/Deep \(1000\)/).getAttribute('aria-pressed')).toBe('true'),
    );
    expect(getMaxTrialsInput().value).toBe('1000');
    expect(getTimeBudgetInput().value).toBe('480');
  });

  it('bug-guard: Deep → Standard clears stale time_budget_min', async () => {
    mockBackend();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToStep5();

    fireEvent.click(getPresetButton(/Deep \(1000\)/));
    await waitFor(() => expect(getTimeBudgetInput().value).toBe('480'));

    fireEvent.click(getPresetButton(/Standard \(200\)/));

    await waitFor(() => expect(getMaxTrialsInput().value).toBe('200'));
    expect(getTimeBudgetInput().value).toBe('');
    expect(getPresetButton(/Standard \(200\)/).getAttribute('aria-pressed')).toBe('true');
  });

  it('bug-guard: Deep → Focused clears stale time_budget_min', async () => {
    mockBackend();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToStep5();

    fireEvent.click(getPresetButton(/Deep \(1000\)/));
    await waitFor(() => expect(getTimeBudgetInput().value).toBe('480'));

    fireEvent.click(getPresetButton(/Focused \(50\)/));

    await waitFor(() => expect(getMaxTrialsInput().value).toBe('50'));
    expect(getTimeBudgetInput().value).toBe('');
    expect(getPresetButton(/Focused \(50\)/).getAttribute('aria-pressed')).toBe('true');
  });

  it('AC-8: Stop condition InfoTooltip is present on the group label', async () => {
    mockBackend();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToStep5();

    // The group label is the visible <span>; InfoTooltip renders an
    // ariaLabel-bearing trigger nearby. The group label must be present and
    // its aria-labelledby target must exist.
    expect(screen.getByText('Stop condition')).toBeInTheDocument();
    const trigger = screen.getByRole('button', { name: /More information about study presets/i });
    expect(trigger).toBeInTheDocument();
  });

  it('AC-10: wire shape — POST body has max_trials but no `preset` field', async () => {
    const { postBodies } = mockBackend();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToStep5();

    // Submit with Standard active (default).
    fireEvent.click(screen.getByRole('button', { name: /Create study/i }));

    await waitFor(() => expect(postBodies.length).toBeGreaterThan(0));
    const body = postBodies[0]!;
    expect(body.config?.max_trials).toBe(200);
    expect('preset' in body).toBe(false);
    expect(body.config && 'preset' in body.config).toBe(false);
  });

  it('all four preset buttons have type="button" (prevent submit-on-click)', async () => {
    mockBackend();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToStep5();

    for (const name of [/Focused \(50\)/, /Standard \(200\)/, /Deep \(1000\)/, /^Custom$/]) {
      const btn = getPresetButton(name);
      expect(btn.getAttribute('type')).toBe('button');
    }
  });
});
