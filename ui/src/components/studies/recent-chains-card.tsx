// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

/**
 * `<RecentChainsCard>` — feat_overnight_studies_summary_card Story 2.2.
 *
 * The "Ran while you were away" card that surfaces recently-completed
 * overnight chains at the top of `/studies` (FR-1, FR-3, FR-4, FR-5,
 * FR-6).
 *
 * The card is self-contained:
 *
 *  - Owns its data via `useRecentChains(since)`, where `since` comes
 *    from `useStudiesVisited()`. Does NOT depend on the page's
 *    `useStudies()` query.
 *  - Early-returns `null` on pending / error / empty so it never blocks
 *    the studies table beneath it (best-effort discoverability per
 *    spec §10 "Failure modes").
 *  - "Got it" calls `dismiss(maxTailCompletedAt)` which writes
 *    `max(tail_completed_at) + 1ms` to localStorage; the next query
 *    refetch returns an empty list and the card unmounts (FR-5).
 *
 * Stop-reason phrasing reuses `CHAIN_STOP_REASON_PHRASE` from
 * `ui/src/lib/chain-stop-reason.ts` — the same Map shipped with
 * `feat_overnight_final_solution_phase2` (Story 1 / FR-8) so both the
 * chain panel and this card stay aligned on a single source of truth
 * for the six wire values defined in
 * `backend/app/domain/study/chain_summary.py` `CHAIN_STOP_REASONS`.
 */

import Link from 'next/link';

import { InfoTooltip } from '@/components/common/info-tooltip';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useStudiesVisited } from '@/hooks/use-studies-visited';
import { useRecentChains, type RecentChainSummary } from '@/lib/api/studies';
import { CHAIN_STOP_REASON_PHRASE } from '@/lib/chain-stop-reason';
import { formatSignedLift } from '@/lib/format-lift';

function formatBestMetric(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  return value.toFixed(4);
}

interface ChainRowProps {
  row: RecentChainSummary;
}

function ChainRow({ row }: ChainRowProps) {
  const stopPhrase = CHAIN_STOP_REASON_PHRASE[row.stop_reason] ?? row.stop_reason;
  const hasMetric = row.best_metric !== null && row.best_metric !== undefined;

  return (
    <li
      className="flex flex-col gap-1 rounded-md border border-border bg-card px-3 py-2 text-sm"
      data-testid={`recent-chains-card-row-${row.anchor_study_id}`}
    >
      <div className="flex items-center justify-between gap-2">
        <Link
          href={`/studies/${row.anchor_study_id}`}
          className="font-medium hover:underline"
          data-testid={`recent-chains-card-anchor-link-${row.anchor_study_id}`}
        >
          {row.anchor_name}
        </Link>
        <span className="text-xs text-muted-foreground">{row.chain_length} studies</span>
      </div>
      {hasMetric ? (
        <div className="flex flex-wrap items-center gap-x-4 text-xs text-muted-foreground">
          <span>
            Best {row.objective_metric || 'metric'}:{' '}
            <span className="font-medium text-foreground">{formatBestMetric(row.best_metric)}</span>
          </span>
          <span>
            Lift:{' '}
            <span className="font-medium text-foreground">
              {formatSignedLift(row.cumulative_lift)}
            </span>
          </span>
          <span>Stopped: {stopPhrase}</span>
        </div>
      ) : (
        // Null-metric branch (AC-11): the chain has no surfaceable best
        // metric (e.g. terminal-failed tail). Drop the numeric line
        // entirely and lead with the stop-reason phrase so the row
        // reads as "the chain ended without a winning trial" rather
        // than "best — / lift —".
        <div className="text-xs text-muted-foreground">Stopped: {stopPhrase}</div>
      )}
    </li>
  );
}

export function RecentChainsCard(): React.ReactNode {
  const { since, dismiss } = useStudiesVisited();
  const query = useRecentChains(since);

  // Best-effort discoverability — pending / error / empty all collapse
  // to `null` so the studies table beneath always renders predictably
  // (FR-3 + spec §10 failure modes).
  if (query.isPending) return null;
  if (query.isError) return null;
  const rows = query.data?.data ?? [];
  if (rows.length === 0) return null;

  const tailTimes = rows
    .map((r) => Date.parse(r.tail_completed_at))
    .filter((n) => Number.isFinite(n));
  // Defensive: tailTimes should always be non-empty when rows is, but
  // guard against a malformed timestamp slipping through (the dismiss
  // hook already silently no-ops on NaN, so this is belt-and-suspenders).
  const maxTail =
    tailTimes.length > 0
      ? new Date(Math.max(...tailTimes)).toISOString()
      : rows[rows.length - 1]?.tail_completed_at;

  const handleDismiss = (): void => {
    if (maxTail !== undefined) {
      dismiss(maxTail);
    }
  };

  return (
    <Card data-testid="recent-chains-card">
      <CardHeader className="flex flex-row items-start justify-between gap-2 space-y-0">
        <div className="space-y-1">
          <CardTitle className="flex items-center gap-2 text-base">
            Ran while you were away
            <InfoTooltip glossaryKey="recent_chains_card" />
          </CardTitle>
          <p className="text-xs text-muted-foreground">
            Overnight <InfoTooltip glossaryKey="overnight_autopilot" /> follow-up chains that
            completed since your last visit.
          </p>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={handleDismiss}
          data-testid="recent-chains-card-dismiss"
        >
          Got it
        </Button>
      </CardHeader>
      <CardContent>
        <ul className="space-y-2">
          {rows.map((row) => (
            <ChainRow key={row.anchor_study_id} row={row} />
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
