'use client';
import { useState } from 'react';

import { CursorPaginator } from '@/components/common/cursor-paginator';
import { EmptyState } from '@/components/common/empty-state';
import { StudiesTable } from '@/components/studies/studies-table';
import { useStudies } from '@/lib/api/studies';

export interface StudiesByClusterTableProps {
  clusterId: string;
}

export function StudiesByClusterTable({ clusterId }: StudiesByClusterTableProps) {
  const [pageSize, setPageSize] = useState(25);
  const [cursorStack, setCursorStack] = useState<(string | undefined)[]>([undefined]);
  const cursor = cursorStack[cursorStack.length - 1];

  const query = useStudies({ cluster_id: clusterId, cursor, limit: pageSize });
  if (query.isPending) {
    return <p className="py-6 text-center text-sm text-muted-foreground">Loading studies…</p>;
  }
  if (query.isError) {
    return <EmptyState title="Backend unreachable" message="Refresh after re-launching the API." />;
  }
  return (
    <div className="space-y-3">
      <StudiesTable rows={query.data?.data ?? []} />
      <CursorPaginator
        hasMore={query.data?.has_more ?? false}
        onNext={() => setCursorStack((s) => [...s, query.data?.next_cursor ?? undefined])}
        onPrev={cursorStack.length > 1 ? () => setCursorStack((s) => s.slice(0, -1)) : undefined}
        pageSize={pageSize}
        onPageSizeChange={(n) => {
          setPageSize(n);
          setCursorStack([undefined]);
        }}
        totalCount={query.data?.totalCount}
      />
    </div>
  );
}
