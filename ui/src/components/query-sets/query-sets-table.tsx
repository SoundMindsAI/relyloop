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
import type { QuerySetSummary } from '@/lib/api/query-sets';

export interface QuerySetsTableProps {
  rows: readonly QuerySetSummary[];
}

export function QuerySetsTable({ rows }: QuerySetsTableProps) {
  if (rows.length === 0) {
    return (
      <p className="py-12 text-center text-sm text-muted-foreground" data-testid="query-sets-empty">
        No query sets yet — click &ldquo;Create query set&rdquo; to add one.
      </p>
    );
  }
  return (
    <Table data-testid="query-sets-table">
      <TableHeader>
        <TableRow>
          <TableHead>Name</TableHead>
          <TableHead>Cluster</TableHead>
          <TableHead>Created</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((q) => (
          <TableRow key={q.id} data-testid={`query-set-row-${q.id}`}>
            <TableCell>
              <Link
                href={`/query-sets/${q.id}`}
                className="text-blue-600 underline-offset-4 hover:underline"
              >
                {q.name}
              </Link>
            </TableCell>
            <TableCell className="font-mono text-xs">{q.cluster_id}</TableCell>
            <TableCell className="whitespace-nowrap">
              {new Date(q.created_at).toLocaleString()}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
