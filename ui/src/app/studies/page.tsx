'use client';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useState } from 'react';

import { CursorPaginator } from '@/components/common/cursor-paginator';
import { EmptyState } from '@/components/common/empty-state';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { CreateStudyModal } from '@/components/studies/create-study-modal';
import { StudiesTable } from '@/components/studies/studies-table';
import { StudyStatusFilterChips } from '@/components/studies/study-status-filter-chips';
import { useStudies } from '@/lib/api/studies';

function StudiesPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const statusParam = searchParams.get('status');

  const [pageSize, setPageSize] = useState(50);
  const [cursorStack, setCursorStack] = useState<(string | undefined)[]>([undefined]);
  const [createOpen, setCreateOpen] = useState(false);
  const cursor = cursorStack[cursorStack.length - 1];

  const query = useStudies({
    status: statusParam ?? undefined,
    cursor,
    limit: pageSize,
  });

  function setStatus(next: string | null) {
    const params = new URLSearchParams(searchParams.toString());
    if (next == null) {
      params.delete('status');
    } else {
      params.set('status', next);
    }
    const qs = params.toString();
    router.replace(qs ? `/studies?${qs}` : '/studies');
    setCursorStack([undefined]);
  }

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
        <CardHeader>
          <CardTitle className="text-base">Filters</CardTitle>
        </CardHeader>
        <CardContent>
          <StudyStatusFilterChips value={statusParam} onChange={setStatus} />
        </CardContent>
      </Card>
      <Card>
        <CardContent className="pt-6">
          {query.isPending ? (
            <p className="py-12 text-center text-sm text-muted-foreground">Loading studies…</p>
          ) : query.isError ? (
            <EmptyState
              title="Backend unreachable"
              message="Check `make logs` and confirm the API container is healthy."
            />
          ) : (
            <>
              <StudiesTable rows={rows} />
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
