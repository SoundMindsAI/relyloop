// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render as rtlRender, screen } from '@testing-library/react';
import { type ReactNode } from 'react';

import { TooltipProvider } from '@/components/ui/tooltip';
import { PrPanel } from '@/components/proposals/pr-panel';
import type { ProposalDetail } from '@/lib/api/proposals';

// PrPanel now wraps its Open PR button in an InfoTooltip (asChild) — every
// render() call must include a TooltipProvider in scope. delayDuration={0}
// so any hover/focus reveals are deterministic in tests.
function render(node: React.ReactElement): ReturnType<typeof rtlRender> {
  return rtlRender(<TooltipProvider delayDuration={0}>{node}</TooltipProvider>);
}

vi.mock('next/link', () => ({
  default: ({ children, href, ...rest }: { children: ReactNode; href: string }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

function proposal(overrides: Partial<ProposalDetail> = {}): ProposalDetail {
  return {
    id: 'p1',
    study_id: null,
    study_summary: null,
    study_trial_id: null,
    cluster: { id: 'c1', name: 'prod', engine_type: 'elasticsearch', environment: 'prod' },
    template: { id: 't1', name: 'tmpl', version: 1, engine_type: 'elasticsearch' },
    config_diff: {},
    metric_delta: null,
    status: 'pending',
    pr_url: null,
    pr_state: null,
    pr_merged_at: null,
    pr_open_error: null,
    rejected_reason: null,
    digest: null,
    created_at: '2026-05-12T00:00:00Z',
    ...overrides,
  } as ProposalDetail;
}

describe('PrPanel', () => {
  it('AC-1: renders Open PR button when status=pending and !openPrIsPending', () => {
    const onOpenPR = vi.fn();
    render(<PrPanel proposal={proposal()} onOpenPR={onOpenPR} openPrIsPending={false} />);
    const btn = screen.getByTestId('open-pr-button');
    expect(btn).toBeInTheDocument();
    expect(btn).toHaveTextContent('Open PR');
    expect(btn).not.toBeDisabled();
    fireEvent.click(btn);
    expect(onOpenPR).toHaveBeenCalledTimes(1);
  });

  it('AC-1: button stays visible, disabled, and shows "Opening PR…" while openPrIsPending=true', () => {
    render(<PrPanel proposal={proposal()} onOpenPR={() => {}} openPrIsPending={true} />);
    const btn = screen.getByTestId('open-pr-button');
    expect(btn).toBeInTheDocument();
    expect(btn).toBeDisabled();
    expect(btn).toHaveTextContent('Opening PR…');
    expect(screen.getByTestId('open-pr-spinner-row')).toBeInTheDocument();
  });

  it('AC-4: renders the inline pr_open_error Alert next to the Open PR button when status=pending', () => {
    render(
      <PrPanel
        proposal={proposal({ pr_open_error: 'Branch already exists' })}
        onOpenPR={() => {}}
        openPrIsPending={false}
      />,
    );
    expect(screen.getByTestId('proposal-error-alert')).toBeInTheDocument();
    expect(screen.getByText('Branch already exists')).toBeInTheDocument();
    // Button still visible for retry per FR-3 + AC-4.
    expect(screen.getByTestId('open-pr-button')).not.toBeDisabled();
  });

  it('FR-3: button is HIDDEN (not just disabled) when status=pr_opened', () => {
    render(
      <PrPanel
        proposal={proposal({
          status: 'pr_opened',
          pr_state: 'open',
          pr_url: 'https://github.com/foo/bar/pull/1',
        })}
        onOpenPR={() => {}}
        openPrIsPending={false}
      />,
    );
    expect(screen.queryByTestId('open-pr-button')).not.toBeInTheDocument();
    expect(screen.getByTestId('pr-link')).toHaveAttribute(
      'href',
      'https://github.com/foo/bar/pull/1',
    );
    expect(screen.getByTestId('pr-link')).toHaveAttribute('target', '_blank');
  });

  it('FR-3: button is HIDDEN when status=pr_merged; renders merged-at timestamp', () => {
    render(
      <PrPanel
        proposal={proposal({
          status: 'pr_merged',
          pr_state: 'merged',
          pr_url: 'https://github.com/foo/bar/pull/1',
          pr_merged_at: '2026-05-12T12:34:56Z',
        })}
        onOpenPR={() => {}}
        openPrIsPending={false}
      />,
    );
    expect(screen.queryByTestId('open-pr-button')).not.toBeInTheDocument();
    expect(screen.getByText(/Merged on/)).toBeInTheDocument();
  });

  it('security: a non-https pr_url is not rendered as a live link (status=pr_opened)', () => {
    render(
      <PrPanel
        proposal={proposal({
          status: 'pr_opened',
          pr_state: 'open',
          pr_url: 'javascript:alert(document.domain)' as unknown as string,
        })}
        onOpenPR={() => {}}
        openPrIsPending={false}
      />,
    );
    expect(screen.queryByTestId('pr-link')).not.toBeInTheDocument();
  });

  it('security: a non-https pr_url is not rendered as a live link (status=pr_merged)', () => {
    render(
      <PrPanel
        proposal={proposal({
          status: 'pr_merged',
          pr_state: 'merged',
          pr_url: 'http://insecure.example/pull/1',
          pr_merged_at: '2026-05-12T12:34:56Z',
        })}
        onOpenPR={() => {}}
        openPrIsPending={false}
      />,
    );
    // Non-https → link suppressed, but the merged-at line still renders.
    expect(screen.queryByTestId('pr-link')).not.toBeInTheDocument();
    expect(screen.getByText(/Merged on/)).toBeInTheDocument();
  });

  it('FR-3: button is HIDDEN when status=rejected; renders rejected_reason', () => {
    render(
      <PrPanel
        proposal={proposal({
          status: 'rejected',
          rejected_reason: 'metric delta too small',
        })}
        onOpenPR={() => {}}
        openPrIsPending={false}
      />,
    );
    expect(screen.queryByTestId('open-pr-button')).not.toBeInTheDocument();
    expect(screen.getByTestId('rejected-reason')).toHaveTextContent('metric delta too small');
  });
});
