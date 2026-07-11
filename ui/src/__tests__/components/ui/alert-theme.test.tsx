// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { Alert } from '@/components/ui/alert';

const setTheme = vi.fn();
let mockTheme = 'light';
vi.mock('next-themes', () => ({
  useTheme: () => ({ theme: mockTheme, setTheme }),
}));

describe('Alert primitive', () => {
  it('renders role=alert and dark-safe variant classes', () => {
    render(
      <Alert variant="destructive" data-testid="a">
        boom
      </Alert>,
    );
    const el = screen.getByTestId('a');
    expect(el).toHaveAttribute('role', 'alert');
    // Keeps the light family AND a dark: pair (dark-safe).
    expect(el.className).toContain('bg-red-50');
    expect(el.className).toContain('dark:bg-red-950');
  });

  it('defaults to the info variant', () => {
    render(<Alert data-testid="b">note</Alert>);
    expect(screen.getByTestId('b').className).toContain('bg-blue-50');
  });
});

describe('ThemeToggle', () => {
  it('cycles light → dark on click', async () => {
    mockTheme = 'light';
    const { ThemeToggle } = await import('@/components/layout/theme-toggle');
    render(<ThemeToggle />);
    fireEvent.click(screen.getByTestId('theme-toggle'));
    expect(setTheme).toHaveBeenCalledWith('dark');
  });
});
