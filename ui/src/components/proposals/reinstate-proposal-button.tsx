// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

import { toast } from 'sonner';

import { InfoTooltip } from '@/components/common/info-tooltip';
import { Button } from '@/components/ui/button';
import { type ProposalDetail, useReinstateProposal } from '@/lib/api/proposals';

export interface ReinstateProposalButtonProps {
  proposal: ProposalDetail;
}

/**
 * Phase 3 FR-8: "Reinstate" button on `/proposals/[id]`. Visible only
 * when `proposal.status === 'superseded'`. On click, POSTs to
 * `/api/v1/proposals/{id}/reinstate` and flips the row back to pending.
 *
 * Mirrors the {@link import('./reject-dialog').RejectDialog} placement
 * pattern — sits to the right of the PR panel as a sibling action.
 * Backend reuses the existing `INVALID_STATE_TRANSITION` error code
 * (D-16); the toast text below handles both the stale-cache 409 and
 * the unknown-id 404 paths uniformly.
 */
export function ReinstateProposalButton({ proposal }: ReinstateProposalButtonProps) {
  const reinstate = useReinstateProposal();
  const handleClick = () => {
    reinstate.mutate(proposal.id, {
      onSuccess: () => {
        toast.success('Proposal reinstated.');
      },
      onError: (err) => {
        if (err.errorCode === 'INVALID_STATE_TRANSITION') {
          toast.error('This proposal is no longer superseded — refreshing.');
        } else if (err.errorCode === 'PROPOSAL_NOT_FOUND') {
          toast.error('Proposal no longer exists.');
        } else {
          toast.error(`Reinstate failed: ${err.message}`);
        }
      },
    });
  };
  return (
    <span className="inline-flex items-center gap-1">
      <Button
        variant="default"
        size="sm"
        onClick={handleClick}
        disabled={reinstate.isPending}
        aria-label="Reinstate proposal"
        data-testid="proposal-reinstate-button"
      >
        {reinstate.isPending ? 'Reinstating…' : 'Reinstate'}
      </Button>
      <InfoTooltip glossaryKey="proposal.reinstate" />
    </span>
  );
}
