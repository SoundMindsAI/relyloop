// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';
import { DemoBadge } from '@/components/common/demo-badge';
import { StatusBadge } from '@/components/common/status-badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { JudgmentListDetail } from '@/lib/api/judgments';

export interface JudgmentListHeaderProps {
  list: JudgmentListDetail;
  /**
   * Whether to render the FR-7 synthetic-data chip next to the list
   * title. Caller is responsible for the
   * `isDemoSyntheticUbiClusterName(cluster.name) &&
   * generation_params?.generation_kind === 'ubi'` decision so this
   * component stays presentational and trivially unit-testable.
   */
  showSyntheticUbiChip?: boolean;
}

function kappaDisplay(list: JudgmentListDetail): {
  cohens: string;
  weighted: string;
  n: number | null;
} {
  const cal = list.calibration as {
    cohens_kappa?: number;
    weighted_kappa?: number;
    n_samples?: number;
  } | null;
  if (!cal) return { cohens: '—', weighted: '—', n: null };
  return {
    cohens: cal.cohens_kappa != null ? cal.cohens_kappa.toFixed(3) : '—',
    weighted: cal.weighted_kappa != null ? cal.weighted_kappa.toFixed(3) : '—',
    n: cal.n_samples ?? null,
  };
}

export function JudgmentListHeader({
  list,
  showSyntheticUbiChip = false,
}: JudgmentListHeaderProps) {
  const k = kappaDisplay(list);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-3 text-base">
          <span>{list.name}</span>
          <StatusBadge kind="judgment_list" value={list.status} />
          {showSyntheticUbiChip && <DemoBadge variant="synthetic-ubi" />}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm md:grid-cols-4">
          <div>
            <dt className="text-xs uppercase text-muted-foreground">Total judgments</dt>
            <dd data-testid="header-count">{list.judgment_count.toLocaleString()}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase text-muted-foreground">LLM / Human</dt>
            <dd data-testid="header-breakdown">
              {list.source_breakdown.llm.toLocaleString()} /{' '}
              {list.source_breakdown.human.toLocaleString()}
            </dd>
          </div>
          <div>
            <dt className="text-xs uppercase text-muted-foreground">Cohen&rsquo;s κ</dt>
            <dd data-testid="header-kappa">{k.cohens}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase text-muted-foreground">Weighted κ</dt>
            <dd data-testid="header-weighted-kappa">{k.weighted}</dd>
          </div>
        </dl>
        {list.failed_reason && (
          <p className="mt-3 text-sm text-destructive">{list.failed_reason}</p>
        )}
      </CardContent>
    </Card>
  );
}
