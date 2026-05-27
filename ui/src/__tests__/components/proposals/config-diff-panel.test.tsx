import '@testing-library/jest-dom/vitest';
import { render, screen, within } from '@testing-library/react';
import type { ReactElement } from 'react';
import { describe, expect, it } from 'vitest';

import { ConfigDiffPanel } from '@/components/proposals/config-diff-panel';
import { TooltipProvider } from '@/components/ui/tooltip';

function renderWithProvider(ui: ReactElement) {
  return render(<TooltipProvider>{ui}</TooltipProvider>);
}

describe('ConfigDiffPanel', () => {
  it('renders empty state when diff is empty', () => {
    renderWithProvider(<ConfigDiffPanel diff={{}} />);
    expect(screen.getByTestId('config-diff-empty')).toBeInTheDocument();
  });

  it('extracts from/to from the digest-worker {from, to} object form', () => {
    // Canonical shape produced by backend/workers/digest.py:1152.
    // Regression guard for the bug where the renderer dumped the entire
    // {from, to} object into the To column and left From empty.
    renderWithProvider(
      <ConfigDiffPanel
        diff={{
          title_boost: { from: 1.0, to: 1.98 },
          description_boost: { from: 1.0, to: 0.72 },
        }}
      />,
    );
    const titleRow = screen.getByTestId('config-diff-row-title_boost');
    const titleCells = within(titleRow).getAllByRole('cell');
    expect(titleCells[0]).toHaveTextContent('title_boost');
    expect(titleCells[1]).toHaveTextContent('1'); // from
    expect(titleCells[2]).toHaveTextContent('1.98'); // to
    expect(titleCells[2]).not.toHaveTextContent('{'); // not raw JSON
  });

  it('handles the legacy [before, after] 2-tuple form', () => {
    renderWithProvider(
      <ConfigDiffPanel
        diff={{
          rrf_window_size: [50, 100],
        }}
      />,
    );
    const row = screen.getByTestId('config-diff-row-rrf_window_size');
    const cells = within(row).getAllByRole('cell');
    expect(cells[1]).toHaveTextContent('50');
    expect(cells[2]).toHaveTextContent('100');
  });

  it('falls back to "—" From + raw JSON in To for unknown shapes', () => {
    renderWithProvider(
      <ConfigDiffPanel
        diff={{
          some_unstructured_value: { foo: 'bar' },
        }}
      />,
    );
    const row = screen.getByTestId('config-diff-row-some_unstructured_value');
    const cells = within(row).getAllByRole('cell');
    expect(cells[1]).toHaveTextContent('—');
    expect(cells[2]).toHaveTextContent(/\{.*foo.*bar/);
  });

  it('alphabetizes rows by key', () => {
    renderWithProvider(
      <ConfigDiffPanel
        diff={{
          zeta_boost: { from: 1, to: 2 },
          alpha_boost: { from: 1, to: 2 },
          mu_boost: { from: 1, to: 2 },
        }}
      />,
    );
    const rows = screen.getAllByRole('row').slice(1); // skip header
    expect(rows[0]).toHaveAttribute('data-testid', 'config-diff-row-alpha_boost');
    expect(rows[1]).toHaveAttribute('data-testid', 'config-diff-row-mu_boost');
    expect(rows[2]).toHaveAttribute('data-testid', 'config-diff-row-zeta_boost');
  });

  it('renders null From when only "to" is present in the object', () => {
    // Edge case: object has `to` but no `from` — falls through to unknown.
    // The 'from' in raw check requires BOTH keys; this is intentional so
    // we don't silently interpret partial shapes as canonical.
    renderWithProvider(
      <ConfigDiffPanel
        diff={{
          partial: { to: 0.5 },
        }}
      />,
    );
    const row = screen.getByTestId('config-diff-row-partial');
    const cells = within(row).getAllByRole('cell');
    expect(cells[1]).toHaveTextContent('—');
  });
});
