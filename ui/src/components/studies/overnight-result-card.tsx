// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

import Link from 'next/link';
import type React from 'react';

import { InfoTooltip } from '@/components/common/info-tooltip';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useStudyDigest } from '@/lib/api/digests';
import { useTemplate } from '@/lib/api/query-templates';
import {
  useStudy,
  useStudyChain,
  type StudyChainResponse,
  type StudyDetail,
} from '@/lib/api/studies';
import { CHAIN_STOP_REASON_PHRASE } from '@/lib/chain-stop-reason';
import { pathTokenForLink } from '@/lib/chain-path-tokens';
import { formatSignedLift } from '@/lib/format-lift';

/**
 * Morning summary card for the overnight autopilot. Renders above
 * `<LinkedEntitiesRow>` on `/studies/{id}` when the auto-followup chain has
 * terminated and has at least 2 links. Compresses the rolled-up answer —
 * headline lift, explored path tokens, winning config link, stop reason,
 * and a short excerpt from the winning link's digest narrative — into one
 * glance.
 *
 * `feat_overnight_final_solution_phase2` Story 3 ships the card shell +
 * everything except the convergence chip. Story 4 mounts the chip inside
 * `<CardTitle>` (the only commented placeholder below).
 *
 * Hook order is INVARIANT across every render per spec D-19:
 *   1. useStudyChain (always — drives the predicate)
 *   2. useStudyDigest (always — `enabled` gates the network call)
 *   3. derive predicate
 *   4. early return AFTER both hooks have been called.
 *
 * Spec D-11/D-18 require per-link hook calls to live inside CHILD
 * components rather than in `.map(...)` loops in the parent; both
 * `<PathTokenChip>` (here) and `<WinningLinkConvergenceChip>` (Story 4)
 * follow that pattern.
 */

export interface OvernightResultCardProps {
  study: StudyDetail;
}

/**
 * FR-7 — pure predicate, exported for direct unit testing.
 *
 * Returns `true` iff the chain is loaded, NOT in-flight, AND has at least
 * 2 links. The card returns `null` for every other case (single-link
 * chains, in-flight chains, and chains the operator never opted into).
 */
export function shouldShowOvernightResultCard(chain: StudyChainResponse | undefined): boolean {
  if (!chain) return false;
  if (chain.stop_reason === 'in_flight') return false;
  return chain.links.length >= 2;
}

/**
 * FR-5 / D-15 — pure helper, exported for direct unit testing.
 *
 * Truncate the digest narrative to ~`maxChars` chars without cutting
 * mid-word. The cascade:
 *   1. text ≤ maxChars → return unchanged.
 *   2. Otherwise prefer the last sentence terminator (`.`, `!`, `?`) at
 *      or before `maxChars`. If found, return through that terminator.
 *   3. Otherwise fall back to the last whitespace at or before `maxChars`
 *      and append "…".
 *   4. Pathological no-whitespace single-token fallback: hard cut at
 *      `maxChars` + "…".
 *
 * The cycle-1 anti-pattern *"Do not truncate the narrative excerpt
 * mid-word"* is satisfied by step 3; step 4 is the strictly-pathological
 * escape hatch.
 */
export function truncateNarrative(text: string, maxChars: number = 240): string {
  if (text.length <= maxChars) return text;
  const slice = text.slice(0, maxChars + 1);
  const lastTerminator = Math.max(
    slice.lastIndexOf('.'),
    slice.lastIndexOf('!'),
    slice.lastIndexOf('?'),
  );
  if (lastTerminator > 0 && lastTerminator <= maxChars) {
    return text.slice(0, lastTerminator + 1);
  }
  const lastSpace = text.lastIndexOf(' ', maxChars);
  if (lastSpace > 0) {
    return `${text.slice(0, lastSpace)}…`;
  }
  return `${text.slice(0, maxChars)}…`;
}

/**
 * FR-4 — winning-link convergence verdict chip.
 *
 * Parent-gates-mount pattern per spec D-18: the parent renders this child
 * ONLY when `chain.best_link_id !== null`, so `linkId` is type-narrowed to
 * `string` here. The hook fires unconditionally at the top of the child;
 * the `enabled` gate skips the cross-study fetch when the operator is
 * already on the winner's own page (then the verdict reads from
 * `viewedStudy.convergence?.verdict` directly via the page-level
 * `useStudy(studyId)` already loaded at `page.tsx:60`).
 *
 * Display mapping per spec FR-4. Null verdict → hide chip entirely; the
 * `StudyConvergenceShape | null` graceful-degrade contract from
 * `feat_study_convergence_indicator` FR-3 is honored.
 */
const VERDICT_LABEL: Record<
  NonNullable<NonNullable<StudyDetail['convergence']>['verdict']>,
  string
> = {
  converged: 'Converged',
  still_improving: 'Still improving',
  too_few_trials: 'Too few trials',
};

function WinningLinkConvergenceChip({
  linkId,
  viewedStudy,
}: {
  linkId: string;
  viewedStudy: StudyDetail;
}): React.ReactNode {
  // Hook always runs; `enabled: false` when we're already on the winner.
  const studyQ = useStudy(linkId, { enabled: linkId !== viewedStudy.id });
  const verdict =
    linkId === viewedStudy.id
      ? (viewedStudy.convergence?.verdict ?? null)
      : (studyQ.data?.convergence?.verdict ?? null);
  if (verdict === null) return null;
  return (
    <Badge variant="secondary" data-testid="overnight-result-convergence-chip" className="ml-2">
      {VERDICT_LABEL[verdict]}
    </Badge>
  );
}

/**
 * FR-3 — child component per Rules-of-Hooks discipline (D-11).
 *
 * The hook runs at the TOP of this child unconditionally; the `enabled`
 * gate skips the network call for non-swap links. Parent guarantees the
 * link's `selected_followup_kind` is non-null via `tokenLinks.filter(...)`
 * before mounting, so `token` is non-null here — the defensive `null`
 * return is belt-and-suspenders.
 */
function PathTokenChip({
  link,
  isLast,
}: {
  link: StudyChainResponse['links'][number];
  isLast: boolean;
}): React.ReactNode {
  const templateQ = useTemplate(
    link.selected_followup_kind === 'swap_template' ? link.template_id : null,
  );
  const token = pathTokenForLink(link, templateQ.data?.name ?? null);
  if (token === null) return null;
  return (
    <span data-testid={`overnight-result-path-token-${link.id}`}>
      {token}
      {!isLast ? ' → ' : ''}
    </span>
  );
}

export function OvernightResultCard({ study }: OvernightResultCardProps): React.ReactNode {
  // Hook order is invariant per spec D-19 — both top-level hooks run
  // BEFORE the predicate gate + early return.
  const chainQ = useStudyChain(study.id);
  const chain = chainQ.data;
  // FR-5 / D-22 hook-call shape: passes `undefined` (NOT `null`) when no
  // winner so the typed hook signature accepts the value and the `enabled`
  // gate skips the fetch.
  const digestQ = useStudyDigest(chain?.best_link_id ?? undefined, {
    enabled: chain?.best_link_id !== null && shouldShowOvernightResultCard(chain),
  });
  const show = shouldShowOvernightResultCard(chain);

  if (!show || !chain) return null;

  const bestLink =
    chain.best_link_id !== null
      ? (chain.links.find((l) => l.id === chain.best_link_id) ?? null)
      : null;

  // FR-3: filter out null-token links BEFORE mounting child components
  // per cycle-1 finding C1-3. The filter is purely a function of the
  // link's `selected_followup_kind` (a wire-data field — no hook needed),
  // so it's safe to apply before mounting children. The resulting
  // `tokenLinks` array length determines isLast correctly.
  const tokenLinks = chain.links
    .slice(1) // drop anchor (always null kind per Phase 1 D-12)
    .filter((l) => l.selected_followup_kind !== null);

  return (
    <Card data-testid="overnight-result-card">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          {`Overnight exploration complete — ${chain.links.length} ${chain.links.length === 1 ? 'study' : 'studies'}${
            chain.cumulative_lift !== null
              ? `, ${formatSignedLift(chain.cumulative_lift)} lift`
              : ''
          }`}
          {/* FR-4 — chip mounted only when there's a winner link to inspect. */}
          {chain.best_link_id !== null && (
            <WinningLinkConvergenceChip linkId={chain.best_link_id} viewedStudy={study} />
          )}
          <InfoTooltip glossaryKey="overnight_result" />
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        {tokenLinks.length > 0 && (
          <p data-testid="overnight-result-path">
            Explored:{' '}
            {tokenLinks.map((link, i) => (
              <PathTokenChip key={link.id} link={link} isLast={i === tokenLinks.length - 1} />
            ))}
          </p>
        )}
        <p data-testid="overnight-result-best-config">
          {/* FR-1 three-case render matrix per D-13. */}
          {chain.best_link_id === null || bestLink === null ? (
            <>Best config: —</>
          ) : chain.proposal_id_for_best_link === null ? (
            <>Best config: {bestLink.name} (Awaiting proposal)</>
          ) : (
            <>
              Best config:{' '}
              <Link
                href={`/proposals/${chain.proposal_id_for_best_link}`}
                className="text-blue-600 underline-offset-4 hover:underline"
              >
                {bestLink.name}
              </Link>
            </>
          )}
        </p>
        <p data-testid="overnight-result-stop-reason">
          Stop reason: {CHAIN_STOP_REASON_PHRASE[chain.stop_reason]}
          {/* Reuse chain-panel tooltip pattern per spec §11. */}
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
        {digestQ.data && !digestQ.isError && chain.best_link_id !== null && (
          <div data-testid="overnight-result-narrative" className="border-t pt-2">
            <p className="text-xs font-medium text-muted-foreground">Summary</p>
            <p className="mt-1">{truncateNarrative(digestQ.data.narrative)}</p>
            <p className="mt-1">
              <Link
                href={`/studies/${chain.best_link_id}#digest`}
                className="text-blue-600 underline-offset-4 hover:underline"
              >
                View full digest →
              </Link>
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
