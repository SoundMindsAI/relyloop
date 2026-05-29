/**
 * Regression test for bug_ceiling_badge_assumes_maximize_direction.
 *
 * The "Ceiling" badge on the studies list flags best_metric >= 0.99. That's
 * correct for MAXIMIZE objectives (NDCG/MAP/MRR/Precision/Recall — pinned at
 * the upper bound) but WRONG for MINIMIZE objectives, where 0.99 is a *bad*
 * score, not a ceiling. After feat_study_baseline_trial added
 * `direction: 'maximize' | 'minimize'` to the objective spec, a minimize
 * study is creatable via the API, so the badge could actively mislabel one.
 *
 * The fix gates the badge on `direction === 'maximize'`. These tests render
 * the best_metric column's cell directly and assert the badge presence.
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { studiesColumns } from '@/components/studies/studies-table.column-config';
import { TooltipProvider } from '@/components/ui/tooltip';
import type { StudySummary } from '@/lib/api/studies';

function renderBestMetricCell(overrides: Partial<StudySummary>) {
  const column = studiesColumns.find((c) => c.id === 'best_metric');
  if (!column?.cell || typeof column.cell !== 'function') {
    throw new Error('best_metric column or its cell renderer not found');
  }
  const original: StudySummary = {
    id: 'study-1',
    name: 'demo',
    cluster_id: 'c1',
    status: 'completed',
    best_metric: 0.995,
    direction: 'maximize',
    created_at: '2026-05-29T00:00:00Z',
    completed_at: '2026-05-29T00:05:00Z',
    ...overrides,
  };
  // The DataTable cell renderer only reads `row.original`; a minimal stub
  // covers the contract without standing up a full TanStack Table instance.
  const cell = column.cell as (ctx: { row: { original: StudySummary } }) => React.ReactNode;
  // The maximize badge embeds an InfoTooltip (Radix Tooltip), which needs a
  // TooltipProvider in the tree — matches the studies page, which wraps the
  // table in one. delayDuration=0 keeps it test-fast.
  return render(<TooltipProvider delayDuration={0}>{cell({ row: { original } })}</TooltipProvider>);
}

describe('studies-table best_metric ceiling badge', () => {
  it('shows the Ceiling badge for a maximize study pinned at >= 0.99', () => {
    renderBestMetricCell({ direction: 'maximize', best_metric: 0.995 });
    expect(screen.getByTestId('best-metric-ceiling-study-1')).toBeInTheDocument();
    expect(screen.getByText(/ceiling/i)).toBeInTheDocument();
  });

  it('does NOT show the Ceiling badge for a minimize study at 0.99 (the bug)', () => {
    // 0.99 on a minimize objective is a *bad* score, not a ceiling — the
    // badge must not appear, or it would claim the optimizer found nothing
    // special when the truth is the opposite.
    renderBestMetricCell({ direction: 'minimize', best_metric: 0.995 });
    expect(screen.queryByTestId('best-metric-ceiling-study-1')).not.toBeInTheDocument();
    expect(screen.queryByText(/ceiling/i)).not.toBeInTheDocument();
    // The raw value still renders.
    expect(screen.getByText('0.995')).toBeInTheDocument();
  });

  it('shows the badge when direction is undefined at >= 0.99 (rolling-deploy default)', () => {
    // During a rolling deploy the FE can run ahead of the BE, so an old
    // API response may omit `direction`. Absent direction must default to
    // maximize (the backend's own default) — the badge should still show
    // for a pinned maximize study rather than vanish for everyone. Per
    // Gemini PR #305: `!== 'minimize'` not `=== 'maximize'`.
    renderBestMetricCell({
      direction: undefined as unknown as StudySummary['direction'],
      best_metric: 0.995,
    });
    expect(screen.getByTestId('best-metric-ceiling-study-1')).toBeInTheDocument();
  });

  it('does not show the badge for a maximize study below the threshold', () => {
    renderBestMetricCell({ direction: 'maximize', best_metric: 0.5 });
    expect(screen.queryByTestId('best-metric-ceiling-study-1')).not.toBeInTheDocument();
  });

  it('renders an em dash when best_metric is null regardless of direction', () => {
    const { container } = renderBestMetricCell({ direction: 'minimize', best_metric: null });
    expect(container.textContent).toContain('—');
    expect(screen.queryByTestId('best-metric-ceiling-study-1')).not.toBeInTheDocument();
  });
});
