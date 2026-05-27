'use client';

import { Check, Copy } from 'lucide-react';
import Link from 'next/link';
import { use, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useTargetDocument } from '@/lib/api/documents';
import { isApiError } from '@/lib/api-errors';

interface RouteProps {
  params: Promise<{ id: string; name: string; doc_id: string[] }>;
}

/**
 * Document detail page (feat_index_document_browser Story 3.4 / FR-9).
 *
 * Catch-all route: ``[...doc_id]`` accepts any number of segments. Next.js
 * URL-decodes route params once before delivering them to React, so
 * ``params.doc_id.join('/')`` is the literal operator-supplied _id (no
 * extra ``decodeURIComponent``). The useTargetDocument hook re-encodes
 * the doc_id for the API URL.
 *
 * Renders the full _source as pretty-printed JSON with a copy-to-clipboard
 * button. Handles `source: null` (AC-18) and `DOCUMENT_NOT_FOUND` (AC-9).
 */
export function DocumentDetailView({
  clusterId,
  indexName,
  docId,
}: {
  clusterId: string;
  indexName: string;
  docId: string;
}) {
  const query = useTargetDocument(clusterId, indexName, docId);
  const [copied, setCopied] = useState(false);
  const errCode = isApiError(query.error) ? query.error.errorCode : null;

  function copy() {
    if (!query.data?.source) return;
    const json = JSON.stringify(query.data.source, null, 2);
    void navigator.clipboard.writeText(json).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }

  const breadcrumb = (
    <nav className="flex flex-wrap items-center gap-1 text-sm">
      <Link
        href={`/clusters/${encodeURIComponent(clusterId)}`}
        className="text-blue-600 underline-offset-4 hover:underline"
      >
        Cluster
      </Link>
      <span className="text-muted-foreground">›</span>
      <Link
        href={`/clusters/${encodeURIComponent(clusterId)}/indices/${encodeURIComponent(indexName)}`}
        className="text-blue-600 underline-offset-4 hover:underline"
      >
        <span className="font-mono">{indexName}</span>
      </Link>
      <span className="text-muted-foreground">›</span>
      <Link
        href={`/clusters/${encodeURIComponent(clusterId)}/indices/${encodeURIComponent(indexName)}/documents`}
        className="text-blue-600 underline-offset-4 hover:underline"
      >
        Documents
      </Link>
      <span className="text-muted-foreground">›</span>
      <span className="font-mono text-muted-foreground" data-testid="document-detail-doc-id">
        {docId}
      </span>
    </nav>
  );

  if (errCode === 'DOCUMENT_NOT_FOUND') {
    return (
      <main className="mx-auto max-w-7xl space-y-4 p-6" data-testid="document-detail-not-found">
        {breadcrumb}
        <Card>
          <CardContent className="space-y-2 p-6 text-sm">
            <p>
              Document <code className="font-mono">{docId}</code> does not exist in
              <span className="font-mono"> {indexName}</span>.
            </p>
            <p className="text-muted-foreground">
              It may have been deleted between the list view and this click.
            </p>
          </CardContent>
        </Card>
      </main>
    );
  }

  if (errCode === 'TARGETS_FORBIDDEN') {
    return (
      <main className="mx-auto max-w-7xl space-y-4 p-6" data-testid="document-detail-forbidden">
        {breadcrumb}
        <Card>
          <CardContent className="space-y-2 p-6 text-sm">
            <p>Cluster credentials don&apos;t allow fetching documents.</p>
            <p className="text-muted-foreground">
              See <span className="font-mono">docs/03_runbooks/cluster-registration.md</span>
              for the required role.
            </p>
          </CardContent>
        </Card>
      </main>
    );
  }

  if (errCode === 'CLUSTER_UNREACHABLE' || errCode === 'TARGET_NOT_FOUND') {
    return (
      <main className="mx-auto max-w-7xl space-y-4 p-6" data-testid="document-detail-unreachable">
        {breadcrumb}
        <p className="text-sm">
          {errCode === 'CLUSTER_UNREACHABLE'
            ? 'Cluster did not respond.'
            : `Index ${indexName} does not exist on this cluster.`}
        </p>
        {errCode === 'CLUSTER_UNREACHABLE' && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => query.refetch()}
            data-testid="document-detail-retry"
          >
            Retry
          </Button>
        )}
      </main>
    );
  }

  if (query.isLoading || !query.data) {
    return (
      <main className="mx-auto max-w-7xl space-y-4 p-6">
        {breadcrumb}
        <p className="text-sm text-muted-foreground">Loading…</p>
      </main>
    );
  }

  const { source } = query.data;

  return (
    <main className="mx-auto max-w-7xl space-y-4 p-6">
      {breadcrumb}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between text-base">
            <span className="font-mono text-sm">{docId}</span>
            {source != null && (
              <Button size="sm" variant="outline" onClick={copy} data-testid="document-detail-copy">
                {copied ? (
                  <>
                    <Check className="mr-1 h-3.5 w-3.5" /> Copied
                  </>
                ) : (
                  <>
                    <Copy className="mr-1 h-3.5 w-3.5" /> Copy JSON
                  </>
                )}
              </Button>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {source == null ? (
            <p
              className="rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"
              data-testid="document-detail-source-null"
            >
              This document has <code>_source: false</code> configured — only the
              <code className="mx-1">_id</code>is retrievable.
            </p>
          ) : (
            <pre
              className="max-h-[60vh] overflow-auto rounded border border-border bg-muted/30 p-3 text-xs"
              data-testid="document-detail-json"
            >
              {JSON.stringify(source, null, 2)}
            </pre>
          )}
        </CardContent>
      </Card>
    </main>
  );
}

export default function DocumentDetailPage({ params }: RouteProps) {
  const { id, name, doc_id } = use(params);
  // Catch-all route: Next.js URL-decodes route params once before delivering
  // them, so joining the segments yields the literal operator-supplied _id
  // (no extra decodeURIComponent needed — cycle-2 F5).
  const docId = doc_id.join('/');
  return <DocumentDetailView clusterId={id} indexName={name} docId={docId} />;
}
