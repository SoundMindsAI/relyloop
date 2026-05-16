'use client';
import { Suspense } from 'react';

import { ProposalsTable } from '@/components/proposals/proposals-table';
import { proposalsColumns } from '@/components/proposals/proposals-table.column-config';
import { Card, CardContent } from '@/components/ui/card';
import { useDataTableUrlState } from '@/hooks/use-data-table-url-state';
import { useProposals } from '@/lib/api/proposals';
import { PROPOSAL_STATUS_VALUES, type ProposalStatus } from '@/lib/enums';

function ProposalsPageInner() {
  const urlState = useDataTableUrlState('proposals', proposalsColumns, { defaultPageSize: 50 });

  // Validate URL ?status= against the canonical allowlist — invalid values
  // become undefined rather than reaching the typed `useProposals` hook.
  // Matches the pre-migration safety check (see prior implementation).
  const rawStatus = urlState.filters['status'];
  const status: ProposalStatus | undefined =
    rawStatus && (PROPOSAL_STATUS_VALUES as readonly string[]).includes(rawStatus)
      ? (rawStatus as ProposalStatus)
      : undefined;

  const rawSource = urlState.filters['source'];
  const source: 'study' | 'manual' | undefined =
    rawSource === 'study' || rawSource === 'manual' ? rawSource : undefined;

  const query = useProposals(
    {
      status,
      cluster_id: urlState.filters['cluster_id'] ?? undefined,
      template_id: urlState.filters['template_id'] ?? undefined,
      source,
      sort: urlState.sort ?? undefined,
      cursor: urlState.cursor ?? undefined,
      limit: urlState.pageSize,
    },
    {
      // FR-1: 30s refetch when any row has status='pr_opened' AND pr_state='open'
      // — catches webhook-driven updates without manual reload.
      refetchInterval: (q) =>
        q.state.data?.data?.some((p) => p.status === 'pr_opened' && p.pr_state === 'open')
          ? 30_000
          : false,
    },
  );

  return (
    <main className="mx-auto max-w-7xl space-y-6 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Proposals</h1>
      </div>
      <Card>
        <CardContent className="pt-6">
          <ProposalsTable
            rows={query.data?.data ?? []}
            totalCount={query.data?.totalCount}
            has_more={query.data?.has_more ?? false}
            next_cursor={query.data?.next_cursor ?? null}
            isLoading={query.isPending}
            isError={query.isError}
            urlState={urlState}
          />
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
