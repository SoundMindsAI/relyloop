'use client';
import Link from 'next/link';
import { Suspense, use } from 'react';

import { EmptyState } from '@/components/common/empty-state';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { DigestPanel } from '@/components/studies/digest-panel';
import { StudyActionBar } from '@/components/studies/study-action-bar';
import { StudyHeader } from '@/components/studies/study-header';
import { TrialsTable } from '@/components/studies/trials-table';
import { trialsColumns } from '@/components/studies/trials-table.column-config';
import { useDataTableUrlState } from '@/hooks/use-data-table-url-state';
import { useStudyDigest } from '@/lib/api/digests';
import { useProposalForStudy } from '@/lib/api/proposals';
import { useStudy, useStudyTrials } from '@/lib/api/studies';
import { TRIAL_SORT_VALUES, type TrialSort } from '@/lib/enums';

interface RouteProps {
  params: Promise<{ id: string }>;
}

const POLL_MS = 3000;
const DEFAULT_TRIAL_SORT: TrialSort = 'primary_metric_desc';

export function StudyDetailView({ studyId }: { studyId: string }) {
  // Scope the URL hook by studyId so col-vis + density preferences don't
  // bleed across different study detail pages.
  const urlState = useDataTableUrlState(`trials-${studyId}`, trialsColumns, {
    defaultPageSize: 50,
  });

  // Narrow the URL sort value to the canonical TrialSortKey allowlist —
  // invalid values fall back to the default. The DataTable feeds the wire
  // form back via urlState.sort thanks to trialsSortCodec; this narrowing
  // protects useStudyTrials from receiving an arbitrary string when an
  // operator hand-edits the URL.
  const rawSort = urlState.sort;
  const sort: TrialSort =
    rawSort && (TRIAL_SORT_VALUES as readonly string[]).includes(rawSort)
      ? (rawSort as TrialSort)
      : DEFAULT_TRIAL_SORT;

  // Caller-driven polling per spec §4: TanStack Query's refetchInterval
  // function form derives the interval from the latest query state on each
  // tick, so the cadence flips off automatically when the study completes.
  const studyQ = useStudy(studyId, {
    refetchInterval: (q) => (q.state.data?.status === 'running' ? POLL_MS : false),
  });
  const trialsQ = useStudyTrials(studyId, {
    sort,
    cursor: urlState.cursor ?? undefined,
    limit: urlState.pageSize,
    refetchInterval: () => (studyQ.data?.status === 'running' ? POLL_MS : false),
  });
  const digestQ = useStudyDigest(studyId);
  const proposalQ = useProposalForStudy(studyId);

  return (
    <main className="mx-auto max-w-7xl space-y-6 p-6">
      <div>
        <Link href="/studies" className="text-sm text-blue-600 underline-offset-4 hover:underline">
          ← All studies
        </Link>
      </div>
      {studyQ.isPending ? (
        <Card>
          <CardContent>
            <p className="py-12 text-center text-sm text-muted-foreground">Loading…</p>
          </CardContent>
        </Card>
      ) : studyQ.isError ? (
        <EmptyState title="Study not found" message="The study may have been deleted." />
      ) : studyQ.data ? (
        <>
          <div className="flex items-center justify-between">
            <h1 className="text-2xl font-semibold tracking-tight">Study detail</h1>
            <StudyActionBar study={studyQ.data} />
          </div>
          <StudyHeader study={studyQ.data} />
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Trials</CardTitle>
            </CardHeader>
            <CardContent>
              <TrialsTable
                rows={trialsQ.data?.data ?? []}
                totalCount={trialsQ.data?.totalCount}
                has_more={trialsQ.data?.has_more ?? false}
                next_cursor={trialsQ.data?.next_cursor ?? null}
                isLoading={trialsQ.isPending}
                isError={trialsQ.isError}
                urlState={urlState}
                tableId={`trials-${studyId}`}
              />
            </CardContent>
          </Card>
          {studyQ.data.status === 'completed' && digestQ.data && (
            <DigestPanel
              digest={digestQ.data}
              baselineMetric={studyQ.data.baseline_metric ?? null}
              bestMetric={studyQ.data.best_metric ?? null}
              pendingProposal={proposalQ.data ?? null}
            />
          )}
        </>
      ) : null}
    </main>
  );
}

export default function StudyDetailPage({ params }: RouteProps) {
  const { id } = use(params);
  // `useSearchParams` (inside useDataTableUrlState) requires a Suspense boundary
  // in Next 16 App Router.
  return (
    <Suspense fallback={<main className="mx-auto max-w-7xl p-6">Loading…</main>}>
      <StudyDetailView studyId={id} />
    </Suspense>
  );
}
