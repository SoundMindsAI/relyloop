// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';
import { Suspense } from 'react';

import { JudgmentListsTable } from '@/components/judgments/judgment-lists-table';
import { judgmentListsColumns } from '@/components/judgments/judgment-lists-table.column-config';
import { Card, CardContent } from '@/components/ui/card';
import { useDataTableUrlState } from '@/hooks/use-data-table-url-state';
import { useDocumentTitle } from '@/hooks/use-document-title';
import { useJudgmentLists } from '@/lib/api/judgments';

function JudgmentsPageInner() {
  useDocumentTitle('Judgments');
  const urlState = useDataTableUrlState('judgment-lists', judgmentListsColumns, {
    defaultPageSize: 50,
  });

  const query = useJudgmentLists({
    cursor: urlState.cursor ?? undefined,
    limit: urlState.pageSize,
  });

  return (
    <main className="mx-auto max-w-7xl space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Judgments</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Judgment lists are the graded query→document relevance labels a study optimizes against.
          Generate one from a query set (LLM-as-judge) or from UBI click data.
        </p>
      </div>
      <Card>
        <CardContent className="pt-6">
          <JudgmentListsTable
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

export default function JudgmentsPage() {
  return (
    <Suspense fallback={<main className="mx-auto max-w-7xl p-6">Loading…</main>}>
      <JudgmentsPageInner />
    </Suspense>
  );
}
