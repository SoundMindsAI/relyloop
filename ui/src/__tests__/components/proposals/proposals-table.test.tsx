/**
 * `<ProposalsTable>` row-level rendering tests
 * (feat_data_table_primitive Story 3.2 Legacy Parity rows 5/6/7).
 *
 * Post-migration the table is a thin DataTable consumer; this file pins
 * the cell render functions on the column config (study/manual link,
 * MetricDelta, StatusBadge) without re-testing DataTable behaviour
 * (that's covered in `__tests__/components/common/data-table.test.tsx`).
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { type ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { ProposalsTable } from '@/components/proposals/proposals-table';
import type { DataTableUrlStateApi } from '@/hooks/use-data-table-url-state';
import type { ProposalSummary } from '@/lib/api/proposals';

import { server } from '../../setup';

const API_BASE = 'http://api.test';

vi.mock('next/link', () => ({
  default: ({ children, href, ...rest }: { children: ReactNode; href: string }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

vi.mock('next/navigation', () => ({
  usePathname: () => '/test',
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

function stubUrlState(): DataTableUrlStateApi {
  return {
    sort: null,
    filters: {},
    q: null,
    cursor: null,
    pageSize: 50,
    setSort: vi.fn(),
    setFilter: vi.fn(),
    setQ: vi.fn(),
    setCursor: vi.fn(),
    setPageSize: vi.fn(),
    clearCursor: vi.fn(),
    clearAllMatchers: vi.fn(),
    anyMatcherActive: false,
  };
}

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

function renderTable(rows: ProposalSummary[]) {
  // Stub the FK-option endpoints the column config consumes so the
  // useClusters / useTemplates calls in the toolbar don't 404.
  server.use(
    http.get(`${API_BASE}/api/v1/clusters`, () =>
      HttpResponse.json(
        { data: [], next_cursor: null, has_more: false },
        { headers: { 'X-Total-Count': '0' } },
      ),
    ),
    http.get(`${API_BASE}/api/v1/query-templates`, () =>
      HttpResponse.json(
        { data: [], next_cursor: null, has_more: false },
        { headers: { 'X-Total-Count': '0' } },
      ),
    ),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ProposalsTable
        rows={rows}
        totalCount={rows.length}
        has_more={false}
        next_cursor={null}
        isLoading={false}
        isError={false}
        urlState={stubUrlState()}
      />
    </QueryClientProvider>,
  );
}

describe('ProposalsTable', () => {
  it('renders the no-rows-exist empty state when rows is empty', () => {
    renderTable([]);
    expect(screen.getByTestId('data-table-empty-no-rows-exist')).toBeInTheDocument();
  });

  it('renders a row with a study link when study_id is set', () => {
    renderTable([row({ id: 'pA', study_id: 'sA' })]);
    expect(screen.getByTestId('proposal-row-pA')).toBeInTheDocument();
    expect(screen.getByTestId('proposal-row-pA-study-link')).toHaveAttribute('href', '/studies/sA');
    expect(screen.getByTestId('proposal-row-pA-detail-link')).toHaveAttribute(
      'href',
      '/proposals/pA',
    );
  });

  it('shows "manual" instead of a study link when study_id is null', () => {
    renderTable([row({ id: 'pM', study_id: null })]);
    expect(screen.getByTestId('proposal-row-pM-manual')).toHaveTextContent('manual');
    expect(screen.queryByTestId('proposal-row-pM-study-link')).not.toBeInTheDocument();
  });

  it('renders all four status variants', () => {
    renderTable([
      row({ id: 'pP', status: 'pending' }),
      row({ id: 'pO', status: 'pr_opened', pr_state: 'open' }),
      row({ id: 'pMm', status: 'pr_merged', pr_state: 'merged' }),
      row({ id: 'pR', status: 'rejected' }),
    ]);
    expect(screen.getByTestId('proposal-row-pP')).toBeInTheDocument();
    expect(screen.getByTestId('proposal-row-pO')).toBeInTheDocument();
    expect(screen.getByTestId('proposal-row-pMm')).toBeInTheDocument();
    expect(screen.getByTestId('proposal-row-pR')).toBeInTheDocument();
  });

  it('renders MetricDelta when metric_delta has the expected shape', () => {
    renderTable([
      row({
        id: 'pMD',
        metric_delta: {
          primary: 'ndcg@10',
          baseline: 0.4,
          best: 0.5,
          delta_pct: 25,
        },
      }),
    ]);
    expect(screen.getByText('ndcg@10')).toBeInTheDocument();
    expect(screen.getByTestId('metric-delta-pct')).toHaveTextContent('(+25.0%)');
  });
});
