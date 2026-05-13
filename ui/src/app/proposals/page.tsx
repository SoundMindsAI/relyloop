'use client';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useCallback, useMemo, useState } from 'react';

import { CursorPaginator } from '@/components/common/cursor-paginator';
import { EmptyState } from '@/components/common/empty-state';
import { ClusterFilterSelect } from '@/components/proposals/cluster-filter-select';
import {
  ProposalSourceFilterChips,
  type ProposalSourceFilterValue,
} from '@/components/proposals/proposal-source-filter-chips';
import { ProposalStatusFilterChips } from '@/components/proposals/proposal-status-filter-chips';
import { ProposalsTable } from '@/components/proposals/proposals-table';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useProposals } from '@/lib/api/proposals';
import { PROPOSAL_STATUS_VALUES, type ProposalStatus } from '@/lib/enums';

function ProposalsPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const rawStatus = searchParams.get('status');
  // Validate the URL ?status= against the canonical allowlist before passing to
  // the now-narrowed useProposals hook. Invalid values are silently ignored so
  // operators cannot send /proposals?status=invented to the backend.
  // Per GPT-5.5 cycle-2 A2.
  const status: ProposalStatus | undefined =
    rawStatus && (PROPOSAL_STATUS_VALUES as readonly string[]).includes(rawStatus)
      ? (rawStatus as ProposalStatus)
      : undefined;

  const [pageSize, setPageSize] = useState(50);
  const [cursorStack, setCursorStack] = useState<(string | undefined)[]>([undefined]);
  const [sourceFilter, setSourceFilter] = useState<ProposalSourceFilterValue>('all');
  const [clusterFilter, setClusterFilter] = useState<string | null>(null);
  const cursor = cursorStack[cursorStack.length - 1];

  // Single source of truth for the post-fetch source filter; consumed both
  // by visibleRows below AND by the refetchInterval predicate inside
  // useProposals so a future change to the filter semantics lands in one
  // place (per Gemini suggestion on PR #77).
  const matchesSourceFilter = useCallback(
    (p: { study_id: string | null }) => {
      if (sourceFilter === 'all') return true;
      if (sourceFilter === 'study') return p.study_id != null;
      return p.study_id == null;
    },
    [sourceFilter],
  );

  const query = useProposals(
    {
      status,
      cluster_id: clusterFilter ?? undefined,
      cursor,
      limit: pageSize,
    },
    {
      // FR-1: auto-refetch every 30s if any VISIBLE row has
      // status='pr_opened' AND pr_state='open' (catches webhook-driven updates
      // without manual reload). The visibility check applies the same
      // client-side source filter that's applied to rows on render, so a
      // study-sourced pr_opened+open row hidden by sourceFilter='manual'
      // doesn't keep the page polling for invisible state (per GPT-5.5
      // final-review cycle finding #3). Returns false otherwise so idle
      // pages stop hitting the backend.
      refetchInterval: (q) =>
        q.state.data?.data?.some((p) => {
          if (p.status !== 'pr_opened' || p.pr_state !== 'open') return false;
          return matchesSourceFilter(p);
        })
          ? 30_000
          : false,
    },
  );

  function setStatus(next: ProposalStatus | null) {
    const params = new URLSearchParams(searchParams.toString());
    if (next == null) {
      params.delete('status');
    } else {
      params.set('status', next);
    }
    const qs = params.toString();
    router.replace(qs ? `/proposals?${qs}` : '/proposals');
    setCursorStack([undefined]);
  }

  function setSource(next: ProposalSourceFilterValue) {
    setSourceFilter(next);
    // No cursor reset here: source is a post-fetch filter; backend pagination
    // is unaware of it (see chore_proposals_source_filter_server_side idea).
  }

  function setCluster(next: string | null) {
    setClusterFilter(next);
    setCursorStack([undefined]);
  }

  const visibleRows = useMemo(() => {
    const rows = query.data?.data ?? [];
    return rows.filter(matchesSourceFilter);
  }, [query.data, matchesSourceFilter]);

  return (
    <main className="mx-auto max-w-7xl space-y-6 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Proposals</h1>
      </div>
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Filters</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <ProposalStatusFilterChips value={status ?? null} onChange={setStatus} />
          <ProposalSourceFilterChips value={sourceFilter} onChange={setSource} />
          <ClusterFilterSelect value={clusterFilter} onChange={setCluster} />
        </CardContent>
      </Card>
      <Card>
        <CardContent className="pt-6">
          {query.isPending ? (
            <p className="py-12 text-center text-sm text-muted-foreground">Loading proposals…</p>
          ) : query.isError ? (
            <EmptyState
              title="Backend unreachable"
              message="Check `make logs` and confirm the API container is healthy."
            />
          ) : visibleRows.length === 0 ? (
            <EmptyState
              title="No proposals yet"
              message="They appear automatically when studies complete."
            />
          ) : (
            <>
              <ProposalsTable rows={visibleRows} />
              <CursorPaginator
                hasMore={query.data?.has_more ?? false}
                onNext={() => setCursorStack((s) => [...s, query.data?.next_cursor ?? undefined])}
                onPrev={
                  cursorStack.length > 1 ? () => setCursorStack((s) => s.slice(0, -1)) : undefined
                }
                pageSize={pageSize}
                onPageSizeChange={(n) => {
                  setPageSize(n);
                  setCursorStack([undefined]);
                }}
                totalCount={query.data?.totalCount}
              />
            </>
          )}
        </CardContent>
      </Card>
    </main>
  );
}

export default function ProposalsPage() {
  // `useSearchParams` must live under a `<Suspense>` boundary in Next 16 App Router.
  return (
    <Suspense fallback={<main className="mx-auto max-w-7xl p-6">Loading…</main>}>
      <ProposalsPageInner />
    </Suspense>
  );
}
