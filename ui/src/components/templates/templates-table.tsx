'use client';
import Link from 'next/link';

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type { QueryTemplateSummary } from '@/lib/api/query-templates';

export interface TemplatesTableProps {
  rows: readonly QueryTemplateSummary[];
}

export function TemplatesTable({ rows }: TemplatesTableProps) {
  if (rows.length === 0) {
    return (
      <p className="py-12 text-center text-sm text-muted-foreground" data-testid="templates-empty">
        No templates yet — click &ldquo;Create template&rdquo; to add one.
      </p>
    );
  }
  return (
    <Table data-testid="templates-table">
      <TableHeader>
        <TableRow>
          <TableHead>Name</TableHead>
          <TableHead>Engine</TableHead>
          <TableHead>Version</TableHead>
          <TableHead>Created</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((t) => (
          <TableRow key={t.id} data-testid={`template-row-${t.id}`}>
            <TableCell>
              <Link
                href={`/templates/${t.id}`}
                className="text-blue-600 underline-offset-4 hover:underline"
              >
                {t.name}
              </Link>
            </TableCell>
            <TableCell>{t.engine_type}</TableCell>
            <TableCell>v{t.version}</TableCell>
            <TableCell className="whitespace-nowrap">
              {new Date(t.created_at).toLocaleString()}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
