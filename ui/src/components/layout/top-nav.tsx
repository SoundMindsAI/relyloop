// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';
import Link from 'next/link';
import { usePathname } from 'next/navigation';

import { ThemeToggle } from '@/components/layout/theme-toggle';
import { cn } from '@/lib/utils';

export const NAV_ITEMS = [
  { href: '/', label: 'Dashboard' },
  { href: '/clusters', label: 'Clusters' },
  { href: '/query-sets', label: 'Query Sets' },
  { href: '/templates', label: 'Templates' },
  { href: '/judgments', label: 'Judgments' },
  { href: '/studies', label: 'Studies' },
  { href: '/proposals', label: 'Proposals' },
  { href: '/chat', label: 'Chat' },
  { href: '/guide', label: 'Guides' },
] as const;

function isActive(pathname: string, href: string): boolean {
  if (href === '/') return pathname === '/';
  return pathname === href || pathname.startsWith(href + '/');
}

export function TopNav() {
  const pathname = usePathname() ?? '/';
  return (
    <nav
      className="border-b border-border bg-background"
      aria-label="Primary navigation"
      data-testid="top-nav"
    >
      <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 py-3 sm:gap-6 sm:px-6">
        <Link href="/" className="shrink-0 text-base font-semibold tracking-tight">
          RelyLoop
        </Link>
        {/* Horizontal scroll below the breakpoint so the 9 items stay usable on
            narrow screens instead of overflowing the viewport. */}
        <ul className="flex flex-1 items-center gap-1 overflow-x-auto">
          {NAV_ITEMS.map(({ href, label }) => {
            const active = isActive(pathname, href);
            return (
              <li key={href}>
                <Link
                  href={href}
                  data-active={active ? 'true' : 'false'}
                  aria-current={active ? 'page' : undefined}
                  className={cn(
                    'block whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
                    active
                      ? 'bg-primary text-primary-foreground'
                      : 'text-muted-foreground hover:bg-muted hover:text-foreground',
                  )}
                >
                  {label}
                </Link>
              </li>
            );
          })}
        </ul>
        <ThemeToggle />
      </div>
    </nav>
  );
}
