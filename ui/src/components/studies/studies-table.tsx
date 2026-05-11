'use client';
import Link from 'next/link';

import { StatusBadge } from '@/components/common/status-badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type { StudySummary } from '@/lib/api/studies';

export interface StudiesTableProps {
  rows: readonly StudySummary[];
}

export function StudiesTable({ rows }: StudiesTableProps) {
  if (rows.length === 0) {
    return (
      <p className="py-12 text-center text-sm text-muted-foreground" data-testid="studies-empty">
        No studies match the current filters.
      </p>
    );
  }
  return (
    <Table data-testid="studies-table">
      <TableHeader>
        <TableRow>
          <TableHead>Name</TableHead>
          <TableHead>Cluster</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Best metric</TableHead>
          <TableHead>Created</TableHead>
          <TableHead>Completed</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((s) => (
          <TableRow key={s.id} data-testid={`study-row-${s.id}`}>
            <TableCell>
              <Link
                href={`/studies/${s.id}`}
                className="text-blue-600 underline-offset-4 hover:underline"
              >
                {s.name}
              </Link>
            </TableCell>
            <TableCell className="font-mono text-xs">{s.cluster_id}</TableCell>
            <TableCell>
              <StatusBadge kind="study" value={s.status} />
            </TableCell>
            <TableCell>
              {s.best_metric != null ? (
                s.best_metric.toFixed(3)
              ) : (
                <span className="text-muted-foreground">—</span>
              )}
            </TableCell>
            <TableCell className="whitespace-nowrap">
              {new Date(s.created_at).toLocaleString()}
            </TableCell>
            <TableCell className="whitespace-nowrap">
              {s.completed_at ? (
                new Date(s.completed_at).toLocaleString()
              ) : (
                <span className="text-muted-foreground">—</span>
              )}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
