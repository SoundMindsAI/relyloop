// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { CurrentlyLiveBadge } from '@/components/proposals/currently-live-badge';
import { TooltipProvider } from '@/components/ui/tooltip';

const SHORT_TEXT =
  'This proposal is the most recently merged PR for its config repo — assumed live in production.';

function renderBadge(isCurrentlyLive: boolean | null | undefined) {
  return render(
    <TooltipProvider>
      <CurrentlyLiveBadge isCurrentlyLive={isCurrentlyLive} />
    </TooltipProvider>,
  );
}

describe('<CurrentlyLiveBadge />', () => {
  it('renders the pill with text "Currently live" + stable testid when isCurrentlyLive=true', () => {
    renderBadge(true);
    const badge = screen.getByTestId('currently-live-badge');
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent('Currently live');
  });

  it('exposes an aria-label that mentions the meaning for screen readers', () => {
    renderBadge(true);
    const badge = screen.getByTestId('currently-live-badge');
    expect(badge).toHaveAttribute(
      'aria-label',
      'Currently live — this proposal is the most recently merged for its config repo',
    );
  });

  it('renders nothing when isCurrentlyLive=false', () => {
    renderBadge(false);
    expect(screen.queryByTestId('currently-live-badge')).toBeNull();
  });

  it('renders nothing when isCurrentlyLive=undefined (defensive on optional prop)', () => {
    renderBadge(undefined);
    expect(screen.queryByTestId('currently-live-badge')).toBeNull();
  });

  it('renders nothing when isCurrentlyLive=null', () => {
    renderBadge(null);
    expect(screen.queryByTestId('currently-live-badge')).toBeNull();
  });

  it('is keyboard-focusable and surfaces the glossary tooltip text on focus', async () => {
    const user = userEvent.setup();
    render(
      <TooltipProvider>
        <button type="button" data-testid="sibling-before">
          before
        </button>
        <CurrentlyLiveBadge isCurrentlyLive={true} />
      </TooltipProvider>,
    );
    screen.getByTestId('sibling-before').focus();
    await user.tab();
    const badge = screen.getByTestId('currently-live-badge');
    expect(badge).toHaveFocus();
    const tooltipContent = await screen.findAllByText(SHORT_TEXT);
    expect(tooltipContent.length).toBeGreaterThan(0);
  });
});
