'use client';

import Link from 'next/link';
import { useMemo } from 'react';

import { InfoTooltip } from '@/components/common/info-tooltip';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useClusterTargets } from '@/lib/api/clusters';
import { isApiError } from '@/lib/api-errors';

export interface ClusterDetailIndicesCardProps {
  clusterId: string;
}

/**
 * Indices card for the cluster-detail page (feat_index_document_browser FR-6 / AC-1).
 *
 * Reuses the existing `useClusterTargets(clusterId)` TanStack hook (the same
 * hook the create-study modal uses). Renders one row per index with name +
 * formatted doc_count; each row links to `/clusters/[id]/indices/[name]`.
 *
 * Error states map the standard backend envelope codes to inline copy
 * (Cap A patterns):
 *  - TARGETS_FORBIDDEN → ACL hint linking to the cluster-registration runbook.
 *  - CLUSTER_UNREACHABLE → retry button calling `refetch()`.
 *
 * Sort: indices are sorted by `name` ascending (`String.localeCompare`) so the
 * order is deterministic regardless of how the engine returns them.
 */
export function ClusterDetailIndicesCard({ clusterId }: ClusterDetailIndicesCardProps) {
  const query = useClusterTargets(clusterId);
  const sortedRows = useMemo(() => {
    const rows = query.data?.data ?? [];
    return [...rows].sort((a, b) => a.name.localeCompare(b.name));
  }, [query.data]);

  const renderBody = () => {
    if (query.isLoading) {
      return <p className="text-sm text-muted-foreground">Loading indices…</p>;
    }

    if (query.isError) {
      const err = query.error;
      const code = isApiError(err) ? err.errorCode : null;
      if (code === 'TARGETS_FORBIDDEN') {
        return (
          <div
            data-testid="indices-card-forbidden"
            className="space-y-2 rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"
          >
            <p>
              Cluster credentials don&apos;t allow listing indices. Register a key with the
              <code className="mx-1">monitor</code>privilege.
            </p>
            <p className="text-xs">
              See <span className="font-mono">docs/03_runbooks/cluster-registration.md</span>
              for the required Elasticsearch / OpenSearch role.
            </p>
          </div>
        );
      }
      if (code === 'CLUSTER_UNREACHABLE') {
        return (
          <div data-testid="indices-card-unreachable" className="space-y-2 text-sm">
            <p className="text-muted-foreground">
              Cluster did not respond. The cluster may be restarting or unreachable.
            </p>
            <Button
              size="sm"
              variant="outline"
              onClick={() => query.refetch()}
              data-testid="indices-card-retry"
            >
              Retry
            </Button>
          </div>
        );
      }
      return (
        <div className="text-sm text-destructive" data-testid="indices-card-error">
          Failed to load indices: {err instanceof Error ? err.message : 'unknown error'}
        </div>
      );
    }

    if (sortedRows.length === 0) {
      return (
        <p className="text-sm text-muted-foreground" data-testid="indices-card-empty">
          No indices found on this cluster. Register at least one index in your engine to begin
          tuning.
        </p>
      );
    }

    return (
      <div
        className="overflow-hidden rounded border border-border"
        data-testid="indices-card-table"
      >
        <table className="w-full text-sm">
          <thead className="bg-muted/40 text-left text-xs uppercase text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium">Name</th>
              <th className="px-3 py-2 font-medium">
                <span className="inline-flex items-center gap-1">
                  Documents
                  <InfoTooltip glossaryKey="cluster.target_doc_count" />
                </span>
              </th>
            </tr>
          </thead>
          <tbody>
            {sortedRows.map((row) => (
              <tr
                key={row.name}
                className="border-t border-border hover:bg-muted/30"
                data-testid={`indices-card-row-${row.name}`}
              >
                <td className="px-3 py-2 font-mono text-xs">
                  <Link
                    href={`/clusters/${encodeURIComponent(clusterId)}/indices/${encodeURIComponent(row.name)}`}
                    className="text-blue-600 underline-offset-4 hover:underline"
                  >
                    {row.name}
                  </Link>
                </td>
                <td className="px-3 py-2 tabular-nums">
                  {row.doc_count != null ? (
                    row.doc_count.toLocaleString()
                  ) : (
                    <span className="text-muted-foreground">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <span>Indices</span>
          <InfoTooltip glossaryKey="cluster.indices_card" />
        </CardTitle>
      </CardHeader>
      <CardContent>{renderBody()}</CardContent>
    </Card>
  );
}
