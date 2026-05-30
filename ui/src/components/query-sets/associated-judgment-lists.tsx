// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';
import Link from 'next/link';

import { StatusBadge } from '@/components/common/status-badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { useJudgmentLists } from '@/lib/api/judgments';

export interface AssociatedJudgmentListsProps {
  querySetId: string;
  onGenerateClick: () => void;
}

export function AssociatedJudgmentLists({
  querySetId,
  onGenerateClick,
}: AssociatedJudgmentListsProps) {
  const query = useJudgmentLists({ query_set_id: querySetId, limit: 50 });
  const rows = query.data?.data ?? [];

  return (
    <div className="space-y-3" data-testid="associated-judgment-lists">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Judgment lists scoped to this query set ({rows.length})
        </p>
        <Button size="sm" onClick={onGenerateClick} data-testid="open-generate-judgments">
          Generate new judgment list
        </Button>
      </div>
      {query.isPending ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-muted-foreground" data-testid="associated-judgment-lists-empty">
          No judgment lists yet for this query set.
        </p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {rows.map((j) => (
            <Card key={j.id} data-testid={`judgment-list-card-${j.id}`}>
              <CardContent className="space-y-2 pt-6">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <Link
                      href={`/judgments/${j.id}`}
                      className="font-medium text-blue-600 underline-offset-4 hover:underline"
                    >
                      {j.name}
                    </Link>
                    <p className="text-xs text-muted-foreground">
                      {new Date(j.created_at).toLocaleString()}
                    </p>
                  </div>
                  <StatusBadge kind="judgment_list" value={j.status} />
                </div>
                {j.description && <p className="text-xs text-muted-foreground">{j.description}</p>}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
