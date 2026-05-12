'use client';
import Link from 'next/link';

import { StatusBadge } from '@/components/common/status-badge';
import { Card, CardContent } from '@/components/ui/card';
import type { ProposalDetail } from '@/lib/api/proposals';

export interface ProposalHeaderProps {
  proposal: ProposalDetail;
}

export function ProposalHeader({ proposal }: ProposalHeaderProps) {
  return (
    <Card>
      <CardContent className="space-y-2 pt-6">
        <div className="flex flex-wrap items-center gap-3">
          <StatusBadge kind="proposal" value={proposal.status} />
          {proposal.pr_state && <StatusBadge kind="proposal_pr" value={proposal.pr_state} />}
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
