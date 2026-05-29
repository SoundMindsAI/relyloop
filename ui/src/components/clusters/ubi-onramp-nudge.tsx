'use client';
import * as React from 'react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { EngineType } from '@/lib/enums';

const ENGINE_NUDGE_COPY: Record<EngineType, string> = {
  elasticsearch:
    'Install the o19s ES UBI fork to start capturing click + dwell behavior — RelyLoop reads it as click-derived judgments without needing the LLM.',
  opensearch:
    'Install the OpenSearch UBI plugin to start capturing click + dwell behavior — RelyLoop reads it as click-derived judgments without needing the LLM.',
};

const ENGINE_RUNBOOK_LINKS: Record<EngineType, string> = {
  elasticsearch: '/guide/runbooks/ubi-judgment-generation#elasticsearch',
  opensearch: '/guide/runbooks/ubi-judgment-generation#opensearch',
};

interface UbiOnrampNudgeProps {
  clusterId: string;
  engineType: EngineType;
  onDismiss?: () => void;
}

/**
 * `<UbiOnrampNudge>` — dismissible nudge surfaced when the cluster's UBI
 * readiness is rung_0 (feat_ubi_judgments Story 4.2 / FR-8 Capability A).
 *
 * Renders above the generate-judgments dialog body when the operator hasn't
 * installed the UBI plugin yet. Engine-aware copy (ES → o19s fork; OpenSearch →
 * OpenSearch UBI plugin); Solr arm is dark until `infra_adapter_solr` ships.
 *
 * Per spec D-7 + plan §"Layout and structure": the dismissal key is
 * scoped per cluster (`relyloop.ubi-onramp-nudge.dismissed:{cluster_id}`)
 * so the operator can dismiss on one cluster without hiding it
 * everywhere. SSR-safe via the safeLocalStorageGet/Set helpers shared
 * with `<DemoDataBanner>`.
 *
 * The actual localStorage round-trip happens at the parent
 * (`<GenerateJudgmentsDialog>`) — that lets the dialog suppress the
 * nudge from re-rendering after dismissal within the same dialog open.
 * `onDismiss` is the parent's hook.
 */
export function UbiOnrampNudge({
  clusterId,
  engineType,
  onDismiss,
}: UbiOnrampNudgeProps): React.ReactElement {
  return (
    <Card
      role="region"
      aria-labelledby="ubi-nudge-heading"
      data-testid="ubi-onramp-nudge"
      data-cluster-id={clusterId}
      className="border-blue-200 bg-blue-50/50 dark:border-blue-900/40 dark:bg-blue-950/20"
    >
      <CardHeader>
        <CardTitle id="ubi-nudge-heading" className="text-base">
          Enable real user signals
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm">{ENGINE_NUDGE_COPY[engineType]}</p>
        <div className="flex items-center gap-3">
          <a
            href={ENGINE_RUNBOOK_LINKS[engineType]}
            data-testid="ubi-nudge-runbook-cta"
            className="text-sm font-medium text-blue-600 underline-offset-4 hover:underline"
          >
            Install instructions →
          </a>
          {onDismiss !== undefined && (
            <Button variant="outline" size="sm" onClick={onDismiss} data-testid="ubi-nudge-dismiss">
              Dismiss
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
