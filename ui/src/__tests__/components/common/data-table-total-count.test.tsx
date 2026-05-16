/**
 * Total-count display tests (feat_data_table_primitive Story 2.5 / FR-7 + AC-14).
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { DataTableTotalCount } from '@/components/common/data-table-total-count';

describe('DataTableTotalCount', () => {
  it('renders the "1–N of M" range on the first page', () => {
    render(<DataTableTotalCount totalCount={12} rowsRendered={10} cursorStackLength={1} />);
    expect(screen.getByTestId('data-table-total-count')).toHaveTextContent('Showing 1–10 of 12');
  });

  it('renders the cursor-paginator-honest wording on subsequent pages', () => {
    render(<DataTableTotalCount totalCount={12} rowsRendered={2} cursorStackLength={2} />);
    expect(screen.getByTestId('data-table-total-count')).toHaveTextContent(
      'Showing 2 rows (of 12 matching)',
    );
  });

  it('renders the "No matching rows" branch when totalCount === 0', () => {
    render(<DataTableTotalCount totalCount={0} rowsRendered={0} cursorStackLength={1} />);
    expect(screen.getByTestId('data-table-total-count')).toHaveTextContent('No matching rows');
  });

  it('formats large numbers with thousands separators', () => {
    render(<DataTableTotalCount totalCount={12345} rowsRendered={50} cursorStackLength={1} />);
    expect(screen.getByTestId('data-table-total-count')).toHaveTextContent(
      'Showing 1–50 of 12,345',
    );
  });
});
