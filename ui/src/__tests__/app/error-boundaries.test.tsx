// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import RouteError from '@/app/error';
import NotFound from '@/app/not-found';
import { Skeleton } from '@/components/ui/skeleton';

vi.mock('next/link', () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

describe('not-found boundary', () => {
  it('renders recovery copy and a link back to the dashboard', () => {
    render(<NotFound />);
    expect(screen.getByText('Page not found')).toBeInTheDocument();
    const link = screen.getByRole('link', { name: /back to dashboard/i });
    expect(link).toHaveAttribute('href', '/');
  });
});

describe('route error boundary', () => {
  it('renders a recoverable error and calls reset() on "Try again"', () => {
    const reset = vi.fn();
    // Suppress the intentional console.error the boundary logs.
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(<RouteError error={new Error('boom')} reset={reset} />);
    expect(screen.getByText('Something went wrong')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /try again/i }));
    expect(reset).toHaveBeenCalledTimes(1);
    spy.mockRestore();
  });
});

describe('Skeleton', () => {
  it('renders an aria-hidden pulse placeholder that respects reduced motion', () => {
    const { container } = render(<Skeleton className="h-4 w-1/2" />);
    const el = container.firstElementChild as HTMLElement;
    expect(el).toHaveAttribute('aria-hidden', 'true');
    expect(el.className).toContain('animate-pulse');
    expect(el.className).toContain('motion-reduce:animate-none');
  });
});
