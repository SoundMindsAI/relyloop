import '@testing-library/jest-dom/vitest';
import { render, screen } from '@testing-library/react';
import { userEvent } from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { InfoTooltip } from '@/components/common/info-tooltip';
import { TooltipProvider } from '@/components/ui/tooltip';

/**
 * Component tests for InfoTooltip wrapper (Story 1.2 / FR-2).
 *
 * The TooltipProvider delay is set to 0 in test wrappers so hover/focus
 * reveals are deterministic. The real app uses delayDuration={700} per
 * Story 1.1 — the test override does not change production behavior.
 */
function renderWithProvider(node: React.ReactNode): ReturnType<typeof render> {
  return render(<TooltipProvider delayDuration={0}>{node}</TooltipProvider>);
}

describe('InfoTooltip standalone mode', () => {
  it('renders a <button> trigger with aria-label and data-testid', () => {
    renderWithProvider(<InfoTooltip glossaryKey="study.target" />);
    const trigger = screen.getByTestId('tooltip-trigger-study.target');
    expect(trigger.tagName).toBe('BUTTON');
    expect(trigger).toHaveAttribute('type', 'button');
    expect(trigger.getAttribute('aria-label')).toBeTruthy();
    expect(trigger.getAttribute('aria-label')?.length).toBeGreaterThan(0);
  });

  it('contains the lucide Info icon inside the button', () => {
    renderWithProvider(<InfoTooltip glossaryKey="study.k" />);
    const trigger = screen.getByTestId('tooltip-trigger-study.k');
    const svg = trigger.querySelector('svg');
    expect(svg).not.toBeNull();
    expect(svg).toHaveAttribute('aria-hidden', 'true');
  });

  it('reveals tooltip body on hover (AC-2)', async () => {
    const user = userEvent.setup();
    renderWithProvider(<InfoTooltip glossaryKey="study.k" />);
    const trigger = screen.getByTestId('tooltip-trigger-study.k');
    await user.hover(trigger);
    expect(await screen.findByTestId('tooltip-body-study.k')).toBeInTheDocument();
  });

  it('reveals tooltip body on keyboard focus (AC-3)', async () => {
    const user = userEvent.setup();
    renderWithProvider(<InfoTooltip glossaryKey="study.k" />);
    await user.tab();
    const trigger = screen.getByTestId('tooltip-trigger-study.k');
    expect(trigger).toHaveFocus();
    expect(await screen.findByTestId('tooltip-body-study.k')).toBeInTheDocument();
  });

  it('dismisses tooltip body on Escape (AC-3)', async () => {
    const user = userEvent.setup();
    renderWithProvider(<InfoTooltip glossaryKey="study.k" />);
    await user.tab();
    expect(await screen.findByTestId('tooltip-body-study.k')).toBeInTheDocument();
    await user.keyboard('{Escape}');
    // Radix unmounts the tooltip body on close
    expect(screen.queryByTestId('tooltip-body-study.k')).not.toBeInTheDocument();
  });
});

describe('InfoTooltip asChild mode', () => {
  it('uses the child as the trigger and does NOT add its own data-testid', async () => {
    const user = userEvent.setup();
    renderWithProvider(
      <InfoTooltip asChild glossaryKey="digest.open_pr_button">
        <button type="button" data-testid="caller-button">
          Open PR…
        </button>
      </InfoTooltip>,
    );
    // The caller's existing testid is preserved (no collision)
    const button = screen.getByTestId('caller-button');
    expect(button.tagName).toBe('BUTTON');
    // The wrapper does NOT inject its own tooltip-trigger-* testid in asChild mode
    expect(screen.queryByTestId('tooltip-trigger-digest.open_pr_button')).not.toBeInTheDocument();
    // But the body testid IS present once revealed
    await user.hover(button);
    expect(await screen.findByTestId('tooltip-body-digest.open_pr_button')).toBeInTheDocument();
  });

  it('focuses the asChild child via Tab and reveals tooltip', async () => {
    const user = userEvent.setup();
    renderWithProvider(
      <InfoTooltip asChild glossaryKey="digest.open_pr_disabled">
        <button type="button" aria-disabled="true" data-testid="caller-disabled-button">
          Open PR (no pending proposal)
        </button>
      </InfoTooltip>,
    );
    await user.tab();
    const button = screen.getByTestId('caller-disabled-button');
    expect(button).toHaveFocus();
    expect(await screen.findByTestId('tooltip-body-digest.open_pr_disabled')).toBeInTheDocument();
  });
});

describe('InfoTooltip motion-reduce (AC-8)', () => {
  it('renders TooltipContent with motion-reduce:animate-none class', async () => {
    const user = userEvent.setup();
    renderWithProvider(<InfoTooltip glossaryKey="study.k" />);
    await user.hover(screen.getByTestId('tooltip-trigger-study.k'));
    const body = await screen.findByTestId('tooltip-body-study.k');
    expect(body.className).toContain('motion-reduce:animate-none');
  });
});
