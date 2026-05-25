/**
 * feat_auto_followup_studies Story 3.3 — StudyActionBar cascade-radio tests.
 *
 * Covers the cascade-radio render-conditions + value forwarding to the
 * cancel mutation (FR-8 frontend + cycle-1 C1-8 + cycle-2 C2-4):
 *   - Hide radio when no chain context (matches pre-Story-3.3 behavior).
 *   - Show radio + default to cascade=true when in-flight child exists.
 *   - Show radio when status='running' + auto_followup_depth > 0 (anticipated).
 *   - cascade=true → POST /cancel?cascade=true (default radio selection).
 *   - cascade=false → POST /cancel?cascade=false.
 */

import { http, HttpResponse } from 'msw';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

import { StudyActionBar } from '@/components/studies/study-action-bar';
import { TooltipProvider } from '@/components/ui/tooltip';
import type { StudyDetail, StudySummary } from '@/lib/api/studies';

import { server } from '../../setup';

vi.mock('sonner', () => ({
  toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() }),
  Toaster: () => null,
}));

// feat_study_clone_from_previous Story 2.2 added `useRouter` to
// StudyActionBar for the Clone-button navigate path. The cascade tests
// don't navigate, but they still need the router stub so `useRouter()`
// doesn't throw "invariant expected app router to be mounted" during
// render.
vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: (_url: string) => {},
    replace: (_url: string) => {},
  }),
}));

const API_BASE = 'http://api.test';

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider delayDuration={0}>{node}</TooltipProvider>
    </QueryClientProvider>,
  );
}

function makeStudy(overrides: Partial<StudyDetail> = {}): StudyDetail {
  return {
    id: 'study-1',
    name: 'Test study',
    cluster_id: 'cluster-1',
    target: 'products',
    template_id: 'template-1',
    query_set_id: 'qs-1',
    judgment_list_id: 'jl-1',
    search_space: { params: {} },
    objective: { metric: 'ndcg', k: 10, direction: 'maximize' },
    config: {},
    status: 'running',
    failed_reason: null,
    optuna_study_name: 'study-1',
    parent_study_id: null,
    baseline_metric: null,
    best_metric: null,
    best_trial_id: null,
    created_at: '2026-05-23T10:00:00Z',
    started_at: '2026-05-23T10:00:01Z',
    completed_at: null,
    trials_summary: {
      total: 5,
      complete: 5,
      failed: 0,
      pruned: 0,
      best_primary_metric: 0.5,
    },
    confidence: null,
    ...overrides,
  } as StudyDetail;
}

function makeChild(overrides: Partial<StudySummary> = {}): StudySummary {
  return {
    id: 'child-1',
    name: 'Test study (chain depth 2)',
    cluster_id: 'cluster-1',
    status: 'running',
    best_metric: null,
    created_at: '2026-05-23T11:00:00Z',
    completed_at: null,
    ...overrides,
  } as StudySummary;
}

describe('StudyActionBar cascade radio (Story 3.3)', () => {
  afterEach(() => cleanup());

  it('hides the cascade radio when there are no in-flight children and no anticipated child', () => {
    const study = makeStudy({ status: 'running', config: {} });
    wrap(<StudyActionBar study={study} chainChildren={[]} />);
    fireEvent.click(screen.getByTestId('cancel-study'));
    expect(screen.queryByTestId('cancel-cascade-radio-group')).toBeNull();
  });

  it('shows the cascade radio when an in-flight child exists', () => {
    const study = makeStudy({ status: 'running', config: {} });
    const child = makeChild({ status: 'running' });
    wrap(<StudyActionBar study={study} chainChildren={[child]} />);
    fireEvent.click(screen.getByTestId('cancel-study'));
    expect(screen.getByTestId('cancel-cascade-radio-group')).toBeInTheDocument();
  });

  it('shows the cascade radio when status=running + auto_followup_depth > 0 (anticipated child)', () => {
    const study = makeStudy({ status: 'running', config: { auto_followup_depth: 3 } });
    wrap(<StudyActionBar study={study} chainChildren={[]} />);
    fireEvent.click(screen.getByTestId('cancel-study'));
    expect(screen.getByTestId('cancel-cascade-radio-group')).toBeInTheDocument();
  });

  it('defaults to cascade=true (D-6) when the radio is shown', () => {
    const study = makeStudy({ status: 'running', config: { auto_followup_depth: 2 } });
    wrap(<StudyActionBar study={study} chainChildren={[]} />);
    fireEvent.click(screen.getByTestId('cancel-study'));
    const cascadeTrue = screen.getByTestId('cascade-true') as HTMLInputElement;
    const cascadeFalse = screen.getByTestId('cascade-false') as HTMLInputElement;
    expect(cascadeTrue.checked).toBe(true);
    expect(cascadeFalse.checked).toBe(false);
  });

  it('POSTs ?cascade=true when the cascade radio is left at the default', async () => {
    let lastCascadeParam: string | null = null;
    server.use(
      http.post(`${API_BASE}/api/v1/studies/study-1/cancel`, ({ request }) => {
        const url = new URL(request.url);
        lastCascadeParam = url.searchParams.get('cascade');
        return HttpResponse.json(makeStudy({ status: 'cancelled' }));
      }),
    );
    const study = makeStudy({ status: 'running', config: { auto_followup_depth: 3 } });
    wrap(<StudyActionBar study={study} chainChildren={[makeChild()]} />);
    fireEvent.click(screen.getByTestId('cancel-study'));
    fireEvent.click(screen.getByTestId('confirm-cancel'));
    await waitFor(() => expect(lastCascadeParam).toBe('true'));
  });

  it('POSTs ?cascade=false when the operator picks "Cancel parent only"', async () => {
    let lastCascadeParam: string | null = null;
    server.use(
      http.post(`${API_BASE}/api/v1/studies/study-1/cancel`, ({ request }) => {
        const url = new URL(request.url);
        lastCascadeParam = url.searchParams.get('cascade');
        return HttpResponse.json(makeStudy({ status: 'cancelled' }));
      }),
    );
    const study = makeStudy({ status: 'running', config: { auto_followup_depth: 3 } });
    wrap(<StudyActionBar study={study} chainChildren={[makeChild()]} />);
    fireEvent.click(screen.getByTestId('cancel-study'));
    fireEvent.click(screen.getByTestId('cascade-false'));
    fireEvent.click(screen.getByTestId('confirm-cancel'));
    await waitFor(() => expect(lastCascadeParam).toBe('false'));
  });
});

// Cleanup helper — vitest's `cleanup` is normally auto-imported by RTL,
// but the explicit import keeps the per-test reset deterministic.
import { cleanup } from '@testing-library/react';
