// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { JudgmentListsTable } from '@/components/judgments/judgment-lists-table';
import type { JudgmentListSummary } from '@/lib/api/judgments';
import type { DataTableUrlStateApi } from '@/hooks/use-data-table-url-state';

vi.mock('next/link', () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

const urlState = {
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
  clearAllMatchers: vi.fn(),
  anyMatcherActive: false,
} as unknown as DataTableUrlStateApi;

const row: JudgmentListSummary = {
  id: 'jl-1',
  name: 'Prod relevance labels',
  status: 'complete',
  target: 'products',
  cluster_id: 'c-1',
  query_set_id: 'qs-1',
  created_at: '2026-05-12T00:00:00Z',
  description: null,
};

describe('JudgmentListsTable (/judgments index)', () => {
  it('links each judgment list name to its detail page', () => {
    render(
      <JudgmentListsTable
        rows={[row]}
        totalCount={1}
        has_more={false}
        next_cursor={null}
        isLoading={false}
        isError={false}
        urlState={urlState}
      />,
    );
    const link = screen.getByRole('link', { name: 'Prod relevance labels' });
    expect(link).toHaveAttribute('href', '/judgments/jl-1');
  });

  it('renders a helpful empty state when there are no judgment lists', () => {
    render(
      <JudgmentListsTable
        rows={[]}
        totalCount={0}
        has_more={false}
        next_cursor={null}
        isLoading={false}
        isError={false}
        urlState={urlState}
      />,
    );
    expect(screen.getByText('No judgment lists yet')).toBeInTheDocument();
  });
});
