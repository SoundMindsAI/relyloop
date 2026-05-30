// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Column configuration for `<ProposalsTable>` (feat_data_table_primitive Story 3.2).
 *
 * 7 columns: Source (link or "manual" text + per-row detail link), Cluster,
 * Template, Status badge, PR state badge, Metric delta, Created.
 *
 * 4 filters in the toolbar:
 *  - `source` (enum chip row — `study | manual`, URL `?source=`)
 *  - `status` (enum chip row — `pending | pr_opened | pr_merged | rejected`)
 *  - `cluster_id` (fk-select — sources from `useClusters({ limit: 200 })`)
 *  - `template_id` (fk-select — NEW, sources from `useTemplates({ limit: 200 })`)
 *
 * Source-of-truth comments on every enum filter point at the backend
 * Literal so the Story 2.13 lint guard passes; wire values come from
 * `@/lib/enums` (which itself carries the canonical comment).
 */
import Link from 'next/link';

import { MetricDelta } from '@/components/common/metric-delta';
import { StatusBadge } from '@/components/common/status-badge';
import type { DataTableColumnDef } from '@/components/common/types';
import { CurrentlyLiveBadge } from '@/components/proposals/currently-live-badge';
import { useClusters } from '@/lib/api/clusters';
import type { ProposalSummary } from '@/lib/api/proposals';
import { useTemplates } from '@/lib/api/query-templates';
import { isDemoClusterName } from '@/lib/demo-data';
import { PROPOSAL_SOURCE_VALUES, PROPOSAL_STATUS_VALUES } from '@/lib/enums';

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

/** Hook adapter for the cluster fk-select. Cluster count is bounded MVP1 (<10).
 *
 * feat_home_first_run_demo_nudge Story 3.4: demo cluster names get a
 * " (Demo)" text-suffix in the dropdown label so operators can spot
 * seeded clusters at a glance. The native <select> rendered by
 * DataTableFkSelect doesn't accept JSX <option> content, hence the
 * text suffix instead of the <DemoBadge> JSX used in the clusters list. */
function useClustersForFilter(): { data: { id: string; label: string }[]; isLoading: boolean } {
  const q = useClusters({ limit: 200 });
  return {
    data: (q.data?.data ?? []).map((c) => ({
      id: c.id,
      label: c.name + (isDemoClusterName(c.name) ? ' (Demo)' : ''),
    })),
    isLoading: q.isPending,
  };
}

/** Hook adapter for the template fk-select. */
function useTemplatesForFilter(): { data: { id: string; label: string }[]; isLoading: boolean } {
  const q = useTemplates({ limit: 200 });
  return {
    data: (q.data?.data ?? []).map((t) => ({ id: t.id, label: t.name })),
    isLoading: q.isPending,
  };
}

export const proposalsColumns: DataTableColumnDef<ProposalSummary>[] = [
  {
    id: 'source',
    header: 'Source',
    accessorKey: 'study_id',
    filter: {
      kind: 'enum',
      wireValues: PROPOSAL_SOURCE_VALUES,
      sourceOfTruth: 'backend/app/api/v1/schemas.py ProposalSourceWire',
    },
    cell: ({ row }) => {
      const p = row.original;
      return (
        <>
          {p.study_id ? (
            <Link
              href={`/studies/${p.study_id}`}
              className="text-blue-600 underline-offset-4 hover:underline"
              data-testid={`proposal-row-${p.id}-study-link`}
            >
              study
            </Link>
          ) : (
            <span className="text-muted-foreground" data-testid={`proposal-row-${p.id}-manual`}>
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
        </>
      );
    },
  },
  {
    id: 'cluster_id',
    header: 'Cluster',
    accessorKey: 'cluster.name',
    filter: {
      kind: 'fk-select',
      useOptions: useClustersForFilter,
      sourceOfTruth: 'backend/app/db/models/proposal.py Proposal.cluster_id',
      placeholder: 'All clusters',
    },
    cell: ({ row }) => row.original.cluster.name,
  },
  {
    id: 'template_id',
    header: 'Template',
    accessorKey: 'template.name',
    filter: {
      kind: 'fk-select',
      useOptions: useTemplatesForFilter,
      sourceOfTruth: 'backend/app/db/models/proposal.py Proposal.template_id',
      placeholder: 'All templates',
    },
    cell: ({ row }) => (
      <>
        {row.original.template.name}{' '}
        <span className="text-xs text-muted-foreground">v{row.original.template.version}</span>
      </>
    ),
  },
  {
    id: 'status',
    header: 'Status',
    accessorKey: 'status',
    sortable: true,
    filter: {
      kind: 'enum',
      wireValues: PROPOSAL_STATUS_VALUES,
      sourceOfTruth: 'backend/app/api/v1/schemas.py ProposalStatusWire',
    },
    cell: ({ row }) => (
      <>
        <StatusBadge kind="proposal" value={row.original.status} />
        <CurrentlyLiveBadge isCurrentlyLive={row.original.is_currently_live} />
      </>
    ),
  },
  {
    id: 'pr_state',
    header: 'PR state',
    accessorKey: 'pr_state',
    sortable: true,
    cell: ({ row }) =>
      row.original.pr_state ? (
        <StatusBadge kind="proposal_pr" value={row.original.pr_state} />
      ) : (
        <span className="text-muted-foreground">—</span>
      ),
  },
  {
    id: 'metric_delta',
    header: 'Metric delta',
    cell: ({ row }) => {
      const md = parseMetricDelta(row.original.metric_delta);
      if (!md || !md.primary || md.baseline == null || md.best == null) {
        return <span className="text-muted-foreground">—</span>;
      }
      return (
        <div className="flex flex-col">
          <span className="text-xs text-muted-foreground">{md.primary}</span>
          <MetricDelta baseline={md.baseline} achieved={md.best} />
        </div>
      );
    },
  },
  {
    id: 'created_at',
    header: 'Created',
    accessorKey: 'created_at',
    sortable: true,
    firstClickDirection: 'desc',
    cell: ({ row }) => (
      <span className="whitespace-nowrap">
        {new Date(row.original.created_at).toLocaleString()}
      </span>
    ),
  },
];
