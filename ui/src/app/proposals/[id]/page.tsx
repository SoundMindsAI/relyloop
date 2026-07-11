// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, use, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';

import { DetailPageShell } from '@/components/common/detail-page-shell';
import { InfoTooltip } from '@/components/common/info-tooltip';
import { MetricDelta } from '@/components/common/metric-delta';
import { ConfigDiffPanel } from '@/components/proposals/config-diff-panel';
import { CurrentlyLiveBadge } from '@/components/proposals/currently-live-badge';
import { FullParamSpacePanel } from '@/components/proposals/full-param-space-panel';
import { PrPanel } from '@/components/proposals/pr-panel';
import { ProposalHeader } from '@/components/proposals/proposal-header';
import { ReinstateProposalButton } from '@/components/proposals/reinstate-proposal-button';
import { RejectDialog } from '@/components/proposals/reject-dialog';
import { SuggestedFollowupsPanel } from '@/components/proposals/suggested-followups-panel';
import { CreateStudyModal, type PrefillValues } from '@/components/studies/create-study-modal';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useOpenPR, useProposal } from '@/lib/api/proposals';
import { useTemplate } from '@/lib/api/query-templates';
import { useStudy } from '@/lib/api/studies';
import type {
  FollowupKind,
  ObjectiveDirection,
  ObjectiveK,
  ObjectiveMetric,
  PrunerKind,
  SamplerKind,
} from '@/lib/enums';
import type { components } from '@/lib/types';

type FollowupItem = components['schemas']['FollowupItem'];

// Per-kind UI gate: which kinds open the create-study modal on Run click.
// Values must match backend/app/domain/study/followups.py FollowupItem.kind
const ACTIONABLE_FOLLOWUP_KINDS: Record<FollowupKind, boolean> = {
  narrow: true,
  widen: true,
  text: false,
  swap_template: true,
};

// Exhaustive resolver for the prefill template_id. ``swap_template`` items
// carry the swap target's id directly; narrow/widen/text retain the parent
// study's template_id (text is unreachable via the actionable-kind gate
// but defensively returns the parent id).
function resolveTemplateIdForPrefill(f: FollowupItem, parentTemplateId: string): string {
  switch (f.kind) {
    case 'swap_template':
      return f.template_id;
    case 'narrow':
    case 'widen':
    case 'text':
      return parentTemplateId;
    default: {
      // Exhaustiveness sentinel — TypeScript proves this branch is
      // unreachable as long as the FollowupKind union is fully covered above.
      const _exhaustive: never = f;
      void _exhaustive;
      return parentTemplateId;
    }
  }
}

interface RouteProps {
  params: Promise<{ id: string }>;
}

interface MetricDeltaShape {
  primary?: string;
  baseline?: number;
  best?: number;
  delta_pct?: number;
}

function parseMetricDelta(md: Record<string, unknown> | null | undefined): MetricDeltaShape | null {
  if (!md || typeof md !== 'object') return null;
  return md as MetricDeltaShape;
}

export function ProposalDetailView({ proposalId }: { proposalId: string }) {
  // Page-owned mutation lifted from PrPanel per GPT-5.5 cycle-1 A1 so the
  // refetchInterval below (and the ?action=open_pr auto-trigger) can read
  // its state without prop-drilling.
  const openPr = useOpenPR();
  const { mutate: mutateOpenPR, isPending: openPrMutationPending } = openPr;

  // `postOpenPrPolling` flips ON inside fireOpenPR's onSuccess (after the
  // 202 enqueues). It is FORCE-CLEARED only by:
  //   (a) the 60s safety setTimeout, OR
  //   (b) the unmount cleanup.
  // We do NOT setState(false) inside a useEffect that watches `data` —
  // the React 19 react-hooks/set-state-in-effect rule (correctly) flags
  // that as a cascading-render smell. Instead the *effective* polling
  // signal below is DERIVED from the current data on every render — see
  // `effectivePollingFlag`. The wasted-tick window between worker writeback
  // and 60s elapsed is bounded above by one 3s tick (refetchInterval reads
  // the same derived value).
  const [postOpenPrPolling, setPostOpenPrPolling] = useState(false);
  const safetyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // refetchInterval reads the latest query data on each tick — flip-off
  // is therefore expressible inline without state mutation.
  const proposalQ = useProposal(proposalId, {
    refetchInterval: (q) => {
      const p = q.state.data;
      if (!p) return false;
      if (postOpenPrPolling && p.status === 'pending' && !p.pr_open_error) return 3_000;
      if (p.status === 'pr_opened' && p.pr_state === 'open') return 30_000;
      return false;
    },
  });

  // Destructured primitives — used by the auto-trigger effect below and
  // by the derived `effectivePollingFlag` for the PrPanel pending prop.
  const proposalStatus = proposalQ.data?.status;
  const proposalPrOpenError = proposalQ.data?.pr_open_error ?? null;

  // The button-disabling signal passed to PrPanel. Derived (NOT a piece of
  // state synchronized via useEffect) so the React 19 hooks rule stays
  // happy. The underlying `postOpenPrPolling` may linger true between the
  // worker writeback and the 60s timer firing; this derived value masks it
  // so the operator can re-click once the error/status flip is observable.
  const effectivePollingFlag =
    postOpenPrPolling && proposalStatus === 'pending' && !proposalPrOpenError;

  // Single helper used by BOTH manual click and ?action=open_pr auto-trigger.
  // Wraps openPr.mutate with the onSuccess that flips postOpenPrPolling on
  // and installs the 60s safety cap. Clears any existing safety timer first
  // so a rapid re-click doesn't leak a stale timeout.
  const fireOpenPR = useCallback(() => {
    if (safetyTimerRef.current) {
      clearTimeout(safetyTimerRef.current);
      safetyTimerRef.current = null;
    }
    mutateOpenPR(proposalId, {
      onSuccess: () => {
        setPostOpenPrPolling(true);
        safetyTimerRef.current = setTimeout(() => {
          setPostOpenPrPolling(false);
          safetyTimerRef.current = null;
        }, 60_000);
      },
    });
  }, [mutateOpenPR, proposalId]);

  // Success feedback for the money path: the POST only enqueues (202), so the
  // real "PR opened" event is the polled status flip to `pr_opened`. Fire a
  // success toast exactly once on that transition (not on initial mount of an
  // already-opened proposal — prev is undefined then).
  const prevStatusRef = useRef<string | undefined>(undefined);
  useEffect(() => {
    const prev = prevStatusRef.current;
    if (prev && prev !== 'pr_opened' && proposalStatus === 'pr_opened') {
      toast.success('Pull request opened');
    }
    // Only remember DEFINED statuses so a transient undefined (hard reload /
    // brief network error) doesn't erase the prior status and swallow the
    // toast when it recovers straight to pr_opened (Gemini review).
    if (proposalStatus !== undefined) {
      prevStatusRef.current = proposalStatus;
    }
  }, [proposalStatus]);

  // Unmount cleanup — prevents "state update after unmount" warnings in
  // tests and dev navigation (GPT-5.5 cycle-2 B2).
  useEffect(() => {
    return () => {
      if (safetyTimerRef.current) {
        clearTimeout(safetyTimerRef.current);
        safetyTimerRef.current = null;
      }
    };
  }, []);

  // feat_digest_executable_followups Story 5.2 — "Run this followup" orchestration.
  // The panel reports the clicked index via `onRun`; the page lazily fetches
  // the parent study (gated on actionable followups + Run click) and assembles
  // the PrefillValues that open the CreateStudyModal.
  const [runFollowupIndex, setRunFollowupIndex] = useState<number | null>(null);
  const proposal = proposalQ.data ?? null;
  const followups = proposal?.digest?.suggested_followups ?? [];
  const parentStudyId = proposal?.study_id ?? null;
  // feat_proposal_full_param_space_view FR-3 (D-13): the source study is
  // fetched for EVERY study-backed proposal (the old `&& hasActionableFollowup`
  // gate was dropped). The new <FullParamSpacePanel> needs search_space.params
  // to classify the tunedUnchanged group even when the digest has no actionable
  // followups — without this lift, study proposals with text-only/empty digests
  // would mis-classify search-space params as "untuned". <SuggestedFollowupsPanel>
  // continues to consume parentStudy.data?.search_space (it branches defensively
  // when the parent isn't an actionable-followup case), so this is strictly more
  // information for it.
  const parentStudy = useStudy(parentStudyId ?? '', {
    enabled: parentStudyId !== null,
  });
  // feat_proposal_full_param_space_view FR-3 (D-1): source declared_params
  // from the proposal's OWN template_id (null-safe via ?. — `proposal` is
  // null during the initial loading render; the hook's `enabled: Boolean(id)`
  // short-circuits when the optional chain yields undefined). For study-backed
  // proposals this equals parentStudy.data?.template_id by construction
  // (backend/workers/digest.py:488-494), so <SuggestedFollowupsPanel> receives
  // the same value; for manual proposals it fires where the old gating did not.
  const parentTemplateQuery = useTemplate(proposal?.template.id);

  const prefillValues: PrefillValues | undefined = useMemo(() => {
    if (runFollowupIndex === null) return undefined;
    if (!proposal || !parentStudy.data || followups.length === 0) return undefined;
    const f = followups[runFollowupIndex];
    // feat_digest_executable_followups_swap_template Story 3.3 (F4 fix):
    // exhaustive actionable-kind gate.
    if (!f || !ACTIONABLE_FOLLOWUP_KINDS[f.kind]) return undefined;
    const s = parentStudy.data;
    const objective = s.objective as {
      metric: ObjectiveMetric;
      k?: ObjectiveK;
      direction: ObjectiveDirection;
    };
    const config = s.config as {
      max_trials?: number;
      time_budget_min?: number;
      parallelism?: number;
      trial_timeout_s?: number;
      sampler?: SamplerKind;
      pruner?: PrunerKind;
      seed?: number;
    };
    // Defensively truncate the parent study name so the assembled prefill
    // name stays within the backend's 256-char ``CreateStudyRequest.name``
    // bound (per Gemini Code Assist feedback on PR #225). The suffix
    // ``" — followup #NN (widen)"`` is at most ~26 chars, so capping the
    // parent name at 200 leaves comfortable headroom.
    const PARENT_NAME_MAX = 200;
    const truncatedParentName =
      s.name.length > PARENT_NAME_MAX ? s.name.slice(0, PARENT_NAME_MAX) + '...' : s.name;
    // The LLM-generated followup typically narrows/widens ONLY the
    // parameters it considers interesting (often 1-2 of the parent's
    // 3+ declared params). Submitting just those would fail backend
    // validation: `Template '…' declares param 'X' but it is missing
    // from the search space.` Merge the followup's bounds onto the
    // parent study's search_space so any params the LLM didn't mention
    // keep their original bounds. Followup bounds take precedence on
    // overlapping keys. For swap_template this still helps when the
    // target template shares param names with the parent (the common
    // case); the wizard's template-load validator will surface any
    // remaining mismatch via its existing 404-recovery path.
    const parentSearchSpaceParams = (
      s.search_space &&
      typeof s.search_space === 'object' &&
      'params' in (s.search_space as object) &&
      typeof (s.search_space as Record<string, unknown>).params === 'object'
        ? ((s.search_space as Record<string, unknown>).params as Record<string, unknown>)
        : {}
    ) as Record<string, unknown>;
    const followupSearchSpaceParams = (
      f.search_space &&
      typeof f.search_space === 'object' &&
      'params' in (f.search_space as object) &&
      typeof (f.search_space as Record<string, unknown>).params === 'object'
        ? ((f.search_space as Record<string, unknown>).params as Record<string, unknown>)
        : {}
    ) as Record<string, unknown>;
    const mergedSearchSpace = {
      params: { ...parentSearchSpaceParams, ...followupSearchSpaceParams },
    };
    return {
      cluster_id: s.cluster_id,
      target: s.target,
      // feat_digest_executable_followups_swap_template Story 3.3 (FR-11 +
      // AC-11/AC-12): swap_template branches seed template_id from the
      // followup itself; narrow/widen/text retain the parent study's id.
      template_id: resolveTemplateIdForPrefill(f, s.template_id),
      query_set_id: s.query_set_id,
      judgment_list_id: s.judgment_list_id,
      name: `${truncatedParentName} — followup #${runFollowupIndex + 1} (${f.kind})`,
      search_space_text: JSON.stringify(mergedSearchSpace, null, 2),
      metric: objective.metric,
      k: objective.k,
      direction: objective.direction,
      max_trials: config.max_trials ?? '',
      time_budget_min: config.time_budget_min ?? '',
      parallelism: config.parallelism ?? '',
      trial_timeout_s: config.trial_timeout_s ?? '',
      sampler: config.sampler,
      pruner: config.pruner,
      seed: config.seed ?? '',
      parent: { proposal_id: proposal.id, followup_index: runFollowupIndex },
    };
  }, [runFollowupIndex, proposal, parentStudy.data, followups]);

  // ?action=open_pr auto-trigger — fires fireOpenPR once per mount when the
  // URL carries the query param + the proposal is pending. Strips the param
  // via router.replace so a remount/back-nav with the same URL does NOT
  // re-fire (GPT-5.5 cycle-1 B2).
  const searchParams = useSearchParams();
  const router = useRouter();
  const action = searchParams.get('action');
  const autoFired = useRef(false);
  useEffect(() => {
    if (autoFired.current) return;
    if (action !== 'open_pr') return;
    if (proposalStatus !== 'pending') return;
    if (openPrMutationPending) return;
    autoFired.current = true;
    fireOpenPR();
    router.replace(`/proposals/${proposalId}`);
  }, [action, proposalStatus, openPrMutationPending, fireOpenPR, proposalId, router]);

  return (
    <main className="mx-auto max-w-7xl space-y-6 p-6">
      <div>
        <Link
          href="/proposals"
          className="text-sm text-blue-600 underline-offset-4 hover:underline"
        >
          ← All proposals
        </Link>
      </div>
      <DetailPageShell
        query={proposalQ}
        entityLabel="proposal"
        notFoundErrorCode="PROPOSAL_NOT_FOUND"
        documentTitle={(p) => `Proposal · ${p.cluster.name}`}
      >
        {(proposal) => (
          <>
            <div className="flex items-center justify-between">
              <h1 className="flex items-center text-2xl font-semibold tracking-tight">
                Proposal detail
                <CurrentlyLiveBadge isCurrentlyLive={proposal.is_currently_live} />
              </h1>
            </div>
            <p className="text-sm text-muted-foreground" data-testid="proposal-page-summary">
              A proposal is a recommended search-config change from an optimization study. Review
              the diff and metric delta below — <strong>Open PR</strong> sends the recommendation to
              your config repo where your existing CI and reviewers decide whether to ship it;{' '}
              <strong>Reject</strong> discards it. Click the floating <em>Guide</em> button
              (bottom-right) for the step-by-step walkthrough.
            </p>
            <ProposalHeader proposal={proposal} />
            <ConfigDiffPanel diff={proposal.config_diff} />
            {/* feat_proposal_full_param_space_view FR-4 — race-aware mount.
                Mount only once the template fetch resolves AND, for
                study-backed proposals, once the study query has settled
                (success OR error) so the tunedUnchanged group never flashes
                through a transient mis-classification. Manual proposals
                (study_id === null) skip the study wait. */}
            {parentTemplateQuery.data && (proposal.study_id === null || !parentStudy.isPending) && (
              <FullParamSpacePanel
                configDiff={proposal.config_diff}
                declaredParams={parentTemplateQuery.data.declared_params}
                searchSpaceParams={
                  (
                    parentStudy.data?.search_space as
                      | { params?: Record<string, unknown> }
                      | undefined
                  )?.params
                }
              />
            )}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-1 text-base">
                  Metric delta
                  <InfoTooltip glossaryKey="proposal.metric_delta" />
                </CardTitle>
              </CardHeader>
              <CardContent>
                {(() => {
                  const md = parseMetricDelta(proposal.metric_delta);
                  if (md && md.primary && md.baseline != null && md.best != null) {
                    return (
                      <div className="space-y-1">
                        <p className="text-xs uppercase text-muted-foreground">{md.primary}</p>
                        <MetricDelta baseline={md.baseline} achieved={md.best} />
                      </div>
                    );
                  }
                  return (
                    <p className="text-sm text-muted-foreground" data-testid="metric-delta-empty">
                      No metric delta recorded.
                    </p>
                  );
                })()}
              </CardContent>
            </Card>
            <div className="flex items-start gap-3">
              <div className="flex-1">
                <PrPanel
                  proposal={proposal}
                  onOpenPR={fireOpenPR}
                  openPrIsPending={openPrMutationPending || effectivePollingFlag}
                />
              </div>
              {proposal.status === 'pending' && (
                <div className="pt-12">
                  <RejectDialog proposal={proposal} />
                </div>
              )}
              {proposal.status === 'superseded' && (
                <div className="pt-12">
                  <ReinstateProposalButton proposal={proposal} />
                </div>
              )}
            </div>
            {proposal.digest?.suggested_followups &&
              proposal.digest.suggested_followups.length > 0 && (
                <SuggestedFollowupsPanel
                  followups={proposal.digest.suggested_followups}
                  onRun={setRunFollowupIndex}
                  parentSearchSpace={
                    (parentStudy.data?.search_space as Record<string, unknown> | undefined) ??
                    undefined
                  }
                  parentStudyLoading={parentStudy.isLoading}
                  parentStudyError={parentStudy.error ?? null}
                  parentTemplate={
                    parentTemplateQuery.data
                      ? { declared_params: parentTemplateQuery.data.declared_params }
                      : undefined
                  }
                  parentTemplateLoading={parentTemplateQuery.isLoading}
                  parentTemplateError={parentTemplateQuery.error ?? null}
                />
              )}
          </>
        )}
      </DetailPageShell>
      <CreateStudyModal
        open={prefillValues !== undefined}
        onOpenChange={(o) => {
          if (!o) setRunFollowupIndex(null);
        }}
        initialValues={prefillValues}
      />
    </main>
  );
}

export default function ProposalDetailPage({ params }: RouteProps) {
  const { id } = use(params);
  return (
    <Suspense fallback={<main className="mx-auto max-w-7xl p-6">Loading…</main>}>
      <ProposalDetailView proposalId={id} />
    </Suspense>
  );
}
