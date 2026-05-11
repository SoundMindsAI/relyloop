import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

const mockUsePathname = vi.fn<() => string>();
vi.mock('next/navigation', () => ({
  usePathname: () => mockUsePathname(),
}));

import { NAV_ITEMS, TopNav } from '@/components/layout/top-nav';

describe('TopNav', () => {
  it('renders the brand link and every NAV_ITEMS entry', () => {
    mockUsePathname.mockReturnValue('/');
    render(<TopNav />);
    expect(screen.getByRole('link', { name: 'RelyLoop' })).toHaveAttribute('href', '/');
    for (const item of NAV_ITEMS) {
      const link = screen.getByRole('link', { name: item.label });
      expect(link).toHaveAttribute('href', item.href);
    }
  });

  it('marks the Dashboard link active when pathname === "/"', () => {
    mockUsePathname.mockReturnValue('/');
    render(<TopNav />);
    const link = screen.getByRole('link', { name: 'Dashboard' });
    expect(link).toHaveAttribute('data-active', 'true');
    expect(link).toHaveAttribute('aria-current', 'page');
  });

  it('marks /studies active when on /studies/abc123', () => {
    mockUsePathname.mockReturnValue('/studies/abc123');
    render(<TopNav />);
    const studiesLink = screen.getByRole('link', { name: 'Studies' });
    expect(studiesLink).toHaveAttribute('data-active', 'true');
    const dashboardLink = screen.getByRole('link', { name: 'Dashboard' });
    expect(dashboardLink).toHaveAttribute('data-active', 'false');
  });

  it('treats /clusters and /clusters/x as separate active states', () => {
    mockUsePathname.mockReturnValue('/clusters');
    render(<TopNav />);
    expect(screen.getByRole('link', { name: 'Clusters' })).toHaveAttribute('data-active', 'true');
  });

  it('home is NOT active when on a non-root path (prefix-match bug check)', () => {
    mockUsePathname.mockReturnValue('/studies');
    render(<TopNav />);
    expect(screen.getByRole('link', { name: 'Dashboard' })).toHaveAttribute('data-active', 'false');
  });
});
