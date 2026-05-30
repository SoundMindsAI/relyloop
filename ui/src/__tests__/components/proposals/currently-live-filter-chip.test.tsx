// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { CurrentlyLiveFilterChip } from '@/components/proposals/currently-live-filter-chip';
import { TooltipProvider } from '@/components/ui/tooltip';

const TOOLTIP_TEXT = 'Show only proposals tracked as the live config in their repo.';

function renderChip(isActive: boolean) {
  const onToggle = vi.fn();
  render(
    <TooltipProvider>
      <CurrentlyLiveFilterChip isActive={isActive} onToggle={onToggle} />
    </TooltipProvider>,
  );
  return { onToggle };
}

describe('<CurrentlyLiveFilterChip />', () => {
  it('renders with the stable testid + label', () => {
    renderChip(false);
    const chip = screen.getByTestId('proposals-currently-live-filter-chip');
    expect(chip).toBeInTheDocument();
    expect(chip).toHaveTextContent('Currently live only');
  });

  it('reflects state via aria-pressed when active', () => {
    renderChip(true);
    const chip = screen.getByTestId('proposals-currently-live-filter-chip');
    expect(chip).toHaveAttribute('aria-pressed', 'true');
  });

  it('reflects state via aria-pressed when inactive', () => {
    renderChip(false);
    const chip = screen.getByTestId('proposals-currently-live-filter-chip');
    expect(chip).toHaveAttribute('aria-pressed', 'false');
  });

  it('fires onToggle on click', async () => {
    const user = userEvent.setup();
    const { onToggle } = renderChip(false);
    const chip = screen.getByTestId('proposals-currently-live-filter-chip');
    await user.click(chip);
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it('fires onToggle on keyboard Enter', async () => {
    const user = userEvent.setup();
    const { onToggle } = renderChip(false);
    const chip = screen.getByTestId('proposals-currently-live-filter-chip');
    chip.focus();
    expect(chip).toHaveFocus();
    await user.keyboard('{Enter}');
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it('renders the InfoTooltip with the correct glossary key (text appears on hover)', async () => {
    const user = userEvent.setup();
    renderChip(false);
    // The InfoTooltip standalone-mode renders a button with this testid.
    const trigger = screen.getByTestId('tooltip-trigger-proposal.currently_live_filter');
    await user.hover(trigger);
    const tooltipContent = await screen.findAllByText(TOOLTIP_TEXT);
    expect(tooltipContent.length).toBeGreaterThan(0);
  });

  it('chip and InfoTooltip are siblings (no nested buttons)', () => {
    renderChip(false);
    const chip = screen.getByTestId('proposals-currently-live-filter-chip');
    // Walk up to the parent wrapper; the InfoTooltip should be a sibling, not
    // a descendant. (Nested buttons would be both invalid HTML and break
    // keyboard semantics — see cycle-2 review F-c2-2.)
    const wrapper = chip.parentElement;
    expect(wrapper).not.toBeNull();
    // The chip itself should contain no nested <button> children.
    expect(chip.querySelector('button')).toBeNull();
  });
});
