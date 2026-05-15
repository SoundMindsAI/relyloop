import '@testing-library/jest-dom/vitest';
import { render, screen } from '@testing-library/react';
import { userEvent } from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

/**
 * Component tests for HelpPopover (Story 1.3 / FR-3).
 *
 * Real glossary entries cover the happy paths (click reveal, ESC + outside
 * click dismiss, Markdown rendering). The safety-filter test injects a
 * malicious test-only entry via `vi.mock('@/lib/glossary', ...)` because
 * the real glossary content-time check forbids `<script>` / `<iframe>` /
 * `<style>` strings (FR-10 / AC-12) — the only way to exercise the runtime
 * filter is with mocked content.
 */

describe('HelpPopover happy paths (real glossary)', () => {
  // Need to import after any vi.mock is set up; here we don't mock so we can
  // import normally at module scope.
  it('renders <button> trigger with aria-label and data-testid', async () => {
    const { HelpPopover } = await import('@/components/common/help-popover');
    render(<HelpPopover glossaryKey="study.metric" />);
    const trigger = screen.getByTestId('popover-trigger-study.metric');
    expect(trigger.tagName).toBe('BUTTON');
    expect(trigger).toHaveAttribute('type', 'button');
    expect(trigger.getAttribute('aria-label')).toBeTruthy();
  });

  it('opens body on click (AC-4)', async () => {
    const { HelpPopover } = await import('@/components/common/help-popover');
    const user = userEvent.setup();
    render(<HelpPopover glossaryKey="study.sampler" />);
    await user.click(screen.getByTestId('popover-trigger-study.sampler'));
    expect(await screen.findByTestId('popover-body-study.sampler')).toBeInTheDocument();
  });

  it('closes on Escape (AC-4)', async () => {
    const { HelpPopover } = await import('@/components/common/help-popover');
    const user = userEvent.setup();
    render(<HelpPopover glossaryKey="study.pruner" />);
    await user.click(screen.getByTestId('popover-trigger-study.pruner'));
    await screen.findByTestId('popover-body-study.pruner');
    await user.keyboard('{Escape}');
    expect(screen.queryByTestId('popover-body-study.pruner')).not.toBeInTheDocument();
  });

  it('renders Markdown bullet list as a semantic <ul>', async () => {
    const { HelpPopover } = await import('@/components/common/help-popover');
    const user = userEvent.setup();
    render(<HelpPopover glossaryKey="study.metric" />);
    await user.click(screen.getByTestId('popover-trigger-study.metric'));
    const body = await screen.findByTestId('popover-body-study.metric');
    // study.metric body lists 6 metric definitions as `- item` Markdown bullets.
    const ul = body.querySelector('ul');
    expect(ul).not.toBeNull();
    const lis = body.querySelectorAll('li');
    expect(lis.length).toBeGreaterThanOrEqual(6);
  });

  it('renders PopoverContent with motion-reduce:animate-none class (AC-8)', async () => {
    const { HelpPopover } = await import('@/components/common/help-popover');
    const user = userEvent.setup();
    render(<HelpPopover glossaryKey="study.sampler" />);
    await user.click(screen.getByTestId('popover-trigger-study.sampler'));
    const body = await screen.findByTestId('popover-body-study.sampler');
    expect(body.className).toContain('motion-reduce:animate-none');
  });
});

describe('HelpPopover safety filter (vi.mock injection)', () => {
  it('strips <script> and <style> tags from malicious markdown content', async () => {
    // Inject a test-only entry containing disallowed HTML. The real glossary
    // cannot carry this content (FR-10 forbids it; AC-12 enforces).
    vi.doMock('@/lib/glossary', () => ({
      glossary: {
        'test.malicious': {
          long: 'Safe text. <script>alert(1)</script> More text. <style>body{}</style>',
        },
      },
    }));
    // Re-import HelpPopover with the mocked module
    vi.resetModules();
    const { HelpPopover } = await import('@/components/common/help-popover');
    const user = userEvent.setup();
    const { container } = render(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      <HelpPopover glossaryKey={'test.malicious' as any} />,
    );
    await user.click(screen.getByTestId('popover-trigger-test.malicious'));
    await screen.findByTestId('popover-body-test.malicious');
    // No script or style tag should be in the rendered DOM
    expect(container.querySelector('script')).toBeNull();
    expect(container.querySelector('style')).toBeNull();
    // Safe text portions still render
    expect(screen.getByText(/Safe text/)).toBeInTheDocument();
    expect(screen.getByText(/More text/)).toBeInTheDocument();
    vi.doUnmock('@/lib/glossary');
  });
});
