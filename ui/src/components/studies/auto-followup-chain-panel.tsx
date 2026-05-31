// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';
import { useEffect, useRef } from 'react';
import Link from 'next/link';
import { useQueryClient } from '@tanstack/react-query';

import { InfoTooltip } from '@/components/common/info-tooltip';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  useStudyChain,
  type StudyChainResponse,
  type StudyDetail,
  type StudySummary,
} from '@/lib/api/studies';

export interface AutoFollowupChainPanelProps {
  study: StudyDetail;
  /**
   * Direct children from GET /api/v1/studies/{id}/children.
   *
   * Named `chainChildren` (NOT `children`) to avoid React's
   * react/no-children-prop lint rule + the prop-name collision with
   * React's built-in `children` semantics.
   */
  chainChildren: StudySummary[];
}

// feat_overnight_autopilot FR-4 — wire stop_reason → human phrase.
// Source-of-truth: backend/app/domain/study/chain_summary.py CHAIN_STOP_REASONS
const CHAIN_STOP_REASON_PHRASE: Record<NonNullable<StudyChainResponse['stop_reason']>, string> = {
  depth_exhausted: 'depth budget exhausted',
  no_lift: 'no further improvement',
  budget: 'daily LLM budget reached',
  parent_failed: 'parent study failed or was cancelled',
  cancelled: 'operator cancelled the chain',
  in_flight: 'chain still running',
};

const TERMINAL_STUDY_STATUSES: ReadonlySet<string> = new Set(['completed', 'cancelled', 'failed']);

/**
 * Format a signed lift/delta value with a leading `+`/`-` and 4 decimals.
 * Returns '—' for null (matches the children-table empty-cell convention).
 */
function formatSignedLift(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  return `${value >= 0 ? '+' : ''}${value.toFixed(4)}`;
}

/** Per-link delta string: '' (empty) for the anchor / in-flight links. */
function formatDelta(value: number | null | undefined): string {
  if (value === null || value === undefined) return '';
  return `${value >= 0 ? '+' : ''}${value.toFixed(4)}`;
}

/**
 * Auto-followup chain panel (feat_auto_followup_studies Story 3.1, FR-10
 * frontend; extended by feat_overnight_autopilot FR-4).
 *
 * Renders the parent link (when this study is itself a chain child) +
 * the remaining-depth indicator + the direct-children table, plus a
 * rolled-up overnight-chain summary (ordered link list, cumulative lift,
 * best config, stop reason) sourced from GET /studies/{id}/chain.
 *
 * The panel is invisible only when there's no chain context AND the
 * operator never opted into chaining: no parent_study_id, no
 * auto_followup_depth set, no children, and the summary predicate (D-13)
 * does not hold.
 */
export function AutoFollowupChainPanel({
  study,
  chainChildren,
}: AutoFollowupChainPanelProps): React.ReactNode {
  const queryClient = useQueryClient();
  const chainQ = useStudyChain(study.id);

  // feat_overnight_autopilot D-10: when the viewed study flips from running
  // to a terminal status, the chain summary may settle (best subset / stop
  // reason change) — invalidate so it refetches.
  const prevStatusRef = useRef(study.status);
  useEffect(() => {
    const prev = prevStatusRef.current;
    if (prev === 'running' && TERMINAL_STUDY_STATUSES.has(study.status)) {
      queryClient.invalidateQueries({ queryKey: ['studies', study.id, 'chain'] });
    }
    prevStatusRef.current = study.status;
  }, [study.status, study.id, queryClient]);

  const parentId = study.parent_study_id;
  const depth =
    typeof study.config?.auto_followup_depth === 'number' ? study.config.auto_followup_depth : null;
  const hasParent = parentId !== null && parentId !== undefined;
  const hasDepth = depth !== null && depth > 0;
  const hasChildren = chainChildren.length > 0;

  const chain = chainQ.data;
  // D-13 render predicate: show the rolled-up summary when there's a real
  // multi-link chain, OR the local study is a descendant, OR the anchor
  // explicitly opted into chaining (depth_remaining set) even if no child
  // has spawned yet.
  const showSummary =
    (chain?.links.length ?? 0) >= 2 ||
    hasParent ||
    chain?.links[0]?.auto_followup_depth_remaining != null;

  // Hide the panel only when there's no chain context AND no summary to show.
  if (!hasParent && !hasDepth && !hasChildren && !showSummary) {
    return null;
  }

  const bestLink =
    chain && chain.best_link_id !== null
      ? (chain.links.find((l) => l.id === chain.best_link_id) ?? null)
      : null;

  return (
    <Card data-testid="auto-followup-chain-panel">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          Auto-followup chain
          <InfoTooltip glossaryKey="auto_followup_chain" />
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {hasParent && (
          <p data-testid="auto-followup-parent-link">
            Parent:{' '}
            <Link
              href={`/studies/${parentId}`}
              className="text-blue-600 underline-offset-4 hover:underline"
            >
              view parent study
            </Link>
          </p>
        )}
        {hasDepth && (
          <p data-testid="auto-followup-remaining-depth">
            Remaining auto-follow-ups: <span className="font-medium">{depth}</span>
            <span className="ml-2 inline-flex">
              <InfoTooltip glossaryKey="auto_followup_depth" />
            </span>
          </p>
        )}
        {hasChildren && (
          <div data-testid="auto-followup-children-table">
            <h3 className="mb-2 text-sm font-medium text-muted-foreground">Direct children</h3>
            <table className="w-full border-collapse text-left">
              <thead className="border-b text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="py-2 pr-4 font-medium">Name</th>
                  <th className="py-2 pr-4 font-medium">Status</th>
                  <th className="py-2 pr-4 font-medium">Best metric</th>
                </tr>
              </thead>
              <tbody>
                {chainChildren.map((child) => (
                  <tr key={child.id} className="border-b last:border-0">
                    <td className="py-2 pr-4">
                      <Link
                        href={`/studies/${child.id}`}
                        className="text-blue-600 underline-offset-4 hover:underline"
                      >
                        {child.name}
                      </Link>
                    </td>
                    <td className="py-2 pr-4">
                      <span className="capitalize">{child.status}</span>
                    </td>
                    <td className="py-2 pr-4">
                      {child.best_metric !== null && child.best_metric !== undefined
                        ? child.best_metric.toFixed(4)
                        : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {showSummary && chain && (
          <div data-testid="chain-summary" className="space-y-2 border-t pt-3">
            <h3 className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
              Overnight chain — {chain.links.length}{' '}
              {chain.links.length === 1 ? 'study' : 'studies'}
              <InfoTooltip glossaryKey="auto_followup_chain" />
            </h3>
            <ol className="space-y-1" data-testid="chain-summary-links">
              {chain.links.map((link) => {
                const delta = formatDelta(link.delta_from_prev);
                return (
                  <li key={link.id} data-testid="chain-summary-link">
                    <Link
                      href={`/studies/${link.id}`}
                      className="text-blue-600 underline-offset-4 hover:underline"
                    >
                      {link.name}
                    </Link>{' '}
                    — <span className="capitalize">{link.status}</span> — best:{' '}
                    {link.best_metric !== null && link.best_metric !== undefined
                      ? link.best_metric.toFixed(4)
                      : '—'}
                    {delta && <span className="ml-1 text-muted-foreground">({delta})</span>}
                  </li>
                );
              })}
            </ol>
            <p data-testid="chain-summary-cumulative-lift">
              Cumulative lift:{' '}
              <span className="font-medium">{formatSignedLift(chain.cumulative_lift)}</span>
              <span className="ml-2 inline-flex">
                <InfoTooltip glossaryKey="lift_gate" />
              </span>
            </p>
            <p data-testid="chain-summary-best-config">
              {chain.proposal_id_for_best_link !== null && bestLink ? (
                <>
                  Best config:{' '}
                  <Link
                    href={`/proposals/${chain.proposal_id_for_best_link}`}
                    className="text-blue-600 underline-offset-4 hover:underline"
                  >
                    {bestLink.name}
                  </Link>
                </>
              ) : chain.best_link_id !== null && bestLink ? (
                <>Best config: {bestLink.name} (Awaiting proposal)</>
              ) : (
                <>Best config: —</>
              )}
            </p>
            <p data-testid="chain-summary-stop-reason">
              Stop reason: {CHAIN_STOP_REASON_PHRASE[chain.stop_reason]}
              {chain.stop_reason === 'depth_exhausted' && (
                <span className="ml-2 inline-flex">
                  <InfoTooltip glossaryKey="auto_followup_depth" />
                </span>
              )}
              {chain.stop_reason === 'budget' && (
                <span className="ml-2 inline-flex">
                  <InfoTooltip glossaryKey="auto_followup_budget_skip" />
                </span>
              )}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
