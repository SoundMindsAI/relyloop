/**
 * Tests for `<AmbiguousSkipRecoveryCard>` (feat_ubi_judgments Story 4.3 /
 * FR-8 Capability D).
 */
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import { AmbiguousSkipRecoveryCard } from '@/components/judgments/ambiguous-skip-recovery-card';

describe('<AmbiguousSkipRecoveryCard>', () => {
  it('renders the skip count + the recovery button', () => {
    const onRerun = vi.fn();
    render(<AmbiguousSkipRecoveryCard skipCount={5} onRerunWithMostRecent={onRerun} />);
    expect(screen.getByText('Skipped 5 queries')).toBeInTheDocument();
    expect(screen.getByTestId('ambiguous-skip-rerun-most-recent')).toBeInTheDocument();
  });

  it('uses singular phrasing for skipCount=1', () => {
    render(<AmbiguousSkipRecoveryCard skipCount={1} onRerunWithMostRecent={vi.fn()} />);
    expect(screen.getByText(/1 query was skipped/i)).toBeInTheDocument();
  });

  it('calls onRerunWithMostRecent when the button is clicked', () => {
    const onRerun = vi.fn();
    render(<AmbiguousSkipRecoveryCard skipCount={3} onRerunWithMostRecent={onRerun} />);
    fireEvent.click(screen.getByTestId('ambiguous-skip-rerun-most-recent'));
    expect(onRerun).toHaveBeenCalledTimes(1);
  });

  it('disables the button when pending=true', () => {
    render(<AmbiguousSkipRecoveryCard skipCount={3} onRerunWithMostRecent={vi.fn()} pending />);
    const button = screen.getByTestId('ambiguous-skip-rerun-most-recent');
    expect(button).toBeDisabled();
    expect(button).toHaveTextContent('Starting…');
  });
});
