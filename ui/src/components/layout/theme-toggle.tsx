// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

import { Monitor, Moon, Sun } from 'lucide-react';
import { useTheme } from 'next-themes';
import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';

/**
 * Light / dark / system theme cycler for the nav. next-themes is already wired
 * (attribute="class", enableSystem); this is the missing user-facing control.
 * Renders a stable placeholder until mounted to avoid a hydration mismatch
 * (the resolved theme is only known client-side).
 */
export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const order = ['light', 'dark', 'system'] as const;
  const current = (theme ?? 'system') as (typeof order)[number];
  const next = order[(order.indexOf(current) + 1) % order.length]!;
  const Icon = current === 'dark' ? Moon : current === 'light' ? Sun : Monitor;

  return (
    <Button
      variant="ghost"
      size="icon"
      className="shrink-0"
      onClick={() => setTheme(next)}
      aria-label={mounted ? `Theme: ${current}. Switch to ${next}.` : 'Toggle theme'}
      data-testid="theme-toggle"
    >
      {mounted ? <Icon className="size-4" aria-hidden="true" /> : <Monitor className="size-4" />}
    </Button>
  );
}
