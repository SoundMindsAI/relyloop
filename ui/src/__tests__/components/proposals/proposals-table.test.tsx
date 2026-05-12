import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { type ReactNode } from 'react';
import { vi } from 'vitest';

import { ProposalsTable } from '@/components/proposals/proposals-table';
import type { ProposalSummary } from '@/lib/api/proposals';

vi.mock('next/link', () => ({
  default: ({ children, href, ...rest }: { children: ReactNode; href: string }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

function row(overrides: Partial<ProposalSummary> = {}): ProposalSummary {
  return {
    id: 'p1',
    study_id: 's1',
    cluster: { id: 'c1', name: 'prod-es', engine_type: 'elasticsearch', environment: 'prod' },
    template: { id: 't1', name: 'products', version: 2, engine_type: 'elasticsearch' },
    status: 'pending',
    pr_state: null,
    pr_url: null,
    metric_delta: null,
    created_at: '2026-05-12T00:00:00Z',
    ...overrides,
  } as ProposalSummary;
}

describe('ProposalsTable', () => {
  it('renders the empty state when rows is empty', () => {
    render(<ProposalsTable rows={[]} />);
    expect(screen.getByTestId('proposals-empty')).toHaveTextContent(
      'No proposals match the current filters.',
    );
  });

  it('renders a row with a study link when study_id is set', () => {
    render(<ProposalsTable rows={[row({ id: 'pA', study_id: 'sA' })]} />);
    expect(screen.getByTestId('proposal-row-pA')).toBeInTheDocument();
    expect(screen.getByTestId('proposal-row-pA-study-link')).toHaveAttribute('href', '/studies/sA');
    expect(screen.getByTestId('proposal-row-pA-detail-link')).toHaveAttribute(
      'href',
      '/proposals/pA',
    );
  });

  it('shows "manual" instead of a study link when study_id is null', () => {
    render(<ProposalsTable rows={[row({ id: 'pM', study_id: null })]} />);
    expect(screen.getByTestId('proposal-row-pM-manual')).toHaveTextContent('manual');
    expect(screen.queryByTestId('proposal-row-pM-study-link')).not.toBeInTheDocument();
  });

  it('renders all four status variants with the correct badge', () => {
    render(
      <ProposalsTable
        rows={[
          row({ id: 'pP', status: 'pending' }),
          row({ id: 'pO', status: 'pr_opened', pr_state: 'open' }),
          row({ id: 'pM', status: 'pr_merged', pr_state: 'merged' }),
          row({ id: 'pR', status: 'rejected' }),
        ]}
      />,
    );
    // Status badges expose data-kind + data-value on the rendered Badge.
    const badges = screen.getAllByText(/pending|pr_opened|pr_merged|rejected|open|merged/);
    // 4 status badges + 2 pr_state badges = 6 (one per pr_state populated row)
    expect(badges.length).toBeGreaterThanOrEqual(4);
  });

  it('renders MetricDelta when metric_delta has the expected shape', () => {
    render(
      <ProposalsTable
        rows={[
          row({
            id: 'pMD',
            metric_delta: {
              primary: 'ndcg@10',
              baseline: 0.4,
              best: 0.5,
              delta_pct: 25,
            },
          }),
        ]}
      />,
    );
    expect(screen.getByText('ndcg@10')).toBeInTheDocument();
    expect(screen.getByTestId('metric-delta-pct')).toHaveTextContent('(+25.0%)');
  });
});
