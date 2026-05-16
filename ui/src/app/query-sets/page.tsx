'use client';
import { Suspense, useState } from 'react';

import { CreateQuerySetModal } from '@/components/query-sets/create-query-set-modal';
import { QuerySetsTable } from '@/components/query-sets/query-sets-table';
import { querySetsColumns } from '@/components/query-sets/query-sets-table.column-config';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { useDataTableUrlState } from '@/hooks/use-data-table-url-state';
import { useQuerySets } from '@/lib/api/query-sets';

function QuerySetsPageInner() {
  const urlState = useDataTableUrlState('query-sets', querySetsColumns, { defaultPageSize: 50 });
  const [createOpen, setCreateOpen] = useState(false);

  const query = useQuerySets({
    q: urlState.q ?? undefined,
    sort: urlState.sort ?? undefined,
    cursor: urlState.cursor ?? undefined,
    limit: urlState.pageSize,
  });

  return (
    <main className="mx-auto max-w-7xl space-y-6 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Query Sets</h1>
        <Button onClick={() => setCreateOpen(true)} data-testid="open-create-query-set">
          Create query set
        </Button>
      </div>
      <Card>
        <CardContent className="pt-6">
          <QuerySetsTable
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
      <CreateQuerySetModal open={createOpen} onOpenChange={setCreateOpen} />
    </main>
  );
}

export default function QuerySetsPage() {
  return (
    <Suspense fallback={<main className="mx-auto max-w-7xl p-6">Loading…</main>}>
      <QuerySetsPageInner />
    </Suspense>
  );
}
