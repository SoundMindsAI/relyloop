'use client';
import Link from 'next/link';
import { use, useState } from 'react';

import { EmptyState } from '@/components/common/empty-state';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { AddQueriesDialog } from '@/components/query-sets/add-queries-dialog';
import { AssociatedJudgmentLists } from '@/components/query-sets/associated-judgment-lists';
import { GenerateJudgmentsDialog } from '@/components/query-sets/generate-judgments-dialog';
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
      {query.isPending ? (
        <Card>
          <CardContent>
            <p className="py-12 text-center text-sm text-muted-foreground">Loading…</p>
          </CardContent>
        </Card>
      ) : query.isError ? (
        <EmptyState title="Query set not found" message="The query set may have been deleted." />
      ) : query.data ? (
        <>
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight">{query.data.name}</h1>
              <p className="text-sm text-muted-foreground">
                Cluster <span className="font-mono">{query.data.cluster_id}</span> ·{' '}
                {query.data.query_count.toLocaleString()} queries
              </p>
            </div>
            <Button onClick={() => setAddQueriesOpen(true)} data-testid="open-add-queries">
              Add queries
            </Button>
          </div>
          {query.data.description && (
            <Card>
              <CardContent className="pt-6">
                <p className="text-sm">{query.data.description}</p>
              </CardContent>
            </Card>
          )}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Queries</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">
                {query.data.query_count.toLocaleString()} queries in this set. Per-query inspection
                is deferred (see <code>chore_query_inline_edit_delete</code>) — use{' '}
                <strong>Add queries</strong> to bulk-upload JSON or CSV.
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Associated judgment lists</CardTitle>
            </CardHeader>
            <CardContent>
              <AssociatedJudgmentLists
                querySetId={query.data.id}
                onGenerateClick={() => setGenerateOpen(true)}
              />
            </CardContent>
          </Card>
          <AddQueriesDialog
            open={addQueriesOpen}
            onOpenChange={setAddQueriesOpen}
            querySetId={query.data.id}
          />
          <GenerateJudgmentsDialog
            open={generateOpen}
            onOpenChange={setGenerateOpen}
            clusterId={query.data.cluster_id}
            querySetId={query.data.id}
          />
        </>
      ) : null}
    </main>
  );
}

export default function QuerySetDetailPage({ params }: RouteProps) {
  const { id } = use(params);
  return <QuerySetDetailView querySetId={id} />;
}
