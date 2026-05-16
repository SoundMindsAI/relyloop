/**
 * Debounced text-search tests (feat_data_table_primitive Story 2.4 / FR-6).
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { DataTableSearch } from '@/components/common/data-table-search';

// Using real timers + short debounceMs avoids the fake-timer/act interaction
// that swallowed flush events in earlier attempts; tests still complete in
// <100ms each.
const FAST_DEBOUNCE_MS = 20;
const WAIT_BUFFER_MS = 200;

describe('DataTableSearch', () => {
  it('does not call onQChange for under-length input (no active q)', async () => {
    const onQChange = vi.fn();
    render(<DataTableSearch value={null} onQChange={onQChange} debounceMs={FAST_DEBOUNCE_MS} />);
    fireEvent.change(screen.getByTestId('data-table-search'), { target: { value: 'p' } });
    await new Promise((r) => setTimeout(r, WAIT_BUFFER_MS));
    expect(onQChange).not.toHaveBeenCalled();
  });

  it('calls onQChange(value) when input reaches 2+ chars after debounce', async () => {
    const onQChange = vi.fn();
    render(<DataTableSearch value={null} onQChange={onQChange} debounceMs={FAST_DEBOUNCE_MS} />);
    fireEvent.change(screen.getByTestId('data-table-search'), { target: { value: 'pr' } });
    await waitFor(() => expect(onQChange).toHaveBeenCalledWith('pr'));
  });

  it('clears q to null when input drops below 2 chars from an active q', async () => {
    const onQChange = vi.fn();
    render(<DataTableSearch value="product" onQChange={onQChange} debounceMs={FAST_DEBOUNCE_MS} />);
    fireEvent.change(screen.getByTestId('data-table-search'), { target: { value: 'p' } });
    await waitFor(() => expect(onQChange).toHaveBeenCalledWith(null));
  });

  it('calls onQChange(null) when input is fully cleared from an active q', async () => {
    const onQChange = vi.fn();
    render(<DataTableSearch value="product" onQChange={onQChange} debounceMs={FAST_DEBOUNCE_MS} />);
    fireEvent.change(screen.getByTestId('data-table-search'), { target: { value: '' } });
    await waitFor(() => expect(onQChange).toHaveBeenCalledWith(null));
  });

  it('renders the "(N results)" indicator when q is active and totalCount is supplied', () => {
    render(<DataTableSearch value="prod" onQChange={vi.fn()} totalCount={312} />);
    expect(screen.getByTestId('data-table-search-result-count')).toHaveTextContent('(312 results)');
  });

  it('does not render the result count when q is null', () => {
    render(<DataTableSearch value={null} onQChange={vi.fn()} totalCount={100} />);
    expect(screen.queryByTestId('data-table-search-result-count')).not.toBeInTheDocument();
  });
});
