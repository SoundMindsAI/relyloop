'use client';
import { StatusBadge } from '@/components/common/status-badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { ClusterDetail } from '@/lib/api/clusters';

export interface ClusterDetailSummaryProps {
  cluster: ClusterDetail;
}

export function ClusterDetailSummary({ cluster }: ClusterDetailSummaryProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-3 text-base">
          <span>{cluster.name}</span>
          <StatusBadge kind="health" value={cluster.health_check.status} />
        </CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm md:grid-cols-3">
          <div>
            <dt className="text-xs uppercase text-muted-foreground">Engine</dt>
            <dd>{cluster.engine_type}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase text-muted-foreground">Environment</dt>
            <dd>{cluster.environment}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase text-muted-foreground">Auth kind</dt>
            <dd>{cluster.auth_kind}</dd>
          </div>
          <div className="md:col-span-3">
            <dt className="text-xs uppercase text-muted-foreground">Base URL</dt>
            <dd className="font-mono text-xs">{cluster.base_url}</dd>
          </div>
          {cluster.health_check.version && (
            <div>
              <dt className="text-xs uppercase text-muted-foreground">Version</dt>
              <dd>{cluster.health_check.version}</dd>
            </div>
          )}
          {cluster.health_check.error && (
            <div className="md:col-span-3">
              <dt className="text-xs uppercase text-muted-foreground">Health error</dt>
              <dd className="text-sm text-destructive">{cluster.health_check.error}</dd>
            </div>
          )}
          {cluster.notes && (
            <div className="md:col-span-3">
              <dt className="text-xs uppercase text-muted-foreground">Notes</dt>
              <dd>{cluster.notes}</dd>
            </div>
          )}
        </dl>
      </CardContent>
    </Card>
  );
}
