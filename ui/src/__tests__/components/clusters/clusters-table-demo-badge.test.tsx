import { render, screen } from '@testing-library/react';
import { type ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { clustersColumns } from '@/components/clusters/clusters-table.column-config';
import { TooltipProvider } from '@/components/ui/tooltip';

vi.mock('next/link', () => ({
  default: ({ children, href }: { children: ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

// Minimal cluster row shape — only the fields the name column cell reads.
function makeRow(name: string) {
  return {
    original: {
      id: `id-${name}`,
      name,
      engine_type: 'elasticsearch',
      environment: 'prod',
      base_url: 'http://elasticsearch:9200',
      auth_kind: 'es_basic',
      target_filter: null,
      created_at: '2026-05-21T00:00:00Z',
      health_check: {
        status: 'green',
        version: '9.0.0',
        checked_at: '2026-05-21T00:00:00Z',
        error: null,
      },
    },
  };
}

function renderNameCell(name: string) {
  const nameColumn = clustersColumns.find((c) => c.id === 'name');
  if (!nameColumn || typeof nameColumn.cell !== 'function') {
    throw new Error('name column or cell renderer missing from clustersColumns');
  }
  // TanStack Table passes `{ row, ... }` to cell renderers; we pass a
  // minimal stub that gives the cell the row shape it needs.
  const cellContext = { row: makeRow(name) };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const cellNode = nameColumn.cell(cellContext as any);
  return render(<TooltipProvider>{cellNode}</TooltipProvider>);
}

describe('clusters-table name column — demo badge', () => {
  it('renders <DemoBadge> for a cluster name in DEMO_CLUSTER_SLUGS', () => {
    renderNameCell('acme-products-prod');
    expect(screen.getByTestId('demo-badge')).toBeInTheDocument();
  });

  it('does NOT render <DemoBadge> for a non-demo cluster name', () => {
    renderNameCell('local-es');
    expect(screen.queryByTestId('demo-badge')).toBeNull();
  });

  it.each([
    'acme-products-prod',
    'corp-docs-search',
    'news-search-staging',
    'jobs-marketplace-prod',
  ])('renders the badge for %s', (slug) => {
    renderNameCell(slug);
    expect(screen.getByTestId('demo-badge')).toBeInTheDocument();
  });
});
