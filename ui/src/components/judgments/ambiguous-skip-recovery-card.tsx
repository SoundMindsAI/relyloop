// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';
import * as React from 'react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

interface AmbiguousSkipRecoveryCardProps {
  skipCount: number;
  onRerunWithMostRecent: () => void;
  pending?: boolean;
}

/**
 * `<AmbiguousSkipRecoveryCard>` — surfaces when a UBI judgment list's
 * calibration reports `ambiguous_query_skip_count > 0`
 * (feat_ubi_judgments Story 4.3 / FR-8 Capability D).
 *
 * One affordance: "Re-run with `most_recent` tiebreaker" — re-POSTs the
 * original generate-from-ubi request with `mapping_strategy='most_recent'`
 * and a derived name. The parent component owns the mutation + name
 * derivation; this card just exposes the button.
 */
export function AmbiguousSkipRecoveryCard({
  skipCount,
  onRerunWithMostRecent,
  pending,
}: AmbiguousSkipRecoveryCardProps): React.ReactElement {
  return (
    <Card
      role="region"
      data-testid="ambiguous-skip-recovery-card"
      className="border-amber-200 bg-amber-50/50 dark:border-amber-900/40 dark:bg-amber-950/20"
    >
      <CardHeader>
        <CardTitle className="text-base">Skipped {skipCount} queries</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-sm">
          {skipCount} {skipCount === 1 ? 'query was' : 'queries were'} skipped because the same UBI{' '}
          <code>user_query</code> matched more than one entry in your query set, and your{' '}
          <code>mapping_strategy</code> is <code>reject</code>.
        </p>
        <Button
          type="button"
          onClick={onRerunWithMostRecent}
          disabled={pending}
          data-testid="ambiguous-skip-rerun-most-recent"
          className="mt-2"
        >
          {pending ? 'Starting…' : 'Re-run with most_recent tiebreaker'}
        </Button>
      </CardContent>
    </Card>
  );
}
