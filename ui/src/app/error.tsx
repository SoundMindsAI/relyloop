// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useEffect } from 'react';

import { EmptyState } from '@/components/common/empty-state';
import { Button } from '@/components/ui/button';

/**
 * Route-segment error boundary. Catches render-time exceptions anywhere below
 * the root layout (a malformed payload a component didn't defensively parse, a
 * thrown error in a child) and shows a recoverable card instead of a blank
 * white screen. `reset()` re-renders the segment; the Dashboard link is the
 * always-works escape hatch. TanStack query errors are handled separately (the
 * global toast + per-surface states) — this is the last-resort render backstop.
 */
export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Surface for local debugging / future error reporting; never rethrows.
    console.error(error);
  }, [error]);

  return (
    <main className="mx-auto max-w-3xl p-6">
      <EmptyState
        title="Something went wrong"
        message="This page hit an unexpected error. Try again, or head back to the dashboard."
        action={
          <div className="flex gap-2">
            <Button onClick={reset}>Try again</Button>
            <Button variant="outline" onClick={() => (window.location.href = '/')}>
              Back to dashboard
            </Button>
          </div>
        }
      />
    </main>
  );
}
