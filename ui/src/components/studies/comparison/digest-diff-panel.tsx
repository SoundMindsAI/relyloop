// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { diffNarratives } from '@/lib/diff/narrative-diff';

export interface DigestDiffPanelProps {
  /** LLM-side narrative; null when that digest is 404 / not ready. */
  llmNarrative: string | null;
  /** UBI-side narrative; null when that digest is 404 / not ready. */
  ubiNarrative: string | null;
}

const MISSING = 'digest not available for this study';

/**
 * Sentence-level digest-narrative diff (FR-4). Per-side placeholder when a
 * digest is missing; `+`/`−` text markers (not color-only) for accessibility.
 */
export function DigestDiffPanel({ llmNarrative, ubiNarrative }: DigestDiffPanelProps) {
  const bothPresent = llmNarrative != null && ubiNarrative != null;
  const diff = bothPresent ? diffNarratives(llmNarrative, ubiNarrative) : null;

  return (
    <Card data-testid="compare-digest-diff-panel">
      <CardHeader>
        <CardTitle className="text-base">Digest narrative</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {diff && (
          <p className="text-xs text-muted-foreground" data-testid="compare-digest-change-counts">
            {diff.addedCount} added in UBI · {diff.removedCount} removed from LLM
          </p>
        )}
        <div className="grid gap-4 md:grid-cols-2">
          <div data-testid="compare-digest-llm">
            <p className="text-xs uppercase text-muted-foreground">LLM</p>
            {llmNarrative == null ? (
              <p className="mt-1 text-sm italic text-muted-foreground">{MISSING}</p>
            ) : (
              <p className="mt-1 whitespace-pre-wrap text-sm">{llmNarrative}</p>
            )}
          </div>
          <div data-testid="compare-digest-ubi">
            <p className="text-xs uppercase text-muted-foreground">UBI</p>
            {ubiNarrative == null ? (
              <p className="mt-1 text-sm italic text-muted-foreground">{MISSING}</p>
            ) : (
              <p className="mt-1 whitespace-pre-wrap text-sm">{ubiNarrative}</p>
            )}
          </div>
        </div>
        {diff && (
          <div
            className="rounded-md border bg-muted/30 p-2 text-sm"
            data-testid="compare-digest-diff"
          >
            {diff.segments.map((seg, i) => (
              <span
                key={i}
                className={
                  seg.added
                    ? 'bg-emerald-100 dark:bg-emerald-950'
                    : seg.removed
                      ? 'bg-red-100 line-through dark:bg-red-950'
                      : ''
                }
              >
                {seg.added ? '+ ' : seg.removed ? '− ' : ''}
                {seg.value}
              </span>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
