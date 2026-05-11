'use client';
import Link from 'next/link';
import { use, useState } from 'react';

import { EmptyState } from '@/components/common/empty-state';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { TemplateDetailView } from '@/components/templates/template-detail-view';
import { ForkTemplateModal } from '@/components/templates/fork-template-modal';
import { useTemplate } from '@/lib/api/query-templates';

interface RouteProps {
  params: Promise<{ id: string }>;
}

export default function TemplateDetailPage({ params }: RouteProps) {
  const { id } = use(params);
  const [forkOpen, setForkOpen] = useState(false);
  const query = useTemplate(id);

  return (
    <main className="mx-auto max-w-7xl space-y-6 p-6">
      <div>
        <Link
          href="/templates"
          className="text-sm text-blue-600 underline-offset-4 hover:underline"
        >
          ← All templates
        </Link>
      </div>
      {query.isPending ? (
        <Card>
          <CardContent>
            <p className="py-12 text-center text-sm text-muted-foreground">Loading…</p>
          </CardContent>
        </Card>
      ) : query.isError ? (
        <EmptyState title="Template not found" message="The template may have been removed." />
      ) : query.data ? (
        <>
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight">{query.data.name}</h1>
              <p className="text-sm text-muted-foreground">
                {query.data.engine_type} · v{query.data.version}
                {query.data.parent_id && ' · forked'}
              </p>
            </div>
            <Button onClick={() => setForkOpen(true)} data-testid="open-fork-modal">
              Fork to v{query.data.version + 1}
            </Button>
          </div>
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Template (read-only)</CardTitle>
            </CardHeader>
            <CardContent>
              <TemplateDetailView template={query.data} />
            </CardContent>
          </Card>
          <ForkTemplateModal open={forkOpen} onOpenChange={setForkOpen} parent={query.data} />
        </>
      ) : null}
    </main>
  );
}
