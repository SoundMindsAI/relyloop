// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';
import { InfoTooltip } from '@/components/common/info-tooltip';
import { StatusBadge } from '@/components/common/status-badge';
import { ProposalErrorAlert } from '@/components/proposals/proposal-error-alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { ProposalDetail } from '@/lib/api/proposals';
import type { ProposalPrState } from '@/lib/enums';
import type { ShortGlossaryKey } from '@/lib/glossary';

const PR_STATE_TO_GLOSSARY_KEY = {
  open: 'proposal.pr_state.open',
  closed: 'proposal.pr_state.closed',
  merged: 'proposal.pr_state.merged',
} as const satisfies Record<ProposalPrState, ShortGlossaryKey>;

export interface PrPanelProps {
  proposal: ProposalDetail;
  /** Page-owned mutation trigger; the page lifts useOpenPR so its
   *  refetchInterval can read mutation + postOpenPrPolling state directly. */
  onOpenPR: () => void;
  /** True while the click-driven 3s polling cadence is active (covers
   *  mutation flight AND post-202 worker-wait). */
  openPrIsPending: boolean;
}

export function PrPanel({ proposal, onOpenPR, openPrIsPending }: PrPanelProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Pull request</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3" data-testid="pr-panel">
        {proposal.status === 'pending' && (
          <>
            {proposal.pr_open_error && <ProposalErrorAlert error={proposal.pr_open_error} />}
            <div className="flex items-center gap-3">
              <InfoTooltip asChild glossaryKey="proposal.open_pr_button">
                <Button
                  type="button"
                  disabled={openPrIsPending}
                  onClick={onOpenPR}
                  data-testid="open-pr-button"
                >
                  {openPrIsPending ? 'Opening PR…' : 'Open PR'}
                </Button>
              </InfoTooltip>
              {openPrIsPending && (
                <p className="text-xs text-muted-foreground" data-testid="open-pr-spinner-row">
                  Working on it…
                </p>
              )}
            </div>
          </>
        )}
        {proposal.status === 'pr_opened' && proposal.pr_url && (
          <div className="flex items-center gap-3">
            <a
              href={proposal.pr_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-600 underline-offset-4 hover:underline"
              data-testid="pr-link"
            >
              {proposal.pr_url}
            </a>
            {proposal.pr_state && (
              <div className="flex items-center gap-1">
                <StatusBadge kind="proposal_pr" value={proposal.pr_state} />
                <InfoTooltip glossaryKey={PR_STATE_TO_GLOSSARY_KEY[proposal.pr_state]} />
              </div>
            )}
          </div>
        )}
        {proposal.status === 'pr_merged' && (
          <div className="space-y-1">
            {proposal.pr_url && (
              <a
                href={proposal.pr_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-blue-600 underline-offset-4 hover:underline"
                data-testid="pr-link"
              >
                {proposal.pr_url}
              </a>
            )}
            <p className="text-xs text-muted-foreground">
              {proposal.pr_merged_at
                ? `Merged on ${new Date(proposal.pr_merged_at).toLocaleString()}`
                : 'Merged'}
            </p>
          </div>
        )}
        {proposal.status === 'rejected' && (
          <p className="text-sm" data-testid="rejected-reason">
            <span className="text-muted-foreground">Rejected reason:</span>{' '}
            {proposal.rejected_reason ?? 'No reason provided'}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
