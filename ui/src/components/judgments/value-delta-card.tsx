// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';
import Link from 'next/link';
import * as React from 'react';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

interface PriorListSummary {
  id: string;
  name: string;
  judgment_count: number;
}

interface ValueDeltaCardProps {
  coveragePct: number | null | undefined;
  judgmentCount: number;
  priorList?: PriorListSummary | null;
  /**
   * `/studies/compare?...` link when this UBI list's study has a valid LLM
   * counterpart (feat_ubi_llm_study_comparison FR-9). Rendered only when set.
   */
  compareHref?: string | null;
}

/**
 * `<ValueDeltaCard>` — surfaces on UBI/hybrid judgment-list detail pages
 * (feat_ubi_judgments Story 4.3 / FR-8 Capability D).
 *
 * Two render variants:
 * * **Coverage-only** (no prior LLM list on the same query_set): plain
 *   text stating coverage_pct + judgment_count.
 * * **Delta** (prior LLM list exists): includes a link to the prior list
 *   so the operator can compare ratings side-by-side.
 *
 * The card is rendered conditionally by the detail page based on
 * presence of `calibration.coverage_pct` (UBI-shape calibration) OR
 * `generation_params.generation_kind === 'ubi'`.
 */
export function ValueDeltaCard({
  coveragePct,
  judgmentCount,
  priorList,
  compareHref,
}: ValueDeltaCardProps): React.ReactElement {
  const pctText = typeof coveragePct === 'number' ? `${Math.round(coveragePct * 100)}%` : 'most';
  return (
    <Card
      data-testid="value-delta-card"
      className="border-green-200 bg-green-50/50 dark:border-green-900/40 dark:bg-green-950/20"
    >
      <CardHeader>
        <CardTitle className="text-base">What real signals bought you</CardTitle>
      </CardHeader>
      <CardContent>
        {priorList ? (
          <p className="text-sm">
            This UBI list covered <strong>{pctText}</strong> of recent traffic with{' '}
            <strong>{judgmentCount}</strong> ratings — the previous LLM list (
            <Link
              href={`/judgments/${priorList.id}`}
              className="text-blue-600 underline-offset-4 hover:underline"
              data-testid="value-delta-prior-link"
            >
              {priorList.name}
            </Link>
            ) rated <strong>{priorList.judgment_count}</strong> pairs on a snapshot.
          </p>
        ) : (
          <p className="text-sm">
            This UBI list covered <strong>{pctText}</strong> of recent traffic with{' '}
            <strong>{judgmentCount}</strong> ratings.
          </p>
        )}
        {compareHref && (
          <p className="mt-2 text-sm">
            <Link
              href={compareHref}
              className="text-blue-600 underline-offset-4 hover:underline"
              data-testid="value-delta-compare-link"
            >
              View matched study comparison →
            </Link>
          </p>
        )}
      </CardContent>
    </Card>
  );
}
