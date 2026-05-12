'use client';
import Link from 'next/link';

import { MetricDelta } from '@/components/common/metric-delta';
import { StatusBadge } from '@/components/common/status-badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type { ProposalSummary } from '@/lib/api/proposals';

export interface ProposalsTableProps {
  rows: readonly ProposalSummary[];
}

interface MetricDeltaShape {
  primary?: string;
  baseline?: number;
  best?: number;
  delta_pct?: number;
}

function parseMetricDelta(md: ProposalSummary['metric_delta']): MetricDeltaShape | null {
  if (!md || typeof md !== 'object') return null;
  return md as MetricDeltaShape;
}

export function ProposalsTable({ rows }: ProposalsTableProps) {
  if (rows.length === 0) {
    return (
      <p className="py-12 text-center text-sm text-muted-foreground" data-testid="proposals-empty">
        No proposals match the current filters.
      </p>
    );
  }
  return (
    <Table data-testid="proposals-table">
      <TableHeader>
        <TableRow>
          <TableHead>Source</TableHead>
          <TableHead>Cluster</TableHead>
          <TableHead>Template</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>PR state</TableHead>
          <TableHead>Metric delta</TableHead>
          <TableHead>Created</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((p) => {
          const md = parseMetricDelta(p.metric_delta);
          return (
            <TableRow key={p.id} data-testid={`proposal-row-${p.id}`}>
              <TableCell>
                {p.study_id ? (
                  <Link
                    href={`/studies/${p.study_id}`}
                    className="text-blue-600 underline-offset-4 hover:underline"
                    data-testid={`proposal-row-${p.id}-study-link`}
                  >
                    study
                  </Link>
                ) : (
                  <span
                    className="text-muted-foreground"
                    data-testid={`proposal-row-${p.id}-manual`}
                  >
                    manual
                  </span>
                )}
                <Link
                  href={`/proposals/${p.id}`}
                  className="ml-2 text-xs text-blue-600 underline-offset-4 hover:underline"
                  data-testid={`proposal-row-${p.id}-detail-link`}
                >
                  view
                </Link>
              </TableCell>
              <TableCell>{p.cluster.name}</TableCell>
              <TableCell>
                {p.template.name}{' '}
                <span className="text-xs text-muted-foreground">v{p.template.version}</span>
              </TableCell>
              <TableCell>
                <StatusBadge kind="proposal" value={p.status} />
              </TableCell>
              <TableCell>
                {p.pr_state ? (
                  <StatusBadge kind="proposal_pr" value={p.pr_state} />
                ) : (
                  <span className="text-muted-foreground">—</span>
                )}
              </TableCell>
              <TableCell>
                {md && md.primary && md.baseline != null && md.best != null ? (
                  <div className="flex flex-col">
                    <span className="text-xs text-muted-foreground">{md.primary}</span>
                    <MetricDelta baseline={md.baseline} achieved={md.best} />
                  </div>
                ) : (
                  <span className="text-muted-foreground">—</span>
                )}
              </TableCell>
              <TableCell className="whitespace-nowrap">
                {new Date(p.created_at).toLocaleString()}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
