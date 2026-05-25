/**
 * feat_study_clone_from_previous Story 2.2 — StudyActionBar clone-button tests.
 *
 * Covers FR-1 / FR-3 / FR-11 + AC-1 / AC-2 / AC-4 / AC-15 / AC-16:
 *   (a) Clone button renders for every study status (queued / running / completed / failed / cancelled).
 *   (b) Click on a terminal-state source navigates directly to /studies?clone_from=<id>.
 *   (c) Click on a `running` source opens the AlertDialog; "Clone anyway" navigates; "Cancel" dismisses.
 */

import { describe, expect, it, vi } from 'vitest';
import { afterEach } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

import { StudyActionBar } from '@/components/studies/study-action-bar';
import { TooltipProvider } from '@/components/ui/tooltip';
import type { StudyDetail } from '@/lib/api/studies';

vi.mock('sonner', () => ({
  toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() }),
  Toaster: () => null,
}));

let lastPush: string | null = null;
vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: (url: string) => {
      lastPush = url;
    },
    replace: (_url: string) => {},
  }),
}));

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
    id: 'study-clone-src',
    name: 'Source study',
    cluster_id: 'cluster-1',
    target: 'products',
    template_id: 'template-1',
    query_set_id: 'qs-1',
    judgment_list_id: 'jl-1',
    search_space: { params: {} },
    objective: { metric: 'ndcg', k: 10, direction: 'maximize' },
    config: {},
    status: 'completed',
    failed_reason: null,
    optuna_study_name: 'study-clone-src',
    parent_study_id: null,
    baseline_metric: null,
    best_metric: 0.5,
    best_trial_id: null,
    created_at: '2026-05-23T10:00:00Z',
    started_at: '2026-05-23T10:00:01Z',
    completed_at: '2026-05-23T10:30:00Z',
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

describe('StudyActionBar — Clone button (feat_study_clone_from_previous Story 2.2)', () => {
  afterEach(() => {
    cleanup();
    lastPush = null;
  });

  it.each(['queued', 'running', 'completed', 'failed', 'cancelled'] as const)(
    '(a) renders Clone button for status=%s (FR-1: visible on every status)',
    (status) => {
      const study = makeStudy({ status });
      wrap(<StudyActionBar study={study} />);
      expect(screen.getByTestId('clone-study')).toBeInTheDocument();
    },
  );

  it('(a) Clone button sits to the LEFT of the Cancel button (FR-1 layout)', () => {
    const study = makeStudy({ status: 'running' });
    wrap(<StudyActionBar study={study} />);
    const clone = screen.getByTestId('clone-study');
    const cancel = screen.getByTestId('cancel-study');
    // Node.compareDocumentPosition returns DOCUMENT_POSITION_FOLLOWING (4)
    // when the argument comes AFTER `this`. We assert clone precedes cancel.
    expect(clone.compareDocumentPosition(cancel) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('(b) click on a completed source navigates directly to /studies?clone_from=<id> (FR-3)', () => {
    const study = makeStudy({ status: 'completed' });
    wrap(<StudyActionBar study={study} />);
    fireEvent.click(screen.getByTestId('clone-study'));
    expect(lastPush).toBe('/studies?clone_from=study-clone-src');
    expect(screen.queryByTestId('clone-running-confirm')).toBeNull();
  });

  it.each(['queued', 'failed', 'cancelled'] as const)(
    '(b) click on status=%s also navigates directly (terminal-state path)',
    (status) => {
      const study = makeStudy({ status });
      wrap(<StudyActionBar study={study} />);
      fireEvent.click(screen.getByTestId('clone-study'));
      expect(lastPush).toBe('/studies?clone_from=study-clone-src');
      expect(screen.queryByTestId('clone-running-confirm')).toBeNull();
    },
  );

  it('(c) click on a running source opens the confirmation dialog (FR-11)', () => {
    const study = makeStudy({ status: 'running' });
    wrap(<StudyActionBar study={study} />);
    fireEvent.click(screen.getByTestId('clone-study'));
    expect(screen.getByTestId('clone-running-confirm')).toBeInTheDocument();
    // FR-11: dialog appears WITHOUT navigation.
    expect(lastPush).toBeNull();
  });

  it('(c) "Clone anyway" in the dialog navigates + closes the dialog', () => {
    const study = makeStudy({ status: 'running' });
    wrap(<StudyActionBar study={study} />);
    fireEvent.click(screen.getByTestId('clone-study'));
    fireEvent.click(screen.getByTestId('clone-confirm-proceed'));
    expect(lastPush).toBe('/studies?clone_from=study-clone-src');
  });

  it('(c) "Cancel" in the dialog dismisses without navigation', () => {
    const study = makeStudy({ status: 'running' });
    wrap(<StudyActionBar study={study} />);
    fireEvent.click(screen.getByTestId('clone-study'));
    // The Radix AlertDialogCancel is the "Cancel" button by its
    // visible name — the dialog has only one such button.
    fireEvent.click(screen.getByRole('button', { name: /^Cancel$/ }));
    expect(lastPush).toBeNull();
  });
});
