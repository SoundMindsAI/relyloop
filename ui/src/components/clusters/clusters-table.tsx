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
import type { ClusterSummary } from '@/lib/api/clusters';

export interface ClustersTableProps {
  rows: readonly ClusterSummary[];
}

export function ClustersTable({ rows }: ClustersTableProps) {
  if (rows.length === 0) {
    return (
      <p className="py-12 text-center text-sm text-muted-foreground" data-testid="clusters-empty">
        No clusters registered. Click &ldquo;Register cluster&rdquo; to add one.
      </p>
    );
  }
  return (
    <Table data-testid="clusters-table">
      <TableHeader>
        <TableRow>
          <TableHead>Name</TableHead>
          <TableHead>Engine</TableHead>
          <TableHead>Environment</TableHead>
          <TableHead>Health</TableHead>
          <TableHead>Base URL</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((c) => (
          <TableRow key={c.id} data-testid={`cluster-row-${c.id}`}>
            <TableCell>
              <Link
                href={`/clusters/${c.id}`}
                className="text-blue-600 underline-offset-4 hover:underline"
              >
                {c.name}
              </Link>
            </TableCell>
            <TableCell>{c.engine_type}</TableCell>
            <TableCell>{c.environment}</TableCell>
            <TableCell>
              <StatusBadge kind="health" value={c.health_check.status} />
            </TableCell>
            <TableCell className="font-mono text-xs">{c.base_url}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
