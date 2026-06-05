// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

import Link from 'next/link';

import { BestMetricPanel } from '@/components/studies/comparison/best-metric-panel';
import { ConvergenceOverlay } from '@/components/studies/comparison/convergence-overlay';
import { DigestDiffPanel } from '@/components/studies/comparison/digest-diff-panel';
import { ParamDiffPanel } from '@/components/studies/comparison/param-diff-panel';
import { DemoBadge } from '@/components/common/demo-badge';
import { useCluster } from '@/lib/api/clusters';
import { useStudyDigest, type DigestResponse } from '@/lib/api/digests';
import {
  useStudy,
  useStudyComparePairing,
  useStudyTrials,
  type StudyDetail,
} from '@/lib/api/studies';
import { isDemoSyntheticUbiClusterName } from '@/lib/demo-data';
import { deriveBestSoFarCurve, type CurvePoint } from '@/lib/diff/best-so-far-curve';

// Values must match backend CompareWarningCode
const WARNING_LABELS: Record<string, string> = {
  CROSS_CLUSTER: 'These studies ran on different clusters.',
  TARGET_MISMATCH: 'These studies targeted different indices/collections.',
  OBJECTIVE_MISMATCH:
    'These studies optimized different objectives — the metric delta is not directly comparable.',
};

function direction(study: StudyDetail | undefined): 'maximize' | 'minimize' {
  const d = (study?.objective as Record<string, unknown> | undefined)?.['direction'];
  return d === 'minimize' ? 'minimize' : 'maximize';
}

function metricLabel(study: StudyDetail | undefined): string {
  const m = study?.confidence?.headline?.metric;
  return typeof m === 'string' && m ? m : 'primary metric';
}

function resolveCurve(
  study: StudyDetail | undefined,
  trials:
    | {
        optuna_trial_number: number;
        primary_metric: number | null;
        status: 'complete' | 'failed' | 'pruned';
        is_baseline: boolean;
      }[]
    | undefined,
): CurvePoint[] | null {
  const borrowed = study?.convergence?.best_so_far_curve;
  if (borrowed && borrowed.length > 0) return borrowed;
  if (!trials) return null;
  return deriveBestSoFarCurve(trials, direction(study));
}

function recommendedConfig(digest: DigestResponse | undefined): Record<string, unknown> | null {
  return (digest?.recommended_config as Record<string, unknown> | undefined) ?? null;
}

/**
 * `/studies/compare?a=&b=` orchestrator (FR-3). Resolves the LLM↔UBI pairing,
 * normalizes columns to LLM-left / UBI-right regardless of URL order, and
 * composes the four diff panels. Renders a keyed error state on pairing
 * failure and a non-fatal warning banner for cross-cluster / target /
 * objective mismatches.
 */
export function StudyComparisonPage({ a, b }: { a?: string; b?: string }) {
  const pairingQ = useStudyComparePairing(a, b);

  // Raw-side hooks keyed on the URL ids (stable) — column mapping to LLM/UBI
  // happens after pairing resolves.
  const idA = a ?? '';
  const idB = b ?? '';
  const studyAQ = useStudy(idA, { enabled: Boolean(idA) });
  const studyBQ = useStudy(idB, { enabled: Boolean(idB) });
  const digestAQ = useStudyDigest(idA, { enabled: Boolean(idA) });
  const digestBQ = useStudyDigest(idB, { enabled: Boolean(idB) });
  const clusterAQ = useCluster(studyAQ.data?.cluster_id ?? '');
  const clusterBQ = useCluster(studyBQ.data?.cluster_id ?? '');
  // Trials fallback only when the borrowed convergence curve is absent.
  const trialsAQ = useStudyTrials(idA, {
    sort: 'optuna_trial_number_asc',
    limit: 200,
    enabled: Boolean(idA) && studyAQ.data != null && studyAQ.data.convergence == null,
  });
  const trialsBQ = useStudyTrials(idB, {
    sort: 'optuna_trial_number_asc',
    limit: 200,
    enabled: Boolean(idB) && studyBQ.data != null && studyBQ.data.convergence == null,
  });

  if (!a || !b) {
    return <ErrorState message="Provide two study ids to compare (?a=&b=)." />;
  }

  if (pairingQ.isError) {
    const code = pairingQ.error?.errorCode ?? 'COMPARE_ERROR';
    return (
      <ErrorState
        message={pairingQ.error?.message ?? 'These studies cannot be compared.'}
        code={code}
      />
    );
  }

  if (!pairingQ.data) {
    return <p className="p-6 text-sm text-muted-foreground">Loading comparison…</p>;
  }

  // Column normalization: LLM always left, UBI always right (AC-18).
  const aIsLlm = pairingQ.data.a_kind === 'llm';
  const llm = {
    study: aIsLlm ? studyAQ.data : studyBQ.data,
    digest: aIsLlm ? digestAQ.data : digestBQ.data,
    cluster: aIsLlm ? clusterAQ.data : clusterBQ.data,
    trials: aIsLlm ? trialsAQ.data?.data : trialsBQ.data?.data,
  };
  const ubi = {
    study: aIsLlm ? studyBQ.data : studyAQ.data,
    digest: aIsLlm ? digestBQ.data : digestAQ.data,
    cluster: aIsLlm ? clusterBQ.data : clusterAQ.data,
    trials: aIsLlm ? trialsBQ.data?.data : trialsAQ.data?.data,
  };

  const objectiveMismatch = pairingQ.data.warnings.some((w) => w.code === 'OBJECTIVE_MISMATCH');

  return (
    <main className="mx-auto max-w-7xl space-y-6 p-6">
      <div>
        <Link href="/studies" className="text-sm text-blue-600 underline-offset-4 hover:underline">
          ← All studies
        </Link>
      </div>
      <h1 className="text-2xl font-semibold tracking-tight">Study comparison — LLM vs UBI</h1>

      <div className="grid grid-cols-2 gap-4">
        <div className="flex items-center gap-2" data-testid="compare-col-llm-header">
          <span className="text-sm font-medium">LLM judgments</span>
          {llm.cluster && isDemoSyntheticUbiClusterName(llm.cluster.name) && (
            <DemoBadge variant="synthetic-ubi" />
          )}
        </div>
        <div className="flex items-center gap-2" data-testid="compare-col-ubi-header">
          <span className="text-sm font-medium">UBI judgments</span>
          {ubi.cluster && isDemoSyntheticUbiClusterName(ubi.cluster.name) && (
            <DemoBadge variant="synthetic-ubi" />
          )}
        </div>
      </div>

      {pairingQ.data.warnings.length > 0 && (
        <div
          className="space-y-1 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm dark:bg-amber-950"
          data-testid="compare-warning-banner"
        >
          {pairingQ.data.warnings.map((w) => (
            <p key={w.code} data-testid={`compare-warning-${w.code}`}>
              ⚠️ {WARNING_LABELS[w.code] ?? w.message}
            </p>
          ))}
        </div>
      )}

      <div className="space-y-6">
        <BestMetricPanel
          llmMetric={llm.study?.best_metric ?? null}
          ubiMetric={ubi.study?.best_metric ?? null}
          direction={direction(llm.study)}
          metricLabel={metricLabel(llm.study)}
          objectiveMismatch={objectiveMismatch}
        />
        <ParamDiffPanel
          llmConfig={recommendedConfig(llm.digest)}
          ubiConfig={recommendedConfig(ubi.digest)}
        />
        <DigestDiffPanel
          llmNarrative={llm.digest?.narrative ?? null}
          ubiNarrative={ubi.digest?.narrative ?? null}
        />
        <ConvergenceOverlay
          llmCurve={resolveCurve(llm.study, llm.trials)}
          ubiCurve={resolveCurve(ubi.study, ubi.trials)}
        />
      </div>
    </main>
  );
}

function ErrorState({ message, code }: { message: string; code?: string }) {
  return (
    <main className="mx-auto max-w-3xl space-y-4 p-6" data-testid="compare-error-state">
      <h1 className="text-xl font-semibold">Study comparison</h1>
      <div className="rounded-md border border-destructive/40 bg-destructive/5 p-4 text-sm">
        {code && <p className="font-mono text-xs text-muted-foreground">{code}</p>}
        <p className="mt-1">{message}</p>
      </div>
      <Link href="/studies" className="text-sm text-blue-600 underline-offset-4 hover:underline">
        ← Back to studies
      </Link>
    </main>
  );
}
