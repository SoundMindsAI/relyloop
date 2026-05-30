// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type ReactNode } from 'react';

import { GuideTrigger } from '@/components/guides/guide-trigger';

let mockPathname = '/clusters';
vi.mock('next/navigation', () => ({
  usePathname: () => mockPathname,
}));

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

describe('<GuideTrigger>', () => {
  it('renders the button when current path has a matching guide', () => {
    mockPathname = '/clusters';
    wrap(<GuideTrigger />);
    expect(screen.getByTestId('guide-trigger')).toBeVisible();
  });

  it('does not render when current path has no matching guide', () => {
    mockPathname = '/some-unmapped-route';
    wrap(<GuideTrigger />);
    expect(screen.queryByTestId('guide-trigger')).toBeNull();
  });

  it('does not render on /guide catalog page', () => {
    mockPathname = '/guide';
    wrap(<GuideTrigger />);
    expect(screen.queryByTestId('guide-trigger')).toBeNull();
  });

  it('uses single-guide direct-open mode when only one guide matches', () => {
    // /clusters has exactly one registered guide (01_register_first_cluster).
    mockPathname = '/clusters';
    wrap(<GuideTrigger />);
    const btn = screen.getByTestId('guide-trigger');
    expect(btn).toHaveAttribute('aria-label', expect.stringContaining('Register a cluster'));
  });

  it('uses picker mode when multiple guides match the route', () => {
    // /proposals has both 02_review_a_proposal and 07_browse_proposals.
    mockPathname = '/proposals';
    wrap(<GuideTrigger />);
    const btn = screen.getByTestId('guide-trigger');
    expect(btn).toHaveAttribute('aria-label', 'Open guide picker');
  });
});
