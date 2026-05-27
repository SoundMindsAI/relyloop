'use client';
import Link from 'next/link';
import { Suspense, use, useMemo, useState } from 'react';

import { DetailPageShell } from '@/components/common/detail-page-shell';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { CalibrationModal } from '@/components/judgments/calibration-modal';
import { JudgmentListHeader } from '@/components/judgments/judgment-list-header';
import { JudgmentsTable } from '@/components/judgments/judgments-table';
import { useJudgmentsColumns } from '@/components/judgments/judgments-table.column-config';
import { useDataTableUrlState } from '@/hooks/use-data-table-url-state';
import { useJudgmentList, useJudgments } from '@/lib/api/judgments';
import { JUDGMENT_SOURCE_FILTER_VALUES } from '@/lib/enums';

interface RouteProps {
  params: Promise<{ id: string }>;
}

export function JudgmentListView({ listId }: { listId: string }) {
  // The column config carries the filter declaration the URL hook consults
  // to figure out which params are filter keys. Pulling the columns once
  // here gives the hook the right scope without re-computing them.
  const columns = useJudgmentsColumns(listId);
  // Scope the URL hook by listId so col-vis + density preferences don't
  // bleed across different judgment lists' detail pages.
  const urlState = useDataTableUrlState(`judgments-${listId}`, columns, { defaultPageSize: 50 });
  const [calibrationOpen, setCalibrationOpen] = useState(false);

  // Narrow the URL source value to the backend's accepted set.
  const rawSource = urlState.filters['source'];
  const source = useMemo<'llm' | 'human' | undefined>(() => {
    if (rawSource === 'llm' || rawSource === 'human') return rawSource;
    if (rawSource && !(JUDGMENT_SOURCE_FILTER_VALUES as readonly string[]).includes(rawSource)) {
      return undefined;
    }
    return undefined;
  }, [rawSource]);

  const list = useJudgmentList(listId);
  const judgments = useJudgments(listId, {
    source,
    sort: urlState.sort ?? undefined,
    cursor: urlState.cursor ?? undefined,
    limit: urlState.pageSize,
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
      <DetailPageShell
        query={list}
        entityLabel="judgment list"
        notFoundErrorCode="JUDGMENT_LIST_NOT_FOUND"
      >
        {(listData) => (
          <>
            <div className="flex items-center justify-between">
              <h1 className="text-2xl font-semibold tracking-tight">Judgment Review</h1>
              <Button onClick={() => setCalibrationOpen(true)} data-testid="open-calibration">
                Calibrate
              </Button>
            </div>
            <p className="text-sm text-muted-foreground" data-testid="judgment-page-summary">
              A judgment list is the <strong>(query, doc, rating)</strong> ground truth your studies
              score against. Ratings come from an LLM (graded against your rubric) or from an
              operator-imported file. <strong>Calibrate</strong> compares LLM-graded ratings against
              a human-imported reference list via Cohen's κ — high agreement means the LLM mirrors
              your team's judgment. Click the floating <em>Guide</em> button (bottom-right) for the
              step-by-step walkthrough.
            </p>
            <JudgmentListHeader list={listData} />
            <Card>
              <CardContent className="pt-6">
                <JudgmentsTable
                  rows={judgments.data?.data ?? []}
                  listId={listId}
                  totalCount={judgments.data?.totalCount}
                  has_more={judgments.data?.has_more ?? false}
                  next_cursor={judgments.data?.next_cursor ?? null}
                  isLoading={judgments.isPending}
                  isError={judgments.isError}
                  urlState={urlState}
                />
              </CardContent>
            </Card>
            <CalibrationModal
              open={calibrationOpen}
              onOpenChange={setCalibrationOpen}
              listId={listId}
            />
          </>
        )}
      </DetailPageShell>
    </main>
  );
}

export default function JudgmentListPage({ params }: RouteProps) {
  const { id } = use(params);
  return (
    <Suspense fallback={<main className="mx-auto max-w-7xl p-6">Loading…</main>}>
      <JudgmentListView listId={id} />
    </Suspense>
  );
}
