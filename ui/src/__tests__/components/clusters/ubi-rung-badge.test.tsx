/**
 * Unit tests for `<UbiRungBadge>` (feat_ubi_judgments Story 4.1 / FR-8).
 */
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import { UbiRungBadge } from '@/components/clusters/ubi-rung-badge';

describe('UbiRungBadge', () => {
  it('renders the rung_0 label', () => {
    render(<UbiRungBadge rung="rung_0" />);
    expect(screen.getByText('UBI not enabled')).toBeInTheDocument();
  });

  it('renders the rung_1 label', () => {
    render(<UbiRungBadge rung="rung_1" />);
    expect(screen.getByText('UBI sparse')).toBeInTheDocument();
  });

  it('renders the rung_2 label', () => {
    render(<UbiRungBadge rung="rung_2" />);
    expect(screen.getByText('UBI dense head')).toBeInTheDocument();
  });

  it('renders the rung_3 label', () => {
    render(<UbiRungBadge rung="rung_3" />);
    expect(screen.getByText('UBI full coverage')).toBeInTheDocument();
  });

  it('carries the data-rung attribute for E2E targeting', () => {
    render(<UbiRungBadge rung="rung_2" />);
    const el = screen.getByTestId('ubi-rung-badge');
    expect(el).toHaveAttribute('data-rung', 'rung_2');
  });

  it('renders the cluster.ubi_readiness HelpPopover trigger', () => {
    render(<UbiRungBadge rung="rung_2" />);
    // The HelpPopover trigger carries data-testid="popover-trigger-cluster.ubi_readiness".
    expect(screen.getByTestId('popover-trigger-cluster.ubi_readiness')).toBeInTheDocument();
  });
});
