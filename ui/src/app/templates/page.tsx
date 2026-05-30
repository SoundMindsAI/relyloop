// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';
import { Suspense, useState } from 'react';

import { CreateTemplateModal } from '@/components/templates/create-template-modal';
import { TemplatesTable } from '@/components/templates/templates-table';
import { templatesColumns } from '@/components/templates/templates-table.column-config';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { useDataTableUrlState } from '@/hooks/use-data-table-url-state';
import { useTemplates } from '@/lib/api/query-templates';

function TemplatesPageInner() {
  const urlState = useDataTableUrlState('templates', templatesColumns, { defaultPageSize: 50 });
  const [createOpen, setCreateOpen] = useState(false);

  const query = useTemplates({
    engine_type: urlState.filters['engine_type'] ?? undefined,
    q: urlState.q ?? undefined,
    sort: urlState.sort ?? undefined,
    cursor: urlState.cursor ?? undefined,
    limit: urlState.pageSize,
  });

  return (
    <main className="mx-auto max-w-7xl space-y-6 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Query Templates</h1>
        <Button onClick={() => setCreateOpen(true)}>Create template</Button>
      </div>
      <Card>
        <CardContent className="pt-6">
          <TemplatesTable
            rows={query.data?.data ?? []}
            totalCount={query.data?.totalCount}
            has_more={query.data?.has_more ?? false}
            next_cursor={query.data?.next_cursor ?? null}
            isLoading={query.isPending}
            isError={query.isError}
            urlState={urlState}
          />
        </CardContent>
      </Card>
      <CreateTemplateModal open={createOpen} onOpenChange={setCreateOpen} />
    </main>
  );
}

export default function TemplatesPage() {
  return (
    <Suspense fallback={<main className="mx-auto max-w-7xl p-6">Loading…</main>}>
      <TemplatesPageInner />
    </Suspense>
  );
}
