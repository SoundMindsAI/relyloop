// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';
import Link from 'next/link';
import { use, useState } from 'react';

import { DetailPageShell } from '@/components/common/detail-page-shell';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { AddQueriesDialog } from '@/components/query-sets/add-queries-dialog';
import { AssociatedJudgmentLists } from '@/components/query-sets/associated-judgment-lists';
import { GenerateJudgmentsDialog } from '@/components/query-sets/generate-judgments-dialog';
import { QueriesTable } from '@/components/query-sets/queries-table';
import { useQuerySet } from '@/lib/api/query-sets';

interface RouteProps {
  params: Promise<{ id: string }>;
}

export function QuerySetDetailView({ querySetId }: { querySetId: string }) {
  const query = useQuerySet(querySetId);
  const [addQueriesOpen, setAddQueriesOpen] = useState(false);
  const [generateOpen, setGenerateOpen] = useState(false);

  return (
    <main className="mx-auto max-w-7xl space-y-6 p-6">
      <div>
        <Link
          href="/query-sets"
          className="text-sm text-blue-600 underline-offset-4 hover:underline"
        >
          ← All query sets
        </Link>
      </div>
      <DetailPageShell
        query={query}
        entityLabel="query set"
        notFoundErrorCode="QUERY_SET_NOT_FOUND"
        documentTitle={(qs) => qs.name}
      >
        {(querySet) => (
          <>
            <div className="flex items-center justify-between">
              <div>
                <h1 className="text-2xl font-semibold tracking-tight">{querySet.name}</h1>
                <p className="text-sm text-muted-foreground">
                  Cluster{' '}
                  <Link
                    href={`/clusters/${querySet.cluster_id}`}
                    className="font-mono text-blue-600 underline-offset-4 hover:underline"
                  >
                    {querySet.cluster_id}
                  </Link>{' '}
                  · {querySet.query_count.toLocaleString()} queries
                </p>
              </div>
              <Button onClick={() => setAddQueriesOpen(true)} data-testid="open-add-queries">
                Add queries
              </Button>
            </div>
            {querySet.description && (
              <Card>
                <CardContent className="pt-6">
                  <p className="text-sm">{querySet.description}</p>
                </CardContent>
              </Card>
            )}
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Queries</CardTitle>
              </CardHeader>
              <CardContent>
                <QueriesTable querySetId={querySet.id} />
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Associated judgment lists</CardTitle>
              </CardHeader>
              <CardContent>
                <AssociatedJudgmentLists
                  querySetId={querySet.id}
                  onGenerateClick={() => setGenerateOpen(true)}
                />
              </CardContent>
            </Card>
            <AddQueriesDialog
              open={addQueriesOpen}
              onOpenChange={setAddQueriesOpen}
              querySetId={querySet.id}
            />
            <GenerateJudgmentsDialog
              open={generateOpen}
              onOpenChange={setGenerateOpen}
              clusterId={querySet.cluster_id}
              querySetId={querySet.id}
            />
          </>
        )}
      </DetailPageShell>
    </main>
  );
}

export default function QuerySetDetailPage({ params }: RouteProps) {
  const { id } = use(params);
  return <QuerySetDetailView querySetId={id} />;
}
