'use client';

/**
 * First-run demo-data banner for the dashboard (feat_home_first_run_demo_nudge).
 *
 * Renders above <StartHereChecklist /> when:
 *   - At least one of the 4 DEMO_CLUSTER_SLUGS is in the first page of clusters
 *   - The user has not dismissed the banner (localStorage key !== '1')
 *
 * The seed script (PR #182) creates clusters + studies on `make up`, so the
 * canonical fresh-stack already has studies — a study-count-based trigger
 * would never fire. The only sticky off-switch is explicit dismissal.
 *
 * Per spec FR-1 + FR-7, the banner MUST NOT render for already-dismissed
 * users. Hydration uses `useSyncExternalStore` with a CONSERVATIVE server
 * snapshot of `true` (dismissed) so the banner stays hidden on both the
 * server render and the first client render. After hydration, the client
 * snapshot reads localStorage via `safeLocalStorageGet`; if `'1'` the
 * banner stays hidden, otherwise it renders. Pre-dismissed users never
 * see a flash; fresh users see a normal "loading finishes, banner
 * appears" transition on the second commit.
 *
 * Same-tab dismissals are tracked in a separate `useState` because
 * localStorage doesn't fire `storage` events for the writer tab.
 */

import Link from 'next/link';
import { useState, useSyncExternalStore } from 'react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { useClusters } from '@/lib/api/clusters';
import { isDemoClusterName } from '@/lib/demo-data';
import { formatDemoClusterPrefix } from '@/lib/format-demo-cluster-prefix';
import { safeLocalStorageGet, safeLocalStorageSet } from '@/lib/safe-local-storage';

const DISMISS_KEY = 'relyloop.home-first-run-demo-nudge.dismissed';

/**
 * Subscribe to cross-tab `storage` events so a dismiss in one tab is
 * reflected in others. Same-tab dismissals are handled by sessionDismissed
 * state (localStorage doesn't fire a `storage` event for same-tab writes).
 */
function subscribeStorage(callback: () => void): () => void {
  if (typeof window === 'undefined') return () => {};
  window.addEventListener('storage', callback);
  return () => window.removeEventListener('storage', callback);
}

function getDismissedSnapshot(): boolean {
  return safeLocalStorageGet(DISMISS_KEY) === '1';
}

function getDismissedServerSnapshot(): boolean {
  // SSR + initial client render: assume DISMISSED so the banner is hidden
  // until the client snapshot is known. Conservative choice — pre-dismissed
  // users never see a flash even if cluster data is somehow available
  // during SSR (prefetch / dehydration / initialData). Fresh users get a
  // normal "loading finishes, banner appears" transition on the second
  // commit, which is fine per spec FR-1.
  return true;
}

export function DemoDataBanner(): React.ReactElement | null {
  // useSyncExternalStore handles SSR + hydration without an effect-based
  // setState (which fails the react-hooks/set-state-in-effect lint rule).
  // The hook's server snapshot is `false`; the client snapshot reads
  // localStorage immediately on the first client render.
  const storageDismissed = useSyncExternalStore(
    subscribeStorage,
    getDismissedSnapshot,
    getDismissedServerSnapshot,
  );

  // Same-tab dismissals: localStorage doesn't fire `storage` for the writer
  // tab, so we track session dismissal in component state. Banner hides if
  // EITHER source says dismissed.
  const [sessionDismissed, setSessionDismissed] = useState(false);
  const dismissed = storageDismissed || sessionDismissed;

  // Uses the existing useClusters hook — its standard queryKey
  // (['clusters', { sort, limit, ... }]) provides natural deduplication
  // with any other dashboard consumer using the same params. `enabled`
  // is gated on !dismissed so already-dismissed operators don't pay the
  // network round-trip on every dashboard mount (Gemini Code Assist
  // feedback on PR #188).
  const clusters = useClusters({ sort: 'name:asc', limit: 200, enabled: !dismissed });

  if (dismissed) return null;
  if (clusters.isError) return null;
  if (!clusters.data) return null;

  const presentDemos = clusters.data.data
    .filter((c) => isDemoClusterName(c.name))
    .map((c) => c.name);
  if (presentDemos.length === 0) return null;

  const copy = formatDemoClusterPrefix(presentDemos);

  function handleDismiss(): void {
    // Update session state synchronously so the banner unmounts on the
    // next React commit regardless of localStorage success — component
    // state is the source of truth for visibility in this tab. The
    // localStorage write is best-effort durability for future visits.
    setSessionDismissed(true);
    safeLocalStorageSet(DISMISS_KEY, '1');
  }

  return (
    <Card
      role="region"
      aria-labelledby="demo-banner-heading"
      data-testid="demo-data-banner"
      className="border-blue-200 bg-blue-50/50 dark:border-blue-900/40 dark:bg-blue-950/20"
    >
      <CardHeader>
        <CardTitle id="demo-banner-heading" className="text-base">
          You&apos;re set up with demo data.
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm">
          {copy.prefix}
          {copy.slugs.map((slug, i) => (
            <span key={slug}>
              <code className="rounded bg-blue-100 px-1 py-0.5 text-xs dark:bg-blue-900/40">
                {slug}
              </code>
              {i < copy.slugs.length - 1 ? ', ' : ''}
            </span>
          ))}
          {copy.suffix}
        </p>
        <p
          className="text-sm text-muted-foreground"
          data-testid="demo-data-banner-synthetic-ubi-prose"
        >
          Three demo clusters include simulated UBI clickstream so the UBI judgment + study path is
          visible end-to-end.
        </p>
        <div className="flex items-center gap-3">
          <Link
            href="/studies"
            data-testid="demo-data-banner-cta"
            className="text-sm font-medium text-blue-600 underline-offset-4 hover:underline"
          >
            Create your first study →
          </Link>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={handleDismiss}
                aria-label="Dismiss demo data banner"
                data-testid="demo-data-banner-dismiss"
              >
                Dismiss
              </Button>
            </TooltipTrigger>
            <TooltipContent side="bottom">
              Hide this banner in this browser. Clear browser storage to show it again.
            </TooltipContent>
          </Tooltip>
        </div>
      </CardContent>
    </Card>
  );
}
