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
 * users. A naive `dismissed = false` initial state would flash visible for
 * one render between SSR/initial-client-render and the post-mount
 * localStorage read. The `mounted` gate prevents this: we return null until
 * the post-mount effect has both (a) set mounted=true AND (b) read
 * localStorage in the same tick. Pre-dismissed users never see the banner;
 * fresh users see it only on the second commit.
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
  // SSR: assume not dismissed; React re-renders on the client using the
  // real snapshot. This is the contract for useSyncExternalStore and is
  // hydration-safe by design (no console warning).
  return false;
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
  // with any other dashboard consumer using the same params.
  const clusters = useClusters({ sort: 'name:asc', limit: 200 });

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
