// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * feat_auto_followup_studies Story 3.1 — AutoFollowupChainPanel tests.
 *
 * Covers FR-10 frontend render conditions: panel renders only when at
 * least one of (parent_study_id set, auto_followup_depth > 0,
 * chainChildren non-empty); parent link renders when parent_study_id;
 * remaining-depth line renders when depth > 0; children table renders
 * one row per child.
 */

import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';

import { AutoFollowupChainPanel } from '@/components/studies/auto-followup-chain-panel';
import { TooltipProvider } from '@/components/ui/tooltip';
import type { StudyDetail, StudySummary } from '@/lib/api/studies';

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

function renderPanel(props: { study: StudyDetail; chainChildren: StudySummary[] }) {
  return render(
    <TooltipProvider>
      <AutoFollowupChainPanel study={props.study} chainChildren={props.chainChildren} />
    </TooltipProvider>,
  );
}

describe('AutoFollowupChainPanel', () => {
  afterEach(() => cleanup());

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
});
