// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Tests for the list-summary count columns (feat_list_count_columns).
 *
 * - query-sets table gains a "Queries" column reading `query_count`.
 * - templates table gains a "Parameters" column reading `param_count`.
 *
 * Both render the integer via `toLocaleString()` (thousands separators for
 * large sets). The cell renderers only read `row.original`, so a minimal
 * stub object covers the contract without standing up a TanStack table.
 */

import { render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it } from 'vitest';

import { querySetsColumns } from '@/components/query-sets/query-sets-table.column-config';
import { templatesColumns } from '@/components/templates/templates-table.column-config';
import type { QuerySetSummary } from '@/lib/api/query-sets';
import type { QueryTemplateSummary } from '@/lib/api/query-templates';

function renderCell<T>(
  columns: { id?: string; cell?: unknown }[],
  columnId: string,
  original: T,
): void {
  const column = columns.find((c) => c.id === columnId);
  if (!column?.cell || typeof column.cell !== 'function') {
    throw new Error(`column ${columnId} or its cell renderer not found`);
  }
  const cell = column.cell as (ctx: { row: { original: T } }) => ReactNode;
  render(<>{cell({ row: { original } })}</>);
}

const baseQuerySet: QuerySetSummary = {
  id: 'qs-1',
  name: 'demo set',
  cluster_id: 'c1',
  query_count: 0,
  created_at: '2026-06-03T00:00:00Z',
};

const baseTemplate: QueryTemplateSummary = {
  id: 'tmpl-1',
  name: 'demo template',
  engine_type: 'elasticsearch',
  version: 1,
  param_count: 0,
  created_at: '2026-06-03T00:00:00Z',
};

describe('query-sets table — Queries column (query_count)', () => {
  it('the column exists with header "Queries"', () => {
    const col = querySetsColumns.find((c) => c.id === 'query_count');
    expect(col).toBeDefined();
    expect(col?.header).toBe('Queries');
  });

  it('renders the query_count value', () => {
    renderCell(querySetsColumns, 'query_count', { ...baseQuerySet, query_count: 42 });
    expect(screen.getByText('42')).toBeInTheDocument();
  });

  it('renders 0 for an empty set (not blank/undefined)', () => {
    renderCell(querySetsColumns, 'query_count', { ...baseQuerySet, query_count: 0 });
    expect(screen.getByText('0')).toBeInTheDocument();
  });

  it('formats large counts with thousands separators', () => {
    renderCell(querySetsColumns, 'query_count', { ...baseQuerySet, query_count: 12500 });
    expect(screen.getByText('12,500')).toBeInTheDocument();
  });
});

describe('templates table — Parameters column (param_count)', () => {
  it('the column exists with header "Parameters"', () => {
    const col = templatesColumns.find((c) => c.id === 'param_count');
    expect(col).toBeDefined();
    expect(col?.header).toBe('Parameters');
  });

  it('renders the param_count value', () => {
    renderCell(templatesColumns, 'param_count', { ...baseTemplate, param_count: 6 });
    expect(screen.getByText('6')).toBeInTheDocument();
  });

  it('renders 0 for a non-tunable template', () => {
    renderCell(templatesColumns, 'param_count', { ...baseTemplate, param_count: 0 });
    expect(screen.getByText('0')).toBeInTheDocument();
  });
});
