// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';
import Link from 'next/link';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { InfoTooltip } from '@/components/common/info-tooltip';
import { ParameterImportanceChart } from '@/components/common/parameter-importance-chart';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { DigestResponse } from '@/lib/api/digests';
import type { Schema } from '@/lib/api/clusters';
import type { ProposalSummary } from '@/lib/api/proposals';
import type { EngineType } from '@/lib/enums';
import { glossary } from '@/lib/glossary';

export interface DigestPanelProps {
  digest: DigestResponse;
  baselineMetric: number | null;
  bestMetric: number | null;
  pendingProposal: ProposalSummary | null;
  /** Engine of the study's cluster (FR-6). Undefined while the cluster query
   * is loading/errored — the advisory predicate then evaluates false. */
  engineType?: EngineType | undefined;
  /** Target-field schema for the study (FR-6). Undefined while the schema
   * query is loading/errored/404 — advisory hidden, panel otherwise intact. */
  schema?: Schema | undefined;
}

// ES/OpenSearch analyzers that apply a lowercase token filter. The
// `whitespace` analyzer is intentionally EXCLUDED — it tokenizes on
// whitespace but does NOT lowercase, so including it would produce
// false-positive advisories (spec FR-6).
const LOWERCASE_APPLYING_ANALYZERS = new Set(['standard', 'english', 'simple']);

/**
 * FR-6 predicate: render the analyzer-redundancy advisory only when ALL of:
 *  1. engine is elasticsearch / opensearch (Solr has no per-field analyzer);
 *  2. `recommended_config.query_normalizer` is a lowercasing choice (not none);
 *  3. the schema has ≥1 `text` field whose analyzer overlaps (a known
 *     lowercase-applying analyzer OR a custom name containing "lowercase").
 * Returns false when engineType or schema is undefined (loading / error).
 */
export function shouldShowNormalizerAdvisory(
  recommendedConfig: Record<string, unknown> | null | undefined,
  engineType: EngineType | undefined,
  schema: Schema | undefined,
): boolean {
  if (!engineType || !schema) return false;
  if (engineType === 'solr') return false;
  const choice = recommendedConfig?.['query_normalizer'];
  if (typeof choice !== 'string') return false;
  // feat_query_normalizer_typed_pipeline FR-6 / AC-13: broaden from
  // "any non-none bundle" to "the `+`-split label includes the `lowercase`
  // token", so a typed pipeline winning on e.g. "lowercase+strip_punctuation"
  // still triggers the lowercasing-redundancy advisory while one winning on
  // "strip_punctuation" alone (no lowercasing) correctly does not.
  if (choice === 'none' || !choice.split('+').includes('lowercase')) return false;
  return schema.fields.some((f) => {
    if (f.type !== 'text') return false;
    const a = f.analyzer;
    if (!a) return false;
    return LOWERCASE_APPLYING_ANALYZERS.has(a) || a.toLowerCase().includes('lowercase');
  });
}

function deltaPct(baseline: number | null, best: number | null): string {
  if (baseline == null || best == null) return '—';
  if (baseline === 0) return '(new)';
  const pct = ((best - baseline) / Math.abs(baseline)) * 100;
  const sign = pct >= 0 ? '+' : '';
  return `${sign}${pct.toFixed(1)}%`;
}

export function DigestPanel({
  digest,
  baselineMetric,
  bestMetric,
  pendingProposal,
  engineType,
  schema,
}: DigestPanelProps) {
  const followups = digest.suggested_followups ?? [];
  return (
    // `id="digest"` is the in-page anchor target for
    // <OvernightResultCard>'s "View full digest →" link (feat_overnight_final_solution_phase2
    // Story 4 / FR-5 / D-22). The chain panel's anchor wrapper is the
    // only thing changing here; the panel's rendering is otherwise
    // unchanged.
    <Card id="digest">
      <CardHeader>
        <CardTitle className="text-base">Digest</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <section>
          <p className="flex items-center gap-1 text-xs uppercase text-muted-foreground">
            Narrative
            <InfoTooltip glossaryKey="digest.narrative" />
          </p>
          <div className="prose prose-sm mt-1 max-w-none" data-testid="digest-narrative">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              disallowedElements={['script', 'iframe', 'style']}
              unwrapDisallowed
            >
              {digest.narrative}
            </ReactMarkdown>
          </div>
        </section>
        <section className="grid gap-6 md:grid-cols-2">
          <div>
            <p className="flex items-center gap-1 text-xs uppercase text-muted-foreground">
              Parameter importance
              <InfoTooltip glossaryKey="digest.parameter_importance" />
            </p>
            <div className="mt-2">
              <ParameterImportanceChart data={digest.parameter_importance} />
            </div>
          </div>
          <div className="space-y-3">
            <div>
              <p className="flex items-center gap-1 text-xs uppercase text-muted-foreground">
                Metric delta
                <InfoTooltip glossaryKey="digest.metric_delta" />
              </p>
              <p className="mt-1 text-lg" data-testid="digest-metric-delta">
                {baselineMetric != null ? baselineMetric.toFixed(3) : '—'} →{' '}
                {bestMetric != null ? bestMetric.toFixed(3) : '—'} (
                {deltaPct(baselineMetric, bestMetric)})
              </p>
            </div>
            <div>
              <p className="flex items-center gap-1 text-xs uppercase text-muted-foreground">
                Recommended config
                <InfoTooltip glossaryKey="digest.recommended_config" />
              </p>
              {shouldShowNormalizerAdvisory(digest.recommended_config, engineType, schema) && (
                <p
                  className="mt-1 text-sm text-muted-foreground"
                  data-testid="digest-normalizer-advisory"
                >
                  {glossary['digest.normalizer_advisory'].long}
                </p>
              )}
              <pre className="mt-1 max-h-48 overflow-auto rounded-md border bg-muted/40 p-2 text-xs">
                {JSON.stringify(digest.recommended_config, null, 2)}
              </pre>
            </div>
          </div>
        </section>
        {followups.length > 0 && (
          <section>
            <p className="flex items-center gap-1 text-xs uppercase text-muted-foreground">
              Suggested follow-ups
              <InfoTooltip glossaryKey="digest.suggested_followups" />
            </p>
            <ul className="mt-1 list-inside list-disc text-sm">
              {followups.map((f, i) => (
                // feat_digest_executable_followups Story 4.1 — followups
                // are now {kind, rationale, search_space} dicts; the
                // study-page digest panel renders only the rationale as a
                // simple bullet (the rich card UI lives on the proposal-
                // detail page; this study summary is intentionally compact).
                <li key={`followup-${i}`}>{f.rationale}</li>
              ))}
            </ul>
          </section>
        )}
        <section className="flex items-center gap-3">
          {pendingProposal ? (
            <InfoTooltip asChild glossaryKey="digest.open_pr_button">
              <Button asChild data-testid="open-pr-link">
                <Link href={`/proposals/${pendingProposal.id}?action=open_pr`}>Open PR…</Link>
              </Button>
            </InfoTooltip>
          ) : (
            <InfoTooltip asChild glossaryKey="digest.open_pr_disabled">
              {/*
               * aria-disabled pattern (not native `disabled`) so the button
               * stays focusable and the tooltip can reveal on focus for
               * keyboard users (AC-11). Click activation is prevented via
               * onClick. The visual disabled state is preserved via Tailwind
               * utilities since the native attribute is no longer set.
               */}
              <Button
                type="button"
                aria-disabled="true"
                onClick={(e) => e.preventDefault()}
                data-testid="open-pr-disabled"
                className="cursor-not-allowed opacity-50"
              >
                Open PR (no pending proposal)
              </Button>
            </InfoTooltip>
          )}
        </section>
      </CardContent>
    </Card>
  );
}
