'use client';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useMemo, useState } from 'react';

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

  const query = useProposals(
    {
      status,
      cluster_id: clusterFilter ?? undefined,
      cursor,
      limit: pageSize,
    },
    {
      // FR-1: auto-refetch every 30s if any visible row has
      // status='pr_opened' AND pr_state='open' (catches webhook-driven updates
      // without manual reload). Returns false otherwise so idle pages stop
      // hitting the backend.
      refetchInterval: (q) =>
        q.state.data?.data?.some((p) => p.status === 'pr_opened' && p.pr_state === 'open')
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

  const rows = query.data?.data ?? [];
  const visibleRows = useMemo(
    () =>
      rows.filter((r) => {
        if (sourceFilter === 'all') return true;
        if (sourceFilter === 'study') return r.study_id != null;
        return r.study_id == null;
      }),
    [rows, sourceFilter],
  );

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
