'use client';
import { Suspense, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { CreateStudyModal } from '@/components/studies/create-study-modal';
import { StudiesTable } from '@/components/studies/studies-table';
import { studiesColumns } from '@/components/studies/studies-table.column-config';
import { useDataTableUrlState } from '@/hooks/use-data-table-url-state';
import { useStudies } from '@/lib/api/studies';

function StudiesPageInner() {
  const urlState = useDataTableUrlState('studies', studiesColumns, { defaultPageSize: 50 });
  const [createOpen, setCreateOpen] = useState(false);

  const query = useStudies({
    status: urlState.filters['status'],
    sort: urlState.sort ?? undefined,
    q: urlState.q ?? undefined,
    cursor: urlState.cursor ?? undefined,
    limit: urlState.pageSize,
  });

  const rows = query.data?.data ?? [];

  return (
    <main className="mx-auto max-w-7xl space-y-6 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Studies</h1>
        <Button onClick={() => setCreateOpen(true)} data-testid="open-create-study">
          Create study
        </Button>
      </div>
      <Card>
        <CardContent className="pt-6">
          <StudiesTable
            rows={rows}
            totalCount={query.data?.totalCount}
            has_more={query.data?.has_more ?? false}
            next_cursor={query.data?.next_cursor ?? null}
            isLoading={query.isPending}
            isError={query.isError}
            urlState={urlState}
          />
        </CardContent>
      </Card>
      <CreateStudyModal open={createOpen} onOpenChange={setCreateOpen} />
    </main>
  );
}

export default function StudiesPage() {
  // `useSearchParams` must live under a `<Suspense>` boundary in Next 16 App Router.
  return (
    <Suspense fallback={<main className="mx-auto max-w-7xl p-6">Loading…</main>}>
      <StudiesPageInner />
    </Suspense>
  );
}
