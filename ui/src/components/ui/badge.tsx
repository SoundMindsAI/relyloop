// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';

import { cn } from '@/lib/utils';

const badgeVariants = cva(
  'inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2',
  {
    variants: {
      // Light classes kept (semantic color families: blue=active, green=ok,
      // amber=warn, red=fail); dark: variants added so chips read correctly on
      // a dark surface instead of floating as light pastels.
      variant: {
        default: 'border-transparent bg-blue-100 text-blue-900 dark:bg-blue-950 dark:text-blue-200',
        secondary:
          'border-transparent bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-200',
        destructive: 'border-transparent bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-200',
        outline: 'border-gray-200 text-gray-700 dark:border-gray-700 dark:text-gray-200',
        success:
          'border-transparent bg-green-100 text-green-900 dark:bg-green-950 dark:text-green-200',
        warning:
          'border-transparent bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { badgeVariants };
