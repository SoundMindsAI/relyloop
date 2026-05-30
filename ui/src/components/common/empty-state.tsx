// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { cn } from '@/lib/utils';

export interface EmptyStateProps {
  title: string;
  message?: string;
  action?: React.ReactNode;
  className?: string;
}

export function EmptyState({ title, message, action, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-gray-200 bg-gray-50 p-12 text-center',
        className,
      )}
      role="status"
      data-testid="empty-state"
    >
      <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
      {message && <p className="max-w-md text-sm text-gray-600">{message}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
