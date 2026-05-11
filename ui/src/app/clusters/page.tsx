'use client';
import { useState } from 'react';

import { CursorPaginator } from '@/components/common/cursor-paginator';
import { EmptyState } from '@/components/common/empty-state';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ClustersTable } from '@/components/clusters/clusters-table';
import { RegisterClusterModal } from '@/components/clusters/register-cluster-modal';
import { useClusters } from '@/lib/api/clusters';

export default function ClustersPage() {
  const [pageSize, setPageSize] = useState(50);
  const [cursorStack, setCursorStack] = useState<(string | undefined)[]>([undefined]);
  const [registerOpen, setRegisterOpen] = useState(false);
  const cursor = cursorStack[cursorStack.length - 1];

  const query = useClusters({ cursor, limit: pageSize });

  return (
    <main className="mx-auto max-w-7xl space-y-6 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Clusters</h1>
        <Button onClick={() => setRegisterOpen(true)} data-testid="open-register-cluster">
          Register cluster
        </Button>
      </div>
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Registered clusters</CardTitle>
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
              <ClustersTable rows={query.data?.data ?? []} />
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
      <RegisterClusterModal open={registerOpen} onOpenChange={setRegisterOpen} />
    </main>
  );
}
