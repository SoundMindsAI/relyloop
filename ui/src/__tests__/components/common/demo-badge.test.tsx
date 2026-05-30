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

  it('is keyboard-reachable from a sibling focusable AND exposes the tooltip text on focus', async () => {
    const user = userEvent.setup();
    // Render a sibling button BEFORE the badge so a single user.tab()
    // advances focus from the button onto the badge — this proves the
    // badge participates in normal keyboard tab order, not just manual
    // imperative focus().
    render(
      <TooltipProvider>
        <button type="button" data-testid="sibling-before">
          before
        </button>
        <DemoBadge />
      </TooltipProvider>,
    );

    // Focus the sibling button first.
    screen.getByTestId('sibling-before').focus();
    expect(screen.getByTestId('sibling-before')).toHaveFocus();

    // One Tab should land on the badge (which has tabIndex={0}).
    await user.tab();
    const badge = screen.getByTestId('demo-badge');
    expect(badge).toHaveFocus();

    // Radix opens tooltips on focus; the portal-rendered content must
    // contain the FR-5 tooltip text.
    const tooltipContent = await screen.findAllByText(TOOLTIP_TEXT);
    expect(tooltipContent.length).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// Story 3.2 / FR-7 — synthetic-ubi variant
// ---------------------------------------------------------------------------

const SYNTHETIC_UBI_TOOLTIP =
  'This UBI data was fabricated by the demo reseed to demonstrate the UBI path; it is not real user behavior.';

function renderSyntheticUbiBadge() {
  return render(
    <TooltipProvider>
      <DemoBadge variant="synthetic-ubi" />
    </TooltipProvider>,
  );
}

describe('<DemoBadge variant="synthetic-ubi" />', () => {
  it('renders the "Synthetic demo data" text with its own testid', () => {
    renderSyntheticUbiBadge();
    const badge = screen.getByTestId('demo-badge-synthetic-ubi');
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent('Synthetic demo data');
  });

  it('exposes aria-label="Synthetic demo data" and is keyboard-focusable', () => {
    renderSyntheticUbiBadge();
    const badge = screen.getByTestId('demo-badge-synthetic-ubi');
    expect(badge).toHaveAttribute('role', 'img');
    expect(badge).toHaveAttribute('aria-label', 'Synthetic demo data');
    expect(badge).toHaveAttribute('tabindex', '0');
  });

  it('reveals the FR-7 tooltip text on keyboard focus (not hover-only)', async () => {
    const user = userEvent.setup();
    render(
      <TooltipProvider>
        <button type="button" data-testid="sibling-before">
          before
        </button>
        <DemoBadge variant="synthetic-ubi" />
      </TooltipProvider>,
    );

    screen.getByTestId('sibling-before').focus();
    await user.tab();
    expect(screen.getByTestId('demo-badge-synthetic-ubi')).toHaveFocus();

    const tooltipContent = await screen.findAllByText(SYNTHETIC_UBI_TOOLTIP);
    expect(tooltipContent.length).toBeGreaterThan(0);
  });
});
