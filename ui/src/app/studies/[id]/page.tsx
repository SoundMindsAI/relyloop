// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';
import Link from 'next/link';
import { Suspense, use, useMemo, useState } from 'react';

import { DetailPageShell } from '@/components/common/detail-page-shell';
import { InfoTooltip } from '@/components/common/info-tooltip';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { AutoFollowupChainPanel } from '@/components/studies/auto-followup-chain-panel';
import { ConfidencePanel } from '@/components/studies/confidence-panel';
import { ConvergencePanel } from '@/components/studies/convergence-panel';
import { LinkedEntitiesRow } from '@/components/studies/linked-entities-row';
import { DigestPanel } from '@/components/studies/digest-panel';
import { StudyActionBar } from '@/components/studies/study-action-bar';
import { StudyHeader } from '@/components/studies/study-header';
import { TrialsTable } from '@/components/studies/trials-table';
import { trialsColumns } from '@/components/studies/trials-table.column-config';
import { useDataTableUrlState } from '@/hooks/use-data-table-url-state';
import { useCluster } from '@/lib/api/clusters';
import { useStudyDigest } from '@/lib/api/digests';
import { useJudgmentList } from '@/lib/api/judgments';
import { useProposalForStudy } from '@/lib/api/proposals';
import { useStudy, useStudyChildren, useStudyTrials } from '@/lib/api/studies';
import { isDemoSyntheticUbiClusterName } from '@/lib/demo-data';
import { TRIAL_SORT_VALUES, type TrialSort } from '@/lib/enums';

interface RouteProps {
  params: Promise<{ id: string }>;
}

const POLL_MS = 3000;
const DEFAULT_TRIAL_SORT: TrialSort = 'primary_metric_desc';

export function StudyDetailView({ studyId }: { studyId: string }) {
  // Scope the URL hook by studyId so col-vis + density preferences don't
  // bleed across different study detail pages.
  const urlState = useDataTableUrlState(`trials-${studyId}`, trialsColumns, {
    defaultPageSize: 50,
  });

  // Narrow the URL sort value to the canonical TrialSortKey allowlist —
  // invalid values fall back to the default. The DataTable feeds the wire
  // form back via urlState.sort thanks to trialsSortCodec; this narrowing
  // protects useStudyTrials from receiving an arbitrary string when an
  // operator hand-edits the URL.
  const rawSort = urlState.sort;
  const sort: TrialSort =
    rawSort && (TRIAL_SORT_VALUES as readonly string[]).includes(rawSort)
      ? (rawSort as TrialSort)
      : DEFAULT_TRIAL_SORT;

  // Caller-driven polling per spec §4: TanStack Query's refetchInterval
  // function form derives the interval from the latest query state on each
  // tick, so the cadence flips off automatically when the study completes.
  const studyQ = useStudy(studyId, {
    refetchInterval: (q) => (q.state.data?.status === 'running' ? POLL_MS : false),
  });
  const trialsQ = useStudyTrials(studyId, {
    sort,
    cursor: urlState.cursor ?? undefined,
    limit: urlState.pageSize,
    refetchInterval: () => (studyQ.data?.status === 'running' ? POLL_MS : false),
  });
  const digestQ = useStudyDigest(studyId);
  const proposalQ = useProposalForStudy(studyId);
  const childrenQ = useStudyChildren(studyId);

  return (
    <main className="mx-auto max-w-7xl space-y-6 p-6">
      <div>
        <Link href="/studies" className="text-sm text-blue-600 underline-offset-4 hover:underline">
          ← All studies
        </Link>
      </div>
      <DetailPageShell query={studyQ} entityLabel="study" notFoundErrorCode="STUDY_NOT_FOUND">
        {(study) => (
          <>
            <div className="flex items-center justify-between">
              <h1 className="text-2xl font-semibold tracking-tight">Study detail</h1>
              <StudyActionBar study={study} chainChildren={childrenQ.data?.data ?? []} />
            </div>
            <p className="text-sm text-muted-foreground" data-testid="study-page-summary">
              A study runs Optuna trials against your cluster and judgment list to search for a
              better parameter configuration. Each row in the trials table is one tried-and-scored
              config. <strong>Parameter importance</strong> shows which knobs the optimizer leaned
              on; the <strong>digest</strong> (when complete) explains the result in prose and
              recommends a config to ship via a proposal. Click the floating <em>Guide</em> button
              (bottom-right) for the step-by-step walkthrough.
            </p>
            <StudyHeaderWithSyntheticChip study={study} />
            <LinkedEntitiesRow study={study} />
            {proposalQ.data && (
              <p className="text-sm" data-testid="study-proposal-link">
                <span className="text-muted-foreground">Proposal:</span>{' '}
                <Link
                  href={`/proposals/${proposalQ.data.id}`}
                  className="text-blue-600 underline-offset-4 hover:underline"
                  data-testid="study-proposal-link-anchor"
                >
                  view proposal (
                  <span className="capitalize">{proposalQ.data.status.replace(/_/g, ' ')}</span>)
                </Link>
              </p>
            )}
            <AutoFollowupChainPanel study={study} chainChildren={childrenQ.data?.data ?? []} />
            <ConfidencePanel confidence={study.confidence} />
            <ConvergencePanel
              convergence={study.convergence ?? null}
              studyStatus={study.status}
              trialsSummary={study.trials_summary}
            />
            <TrialsCard trialsQ={trialsQ} urlState={urlState} tableId={`trials-${studyId}`} />
            {study.status === 'completed' && digestQ.data && (
              <DigestPanel
                digest={digestQ.data}
                baselineMetric={study.baseline_metric ?? null}
                bestMetric={study.best_metric ?? null}
                pendingProposal={proposalQ.data ?? null}
              />
            )}
          </>
        )}
      </DetailPageShell>
    </main>
  );
}

/**
 * Trials card with the feat_study_baseline_trial FR-9 "Show baseline
 * trial" toggle.
 *
 * The trials-listing API returns BOTH Optuna and baseline rows (FR-11
 * intentionally exempts that helper from the is_baseline=FALSE filter
 * so the UI can render them). This component filters baseline rows out
 * of the visible data by default and exposes a toggle to reveal them.
 * When revealed, the baseline row sits at the top of the table with a
 * "Baseline" badge.
 */
function TrialsCard({
  trialsQ,
  urlState,
  tableId,
}: {
  trialsQ: ReturnType<typeof useStudyTrials>;
  urlState: ReturnType<typeof useDataTableUrlState>;
  tableId: string;
}) {
  const [showBaseline, setShowBaseline] = useState(false);
  const data = trialsQ.data?.data ?? [];
  const baselineRows = useMemo(() => data.filter((r) => r.is_baseline), [data]);
  const visibleRows = useMemo(
    () => (showBaseline ? data : data.filter((r) => !r.is_baseline)),
    [data, showBaseline],
  );

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle className="flex items-center gap-1 text-base">
          Trials
          <InfoTooltip glossaryKey="trial" />
        </CardTitle>
        {baselineRows.length > 0 && (
          <div className="flex items-center gap-2">
            <Button
              variant={showBaseline ? 'default' : 'outline'}
              size="sm"
              onClick={() => setShowBaseline((v) => !v)}
              data-testid="trials-toggle-baseline"
            >
              {showBaseline ? 'Hide baseline trial' : 'Show baseline trial'}
            </Button>
            {showBaseline && (
              <Badge variant="secondary" data-testid="trials-baseline-badge">
                Baseline
              </Badge>
            )}
          </div>
        )}
      </CardHeader>
      <CardContent>
        <TrialsTable
          rows={visibleRows}
          totalCount={trialsQ.data?.totalCount}
          has_more={trialsQ.data?.has_more ?? false}
          next_cursor={trialsQ.data?.next_cursor ?? null}
          isLoading={trialsQ.isPending}
          isError={trialsQ.isError}
          urlState={urlState}
          tableId={tableId}
        />
      </CardContent>
    </Card>
  );
}

/**
 * Wrapper that resolves cluster.name + judgment_list.generation_params
 * for the FR-7 synthetic-data chip gate and forwards a boolean to keep
 * <StudyHeader> presentational. Decision rule per FR-7 surface #4:
 * `isDemoSyntheticUbiClusterName(cluster.name) &&
 * judgment_list.generation_params?.generation_kind === 'ubi'`.
 */
function StudyHeaderWithSyntheticChip({
  study,
}: {
  study: import('@/lib/api/studies').StudyDetail;
}) {
  const cluster = useCluster(study.cluster_id);
  const judgmentList = useJudgmentList(study.judgment_list_id);
  const params = judgmentList.data?.generation_params as Record<string, unknown> | null | undefined;
  const generationKindIsUbi = params != null && params.generation_kind === 'ubi';
  const showSyntheticUbiChip =
    cluster.data !== undefined &&
    generationKindIsUbi &&
    isDemoSyntheticUbiClusterName(cluster.data.name);
  return <StudyHeader study={study} showSyntheticUbiChip={showSyntheticUbiChip} />;
}

export default function StudyDetailPage({ params }: RouteProps) {
  const { id } = use(params);
  // `useSearchParams` (inside useDataTableUrlState) requires a Suspense boundary
  // in Next 16 App Router.
  return (
    <Suspense fallback={<main className="mx-auto max-w-7xl p-6">Loading…</main>}>
      <StudyDetailView studyId={id} />
    </Suspense>
  );
}
