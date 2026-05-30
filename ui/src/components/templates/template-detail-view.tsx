// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';
import { TemplateBodyEditor } from '@/components/templates/template-body-editor';
import type { QueryTemplateDetail } from '@/lib/api/query-templates';

export interface TemplateDetailViewProps {
  template: QueryTemplateDetail;
}

export function TemplateDetailView({ template }: TemplateDetailViewProps) {
  const params = Object.entries(template.declared_params ?? {});
  return (
    <div className="space-y-6">
      <section>
        <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Body
        </h3>
        <TemplateBodyEditor value={template.body} readOnly />
      </section>
      <section>
        <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Declared parameters
        </h3>
        {params.length === 0 ? (
          <p className="text-sm text-muted-foreground">No declared parameters.</p>
        ) : (
          <ul className="divide-y rounded-md border">
            {params.map(([name, type]) => (
              <li key={name} className="flex items-center justify-between px-3 py-2 text-sm">
                <code className="font-mono">{name}</code>
                <span className="text-muted-foreground">{type}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
