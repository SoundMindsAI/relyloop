'use client';
import Link from 'next/link';
import { Suspense, use } from 'react';

import { MetricDelta } from '@/components/common/metric-delta';
import { EmptyState } from '@/components/common/empty-state';
import { ConfigDiffPanel } from '@/components/proposals/config-diff-panel';
import { ProposalErrorAlert } from '@/components/proposals/proposal-error-alert';
import { ProposalHeader } from '@/components/proposals/proposal-header';
import { SuggestedFollowupsPanel } from '@/components/proposals/suggested-followups-panel';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useProposal } from '@/lib/api/proposals';

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
  // Story 3.1 ships the read-only shell; Story 3.2 will wire the
  // refetchInterval polling cadences here.
  const proposalQ = useProposal(proposalId);

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
      {proposalQ.isPending ? (
        <Card>
          <CardContent>
            <p className="py-12 text-center text-sm text-muted-foreground">Loading…</p>
          </CardContent>
        </Card>
      ) : proposalQ.isError ? (
        proposalQ.error?.errorCode === 'PROPOSAL_NOT_FOUND' ? (
          <EmptyState title="Proposal not found" message="The proposal may have been deleted." />
        ) : (
          <EmptyState title="Backend unreachable" message="Refresh after re-launching the API." />
        )
      ) : proposalQ.data ? (
        <>
          <div className="flex items-center justify-between">
            <h1 className="text-2xl font-semibold tracking-tight">Proposal detail</h1>
          </div>
          <ProposalHeader proposal={proposalQ.data} />
          {proposalQ.data.status === 'pending' && proposalQ.data.pr_open_error && (
            <ProposalErrorAlert error={proposalQ.data.pr_open_error} />
          )}
          <ConfigDiffPanel diff={proposalQ.data.config_diff} />
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Metric delta</CardTitle>
            </CardHeader>
            <CardContent>
              {(() => {
                const md = parseMetricDelta(proposalQ.data.metric_delta);
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
          {/* PrPanel + RejectDialog land in Stories 3.2 + 3.3 */}
          {proposalQ.data.digest?.suggested_followups &&
            proposalQ.data.digest.suggested_followups.length > 0 && (
              <SuggestedFollowupsPanel followups={proposalQ.data.digest.suggested_followups} />
            )}
        </>
      ) : null}
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
