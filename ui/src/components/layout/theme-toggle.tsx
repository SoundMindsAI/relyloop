// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

import { Moon, Sun } from 'lucide-react';
import { useTheme } from 'next-themes';
import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';

/**
 * Light ↔ dark theme toggle for the nav. next-themes is already wired
 * (attribute="class", enableSystem); this is the missing user-facing control.
 *
 * Toggles off `resolvedTheme` (the actually-displayed theme, whether from an
 * explicit choice or the system preference) so every click produces a visible
 * change — a blind light→dark→system cycle can no-op on the first click when
 * system already resolves to the theme it lands on (Gemini review). Renders a
 * stable placeholder until mounted to avoid a hydration mismatch (the resolved
 * theme is only known client-side).
 */
export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  // Canonical next-themes hydration guard: the resolved theme is only known
  // client-side, so render a stable placeholder until mount. The synchronous
  // set-on-mount is intentional (one-shot, empty deps).
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => setMounted(true), []);

  const isDark = resolvedTheme === 'dark';
  const next = isDark ? 'light' : 'dark';
  const Icon = isDark ? Moon : Sun;

  return (
    <Button
      variant="ghost"
      size="icon"
      className="shrink-0"
      onClick={() => setTheme(next)}
      aria-label={mounted ? `Switch to ${next} theme` : 'Toggle theme'}
      data-testid="theme-toggle"
    >
      {mounted ? <Icon className="size-4" aria-hidden="true" /> : <Sun className="size-4" />}
    </Button>
  );
}
