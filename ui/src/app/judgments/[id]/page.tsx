// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';
import Link from 'next/link';
import { Suspense, use, useMemo, useState } from 'react';

import { DetailPageShell } from '@/components/common/detail-page-shell';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { AmbiguousSkipRecoveryCard } from '@/components/judgments/ambiguous-skip-recovery-card';
import { CalibrationModal } from '@/components/judgments/calibration-modal';
import { JudgmentListHeader } from '@/components/judgments/judgment-list-header';
import { JudgmentsTable } from '@/components/judgments/judgments-table';
import { useJudgmentsColumns } from '@/components/judgments/judgments-table.column-config';
import { ValueDeltaCard } from '@/components/judgments/value-delta-card';
import { useDataTableUrlState } from '@/hooks/use-data-table-url-state';
import { useCluster } from '@/lib/api/clusters';
import { useJudgmentList, useJudgmentLists, useJudgments } from '@/lib/api/judgments';
import { useGenerateJudgmentsFromUbi } from '@/lib/api/ubi';
import { isDemoSyntheticUbiClusterName } from '@/lib/demo-data';
import { JUDGMENT_SOURCE_FILTER_VALUES } from '@/lib/enums';

interface RouteProps {
  params: Promise<{ id: string }>;
}

export function JudgmentListView({ listId }: { listId: string }) {
  // The column config carries the filter declaration the URL hook consults
  // to figure out which params are filter keys. Pulling the columns once
  // here gives the hook the right scope without re-computing them.
  const columns = useJudgmentsColumns(listId);
  // Scope the URL hook by listId so col-vis + density preferences don't
  // bleed across different judgment lists' detail pages.
  const urlState = useDataTableUrlState(`judgments-${listId}`, columns, { defaultPageSize: 50 });
  const [calibrationOpen, setCalibrationOpen] = useState(false);

  // Narrow the URL source value to the backend's accepted set (widened
  // by feat_ubi_judgments FR-10 to include 'click').
  const rawSource = urlState.filters['source'];
  const source = useMemo<'llm' | 'human' | 'click' | undefined>(() => {
    if (rawSource === 'llm' || rawSource === 'human' || rawSource === 'click') return rawSource;
    if (rawSource && !(JUDGMENT_SOURCE_FILTER_VALUES as readonly string[]).includes(rawSource)) {
      return undefined;
    }
    return undefined;
  }, [rawSource]);

  const list = useJudgmentList(listId);
  const judgments = useJudgments(listId, {
    source,
    sort: urlState.sort ?? undefined,
    cursor: urlState.cursor ?? undefined,
    limit: urlState.pageSize,
  });

  // Pull LLM-only prior lists on the same query_set so the value-delta card
  // can render a comparison link. Disabled until the list detail resolves.
  const priorLists = useJudgmentLists(
    list.data
      ? {
          query_set_id: list.data.query_set_id,
          limit: 20,
        }
      : {},
  );

  const generateUbi = useGenerateJudgmentsFromUbi();

  return (
    <main className="mx-auto max-w-7xl space-y-6 p-6">
      <div>
        <Link
          href="/judgments"
          className="text-sm text-blue-600 underline-offset-4 hover:underline"
        >
          ← All judgment lists
        </Link>
      </div>
      <DetailPageShell
        query={list}
        entityLabel="judgment list"
        notFoundErrorCode="JUDGMENT_LIST_NOT_FOUND"
      >
        {(listData) => (
          <>
            <div className="flex items-center justify-between">
              <h1 className="text-2xl font-semibold tracking-tight">Judgment Review</h1>
              <Button onClick={() => setCalibrationOpen(true)} data-testid="open-calibration">
                Calibrate
              </Button>
            </div>
            <p className="text-sm text-muted-foreground" data-testid="judgment-page-summary">
              A judgment list is the <strong>(query, doc, rating)</strong> ground truth your studies
              score against. Ratings come from an LLM (graded against your rubric) or from an
              operator-imported file. <strong>Calibrate</strong> compares LLM-graded ratings against
              a human-imported reference list via Cohen's κ — high agreement means the LLM mirrors
              your team's judgment. Click the floating <em>Guide</em> button (bottom-right) for the
              step-by-step walkthrough.
            </p>
            <JudgmentListHeaderWithSyntheticChip listData={listData} />
            {(() => {
              const calibration = listData.calibration as Record<string, unknown> | null;
              const params = listData.generation_params as Record<string, unknown> | null;
              const isUbi =
                (calibration !== null &&
                  typeof calibration === 'object' &&
                  'coverage_pct' in calibration) ||
                (params !== null && params?.generation_kind === 'ubi');
              if (!isUbi) return null;
              const coverage =
                typeof calibration?.coverage_pct === 'number' ? calibration.coverage_pct : null;
              const ambiguousSkip =
                typeof calibration?.ambiguous_query_skip_count === 'number'
                  ? calibration.ambiguous_query_skip_count
                  : 0;
              // Find a prior LLM list on the same query_set (latest first).
              const priorLlm = (priorLists.data?.data ?? []).find(
                (item) => item.id !== listData.id,
              );
              const priorListSummary = priorLlm
                ? {
                    id: priorLlm.id,
                    name: priorLlm.name,
                    judgment_count: 0,
                  }
                : null;
              return (
                <>
                  <ValueDeltaCard
                    coveragePct={coverage}
                    judgmentCount={listData.judgment_count}
                    priorList={priorListSummary}
                  />
                  {ambiguousSkip > 0 && params && (
                    <AmbiguousSkipRecoveryCard
                      skipCount={ambiguousSkip}
                      pending={generateUbi.isPending}
                      onRerunWithMostRecent={() => {
                        // Reconstruct the original request body from generation_params
                        // + override mapping_strategy + derive a new name.
                        const body = {
                          name: `${listData.name}-most-recent`,
                          description: listData.description,
                          query_set_id: listData.query_set_id,
                          cluster_id: listData.cluster_id,
                          target: listData.target,
                          since: (params.since as string | null) ?? new Date().toISOString(),
                          until: (params.until as string | null) ?? null,
                          converter: params.converter as
                            | 'ctr_threshold'
                            | 'dwell_time'
                            | 'hybrid_ubi_llm',
                          mapping_strategy: 'most_recent' as const,
                          llm_fill_threshold: (params.llm_fill_threshold as number | null) ?? null,
                          min_impressions_threshold:
                            (params.min_impressions_threshold as number | null) ?? null,
                          current_template_id:
                            (params.current_template_id as string | null) ?? null,
                          rubric: (params.rubric as string | null) ?? null,
                        };
                        generateUbi.mutate(body);
                      }}
                    />
                  )}
                </>
              );
            })()}
            <Card>
              <CardContent className="pt-6">
                <JudgmentsTable
                  rows={judgments.data?.data ?? []}
                  listId={listId}
                  totalCount={judgments.data?.totalCount}
                  has_more={judgments.data?.has_more ?? false}
                  next_cursor={judgments.data?.next_cursor ?? null}
                  isLoading={judgments.isPending}
                  isError={judgments.isError}
                  urlState={urlState}
                />
              </CardContent>
            </Card>
            <CalibrationModal
              open={calibrationOpen}
              onOpenChange={setCalibrationOpen}
              listId={listId}
            />
          </>
        )}
      </DetailPageShell>
    </main>
  );
}

/**
 * Wrapper that resolves cluster.name for the FR-7 synthetic-data chip
 * gate and forwards it as a boolean to keep <JudgmentListHeader>
 * presentational. Decision rule mirrors spec FR-7 surface #2:
 * `isDemoSyntheticUbiClusterName(cluster.name) &&
 * generation_params?.generation_kind === 'ubi'`.
 */
function JudgmentListHeaderWithSyntheticChip({
  listData,
}: {
  listData: import('@/lib/api/judgments').JudgmentListDetail;
}) {
  const clusterId = listData.cluster_id;
  const cluster = useCluster(clusterId);
  const params = listData.generation_params as Record<string, unknown> | null;
  const generationKindIsUbi = params?.generation_kind === 'ubi';
  const showSyntheticUbiChip =
    cluster.data !== undefined &&
    generationKindIsUbi &&
    isDemoSyntheticUbiClusterName(cluster.data.name);
  return <JudgmentListHeader list={listData} showSyntheticUbiChip={showSyntheticUbiChip} />;
}

export default function JudgmentListPage({ params }: RouteProps) {
  const { id } = use(params);
  return (
    <Suspense fallback={<main className="mx-auto max-w-7xl p-6">Loading…</main>}>
      <JudgmentListView listId={id} />
    </Suspense>
  );
}
