// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * feat_auto_followup_studies Story 3.1 — AutoFollowupChainPanel tests
 * (extended by feat_overnight_autopilot Story 2.1).
 *
 * Covers FR-10 frontend render conditions: panel renders only when at
 * least one of (parent_study_id set, auto_followup_depth > 0,
 * chainChildren non-empty, or the D-13 summary predicate); parent link
 * renders when parent_study_id; remaining-depth line renders when
 * depth > 0; children table renders one row per child.
 *
 * feat_overnight_autopilot FR-4: rolled-up chain summary (ordered links,
 * cumulative lift, best-config 3-branch per D-11, stop-reason phrases).
 * `useStudyChain` is mocked per-test; the original module is preserved
 * (importOriginal) so the type re-exports + other hooks stay real.
 */

import type { UseQueryResult } from '@tanstack/react-query';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';

import { AutoFollowupChainPanel } from '@/components/studies/auto-followup-chain-panel';
import { TooltipProvider } from '@/components/ui/tooltip';
import type {
  StudyChainLink,
  StudyChainResponse,
  StudyDetail,
  StudySummary,
} from '@/lib/api/studies';
import { useStudyChain } from '@/lib/api/studies';

vi.mock('@/lib/api/studies', async (importOriginal) => {
  const mod = await importOriginal<typeof import('@/lib/api/studies')>();
  return { ...mod, useStudyChain: vi.fn() };
});

const mockedUseStudyChain = vi.mocked(useStudyChain);

/** Default mock: no chain data (mirrors the pre-overnight null-context world). */
function setChain(data: StudyChainResponse | undefined): void {
  mockedUseStudyChain.mockReturnValue({
    data,
  } as unknown as UseQueryResult<StudyChainResponse, never>);
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
    status: 'completed',
    failed_reason: null,
    optuna_study_name: 'study-1',
    parent_study_id: null,
    baseline_metric: null,
    best_metric: 0.5,
    best_trial_id: 'trial-best',
    created_at: '2026-05-23T10:00:00Z',
    started_at: '2026-05-23T10:00:01Z',
    completed_at: '2026-05-23T11:00:00Z',
    trials_summary: {
      total: 20,
      complete: 20,
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
    status: 'queued',
    best_metric: null,
    created_at: '2026-05-23T11:00:05Z',
    completed_at: null,
    ...overrides,
  } as StudySummary;
}

function makeLink(overrides: Partial<StudyChainLink> = {}): StudyChainLink {
  return {
    id: 'link-1',
    name: 'Link 1',
    status: 'completed',
    best_metric: 0.5,
    baseline_metric: 0.4,
    direction: 'maximize',
    delta_from_prev: null,
    proposal_id: null,
    auto_followup_depth_remaining: null,
    failed_reason: null,
    created_at: '2026-05-23T10:00:00Z',
    completed_at: '2026-05-23T11:00:00Z',
    ...overrides,
  } as StudyChainLink;
}

function makeChain(overrides: Partial<StudyChainResponse> = {}): StudyChainResponse {
  return {
    anchor_study_id: 'link-1',
    best_link_id: null,
    best_metric: null,
    cumulative_lift: null,
    direction: 'maximize',
    stop_reason: 'in_flight',
    proposal_id_for_best_link: null,
    links: [makeLink()],
    ...overrides,
  } as StudyChainResponse;
}

function renderPanel(props: { study: StudyDetail; chainChildren: StudySummary[] }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>
      <TooltipProvider>{children}</TooltipProvider>
    </QueryClientProvider>
  );
  return render(
    <AutoFollowupChainPanel study={props.study} chainChildren={props.chainChildren} />,
    { wrapper },
  );
}

describe('AutoFollowupChainPanel', () => {
  beforeEach(() => {
    // Default: no chain data — preserves the original null-context behavior
    // for the 7 legacy cases that predate the rolled-up summary.
    setChain(undefined);
  });
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  // ---------------------------------------------------------------------------
  // Existing 7 cases (preserved unchanged in intent — AC-12).
  // ---------------------------------------------------------------------------

  it('renders nothing when there is no chain context', () => {
    const study = makeStudy({ parent_study_id: null, config: {} });
    renderPanel({ study, chainChildren: [] });
    expect(screen.queryByTestId('auto-followup-chain-panel')).toBeNull();
  });

  it('renders the panel + parent link when parent_study_id is set', () => {
    const study = makeStudy({ parent_study_id: 'parent-1' });
    renderPanel({ study, chainChildren: [] });
    expect(screen.getByTestId('auto-followup-chain-panel')).toBeInTheDocument();
    const link = screen.getByTestId('auto-followup-parent-link');
    expect(link).toBeInTheDocument();
    expect(link.querySelector('a')?.getAttribute('href')).toBe('/studies/parent-1');
  });

  it('renders the remaining-depth indicator when config.auto_followup_depth > 0', () => {
    const study = makeStudy({ config: { auto_followup_depth: 2 } });
    renderPanel({ study, chainChildren: [] });
    const line = screen.getByTestId('auto-followup-remaining-depth');
    expect(line.textContent).toContain('Remaining auto-follow-ups');
    expect(line.textContent).toContain('2');
  });

  it('hides the depth line when auto_followup_depth is 0 (terminal leaf)', () => {
    const study = makeStudy({ config: { auto_followup_depth: 0 } });
    renderPanel({ study, chainChildren: [] });
    // 0 is the worker-internal terminal value; nothing to show beyond
    // the children list (which is also empty here, so the whole panel
    // is hidden).
    expect(screen.queryByTestId('auto-followup-chain-panel')).toBeNull();
  });

  it('renders the children table with one row per direct child', () => {
    const study = makeStudy({ config: { auto_followup_depth: 1 } });
    const child = makeChild({ id: 'child-7', name: 'Test study (chain depth 1)' });
    renderPanel({ study, chainChildren: [child] });
    expect(screen.getByTestId('auto-followup-children-table')).toBeInTheDocument();
    const childLink = screen.getByText('Test study (chain depth 1)');
    expect(childLink.closest('a')?.getAttribute('href')).toBe('/studies/child-7');
  });

  it('renders all three sub-elements when parent + depth + children all present', () => {
    const study = makeStudy({
      parent_study_id: 'parent-1',
      config: { auto_followup_depth: 2 },
    });
    const child = makeChild();
    renderPanel({ study, chainChildren: [child] });
    expect(screen.getByTestId('auto-followup-parent-link')).toBeInTheDocument();
    expect(screen.getByTestId('auto-followup-remaining-depth')).toBeInTheDocument();
    expect(screen.getByTestId('auto-followup-children-table')).toBeInTheDocument();
  });

  it('shows the children table even when chain context is only via children (no parent, no depth)', () => {
    const study = makeStudy({ parent_study_id: null, config: {} });
    const child = makeChild({ status: 'running' });
    renderPanel({ study, chainChildren: [child] });
    expect(screen.getByTestId('auto-followup-chain-panel')).toBeInTheDocument();
    expect(screen.queryByTestId('auto-followup-parent-link')).toBeNull();
    expect(screen.queryByTestId('auto-followup-remaining-depth')).toBeNull();
    expect(screen.getByTestId('auto-followup-children-table')).toBeInTheDocument();
  });

  // ---------------------------------------------------------------------------
  // feat_overnight_autopilot FR-4 — rolled-up chain summary.
  // ---------------------------------------------------------------------------

  it('AC-11: renders the rolled-up summary for a 3-link chain (cumulative lift + Awaiting-proposal branch)', () => {
    const links = [
      makeLink({ id: 's1', name: 'S1', best_metric: 0.5, delta_from_prev: null }),
      makeLink({ id: 's2', name: 'S2', best_metric: 0.58, delta_from_prev: 0.08 }),
      makeLink({
        id: 's3',
        name: 'S3',
        best_metric: 0.64,
        delta_from_prev: 0.06,
        proposal_id: null,
      }),
    ];
    setChain(
      makeChain({
        links,
        anchor_study_id: 's1',
        best_link_id: 's3',
        best_metric: 0.64,
        cumulative_lift: 0.14,
        proposal_id_for_best_link: null,
        stop_reason: 'no_lift',
      }),
    );
    const study = makeStudy({ id: 's1', config: { auto_followup_depth: 0 } });
    renderPanel({ study, chainChildren: [] });

    const summary = screen.getByTestId('chain-summary');
    expect(summary).toBeInTheDocument();
    expect(summary.textContent).toContain('Overnight chain — 3 studies');
    // Ordered link list with each name.
    expect(screen.getByText('S1').closest('a')?.getAttribute('href')).toBe('/studies/s1');
    expect(screen.getByText('S2').closest('a')?.getAttribute('href')).toBe('/studies/s2');
    expect(screen.getByText('S3').closest('a')?.getAttribute('href')).toBe('/studies/s3');
    // Cumulative lift formatted +0.1400.
    expect(screen.getByTestId('chain-summary-cumulative-lift').textContent).toContain('+0.1400');
    // Best-config Awaiting-proposal branch (no proposal on S3) — plain text, not a link.
    const best = screen.getByTestId('chain-summary-best-config');
    expect(best.textContent).toContain('Best config: S3 (Awaiting proposal)');
    expect(best.querySelector('a')).toBeNull();
    // Stop-reason phrase.
    expect(screen.getByTestId('chain-summary-stop-reason').textContent).toContain(
      'no further improvement',
    );
  });

  it('AC-12a: single-link opt-in renders the summary (depth_remaining set, no children)', () => {
    const link = makeLink({
      id: 's1',
      name: 'S1',
      best_metric: 0.41,
      baseline_metric: 0.4,
      delta_from_prev: null,
      auto_followup_depth_remaining: 3,
    });
    setChain(
      makeChain({
        links: [link],
        anchor_study_id: 's1',
        best_link_id: 's1',
        best_metric: 0.41,
        cumulative_lift: 0.01,
        proposal_id_for_best_link: null,
        stop_reason: 'no_lift',
      }),
    );
    const study = makeStudy({ id: 's1', config: {} });
    renderPanel({ study, chainChildren: [] });

    expect(screen.getByTestId('chain-summary')).toBeInTheDocument();
    expect(screen.getByTestId('chain-summary-cumulative-lift').textContent).toContain('+0.0100');
    expect(screen.getByTestId('chain-summary-stop-reason').textContent).toContain(
      'no further improvement',
    );
  });

  it('D-11 branch A: best-config renders a proposal link when proposal_id_for_best_link is set', () => {
    const links = [
      makeLink({ id: 's1', name: 'S1', best_metric: 0.5 }),
      makeLink({
        id: 's2',
        name: 'S2',
        best_metric: 0.6,
        delta_from_prev: 0.1,
        proposal_id: 'prop-9',
      }),
    ];
    setChain(
      makeChain({
        links,
        anchor_study_id: 's1',
        best_link_id: 's2',
        best_metric: 0.6,
        cumulative_lift: 0.2,
        proposal_id_for_best_link: 'prop-9',
        stop_reason: 'depth_exhausted',
      }),
    );
    const study = makeStudy({ id: 's1', config: { auto_followup_depth: 0 } });
    renderPanel({ study, chainChildren: [] });

    const best = screen.getByTestId('chain-summary-best-config');
    const anchor = best.querySelector('a');
    expect(anchor?.getAttribute('href')).toBe('/proposals/prop-9');
    expect(anchor?.textContent).toBe('S2');
  });

  it('D-11 branch C: best-config renders "—" when best_link_id is null', () => {
    setChain(
      makeChain({
        links: [
          makeLink({ id: 's1', name: 'S1' }),
          makeLink({ id: 's2', name: 'S2', status: 'running', best_metric: null }),
        ],
        anchor_study_id: 's1',
        best_link_id: null,
        best_metric: null,
        cumulative_lift: null,
        proposal_id_for_best_link: null,
        stop_reason: 'in_flight',
      }),
    );
    const study = makeStudy({ id: 's1', config: { auto_followup_depth: 0 } });
    renderPanel({ study, chainChildren: [] });

    const best = screen.getByTestId('chain-summary-best-config');
    expect(best.textContent).toBe('Best config: —');
    expect(best.querySelector('a')).toBeNull();
    // Cumulative lift null → "—".
    expect(screen.getByTestId('chain-summary-cumulative-lift').textContent).toContain('—');
  });

  it('stop-reason mapping renders the expected phrase for each of the 6 wire values', () => {
    const cases: Array<[StudyChainResponse['stop_reason'], string]> = [
      ['depth_exhausted', 'depth budget exhausted'],
      ['no_lift', 'no further improvement'],
      ['budget', 'daily LLM budget reached'],
      ['parent_failed', 'parent study failed or was cancelled'],
      ['cancelled', 'operator cancelled the chain'],
      ['in_flight', 'chain still running'],
    ];
    for (const [wire, phrase] of cases) {
      setChain(
        makeChain({
          links: [makeLink({ id: 's1', name: 'S1' }), makeLink({ id: 's2', name: 'S2' })],
          stop_reason: wire,
        }),
      );
      const study = makeStudy({ id: 's1', config: { auto_followup_depth: 0 } });
      renderPanel({ study, chainChildren: [] });
      expect(screen.getByTestId('chain-summary-stop-reason').textContent).toContain(phrase);
      cleanup();
    }
  });

  it('does not render the summary for a true single-link non-chained study (opted out)', () => {
    // links.length === 1, no parent, depth_remaining null → showSummary false.
    setChain(
      makeChain({
        links: [makeLink({ id: 's1', name: 'S1', auto_followup_depth_remaining: null })],
        anchor_study_id: 's1',
        stop_reason: 'no_lift',
      }),
    );
    const study = makeStudy({ id: 's1', parent_study_id: null, config: {} });
    renderPanel({ study, chainChildren: [] });
    expect(screen.queryByTestId('chain-summary')).toBeNull();
    // Whole panel hidden too (no other chain context).
    expect(screen.queryByTestId('auto-followup-chain-panel')).toBeNull();
  });
});
