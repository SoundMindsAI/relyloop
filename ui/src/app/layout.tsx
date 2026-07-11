// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import type { Metadata } from 'next';
import './globals.css';

import { GuideTrigger } from '@/components/guides/guide-trigger';
import { QueryProvider } from '@/components/providers/query-provider';
import { ThemeProvider } from '@/components/providers/theme-provider';
import { TopNav } from '@/components/layout/top-nav';
import { Toaster } from '@/components/ui/sonner';
import { TooltipProvider } from '@/components/ui/tooltip';

export const metadata: Metadata = {
  title: 'RelyLoop',
  description: 'Open-source automated relevance tuning for enterprise search platforms',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    /* suppressHydrationWarning required because next-themes injects a `class`
       attribute on <html> from inline script before React hydrates. Without it
       React 19's strict-mode rendering logs an "Extra attributes from the server"
       warning that fails the `pnpm build` strict-mode SSR pass. */
    <html lang="en" suppressHydrationWarning>
      <body>
        <ThemeProvider>
          <QueryProvider>
            <TooltipProvider delayDuration={700}>
              {/* Skip link: first focusable element, visually hidden until
                  focused, so keyboard/switch users can jump past the 8-item
                  nav straight to page content. */}
              <a
                href="#main-content"
                className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-background focus:px-4 focus:py-2 focus:shadow focus:ring-2 focus:ring-ring"
              >
                Skip to content
              </a>
              <TopNav />
              <div id="main-content" tabIndex={-1} className="outline-none">
                {children}
              </div>
              <Toaster />
              <GuideTrigger />
            </TooltipProvider>
          </QueryProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
