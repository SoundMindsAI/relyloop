import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { DemoBadge } from '@/components/common/demo-badge';
import { TooltipProvider } from '@/components/ui/tooltip';

const TOOLTIP_TEXT =
  "Pre-loaded by 'make up' or 'make seed-demo'. Has realistic queries + judgments + a winning study. Safe to delete with 'make seed-demo FORCE=1' to start over.";

function renderBadge() {
  return render(
    <TooltipProvider>
      <DemoBadge />
    </TooltipProvider>,
  );
}

describe('<DemoBadge />', () => {
  it('renders with text "Demo" and the stable testid', () => {
    renderBadge();
    const badge = screen.getByTestId('demo-badge');
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent('Demo');
  });

  it('has accessibility attributes for screen readers + keyboard users', () => {
    renderBadge();
    const badge = screen.getByTestId('demo-badge');
    expect(badge).toHaveAttribute('role', 'img');
    expect(badge).toHaveAttribute('aria-label', 'Demo cluster');
    expect(badge).toHaveAttribute('tabindex', '0');
  });

  it('exposes the tooltip text on focus', async () => {
    const user = userEvent.setup();
    renderBadge();
    const badge = screen.getByTestId('demo-badge');
    // Tab into the badge to open the tooltip via keyboard.
    badge.focus();
    expect(badge).toHaveFocus();
    // Radix opens tooltips on focus; wait for the portal to render content.
    await user.tab(); // shift focus; some Radix versions need the focus event to settle
    badge.focus();
    // The tooltip text MUST be reachable in the DOM after focus. Use
    // findAllByText to allow Radix's portal rendering pattern.
    const tooltipContent = await screen.findAllByText(TOOLTIP_TEXT);
    expect(tooltipContent.length).toBeGreaterThan(0);
  });
});
