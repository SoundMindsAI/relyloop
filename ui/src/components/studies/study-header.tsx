'use client';
import { StatusBadge } from '@/components/common/status-badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { StudyDetail } from '@/lib/api/studies';

export interface StudyHeaderProps {
  study: StudyDetail;
}

export function StudyHeader({ study }: StudyHeaderProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-3 text-base">
          <span data-testid="study-name">{study.name}</span>
          <StatusBadge kind="study" value={study.status} />
        </CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm md:grid-cols-4">
          <div>
            <dt className="text-xs uppercase text-muted-foreground">Cluster</dt>
            <dd className="font-mono text-xs">{study.cluster_id}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase text-muted-foreground">Target</dt>
            <dd>{study.target}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase text-muted-foreground">Best metric</dt>
            <dd data-testid="study-best-metric">
              {study.best_metric != null ? study.best_metric.toFixed(3) : '—'}
            </dd>
          </div>
          <div>
            <dt className="text-xs uppercase text-muted-foreground">Trials</dt>
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
