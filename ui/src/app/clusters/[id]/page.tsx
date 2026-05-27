'use client';
import Link from 'next/link';
import { use } from 'react';

import { DetailPageShell } from '@/components/common/detail-page-shell';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ClusterActionBar } from '@/components/clusters/cluster-action-bar';
import { ClusterDetailIndicesCard } from '@/components/clusters/cluster-detail-indices-card';
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
      <DetailPageShell query={query} entityLabel="cluster" notFoundErrorCode="CLUSTER_NOT_FOUND">
        {(cluster) => (
          <>
            <ClusterDetailSummary cluster={cluster} />
            <ClusterActionBar cluster={cluster} />
            <ClusterDetailIndicesCard clusterId={cluster.id} />
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Studies using this cluster</CardTitle>
              </CardHeader>
              <CardContent>
                <StudiesByClusterTable clusterId={cluster.id} />
              </CardContent>
            </Card>
          </>
        )}
      </DetailPageShell>
    </main>
  );
}

export default function ClusterDetailPage({ params }: RouteProps) {
  const { id } = use(params);
  return <ClusterDetailView clusterId={id} />;
}
