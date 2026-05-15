import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render as rtlRender, screen } from '@testing-library/react';

import { TooltipProvider } from '@/components/ui/tooltip';
import { ProposalSourceFilterChips } from '@/components/proposals/proposal-source-filter-chips';
import { ProposalStatusFilterChips } from '@/components/proposals/proposal-status-filter-chips';

// The filter chips now embed an InfoTooltip — every test render needs a
// TooltipProvider in scope. delayDuration={0} so hover/focus reveals are
// deterministic in tests.
function render(node: React.ReactElement): ReturnType<typeof rtlRender> {
  return rtlRender(<TooltipProvider delayDuration={0}>{node}</TooltipProvider>);
}

describe('ProposalStatusFilterChips', () => {
  it('renders 5 chips (all + 4 wire values) and marks the active one', () => {
    const onChange = vi.fn();
    render(<ProposalStatusFilterChips value="pr_opened" onChange={onChange} />);
    expect(screen.getByTestId('proposal-status-chip-all')).toHaveAttribute('data-active', 'false');
    expect(screen.getByTestId('proposal-status-chip-pending')).toHaveAttribute(
      'data-active',
      'false',
    );
    expect(screen.getByTestId('proposal-status-chip-pr_opened')).toHaveAttribute(
      'data-active',
      'true',
    );
    expect(screen.getByTestId('proposal-status-chip-pr_merged')).toBeInTheDocument();
    expect(screen.getByTestId('proposal-status-chip-rejected')).toBeInTheDocument();
  });

  it('clicking a wire-value chip invokes onChange with the wire value', () => {
    const onChange = vi.fn();
    render(<ProposalStatusFilterChips value={null} onChange={onChange} />);
    fireEvent.click(screen.getByTestId('proposal-status-chip-pr_merged'));
    expect(onChange).toHaveBeenCalledWith('pr_merged');
  });

  it('clicking the "all" chip invokes onChange with null', () => {
    const onChange = vi.fn();
    render(<ProposalStatusFilterChips value="pending" onChange={onChange} />);
    fireEvent.click(screen.getByTestId('proposal-status-chip-all'));
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it('an unknown URL value (e.g. "invented") falls back to "all" as active', () => {
    const onChange = vi.fn();
    render(<ProposalStatusFilterChips value="invented" onChange={onChange} />);
    expect(screen.getByTestId('proposal-status-chip-all')).toHaveAttribute('data-active', 'true');
  });
});

describe('ProposalSourceFilterChips', () => {
  it('renders 3 chips and marks the active one', () => {
    const onChange = vi.fn();
    render(<ProposalSourceFilterChips value="manual" onChange={onChange} />);
    expect(screen.getByTestId('proposal-source-chip-all')).toHaveAttribute('data-active', 'false');
    expect(screen.getByTestId('proposal-source-chip-study')).toHaveAttribute(
      'data-active',
      'false',
    );
    expect(screen.getByTestId('proposal-source-chip-manual')).toHaveAttribute(
      'data-active',
      'true',
    );
  });

  it('clicking a chip invokes onChange with the value', () => {
    const onChange = vi.fn();
    render(<ProposalSourceFilterChips value="all" onChange={onChange} />);
    fireEvent.click(screen.getByTestId('proposal-source-chip-study'));
    expect(onChange).toHaveBeenCalledWith('study');
  });
});
