// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * feat_study_target_judgment_mismatch_guard Story 2.1 — create-study modal
 * Step-2 judgment-list dropdown filters by the Step-1 target via the new
 * `?target=` wire param, and cascade-resets `judgment_list_id` on target /
 * cluster change. Empty-state copy surfaces the target value + CTA to
 * /judgments.
 *
 * Test inventory (plan §3.5, 5 vitest cases):
 *   1. Modal calls useJudgmentLists with { query_set_id, cluster_id, target,
 *      limit: 200 } — verifies the component DELEGATES filtering to the wire
 *      (NOT client-side filtering, which the spec's anti-patterns forbid).
 *   2a. target change via the DROPDOWN <EntitySelect> resets judgment_list_id.
 *   2b. target change via the MANUAL <Input> resets judgment_list_id.
 *   3. cluster_id change resets judgment_list_id (regression-lock for the
 *      pre-existing cascade at create-study-modal.tsx:509).
 *   4. Empty-state copy renders with the exact target value substituted +
 *      CTA href="/judgments" when the judgment-lists endpoint returns
 *      `{ data: [], next_cursor: null, has_more: false }`.
 */
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type ReactNode } from 'react';

import { TooltipProvider } from '@/components/ui/tooltip';

import { server } from '../../setup';

// Native-select shim — same escape hatch the sibling modal tests use so
// Radix's portal handling doesn't crash jsdom.
vi.mock('@/components/ui/select', async () => {
  const { mockShadcnSelect } = await import('../../helpers/shadcn-select-mock');
  return mockShadcnSelect();
});

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

interface JudgmentListsCallSpy {
  calls: URL[];
}

/**
 * Mock the full Step-1 + Step-2 cluster + target + query-set + judgment-list
 * surface, with a `judgmentListsSpy` that captures every `?target=` /
 * `?cluster_id=` / `?query_set_id=` filter the modal passes.
 */
function setupBackend(opts: {
  judgmentListsData?: Array<{
    id: string;
    name: string;
    target: string;
    cluster_id: string;
    query_set_id: string;
  }>;
}): JudgmentListsCallSpy {
  const spy: JudgmentListsCallSpy = { calls: [] };
  const summaries = (opts.judgmentListsData ?? []).map((jl) => ({
    id: jl.id,
    name: jl.name,
    description: null,
    query_set_id: jl.query_set_id,
    cluster_id: jl.cluster_id,
    target: jl.target,
    status: 'complete',
    created_at: '2026-05-21T00:00:00Z',
  }));

  server.use(
    http.get(`${API_BASE}/api/v1/clusters`, () =>
      HttpResponse.json(
        {
          data: [
            {
              id: 'c1',
              name: 'cluster-one',
              engine_type: 'elasticsearch',
              environment: 'dev',
              base_url: 'http://localhost:9200',
              auth_kind: 'es_apikey',
              created_at: '2026-05-21T00:00:00Z',
              health_check: {
                status: 'green',
                version: '9.4.0',
                checked_at: '2026-05-21T00:00:00Z',
                error: null,
              },
            },
            {
              id: 'c2',
              name: 'cluster-two',
              engine_type: 'elasticsearch',
              environment: 'dev',
              base_url: 'http://localhost:9201',
              auth_kind: 'es_apikey',
              created_at: '2026-05-21T00:00:00Z',
              health_check: {
                status: 'green',
                version: '9.4.0',
                checked_at: '2026-05-21T00:00:00Z',
                error: null,
              },
            },
          ],
          next_cursor: null,
          has_more: false,
        },
        { headers: { 'X-Total-Count': '2' } },
      ),
    ),
    http.get(`${API_BASE}/api/v1/clusters/:id/schema`, () => HttpResponse.json({ fields: [] })),
    http.get(`${API_BASE}/api/v1/clusters/:id/targets`, () =>
      HttpResponse.json({
        data: [
          { name: 'products', doc_count: 42 },
          { name: 'articles', doc_count: 12 },
        ],
      }),
    ),
    http.get(`${API_BASE}/api/v1/query-sets`, () =>
      HttpResponse.json(
        {
          data: [
            { id: 'qs1', name: 'demo-qs', cluster_id: 'c1', created_at: '2026-05-21T00:00:00Z' },
          ],
          next_cursor: null,
          has_more: false,
        },
        { headers: { 'X-Total-Count': '1' } },
      ),
    ),
    http.get(`${API_BASE}/api/v1/judgment-lists`, ({ request }) => {
      spy.calls.push(new URL(request.url));
      return HttpResponse.json(
        { data: summaries, next_cursor: null, has_more: false },
        { headers: { 'X-Total-Count': String(summaries.length) } },
      );
    }),
    http.get(`${API_BASE}/api/v1/query-templates`, () =>
      HttpResponse.json(
        { data: [], next_cursor: null, has_more: false },
        { headers: { 'X-Total-Count': '0' } },
      ),
    ),
  );
  return spy;
}

async function pickCluster(value: 'c1' | 'c2') {
  await waitFor(() =>
    expect(screen.getByRole('option', { name: /cluster-one/ })).toBeInTheDocument(),
  );
  fireEvent.change(screen.getByLabelText('Cluster'), { target: { value } });
}

async function pickTargetDropdown(value: 'products' | 'articles') {
  await waitFor(() =>
    expect(screen.queryAllByRole('option', { name: new RegExp(value) }).length).toBeGreaterThan(0),
  );
  fireEvent.change(screen.getByLabelText('Target index / collection'), { target: { value } });
}

async function advanceToStep2() {
  fireEvent.click(screen.getByTestId('step-next'));
  await waitFor(() => expect(screen.getByTestId('step-2')).toBeInTheDocument());
}

async function pickQuerySet() {
  await waitFor(() =>
    expect(screen.queryAllByRole('option', { name: /demo-qs/ }).length).toBeGreaterThan(0),
  );
  fireEvent.change(screen.getByLabelText('Query set'), { target: { value: 'qs1' } });
}

async function pickJudgmentList(value: string) {
  await waitFor(() =>
    expect(screen.queryAllByRole('option', { name: value }).length).toBeGreaterThan(0),
  );
  fireEvent.change(screen.getByLabelText('Judgment list'), { target: { value } });
}

function findLastJudgmentListsCall(spy: JudgmentListsCallSpy): URL {
  expect(spy.calls.length).toBeGreaterThan(0);
  return spy.calls[spy.calls.length - 1]!;
}

// --- Test cases ---------------------------------------------------------

describe('CreateStudyModal Step-2 judgment-list dropdown — target-aware filter', () => {
  it('passes target + cluster_id + query_set_id to useJudgmentLists (Case 1)', async () => {
    const spy = setupBackend({
      judgmentListsData: [
        {
          id: 'jl-prod',
          name: 'jl-for-products',
          target: 'products',
          cluster_id: 'c1',
          query_set_id: 'qs1',
        },
      ],
    });
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await pickCluster('c1');
    await pickTargetDropdown('products');
    await advanceToStep2();
    await pickQuerySet();
    // Wait for the judgment-lists hook to fire after Step-2 query_set pick.
    await waitFor(() => {
      const last = findLastJudgmentListsCall(spy);
      expect(last.searchParams.get('target')).toBe('products');
      expect(last.searchParams.get('cluster_id')).toBe('c1');
      expect(last.searchParams.get('query_set_id')).toBe('qs1');
      expect(last.searchParams.get('limit')).toBe('200');
    });
  });

  it('cascades target dropdown change → judgment_list_id reset (Case 2a, AC-9)', async () => {
    const spy = setupBackend({
      judgmentListsData: [
        {
          id: 'jl-prod',
          name: 'jl-for-products',
          target: 'products',
          cluster_id: 'c1',
          query_set_id: 'qs1',
        },
        {
          id: 'jl-art',
          name: 'jl-for-articles',
          target: 'articles',
          cluster_id: 'c1',
          query_set_id: 'qs1',
        },
      ],
    });
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await pickCluster('c1');
    await pickTargetDropdown('products');
    await advanceToStep2();
    await pickQuerySet();
    await pickJudgmentList('jl-for-products');
    // The Step-2 advance gate at create-study-modal.tsx:386 requires
    // judgment_list_id to be set. We assert state via the gate behavior:
    // if the cascade reset fires correctly, the Next button is disabled
    // after we change target back to articles.
    fireEvent.click(screen.getByText(/Back/));
    await waitFor(() => expect(screen.getByTestId('step-1')).toBeInTheDocument());
    await pickTargetDropdown('articles');
    fireEvent.click(screen.getByTestId('step-next'));
    await waitFor(() => expect(screen.getByTestId('step-2')).toBeInTheDocument());
    // judgment_list_id should be '' — Next is disabled until we re-pick.
    const nextBtn = screen.getByTestId('step-next');
    expect(nextBtn).toBeDisabled();
    // Spy should now show the latest hook call uses ?target=articles.
    await waitFor(() => {
      const last = findLastJudgmentListsCall(spy);
      expect(last.searchParams.get('target')).toBe('articles');
    });
  });

  it('cascades target manual-input change → judgment_list_id reset (Case 2b, AC-9)', async () => {
    setupBackend({
      judgmentListsData: [
        {
          id: 'jl-prod',
          name: 'jl-for-products',
          target: 'products',
          cluster_id: 'c1',
          query_set_id: 'qs1',
        },
      ],
    });
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await pickCluster('c1');
    await pickTargetDropdown('products');
    await advanceToStep2();
    await pickQuerySet();
    await pickJudgmentList('jl-for-products');
    fireEvent.click(screen.getByText(/Back/));
    await waitFor(() => expect(screen.getByTestId('step-1')).toBeInTheDocument());
    // Switch to manual mode and edit the input — the registered RHF onChange
    // PLUS the new cascade reset must both fire.
    fireEvent.click(screen.getByRole('button', { name: 'Enter manually' }));
    await waitFor(() => expect(screen.getByPlaceholderText('products')).toBeInTheDocument());
    fireEvent.change(screen.getByPlaceholderText('products'), {
      target: { value: 'custom-target' },
    });
    fireEvent.click(screen.getByTestId('step-next'));
    await waitFor(() => expect(screen.getByTestId('step-2')).toBeInTheDocument());
    // Step-2 advance gated until we re-pick a judgment list.
    expect(screen.getByTestId('step-next')).toBeDisabled();
  });

  it('cascades cluster change → judgment_list_id reset (Case 3, AC-12 regression-lock)', async () => {
    setupBackend({
      judgmentListsData: [
        {
          id: 'jl-prod',
          name: 'jl-for-products',
          target: 'products',
          cluster_id: 'c1',
          query_set_id: 'qs1',
        },
      ],
    });
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await pickCluster('c1');
    await pickTargetDropdown('products');
    await advanceToStep2();
    await pickQuerySet();
    await pickJudgmentList('jl-for-products');
    fireEvent.click(screen.getByText(/Back/));
    await waitFor(() => expect(screen.getByTestId('step-1')).toBeInTheDocument());
    // Existing cluster-change handler at line 502-514 resets target +
    // judgment_list_id + query_set_id + template_id + manualMode. This
    // test locks that behavior against regression.
    fireEvent.change(screen.getByLabelText('Cluster'), { target: { value: 'c2' } });
    // Step-1 advance gate fails until we re-pick target.
    expect(screen.getByTestId('step-next')).toBeDisabled();
  });

  it('renders empty-state copy with target value and /judgments CTA when filter returns no matches (Case 4, AC-8)', async () => {
    setupBackend({ judgmentListsData: [] });
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await pickCluster('c1');
    await pickTargetDropdown('articles');
    await advanceToStep2();
    await pickQuerySet();
    // Empty-state message should mention the target value verbatim.
    await waitFor(() => {
      expect(
        screen.getByText(
          /No judgment lists for target "articles" on this cluster \+ query set\. Generate a new one from \/judgments\./,
        ),
      ).toBeInTheDocument();
    });
    // CTA link points at /judgments.
    const cta = screen.getByRole('link', { name: 'Generate judgments' });
    expect(cta).toHaveAttribute('href', '/judgments');
  });
});
