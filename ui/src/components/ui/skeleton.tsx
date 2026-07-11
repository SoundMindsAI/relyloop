// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { cn } from '@/lib/utils';

/**
 * Shape-holding loading placeholder. Use instead of a bare "Loading…" text so
 * the layout doesn't shift when real content arrives. Respects reduced-motion.
 */
export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('animate-pulse rounded-md bg-muted motion-reduce:animate-none', className)}
      aria-hidden="true"
      {...props}
    />
  );
}
