'use client';
import { Suspense, useState } from 'react';

import { ClustersTable } from '@/components/clusters/clusters-table';
import { clustersColumns } from '@/components/clusters/clusters-table.column-config';
import { RegisterClusterModal } from '@/components/clusters/register-cluster-modal';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { useDataTableUrlState } from '@/hooks/use-data-table-url-state';
import { useClusters } from '@/lib/api/clusters';

function ClustersPageInner() {
  const urlState = useDataTableUrlState('clusters', clustersColumns, { defaultPageSize: 50 });
  const [registerOpen, setRegisterOpen] = useState(false);

  const query = useClusters({
    engine_type: urlState.filters['engine_type'] ?? undefined,
    environment: urlState.filters['environment'] ?? undefined,
    q: urlState.q ?? undefined,
    sort: urlState.sort ?? undefined,
    cursor: urlState.cursor ?? undefined,
    limit: urlState.pageSize,
  });

  return (
    <main className="mx-auto max-w-7xl space-y-6 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Clusters</h1>
        <Button onClick={() => setRegisterOpen(true)} data-testid="open-register-cluster">
          Register cluster
        </Button>
      </div>
      <Card>
        <CardContent className="pt-6">
          <ClustersTable
            rows={query.data?.data ?? []}
            totalCount={query.data?.totalCount}
            has_more={query.data?.has_more ?? false}
            next_cursor={query.data?.next_cursor ?? null}
            isLoading={query.isPending}
            isError={query.isError}
            urlState={urlState}
            onRegisterCluster={() => setRegisterOpen(true)}
          />
        </CardContent>
      </Card>
      <RegisterClusterModal open={registerOpen} onOpenChange={setRegisterOpen} />
    </main>
  );
}

export default function ClustersPage() {
  return (
    <Suspense fallback={<main className="mx-auto max-w-7xl p-6">Loading…</main>}>
      <ClustersPageInner />
    </Suspense>
  );
}
