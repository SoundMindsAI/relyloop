// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

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
    auto_followup_depth?: unknown;
    [key: string]: unknown;
  };
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
  fireEvent.change(screen.getByLabelText('Study name'), {
    target: { value: 'auto-followup-test' },
  });
  fireEvent.click(screen.getByTestId('step-next'));
  await waitFor(() => expect(screen.getByTestId('step-5')).toBeInTheDocument());
}

function getDepthSelect(): HTMLSelectElement {
  return screen.getByTestId('cs-auto-followup') as HTMLSelectElement;
}

describe('CreateStudyModal — auto-followup depth selector (FR-11, Story 3.2)', () => {
  afterEach(() => server.resetHandlers());

  it('default state: depth selector renders "Off" (value 0)', async () => {
    mockBackend();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToStep5();

    expect(getDepthSelect().value).toBe('0');
  });

  it('selecting "3 follow-ups" updates the visible value to 3', async () => {
    mockBackend();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToStep5();

    fireEvent.change(getDepthSelect(), { target: { value: '3' } });

    await waitFor(() => expect(getDepthSelect().value).toBe('3'));
  });

  it('switching back to "Off" after a non-zero selection returns to value 0', async () => {
    mockBackend();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToStep5();

    fireEvent.change(getDepthSelect(), { target: { value: '4' } });
    await waitFor(() => expect(getDepthSelect().value).toBe('4'));

    fireEvent.change(getDepthSelect(), { target: { value: '0' } });
    await waitFor(() => expect(getDepthSelect().value).toBe('0'));
  });

  it('submit with depth=3 → POST body has config.auto_followup_depth=3', async () => {
    const { postBodies } = mockBackend();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToStep5();

    fireEvent.change(getDepthSelect(), { target: { value: '3' } });
    await waitFor(() => expect(getDepthSelect().value).toBe('3'));

    fireEvent.click(screen.getByRole('button', { name: /Create study/i }));

    await waitFor(() => expect(postBodies.length).toBeGreaterThan(0));
    expect(postBodies[0]!.config?.auto_followup_depth).toBe(3);
  });

  it('submit with depth=Off (0 sentinel) → POST body omits config.auto_followup_depth entirely', async () => {
    // D-12: wizard-`0` is the "Off" sentinel and maps to undefined at submit
    // (omit the key from `config`). Wire-`0` is reserved for the worker's
    // decrement-to-terminal path; the wizard never sends it. Asserting key
    // absence (not equality with 0 or null) is the wire contract.
    const { postBodies } = mockBackend();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToStep5();

    expect(getDepthSelect().value).toBe('0');
    fireEvent.click(screen.getByRole('button', { name: /Create study/i }));

    await waitFor(() => expect(postBodies.length).toBeGreaterThan(0));
    const config = postBodies[0]!.config ?? {};
    expect('auto_followup_depth' in config).toBe(false);
  });

  it('selecting nonzero then switching back to Off → POST body omits config.auto_followup_depth', async () => {
    const { postBodies } = mockBackend();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToStep5();

    fireEvent.change(getDepthSelect(), { target: { value: '5' } });
    await waitFor(() => expect(getDepthSelect().value).toBe('5'));

    fireEvent.change(getDepthSelect(), { target: { value: '0' } });
    await waitFor(() => expect(getDepthSelect().value).toBe('0'));

    fireEvent.click(screen.getByRole('button', { name: /Create study/i }));

    await waitFor(() => expect(postBodies.length).toBeGreaterThan(0));
    const config = postBodies[0]!.config ?? {};
    expect('auto_followup_depth' in config).toBe(false);
  });

  it('depth selector renders all 6 options (Off, 1..5) from AUTO_FOLLOWUP_DEPTH_WIZARD_VALUES', async () => {
    mockBackend();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToStep5();

    const select = getDepthSelect();
    // The shadcn-select-mock prepends a hidden placeholder option (value="");
    // filter it out so the assertion only sees real wire values.
    const realOptions = Array.from(select.querySelectorAll('option')).filter((o) => o.value !== '');
    expect(realOptions.map((o) => o.value)).toEqual(['0', '1', '2', '3', '4', '5']);
    expect(realOptions.map((o) => o.textContent)).toEqual([
      'Off',
      '1 follow-up',
      '2 follow-ups',
      '3 follow-ups',
      '4 follow-ups',
      '5 follow-ups',
    ]);
  });
});

describe('CreateStudyModal — overnight autopilot relabel + hint (feat_overnight_autopilot, Story 3.1)', () => {
  afterEach(() => server.resetHandlers());

  // AC-1: the wizard label is reframed to the canonical overnight string.
  it('AC-1: wizard label reads "🌙 Run overnight (compound automatically)" verbatim', async () => {
    mockBackend();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToStep5();

    const label = screen.getByText('🌙 Run overnight (compound automatically)');
    expect(label).toBeInTheDocument();
    expect(label.tagName.toLowerCase()).toBe('label');
    expect(label).toHaveAttribute('for', 'cs-auto-followup');
  });

  it('AC-1: helper text reads the FR-1 paragraph verbatim', async () => {
    mockBackend();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToStep5();

    expect(
      screen.getByText(
        /When this study finishes, automatically start a follow-up that narrows in on the best result, then repeat\. Stops on its own when it stops improving, hits the daily budget, or runs out of depth\. No production changes happen without your review — you still open every PR by hand\./,
      ),
    ).toBeInTheDocument();
  });

  // AC-2 (show): Deep preset + depth Off → hint renders with exact copy.
  it('AC-2: Deep preset with depth Off shows the overnight hint', async () => {
    mockBackend();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToStep5();

    // Default depth is Off (0). Select the Deep preset.
    fireEvent.click(screen.getByRole('button', { name: 'Deep (1000)' }));

    const hint = await screen.findByTestId('cs-overnight-hint');
    expect(hint).toHaveAttribute('role', 'note');
    expect(hint).toHaveTextContent(
      "💡 Tip — this is a long study. Enable '🌙 Run overnight (compound automatically)' below to chain follow-up runs while you're away.",
    );
  });

  // AC-2 (hide): setting depth ≥ 1 removes the hint within the same render cycle.
  it('AC-2: selecting depth ≥ 1 hides the overnight hint', async () => {
    mockBackend();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToStep5();

    fireEvent.click(screen.getByRole('button', { name: 'Deep (1000)' }));
    expect(await screen.findByTestId('cs-overnight-hint')).toBeInTheDocument();

    fireEvent.change(getDepthSelect(), { target: { value: '1' } });
    await waitFor(() => expect(getDepthSelect().value).toBe('1'));

    expect(screen.queryByTestId('cs-overnight-hint')).not.toBeInTheDocument();
  });

  // The hint must NOT show for a non-Deep preset even with depth Off.
  it('AC-2: hint absent for non-Deep presets', async () => {
    mockBackend();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToStep5();

    fireEvent.click(screen.getByRole('button', { name: 'Focused (50)' }));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Focused (50)' })).toHaveAttribute(
        'aria-pressed',
        'true',
      ),
    );

    expect(screen.queryByTestId('cs-overnight-hint')).not.toBeInTheDocument();
  });
});
