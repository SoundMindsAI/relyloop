'use client';
import Link from 'next/link';
import { use } from 'react';

import { EmptyState } from '@/components/common/empty-state';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ClusterDetailSummary } from '@/components/clusters/cluster-detail-summary';
import { StudiesByClusterTable } from '@/components/clusters/studies-by-cluster-table';
import { useCluster } from '@/lib/api/clusters';

interface RouteProps {
  params: Promise<{ id: string }>;
}

export function ClusterDetailView({ clusterId }: { clusterId: string }) {
  const query = useCluster(clusterId);

  return (
    <main className="mx-auto max-w-7xl space-y-6 p-6">
      <div>
        <Link href="/clusters" className="text-sm text-blue-600 underline-offset-4 hover:underline">
          ← All clusters
        </Link>
      </div>
      {query.isPending ? (
        <Card>
          <CardContent>
            <p className="py-12 text-center text-sm text-muted-foreground">Loading…</p>
          </CardContent>
        </Card>
      ) : query.isError ? (
        <EmptyState title="Cluster not found" message="The cluster may have been deleted." />
      ) : query.data ? (
        <>
          <ClusterDetailSummary cluster={query.data} />
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Studies using this cluster</CardTitle>
            </CardHeader>
            <CardContent>
              <StudiesByClusterTable clusterId={query.data.id} />
            </CardContent>
          </Card>
        </>
      ) : null}
    </main>
  );
}

export default function ClusterDetailPage({ params }: RouteProps) {
  const { id } = use(params);
  return <ClusterDetailView clusterId={id} />;
}
