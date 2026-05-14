'use client';
import Link from 'next/link';
import { usePathname } from 'next/navigation';

import { cn } from '@/lib/utils';

export const NAV_ITEMS = [
  { href: '/', label: 'Dashboard' },
  { href: '/clusters', label: 'Clusters' },
  { href: '/query-sets', label: 'Query Sets' },
  { href: '/templates', label: 'Templates' },
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
      className="border-b border-gray-200 bg-white"
      aria-label="Primary navigation"
      data-testid="top-nav"
    >
      <div className="mx-auto flex max-w-7xl items-center gap-6 px-6 py-3">
        <Link href="/" className="text-base font-semibold tracking-tight">
          RelyLoop
        </Link>
        <ul className="flex items-center gap-1">
          {NAV_ITEMS.map(({ href, label }) => {
            const active = isActive(pathname, href);
            return (
              <li key={href}>
                <Link
                  href={href}
                  data-active={active ? 'true' : 'false'}
                  aria-current={active ? 'page' : undefined}
                  className={cn(
                    'rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
                    active
                      ? 'bg-gray-900 text-white'
                      : 'text-gray-700 hover:bg-gray-100 hover:text-gray-900',
                  )}
                >
                  {label}
                </Link>
              </li>
            );
          })}
        </ul>
      </div>
    </nav>
  );
}
