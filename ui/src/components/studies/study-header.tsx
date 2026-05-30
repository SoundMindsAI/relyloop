'use client';
import { DemoBadge } from '@/components/common/demo-badge';
import { InfoTooltip } from '@/components/common/info-tooltip';
import { StatusBadge } from '@/components/common/status-badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { StudyDetail } from '@/lib/api/studies';
import type { StudyStatus } from '@/lib/enums';
import type { ShortGlossaryKey } from '@/lib/glossary';

export interface StudyHeaderProps {
  study: StudyDetail;
  /**
   * Whether to render the FR-7 synthetic-data chip next to the study
   * title. Caller is responsible for the
   * `isDemoSyntheticUbiClusterName(cluster.name) &&
   * judgment_list.generation_params?.generation_kind === 'ubi'`
   * decision so this component stays presentational.
   */
  showSyntheticUbiChip?: boolean;
}

/**
 * Dynamic glossary-key lookup for the study status badge tooltip (FR-7).
 * Typed as `Record<StudyStatus, ShortGlossaryKey>` so TypeScript enforces
 * that every status value has a glossary `short` entry — the FR-4 parity
 * test is the runtime sibling check.
 */
const STATUS_TO_GLOSSARY_KEY = {
  queued: 'study.status.queued',
  running: 'study.status.running',
  completed: 'study.status.completed',
  cancelled: 'study.status.cancelled',
  failed: 'study.status.failed',
} as const satisfies Record<StudyStatus, ShortGlossaryKey>;

export function StudyHeader({ study, showSyntheticUbiChip = false }: StudyHeaderProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-3 text-base">
          <span data-testid="study-name">{study.name}</span>
          <div className="flex items-center gap-1">
            <StatusBadge kind="study" value={study.status} />
            <InfoTooltip glossaryKey={STATUS_TO_GLOSSARY_KEY[study.status]} />
          </div>
          {showSyntheticUbiChip && <DemoBadge variant="synthetic-ubi" />}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm md:grid-cols-4">
          <div>
            <dt className="text-xs uppercase text-muted-foreground">Cluster</dt>
            <dd className="font-mono text-xs">{study.cluster_id}</dd>
          </div>
          <div>
            <dt className="flex items-center gap-1 text-xs uppercase text-muted-foreground">
              Target
              <InfoTooltip glossaryKey="study.target" />
            </dt>
            <dd>{study.target}</dd>
          </div>
          <div>
            <dt className="flex items-center gap-1 text-xs uppercase text-muted-foreground">
              Best metric
              <InfoTooltip glossaryKey="study.best_metric" />
            </dt>
            <dd data-testid="study-best-metric">
              {study.best_metric != null ? study.best_metric.toFixed(3) : '—'}
            </dd>
          </div>
          <div>
            <dt className="flex items-center gap-1 text-xs uppercase text-muted-foreground">
              Trials
              <InfoTooltip glossaryKey="study.trials_summary" />
            </dt>
            <dd data-testid="study-trial-count">
              {study.trials_summary.total.toLocaleString()} ({study.trials_summary.complete}{' '}
              complete · {study.trials_summary.failed} failed · {study.trials_summary.pruned}{' '}
              pruned)
            </dd>
          </div>
          <div>
            <dt className="text-xs uppercase text-muted-foreground">Created</dt>
            <dd>{new Date(study.created_at).toLocaleString()}</dd>
          </div>
          {study.started_at && (
            <div>
              <dt className="text-xs uppercase text-muted-foreground">Started</dt>
              <dd>{new Date(study.started_at).toLocaleString()}</dd>
            </div>
          )}
          {study.completed_at && (
            <div>
              <dt className="text-xs uppercase text-muted-foreground">Completed</dt>
              <dd>{new Date(study.completed_at).toLocaleString()}</dd>
            </div>
          )}
          {study.failed_reason && (
            <div className="md:col-span-4">
              <dt className="text-xs uppercase text-muted-foreground">Failed reason</dt>
              <dd className="text-sm text-destructive">{study.failed_reason}</dd>
            </div>
          )}
        </dl>
      </CardContent>
    </Card>
  );
}
