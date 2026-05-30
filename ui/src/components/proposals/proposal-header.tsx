// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';
import Link from 'next/link';

import { InfoTooltip } from '@/components/common/info-tooltip';
import { StatusBadge } from '@/components/common/status-badge';
import { Card, CardContent } from '@/components/ui/card';
import type { ProposalDetail } from '@/lib/api/proposals';
import type { ProposalPrState, ProposalStatus } from '@/lib/enums';
import type { ShortGlossaryKey } from '@/lib/glossary';

const STATUS_TO_GLOSSARY_KEY = {
  pending: 'proposal.status.pending',
  pr_opened: 'proposal.status.pr_opened',
  pr_merged: 'proposal.status.pr_merged',
  rejected: 'proposal.status.rejected',
} as const satisfies Record<ProposalStatus, ShortGlossaryKey>;

const PR_STATE_TO_GLOSSARY_KEY = {
  open: 'proposal.pr_state.open',
  closed: 'proposal.pr_state.closed',
  merged: 'proposal.pr_state.merged',
} as const satisfies Record<ProposalPrState, ShortGlossaryKey>;

export interface ProposalHeaderProps {
  proposal: ProposalDetail;
}

export function ProposalHeader({ proposal }: ProposalHeaderProps) {
  return (
    <Card>
      <CardContent className="space-y-2 pt-6">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-1">
            <StatusBadge kind="proposal" value={proposal.status} />
            <InfoTooltip glossaryKey={STATUS_TO_GLOSSARY_KEY[proposal.status]} />
          </div>
          {proposal.pr_state && (
            <div className="flex items-center gap-1">
              <StatusBadge kind="proposal_pr" value={proposal.pr_state} />
              <InfoTooltip glossaryKey={PR_STATE_TO_GLOSSARY_KEY[proposal.pr_state]} />
            </div>
          )}
          <span className="text-xs text-muted-foreground">
            created {new Date(proposal.created_at).toLocaleString()}
          </span>
        </div>
        <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
          <span>
            <span className="text-muted-foreground">Cluster:</span> {proposal.cluster.name}
            <span className="ml-1 text-xs text-muted-foreground">
              ({proposal.cluster.engine_type})
            </span>
          </span>
          <span>
            <span className="text-muted-foreground">Template:</span> {proposal.template.name}{' '}
            <span className="text-xs text-muted-foreground">v{proposal.template.version}</span>
          </span>
          {proposal.study_id && (
            <span>
              <span className="text-muted-foreground">Study:</span>{' '}
              <Link
                href={`/studies/${proposal.study_id}`}
                className="text-blue-600 underline-offset-4 hover:underline"
                data-testid="proposal-header-study-link"
              >
                {proposal.study_summary?.name ?? proposal.study_id}
              </Link>
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
