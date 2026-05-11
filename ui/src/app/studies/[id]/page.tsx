'use client';
import Link from 'next/link';
import { use, useState } from 'react';

import { CursorPaginator } from '@/components/common/cursor-paginator';
import { EmptyState } from '@/components/common/empty-state';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { DigestPanel } from '@/components/studies/digest-panel';
import { StudyActionBar } from '@/components/studies/study-action-bar';
import { StudyHeader } from '@/components/studies/study-header';
import { TrialsTable } from '@/components/studies/trials-table';
import { useStudyDigest } from '@/lib/api/digests';
import { useProposalForStudy } from '@/lib/api/proposals';
import { useStudy, useStudyTrials } from '@/lib/api/studies';
import type { TrialSort } from '@/lib/enums';

interface RouteProps {
  params: Promise<{ id: string }>;
}

const POLL_MS = 3000;

export function StudyDetailView({ studyId }: { studyId: string }) {
  const [pageSize, setPageSize] = useState(50);
  const [cursorStack, setCursorStack] = useState<(string | undefined)[]>([undefined]);
  const [sort, setSort] = useState<TrialSort>('primary_metric_desc');
  const cursor = cursorStack[cursorStack.length - 1];

  // Caller-driven polling per spec §4: TanStack Query's refetchInterval
  // function form derives the interval from the latest query state on each
  // tick, so the cadence flips off automatically when the study completes.
  const studyQ = useStudy(studyId, {
    refetchInterval: (q) => (q.state.data?.status === 'running' ? POLL_MS : false),
  });
  const trialsQ = useStudyTrials(studyId, {
    sort,
    cursor,
    limit: pageSize,
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
              {trialsQ.isError ? (
                <EmptyState
                  title="Backend unreachable"
                  message="Refresh after re-launching the API."
                />
              ) : (
                <>
                  <TrialsTable
                    rows={trialsQ.data?.data ?? []}
                    sort={sort}
                    onSortChange={(s) => {
                      setSort(s);
                      setCursorStack([undefined]);
                    }}
                  />
                  <CursorPaginator
                    hasMore={trialsQ.data?.has_more ?? false}
                    onNext={() =>
                      setCursorStack((s) => [...s, trialsQ.data?.next_cursor ?? undefined])
                    }
                    onPrev={
                      cursorStack.length > 1
                        ? () => setCursorStack((s) => s.slice(0, -1))
                        : undefined
                    }
                    pageSize={pageSize}
                    onPageSizeChange={(n) => {
                      setPageSize(n);
                      setCursorStack([undefined]);
                    }}
                    totalCount={trialsQ.data?.totalCount}
                  />
                </>
              )}
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
  return <StudyDetailView studyId={id} />;
}
