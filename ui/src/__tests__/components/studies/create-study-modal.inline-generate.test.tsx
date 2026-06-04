// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * feat_study_wizard_inline_judgment_generation — wizard-side coverage:
 *  - AC-1: a persistent "Generate judgments for this query set" button shows
 *    when the judgment-list dropdown is empty AND when it lists only a failed
 *    list; clicking it opens <GenerateJudgmentsDialog> in-place.
 *  - AC-4: the dropdown option label surfaces non-complete status.
 *  - AC-3/AC-7: closing the dialog refetches the judgment-list query (covers the
 *    UBI path, which does not self-invalidate).
 *
 * AC-2 (target lock/seed) is unit-tested in generate-judgments-dialog.test.tsx;
 * AC-5 (generating→complete poll) is in lib/api/judgments.test.tsx.
 */
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

interface JudgmentList {
  id: string;
  name: string;
  description: string | null;
  query_set_id: string;
  cluster_id: string;
  status: 'generating' | 'complete' | 'failed';
  created_at: string;
}

/** Register the common cluster/target/query-set/template handlers + a
 *  judgment-lists handler returning `lists` (and counting its GET calls). */
function mockBackend(lists: JudgmentList[]): { jlGetCount: () => number } {
  let jlGets = 0;
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
    http.get(`${API_BASE}/api/v1/clusters/c1`, () =>
      HttpResponse.json({
        id: 'c1',
        name: 'local-es',
        engine_type: 'elasticsearch',
        environment: 'dev',
        base_url: 'http://localhost:9200',
        auth_kind: 'es_apikey',
        created_at: '2026-05-12T00:00:00Z',
      }),
    ),
    http.get(`${API_BASE}/api/v1/clusters/c1/ubi-readiness`, () =>
      HttpResponse.json({
        rung: 'rung_0',
        covered_pairs_pct: null,
        head_covered: null,
        checked_at: '2026-05-12T00:00:00Z',
      }),
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
    http.get(`${API_BASE}/api/v1/judgment-lists`, () => {
      jlGets += 1;
      return HttpResponse.json(
        { data: lists, next_cursor: null, has_more: false },
        { headers: { 'X-Total-Count': String(lists.length) } },
      );
    }),
    http.get(`${API_BASE}/api/v1/query-templates`, () =>
      HttpResponse.json(
        { data: [], next_cursor: null, has_more: false },
        { headers: { 'X-Total-Count': '0' } },
      ),
    ),
  );
  return { jlGetCount: () => jlGets };
}

/** Drive the wizard to the Query-set + Judgment-list step (step-2). */
async function walkToJudgmentStep(): Promise<void> {
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
}

function jl(status: JudgmentList['status']): JudgmentList {
  return {
    id: 'jl1',
    name: 'demo',
    description: null,
    query_set_id: 'qs1',
    cluster_id: 'c1',
    status,
    created_at: '2026-05-12T00:00:00Z',
  };
}

describe('CreateStudyModal — inline judgment generation', () => {
  afterEach(() => server.resetHandlers());

  it('AC-1: shows the inline generate button when no judgment list exists, and opens the dialog', async () => {
    mockBackend([]);
    wrap(<CreateStudyModal open onOpenChange={() => {}} />);
    await walkToJudgmentStep();

    const btn = await screen.findByTestId('cs-generate-judgments');
    expect(btn).toBeInTheDocument();
    fireEvent.click(btn);
    // The reused GenerateJudgmentsDialog renders its form.
    expect(await screen.findByTestId('generate-form')).toBeInTheDocument();
    // AC-2 (integration cross-check): the dialog's target is pre-filled + locked.
    await waitFor(() => expect(screen.getByTestId('gen-target')).toHaveValue('products'));
    expect(screen.getByTestId('gen-target')).toHaveAttribute('readonly');
  });

  it('AC-1: the button is still present when only a FAILED list exists (retry path)', async () => {
    mockBackend([jl('failed')]);
    wrap(<CreateStudyModal open onOpenChange={() => {}} />);
    await walkToJudgmentStep();
    expect(await screen.findByTestId('cs-generate-judgments')).toBeInTheDocument();
  });

  it('AC-4: the dropdown option surfaces non-complete status in its label', async () => {
    mockBackend([jl('generating')]);
    wrap(<CreateStudyModal open onOpenChange={() => {}} />);
    await walkToJudgmentStep();
    await waitFor(() =>
      expect(screen.getByRole('option', { name: 'demo · generating' })).toBeInTheDocument(),
    );
  });

  it('AC-4: a complete list shows just its name (no status suffix)', async () => {
    mockBackend([jl('complete')]);
    wrap(<CreateStudyModal open onOpenChange={() => {}} />);
    await walkToJudgmentStep();
    await waitFor(() =>
      expect(screen.queryAllByRole('option', { name: 'demo' }).length).toBeGreaterThanOrEqual(1),
    );
    expect(screen.queryByRole('option', { name: 'demo · complete' })).not.toBeInTheDocument();
  });

  it('AC-3/AC-7: closing the dialog refetches the judgment-list query', async () => {
    const { jlGetCount } = mockBackend([]);
    wrap(<CreateStudyModal open onOpenChange={() => {}} />);
    await walkToJudgmentStep();
    fireEvent.click(await screen.findByTestId('cs-generate-judgments'));
    expect(await screen.findByTestId('generate-form')).toBeInTheDocument();
    const before = jlGetCount();
    // Close the dialog (Escape) → onOpenChange(false) → invalidate ['judgment-lists'].
    fireEvent.keyDown(document.body, { key: 'Escape' });
    await waitFor(() => expect(jlGetCount()).toBeGreaterThan(before));
  });
});
