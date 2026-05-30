// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';
import * as React from 'react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

interface UbiSparseDataCardProps {
  coveragePct?: number | null;
  onSwitchToHybrid: () => void;
}

/**
 * `<UbiSparseDataCard>` — surfaces when UBI is enabled but sparse
 * (rung_1) AND the operator has picked a pure-UBI converter
 * (feat_ubi_judgments Story 4.2 / FR-8 Capability C).
 *
 * One affordance: "Switch to Hybrid UBI + LLM" — mutates the dialog's
 * method picker to `hybrid_ubi_llm` via the supplied callback. Visible
 * inline below the picker so the operator sees the recommendation at
 * the point of choice.
 */
export function UbiSparseDataCard({
  coveragePct,
  onSwitchToHybrid,
}: UbiSparseDataCardProps): React.ReactElement {
  const pctText =
    typeof coveragePct === 'number'
      ? `Only ~${Math.round(coveragePct * 100)}% of your query set has dense UBI signal.`
      : 'Your UBI signal is sparse for this query set.';
  return (
    <Card
      role="region"
      aria-labelledby="ubi-sparse-card-heading"
      data-testid="ubi-sparse-data-card"
      className="border-amber-200 bg-amber-50/50 dark:border-amber-900/40 dark:bg-amber-950/20"
    >
      <CardHeader>
        <CardTitle id="ubi-sparse-card-heading" className="text-sm">
          Your UBI data is sparse — consider Hybrid mode
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-sm">
          {pctText} Hybrid rates the dense head from UBI and uses the LLM to fill the rest.
        </p>
        <Button
          type="button"
          variant="default"
          size="sm"
          onClick={onSwitchToHybrid}
          data-testid="ubi-sparse-switch-to-hybrid"
          className="mt-2"
        >
          Switch to Hybrid UBI + LLM
        </Button>
      </CardContent>
    </Card>
  );
}
