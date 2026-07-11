// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import Link from 'next/link';

import { EmptyState } from '@/components/common/empty-state';
import { Button } from '@/components/ui/button';

/**
 * Global 404. Rendered for unmatched routes and any `notFound()` call that
 * isn't caught by a nearer boundary. Inherits the root layout (TopNav stays),
 * so it just needs recovery content + a way back — not a bare Next default.
 */
export default function NotFound() {
  return (
    <main className="mx-auto max-w-3xl p-6">
      <EmptyState
        title="Page not found"
        message="That page doesn't exist or may have been moved. It might be a deleted study, proposal, or a mistyped link."
        action={
          <Button asChild>
            <Link href="/">Back to dashboard</Link>
          </Button>
        }
      />
    </main>
  );
}
