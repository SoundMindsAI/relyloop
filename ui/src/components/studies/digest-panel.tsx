'use client';
import Link from 'next/link';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { InfoTooltip } from '@/components/common/info-tooltip';
import { ParameterImportanceChart } from '@/components/common/parameter-importance-chart';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { DigestResponse } from '@/lib/api/digests';
import type { ProposalSummary } from '@/lib/api/proposals';

export interface DigestPanelProps {
  digest: DigestResponse;
  baselineMetric: number | null;
  bestMetric: number | null;
  pendingProposal: ProposalSummary | null;
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
}: DigestPanelProps) {
  const followups = digest.suggested_followups ?? [];
  return (
    <Card>
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
                <li key={`followup-${i}`}>{f}</li>
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
