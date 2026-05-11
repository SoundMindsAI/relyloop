'use client';
import { Suspense, useState } from 'react';

import { CursorPaginator } from '@/components/common/cursor-paginator';
import { EmptyState } from '@/components/common/empty-state';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { TemplatesTable } from '@/components/templates/templates-table';
import { CreateTemplateModal } from '@/components/templates/create-template-modal';
import { useTemplates } from '@/lib/api/query-templates';

function TemplatesPageInner() {
  const [pageSize, setPageSize] = useState(50);
  const [cursorStack, setCursorStack] = useState<(string | undefined)[]>([undefined]);
  const [createOpen, setCreateOpen] = useState(false);
  const cursor = cursorStack[cursorStack.length - 1];

  const query = useTemplates({ cursor, limit: pageSize });
  const rows = query.data?.data ?? [];

  return (
    <main className="mx-auto max-w-7xl space-y-6 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Query Templates</h1>
        <Button onClick={() => setCreateOpen(true)}>Create template</Button>
      </div>
      <Card>
        <CardHeader>
          <CardTitle className="text-base">All templates</CardTitle>
        </CardHeader>
        <CardContent>
          {query.isPending ? (
            <p className="py-12 text-center text-sm text-muted-foreground">Loading…</p>
          ) : query.isError ? (
            <EmptyState
              title="Backend unreachable"
              message="Check `make logs` and confirm the API container is healthy."
            />
          ) : (
            <>
              <TemplatesTable rows={rows} />
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
      <CreateTemplateModal open={createOpen} onOpenChange={setCreateOpen} />
    </main>
  );
}

export default function TemplatesPage() {
  return (
    <Suspense fallback={<main className="mx-auto max-w-7xl p-6">Loading…</main>}>
      <TemplatesPageInner />
    </Suspense>
  );
}
