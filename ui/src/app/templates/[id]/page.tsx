// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';
import Link from 'next/link';
import { use, useState } from 'react';

import { DetailPageShell } from '@/components/common/detail-page-shell';
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
      <DetailPageShell query={query} entityLabel="template" notFoundErrorCode="TEMPLATE_NOT_FOUND">
        {(template) => (
          <>
            <div className="flex items-center justify-between">
              <div>
                <h1 className="text-2xl font-semibold tracking-tight">{template.name}</h1>
                <p className="text-sm text-muted-foreground">
                  {template.engine_type} · v{template.version}
                  {template.parent_id && ' · forked'}
                </p>
              </div>
              <Button onClick={() => setForkOpen(true)} data-testid="open-fork-modal">
                Fork to v{template.version + 1}
              </Button>
            </div>
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Template (read-only)</CardTitle>
              </CardHeader>
              <CardContent>
                <TemplateDetailView template={template} />
              </CardContent>
            </Card>
            <ForkTemplateModal open={forkOpen} onOpenChange={setForkOpen} parent={template} />
          </>
        )}
      </DetailPageShell>
    </main>
  );
}
