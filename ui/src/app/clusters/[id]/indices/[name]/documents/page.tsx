// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

import Link from 'next/link';
import { use, useState } from 'react';

import { InfoTooltip } from '@/components/common/info-tooltip';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useTargetDocuments } from '@/lib/api/documents';
import type { DocumentSummary } from '@/lib/api/documents';
import { isApiError } from '@/lib/api-errors';
import { DOCUMENT_FIELD_TRUNCATED } from '@/lib/documents-constants';

interface RouteProps {
  params: Promise<{ id: string; name: string }>;
}

const PAGE_SIZES = [25, 50, 100] as const;

function renderPreview(source: DocumentSummary['source']) {
  if (source == null) {
    return <span className="text-muted-foreground">_source: false</span>;
  }
  const entries = Object.entries(source).slice(0, 3);
  return (
    <div className="space-y-0.5 font-mono text-xs">
      {entries.map(([key, value]) => (
        <div key={key} className="truncate">
          <span className="text-muted-foreground">{key}=</span>
          {value === DOCUMENT_FIELD_TRUNCATED ? (
            <span className="inline-flex items-center gap-1">
              <span className="italic text-amber-700">{String(value)}</span>
              <InfoTooltip glossaryKey="document.truncation_sentinel" />
            </span>
          ) : (
            <span>{JSON.stringify(value)}</span>
          )}
        </div>
      ))}
      {Object.keys(source).length > 3 && (
        <div className="text-xs text-muted-foreground">
          + {Object.keys(source).length - 3} more field
          {Object.keys(source).length - 3 > 1 ? 's' : ''}
        </div>
      )}
    </div>
  );
}

export function DocumentsListView({
  clusterId,
  indexName,
}: {
  clusterId: string;
  indexName: string;
}) {
  const [cursor, setCursor] = useState<string | null>(null);
  const [limit, setLimit] = useState<number>(25);
  const [cursorStack, setCursorStack] = useState<(string | null)[]>([null]);

  const query = useTargetDocuments(clusterId, indexName, { cursor, limit });
  const errCode = isApiError(query.error) ? query.error.errorCode : null;
  const rows: DocumentSummary[] = query.data?.data.data ?? [];
  const hasMore = query.data?.data.has_more ?? false;
  const nextCursor = query.data?.data.next_cursor ?? null;
  const totalCount = query.data?.totalCount ?? null;

  function goNext() {
    if (!hasMore || !nextCursor) return;
    setCursorStack((prev) => [...prev, nextCursor]);
    setCursor(nextCursor);
  }
  function goPrev() {
    if (cursorStack.length <= 1) return;
    const next = cursorStack.slice(0, -1);
    setCursorStack(next);
    setCursor(next[next.length - 1] ?? null);
  }
  function changePageSize(n: number) {
    setLimit(n);
    setCursor(null);
    setCursorStack([null]);
  }

  if (errCode === 'TARGETS_FORBIDDEN') {
    return (
      <main className="mx-auto max-w-7xl space-y-4 p-6" data-testid="documents-list-forbidden">
        <Link
          href={`/clusters/${encodeURIComponent(clusterId)}/indices/${encodeURIComponent(indexName)}`}
          className="text-sm text-blue-600 underline-offset-4 hover:underline"
        >
          ← Back to index summary
        </Link>
        <Card>
          <CardContent className="space-y-2 p-6 text-sm">
            <p>Cluster credentials don&apos;t allow listing documents.</p>
            <p className="text-muted-foreground">
              See <span className="font-mono">docs/03_runbooks/cluster-registration.md</span>
              for the required role.
            </p>
          </CardContent>
        </Card>
      </main>
    );
  }

  if (errCode === 'TARGET_NOT_FOUND') {
    return (
      <main className="mx-auto max-w-7xl space-y-4 p-6" data-testid="documents-list-not-found">
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
          </CardContent>
        </Card>
      </main>
    );
  }

  if (errCode === 'CLUSTER_UNREACHABLE' || errCode === 'VALIDATION_ERROR') {
    return (
      <main className="mx-auto max-w-7xl space-y-4 p-6" data-testid="documents-list-unreachable">
        <p className="text-sm">
          {errCode === 'CLUSTER_UNREACHABLE'
            ? 'Cluster did not respond.'
            : 'Request validation failed.'}
        </p>
        <Button
          size="sm"
          variant="outline"
          onClick={() => query.refetch()}
          data-testid="documents-list-retry"
        >
          Retry
        </Button>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-7xl space-y-4 p-6">
      <div className="flex items-center justify-between">
        <Link
          href={`/clusters/${encodeURIComponent(clusterId)}/indices/${encodeURIComponent(indexName)}`}
          className="text-sm text-blue-600 underline-offset-4 hover:underline"
        >
          ← <span className="font-mono">{indexName}</span>
        </Link>
        {totalCount != null && (
          <span className="text-sm text-muted-foreground" data-testid="documents-list-total-count">
            {totalCount.toLocaleString()} documents
          </span>
        )}
      </div>
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Documents</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {query.isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
          {!query.isLoading && rows.length === 0 && (
            <p className="text-sm text-muted-foreground" data-testid="documents-list-empty">
              No documents in this index.
            </p>
          )}
          {rows.length > 0 && (
            <div
              className="overflow-hidden rounded border border-border"
              data-testid="documents-list-table"
            >
              <table className="w-full text-sm">
                <thead className="bg-muted/40 text-left text-xs uppercase text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2 font-medium">_id</th>
                    <th className="px-3 py-2 font-medium">Preview</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr
                      key={row.doc_id}
                      className="border-t border-border hover:bg-muted/30"
                      data-testid={`documents-row-${row.doc_id}`}
                    >
                      <td className="w-1/3 px-3 py-2 font-mono text-xs">
                        <Link
                          href={`/clusters/${encodeURIComponent(clusterId)}/indices/${encodeURIComponent(indexName)}/documents/${encodeURIComponent(row.doc_id)}`}
                          className="text-blue-600 underline-offset-4 hover:underline"
                        >
                          {row.doc_id}
                        </Link>
                      </td>
                      <td className="px-3 py-2">{renderPreview(row.source)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
            <label className="inline-flex items-center gap-2 text-xs text-muted-foreground">
              Page size
              <select
                className="rounded border border-border bg-background px-2 py-1 text-xs"
                value={limit}
                onChange={(e) => changePageSize(parseInt(e.target.value, 10))}
                data-testid="documents-list-page-size"
              >
                {PAGE_SIZES.map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={goPrev}
                disabled={cursorStack.length <= 1}
                data-testid="documents-list-prev"
              >
                ← Prev
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={goNext}
                disabled={!hasMore}
                data-testid="documents-list-next"
              >
                Next →
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </main>
  );
}

export default function DocumentsListPage({ params }: RouteProps) {
  const { id, name } = use(params);
  return <DocumentsListView clusterId={id} indexName={name} />;
}
