'use client';
import Link from 'next/link';
import { use, useState } from 'react';

import { CursorPaginator } from '@/components/common/cursor-paginator';
import { EmptyState } from '@/components/common/empty-state';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { CalibrationModal } from '@/components/judgments/calibration-modal';
import { JudgmentListHeader } from '@/components/judgments/judgment-list-header';
import { JudgmentsTable, type SourceChoice } from '@/components/judgments/judgments-table';
import { useJudgmentList, useJudgments } from '@/lib/api/judgments';

interface RouteProps {
  params: Promise<{ id: string }>;
}

export function JudgmentListView({ listId }: { listId: string }) {
  const [pageSize, setPageSize] = useState(50);
  const [cursorStack, setCursorStack] = useState<(string | undefined)[]>([undefined]);
  const [source, setSource] = useState<SourceChoice>('all');
  const [calibrationOpen, setCalibrationOpen] = useState(false);
  const cursor = cursorStack[cursorStack.length - 1];

  const list = useJudgmentList(listId);
  const judgments = useJudgments(listId, {
    cursor,
    limit: pageSize,
    source: source === 'all' ? undefined : source,
  });

  return (
    <main className="mx-auto max-w-7xl space-y-6 p-6">
      <div>
        <Link
          href="/judgments"
          className="text-sm text-blue-600 underline-offset-4 hover:underline"
        >
          ← All judgment lists
        </Link>
      </div>
      {list.isPending ? (
        <Card>
          <CardContent>
            <p className="py-12 text-center text-sm text-muted-foreground">Loading…</p>
          </CardContent>
        </Card>
      ) : list.isError ? (
        <EmptyState title="Judgment list not found" message="The list may have been removed." />
      ) : list.data ? (
        <>
          <div className="flex items-center justify-between">
            <h1 className="text-2xl font-semibold tracking-tight">Judgment Review</h1>
            <Button onClick={() => setCalibrationOpen(true)} data-testid="open-calibration">
              Calibrate
            </Button>
          </div>
          <JudgmentListHeader list={list.data} />
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Judgments</CardTitle>
            </CardHeader>
            <CardContent>
              {judgments.isPending ? (
                <p className="py-12 text-center text-sm text-muted-foreground">Loading…</p>
              ) : judgments.isError ? (
                <EmptyState
                  title="Backend unreachable"
                  message="Check `make logs` and confirm the API container is healthy."
                />
              ) : (
                <>
                  <JudgmentsTable
                    rows={judgments.data?.data ?? []}
                    listId={listId}
                    sourceFilter={source}
                    onSourceFilterChange={(next) => {
                      setSource(next);
                      setCursorStack([undefined]);
                    }}
                  />
                  <CursorPaginator
                    hasMore={judgments.data?.has_more ?? false}
                    onNext={() =>
                      setCursorStack((s) => [...s, judgments.data?.next_cursor ?? undefined])
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
                    totalCount={judgments.data?.totalCount}
                  />
                </>
              )}
            </CardContent>
          </Card>
          <CalibrationModal
            open={calibrationOpen}
            onOpenChange={setCalibrationOpen}
            listId={listId}
          />
        </>
      ) : null}
    </main>
  );
}

export default function JudgmentListPage({ params }: RouteProps) {
  const { id } = use(params);
  return <JudgmentListView listId={id} />;
}
