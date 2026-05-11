'use client';
import Link from 'next/link';

import { StatusBadge } from '@/components/common/status-badge';
import { Card, CardContent } from '@/components/ui/card';
import type { StudySummary } from '@/lib/api/studies';

export interface RecentStudiesCardsProps {
  rows: readonly StudySummary[];
}

export function RecentStudiesCards({ rows }: RecentStudiesCardsProps) {
  if (rows.length === 0) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="recent-studies-empty">
        No studies yet. Create one from the Studies tab.
      </p>
    );
  }
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3" data-testid="recent-studies">
      {rows.map((s) => (
        <Link key={s.id} href={`/studies/${s.id}`} data-testid={`recent-study-${s.id}`}>
          <Card>
            <CardContent className="space-y-2 pt-6">
              <div className="flex items-start justify-between gap-3">
                <span className="font-medium">{s.name}</span>
                <StatusBadge kind="study" value={s.status} />
              </div>
              <dl className="grid grid-cols-2 gap-x-3 text-xs text-muted-foreground">
                <div>
                  <dt className="uppercase">Best metric</dt>
                  <dd>{s.best_metric != null ? s.best_metric.toFixed(3) : '—'}</dd>
                </div>
                <div>
                  <dt className="uppercase">Created</dt>
                  <dd>{new Date(s.created_at).toLocaleDateString()}</dd>
                </div>
              </dl>
            </CardContent>
          </Card>
        </Link>
      ))}
    </div>
  );
}
