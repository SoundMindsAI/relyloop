'use client';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, use, useCallback, useEffect, useRef, useState } from 'react';

import { DetailPageShell } from '@/components/common/detail-page-shell';
import { InfoTooltip } from '@/components/common/info-tooltip';
import { MetricDelta } from '@/components/common/metric-delta';
import { ConfigDiffPanel } from '@/components/proposals/config-diff-panel';
import { PrPanel } from '@/components/proposals/pr-panel';
import { ProposalHeader } from '@/components/proposals/proposal-header';
import { RejectDialog } from '@/components/proposals/reject-dialog';
import { SuggestedFollowupsPanel } from '@/components/proposals/suggested-followups-panel';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useOpenPR, useProposal } from '@/lib/api/proposals';

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
      >
        {(proposal) => (
          <>
            <div className="flex items-center justify-between">
              <h1 className="text-2xl font-semibold tracking-tight">Proposal detail</h1>
            </div>
            <ProposalHeader proposal={proposal} />
            <ConfigDiffPanel diff={proposal.config_diff} />
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
            </div>
            {proposal.digest?.suggested_followups &&
              proposal.digest.suggested_followups.length > 0 && (
                <SuggestedFollowupsPanel followups={proposal.digest.suggested_followups} />
              )}
          </>
        )}
      </DetailPageShell>
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
