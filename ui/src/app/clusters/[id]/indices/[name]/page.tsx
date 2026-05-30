// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

import Link from 'next/link';
import { use } from 'react';

import { IndexSummarySchemaTable } from '@/components/clusters/index-summary-schema-table';
import { InfoTooltip } from '@/components/common/info-tooltip';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useCluster, useClusterSchema, useClusterTargets } from '@/lib/api/clusters';
import { isApiError } from '@/lib/api-errors';

interface RouteProps {
  params: Promise<{ id: string; name: string }>;
}

/**
 * Index summary page (feat_index_document_browser Story 3.2 / FR-7 / AC-2).
 *
 * Composes the existing `/targets` + `/schema` endpoints — no new endpoint.
 * Renders:
 *  - Page header: <index name> · <formatted doc_count> · <engine type chip>
 *  - Two nav cards (browse documents, view studies targeting this index)
 *  - Schema table
 *
 * Error states:
 *  - 404 TARGET_NOT_FOUND (from /schema) → AC-17 empty-state with breadcrumb.
 *  - 403 TARGETS_FORBIDDEN on /targets but /schema 200 → D-28 partial-permission
 *    state (doc_count: unknown).
 *  - 403 on BOTH → cycle-2 F8 full-denial state.
 */
export function IndexSummaryView({
  clusterId,
  indexName,
}: {
  clusterId: string;
  indexName: string;
}) {
  const clusterQuery = useCluster(clusterId);
  const targetsQuery = useClusterTargets(clusterId);
  const schemaQuery = useClusterSchema(clusterId, indexName);

  const cluster = clusterQuery.data;
  const target = targetsQuery.data?.data.find((t) => t.name === indexName);
  const schema = schemaQuery.data;

  const schemaErrCode = isApiError(schemaQuery.error) ? schemaQuery.error.errorCode : null;
  const targetsErrCode = isApiError(targetsQuery.error) ? targetsQuery.error.errorCode : null;

  // 404 TARGET_NOT_FOUND on schema → empty state (AC-17).
  if (schemaErrCode === 'TARGET_NOT_FOUND') {
    return (
      <main className="mx-auto max-w-7xl space-y-4 p-6" data-testid="index-summary-not-found">
        <Link
          href={`/clusters/${encodeURIComponent(clusterId)}`}
          className="text-sm text-blue-600 underline-offset-4 hover:underline"
        >
          ← Back to cluster
        </Link>
        <Card>
          <CardContent className="space-y-2 p-6 text-sm">
            <p>
              Index <code className="font-mono">{indexName}</code> does not exist on this cluster.
            </p>
            <p className="text-muted-foreground">
              It may have been deleted or renamed. Return to the cluster page to see the current
              list.
            </p>
          </CardContent>
        </Card>
      </main>
    );
  }

  // Full denial — both endpoints 403 (cycle-2 F8).
  if (targetsErrCode === 'TARGETS_FORBIDDEN' && schemaErrCode === 'TARGETS_FORBIDDEN') {
    return (
      <main className="mx-auto max-w-7xl space-y-4 p-6" data-testid="index-summary-fully-denied">
        <Link
          href={`/clusters/${encodeURIComponent(clusterId)}`}
          className="text-sm text-blue-600 underline-offset-4 hover:underline"
        >
          ← Back to cluster
        </Link>
        <Card>
          <CardContent className="space-y-2 p-6 text-sm">
            <p>Cluster credentials don&apos;t allow inspecting this index.</p>
            <p className="text-muted-foreground">
              See <span className="font-mono">docs/03_runbooks/cluster-registration.md</span>
              for the required role.
            </p>
          </CardContent>
        </Card>
      </main>
    );
  }

  // Standard error fallthrough.
  if (schemaErrCode && schemaErrCode !== 'TARGETS_FORBIDDEN') {
    return (
      <main className="mx-auto max-w-7xl space-y-4 p-6" data-testid="index-summary-error">
        <p className="text-sm text-destructive">Failed to load schema: {String(schemaErrCode)}</p>
      </main>
    );
  }

  if (schemaQuery.isLoading || !schema) {
    return (
      <main className="mx-auto max-w-7xl p-6">
        <p className="text-sm text-muted-foreground">Loading…</p>
      </main>
    );
  }

  const docCountUnknown = targetsErrCode === 'TARGETS_FORBIDDEN' || !target;

  return (
    <main className="mx-auto max-w-7xl space-y-6 p-6">
      <Link
        href={`/clusters/${encodeURIComponent(clusterId)}`}
        className="text-sm text-blue-600 underline-offset-4 hover:underline"
      >
        ← {cluster?.name ?? 'Back to cluster'}
      </Link>

      <Card data-testid="index-summary-header">
        <CardHeader>
          <CardTitle className="flex flex-wrap items-center gap-3 text-base">
            <span className="font-mono">{indexName}</span>
            <span className="text-muted-foreground">·</span>
            {docCountUnknown || target.doc_count == null ? (
              <span className="italic text-muted-foreground">document count unknown</span>
            ) : (
              <span className="text-muted-foreground">
                {target.doc_count.toLocaleString()} documents
              </span>
            )}
            {cluster && (
              <>
                <span className="text-muted-foreground">·</span>
                <span className="rounded bg-muted px-2 py-0.5 text-xs">{cluster.engine_type}</span>
              </>
            )}
          </CardTitle>
        </CardHeader>
      </Card>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Link
          href={`/clusters/${encodeURIComponent(clusterId)}/indices/${encodeURIComponent(indexName)}/documents`}
          data-testid="index-summary-browse-link"
        >
          <Card className="cursor-pointer transition-shadow hover:shadow">
            <CardHeader>
              <CardTitle className="text-sm">Browse documents →</CardTitle>
            </CardHeader>
            <CardContent className="pt-0 text-xs text-muted-foreground">
              Paginate through the documents in this index. View truncated previews; open any
              document for the full JSON.
            </CardContent>
          </Card>
        </Link>
        <Link
          href={`/studies?cluster_id=${encodeURIComponent(clusterId)}&target=${encodeURIComponent(indexName)}`}
          data-testid="index-summary-studies-link"
        >
          <Card className="cursor-pointer transition-shadow hover:shadow">
            <CardHeader>
              <CardTitle className="text-sm">View studies targeting this index →</CardTitle>
            </CardHeader>
            <CardContent className="pt-0 text-xs text-muted-foreground">
              See every study scoped to this index, plus its current best metric and proposal
              status.
            </CardContent>
          </Card>
        </Link>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <span>Schema</span>
            <InfoTooltip glossaryKey="target.schema" />
            <span
              className="ml-auto text-xs font-normal text-muted-foreground"
              data-testid="index-summary-field-count"
            >
              {schema.fields.length} fields
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <IndexSummarySchemaTable schema={schema} />
        </CardContent>
      </Card>

      <div className="flex justify-end">
        <Button asChild variant="ghost" size="sm">
          <Link href={`/clusters/${encodeURIComponent(clusterId)}`}>← Cluster detail</Link>
        </Button>
      </div>
    </main>
  );
}

export default function IndexSummaryPage({ params }: RouteProps) {
  const { id, name } = use(params);
  return <IndexSummaryView clusterId={id} indexName={name} />;
}
