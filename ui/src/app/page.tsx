/**
 * Welcome stub home page.
 *
 * This is the transitional shell after `infra_foundation`'s placeholder and
 * before Story 3.1's real dashboard. It exists so `/` doesn't 404 between
 * Stories 1.2 and 3.1.
 */
import Link from 'next/link';

import { Button } from '@/components/ui/button';

export default function HomePage() {
  return (
    <main className="mx-auto max-w-3xl space-y-6 p-8">
      <h1 className="text-3xl font-semibold tracking-tight">Welcome to RelyLoop</h1>
      <p className="text-gray-600">
        Open-source automated relevance tuning for enterprise search platforms. The dashboard is
        coming online — meanwhile, jump straight to a section:
      </p>
      <div className="flex flex-wrap gap-3">
        <Button asChild>
          <Link href="/studies">Studies</Link>
        </Button>
        <Button asChild variant="outline">
          <Link href="/clusters">Clusters</Link>
        </Button>
        <Button asChild variant="outline">
          <Link href="/query-sets">Query Sets</Link>
        </Button>
      </div>
    </main>
  );
}
